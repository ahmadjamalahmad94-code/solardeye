from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import url_for

from ..extensions import db
from ..models import (
    AppUser, CannedReply, InternalMailMessage, InternalMailThread, NotificationEvent,
    SupportAuditLog, SupportCase, SupportTicket, SupportTicketMessage, TenantAccount,
)

OPEN_STATUSES = {'new', 'open', 'assigned', 'in_progress', 'waiting_user', 'pending'}
CLOSED_STATUSES = {'resolved', 'closed'}
DEFAULT_REPLIES = [
    ('تم استلام طلبك', 'تم استلام طلبك وتحويله للمتابعة. سنعود إليك بالتحديثات قريبًا.'),
    ('تم تحويله للمدير المسؤول', 'تم تحويل الطلب إلى المدير المسؤول، وسيتم متابعته حتى الوصول للحل.'),
    ('نحتاج معلومات إضافية', 'نحتاج منك معلومات إضافية حتى نستطيع معالجة الطلب بدقة.'),
    ('تم حل المشكلة', 'تم حل المشكلة. يرجى إبلاغنا إن ظهرت لديك أي ملاحظة إضافية.'),
    ('تم إغلاق التذكرة', 'تم إغلاق الطلب بعد الحل. يمكن إعادة فتحه عند الحاجة بإجراء واضح.'),
    ('تحديث متابعة', 'نعمل على متابعة طلبك حاليًا، وسنرسل لك تحديثًا بمجرد توفر نتيجة جديدة.'),
    ('بانتظار ردك', 'بانتظار تزويدنا بالمعلومة المطلوبة حتى نكمل معالجة الطلب.'),
]


def seed_canned_replies():
    existing_titles = {row.title for row in CannedReply.query.all()}
    now = datetime.utcnow()
    changed = False
    for title, body in DEFAULT_REPLIES:
        if title in existing_titles:
            continue
        db.session.add(CannedReply(title=title, body=body, category='support', created_at=now, updated_at=now))
        changed = True
    if changed:
        db.session.commit()


def case_url(case_type: str, source_id: int, owner_id: int | None = None, lang: str = 'ar') -> str:
    if owner_id:
        anchor = f"#case-mail-{source_id}" if case_type == 'message' else f"#case-ticket-{source_id}"
        return url_for('main.admin_user_profile', user_id=owner_id, lang=lang, tab='support') + anchor
    if case_type == 'message':
        return url_for('main.admin_internal_mail', lang=lang) + f"#thread-{source_id}"
    return url_for('main.admin_tickets', lang=lang) + f"#ticket-{source_id}"


def portal_case_url(case_type: str, source_id: int, lang: str = 'ar') -> str:
    typ = 'mail' if case_type == 'message' else 'ticket'
    anchor = f"#case-mail-{source_id}" if case_type == 'message' else f"#case-ticket-{source_id}"
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
    if not case.user_id:
        case.user_id = _owner_id_for(case_type, source)
    case.assigned_admin_user_id = getattr(source, 'assigned_admin_user_id', None)
    case.subject = getattr(source, 'subject', '') or ''
    case.priority = getattr(source, 'priority', 'normal') or 'normal'
    case.status = getattr(source, 'status', 'open') or 'open'
    case.is_frozen = case.status in CLOSED_STATUSES
    case.last_reply_at = getattr(source, 'last_reply_at', None) or getattr(source, 'updated_at', None) or getattr(source, 'created_at', None)
    if last_reply_by:
        case.last_reply_by = last_reply_by
    case.updated_at = getattr(source, 'updated_at', None) or datetime.utcnow()
    if not case.sla_due_at:
        hours = 6 if case.priority == 'urgent' else (8 if case.priority == 'high' else 24)
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


def sync_existing_cases(commit: bool = False):
    changed = False
    for thread in InternalMailThread.query.all():
        msg = InternalMailMessage.query.filter_by(thread_id=thread.id, is_internal_note=False).order_by(InternalMailMessage.created_at.desc(), InternalMailMessage.id.desc()).first()
        case = upsert_support_case('message', thread, getattr(msg, 'sender_scope', None))
        changed = bool(case) or changed
    for ticket in SupportTicket.query.all():
        msg = SupportTicketMessage.query.filter_by(ticket_id=ticket.id, is_internal_note=False).order_by(SupportTicketMessage.created_at.desc(), SupportTicketMessage.id.desc()).first()
        case = upsert_support_case('ticket', ticket, getattr(msg, 'sender_scope', None))
        changed = bool(case) or changed
    if commit and changed:
        db.session.commit()


def notification_items_for(user, is_admin: bool, limit=5, include_read=False, lang='ar'):
    q = NotificationEvent.query.filter_by(target_user_id=user.id)
    if not include_read:
        q = q.filter_by(is_read=False)
    rows = q.order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc()).limit(limit or 200).all()
    now = datetime.utcnow()
    changed = False
    for ev in rows:
        if not ev.appeared_in_bell:
            ev.appeared_in_bell = True
            ev.delivered_to_user = True
            ev.result = ev.result or 'shown_in_bell'
            changed = True
    if changed:
        db.session.commit()
    return rows


def unread_counts(user):
    q = NotificationEvent.query.filter_by(target_user_id=user.id, is_read=False)
    total = q.count()
    mail = q.filter_by(source_type='message').count()
    ticket = q.filter_by(source_type='ticket').count()
    return total, mail, ticket


