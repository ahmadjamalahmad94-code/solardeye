"""v68 — mobile support attachment read-endpoint tests.

The backend additions are:

  1. `_attachment_case_type_for(kind)`         — pure normalizer.
  2. `_mobile_attachment_payload(att, kind, case_id)` — pure mapper
     that surfaces a SupportAttachment row in the mobile contract
     shape without leaking `storage_path`.
  3. `_attachments_grouped_by_message(kind, source_id)` — bulk
     loader that groups attachment rows by `message_id`. Used by
     `_messages_for` to embed `attachments[]` per message.
  4. `_messages_for(kind, source_id, user)`    — already existed; now
     extended to embed `attachments[]`.
  5. `support_attachment_download`             — new owner-scoped
     download route at `GET /api/v1/support/cases/<kind>/<case_id>/
     attachments/<attachment_id>`.

Coverage mirrors v59 / v62 / v65: pure-helper unit tests + route
handler tests via `Flask.test_request_context` + mocks. No DB, no
`create_app()` boot.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Pure helper tests (no Flask context required)
# ═══════════════════════════════════════════════════════════════════════

def test_case_type_for_normalizes_kind():
    """`kind='message'` and `kind='mail'` both map to the same
    `case_type='message'` value the SupportAttachment table uses.
    `kind='ticket'` maps to `'ticket'`. Unknown kinds default to
    the safer `'message'` because the mobile route layer already
    rejects unknown kinds upstream via `_case_for_user`."""
    from app.blueprints.mobile_support_api import _attachment_case_type_for
    assert _attachment_case_type_for('message') == 'message'
    assert _attachment_case_type_for('mail') == 'message'
    assert _attachment_case_type_for('ticket') == 'ticket'
    assert _attachment_case_type_for('garbage') == 'message'


def _fake_attachment(
    *, id_=55, message_id=10, original='guide.pdf',
    content_type='application/pdf', file_size=102400,
    created_at=datetime(2026, 5, 12, 10, 0, 0),
    storage_path='/tmp/support_uploads/ticket/10/guide.pdf',
    filename='ticket_10_abc.pdf',
):
    a = mock.Mock()
    a.id = id_
    a.message_id = message_id
    a.original_filename = original
    a.content_type = content_type
    a.file_size = file_size
    a.created_at = created_at
    a.storage_path = storage_path
    a.filename = filename
    return a


def test_attachment_payload_shape_locked():
    """The mobile contract for one attachment row. Notably: NO
    `storage_path` leak, `download_url` follows the v68 route
    pattern verbatim, `file_size` is normalized to int."""
    from app.blueprints.mobile_support_api import _mobile_attachment_payload
    att = _fake_attachment()
    payload = _mobile_attachment_payload(att, kind='ticket', case_id=10)
    assert payload == {
        'id': 55,
        'original_filename': 'guide.pdf',
        'content_type': 'application/pdf',
        'file_size': 102400,
        'download_url': '/api/v1/support/cases/ticket/10/attachments/55',
        'created_at': '2026-05-12T10:00:00',
    }
    # Locked: storage_path never leaks to JSON.
    assert 'storage_path' not in payload


def test_attachment_payload_handles_null_optional_fields():
    """Some attachments lack a `content_type` or `created_at`. The
    helper must surface those as `None` rather than crashing."""
    from app.blueprints.mobile_support_api import _mobile_attachment_payload
    att = _fake_attachment(content_type=None, created_at=None, file_size=None)
    payload = _mobile_attachment_payload(att, kind='message', case_id=7)
    assert payload['content_type'] is None
    assert payload['created_at'] is None
    # `file_size=None` normalizes to 0 — keeps the mobile parser shape
    # stable (it's a count, never null in the contract).
    assert payload['file_size'] == 0
    assert payload['download_url'] == '/api/v1/support/cases/message/7/attachments/55'


def test_attachments_grouped_by_message_filters_by_case():
    """The bulk loader must filter on BOTH `case_type` and
    `source_id` — otherwise an attachment from another case could
    leak through if it happened to share a `message_id` number."""
    from app.blueprints.mobile_support_api import (
        _attachments_grouped_by_message, SupportAttachment,
    )
    # In-case attachments — three on message 10, one on message 11.
    in_case = [
        _fake_attachment(id_=1, message_id=10),
        _fake_attachment(id_=2, message_id=10),
        _fake_attachment(id_=3, message_id=11),
    ]
    # Query chain: `.filter_by(case_type=..., source_id=...).order_by(...).all()`
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = in_case
    captured_filter_kwargs = {}

    def _filter_by(**kwargs):
        captured_filter_kwargs.update(kwargs)
        return chain

    chain.filter_by = mock.Mock(side_effect=_filter_by)

    # `flask_sqlalchemy.Model.query` is a descriptor that needs an app
    # context — wrap the helper call (same pattern as v65 helper tests).
    app = _make_app()
    with app.test_request_context('/'), \
         mock.patch.object(SupportAttachment, 'query', chain):
        grouped = _attachments_grouped_by_message('ticket', 10)

    # Filter kwargs include BOTH case_type and source_id.
    assert captured_filter_kwargs == {'case_type': 'ticket', 'source_id': 10}
    # Grouped by message_id.
    assert set(grouped.keys()) == {10, 11}
    assert [a.id for a in grouped[10]] == [1, 2]
    assert [a.id for a in grouped[11]] == [3]


def test_attachments_grouped_returns_empty_dict_when_no_rows():
    from app.blueprints.mobile_support_api import (
        _attachments_grouped_by_message, SupportAttachment,
    )
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = []
    app = _make_app()
    with app.test_request_context('/'), \
         mock.patch.object(SupportAttachment, 'query', chain):
        grouped = _attachments_grouped_by_message('message', 99)
    assert grouped == {}


# ═══════════════════════════════════════════════════════════════════════
# `_messages_for` embedding tests
# ═══════════════════════════════════════════════════════════════════════

def _fake_message(*, id_, body='', created_at=None, is_internal=False):
    m = mock.Mock()
    m.id = id_
    m.sender_user_id = 42
    m.sender_scope = 'user'
    m.is_internal_note = is_internal
    m.body = body
    m.created_at = created_at or datetime(2026, 5, 12, 12, 0, 0)
    return m


def _patch_message_query(rows):
    """Patch the `query` attribute on both message models. The route
    branches on `kind`, so we patch both to keep the test agnostic."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = rows
    return chain


