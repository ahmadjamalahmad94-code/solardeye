"""v80 — quota tracking + effective-summary fix.

Three narrow product fixes verified here:

  Part A — `quota_summary_rows` + `effective_quota_rows_for_tenant`
           now apply the same "override wins over plan" rule the
           enforcement engine has always used per-key, so the
           subscriber profile / admin profile stop showing duplicate
           or contradictory pairs like "used=85 / limit=0" alongside
           "used=20 / limit=3" for the same key.

  Part B — `devices_limit` is now incremented on real device
           creation through both the mobile and web flows. The
           existing stock-based ceiling (`allowed_device_limit`)
           stays unchanged; the new tracker is a usage-flow
           counter that climbs truthfully even past a soft-exceeded
           row.

  Part C — `api_calls_limit` is now tracked centrally via a
           `before_request` hook on `mobile_core_api_bp`. Auth +
           health + CORS preflight are excluded; the per-request
           flag on `flask.g` prevents double-counting.

Style mirrors v59 / v62 / v68 / v74 / v76 / v78: mock-based, no DB
boot, no `create_app()`.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Part A — effective_quota_rows_for_tenant + quota_summary_rows
# ═══════════════════════════════════════════════════════════════════════


def _quota_row(
    *, id_=1, key='devices_limit', period='monthly', limit=3.0, used=0.0,
    source='plan', status='active', unlimited=False,
    label=None, notes=None,
):
    """Build a real-shaped fake `TenantQuota` row.

    We construct a `mock.Mock()` so the helper can introspect both
    direct attributes (`q.quota_key`, `q.limit_value`, …) and the
    `getattr(q, 'source', ...)` fallback the engine relies on.
    """
    q = mock.Mock()
    q.id = id_
    q.quota_key = key
    q.reset_period = period
    q.limit_value = limit
    q.used_value = used
    q.source = source
    q.status = status
    q.is_unlimited = unlimited
    q.quota_label = label or f'{key} label'
    q.notes = notes or ''
    return q


def _patch_quotas(rows):
    """Patch `quotas_for_tenant(...)` to return the supplied list.

    Required because the helper hits the SQLAlchemy session
    otherwise. We patch at the module path the engine uses
    internally so both effective + summary helpers see the same
    rows.
    """
    return mock.patch(
        'app.services.quota_engine.quotas_for_tenant',
        return_value=list(rows),
    )


def test_effective_helper_drops_plan_row_when_override_exists_for_same_key():
    """The classic v80 reproduction: a tenant has both a plan-row
    (`source='plan'`, `used=85, limit=100`) and a manual override
    (`source='manual'`, `used=20, limit=50`) for `api_calls_limit`.
    The effective helper must surface only the override — that's
    the row the enforcement engine consults, and the display must
    match."""
    from app.services.quota_engine import effective_quota_rows_for_tenant

    plan_row = _quota_row(
        id_=1, key='api_calls_limit', limit=100.0, used=85.0,
        source='plan',
    )
    override_row = _quota_row(
        id_=2, key='api_calls_limit', limit=50.0, used=20.0,
        source='manual',
    )
    with _patch_quotas([plan_row, override_row]):
        out = effective_quota_rows_for_tenant(7)

    assert len(out) == 1
    assert out[0].id == 2
    assert out[0].source == 'manual'


def test_effective_helper_returns_plan_rows_when_no_override_exists():
    """A tenant with only plan rows for a key keeps them — the
    helper only hides plan rows when at least one override exists
    for that same key."""
    from app.services.quota_engine import effective_quota_rows_for_tenant

    plan_a = _quota_row(
        id_=1, key='telegram_limit', limit=50.0, used=10.0, source='plan',
    )
    plan_b = _quota_row(
        id_=2, key='sms_limit', limit=20.0, used=2.0, source='plan',
    )
    with _patch_quotas([plan_a, plan_b]):
        out = effective_quota_rows_for_tenant(7)

    assert sorted(q.id for q in out) == [1, 2]


def test_effective_helper_skips_paused_rows():
    """Paused / exhausted rows are filtered before the override
    rule runs — they participate in neither display nor
    enforcement."""
    from app.services.quota_engine import effective_quota_rows_for_tenant

    paused = _quota_row(
        id_=1, key='reports_limit', limit=10.0, status='paused',
    )
    active = _quota_row(
        id_=2, key='reports_limit', limit=10.0, status='active',
    )
    with _patch_quotas([paused, active]):
        out = effective_quota_rows_for_tenant(7)

    assert len(out) == 1
    assert out[0].id == 2


def test_effective_helper_empty_tenant_returns_empty_list():
    from app.services.quota_engine import effective_quota_rows_for_tenant
    assert effective_quota_rows_for_tenant(None) == []


def test_summary_rows_consumes_effective_set_only():
    """`quota_summary_rows` was the source of the misleading "85 /
    0" pairs because it iterated raw rows. After v80 it reads
    through the effective helper so display matches enforcement."""
    from app.services.quota_engine import quota_summary_rows

    plan_row = _quota_row(
        id_=1, key='devices_limit', limit=0.0, used=85.0, source='plan',
        # Stale plan-row with limit=0 — historically produced the
        # misleading "85 / 0" display pair.
    )
    override_row = _quota_row(
        id_=2, key='devices_limit', limit=3.0, used=2.0, source='manual',
    )
    with _patch_quotas([plan_row, override_row]):
        rows = quota_summary_rows(7, lang='ar')

    assert len(rows) == 1
    # The override row is what reaches the UI — `used=2 / limit=3`.
    assert rows[0]['limit'] == 3.0
    assert rows[0]['used'] == 2.0
    # And the engine has surfaced the right row identity, so any
    # edit/delete action on the summary card targets the override.
    assert rows[0]['quota'].id == 2


# ═══════════════════════════════════════════════════════════════════════
# Part B — devices_limit tracking
# ═══════════════════════════════════════════════════════════════════════


def test_record_usage_for_user_unconditionally_bumps_effective_rows():
    """The new `record_usage_for_user` helper is the foundation of
    both Part B and Part C — it must bump every non-unlimited
    effective row even when the row is already over its limit, so
    truthful "used > limit" display is preserved."""
    from app.services.quota_engine import record_usage_for_user

    user = mock.Mock()
    user.id = 1
    user.is_admin = False

    over_limit = _quota_row(
        id_=1, key='devices_limit', limit=3.0, used=5.0, source='manual',
    )
    tenant = mock.Mock()
    tenant.id = 7

    with mock.patch(
        'app.services.quota_engine.tenant_for_user', return_value=tenant,
    ), mock.patch(
        'app.services.quota_engine.effective_quota_rows',
        return_value=[over_limit],
    ):
        result = record_usage_for_user(user, 'devices_limit', 1)

    assert result is over_limit
    assert over_limit.used_value == 6.0


def test_record_usage_for_user_skips_unlimited_rows():
    """Unlimited rows stay at zero — they don't carry a meaningful
    "used" counter and would never be enforced anyway."""
    from app.services.quota_engine import record_usage_for_user

    user = mock.Mock(); user.id = 1; user.is_admin = False
    unlimited = _quota_row(
        id_=1, key='api_calls_limit', limit=0.0, used=0.0,
        source='plan', unlimited=True,
    )
    tenant = mock.Mock(); tenant.id = 7
    with mock.patch(
        'app.services.quota_engine.tenant_for_user', return_value=tenant,
    ), mock.patch(
        'app.services.quota_engine.effective_quota_rows',
        return_value=[unlimited],
    ):
        record_usage_for_user(user, 'api_calls_limit', 1)

    assert unlimited.used_value == 0.0


def test_record_usage_for_user_is_a_noop_for_admin_and_no_tenant():
    """Admin requests / users without a tenant must never affect
    quota counters."""
    from app.services.quota_engine import record_usage_for_user

    admin = mock.Mock(); admin.is_admin = True
    assert record_usage_for_user(admin, 'api_calls_limit', 1) is None

    plain = mock.Mock(); plain.is_admin = False
    with mock.patch(
        'app.services.quota_engine.tenant_for_user', return_value=None,
    ), mock.patch(
        'app.services.quota_engine.effective_quota_rows',
        return_value=[],
    ):
        assert record_usage_for_user(plain, 'api_calls_limit', 1) is None


def test_mobile_device_create_bumps_devices_limit():
    """End-to-end check that the v80 wiring is present on the
    mobile create path: a successful device-create call invokes
    `record_usage_for_user(..., 'devices_limit', 1)` exactly once."""
    from flask import Flask
    from app.blueprints.mobile_api import (
        mobile_core_api_bp, mobile_device_create, AppDevice,
    )
    app = Flask(__name__)
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_core_api_bp)

    user = mock.Mock()
    user.id = 5
    user.is_admin = False
    user.tenant_id = 9
    user.preferred_device_id = None
    user.preferred_device_type = None

    # Mock the device count + ceiling so create proceeds.
    device_chain = mock.Mock()
    device_chain.filter_by.return_value = device_chain
    device_chain.count.return_value = 0

    with app.test_request_context(
        '/api/mobile/devices',
        method='POST',
        json={'name': 'New', 'device_type': 'deye'},
    ), mock.patch(
        'app.blueprints.mobile_api._require_bearer_user',
        return_value=(user, None),
    ), mock.patch(
        'app.blueprints.mobile_api._strict_json_object',
        return_value=({'name': 'New', 'device_type': 'deye'}, None),
    ), mock.patch.object(
        AppDevice, 'query', device_chain,
    ), mock.patch(
        'app.blueprints.mobile_api.allowed_device_limit',
        return_value=3,
    ), mock.patch(
        'app.blueprints.mobile_api._mobile_apply_device_fields',
        return_value=None,
    ), mock.patch(
        'app.blueprints.mobile_api._mobile_device_detail_payload',
        return_value={'id': 42},
    ), mock.patch(
        'app.blueprints.mobile_api._device_summary_payload',
        return_value={'total': 1, 'active': 1, 'selected_device_id': 42},
    ), mock.patch(
        'app.blueprints.mobile_api.db.session.add',
    ), mock.patch(
        'app.blueprints.mobile_api.db.session.flush',
    ), mock.patch(
        'app.blueprints.mobile_api.db.session.commit',
    ), mock.patch(
        'app.blueprints.mobile_api._record_usage_for_user',
    ) as record_mock:
        resp = mobile_device_create()

    assert resp.status_code == 201
    # The tracker was hit once with the expected (user, key, amount).
    assert record_mock.call_count == 1
    call_args = record_mock.call_args
    assert call_args.args[:3] == (user, 'devices_limit', 1)


def test_mobile_device_create_still_enforces_stock_ceiling():
    """Belt-and-braces: the `allowed_device_limit` hard ceiling must
    keep blocking creates once a tenant is at-stock. v80 must not
    accidentally drop the existing 403 behaviour."""
    from flask import Flask
    from app.blueprints.mobile_api import (
        mobile_core_api_bp, mobile_device_create, AppDevice,
    )
    app = Flask(__name__)
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_core_api_bp)

    user = mock.Mock(); user.id = 5; user.is_admin = False
    user.tenant_id = 9

    device_chain = mock.Mock()
    device_chain.filter_by.return_value = device_chain
    device_chain.count.return_value = 3  # already at stock

    with app.test_request_context(
        '/api/mobile/devices', method='POST',
    ), mock.patch(
        'app.blueprints.mobile_api._require_bearer_user',
        return_value=(user, None),
    ), mock.patch(
        'app.blueprints.mobile_api._strict_json_object',
        return_value=({'name': 'x'}, None),
    ), mock.patch.object(
        AppDevice, 'query', device_chain,
    ), mock.patch(
        'app.blueprints.mobile_api.allowed_device_limit',
        return_value=3,
    ), mock.patch(
        'app.blueprints.mobile_api._record_usage_for_user',
    ) as record_mock:
        resp = mobile_device_create()

    assert resp.status_code == 403
    body = resp.get_json()
    assert body['code'] == 'device_limit_reached'
    # Critical: no usage tick when the create itself was refused.
    record_mock.assert_not_called()


def test_device_edit_does_not_increment_devices_limit():
    """Edit / PATCH must not bump the counter — only real
    additions count. We lock this contract via source inspection
    rather than running the full PATCH route end-to-end: the
    tracker call site is a single line in `mobile_device_create`
    and must NOT appear anywhere in the body of
    `mobile_device_update`.

    Source-level check is more reliable here than a route-level
    mock because the update handler walks several DB helpers that
    are awkward to fully stub without booting the real app."""
    import inspect
    from app.blueprints.mobile_api import (
        mobile_device_create, mobile_device_update,
    )
    create_src = inspect.getsource(mobile_device_create)
    update_src = inspect.getsource(mobile_device_update)
    # Sanity: the create path does carry the tracker call.
    assert '_record_usage_for_user' in create_src
    assert "'devices_limit'" in create_src
    # Locked: the update path must NOT call the tracker.
    assert '_record_usage_for_user' not in update_src


# ═══════════════════════════════════════════════════════════════════════
# Part C — api_calls_limit centralized tracker
# ═══════════════════════════════════════════════════════════════════════


def _api_call_app():
    """Tiny Flask app with the mobile-core blueprint mounted so the
    `before_request` hook fires."""
    from flask import Flask
    from app.blueprints.mobile_api import mobile_core_api_bp
    app = Flask(__name__)
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_core_api_bp)
    return app


def test_api_call_hook_increments_on_protected_path():
    """A GET to `/api/mobile/health` is auth-free so it should NOT
    count, but `/api/mobile/profile` (a protected user surface)
    should fire the tracker exactly once."""
    app = _api_call_app()
    user = mock.Mock(); user.id = 1; user.is_admin = False
    with app.test_request_context('/api/mobile/profile', method='GET'), \
         mock.patch(
             'app.blueprints.mobile_api.user_from_bearer_or_session',
             return_value=user,
         ), \
         mock.patch(
             'app.blueprints.mobile_api._track_api_call_for_user',
         ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        tracker.assert_called_once()


def test_api_call_hook_skips_auth_namespace():
    """A login/refresh/me call must NEVER count against the
    subscriber's API budget — they need to be able to authenticate
    even when the quota is exhausted."""
    app = _api_call_app()
    user = mock.Mock(); user.id = 1; user.is_admin = False
    with app.test_request_context(
        '/api/mobile/auth/login', method='POST',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=user,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
    ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        tracker.assert_not_called()


def test_api_call_hook_skips_health_endpoint():
    """Health probes are stateless infrastructure pings; charging
    for them would be dishonest."""
    app = _api_call_app()
    user = mock.Mock(); user.id = 1; user.is_admin = False
    with app.test_request_context(
        '/api/mobile/health', method='GET',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=user,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
    ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        tracker.assert_not_called()


def test_api_call_hook_skips_options_preflight():
    """CORS preflight `OPTIONS` requests must never count — they're
    browser plumbing, not subscriber traffic."""
    app = _api_call_app()
    user = mock.Mock(); user.id = 1; user.is_admin = False
    with app.test_request_context(
        '/api/mobile/profile', method='OPTIONS',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=user,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
    ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        tracker.assert_not_called()


def test_api_call_hook_skips_unauthenticated_request():
    """If the bearer/session resolver returns `None`, the request
    is anonymous and we have no tenant to charge. The hook must
    skip silently — never crash."""
    app = _api_call_app()
    with app.test_request_context(
        '/api/mobile/profile', method='GET',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=None,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
    ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        tracker.assert_not_called()


def test_api_call_hook_skips_admin_users():
    """Admin/staff API traffic is operational; it must never
    consume subscriber quota."""
    app = _api_call_app()
    admin = mock.Mock(); admin.id = 1; admin.is_admin = True
    with app.test_request_context(
        '/api/mobile/profile', method='GET',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=admin,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
    ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        tracker.assert_not_called()


def test_api_call_hook_does_not_double_count_on_same_request():
    """The hook sets `g._v80_api_call_counted` on first success so
    accidental re-entry (e.g. a sub-call that triggers another
    blueprint cycle inside the same request) cannot double-count."""
    app = _api_call_app()
    user = mock.Mock(); user.id = 1; user.is_admin = False
    with app.test_request_context(
        '/api/mobile/profile', method='GET',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=user,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
    ) as tracker:
        from app.blueprints.mobile_api import _record_api_call_quota
        _record_api_call_quota()
        _record_api_call_quota()  # second invocation in same request
        _record_api_call_quota()  # third — also a no-op
        tracker.assert_called_once()


def test_api_call_hook_swallows_tracker_exceptions():
    """The hook must NEVER let a quota bookkeeping failure derail a
    legitimate API request. A `RuntimeError` from the tracker is
    swallowed silently."""
    app = _api_call_app()
    user = mock.Mock(); user.id = 1; user.is_admin = False
    with app.test_request_context(
        '/api/mobile/profile', method='GET',
    ), mock.patch(
        'app.blueprints.mobile_api.user_from_bearer_or_session',
        return_value=user,
    ), mock.patch(
        'app.blueprints.mobile_api._track_api_call_for_user',
        side_effect=RuntimeError('db went away'),
    ):
        from app.blueprints.mobile_api import _record_api_call_quota
        # Must return cleanly — no exception propagates out of the
        # hook.
        assert _record_api_call_quota() is None
