"""v71 — mobile support attachment upload endpoint tests.

Coverage layers (same shape as v59 / v62 / v65 / v68):

  1. **Helper unit tests** for `_mobile_save_support_attachments`
     — validation + persistence + structured rejection without a
     Flask request context (Mock FileStorage objects are passed
     directly as the `uploads` argument).
  2. **Body-reader unit tests** for `_read_support_body` — JSON vs
     multipart routing.
  3. **Route handler tests** for `create_support_case` and
     `reply_support_case` covering:
       * JSON-only path still works (backward compatibility).
       * Multipart create with valid file → 201 + saved + empty rejected.
       * Multipart create with mixed valid/invalid → 201 + both lists.
       * Multipart reply with valid file → 200 + saved + empty rejected.
       * Empty multipart (no files attached) behaves like JSON-only.

No DB, no `create_app()` boot. Filesystem writes are exercised
against `tmp_path` by pointing the test Flask app's `instance_path`
at the temp directory.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Helper builders
# ═══════════════════════════════════════════════════════════════════════

def _make_app(instance_path):
    """Tiny Flask app with the mobile support blueprint and a real
    on-disk `instance_path` (the helper writes attachment files under
    `<instance_path>/support_uploads/...`)."""
    from flask import Flask
    from app.blueprints.mobile_support_api import mobile_support_api_bp
    app = Flask(__name__, instance_path=str(instance_path))
    app.register_blueprint(mobile_support_api_bp)
    return app


def _mock_upload(filename, *, content=b'X', mimetype='application/octet-stream'):
    """werkzeug FileStorage stand-in. `.save(path)` writes the
    provided bytes (or `'X' * size` repetition) to the target path
    so the helper's `.stat().st_size` check works on real bytes."""
    upload = mock.Mock()
    upload.filename = filename
    upload.mimetype = mimetype

    def fake_save(path):
        # `path` is a pathlib.Path from the helper; Flask file storage
        # accepts both str + Path so we coerce.
        with open(str(path), 'wb') as f:
            f.write(content)

    upload.save = mock.Mock(side_effect=fake_save)
    return upload


# ═══════════════════════════════════════════════════════════════════════
# Helper unit tests — _mobile_save_support_attachments
# ═══════════════════════════════════════════════════════════════════════

def test_helper_returns_empty_lists_for_no_uploads(tmp_path):
    """JSON-only path: uploads is `[]`. Helper returns `([], [])`
    immediately without touching the filesystem."""
    from app.blueprints.mobile_support_api import (
        _mobile_save_support_attachments,
    )
    app = _make_app(tmp_path)
    with app.test_request_context('/'):
        saved, rejected = _mobile_save_support_attachments(
            case_type='ticket', source_id=10, message_id=99,
            actor_id=1, uploads=[],
        )
    assert saved == []
    assert rejected == []


def test_helper_persists_valid_file_and_returns_saved_row(tmp_path):
    """Happy path. Whitelisted extension + under 10 MB → persisted as
    a `SupportAttachment` row added to the session (commit is the
    caller's responsibility — we never commit inside the helper)."""
    from app.blueprints.mobile_support_api import (
        _mobile_save_support_attachments,
    )
    app = _make_app(tmp_path)
    upload = _mock_upload(
        'guide.pdf', content=b'%PDF-1.4 mock', mimetype='application/pdf',
    )
    db_mock = mock.Mock()
    with app.test_request_context('/'), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock):
        saved, rejected = _mobile_save_support_attachments(
            case_type='ticket', source_id=10, message_id=99,
            actor_id=42, uploads=[upload],
        )

    assert rejected == []
    assert len(saved) == 1
    row = saved[0]
    # `SupportAttachment` is a SQLAlchemy model — we check the
    # attributes the helper set, not session state.
    assert row.case_type == 'ticket'
    assert row.source_id == 10
    assert row.message_id == 99
    assert row.uploaded_by_user_id == 42
    assert row.original_filename == 'guide.pdf'
    assert row.content_type == 'application/pdf'
    assert row.file_size == len(b'%PDF-1.4 mock')
    # storage_path lives under the test instance path — never leaks
    # to the response (asserted separately in the payload tests).
    assert str(tmp_path) in row.storage_path
    assert row.storage_path.endswith('.pdf')
    # The helper adds to the session but never commits.
    db_mock.session.add.assert_called_once()
    db_mock.session.commit.assert_not_called()


