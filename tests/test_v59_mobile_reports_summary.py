"""v59 — mobile reports summary endpoint tests.

The new route in `app/blueprints/mobile_devices_api.py` is a thin
wrapper around four things:

  1. `_validate_statistics_view` — reused verbatim from v56.
  2. `_validate_statistics_date` — reused verbatim from v56.
  3. `_device_allowed`            — owner-scope guard (existing).
  4. `_mobile_reports_summary_payload` — the new pure helper that
     turns canonical `compute_energy_stats(rows)` totals into the
     mobile-facing derived report metrics.

Coverage is split into two layers:

  * **Helper unit tests** — pure functions, no Flask / DB. Lock the
    math, the empty contract, and the validator semantics.
  * **Route handler tests** — drive `device_reports_summary(device_id)`
    inside a `Flask.test_request_context` with `AppDevice.query`,
    `Reading.query`, and `user_from_bearer_or_session` mocked. Lock
    the response shape, the validation-error wiring, and the
    owner-scope 404 path.

Style mirrors v43 / v45 / v49 / v50 — no DB, no `create_app()` boot.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Helper unit tests (no Flask context)
# ═══════════════════════════════════════════════════════════════════════

# ─── Sanity: validators are shared with v56 ────────────────────────────

def test_reports_validator_view_shares_v56_contract():
    from app.blueprints.mobile_devices_api import _validate_statistics_view
    # Same accept list (day / month) and same default-to-day for blank.
    assert _validate_statistics_view('day') == 'day'
    assert _validate_statistics_view('month') == 'month'
    assert _validate_statistics_view('') == 'day'
    assert _validate_statistics_view('week') is None
    assert _validate_statistics_view('year') is None


def test_reports_validator_date_shares_v56_contract():
    from app.blueprints.mobile_devices_api import _validate_statistics_date
    assert _validate_statistics_date(None) is True
    assert _validate_statistics_date('2026-05-12') is True
    assert _validate_statistics_date('2026/05/12') is False


# ─── Empty payload contract ────────────────────────────────────────────

def _empty_stats():
    return {
        'samples': 0,
        'data_gaps': 0,
        'solar_generated_kwh': 0.0,
        'home_consumed_kwh': 0.0,
        'solar_to_home_kwh': 0.0,
        'solar_to_battery_kwh': 0.0,
        'battery_to_home_kwh': 0.0,
        'grid_to_home_kwh': 0.0,
        'avg_battery_soc': 0.0,
        'max_solar_w': 0.0,
    }


def test_payload_empty_zeroes_every_derived_metric():
    """A period with no readings must NOT report 100% self-sufficiency
    just because the raw formula divides 0 by the 0.01 floor. Mobile
    surfaces the empty-state instead."""
    from app.blueprints.mobile_devices_api import _mobile_reports_summary_payload
    payload = _mobile_reports_summary_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats=_empty_stats(),
        generated_at='2026-05-12T10:00:00',
    )

    assert payload['view'] == 'day'
    assert payload['anchor'] == '2026-05-12'
    assert payload['title_hint'] == 'يوم 2026-05-12'
    assert payload['empty'] is True
    assert payload['generated_at'] == '2026-05-12T10:00:00'

    s = payload['summary']
    assert s['production_kwh'] == 0.0
    assert s['consumption_kwh'] == 0.0
    assert s['battery_in_kwh'] == 0.0
    assert s['grid_in_kwh'] == 0.0
    assert s['solar_share_percent'] == 0.0
    assert s['battery_share_percent'] == 0.0
    assert s['grid_share_percent'] == 0.0
    # The honest sentinel: empty must not claim 100% self-sufficiency.
    assert s['self_sufficiency_percent'] == 0.0
    assert s['average_load_w'] == 0.0
    assert s['solar_surplus_kwh'] == 0.0


# ─── Day-view derivations (mirrors energy.py::reports formulas) ────────

def test_payload_day_view_derivations_match_web_reports_formulas():
    """Worked example using the same formulas as `energy.py::reports`:
       solar_to_home   = 6 kWh
       battery_to_home = 2 kWh
       grid_to_home    = 2 kWh
       total_supplied  = 10 kWh
       → solar_share = 60.0, battery_share = 20.0, grid_share = 20.0
       → self_sufficiency = 100 - 20 = 80.0
       solar_generated  = 10 kWh; solar_to_home = 6
       → solar_surplus_kwh = 10 - 6 = 4.0
       home_consumed    = 10 kWh; samples = 100
       → average_load_w = 10/100 * 1000 = 100.0
    """
    from app.blueprints.mobile_devices_api import _mobile_reports_summary_payload
    stats = {
        'samples': 100,
        'data_gaps': 0,
        'solar_generated_kwh': 10.0,
        'home_consumed_kwh': 10.0,
        'solar_to_home_kwh': 6.0,
        'solar_to_battery_kwh': 4.0,
        'battery_to_home_kwh': 2.0,
        'grid_to_home_kwh': 2.0,
        'avg_battery_soc': 55.0,
        'max_solar_w': 2100.0,
    }
    payload = _mobile_reports_summary_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats=stats,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['view'] == 'day'
    assert payload['anchor'] == '2026-05-12'
    assert payload['empty'] is False

    s = payload['summary']
    assert s['production_kwh'] == 10.0
    assert s['consumption_kwh'] == 10.0
    assert s['battery_in_kwh'] == 4.0
    assert s['grid_in_kwh'] == 2.0
    assert s['solar_share_percent'] == 60.0
    assert s['battery_share_percent'] == 20.0
    assert s['grid_share_percent'] == 20.0
    assert s['self_sufficiency_percent'] == 80.0
    assert s['average_load_w'] == 100.0
    assert s['solar_surplus_kwh'] == 4.0


def test_payload_clamps_share_to_100_percent():
    from app.blueprints.mobile_devices_api import _mobile_reports_summary_payload
    stats = {
        'samples': 1,
        'data_gaps': 0,
        'solar_generated_kwh': 5.0,
        'home_consumed_kwh': 5.0,
        'solar_to_home_kwh': 5.0,
        'solar_to_battery_kwh': 0.0,
        'battery_to_home_kwh': 0.0,
        'grid_to_home_kwh': 0.0,
        'avg_battery_soc': 80.0,
        'max_solar_w': 2500.0,
    }
    payload = _mobile_reports_summary_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats=stats,
        generated_at='2026-05-12T10:00:00',
    )
    s = payload['summary']
    assert s['solar_share_percent'] == 100.0
    assert s['battery_share_percent'] == 0.0
    assert s['grid_share_percent'] == 0.0
    assert s['self_sufficiency_percent'] == 100.0


# ─── Month-view payload + anchor format ────────────────────────────────

def test_payload_month_view_uses_year_month_anchor():
    from app.blueprints.mobile_devices_api import _mobile_reports_summary_payload
    stats = {
        'samples': 2400,
        'data_gaps': 2,
        'solar_generated_kwh': 145.6,
        'home_consumed_kwh': 128.4,
        'solar_to_home_kwh': 90.0,
        'solar_to_battery_kwh': 35.0,
        'battery_to_home_kwh': 25.0,
        'grid_to_home_kwh': 13.4,
        'avg_battery_soc': 60.2,
        'max_solar_w': 4500.0,
    }
    payload = _mobile_reports_summary_payload(
        view='month',
        selected_date=datetime(2026, 5, 12),
        title_hint='شهر 2026-05',
        stats=stats,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['view'] == 'month'
    assert payload['anchor'] == '2026-05'
    assert payload['title_hint'] == 'شهر 2026-05'
    assert payload['empty'] is False

    s = payload['summary']
    assert s['production_kwh'] == 145.6
    assert s['consumption_kwh'] == 128.4
    assert s['battery_in_kwh'] == 35.0
    assert s['grid_in_kwh'] == 13.4
    assert s['solar_surplus_kwh'] == 55.6
    assert s['average_load_w'] == 53.5


# ─── Defensive coercion ────────────────────────────────────────────────

def test_payload_tolerates_partial_stats_keys():
    from app.blueprints.mobile_devices_api import _mobile_reports_summary_payload
    payload = _mobile_reports_summary_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats={},
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['empty'] is True
    s = payload['summary']
    assert s['production_kwh'] == 0.0
    assert s['self_sufficiency_percent'] == 0.0


def test_payload_treats_negative_solar_surplus_as_zero():
    from app.blueprints.mobile_devices_api import _mobile_reports_summary_payload
    stats = {
        'samples': 1,
        'data_gaps': 0,
        'solar_generated_kwh': 3.0,
        'home_consumed_kwh': 3.0,
        'solar_to_home_kwh': 5.0,  # drift case: > generated
        'solar_to_battery_kwh': 0.0,
        'battery_to_home_kwh': 0.0,
        'grid_to_home_kwh': 0.0,
        'avg_battery_soc': 50.0,
        'max_solar_w': 1500.0,
    }
    payload = _mobile_reports_summary_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats=stats,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['summary']['solar_surplus_kwh'] == 0.0


# ═══════════════════════════════════════════════════════════════════════
# Route handler tests (Flask test_request_context + mocks)
# ═══════════════════════════════════════════════════════════════════════

def _make_app():
    """Build a minimal Flask app with just our blueprint mounted.

    No DB, no scheduler, no `create_app()` boot — every DB / auth
    dependency is monkeypatched at the call site.
    """
    from flask import Flask
    from app.blueprints.mobile_devices_api import mobile_devices_api_bp
    app = Flask(__name__)
    # The route reads MAX_READINGS_QUERY + LOCAL_TIMEZONE off current_app.config.
    app.config['MAX_READINGS_QUERY'] = 2000
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    # Re-registering the same blueprint on a NEW Flask instance is fine —
    # the BP is a module-level singleton but each Flask carries its own
    # registry. Tests build a fresh app per call to keep contexts clean.
    app.register_blueprint(mobile_devices_api_bp)
    return app


def _fake_device(*, id_=42, timezone='UTC'):
    dev = mock.Mock()
    dev.id = id_
    dev.timezone = timezone
    return dev


def _fake_user(*, id_=1, is_admin=False):
    user = mock.Mock()
    user.id = id_
    user.is_admin = is_admin
    return user


def _patch_user(user):
    return mock.patch(
        'app.blueprints.mobile_devices_api.user_from_bearer_or_session',
        return_value=user,
    )


def _device_query_returning(device):
    """Build a `query` stand-in for `AppDevice` whose chained
    `.filter_by(...).filter_by(...).first()` returns `device`.

    `_device_allowed` chains two `filter_by` calls for non-admin
    users (`id=...` then `owner_user_id=...`), so the chain mock's
    `filter_by.return_value` is set to the chain itself — every
    `filter_by(...)` call keeps returning the same object, and the
    terminal `.first()` returns the configured device (or `None`
    to simulate the foreign-owner case)."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.first.return_value = device
    return chain


