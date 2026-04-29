from __future__ import annotations

# Heavy v10.1 split blueprint. The route logic is intentionally moved out of
# main.py while importing legacy helpers/services from main during the migration
# window. This keeps behavior stable while main.py shrinks safely.
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, jsonify, send_file
from werkzeug.utils import secure_filename

from .main import *  # noqa: F401,F403 - transitional legacy dependency bridge
from . import main as _legacy_main
from ..models import SupportAttachment

for _legacy_name in dir(_legacy_main):
    if _legacy_name.startswith('_') and not _legacy_name.startswith('__'):
        globals()[_legacy_name] = getattr(_legacy_main, _legacy_name)

from ..services.quota_engine import consume_quota_for_user
from ..services.support_ops import build_case_detail, recent_cases_for_user

support_bp = Blueprint('support', __name__)


def _support_assignable_admins():
    """Users who can be assigned to a support case.

    Includes is_admin=True OR any role with the can_manage_support permission.
    Falls back to is_admin filter if the role catalog isn't available.
    """
    candidates = AppUser.query.filter_by(is_active=True).order_by(AppUser.full_name.asc(), AppUser.username.asc()).all()
    out = []
    for u in candidates:
        if getattr(u, 'is_admin', False):
            out.append(u)
            continue
        try:
            from ..services.scope import get_user_permissions
            perms = get_user_permissions(u) or {}
            if perms.get('can_manage_support'):
                out.append(u)
        except Exception:
            continue
    return out


def _wants_json_response():
    """Detect whether the caller wants a JSON response (AJAX) instead of redirect."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    if (request.args.get('format') or request.form.get('format') or '').strip().lower() == 'json':
        return True
    accept = (request.accept_mimetypes.best or '').lower()
    return accept == 'application/json'


def _ajax_action_response(case_type: str, source_id: int, message_text: str, category: str = 'success', filter_key: str = 'all', extra: dict | None = None):
    """Standard JSON envelope for AJAX action submissions."""
    payload = {
        'ok': category != 'danger',
        'category': category,
        'message': message_text,
        'case_type': case_type,
        'source_id': source_id,
        'case_key': f'{case_type}-{source_id}' if case_type and source_id else '',
        'filter_key': filter_key,
    }
    if extra:
        payload.update(extra)
    return jsonify(payload), (200 if payload['ok'] else 400)

SUPPORT_ATTACHMENT_EXTENSIONS = {
    '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.csv', '.doc', '.docx',
    '.xls', '.xlsx', '.zip',
}
SUPPORT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024


def _support_uploaded_files():
    return [item for item in request.files.getlist('attachments') if item and (item.filename or '').strip()]


def _support_has_uploads():
    return bool(_support_uploaded_files())


def _support_attachment_folder(case_type: str, source_id: int) -> Path:
    folder = Path(current_app.instance_path) / 'support_uploads' / case_type / str(source_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save_support_attachments(case_type: str, source_id: int, message_id: int | None, actor_id: int | None):
    saved = []
    for upload in _support_uploaded_files():
        original = (upload.filename or '').strip()
        ext = Path(original).suffix.lower()
        if ext not in SUPPORT_ATTACHMENT_EXTENSIONS:
            flash('نوع الملف غير مدعوم. الملفات المسموحة: PDF, صور, Word, Excel, CSV, ZIP.', 'warning')
            continue
        safe_original = secure_filename(original) or f'attachment{ext}'
        stored = f'{case_type}_{source_id}_{uuid4().hex}{ext}'
        target = _support_attachment_folder(case_type, source_id) / stored
        upload.save(target)
        file_size = target.stat().st_size if target.exists() else 0
        if file_size > SUPPORT_ATTACHMENT_MAX_BYTES:
            try:
                target.unlink()
            except OSError:
                pass
            flash('حجم الملف أكبر من الحد المسموح 10MB.', 'warning')
            continue
        attachment = SupportAttachment(
            case_type=case_type,
            source_id=source_id,
            message_id=message_id,
            uploaded_by_user_id=actor_id,
            filename=stored,
            original_filename=original[:255],
            content_type=(upload.mimetype or '')[:120],
            file_size=file_size,
            storage_path=str(target),
            created_at=datetime.utcnow(),
        )
        db.session.add(attachment)
        saved.append(attachment)
    return saved


def _support_attachments_for(case_type: str, source_id: int):
    return SupportAttachment.query.filter_by(case_type=case_type, source_id=source_id).order_by(SupportAttachment.created_at.desc(), SupportAttachment.id.desc()).all()


def _support_attachment_map(rows):
    result = {}
    for row in rows or []:
        case = row.get('case') if isinstance(row, dict) else None
        if case is not None:
            key = row.get('case_key') or f'{case.case_type}-{case.source_id}'
            result[key] = _support_attachments_for(case.case_type, case.source_id)
            continue
        kind = row.get('kind') if isinstance(row, dict) else None
        source_id = row.get('id') if isinstance(row, dict) else None
        if kind and source_id:
            case_type = 'message' if kind == 'mail' else 'ticket'
            result[f'{kind}-{source_id}'] = _support_attachments_for(case_type, source_id)
    return result


def _support_can_access_source(case_type: str, source) -> bool:
    if not source:
        return False
    if is_system_admin() or has_permission('can_manage_support'):
        return True
    user = _active_user()
    if user is None:
        return False
    tenant, _subscription = ensure_user_tenant_and_subscription(user, activated_by_user_id=getattr(user, 'id', None))
    tenant_id = getattr(tenant, 'id', None)
    if case_type == 'message':
        return bool(getattr(source, 'created_by_user_id', None) == user.id or (tenant_id and getattr(source, 'tenant_id', None) == tenant_id))
    return bool(getattr(source, 'opened_by_user_id', None) == user.id or (tenant_id and getattr(source, 'tenant_id', None) == tenant_id))


def _support_owner_tenant_id(user):
    if not user:
        return None
    if getattr(user, 'tenant_id', None):
        return user.tenant_id
    tenant = TenantAccount.query.filter_by(owner_user_id=user.id).first()
    return getattr(tenant, 'id', None)


def _attachment_error_page(title: str, message: str, status: int = 404):
    """Render a friendly bilingual error page when an attachment can't be served.

    Render's filesystem is ephemeral — files uploaded before a redeploy are
    gone after restart. The default Flask "Not Found" text is unhelpful, so we
    return a small inline HTML page with a useful message and a back link.
    """
    is_en = _lang() == 'en'
    referrer = request.referrer or url_for('main.admin_support_command_center', lang=_lang())
    html = f"""<!doctype html>
