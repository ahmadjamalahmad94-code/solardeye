from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import url_for

from ..extensions import db
from ..models import (
    AppUser, CannedReply, InternalMailMessage, InternalMailThread, NotificationEvent,
    SupportAuditLog, SupportCase, SupportTicket, SupportTicketMessage, TenantAccount,
)

OPEN_STATUSES = {'open', 'assigned', 'waiting_user', 'pending', 'new'}
CLOSED_STATUSES = {'resolved', 'closed'}
DEFAULT_REPLIES = [
    ('تم استلام طلبك', 'تم استلام طلبك وتحويله للمتابعة. سنعود إليك بالتحديثات قريبًا.'),
    ('تم تحويله للمدير المسؤول', 'تم تحويل الطلب إلى المدير المسؤول، وسيتم متابعته حتى الوصول للحل.'),
    ('نحتاج معلومات إضافية', 'نحتاج منك معلومات إضافية حتى نستطيع معالجة الطلب بدقة.'),
    ('تم حل المشكلة', 'تم حل المشكلة. يرجى إبلاغنا إن ظهرت لديك أي ملاحظة إضافية.'),
    ('تم إغلاق التذكرة', 'تم إغلاق الطلب بعد الحل. يمكن إعادة فتحه عند الحاجة بإجراء واضح.'),
]


def seed_canned_replies():
    if CannedReply.query.count():
        return
    now = datetime.utcnow()
    for title, body in DEFAULT_REPLIES:
        db.session.add(CannedReply(title=title, body=body, category='support', created_at=now, updated_at=now))
    db.session.commit()


def case_url(case_type: str, source_id: int, owner_id: int | None = None, lang: str = 'ar') -> str:
    if owner_id:
        anchor = f"#thread-{source_id}" if case_type == 'message' else f"#ticket-{source_id}"
        return url_for('main.admin_user_profile', user_id=owner_id, lang=lang, tab='support') + anchor
    if case_type == 'message':
        return url_for('main.admin_internal_mail', lang=lang) + f"#thread-{source_id}"
    return url_for('main.admin_tickets', lang=lang) + f"#ticket-{source_id}"


def portal_case_url(case_type: str, source_id: int, lang: str = 'ar') -> str:
    typ = 'mail' if case_type == 'message' else 'ticket'
    anchor = f"#thread-{source_id}" if case_type == 'message' else f"#ticket-{source_id}"
    return url_for('main.portal_support', lang=lang, type=typ) + anchor


def _owner_id_for(case_type: str, source):
    if case_type == 'message':
        tenant = TenantAccount.query.get(getattr(source, 'tenant_id', None)) if getattr(source, 'tenant_id', None) else None
        return getattr(source, 'created_by_user_id', None) or getattr(tenant, 'owner_user_id', None)
    tenant = TenantAccount.query.get(getattr(source, 'tenant_id', None)) if getattr(source, 'tenant_id', None) else None
    return getattr(source, 'opened_by_user_id', None) or getattr(tenant, 'owner_user_id', None)


def upsert_support_case(case_type: str, source, last_reply_by: str | None = None):
    if not source:
        return None
    case = SupportCase.query.filter_by(case_type=case_type, source_id=source.id).first()
    created = False
    if not case:
        case = SupportCase(case_type=case_type, source_id=source.id, created_at=getattr(source, 'created_at', None) or datetime.utcnow())
        db.session.add(case)
        created = True
    case.tenant_id = getattr(source, 'tenant_id', None)
    case.user_id = getattr(source, 'created_by_user_id', None) if case_type == 'message' else getattr(source, 'opened_by_user_id', None)
    case.assigned_admin_user_id = getattr(source, 'assigned_admin_user_id', None)
    case.subject = getattr(source, 'subject', '') or ''
    case.priority = getattr(source, 'priority', 'normal') or 'normal'
    case.status = getattr(source, 'status', 'open') or 'open'
    case.is_frozen = case.status == 'closed'
    case.last_reply_at = getattr(source, 'last_reply_at', None) or getattr(source, 'updated_at', None) or getattr(source, 'created_at', None)
    case.last_reply_by = last_reply_by or case.last_reply_by
    case.updated_at = getattr(source, 'updated_at', None) or datetime.utcnow()
    if not case.sla_due_at:
        hours = 8 if case.priority in {'urgent', 'high'} else 24
        case.sla_due_at = (getattr(source, 'created_at', None) or datetime.utcnow()) + timedelta(hours=hours)
    if created:
        audit_case(case_type, source.id, None, 'case.create', f'Created support case for {case_type} #{source.id}', commit=False)
    return case


