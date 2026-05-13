from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, current_app, request

from ..models import AppDevice, Reading
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.security import sanitize_response_payload, mask_identifier
from .helpers import (
    build_period_chart,
    build_pre_sunset_prediction,
    compute_energy_stats,
    filter_rows_for_view,
    load_settings,
    parse_selected_date,
)
from .smart_engine import build_smart_energy_advice
# v62: weather endpoint reuses the existing web-side pipeline verbatim.
# `fetch_weather` is the Open-Meteo client in
# `services/weather_service.py` — light, safe to import eagerly.
# `extract_station_coords` lives in `main.py`, whose module-level
# imports pull in heavy report-rendering deps (reportlab) that
# don't belong in the mobile-endpoint critical path. We expose a
# thin wrapper that lazy-imports the real helper at call time;
# tests patch the wrapper to avoid touching `main.py` entirely.
from ..services.weather_service import fetch_weather


def _extract_station_coords(latest):
    """Lazy proxy for `main.extract_station_coords`. Keeps the
    mobile-endpoint module free of `main.py`'s eager imports so
    the test suite never has to install report-rendering deps to
    exercise this route. Behaviour matches the wrapped helper
    exactly: returns `(lat, lng)` on success, `(None, None)` on
    missing reading / missing `station_summary.locationLat|Lng` /
    JSON parse failure."""
    from .main import extract_station_coords as _impl
    return _impl(latest)

mobile_devices_api_bp = Blueprint('mobile_devices_api', __name__, url_prefix='/api/v1/devices')

# v56: views accepted by `GET /<id>/statistics`. The wider web surface
# (`/statistics`, `/reports`) also supports `week`, but phase-1 mobile
# only renders `day` and `month` — week support would require a new
# Arabic label + range chip on the mobile side and is intentionally
# deferred until the mobile screen lands.
_MOBILE_STATS_VIEWS = frozenset({'day', 'month'})


def _require_user():
    user = user_from_bearer_or_session()
    if not user:
        return None, api_error('Authentication required.', code='auth_required', status=401)
    return user, None


def _device_query_for(user):
    q = AppDevice.query.order_by(AppDevice.updated_at.desc(), AppDevice.id.desc())
    if not getattr(user, 'is_admin', False):
        q = q.filter_by(owner_user_id=user.id)
    return q


def _device_allowed(user, device_id: int):
    q = AppDevice.query.filter_by(id=device_id)
    if not getattr(user, 'is_admin', False):
        q = q.filter_by(owner_user_id=user.id)
    return q.first()


def _device_payload(dev, *, include_private: bool = False):
    if not dev:
        return None
    data = {
        'id': dev.id,
        'name': dev.name,
        'device_type': dev.device_type,
        'api_provider': dev.api_provider,
        'connection_status': dev.connection_status,
        'last_connected_at': dev.last_connected_at.isoformat() if dev.last_connected_at else None,
        'is_active': bool(dev.is_active),
        'plant_name': dev.plant_name,
        'timezone': dev.timezone,
        'identifiers': {
            'external_device_id': dev.external_device_id if include_private else mask_identifier(dev.external_device_id),
            'device_uid': dev.device_uid if include_private else mask_identifier(dev.device_uid),
            'station_id': dev.station_id if include_private else mask_identifier(dev.station_id),
        },
    }
    return sanitize_response_payload(data)


def _reading_payload(row):
    if not row:
        return None
    return sanitize_response_payload({
        'id': row.id,
        'device_id': row.device_id,
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'solar_power': row.solar_power,
        'home_load': row.home_load,
        'battery_soc': row.battery_soc,
        'battery_power': row.battery_power,
        'grid_power': row.grid_power,
        'inverter_power': row.inverter_power,
        'daily_production': row.daily_production,
        'monthly_production': row.monthly_production,
        'total_production': row.total_production,
        'status_text': row.status_text,
        'pv1_power': row.pv1_power,
        'pv2_power': row.pv2_power,
        'pv3_power': row.pv3_power,
        'pv4_power': row.pv4_power,
        'inverter_temp': row.inverter_temp,
        'dc_temp': row.dc_temp,
        'grid_voltage': row.grid_voltage,
        'grid_frequency': row.grid_frequency,
    })


@mobile_devices_api_bp.get('')
@mobile_devices_api_bp.get('/')
def devices_list():
    user, err = _require_user()
    if err:
        return err
    page, page_size = pagination_args(default_size=30, max_size=100)
    q = _device_query_for(user)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return api_ok({'items': [_device_payload(row) for row in rows]}, meta=page_meta(page, page_size, total))


@mobile_devices_api_bp.get('/<int:device_id>')
def device_detail(device_id: int):
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)
    latest = Reading.query.filter_by(device_id=dev.id).order_by(Reading.created_at.desc(), Reading.id.desc()).first()
    return api_ok({'device': _device_payload(dev), 'latest': _reading_payload(latest)})


