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


def test_russian_pages(client):
    ru = {'Accept-Language': 'ru'}
    html = client.get(f'{BASE}/', headers=ru).data.decode()
    assert 'Префиксы IPv4 и IP-адреса по VRF' in html and '>Глобальный</a>' in html
    html = client.get(f'{BASE}/map/1', headers=ru).data.decode()
    assert 'Занято адресов' in html and '<span class="pill">Контейнер</span>' in html
    assert re.search(r'<b>[\d ]+</b><span>(префикс|префикса|префиксов) IPv4</span>', html)
    html = client.get(f'{BASE}/map/1/10_20_48_0_20', headers=ru).data.decode()
    assert 'Инспектор' in html and 'Дерево префиксов' in html and '<kbd>Esc</kbd> открепляет' in html
    r = client.get(f'{BASE}/map/999', headers=ru)
    assert r.status_code == 404 and 'VRF 999 не найден.' in r.data.decode()


def test_search_errors_are_translated_with_a_code(client):
    r = client.get(f'{BASE}/search?q=x', headers={'Accept-Language': 'ru'})
    assert r.status_code == 400
    assert r.json['error_code'] == 'bad_query' and r.json['error'].startswith('Нужен IPv4-адрес')
    r = client.get(f'{BASE}/search?q=free /26 in 10.20.0.0/99')
    assert r.status_code == 400
    assert r.json == {'error': 'Not an IPv4 prefix: 10.20.0.0/99', 'error_code': 'bad_prefix'}


def test_free_search_in_russian(client):
    en = client.get(f'{BASE}/search', query_string={'q': 'free /26 in 10.20.0.0/16'}).json
    ru = client.get(f'{BASE}/search', query_string={'q': 'свободные /26 в 10.20.0.0/16'}).json
    assert ru['free'] and ru['results'] == en['results'] and ru['results']


TEXT_ALLOWED = re.compile(r'^(VRF|RD|VLAN|NetBox|IPv4|[A-Z]?[\W\d_]*)$')


class TemplateText(__import__('html.parser').parser.HTMLParser):
    """Words in template text and in title, alt, placeholder, aria-label attributes, outside {{ }} and {% %}."""
    ATTRS = ('title', 'alt', 'placeholder', 'aria-label')

    def __init__(self):
        super().__init__()
        self.words, self.skip = [], 0

    def add(self, text):
        text = re.sub(r'\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}', ' ', text, flags=re.S)
        self.words += [w for w in re.findall(r'[^\s·›—|]+', text) if not TEXT_ALLOWED.match(w)]

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'svg', 'kbd', 'code'):
            self.skip += 1
        for name, value in attrs:
            if name in self.ATTRS and value:
                self.add(value)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'svg', 'kbd', 'code'):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.add(data)


# Help prose is checked by structure (test_help_bodies_match); the rest must take its text from the catalogues
TEMPLATES = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, 'templates', '*.html'))
                   if os.path.basename(p) != 'help.html')


@pytest.mark.parametrize('name', TEMPLATES)
def test_templates_have_no_literal_text(name):
    with open(os.path.join(ROOT, 'templates', name), encoding='utf-8') as f:
        source = f.read()
    parser = TemplateText()
    parser.feed(re.sub(r'\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}', ' ', source, flags=re.S))
    assert not parser.words, parser.words
