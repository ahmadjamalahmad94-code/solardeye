from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, request, session
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from ..extensions import db
from ..models import AppDevice, AppUser, NotificationEvent, Reading, SubscriptionPlan, TenantAccount
from ..services.energy_integrations import provider_catalog
from ..services.location_catalog import countries_for_template, find_country, phone_prefixes_for_template, timezones_grouped_for_template, timezones_for_template
from ..services.rbac import portal_pages, portal_page_visible, role_label
from ..services.scope import get_current_device, get_user_permissions
from ..services.security import csrf_token, sanitize_response_payload
from ..services.subscriptions import allowed_device_limit, compute_subscription_status, current_subscription_for_user, ensure_user_tenant_and_subscription, plan_features
from ..services.mobile_auth import user_from_bearer_or_session, verify_access_token
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args

mobile_api_bp = Blueprint('mobile_api', __name__, url_prefix='/api/v1/mobile')
mobile_core_api_bp = Blueprint('mobile_core_api', __name__, url_prefix='/api/mobile')

_MOBILE_CORE_ALLOWED_METHODS = {
    '/profile': {'GET', 'PATCH'},
    '/onboarding': {'GET', 'POST', 'PATCH'},
    '/location-catalog': {'GET'},
    '/device-providers': {'GET'},
    '/dashboard': {'GET'},
    '/dashboard/feed': {'GET'},
    '/live': {'GET'},
    '/bootstrap': {'GET'},
    '/health': {'GET'},
}


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _require_login():
    user = user_from_bearer_or_session()
    if not user:
        return None, api_error('Authentication required.', code='auth_required', status=401), 401
    return user, None, None


def _require_bearer_user():
    auth = request.headers.get('Authorization', '')
    if not auth.lower().startswith('bearer '):
        return None, api_error('Bearer token is required.', code='auth_required', status=401)
    user = verify_access_token(auth.split(' ', 1)[1])
    if not user:
        return None, api_error('Authentication token is invalid or expired.', code='invalid_token', status=401)
    return user, None


def _strict_json_object():
    if not request.content_length and not request.is_json:
        return {}, None
    try:
        data = request.get_json(silent=False)
    except (BadRequest, UnsupportedMediaType):
        return None, _json_error('Request body must be valid JSON.', code='invalid_json')
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, _json_error('JSON object is required.', code='invalid_json')
    return data, None


def _boolean_or_error(value, field: str):
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes'}:
            return True, None
        if normalized in {'false', '0', 'no'}:
            return False, None
    return None, _json_error('Boolean value is invalid.', code='invalid_boolean', field=field)


def _safe_json_loads(raw_value):
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _json_error(message: str, *, code: str, status: int = 400, field: str | None = None):
    errors = [{'field': field, 'message': message}] if field else []
    return api_error(message, code=code, status=status, errors=errors)


def _normalize_language(value: str | None):
    if value is None:
        return None
    lang = str(value or '').strip().lower()
    if lang not in {'ar', 'en'}:
        return None
    return lang


def _clean_phone(value: str | None) -> str:
    allowed = set('+ -()')
    return ''.join(ch for ch in (value or '') if ch.isdigit() or ch in allowed).strip()


