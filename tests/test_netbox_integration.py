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
