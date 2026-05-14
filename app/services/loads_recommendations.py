"""Heavy v10.5.37 — Loads Recommendations transformer.

Owner constraint (2026-05-14): the Flask backend must be the
**single source** of allow/deny decisions for both the web
dashboard and the mobile app. The previous v10.5.35 / v10.5.36
service re-implemented a parallel algorithm (priority + headroom
+ essentials override + predicted_next_hour_surplus), which
disagreed with the web at the same moment because the web uses
the **actual measured** surplus (after battery charge need) and
a simple `power_w ≤ safe_available` rule.

This module is now a thin TRANSFORMER over the web's
authoritative ``_smart_load_suggestions(latest, settings)`` in
``app/blueprints/main.py``. The mobile blueprint calls that
function — the same one the web template at
``app/templates/dashboard.html`` renders — and feeds its output
through :func:`transform_loads_suggestions` here to shape the
mobile JSON envelope.

What the web's helper returns (from main.py:597-616):
  * ``can_run``   — list of dicts {id, name, power_w, priority}
  * ``hold``      — list of dicts {id, name, power_w, priority}
  * ``safe_available_w`` — the watts a NEW load may consume now
  * ``raw_surplus_w``    — raw surplus (solar - home)
  * ``actual_surplus_w`` — raw_surplus minus battery_charge_need
  * ``battery_charge_need_w``
  * ``phase``     — ``'day'`` or ``'night'``
  * ``headline_ar``, ``mode_ar``, ``surplus_note_ar``
  * ``night_max_w``

What we expose to mobile:
  * ``available``, ``reason``, ``message`` — envelope
  * ``scope`` — {mode, device_id}
  * ``decision`` — {headline, summary, level, confidence}
  * ``items`` — per-load {load_id, name, power_w, priority,
                          allowed, reason}
  * ``totals`` — count + watt totals per bucket
  * ``surplus`` — {safe_available_w, raw_w, battery_need_w,
                   actual_w, phase, night_max_w} so the mobile
                   "اقتراح الأحمال" sub-section can show the same
                   surplus numbers the web shows on its dashboard.

Algorithm here is intentionally TRIVIAL — every decision was
already made on the web side. We only re-shape and re-label.
"""
from __future__ import annotations

from typing import Iterable


def _load_to_dict(load: dict, *, allowed: bool, reason: str) -> dict:
    """Convert a web-shape load dict ({id, name, power_w, priority})
    to the mobile-shape item dict.
    """
    return {
        'load_id': int(load.get('id') or 0),
        'name': str(load.get('name') or '').strip(),
        'power_w': float(load.get('power_w') or 0.0),
        'priority': int(load.get('priority') or 1),
        'allowed': bool(allowed),
        'reason': reason,
    }


def _empty_totals() -> dict:
    return {
        'enabled_load_count': 0,
        'allowed_count': 0,
        'denied_count': 0,
        'allowed_power_w': 0.0,
        'denied_power_w': 0.0,
    }


def _totals_from_items(items: Iterable[dict]) -> dict:
    items = list(items)
    allowed_count = 0
    denied_count = 0
    allowed_power = 0.0
    denied_power = 0.0
    for it in items:
        if it.get('allowed'):
            allowed_count += 1
            allowed_power += float(it.get('power_w') or 0.0)
        else:
            denied_count += 1
            denied_power += float(it.get('power_w') or 0.0)
    return {
        'enabled_load_count': len(items),
        'allowed_count': allowed_count,
        'denied_count': denied_count,
        'allowed_power_w': round(allowed_power, 1),
        'denied_power_w': round(denied_power, 1),
    }


