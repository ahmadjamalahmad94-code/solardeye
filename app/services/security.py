from __future__ import annotations

import hmac
import re
import secrets
import time
from typing import Any

from flask import abort, current_app, flash, jsonify, redirect, request, session, url_for

CSRF_SESSION_KEY = '_csrf_token_v70'
CSRF_EXEMPT_ENDPOINTS = {
    'main.telegram_webhook',
    'notifications_routes.telegram_webhook',
    'main.telegram_multilink_webhook',
}

SENSITIVE_KEY_RE = re.compile(
    r'(password|passwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key|client[_-]?secret|credentials|chat[_-]?id|sms[_-]?recipients|phone|email|plant[_-]?id|station[_-]?id|device[_-]?(sn|uid)|logger[_-]?sn|battery[_-]?sn|serial)',
    re.IGNORECASE,
)
SECRET_PLACEHOLDERS = {'', '****', '********', '••••••', '••••••••', '__KEEP_SECRET__'}
RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}


def csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _csrf_from_request() -> str:
    return (
        request.form.get('csrf_token')
        or request.headers.get('X-CSRF-Token')
        or request.headers.get('X-CSRFToken')
        or request.headers.get('X-CSRF')
        or ''
    )


def _csrf_error_response():
    wants_json = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
        or request.path.startswith('/api/')
    )
    if wants_json:
        return jsonify({'ok': False, 'message': 'CSRF token is missing or invalid.'}), 400
    abort(400, description='CSRF token is missing or invalid.')


def register_security(app):
    """Register lightweight app-wide security helpers.

    This avoids adding new dependencies while giving every POST form and AJAX call
    a session-bound CSRF token. Telegram webhooks stay exempt because they are
    validated with their own secret when configured.
    """

    @app.context_processor
    def _security_context():
        from .access_state import account_access_state, account_restricted_message, request_user_from_session
        user = request_user_from_session()
        state = account_access_state(user)
        lang = 'en' if (request.args.get('lang') or session.get('ui_lang') or 'ar') == 'en' else 'ar'
        return {
            'csrf_token': csrf_token,
            'mask_secret': mask_secret,
            'mask_email': mask_email,
            'mask_identifier': mask_identifier,
            'is_sensitive_key': is_sensitive_key,
            'account_preview_restricted': bool(state.get('restricted')),
            'account_preview_reason': state.get('reason') or '',
            'account_preview_message': account_restricted_message(lang, user),
        }

    @app.before_request
    def _light_rate_limit():
        # Dependency-free guardrail. It protects login and heavy write endpoints without
        # blocking normal browsing. It is per worker, so use Cloudflare/NGINX limits too
        # for very high-traffic production.
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None
        path = request.path or ''
        strict = request.endpoint in {'auth.login', 'auth.register'}
        if not strict and not (path.startswith('/admin') or path.startswith('/api/')):
            return None
        now = time.time()
        window = 60.0
        max_hits = 12 if strict else 80
        identity = session.get('user_id') or request.headers.get('X-Forwarded-For', request.remote_addr or 'anon')
        key = f"{identity}:{request.endpoint or path}"
        hits = [t for t in RATE_LIMIT_BUCKETS.get(key, []) if now - t < window]
        if len(hits) >= max_hits:
            wants_json = request.accept_mimetypes.best == 'application/json' or path.startswith('/api/')
            if wants_json:
                return jsonify({'ok': False, 'message': 'Rate limit exceeded. Try again shortly.'}), 429
            abort(429, description='Rate limit exceeded. Try again shortly.')
        hits.append(now)
        RATE_LIMIT_BUCKETS[key] = hits
        if len(RATE_LIMIT_BUCKETS) > 2000:
            for old_key in list(RATE_LIMIT_BUCKETS.keys())[:500]:
                RATE_LIMIT_BUCKETS.pop(old_key, None)
        return None

    @app.before_request
    def _account_preview_write_guard():
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None
        endpoint = request.endpoint or ''
        path = request.path or ''
        # Auth endpoints must remain usable; logout is allowed from preview mode.
        if endpoint in {'auth.login', 'auth.register', 'auth.logout', 'mobile_auth_api.mobile_login', 'mobile_auth_api.mobile_refresh', 'mobile_auth_api.mobile_logout'}:
            return None
        from .access_state import account_access_state, request_user_from_session
        user = request_user_from_session()
        # Bearer-token mobile requests do not have a browser session; resolve lazily.
        if user is None and path.startswith('/api/v1/'):
            try:
                from .mobile_auth import user_from_bearer_or_session
                user = user_from_bearer_or_session()
            except Exception:
                user = None
        state = account_access_state(user)
        if not state.get('restricted'):
            return None
        lang = 'en' if (request.args.get('lang') or session.get('ui_lang') or 'ar') == 'en' else 'ar'
        msg = state.get('message_en' if lang == 'en' else 'message_ar') or 'Account is in read-only preview mode.'
        wants_json = request.accept_mimetypes.best == 'application/json' or path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if wants_json:
            return jsonify({'ok': False, 'code': 'account_restricted', 'message': msg}), 403
        flash(msg, 'warning')
        if path.startswith('/admin'):
            return redirect(url_for('main.account_subscription', lang=lang))
        ref = request.referrer or ''
        if ref and request.host_url and ref.startswith(request.host_url):
            return redirect(ref)
        return redirect(url_for('main.account_subscription', lang=lang))

    @app.before_request
    def _csrf_protect():
        if not current_app.config.get('CSRF_ENABLED', True):
            return None
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None
        if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
            return None
        # Mobile/API clients authenticate with bearer/refresh tokens instead of browser cookies.
        # They are intentionally CSRF-exempt so Android can call JSON endpoints cleanly.
        if (request.path or '').startswith('/api/v1/'):
            return None
        expected = session.get(CSRF_SESSION_KEY)
        supplied = _csrf_from_request()
        if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
            return _csrf_error_response()
        return None

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
        return response


