from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, request, send_file, url_for
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import AppUser, CannedReply, InternalMailMessage, InternalMailThread, SupportAttachment, SupportTicket, SupportTicketMessage, TenantAccount
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.support_ops import audit_case, notify_user, upsert_support_case
from ..services.subscriptions import ensure_user_tenant_and_subscription
from ..services.quota_engine import consume_quota_for_user

mobile_support_api_bp = Blueprint('mobile_support_api', __name__, url_prefix='/api/v1/support')

# v71: ── Mobile attachment upload constants ─────────────────────────
#
# Mirror of `SUPPORT_ATTACHMENT_EXTENSIONS` and
# `SUPPORT_ATTACHMENT_MAX_BYTES` in `support.py`. We deliberately
# duplicate the values here instead of importing from `support.py`
# so this module stays free of the web blueprint's eager flash/
# session dependencies — the audit's rule was to leave `support.py`
# untouched.
_MOBILE_SUPPORT_ATTACHMENT_EXTENSIONS = frozenset({
    '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.csv', '.doc',
    '.docx', '.xls', '.xlsx', '.zip',
})
_MOBILE_SUPPORT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


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


# v68: ── Support attachments helpers ────────────────────────────────
#
# Read-only mobile contract for the existing `SupportAttachment` rows
# (persisted by the web `_save_support_attachments` flow in
# `support.py`). We never write attachments here, never re-shape the
# stored file, never expose `storage_path` to the client — the URL is
# the only handle the mobile layer gets.
#
# Per-message grouping is critical: each attachment row carries a
# `message_id` pointer back to the message it was uploaded with, so
# we bulk-load all attachments for a case in one query and group by
# message_id in Python (avoids N+1 inside `_messages_for`).

# `kind` arriving from the route layer is `'message'` / `'mail'` /
# `'ticket'`. The SupportAttachment table stores `'message'` /
# `'ticket'` only, so we normalize. `'mail'` is the legacy URL alias
# used by some mobile clients (matches `_case_for_user`'s behavior).
def _attachment_case_type_for(kind: str) -> str:
    return 'ticket' if kind == 'ticket' else 'message'


def _mobile_attachment_payload(attachment, *, kind: str, case_id: int) -> dict:
    """Shape one SupportAttachment row for the mobile contract.

    `download_url` is hardcoded to the v68 route pattern instead of
    going through `url_for`. The route prefix is owned by this
    blueprint so the URL is stable, and avoiding `url_for` lets the
    unit tests run without a Flask request context.
    """
    created_at = getattr(attachment, 'created_at', None)
    return {
        'id': attachment.id,
        'original_filename': attachment.original_filename,
        'content_type': attachment.content_type,
        'file_size': int(attachment.file_size or 0),
        'download_url':
            f'/api/v1/support/cases/{kind}/{case_id}/attachments/{attachment.id}',
        'created_at': created_at.isoformat() if created_at else None,
    }


def _attachments_grouped_by_message(kind: str, source_id: int) -> dict:
    """Bulk-load every attachment for one case, grouped by
    `message_id`. Returns `{message_id: [SupportAttachment]}`.

    Always queried by both `case_type` + `source_id` so a row from
    another case can never leak in. Ordered by `id asc` so the mobile
    client sees attachments in the order they were uploaded
    (matches the web `_support_attachments_for` deterministic order,
    just ascending instead of descending — newest at the bottom of
    the chat bubble feels more natural in a vertical timeline).
    """
    case_type = _attachment_case_type_for(kind)
    rows = (
        SupportAttachment.query
        .filter_by(case_type=case_type, source_id=source_id)
        .order_by(SupportAttachment.id.asc())
        .all()
    )
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.message_id, []).append(row)
    return grouped


# v71: ── Mobile attachment upload helpers ──────────────────────────
#
# These mirror the persistence + validation semantics of the web
# `_save_support_attachments` flow in `support.py` (same whitelist,
# same 10 MB cap, same `<instance>/support_uploads/<case_type>/
# <source_id>/<uuid>.<ext>` storage layout, same SupportAttachment
# row shape) but with two important differences:
#
#   1. The web helper uses `flash(...)` to surface per-file rejection
#      warnings — invisible to mobile clients. The mobile helper
#      returns a structured `(saved, rejected)` tuple so the route
#      can embed `rejected_attachments[]` in the JSON response.
#
#   2. The web helper reads files straight off `request.files` inside
#      the handler. The mobile helper accepts the list of uploaded
#      file objects as a parameter so unit tests can pass Mock
#      FileStorage objects without a Flask request context.