@mobile_devices_api_bp.get('/<int:device_id>/latest')
def device_latest(device_id: int):
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)
    latest = Reading.query.filter_by(device_id=dev.id).order_by(Reading.created_at.desc(), Reading.id.desc()).first()
    return api_ok(_reading_payload(latest) or {})


@mobile_devices_api_bp.get('/<int:device_id>/history')
def device_history(device_id: int):
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)
    page, page_size = pagination_args(default_size=100, max_size=500)
    q = Reading.query.filter_by(device_id=dev.id).order_by(Reading.created_at.desc(), Reading.id.desc())
    date_from = request.args.get('from') or request.args.get('date_from')
    date_to = request.args.get('to') or request.args.get('date_to')
    try:
        if date_from:
            q = q.filter(Reading.created_at >= datetime.fromisoformat(date_from.replace('Z','+00:00')).replace(tzinfo=None))
        if date_to:
            q = q.filter(Reading.created_at <= datetime.fromisoformat(date_to.replace('Z','+00:00')).replace(tzinfo=None))
    except Exception:
        return api_error('Invalid date range. Use ISO-8601 dates.', code='invalid_date_range', status=400)
    # Safe default: last 7 days if no range was passed.
    if not date_from and not date_to:
        q = q.filter(Reading.created_at >= datetime.utcnow() - timedelta(days=7))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return api_ok({'items': [_reading_payload(row) for row in rows]}, meta=page_meta(page, page_size, total))


# v56: ── Statistics helpers ─────────────────────────────────────────
#
# Pulled out as small pure functions so the contract is unit-testable
# without a Flask app / database context — the route handler stays a
# thin wrapper that wires request parsing + the DB query + these
# helpers together.

def _validate_statistics_view(raw):
    """Returns the normalised view string or `None` when invalid.

    v56 mobile only ships `day` and `month`. The wider web surface
    also supports `week`, but exposing it here without a mobile
    consumer would create a contract mobile must honour later — keep
    it tight.

    A missing / blank / whitespace-only value falls back to `day`
    (the default the mobile screen also opens with) — this is NOT
    an invalid input.
    """
    view = (raw or '').strip().lower()
    if not view:
        return 'day'
    return view if view in _MOBILE_STATS_VIEWS else None


def _validate_statistics_date(raw):
    """Returns `True` when the raw date is missing OR matches
    `YYYY-MM-DD`. Empty falls back to "today" inside
    `parse_selected_date`, so it counts as valid here."""
    s = (raw or '').strip()
    if not s:
        return True
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def _mobile_statistics_payload(view, selected_date, title_hint, stats, chart, generated_at):
    """Map the web-side stats/chart dicts onto the mobile contract.

    The web `compute_energy_stats` returns canonical "solar_generated"
    / "home_consumed" / "solar_to_battery" / "grid_to_home" energy
    totals. The mobile contract uses the more user-facing labels:
    `production_kwh`, `consumption_kwh`, `battery_in_kwh`,
    `grid_in_kwh` — only the *naming* changes here, never the values.

    The chart dict from `build_period_chart` is honest about its own
    units:
      * `day`   → averages of W per hour bucket.
      * `month` → kWh sums per day bucket (already from
                  `compute_energy_stats`).
    The mobile contract is "kWh per bucket" regardless of view, so
    day-view W are converted to kWh-per-hour here (avg_W × 1h / 1000).
    """
    if view == 'day':
        production_buckets = [round((v or 0.0) / 1000.0, 2) for v in chart.get('solar', [])]
        consumption_buckets = [round((v or 0.0) / 1000.0, 2) for v in chart.get('home', [])]
        anchor = selected_date.strftime('%Y-%m-%d')
    else:  # 'month'
        production_buckets = [round(v or 0.0, 2) for v in chart.get('solar', [])]
        consumption_buckets = [round(v or 0.0, 2) for v in chart.get('home', [])]
        anchor = selected_date.strftime('%Y-%m')

    return {
        'view': view,
        'anchor': anchor,
        'title_hint': title_hint,
        'totals': {
            'production_kwh': stats.get('solar_generated_kwh', 0.0),
            'consumption_kwh': stats.get('home_consumed_kwh', 0.0),
            'battery_in_kwh': stats.get('solar_to_battery_kwh', 0.0),
            'grid_in_kwh': stats.get('grid_to_home_kwh', 0.0),
            'avg_battery_soc': stats.get('avg_battery_soc', 0.0),
            'max_solar_w': stats.get('max_solar_w', 0.0),
            'samples': stats.get('samples', 0),
            'data_gaps': stats.get('data_gaps', 0),
        },
        'buckets': {
            'labels': list(chart.get('labels', [])),
            'production_kwh': production_buckets,
            'consumption_kwh': consumption_buckets,
        },
        'empty': stats.get('samples', 0) == 0,
        'generated_at': generated_at,
    }


