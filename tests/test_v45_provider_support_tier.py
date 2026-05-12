"""v45 — provider support-tier audit + label tests.

These guards lock in two invariants that survive any future change to
the catalog:

  1. Every approved provider code is tagged with the exact tier the
     v45 product brief specifies (live / beta / blueprint).
  2. The visible Arabic / English labels never leak a raw machine
     code to the UI, even when the input is unknown or empty.

The mobile payload + web template both render via the same single
source of truth (`resolve_support_tier` / `support_tier_label`), so
locking the table here covers every UI surface.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _resolve(code):
    from app.services.energy_integrations import (
        PROVIDER_MAP,
        resolve_support_tier,
    )
    return resolve_support_tier(PROVIDER_MAP[code])


# ─── invariant: every approved provider is tagged correctly ───────────


def test_live_supported_providers():
    assert _resolve('deye') == 'live-supported'
    assert _resolve('fronius_local') == 'live-supported'
    assert _resolve('shelly_gen2') == 'live-supported'
    assert _resolve('opendtu_local') == 'live-supported'


def test_beta_supported_providers():
    for code in (
        'solaredge_cloud',
        'victron_vrm',
        'home_assistant_energy',
        'growatt_v1',
        'kostal_plenticore_local',
        'enphase_enlighten',
        'tesla_energy',
        'solarman_openapi',
        'sungrow_isolarcloud',
        'goodwe_sems',
        'soliscloud_v2',
    ):
        assert _resolve(code) == 'beta-supported', code


def test_blueprint_only_providers():
    for code in (
        'sma_cloud',
        'huawei_fusionsolar',
        'modbus_tcp_energy',
        'mqtt_energy_gateway',
        'apsystems_ema',
        'tigo_energy_intelligence',
    ):
        assert _resolve(code) == 'blueprint-only', code


def test_every_catalog_code_is_in_the_tier_table():
    """No silent default — every shipped provider must have an
    explicit tier in PROVIDER_SUPPORT_TIERS. If a new provider is
    added to the catalog without a tier mapping, this test fails."""
    from app.services.energy_integrations import (
        PROVIDER_CATALOG,
        PROVIDER_SUPPORT_TIERS,
    )
    catalog_codes = {spec.code for spec in PROVIDER_CATALOG}
    table_codes = set(PROVIDER_SUPPORT_TIERS.keys())
    missing = catalog_codes - table_codes
    assert not missing, f'providers missing a tier mapping: {missing}'


# ─── invariant: visible labels never leak a raw code ─────────────────


def test_support_tier_label_arabic():
    from app.services.energy_integrations import support_tier_label
    assert support_tier_label('live-supported', 'ar') == 'مدعوم'
    assert support_tier_label('beta-supported', 'ar') == 'تجريبي'
    assert support_tier_label('blueprint-only', 'ar') == 'قيد التهيئة'


def test_support_tier_label_english():
    from app.services.energy_integrations import support_tier_label
    assert support_tier_label('live-supported', 'en') == 'Supported'
    assert support_tier_label('beta-supported', 'en') == 'Beta'
    assert support_tier_label('blueprint-only', 'en') == 'Coming soon'


def test_support_tier_label_falls_back_for_unknown_or_empty():
    from app.services.energy_integrations import support_tier_label
    # Unknown / empty / None / whitespace all render the safe-default
    # beta label, never the raw machine code.
    assert support_tier_label(None) == 'تجريبي'
    assert support_tier_label('') == 'تجريبي'
    assert support_tier_label('   ') == 'تجريبي'
    assert support_tier_label('made-up-tier') == 'تجريبي'
    assert support_tier_label('made-up-tier', 'en') == 'Beta'


def test_support_tier_label_is_case_insensitive():
    from app.services.energy_integrations import support_tier_label
    assert support_tier_label('LIVE-SUPPORTED', 'ar') == 'مدعوم'
    assert support_tier_label('Blueprint-Only', 'en') == 'Coming soon'


# ─── invariant: serializers carry the tier through ───────────────────


def test_as_device_type_payload_includes_resolved_tier():
    from app.services.energy_integrations import PROVIDER_MAP
    payload = PROVIDER_MAP['deye'].as_device_type_payload()
    assert payload['support_tier'] == 'live-supported'
    payload_blueprint = PROVIDER_MAP['sma_cloud'].as_device_type_payload()
    assert payload_blueprint['support_tier'] == 'blueprint-only'
