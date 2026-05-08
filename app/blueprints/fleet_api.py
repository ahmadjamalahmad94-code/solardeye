"""v33-β — Fleet API.

Lightweight JSON endpoints that power the Live Device Rail / Fleet
Switcher on /dashboard and /live-data. Every endpoint:

  * Requires a logged-in subscriber session (`session['logged_in']`).
  * Filters by ``owner_user_id == session.user_id`` so cross-user data
    leaks are impossible.
  * Skips when the request is in admin scope (admins do not use the
    subscriber rail).
  * Returns small JSON payloads suitable for 30-second polling.

Endpoints
---------
POST  /api/fleet/select                          ← session flip
GET   /api/fleet/summary                         ← rail data
GET   /api/devices/<int:device_id>/live-summary  ← single-device snapshot
GET   /api/fleet/overview                        ← aggregate combined + per-device
GET   /api/devices/<int:device_id>/notifications-preview ← chip alert badge

Caching: per-user 10s in-memory LRU on the read endpoints. The select
endpoint never caches (it is a mutation).

NOTHING about the existing ``energy.api_live`` endpoint is changed; this
blueprint runs alongside it. The Flow Graph is touched only via the
existing ``data-bind`` mechanism on the page side; this server module
does not know about the SVG.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from ..extensions import db
from ..models import AppDevice, AppUser, NotificationLog, Reading
from ..services.scope import is_admin_scope, scoped_query


fleet_api_bp = Blueprint('fleet_api', __name__)


# ────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested in tests/test_v33_beta.py)
# ────────────────────────────────────────────────────────────────────────

# Status thresholds in seconds since the device's last reading.
_STATUS_ONLINE_S = 5 * 60        # ≤5 min      → online (green)
_STATUS_STALE_S  = 30 * 60       # ≤30 min     → stale  (amber)
                                 # >30 min      → offline (red)
                                 # None last_seen → offline


def _status_from_age(age_seconds: int | float | None) -> str:
    """Classify a device's freshness into a stable status string."""
    if age_seconds is None:
        return 'offline'
    if age_seconds <= _STATUS_ONLINE_S:
        return 'online'
    if age_seconds <= _STATUS_STALE_S:
        return 'stale'
    return 'offline'


def _device_icon(name: str | None) -> str:
    """Pick a keyword-derived emoji for a device. Mirrors the v32
    `_device_switcher.html` logic so chips look the same."""
    n = (name or '').lower()
    if 'farm' in n or 'مزرعة' in n:
        return '🌾'
    if 'workshop' in n or 'ورشة' in n:
        return '🏭'
    if 'shop' in n or 'محل' in n:
        return '🏪'
    if 'office' in n or 'مكتب' in n:
        return '🏢'
    if 'roof' in n or 'سطح' in n:
        return '🏘️'
    return '🏠'


