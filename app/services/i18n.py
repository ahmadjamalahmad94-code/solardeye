from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from flask import g, request, session, url_for

from .translations import SUPPORTED_LANGS, catalog_for

_ARABIC_RE = re.compile(r'[\u0600-\u06FF]')
_PROTECTED_HTML_RE = re.compile(r'(<(?:script|style|textarea|pre|code)\b[^>]*>.*?</(?:script|style|textarea|pre|code)>)', re.IGNORECASE | re.DOTALL)


def normalize_lang(value: str | None) -> str:
    value = str(value or '').strip().lower()
    if value.startswith('en'):
        return 'en'
    if value.startswith('ar'):
        return 'ar'
    return 'ar'


def active_lang() -> str:
    return normalize_lang(getattr(g, 'ui_lang', None) or session.get('ui_lang') or 'ar')


def choose(ar: str, en: str) -> str:
    return en if active_lang() == 'en' else ar


def _sorted_catalog(lang: str) -> list[tuple[str, str]]:
    catalog = catalog_for(lang)
    return sorted(catalog.items(), key=lambda item: len(item[0]), reverse=True)


def _replace_known_phrase(text: str, source: str, target: str) -> str:
    if not source or source not in text:
        return text
    # Short standalone Arabic words must not be replaced inside other words
    # (e.g. 'من' inside 'منصة').
    if re.fullmatch(r'[\u0600-\u06FF]+', source):
        pattern = re.compile(r'(?<![\u0600-\u06FF])' + re.escape(source) + r'(?![\u0600-\u06FF])')
        return pattern.sub(target, text)
    return text.replace(source, target)


def translate(value: str | None, lang: str | None = None, **kwargs) -> str:
    """Translate an Arabic-source phrase to the active UI language.

    Arabic remains the source language for backwards compatibility. English is
    served from the central catalog. New languages can be added by extending
    app/services/translations.py.
    """
    target = normalize_lang(lang or active_lang())
    text = '' if value is None else str(value)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    if target == 'ar' or not text:
        return text
    catalog = catalog_for(target)
    exact = catalog.get(text.strip())
    if exact:
        if text == text.strip():
            return exact
        return text.replace(text.strip(), exact)
    out = text
    for ar, translated in _sorted_catalog(target):
        out = _replace_known_phrase(out, ar, translated)
    return out


def translate_html(html: str, lang: str | None = None) -> str:
    """Translate legacy hard-coded Arabic UI text in rendered HTML.

    This keeps old templates functional while the project moves toward explicit
    translation keys. Script/style/code/textarea blocks are preserved so JSON,
    user typing areas, and executable code are not corrupted.
    """
    target = normalize_lang(lang or active_lang())
    if target == 'ar' or not html or not _ARABIC_RE.search(html):
        return html
    parts = _PROTECTED_HTML_RE.split(html)
    for i, part in enumerate(parts):
        if not part or _PROTECTED_HTML_RE.match(part):
            continue
        parts[i] = translate(part, target)
    return ''.join(parts)


def lang_url(lang: str, endpoint: str | None = None, **values) -> str:
    """Build a URL preserving the current route/query while changing language."""
    lang = normalize_lang(lang)
    endpoint = endpoint or request.endpoint
    if not endpoint:
        return f'?lang={lang}'
    args = request.view_args.copy() if request.view_args else {}
    args.update(values)
    query = request.args.to_dict(flat=True)
    query.update(args)
    query['lang'] = lang
    try:
        return url_for(endpoint, **query)
    except Exception:
        query = request.args.to_dict(flat=True)
        query['lang'] = lang
        return request.path + '?' + urlencode(query)


def register_i18n(app):
    @app.before_request
    def _capture_language():
        raw = request.args.get('lang') or request.form.get('lang')
        if raw:
            session['ui_lang'] = normalize_lang(raw)
        elif 'ui_lang' not in session:
            session['ui_lang'] = 'ar'
        g.ui_lang = normalize_lang(session.get('ui_lang'))
        return None

    @app.after_request
    def _translate_legacy_html(response):
        try:
            if active_lang() == 'en' and response.mimetype == 'text/html' and response.status_code < 400:
                text = response.get_data(as_text=True)
                translated = translate_html(text, 'en')
                if translated != text:
                    response.set_data(translated)
        except Exception:
            # Translation should never break the page response.
            pass
        return response

    @app.template_filter('tr')
    def _tr_filter(value, lang=None):
        return translate(value, lang)

    @app.context_processor
    def _i18n_context():
        lang = active_lang()
        client_catalog = catalog_for('en') if lang == 'en' else {}
        return {
            'ui_lang': lang,
            'is_en': lang == 'en',
            'supported_langs': sorted(SUPPORTED_LANGS),
            't': translate,
            'tr': translate,
            'lang_url': lang_url,
            'i18n_client_catalog': client_catalog,
            'i18n_client_catalog_json': json.dumps(client_catalog, ensure_ascii=False),
        }
