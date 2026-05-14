"""v101 — FCM push dispatcher unit tests.

Covers ``app/services/push_dispatch.py`` in isolation:
  P1  ``_ensure_init`` is a no-op when no credentials env var is set.
  P2  ``_ensure_init`` is a no-op when the env var points at a missing file.
  P3  ``_ensure_init`` honours PUSH_ENABLED=false as a kill switch.
  P4  ``send_push_to_user`` returns (0,0) without ever calling Firebase
      when the dispatcher is uninitialised.
  P5  ``send_push_to_user`` returns (0,0) when the user has no active
      tokens, even with a fully initialised dispatcher.
  P6  Happy path: one active token → one ``messaging.send`` call →
      returns (1,0) and bumps ``last_seen_at``.
  P7  ``UnregisteredError`` flips ``is_active=False`` and sets
      ``revoked_at``; returns (0,1).
  P8  Mixed-outcome batch: 2 succeed, 1 raises generic ``Exception``
      → returns (2,1) and the loop never aborts mid-way.
  P9  Tokens are NEVER passed to the logger (defensive — leaking a
      token to Render logs would let anyone push to that device).

These tests don't need a live database: they monkey-patch
``MobilePushToken.query`` to return in-memory fakes, and
``firebase_admin.messaging.send`` is stubbed via ``unittest.mock``.
"""
from __future__ import annotations

import io
import logging
import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── helpers ───────────────────────────────────────────────────────────────


def _fake_token_row(
    *,
    token: str = 'fake-fcm-token-abcdef0123456789',
    user_id: int = 1,
    is_active: bool = True,
):
    """A stand-in for a ``MobilePushToken`` ORM row.

    SimpleNamespace is enough — the dispatcher only reads/writes a
    handful of attributes (``token``, ``user_id``, ``is_active``,
    ``last_seen_at``, ``revoked_at``).
    """
    return SimpleNamespace(
        token=token,
        user_id=user_id,
        is_active=is_active,
        last_seen_at=None,
        revoked_at=None,
    )


def _patch_model_with_rows(monkeypatch, rows):
    """Replace ``push_dispatch.MobilePushToken`` with a MagicMock so
    ``MobilePushToken.query.filter_by(...).all()`` returns the canned
    list without touching Flask-SQLAlchemy's app-context-bound
    ``Model.query`` descriptor."""
    from app.services import push_dispatch as mod

    fake_model = mock.MagicMock()
    fake_model.query.filter_by.return_value.all.return_value = rows
    monkeypatch.setattr(mod, 'MobilePushToken', fake_model)
    return fake_model


def _patch_messaging(monkeypatch, fake_messaging):
    """Inject a fake ``firebase_admin.messaging`` via the module's
    own indirection helper. Avoids ``sys.modules`` juggling and the
    pitfalls of mocking submodule imports."""
    from app.services import push_dispatch as mod
    monkeypatch.setattr(mod, '_import_messaging', lambda: fake_messaging)


def _force_initialised(monkeypatch):
    """Bypass ``_ensure_init`` so tests focus on the send loop."""
    from app.services import push_dispatch as mod
    monkeypatch.setattr(mod, '_initialized', True)


def _patch_db_commit(monkeypatch):
    """Skip the SQLAlchemy commit — no live session in unit tests."""
    from app.services import push_dispatch as mod
    monkeypatch.setattr(mod.db.session, 'commit', lambda: None)


def _make_fake_messaging():
    """A MagicMock shaped like ``firebase_admin.messaging`` —
    ``Message`` / ``Notification`` / ``AndroidConfig`` /
    ``AndroidNotification`` are constructors, ``send`` is the
    method we drive in tests, and ``UnregisteredError`` is a real
    exception class so our ``except`` clause matches it."""
    fake = mock.MagicMock()
    fake.UnregisteredError = type('UnregisteredError', (Exception,), {})
    return fake


# ─── lazy-init behaviour (P1-P4) ──────────────────────────────────────────


def test_ensure_init_noop_without_credentials_env(monkeypatch):
    """P1 — no GOOGLE_APPLICATION_CREDENTIALS → silently bail."""
    from app.services import push_dispatch as mod
    mod._reset_for_tests()
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)
    mod._ensure_init()
    assert mod._initialized is False


def test_ensure_init_noop_when_credentials_file_missing(monkeypatch, tmp_path):
    """P2 — env var set but file does not exist → no init, no crash."""
    from app.services import push_dispatch as mod
    mod._reset_for_tests()
    monkeypatch.setenv(
        'GOOGLE_APPLICATION_CREDENTIALS', str(tmp_path / 'absent.json'),
    )
    mod._ensure_init()
    assert mod._initialized is False


def test_ensure_init_honours_push_enabled_kill_switch(monkeypatch, tmp_path):
    """P3 — PUSH_ENABLED=false short-circuits even when creds exist."""
    from app.services import push_dispatch as mod
    mod._reset_for_tests()
    fake_creds = tmp_path / 'creds.json'
    fake_creds.write_text('{}')
    monkeypatch.setenv('GOOGLE_APPLICATION_CREDENTIALS', str(fake_creds))
    monkeypatch.setenv('PUSH_ENABLED', 'false')
    mod._ensure_init()
    assert mod._initialized is False


def test_send_push_to_user_short_circuits_when_uninitialised(monkeypatch):
    """P4 — uninitialised dispatcher must return (0,0) WITHOUT
    touching MobilePushToken.query or firebase_admin.messaging."""
    from app.services import push_dispatch as mod
    mod._reset_for_tests()
    monkeypatch.delenv('GOOGLE_APPLICATION_CREDENTIALS', raising=False)

    fake_model = _patch_model_with_rows(monkeypatch, [])

    sent, failed = mod.send_push_to_user(user_id=1, title='t', body='b')
    assert (sent, failed) == (0, 0)
    fake_model.query.filter_by.assert_not_called()


