from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, current_app, request

from ..models import AppDevice, Reading
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.security import sanitize_response_payload, mask_identifier
from .helpers import (
    build_period_chart,
    compute_energy_stats,
    filter_rows_for_view,
    parse_selected_date,
)

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