def test_helper_rejects_unsupported_extension(tmp_path):
    """`.exe` is not in the whitelist → file rejected before any
    on-disk write, surfaced with a stable reason_code."""
    from app.blueprints.mobile_support_api import (
        _mobile_save_support_attachments,
    )
    app = _make_app(tmp_path)
    upload = _mock_upload('virus.exe', content=b'MZ\x90\x00')
    db_mock = mock.Mock()
    with app.test_request_context('/'), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock):
        saved, rejected = _mobile_save_support_attachments(
            case_type='ticket', source_id=10, message_id=99,
            actor_id=42, uploads=[upload],
        )

    assert saved == []
    assert len(rejected) == 1
    assert rejected[0] == {
        'filename': 'virus.exe',
        'reason_code': 'unsupported_extension',
        'reason_message': 'نوع الملف غير مدعوم.',
    }
    # The upload was rejected before save — no DB add, no .save() call.
    db_mock.session.add.assert_not_called()
    upload.save.assert_not_called()


def test_helper_rejects_oversized_file_and_unlinks_it(tmp_path):
    """A 10 MB + 1 byte file gets written first (we don't know the
    size until after save), then deleted, then surfaced as rejected.
    The next valid file in the same batch must still get saved."""
    from app.blueprints.mobile_support_api import (
        _mobile_save_support_attachments,
        _MOBILE_SUPPORT_ATTACHMENT_MAX_BYTES,
    )
    app = _make_app(tmp_path)
    big_content = b'X' * (_MOBILE_SUPPORT_ATTACHMENT_MAX_BYTES + 1)
    big_upload = _mock_upload('big.pdf', content=big_content,
                              mimetype='application/pdf')
    db_mock = mock.Mock()
    with app.test_request_context('/'), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock):
        saved, rejected = _mobile_save_support_attachments(
            case_type='ticket', source_id=10, message_id=99,
            actor_id=42, uploads=[big_upload],
        )

    assert saved == []
    assert len(rejected) == 1
    assert rejected[0]['filename'] == 'big.pdf'
    assert rejected[0]['reason_code'] == 'file_too_large'
    assert 'ميغابايت' in rejected[0]['reason_message']
    # The oversized blob must be cleaned up — no leftover files in
    # the per-case directory.
    case_dir = tmp_path / 'support_uploads' / 'ticket' / '10'
    if case_dir.exists():
        assert list(case_dir.iterdir()) == []


def test_helper_mixed_batch_saves_valid_and_rejects_invalid(tmp_path):
    """Realistic submission: user attaches a PDF, a malware-looking
    .exe, and an over-cap zip. The PDF should still persist; the
    other two surface in `rejected[]` with distinct reason_codes."""
    from app.blueprints.mobile_support_api import (
        _mobile_save_support_attachments,
        _MOBILE_SUPPORT_ATTACHMENT_MAX_BYTES,
    )
    app = _make_app(tmp_path)
    uploads = [
        _mock_upload('valid.pdf', content=b'%PDF-1.4',
                     mimetype='application/pdf'),
        _mock_upload('virus.exe', content=b'MZ'),
        _mock_upload('big.zip',
                     content=b'P' * (_MOBILE_SUPPORT_ATTACHMENT_MAX_BYTES + 1),
                     mimetype='application/zip'),
    ]
    db_mock = mock.Mock()
    with app.test_request_context('/'), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock):
        saved, rejected = _mobile_save_support_attachments(
            case_type='message', source_id=7, message_id=21,
            actor_id=42, uploads=uploads,
        )

    assert len(saved) == 1
    assert saved[0].original_filename == 'valid.pdf'
    assert len(rejected) == 2
    reasons = {r['filename']: r['reason_code'] for r in rejected}
    assert reasons == {
        'virus.exe': 'unsupported_extension',
        'big.zip': 'file_too_large',
    }