def _decision_from_web(web: dict) -> dict:
    """Synthesise the mobile ``decision`` block from the web's
    ``headline_ar`` + ``mode_ar`` + ``phase`` + ``safe_available_w``.

    The decision level is a coarse summary so the mobile card can
    pick a tone (success / caution / warning) — the granular
    per-load answer lives in ``items`` and matches the web exactly.
    """
    headline = (web.get('headline_ar') or '').strip()
    mode = (web.get('mode_ar') or '').strip()
    surplus_note = (web.get('surplus_note_ar') or '').strip()
    phase = (web.get('phase') or '').strip().lower()
    can_run = web.get('can_run') or []
    hold = web.get('hold') or []
    safe_available = float(web.get('safe_available_w') or 0.0)

    summary_parts = []
    if mode:
        summary_parts.append(mode)
    if surplus_note:
        summary_parts.append(surplus_note)
    summary = ' • '.join(summary_parts) if summary_parts else headline

    # Tone mapping (matches the visual buckets in the mobile UI):
    #   * can_run non-empty                         → 'good'
    #   * no can_run but some safe_available remains → 'caution'
    #   * no can_run AND safe_available == 0 AND day → 'warning'
    #   * night phase with nothing runnable          → 'caution'
    if can_run:
        level = 'good'
    elif safe_available > 0:
        level = 'caution'
    elif phase == 'day':
        level = 'warning'
    else:
        level = 'caution'

    # Hold-only with no surplus during day is a meaningful
    # signal that the system is constrained — keep it as a
    # noticeable but non-critical state. We do NOT escalate to
    # 'critical' here because the smart_engine's level lives in
    # `/insights`; this endpoint stays focused on loads.
    if not can_run and not hold:
        # No enabled loads at all — neutral state.
        level = 'unknown'

    return {
        'headline': headline,
        'summary': summary,
        'level': level,
        'confidence': 'medium',
    }


def _surplus_block(web: dict) -> dict:
    """Mirror the surplus metrics the web shows on its dashboard
    so the mobile card can render the same numbers without
    re-querying ``compute_actual_solar_surplus``.
    """
    return {
        'safe_available_w': round(float(web.get('safe_available_w') or 0.0), 1),
        'raw_w': round(float(web.get('raw_surplus_w') or 0.0), 1),
        'battery_need_w': round(
            float(web.get('battery_charge_need_w') or 0.0), 1,
        ),
        'actual_w': round(float(web.get('actual_surplus_w') or 0.0), 1),
        'phase': (web.get('phase') or 'night').strip().lower(),
        'night_max_w': round(float(web.get('night_max_w') or 0.0), 1),
    }


def transform_loads_suggestions(
    *,
    web_result: dict,
    scope_mode: str,
    scope_device_id: int | None,
    generated_at: str,
    available: bool = True,
    reason: str | None = None,
    message: str | None = None,
) -> dict:
    """Build the mobile envelope from the web's
    ``_smart_load_suggestions`` output.

    When ``available`` is False, the ``web_result`` is treated as
    a stub (only ``reason`` / ``message`` and an empty items
    list matter) and the mobile envelope reflects that honestly.
    """
    scope = {'mode': scope_mode, 'device_id': scope_device_id}

    if not available:
        return {
            'available': False,
            'reason': reason or 'unavailable',
            'message': message
                or 'Loads recommendations are not available right now.',
            'scope': scope,
            'decision': None,
            'items': [],
            'totals': _empty_totals(),
            'surplus': _surplus_block(web_result or {}),
            'generated_at': generated_at,
        }

    can_run = web_result.get('can_run') or []
    hold = web_result.get('hold') or []
    safe_available = float(web_result.get('safe_available_w') or 0.0)
    phase = (web_result.get('phase') or 'day').strip().lower()

    # Per-load reasons. The web's algorithm is a single
    # `power_w ≤ safe_available` check, so the reason for each
    # bucket is uniform per phase.
    if phase == 'day':
        allowed_reason_template = (
            'الفائض الفعلي يكفي '
            '({safe} واط متاحة)'
        )
        denied_reason = 'الفائض الفعلي لا يكفي لتشغيل هذا الحمل الآن'
    else:
        allowed_reason_template = (
            'ضمن الحد الليلي المتاح '
            '({safe} واط متاحة)'
        )
        denied_reason = 'يتجاوز الحد الليلي للأحمال'

    items: list[dict] = []
    for load in can_run:
        items.append(_load_to_dict(
            load,
            allowed=True,
            reason=allowed_reason_template.format(
                safe=int(round(safe_available)),
            ),
        ))
    for load in hold:
        items.append(_load_to_dict(
            load,
            allowed=False,
            reason=denied_reason,
        ))

    totals = _totals_from_items(items)
    decision = _decision_from_web(web_result)

    return {
        'available': True,
        'reason': None,
        'message': None,
        'scope': scope,
        'decision': decision,
        'items': items,
        'totals': totals,
        'surplus': _surplus_block(web_result),
        'generated_at': generated_at,
    }
