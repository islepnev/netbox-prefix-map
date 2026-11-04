import logging
import re

import pytest
import requests

from app import auth

BASE = '/prefix-map'
COOKIE = 'nb-session-value-123'


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body

    def json(self):
        if self.body is None:
            raise ValueError('no JSON')
        return self.body


class FakeNetbox:
    """NetBox API answering by session cookie: sessions maps a cookie to (username, may view prefixes)."""

    def __init__(self, sessions=None, error=None, status=None):
        self.sessions = sessions or {}
        self.error = error
        self.status = status
        self.calls = []

    def get(self, url, cookies=None, **kwargs):
        self.calls.append(url)
        if self.error:
            raise self.error
        if self.status:
            return FakeResponse(self.status)
        user = self.sessions.get((cookies or {}).get('sessionid'))
        if url.endswith(auth.PROBE_PATH):
            return FakeResponse(200 if user and user[1] else 403, {'results': []})
        if url.endswith(auth.WHOAMI_PATH):
            return FakeResponse(200, {'username': user[0]}) if user else FakeResponse(403)
        return FakeResponse(404)


def checker(netbox, cache_seconds=300):
    return auth.NetboxSessionAuth('https://netbox.example.test/', cache_seconds=cache_seconds, session=netbox)


def test_user_who_may_view_prefixes_is_allowed_with_one_request():
    netbox = FakeNetbox({COOKIE: ('alice', True)})
    assert checker(netbox).check('sessionid', COOKIE) == auth.ALLOW
    assert netbox.calls == ['https://netbox.example.test' + auth.PROBE_PATH]


def test_user_without_permission_is_denied():
    netbox = FakeNetbox({COOKIE: ('bob', False)})
    assert checker(netbox).check('sessionid', COOKIE) == auth.DENY
    assert len(netbox.calls) == 2


def test_stale_or_missing_session_goes_to_login():
    netbox = FakeNetbox()
    assert checker(netbox).check('sessionid', 'expired') == auth.LOGIN
    assert checker(netbox).check('sessionid', None) == auth.LOGIN
    assert checker(netbox).check('sessionid', '') == auth.LOGIN


@pytest.mark.parametrize('netbox', [FakeNetbox(error=requests.ConnectionError('refused')), FakeNetbox(status=502)])
def test_netbox_failure_is_unavailable_and_not_cached(netbox):
    check = checker(netbox)
    assert check.check('sessionid', COOKIE) == auth.UNAVAILABLE
    assert check.check('sessionid', COOKIE) == auth.UNAVAILABLE
    assert len(netbox.calls) == 2


def test_result_is_cached_per_session():
    netbox = FakeNetbox({COOKIE: ('alice', True), 'other': ('bob', False)})
    check = checker(netbox)
    for _ in range(3):
        assert check.check('sessionid', COOKIE) == auth.ALLOW
    assert len(netbox.calls) == 1
    assert check.check('sessionid', 'other') == auth.DENY
    assert len(netbox.calls) == 3


def test_cache_expires():
    netbox = FakeNetbox({COOKIE: ('alice', True)})
    check = checker(netbox, cache_seconds=0)
    check.check('sessionid', COOKIE)
    check.check('sessionid', COOKIE)
    assert len(netbox.calls) == 2


def test_cookie_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    checker(FakeNetbox({COOKIE: ('bob', False)})).check('sessionid', COOKIE)
    checker(FakeNetbox(error=requests.ConnectionError(f'cookie {COOKIE}'))).check('sessionid', COOKIE)
    checker(FakeNetbox(status=500)).check('sessionid', COOKIE)
    assert caplog.text and COOKIE not in caplog.text
    assert 'bob' in caplog.text


# Web app with NETBOX_SESSION_AUTH=1

@pytest.fixture
def netbox(webapp, monkeypatch):
    fake = FakeNetbox({COOKIE: ('alice', True), 'no-perm': ('bob', False)})
    monkeypatch.setattr(webapp, 'NETBOX_SESSION_AUTH', True)
    monkeypatch.setattr(webapp, 'session_auth', checker(fake))
    return fake


def with_cookie(client, value):
    client.set_cookie('sessionid', value, domain='localhost')
    return client


def sample_url(rule):
    """A URL of a route, its variables filled with sample values."""
    return re.sub(r'<(?:[^:>]+:)?([^>]+)>', lambda m: {'filename': 'address_map-1-10_20_0_0_17.png'}.get(
        m.group(1), {'vrf': '1', 'prefix': '10_20_0_0_17'}.get(m.group(1), 'x')), rule.rule)


def test_every_route_but_the_exempt_ones_needs_a_session(webapp, client, netbox):
    routes = [rule for rule in webapp.app.url_map.iter_rules()]
    exempt = {rule.endpoint for rule in routes} & webapp.AUTH_EXEMPT_ENDPOINTS
    assert exempt == {'static', 'app.healthz', 'app.metrics', 'app.webhook'}
    checked = 0
    for rule in routes:
        if rule.endpoint in webapp.AUTH_EXEMPT_ENDPOINTS:
            continue
        url = sample_url(rule)
        method = 'GET' if 'GET' in rule.methods else sorted(rule.methods - {'OPTIONS', 'HEAD'})[0]
        r = client.open(url, method=method)
        if rule.endpoint in webapp.AUTH_API_ENDPOINTS:
            assert r.status_code == 401 and r.get_json()['error_code'] == 'login_required', url
        else:
            assert r.status_code == 302 and r.location.startswith('/login/?next='), url
        checked += 1
    assert checked >= 8
    assert netbox.calls == [], "no session cookie: NetBox is not asked"


