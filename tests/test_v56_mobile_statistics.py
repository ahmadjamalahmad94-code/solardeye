"""v56 — mobile statistics endpoint tests.

The route handler in `app/blueprints/mobile_devices_api.py` is a thin
wrapper around three things:

  1. `_validate_statistics_view` — accepts ONLY `day` / `month`.
  2. `_validate_statistics_date`  — accepts empty / `YYYY-MM-DD`.
  3. `_mobile_statistics_payload` — maps the canonical web
     `compute_energy_stats` / `build_period_chart` dicts onto the
     mobile-facing payload (totals + buckets + empty flag).

These three helpers carry the whole contract — covering them
without a Flask app context locks the mobile-facing shape and the
day-view W → kWh-per-hour conversion. The DB filter + the energy
helpers themselves are already exercised by the existing web
statistics/reports tests; v56 does not fork that math.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── View validator ────────────────────────────────────────────────────

def test_view_validator_accepts_day_and_month():
    from app.blueprints.mobile_devices_api import _validate_statistics_view
    assert _validate_statistics_view('day') == 'day'
    assert _validate_statistics_view('month') == 'month'


def test_view_validator_defaults_blank_to_day():
    from app.blueprints.mobile_devices_api import _validate_statistics_view
    assert _validate_statistics_view(None) == 'day'
    assert _validate_statistics_view('') == 'day'
    assert _validate_statistics_view('   ') == 'day'


def test_view_validator_normalises_case_and_whitespace():
    from app.blueprints.mobile_devices_api import _validate_statistics_view
    assert _validate_statistics_view('  DAY  ') == 'day'
    assert _validate_statistics_view('Month') == 'month'


def test_view_validator_rejects_week_and_year_in_phase_1():
    """v56 deliberately keeps the contract tight to two views — week
    and year are deferred so the mobile screen can ship without
    speculative chips."""
    from app.blueprints.mobile_devices_api import _validate_statistics_view
    assert _validate_statistics_view('week') is None
    assert _validate_statistics_view('year') is None
    assert _validate_statistics_view('mystery') is None


# ─── Date validator ────────────────────────────────────────────────────

def test_date_validator_accepts_empty_as_today_fallback():
    from app.blueprints.mobile_devices_api import _validate_statistics_date
    assert _validate_statistics_date(None) is True
    assert _validate_statistics_date('') is True
    assert _validate_statistics_date('   ') is True


def test_date_validator_accepts_proper_iso_date():
    from app.blueprints.mobile_devices_api import _validate_statistics_date
    assert _validate_statistics_date('2026-05-12') is True
    # Python's strptime('%Y-%m-%d') also accepts single-digit month
    # / day, so we accept it too rather than adding a regex layer
    # whose only purpose would be to reject correct ISO-ish dates.
    assert _validate_statistics_date('2026-1-1') is True
    # But other separators / orderings are rejected.
    assert _validate_statistics_date('2026/05/12') is False
    assert _validate_statistics_date('12-05-2026') is False


def test_date_validator_rejects_garbage_and_partials():
    from app.blueprints.mobile_devices_api import _validate_statistics_date
    assert _validate_statistics_date('not-a-date') is False
    assert _validate_statistics_date('2026-05') is False
    assert _validate_statistics_date('2026-13-01') is False  # invalid month


# ─── Payload shape (day view) ──────────────────────────────────────────

def _fake_stats(samples=0, **overrides):
    """Empty-shape canonical stats dict matching `compute_energy_stats`
    output — overrides simulate the populated path."""
    base = {
        'samples': samples,
        'solar_generated_kwh': 0.0,
        'home_consumed_kwh': 0.0,
        'solar_to_home_kwh': 0.0,
        'solar_to_battery_kwh': 0.0,
        'battery_to_home_kwh': 0.0,
        'grid_to_home_kwh': 0.0,
        'avg_battery_soc': 0.0,
        'max_solar_w': 0.0,
        'data_gaps': 0,
    }
    base.update(overrides)
    return base


def test_payload_day_view_maps_totals_and_converts_buckets_to_kwh_per_hour():
    """Day view: build_period_chart returns hourly AVERAGE POWER in W.
    The mobile contract is kWh per bucket, so 600W avg over 1h = 0.6 kWh."""
    from app.blueprints.mobile_devices_api import _mobile_statistics_payload
    stats = _fake_stats(
        samples=12,
        solar_generated_kwh=4.2,
        home_consumed_kwh=3.1,
        solar_to_battery_kwh=0.8,
        grid_to_home_kwh=0.4,
        avg_battery_soc=55.5,
        max_solar_w=2100.0,
        data_gaps=1,
    )
    chart = {
        'labels': ['09:00', '10:00', '11:00'],
        'solar': [600.0, 1500.0, 2000.0],   # W — averages per hour
        'home':  [400.0, 800.0, 1200.0],
        'battery': [0.0, 0.0, 0.0],
        'grid':   [0.0, 0.0, 0.0],
        'soc':    [50.0, 52.0, 55.0],
    }
    payload = _mobile_statistics_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats=stats,
        chart=chart,
        generated_at='2026-05-12T10:00:00',
    )

    assert payload['view'] == 'day'
    assert payload['anchor'] == '2026-05-12'
    assert payload['title_hint'] == 'يوم 2026-05-12'
    assert payload['empty'] is False
    assert payload['generated_at'] == '2026-05-12T10:00:00'

    # Totals come straight from compute_energy_stats with mobile names.
    totals = payload['totals']
    assert totals['production_kwh']   == 4.2
    assert totals['consumption_kwh']  == 3.1
    assert totals['battery_in_kwh']   == 0.8
    assert totals['grid_in_kwh']      == 0.4
    assert totals['avg_battery_soc']  == 55.5
    assert totals['max_solar_w']      == 2100.0
    assert totals['samples']          == 12
    assert totals['data_gaps']        == 1

    # Buckets — day view converts avg-power-W to kWh-per-hour.
    buckets = payload['buckets']
    assert buckets['labels'] == ['09:00', '10:00', '11:00']
    assert buckets['production_kwh']  == [0.6, 1.5, 2.0]
    assert buckets['consumption_kwh'] == [0.4, 0.8, 1.2]
    # Battery + grid bucket arrays are deliberately NOT in the
    # contract — phase 1 keeps the chart to production vs.
    # consumption to stay legible on a phone.
    assert 'battery_kwh' not in buckets
    assert 'grid_kwh' not in buckets


# ─── Payload shape (month view) ────────────────────────────────────────

def test_payload_month_view_keeps_buckets_as_kwh_and_uses_year_month_anchor():
    """Month view: build_period_chart already returns daily kWh sums
    (it pipes each day's rows through compute_energy_stats). No unit
    conversion needed — the mobile contract just passes them through."""
    from app.blueprints.mobile_devices_api import _mobile_statistics_payload
    stats = _fake_stats(
        samples=2400,
        solar_generated_kwh=145.6,
        home_consumed_kwh=128.4,
        solar_to_battery_kwh=15.2,
        grid_to_home_kwh=8.3,
        avg_battery_soc=60.2,
        max_solar_w=4500.0,
        data_gaps=2,
    )
    chart = {
        'labels': ['05/01', '05/02', '05/03'],
        'solar': [5.2, 4.8, 5.1],   # already kWh
        'home':  [4.5, 4.2, 4.6],
        'battery': [0.5, 0.4, 0.6],
        'grid':   [0.2, 0.3, 0.1],
        'soc':    [62.0, 60.0, 59.5],
    }
    payload = _mobile_statistics_payload(
        view='month',
        selected_date=datetime(2026, 5, 12),
        title_hint='شهر 2026-05',
        stats=stats,
        chart=chart,
        generated_at='2026-05-12T10:00:00',
    )

    assert payload['view'] == 'month'
    # Month anchor is the year-month key, not the chosen day.
    assert payload['anchor'] == '2026-05'
    assert payload['title_hint'] == 'شهر 2026-05'
    assert payload['empty'] is False

    buckets = payload['buckets']
    assert buckets['labels'] == ['05/01', '05/02', '05/03']
    # No unit conversion for month view — values pass through (with
    # the standard rounding clamp).
    assert buckets['production_kwh']  == [5.2, 4.8, 5.1]
    assert buckets['consumption_kwh'] == [4.5, 4.2, 4.6]


# ─── Empty-state contract ──────────────────────────────────────────────

def test_payload_empty_when_samples_zero():
    """Mobile UI gates its "no data" empty state on `empty=true` so
    the contract must surface it whenever `samples == 0`."""
    from app.blueprints.mobile_devices_api import _mobile_statistics_payload
    stats = _fake_stats(samples=0)
    chart = {'labels': [], 'solar': [], 'home': [], 'battery': [], 'grid': [], 'soc': []}
    payload = _mobile_statistics_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats=stats,
        chart=chart,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['empty'] is True
    assert payload['totals']['samples'] == 0
    assert payload['buckets']['labels'] == []
    assert payload['buckets']['production_kwh'] == []
    assert payload['buckets']['consumption_kwh'] == []


def test_payload_tolerates_missing_chart_keys():
    """Defensive: if `build_period_chart` ever returns a partial
    dict (e.g. the day-view branch produced no buckets because no
    rows had a local time), the helper still yields a valid empty
    bucket section instead of raising."""
    from app.blueprints.mobile_devices_api import _mobile_statistics_payload
    stats = _fake_stats(samples=0)
    chart = {}
    payload = _mobile_statistics_payload(
        view='month',
        selected_date=datetime(2026, 5, 12),
        title_hint='شهر 2026-05',
        stats=stats,
        chart=chart,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['buckets']['labels'] == []
    assert payload['buckets']['production_kwh'] == []
    assert payload['buckets']['consumption_kwh'] == []
    assert payload['empty'] is True


def test_payload_tolerates_partial_stats_keys():
    """compute_energy_stats always returns the full dict in production,
    but the mapper should not crash if a future upstream change drops
    a key — every missing total reads as 0.0 / 0 instead."""
    from app.blueprints.mobile_devices_api import _mobile_statistics_payload
    payload = _mobile_statistics_payload(
        view='day',
        selected_date=datetime(2026, 5, 12),
        title_hint='يوم 2026-05-12',
        stats={},  # nothing
        chart={'labels': [], 'solar': [], 'home': []},
        generated_at='2026-05-12T10:00:00',
    )
    totals = payload['totals']
    assert totals['production_kwh'] == 0.0
    assert totals['consumption_kwh'] == 0.0
    assert totals['battery_in_kwh'] == 0.0
    assert totals['grid_in_kwh'] == 0.0
    assert totals['avg_battery_soc'] == 0.0
    assert totals['max_solar_w'] == 0.0
    assert totals['samples'] == 0
    assert totals['data_gaps'] == 0
    assert payload['empty'] is True
