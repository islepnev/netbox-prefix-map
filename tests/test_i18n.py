"""UI language: catalogues, language choice, plurals."""
import glob
import json
import os
import re

import pytest

from app import i18n

BASE = '/prefix-map'
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PLURAL_FORMS = {'en': {'one', 'other'}, 'ru': {'one', 'few', 'many'}}
PLACEHOLDER = re.compile(r'\{(\w+)\}')


def placeholders(message):
    texts = message.values() if isinstance(message, dict) else [message]
    return {name for text in texts for name in PLACEHOLDER.findall(text)}


def test_catalogues_have_the_same_keys():
    en = i18n.CATALOGUES['en']
    for lang in i18n.LANGUAGES:
        keys = set(i18n.CATALOGUES[lang])
        assert keys == set(en), (lang, sorted(keys ^ set(en)))


@pytest.mark.parametrize('lang', i18n.LANGUAGES)
def test_messages_match_english(lang):
    """Same placeholders as English; plurals with every form of the language; nothing empty."""
    for key, message in i18n.CATALOGUES[lang].items():
        english = i18n.CATALOGUES['en'][key]
        assert placeholders(message) == placeholders(english), key
        assert isinstance(message, dict) == isinstance(english, dict), key
        if isinstance(message, dict):
            assert set(message) == PLURAL_FORMS[lang], key
            assert '{n}' in ''.join(message.values()) or 'n' not in placeholders(english), key
        texts = message.values() if isinstance(message, dict) else [message]
        assert all(text.strip() for text in texts), key


def used_keys():
    """Keys passed as literals to t() in templates and scripts."""
    pattern = re.compile(r'''\bt\(\s*["'`]([\w.-]+)["'`]''')
    files = [path for pattern in ('templates/*.html', 'static/js/*.js', 'app/*.py')
             for path in glob.glob(os.path.join(ROOT, pattern))]
    keys = {}
    for path in files:
        with open(path, encoding='utf-8') as f:
            for key in pattern.findall(f.read()):
                keys.setdefault(key, os.path.relpath(path, ROOT))
    return keys


def test_every_used_key_exists():
    missing = {k: f for k, f in used_keys().items() if k not in i18n.CATALOGUES['en']}
    assert not missing


@pytest.mark.parametrize('n, form', [(0, 'many'), (1, 'one'), (2, 'few'), (4, 'few'), (5, 'many'), (11, 'many'),
                                     (12, 'many'), (14, 'many'), (21, 'one'), (22, 'few'), (101, 'one'),
                                     (111, 'many'), (1000, 'many')])
def test_russian_plural_forms(n, form):
    assert i18n.plural_form('ru', n) == form


def test_translate_plural_and_number(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGUES, 'ru', {'x': {'one': '{n} адрес', 'few': '{n} адреса', 'many': '{n} адресов'}})
    assert i18n.translate('ru', 'x', n=1) == '1 адрес'
    assert i18n.translate('ru', 'x', n=3) == '3 адреса'
    assert i18n.translate('ru', 'x', n=1234) == '1 234 адреса'
    assert i18n.translate('ru', 'no.such.key') == 'no.such.key'


def test_english_by_default(client):
    r = client.get(f'{BASE}/')
    assert b'<html lang="en">' in r.data
    assert 'Accept-Language' in r.headers['Vary'] and 'Cookie' in r.headers['Vary']
    assert 'lang=' not in r.headers.get('Set-Cookie', '')


def test_language_from_accept_language(client):
    r = client.get(f'{BASE}/', headers={'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8'})
    assert b'<html lang="ru">' in r.data
    r = client.get(f'{BASE}/', headers={'Accept-Language': 'de-DE,fr;q=0.8'})
    assert b'<html lang="en">' in r.data


def test_lang_parameter_sets_cookie(client):
    r = client.get(f'{BASE}/help?lang=ru', headers={'Accept-Language': 'en'})
    assert b'<html lang="ru">' in r.data
    cookie = r.headers['Set-Cookie']
    assert cookie.startswith('lang=ru;') and f'Path={BASE}' in cookie
    r = client.get(f'{BASE}/', headers={'Accept-Language': 'en'})
    assert b'<html lang="ru">' in r.data, "the cookie wins over Accept-Language"
    r = client.get(f'{BASE}/?lang=xx')
    assert b'<html lang="ru">' in r.data, "an unknown language is ignored"
    client.get(f'{BASE}/?lang=en')
    assert b'<html lang="en">' in client.get(f'{BASE}/').data


def test_page_embeds_messages_of_its_language(client):
    for path in ('/', '/map/1', '/map/1/10_20_48_0_20', '/help', '/errors'):
        r = client.get(f'{BASE}{path}?lang=ru')
        html = r.data.decode()
        m = re.search(r'<script type="application/json" id="i18n">(.*?)</script>', html)
        assert m, path
        conf = json.loads(m.group(1))
        assert conf['lang'] == 'ru' and conf['messages']['topbar.language'] == 'Язык'
        assert 'aria-current="true">RU</a>' in html, path
    client.get(f'{BASE}/?lang=en')


def test_json_endpoints_have_no_language_vary(client):
    r = client.get(f'{BASE}/data/1/10_20_48_0_20')
    assert 'Accept-Language' not in r.headers.get('Vary', '')
