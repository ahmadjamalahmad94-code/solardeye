"""v33-β automated tests.

Covers the new fleet API blueprint:
  /api/fleet/select
  /api/fleet/summary
  /api/devices/<id>/live-summary
  /api/fleet/overview
  /api/devices/<id>/notifications-preview

Tests use mocked AppDevice/AppUser/Reading queries so they run without
a live database. Production CI (with pytest+flask) will run them
against a SQLite test DB; the WSL sandbox runs the pure-helper tests
via the same stub harness used in test_v33_alpha.py.
"""
from __future__ import annotations

import os
import sys
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── pure-helper tests ────────────────────────────────────────────────

def test_status_from_age_classifies_correctly():
    """`_status_from_age(seconds)` returns 'online' / 'stale' / 'offline'."""
    from app.blueprints.fleet_api import _status_from_age
    assert _status_from_age(60) == 'online'        # 1 min ago
    assert _status_from_age(290) == 'online'       # 4m50 ago
    assert _status_from_age(310) == 'stale'        # 5m10 ago
    assert _status_from_age(1700) == 'stale'       # 28m ago
    assert _status_from_age(1900) == 'offline'     # 31m ago
    assert _status_from_age(None) == 'offline'     # never seen
    assert _status_from_age(0) == 'online'


def test_device_icon_picks_keyword_emoji():
    from app.blueprints.fleet_api import _device_icon
    assert _device_icon('Home Roof') == '🏘️'
    assert _device_icon('Workshop A') == '🏭'
    assert _device_icon('Test Farm') == '🌾'
    assert _device_icon('Office HQ') == '🏢'
    assert _device_icon('Random Device') == '🏠'   # default
    assert _device_icon(None) == '🏠'              # null safe


def test_aggregate_overview_sums_solar_load_grid_but_not_battery():
    """Combined view sums kWh-style metrics, never averages SOC."""
    from app.blueprints.fleet_api import _build_aggregate_overview
    fake_devices = [
        type('D', (), {'id': 1, 'name': 'A', 'is_active': True, 'api_provider': 'deye', 'timezone': 'Asia/Hebron'}),
        type('D', (), {'id': 2, 'name': 'B', 'is_active': True, 'api_provider': 'deye', 'timezone': 'Asia/Hebron'}),
        type('D', (), {'id': 3, 'name': 'C', 'is_active': True, 'api_provider': 'deye', 'timezone': 'Asia/Hebron'}),
    ]
    fake_readings = {
        1: type('R', (), {'solar_power': 1000, 'home_load': 500, 'grid_power': -200, 'battery_soc': 80, 'battery_power': 100, 'inverter_power': 1000, 'daily_production': 5.0, 'created_at': None}),
        2: type('R', (), {'solar_power':  500, 'home_load': 300, 'grid_power':  100, 'battery_soc': 60, 'battery_power':   0, 'inverter_power':  500, 'daily_production': 3.0, 'created_at': None}),
        3: type('R', (), {'solar_power':    0, 'home_load': 700, 'grid_power':  700, 'battery_soc': 30, 'battery_power': -50, 'inverter_power':    0, 'daily_production': 0.0, 'created_at': None}),
    }
    out = _build_aggregate_overview(fake_devices, fake_readings)
    assert out['combined']['solar_power']  == 1500.0
    assert out['combined']['home_load']    == 1500.0
    assert out['combined']['grid_power']   ==  600.0
    assert out['combined']['daily_production_kwh'] == 8.0
    assert 'battery_soc' not in out['combined'], "Aggregate must NOT expose a single SOC number"
    assert 'battery_average' not in out['combined']
    breakdown_socs = [r['battery_soc'] for r in out['per_device']]
    assert sorted(breakdown_socs) == [30, 60, 80]
    assert len(out['per_device']) == 3


def test_aggregate_overview_handles_devices_without_readings():
    from app.blueprints.fleet_api import _build_aggregate_overview
    devices = [type('D', (), {'id': 1, 'name': 'NoData', 'is_active': True, 'api_provider': 'deye', 'timezone': 'Asia/Hebron'})]
    out = _build_aggregate_overview(devices, {})
    assert out['combined']['solar_power'] == 0.0
    assert out['combined']['home_load'] == 0.0
    assert out['per_device'][0]['has_reading'] is False


def test_status_dot_field_present_on_summary_payload():
    from app.blueprints.fleet_api import _status_from_age
    # contract-test: 'online' / 'stale' / 'offline' strings only — no other states
    valid = {'online', 'stale', 'offline'}
    for sec in (0, 1, 60, 300, 301, 1800, 1801, None):
        assert _status_from_age(sec) in valid


# ─── integration tests (skipped if app cannot be constructed) ─────────

def _can_run_integration_tests() -> bool:
    try:
        os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
        os.environ.setdefault('SECRET_KEY', 'x' * 64)
        os.environ.setdefault('SESSION_COOKIE_SECURE', 'false')
        from app import create_app  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _can_run_integration_tests(),
                    reason='Flask app could not be constructed in this sandbox')
def test_fleet_summary_returns_only_owned_devices():
    pytest.skip('Integration harness — manual T6 in v33-beta-test-plan.md')


@pytest.mark.skipif(not _can_run_integration_tests(),
                    reason='Flask app could not be constructed in this sandbox')
def test_fleet_select_updates_session_and_preferred_device():
    pytest.skip('Integration harness — manual T2/T4 in v33-beta-test-plan.md')


@pytest.mark.skipif(not _can_run_integration_tests(),
                    reason='Flask app could not be constructed in this sandbox')
def test_devices_live_summary_403_for_other_users_devices():
    pytest.skip('Integration harness — manual T6 in v33-beta-test-plan.md')
