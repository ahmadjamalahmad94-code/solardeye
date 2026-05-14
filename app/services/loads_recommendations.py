"""Heavy v10.5.35 — Loads Recommendations decision logic.

Pure function over the existing ``smart_engine`` output + a list
of ``UserLoad`` rows. The Flask blueprint
``mobile_api.mobile_load_recommendations`` is a thin HTTP wrapper
that calls into here.

Design (matches ``docs/LOADS_BACKEND_SPEC.md`` in the mobile repo):

* Flask backend is the **sole** source of truth for the
  allow/deny decision. No mobile-side heuristic, no mock data.
* Same ``build_smart_energy_advice`` output the web dashboard
  uses (re-used read-only here — never re-implemented).
* ``UserLoad`` model is **not** modified — every input the
  algorithm needs already exists as a column.
* Algorithm is deterministic: same inputs → same outputs.
* No web UI / no Flow Graph touch. This module is server-side
  only and contains zero rendering code.

Conservative when uncertain:
  * ``critical`` level    → every load denied.
  * ``unknown`` level     → only priority-1 essentials run.
  * ``good`` / ``caution`` / ``warning`` → priority-aware
    surplus accounting with a headroom factor that tightens as
    the level worsens.

Priority semantics: smaller ``priority`` value means HIGHER
priority. The constant ``ESSENTIAL_PRIORITY_THRESHOLD`` defines
the cutoff for the "essentials override" branch (priority ≤ 1).

Surplus unit: ``predicted_next_hour_surplus`` is in kilowatts
per ``smart_engine.build_smart_energy_advice``. We multiply by
1000 to compare against ``UserLoad.power_w``.
"""
from __future__ import annotations

from typing import Iterable, Sequence

# Headroom multipliers — see SPEC §3.2. Module-level so the
# owner can tune after a real-device run without re-reading the
# whole algorithm.
HEADROOM_BY_LEVEL: dict[str, float] = {
    'good': 1.0,
    'caution': 1.3,
    'warning': 1.8,
}

# Essential cutoff. Priority values at or below this are treated
# as must-run (non-critical levels MAY grant them an override
# when surplus is insufficient — gated by ESSENTIALS_POWER_CAP_W
# so a 2 kW "essential" doesn't slip through on a low-battery day).
ESSENTIAL_PRIORITY_THRESHOLD: int = 1

# v10.5.36 — power-aware essentials override.
#
# First on-device run revealed that owners often classify every
# load as `priority=1` (a UX wart in the loads-management screen,
# not the algorithm's fault). With the unconditional override
# from v10.5.35 the result was "all 17 loads allowed" — useless
# for the mobile cards.
#
# The override now ALSO requires `power_w <= ESSENTIALS_POWER_CAP_W[level]`,
# so a 30 W fan still gets the override but a 1600 W air fryer
# does not. The cap tightens with system stress.
ESSENTIALS_POWER_CAP_W: dict[str, float] = {
    'good': 2000.0,
    'caution': 500.0,
    'warning': 200.0,
}


def _safe_power_w(load) -> float:
    raw = getattr(load, 'power_w', None)
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def _safe_priority(load) -> int:
    raw = getattr(load, 'priority', None)
    if raw is None:
        return 99
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 99


def _load_to_dict(load, *, allowed: bool, reason: str) -> dict:
    return {
        'load_id': int(getattr(load, 'id', 0) or 0),
        'name': str(getattr(load, 'name', '') or '').strip(),
        'power_w': _safe_power_w(load),
        'priority': _safe_priority(load),
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


def _totals_from_items(items: Sequence[dict]) -> dict:
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


def _decision_from_advice(advice_dict) -> dict:
    """Mirror ``mobile_devices_api._mobile_energy_advice`` shape so
    the two surfaces (insights + loads recommendations) agree on
    tone vocabulary.
    """
    raw = advice_dict if isinstance(advice_dict, dict) else {}
    headline = (raw.get('status_label') or '').strip()
    warning = (raw.get('smart_warning') or '').strip()
    recommendation = (raw.get('smart_recommendation') or '').strip()
    decision = (raw.get('decision_now') or '').strip()
    summary_parts = []
    if warning:
        summary_parts.append(warning)
    if recommendation:
        summary_parts.append(recommendation)
    elif decision:
        summary_parts.append(decision)
    summary = ' '.join(summary_parts).strip()

    if '🟢' in headline:
        level = 'good'
    elif '🟡' in headline:
        level = 'caution'
    elif '🟠' in headline:
        level = 'warning'
    elif '🔴' in headline:
        level = 'critical'
    else:
        level = 'unknown'

    confidence = (raw.get('confidence_band') or '').strip().lower()
    if confidence not in {'low', 'medium', 'high'}:
        confidence = 'unknown'

    return {
        'headline': headline,
        'summary': summary,
        'level': level,
        'confidence': confidence,
    }


def _surplus_w_from_advice(advice_dict) -> float:
    """Convert ``predicted_next_hour_surplus`` (kW) → W. Returns
    ``0.0`` when the helper had no estimate (treat as no surplus
    available — conservative)."""
    if not isinstance(advice_dict, dict):
        return 0.0
    raw = advice_dict.get('predicted_next_hour_surplus')
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(raw) * 1000.0)
    except (TypeError, ValueError):
        return 0.0