def test_helper_skips_empty_filename_uploads(tmp_path):
    """Some clients submit empty FileStorage entries when the form
    field is rendered but no file was picked. The web flow drops
    them silently — we mirror that (not even a rejection entry)."""
    from app.blueprints.mobile_support_api import (
        _mobile_save_support_attachments,
    )
    app = _make_app(tmp_path)
    empty = _mock_upload('', content=b'')
    db_mock = mock.Mock()
    with app.test_request_context('/'), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock):
        saved, rejected = _mobile_save_support_attachments(
            case_type='ticket', source_id=10, message_id=99,
            actor_id=42, uploads=[empty],
        )
    assert saved == []
    assert rejected == []


# ═══════════════════════════════════════════════════════════════════════
# Body-reader unit tests — _read_support_body
# ═══════════════════════════════════════════════════════════════════════

def test_body_reader_returns_json_dict_and_empty_uploads(tmp_path):
    """`application/json` body → dict from `get_json`, empty uploads."""
    from app.blueprints.mobile_support_api import _read_support_body
    app = _make_app(tmp_path)
    with app.test_request_context(
        '/',
        method='POST',
        json={'subject': 'X', 'body': 'Y'},
    ):
        data, uploads = _read_support_body()
    assert data.get('subject') == 'X'
    assert data.get('body') == 'Y'
    assert uploads == []


def test_body_reader_returns_form_dict_and_files_for_multipart(tmp_path):
    """`multipart/form-data` body → `request.form` for fields and
    `request.files.getlist('attachments')` for files."""
    from app.blueprints.mobile_support_api import _read_support_body
    from werkzeug.datastructures import FileStorage
    app = _make_app(tmp_path)
    file_one = FileStorage(
        stream=io.BytesIO(b'%PDF-1.4'),
        filename='one.pdf', content_type='application/pdf',
    )
    file_two = FileStorage(
        stream=io.BytesIO(b'\x89PNG'),
        filename='two.png', content_type='image/png',
    )
    with app.test_request_context(
        '/',
        method='POST',
        data={
            'subject': 'multi',
            'body': 'with files',
            'attachments': [file_one, file_two],
        },
        content_type='multipart/form-data',
    ):
        data, uploads = _read_support_body()
    assert data.get('subject') == 'multi'
    assert data.get('body') == 'with files'
    assert len(uploads) == 2
    assert {u.filename for u in uploads} == {'one.pdf', 'two.png'}


# ═══════════════════════════════════════════════════════════════════════
# Route handler tests — create_support_case
# ═══════════════════════════════════════════════════════════════════════

def _fake_user(*, id_=42, is_admin=False):
    user = mock.Mock()
    user.id = id_
    user.is_admin = is_admin
    return user


def _patch_user(user):
    return mock.patch(
        'app.blueprints.mobile_support_api.user_from_bearer_or_session',
        return_value=user,
    )


def _patch_tenant(tenant):
    return mock.patch(
        'app.blueprints.mobile_support_api.ensure_user_tenant_and_subscription',
        return_value=(tenant, None),
    )


def _patch_quota_ok():
    return mock.patch(
        'app.blueprints.mobile_support_api.consume_quota_for_user',
        return_value=(True, '', None),
    )


def _patch_case_for_user(kind, item):
    return mock.patch(
        'app.blueprints.mobile_support_api._case_for_user',
        return_value=(kind, item),
    )


def _patch_case_payload(payload):
    return mock.patch(
        'app.blueprints.mobile_support_api._case_payload',
        return_value=dict(payload),
    )