def test_messages_for_includes_per_message_attachments():
    """End-to-end: two messages, attachments grouped by message_id,
    each message dict gets an `attachments[]` list in the mobile
    contract shape."""
    from app.blueprints.mobile_support_api import (
        _messages_for, SupportTicketMessage, SupportAttachment,
    )
    user = mock.Mock(is_admin=False)
    msgs = [_fake_message(id_=10), _fake_message(id_=11)]
    attachments = [
        _fake_attachment(id_=1, message_id=10, original='one.pdf'),
        _fake_attachment(id_=2, message_id=10, original='two.png',
                         content_type='image/png'),
        _fake_attachment(id_=3, message_id=11, original='three.csv',
                         content_type='text/csv'),
    ]

    msg_chain = _patch_message_query(msgs)
    att_chain = mock.Mock()
    att_chain.filter_by.return_value = att_chain
    att_chain.order_by.return_value = att_chain
    att_chain.all.return_value = attachments

    app = _make_app()
    with app.test_request_context('/'), \
         mock.patch.object(SupportTicketMessage, 'query', msg_chain), \
         mock.patch.object(SupportAttachment, 'query', att_chain):
        result = _messages_for('ticket', 10, user)

    assert len(result) == 2
    # Message 10 has TWO attachments, in stored order.
    msg10 = result[0]
    assert msg10['id'] == 10
    assert 'attachments' in msg10
    assert len(msg10['attachments']) == 2
    assert msg10['attachments'][0]['id'] == 1
    assert msg10['attachments'][0]['download_url'] == \
        '/api/v1/support/cases/ticket/10/attachments/1'
    assert msg10['attachments'][1]['content_type'] == 'image/png'
    # Message 11 has ONE attachment.
    msg11 = result[1]
    assert len(msg11['attachments']) == 1
    assert msg11['attachments'][0]['id'] == 3


def test_messages_for_empty_attachments_when_message_has_none():
    """A case with zero attachments still surfaces every message
    with an empty `attachments` list — the mobile parser shape
    must stay stable."""
    from app.blueprints.mobile_support_api import (
        _messages_for, SupportTicketMessage, SupportAttachment,
    )
    user = mock.Mock(is_admin=False)
    msg_chain = _patch_message_query([_fake_message(id_=10)])
    att_chain = mock.Mock()
    att_chain.filter_by.return_value = att_chain
    att_chain.order_by.return_value = att_chain
    att_chain.all.return_value = []

    app = _make_app()
    with app.test_request_context('/'), \
         mock.patch.object(SupportTicketMessage, 'query', msg_chain), \
         mock.patch.object(SupportAttachment, 'query', att_chain):
        result = _messages_for('ticket', 10, user)
    assert result[0]['attachments'] == []