# ─── send loop behaviour (P5-P8) ──────────────────────────────────────────


def test_send_returns_zero_when_user_has_no_tokens(monkeypatch):
    """P5 — initialised dispatcher + empty token list → (0,0)."""
    from app.services import push_dispatch as mod
    _force_initialised(monkeypatch)
    _patch_model_with_rows(monkeypatch, [])
    _patch_db_commit(monkeypatch)

    fake_messaging = _make_fake_messaging()
    _patch_messaging(monkeypatch, fake_messaging)

    sent, failed = mod.send_push_to_user(user_id=99, title='t', body='b')

    assert (sent, failed) == (0, 0)
    fake_messaging.send.assert_not_called()


def test_send_happy_path_one_token(monkeypatch):
    """P6 — single active token → one send call → (1,0), last_seen
    bumped to a real datetime."""
    from app.services import push_dispatch as mod
    _force_initialised(monkeypatch)
    row = _fake_token_row()
    _patch_model_with_rows(monkeypatch, [row])
    _patch_db_commit(monkeypatch)

    fake_messaging = _make_fake_messaging()
    _patch_messaging(monkeypatch, fake_messaging)

    sent, failed = mod.send_push_to_user(
        user_id=1, title='تحذير', body='البطارية 15%',
    )

    assert (sent, failed) == (1, 0)
    assert fake_messaging.send.call_count == 1
    assert isinstance(row.last_seen_at, datetime)
    assert row.is_active is True
    assert row.revoked_at is None


def test_send_marks_token_inactive_on_unregistered_error(monkeypatch):
    """P7 — UnregisteredError → row.is_active=False, revoked_at set,
    return (0,1)."""
    from app.services import push_dispatch as mod
    _force_initialised(monkeypatch)
    row = _fake_token_row()
    _patch_model_with_rows(monkeypatch, [row])
    _patch_db_commit(monkeypatch)

    fake_messaging = _make_fake_messaging()
    fake_messaging.send.side_effect = fake_messaging.UnregisteredError('gone')
    _patch_messaging(monkeypatch, fake_messaging)

    sent, failed = mod.send_push_to_user(user_id=1, title='t', body='b')

    assert (sent, failed) == (0, 1)
    assert row.is_active is False
    assert isinstance(row.revoked_at, datetime)


def test_send_loop_continues_through_per_token_failures(monkeypatch):
    """P8 — three rows; the middle one raises a generic Exception.
    The loop must finish, returning (2,1)."""
    from app.services import push_dispatch as mod
    _force_initialised(monkeypatch)
    rows = [
        _fake_token_row(token='aaaa1111'),
        _fake_token_row(token='bbbb2222'),
        _fake_token_row(token='cccc3333'),
    ]
    _patch_model_with_rows(monkeypatch, rows)
    _patch_db_commit(monkeypatch)

    fake_messaging = _make_fake_messaging()
    # First call ok, second raises, third ok.
    fake_messaging.send.side_effect = [None, RuntimeError('boom'), None]
    _patch_messaging(monkeypatch, fake_messaging)

    sent, failed = mod.send_push_to_user(user_id=7, title='t', body='b')

    assert (sent, failed) == (2, 1)
    # rows[0] and rows[2] succeeded; rows[1] generic failure does NOT
    # mark inactive (only UnregisteredError does).
    assert rows[0].is_active is True
    assert rows[1].is_active is True
    assert rows[2].is_active is True


# ─── security: never log tokens (P9) ──────────────────────────────────────


def test_failure_log_does_not_include_token(monkeypatch):
    """P9 — even when send raises, the captured log line must NOT
    contain the token string. Tokens are per-install secrets."""
    from app.services import push_dispatch as mod
    _force_initialised(monkeypatch)

    secret_token = 'super-secret-fcm-token-do-not-leak-9876543210'
    row = _fake_token_row(token=secret_token)
    _patch_model_with_rows(monkeypatch, [row])
    _patch_db_commit(monkeypatch)

    fake_messaging = _make_fake_messaging()
    fake_messaging.send.side_effect = RuntimeError(
        # If our code blindly stringified the exception, it could
        # contain the token. We deliberately bake the token into the
        # exception message to make the assertion meaningful.
        f'sent token {secret_token} got rejected',
    )
    _patch_messaging(monkeypatch, fake_messaging)

    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    mod._log.addHandler(handler)
    mod._log.setLevel(logging.DEBUG)
    try:
        mod.send_push_to_user(user_id=1, title='t', body='b')
    finally:
        mod._log.removeHandler(handler)

    captured = log_buf.getvalue()
    assert secret_token not in captured, (
        'FCM token leaked into log output — see PUSH_BACKEND_SPEC §10.3'
    )


# ─── notifications.py wiring smoke (P10) ──────────────────────────────────


def test_notifications_dispatch_recognises_push_channel():
    """P10 — the channel-mapping inside ``dispatch_notification`` must
    accept 'push' and 'all'. We assert the textual presence of the
    branches so a future refactor that drops them fails loudly."""
    import inspect

    from app.blueprints import notifications as mod

    src = inspect.getsource(mod.dispatch_notification)
    assert "'push'" in src or '"push"' in src, (
        "dispatch_notification lost its 'push' branch"
    )
    assert "'all'" in src or '"all"' in src, (
        "dispatch_notification lost its 'all' branch"
    )
    assert 'send_push_to_user' in src, (
        'dispatch_notification no longer references send_push_to_user'
    )
