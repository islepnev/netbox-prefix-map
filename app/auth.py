"""
Optional access check through the NetBox session of the user (NETBOX_SESSION_AUTH=1).

The app shares the host with NetBox, so the browser sends the NetBox session cookie with every request. The cookie is
passed to the NetBox API: a user who may view prefixes there may open the maps. Results are cached per session.
"""

import hashlib
import logging
import threading
import time

import requests

ALLOW, LOGIN, DENY, UNAVAILABLE = 'allow', 'login', 'deny', 'unavailable'

PROBE_PATH = '/api/ipam/prefixes/?limit=1&brief=1'
WHOAMI_PATH = '/api/authentication-check/'
CACHE_LIMIT = 10000


class NetboxSessionAuth:
    def __init__(self, netbox_url, cache_seconds=300, timeout=10, session=None):
        self.netbox_url = (netbox_url or '').rstrip('/')
        self.cache_seconds = cache_seconds
        self.timeout = timeout
        self.session = session or requests.Session()
        self._cache = {}
        self._lock = threading.Lock()

    def _get(self, path, cookies):
        return self.session.get(self.netbox_url + path, cookies=cookies, timeout=self.timeout,
                                allow_redirects=False, headers={'Accept': 'application/json'})

    def _ask_netbox(self, cookies):
        """(result, username) from NetBox; UNAVAILABLE when NetBox gives no clear answer."""
        r = self._get(PROBE_PATH, cookies)
        if r.status_code == 200:
            return ALLOW, None
        if r.status_code not in (401, 403):
            logging.warning(f"Access check: NetBox answered {r.status_code} to {PROBE_PATH}")
            return UNAVAILABLE, None
        # 403 for both a stale session and a user without the permission: ask who the session belongs to
        r = self._get(WHOAMI_PATH, cookies)
        if r.status_code in (401, 403):
            return LOGIN, None
        if r.status_code == 200:
            try:
                username = r.json().get('username')
            except ValueError:
                username = None
            return DENY, username
        logging.warning(f"Access check: NetBox answered {r.status_code} to {WHOAMI_PATH}")
        return UNAVAILABLE, None

    def check(self, cookie_name, cookie_value):
        """ALLOW, LOGIN, DENY or UNAVAILABLE for a NetBox session cookie; the cookie itself is never logged."""
        if not cookie_value:
            return LOGIN
        key = hashlib.sha256(cookie_value.encode()).hexdigest()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        try:
            result, username = self._ask_netbox({cookie_name: cookie_value})
        except requests.RequestException as e:
            logging.warning(f"Access check: NetBox unreachable: {type(e).__name__}")
            return UNAVAILABLE
        if result == UNAVAILABLE:
            return result
        if result == DENY:
            logging.info(f"Access check: user {username or '?'} may not view prefixes in NetBox")
        with self._lock:
            if len(self._cache) >= CACHE_LIMIT:
                self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
                if len(self._cache) >= CACHE_LIMIT:
                    self._cache.clear()
            self._cache[key] = (now + self.cache_seconds, result)
        return result