<html lang="{_lang()}" dir="{'ltr' if is_en else 'rtl'}">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: 'Cairo', system-ui, sans-serif; background: #f4f7fb; color: #1f2a44; padding: 60px 20px; text-align: center; }}
    .box {{ max-width: 480px; margin: 0 auto; background: #fff; border: 1px solid #e3e9f2; border-radius: 14px; padding: 32px 28px; box-shadow: 0 4px 16px rgba(15,23,42,.06); }}
    h1 {{ margin: 0 0 12px; font-size: 1.4rem; }}
    p  {{ margin: 0 0 20px; color: #5a6885; line-height: 1.7; }}
    a  {{ display: inline-block; padding: 10px 18px; background: #2563eb; color: #fff; text-decoration: none; border-radius: 10px; font-weight: 600; }}
    a:hover {{ background: #1d4ed8; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>{title}</h1>
    <p>{message}</p>
    <a href="{referrer}">{('Back' if is_en else 'العودة')}</a>
  </div>
</body>
</html>"""
    return html, status, {'Content-Type': 'text/html; charset=utf-8'}


@support_bp.route('/support/attachments/<int:attachment_id>')
def support_attachment_download(attachment_id: int):
    is_en = _lang() == 'en'
    attachment = SupportAttachment.query.get(attachment_id)
    if not attachment:
        return _attachment_error_page(
            'Attachment not found' if is_en else 'المرفق غير موجود',
            'This attachment does not exist or has been removed from the database.' if is_en else 'هذا المرفق غير موجود أو تم حذفه من قاعدة البيانات.',
            status=404,
        )
    source = _support_source_for(attachment.case_type, attachment.source_id)
    if not _support_can_access_source(attachment.case_type, source):
        return _attachment_error_page(
            'Access denied' if is_en else 'لا تملك صلاحية الوصول',
            'You are not allowed to view this attachment.' if is_en else 'لا تملك الصلاحية لفتح هذا المرفق.',
            status=403,
        )
    path = Path(attachment.storage_path or '')
    if not path.exists() or not path.is_file():
        # Common on Render — the ephemeral filesystem loses files on redeploy.
        # Show a clearer message instead of a bare 404.
        return _attachment_error_page(
            'File missing on server' if is_en else 'الملف غير موجود على الخادم',
            ('This file was uploaded before the latest deploy and is no longer available. Re-upload it through the conversation.'
             if is_en else
             'تم رفع هذا الملف قبل نشر إصدار جديد ولم يعد متاحًا على الخادم. يمكن إعادة رفعه من داخل المحادثة.'),
            status=410,  # 410 Gone — semantically clearer than 404 for "existed but no longer here"
        )
    return send_file(
        path,
        as_attachment=False,  # Open inline (so images preview in browser); browser still allows download.
        download_name=attachment.original_filename or attachment.filename,
        mimetype=attachment.content_type or None,
    )

@support_bp.route('/admin/mail', methods=['GET', 'POST'])
def admin_internal_mail():
    guard = _admin_guard('can_manage_support')
    if guard:
        return guard
    actor = _active_user()
    if request.method == 'POST':
        action = (request.form.get('action') or 'create').strip()
        if action == 'create':
            subject = (request.form.get('subject') or '').strip()
            body = (request.form.get('body') or '').strip()
            if subject and body:
                thread = InternalMailThread(
                    created_by_user_id=getattr(actor, 'id', None),
                    assigned_admin_user_id=getattr(actor, 'id', None),
                    subject=subject,
                    category=(request.form.get('category') or 'general').strip(),
                    priority=(request.form.get('priority') or 'normal').strip(),
                    status='open',
                    last_reply_at=datetime.utcnow(),
                )
                db.session.add(thread)
                db.session.flush()
                db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', body=body))
                db.session.commit()
                _admin_write_log('mail.create', f'Created internal mail thread #{thread.id}', 'internal_mail_thread', thread.id, {'subject': thread.subject})
                flash('تم إنشاء رسالة داخلية جديدة', 'success')
                return redirect(url_for('main.admin_internal_mail', lang=_lang()))
        elif action == 'reply':
            thread_id = int(request.form.get('thread_id') or 0)
            body = (request.form.get('body') or '').strip()
            thread = InternalMailThread.query.get(thread_id)
            if thread:
                old_status = (thread.status or 'open').strip()
                new_status = (request.form.get('status') or old_status).strip() or old_status
                if old_status == 'closed':
                    flash('هذه الرسالة مغلقة ومجمّدة، لا يمكن إضافة ردود جديدة.', 'warning')
                    return redirect(url_for('main.admin_internal_mail', lang=_lang()))
                old_assignee_id = thread.assigned_admin_user_id
                requested_assignee_id = int(request.form.get('assigned_admin_user_id') or 0) or None
                final_assignee_id = requested_assignee_id or thread.assigned_admin_user_id or getattr(actor, 'id', None)
                thread_messages = InternalMailMessage.query.filter_by(thread_id=thread.id).order_by(InternalMailMessage.created_at.asc(), InternalMailMessage.id.asc()).all()
                if body:
                    db.session.add(InternalMailMessage(
                        thread_id=thread.id,
                        sender_user_id=getattr(actor, 'id', None),
                        sender_scope='admin',
                        is_internal_note=bool(request.form.get('is_internal_note')),
                        body=body,
                    ))
                    thread.last_reply_at = datetime.utcnow()
                if final_assignee_id and old_assignee_id != final_assignee_id and not _support_already_has_assignment_notice(thread_messages):
                    assigned_admin = AppUser.query.get(final_assignee_id)
                    db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=final_assignee_id, sender_scope='admin', is_internal_note=False, body=_assignment_notice_body('mail', assigned_admin)))
                    thread.last_reply_at = datetime.utcnow()
                if new_status in ('closed', 'resolved') and old_status not in ('closed', 'resolved') and not body:
                    db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', is_internal_note=False, body='تم إغلاق المحادثة بعد حل الطلب.'))
                    thread.last_reply_at = datetime.utcnow()
                thread.status = new_status
                thread.assigned_admin_user_id = final_assignee_id
                db.session.commit()
                _admin_write_log('mail.reply', f'Updated mail thread #{thread.id}', 'internal_mail_thread', thread.id, {'status': thread.status})
                flash('تم تحديث الرسالة', 'success')
                return redirect(url_for('main.admin_internal_mail', lang=_lang()))
    rows = []
    threads = InternalMailThread.query.order_by(InternalMailThread.updated_at.desc(), InternalMailThread.id.desc()).all()
    admin_users = AppUser.query.filter_by(is_admin=True).order_by(AppUser.username.asc()).all()
    for thread in threads:
        owner = AppUser.query.get(thread.created_by_user_id) if thread.created_by_user_id else None
        assignee = AppUser.query.get(thread.assigned_admin_user_id) if thread.assigned_admin_user_id else None
        rows.append({'thread': thread, 'owner': owner, 'assignee': assignee, 'messages': InternalMailMessage.query.filter_by(thread_id=thread.id).order_by(InternalMailMessage.created_at.asc()).all()})
    return render_template('admin_internal_mail.html', rows=rows, admin_users=admin_users, ui_lang=_lang())


@support_bp.route('/admin/tickets', methods=['GET', 'POST'])
def admin_tickets():
    guard = _admin_guard('can_manage_support')
    if guard:
        return guard
    actor = _active_user()
    if request.method == 'POST':
        action = (request.form.get('action') or 'create').strip()
        if action == 'create':
            subject = (request.form.get('subject') or '').strip()
            body = (request.form.get('body') or '').strip()
            if subject and body:
                ticket = SupportTicket(
                    tenant_id=int(request.form.get('tenant_id') or 0) or None,
                    opened_by_user_id=getattr(actor, 'id', None),
                    assigned_admin_user_id=getattr(actor, 'id', None),
                    subject=subject,
                    category=(request.form.get('category') or 'support').strip(),
                    priority=(request.form.get('priority') or 'normal').strip(),
                    status='open',
                    related_device_id=int(request.form.get('related_device_id') or 0) or None,
                    last_reply_at=datetime.utcnow(),
                )
                db.session.add(ticket)
                db.session.flush()
                db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', body=body))
                upsert_support_case('ticket', ticket, 'admin')
                if ticket.tenant_id:
                    tenant = TenantAccount.query.get(ticket.tenant_id)
                    notify_user(getattr(tenant, 'owner_user_id', None), source_type='ticket', source_id=ticket.id, tenant_id=ticket.tenant_id, title='تذكرة جديدة من الإدارة', message=subject, direct_url=portal_case_url('ticket', ticket.id, _lang()))
                audit_case('ticket', ticket.id, getattr(actor, 'id', None), 'ticket.admin_create', 'Admin created ticket', commit=False)
                db.session.commit()
                _admin_write_log('ticket.create', f'Created ticket #{ticket.id}', 'support_ticket', ticket.id, {'subject': ticket.subject})
                flash('تم إنشاء التذكرة', 'success')
        elif action == 'reply':
            ticket_id = int(request.form.get('ticket_id') or 0)
            body = (request.form.get('body') or '').strip()
            ticket = SupportTicket.query.get(ticket_id)
            if ticket:
                old_status = (ticket.status or 'open').strip()
                new_status = (request.form.get('status') or old_status).strip() or old_status
                if old_status in ('closed', 'resolved'):
                    flash('هذه التذكرة مغلقة ومجمّدة، لا يمكن إضافة ردود جديدة.', 'warning')
                    return redirect(url_for('main.admin_tickets', lang=_lang()))
                old_assignee_id = ticket.assigned_admin_user_id
                requested_assignee_id = int(request.form.get('assigned_admin_user_id') or 0) or None
                final_assignee_id = requested_assignee_id or ticket.assigned_admin_user_id or getattr(actor, 'id', None)
                ticket_messages = SupportTicketMessage.query.filter_by(ticket_id=ticket.id).order_by(SupportTicketMessage.created_at.asc(), SupportTicketMessage.id.asc()).all()
                if body:
                    db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', body=body, is_internal_note=bool(request.form.get('is_internal_note'))))
                if final_assignee_id and old_assignee_id != final_assignee_id and not _support_already_has_assignment_notice(ticket_messages):
                    assigned_admin = AppUser.query.get(final_assignee_id)
                    db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=final_assignee_id, sender_scope='admin', is_internal_note=False, body=_assignment_notice_body('ticket', assigned_admin)))
                if new_status in ('closed', 'resolved') and old_status not in ('closed', 'resolved') and not body:
                    db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', is_internal_note=False, body='تم إغلاق التذكرة بعد حل المشكلة.'))
                ticket.status = new_status
                ticket.assigned_admin_user_id = final_assignee_id
                ticket.last_reply_at = datetime.utcnow()
                ticket.updated_at = datetime.utcnow()
                upsert_support_case('ticket', ticket, 'admin')
                target_id = ticket.opened_by_user_id
                if not target_id and ticket.tenant_id:
                    target_id = getattr(TenantAccount.query.get(ticket.tenant_id), 'owner_user_id', None)
                notify_user(target_id, source_type='ticket', source_id=ticket.id, tenant_id=ticket.tenant_id, title='تحديث على التذكرة', message=ticket.subject, direct_url=portal_case_url('ticket', ticket.id, _lang()))
                audit_case('ticket', ticket.id, getattr(actor, 'id', None), 'ticket.admin_reply', 'Admin replied to ticket', {'status': ticket.status}, commit=False)
                db.session.commit()
                _admin_write_log('ticket.reply', f'Replied to ticket #{ticket.id}', 'support_ticket', ticket.id, {'status': ticket.status})
                flash('تم تحديث التذكرة', 'success')
    tickets=[]
    for ticket in SupportTicket.query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).all():
        opener = AppUser.query.get(ticket.opened_by_user_id) if ticket.opened_by_user_id else None
        assignee = AppUser.query.get(ticket.assigned_admin_user_id) if ticket.assigned_admin_user_id else None
        tenant = TenantAccount.query.get(ticket.tenant_id) if ticket.tenant_id else None
        device = AppDevice.query.get(ticket.related_device_id) if ticket.related_device_id else None
        messages = SupportTicketMessage.query.filter_by(ticket_id=ticket.id).order_by(SupportTicketMessage.created_at.asc()).all()
        tickets.append({'ticket': ticket, 'opener': opener, 'assignee': assignee, 'tenant': tenant, 'device': device, 'messages': messages})
    return render_template('admin_tickets.html', rows=tickets, tenants=TenantAccount.query.order_by(TenantAccount.display_name.asc()).all(), devices=AppDevice.query.order_by(AppDevice.name.asc()).all(), admin_users=AppUser.query.filter_by(is_admin=True).order_by(AppUser.username.asc()).all(), ui_lang=_lang())


@support_bp.route('/support', methods=['GET', 'POST'])
@support_bp.route('/portal/support', methods=['GET', 'POST'])
def portal_support():
    guard = _energy_portal_guard()
    if guard:
        return guard
    user = _active_user()
    tenant, _subscription = ensure_user_tenant_and_subscription(user, activated_by_user_id=getattr(user, 'id', None)) if user else (None, None)

    if request.method == 'POST' and user is not None:
        action = (request.form.get('action') or '').strip()
        kind = (request.form.get('kind') or request.form.get('type') or 'mail').strip()
        body = (request.form.get('body') or '').strip()
        if action == 'create':
            subject = (request.form.get('subject') or '').strip()
            priority = (request.form.get('priority') or 'normal').strip()
            category = (request.form.get('category') or ('support' if kind == 'ticket' else 'general')).strip()
            if subject and body:
                ok, quota_msg, _quota = consume_quota_for_user(user, 'support_cases_limit', 1, lang=_lang())
                if not ok:
                    flash(quota_msg, 'warning')
                    return redirect(url_for('main.portal_support', lang=_lang(), type='all'))
                if kind == 'ticket':
                    ticket = SupportTicket(tenant_id=getattr(tenant, 'id', None), opened_by_user_id=user.id, subject=subject, category=category, priority=priority, status='open', related_device_id=int(request.form.get('related_device_id') or 0) or getattr(_active_device(), 'id', None), last_reply_at=datetime.utcnow())
                    db.session.add(ticket)
                    db.session.flush()
                    msg = SupportTicketMessage(ticket_id=ticket.id, sender_user_id=user.id, sender_scope='user', body=body)
                    db.session.add(msg)
                    db.session.flush()
                    attachments = _save_support_attachments('ticket', ticket.id, msg.id, user.id)
                    upsert_support_case('ticket', ticket, 'user')
                    for admin in AppUser.query.filter_by(is_admin=True).all():
                        notify_user(admin.id, source_type='ticket', source_id=ticket.id, tenant_id=getattr(tenant, 'id', None), title='تذكرة جديدة', message=subject, direct_url=case_url('ticket', ticket.id, user.id, _lang()))
                    audit_case('ticket', ticket.id, user.id, 'ticket.create', 'Subscriber opened a ticket', {'attachments': len(attachments)}, commit=False)
                    db.session.commit()
                    flash('تم فتح التذكرة بنجاح' if _lang() != 'en' else 'Ticket opened successfully', 'success')
                    return redirect(url_for('main.portal_support', lang=_lang(), type='ticket') + f'#case-ticket-{ticket.id}')
                thread = InternalMailThread(tenant_id=getattr(tenant, 'id', None), created_by_user_id=user.id, subject=subject, category=category, priority=priority, status='open', last_reply_at=datetime.utcnow())
                db.session.add(thread)
                db.session.flush()
                msg = InternalMailMessage(thread_id=thread.id, sender_user_id=user.id, sender_scope='user', body=body)
                db.session.add(msg)
                db.session.flush()
                attachments = _save_support_attachments('message', thread.id, msg.id, user.id)
                upsert_support_case('message', thread, 'user')
                for admin in AppUser.query.filter_by(is_admin=True).all():
                    notify_user(admin.id, source_type='message', source_id=thread.id, tenant_id=getattr(tenant, 'id', None), title='رسالة دعم جديدة', message=subject, direct_url=case_url('message', thread.id, user.id, _lang()))
                audit_case('message', thread.id, user.id, 'message.create', 'Subscriber opened a support message', {'attachments': len(attachments)}, commit=False)
                db.session.commit()
                flash('تم إرسال الرسالة للإدارة' if _lang() != 'en' else 'Message sent to management', 'success')
                return redirect(url_for('main.portal_support', lang=_lang(), type='mail') + f'#case-mail-{thread.id}')
        elif action == 'reply':
            if kind == 'ticket':
                ticket = SupportTicket.query.get(int(request.form.get('ticket_id') or 0))
                belongs = bool(ticket and (ticket.opened_by_user_id == user.id or (getattr(tenant, 'id', None) and ticket.tenant_id == tenant.id)))
                if ticket and belongs and body:
                    if (ticket.status or '').strip() == 'closed':
                        flash('هذه التذكرة مغلقة ولا يمكن إضافة ردود جديدة.' if _lang() != 'en' else 'This ticket is closed and cannot receive new replies.', 'warning')
                        return redirect(url_for('main.portal_support', lang=_lang(), type='ticket') + f'#case-ticket-{ticket.id}')
                    if not ticket.opened_by_user_id:
                        ticket.opened_by_user_id = user.id
                    if not ticket.tenant_id and tenant:
                        ticket.tenant_id = tenant.id
                    msg = SupportTicketMessage(ticket_id=ticket.id, sender_user_id=user.id, sender_scope='user', body=body)
                    db.session.add(msg)
                    db.session.flush()
                    attachments = _save_support_attachments('ticket', ticket.id, msg.id, user.id)
                    ticket.last_reply_at = datetime.utcnow()
                    ticket.updated_at = datetime.utcnow()
                    upsert_support_case('ticket', ticket, 'user')
                    targets = [ticket.assigned_admin_user_id] if ticket.assigned_admin_user_id else [a.id for a in AppUser.query.filter_by(is_admin=True).all()]
                    for target_id in set([t for t in targets if t]):
                        notify_user(target_id, source_type='ticket', source_id=ticket.id, tenant_id=ticket.tenant_id, title='رد جديد من المشترك', message=ticket.subject, direct_url=case_url('ticket', ticket.id, user.id, _lang()))
                    audit_case('ticket', ticket.id, user.id, 'ticket.user_reply', 'Subscriber replied to ticket', {'attachments': len(attachments)}, commit=False)
                    db.session.commit()
                    flash('تمت إضافة الرد على التذكرة' if _lang() != 'en' else 'Ticket reply added', 'success')
                    return redirect(url_for('main.portal_support', lang=_lang(), type='ticket') + f'#case-ticket-{ticket.id}')
            else:
                thread = InternalMailThread.query.get(int(request.form.get('thread_id') or 0))
                belongs = bool(thread and (thread.created_by_user_id == user.id or (getattr(tenant, 'id', None) and thread.tenant_id == tenant.id)))
                if thread and belongs and body:
                    if (thread.status or '').strip() == 'closed':
                        flash('هذه المحادثة مغلقة ولا يمكن إضافة ردود جديدة.' if _lang() != 'en' else 'This conversation is closed and cannot receive new replies.', 'warning')
                        return redirect(url_for('main.portal_support', lang=_lang(), type='mail') + f'#case-mail-{thread.id}')
                    if not thread.created_by_user_id:
                        thread.created_by_user_id = user.id
                    if not thread.tenant_id and tenant:
                        thread.tenant_id = tenant.id
                    msg = InternalMailMessage(thread_id=thread.id, sender_user_id=user.id, sender_scope='user', body=body)
                    db.session.add(msg)
                    db.session.flush()
                    attachments = _save_support_attachments('message', thread.id, msg.id, user.id)
                    thread.last_reply_at = datetime.utcnow()
                    thread.updated_at = datetime.utcnow()
                    upsert_support_case('message', thread, 'user')
                    targets = [thread.assigned_admin_user_id] if thread.assigned_admin_user_id else [a.id for a in AppUser.query.filter_by(is_admin=True).all()]
                    for target_id in set([t for t in targets if t]):
                        notify_user(target_id, source_type='message', source_id=thread.id, tenant_id=thread.tenant_id, title='رد جديد من المشترك', message=thread.subject, direct_url=case_url('message', thread.id, user.id, _lang()))
                    audit_case('message', thread.id, user.id, 'message.user_reply', 'Subscriber replied to message', {'attachments': len(attachments)}, commit=False)
                    db.session.commit()
                    flash('تمت إضافة الرد' if _lang() != 'en' else 'Reply added', 'success')
                    return redirect(url_for('main.portal_support', lang=_lang(), type='mail') + f'#case-mail-{thread.id}')
            flash('تعذر حفظ الرد، تأكد من أن العنصر تابع لحسابك.' if _lang() != 'en' else 'Could not save reply for this account.', 'danger')

        elif action in ('close', 'reopen'):
            case_type = 'ticket' if kind == 'ticket' else 'message'
            source = SupportTicket.query.get(int(request.form.get('ticket_id') or 0)) if kind == 'ticket' else InternalMailThread.query.get(int(request.form.get('thread_id') or 0))
            tenant_id = getattr(tenant, 'id', None)
            belongs = bool(source and (
                (kind == 'ticket' and (getattr(source, 'opened_by_user_id', None) == user.id or (tenant_id and getattr(source, 'tenant_id', None) == tenant_id))) or
                (kind != 'ticket' and (getattr(source, 'created_by_user_id', None) == user.id or (tenant_id and getattr(source, 'tenant_id', None) == tenant_id)))
            ))
            if source and belongs:
                source.status = 'open' if action == 'reopen' else 'closed'
                source.updated_at = datetime.utcnow()
                body_text = 'طلب المشترك إعادة فتح المحادثة للمتابعة.' if action == 'reopen' else 'قام المشترك بإغلاق الطلب من مركز الدعم.'
                if kind == 'ticket':
                    msg = SupportTicketMessage(ticket_id=source.id, sender_user_id=user.id, sender_scope='user', body=body_text)
                else:
                    msg = InternalMailMessage(thread_id=source.id, sender_user_id=user.id, sender_scope='user', body=body_text)
                db.session.add(msg)
                source.last_reply_at = datetime.utcnow()
                upsert_support_case(case_type, source, 'user')
                targets = [getattr(source, 'assigned_admin_user_id', None)] if getattr(source, 'assigned_admin_user_id', None) else [a.id for a in AppUser.query.filter_by(is_admin=True).all()]
                title = getattr(source, 'subject', '') or 'طلب دعم'
                for target_id in set([t for t in targets if t]):
                    notify_user(target_id, source_type=case_type, source_id=source.id, tenant_id=getattr(source, 'tenant_id', None), title=('تمت إعادة فتح طلب' if action == 'reopen' else 'تم إغلاق طلب'), message=title, direct_url=case_url(case_type, source.id, user.id, _lang()))
                audit_case(case_type, source.id, user.id, f'{case_type}.user_{action}', f'Subscriber {action} support request', {'status': source.status}, commit=False)
                db.session.commit()
                flash(('تمت إعادة فتح الطلب.' if action == 'reopen' else 'تم إغلاق الطلب.') if _lang() != 'en' else ('Request reopened.' if action == 'reopen' else 'Request closed.'), 'success')
                return redirect(url_for('main.portal_support', lang=_lang(), type=kind) + f'#case-{kind}-{source.id}')
            flash('تعذر تنفيذ الإجراء لهذا الحساب.' if _lang() != 'en' else 'Could not apply this action for this account.', 'danger')

    rows = _portal_support_rows(user)
    selected_type = (request.args.get('type') or 'all').strip()
    return render_template('portal_support.html', rows=rows, devices=_device_collection(), selected_type=selected_type, attachment_map=_support_attachment_map(rows), ui_lang=_lang(), format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']))


@support_bp.route('/portal/messages', methods=['GET', 'POST'])
def portal_messages():
    return redirect(url_for('main.portal_support', lang=_lang(), type='mail'))


@support_bp.route('/portal/tickets', methods=['GET', 'POST'])
def portal_tickets():
    return redirect(url_for('main.portal_support', lang=_lang(), type='ticket'))


@support_bp.route('/admin/support-command-center')
def admin_support_command_center():
    guard = _admin_guard('can_manage_support')
    if guard:
        return guard
    actor = _active_user()
    filter_key = (request.args.get('filter') or 'all').strip()
    # The list view doesn't need every message body — it only renders the
    # inbox cards. Messages for the selected case are loaded separately.
    rows = build_support_queue(filter_key=filter_key, actor_id=getattr(actor, 'id', None), lang=_lang(), include_messages=False)
    stats = support_queue_stats(actor_id=getattr(actor, 'id', None))
    canned_replies = CannedReply.query.filter_by(is_active=True).order_by(CannedReply.title.asc()).all()
    canned_rows = [{'item': r, 'suggested_status': _suggest_status_for_canned(r.title, r.body)} for r in canned_replies]
    admin_users = _support_assignable_admins()
    subscriber_users = [u for u in AppUser.query.order_by(AppUser.full_name.asc(), AppUser.username.asc()).all() if not _is_admin_like_user(u)]
    is_en = _lang() == 'en'
    labels = _support_label_maps(is_en)
    selected_key = (request.args.get('case') or '').strip()
    available_keys = {row.get('case_key') for row in rows}
    if not selected_key or selected_key not in available_keys:
        selected_key = rows[0].get('case_key') if rows else ''
    selected_detail = None
    selected_attachments = []
    selected_recent = []
    if selected_key:
        case_type, _, source_id_str = selected_key.partition('-')
        try:
            source_id = int(source_id_str)
        except ValueError:
            source_id = 0
        if case_type and source_id:
            selected_detail = build_case_detail(case_type, source_id, lang=_lang())
            if selected_detail:
                selected_attachments = _support_attachments_for(case_type, source_id)
                user_id = getattr(selected_detail.get('user'), 'id', None)
                if user_id:
                    selected_recent = recent_cases_for_user(user_id, exclude_case_key=selected_key, limit=5)
    filter_defs = [
        ('all', 'كل الدعم', 'All support', stats.get('all', 0)),
        ('mine', 'المخصص لي', 'Assigned to me', stats.get('mine', 0)),
        ('unassigned', 'بدون مدير', 'Unassigned', stats.get('unassigned', 0)),
        ('urgent', 'عاجل', 'Urgent', stats.get('urgent', 0)),
        ('overdue', 'متأخر', 'Overdue', stats.get('overdue', 0)),
        ('waiting_user', 'بانتظار المستخدم', 'Waiting user', stats.get('waiting_user', 0)),
        ('unanswered', 'لم يتم الرد عليه', 'Unanswered', stats.get('unanswered', 0)),
        ('closed', 'مغلق', 'Closed', stats.get('closed', 0)),
    ]
    return render_template(
        'admin_support_command_center.html',
        rows=rows,
        stats=stats,
        filter_defs=filter_defs,
        filter_key=filter_key,
        selected_key=selected_key,
        selected_detail=selected_detail,
        selected_attachments=selected_attachments,
        selected_recent=selected_recent,
        canned_replies=canned_replies,
        canned_rows=canned_rows,
        admin_users=admin_users,
        subscriber_users=subscriber_users,
        labels=labels,
        status_options=['open', 'assigned', 'in_progress', 'waiting_user', 'resolved', 'closed'],
        priority_options=['low', 'normal', 'high', 'urgent'],
        ui_lang=_lang(),
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )


@support_bp.route('/admin/support-command-center/list.json')
def admin_support_command_list_json():
    """Return inbox cards + KPI stats as JSON for AJAX filter switching."""
    guard = _admin_guard('can_manage_support')
    if guard:
        # Guard returns a redirect; convert to a JSON 403 for AJAX.
        return jsonify({'ok': False, 'message': 'Access denied'}), 403
    actor = _active_user()
    filter_key = (request.args.get('filter') or 'all').strip()
    is_en = _lang() == 'en'
    labels = _support_label_maps(is_en)
    rows = build_support_queue(filter_key=filter_key, actor_id=getattr(actor, 'id', None), lang=_lang(), include_messages=False)
    stats = support_queue_stats(actor_id=getattr(actor, 'id', None))
    fmt = lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']) if dt else ''
    items = []
    for row in rows:
        case = row['case']
        owner = row.get('user')
        owner_label = (getattr(owner, 'full_name', None) or getattr(owner, 'username', None)) if owner else (getattr(row.get('tenant'), 'display_name', None) if row.get('tenant') else '')
        items.append({
            'case_key': row['case_key'],
            'case_type': case.case_type,
            'source_id': case.source_id,
            'subject': case.subject or '',
            'owner_label': owner_label or '',
            'owner_initial': (owner_label or '?')[:1].upper(),
            'status': case.status,
            'status_label': labels['status'].get(case.status, case.status),
            'priority': case.priority,
            'priority_label': labels['priority'].get(case.priority, case.priority),
            'updated_at': fmt(case.updated_at or case.last_reply_at or case.created_at),
            'preview': row.get('last_preview') or '',
            'overdue': bool(row.get('overdue')),
            'until_sla_hours': row.get('until_sla_hours'),
            'reference': f'#SUP-{(case.created_at or datetime.utcnow()).strftime("%Y-%m%d")}-{case.source_id:05d}' if case.created_at else f'#SUP-{case.source_id:05d}',
        })
    return jsonify({
        'ok': True,
        'filter_key': filter_key,
        'stats': stats,
        'items': items,
        'total': len(items),
    })


@support_bp.route('/admin/support-command-center/case/<case_type>-<int:source_id>.json')
def admin_support_command_case_json(case_type: str, source_id: int):
    """Return a single case (details + messages + attachments + recent) as JSON."""
    guard = _admin_guard('can_manage_support')
    if guard:
        return jsonify({'ok': False, 'message': 'Access denied'}), 403
    if case_type not in {'message', 'ticket'}:
        return jsonify({'ok': False, 'message': 'Invalid case type'}), 400
    detail = build_case_detail(case_type, source_id, lang=_lang())
    if not detail:
        return jsonify({'ok': False, 'message': 'Case not found'}), 404
    is_en = _lang() == 'en'
    labels = _support_label_maps(is_en)
    fmt = lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']) if dt else ''
    case = detail['case']
    user = detail.get('user')
    tenant = detail.get('tenant')
    assignee = detail.get('assignee')
    owner_label = (getattr(user, 'full_name', None) or getattr(user, 'username', None)) if user else (getattr(tenant, 'display_name', None) if tenant else '')
    attachments = _support_attachments_for(case_type, source_id)
    recent = recent_cases_for_user(getattr(user, 'id', None), exclude_case_key=detail['case_key'], limit=5)
    return jsonify({
        'ok': True,
        'case_key': detail['case_key'],
        'case_type': case_type,
        'source_id': source_id,
        'subject': case.subject or '',
        'status': case.status,
        'status_label': labels['status'].get(case.status, case.status),
        'priority': case.priority,
        'priority_label': labels['priority'].get(case.priority, case.priority),
        'category': case.case_type,
        'created_at': fmt(case.created_at),
        'updated_at': fmt(case.updated_at),
        'until_sla_hours': detail.get('until_sla_hours'),
        'overdue': detail.get('overdue', False),
        'owner': {
            'id': getattr(user, 'id', None),
            'name': owner_label,
            'email': getattr(user, 'email', None) or '',
            'phone': ((getattr(user, 'phone_country_code', '') or '') + ' ' + (getattr(user, 'phone_number', '') or '')).strip(),
            'created_at': fmt(getattr(user, 'created_at', None)) if user else '',
        },
        'tenant': {
            'id': getattr(tenant, 'id', None),
            'name': getattr(tenant, 'display_name', '') or '',
        },
        'assignee': {
            'id': getattr(assignee, 'id', None),
            'name': (getattr(assignee, 'full_name', None) or getattr(assignee, 'username', None)) if assignee else '',
        },
        'messages': [{
            'id': m.id,
            'sender_scope': getattr(m, 'sender_scope', '') or '',
            'is_internal_note': bool(getattr(m, 'is_internal_note', False)),
            'body': getattr(m, 'body', '') or '',
            'created_at': fmt(getattr(m, 'created_at', None)),
        } for m in detail.get('messages', [])],
        'attachments': [{
            'id': a.id,
            'name': a.original_filename or a.filename,
            'size_kb': round((a.file_size or 0) / 1024, 1),
            'download_url': url_for('support.support_attachment_download', attachment_id=a.id),
        } for a in attachments],
        'recent': [{
            'case_key': r['case_key'],
            'subject': r['case'].subject or '',
            'status': r['case'].status,
            'reference': f'#SUP-{r["case"].source_id:05d}',
        } for r in recent],
    })


@support_bp.route('/admin/support-command-center/action', methods=['POST'])
def admin_support_command_action():
    guard = _admin_guard('can_manage_support')
    if guard:
        return guard
    actor = _active_user()
    actor_id = getattr(actor, 'id', None)
    case_type = (request.form.get('case_type') or '').strip()
    source_id = int(request.form.get('source_id') or 0)
    action = (request.form.get('case_action') or '').strip()
    filter_key = (request.args.get('filter') or request.form.get('filter_key') or 'all').strip()
    case_key = f'{case_type}-{source_id}' if case_type and source_id else ''
    wants_json = _wants_json_response()

    def _finish(message_text: str, category: str = 'success', case_type_override: str | None = None, source_id_override: int | None = None, extra: dict | None = None):
        """Either flash + redirect, or return JSON, depending on the caller."""
        ct = case_type_override if case_type_override is not None else case_type
        sid = source_id_override if source_id_override is not None else source_id
        ck = f'{ct}-{sid}' if ct and sid else ''
        if wants_json:
            return _ajax_action_response(ct, sid, message_text, category=category, filter_key=filter_key, extra=extra)
        flash(message_text, category)
        if ck:
            return redirect(url_for('main.admin_support_command_center', lang=_lang(), filter=filter_key, case=ck) + f'#case-{ck}')
        return redirect(url_for('main.admin_support_command_center', lang=_lang(), filter=filter_key))

    if action == 'create_case':
        kind = (request.form.get('kind') or 'message').strip()
        target_user = AppUser.query.get(int(request.form.get('target_user_id') or 0))
        subject = (request.form.get('subject') or '').strip()
        body = (request.form.get('body') or '').strip()
        priority = (request.form.get('priority') or 'normal').strip()
        category = (request.form.get('category') or 'support').strip()
        if not target_user or not subject or not body:
            return _finish('اختر المشترك واكتب العنوان والرسالة قبل الإنشاء.', 'warning')
        tenant_id = _support_owner_tenant_id(target_user)
        if kind == 'ticket':
            source = SupportTicket(
                tenant_id=tenant_id,
                opened_by_user_id=target_user.id,
                assigned_admin_user_id=actor_id,
                subject=subject,
                category=category,
                priority=priority,
                status='open',
                last_reply_at=datetime.utcnow(),
            )
            db.session.add(source)
            db.session.flush()
            msg = SupportTicketMessage(ticket_id=source.id, sender_user_id=actor_id, sender_scope='admin', body=body)
            db.session.add(msg)
            db.session.flush()
            attachments = _save_support_attachments('ticket', source.id, msg.id, actor_id)
            case_type = 'ticket'
        else:
            source = InternalMailThread(
                tenant_id=tenant_id,
                created_by_user_id=target_user.id,
                assigned_admin_user_id=actor_id,
                subject=subject,
                category=category,
                priority=priority,
                status='open',
                last_reply_at=datetime.utcnow(),
            )
            db.session.add(source)
            db.session.flush()
            msg = InternalMailMessage(thread_id=source.id, sender_user_id=actor_id, sender_scope='admin', body=body)
            db.session.add(msg)
            db.session.flush()
            attachments = _save_support_attachments('message', source.id, msg.id, actor_id)
            case_type = 'message'
        upsert_support_case(case_type, source, 'admin')
        notify_user(target_user.id, source_type=case_type, source_id=source.id, tenant_id=tenant_id, title='طلب دعم جديد من الإدارة', message=subject, direct_url=portal_case_url(case_type, source.id, _lang()))
        audit_case(case_type, source.id, actor_id, 'case.admin_create', 'Admin created support case from command center', {'target_user_id': target_user.id, 'attachments': len(attachments)}, commit=False)
        db.session.commit()
        return _finish('تم إنشاء طلب الدعم وإشعار المشترك.', 'success', case_type_override=case_type, source_id_override=source.id)
    source = _support_source_for(case_type, source_id)
    if not source:
        return _finish('تعذر العثور على عنصر الدعم.', 'danger')

    old_status = (getattr(source, 'status', None) or 'open').strip()
    if old_status in ('closed', 'resolved') and action not in ('reopen',):
        return _finish('هذا الطلب مغلق ومجمّد. استخدم إعادة فتح أولًا.', 'warning')

    owner_id = _support_owner_id_for_source(case_type, source)
    title = getattr(source, 'subject', '') or 'طلب دعم'
    audit_action = 'case.update'
    notification_title = 'تحديث على طلب الدعم'
    should_notify = True

    if action in ('send_reply', 'save_update', 'save_draft'):
        body = (request.form.get('body') or '').strip()
        has_uploads = _support_has_uploads()
        if has_uploads and not body:
            body = 'تم إرفاق ملف جديد.'
        is_internal_note = bool(request.form.get('is_internal_note')) or action == 'save_draft'
        requested_status = (request.form.get('status') or old_status or 'open').strip()
        requested_priority = (request.form.get('priority') or getattr(source, 'priority', None) or 'normal').strip()
        requested_assignee_id = int(request.form.get('assigned_admin_user_id') or 0) or getattr(source, 'assigned_admin_user_id', None) or None
        changed = False

        if requested_status and requested_status != old_status:
            source.status = requested_status
            changed = True
        if requested_priority and requested_priority != getattr(source, 'priority', None):
            source.priority = requested_priority
            changed = True
        if requested_assignee_id != getattr(source, 'assigned_admin_user_id', None):
            source.assigned_admin_user_id = requested_assignee_id
            changed = True
        if action == 'send_reply' and request.form.get('close_after_send') and requested_status not in ('closed', 'resolved'):
            source.status = 'closed'
            changed = True

        msg = None
        attachments = []
        if body:
            if action == 'save_draft' and not body.startswith('[مسودة]'):
                body = f'[مسودة] {body}'
            msg = _support_add_admin_message(case_type, source, body, actor_id, is_internal_note=is_internal_note)
            db.session.flush()
            attachments = _save_support_attachments(case_type, source.id, getattr(msg, 'id', None), actor_id)
            changed = True

        if not changed:
            return _finish('لا يوجد رد أو تغيير جديد للحفظ.', 'warning')

        source.updated_at = datetime.utcnow()
        last_reply_by = None if is_internal_note else ('admin' if msg else None)
        upsert_support_case(case_type, source, last_reply_by)
        audit_action = 'case.draft' if action == 'save_draft' else ('case.internal_note' if is_internal_note and msg else 'case.reply')
        audit_case(case_type, source_id, actor_id, audit_action, f'{audit_action} for {case_type} #{source_id}', {'status': getattr(source, 'status', None), 'priority': getattr(source, 'priority', None), 'internal_note': is_internal_note, 'attachments': len(attachments)}, commit=False)
        if msg and not is_internal_note:
            notification_title = 'رد جديد من الدعم'
            notify_user(owner_id, source_type=case_type, source_id=source_id, tenant_id=getattr(source, 'tenant_id', None), title=notification_title, message=title, direct_url=portal_case_url(case_type, source_id, _lang()))
        elif changed and not is_internal_note:
            notify_user(owner_id, source_type=case_type, source_id=source_id, tenant_id=getattr(source, 'tenant_id', None), title='تم تحديث حالة طلب الدعم', message=title, direct_url=portal_case_url(case_type, source_id, _lang()))
        db.session.commit()
        return _finish('تم حفظ الرد وتحديث المحادثة.', 'success')

    # Each branch records the user-facing message + category in result_message
    # so the same text is shown both via flash (HTML flow) and via JSON toast
    # (AJAX flow). Avoids the previous behaviour where AJAX showed a generic
    # 'done' message and ignored the per-action wording.
    result_message = 'تم تنفيذ الإجراء.'
    result_category = 'success'

    if action == 'start_processing':
        source.assigned_admin_user_id = actor_id
        source.status = 'in_progress'
        _support_add_public_message(case_type, source, 'بدأ فريق الدعم معالجة طلبك الآن.', actor_id)
        audit_action = 'case.start_processing'
        notification_title = 'بدأت معالجة طلب الدعم'
        result_message = 'تم بدء المعالجة وتحديث حالة الطلب.'
    elif action == 'assign_me':
        assigned_admin = actor
        source.assigned_admin_user_id = actor_id
        if old_status in ('new', 'open', 'pending'):
            source.status = 'assigned'
        existing_messages = _support_messages_for_source(case_type, source)
        if not _support_has_assignment_notice_for(existing_messages, assigned_admin):
            _support_add_public_message(case_type, source, _assignment_notice_body('ticket' if case_type == 'ticket' else 'mail', assigned_admin), actor_id)
        audit_action = 'case.assign_me'
        notification_title = 'تم اعتماد المدير المسؤول'
        result_message = 'تم اعتمادك كمدير مسؤول وإشعار المشترك.'
    elif action == 'assign_admin':
        assigned_id = int(request.form.get('assigned_admin_user_id') or 0)
        assigned_admin = AppUser.query.get(assigned_id) if assigned_id else actor
        # Allow any user with can_manage_support, not just is_admin=True roles.
        valid_assignees = {u.id for u in _support_assignable_admins()}
        if not assigned_admin or assigned_admin.id not in valid_assignees:
            return _finish('اختر عضو دعم صالح للتعيين.', 'warning')
        source.assigned_admin_user_id = assigned_admin.id
        if old_status in ('new', 'open', 'pending'):
            source.status = 'assigned'
        existing_messages = _support_messages_for_source(case_type, source)
        if not _support_has_assignment_notice_for(existing_messages, assigned_admin):
            _support_add_public_message(case_type, source, _assignment_notice_body('ticket' if case_type == 'ticket' else 'mail', assigned_admin), actor_id)
        audit_action = 'case.assign_admin'
        notification_title = 'تم تعيين مسؤول لطلب الدعم'
        result_message = 'تم تعيين المسؤول وتسجيل الحركة.'
    elif action == 'mark_urgent':
        source.priority = 'urgent'
        if old_status in ('new', 'open', 'pending'):
            source.status = 'assigned'
        audit_action = 'case.mark_urgent'
        notification_title = 'تم رفع أولوية طلب الدعم'
        result_message = 'تم وضع علامة عاجل على الطلب.'
    elif action == 'tag_followup':
        _support_add_admin_message(case_type, source, 'ملاحظة داخلية: تم وضع علامة متابعة على هذا الطلب.', actor_id, is_internal_note=True)
        audit_action = 'case.tag_followup'
        notification_title = 'تم تحديث طلب الدعم'
        should_notify = False
        result_message = 'تم تسجيل علامة متابعة داخلية.'
    elif action == 'merge_note':
        _support_add_admin_message(case_type, source, 'ملاحظة داخلية: تم تسجيل هذا الطلب للمراجعة قبل الدمج مع طلب مشابه.', actor_id, is_internal_note=True)
        audit_action = 'case.merge_review'
        notification_title = 'تم تحديث طلب الدعم'
        should_notify = False
        result_message = 'تم تسجيل طلب الدمج للمراجعة داخل السجل.'
    elif action == 'waiting_user':
        if old_status != 'waiting_user':
            source.status = 'waiting_user'
            _support_add_public_message(case_type, source, 'نحتاج منك معلومات إضافية حتى نكمل معالجة الطلب.', actor_id)
            result_message = 'تم نقل الطلب إلى بانتظار المستخدم.'
        else:
            result_message = 'الطلب موجود مسبقًا في حالة بانتظار المستخدم.'
            result_category = 'info'
        audit_action = 'case.waiting_user'
        notification_title = 'نحتاج معلومات إضافية'
    elif action == 'close':
        source.status = 'closed'
        _support_add_public_message(case_type, source, 'تم إغلاق الطلب بعد الحل. يمكنك طلب إعادة فتحه عند الحاجة.', actor_id)
        audit_action = 'case.close'
        notification_title = 'تم إغلاق طلب الدعم'
        result_message = 'تم إغلاق الطلب وتجميده.'
    elif action == 'reopen':
        source.status = 'open'
        _support_add_public_message(case_type, source, 'تمت إعادة فتح الطلب وسيتم متابعته من جديد.', actor_id)
        audit_action = 'case.reopen'
        notification_title = 'تمت إعادة فتح طلب الدعم'
        result_message = 'تمت إعادة فتح الطلب.'
    else:
        return _finish('الإجراء غير معروف.', 'warning')

    source.updated_at = datetime.utcnow()
    if not getattr(source, 'last_reply_at', None):
        source.last_reply_at = datetime.utcnow()
    upsert_support_case(case_type, source, 'admin')
    audit_case(case_type, source_id, actor_id, audit_action, f'{audit_action} for {case_type} #{source_id}', {'status': getattr(source, 'status', None)}, commit=False)
    if should_notify:
        notify_user(owner_id, source_type=case_type, source_id=source_id, tenant_id=getattr(source, 'tenant_id', None), title=notification_title, message=title, direct_url=portal_case_url(case_type, source_id, _lang()))
    db.session.commit()
    return _finish(result_message, result_category, extra={
        'new_status': getattr(source, 'status', None),
        'new_priority': getattr(source, 'priority', None),
        'new_assignee_id': getattr(source, 'assigned_admin_user_id', None),
    })


@support_bp.route('/admin/support-command-center/reopen', methods=['POST'])
def admin_support_reopen():
    guard = _admin_guard('can_manage_support')
    if guard:
        return guard
    case_type = (request.form.get('case_type') or '').strip()
    source_id = int(request.form.get('source_id') or 0)
    actor = _active_user()
    source = _support_source_for(case_type, source_id)
    if not source:
        flash('تعذر العثور على عنصر الدعم.', 'danger')
        return redirect(url_for('main.admin_support_command_center', lang=_lang()))
    source.status = 'open'
    source.updated_at = datetime.utcnow()
    _support_add_public_message(case_type, source, 'تمت إعادة فتح الطلب وسيتم متابعته من جديد.', getattr(actor, 'id', None))
    upsert_support_case(case_type, source, 'admin')
    audit_case(case_type, source_id, getattr(actor, 'id', None), 'case.reopen', 'Reopened closed support case', commit=False)
    owner_id = _support_owner_id_for_source(case_type, source)
    notify_user(owner_id, source_type=case_type, source_id=source_id, tenant_id=getattr(source, 'tenant_id', None), title='تمت إعادة فتح طلب الدعم', message=getattr(source, 'subject', ''), direct_url=portal_case_url(case_type, source_id, _lang()))
    db.session.commit()
    flash('تمت إعادة فتح الطلب وتسجيل الحركة.', 'success')
    return redirect(url_for('main.admin_support_command_center', lang=_lang()))
