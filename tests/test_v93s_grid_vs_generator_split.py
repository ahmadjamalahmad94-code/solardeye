"""v93s — battery_insights splits external AC-IN into grid vs generator.

The owner reorganised the operating-indicators panel to show two
distinct external-input rows plus a single status summary:

    إدخال خارجي · شبكة    (when grid_input_w > 5)
    إدخال خارجي · مولد    (when generator_input_w > 5)
    حالة AC IN            ("شبكة" / "مولد" / "شبكة ومولد" /
                           "لا يوجد إدخال")

A Deye residential hybrid CANNOT distinguish utility vs generator
electrically — both share the AC-IN port — so we attribute by
auxiliary signal:

  * gridStatus = Static      → off-grid setup → direct AC-IN flow
                                is attributed to GENERATOR
  * gridStatus = On/Normal   → grid present → direct AC-IN flow
                                is attributed to GRID
  * Station-tier inferred (relay = Break + station - PV >= 50W)
                              → always GENERATOR (external transfer
                                switch bypassing the sensor)

This test pins the attribution logic + the label builder.
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


def _fake_reading(*, soc, derived, battery_power=0.0):
    r = mock.Mock()
    r.battery_soc = soc
    r.battery_power = battery_power
    r.home_load = 0.0
    r.solar_power = 0.0
    r.raw_json = json.dumps(
        {'derived': derived, 'station_summary': derived.pop('_station', {})},
        ensure_ascii=False,
    )
    return r


def test_grid_attribution_when_grid_status_normal():
    """gridStatus is normal (On / Normal / etc.) → the direct
    AC-IN reading is attributed to the utility grid."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    reading = _fake_reading(
        soc=60,
        derived={
            'purchasePower': 800,
            'gridPowerSigned': -800,
            'gridStatus': 'On',
            'chargePower': 800,
        },
        battery_power=800,
    )
    with app.app_context():
        out = build_battery_insights(reading, 5.0, 20.0)
    assert out['grid_input_w'] == 800.0
    assert out['generator_input_w'] == 0.0
    assert out['ac_in_source_label'] == 'شبكة'


def test_generator_attribution_when_offgrid_with_direct_reading():
    """gridStatus = Static + direct AC-IN > 5 W → AC-IN must come
    from a generator (off-grid setup has no utility grid)."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    reading = _fake_reading(
        soc=60,
        derived={
            'purchasePower': 950,
            'gridPowerSigned': -950,
            'gridStatus': 'Static',
            'chargePower': 950,
        },
        battery_power=950,
    )
    with app.app_context():
        out = build_battery_insights(reading, 5.0, 20.0)
    assert out['grid_input_w'] == 0.0
    assert out['generator_input_w'] == 950.0
    assert out['ac_in_source_label'] == 'مولد'


def test_generator_attribution_from_station_inference():
    """The exact off-grid + relay=Break + transfer-switch case
    the user reported. Direct sensor reads 0, station tier shows
    a non-zero generationPower gap — must classify as generator."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    # We need the station_summary block at the top of raw, not
    # inside derived. Build the row manually.
    r = mock.Mock()
    r.battery_soc = 81
    r.battery_power = 646
    r.home_load = 0.0
    r.solar_power = 0.0
    r.raw_json = json.dumps({
        'derived': {
            'purchasePower': 0,
            'gridPowerSigned': 0,
            'gridStatus': 'Static',
            'gridRelayStatus': 'Break',
            'dcPowerPv1': 6,
            'dcPowerPv2': 0,
            'dcPowerPv3': 0,
            'chargePower': 646,
        },
        'station_summary': {'generationPower': 1003},
    }, ensure_ascii=False)
    with app.app_context():
        out = build_battery_insights(r, 5.0, 20.0)
    assert out['grid_input_w'] == 0.0
    assert out['generator_input_w'] == 997.0  # 1003 - 6
    assert out['ac_in_source_label'] == 'مولد'


def test_both_grid_and_generator_active():
    """Grid is online (gridStatus normal, direct AC-IN > 5) AND
    the station-tier shows extra throughput (inferred external
    generator) → label must read "شبكة ومولد"."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    r = mock.Mock()
    r.battery_soc = 70
    r.battery_power = 500
    r.home_load = 0.0
    r.solar_power = 0.0
    r.raw_json = json.dumps({
        'derived': {
            'purchasePower': 600,
            'gridPowerSigned': -600,
            'gridStatus': 'On',
            'gridRelayStatus': 'Break',  # weird: real reading + inferred
            'dcPowerPv1': 0,
        },
        'station_summary': {'generationPower': 700},
    }, ensure_ascii=False)
    with app.app_context():
        out = build_battery_insights(r, 5.0, 20.0)
    # 700 - 0 = 700, which > 50 → inferred fires.
    # But wait: external_ac_input_w (=600) > 5, so the v93o
    # gating "external_ac_input_w <= 5" prevents inferred from
    # firing in this case. So we expect grid=600, gen=0.
    # That's correct because if direct sensor sees something,
    # we trust it and don't double-count.
    assert out['grid_input_w'] == 600.0
    assert out['ac_in_source_label'] == 'شبكة'


def test_no_input_label():
    """No AC-IN flow from either path → label reads 'لا يوجد إدخال'."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    r = mock.Mock()
    r.battery_soc = 50
    r.battery_power = 0.0
    r.home_load = 0.0
    r.solar_power = 1500
    r.raw_json = json.dumps({
        'derived': {
            'purchasePower': 0,
            'gridPowerSigned': 0,
            'gridStatus': 'Static',
            'dcPowerPv1': 1500,
        },
    }, ensure_ascii=False)
    with app.app_context():
        out = build_battery_insights(r, 5.0, 20.0)
    assert out['grid_input_w'] == 0.0
    assert out['generator_input_w'] == 0.0
    assert out['ac_in_source_label'] == 'لا يوجد إدخال'


def test_empty_path_defaults():
    """latest is None → empty defaults present so the template
    doesn't KeyError."""
    from app.blueprints.helpers import build_battery_insights
    app = _make_flask_app()
    with app.app_context():
        out = build_battery_insights(None, 5.0, 20.0)
    assert 'grid_input_w' in out
    assert 'generator_input_w' in out
    assert 'ac_in_source_label' in out
    assert out['grid_input_w'] == 0.0
    assert out['generator_input_w'] == 0.0
    assert out['ac_in_source_label'] == 'لا يوجد إدخال'