@mobile_devices_api_bp.get('/<int:device_id>/statistics')
def device_statistics(device_id: int):
    """v56 — subscriber-scoped historical statistics for one device.

    Owner-scoped via `_device_allowed`, identical to the v52
    `/history` + `/alerts` endpoints. The handler reuses the existing
    web-side energy helpers (`parse_selected_date`,
    `filter_rows_for_view`, `compute_energy_stats`,
    `build_period_chart`) verbatim — the energy integration math is
    NOT forked.

    Query parameters:
      * `view=day|month` — defaults to `day`; returns
        `invalid_view` (400) when the value is anything else.
      * `date=YYYY-MM-DD` — anchor inside the selected period;
        defaults to "today" in the device's timezone.  Returns
        `invalid_date` (400) when the format is wrong.
    """
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)

    view = _validate_statistics_view(request.args.get('view'))
    if view is None:
        return api_error(
            'Statistics view must be one of: day, month.',
            code='invalid_view',
            status=400,
            field='view',
        )

    raw_date = request.args.get('date')
    if not _validate_statistics_date(raw_date):
        return api_error(
            'Statistics date must be in YYYY-MM-DD format.',
            code='invalid_date',
            status=400,
            field='date',
        )

    # Device timezone wins over the app-level fallback so the day /
    # month buckets line up with what the user actually experienced.
    tz_name = (dev.timezone or current_app.config.get('LOCAL_TIMEZONE') or 'UTC')
    selected_date = parse_selected_date(raw_date or None, tz_name)

    # Compute the window bounds in the same convention used by the
    # existing web `_get_stats_context` helper: local-time start/end,
    # tzinfo stripped before the DB filter (Reading.created_at is a
    # naive `DateTime` column populated in local time).
    if view == 'day':
        start = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    else:  # 'month'
        start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    end_naive = end.replace(tzinfo=None) if end.tzinfo else end

    max_rows = current_app.config.get('MAX_READINGS_QUERY', 2000)
    ordered = (
        Reading.query
        .filter_by(device_id=dev.id)
        .filter(Reading.created_at >= start_naive, Reading.created_at < end_naive)
        .order_by(Reading.created_at.asc())
        .limit(max_rows)
        .all()
    )

    filtered_rows, title_hint = filter_rows_for_view(ordered, view, selected_date, tz_name)
    stats = compute_energy_stats(filtered_rows)
    chart = build_period_chart(filtered_rows, tz_name, view)

    payload = _mobile_statistics_payload(
        view=view,
        selected_date=selected_date,
        title_hint=title_hint,
        stats=stats,
        chart=chart,
        generated_at=datetime.utcnow().isoformat(),
    )
    return api_ok(payload)


# v59: ── Reports summary helpers ──────────────────────────────────────
#
# Mirrors the derivations the web `/reports` route runs today (see
# `web/app/blueprints/energy.py::reports`). The math here is a pure
# function of the canonical `compute_energy_stats(rows)` output — no
# new energy integration is performed; the helper just expresses the
# same web-side derivations in a mobile-friendly shape.
#
# Phase-1 scope (matches v59 brief):
#   * production_kwh / consumption_kwh / battery_in_kwh / grid_in_kwh
#     — already in the canonical stats dict, renamed for the mobile
#     contract.
#   * solar_share / battery_share / grid_share / self_sufficiency
#     — identical formulas to `energy.py::reports`.
#   * average_load_w — identical formula to `energy.py::reports`.
#   * solar_surplus_kwh — identical formula to `energy.py::reports`.
#
# Deliberately NOT in phase-1: smart-load suggestions (depend on
# `_smart_load_suggestions(latest)` which is web-session coupled),
# the CSV/PDF export paths, and the per-bucket chart series (already
# served by the v56 `/statistics` endpoint — clients wanting the
# chart side hit that one).

