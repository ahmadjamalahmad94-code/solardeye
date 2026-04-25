from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request, url_for

from ..extensions import db
from ..models import AppUser, CannedReply, InternalMailMessage, InternalMailThread, SupportTicket, SupportTicketMessage, TenantAccount
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.support_ops import audit_case, notify_user, upsert_support_case
from ..services.subscriptions import ensure_user_tenant_and_subscription
from ..services.quota_engine import consume_quota_for_user

mobile_support_api_bp = Blueprint('mobile_support_api', __name__, url_prefix='/api/v1/support')


def _require_user():
    user = user_from_bearer_or_session()
    if not user:
        return None, api_error('Authentication required.', code='auth_required', status=401)
    return user, None


def _json():
    return request.get_json(silent=True) or {}


def _owner_filter(user, model, kind='message'):
    if getattr(user, 'is_admin', False):
        return model.query
    tenant, _ = ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    tenant_id = getattr(tenant, 'id', None)
    if kind == 'message':
        q = model.query.filter((model.created_by_user_id == user.id) | (model.tenant_id == tenant_id)) if tenant_id else model.query.filter_by(created_by_user_id=user.id)
    else:
        q = model.query.filter((model.opened_by_user_id == user.id) | (model.tenant_id == tenant_id)) if tenant_id else model.query.filter_by(opened_by_user_id=user.id)
    return q


def _messages_for(kind: str, source_id: int, user) -> list[dict]:
    model = InternalMailMessage if kind == 'message' else SupportTicketMessage
    if kind == 'message':
        q = model.query.filter_by(thread_id=source_id)
    else:
        q = model.query.filter_by(ticket_id=source_id)
    if not getattr(user, 'is_admin', False):
        q = q.filter_by(is_internal_note=False)
    rows = q.order_by(model.created_at.asc(), model.id.asc()).all()
    return [{
        'id': row.id,
        'sender_user_id': row.sender_user_id,
        'sender_scope': row.sender_scope,
        'is_internal_note': bool(row.is_internal_note),
        'body': row.body,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    } for row in rows]


def _case_payload(kind: str, item, user, include_messages: bool = False):
    if not item:
        return None
    owner_id = getattr(item, 'created_by_user_id', None) if kind == 'message' else getattr(item, 'opened_by_user_id', None)
    data = {
        'type': kind,
        'id': item.id,
        'tenant_id': item.tenant_id,
        'owner_user_id': owner_id,
        'assigned_admin_user_id': getattr(item, 'assigned_admin_user_id', None),
        'subject': item.subject,
        'category': item.category,
        'priority': item.priority,
        'status': item.status,
        'last_reply_at': item.last_reply_at.isoformat() if item.last_reply_at else None,
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'updated_at': item.updated_at.isoformat() if item.updated_at else None,
    }
    if kind == 'ticket':
        data['related_device_id'] = getattr(item, 'related_device_id', None)
    if include_messages:
        data['messages'] = _messages_for(kind, item.id, user)
    return data


def _case_for_user(user, kind: str, case_id: int):
    if kind in ['message', 'mail']:
        return 'message', _owner_filter(user, InternalMailThread, 'message').filter_by(id=case_id).first()
    if kind == 'ticket':
        return 'ticket', _owner_filter(user, SupportTicket, 'ticket').filter_by(id=case_id).first()
    return kind, None


@mobile_support_api_bp.get('/cases')
def support_cases():
    user, err = _require_user()
    if err:
        return err
    page, page_size = pagination_args(default_size=30, max_size=100)
    kind_filter = (request.args.get('type') or 'all').strip()
    rows = []
    if kind_filter in ['all', 'message', 'mail']:
        for item in _owner_filter(user, InternalMailThread, 'message').all():
            rows.append(_case_payload('message', item, user))
    if kind_filter in ['all', 'ticket']:
        for item in _owner_filter(user, SupportTicket, 'ticket').all():
            rows.append(_case_payload('ticket', item, user))
    status_filter = (request.args.get('status') or '').strip()
    if status_filter:
        rows = [row for row in rows if row and row.get('status') == status_filter]
    rows.sort(key=lambda row: row.get('updated_at') or row.get('created_at') or '', reverse=True)
    total = len(rows)
    start = (page - 1) * page_size
    return api_ok({'items': rows[start:start + page_size]}, meta=page_meta(page, page_size, total))


@mobile_support_api_bp.get('/cases/<kind>/<int:case_id>')
def support_case_detail(kind: str, case_id: int):
    user, err = _require_user()
    if err:
        return err
    kind, item = _case_for_user(user, kind, case_id)
    if not item:
        return api_error('Support case not found.', code='support_case_not_found', status=404)
    return api_ok(_case_payload(kind, item, user, include_messages=True))