def _id_assigning_session_add(start_id=1):
    """Side-effect fn that sets `.id` on every added row sequentially.
    Mimics what `db.session.flush()` does in production so the helper
    sees a real id on the message row."""
    counter = {'n': start_id}

    def _add(obj):
        if getattr(obj, 'id', None) in (None, 0):
            obj.id = counter['n']
            counter['n'] += 1

    return _add


def test_route_json_only_create_still_works(tmp_path):
    """Backward compatibility: a JSON-only POST returns the existing
    payload (now with empty `attachments` + `rejected_attachments`)
    and never touches the filesystem."""
    from app.blueprints.mobile_support_api import create_support_case
    app = _make_app(tmp_path)
    user = _fake_user()
    tenant = mock.Mock(id=7)

    captured_admins = mock.Mock()
    captured_admins.query.filter_by.return_value.all.return_value = []

    db_mock = mock.Mock()
    db_mock.session.add.side_effect = _id_assigning_session_add()

    with app.test_request_context(
        '/api/v1/support/cases',
        method='POST',
        json={'type': 'ticket', 'subject': 'S', 'body': 'B'},
    ), _patch_user(user), \
         _patch_tenant(tenant), \
         _patch_quota_ok(), \
         _patch_case_payload({'id': 1, 'type': 'ticket', 'subject': 'S'}), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_support_api.AppUser', captured_admins), \
         mock.patch('app.blueprints.mobile_support_api.upsert_support_case'), \
         mock.patch('app.blueprints.mobile_support_api.audit_case'), \
         mock.patch('app.blueprints.mobile_support_api.notify_user'):
        resp = create_support_case()

    assert resp.status_code == 201
    data = resp.get_json()['data']
    # Locked: new keys are present even on JSON-only path, both empty.
    assert data['attachments'] == []
    assert data['rejected_attachments'] == []
    db_mock.session.commit.assert_called_once()
    # No support_uploads directory was created — no work done.
    assert not (tmp_path / 'support_uploads').exists()


def test_route_multipart_create_saves_valid_file(tmp_path):
    """Happy multipart path: the case + message commit, the file
    persists, the response carries the saved attachment."""
    from app.blueprints.mobile_support_api import create_support_case
    from werkzeug.datastructures import FileStorage
    app = _make_app(tmp_path)
    user = _fake_user()
    tenant = mock.Mock(id=7)

    captured_admins = mock.Mock()
    captured_admins.query.filter_by.return_value.all.return_value = []

    db_mock = mock.Mock()
    db_mock.session.add.side_effect = _id_assigning_session_add()

    pdf = FileStorage(
        stream=io.BytesIO(b'%PDF-1.4 mock'),
        filename='guide.pdf', content_type='application/pdf',
    )

    with app.test_request_context(
        '/api/v1/support/cases',
        method='POST',
        data={
            'type': 'ticket',
            'subject': 'multi test',
            'body': 'with file',
            'attachments': [pdf],
        },
        content_type='multipart/form-data',
    ), _patch_user(user), \
         _patch_tenant(tenant), \
         _patch_quota_ok(), \
         _patch_case_payload({'id': 1, 'type': 'ticket', 'subject': 'multi test'}), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_support_api.AppUser', captured_admins), \
         mock.patch('app.blueprints.mobile_support_api.upsert_support_case'), \
         mock.patch('app.blueprints.mobile_support_api.audit_case'), \
         mock.patch('app.blueprints.mobile_support_api.notify_user'):
        resp = create_support_case()

    assert resp.status_code == 201
    data = resp.get_json()['data']
    # Locked: one saved attachment, no rejections.
    assert len(data['attachments']) == 1
    saved = data['attachments'][0]
    assert saved['original_filename'] == 'guide.pdf'
    assert saved['content_type'] == 'application/pdf'
    assert saved['file_size'] == len(b'%PDF-1.4 mock')
    # download_url follows the v68 contract pattern. The ticket id
    # came from our id-assigning side effect (first add → ticket=1).
    assert saved['download_url'].startswith(
        '/api/v1/support/cases/ticket/1/attachments/'
    )
    # No `storage_path` ever leaks to JSON.
    assert 'storage_path' not in saved
    assert data['rejected_attachments'] == []
    db_mock.session.commit.assert_called_once()


