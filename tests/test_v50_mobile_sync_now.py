"""v50 — mobile sync-now error classifier tests.

The endpoint's heavy lifting is delegated to ``sync_now_internal``
(in ``app/blueprints/main.py``), which is already exercised by the
existing v33 scheduler suite and runs real provider clients in dev.
The mobile-side surface that's purely testable without a Flask app
context is the small ``_mobile_sync_error_payload`` classifier — it
maps Python exceptions to the `(status, code, message)` tuple the
mobile UI consumes. Locking that contract is what these tests do.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def test_value_error_classifies_as_setup_not_ready():
    """`_device_sync_ready` raises ValueError for the "missing
    credentials / device inactive" case. Mobile UI should show this
    as a calm "complete setup first" message, not a sync failure."""
    from app.blueprints.mobile_api import _mobile_sync_error_payload
    status, code, message = _mobile_sync_error_payload(
        ValueError('أكمل إعدادات الجهاز الحالي أولًا: App ID')
    )
    assert status == 400
    assert code == 'setup_not_ready'
    assert 'App ID' in message


def test_value_error_with_blank_message_uses_friendly_arabic_fallback():
    from app.blueprints.mobile_api import _mobile_sync_error_payload
    status, code, message = _mobile_sync_error_payload(ValueError(''))
    assert status == 400
    assert code == 'setup_not_ready'
    assert message == 'تعذّر التحقق من جاهزية الجهاز.'


def test_generic_exception_classifies_as_sync_failed():
    """Any exception that isn't ValueError comes from the provider
    client itself — wrong creds, network error, vendor API outage.
    Mobile UI should show this as a 502-style sync failure with the
    raw error message (trimmed)."""
    from app.blueprints.mobile_api import _mobile_sync_error_payload
    status, code, message = _mobile_sync_error_payload(
        RuntimeError('Deye token endpoint returned 401')
    )
    assert status == 502
    assert code == 'sync_failed'
    assert 'Deye token endpoint returned 401' in message


def test_generic_exception_with_empty_message_uses_friendly_fallback():
    from app.blueprints.mobile_api import _mobile_sync_error_payload
    status, code, message = _mobile_sync_error_payload(RuntimeError(''))
    assert status == 502
    assert code == 'sync_failed'
    assert message == 'فشلت محاولة المزامنة.'


def test_very_long_exception_message_is_capped():
    """A verbose third-party exception (e.g. a 5 KB JSON dump from a
    cloud API) must not blow up the mobile snack-bar copy. The
    classifier caps the message at 240 chars."""
    from app.blueprints.mobile_api import _mobile_sync_error_payload
    payload = 'X' * 10_000
    _, code, message = _mobile_sync_error_payload(RuntimeError(payload))
    assert code == 'sync_failed'
    assert len(message) == 240
    assert message == 'X' * 240