def _build_aggregate_overview(devices: list, readings_by_device: dict) -> dict:
    """Return the aggregate overview payload.

    * Solar / home / grid / daily_production_kwh / inverter_power are SUMS.
    * Battery SOC is NEVER averaged — only present in the per-device
      breakdown rows.
    """
    combined = {
        'solar_power': 0.0,
        'home_load':   0.0,
        'grid_power':  0.0,
        'inverter_power': 0.0,
        'daily_production_kwh': 0.0,
        'battery_charge_w':   0.0,
        'battery_discharge_w': 0.0,
    }
    per_device = []
    for d in devices:
        r = readings_by_device.get(d.id)
        if r is None:
            per_device.append({
                'id': d.id,
                'name': d.name or '',
                'icon': _device_icon(d.name),
                'has_reading': False,
                'battery_soc': None,
                'solar_power': 0.0,
                'home_load': 0.0,
                'grid_power': 0.0,
                'last_update_iso': None,
                'status': 'offline',
            })
            continue
        s_w = float(getattr(r, 'solar_power', 0) or 0)
        h_w = float(getattr(r, 'home_load',  0) or 0)
        g_w = float(getattr(r, 'grid_power', 0) or 0)
        i_w = float(getattr(r, 'inverter_power', 0) or 0)
        soc = getattr(r, 'battery_soc', None)
        bp  = float(getattr(r, 'battery_power', 0) or 0)
        combined['solar_power']    += s_w
        combined['home_load']      += h_w
        combined['grid_power']     += g_w
        combined['inverter_power'] += i_w
        combined['daily_production_kwh'] += float(getattr(r, 'daily_production', 0) or 0)
        if bp > 0:
            combined['battery_charge_w'] += bp
        elif bp < 0:
            combined['battery_discharge_w'] += abs(bp)
        last_iso = None
        last_seen_age = None
        if getattr(r, 'created_at', None):
            try:
                last_iso = r.created_at.isoformat()
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                created = r.created_at.replace(tzinfo=None) if r.created_at.tzinfo else r.created_at
                last_seen_age = (now - created).total_seconds()
            except Exception:
                pass
        per_device.append({
            'id': d.id,
            'name': d.name or '',
            'icon': _device_icon(d.name),
            'has_reading': True,
            'battery_soc': int(soc) if soc is not None else None,
            'solar_power': s_w,
            'home_load': h_w,
            'grid_power': g_w,
            'last_update_iso': last_iso,
            'status': _status_from_age(last_seen_age),
        })
    return {'combined': combined, 'per_device': per_device}


# ────────────────────────────────────────────────────────────────────────
# Cache (per-user, 10s TTL, in-memory)
# ────────────────────────────────────────────────────────────────────────

_cache: dict[tuple, tuple[float, Any]] = {}
_CACHE_TTL_S = 10.0


def _cache_get(key: tuple):
    entry = _cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.monotonic() - ts > _CACHE_TTL_S:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: tuple, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


def _cache_invalidate_user(user_id: int) -> None:
    """Drop all cache entries for one user (called on /api/fleet/select)."""
    for k in list(_cache.keys()):
        if isinstance(k, tuple) and k and k[0] == user_id:
            _cache.pop(k, None)


# ────────────────────────────────────────────────────────────────────────
# Auth helpers
# ────────────────────────────────────────────────────────────────────────

def _current_subscriber_user() -> AppUser | None:
    """Return the AppUser for the logged-in subscriber, or None.

    Returns None for: not-logged-in, admin scope, missing user. The
    caller responds with 401 in those cases.
    """
    if not session.get('logged_in'):
        return None
    if is_admin_scope():
        return None
    uid = session.get('user_id')
    if not uid:
        return None
    user = AppUser.query.filter_by(id=uid).first()
    return user


def _api_unauthorized():
    return jsonify({'ok': False, 'error': 'unauthorized'}), 401


def _api_forbidden(reason: str = 'forbidden'):
    return jsonify({'ok': False, 'error': reason}), 403


def _api_not_found(reason: str = 'not_found'):
    return jsonify({'ok': False, 'error': reason}), 404


# ────────────────────────────────────────────────────────────────────────
# Endpoint: POST /api/fleet/select
# ────────────────────────────────────────────────────────────────────────

@fleet_api_bp.route('/api/fleet/select', methods=['POST'])
def fleet_select():
    user = _current_subscriber_user()
    if user is None:
        return _api_unauthorized()
    payload = request.get_json(silent=True) or {}
    raw = payload.get('device_id')
    if raw == '__all__':
        session['current_device_id'] = '__all__'
        _cache_invalidate_user(user.id)
        return jsonify({'ok': True, 'device_id': None, 'aggregate': True})
    try:
        did = int(raw)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_device_id'}), 400
    owned = AppDevice.query.filter_by(id=did, owner_user_id=user.id).first()
    if owned is None:
        return _api_forbidden('device_not_owned')
    session['current_device_id'] = did
    if user.preferred_device_id != did:
        try:
            user.preferred_device_id = did
            db.session.commit()
        except Exception:
            db.session.rollback()
    _cache_invalidate_user(user.id)
    return jsonify({'ok': True, 'device_id': did, 'aggregate': False})