def test_route_multipart_create_mixed_returns_both_lists(tmp_path):
    """One valid + one disallowed extension → 201 with saved + rejected."""
    from app.blueprints.mobile_support_api import create_support_case
    from werkzeug.datastructures import FileStorage
    app = _make_app(tmp_path)
    user = _fake_user()
    tenant = mock.Mock(id=7)
    captured_admins = mock.Mock()
    captured_admins.query.filter_by.return_value.all.return_value = []
    db_mock = mock.Mock()
    db_mock.session.add.side_effect = _id_assigning_session_add()

    valid = FileStorage(
        stream=io.BytesIO(b'%PDF-1.4'),
        filename='good.pdf', content_type='application/pdf',
    )
    invalid = FileStorage(
        stream=io.BytesIO(b'MZ\x90'),
        filename='virus.exe', content_type='application/x-dosexec',
    )

    with app.test_request_context(
        '/api/v1/support/cases',
        method='POST',
        data={
            'type': 'message',
            'subject': 'mixed',
            'body': 'attaching two',
            'attachments': [valid, invalid],
        },
        content_type='multipart/form-data',
    ), _patch_user(user), \
         _patch_tenant(tenant), \
         _patch_quota_ok(), \
         _patch_case_payload({'id': 1, 'type': 'message'}), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_support_api.AppUser', captured_admins), \
         mock.patch('app.blueprints.mobile_support_api.upsert_support_case'), \
         mock.patch('app.blueprints.mobile_support_api.audit_case'), \
         mock.patch('app.blueprints.mobile_support_api.notify_user'):
        resp = create_support_case()

    assert resp.status_code == 201
    data = resp.get_json()['data']
    assert len(data['attachments']) == 1
    assert data['attachments'][0]['original_filename'] == 'good.pdf'
    assert len(data['rejected_attachments']) == 1
    r = data['rejected_attachments'][0]
    assert r['filename'] == 'virus.exe'
    assert r['reason_code'] == 'unsupported_extension'


def test_route_empty_multipart_behaves_like_json_only(tmp_path):
    """Multipart form with subject/body but NO files attached → 201,
    both attachment lists empty. The endpoint must NOT 400 just
    because the user submitted multipart without files."""
    from app.blueprints.mobile_support_api import create_support_case
    app = _make_app(tmp_path)
    user = _fake_user()
    tenant = mock.Mock(id=7)
    captured_admins = mock.Mock()
    captured_admins.query.filter_by.return_value.all.return_value = []
    db_mock = mock.Mock()
    db_mock.session.add.side_effect = _id_assigning_session_add()

    with app.test_request_context(
        '/api/v1/support/cases',
        method='POST',
        data={'type': 'ticket', 'subject': 'no files', 'body': 'just text'},
        content_type='multipart/form-data',
    ), _patch_user(user), \
         _patch_tenant(tenant), \
         _patch_quota_ok(), \
         _patch_case_payload({'id': 1, 'type': 'ticket'}), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_support_api.AppUser', captured_admins), \
         mock.patch('app.blueprints.mobile_support_api.upsert_support_case'), \
         mock.patch('app.blueprints.mobile_support_api.audit_case'), \
         mock.patch('app.blueprints.mobile_support_api.notify_user'):
        resp = create_support_case()

    assert resp.status_code == 201
    data = resp.get_json()['data']
    assert data['attachments'] == []
    assert data['rejected_attachments'] == []


# ═══════════════════════════════════════════════════════════════════════
# Route handler tests — reply_support_case
# ═══════════════════════════════════════════════════════════════════════