def _mobile_support_attachment_folder(case_type: str, source_id: int) -> Path:
    """Same storage layout as the web flow:
        <instance_path>/support_uploads/<case_type>/<source_id>/
    Creates the directory tree if it doesn't already exist."""
    folder = (
        Path(current_app.instance_path)
        / 'support_uploads'
        / case_type
        / str(source_id)
    )
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _mobile_save_support_attachments(
    *,
    case_type: str,
    source_id: int,
    message_id: int | None,
    actor_id: int | None,
    uploads,
):
    """Save valid uploads as `SupportAttachment` rows; return rejects
    as structured dicts instead of `flash(...)`-ing them.

    `uploads` is the list of werkzeug FileStorage-like objects (the
    handler passes `request.files.getlist('attachments')`). Empty
    list → returns `([], [])` immediately, mirroring "no files were
    uploaded" exactly.

    Per-file failure modes (rejection codes are stable + machine-
    readable so the mobile client can render localised copy):

      * `unsupported_extension` — extension not in the whitelist.
      * `file_too_large`        — file written but exceeds the 10 MB cap.

    Returns `(saved: list[SupportAttachment], rejected: list[dict])`.
    The helper does NOT commit — the caller wraps everything in a
    single transaction so a case + its attachments persist atomically.
    """
    saved: list[SupportAttachment] = []
    rejected: list[dict] = []
    if not uploads:
        return saved, rejected

    for upload in uploads:
        original = (getattr(upload, 'filename', '') or '').strip()
        # Werkzeug's getlist may include empty FileStorage objects
        # when the form field was rendered but no file was picked.
        # The web helper drops them silently — we do the same.
        if not original:
            continue

        ext = Path(original).suffix.lower()
        if ext not in _MOBILE_SUPPORT_ATTACHMENT_EXTENSIONS:
            rejected.append({
                'filename': original,
                'reason_code': 'unsupported_extension',
                'reason_message': 'نوع الملف غير مدعوم.',
            })
            continue

        # Server-side stored name uses the case_type/source_id prefix
        # + a fresh uuid + the original extension, same convention as
        # the web flow so admin tooling sees a single naming scheme.
        stored = f'{case_type}_{source_id}_{uuid4().hex}{ext}'
        target = _mobile_support_attachment_folder(case_type, source_id) / stored
        upload.save(target)
        file_size = target.stat().st_size if target.exists() else 0

        if file_size > _MOBILE_SUPPORT_ATTACHMENT_MAX_BYTES:
            try:
                target.unlink()
            except OSError:
                pass
            rejected.append({
                'filename': original,
                'reason_code': 'file_too_large',
                'reason_message': 'حجم الملف أكبر من 10 ميغابايت.',
            })
            continue

        attachment = SupportAttachment(
            case_type=case_type,
            source_id=source_id,
            message_id=message_id,
            uploaded_by_user_id=actor_id,
            filename=stored,
            original_filename=original[:255],
            content_type=(getattr(upload, 'mimetype', '') or '')[:120],
            file_size=file_size,
            storage_path=str(target),
            created_at=datetime.utcnow(),
        )
        db.session.add(attachment)
        saved.append(attachment)

    return saved, rejected


def _read_support_body():
    """Return `(data, uploads)` where `data` is a dict-like read of the
    submission fields and `uploads` is the list of file uploads (empty
    list for JSON requests).

    Multipart requests are detected via `Content-Type` so JSON-only
    callers keep working unchanged — the v70 audit's backward-
    compatibility rule. Empty multipart submissions (form-encoded but
    no actual files attached) behave like JSON-only.
    """
    content_type = (request.content_type or '').lower()
    if content_type.startswith('multipart/form-data'):
        return request.form, request.files.getlist('attachments')
    # JSON body — `silent=True` matches the existing _json() behaviour
    # so a malformed body degrades to {} rather than raising 400.
    return (request.get_json(silent=True) or {}), []