def _filtered_query(filter_key='all', actor_id=None):
    q = SupportCase.query
    if filter_key == 'mine' and actor_id:
        q = q.filter_by(assigned_admin_user_id=actor_id)
    elif filter_key == 'unassigned':
        q = q.filter(SupportCase.assigned_admin_user_id.is_(None)).filter(~SupportCase.status.in_(list(CLOSED_STATUSES)))
    elif filter_key == 'urgent':
        q = q.filter(SupportCase.priority.in_(['urgent', 'high'])).filter(~SupportCase.status.in_(list(CLOSED_STATUSES)))
    elif filter_key == 'waiting_user':
        q = q.filter_by(status='waiting_user')
    elif filter_key == 'closed':
        q = q.filter(SupportCase.status.in_(list(CLOSED_STATUSES)))
    elif filter_key == 'unanswered':
        q = q.filter(SupportCase.last_reply_by == 'user').filter(~SupportCase.status.in_(list(CLOSED_STATUSES)))
    elif filter_key != 'all':
        q = q.filter(~SupportCase.status.in_(list(CLOSED_STATUSES)))
    return q


def support_queue_stats(actor_id=None):
    sync_existing_cases(commit=False)
    now = datetime.utcnow()
    active_q = SupportCase.query.filter(~SupportCase.status.in_(list(CLOSED_STATUSES)))
    stats = {
        'all': SupportCase.query.count(),
        'active': active_q.count(),
        'mine': SupportCase.query.filter_by(assigned_admin_user_id=actor_id).filter(~SupportCase.status.in_(list(CLOSED_STATUSES))).count() if actor_id else 0,
        'unassigned': active_q.filter(SupportCase.assigned_admin_user_id.is_(None)).count(),
        'urgent': active_q.filter(SupportCase.priority.in_(['urgent', 'high'])).count(),
        'waiting_user': SupportCase.query.filter_by(status='waiting_user').count(),
        'unanswered': active_q.filter(SupportCase.last_reply_by == 'user').count(),
        'closed': SupportCase.query.filter(SupportCase.status.in_(list(CLOSED_STATUSES))).count(),
        'overdue': active_q.filter(SupportCase.sla_due_at.isnot(None), SupportCase.sla_due_at < now).count(),
    }
    return stats


def _source_for_case(case: SupportCase):
    if not case:
        return None
    if case.case_type == 'message':
        return InternalMailThread.query.get(case.source_id)
    if case.case_type == 'ticket':
        return SupportTicket.query.get(case.source_id)
    return None


def _messages_for_case(case: SupportCase):
    if not case:
        return []
    if case.case_type == 'message':
        return InternalMailMessage.query.filter_by(thread_id=case.source_id).order_by(InternalMailMessage.created_at.asc(), InternalMailMessage.id.asc()).all()
    if case.case_type == 'ticket':
        return SupportTicketMessage.query.filter_by(ticket_id=case.source_id).order_by(SupportTicketMessage.created_at.asc(), SupportTicketMessage.id.asc()).all()
    return []


def _preview(text: str | None, limit: int = 150) -> str:
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + '…'


def build_support_queue(filter_key='all', actor_id=None, lang='ar'):
    sync_existing_cases(commit=True)
    q = _filtered_query(filter_key, actor_id)
    rows = []
    now = datetime.utcnow()
    cases = q.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc()).all()
    for case in cases:
        source = _source_for_case(case)
        messages = _messages_for_case(case)
        last_message = messages[-1] if messages else None
        user = AppUser.query.get(case.user_id) if case.user_id else None
        assignee = AppUser.query.get(case.assigned_admin_user_id) if case.assigned_admin_user_id else None
        tenant = TenantAccount.query.get(case.tenant_id) if case.tenant_id else None
        audits = SupportAuditLog.query.filter_by(case_type=case.case_type, source_id=case.source_id).order_by(SupportAuditLog.created_at.desc(), SupportAuditLog.id.desc()).limit(10).all()
        overdue = bool(case.sla_due_at and case.sla_due_at < now and case.status not in CLOSED_STATUSES)
        age_hours = round(((now - (case.created_at or now)).total_seconds() / 3600), 1)
        updated_at = case.updated_at or case.last_reply_at or case.created_at
        updated_hours = round(((now - (updated_at or now)).total_seconds() / 3600), 1)
        until_sla_hours = None
        if case.sla_due_at and case.status not in CLOSED_STATUSES:
            until_sla_hours = round(((case.sla_due_at - now).total_seconds() / 3600), 1)
        rows.append({
            'case': case,
            'case_key': f'{case.case_type}-{case.source_id}',
            'source': source,
            'messages': messages,
            'last_message': last_message,
            'last_preview': _preview(getattr(last_message, 'body', '') if last_message else ''),
            'last_sender_scope': getattr(last_message, 'sender_scope', None) if last_message else None,
            'user': user,
            'assignee': assignee,
            'tenant': tenant,
            'audits': audits,
            'overdue': overdue,
            'age_hours': age_hours,
            'updated_hours': updated_hours,
            'until_sla_hours': until_sla_hours,
            'url': case_url(case.case_type, case.source_id, case.user_id, lang=lang),
            'portal_url': portal_case_url(case.case_type, case.source_id, lang=lang),
        })
    return rows
