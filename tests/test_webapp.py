import hashlib
import hmac
import json
import logging

import pytest

BASE = '/prefix-map'


class StubUpdater:
    def __init__(self):
        self.calls = 0

    def webhook_received(self):
        self.calls += 1


@pytest.fixture
def stub_updater(webapp, monkeypatch):
    stub = StubUpdater()
    monkeypatch.setattr(webapp, 'updater_manager', stub)
    monkeypatch.setattr(webapp, 'WEBHOOK_SECRET', '')
    return stub


def prefix_id(dataset, prefix):
    return next(p['id'] for p in dataset['prefixes'] if p['prefix'] == prefix)


def test_index_lists_vrfs(client):
    r = client.get(f'{BASE}/')
    assert r.status_code == 200
    assert b'LAN' in r.data and b'Global' in r.data


def test_vrf_view(client):
    assert client.get(f'{BASE}/map/1').status_code == 200
    assert client.get(f'{BASE}/map/None').status_code == 200


def test_unknown_vrf_is_404(client):
    r = client.get(f'{BASE}/map/999')
    assert r.status_code == 404
    assert b'not found' in r.data


def test_map_page_links_prefix_in_netbox(client, dataset):
    r = client.get(f'{BASE}/map/1/10_20_0_0_17')
    assert r.status_code == 200
    assert f'/ipam/prefixes/{prefix_id(dataset, "10.20.0.0/17")}/'.encode() in r.data
    assert b'/ipam/prefixes//' not in r.data
    assert b'address_map-1-10_20_0_0_17.png' in r.data


def test_map_page_for_large_prefix_shows_layered_map(client):
    r = client.get(f'{BASE}/map/1/10_0_0_0_8')
    assert r.status_code == 200
    assert b'address_map-1-10_0_0_0_8.png' in r.data and b'No map image' not in r.data


def test_missing_map_is_404(client):
    assert client.get(f'{BASE}/map/1/172_16_0_0_24').status_code == 404


def test_image_served(client):
    r = client.get(f'{BASE}/images/address_map-1-10_20_0_0_17.png')
    assert r.status_code == 200
    assert r.mimetype == 'image/png'


@pytest.mark.parametrize('name', ['prefix_tree.json', 'names.json', 'summary.json', 'vrf.json',
                                  'data-1-10_20_0_0_17.json', 'address_map-1-10_20_0_0_17.png.tmp'])
def test_images_route_serves_only_map_images(client, name):
    assert client.get(f'{BASE}/images/{name}').status_code == 404


def test_data_endpoint(client):
    r = client.get(f'{BASE}/data/1/10_20_0_0_17')
    assert r.status_code == 200
    data = r.get_json()
    assert data['prefix'] == '10.20.0.0/17'
    assert data['child_prefixes']


def test_errors_page_shows_recent_warnings(client):
    logging.getLogger().warning("synthetic warning for test")
    r = client.get(f'{BASE}/errors')
    assert r.status_code == 200
    assert b'synthetic warning for test' in r.data


@pytest.mark.parametrize("payload,expected_status,expected_calls", [
    ({"event": "created", "model": "ipaddress"}, "success", 1),
    ({"event": "deleted", "model": "prefix"}, "success", 1),
    ({"event": "updated"}, "success", 1),  # no model: accepted (older payloads)
    ({"event": "updated", "model": "device"}, "ignored", 0),
    ({"event": "job_started", "model": "prefix"}, "ignored", 0),
])
def test_webhook_filtering(client, stub_updater, payload, expected_status, expected_calls):
    r = client.post(f'{BASE}/webhook', json=payload)
    assert r.status_code == 200
    assert r.get_json()['status'] == expected_status
    assert stub_updater.calls == expected_calls


def test_webhook_rejects_non_json(client, stub_updater):
    r = client.post(f'{BASE}/webhook', data='not json', content_type='text/plain')
    assert r.status_code == 400
    assert stub_updater.calls == 0


def test_webhook_signature(client, stub_updater, webapp, monkeypatch):
    monkeypatch.setattr(webapp, 'WEBHOOK_SECRET', 's3cret')
    body = json.dumps({"event": "created", "model": "ipaddress"}).encode()
    headers = {'Content-Type': 'application/json'}

    assert client.post(f'{BASE}/webhook', data=body, headers=headers).status_code == 403
    bad = dict(headers, **{'X-Hook-Signature': 'deadbeef'})
    assert client.post(f'{BASE}/webhook', data=body, headers=bad).status_code == 403
    assert stub_updater.calls == 0

    signature = hmac.new(b's3cret', body, hashlib.sha512).hexdigest()
    good = dict(headers, **{'X-Hook-Signature': signature})
    assert client.post(f'{BASE}/webhook', data=body, headers=good).status_code == 200
    assert stub_updater.calls == 1