def test_messages_for_does_not_leak_attachments_from_other_case():
    """The bulk loader filters by `case_type` + `source_id`. We
    verify the underlying filter_by call uses both — guards against
    a future refactor that accidentally drops one half of the
    composite filter."""
    from app.blueprints.mobile_support_api import (
        _messages_for, SupportTicketMessage, SupportAttachment,
    )
    user = mock.Mock(is_admin=False)
    msg_chain = _patch_message_query([_fake_message(id_=10)])

    captured = []
    att_chain = mock.Mock()

    def _filter_by(**kwargs):
        captured.append(kwargs)
        return att_chain

    att_chain.filter_by = mock.Mock(side_effect=_filter_by)
    att_chain.order_by.return_value = att_chain
    att_chain.all.return_value = []

    app = _make_app()
    with app.test_request_context('/'), \
         mock.patch.object(SupportTicketMessage, 'query', msg_chain), \
         mock.patch.object(SupportAttachment, 'query', att_chain):
        _messages_for('ticket', 10, user)

    # The attachment loader was called once with BOTH case_type and source_id.
    assert captured == [{'case_type': 'ticket', 'source_id': 10}]


# ═══════════════════════════════════════════════════════════════════════
# Download route handler tests (Flask test_request_context + mocks)
# ═══════════════════════════════════════════════════════════════════════

def _make_app():
    from flask import Flask
    from app.blueprints.mobile_support_api import mobile_support_api_bp
    app = Flask(__name__)
    app.register_blueprint(mobile_support_api_bp)
    return app


def _patch_user(user):
    return mock.patch(
        'app.blueprints.mobile_support_api.user_from_bearer_or_session',
        return_value=user,
    )


def _patch_case_for_user(kind, item):
    return mock.patch(
        'app.blueprints.mobile_support_api._case_for_user',
        return_value=(kind, item),
    )


def _attachment_query_returning(attachment):
    """Chain mock for
    `SupportAttachment.query.filter_by(id=..., case_type=..., source_id=...).first()`."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.first.return_value = attachment
    return chain


def test_route_unauthenticated_returns_401():
    from app.blueprints.mobile_support_api import support_attachment_download
    app = _make_app()
    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/55',
    ), _patch_user(None):
        resp = support_attachment_download('ticket', 10, 55)
        assert resp.status_code == 401
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'auth_required'


def test_route_foreign_owner_returns_404_support_case_not_found():
    """`_case_for_user` returns `(kind, None)` when the case isn't
    on this user. Route must return 404 — never expose case
    existence to a different user."""
    from app.blueprints.mobile_support_api import support_attachment_download
    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/55',
    ), _patch_user(user), _patch_case_for_user('ticket', None):
        resp = support_attachment_download('ticket', 10, 55)
        assert resp.status_code == 404
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'support_case_not_found'


def test_route_attachment_belongs_to_another_case_returns_404():
    """The attachment id is real but its `(case_type, source_id)`
    doesn't match the route's `(kind, case_id)`. We model this by
    making the composite filter_by chain return None — same code
    path as a non-existent attachment, so a user can't probe for
    attachment ids that don't belong to them."""
    from app.blueprints.mobile_support_api import (
        support_attachment_download, SupportAttachment,
    )
    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    case = mock.Mock(id=10)
    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/9999',
    ), _patch_user(user), _patch_case_for_user('ticket', case), \
         mock.patch.object(
             SupportAttachment, 'query',
             _attachment_query_returning(None),
         ):
        resp = support_attachment_download('ticket', 10, 9999)
        assert resp.status_code == 404
        body = resp.get_json()
        assert body['code'] == 'attachment_not_found'


def test_route_storage_missing_returns_410():
    """Row exists in the DB but the on-disk file is gone (Render
    ephemeral filesystem after redeploy). Route returns 410 with a
    stable `reason` so the mobile UI renders a calm prompt to
    re-upload through the conversation."""
    from app.blueprints.mobile_support_api import (
        support_attachment_download, SupportAttachment,
    )
    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    case = mock.Mock(id=10)
    attachment = _fake_attachment(
        id_=55,
        # An obviously-bogus path so `Path(...).is_file()` returns False.
        storage_path='/definitely/does/not/exist/guide.pdf',
    )
    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/55',
    ), _patch_user(user), _patch_case_for_user('ticket', case), \
         mock.patch.object(
             SupportAttachment, 'query',
             _attachment_query_returning(attachment),
         ):
        resp = support_attachment_download('ticket', 10, 55)
        assert resp.status_code == 410
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'attachment_storage_missing'


def test_route_storage_missing_when_storage_path_blank():
    """Defensive: a row with `storage_path=''` (rare but possible)
    must NOT crash the route; same 410 path applies."""
    from app.blueprints.mobile_support_api import (
        support_attachment_download, SupportAttachment,
    )
    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    case = mock.Mock(id=10)
    attachment = _fake_attachment(id_=55, storage_path='')
    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/55',
    ), _patch_user(user), _patch_case_for_user('ticket', case), \
         mock.patch.object(
             SupportAttachment, 'query',
             _attachment_query_returning(attachment),
         ):
        resp = support_attachment_download('ticket', 10, 55)
        assert resp.status_code == 410
        assert resp.get_json()['code'] == 'attachment_storage_missing'