@mobile_support_api_bp.post('/cases')
def create_support_case():
    user, err = _require_user()
    if err:
        return err
    data = _json()
    kind = (data.get('type') or data.get('kind') or 'message').strip()
    subject = (data.get('subject') or '').strip()
    body = (data.get('body') or data.get('message') or '').strip()
    priority = (data.get('priority') or 'normal').strip()
    category = (data.get('category') or ('support' if kind == 'ticket' else 'general')).strip()
    if not subject or not body:
        return api_error('Subject and message body are required.', code='missing_support_fields', status=400)
    tenant, _ = ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    tenant_id = getattr(tenant, 'id', None)
    ok, quota_msg, _quota = consume_quota_for_user(user, 'support_cases_limit', 1, lang='en')
    if not ok:
        return api_error(quota_msg, code='quota_exceeded', status=429)
    if kind == 'ticket':
        item = SupportTicket(tenant_id=tenant_id, opened_by_user_id=user.id, subject=subject, category=category, priority=priority, status='open', related_device_id=data.get('related_device_id') or None, last_reply_at=datetime.utcnow())
        db.session.add(item); db.session.flush()
        db.session.add(SupportTicketMessage(ticket_id=item.id, sender_user_id=user.id, sender_scope='user', body=body))
        upsert_support_case('ticket', item, 'user')
        audit_case('ticket', item.id, user.id, 'ticket.mobile_create', 'Subscriber opened a ticket from mobile API', commit=False)
        source_type = 'ticket'
    else:
        item = InternalMailThread(tenant_id=tenant_id, created_by_user_id=user.id, subject=subject, category=category, priority=priority, status='open', last_reply_at=datetime.utcnow())
        db.session.add(item); db.session.flush()
        db.session.add(InternalMailMessage(thread_id=item.id, sender_user_id=user.id, sender_scope='user', body=body))
        upsert_support_case('message', item, 'user')
        audit_case('message', item.id, user.id, 'message.mobile_create', 'Subscriber opened a message from mobile API', commit=False)
        source_type = 'message'
    for admin in AppUser.query.filter_by(is_admin=True).all():
        notify_user(admin.id, source_type=source_type, source_id=item.id, tenant_id=tenant_id, title='New support request', message=subject, direct_url=url_for('main.admin_support_command_center', lang='en'), commit=False)
    db.session.commit()
    return api_ok(_case_payload(source_type, item, user, include_messages=True), status=201)


@mobile_support_api_bp.post('/cases/<kind>/<int:case_id>/reply')
def reply_support_case(kind: str, case_id: int):
    user, err = _require_user()
    if err:
        return err
    kind, item = _case_for_user(user, kind, case_id)
    if not item:
        return api_error('Support case not found.', code='support_case_not_found', status=404)
    if item.status in ['closed', 'resolved'] and not getattr(user, 'is_admin', False):
        return api_error('This support case is closed.', code='support_case_closed', status=409)
    data = _json()
    body = (data.get('body') or data.get('message') or '').strip()
    if not body:
        return api_error('Reply body is required.', code='missing_reply_body', status=400)
    scope = 'admin' if getattr(user, 'is_admin', False) else 'user'
    is_internal = bool(data.get('is_internal_note')) and getattr(user, 'is_admin', False)
    if kind == 'message':
        db.session.add(InternalMailMessage(thread_id=item.id, sender_user_id=user.id, sender_scope=scope, is_internal_note=is_internal, body=body))
    else:
        db.session.add(SupportTicketMessage(ticket_id=item.id, sender_user_id=user.id, sender_scope=scope, is_internal_note=is_internal, body=body))
    new_status = (data.get('status') or item.status or 'open').strip()
    if getattr(user, 'is_admin', False) and new_status:
        item.status = new_status
    item.last_reply_at = datetime.utcnow(); item.updated_at = datetime.utcnow()
    upsert_support_case(kind, item, scope)
    owner_id = getattr(item, 'created_by_user_id', None) if kind == 'message' else getattr(item, 'opened_by_user_id', None)
    target_id = owner_id if getattr(user, 'is_admin', False) else getattr(item, 'assigned_admin_user_id', None)
    if target_id:
        notify_user(target_id, source_type=kind, source_id=item.id, tenant_id=item.tenant_id, title='Support case updated', message=item.subject, direct_url=url_for('main.portal_support', lang='en'), commit=False)
    audit_case(kind, item.id, user.id, f'{kind}.mobile_reply', 'Mobile API support reply', {'status': item.status}, commit=False)
    db.session.commit()
    return api_ok(_case_payload(kind, item, user, include_messages=True))


@mobile_support_api_bp.post('/cases/<kind>/<int:case_id>/reopen')
def reopen_support_case(kind: str, case_id: int):
    user, err = _require_user()
    if err:
        return err
    kind, item = _case_for_user(user, kind, case_id)
    if not item:
        return api_error('Support case not found.', code='support_case_not_found', status=404)
    item.status = 'open'; item.updated_at = datetime.utcnow(); item.last_reply_at = datetime.utcnow()
    upsert_support_case(kind, item, 'user' if not getattr(user, 'is_admin', False) else 'admin')
    audit_case(kind, item.id, user.id, f'{kind}.mobile_reopen', 'Mobile API support reopen', commit=False)
    db.session.commit()
    return api_ok(_case_payload(kind, item, user, include_messages=True))


@mobile_support_api_bp.get('/canned-replies')
def canned_replies():
    user, err = _require_user()
    if err:
        return err
    if not getattr(user, 'is_admin', False):
        return api_error('Admin access required.', code='admin_required', status=403)
    rows = CannedReply.query.filter_by(is_active=True).order_by(CannedReply.title.asc()).all()
    return api_ok({'items': [{'id': r.id, 'title': r.title, 'body': r.body, 'category': r.category} for r in rows]})
