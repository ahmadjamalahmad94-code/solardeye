"""v93r — Flow-graph generator node data pipeline.

The mobile home screen now renders a "مولد" (generator) card in
the previously-empty top-middle cell of the energy flow graph.
The card reads `cards.generatorPowerW`, which the mobile parses
from the server's `generator_power_w` field in the dashboard
cards payload.

This test pins the server-side helper that computes
`generator_power_w` from a Reading's raw_json snapshot, mirroring
the same direct + inferred logic as
`helpers.build_battery_insights`:

  * direct measurement: `derived.purchasePower` (>= 5 W)
  * fallback to `gridPowerSigned` when negative
  * station-tier inference when relay=Break:
      `generationPower - sum(PV) >= 50 W`
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _fake_row(raw_obj):
    r = mock.Mock()
    r.raw_json = json.dumps(raw_obj) if raw_obj is not None else None
    return r


def test_direct_purchase_power_passes_through():
    from app.blueprints.mobile_api import _derive_generator_power_w
    row = _fake_row({
        'derived': {
            'purchasePower': 1200.0,
            'gridPowerSigned': -1200.0,
            'gridRelayStatus': 'Close',
        }
    })
    assert _derive_generator_power_w(row) == 1200.0


def test_signed_grid_power_fallback_when_purchase_missing():
    """`purchasePower` absent but `gridPowerSigned` is negative
    (utility/generator is importing power) — we still derive a
    positive wattage."""
    from app.blueprints.mobile_api import _derive_generator_power_w
    row = _fake_row({
        'derived': {
            'gridPowerSigned': -750.0,
        }
    })
    assert _derive_generator_power_w(row) == 750.0


def test_inferred_from_station_tier_when_relay_break():
    """The exact off-grid + generator scenario the user reported:
    AC-IN sensor reads 0 (relay Break) but station_summary says
    1003 W of generation while PV is just 6 W. The helper must
    surface the gap (~997 W) as the generator wattage so the
    flow graph card has something to show."""
    from app.blueprints.mobile_api import _derive_generator_power_w
    row = _fake_row({
        'derived': {
            'purchasePower': 0.0,
            'gridPowerSigned': 0.0,
            'gridRelayStatus': 'Break',
            'dcPowerPv1': 6.0,
            'dcPowerPv2': 0.0,
            'dcPowerPv3': 0.0,
        },
        'station_summary': {
            'generationPower': 1003.0,
        },
    })
    assert _derive_generator_power_w(row) == 997.0


def test_returns_zero_when_no_meaningful_input():
    """All sensors quiet → 0 W. Below the 5 W floor + below the
    50 W inference threshold → no false positives."""
    from app.blueprints.mobile_api import _derive_generator_power_w
    row = _fake_row({
        'derived': {
            'purchasePower': 0.0,
            'gridPowerSigned': 0.0,
            'dcPowerPv1': 1.0,
        },
        'station_summary': {
            'generationPower': 8.0,  # gap = 7 W, below 50 W floor
        },
    })
    assert _derive_generator_power_w(row) == 0.0


def test_returns_zero_for_missing_row_or_raw_json():
    from app.blueprints.mobile_api import _derive_generator_power_w
    assert _derive_generator_power_w(None) == 0.0
    assert _derive_generator_power_w(_fake_row(None)) == 0.0


def test_handles_corrupt_json_gracefully():
    """A malformed raw_json must not crash the dashboard
    endpoint — the helper logs nothing and returns 0."""
    from app.blueprints.mobile_api import _derive_generator_power_w
    row = mock.Mock()
    row.raw_json = '{this is not json'
    assert _derive_generator_power_w(row) == 0.0


def test_reading_cards_carries_generator_power_w_key():
    """End-to-end: the mobile dashboard cards payload must
    include the new key on both populated and empty paths so the
    Flutter `DashboardCards.fromJson` always finds the field."""
    from app.blueprints.mobile_api import _mobile_reading_cards
    empty = _mobile_reading_cards(None)
    assert 'generator_power_w' in empty
    assert empty['generator_power_w'] == 0.0

    row = mock.Mock()
    row.solar_power = 6
    row.home_load = 295
    row.battery_soc = 83
    row.battery_power = 641
    row.grid_power = 0
    row.inverter_power = 1003
    row.daily_production = 0
    row.monthly_production = 0
    row.total_production = 0
    row.raw_json = json.dumps({
        'derived': {
            'purchasePower': 0,
            'gridPowerSigned': 0,
            'gridRelayStatus': 'Break',
            'dcPowerPv1': 6,
        },
        'station_summary': {'generationPower': 1003},
    })
    populated = _mobile_reading_cards(row)
    assert populated['generator_power_w'] == 997.0
