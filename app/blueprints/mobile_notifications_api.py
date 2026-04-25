from __future__ import annotations

import hashlib
from datetime import datetime

from flask import Blueprint, request

from ..extensions import db
from ..models import MobilePushToken, NotificationEvent
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.security import sanitize_response_payload

mobile_notifications_api_bp = Blueprint('mobile_notifications_api', __name__, url_prefix='/api/v1/notifications')


def _require_user():
    user = user_from_bearer_or_session()
    if not user:
        return None, api_error('Authentication required.', code='auth_required', status=401)
    return user, None


def _json():
    return request.get_json(silent=True) or {}


def _hash(raw: str) -> str:
    return hashlib.sha256((raw or '').encode('utf-8')).hexdigest()


def _notification_payload(row):
    return sanitize_response_payload({
        'id': row.id,
        'type': row.event_type,
        'source_type': row.source_type,
        'source_id': row.source_id,
        'title': row.title,
        'message': row.message,
        'url': row.direct_url,
        'status': row.status,
        'is_read': bool(row.is_read),
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'read_at': row.read_at.isoformat() if row.read_at else None,
    })


@mobile_notifications_api_bp.get('')
@mobile_notifications_api_bp.get('/')
def notification_list():
    user, err = _require_user()
    if err:
        return err
    page, page_size = pagination_args(default_size=30, max_size=100)
    q = NotificationEvent.query.filter_by(target_user_id=user.id).order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
    if request.args.get('unread') in ['1', 'true', 'yes']:
        q = q.filter_by(is_read=False)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return api_ok({'items': [_notification_payload(row) for row in rows]}, meta=page_meta(page, page_size, total))


@mobile_notifications_api_bp.post('/mark-read')
def mark_read():
    user, err = _require_user()
    if err:
        return err
    data = _json()
    ids = data.get('ids') or []
    q = NotificationEvent.query.filter_by(target_user_id=user.id, is_read=False)
    if ids:
        q = q.filter(NotificationEvent.id.in_([int(x) for x in ids if str(x).isdigit()]))
    now = datetime.utcnow()
    changed = 0
    for row in q.all():
        row.is_read = True; row.status = 'read'; row.read_at = now; changed += 1
    db.session.commit()
    return api_ok({'changed': changed})


@mobile_notifications_api_bp.post('/push-tokens')
def register_push_token():
    user, err = _require_user()
    if err:
        return err
    data = _json()
    token = (data.get('token') or '').strip()
    platform = (data.get('platform') or 'android').strip().lower()
    if not token:
        return api_error('Push token is required.', code='missing_push_token', status=400)
    token_hash = _hash(token)
    row = MobilePushToken.query.filter_by(token_hash=token_hash).first()
    now = datetime.utcnow()
    if not row:
        row = MobilePushToken(user_id=user.id, token=token, token_hash=token_hash, platform=platform, created_at=now)
        db.session.add(row)
    row.user_id = user.id
    row.token = token
    row.platform = platform
    row.device_label = (data.get('device_label') or '')[:160]
    row.app_version = (data.get('app_version') or '')[:60]
    row.is_active = True
    row.last_seen_at = now
    row.revoked_at = None
    db.session.commit()
    return api_ok({'registered': True, 'platform': platform})


@mobile_notifications_api_bp.delete('/push-tokens')
@mobile_notifications_api_bp.post('/push-tokens/unregister')
def unregister_push_token():
    user, err = _require_user()
    if err:
        return err
    data = _json()
    token = (data.get('token') or '').strip()
    if not token:
        return api_error('Push token is required.', code='missing_push_token', status=400)
    row = MobilePushToken.query.filter_by(user_id=user.id, token_hash=_hash(token), is_active=True).first()
    if row:
        row.is_active = False; row.revoked_at = datetime.utcnow()
        db.session.commit()
    return api_ok({'unregistered': bool(row)})