def test_route_json_only_reply_still_works(tmp_path):
    """Backward compatibility for the reply endpoint."""
    from app.blueprints.mobile_support_api import reply_support_case
    app = _make_app(tmp_path)
    user = _fake_user()
    case = mock.Mock()
    case.id = 10
    case.status = 'open'
    case.tenant_id = 7
    case.created_by_user_id = user.id
    case.opened_by_user_id = user.id
    case.assigned_admin_user_id = None
    case.subject = 'S'

    db_mock = mock.Mock()
    db_mock.session.add.side_effect = _id_assigning_session_add(start_id=100)

    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/reply',
        method='POST',
        json={'body': 'hello'},
    ), _patch_user(user), \
         _patch_case_for_user('ticket', case), \
         _patch_case_payload({'id': 10, 'type': 'ticket'}), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_support_api.upsert_support_case'), \
         mock.patch('app.blueprints.mobile_support_api.audit_case'), \
         mock.patch('app.blueprints.mobile_support_api.notify_user'):
        resp = reply_support_case('ticket', 10)

    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['attachments'] == []
    assert data['rejected_attachments'] == []
    assert not (tmp_path / 'support_uploads').exists()


def test_route_multipart_reply_saves_valid_file(tmp_path):
    from app.blueprints.mobile_support_api import reply_support_case
    from werkzeug.datastructures import FileStorage
    app = _make_app(tmp_path)
    user = _fake_user()
    case = mock.Mock()
    case.id = 10
    case.status = 'open'
    case.tenant_id = 7
    case.created_by_user_id = user.id
    case.opened_by_user_id = user.id
    case.assigned_admin_user_id = None
    case.subject = 'S'

    db_mock = mock.Mock()
    db_mock.session.add.side_effect = _id_assigning_session_add(start_id=100)

    png = FileStorage(
        stream=io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'X' * 200),
        filename='screenshot.png', content_type='image/png',
    )

    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/reply',
        method='POST',
        data={'body': 'see screenshot', 'attachments': [png]},
        content_type='multipart/form-data',
    ), _patch_user(user), \
         _patch_case_for_user('ticket', case), \
         _patch_case_payload({'id': 10, 'type': 'ticket'}), \
         mock.patch('app.blueprints.mobile_support_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_support_api.upsert_support_case'), \
         mock.patch('app.blueprints.mobile_support_api.audit_case'), \
         mock.patch('app.blueprints.mobile_support_api.notify_user'):
        resp = reply_support_case('ticket', 10)

    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert len(data['attachments']) == 1
    saved = data['attachments'][0]
    assert saved['original_filename'] == 'screenshot.png'
    assert saved['content_type'] == 'image/png'
    assert saved['download_url'].startswith(
        '/api/v1/support/cases/ticket/10/attachments/'
    )
    assert data['rejected_attachments'] == []
    db_mock.session.commit.assert_called_once()


def test_route_reply_rejects_closed_case_even_for_multipart(tmp_path):
    """The existing 409 `support_case_closed` guard must still fire
    for multipart submissions — we don't want a clever client to
    sneak around the closed-case rule by switching content-type."""
    from app.blueprints.mobile_support_api import reply_support_case
    from werkzeug.datastructures import FileStorage
    app = _make_app(tmp_path)
    user = _fake_user()
    case = mock.Mock()
    case.id = 10
    case.status = 'closed'  # ← guard trigger
    png = FileStorage(
        stream=io.BytesIO(b'\x89PNG'),
        filename='shot.png', content_type='image/png',
    )
    with app.test_request_context(
        '/api/v1/support/cases/ticket/10/reply',
        method='POST',
        data={'body': 'try anyway', 'attachments': [png]},
        content_type='multipart/form-data',
    ), _patch_user(user), \
         _patch_case_for_user('ticket', case):
        resp = reply_support_case('ticket', 10)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['code'] == 'support_case_closed'
