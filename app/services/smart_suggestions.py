"""v102d-fix — proactive smart-suggestion notifications.

The Notifications screen has a "اقتراحات ذكية" bucket that only fills
when the backend writes events with one of the suggestion event types
(``smart_suggestion``, ``solar_surplus``, ``load_recommendation``,
``energy_optimization``). Without this module the bucket sat empty
because nothing was emitting those events on a regular cadence.

This module fixes that with two lightweight emitters:

* :func:`send_daily_smart_suggestions` — scheduled cron job. For each
  active subscriber + their active device, runs the existing smart
  engine (`build_smart_energy_advice`) and persists ONE
  ``smart_suggestion`` ``NotificationEvent`` per device per day with
  the engine's headline + actionable detail. Dedup is per-day
  (``YYYY-MM-DD`` + ``device_id`` + a stable ``digest_key`` embedded
  in ``result``) so re-runs of the cron during the day are no-ops.

* :func:`maybe_emit_surplus_suggestion` — called from the
  reading-save hook in ``main.sync_now_internal`` after the reading
  is committed. When the reading shows a sustained surplus
  (``surplus_w >= SURPLUS_W_THRESHOLD`` AND battery SoC above a
  comfort floor so we're not stealing from a half-empty pack), emits
  a single ``solar_surplus`` notification per device per day. Same
  dedup pattern as the daily suggestion.

Both writers use plain ``NotificationEvent`` rows (the same table the
mobile Notifications screen reads), so no API changes are needed on
the mobile side beyond the bucket classifier already accepting these
event types.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Optional

from flask import has_app_context

from ..extensions import db
from ..models import AppUser, Device, NotificationEvent, Reading

log = logging.getLogger(__name__)

# ── Tuning knobs ──────────────────────────────────────────────────────

SURPLUS_W_THRESHOLD = 800  # watts — minimum solar surplus to suggest a load
SURPLUS_SOC_FLOOR = 60     # percent — only suggest when battery is comfy
DAILY_SUGGESTION_EVENT = 'smart_suggestion'
SURPLUS_EVENT = 'solar_surplus'
SUGGESTION_SOURCE_TYPE = 'energy'


# ── Daily suggestion ──────────────────────────────────────────────────


def send_daily_smart_suggestions() -> int:
    """Cron entry point — emit one ``smart_suggestion`` notification
    per active subscriber-device pair per day.

    Returns the number of rows actually written (a re-run on the same
    day returns 0 because the dedup query short-circuits each pair).
    Always returns; never raises.
    """
    if not has_app_context():
        return 0

    rows_created = 0
    today_iso = date.today().isoformat()

    try:
        # Active subscribers with at least one device.
        subscribers = (
            AppUser.query
            .filter(AppUser.is_active.is_(True))
            .filter((AppUser.is_admin.is_(False)) | (AppUser.is_admin.is_(None)))
            .all()
        )
    except Exception as exc:
        log.warning('send_daily_smart_suggestions: subscriber query failed: %s', exc)
        return 0

    for owner in subscribers:
        try:
            devices = (
                Device.query
                .filter_by(user_id=owner.id, is_active=True)
                .order_by(Device.id.asc())
                .all()
            )
        except Exception:
            devices = []
        for dev in devices:
            try:
                rows_created += _emit_daily_suggestion_for_device(
                    owner=owner, device=dev, today_iso=today_iso,
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.warning(
                    'send_daily_smart_suggestions: per-device emit failed '
                    '(user=%s device=%s): %s',
                    owner.id, getattr(dev, 'id', '?'), exc,
                )

    if rows_created:
        try:
            db.session.commit()
            log.info('send_daily_smart_suggestions: wrote %d rows', rows_created)
        except Exception as exc:
            log.warning('send_daily_smart_suggestions: commit failed: %s', exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            return 0
    return rows_created


def _emit_daily_suggestion_for_device(
    *, owner: AppUser, device: Device, today_iso: str,
) -> int:
    digest_key = f'smart_suggestion:{device.id}:{today_iso}'
    if _already_emitted(owner.id, DAILY_SUGGESTION_EVENT, digest_key):
        return 0

    advice = _build_advice_for_device(device)
    if advice is None:
        return 0
    headline, detail = advice
    if not headline and not detail:
        return 0

    title = headline or 'اقتراح ذكي لليوم'
    message = detail or 'مراجعة لحالة النظام جاهزة في تبويب البطارية.'
    payload = json.dumps({
        'digest_key': digest_key,
        'device_id': device.id,
        'date': today_iso,
        'kind': 'daily',
    }, ensure_ascii=False)

    db.session.add(NotificationEvent(
        event_type=DAILY_SUGGESTION_EVENT,
        target_user_id=owner.id,
        tenant_id=getattr(owner, 'tenant_id', None),
        source_type=SUGGESTION_SOURCE_TYPE,
        source_id=device.id,
        title=title[:220],
        message=message,
        status='new',
        result=payload,
        is_read=False,
        appeared_in_bell=False,
        delivered_to_user=False,
        created_at=datetime.utcnow(),
    ))
    return 1


def _build_advice_for_device(device: Device) -> Optional[tuple[str, str]]:
    """Run the existing smart engine for ``device`` and return
    ``(headline, detail)`` or ``None`` when no advice can be produced
    (no readings yet, weather unavailable, etc.).

    Reuses ``build_smart_energy_advice`` verbatim — no parallel
    heuristics. The smart engine internally tolerates ``weather=None``
    and produces a sensible "no weather" advice; we still try to
    fetch weather first because the with-weather copy is far more
    useful.
    """
    try:
        latest = (
            Reading.query
            .filter_by(device_id=device.id)
            .order_by(Reading.created_at.desc(), Reading.id.desc())
            .first()
        )
        if latest is None:
            return None
    except Exception:
        return None

    weather = None
    try:
        from ..services.weather_service import fetch_weather
        from ..blueprints.mobile_devices_api import _extract_station_coords
        lat, lng = _extract_station_coords(latest)
        if lat is not None and lng is not None:
            tz_name = getattr(device, 'timezone', None) or 'UTC'
            weather = fetch_weather(lat, lng, tz_name)
    except Exception:
        weather = None

    settings = None
    try:
        from ..blueprints.helpers import load_settings
        settings = load_settings()
    except Exception:
        settings = None

    advice_dict = None
    try:
        from flask import g
        prev_user = getattr(g, 'current_user', None)
        prev_device = getattr(g, 'current_device', None)
        try:
            owner = AppUser.query.get(getattr(device, 'user_id', None))
            if owner is not None:
                g.current_user = owner
            g.current_device = device
            from ..blueprints.smart_engine import build_smart_energy_advice
            advice_dict = build_smart_energy_advice(
                latest, weather=weather, settings=settings, context='periodic_day',
            )
        finally:
            g.current_user = prev_user
            g.current_device = prev_device
    except Exception as exc:
        log.warning(
            'smart_suggestions: build_smart_energy_advice failed for device %s: %s',
            getattr(device, 'id', '?'), exc,
        )
        return None

    if not isinstance(advice_dict, dict):
        return None
    headline = (advice_dict.get('headline') or '').strip()
    # The smart engine returns separate `smart_warning` /
    # `smart_recommendation` keys; mobile concatenates them as
    # `detail`. We do the same here.
    parts = []
    for key in ('smart_warning', 'smart_recommendation', 'detail'):
        raw = advice_dict.get(key)
        if raw and isinstance(raw, str) and raw.strip():
            parts.append(raw.strip())
    detail = '\n\n'.join(parts) if parts else ''
    return headline, detail


# ── Surplus suggestion ────────────────────────────────────────────────


def maybe_emit_surplus_suggestion(reading: Reading) -> bool:
    """Hook called from the reading-save path. Emits ONE
    ``solar_surplus`` notification per device per day when the new
    reading shows a meaningful surplus AND the battery is comfortable.

    Returns ``True`` when a row was committed, ``False`` when the
    reading didn't qualify or the suggestion was already emitted
    today. Always returns; never raises.
    """
    try:
        if not reading or not reading.device_id:
            return False
        solar = float(reading.solar_power or 0)
        load = float(reading.home_load or 0)
        soc = float(reading.battery_soc or 0)
        surplus = solar - load
        if surplus < SURPLUS_W_THRESHOLD:
            return False
        if soc < SURPLUS_SOC_FLOOR:
            return False

        device = Device.query.get(reading.device_id)
        if device is None:
            return False
        owner_id = device.user_id
        if not owner_id:
            return False
        owner = AppUser.query.get(owner_id)
        if owner is None or not getattr(owner, 'is_active', True):
            return False

        today_iso = date.today().isoformat()
        digest_key = f'solar_surplus:{device.id}:{today_iso}'
        if _already_emitted(owner.id, SURPLUS_EVENT, digest_key):
            return False

        title = 'فرصة لتشغيل أحمال إضافية'
        message = (
            f'الفائض الشمسي الآن ≈ {int(round(surplus))} واط، والبطارية '
            f'{int(round(soc))}%. وقت مناسب لتشغيل غسالة، سخان، أو سحب '
            'كميّة شحن من السيارة الكهربائية دون استنزاف البطارية.'
        )
        payload = json.dumps({
            'digest_key': digest_key,
            'device_id': device.id,
            'date': today_iso,
            'surplus_w': int(round(surplus)),
            'soc_percent': int(round(soc)),
            'kind': 'surplus',
        }, ensure_ascii=False)

        db.session.add(NotificationEvent(
            event_type=SURPLUS_EVENT,
            target_user_id=owner.id,
            tenant_id=getattr(owner, 'tenant_id', None),
            source_type=SUGGESTION_SOURCE_TYPE,
            source_id=device.id,
            title=title[:220],
            message=message,
            status='new',
            result=payload,
            is_read=False,
            appeared_in_bell=False,
            delivered_to_user=False,
            created_at=datetime.utcnow(),
        ))
        db.session.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        log.warning('maybe_emit_surplus_suggestion: failed: %s', exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


# ── Shared dedup helper ───────────────────────────────────────────────


def _already_emitted(user_id: int, event_type: str, digest_key: str) -> bool:
    try:
        existing = (
            NotificationEvent.query
            .filter_by(target_user_id=user_id, event_type=event_type)
            .filter(NotificationEvent.result.like(f'%{digest_key}%'))
            .first()
        )
        return existing is not None
    except Exception:
        # If the dedup query itself fails, prefer NOT inserting to
        # avoid spamming on retry.
        return True


__all__ = [
    'SURPLUS_W_THRESHOLD',
    'SURPLUS_SOC_FLOOR',
    'DAILY_SUGGESTION_EVENT',
    'SURPLUS_EVENT',
    'send_daily_smart_suggestions',
    'maybe_emit_surplus_suggestion',
]
