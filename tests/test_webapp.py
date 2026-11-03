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