# ────────────────────────────────────────────────────────────────────────
# Endpoint: GET /api/fleet/summary
# ────────────────────────────────────────────────────────────────────────

@fleet_api_bp.route('/api/fleet/summary', methods=['GET'])
def fleet_summary():
    """Per-device tiny summary for the Live Device Rail."""
    user = _current_subscriber_user()
    if user is None:
        return _api_unauthorized()

    cache_key = (user.id, 'fleet_summary')
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    devices = (AppDevice.query
               .filter_by(owner_user_id=user.id, is_active=True)
               .order_by(AppDevice.id.asc())
               .all())
    items = []
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    raw_session = session.get('current_device_id')
    aggregate_mode = (raw_session == '__all__')
    current_did = None
    if not aggregate_mode and raw_session:
        try:
            current_did = int(raw_session)
        except (TypeError, ValueError):
            current_did = None
    if current_did is None and not aggregate_mode and user.preferred_device_id:
        current_did = user.preferred_device_id
    if current_did is None and not aggregate_mode and devices:
        current_did = devices[0].id

    for d in devices:
        latest = (Reading.query
                  .filter_by(user_id=user.id, device_id=d.id)
                  .order_by(Reading.created_at.desc())
                  .first())
        last_iso = None
        last_seen_age = None
        soc = None
        solar_w = 0.0
        if latest:
            soc = int(latest.battery_soc) if latest.battery_soc is not None else None
            solar_w = float(latest.solar_power or 0)
            if latest.created_at:
                try:
                    last_iso = latest.created_at.isoformat()
                    created = latest.created_at.replace(tzinfo=None) if latest.created_at.tzinfo else latest.created_at
                    last_seen_age = (now_naive - created).total_seconds()
                except Exception:
                    pass
        # Lightweight unread alert count for badge
        try:
            alerts = (NotificationLog.query
                      .filter_by(user_id=user.id, device_id=d.id, level='warning')
                      .count())
        except Exception:
            alerts = 0
        items.append({
            'id': d.id,
            'name': d.name or '',
            'icon': _device_icon(d.name),
            'provider': d.api_provider or '',
            'is_active': bool(d.is_active),
            'is_current': bool(current_did == d.id and not aggregate_mode),
            'battery_soc': soc,
            'solar_power_w': solar_w,
            'last_update_iso': last_iso,
            'status': _status_from_age(last_seen_age),
            'alerts_count': int(alerts or 0),
        })
    payload = {
        'ok': True,
        'aggregate_mode': aggregate_mode,
        'current_device_id': current_did if not aggregate_mode else None,
        'devices': items,
        'devices_count': len(items),
    }
    _cache_set(cache_key, payload)
    return jsonify(payload)


# ────────────────────────────────────────────────────────────────────────
# Endpoint: GET /api/devices/<id>/live-summary
# ────────────────────────────────────────────────────────────────────────