def _messages_for(kind: str, source_id: int, user) -> list[dict]:
    model = InternalMailMessage if kind == 'message' else SupportTicketMessage
    if kind == 'message':
        q = model.query.filter_by(thread_id=source_id)
    else:
        q = model.query.filter_by(ticket_id=source_id)
    if not getattr(user, 'is_admin', False):
        q = q.filter_by(is_internal_note=False)
    rows = q.order_by(model.created_at.asc(), model.id.asc()).all()
    # v68: bulk-load attachments once, group by message_id, then
    # surface a per-message list on each message dict.
    attachments_by_msg = _attachments_grouped_by_message(kind, source_id)
    return [{
        'id': row.id,
        'sender_user_id': row.sender_user_id,
        'sender_scope': row.sender_scope,
        'is_internal_note': bool(row.is_internal_note),
        'body': row.body,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        # v68: always-present list; empty when this message has no
        # attachments — keeps the mobile parser shape stable.
        'attachments': [
            _mobile_attachment_payload(a, kind=kind, case_id=source_id)
            for a in attachments_by_msg.get(row.id, [])
        ],
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
    # v71: accept JSON OR multipart/form-data. `uploads` is `[]` for
    # JSON requests so older clients continue to work unchanged.
    data, uploads = _read_support_body()
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
    # v71: capture the new message in a variable and flush so its id
    # is available for the SupportAttachment FK below. Same shape as
    # the web `/portal/support` flow, only differs in how rejections
    # are surfaced (structured JSON vs flash).
    if kind == 'ticket':
        item = SupportTicket(tenant_id=tenant_id, opened_by_user_id=user.id, subject=subject, category=category, priority=priority, status='open', related_device_id=data.get('related_device_id') or None, last_reply_at=datetime.utcnow())
        db.session.add(item); db.session.flush()
        msg = SupportTicketMessage(ticket_id=item.id, sender_user_id=user.id, sender_scope='user', body=body)
        db.session.add(msg); db.session.flush()
        attach_case_type = 'ticket'
        upsert_support_case('ticket', item, 'user')
        audit_case('ticket', item.id, user.id, 'ticket.mobile_create', 'Subscriber opened a ticket from mobile API', commit=False)
        source_type = 'ticket'
    else:
        item = InternalMailThread(tenant_id=tenant_id, created_by_user_id=user.id, subject=subject, category=category, priority=priority, status='open', last_reply_at=datetime.utcnow())
        db.session.add(item); db.session.flush()
        msg = InternalMailMessage(thread_id=item.id, sender_user_id=user.id, sender_scope='user', body=body)
        db.session.add(msg); db.session.flush()
        attach_case_type = 'message'
        upsert_support_case('message', item, 'user')
        audit_case('message', item.id, user.id, 'message.mobile_create', 'Subscriber opened a message from mobile API', commit=False)
        source_type = 'message'

    # v71: persist any uploaded files. Helper validates per-file and
    # surfaces rejections as structured dicts — the case itself still
    # commits cleanly even when every uploaded file was rejected.
    saved_attachments, rejected_attachments = _mobile_save_support_attachments(
        case_type=attach_case_type,
        source_id=item.id,
        message_id=msg.id,
        actor_id=user.id,
        uploads=uploads,
    )

    for admin in AppUser.query.filter_by(is_admin=True).all():
        notify_user(admin.id, source_type=source_type, source_id=item.id, tenant_id=tenant_id, title='New support request', message=subject, direct_url=url_for('main.admin_support_command_center', lang='en'), commit=False)
    db.session.commit()

    payload = _case_payload(source_type, item, user, include_messages=True)
    # v71: embed the attachment results so the mobile UI sees what was
    # saved + what was rejected in the single round-trip. The shape is
    # additive — older clients that don't read these keys are unchanged.
    payload['attachments'] = [
        _mobile_attachment_payload(a, kind=source_type, case_id=item.id)
        for a in saved_attachments
    ]
    payload['rejected_attachments'] = rejected_attachments
    return api_ok(payload, status=201)


def _support_bool(value):
    """Coerce JSON booleans + multipart string flags into a real bool.
    JSON delivers `True` / `False` natively; multipart form fields
    arrive as `'true'` / `'1'` / `'yes'` strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'true', '1', 'yes', 'on'}
    return bool(value)


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
    # v71: accept JSON OR multipart/form-data. JSON-only clients keep
    # working unchanged (`uploads` will be `[]`).
    data, uploads = _read_support_body()
    body = (data.get('body') or data.get('message') or '').strip()
    if not body:
        return api_error('Reply body is required.', code='missing_reply_body', status=400)
    scope = 'admin' if getattr(user, 'is_admin', False) else 'user'
    # `is_internal_note` arrives as a real bool from JSON or as a
    # string from multipart — `_support_bool` normalises both.
    is_internal = _support_bool(data.get('is_internal_note')) and getattr(user, 'is_admin', False)
    # v71: capture the new reply message + flush so its id is
    # available for the SupportAttachment FK below.
    if kind == 'message':
        msg = InternalMailMessage(thread_id=item.id, sender_user_id=user.id, sender_scope=scope, is_internal_note=is_internal, body=body)
    else:
        msg = SupportTicketMessage(ticket_id=item.id, sender_user_id=user.id, sender_scope=scope, is_internal_note=is_internal, body=body)
    db.session.add(msg); db.session.flush()

    new_status = (data.get('status') or item.status or 'open').strip()
    if getattr(user, 'is_admin', False) and new_status:
        item.status = new_status
    item.last_reply_at = datetime.utcnow(); item.updated_at = datetime.utcnow()
    upsert_support_case(kind, item, scope)

    # v71: persist any uploaded files. Same atomicity contract as the
    # create endpoint — rejections never abort the reply itself.
    attach_case_type = 'ticket' if kind == 'ticket' else 'message'
    saved_attachments, rejected_attachments = _mobile_save_support_attachments(
        case_type=attach_case_type,
        source_id=item.id,
        message_id=msg.id,
        actor_id=user.id,
        uploads=uploads,
    )

    owner_id = getattr(item, 'created_by_user_id', None) if kind == 'message' else getattr(item, 'opened_by_user_id', None)
    target_id = owner_id if getattr(user, 'is_admin', False) else getattr(item, 'assigned_admin_user_id', None)
    if target_id:
        notify_user(target_id, source_type=kind, source_id=item.id, tenant_id=item.tenant_id, title='Support case updated', message=item.subject, direct_url=url_for('main.portal_support', lang='en'), commit=False)
    audit_case(kind, item.id, user.id, f'{kind}.mobile_reply', 'Mobile API support reply', {'status': item.status, 'attachments': len(saved_attachments)}, commit=False)
    db.session.commit()

    payload = _case_payload(kind, item, user, include_messages=True)
    # v71: additive embedding. The case payload's `messages[].attachments`
    # already lists the persisted rows for the entire thread; these
    # two extra top-level keys narrow that down to "just what this
    # request saved" + "what this request rejected" so the mobile UI
    # can show a per-submission summary snackbar.
    payload['attachments'] = [
        _mobile_attachment_payload(a, kind=kind, case_id=item.id)
        for a in saved_attachments
    ]
    payload['rejected_attachments'] = rejected_attachments
    return api_ok(payload)


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


@mobile_support_api_bp.get(
    '/cases/<kind>/<int:case_id>/attachments/<int:attachment_id>'
)
def support_attachment_download(kind: str, case_id: int, attachment_id: int):
    """v68 — owner-scoped mobile download for one support attachment.

    Three-layer gate (never trust a raw attachment_id alone):

      1. `_require_user` — bearer auth (401 `auth_required` on miss).
      2. `_case_for_user(user, kind, case_id)` — case must be on this
         user (or this user must be admin). Returns `None` for a
         foreign owner → **404 `support_case_not_found`**, never
         leaks the case's existence.
      3. The attachment row must belong to **this exact** case_type
         + source_id. A row with a different parent → **404
         `attachment_not_found`**, same status as a missing row.

    Honest 410 path: when the row exists but the underlying file is
    missing from storage (common on Render's ephemeral filesystem
    between deploys — see the web `support_attachment_download`
    comment at `support.py:228`), return **410 `attachment_storage_missing`**
    so the mobile client can render a calm "تم رفع هذا الملف قبل
    تحديث الخادم ولم يعد متاحًا" message instead of treating it as a
    generic failure.

    On success: stream inline with `send_file(...)`, preserving the
    user-supplied `original_filename` as the download_name and the
    stored `content_type` as the mimetype — matches the web route's
    behaviour exactly so the mobile client and the web get the same
    UX.
    """
    user, err = _require_user()
    if err:
        return err
    # Owner-scope the parent case first; `_case_for_user` returns
    # the normalized kind alongside the row, which we re-use below.
    normalized_kind, item = _case_for_user(user, kind, case_id)
    if not item:
        return api_error(
            'Support case not found.',
            code='support_case_not_found',
            status=404,
        )
    case_type = _attachment_case_type_for(normalized_kind)
    # Attachment must belong to THIS case + THIS source. Filtering by
    # `id` alone would let an attacker probe attachment ids that
    # belong to cases they own with one whose row they don't.
    attachment = (
        SupportAttachment.query
        .filter_by(
            id=attachment_id,
            case_type=case_type,
            source_id=case_id,
        )
        .first()
    )
    if attachment is None:
        return api_error(
            'Support attachment not found.',
            code='attachment_not_found',
            status=404,
        )

    storage_path = (attachment.storage_path or '').strip()
    path = Path(storage_path) if storage_path else None
    # Honest 410: row exists, but the file isn't on disk anymore
    # (post-redeploy ephemeral-storage loss). Mobile client renders a
    # calm "re-upload through the case" prompt rather than treating
    # this as a generic 404.
    if path is None or not path.is_file():
        return api_error(
            'Attachment file is no longer available on the server.',
            code='attachment_storage_missing',
            status=410,
        )

    # Inline streaming, same semantics as the web download route.
    return send_file(
        path,
        as_attachment=False,
        download_name=attachment.original_filename or attachment.filename,
        mimetype=attachment.content_type or None,
    )