def _float_or_error(value, field: str, *, minimum: float | None = None, maximum: float | None = None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, _json_error(f'{field} must be a number.', code='invalid_number', field=field)
    if minimum is not None and number < minimum:
        return None, _json_error(f'{field} is below the allowed range.', code='number_too_low', field=field)
    if maximum is not None and number > maximum:
        return None, _json_error(f'{field} is above the allowed range.', code='number_too_high', field=field)
    return number, None


def _is_secret_field(name: str) -> bool:
    lowered = (name or '').lower()
    return any(word in lowered for word in ('password', 'secret', 'token', 'key', 'credential'))


def _field_label(name: str) -> dict:
    labels = {
        'deye_app_id': ('Deye App ID', 'Deye App ID'),
        'deye_app_secret': ('Deye App Secret', 'Deye App Secret'),
        'deye_email': ('بريد Deye', 'Deye email'),
        'deye_password_or_hash': ('كلمة مرور Deye أو SHA-256', 'Deye password or SHA-256'),
        'deye_plant_id': ('Plant ID', 'Plant ID'),
        'deye_device_sn': ('Device SN', 'Device SN'),
        'deye_logger_sn': ('Logger SN', 'Logger SN'),
        'battery_capacity_kwh': ('سعة البطارية kWh', 'Battery capacity kWh'),
        'battery_reserve_percent': ('احتياطي البطارية %', 'Battery reserve %'),
        'local_base_url': ('رابط الجهاز المحلي', 'Local device URL'),
        'api_key': ('API Key', 'API key'),
        'api_secret': ('API Secret', 'API secret'),
        'access_token': ('Access Token', 'Access token'),
        'oauth_access_token': ('OAuth Access Token', 'OAuth access token'),
        'refresh_token': ('Refresh Token', 'Refresh token'),
        'username': ('اسم المستخدم', 'Username'),
        'password': ('كلمة المرور', 'Password'),
    }
    ar, en = labels.get(name, (name.replace('_', ' ').title(), name.replace('_', ' ').title()))
    return {'ar': ar, 'en': en}


def _profile_payload(user):
    return {
        'id': user.id,
        'username': user.username,
        'full_name': user.full_name,
        'email': user.email,
        'role': user.role,
        'role_label': role_label(user.role, _lang()),
        'is_admin': bool(user.is_admin),
        'is_active': bool(user.is_active),
        'preferred_language': user.preferred_language or 'ar',
        'country': user.country or '',
        'city': user.city or '',
        'timezone': user.timezone or '',
        'phone_country_code': user.phone_country_code or '',
        'phone_number': user.phone_number or '',
        'profile_image_url': user.profile_image_url or '',
        'preferred_device_id': user.preferred_device_id,
    }


def _device_summary_payload(user):
    q = AppDevice.query.filter_by(owner_user_id=user.id).order_by(AppDevice.is_active.desc(), AppDevice.id.asc())
    devices = q.all()
    selected = None
    if user.preferred_device_id:
        selected = next((dev for dev in devices if dev.id == user.preferred_device_id), None)
    if selected is None:
        selected = next((dev for dev in devices if dev.is_active), devices[0] if devices else None)
    return {
        'selected_device_id': selected.id if selected else None,
        'total': len(devices),
        'active': len([dev for dev in devices if dev.is_active]),
        'items': [{
            'id': dev.id,
            'name': dev.name,
            'device_type': dev.device_type,
            'api_provider': dev.api_provider,
            'connection_status': dev.connection_status,
            'is_active': bool(dev.is_active),
            'timezone': dev.timezone,
        } for dev in devices],
    }


def _mobile_owned_devices(user):
    return (
        AppDevice.query
        .filter_by(owner_user_id=user.id)
        .order_by(AppDevice.is_active.desc(), AppDevice.id.asc())
        .all()
    )


def _mobile_device_payload(dev):
    if not dev:
        return None
    return sanitize_response_payload({
        'id': dev.id,
        'name': dev.name,
        'device_type': dev.device_type,
        'api_provider': dev.api_provider,
        'connection_status': dev.connection_status,
        'last_connected_at': dev.last_connected_at.isoformat() if dev.last_connected_at else None,
        'is_active': bool(dev.is_active),
        'plant_name': dev.plant_name,
        'timezone': dev.timezone,
    })


def _selected_device_for_user(user):
    q = AppDevice.query.filter_by(owner_user_id=user.id)
    device = None
    if getattr(user, 'preferred_device_id', None):
        device = q.filter_by(id=user.preferred_device_id).first()
    if device is None:
        device = AppDevice.query.filter_by(owner_user_id=user.id, is_active=True).order_by(AppDevice.id.asc()).first()
    if device is None:
        device = AppDevice.query.filter_by(owner_user_id=user.id).order_by(AppDevice.id.asc()).first()
    return device


def _device_state_payload(user):
    device = _selected_device_for_user(user)
    return {
        'selected_device_id': getattr(device, 'id', None),
        'current_device': {
            'id': device.id,
            'name': device.name,
            'device_type': device.device_type,
            'api_provider': device.api_provider,
            'connection_status': device.connection_status,
            'is_active': bool(device.is_active),
            'timezone': device.timezone,
        } if device else None,
        'devices': _device_summary_payload(user),
    }


def _system_basics_payload(user):
    device = _selected_device_for_user(user)
    settings = _safe_json_loads(getattr(device, 'settings_json', None)) if device else {}
    return {
        'selected_device_id': getattr(device, 'id', None),
        'preferred_device_type': user.preferred_device_type or '',
        'battery_capacity_kwh': settings.get('battery_capacity_kwh') or '',
        'battery_reserve_percent': settings.get('battery_reserve_percent') or '',
    }


def _subscription_payload(user):
    tenant = TenantAccount.query.get(user.tenant_id) if getattr(user, 'tenant_id', None) else None
    sub = current_subscription_for_user(user)
    if tenant is None or sub is None:
        tenant, sub = ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    plan = SubscriptionPlan.query.get(tenant.plan_id) if tenant and tenant.plan_id else None
    status = compute_subscription_status(sub)
    return {
        'tenant_id': getattr(tenant, 'id', None),
        'status': status,
        'expires_at': sub.ends_at.isoformat() if sub and sub.ends_at else None,
        'trial_ends_at': sub.trial_ends_at.isoformat() if sub and sub.trial_ends_at else None,
        'max_devices': allowed_device_limit(user),
        'plan': {
            'id': plan.id,
            'code': plan.code,
            'name_ar': plan.name_ar,
            'name_en': plan.name_en,
            'price': plan.price,
            'currency': plan.currency,
            'max_devices': plan.max_devices,
            'features': plan_features(plan),
        } if plan else None,
    }


def _onboarding_payload(user):
    has_location = bool((user.country or '').strip() and (user.city or '').strip() and (user.timezone or '').strip())
    has_device = bool(AppDevice.query.filter_by(owner_user_id=user.id).first())
    return {
        'completed': bool(user.onboarding_completed),
        'step': user.onboarding_step or ('done' if user.onboarding_completed else 'welcome'),
        'needs_profile_location': not has_location,
        'needs_device_link': not has_device,
        'system_basics': _system_basics_payload(user),
        'device_state': _device_state_payload(user),
    }


def _provider_payloads():
    rows = []
    for spec in provider_catalog():
        fields = []
        for field in list(spec.required_fields or ()) + list(spec.optional_fields or ()):
            fields.append({
                'name': field,
                'label': _field_label(field),
                'required': field in (spec.required_fields or ()),
                'secret': _is_secret_field(field),
            })
        rows.append({
            'key': spec.code,
            'code': spec.code,
            'display_name': spec.name,
            'name': spec.name,
            'provider': spec.provider,
            'auth_mode': spec.auth_mode,
            'category': spec.category,
            'status': spec.status,
            'base_url': spec.base_url or '',
            'required_fields': list(spec.required_fields or ()),
            'optional_fields': list(spec.optional_fields or ()),
            'fields': fields,
            'notes_ar': spec.notes_ar,
            'notes_en': spec.notes_en,
        })
    return rows


def _location_payload():
    countries = countries_for_template()
    return {
        'countries': countries,
        'phone_prefixes': phone_prefixes_for_template(),
        'cities': {
            (country.get('code') or '').strip().upper(): {
                'ar': country.get('cities_ar') or [],
                'en': country.get('cities_en') or [],
                'timezone': country.get('timezone') or '',
                'dial': country.get('dial') or '',
            }
            for country in countries
            if country.get('code')
        },
        'timezones': timezones_for_template(),
        'timezone_groups': timezones_grouped_for_template(),
    }


@mobile_core_api_bp.get('/profile')
def mobile_profile_get():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_ok({
        'user': _profile_payload(user),
        'onboarding': _onboarding_payload(user),
        'subscription': _subscription_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.patch('/profile')
def mobile_profile_update():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    if 'full_name' in data:
        user.full_name = (data.get('full_name') or '').strip() or None

    if 'email' in data:
        email = (data.get('email') or '').strip().lower()
        if email and '@' not in email:
            return _json_error('Email address is invalid.', code='invalid_email', field='email')
        if email:
            other = AppUser.query.filter(db.func.lower(AppUser.email) == email, AppUser.id != user.id).first()
            if other:
                return _json_error('Email is already in use.', code='email_taken', status=409, field='email')
        user.email = email or None

    if 'phone_country_code' in data:
        prefix = (data.get('phone_country_code') or '').strip()
        valid_prefixes = {row.get('dial') for row in phone_prefixes_for_template()}
        if prefix and prefix not in valid_prefixes:
            return _json_error('Phone country code is not supported.', code='invalid_phone_country_code', field='phone_country_code')
        user.phone_country_code = prefix or None

    if 'phone_number' in data:
        phone = _clean_phone(data.get('phone_number'))
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if phone and len(digits) < 6:
            return _json_error('Phone number is too short.', code='invalid_phone_number', field='phone_number')
        user.phone_number = phone or None

    country_changed = any(key in data for key in ('country', 'country_code'))
    if country_changed:
        lang = _normalize_language(data.get('preferred_language')) or user.preferred_language or _lang()
        selected_country = find_country(data.get('country_code') or data.get('country'))
        if not selected_country and (data.get('country') or data.get('country_code')):
            return _json_error('Country is not supported.', code='invalid_country', field='country')
        if selected_country:
            user.country = selected_country.get('name_en') if lang == 'en' else selected_country.get('name_ar')
            if not user.phone_country_code:
                user.phone_country_code = selected_country.get('dial') or None
            if not data.get('timezone'):
                user.timezone = selected_country.get('timezone') or user.timezone or 'Asia/Hebron'
        else:
            user.country = None

    if 'city' in data:
        user.city = (data.get('city') or '').strip() or None

    if 'timezone' in data:
        timezone = (data.get('timezone') or '').strip()
        if timezone and timezone not in timezones_for_template():
            return _json_error('Timezone is not supported.', code='invalid_timezone', field='timezone')
        user.timezone = timezone or None

    if 'preferred_language' in data:
        lang = _normalize_language(data.get('preferred_language'))
        if not lang:
            return _json_error('Preferred language must be ar or en.', code='invalid_language', field='preferred_language')
        user.preferred_language = lang

    db.session.commit()
    return api_ok({
        'user': _profile_payload(user),
        'onboarding': _onboarding_payload(user),
        'subscription': _subscription_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/onboarding')
def mobile_onboarding_get():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_ok({
        'onboarding': _onboarding_payload(user),
        'user': _profile_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/onboarding')
@mobile_core_api_bp.patch('/onboarding')
def mobile_onboarding_update():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    allowed_steps = {'welcome', 'profile', 'device', 'notifications', 'finish', 'done', 'explore_services'}
    if 'onboarding_step' in data or 'step' in data:
        step = (data.get('onboarding_step') or data.get('step') or '').strip().lower()
        if step not in allowed_steps:
            return _json_error('Onboarding step is not supported.', code='invalid_onboarding_step', field='onboarding_step')
        user.onboarding_step = step

    if 'onboarding_completed' in data or 'completed' in data:
        field = 'onboarding_completed' if 'onboarding_completed' in data else 'completed'
        completed = data.get('onboarding_completed') if 'onboarding_completed' in data else data.get('completed')
        parsed_completed, error = _boolean_or_error(completed, field)
        if error:
            return error
        user.onboarding_completed = parsed_completed
        if user.onboarding_completed and not user.onboarding_step:
            user.onboarding_step = 'done'

    if 'selected_device_id' in data or 'current_device_id' in data:
        raw_id = data.get('selected_device_id') if 'selected_device_id' in data else data.get('current_device_id')
        try:
            device_id = int(raw_id)
        except (TypeError, ValueError):
            return _json_error('Selected device id is invalid.', code='invalid_device_id', field='selected_device_id')
        device = AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()
        if not device:
            return _json_error('Device was not found for this account.', code='device_not_found', status=404, field='selected_device_id')
        if not device.is_active:
            return _json_error('Selected device is not active.', code='device_inactive', field='selected_device_id')
        user.preferred_device_id = device.id
        user.preferred_device_type = device.device_type or user.preferred_device_type

    if 'preferred_device_type' in data:
        provider_codes = {spec.code for spec in provider_catalog()}
        provider_code = (data.get('preferred_device_type') or '').strip().lower()
        if provider_code and provider_code not in provider_codes:
            return _json_error('Device provider is not supported.', code='invalid_provider', field='preferred_device_type')
        if provider_code:
            user.preferred_device_type = provider_code

    basics = data.get('system_basics') if isinstance(data.get('system_basics'), dict) else {}
    for key in ('battery_capacity_kwh', 'battery_reserve_percent'):
        if key in data and key not in basics:
            basics[key] = data.get(key)
    if basics:
        device = _selected_device_for_user(user)
        if not device:
            return _json_error('A device is required before saving system basics.', code='device_required', status=409)
        settings = _safe_json_loads(device.settings_json)
        if 'battery_capacity_kwh' in basics:
            capacity, error = _float_or_error(basics.get('battery_capacity_kwh'), 'battery_capacity_kwh', minimum=0.1, maximum=1000)
            if error:
                return error
            settings['battery_capacity_kwh'] = str(capacity).rstrip('0').rstrip('.') if capacity % 1 else str(int(capacity))
        if 'battery_reserve_percent' in basics:
            reserve, error = _float_or_error(basics.get('battery_reserve_percent'), 'battery_reserve_percent', minimum=0, maximum=100)
            if error:
                return error
            settings['battery_reserve_percent'] = str(reserve).rstrip('0').rstrip('.') if reserve % 1 else str(int(reserve))
        device.settings_json = json.dumps(settings, ensure_ascii=False)

    db.session.commit()
    return api_ok({
        'onboarding': _onboarding_payload(user),
        'user': _profile_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/location-catalog')
def mobile_location_catalog():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_ok(_location_payload(), meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/device-providers')
def mobile_device_providers():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_ok({'items': _provider_payloads()}, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


def _reading_payload(row):
    if not row:
        return None
    return sanitize_response_payload({
        'id': row.id,
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
    })


def _reading_number(value):
    try:
        return round(float(value or 0), 2)
    except Exception:
        return 0.0


def _bounded_int(value, *, default: int, maximum: int):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _mobile_reading_payload(row):
    if not row:
        return None
    payload = _reading_payload(row) or {}
    payload.update({
        'device_id': row.device_id,
        'user_id': row.user_id,
        'pv1_power': row.pv1_power,
        'pv2_power': row.pv2_power,
        'pv3_power': row.pv3_power,
        'pv4_power': row.pv4_power,
        'inverter_temp': row.inverter_temp,
        'dc_temp': row.dc_temp,
        'grid_voltage': row.grid_voltage,
        'grid_frequency': row.grid_frequency,
    })
    return sanitize_response_payload(payload)


def _mobile_reading_cards(row):
    if not row:
        return {
            'solar_power_w': 0.0,
            'home_load_w': 0.0,
            'battery_soc_percent': 0.0,
            'battery_power_w': 0.0,
            'grid_power_w': 0.0,
            'inverter_power_w': 0.0,
            'daily_production_kwh': 0.0,
            'monthly_production_kwh': 0.0,
            'total_production_kwh': 0.0,
        }
    return {
        'solar_power_w': _reading_number(row.solar_power),
        'home_load_w': _reading_number(row.home_load),
        'battery_soc_percent': _reading_number(row.battery_soc),
        'battery_power_w': _reading_number(row.battery_power),
        'grid_power_w': _reading_number(row.grid_power),
        'inverter_power_w': _reading_number(row.inverter_power),
        'daily_production_kwh': _reading_number(row.daily_production),
        'monthly_production_kwh': _reading_number(row.monthly_production),
        'total_production_kwh': _reading_number(row.total_production),
    }


def _mobile_device_scope(user):
    raw_device_id = (request.args.get('device_id') or request.args.get('device') or '').strip()
    raw_scope = (request.args.get('scope') or '').strip().lower()
    if raw_scope == 'all' or raw_device_id.lower() == 'all':
        return 'all', None, None
    if raw_device_id:
        try:
            device_id = int(raw_device_id)
        except (TypeError, ValueError):
            return None, None, api_error('Device id is invalid.', code='invalid_device_id', status=400)
        device = AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()
        if not device:
            return None, None, api_error('Device was not found for this account.', code='device_not_found', status=404)
        return 'device', device, None
    return 'device', _selected_device_for_user(user), None


def _mobile_readings_query(user, *, mode: str, device=None):
    q = Reading.query
    if mode == 'all':
        device_ids = [dev.id for dev in _mobile_owned_devices(user)]
        if device_ids:
            return q.filter(Reading.device_id.in_(device_ids))
        return q.filter_by(user_id=user.id)
    if device:
        return q.filter_by(device_id=device.id)
    return q.filter_by(user_id=user.id)


def _mobile_latest_reading(user, *, mode: str, device=None):
    return (
        _mobile_readings_query(user, mode=mode, device=device)
        .order_by(Reading.created_at.desc(), Reading.id.desc())
        .first()
    )


def _mobile_feed_rows(user, *, mode: str, device=None, limit: int = 48):
    bounded_limit = _bounded_int(limit, default=48, maximum=200)
    rows = (
        _mobile_readings_query(user, mode=mode, device=device)
        .order_by(Reading.created_at.desc(), Reading.id.desc())
        .limit(bounded_limit)
        .all()
    )
    return list(reversed(rows))


def _mobile_fleet_snapshot(user):
    items = []
    latest_rows = []
    for dev in _mobile_owned_devices(user):
        latest = (
            Reading.query
            .filter_by(device_id=dev.id)
            .order_by(Reading.created_at.desc(), Reading.id.desc())
            .first()
        )
        if latest:
            latest_rows.append(latest)
        items.append({
            'device': _mobile_device_payload(dev),
            'latest': _mobile_reading_payload(latest),
            'cards': _mobile_reading_cards(latest),
            'empty': latest is None,
        })
    battery_values = [_reading_number(row.battery_soc) for row in latest_rows if row.battery_soc is not None]
    return {
        'items': items,
        'aggregate': {
            'device_count': len(items),
            'devices_with_readings': len(latest_rows),
            'solar_power_w': round(sum(_reading_number(row.solar_power) for row in latest_rows), 2),
            'home_load_w': round(sum(_reading_number(row.home_load) for row in latest_rows), 2),
            'battery_power_w': round(sum(_reading_number(row.battery_power) for row in latest_rows), 2),
            'grid_power_w': round(sum(_reading_number(row.grid_power) for row in latest_rows), 2),
            'inverter_power_w': round(sum(_reading_number(row.inverter_power) for row in latest_rows), 2),
            'daily_production_kwh': round(sum(_reading_number(row.daily_production) for row in latest_rows), 2),
            'monthly_production_kwh': round(sum(_reading_number(row.monthly_production) for row in latest_rows), 2),
            'total_production_kwh': round(sum(_reading_number(row.total_production) for row in latest_rows), 2),
            'battery_soc_average_percent': round(sum(battery_values) / len(battery_values), 2) if battery_values else 0.0,
        },
    }


def _mobile_dashboard_payload(user, *, include_feed: bool = True):
    mode, device, error = _mobile_device_scope(user)
    if error:
        return None, error
    latest = _mobile_latest_reading(user, mode=mode, device=device)
    limit = request.args.get('limit') or request.args.get('page_size') or 48
    feed_rows = _mobile_feed_rows(user, mode=mode, device=device, limit=limit) if include_feed else []
    payload = {
        'scope': {
            'mode': 'all' if mode == 'all' else 'device',
            'device_id': device.id if device else None,
            'is_all_devices': mode == 'all',
        },
        'device': _mobile_device_payload(device),
        'devices': _device_summary_payload(user),
        'latest': _mobile_reading_payload(latest),
        'cards': _mobile_reading_cards(latest),
        'feed': {
            'items': [_mobile_reading_payload(row) for row in feed_rows],
            'count': len(feed_rows),
            'order': 'oldest_first',
        },
        'empty': latest is None,
        'generated_at': datetime.utcnow().isoformat(),
    }
    if mode == 'all':
        fleet = _mobile_fleet_snapshot(user)
        aggregate = fleet['aggregate']
        payload['fleet'] = fleet
        payload['cards'] = {
            'solar_power_w': aggregate['solar_power_w'],
            'home_load_w': aggregate['home_load_w'],
            'battery_soc_percent': aggregate['battery_soc_average_percent'],
            'battery_power_w': aggregate['battery_power_w'],
            'grid_power_w': aggregate['grid_power_w'],
            'inverter_power_w': aggregate['inverter_power_w'],
            'daily_production_kwh': aggregate['daily_production_kwh'],
            'monthly_production_kwh': aggregate['monthly_production_kwh'],
            'total_production_kwh': aggregate['total_production_kwh'],
        }
    return payload, None


@mobile_core_api_bp.get('/dashboard')
def mobile_dashboard():
    user, err = _require_bearer_user()
    if err:
        return err
    payload, error = _mobile_dashboard_payload(user, include_feed=True)
    if error:
        return error
    return api_ok(payload, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/live')
def mobile_live():
    user, err = _require_bearer_user()
    if err:
        return err
    payload, error = _mobile_dashboard_payload(user, include_feed=False)
    if error:
        return error
    return api_ok({
        'scope': payload['scope'],
        'device': payload['device'],
        'latest': payload['latest'],
        'cards': payload['cards'],
        'empty': payload['empty'],
        'generated_at': payload['generated_at'],
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/dashboard/feed')
def mobile_dashboard_feed():
    user, err = _require_bearer_user()
    if err:
        return err
    mode, device, error = _mobile_device_scope(user)
    if error:
        return error
    page, page_size = pagination_args(default_size=50, max_size=200)
    q = _mobile_readings_query(user, mode=mode, device=device).order_by(Reading.created_at.desc(), Reading.id.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return api_ok({
        'scope': {
            'mode': 'all' if mode == 'all' else 'device',
            'device_id': device.id if device else None,
            'is_all_devices': mode == 'all',
        },
        'device': _mobile_device_payload(device),
        'items': [_mobile_reading_payload(row) for row in rows],
        'order': 'newest_first',
    }, meta={**page_meta(page, page_size, total), 'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/bootstrap')
@mobile_api_bp.get('/bootstrap')
def bootstrap():
    user, error, status = _require_login()
    if error:
        return error, status
    lang = _lang()
    pages = []
    for page in portal_pages(include_locked=True):
        key = getattr(page, 'page_key', '')
        if not portal_page_visible(key):
            continue
        pages.append({
            'key': key,
            'endpoint': page.endpoint,
            'label': page.label_en if lang == 'en' else page.label_ar,
            'icon': page.icon,
            'group': page.group_key,
            'order': page.sort_order,
        })
    payload = {
        'version': '10.1',
        'auth_strategy': {'type': 'Bearer', 'refresh_token': True},
        'user': _profile_payload(user),
        'subscription': _subscription_payload(user),
        'onboarding': _onboarding_payload(user),
        'devices': _device_summary_payload(user),
        'permissions': get_user_permissions(user),
        'navigation': pages,
        'providers': _provider_payloads(),
        'location_catalog': _location_payload(),
    }
    if request.path.startswith('/api/v1/'):
        payload['csrf_token'] = csrf_token()
    return api_ok(payload, meta={'api_version': 'v1', 'namespace': 'api/mobile', 'lang': lang})


@mobile_api_bp.get('/summary')
def summary():
    user, error, status = _require_login()
    if error:
        return error, status
    device = get_current_device()
    q = Reading.query.order_by(Reading.created_at.desc())
    if device:
        q = q.filter_by(device_id=device.id)
    elif user and not user.is_admin:
        q = q.filter_by(user_id=user.id)
    latest = q.first()
    return api_ok({
        'device': {'id': getattr(device, 'id', None), 'name': getattr(device, 'name', None), 'type': getattr(device, 'device_type', None)},
        'latest': _reading_payload(latest),
    }, meta={'api_version': 'v1'})


@mobile_api_bp.get('/notifications')
def notifications():
    user, error, status = _require_login()
    if error:
        return error, status
    rows = NotificationEvent.query.filter_by(target_user_id=user.id).order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc()).limit(30).all()
    return api_ok({
        'items': [sanitize_response_payload({'id': r.id, 'title': r.title, 'message': r.message, 'url': r.direct_url, 'is_read': r.is_read, 'created_at': r.created_at.isoformat() if r.created_at else None}) for r in rows],
    }, meta={'api_version': 'v1'})


@mobile_api_bp.get('/health')
def health():
    return api_ok({'version': '10.1', 'message': 'SolarDeye mobile API is ready'}, meta={'api_version': 'v1'})


@mobile_core_api_bp.get('/health')
def mobile_health():
    return api_ok({'version': '10.1', 'message': 'SolarDeye mobile API is ready'}, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.route('/<path:mobile_path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def mobile_core_missing_or_method_not_allowed(mobile_path):
    normalized_path = '/' + (mobile_path or '').strip('/')
    allowed_methods = _MOBILE_CORE_ALLOWED_METHODS.get(normalized_path)
    if allowed_methods:
        return api_error(
            'Method is not allowed for this mobile API endpoint.',
            code='method_not_allowed',
            status=405,
            allowed_methods=sorted(allowed_methods),
        )
    return api_error('Mobile API endpoint was not found.', code='not_found', status=404)
