from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from flask import current_app, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

from ..extensions import db
from ..models import AppUser, MobileRefreshToken
from .access_state import account_access_state

ACCESS_TOKEN_SALT = 'solardeye-mobile-access-v1'
REFRESH_TOKEN_BYTES = 48


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=ACCESS_TOKEN_SALT)


def access_token_max_age() -> int:
    return int(current_app.config.get('MOBILE_ACCESS_TOKEN_SECONDS', 15 * 60) or (15 * 60))


def refresh_token_days() -> int:
    return int(current_app.config.get('MOBILE_REFRESH_TOKEN_DAYS', 30) or 30)


def _hash_token(raw: str) -> str:
    return hashlib.sha256((raw or '').encode('utf-8')).hexdigest()


def issue_access_token(user: AppUser) -> str:
    payload = {'uid': user.id, 'role': user.role, 'iat': int(datetime.utcnow().timestamp())}
    return _serializer().dumps(payload)


def issue_refresh_token(user: AppUser, *, device_label: str = '', ip_address: str = '', user_agent: str = '') -> str:
    raw = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    now = datetime.utcnow()
    row = MobileRefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw),
        device_label=(device_label or '')[:160],
        ip_address=(ip_address or '')[:80],
        user_agent=(user_agent or '')[:255],
        expires_at=now + timedelta(days=refresh_token_days()),
        created_at=now,
        last_used_at=now,
    )
    db.session.add(row)
    db.session.commit()
    return raw


def verify_access_token(raw: str | None) -> AppUser | None:
    token = (raw or '').strip()
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=access_token_max_age())
    except (BadSignature, SignatureExpired, Exception):
        return None
    user_id = payload.get('uid') if isinstance(payload, dict) else None
    if not user_id:
        return None
    user = AppUser.query.get(int(user_id))
    if not user:
        return None
    return user


def refresh_access_token(refresh_token: str | None) -> tuple[AppUser | None, str | None]:
    token_hash = _hash_token(refresh_token or '')
    if not refresh_token:
        return None, None
    row = MobileRefreshToken.query.filter_by(token_hash=token_hash, revoked_at=None).first()
    now = datetime.utcnow()
    if not row or (row.expires_at and row.expires_at < now):
        return None, None
    user = AppUser.query.get(row.user_id)
    if not user:
        return None, None
    row.last_used_at = now
    db.session.commit()
    return user, issue_access_token(user)


def revoke_refresh_token(refresh_token: str | None) -> bool:
    token_hash = _hash_token(refresh_token or '')
    row = MobileRefreshToken.query.filter_by(token_hash=token_hash, revoked_at=None).first()
    if not row:
        return False
    row.revoked_at = datetime.utcnow()
    db.session.commit()
    return True


def user_from_bearer_or_session() -> AppUser | None:
    auth = request.headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        user = verify_access_token(auth.split(' ', 1)[1])
        if user:
            return user
    if session.get('logged_in') and session.get('user_id'):
        return AppUser.query.get(int(session.get('user_id')))
    return None


def authenticate_username_password(username: str, password: str) -> AppUser | None:
    user = AppUser.query.filter(AppUser.username == (username or '').strip()).first()
    if not user:
        return None
    if not check_password_hash(user.password_hash or '', password or ''):
        return None
    user.last_login_at = datetime.utcnow()
    db.session.commit()
    return user


def token_payload(user: AppUser, refresh_token: str | None = None) -> dict[str, Any]:
    state = account_access_state(user)
    data = {
        'access_token': issue_access_token(user),
        'token_type': 'Bearer',
        'expires_in': access_token_max_age(),
        'account_restricted': bool(state.get('restricted')),
        'restriction_reason': state.get('reason') or '',
        'restriction_message': state.get('message_en') or '',
        'can_write': not bool(state.get('restricted')),
        'user': {'id': user.id, 'username': user.username, 'full_name': user.full_name, 'role': user.role, 'is_admin': bool(user.is_admin), 'is_active': bool(user.is_active)},
    }
    if refresh_token:
        data['refresh_token'] = refresh_token
        data['refresh_expires_in_days'] = refresh_token_days()
    return data
