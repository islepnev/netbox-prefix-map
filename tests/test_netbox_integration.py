import socket
import time

import pytest

from app.netbox_integration import NetboxAddressManager


def test_unresponsive_netbox_times_out(monkeypatch):
    for var in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('NETBOX_TIMEOUT', '1')
    with socket.socket() as server:  # accepts connections, never answers
        server.bind(('127.0.0.1', 0))
        server.listen(5)
        started = time.monotonic()
        with pytest.raises(RuntimeError):
            NetboxAddressManager(f"http://127.0.0.1:{server.getsockname()[1]}", 'token')
        assert time.monotonic() - started < 10


def test_roles_are_optional(monkeypatch):
    calls = []

    def fake_fetch(fetch_method, data_type):
        calls.append(data_type)
        if data_type == "prefix roles":
            raise RuntimeError("403")
        return [{"id": 1, "name": "x"}]

    monkeypatch.setattr(NetboxAddressManager, 'nb_connect', staticmethod(lambda *a: _FakeApi()))
    monkeypatch.setattr(NetboxAddressManager, '_fetch_data', staticmethod(fake_fetch))
    mgr = NetboxAddressManager('http://netbox.invalid', 'token')
    assert mgr.get_roles() == [] and mgr.get_tenants() == [{"id": 1, "name": "x"}]
    assert "prefix roles" in calls


def test_ranges_vlans_and_scopes_are_optional(monkeypatch):
    optional = {"IP ranges", "VLANs", "sites", "locations", "regions", "site groups"}

    def fake_fetch(fetch_method, data_type):
        if data_type in optional:
            raise RuntimeError("403")
        return [{"id": 1, "name": "x"}]

    monkeypatch.setattr(NetboxAddressManager, 'nb_connect', staticmethod(lambda *a: _FakeApi()))
    monkeypatch.setattr(NetboxAddressManager, '_fetch_data', staticmethod(fake_fetch))
    mgr = NetboxAddressManager('http://netbox.invalid', 'token')
    assert mgr.get_ip_ranges() == [] and mgr.get_vlans() == []
    assert all(objects == [] for objects in mgr.get_scope_objects().values())


class _Endpoint:
    all = None


class _App:
    def __getattr__(self, name):
        return _Endpoint()


class _FakeApi:
    ipam = _App()
    tenancy = _App()
    dcim = _App()
