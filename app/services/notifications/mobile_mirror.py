"""Mirror an already-decided energy / load / solar / weather notification
into the mobile Notification Center.

Background
----------
The Flask backend already sends Telegram and SMS notifications through
two well-defined chokepoints:

    * ``dispatch_notification`` — used for "live" energy events
      (battery cross thresholds, day deficit, night load, weather
      transitions, temperature alerts, periodic-status, pre-sunset,
      morning-report).
    * ``_send_scheduled_notification`` — used for scheduled events
      (periodic_day, periodic_night, pre_sunset window, load_alert,
      battery_test, daily_report).

Both functions persist a row into ``NotificationLog`` (the per-channel
send-log table). That table is **not** what the mobile Notification
Center reads. The mobile API reads ``NotificationEvent`` (the user-
facing inbox table that stores ``event_type`` / ``source_type`` /
``is_read`` / ``target_user_id`` / ``tenant_id``).

This module bridges the two: when the backend has *already decided* to
send a notification (i.e. dedup has passed and a Telegram/SMS dispatch
is happening), we also persist a single ``NotificationEvent`` row so
the mobile app's "متابعة الطاقة والأحمال" tab can read the same
event the user just received on Telegram.

Hard guarantees
---------------
* No external traffic — this module never calls Telegram/SMS providers.
* Never blocks Telegram/SMS sending. The mirror call is wrapped in a
  try/except + ``db.session.rollback()`` and any error is swallowed
  after a diagnostic log line.
* Relies on the upstream dispatch dedup. Both call sites invoke this
  helper exactly once per logical event (after the dedup gate passes
  and after the channel loop is finished), so there is **no extra
  per-channel duplication** in the mobile Notification Center.
* No new schema. Reuses the existing ``NotificationEvent`` table.

Classification
--------------
Mobile filters its energy tab by ``source_type == 'energy'``.
``event_type`` is the fine-grained category the mobile client maps
into a label and an icon. The values used here come from the task
brief's recommended whitelist (``battery_status``, ``load_alert``,
``solar_surplus``, ``weather_alert``, ``daily_report``, etc.).
"""

from __future__ import annotations

import logging
from typing import Optional

from ...extensions import db
from ...models import AppUser, NotificationEvent

log = logging.getLogger(__name__)

#: Every mirrored row is tagged with this ``source_type`` so the mobile
#: client can filter the energy/loads tab without a complex WHERE
#: clause. Do not change without coordinating with the mobile classifier.
ENERGY_SOURCE_TYPE = 'energy'

#: Fallback ``event_type`` when the dispatch site doesn't carry enough
#: structure to classify. Mobile renders this as a generic energy entry.
DEFAULT_EVENT_TYPE = 'energy_status_change'

# ── Classification helpers ────────────────────────────────────────────

#: Maps the rule ``prefix`` used by ``_send_scheduled_notification``
#: (one per scheduled notification kind) onto a stable mobile-side
#: ``event_type``. Keys are exactly the strings the scheduler passes
#: in today.
_SCHEDULED_PREFIX_TO_EVENT_TYPE = {
    'periodic_day':  'periodic_day',
    'periodic_night': 'periodic_night',
    'pre_sunset':    'pre_sunset',
    'load_alert':    'load_alert',
    'battery_test':  'battery_warning',
    'daily_report':  'daily_report',
}


def event_type_for_scheduled(prefix: str) -> str:
    """Resolve an ``event_type`` for a scheduled notification prefix."""
    return _SCHEDULED_PREFIX_TO_EVENT_TYPE.get(
        (prefix or '').strip(), DEFAULT_EVENT_TYPE,
    )


