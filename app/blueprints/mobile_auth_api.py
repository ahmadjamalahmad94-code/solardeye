from __future__ import annotations

from flask import Blueprint, request

from ..services.api_responses import api_error, api_ok
from ..services.mobile_auth import authenticate_username_password, issue_refresh_token, refresh_access_token, revoke_refresh_token, token_payload, user_from_bearer_or_session
from ..services.access_state import account_access_state

mobile_auth_api_bp = Blueprint('mobile_auth_api', __name__, url_prefix='/api/v1/auth')


def _json():
    return request.get_json(silent=True) or {}


@mobile_auth_api_bp.post('/login')
def mobile_login():
    data = _json()
    username = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return api_error('Username and password are required.', code='missing_credentials', status=400)
    user = authenticate_username_password(username, password)
    if not user:
        return api_error('Invalid username or password.', code='invalid_credentials', status=401)
    refresh = issue_refresh_token(user, device_label=data.get('device_label') or '', ip_address=request.remote_addr or '', user_agent=request.headers.get('User-Agent', ''))
    return api_ok(token_payload(user, refresh), meta={'api_version': 'v1'})


@mobile_auth_api_bp.post('/refresh')
def mobile_refresh():
    data = _json()
    user, access = refresh_access_token(data.get('refresh_token'))
    if not user or not access:
        return api_error('Refresh token is invalid or expired.', code='invalid_refresh_token', status=401)
    payload = token_payload(user)
    payload['access_token'] = access
    return api_ok(payload, meta={'api_version': 'v1'})


@mobile_auth_api_bp.post('/logout')
def mobile_logout():
    data = _json()
    changed = revoke_refresh_token(data.get('refresh_token')) if data.get('refresh_token') else False
    return api_ok({'revoked': changed})


@mobile_auth_api_bp.get('/me')
def mobile_me():
    user = user_from_bearer_or_session()
    if not user:
        return api_error('Authentication required.', code='auth_required', status=401)
    state = account_access_state(user)
    return api_ok({'id': user.id, 'username': user.username, 'full_name': user.full_name, 'email': user.email, 'role': user.role, 'is_admin': bool(user.is_admin), 'is_active': bool(user.is_active), 'account_restricted': bool(state.get('restricted')), 'restriction_reason': state.get('reason') or '', 'can_write': not bool(state.get('restricted'))})
