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


def test_map_page_for_large_prefix_explains_missing_image(client):
    r = client.get(f'{BASE}/map/1/10_0_0_0_8')
    assert r.status_code == 200
    assert b'No map image' in r.data


def test_missing_map_is_404(client):
    assert client.get(f'{BASE}/map/1/172_16_0_0_24').status_code == 404


def test_image_served(client):
    r = client.get(f'{BASE}/images/address_map-1-10_20_0_0_17.png')
    assert r.status_code == 200
    assert r.mimetype == 'image/png'


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