def _mobile_reports_summary_payload(view, selected_date, title_hint, stats, generated_at):
    """Build the mobile reports-summary payload.

    `stats` is the canonical `compute_energy_stats(rows)` dict. The
    `view` is `day` or `month`; the anchor format follows the same
    convention as the v56 `/statistics` endpoint (`YYYY-MM-DD` for
    day, `YYYY-MM` for month).

    When `stats.samples == 0` the helper zeroes every derived metric
    and sets `empty=true` — this avoids the misleading "100% self-
    sufficiency" the raw formulas would produce on empty days (the
    web page renders an empty-state instead and never surfaces those
    derived values).
    """
    samples = int(stats.get('samples', 0) or 0)

    if samples == 0:
        summary = {
            'production_kwh': 0.0,
            'consumption_kwh': 0.0,
            'battery_in_kwh': 0.0,
            'grid_in_kwh': 0.0,
            'solar_share_percent': 0.0,
            'battery_share_percent': 0.0,
            'grid_share_percent': 0.0,
            'self_sufficiency_percent': 0.0,
            'average_load_w': 0.0,
            'solar_surplus_kwh': 0.0,
        }
        empty = True
    else:
        solar_generated = float(stats.get('solar_generated_kwh', 0.0) or 0.0)
        home_consumed = float(stats.get('home_consumed_kwh', 0.0) or 0.0)
        solar_to_home = float(stats.get('solar_to_home_kwh', 0.0) or 0.0)
        solar_to_battery = float(stats.get('solar_to_battery_kwh', 0.0) or 0.0)
        battery_to_home = float(stats.get('battery_to_home_kwh', 0.0) or 0.0)
        grid_to_home = float(stats.get('grid_to_home_kwh', 0.0) or 0.0)

        # Identical formula to `energy.py::reports`: shares are taken
        # against what actually fed the home, with a 0.01 floor so an
        # all-zero period never divides by zero.
        total_supplied = max(solar_to_home + battery_to_home + grid_to_home, 0.01)
        solar_share = round(min((solar_to_home / total_supplied) * 100.0, 100.0), 1)
        battery_share = round(min((battery_to_home / total_supplied) * 100.0, 100.0), 1)
        grid_share = round(min((grid_to_home / total_supplied) * 100.0, 100.0), 1)
        self_sufficiency = round(max(0.0, 100.0 - grid_share), 1)

        # Identical formula to `energy.py::reports`:
        #   avg_load = (home_consumed_kwh / max(samples, 1)) * 1000
        average_load_w = round((home_consumed / max(samples, 1)) * 1000.0, 1)

        # Identical formula to `energy.py::reports`:
        #   solar_surplus = max(solar_generated - solar_to_home, 0)
        solar_surplus = round(max(solar_generated - solar_to_home, 0.0), 2)

        summary = {
            'production_kwh': solar_generated,
            'consumption_kwh': home_consumed,
            # battery_in_kwh mirrors the v56 statistics endpoint naming
            # (energy *into* the battery from solar), not the inverse
            # battery_to_home flow.
            'battery_in_kwh': solar_to_battery,
            'grid_in_kwh': grid_to_home,
            'solar_share_percent': solar_share,
            'battery_share_percent': battery_share,
            'grid_share_percent': grid_share,
            'self_sufficiency_percent': self_sufficiency,
            'average_load_w': average_load_w,
            'solar_surplus_kwh': solar_surplus,
        }
        empty = False

    if view == 'day':
        anchor = selected_date.strftime('%Y-%m-%d')
    else:  # 'month'
        anchor = selected_date.strftime('%Y-%m')

    return {
        'view': view,
        'anchor': anchor,
        'title_hint': title_hint,
        'summary': summary,
        'empty': empty,
        'generated_at': generated_at,
    }


@mobile_devices_api_bp.get('/<int:device_id>/reports/summary')
def device_reports_summary(device_id: int):
    """v59 — subscriber-scoped reports summary for one device.

    Owner-scoped via `_device_allowed`, same pattern as the v52
    `/history` + `/alerts` and v56 `/statistics` endpoints. Reuses
    the existing energy helpers (`parse_selected_date`,
    `filter_rows_for_view`, `compute_energy_stats`) and the same
    view/date validators as v56 so the two surfaces accept identical
    `view=day|month&date=YYYY-MM-DD` inputs — the mobile client can
    drive both with one selector.

    No new energy integration is added. PDF / CSV export remains
    web-only and is intentionally out of scope.
    """
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)

    view = _validate_statistics_view(request.args.get('view'))
    if view is None:
        return api_error(
            'Reports view must be one of: day, month.',
            code='invalid_view',
            status=400,
            field='view',
        )

    raw_date = request.args.get('date')
    if not _validate_statistics_date(raw_date):
        return api_error(
            'Reports date must be in YYYY-MM-DD format.',
            code='invalid_date',
            status=400,
            field='date',
        )

    tz_name = (dev.timezone or current_app.config.get('LOCAL_TIMEZONE') or 'UTC')
    selected_date = parse_selected_date(raw_date or None, tz_name)

    if view == 'day':
        start = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    else:  # 'month'
        start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    end_naive = end.replace(tzinfo=None) if end.tzinfo else end

    max_rows = current_app.config.get('MAX_READINGS_QUERY', 2000)
    ordered = (
        Reading.query
        .filter_by(device_id=dev.id)
        .filter(Reading.created_at >= start_naive, Reading.created_at < end_naive)
        .order_by(Reading.created_at.asc())
        .limit(max_rows)
        .all()
    )

    filtered_rows, title_hint = filter_rows_for_view(ordered, view, selected_date, tz_name)
    stats = compute_energy_stats(filtered_rows)

    payload = _mobile_reports_summary_payload(
        view=view,
        selected_date=selected_date,
        title_hint=title_hint,
        stats=stats,
        generated_at=datetime.utcnow().isoformat(),
    )
    return api_ok(payload)