def is_sensitive_key(key: Any) -> bool:
    return bool(SENSITIVE_KEY_RE.search(str(key or '')))


def mask_email(value: Any, *, empty: str = '—') -> str:
    raw = '' if value is None else str(value).strip()
    if not raw:
        return empty
    if '@' not in raw:
        return mask_secret(raw, visible=3, empty=empty)
    name, domain = raw.split('@', 1)
    prefix = name[:2] if len(name) > 2 else name[:1]
    return f"{prefix}{'*' * 6}@{domain}"


def mask_identifier(value: Any, *, visible: int = 4, empty: str = '—') -> str:
    return mask_secret(value, visible=visible, empty=empty)


def mask_secret(value: Any, *, visible: int = 4, empty: str = '—') -> str:
    raw = '' if value is None else str(value)
    if not raw:
        return empty
    if len(raw) <= max(visible, 0):
        return '****'
    return f"{'*' * 8}{raw[-visible:]}"


def preserve_secret_form_value(form, key: str, existing: Any = '') -> str:
    """Return the submitted secret unless it is intentionally masked/blank.

    This lets templates render secret fields as empty password inputs with a
    masked placeholder without erasing stored values on save.
    """
    value = (form.get(key, '') or '').strip()
    if value in SECRET_PLACEHOLDERS:
        return '' if form.get(f'clear_{key}') == '1' else (existing or '')
    return value


def sanitize_response_payload(payload: Any, *, max_depth: int = 8) -> Any:
    """Mask secrets recursively before returning debug/API payloads to users."""
    if max_depth <= 0:
        return '[truncated]'
    if isinstance(payload, dict):
        cleaned = {}
        for key, value in payload.items():
            if is_sensitive_key(key):
                cleaned[key] = mask_secret(value)
            else:
                cleaned[key] = sanitize_response_payload(value, max_depth=max_depth - 1)
        return cleaned
    if isinstance(payload, list):
        return [sanitize_response_payload(item, max_depth=max_depth - 1) for item in payload]
    return payload