def test_route_success_streams_inline_with_original_filename(tmp_path):
    """Happy path: row exists, file is on disk. Route calls
    `send_file` with `as_attachment=False` (inline preview),
    `download_name=original_filename`, `mimetype=content_type`."""
    from app.blueprints.mobile_support_api import (
        support_attachment_download, SupportAttachment,
    )
    # Create a real file on disk so `Path(...).is_file()` is True.
    real_file = tmp_path / 'guide.pdf'
    real_file.write_bytes(b'%PDF-1.4 mock content')

    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    case = mock.Mock(id=10)
    attachment = _fake_attachment(
        id_=55,
        storage_path=str(real_file),
        original='guide.pdf',
        content_type='application/pdf',
    )

    captured = {}

    def fake_send_file(path, *,
                       as_attachment=None, download_name=None,
                       mimetype=None, **_):
        captured.update(dict(
            path=path, as_attachment=as_attachment,
            download_name=download_name, mimetype=mimetype,
        ))
        from flask import Response
        return Response(b'streamed', mimetype=mimetype or 'application/octet-stream')

    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/55',
    ), _patch_user(user), _patch_case_for_user('ticket', case), \
         mock.patch.object(
             SupportAttachment, 'query',
             _attachment_query_returning(attachment),
         ), mock.patch(
             'app.blueprints.mobile_support_api.send_file',
             side_effect=fake_send_file,
         ):
        resp = support_attachment_download('ticket', 10, 55)

    assert resp.status_code == 200
    # send_file invoked with locked semantics (inline preview, original
    # filename for download, stored mimetype).
    assert captured['as_attachment'] is False
    assert captured['download_name'] == 'guide.pdf'
    assert captured['mimetype'] == 'application/pdf'
    # The Path arg is the same file we wrote to disk.
    assert Path(str(captured['path'])) == real_file


def test_route_success_falls_back_to_filename_when_original_missing(tmp_path):
    """`download_name` falls back to `attachment.filename` when the
    `original_filename` field is empty / None — matches the web
    route's behavior."""
    from app.blueprints.mobile_support_api import (
        support_attachment_download, SupportAttachment,
    )
    real_file = tmp_path / 'opaque.bin'
    real_file.write_bytes(b'\x00\x01\x02')

    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    case = mock.Mock(id=10)
    attachment = _fake_attachment(
        id_=55,
        storage_path=str(real_file),
        original=None,
        content_type=None,
        filename='ticket_10_abc.bin',
    )
    captured = {}

    def fake_send_file(path, *, as_attachment=None, download_name=None,
                       mimetype=None, **_):
        captured.update(dict(download_name=download_name, mimetype=mimetype))
        from flask import Response
        return Response(b'streamed')

    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/attachments/55',
    ), _patch_user(user), _patch_case_for_user('ticket', case), \
         mock.patch.object(
             SupportAttachment, 'query',
             _attachment_query_returning(attachment),
         ), mock.patch(
             'app.blueprints.mobile_support_api.send_file',
             side_effect=fake_send_file,
         ):
        support_attachment_download('ticket', 10, 55)

    assert captured['download_name'] == 'ticket_10_abc.bin'
    assert captured['mimetype'] is None


def test_route_owner_scope_uses_case_for_user_normalized_kind():
    """`_case_for_user('mail', ...)` normalizes to `'message'`. The
    route must use that normalized kind when filtering attachments,
    so a 'mail' URL alias still matches `case_type='message'` rows."""
    from app.blueprints.mobile_support_api import (
        support_attachment_download, SupportAttachment,
    )
    app = _make_app()
    user = mock.Mock(id=1, is_admin=False)
    case = mock.Mock(id=7)
    captured_filter_kwargs = {}

    chain = mock.Mock()

    def _filter_by(**kwargs):
        captured_filter_kwargs.update(kwargs)
        return chain

    chain.filter_by = mock.Mock(side_effect=_filter_by)
    chain.first.return_value = None  # we only care that filter_by was right

    with app.test_request_context(
        '/api/v1/support/cases/mail/7/attachments/55',
    ), _patch_user(user), _patch_case_for_user('message', case), \
         mock.patch.object(SupportAttachment, 'query', chain):
        resp = support_attachment_download('mail', 7, 55)

    assert resp.status_code == 404  # attachment row didn't exist
    # Filter used the NORMALIZED 'message' case_type, not the raw 'mail' alias.
    assert captured_filter_kwargs == {
        'id': 55, 'case_type': 'message', 'source_id': 7,
    }