# v62: ── Weather helpers ────────────────────────────────────────────
#
# The web `weather_service.WeatherSnapshot` dataclass already carries
# every field the phase-1 mobile Weather tab needs (current
# conditions, sun times, next-hour slot, day-parts, six-entry
# timeline). The helpers below do nothing except *re-shape* that
# snapshot into a flat JSON contract the mobile client can parse
# without learning dataclass internals — no values are recomputed,
# no derivations are added, no fabricated fallbacks are inserted.
#
# Slot dicts inside `WeatherSnapshot` are already mobile-safe (plain
# Python primitives produced by `_slot_from_hourly` /
# `fetch_weather`), so passing them through verbatim is the honest
# choice. We only filter the keys to the documented contract.

# Keys the mobile contract surfaces from each slot dict. Anything
# outside this set is dropped so a future backend field addition
# doesn't silently leak into the mobile payload before the mobile
# parser is updated.
_MOBILE_WEATHER_SLOT_KEYS = (
    'time', 'time_label',
    'temperature', 'cloud_cover', 'precipitation_probability',
    'condition_ar', 'category', 'icon',
    'solar_rating', 'advice',
)


def _slot_for_mobile(slot):
    """Filter a weather-pipeline slot dict to the mobile contract.

    Returns `None` when the slot is missing or not a dict (matches
    how `WeatherSnapshot.next_hour` / day-parts behave on cold
    payloads). Day-part slots from `_slot_from_hourly` carry `time`
    (ISO); `timeline[]` entries carry `time_label` (already-Arabic
    `HH:MM ص/م`) — both keys are forwarded so the mobile client
    can pick whichever is present without re-formatting.
    """
    if not isinstance(slot, dict):
        return None
    return {key: slot.get(key) for key in _MOBILE_WEATHER_SLOT_KEYS}


def _mobile_weather_payload(device, snapshot, generated_at):
    """Build the success payload from a `WeatherSnapshot`.

    Every value is read straight off `snapshot` (no rounding, no
    derivations). The shape mirrors the v62 contract documented
    in the route handler docstring.
    """
    return {
        'available': True,
        'device': {
            'id': device.id,
            'name': device.name or '',
            'timezone': device.timezone or '',
        },
        'current': {
            'temperature_c': snapshot.temperature,
            'wind_speed': snapshot.wind_speed,
            'cloud_cover_percent': snapshot.cloud_cover,
            'precipitation_probability_percent': snapshot.precipitation_probability,
            'condition_ar': snapshot.condition_ar,
            'category': snapshot.category,
            'icon': snapshot.icon,
            'code': snapshot.code,
            'current_time': snapshot.current_time,
        },
        'sun': {
            'sunrise_time': snapshot.sunrise_time,
            'sunset_time': snapshot.sunset_time,
            'effective_sunrise_time': snapshot.effective_sunrise_time,
            'effective_sunset_time': snapshot.effective_sunset_time,
        },
        'next_hour': _slot_for_mobile(snapshot.next_hour),
        'day_parts': {
            'morning': _slot_for_mobile(snapshot.morning),
            'noon': _slot_for_mobile(snapshot.noon),
            'afternoon': _slot_for_mobile(snapshot.afternoon),
        },
        'timeline': [
            slot for slot in (
                _slot_for_mobile(entry) for entry in (snapshot.timeline or [])
            )
            if slot is not None
        ],
        'generated_at': generated_at,
    }


def _mobile_weather_unavailable(*, reason, message, device, generated_at):
    """Build the honest empty payload. `reason` is the machine-
    readable stable code; `message` is a calm Arabic-friendly hint.

    Device summary is included even on the unavailable path so the
    mobile client can render the screen header consistently. No
    fabricated weather fields — the absence of `current` / `sun` /
    `timeline` is the contract."""
    return {
        'available': False,
        'reason': reason,
        'message': message,
        'device': {
            'id': device.id,
            'name': device.name or '',
            'timezone': device.timezone or '',
        },
        'generated_at': generated_at,
    }


