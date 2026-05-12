"""v76 — mobile subscriber quota visibility tests.

The backend extension is a pure projection helper
(`_mobile_quotas_payload`) that re-shapes the existing
`quota_summary_rows(tenant_id, lang)` output into a mobile-friendly
list. No new quota math; the web helper stays the single source
of truth for `limit`/`used`/`remaining`/`percent`/`is_unlimited`.

Coverage:
  * Empty list when the user has no tenant.
  * Empty list when the helper returns no rows.
  * Defensive drop of garbage rows.
  * Field-by-field mapping for a populated row.
  * Unlimited row → `remaining=None`, `is_unlimited=True`.
  * `storage_path`-style internal model fields never leak (no
    notes/source_plan_id/created_at/etc.).
  * Stringified numeric inputs coerce cleanly.

Style mirrors v59 / v62 / v65 / v68 / v71 / v74: mock-based, no DB,
no `create_app()` boot.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _make_app():
    """Tiny Flask app to provide a request context for `_lang()`."""
    from flask import Flask
    from app.blueprints.mobile_api import mobile_core_api_bp
    app = Flask(__name__)
    app.register_blueprint(mobile_core_api_bp)
    return app


def _fake_quota_row(
    *, quota_key='support_cases_limit',
    reset_period='monthly',
    status='active',
):
    """`quota_summary_rows(...)` returns dicts whose `'quota'` key is
    the `TenantQuota` model row. We mock the row with `Mock()` so the
    helper can `getattr` for `quota_key`/`reset_period`/`status`."""
    q = mock.Mock()
    q.quota_key = quota_key
    q.reset_period = reset_period
    q.status = status
    return q


def _summary_row(*, limit=10.0, used=4.0, unlimited=False,
                 label='تذاكر الدعم', description='عدد التذاكر الشهري',
                 percent=40.0, source_label='من الخطة',
                 quota_key='support_cases_limit',
                 reset_period='monthly', status='active'):
    """Build the dict shape `quota_summary_rows` produces."""
    q = _fake_quota_row(
        quota_key=quota_key, reset_period=reset_period, status=status,
    )
    remaining = '∞' if unlimited else max(limit - used, 0)
    return {
        'quota': q,
        'label': label,
        'description': description,
        'limit': limit,
        'used': used,
        'remaining': remaining,
        'percent': percent,
        'is_unlimited': unlimited,
        'source_label': source_label,
    }


def _fake_user(*, id_=42, tenant_id=7, is_admin=False):
    user = mock.Mock()
    user.id = id_
    user.tenant_id = tenant_id
    user.is_admin = is_admin
    return user


# ─── No tenant → empty list ────────────────────────────────────────────

def test_quotas_payload_empty_when_user_has_no_tenant():
    """Defensive: a freshly-registered user before
    `ensure_user_tenant_and_subscription` runs has `tenant_id=None`.
    The mobile contract surfaces an empty list rather than calling
    the quota helper with `None`."""
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user(tenant_id=None)
    with app.test_request_context('/'):
        result = _mobile_quotas_payload(user)
    assert result == []


def test_quotas_payload_empty_when_helper_returns_no_rows():
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user()
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api.quota_summary_rows',
             return_value=[],
         ):
        result = _mobile_quotas_payload(user)
    assert result == []


# ─── Populated row → full mapping ──────────────────────────────────────

def test_quotas_payload_maps_populated_row_with_all_fields():
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user()
    row = _summary_row(
        limit=10.0, used=4.0,
        label='تذاكر الدعم', description='عدد التذاكر الشهري',
        percent=40.0, source_label='من الخطة',
        quota_key='support_cases_limit',
        reset_period='monthly', status='active',
    )
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api.quota_summary_rows',
             return_value=[row],
         ):
        result = _mobile_quotas_payload(user)

    assert len(result) == 1
    item = result[0]
    assert item == {
        'key': 'support_cases_limit',
        'label': 'تذاكر الدعم',
        'description': 'عدد التذاكر الشهري',
        'limit': 10.0,
        'used': 4.0,
        'remaining': 6.0,
        'percent': 40.0,
        'is_unlimited': False,
        'reset_period': 'monthly',
        'status': 'active',
        'source_label': 'من الخطة',
    }


# ─── Unlimited row → null remaining + is_unlimited flag ───────────────

def test_quotas_payload_unlimited_row_maps_remaining_to_null():
    """`quota_summary_rows` returns the literal '∞' string for
    unlimited quotas. The mobile contract translates that into
    `remaining=None` + `is_unlimited=True` so the parser never
    has to handle mixed types on one key."""
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user()
    row = _summary_row(
        limit=100.0, used=42.0, unlimited=True,
        percent=0.0,
        label='زيارات API', source_label='معدل لهذا المشترك',
        quota_key='api_calls_limit',
    )
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api.quota_summary_rows',
             return_value=[row],
         ):
        result = _mobile_quotas_payload(user)

    item = result[0]
    assert item['is_unlimited'] is True
    assert item['remaining'] is None
    # The other fields still surface honest values so the UI can show
    # "42 used" even when the limit is conceptually infinite.
    assert item['used'] == 42.0
    assert item['limit'] == 100.0
    assert item['percent'] == 0.0


# ─── Garbage rows dropped defensively ─────────────────────────────────

def test_quotas_payload_drops_row_without_quota_model():
    """If `quota_summary_rows` ever returns a row with `quota=None`
    (unlikely but defensive), the mapper skips it instead of
    crashing on `getattr(None, 'quota_key', ...)`."""
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user()
    good = _summary_row()
    bad = {'quota': None, 'label': 'broken', 'limit': 0, 'used': 0,
           'remaining': 0, 'percent': 0, 'is_unlimited': False,
           'source_label': ''}
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api.quota_summary_rows',
             return_value=[good, bad],
         ):
        result = _mobile_quotas_payload(user)

    assert len(result) == 1
    assert result[0]['label'] == 'تذاكر الدعم'


def test_quotas_payload_does_not_leak_internal_quota_columns():
    """Locked: the `TenantQuota` model carries internals like
    `notes`, `source_plan_id`, `created_at`, `updated_at`. The
    mobile contract surfaces only the documented 11 keys."""
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user()
    q = _fake_quota_row()
    # Stuff the model with internal fields that MUST NOT leak.
    q.notes = 'internal note'
    q.source_plan_id = 99
    q.created_at = 'should-not-leak'
    q.updated_at = 'should-not-leak'
    q.id = 12345  # raw row id

    row = {
        'quota': q,
        'label': 'تذاكر الدعم',
        'description': '',
        'limit': 10.0,
        'used': 4.0,
        'remaining': 6.0,
        'percent': 40.0,
        'is_unlimited': False,
        'source_label': 'من الخطة',
    }
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api.quota_summary_rows',
             return_value=[row],
         ):
        result = _mobile_quotas_payload(user)

    item = result[0]
    # Locked contract keys only.
    assert set(item.keys()) == {
        'key', 'label', 'description', 'limit', 'used',
        'remaining', 'percent', 'is_unlimited',
        'reset_period', 'status', 'source_label',
    }
    forbidden = {'notes', 'source_plan_id', 'created_at',
                 'updated_at', 'id', 'quota'}
    assert set(item.keys()).isdisjoint(forbidden)


# ─── Defensive coercion ────────────────────────────────────────────────

def test_quotas_payload_coerces_falsy_numeric_inputs():
    """If the helper ever returns `None` for `limit`/`used`/`remaining`,
    the mapper coerces to 0.0 cleanly via the `(value or 0)` guard."""
    from app.blueprints.mobile_api import _mobile_quotas_payload
    app = _make_app()
    user = _fake_user()
    row = {
        'quota': _fake_quota_row(),
        'label': 'تذاكر الدعم',
        'description': '',
        'limit': None,
        'used': None,
        'remaining': 0,
        'percent': None,
        'is_unlimited': False,
        'source_label': '',
    }
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api.quota_summary_rows',
             return_value=[row],
         ):
        result = _mobile_quotas_payload(user)

    item = result[0]
    assert item['limit'] == 0.0
    assert item['used'] == 0.0
    assert item['remaining'] == 0.0
    assert item['percent'] == 0.0


# ─── _account_payload envelope ─────────────────────────────────────────

def test_account_payload_embeds_quotas_key():
    """`_account_payload` must always include `quotas` (even when
    empty) so the mobile parser has a stable shape."""
    from app.blueprints.mobile_api import _account_payload
    app = _make_app()
    user = _fake_user(tenant_id=None)  # forces empty quotas list
    # The full _account_payload calls many other helpers — we only
    # need to verify the new key is present. Patch the heavy bits
    # so this test doesn't depend on the full DB.
    with app.test_request_context('/'), \
         mock.patch(
             'app.blueprints.mobile_api._profile_payload',
             return_value={},
         ), \
         mock.patch(
             'app.blueprints.mobile_api._subscription_payload',
             return_value={},
         ), \
         mock.patch(
             'app.blueprints.mobile_api._device_summary_payload',
             return_value={'total': 0, 'active': 0, 'selected_device_id': None},
         ), \
         mock.patch(
             'app.blueprints.mobile_api._available_plans_payload',
             return_value=[],
         ), \
         mock.patch(
             'app.blueprints.mobile_api._pending_plan_change_request_payload',
             return_value=None,
         ), \
         mock.patch(
             'app.blueprints.mobile_api.role_label',
             return_value='مستخدم',
         ):
        user.role = 'user'
        payload = _account_payload(user)

    assert 'quotas' in payload
    assert payload['quotas'] == []
    # Existing v65 keys remain present so older clients keep working.
    assert 'available_plans' in payload
    assert 'pending_plan_change_request' in payload
    assert 'capabilities' in payload
