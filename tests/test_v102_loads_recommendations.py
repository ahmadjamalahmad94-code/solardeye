"""Heavy v10.5.37 — Loads Recommendations transformer tests.

The mobile endpoint is now a thin wrapper over the web's
``_smart_load_suggestions`` helper (single source of truth).
This module's algorithm is therefore a TRANSFORMER: given a web
result dict, shape it into the mobile envelope.

The tests exercise the transformer in isolation by feeding it
synthetic web-result dicts that mimic the keys
``_smart_load_suggestions`` actually emits (see main.py:597-616).

Cases:
  T1 — happy path, day, mixed can_run/hold.
  T2 — day phase, no can_run, hold-only with zero safe_available
       (the "all hold" scenario the owner reported).
  T3 — night phase, hold-only — level resolves to 'caution', not
       'warning'.
  T4 — no enabled loads at all → items=[], decision.level=unknown.
  T5 — `available=false, reason='reading_unavailable'` envelope.
  T6 — surplus block carries the four headline metrics
       (safe / raw / battery / actual + phase + night_max).
  T7 — totals correctly split watts across the two buckets.
  T8 — endpoint is registered and references the new transformer.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _web(**overrides):
    """Synthetic web-result. Mirrors the keys main.py:597-616
    emits — keep this in sync if `_smart_load_suggestions`'s
    output shape ever changes."""
    base = {
        'available_w': 0.0,
        'safe_available_w': 0.0,
        'actual_surplus_w': 0.0,
        'raw_surplus_w': 0.0,
        'battery_charge_need_w': 0.0,
        'battery_soc': 0.0,
        'can_run': [],
        'hold': [],
        'headline_ar': '',
        'headline_en': '',
        'mode_ar': '',
        'mode_en': '',
        'phase': 'day',
        'night_max_w': 500.0,
        'surplus_note_ar': '',
        'surplus_note_en': '',
    }
    base.update(overrides)
    return base


def _load(*, id_: int, name: str, power_w: float, priority: int = 1):
    return {
        'id': id_,
        'name': name,
        'power_w': power_w,
        'priority': priority,
    }


# ── T1 — happy path, day, mixed ──────────────────────────────────


def test_t1_day_mixed_can_run_and_hold():
    from app.services.loads_recommendations import transform_loads_suggestions
    web = _web(
        safe_available_w=300,
        raw_surplus_w=1200,
        battery_charge_need_w=900,
        actual_surplus_w=300,
        phase='day',
        headline_ar='يمكنك الآن تشغيل: ثلاجة',
        mode_ar='يعتمد الاقتراح الآن على الفائض الشمسي الفعلي',
        can_run=[_load(id_=1, name='ثلاجة', power_w=200)],
        hold=[_load(id_=2, name='فرن', power_w=2500)],
    )
    out = transform_loads_suggestions(
        web_result=web,
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T15:00:00',
    )
    assert out['available'] is True
    assert out['decision']['level'] == 'good'
    assert out['decision']['headline'] == 'يمكنك الآن تشغيل: ثلاجة'
    by_id = {it['load_id']: it for it in out['items']}
    assert by_id[1]['allowed'] is True
    assert 'الفائض الفعلي يكفي' in by_id[1]['reason']
    assert by_id[2]['allowed'] is False
    assert 'الفائض الفعلي لا يكفي' in by_id[2]['reason']
    assert out['totals']['allowed_count'] == 1
    assert out['totals']['denied_count'] == 1


# ── T2 — day, zero surplus, hold-only (owner's reported scenario)


def test_t2_day_zero_surplus_hold_only_level_warning():
    from app.services.loads_recommendations import transform_loads_suggestions
    web = _web(
        safe_available_w=0.0,
        raw_surplus_w=0.0,
        battery_charge_need_w=210.9,
        actual_surplus_w=0.0,
        phase='day',
        headline_ar='يفضل تأجيل تشغيل الأحمال الإضافية الآن',
        mode_ar='يعتمد الاقتراح الآن على الفائض الشمسي الفعلي',
        can_run=[],
        hold=[
            _load(id_=1, name='ثلاجة', power_w=200),
            _load(id_=2, name='قلاية', power_w=1600),
        ],
    )
    out = transform_loads_suggestions(
        web_result=web,
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T15:00:00',
    )
    # Even a "small" essential load is denied — the web's algorithm
    # is `power_w ≤ safe_available` and safe_available is 0.
    assert out['decision']['level'] == 'warning'
    assert out['totals']['allowed_count'] == 0
    assert out['totals']['denied_count'] == 2
    assert all(it['allowed'] is False for it in out['items'])
    assert 'يفضل تأجيل' in out['decision']['headline']


# ── T3 — night, hold-only, level=caution not warning ─────────────


def test_t3_night_phase_hold_only_level_caution():
    from app.services.loads_recommendations import transform_loads_suggestions
    web = _web(
        safe_available_w=0.0,
        phase='night',
        headline_ar='يفضل تأجيل تشغيل الأحمال الإضافية الآن',
        mode_ar='ليلًا: الحد المعتمد 500 واط',
        can_run=[],
        hold=[_load(id_=1, name='ثلاجة', power_w=200)],
    )
    out = transform_loads_suggestions(
        web_result=web,
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T22:00:00',
    )
    # Night with nothing runnable stays at 'caution' — we don't
    # raise to 'warning' because lack of solar at night is
    # expected and not an alert state.
    assert out['decision']['level'] == 'caution'
    assert out['items'][0]['allowed'] is False
    assert 'الحد الليلي' in out['items'][0]['reason']


# ── T4 — no enabled loads ───────────────────────────────────────


def test_t4_no_loads_neutral_state():
    from app.services.loads_recommendations import transform_loads_suggestions
    web = _web(
        safe_available_w=500.0,
        can_run=[],
        hold=[],
        phase='day',
    )
    out = transform_loads_suggestions(
        web_result=web,
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T15:00:00',
    )
    assert out['items'] == []
    assert out['decision']['level'] == 'unknown'
    assert out['totals']['enabled_load_count'] == 0


# ── T5 — reading_unavailable envelope ────────────────────────────


def test_t5_reading_unavailable_envelope():
    from app.services.loads_recommendations import transform_loads_suggestions
    out = transform_loads_suggestions(
        web_result={},
        scope_mode='device',
        scope_device_id=7,
        generated_at='2026-05-14T15:00:00',
        available=False,
        reason='reading_unavailable',
        message='No recent reading is available for this device yet.',
    )
    assert out['available'] is False
    assert out['reason'] == 'reading_unavailable'
    assert out['items'] == []
    assert out['decision'] is None
    assert out['totals']['enabled_load_count'] == 0


# ── T6 — surplus block carries headline metrics ──────────────────


def test_t6_surplus_block_is_complete():
    from app.services.loads_recommendations import transform_loads_suggestions
    web = _web(
        safe_available_w=300.0,
        raw_surplus_w=1200.0,
        battery_charge_need_w=900.0,
        actual_surplus_w=300.0,
        phase='day',
        night_max_w=500.0,
    )
    out = transform_loads_suggestions(
        web_result=web,
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T15:00:00',
    )
    assert out['surplus'] == {
        'safe_available_w': 300.0,
        'raw_w': 1200.0,
        'battery_need_w': 900.0,
        'actual_w': 300.0,
        'phase': 'day',
        'night_max_w': 500.0,
    }


# ── T7 — totals split watts across buckets ───────────────────────


def test_t7_totals_split_watts():
    from app.services.loads_recommendations import transform_loads_suggestions
    web = _web(
        safe_available_w=400.0,
        phase='day',
        can_run=[
            _load(id_=1, name='ثلاجة', power_w=200),
            _load(id_=2, name='شاشة', power_w=40),
        ],
        hold=[
            _load(id_=3, name='فرن', power_w=2500),
            _load(id_=4, name='قلاية', power_w=1600),
        ],
    )
    out = transform_loads_suggestions(
        web_result=web,
        scope_mode='device',
        scope_device_id=1,
        generated_at='2026-05-14T15:00:00',
    )
    assert out['totals']['allowed_count'] == 2
    assert out['totals']['denied_count'] == 2
    assert out['totals']['allowed_power_w'] == 240.0
    assert out['totals']['denied_power_w'] == 4100.0


# ── T8 — endpoint references the transformer ─────────────────────


def test_t8_endpoint_references_transformer():
    from app.blueprints import mobile_api as mod
    handler = getattr(mod, 'mobile_load_recommendations', None)
    assert handler is not None
    import inspect
    src = inspect.getsource(handler)
    # The new endpoint calls into the web helper directly + uses
    # the transformer. Both references must be present.
    assert '_smart_load_suggestions' in src
    assert 'transform_loads_suggestions' in src