@mobile_devices_api_bp.get('/<int:device_id>/weather')
def device_weather(device_id: int):
    """v62 — subscriber-scoped current weather for one device.

    Owner-scoped via `_device_allowed`, same pattern as the v52
    `/history` + `/alerts`, v56 `/statistics`, and v59
    `/reports/summary` endpoints. Reuses the existing web-side
    weather pipeline verbatim: `extract_station_coords(latest)` and
    `fetch_weather(lat, lng, tz)` — no derivations, no smart-engine
    coupling, no notification side-effects.

    Honest unavailability:
      * No latest reading for the device →
        `available=false, reason='reading_unavailable'`. (v78: was
        previously folded into `station_coords_unavailable`; the two
        cases now diverge so the client can render different copy
        for "not synced yet" vs "vendor blob has no coords".)
      * Latest reading exists but carries no station coords →
        `available=false, reason='station_coords_unavailable'`.
        Typical for providers whose vendor blob doesn't ship
        `locationLat` / `locationLng`.
      * Open-Meteo call raises (network / vendor outage / timeout) →
        `available=false, reason='weather_unreachable'`. The mobile
        client renders a retry-friendly error; nothing is logged
        about the inverter or its data.

    Night-time is NEVER reported as a weather failure — Open-Meteo
    serves valid payloads 24×7 and the helper's sunrise/sunset block
    is the right place to express "the sun is down", not the
    unavailability path.

    Energy-coupled extras intentionally NOT in this contract:
    pre-sunset prediction, weather-aware smart energy advice, sun
    context phase classification. Those live on the dashboard /
    reports surfaces today and stay there.
    """
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)

    generated_at = datetime.utcnow().isoformat()

    # Use the device's timezone when present; fall back to the app-
    # level default. We never invent one — Open-Meteo accepts plain
    # IANA names and the wrapper raises if they're unknown.
    tz_name = (dev.timezone or current_app.config.get('LOCAL_TIMEZONE') or 'UTC')

    # Resolve the latest reading for the device. Same query shape as
    # `/history` / `/alerts` so the DB index path is identical.
    latest = (
        Reading.query
        .filter_by(device_id=dev.id)
        .order_by(Reading.created_at.desc(), Reading.id.desc())
        .first()
    )

    # v78: split "no reading yet" from "reading exists but no coords"
    # so the client can render different copy. The two cases have
    # different remediation:
    #   * `reading_unavailable` → the user is waiting for the first
    #     successful sync; nothing to fix on their end.
    #   * `station_coords_unavailable` → the provider doesn't ship
    #     coords in its vendor blob; the user can fix this by
    #     editing the device location (or contacting support).
    if latest is None:
        return api_ok(_mobile_weather_unavailable(
            reason='reading_unavailable',
            message='No recent reading is available for this device yet.',
            device=dev,
            generated_at=generated_at,
        ))

    lat, lng = _extract_station_coords(latest)
    if lat is None or lng is None:
        return api_ok(_mobile_weather_unavailable(
            reason='station_coords_unavailable',
            message='Weather data is not available for this device yet.',
            device=dev,
            generated_at=generated_at,
        ))

    try:
        snapshot = fetch_weather(lat, lng, tz_name)
    except Exception:
        # Open-Meteo outage / network error / timeout. We swallow
        # the underlying exception text on purpose: the mobile
        # client doesn't need vendor stack traces. The stable
        # `reason` code is the contract for retry behaviour.
        return api_ok(_mobile_weather_unavailable(
            reason='weather_unreachable',
            message='Weather service could not be reached right now.',
            device=dev,
            generated_at=generated_at,
        ))

    # v78: defensive — if the wrapper returns `None` instead of
    # raising (e.g. internal caller swallowed the error), surface
    # `weather_unreachable` honestly rather than crashing the
    # payload builder downstream.
    if snapshot is None:
        return api_ok(_mobile_weather_unavailable(
            reason='weather_unreachable',
            message='Weather service could not be reached right now.',
            device=dev,
            generated_at=generated_at,
        ))

    return api_ok(_mobile_weather_payload(dev, snapshot, generated_at))


# v74: ── Smart insights helpers ─────────────────────────────────────
#
# Tiny payload mappers that turn the rich dicts returned by the
# existing smart/energy/weather helpers into the compact mobile
# contract surfaced by `GET /<id>/insights`. The mapping is a pure
# field-pick + level-translation; no smart logic is reproduced here.

# Status-label → mobile-friendly level. `build_smart_energy_advice`
# returns Arabic labels prefixed with a coloured circle emoji
# (🟢/🟡/🟠/🔴/⚪) — the mobile screen wants a stable machine value.
def _mobile_advice_level(status_label: str) -> str:
    s = str(status_label or '')
    if '🟢' in s:
        return 'good'
    if '🟡' in s:
        return 'caution'
    if '🟠' in s:
        return 'warning'
    if '🔴' in s:
        return 'critical'
    return 'unknown'