def test_healthz(client):
    r = client.get(f'{BASE}/healthz')
    assert r.status_code == 200
    assert r.get_json()['status'] == 'ok'


def test_metrics(client, stub_updater, webapp, monkeypatch):
    class Status:
        def status(self):
            return {'runs': 3, 'failures': 1, 'running': False, 'pending': True, 'last_duration': 1.5,
                    'last_success_at': 1700000000.0}

        def webhook_received(self):
            pass
    monkeypatch.setattr(webapp, 'updater_manager', Status())
    before = client.get(f'{BASE}/metrics').data.decode()
    client.post(f'{BASE}/webhook', json={"event": "created", "model": "ipaddress"})
    client.post(f'{BASE}/webhook', json={"event": "updated", "model": "device"})
    text = client.get(f'{BASE}/metrics').data.decode()
    assert 'prefix_map_updates_total 3' in text
    assert 'prefix_map_update_pending 1' in text
    assert 'prefix_map_last_success_timestamp_seconds 1700000000.0' in text

    def count(t, result):
        return int(next(line for line in t.splitlines()
                        if line.startswith(f'prefix_map_webhooks_total{{result="{result}"}}')).split()[-1])
    assert count(text, 'accepted') == count(before, 'accepted') + 1
    assert count(text, 'ignored') == count(before, 'ignored') + 1