def _reading_query_returning(rows):
    """Build a `query` stand-in for `Reading` whose chained
    `.filter_by(...).filter(...).order_by(...).limit(...).all()`
    returns `rows`. Patched onto `Reading.query` only — `Reading`'s
    column descriptors (e.g. `Reading.created_at`) stay intact so the
    route's `>=` / `<` filter expressions still build cleanly."""
    chain = mock.Mock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.limit.return_value = chain
    chain.all.return_value = rows
    q = mock.Mock()
    q.filter_by.return_value = chain
    return q


# ─── Validation error wiring ───────────────────────────────────────────

def test_route_invalid_view_returns_400_with_code():
    """An unsupported `view` (e.g. `year`) returns 400 with the
    `invalid_view` code so the mobile client can render a calm error."""
    from app.blueprints.mobile_devices_api import device_reports_summary, AppDevice
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    with app.test_request_context('/api/v1/devices/42/reports/summary?view=year'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)):
        resp = device_reports_summary(42)
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'invalid_view'
        # Locked field name so mobile UI can target the right form input.
        assert body.get('field') == 'view'


def test_route_invalid_date_returns_400_with_code():
    """Bad date format (e.g. `2026/05/12`) returns 400 with the
    `invalid_date` code. View defaults to `day` since blank is allowed."""
    from app.blueprints.mobile_devices_api import device_reports_summary, AppDevice
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    with app.test_request_context(
            '/api/v1/devices/42/reports/summary?view=day&date=2026/05/12'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)):
        resp = device_reports_summary(42)
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'invalid_date'
        assert body.get('field') == 'date'


