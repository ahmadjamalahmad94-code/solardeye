"""v93l — battery_insights tells the truth when discharging.

The bug: a subscriber running their inverter from a generator at
night saw the "وقت امتلاء البطارية" card show "غير متاح". The
battery WAS actively discharging (so a "time to full" is
literally not meaningful), and the inverter WAS receiving AC-IN
from the generator (so the user had real-time information we
weren't surfacing anywhere).

v93l fix:
    1. `charge_eta` no longer falls back to "غير متاح" when the
       battery is in active discharge. It now reads
       "البطارية في وضع التفريغ" or, if there's measurable AC-IN,
       "وضع التفريغ نشط — يوجد إدخال خارجي".
    2. `external_ac_input_w` is a new field on the insights dict
       projecting `derived.purchasePower` (or, as fallback,
       `derived.gridPowerSigned < 0`) into a positive wattage.
       On residential Deye hybrids the AC-IN port is shared
       between utility grid and generator, so the field is
       intentionally labelled "external" — the inverter cannot
       distinguish the two sources.
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _make_flask_app():
    from flask import Flask
    app = Flask(__name__)
    app.config['BATTERY_RESERVE_PERCENT'] = 20
    return app


def _fake_reading(*, soc, raw_derived: dict, battery_power=0.0, home_load=0.0, solar_power=0.0):
    r = mock.Mock()
    r.battery_soc = soc
    r.battery_power = battery_power
    r.home_load = home_load
    r.solar_power = solar_power
    r.raw_json = json.dumps({'derived': raw_derived}, ensure_ascii=False)
    return r


def test_discharging_with_generator_reports_external_input_and_state():
    """The exact user scenario: battery is actively discharging
    while a generator is plugged into AC-IN. The card must:
      * not lie that "وقت الامتلاء" is "غير متاح",
      * say something true about the discharge state,
      * surface the AC-IN power so the user can see what the
        generator is feeding in.
    """
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    derived = {
        'chargePower': 0,
        'dischargePower': 850,        # battery is feeding the load
        'purchasePower': 1200,        # AC-IN from generator (W)
        'feedInPower': 0,
        'gridPowerSigned': -1200,     # negative = import
    }
    reading = _fake_reading(
        soc=42, raw_derived=derived,
        battery_power=850, home_load=2050, solar_power=0,
    )
    with app.app_context():
        out = build_battery_insights(reading, 5.0, 20.0)

    assert out['mode_label'] == 'يتم التفريغ'
    # The "battery full" cell must be honest about the state
    # instead of saying "غير متاح".
    assert out['charge_eta'] != 'غير متاح', out
    assert 'تفريغ' in out['charge_eta'], out['charge_eta']
    # When AC-IN is non-zero, the card mentions the external
    # input so the user understands why the battery is not
    # charging despite the input.
    assert 'إدخال خارجي' in out['charge_eta'], out['charge_eta']
    # discharge_eta is the real ETA in this mode — must not be
    # the placeholder string.
    assert out['discharge_eta'] != 'غير متاح'
    # The new field exposes generator/grid AC-IN wattage.
    assert out['external_ac_input_w'] == 1200.0


def test_discharging_without_external_input_reads_battery_only_state():
    """No generator, no grid — same state but the message must
    not invent an external input."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    derived = {
        'chargePower': 0,
        'dischargePower': 500,
        'purchasePower': 0,
        'feedInPower': 0,
        'gridPowerSigned': 0,
    }
    reading = _fake_reading(
        soc=60, raw_derived=derived,
        battery_power=500, home_load=500, solar_power=0,
    )
    with app.app_context():
        out = build_battery_insights(reading, 5.0, 20.0)

    assert out['mode_label'] == 'يتم التفريغ'
    assert out['charge_eta'] != 'غير متاح'
    assert 'تفريغ' in out['charge_eta']
    # No external input mentioned because none exists.
    assert 'إدخال خارجي' not in out['charge_eta']
    assert out['external_ac_input_w'] == 0.0


def test_charging_keeps_legacy_eta_text():
    """When the battery is actually charging, the behaviour is
    unchanged: charge_eta is the human-formatted time to 100%."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    derived = {
        'chargePower': 2000,
        'dischargePower': 0,
        'purchasePower': 0,
        'feedInPower': 500,
        'gridPowerSigned': 500,
    }
    reading = _fake_reading(
        soc=40, raw_derived=derived,
        battery_power=2000, home_load=500, solar_power=2500,
    )
    with app.app_context():
        out = build_battery_insights(reading, 5.0, 20.0)

    assert out['mode_label'] == 'يتم الشحن'
    # Charging path produces a real ETA (human_duration_hours), not
    # the placeholder.
    assert out['charge_eta'] != 'غير متاح'
    assert 'تفريغ' not in out['charge_eta']
    # When charging, discharge_eta now narrates the state instead
    # of "غير متاح".
    assert out['discharge_eta'] != 'غير متاح'
    assert 'تشحن' in out['discharge_eta']
    # Feed-in surfaces.
    assert out['feed_in_w'] == 500.0


def test_external_input_falls_back_to_signed_grid_power():
    """If `purchasePower` is missing but `gridPowerSigned` is
    negative, we still derive `external_ac_input_w` correctly.
    Catches an older raw-snapshot shape regression."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    derived = {
        'chargePower': 0,
        'dischargePower': 300,
        # purchasePower/feedInPower intentionally missing
        'gridPowerSigned': -750,  # 750 W coming in
    }
    reading = _fake_reading(
        soc=50, raw_derived=derived, battery_power=300,
    )
    with app.app_context():
        out = build_battery_insights(reading, 5.0, 20.0)

    assert out['external_ac_input_w'] == 750.0


def test_empty_path_includes_new_fields():
    """The `latest is None` empty dict must include the new fields
    so consumers (mobile_api, web templates) don't break on a
    KeyError. Catches the regression of forgetting to mirror
    new fields across paths."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    with app.app_context():
        out = build_battery_insights(None, 5.0, 20.0)
    assert 'external_ac_input_w' in out
    assert 'feed_in_w' in out
    assert out['external_ac_input_w'] == 0.0
    assert out['feed_in_w'] == 0.0