def test_healthcheck_bypasses_proxy(webapp, monkeypatch):
    import socket
    import threading
    from werkzeug.serving import make_server
    from app import healthcheck

    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    server = make_server('127.0.0.1', port, webapp.app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for var in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY'):
            monkeypatch.setenv(var, 'http://127.0.0.1:9')
        monkeypatch.delenv('NO_PROXY', raising=False)
        monkeypatch.delenv('no_proxy', raising=False)
        monkeypatch.setenv('PORT', str(port))
        assert healthcheck.main() == 0
        monkeypatch.setenv('PORT', '9')
        assert healthcheck.main() == 1
    finally:
        server.shutdown()


def test_data_nav_mode_omits_addresses(client):
    full = client.get(f'{BASE}/data/1/10_20_0_0_17').get_json()
    nav = client.get(f'{BASE}/data/1/10_20_0_0_17?nav=1').get_json()
    assert full['ip_addresses'] and full['nested_prefixes']
    assert 'ip_addresses' not in nav and 'nested_prefixes' not in nav
    assert nav['child_prefixes'] == full['child_prefixes']


def test_data_is_gzipped_when_accepted(client):
    import gzip
    r = client.get(f'{BASE}/data/1/10_20_0_0_17', headers={'Accept-Encoding': 'gzip, deflate'})
    assert r.headers['Content-Encoding'] == 'gzip'
    assert json.loads(gzip.decompress(r.data))['prefix'] == '10.20.0.0/17'
    assert 'Content-Encoding' not in client.get(f'{BASE}/data/1/10_20_0_0_17').headers


def test_duplicate_parent_prefixes_listed_once(webapp, monkeypatch):
    tree = {'1': {'prefixes': [
        {'id': 1, 'prefix': '10.0.0.0/8', 'description': 'first'},
        {'id': 2, 'prefix': '10.0.0.0/8', 'description': 'duplicate'},
        {'id': 3, 'prefix': '10.1.0.0/16'},
        {'id': 4, 'prefix': '10.1.2.0/24'},
    ]}}
    monkeypatch.setattr(webapp, 'load_prefix_tree', lambda: tree)
    parents = webapp.find_parents('1', '10.1.2.0/24')
    assert [(p['prefix'], p['id']) for p in parents] == [('10.0.0.0/8', 1), ('10.1.0.0/16', 3)]
    assert parents[0]['sanitized'] == '10_0_0_0_8'


def ipv4_counts(dataset, vrf):
    prefixes = [p for p in dataset['prefixes'] if p['vrf'] == vrf and ':' not in p['prefix']]
    ips = [ip for ip in dataset['ip_addresses'] if ip['vrf'] == vrf and ':' not in ip['address']]
    return len(prefixes), len(ips)


def test_summary_file(output_dir, dataset):
    import json
    import os
    with open(os.path.join(output_dir, 'summary.json')) as f:
        summary = json.load(f)
    for key, vrf in (('1', 1), ('None', None)):
        assert (summary[key]['prefix_count'], summary[key]['ip_count']) == ipv4_counts(dataset, vrf)
    assert [p['prefix'] for p in summary['1']['top_prefixes']] == ['10.0.0.0/8']
    assert [p['prefix'] for p in summary['None']['top_prefixes']] == ['172.31.0.0/16', '192.168.0.0/24']
    top = summary['1']['top_prefixes'][0]
    assert top['size'] == 2 ** 24 and top['has_children'] and top['ip_count'] == summary['1']['ip_count']


def test_index_shows_counts(client, dataset):
    html = client.get(f'{BASE}/').data.decode()
    prefixes, ips = ipv4_counts(dataset, 1)
    row = html[html.index(f'href="{BASE}/map/1"'):]
    row = row[:row.index('</tr>')]
    assert f'>{prefixes:,}<' in row and f'>{ips:,}<' in row
    assert f'href="{BASE}/map/None"' in html


def test_vrf_page_lists_top_level_prefixes_with_usage(client):
    html = client.get(f'{BASE}/map/None').data.decode()
    assert f'href="{BASE}/map/None/172_31_0_0_16"' in html
    assert f'href="{BASE}/map/None/192_168_0_0_24"' in html
    assert '172_31_4_0_24' not in html, "nested prefixes are reached through maps"
    assert 'Management' in html and 'title="7 of 256 addresses with an IP record"' in html


def test_vrf_page_without_summary_file(client, webapp, monkeypatch):
    monkeypatch.setattr(webapp, 'load_summary', lambda: {})
    html = client.get(f'{BASE}/map/1').data.decode()
    assert f'href="{BASE}/map/1/10_0_0_0_8"' in html and '10_20_0_0_16' not in html
    assert 'No usage data' in html
    assert client.get(f'{BASE}/').status_code == 200


def test_top_level_prefixes(webapp):
    entries = [{'prefix': p} for p in ('10.1.0.0/16', '10.0.0.0/8', '10.0.0.0/8', '192.168.0.0/24', '2001:db8::/32')]
    assert [str(n) for n, _ in webapp.top_level_prefixes(entries)] == ['10.0.0.0/8', '192.168.0.0/24']


def search(client, q):
    r = client.get(f'{BASE}/search', query_string={'q': q})
    return r.status_code, r.get_json()


def test_search_address(client, dataset):
    status, body = search(client, '10.20.48.1')
    assert status == 200
    first = body['results'][0]
    assert (first['vrf'], first['vrf_name'], first['prefix'], first['match']) == ('1', 'LAN', '10.20.48.0/24', 'within')
    assert first['url'] == f'{BASE}/map/1/10_20_48_0_24?focus=10.20.48.1'
    assert first['ip']['dns_name'] == 'gw-48.example.test' and first['ip']['role'] == 'anycast'


def test_search_prefix(client):
    _, body = search(client, '10.20.48.0/20')
    assert body['results'][0]['match'] == 'exact'
    assert body['results'][0]['url'] == f'{BASE}/map/1/10_20_48_0_20'
    _, body = search(client, '10.20.48.0/25')
    assert body['results'][0]['prefix'] == '10.20.48.0/24'
    assert body['results'][0]['url'].endswith('?focus=10.20.48.0/25')
    _, body = search(client, '10.20.48.7/24')
    assert body['results'][0]['prefix'] == '10.20.48.0/24' and body['results'][0]['match'] == 'exact'


def test_search_global_and_misses(client):
    _, body = search(client, '192.168.0.5')
    assert [(r['vrf'], r['prefix']) for r in body['results']] == [('None', '192.168.0.0/24')]
    assert search(client, '8.8.8.8') == (200, {'query': '8.8.8.8', 'results': []})
    for bad in ('', 'foo', '300.1.1.1', '10.0.0.0/33', '2001:db8::1', '010.0.0.1'):
        status, body = search(client, bad)
        assert status == 400 and 'error' in body, bad


def test_output_json_cache_follows_file(webapp, output_dir):
    import json
    import os
    path = os.path.join(output_dir, 'cache-test.json')
    with open(path, 'w') as f:
        json.dump({'v': 1}, f)
    assert webapp.load_output_json('cache-test.json', {}) == {'v': 1}
    with open(path, 'w') as f:
        json.dump({'v': 2}, f)
    os.utime(path, ns=(1, 1))
    assert webapp.load_output_json('cache-test.json', {}) == {'v': 2}
    os.remove(path)
    assert webapp.load_output_json('cache-test.json', None) is None


def test_usage_percent_is_capped(webapp):
    from flask import render_template_string
    with webapp.app.test_request_context():
        html = render_template_string(
            "{% from '_usage.html' import percent %}{{ percent(3, 2) }} {{ percent(1, 1000) }} {{ percent(None, 2) }}")
    assert html == '100% &lt;1% —'


def test_search_ip_record_unknown_without_ip_list(client):
    _, body = search(client, '10.40.0.1')
    result = body['results'][0]
    assert result['prefix'] == '10.0.0.0/8' and 'ip' not in result
    _, body = search(client, '10.20.48.1/32')
    assert body['results'][0]['url'].endswith('?focus=10.20.48.1')
    assert body['results'][0]['ip']['dns_name'] == 'gw-48.example.test'


def test_vrf_page_shows_container_usage_as_allocation(client):
    html = client.get(f'{BASE}/map/1').get_data(as_text=True)
    assert 'assigned to prefixes (not containers)' in html and 'assigned</div>' in html