def _mobile_energy_advice(raw: dict) -> dict:
    """Flatten `build_smart_energy_advice(...)` into the mobile shape:
    `{headline, detail, level}`. Picks the most actionable phrase
    from the warning / recommendation / decision tree so the Home
    card stays calm even when the advice dict is verbose."""
    if not isinstance(raw, dict):
        return {'headline': '', 'detail': '', 'level': 'unknown'}
    headline = (raw.get('status_label') or '').strip()
    # Prefer the explicit warning when one is present (means the
    # advice actually has something to flag). Fall back to the
    # recommendation, then to the "what now" sentence.
    warning = (raw.get('smart_warning') or '').strip()
    recommendation = (raw.get('smart_recommendation') or '').strip()
    decision = (raw.get('decision_now') or '').strip()
    detail_parts = []
    if warning:
        detail_parts.append(warning)
    if recommendation:
        detail_parts.append(recommendation)
    elif decision:
        detail_parts.append(decision)
    detail = ' '.join(detail_parts).strip()
    return {
        'headline': headline,
        'detail': detail,
        'level': _mobile_advice_level(headline),
    }


def _mobile_solar_prediction(raw) -> dict | None:
    """Compact subset of `build_pre_sunset_prediction(...)`. Returns
    `None` when the helper itself returned `None` (no latest reading).
    Otherwise picks exactly the seven fields the mobile Home card
    renders — drops admin-only / internal keys like `capacity_kwh`,
    `reserve_percent`, `minutes_to_sunset`, `weather_level`, `is_day`.

    v78: also surfaces the new `is_night` flag so the card can pivot
    to night-state copy without recomputing the geometric daylight
    window. `time_to_full_hours` is force-cleared at night because
    the underlying derivation only makes sense while the sun is up;
    leaving a stale value would mislead the subscriber.
    """
    if not isinstance(raw, dict):
        return None
    time_to_full = raw.get('time_to_full_hours')
    if isinstance(time_to_full, (int, float)):
        time_to_full = round(float(time_to_full), 2)
    is_night = bool(raw.get('is_night'))
    if is_night:
        time_to_full = None
    return {
        'sunset_time': raw.get('sunset_time'),
        'effective_sunset_time': raw.get('effective_sunset_time'),
        'time_to_full_hours': time_to_full,
        # v78: night → never claim "will be full before sunset" — the
        # sunset is in the past today, the heuristic is no longer
        # applicable.
        'will_full_before_sunset': False if is_night else bool(
            raw.get('will_full_before_sunset'),
        ),
        'verdict': (raw.get('verdict') or '').strip() or None,
        'advice': (raw.get('advice') or '').strip() or None,
        'is_night': is_night,
    }


def _mobile_weather_context(snapshot) -> dict:
    """Compact, self-contained weather subset for the insights card.
    The full `WeatherSnapshot` shape lives on the v62 `/weather`
    endpoint — here we only need three fields to give the card a
    one-line header without forcing the mobile to fire a second
    weather fetch."""
    if snapshot is None:
        return {
            'condition_ar': '',
            'icon': '',
            'cloud_cover_percent': None,
        }
    return {
        'condition_ar': getattr(snapshot, 'condition_ar', '') or '',
        'icon': getattr(snapshot, 'icon', '') or '',
        'cloud_cover_percent': getattr(snapshot, 'cloud_cover', None),
    }


def _mobile_insights_payload(device, snapshot, prediction_dict,
                             advice_dict, generated_at) -> dict:
    """Build the success payload from the three upstream dicts.
    Every value passes through the small mappers above so no
    oversized internal helper structures leak into the response."""
    return {
        'available': True,
        'device': {
            'id': device.id,
            'name': getattr(device, 'name', '') or '',
            'timezone': getattr(device, 'timezone', '') or '',
        },
        'weather_context': _mobile_weather_context(snapshot),
        'solar_prediction': _mobile_solar_prediction(prediction_dict),
        'energy_advice': _mobile_energy_advice(advice_dict),
        'generated_at': generated_at,
    }


def _mobile_insights_unavailable(*, reason: str, message: str,
                                 device, generated_at) -> dict:
    """Honest empty payload. `reason` is the machine-readable stable
    code; `message` is a calm English fallback (the mobile screen
    maps the `reason` onto its own localised Arabic copy). Device
    summary is still present so the header renders consistently."""
    return {
        'available': False,
        'reason': reason,
        'message': message,
        'device': {
            'id': device.id,
            'name': getattr(device, 'name', '') or '',
            'timezone': getattr(device, 'timezone', '') or '',
        },
        'generated_at': generated_at,
    }


