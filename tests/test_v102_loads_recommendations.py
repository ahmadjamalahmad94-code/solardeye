"""Heavy v10.5.35 — Loads Recommendations unit tests.

Covers `app/services/loads_recommendations.py` as a pure function
(no DB, no Flask context) plus the endpoint-registration smoke
test. Decision logic mirrors `docs/LOADS_BACKEND_SPEC.md` §3.2.

Cases:
  R1 — no loads + good level → empty items, totals zero.
  R2 — critical level → every load denied with the same reason.
  R3 — unknown level → only priority<=1 essentials allowed.
  R4 — good level, surplus 3000 W, three loads → all allowed
       in priority order; remaining_w shrinks correctly.
  R5 — warning level, surplus 1000 W → essentials (priority<=1)
       override; mid-priority denied because headroom 1.8x
       blows past surplus.
  R6 — reading_unavailable envelope is shaped honestly.
  R7 — `predicted_next_hour_surplus` is None → treated as 0 W;
       non-essentials denied.
  R8 — endpoint path is registered (smoke).
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ── helpers ───────────────────────────────────────────────────────


def _fake_load(*, load_id: int, name: str, power_w: float, priority: int):
    """SimpleNamespace fixture matching the columns
    `build_loads_recommendations` reads from a UserLoad row."""
    return SimpleNamespace(
        id=load_id, name=name, power_w=power_w, priority=priority,
    )


def _advice(*, status_label: str = '🟢 مطمئن',
            smart_warning: str = '',
            smart_recommendation: str = '',
            decision_now: str = '',
            predicted_next_hour_surplus=None,
            confidence_band: str = 'medium') -> dict:
    return {
        'status_label': status_label,
        'smart_warning': smart_warning,
        'smart_recommendation': smart_recommendation,
        'decision_now': decision_now,
        'predicted_next_hour_surplus': predicted_next_hour_surplus,
        'confidence_band': confidence_band,
    }


# ── R1 — no loads ─────────────────────────────────────────────────


def test_r1_no_loads_returns_empty_items_and_zero_totals():
    from app.services.loads_recommendations import build_loads_recommendations
    out = build_loads_recommendations(
        enabled_loads=[],
        advice_dict=_advice(predicted_next_hour_surplus=3.0),
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T12:00:00',
    )
    assert out['available'] is True
    assert out['items'] == []
    assert out['totals'] == {
        'enabled_load_count': 0,
        'allowed_count': 0,
        'denied_count': 0,
        'allowed_power_w': 0.0,
        'denied_power_w': 0.0,
    }
    assert out['decision']['level'] == 'good'


# ── R2 — critical denies every load ──────────────────────────────


def test_r2_critical_level_denies_all_loads_with_unified_reason():
    from app.services.loads_recommendations import build_loads_recommendations
    loads = [
        _fake_load(load_id=10, name='ثلاجة', power_w=200, priority=1),
        _fake_load(load_id=11, name='فرن', power_w=2500, priority=3),
    ]
    out = build_loads_recommendations(
        enabled_loads=loads,
        advice_dict=_advice(
            status_label='🔴 حرج',
            predicted_next_hour_surplus=5.0,  # ignored at critical
        ),
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T12:00:00',
    )
    assert out['decision']['level'] == 'critical'
    assert all(item['allowed'] is False for item in out['items'])
    assert all('الحالة حرجة' in item['reason'] for item in out['items'])
    assert out['totals']['allowed_count'] == 0
    assert out['totals']['denied_count'] == 2


# ── R3 — unknown level — only essentials run ─────────────────────


def test_r3_unknown_level_allows_only_essentials():
    from app.services.loads_recommendations import build_loads_recommendations
    loads = [
        _fake_load(load_id=10, name='ثلاجة', power_w=200, priority=1),
        _fake_load(load_id=11, name='غسالة', power_w=1200, priority=3),
    ]
    out = build_loads_recommendations(
        enabled_loads=loads,
        advice_dict=_advice(
            status_label='⚪ غير محدد',
            predicted_next_hour_surplus=None,
        ),
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T12:00:00',
    )
    assert out['decision']['level'] == 'unknown'
    by_id = {item['load_id']: item for item in out['items']}
    assert by_id[10]['allowed'] is True
    assert 'حمل أساسي' in by_id[10]['reason']
    assert by_id[11]['allowed'] is False
    assert 'القرار غير محدد' in by_id[11]['reason']


# ── R4 — good level, surplus 3000 W, three loads ─────────────────


def test_r4_good_level_surplus_eats_loads_in_priority_order():
    from app.services.loads_recommendations import build_loads_recommendations
    loads = [
        _fake_load(load_id=10, name='ثلاجة', power_w=500, priority=1),
        _fake_load(load_id=11, name='غسالة', power_w=1200, priority=2),
        _fake_load(load_id=12, name='فرن', power_w=2500, priority=3),
    ]
    out = build_loads_recommendations(
        enabled_loads=loads,
        advice_dict=_advice(
            status_label='🟢 مطمئن',
            predicted_next_hour_surplus=3.0,  # 3 kW = 3000 W
        ),
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T12:00:00',
    )
    by_id = {item['load_id']: item for item in out['items']}
    # priority 1 + 2 fit (500 + 1200 = 1700 W); priority 3 needs
    # 2500 W but only 1300 W remains → denied.
    assert by_id[10]['allowed'] is True
    assert by_id[11]['allowed'] is True
    assert by_id[12]['allowed'] is False
    assert out['totals']['allowed_count'] == 2
    assert out['totals']['denied_count'] == 1


# ── R5 — warning level, surplus 1000 W, essentials override ──────


def test_r5_warning_level_essentials_override_when_surplus_short():
    from app.services.loads_recommendations import build_loads_recommendations
    loads = [
        _fake_load(load_id=10, name='ثلاجة', power_w=200, priority=1),
        _fake_load(load_id=11, name='غسالة', power_w=1200, priority=2),
        _fake_load(load_id=12, name='فرن', power_w=2500, priority=3),
    ]
    out = build_loads_recommendations(
        enabled_loads=loads,
        advice_dict=_advice(
            status_label='🟠 احذر',
            smart_warning='البطارية منخفضة',
            predicted_next_hour_surplus=1.0,  # 1 kW = 1000 W
        ),
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T12:00:00',
    )
    by_id = {item['load_id']: item for item in out['items']}
    # priority 1: 200 W × 1.8 = 360 W, surplus 1000 ≥ 360 → allowed
    assert by_id[10]['allowed'] is True
    # priority 2: 1200 W × 1.8 = 2160 W, surplus 640 W remaining
    # after the fridge consumed 200 → 640 < 2160 → denied (NOT
    # essential, so no override).
    assert by_id[11]['allowed'] is False
    # priority 3: 2500 W × 1.8 = 4500 W, surplus much less → denied
    assert by_id[12]['allowed'] is False
    assert out['decision']['level'] == 'warning'


# ── R6 — reading_unavailable envelope ─────────────────────────────


def test_r6_reading_unavailable_envelope_is_honest():
    from app.services.loads_recommendations import build_loads_recommendations
    out = build_loads_recommendations(
        enabled_loads=[],
        advice_dict=None,
        scope_mode='device',
        scope_device_id=7,
        generated_at='2026-05-14T12:00:00',
        available=False,
        reason='reading_unavailable',
        message='No recent reading is available for this device yet.',
    )
    assert out['available'] is False
    assert out['reason'] == 'reading_unavailable'
    assert out['items'] == []
    assert out['decision'] is None
    assert out['scope']['device_id'] == 7
    assert out['totals']['enabled_load_count'] == 0


# ── R7 — surplus None → treated as 0 W ────────────────────────────


def test_r7_none_surplus_treated_as_zero():
    from app.services.loads_recommendations import build_loads_recommendations
    loads = [
        _fake_load(load_id=10, name='ثلاجة', power_w=200, priority=1),
        _fake_load(load_id=11, name='غسالة', power_w=1200, priority=2),
    ]
    out = build_loads_recommendations(
        enabled_loads=loads,
        advice_dict=_advice(
            status_label='🟡 ابقَ منتبهاً',
            predicted_next_hour_surplus=None,
        ),
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T12:00:00',
    )
    by_id = {item['load_id']: item for item in out['items']}
    # Essential allowed via override; non-essential denied (0 W
    # surplus < anything).
    assert by_id[10]['allowed'] is True
    assert by_id[11]['allowed'] is False
    assert out['decision']['level'] == 'caution'


# ── R8 — endpoint path is registered ──────────────────────────────


def test_r8_endpoint_path_is_registered_under_mobile_blueprint():
    from app.blueprints import mobile_api as mod
    handler = getattr(mod, 'mobile_load_recommendations', None)
    assert handler is not None
    src = handler.__doc__ or ''
    # Cheap sanity check that we replaced the stub, not preserved it.
    assert 'live endpoint' in src or 'real per-load' in src or 'v10.5.35' in src
