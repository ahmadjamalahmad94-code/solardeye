from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, request

from ..models import AppDevice, Reading
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.security import sanitize_response_payload, mask_identifier

mobile_devices_api_bp = Blueprint('mobile_devices_api', __name__, url_prefix='/api/v1/devices')


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