@mobile_devices_api_bp.get('/<int:device_id>/insights')
def device_insights(device_id: int):
    """v74 — subscriber-scoped "what should I do right now?" card
    inputs for one device.

    Owner-scoped via `_device_allowed`, same pattern as the v52
    `/history` + `/alerts`, v56 `/statistics`, v59 `/reports/summary`,
    and v62 `/weather` endpoints. Reuses the existing web-side
    helpers verbatim — `build_pre_sunset_prediction(latest, weather,
    settings)` and `build_smart_energy_advice(latest, weather,
    settings, context='periodic_day')` — and flattens their rich
    output into a compact mobile contract.

    The smart_engine + helpers chain consumes scope-bound `g`
    state in a few places (e.g. `save_smart_snapshot_from_reading`
    looks up the previous snapshot via `scoped_query`). We bind
    `g.current_user` + `g.current_device` for the duration of this
    request (same pattern as the v50 sync-now route) and restore
    on the way out so a later handler in the request lifecycle
    doesn't pick up a stale scope.

    Honest unavailable paths:
      * No latest reading for the device →
        `available=false, reason='reading_unavailable'`.
      * Latest reading exists but has no station coords →
        `available=false, reason='station_coords_unavailable'`.
      * Open-Meteo unreachable → `available=false,
        reason='weather_unreachable'`. The smart engine *can* run
        without weather, but the resulting advice + prediction are
        materially less useful without the sunset time, so we
        surface this honestly instead of producing degraded copy.
    """
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)

    generated_at = datetime.utcnow().isoformat()

    # Latest reading. The smart engine returns a `safe_empty` dict
    # when `latest is None`, but the mobile contract wants an
    # explicit `available=false` so the card can render a calm
    # "no data yet" state instead of placeholder advice.
    latest = (
        Reading.query
        .filter_by(device_id=dev.id)
        .order_by(Reading.created_at.desc(), Reading.id.desc())
        .first()
    )
    if latest is None:
        return api_ok(_mobile_insights_unavailable(
            reason='reading_unavailable',
            message='No recent reading is available for this device yet.',
            device=dev,
            generated_at=generated_at,
        ))

    # Station coords drive the weather fetch + sunset times. Without
    # them the smart engine produces vague advice without a sunset
    # anchor — surface as `available=false` honestly.
    lat, lng = _extract_station_coords(latest)
    if lat is None or lng is None:
        return api_ok(_mobile_insights_unavailable(
            reason='station_coords_unavailable',
            message='Weather-dependent insights are not available for this device yet.',
            device=dev,
            generated_at=generated_at,
        ))

    tz_name = (dev.timezone or current_app.config.get('LOCAL_TIMEZONE') or 'UTC')
    try:
        snapshot = fetch_weather(lat, lng, tz_name)
    except Exception:
        return api_ok(_mobile_insights_unavailable(
            reason='weather_unreachable',
            message='Weather service could not be reached right now.',
            device=dev,
            generated_at=generated_at,
        ))
    # v78: defensive — treat a `None` return as a weather-unreachable
    # event so downstream helpers never crash on missing attributes.
    if snapshot is None:
        return api_ok(_mobile_insights_unavailable(
            reason='weather_unreachable',
            message='Weather service could not be reached right now.',
            device=dev,
            generated_at=generated_at,
        ))

    # Bind the request-scoped helpers so smart_engine's scope-aware
    # snapshot save targets THIS device + user. Restore on the way
    # out — same shape as the v50 sync-now route.
    from flask import g
    prev_user = getattr(g, 'current_user', None)
    prev_device = getattr(g, 'current_device', None)
    g.current_user = user
    g.current_device = dev

    try:
        settings = load_settings()
        prediction_dict = build_pre_sunset_prediction(
            latest, weather=snapshot, settings=settings,
        )
        advice_dict = build_smart_energy_advice(
            latest, weather=snapshot, settings=settings, context='periodic_day',
        )
    finally:
        g.current_user = prev_user
        g.current_device = prev_device

    return api_ok(_mobile_insights_payload(
        device=dev,
        snapshot=snapshot,
        prediction_dict=prediction_dict,
        advice_dict=advice_dict,
        generated_at=generated_at,
    ))


@mobile_devices_api_bp.get('/<int:device_id>/alerts')
def device_alerts(device_id: int):
    user, err = _require_user()
    if err:
        return err
    dev = _device_allowed(user, device_id)
    if not dev:
        return api_error('Device not found.', code='device_not_found', status=404)
    latest = Reading.query.filter_by(device_id=dev.id).order_by(Reading.created_at.desc(), Reading.id.desc()).first()
    alerts = []
    if latest and latest.battery_soc is not None and latest.battery_soc < 20:
        alerts.append({'level': 'warning', 'key': 'battery_low', 'message': 'Battery is below 20%.'})
    if latest and latest.solar_power is not None and latest.solar_power <= 0:
        alerts.append({'level': 'info', 'key': 'solar_zero', 'message': 'Solar production is currently zero.'})
    return api_ok({'items': alerts})
