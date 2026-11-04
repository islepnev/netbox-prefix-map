"""
UI language: message catalogues (app/locales/<lang>.json) shared by templates and the browser scripts.

A message is a string with {name} placeholders, or a dict of plural forms (one, few, many, other) chosen by the
count n. A key missing in a language falls back to English, then to the key itself.
"""
import json
import os

from flask import request

LANGUAGES = ('en', 'ru')
# Each language named in itself, for the switcher
LANGUAGE_NAMES = {'en': 'English', 'ru': 'Русский'}
DEFAULT_LANGUAGE = 'en'
COOKIE = 'lang'
LOCALES_DIR = os.path.join(os.path.dirname(__file__), 'locales')


def load_catalogue(lang):
    with open(os.path.join(LOCALES_DIR, f'{lang}.json'), encoding='utf-8') as f:
        return json.load(f)


CATALOGUES = {lang: load_catalogue(lang) for lang in LANGUAGES}
# Sent to the page: English fills keys a language lacks
PAGE_MESSAGES = {lang: {**CATALOGUES[DEFAULT_LANGUAGE], **CATALOGUES[lang]} for lang in LANGUAGES}


def plural_form(lang, n):
    """CLDR plural category of an integer count."""
    n = abs(int(n))
    if lang == 'ru':
        if n % 10 == 1 and n % 100 != 11:
            return 'one'
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return 'few'
        return 'many'
    return 'one' if n == 1 else 'other'


def format_number(lang, n):
    """Thousands grouped as the browser does it: 1,234 in English, 1 234 (no-break space) in Russian."""
    text = f'{n:,}'
    return text.replace(',', ' ') if lang == 'ru' else text


def translate(lang, key, **params):
    message = CATALOGUES[lang].get(key)
    if message is None:
        message = CATALOGUES[DEFAULT_LANGUAGE].get(key, key)
    if isinstance(message, dict):
        n = params.get('n', 0)
        message = message.get(plural_form(lang, n)) or message.get('other') or message.get('many') or ''
    if 'n' in params and isinstance(params['n'], int):
        params = dict(params, n=format_number(lang, params['n']))
    for name, value in params.items():
        message = message.replace('{' + name + '}', str(value))
    return message


def requested_language():
    """?lang=, then the lang cookie, then Accept-Language; English by default."""
    for value in (request.args.get('lang'), request.cookies.get(COOKIE)):
        if value in LANGUAGES:
            return value
    return request.accept_languages.best_match(LANGUAGES, default=DEFAULT_LANGUAGE)


def get_language():
    """The language of the current request, resolved once."""
    lang = getattr(request, '_ui_language', None)
    if lang is None:
        lang = request._ui_language = requested_language()
    return lang


def t(key, **params):
    return translate(get_language(), key, **params)


def init_app(app, cookie_path='/'):
    @app.context_processor
    def inject_i18n():
        lang = get_language()
        return {'lang': lang, 't': t, 'languages': LANGUAGES, 'language_names': LANGUAGE_NAMES,
                'i18n_messages': PAGE_MESSAGES[lang],
                'fmt_count': lambda n: format_number(lang, n)}

    @app.after_request
    def remember_language(response):
        lang = request.args.get('lang')
        if lang in LANGUAGES and request.cookies.get(COOKIE) != lang:
            response.set_cookie(COOKIE, lang, max_age=365 * 86400, path=cookie_path, samesite='Lax')
        if response.mimetype == 'text/html':
            response.vary.update(('Accept-Language', 'Cookie'))
        return response