def event_type_for_dispatch_key(event_key: str) -> str:
    """Classify a ``dispatch_notification`` event_key into an
    ``event_type`` the mobile client knows how to render.

    The function only inspects the key prefix — it never reaches into
    the database or recomputes any decision.
    """
    raw = (event_key or '').lower()
    # Strip the optional "::devN" device-aware suffix added by
    # ``_build_device_dedup_key`` so the classifier matches both forms.
    base = raw.split('::', 1)[0]

    if base.startswith('charge-'):
        return 'battery_status'
    if base.startswith('discharge-'):
        return 'night_discharge'
    if base.startswith('day-deficit'):
        return 'solar_status'
    if base.startswith('night-load'):
        return 'load_alert'
    if base.startswith('weather-'):
        return 'weather_alert'
    if base.startswith('periodic-status'):
        # ``dispatch_notification``'s live periodic-status update is
        # neither strictly day nor night — map it to the recommended
        # whitelist's catch-all so every value the helper emits is on
        # the mobile classifier's known list.
        return 'energy_status_change'
    if base.startswith('pre-sunset'):
        return 'pre_sunset'
    if base.startswith('morning-report'):
        return 'daily_report'
    if base.startswith('inv-temp-high'):
        return 'inverter_status'
    if base.startswith('bms-temp-high'):
        return 'battery_warning'
    if base.startswith('pv-high'):
        return 'solar_status'
    return DEFAULT_EVENT_TYPE


# ── Severity helper ───────────────────────────────────────────────────
#
# ``NotificationEvent`` does not have a dedicated ``severity`` column —
# the table predates that need. We carry severity in the ``status``
# column which the mobile classifier already reads. ``status`` is
# normally one of {new, read, archived} so we only override it for
# stronger levels and keep the default for routine info.

def _status_for_level(level: Optional[str]) -> str:
    norm = (level or '').strip().lower()
    if norm in ('danger', 'critical', 'error'):
        return 'critical'
    if norm in ('warning', 'warn'):
        return 'warning'
    return 'new'


# ── The actual mirror ─────────────────────────────────────────────────


def mirror_energy_notification_to_center(
    *,
    event_type: str,
    title: str,
    message: str,
    user_id: Optional[int] = None,
    device_id: Optional[int] = None,
    level: Optional[str] = None,
    source_type: str = ENERGY_SOURCE_TYPE,
) -> bool:
    """Persist one ``NotificationEvent`` row mirroring an already-sent
    energy/load/solar/weather notification.

    Returns ``True`` when a row was committed, ``False`` when the
    mirror was skipped or the write failed. **This function never
    raises** — failures are logged and swallowed so that Telegram/SMS
    dispatch in the caller is never affected.

    Skipped (returns ``False``) when:
      * ``user_id`` is missing — the Notification Center is per-user;
        we cannot honestly attribute a row without an owner.
      * ``title`` AND ``message`` are both empty — nothing to render.
    """
    if not user_id:
        # Admin/global scope (no per-user context). The mobile app is
        # per-user; mirroring without an owner would create an
        # orphaned, invisible row. Skip honestly.
        return False

    safe_title = (title or '').strip()
    safe_message = (message or '').strip()
    if not safe_title and not safe_message:
        return False

    safe_event_type = (event_type or DEFAULT_EVENT_TYPE).strip()[:40]
    safe_source_type = (source_type or ENERGY_SOURCE_TYPE).strip()[:40]

    # Tenant lookup is best-effort. If the user has no tenant (legacy
    # single-tenant install) we still mirror — ``tenant_id`` is nullable.
    tenant_id = None
    try:
        owner = AppUser.query.filter_by(id=int(user_id)).first()
        if owner is not None:
            tenant_id = getattr(owner, 'tenant_id', None)
    except Exception:  # pragma: no cover - defensive
        tenant_id = None

    try:
        row = NotificationEvent(
            event_type=safe_event_type,
            target_user_id=int(user_id),
            tenant_id=tenant_id,
            source_type=safe_source_type,
            source_id=int(device_id) if device_id else None,
            title=safe_title[:220],
            message=safe_message,
            status=_status_for_level(level),
            is_read=False,
            appeared_in_bell=False,
            delivered_to_user=False,
        )
        db.session.add(row)
        db.session.commit()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        # Telegram/SMS sending must never be affected by a DB hiccup.
        # Roll back and log; the caller continues normally.
        try:
            db.session.rollback()
        except Exception:
            pass
        log.warning(
            'mirror_energy_notification_to_center: DB write failed '
            '(event_type=%s user_id=%s device_id=%s): %s',
            safe_event_type, user_id, device_id, exc,
        )
        return False


__all__ = [
    'ENERGY_SOURCE_TYPE',
    'DEFAULT_EVENT_TYPE',
    'event_type_for_scheduled',
    'event_type_for_dispatch_key',
    'mirror_energy_notification_to_center',
]