@fleet_api_bp.route('/api/devices/<int:device_id>/live-summary', methods=['GET'])
def device_live_summary(device_id: int):
    """Single-device live snapshot — the payload shape is intentionally
    simple so the JS controller can drop values into existing data-bind
    slots without restructuring any DOM."""
    user = _current_subscriber_user()
    if user is None:
        return _api_unauthorized()
    owned = AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()
    if owned is None:
        return _api_forbidden('device_not_owned')
    latest = (Reading.query
              .filter_by(user_id=user.id, device_id=device_id)
              .order_by(Reading.created_at.desc())
              .first())
    if latest is None:
        return jsonify({
            'ok': True, 'device_id': device_id, 'has_reading': False,
            'device': {'id': owned.id, 'name': owned.name, 'icon': _device_icon(owned.name),
                       'timezone': owned.timezone, 'provider': owned.api_provider},
        })
    last_iso = None
    last_seen_age = None
    if latest.created_at:
        try:
            last_iso = latest.created_at.isoformat()
            now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
            created = latest.created_at.replace(tzinfo=None) if latest.created_at.tzinfo else latest.created_at
            last_seen_age = (now_naive - created).total_seconds()
        except Exception:
            pass
    payload = {
        'ok': True,
        'device_id': device_id,
        'has_reading': True,
        'device': {
            'id': owned.id, 'name': owned.name, 'icon': _device_icon(owned.name),
            'timezone': owned.timezone, 'provider': owned.api_provider,
            'is_active': bool(owned.is_active),
        },
        'reading': {
            'solar_power': float(latest.solar_power or 0),
            'home_load':   float(latest.home_load or 0),
            'grid_power':  float(latest.grid_power or 0),
            'battery_soc': int(latest.battery_soc) if latest.battery_soc is not None else None,
            'battery_power': float(latest.battery_power or 0),
            'inverter_power': float(latest.inverter_power or 0),
            'daily_production_kwh': float(latest.daily_production or 0),
            'monthly_production_kwh': float(latest.monthly_production or 0),
            'total_production_kwh': float(latest.total_production or 0),
            'status_text': latest.status_text or '',
            'created_at_iso': last_iso,
            'age_seconds': last_seen_age,
            'status': _status_from_age(last_seen_age),
        },
    }
    return jsonify(payload)


# ────────────────────────────────────────────────────────────────────────
# Endpoint: GET /api/fleet/overview (aggregate)
# ────────────────────────────────────────────────────────────────────────

@fleet_api_bp.route('/api/fleet/overview', methods=['GET'])
def fleet_overview():
    """Aggregate-mode payload: combined sums + per-device breakdown.
    Battery SOC is NEVER averaged — present per-device only."""
    user = _current_subscriber_user()
    if user is None:
        return _api_unauthorized()
    cache_key = (user.id, 'fleet_overview')
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)
    devices = (AppDevice.query
               .filter_by(owner_user_id=user.id, is_active=True)
               .order_by(AppDevice.id.asc())
               .all())
    readings_by_device: dict[int, Any] = {}
    for d in devices:
        latest = (Reading.query
                  .filter_by(user_id=user.id, device_id=d.id)
                  .order_by(Reading.created_at.desc())
                  .first())
        if latest is not None:
            readings_by_device[d.id] = latest
    overview = _build_aggregate_overview(devices, readings_by_device)
    payload = {
        'ok': True,
        'aggregate_mode': True,
        'devices_count': len(devices),
        **overview,
    }
    _cache_set(cache_key, payload)
    return jsonify(payload)


# ────────────────────────────────────────────────────────────────────────
# Endpoint: GET /api/devices/<id>/notifications-preview
# ────────────────────────────────────────────────────────────────────────

@fleet_api_bp.route('/api/devices/<int:device_id>/notifications-preview', methods=['GET'])
def device_notifications_preview(device_id: int):
    """5 most-recent NotificationLog rows for one device. Powers the
    chip's alert badge dropdown peek."""
    user = _current_subscriber_user()
    if user is None:
        return _api_unauthorized()
    owned = AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()
    if owned is None:
        return _api_forbidden('device_not_owned')
    rows = (NotificationLog.query
            .filter_by(user_id=user.id, device_id=device_id)
            .order_by(NotificationLog.created_at.desc())
            .limit(5)
            .all())
    items = []
    for r in rows:
        ts = None
        if r.created_at:
            try:
                ts = r.created_at.isoformat()
            except Exception:
                pass
        items.append({
            'event_key': r.event_key or '',
            'title': r.title or '',
            'level': r.level or 'info',
            'channel': r.channel or '',
            'created_at_iso': ts,
        })
    return jsonify({'ok': True, 'device_id': device_id, 'count': len(items), 'items': items})