def test_login_redirect_keeps_the_page(client, netbox):
    r = client.get(f'{BASE}/map/1/10_20_0_0_17?focus=10.20.0.5&tenant=3')
    assert r.status_code == 302
    assert r.location == '/login/?next=/prefix-map/map/1/10_20_0_0_17%3Ffocus%3D10.20.0.5%26tenant%3D3'
    assert client.get(f'{BASE}/').location == '/login/?next=/prefix-map/'


def test_unknown_path_needs_a_session_too(client, netbox):
    assert client.get(f'{BASE}/nothing-here').status_code == 302


def test_exempt_routes_open_without_a_session(client, netbox, monkeypatch):
    assert client.get(f'{BASE}/healthz').status_code == 200
    assert client.get(f'{BASE}/metrics').status_code == 200
    assert client.get(f'{BASE}/static/js/map.js').status_code == 200
    r = client.post(f'{BASE}/webhook', json={'event': 'updated', 'model': 'dcim.cable'})
    assert r.status_code == 200 and r.get_json()['status'] == 'ignored'


def test_user_with_access_opens_the_maps(client, netbox):
    with_cookie(client, COOKIE)
    assert client.get(f'{BASE}/').status_code == 200
    assert client.get(f'{BASE}/map/1/10_20_0_0_17').status_code == 200
    assert client.get(f'{BASE}/data/1/10_20_0_0_17').status_code == 200
    assert client.get(f'{BASE}/search', query_string={'q': '10.20.0.5'}).status_code == 200
    assert client.get(f'{BASE}/errors').status_code == 200
    assert len(netbox.calls) == 1, "cached for the session"


def test_user_without_permission_gets_403(client, netbox):
    with_cookie(client, 'no-perm')
    r = client.get(f'{BASE}/map/1/10_20_0_0_17', headers={'Accept-Language': 'en'})
    assert r.status_code == 403 and b'may not view prefixes' in r.data and b'No access' in r.data
    assert b'>Back to the VRF list</a>' not in r.data, "the VRF list is closed too"
    r = client.get(f'{BASE}/data/1/10_20_0_0_17')
    assert r.status_code == 403 and r.get_json()['error_code'] == 'forbidden'
    assert b'10.20.' not in client.get(f'{BASE}/search', query_string={'q': '10.20.0.5'}).data


def test_403_page_in_russian(client, netbox):
    with_cookie(client, 'no-perm')
    r = client.get(f'{BASE}/', headers={'Accept-Language': 'ru'})
    assert r.status_code == 403 and 'Нет доступа' in r.get_data(as_text=True)


def test_netbox_down_gives_503(webapp, client, monkeypatch):
    monkeypatch.setattr(webapp, 'NETBOX_SESSION_AUTH', True)
    monkeypatch.setattr(webapp, 'session_auth', checker(FakeNetbox(error=requests.ConnectionError('refused'))))
    with_cookie(client, COOKIE)
    assert client.get(f'{BASE}/').status_code == 503
    r = client.get(f'{BASE}/data/1/10_20_0_0_17')
    assert r.status_code == 503 and r.get_json()['error_code'] == 'unavailable'


def test_without_netbox_url_everything_is_refused(webapp, client, monkeypatch):
    monkeypatch.setattr(webapp, 'NETBOX_SESSION_AUTH', True)
    monkeypatch.setattr(webapp, 'NETBOX_URL', None)
    with_cookie(client, COOKIE)
    assert client.get(f'{BASE}/').status_code == 503


def test_login_url_setting(client, netbox, webapp, monkeypatch):
    monkeypatch.setattr(webapp, 'NETBOX_LOGIN_URL', '/netbox/login/')
    assert client.get(f'{BASE}/help').location == '/netbox/login/?next=/prefix-map/help'


def test_off_by_default(webapp, client):
    assert webapp.NETBOX_SESSION_AUTH is False
    assert client.get(f'{BASE}/').status_code == 200


def test_client_address_from_the_trusted_proxy(webapp):
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert isinstance(webapp.app.wsgi_app, ProxyFix) and webapp.app.wsgi_app.x_for == 1
    seen = {}

    def inner(environ, start_response):
        seen['addr'] = environ['REMOTE_ADDR']
        start_response('200 OK', [])
        return [b'']

    fix = ProxyFix(inner, x_for=webapp.TRUSTED_PROXIES)
    list(fix({'REMOTE_ADDR': '127.0.0.1', 'HTTP_X_FORWARDED_FOR': '6.6.6.6, 10.0.0.7',
              'REQUEST_METHOD': 'GET', 'PATH_INFO': '/', 'wsgi.url_scheme': 'http'}, lambda *a: None))
    assert seen['addr'] == '10.0.0.7', "the address added by the proxy, not the one the client wrote"


def test_large_request_body_is_refused(client, webapp, monkeypatch):
    monkeypatch.setattr(webapp, 'WEBHOOK_SECRET', '')
    r = client.post(f'{BASE}/webhook', data=b'x' * (2 * 1024 * 1024), content_type='application/json')
    assert r.status_code == 413