def audit_case(case_type: str, source_id: int, actor_user_id: int | None, action: str, summary: str, details: dict | None = None, commit: bool = True):
    db.session.add(SupportAuditLog(case_type=case_type, source_id=source_id, actor_user_id=actor_user_id, action=action, summary=summary, details_json=json.dumps(details or {}, ensure_ascii=False), created_at=datetime.utcnow()))
    if commit:
        db.session.commit()


def notify_user(target_user_id: int | None, *, event_type='support', source_type=None, source_id=None, tenant_id=None, title='', message='', direct_url='#', status='new', commit=False):
    if not target_user_id:
        return None
    ev = NotificationEvent(event_type=event_type, target_user_id=target_user_id, tenant_id=tenant_id, source_type=source_type, source_id=source_id, title=title or '', message=message or '', direct_url=direct_url or '#', status=status, created_at=datetime.utcnow())
    db.session.add(ev)
    if commit:
        db.session.commit()
    return ev


def sync_existing_cases():
    for thread in InternalMailThread.query.all():
        msg = InternalMailMessage.query.filter_by(thread_id=thread.id, is_internal_note=False).order_by(InternalMailMessage.created_at.desc(), InternalMailMessage.id.desc()).first()
        upsert_support_case('message', thread, getattr(msg, 'sender_scope', None))
    for ticket in SupportTicket.query.all():
        msg = SupportTicketMessage.query.filter_by(ticket_id=ticket.id, is_internal_note=False).order_by(SupportTicketMessage.created_at.desc(), SupportTicketMessage.id.desc()).first()
        upsert_support_case('ticket', ticket, getattr(msg, 'sender_scope', None))


def notification_items_for(user, is_admin: bool, limit=5, include_read=False, lang='ar'):
    q = NotificationEvent.query.filter_by(target_user_id=user.id)
    if not include_read:
        q = q.filter_by(is_read=False)
    rows = q.order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc()).limit(limit or 200).all()
    for ev in rows:
        ev.appeared_in_bell = True
    db.session.commit()
    return rows


def unread_counts(user):
    q = NotificationEvent.query.filter_by(target_user_id=user.id, is_read=False)
    total = q.count()
    mail = q.filter_by(source_type='message').count()
    ticket = q.filter_by(source_type='ticket').count()
    return total, mail, ticket


def build_support_queue(filter_key='all', actor_id=None):
    sync_existing_cases()
    q = SupportCase.query
    if filter_key == 'mine' and actor_id:
        q = q.filter_by(assigned_admin_user_id=actor_id)
    elif filter_key == 'unassigned':
        q = q.filter(SupportCase.assigned_admin_user_id.is_(None))
    elif filter_key == 'urgent':
        q = q.filter(SupportCase.priority.in_(['urgent', 'high']))
    elif filter_key == 'waiting_user':
        q = q.filter_by(status='waiting_user')
    elif filter_key == 'closed':
        q = q.filter(SupportCase.status.in_(['closed', 'resolved']))
    elif filter_key == 'unanswered':
        q = q.filter(SupportCase.last_reply_by == 'user')
    elif filter_key != 'all':
        q = q.filter(~SupportCase.status.in_(['closed', 'resolved']))
    rows = []
    now = datetime.utcnow()
    for case in q.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).all():
        user = AppUser.query.get(case.user_id) if case.user_id else None
        assignee = AppUser.query.get(case.assigned_admin_user_id) if case.assigned_admin_user_id else None
        tenant = TenantAccount.query.get(case.tenant_id) if case.tenant_id else None
        overdue = bool(case.sla_due_at and case.sla_due_at < now and case.status not in CLOSED_STATUSES)
        age_hours = round(((now - (case.created_at or now)).total_seconds() / 3600), 1)
        rows.append({'case': case, 'user': user, 'assignee': assignee, 'tenant': tenant, 'overdue': overdue, 'age_hours': age_hours, 'url': case_url(case.case_type, case.source_id, case.user_id, lang='ar')})
    return rows