# ─── Owner-scope ───────────────────────────────────────────────────────

def test_route_device_not_found_for_foreign_owner():
    """`_device_allowed` returns None when the device doesn't belong
    to the requesting user (`filter_by(owner_user_id=user.id)` matches
    nothing). The route must return 404 `device_not_found` — never
    expose the device's existence to a different user."""
    from app.blueprints.mobile_devices_api import device_reports_summary, AppDevice
    app = _make_app()
    user = _fake_user(id_=1)
    # `None` from `.filter_by(...).first()` simulates the foreign-owner
    # case where the SQL filter chain doesn't match any row.
    with app.test_request_context('/api/v1/devices/42/reports/summary?view=day'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(None)):
        resp = device_reports_summary(42)
        assert resp.status_code == 404
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'device_not_found'


def test_route_unauthenticated_returns_401():
    """No bearer token → 401 auth_required. Locks the auth gate."""
    from app.blueprints.mobile_devices_api import device_reports_summary
    app = _make_app()
    with app.test_request_context('/api/v1/devices/42/reports/summary?view=day'), \
         _patch_user(None):
        resp = device_reports_summary(42)
        assert resp.status_code == 401
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'auth_required'


# ─── Success: empty period ─────────────────────────────────────────────

def test_route_empty_period_returns_empty_true_with_zero_derivations():
    """When the DB has no readings for the period, the response must
    set `empty=true` and every derived metric must be 0.0 — no
    fabricated 100% self-sufficiency from the divide-by-0.01 floor."""
    from app.blueprints.mobile_devices_api import (
        device_reports_summary, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    with app.test_request_context(
            '/api/v1/devices/42/reports/summary?view=day&date=2026-05-12'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning([])):
        resp = device_reports_summary(42)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        data = body['data']
        assert data['view'] == 'day'
        assert data['anchor'] == '2026-05-12'
        assert data['empty'] is True
        s = data['summary']
        assert s['production_kwh'] == 0.0
        assert s['consumption_kwh'] == 0.0
        assert s['battery_in_kwh'] == 0.0
        assert s['grid_in_kwh'] == 0.0
        assert s['solar_share_percent'] == 0.0
        assert s['battery_share_percent'] == 0.0
        assert s['grid_share_percent'] == 0.0
        assert s['self_sufficiency_percent'] == 0.0
        assert s['average_load_w'] == 0.0
        assert s['solar_surplus_kwh'] == 0.0
        # Honest meta keys always present.
        assert 'generated_at' in data
        assert 'title_hint' in data


# ─── Success: day view with synthetic readings ─────────────────────────

class _FakeReading:
    """Drop-in for SQLAlchemy `Reading` rows. Carries every column the
    energy helper chain (`compute_energy_stats` →
    `energy_parts_from_reading` → `build_flow`) reads off a row,
    including `raw_json` which `build_flow` checks for vendor-derived
    flow values. `raw_json=None` is the realistic case for mobile-
    fetched rows that don't carry a vendor blob."""
    def __init__(self, *, created_at, solar_power=0.0, home_load=0.0,
                 battery_soc=0.0, battery_power=0.0, grid_power=0.0,
                 raw_json=None):
        self.created_at = created_at
        self.solar_power = solar_power
        self.home_load = home_load
        self.battery_soc = battery_soc
        self.battery_power = battery_power
        self.grid_power = grid_power
        self.raw_json = raw_json


def test_route_day_view_success_shape_with_synthetic_readings():
    """Two consecutive 30-minute readings inside the target day produce
    non-zero totals and derived metrics — the helpers run end-to-end."""
    from app.blueprints.mobile_devices_api import (
        device_reports_summary, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device(timezone='UTC')

    # Two readings 30 minutes apart inside 2026-05-12 UTC. Power values
    # are chosen so the rectangular integration produces a tidy result:
    #   dt = 0.5h, prev.solar_power = 2000W → 1.0 kWh generated.
    rows = [
        _FakeReading(
            created_at=datetime(2026, 5, 12, 10, 0, 0),
            solar_power=2000.0,
            home_load=1000.0,
            battery_soc=50.0,
        ),
        _FakeReading(
            created_at=datetime(2026, 5, 12, 10, 30, 0),
            solar_power=2400.0,
            home_load=1100.0,
            battery_soc=52.0,
        ),
    ]
    with app.test_request_context(
            '/api/v1/devices/42/reports/summary?view=day&date=2026-05-12'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(rows)):
        resp = device_reports_summary(42)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        data = body['data']
        assert data['view'] == 'day'
        assert data['anchor'] == '2026-05-12'
        assert data['empty'] is False

        s = data['summary']
        # Locked structural keys (never silently dropped).
        for key in (
            'production_kwh', 'consumption_kwh',
            'battery_in_kwh', 'grid_in_kwh',
            'solar_share_percent', 'battery_share_percent',
            'grid_share_percent', 'self_sufficiency_percent',
            'average_load_w', 'solar_surplus_kwh',
        ):
            assert key in s, f'missing summary key: {key}'

        # Production over 0.5h at 2000W = 1.0 kWh.
        assert s['production_kwh'] == 1.0
        # Consumption over 0.5h at 1000W = 0.5 kWh.
        assert s['consumption_kwh'] == 0.5
        # Average load = 0.5 kWh / 2 samples * 1000 = 250 W.
        assert s['average_load_w'] == 250.0


# ─── Success: month view shape ─────────────────────────────────────────

def test_route_month_view_success_shape():
    """Month-view path passes through `filter_rows_for_view` with view
    `month` and anchors to `YYYY-MM`. We don't assert exact derived
    values here (those are locked by the unit tests above) — this
    test locks the response shape + view-specific anchor format."""
    from app.blueprints.mobile_devices_api import (
        device_reports_summary, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device(timezone='UTC')

    rows = [
        _FakeReading(
            created_at=datetime(2026, 5, 15, 12, 0, 0),
            solar_power=1500.0, home_load=800.0, battery_soc=60.0,
        ),
        _FakeReading(
            created_at=datetime(2026, 5, 15, 12, 30, 0),
            solar_power=1700.0, home_load=900.0, battery_soc=62.0,
        ),
    ]
    with app.test_request_context(
            '/api/v1/devices/42/reports/summary?view=month&date=2026-05-15'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(rows)):
        resp = device_reports_summary(42)
        assert resp.status_code == 200
        body = resp.get_json()
        data = body['data']
        assert data['view'] == 'month'
        # Month anchor drops the day component.
        assert data['anchor'] == '2026-05'
        assert data['empty'] is False
        # Same locked summary keys regardless of view.
        for key in (
            'production_kwh', 'consumption_kwh',
            'battery_in_kwh', 'grid_in_kwh',
            'solar_share_percent', 'battery_share_percent',
            'grid_share_percent', 'self_sufficiency_percent',
            'average_load_w', 'solar_surplus_kwh',
        ):
            assert key in data['summary']