def build_loads_recommendations(
    *,
    enabled_loads: Iterable,
    advice_dict,
    scope_mode: str,
    scope_device_id: int | None,
    generated_at: str,
    available: bool = True,
    reason: str | None = None,
    message: str | None = None,
) -> dict:
    """Build the loads-recommendations response payload.

    Inputs are passed in plain Python — the function does not
    touch the DB session or Flask request context. The blueprint
    is responsible for fetching ``enabled_loads`` (already
    filtered by ``is_enabled=True`` and scoped per the
    ``device_id`` query param) and ``advice_dict`` (from
    ``build_smart_energy_advice``).
    """
    scope = {
        'mode': scope_mode,
        'device_id': scope_device_id,
    }

    if not available:
        return {
            'available': False,
            'reason': reason or 'unavailable',
            'message': message or 'Loads recommendations are not available right now.',
            'scope': scope,
            'decision': None,
            'items': [],
            'totals': _empty_totals(),
            'generated_at': generated_at,
        }

    decision = _decision_from_advice(advice_dict)
    level = decision['level']
    items: list[dict] = []
    remaining_w = _surplus_w_from_advice(advice_dict)

    # Stable order: priority ASC (essentials first), then by id ASC
    # as a deterministic tie-breaker so two loads with the same
    # priority always classify the same way across calls.
    loads_sorted = sorted(
        list(enabled_loads),
        key=lambda load: (
            _safe_priority(load),
            int(getattr(load, 'id', 0) or 0),
        ),
    )

    for load in loads_sorted:
        priority = _safe_priority(load)
        power_w = _safe_power_w(load)

        if level == 'critical':
            items.append(_load_to_dict(
                load,
                allowed=False,
                reason='الحالة حرجة — يُفضَّل تأجيل كل الأحمال',
            ))
            continue

        if level == 'unknown':
            if priority <= ESSENTIAL_PRIORITY_THRESHOLD:
                items.append(_load_to_dict(
                    load,
                    allowed=True,
                    reason='حمل أساسي',
                ))
            else:
                items.append(_load_to_dict(
                    load,
                    allowed=False,
                    reason='القرار غير محدد — أجِّل غير الضروري',
                ))
            continue

        headroom = HEADROOM_BY_LEVEL.get(level, 1.5)
        needed_w = power_w * headroom

        if remaining_w >= needed_w:
            items.append(_load_to_dict(
                load,
                allowed=True,
                reason=f'الفائض المتوقع كافٍ ({int(remaining_w)} و)',
            ))
            remaining_w -= power_w
        else:
            power_cap = ESSENTIALS_POWER_CAP_W.get(level, 0.0)
            is_essential = (
                priority <= ESSENTIAL_PRIORITY_THRESHOLD
                and power_w <= power_cap
            )
            if is_essential:
                items.append(_load_to_dict(
                    load,
                    allowed=True,
                    reason='حمل أساسي خفيف — مسموح رغم محدودية الفائض',
                ))
            else:
                items.append(_load_to_dict(
                    load,
                    allowed=False,
                    reason=f'الفائض المتوقع لا يكفي ({int(power_w)} و)',
                ))

    totals = _totals_from_items(items)

    return {
        'available': True,
        'reason': None,
        'message': None,
        'scope': scope,
        'decision': decision,
        'items': items,
        'totals': totals,
        'generated_at': generated_at,
    }
