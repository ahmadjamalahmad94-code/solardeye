"""v101 — Firebase Cloud Messaging dispatcher.

Single entry point: ``send_push_to_user(user_id, title, body, data=None)``.
Wraps the ``firebase-admin`` Python SDK so the rest of the codebase
never has to know about Google's APIs directly.

Design choices (see ``docs/PUSH_BACKEND_SPEC.md`` in the mobile repo
for the full rationale):

* **Lazy init.** ``firebase_admin.initialize_app`` is called on the
  first ``send_push_to_user`` call, not at import time. This keeps
  the module importable even before ``firebase-admin`` is installed
  (e.g. immediately after a ``requirements.txt`` bump but before
  pip has run on the deploy host) and even when the credentials
  env var is absent (dev workstations without secrets).
* **Lazy import of firebase-admin.** Same reasoning — keeps
  ``from app.services.push_dispatch import send_push_to_user``
  working in environments where the SDK isn't installed at all.
  The function silently no-ops in that case.
* **Per-token send loop, not multicast.** Token counts per user
  are tiny (typically 1-3); multicast obscures per-token errors.
* **Auto-prune on UnregisteredError.** Google's signal that the
  install is gone (uninstall, app data cleared, token rotated).
  We flip ``is_active=False`` and ``revoked_at=now()`` so
  subsequent dispatches skip the dead token.
* **No token in logs, ever.** Per ``PUSH_BACKEND_SPEC §10.3`` the
  full FCM token is a per-install secret; including it in any
  log line would leak it to Render logs / observability.

Channels are wired into the existing ``dispatch_notification``
flow at ``app/blueprints/notifications.py`` — see the ``'push'``
and ``'all'`` branches there.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from ..extensions import db
from ..models import MobilePushToken

_log = logging.getLogger(__name__)
_initialized = False


def _push_enabled_env() -> bool:
    """Honour ``PUSH_ENABLED=false`` as an explicit kill switch.

    Defaults to ``True`` when unset so that simply providing
    ``GOOGLE_APPLICATION_CREDENTIALS`` is enough to enable push.
    """
    raw = (os.environ.get('PUSH_ENABLED') or 'true').strip().lower()
    return raw not in ('false', '0', 'no', 'off')


def _ensure_init() -> None:
    """Lazily initialise the Firebase Admin SDK.

    Returns silently in any of these cases:
      * Already initialised once this process.
      * ``GOOGLE_APPLICATION_CREDENTIALS`` env var missing.
      * The credentials file at that path doesn't exist.
      * ``PUSH_ENABLED=false`` is set.
      * ``firebase-admin`` is not installed (ImportError).

    A subsequent call to ``send_push_to_user`` then returns
    ``(0, 0)`` instead of raising, so the rest of the dispatch
    flow (Telegram / SMS / NotificationCenter mirror) continues
    untouched.
    """
    global _initialized
    if _initialized:
        return
    if not _push_enabled_env():
        return
    cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not cred_path:
        return
    if not os.path.exists(cred_path):
        _log.warning(
            'GOOGLE_APPLICATION_CREDENTIALS points at a missing file; '
            'push notifications disabled.'
        )
        return
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        _log.warning(
            'firebase-admin is not installed; push notifications disabled.'
        )
        return
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(cred_path))
    _initialized = True


def _reset_for_tests() -> None:
    """Test-only: clear the cached init flag so each test starts clean.

    The production code path never calls this. It exists so unit
    tests can exercise the lazy-init branches independently.
    """
    global _initialized
    _initialized = False


def _import_messaging():
    """Lazy import indirection for ``firebase_admin.messaging``.

    Pulled out as a module-level helper so unit tests can
    ``monkeypatch.setattr(push_dispatch, '_import_messaging', ...)``
    to inject a fake messaging module without juggling
    ``sys.modules``. Returns ``None`` when ``firebase-admin`` is not
    installed — the caller short-circuits to ``(0, 0)``.
    """
    try:
        from firebase_admin import messaging  # noqa: WPS433 — lazy by design
        return messaging
    except ImportError:
        return None


def send_push_to_user(
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """Fan out a single notification to every active token for a user.

    Returns ``(sent_count, failed_count)``. Returns ``(0, 0)`` and
    no-ops when:
      * Firebase isn't initialised (no creds / SDK / opt-out).
      * The user has no active ``mobile_push_token`` rows.

    On per-token ``messaging.UnregisteredError`` the row is marked
    inactive so future calls don't keep trying. Every other
    exception is caught and counted as a failure — one bad token
    must never abort the loop for the others.
    """
    _ensure_init()
    if not _initialized:
        return (0, 0)

    rows = MobilePushToken.query.filter_by(
        user_id=user_id, is_active=True
    ).all()
    if not rows:
        return (0, 0)

    messaging = _import_messaging()
    if messaging is None:
        return (0, 0)

    sent = 0
    failed = 0
    now = datetime.utcnow()
    for row in rows:
        try:
            msg = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data={k: str(v) for k, v in (data or {}).items()},
                token=row.token,
                android=messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        sound='default',
                    ),
                ),
            )
            messaging.send(msg)
            sent += 1
            row.last_seen_at = now
        except messaging.UnregisteredError:
            row.is_active = False
            row.revoked_at = now
            failed += 1
            _log.info(
                'FCM marked token unregistered for user_id=%s; pruning.',
                user_id,
            )
        except Exception as exc:  # noqa: BLE001 — must not abort the loop
            failed += 1
            _log.warning(
                'FCM send failed for user_id=%s: %s',
                user_id, exc.__class__.__name__,
            )

    db.session.commit()
    return (sent, failed)
