"""
v33-μ: profile clock + weather bar context

Provides a small before_request hook that attaches the active user's saved
country, city, and timezone to flask.g so templates (notably the
_clock_weather_bar.html partial and base.html body data attrs) can render
without each route having to pass these values explicitly.

Read-only. No mutation. No GPS. No IP geolocation. Profile fields only.
"""
from __future__ import annotations

from flask import g, has_request_context, request, url_for
from werkzeug.routing import BuildError

from .scope import get_current_user


_SKIP_PATH_PREFIXES = ('/static/', '/api/', '/mobile/api/')
_SKIP_ENDPOINT_PREFIXES = ('static', 'energy.', 'mobile_api.', 'mobile_auth_api.', 'openapi_api.')


def _should_skip_cwx_request():
    """Avoid profile lookups for assets and JSON/AJAX endpoints."""
    if not has_request_context():
        return True
    path = request.path or ''
    endpoint = request.endpoint or ''
    if path.startswith(_SKIP_PATH_PREFIXES):
        return True
    if endpoint == 'static' or endpoint.startswith(_SKIP_ENDPOINT_PREFIXES):
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    return False


def register_clock_weather_context(app):
    @app.before_request
    def _hydrate_cwx_context():
        """Populate g.cwx_user_* from the signed-in user's profile.

        Anonymous (logged-out) requests get empty strings; the partial then
        renders its empty state with a profile-setup hint that points at the
        login page (since g.cwx_profile_url falls back to login).
        """
        if _should_skip_cwx_request():
            return None
        user = None
        try:
            user = get_current_user()
        except Exception:
            user = None

        country = (getattr(user, 'country', None) or '').strip() if user else ''
        city = (getattr(user, 'city', None) or '').strip() if user else ''
        timezone = (getattr(user, 'timezone', None) or '').strip() if user else ''

        g.cwx_user_country = country
        g.cwx_user_city = city
        g.cwx_user_timezone = timezone

        # Pick the right profile URL based on the user's role. Admin users get
        # /admin/me (their dedicated self-profile from v33-ε-3). Regular users
        # get /account/profile. Anonymous visitors get the login page.
        profile_url = ''
        try:
            if user is None:
                lang = request.args.get('lang') or getattr(g, 'ui_lang', 'ar')
                profile_url = url_for('auth.login', lang=lang)
            else:
                lang = request.args.get('lang') or getattr(g, 'ui_lang', 'ar')
                role = (getattr(user, 'role', '') or '').strip().lower()
                is_admin_flag = bool(getattr(user, 'is_admin', False))
                if role == 'admin' or is_admin_flag or role in {'staff', 'support'}:
                    # Prefer the v33-ε-3 admin self-profile if registered;
                    # otherwise fall back to account_profile.
                    try:
                        profile_url = url_for('users_routes.admin_me', lang=lang)
                    except BuildError:
                        profile_url = url_for('main.account_profile', lang=lang)
                else:
                    profile_url = url_for('main.account_profile', lang=lang)
        except Exception:
            profile_url = '/'

        g.cwx_profile_url = profile_url
        return None

    @app.context_processor
    def _expose_cwx_to_templates():
        return {
            'cwx_user_country': getattr(g, 'cwx_user_country', '') if has_request_context() else '',
            'cwx_user_city': getattr(g, 'cwx_user_city', '') if has_request_context() else '',
            'cwx_user_timezone': getattr(g, 'cwx_user_timezone', '') if has_request_context() else '',
            'cwx_profile_url': getattr(g, 'cwx_profile_url', '') if has_request_context() else '',
        }
