from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, current_app, g, request, session
from werkzeug.exceptions import BadRequest, UnsupportedMediaType
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import AppDevice, AppUser, MobileRefreshToken, NotificationEvent, Reading, SubscriptionPlan, SupportCase, TenantAccount, UserLoad
from ..services.energy_integrations import (
    provider_catalog,
    resolve_support_tier,
    support_tier_label,
)
from ..services.location_catalog import countries_for_template, find_country, phone_prefixes_for_template, timezones_grouped_for_template, timezones_for_template
from ..services.rbac import portal_pages, portal_page_visible, role_label
from ..services.scope import get_current_device, get_user_permissions
from ..services.security import csrf_token, sanitize_response_payload
from ..services.quota_engine import (
    quota_summary_rows,
    record_usage_for_user as _record_usage_for_user,
    track_api_call_for_user as _track_api_call_for_user,
)
from ..services.subscriptions import allowed_device_limit, compute_subscription_status, current_subscription_for_user, ensure_user_tenant_and_subscription, plan_features
from ..services.mobile_auth import user_from_bearer_or_session, verify_access_token
from ..services.api_responses import api_error, api_ok, page_meta, pagination_args
from .helpers import _upsert_setting, load_settings
from .notifications import NOTIFICATION_SECTION_FIELDS, load_notification_rules

mobile_api_bp = Blueprint('mobile_api', __name__, url_prefix='/api/v1/mobile')
mobile_core_api_bp = Blueprint('mobile_core_api', __name__, url_prefix='/api/mobile')


# v80: ── api_calls_limit centralized tracking ──────────────────────────
#
# `api_calls_limit` previously existed only in the plan catalogue / quota
# rows but had no real consumer — the card on the subscriber profile was
# decorative. v80 wires a single `before_request` hook on the
# `mobile_core_api_bp` blueprint (the `/api/mobile/*` namespace) that
# resolves the bearer user, records one usage tick on the effective
# `api_calls_limit` row, and short-circuits double-counting via a flag
# on `flask.g`. The hook is intentionally narrow:
#
#   * Only the `mobile_core_api_bp` namespace participates (`/api/mobile/*`).
#     Other API blueprints (`/api/v1/devices/*`, `/api/v1/notifications/*`,
#     `/api/v1/support/*`) live in modules outside the v80 modification
#     scope; extending coverage there is a follow-up.
#   * `OPTIONS` (CORS preflight) is never counted.
#   * Auth + health endpoints are never counted: a user can't pay quota
#     just to learn whether the service is up, and login/refresh/me
#     traffic must work even when the subscriber's quota is exhausted.
#   * Failures are swallowed; quota bookkeeping never blocks an
#     otherwise valid API request.
_API_QUOTA_SKIP_PREFIXES = (
    '/api/mobile/auth/',          # login / refresh / me / logout
)
_API_QUOTA_SKIP_PATHS = {
    '/api/mobile/health',
}


@mobile_core_api_bp.before_request
def _record_api_call_quota():
    """Record one `api_calls_limit` tick per protected request.

    Runs before every handler in `mobile_core_api_bp`. Skips auth
    + health + CORS preflight (`OPTIONS`) so subscribers can never
    be locked out of authentication by an exhausted quota. Tags
    `flask.g._v80_api_call_counted` after a successful bump so any
    re-entry inside the same request cycle doesn't double-count.
    """
    try:
        method = (request.method or '').upper()
        if method == 'OPTIONS':
            return None
        path = request.path or ''
        if path in _API_QUOTA_SKIP_PATHS:
            return None
        if any(path.startswith(p) for p in _API_QUOTA_SKIP_PREFIXES):
            return None
        # Per-request idempotency. The flag is set on the very
        # first successful bump; any later re-entry on the same
        # request is a no-op.
        if getattr(g, '_v80_api_call_counted', False):
            return None
        user = user_from_bearer_or_session()
        if user is None or getattr(user, 'is_admin', False):
            return None
        _track_api_call_for_user(user, commit=False)
        g._v80_api_call_counted = True
    except Exception:
        # Defensive: never let the tracker derail a real request.
        pass
    return None

_MOBILE_CORE_ALLOWED_METHODS = {
    '/account': {'GET', 'PATCH', 'DELETE'},
    '/account/change-password': {'POST'},
    '/account/logout-all': {'POST'},
    # v65: subscriber-initiated plan-change request. Persists as a
    # `SupportCase(case_type='plan_change_request')` — does NOT switch
    # plans immediately; the admin team triages the case.
    '/account/subscription/request-change': {'POST'},
    '/profile': {'GET', 'PATCH'},
    '/onboarding': {'GET', 'POST', 'PATCH'},
    '/location-catalog': {'GET'},
    '/device-providers': {'GET'},
    '/devices': {'GET', 'POST'},
    '/loads': {'GET', 'POST'},
    '/loads/recommendations': {'GET'},
    '/notifications': {'GET'},
    '/notifications/settings': {'GET', 'PATCH'},
    '/notifications/read-all': {'POST'},
    '/dashboard': {'GET'},
    '/dashboard/feed': {'GET'},
    '/live': {'GET'},
    '/bootstrap': {'GET'},
    '/health': {'GET'},
}

_MOBILE_DEVICE_DETAIL_ALLOWED_METHODS = {'GET', 'PATCH', 'DELETE'}
_MOBILE_DEVICE_SETUP_ALLOWED_METHODS = {'POST'}  # v49
_MOBILE_DEVICE_SYNC_NOW_ALLOWED_METHODS = {'POST'}  # v50
_MOBILE_LOAD_DETAIL_ALLOWED_METHODS = {'GET', 'PATCH', 'DELETE'}
_MOBILE_LOAD_TOGGLE_ALLOWED_METHODS = {'POST'}
_MOBILE_NOTIFICATION_READ_ALLOWED_METHODS = {'POST'}
_SAFE_DEVICE_SETTING_KEYS = {'battery_capacity_kwh', 'battery_reserve_percent'}
_MOBILE_LOAD_ALLOWED_FIELDS = {'name', 'power_w', 'wattage', 'watts', 'power', 'priority', 'device_id', 'is_enabled', 'enabled'}
_MOBILE_NOTIFICATION_CHANNEL_VALUES = {'telegram', 'sms', 'both', 'none', 'disabled', ''}
_MOBILE_ACCOUNT_ALLOWED_FIELDS = {
    'full_name',
    'email',
    'phone_country_code',
    'phone_number',
    'country',
    'country_code',
    'city',
    'timezone',
    'preferred_language',
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


def _setting_bool(value) -> bool:
    return str(value if value is not None else '').strip().lower() in {'true', '1', 'yes', 'on'}


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


def _int_or_error(value, field: str, *, minimum: int | None = None, maximum: int | None = None):
    if isinstance(value, bool):
        return None, _json_error(f'{field} must be a whole number.', code='invalid_number', field=field)
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None, _json_error(f'{field} must be a whole number.', code='invalid_number', field=field)
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
    # v45: surface the provider's readiness tier alongside the device
    # row so the mobile detail screen can render a small Arabic badge
    # without an extra round-trip to ``/api/mobile/device-providers``.
    # Resolution prefers ``device_type`` (the explicit provider code)
    # then falls back to ``api_provider`` (the legacy column). Spec
    # lookup is tolerant of unknown codes — see _resolve_device_tier.
    tier, tier_label_ar, tier_label_en = _resolve_device_tier(dev)
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
        # v45 additive — see comment above.
        'provider_support_tier': tier,
        'provider_support_tier_label': tier_label_ar,
        'provider_support_tier_label_en': tier_label_en,
    })


def _resolve_device_tier(dev):
    """Resolve a device's provider support tier for mobile payloads.
    Returns a ``(tier, label_ar, label_en)`` tuple. Tier defaults to
    ``beta-supported`` when the device's provider code is unknown
    (e.g. a legacy row whose ``device_type`` does not match any
    catalog entry). The labels never leak a raw code to the UI.
    """
    code = (getattr(dev, 'device_type', None)
            or getattr(dev, 'api_provider', None) or '').strip().lower()
    spec = next(
        (s for s in provider_catalog() if s.code == code), None,
    ) if code else None
    if spec is None:
        from ..services.energy_integrations import SUPPORT_TIER_BETA
        tier = SUPPORT_TIER_BETA
    else:
        tier = resolve_support_tier(spec)
    return (
        tier,
        support_tier_label(tier, lang='ar'),
        support_tier_label(tier, lang='en'),
    )


def _mobile_device_detail_payload(dev):
    payload = _mobile_device_payload(dev) or {}
    payload.update({
        'created_at': dev.created_at.isoformat() if dev.created_at else None,
        'updated_at': dev.updated_at.isoformat() if dev.updated_at else None,
        'auth_mode': dev.auth_mode,
        'safe_settings': {
            key: value
            for key, value in _safe_json_loads(dev.settings_json).items()
            if key in _SAFE_DEVICE_SETTING_KEYS
        },
    })
    return sanitize_response_payload(payload)


def _mobile_device_for_user(user, device_id: int):
    return AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()


def _mobile_provider_spec(value: str | None):
    provider_code = (value or 'deye').strip().lower() or 'deye'
    specs = provider_catalog()
    return next((spec for spec in specs if spec.code == provider_code), None)


def _mobile_apply_device_fields(device, user, data: dict, *, creating: bool = False):
    if 'name' in data or creating:
        name = (data.get('name') or '').strip()
        if not name:
            return _json_error('Device name is required.', code='missing_device_name', field='name')
        if len(name) > 120:
            return _json_error('Device name is too long.', code='device_name_too_long', field='name')
        device.name = name

    provider_requested = any(key in data for key in ('device_type', 'provider_code', 'provider', 'api_provider'))
    if provider_requested or creating:
        provider_code = data.get('device_type') or data.get('provider_code') or data.get('provider') or data.get('api_provider') or device.device_type or 'deye'
        spec = _mobile_provider_spec(provider_code)
        if not spec:
            return _json_error('Device provider is not supported.', code='invalid_provider', field='provider_code')
        device.device_type = spec.code
        device.api_provider = (spec.provider or spec.code).strip().lower()
        device.api_base_url = spec.base_url or device.api_base_url or None
        device.auth_mode = (spec.auth_mode or device.auth_mode or 'wizard').strip().lower()

    if 'timezone' in data:
        timezone = (data.get('timezone') or '').strip()
        if timezone and timezone not in timezones_for_template():
            return _json_error('Timezone is not supported.', code='invalid_timezone', field='timezone')
        device.timezone = timezone or user.timezone or 'Asia/Hebron'
    elif creating:
        device.timezone = device.timezone or user.timezone or 'Asia/Hebron'

    if 'plant_name' in data:
        plant_name = (data.get('plant_name') or '').strip()
        device.plant_name = plant_name[:120] or None
    elif creating:
        device.plant_name = device.plant_name or device.name

    if 'is_active' in data:
        return _json_error(
            'Device active status can only be changed through the device deactivate endpoint.',
            code='unsupported_field',
            field='is_active',
        )
    if creating:
        device.is_active = True

    settings_input = data.get('safe_settings') if isinstance(data.get('safe_settings'), dict) else {}
    settings = _safe_json_loads(device.settings_json)
    for key in _SAFE_DEVICE_SETTING_KEYS:
        if key in data and key not in settings_input:
            settings_input[key] = data.get(key)
    for key, value in settings_input.items():
        if key not in _SAFE_DEVICE_SETTING_KEYS:
            continue
        if value in (None, ''):
            settings.pop(key, None)
        else:
            if key == 'battery_capacity_kwh':
                number, error = _float_or_error(value, key, minimum=0.1, maximum=1000)
            else:
                number, error = _float_or_error(value, key, minimum=0, maximum=100)
            if error:
                return error
            settings[key] = str(number).rstrip('0').rstrip('.') if number % 1 else str(int(number))
    if settings_input:
        device.settings_json = json.dumps(settings, ensure_ascii=False)

    device.owner_user_id = user.id
    device.updated_at = datetime.utcnow()
    return None


# v49: provider setup field handling — kept parallel to the web flow
# in `devices_routes.py:_save_device_fields` so a device whose
# credentials were entered on either surface ends up in exactly the
# same shape on disk (same JSON keys in `credentials_json` /
# `settings_json`, same Deye compatibility mapping into `station_id` /
# `device_uid`). This is the single source of truth for "what does
# the sync engine read"; duplicating it would risk drift.

# Field-name patterns that classify a value as a secret. Matches the
# web flow at devices_routes.py:155.
_SECRET_FIELD_SUBSTRINGS = ('password', 'secret', 'token', 'key')
_SECRET_FIELD_NAMES = frozenset({'deye_email', 'username', 'account'})


def _is_secret_setup_field(field_name: str) -> bool:
    n = (field_name or '').strip().lower()
    if not n:
        return False
    if n in _SECRET_FIELD_NAMES:
        return True
    return any(s in n for s in _SECRET_FIELD_SUBSTRINGS)


def _mobile_apply_provider_setup(device, spec, fields_input: dict):
    """v49: persist provider credential / setup fields submitted via
    `POST /api/mobile/devices/<id>/setup` into the same backend storage
    used by the web flow.

    Mirrors `devices_routes.py:_save_device_fields` for the fields-only
    portion:
      * only keys declared in the provider spec's
        ``required_fields + optional_fields`` whitelist are accepted;
        unknown keys are silently dropped (defence against arbitrary
        credentials_json injection).
      * secret-classified keys (``password`` / ``secret`` / ``token`` /
        ``key`` substrings, or the special names
        ``deye_email`` / ``username`` / ``account``) are written into
        ``credentials_json``; non-secret keys into ``settings_json``.
      * empty / blank values are treated as "no change" — the previous
        stored value is preserved, exactly like the web flow's
        ``preserve_secret_form_value(... settings.get(field) or
        creds.get(field) or '')``.
      * Deye compatibility mappings are replicated:
        ``deye_password_or_hash → deye_password`` and
        ``deye_plant_id → station_id`` / ``deye_device_sn → device_uid``.
      * Connection status is **not** changed here — it stays at
        ``setup_required`` until a real sync flips it to ``ok`` (the
        only place that happens is the sync engine in
        ``main.py:685, 728``). This keeps the mobile UI honest.
    """
    creds = dict(_safe_json_loads(getattr(device, 'credentials_json', None)))
    settings = dict(_safe_json_loads(getattr(device, 'settings_json', None)))

    whitelist = list(spec.required_fields or ()) + list(spec.optional_fields or ())
    for field in whitelist:
        if field not in fields_input:
            continue
        raw = fields_input.get(field)
        value = str(raw).strip() if raw is not None else ''
        if not value:
            # Blank input → keep existing stored value (mirrors web's
            # preserve_secret_form_value behaviour).
            continue
        if _is_secret_setup_field(field):
            creds[field] = value
        else:
            settings[field] = value

    provider_code = (spec.code or '').strip().lower()

    # Deye-specific compatibility for the existing sync client.
    if provider_code == 'deye':
        if creds.get('deye_password_or_hash') and not creds.get('deye_password') and not creds.get('deye_password_hash'):
            creds['deye_password'] = creds['deye_password_or_hash']
        if settings.get('deye_plant_id'):
            device.station_id = settings['deye_plant_id']
        if settings.get('deye_device_sn'):
            device.device_uid = settings['deye_device_sn']
    else:
        # Generic provider compat: pull common station/device identifiers
        # from whichever spec-defined alias is populated. Same precedence
        # order as the web flow.
        device.station_id = (
            settings.get('station_id') or settings.get('site_id')
            or settings.get('system_id') or settings.get('installation_id')
            or settings.get('powerstation_id') or device.station_id
        )
        device.device_uid = (
            settings.get('device_uid') or settings.get('device_sn')
            or settings.get('inverter_sn') or settings.get('serial_number')
            or settings.get('device_id') or device.device_uid
        )
        device.external_device_id = (
            settings.get('external_device_id') or settings.get('entity_id')
            or settings.get('energy_site_id') or device.external_device_id
        )

    # Keep provider metadata mirrored into settings_json the same way
    # the web flow does. Useful for the sync engine and audit trails.
    settings.update({
        'provider_code': provider_code,
        'provider_name': spec.name,
        'api_provider': device.api_provider or provider_code,
        'api_base_url': device.api_base_url or (spec.base_url or ''),
        'auth_mode': device.auth_mode or spec.auth_mode,
        'timezone': device.timezone or settings.get('timezone', ''),
    })

    device.credentials_json = json.dumps(creds, ensure_ascii=False)
    device.settings_json = json.dumps(settings, ensure_ascii=False)
    device.updated_at = datetime.utcnow()


def _mobile_load_payload(load: UserLoad) -> dict:
    return sanitize_response_payload({
        'id': load.id,
        'name': load.name,
        'power_w': float(load.power_w or 0),
        'priority': int(load.priority or 1),
        'is_enabled': bool(load.is_enabled),
        'device_id': load.device_id,
        'created_at': load.created_at.isoformat() if load.created_at else None,
        'control_type': 'persisted_preference',
        'execution_note': 'Toggling a load only changes the saved preference. It does not send commands to an inverter, relay, scheduler, or hardware device.',
    })


def _mobile_load_device_from_payload(user, data: dict, *, required: bool = False):
    raw_device_id = data.get('device_id')
    if raw_device_id in (None, ''):
        if not required:
            return None, None
        selected = _selected_device_for_user(user)
        if selected:
            return selected, None
        return None, _json_error('A target device is required before creating a load.', code='device_required', field='device_id')
    try:
        device_id = int(str(raw_device_id).strip())
    except (TypeError, ValueError):
        return None, _json_error('Device id is invalid.', code='invalid_device_id', field='device_id')
    device = AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()
    if not device:
        return None, api_error('Device was not found for this account.', code='device_not_found', status=404)
    return device, None


def _mobile_loads_query(user):
    query = UserLoad.query.filter_by(user_id=user.id)
    raw_device_id = (request.args.get('device_id') or request.args.get('device') or '').strip()
    if not raw_device_id or raw_device_id.lower() == 'all':
        return query, None, None
    try:
        device_id = int(raw_device_id)
    except (TypeError, ValueError):
        return None, None, api_error('Device id is invalid.', code='invalid_device_id', status=400)
    device = AppDevice.query.filter_by(id=device_id, owner_user_id=user.id).first()
    if not device:
        return None, None, api_error('Device was not found for this account.', code='device_not_found', status=404)
    return query.filter_by(device_id=device.id), device, None


def _mobile_load_for_user(user, load_id: int):
    return UserLoad.query.filter_by(id=load_id, user_id=user.id).first()


def _mobile_validate_load_fields(data: dict):
    for key in data:
        if key not in _MOBILE_LOAD_ALLOWED_FIELDS:
            return _json_error('Load field is not supported by the mobile API.', code='unsupported_field', field=key)
    return None


def _mobile_load_power_value(data: dict):
    for key in ('power_w', 'wattage', 'watts', 'power'):
        if key in data:
            return data.get(key), key
    return None, 'power_w'


def _mobile_apply_load_fields(load: UserLoad, user, data: dict, *, creating: bool = False):
    error = _mobile_validate_load_fields(data)
    if error:
        return error

    if creating or 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return _json_error('Load name is required.', code='missing_load_name', field='name')
        if len(name) > 120:
            return _json_error('Load name is too long.', code='load_name_too_long', field='name')
        load.name = name

    if creating or any(key in data for key in ('power_w', 'wattage', 'watts', 'power')):
        raw_power, power_field = _mobile_load_power_value(data)
        power_w, error = _float_or_error(raw_power, power_field, minimum=0.1, maximum=100000)
        if error:
            return error
        load.power_w = power_w

    if 'priority' in data:
        priority, error = _int_or_error(data.get('priority'), 'priority', minimum=1, maximum=100)
        if error:
            return error
        load.priority = priority
    elif creating:
        load.priority = 1

    if 'is_enabled' in data or 'enabled' in data:
        parsed, error = _boolean_or_error(data.get('is_enabled') if 'is_enabled' in data else data.get('enabled'), 'is_enabled')
        if error:
            return error
        load.is_enabled = parsed
    elif creating:
        load.is_enabled = True

    if creating or 'device_id' in data:
        device, error = _mobile_load_device_from_payload(user, data, required=creating)
        if error:
            return error
        if device is not None:
            load.device_id = device.id

    load.user_id = user.id
    return None


def _mobile_notification_allowed_setting_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for section, config in NOTIFICATION_SECTION_FIELDS.items():
        for key in config.get('text', []):
            keys[key] = 'text'
        for key in config.get('checkbox', []):
            keys[key] = 'checkbox'
    return keys


def _mobile_notification_sections_payload(settings: dict) -> dict:
    allowed = _mobile_notification_allowed_setting_keys()
    sections: dict[str, dict] = {}
    for section, config in NOTIFICATION_SECTION_FIELDS.items():
        section_keys = list(config.get('text', [])) + list(config.get('checkbox', []))
        sections[section] = {
            'settings': {
                key: _setting_bool(settings.get(key)) if allowed.get(key) == 'checkbox' else (settings.get(key) or '')
                for key in section_keys
            },
            'editable': True,
        }
    return sections


def _mobile_channels_status(settings: dict) -> dict:
    telegram_token = bool((settings.get('telegram_bot_token') or '').strip())
    telegram_chat = bool((settings.get('telegram_chat_id') or '').strip())
    sms_url = bool((settings.get('sms_api_url') or '').strip())
    sms_key = bool((settings.get('sms_api_key') or '').strip())
    sms_recipients = bool((settings.get('sms_recipients') or '').strip())
    return {
        'telegram': {
            'enabled': _setting_bool(settings.get('telegram_enabled')),
            'configured': telegram_token and telegram_chat,
            'has_bot_token': telegram_token,
            'has_chat_id': telegram_chat,
            'api_url_configured': bool((settings.get('telegram_api_url') or '').strip()),
        },
        'sms': {
            'enabled': _setting_bool(settings.get('sms_enabled')),
            'configured': sms_url and sms_key and sms_recipients,
            'has_api_url': sms_url,
            'has_api_key': sms_key,
            'has_recipients': sms_recipients,
            'sender_configured': bool((settings.get('sms_sender') or '').strip()),
        },
    }


def _mobile_notification_settings_payload() -> dict:
    settings = load_settings()
    return sanitize_response_payload({
        'scope': 'global',
        'scope_note': 'Notification settings are currently global for the account/platform. Per-device notification rules are not enabled by the current database schema.',
        'channels': _mobile_channels_status(settings),
        'sections': _mobile_notification_sections_payload(settings),
        'rules': _mobile_notification_rules_payload(settings),
        'supported_channel_values': ['telegram', 'sms', 'both', 'none'],
        'read_only': False,
    })


def _mobile_notification_rules_payload(settings: dict) -> dict:
    rules = load_notification_rules(settings)
    cleaned = {'charge': {}, 'discharge': {}, 'night_thresholds': {}, 'day_deficit': {}}
    for group in ('charge', 'discharge', 'night_thresholds'):
        values = rules.get(group) if isinstance(rules.get(group), dict) else {}
        for level, channel in values.items():
            normalized, _error = _mobile_normalize_channel(channel, f'rules.{group}.{level}')
            if normalized:
                cleaned[group][str(level)] = normalized
    day_deficit = rules.get('day_deficit') if isinstance(rules.get('day_deficit'), dict) else {}
    enabled_raw = day_deficit.get('enabled', True)
    cleaned['day_deficit'] = {
        'enabled': enabled_raw if isinstance(enabled_raw, bool) else _setting_bool(enabled_raw),
        'channel': _mobile_normalize_channel(day_deficit.get('channel', 'telegram'), 'rules.day_deficit.channel')[0] or 'telegram',
    }
    return cleaned


def _mobile_normalize_channel(value, field: str):
    normalized = str(value or '').strip().lower()
    if normalized == 'disabled':
        normalized = 'none'
    if normalized not in _MOBILE_NOTIFICATION_CHANNEL_VALUES:
        return None, _json_error('Notification channel value is not supported.', code='invalid_channel', field=field)
    return normalized or 'none', None


def _mobile_normalize_threshold_key(group: str, raw_key):
    field = f'rules.{group}.{raw_key}'
    if isinstance(raw_key, bool):
        return None, _json_error('Notification threshold must be a whole number.', code='invalid_threshold', field=field)
    raw_text = str(raw_key).strip()
    if not raw_text:
        return None, _json_error('Notification threshold is required.', code='invalid_threshold', field=f'rules.{group}')
    try:
        threshold = int(raw_text)
    except (TypeError, ValueError):
        return None, _json_error('Notification threshold must be a whole number.', code='invalid_threshold', field=field)
    if str(threshold) != raw_text:
        return None, _json_error('Notification threshold must be a whole number.', code='invalid_threshold', field=field)
    if group in {'charge', 'discharge'} and not (0 <= threshold <= 100):
        return None, _json_error('Notification percentage threshold must be between 0 and 100.', code='invalid_threshold', field=field)
    if group == 'night_thresholds' and threshold < 0:
        return None, _json_error('Night load threshold must be zero or higher.', code='invalid_threshold', field=field)
    return str(threshold), None


def _mobile_validate_notification_rules(raw_rules):
    if raw_rules is None:
        return None, None
    if not isinstance(raw_rules, dict):
        return None, _json_error('Notification rules must be a JSON object.', code='invalid_rules', field='rules')
    current = load_notification_rules(load_settings())
    allowed_groups = {'charge', 'discharge', 'night_thresholds', 'day_deficit'}
    for group, value in raw_rules.items():
        if group not in allowed_groups:
            return None, _json_error('Notification rule group is not supported.', code='unsupported_field', field=f'rules.{group}')
        if not isinstance(value, dict):
            return None, _json_error('Notification rule group must be a JSON object.', code='invalid_rules', field=f'rules.{group}')
        if group in {'charge', 'discharge', 'night_thresholds'}:
            target = dict(current.get(group) or {})
            for level, channel in value.items():
                level_key, error = _mobile_normalize_threshold_key(group, level)
                if error:
                    return None, error
                normalized, error = _mobile_normalize_channel(channel, f'rules.{group}.{level_key}')
                if error:
                    return None, error
                target[level_key] = normalized
            current[group] = target
        else:
            target = dict(current.get('day_deficit') or {})
            for key, incoming in value.items():
                if key == 'enabled':
                    parsed, error = _boolean_or_error(incoming, 'rules.day_deficit.enabled')
                    if error:
                        return None, error
                    target['enabled'] = parsed
                elif key == 'channel':
                    normalized, error = _mobile_normalize_channel(incoming, 'rules.day_deficit.channel')
                    if error:
                        return None, error
                    target['channel'] = normalized
                else:
                    return None, _json_error('Notification rule field is not supported.', code='unsupported_field', field=f'rules.day_deficit.{key}')
            current['day_deficit'] = target
    return current, None


def _mobile_notification_event_query(user):
    return NotificationEvent.query.filter_by(target_user_id=user.id)


def _parse_event_structured_payload(raw):
    """v44 phase 1a — parse the JSON string stored in
    ``NotificationEvent.result`` into a plain ``dict``, or return
    ``None`` when the column is empty or holds anything that is not
    a JSON object. Mobile clients that don't understand the payload
    simply ignore it; older rows without a payload keep returning
    ``None`` here so the API contract stays additive."""
    if raw is None:
        return None
    text = raw if isinstance(raw, str) else str(raw)
    if not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _mobile_notification_event_payload(event: NotificationEvent) -> dict:
    return sanitize_response_payload({
        'id': event.id,
        'event_type': event.event_type,
        'source_type': event.source_type,
        'source_id': event.source_id,
        'title': event.title,
        'message': event.message,
        'url': event.direct_url,
        'status': event.status,
        'is_read': bool(event.is_read),
        'appeared_in_bell': bool(event.appeared_in_bell),
        'delivered_to_user': bool(event.delivered_to_user),
        'created_at': event.created_at.isoformat() if event.created_at else None,
        'read_at': event.read_at.isoformat() if event.read_at else None,
        # v44 phase 1a: optional structured echo. ``None`` for legacy
        # rows and live events that don't carry one yet.
        'payload': _parse_event_structured_payload(event.result),
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


def _account_capabilities_payload():
    return {
        'profile_update': True,
        'password_change': True,
        'logout_all_refresh_tokens': True,
        'account_deletion': False,
        # v65: subscriber can submit a plan-change request through the
        # mobile API. The action is persisted as a SupportCase (admin
        # triage required); it does NOT switch plans immediately.
        'plan_change_request': True,
        'mobile_api_sections': [
            'auth',
            'profile',
            'onboarding',
            'dashboard',
            'devices',
            'loads',
            'notifications',
            'support',
            'account',
        ],
    }


# v65: ── Plan-change request helpers ─────────────────────────────────
#
# Two additive surfaces on top of the existing account payload:
#   * `available_plans`            — every active plan the user could
#                                    request, marked with `is_current`.
#   * `pending_plan_change_request` — best-effort projection of the
#                                    user's most recent `open`
#                                    SupportCase(case_type=
#                                    'plan_change_request').
#
# We mirror the exact subject convention used by the web flow in
# `billing.account_subscription_request_change` so admins continue to
# see a single, consistent triage queue regardless of submission
# channel. The plan_id is recovered best-effort by matching the
# extracted name against `name_ar` / `name_en` / `code`.

# Subject prefix from `billing.py:401` — kept in sync verbatim.
_PLAN_CHANGE_SUBJECT_PREFIX = 'طلب تغيير الخطة إلى '

# Separators the web flow has used to glue the optional user message
# onto the subject. The em-dash (U+2014) is the canonical one; we
# also accept a plain hyphen for forward-compat if the convention
# ever drifts.
_PLAN_CHANGE_SUBJECT_SEPARATORS = (' — ', ' - ')


def _parse_plan_change_subject(subject: str | None) -> tuple[str, str | None]:
    """Return `(requested_plan_name, message)` parsed from a
    SupportCase subject of the form

        'طلب تغيير الخطة إلى <plan_name>' + (' — <message>')?

    When the subject doesn't match the prefix the whole string is
    surfaced as the requested name (never crashes on legacy data).
    """
    s = (subject or '').strip()
    if not s:
        return '', None
    if not s.startswith(_PLAN_CHANGE_SUBJECT_PREFIX):
        return s, None
    rest = s[len(_PLAN_CHANGE_SUBJECT_PREFIX):].strip()
    for sep in _PLAN_CHANGE_SUBJECT_SEPARATORS:
        if sep in rest:
            name, _, msg = rest.partition(sep)
            cleaned_msg = msg.strip()
            return name.strip(), (cleaned_msg or None)
    return rest, None


def _resolve_plan_id_by_name(name: str | None) -> int | None:
    """Best-effort plan_id lookup. Matches `name_ar` first (the web
    flow's preferred display name), then `name_en`, then `code`.
    Returns `None` when no plan matches — the mobile UI then renders
    only the textual `requested_plan_name`."""
    if not name:
        return None
    target = (
        SubscriptionPlan.query
        .filter(
            (SubscriptionPlan.name_ar == name)
            | (SubscriptionPlan.name_en == name)
            | (SubscriptionPlan.code == name)
        )
        .first()
    )
    return getattr(target, 'id', None)


def _available_plans_payload(user):
    """List every active plan the subscriber could pick. Adds an
    `is_current` flag so the mobile screen can dim / mark the current
    plan in place. Empty list when no active plans exist (defensive)."""
    tenant = (
        TenantAccount.query.get(user.tenant_id)
        if getattr(user, 'tenant_id', None) else None
    )
    current_plan_id = getattr(tenant, 'plan_id', None)
    rows = (
        SubscriptionPlan.query
        .filter_by(is_active=True)
        .order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc())
        .all()
    )
    items = []
    for plan in rows:
        items.append({
            'id': plan.id,
            'code': plan.code,
            'name_ar': plan.name_ar,
            'name_en': plan.name_en,
            'price': plan.price,
            'currency': plan.currency,
            'max_devices': plan.max_devices,
            'features': plan_features(plan),
            'is_current': bool(current_plan_id) and plan.id == current_plan_id,
        })
    return items


def _pending_plan_change_request_payload(user):
    """Most recent `open` plan-change request for this user, or
    `None` when nothing pending. Surface mirrors what the web
    `account_subscription` template renders so admin + subscriber
    both read the same case."""
    case = (
        SupportCase.query
        .filter_by(
            user_id=user.id,
            case_type='plan_change_request',
            status='open',
        )
        .order_by(SupportCase.created_at.desc())
        .first()
    )
    if case is None:
        return None
    requested_name, message = _parse_plan_change_subject(getattr(case, 'subject', ''))
    return {
        'id': case.id,
        'status': case.status,
        'requested_plan_id': _resolve_plan_id_by_name(requested_name),
        'requested_plan_name': requested_name,
        'message': message,
        'created_at': case.created_at.isoformat() if case.created_at else None,
    }


# v76: ── Subscriber quota visibility helpers ────────────────────────
#
# Read-only projection of `quota_summary_rows(tenant_id, lang)` into a
# mobile-friendly shape. We never re-compute quota math on the mobile
# side — the backend `quota_summary_rows` helper is the single source
# of truth for limit / used / remaining / percent / unlimited.
#
# The raw helper returns the `TenantQuota` model row under the
# `'quota'` key alongside the derived display fields. We strip that
# model reference so internal columns (notes, source_plan_id,
# created_at, etc.) never leak to the mobile client.


def _mobile_quotas_payload(user):
    """Return the subscriber-visible quota rows for the user's tenant.

    Empty list when the user has no tenant (defensive — every active
    subscriber should, but a fresh registration can land here briefly).
    Empty list when the tenant carries no quota rows yet.

    Field shape per row (mobile contract):
      * `key`           — `quota_key`, stable machine code (e.g.
                          `support_cases_limit`).
      * `label`         — Arabic display label.
      * `description`   — Arabic short description (may be empty).
      * `limit`         — float; 0 when undefined.
      * `used`          — float; 0 when none consumed.
      * `remaining`     — float; `None` for unlimited quotas (the
                          web helper uses `'∞'` for those — mobile
                          gets the cleaner null/`is_unlimited` pair).
      * `percent`       — float 0..100; 0 for unlimited.
      * `is_unlimited`  — bool.
      * `reset_period`  — string (`'monthly'` / `'manual'` / etc.).
      * `status`        — string (`'active'` / `'inactive'` / etc.).
      * `source_label`  — Arabic phrase (e.g. "من الخطة").
    """
    tenant_id = getattr(user, 'tenant_id', None)
    if not tenant_id:
        return []
    lang = _lang()
    items = []
    for row in quota_summary_rows(tenant_id, lang):
        q = row.get('quota')
        if q is None:
            continue
        unlimited = bool(row.get('is_unlimited'))
        raw_remaining = row.get('remaining')
        # `quota_summary_rows` puts the literal '∞' string in
        # `remaining` for unlimited quotas; mobile gets `null` +
        # the bool flag instead so the parser never has to handle
        # mixed types on one key.
        remaining_value = None if unlimited else float(raw_remaining or 0)
        items.append({
            'key': (getattr(q, 'quota_key', '') or '').strip(),
            'label': (row.get('label') or '').strip(),
            'description': (row.get('description') or '').strip(),
            'limit': float(row.get('limit', 0) or 0),
            'used': float(row.get('used', 0) or 0),
            'remaining': remaining_value,
            'percent': float(row.get('percent', 0) or 0),
            'is_unlimited': unlimited,
            'reset_period': (getattr(q, 'reset_period', '') or '').strip(),
            'status': (getattr(q, 'status', '') or '').strip(),
            'source_label': (row.get('source_label') or '').strip(),
        })
    return items


def _account_payload(user):
    devices = _device_summary_payload(user)
    return {
        'user': _profile_payload(user),
        'role': {
            'code': user.role,
            'label': role_label(user.role, _lang()),
            'is_admin': bool(user.is_admin),
        },
        'subscription': _subscription_payload(user),
        'devices': {
            'total': devices.get('total', 0),
            'active': devices.get('active', 0),
            'selected_device_id': devices.get('selected_device_id'),
        },
        'capabilities': _account_capabilities_payload(),
        # v65: additive — never `None` (empty list when no plans).
        'available_plans': _available_plans_payload(user),
        # v65: additive — `None` when no `open` plan-change request.
        'pending_plan_change_request':
            _pending_plan_change_request_payload(user),
        # v76: additive — subscriber quota visibility. Always a list
        # (empty when no tenant or no rows). Backwards-compatible
        # for older mobile clients that ignore unknown keys.
        'quotas': _mobile_quotas_payload(user),
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
        tier = resolve_support_tier(spec)
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
            # v45 additive: structured readiness tier + polished
            # Arabic / English visible labels. Older mobile clients
            # ignore unknown keys.
            'support_tier': tier,
            'support_tier_label': support_tier_label(tier, lang='ar'),
            'support_tier_label_en': support_tier_label(tier, lang='en'),
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


def _apply_mobile_profile_fields(user, data):
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

    return None


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

    error = _apply_mobile_profile_fields(user, data)
    if error:
        return error

    db.session.commit()
    return api_ok({
        'user': _profile_payload(user),
        'onboarding': _onboarding_payload(user),
        'subscription': _subscription_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/account')
def mobile_account_get():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_ok(_account_payload(user), meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.patch('/account')
def mobile_account_update():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    for key in data:
        if key not in _MOBILE_ACCOUNT_ALLOWED_FIELDS:
            return _json_error('Account field is not supported by the mobile API.', code='unsupported_field', field=key)

    error = _apply_mobile_profile_fields(user, data)
    if error:
        return error

    db.session.commit()
    return api_ok(_account_payload(user), meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/account/change-password')
def mobile_account_change_password():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    current_password = data.get('current_password')
    new_password = data.get('new_password')
    if not isinstance(current_password, str) or not current_password:
        return _json_error('Current password is required.', code='missing_field', field='current_password')
    if not isinstance(new_password, str) or not new_password:
        return _json_error('New password is required.', code='missing_field', field='new_password')
    if not check_password_hash(user.password_hash or '', current_password):
        return _json_error('Current password is incorrect.', code='invalid_current_password', status=401, field='current_password')
    if len(new_password) < 6:
        return _json_error('New password must be at least 6 characters.', code='weak_password', field='new_password')

    user.password_hash = generate_password_hash(new_password)
    user.updated_at = datetime.utcnow()
    db.session.commit()
    return api_ok({'changed': True}, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/account/logout-all')
def mobile_account_logout_all():
    user, err = _require_bearer_user()
    if err:
        return err
    _, error = _strict_json_object()
    if error:
        return error

    now = datetime.utcnow()
    revoked_count = (
        MobileRefreshToken.query
        .filter(MobileRefreshToken.user_id == user.id, MobileRefreshToken.revoked_at.is_(None))
        .update({'revoked_at': now}, synchronize_session=False)
    )
    db.session.commit()
    return api_ok({
        'supported': True,
        'revoked_refresh_tokens': int(revoked_count or 0),
        'access_tokens_revoked': False,
        'access_token_note': 'Access tokens are stateless and expire automatically.',
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.delete('/account')
def mobile_account_delete():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_error(
        'Account deletion is not supported by the mobile API.',
        code='account_deletion_not_supported',
        status=501,
        supported=False,
    )


@mobile_core_api_bp.post('/account/subscription/request-change')
def mobile_account_request_plan_change():
    """v65 — subscriber-initiated plan-change request.

    Mirrors the web `billing.account_subscription_request_change`
    flow verbatim: persists the request as a `SupportCase` row
    (`case_type='plan_change_request'`, `status='open'`) and cancels
    any prior open request for the same user. **Does NOT switch
    plans immediately** — admins triage the case through the
    existing support workflow.

    Request body:
      * `plan_id`  (int, **required**) — target plan id; must be
                                          active. Bad / missing →
                                          `400 plan_id_required` /
                                          `400 plan_id_invalid` /
                                          `404 plan_not_found`.
      * `message`  (str, **optional**)  — short user note. Capped
                                          server-side at 240 chars
                                          and appended to the case
                                          subject behind ' — ' so
                                          the existing admin queue
                                          renders unchanged.

    Returns the refreshed `_account_payload(user)` — the mobile
    client updates the Account screen in-place, no second GET.
    """
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    raw_plan_id = data.get('plan_id')
    if raw_plan_id is None or (isinstance(raw_plan_id, str) and not raw_plan_id.strip()):
        return _json_error(
            'Plan id is required.',
            code='plan_id_required',
            field='plan_id',
        )
    try:
        plan_id = int(raw_plan_id)
    except (TypeError, ValueError):
        return _json_error(
            'Plan id must be an integer.',
            code='plan_id_invalid',
            field='plan_id',
        )

    target_plan = SubscriptionPlan.query.get(plan_id)
    if target_plan is None or not target_plan.is_active:
        return _json_error(
            'Subscription plan was not found or is not active.',
            code='plan_not_found',
            status=404,
            field='plan_id',
        )

    raw_message = data.get('message')
    message = (raw_message or '').strip() if isinstance(raw_message, str) else ''
    if len(message) > 240:
        message = message[:240]

    # Same cancel-then-create pattern as `billing.account_subscription_request_change`.
    SupportCase.query.filter_by(
        user_id=user.id,
        case_type='plan_change_request',
        status='open',
    ).update({'status': 'cancelled'})

    tenant, _ = ensure_user_tenant_and_subscription(
        user, activated_by_user_id=user.id,
    )
    plan_name = target_plan.name_ar or target_plan.name_en or target_plan.code
    # Exact subject convention from `billing.py:401` — admin queue
    # must continue to read both submission paths identically.
    subject = f'{_PLAN_CHANGE_SUBJECT_PREFIX}{plan_name}'
    if message:
        subject = f'{subject} — {message}'

    case = SupportCase(
        case_type='plan_change_request',
        source_id=user.id,
        tenant_id=getattr(tenant, 'id', None),
        user_id=user.id,
        subject=subject,
        priority='normal',
        status='open',
    )
    db.session.add(case)
    db.session.flush()
    # v86: mobile parity with web. The web subscriber path
    # (`billing.account_subscription_request_change` → preview →
    # confirm) routes through `notify_admins_of_plan_change_request`
    # so every active admin sees the new request in their bell +
    # notification center. The mobile path historically skipped
    # this — admins were blind to mobile submissions. v86 closes
    # that gap. Wrapped defensively so a notification failure can
    # never block the subscriber's submission.
    try:
        from ..services.support_ops import notify_admins_of_plan_change_request
        notify_admins_of_plan_change_request(
            case, requester=user, target_plan=target_plan, commit=False,
        )
    except Exception:
        current_app.logger.exception(
            'mobile_plan_change_request admin notify failed'
        )
    db.session.commit()

    return api_ok(
        _account_payload(user),
        meta={'api_version': 'v1', 'namespace': 'api/mobile'},
        status=201,
    )


# v87 — mobile-native plan-change preview/confirm endpoints.
# Keeps the backend contract clean for future mobile UI parity. The
# web flow already supports JSON output, but a dedicated mobile
# namespace gives clients a stable, named endpoint without forcing
# them to negotiate Accept headers against a web route.

@mobile_core_api_bp.get('/account/plan-change/preview')
def mobile_account_plan_change_preview():
    """Return both scenarios + the v87 policy classification for a
    selected target plan.

    Query string:
      * `plan_id` (int, required)

    Response body mirrors `subscriber_plan_change.PreviewResult` —
    in particular the top-level `policy_kind` plus per-scenario
    `is_eligible`, `is_recommended`, `eligibility_reason`. The mobile
    client must branch on `policy_kind`:

      * `downgrade` → only render the `reduced_days` card; the
        `same_duration` card has `is_eligible=False` with
        `eligibility_reason='downgrade_no_refund_policy'` and MUST
        NOT be offered as a CTA.
      * `upgrade`   → both eligible; offer A=same_duration (pay diff)
                      and B=reduced_days (fewer days, no payment).
      * `lateral`   → same_duration is the primary path.
    """
    user, err = _require_bearer_user()
    if err:
        return err
    raw_plan_id = request.args.get('plan_id', '').strip()
    if not raw_plan_id:
        return _json_error(
            'Plan id is required.', code='plan_id_required',
            field='plan_id',
        )
    try:
        plan_id = int(raw_plan_id)
    except (TypeError, ValueError):
        return _json_error(
            'Plan id must be an integer.', code='plan_id_invalid',
            field='plan_id',
        )
    from ..services.subscriber_plan_change import preview as _preview
    result = _preview(user, plan_id)
    return api_ok(
        result.to_dict(),
        meta={'api_version': 'v1', 'namespace': 'api/mobile'},
    )


@mobile_core_api_bp.post('/account/plan-change/confirm')
def mobile_account_plan_change_confirm():
    """Commit to a scenario from a mobile client.

    Body (JSON object):
      * `plan_id`              (int,  required) — target plan
      * `mode`                 (str,  required) — 'same_duration' or
                                                  'reduced_days'
      * `desired_target_days`  (int,  optional) — admin-style override
                                                  (mobile UI does NOT
                                                  expose this; reserved
                                                  for future)

    Response on success: `{ ok: true, data: ConfirmResult.to_dict() }`.
    On a v87 policy refusal (downgrade same_duration) the response
    is `400` with `data.outcome == 'blocked'` and
    `data.blocked_reason == 'downgrade_same_duration_not_allowed'`.
    """
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error
    raw_plan_id = data.get('plan_id')
    if raw_plan_id is None:
        return _json_error(
            'Plan id is required.', code='plan_id_required',
            field='plan_id',
        )
    try:
        plan_id = int(raw_plan_id)
    except (TypeError, ValueError):
        return _json_error(
            'Plan id must be an integer.', code='plan_id_invalid',
            field='plan_id',
        )
    mode = (data.get('mode') or '').strip()
    if mode not in ('same_duration', 'reduced_days'):
        return _json_error(
            'Unknown pricing mode.', code='unknown_mode', field='mode',
        )
    desired_days = data.get('desired_target_days')
    if desired_days is not None:
        try:
            desired_days = int(desired_days)
        except (TypeError, ValueError):
            return _json_error(
                'desired_target_days must be an integer.',
                code='desired_target_days_invalid',
                field='desired_target_days',
            )
    from ..services.subscriber_plan_change import confirm as _confirm
    result = _confirm(
        user, plan_id, mode=mode, desired_target_days=desired_days,
        commit=True,
    )
    payload = result.to_dict()
    if result.outcome == 'blocked':
        return api_error(
            payload.get('blocked_reason') or 'Plan change blocked.',
            code=payload.get('blocked_reason') or 'blocked',
            status=400,
            data=payload,
        )
    return api_ok(
        payload,
        meta={'api_version': 'v1', 'namespace': 'api/mobile'},
    )


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


@mobile_core_api_bp.get('/devices')
def mobile_devices_list():
    user, err = _require_bearer_user()
    if err:
        return err
    devices = _mobile_owned_devices(user)
    return api_ok({
        'items': [_mobile_device_payload(device) for device in devices],
        'total': len(devices),
        'active': len([device for device in devices if device.is_active]),
        'selected_device_id': user.preferred_device_id,
        'max_devices': allowed_device_limit(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/devices')
def mobile_device_create():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    active_count = AppDevice.query.filter_by(owner_user_id=user.id, is_active=True).count()
    max_devices = allowed_device_limit(user)
    if max_devices <= 0 or active_count >= max_devices:
        return api_error(
            'Device limit has been reached for this account.',
            code='device_limit_reached',
            status=403,
            max_devices=max_devices,
            active_devices=active_count,
        )

    device = AppDevice(
        owner_user_id=user.id,
        tenant_id=getattr(user, 'tenant_id', None),
        connection_status='setup_required',
    )
    error = _mobile_apply_device_fields(device, user, data, creating=True)
    if error:
        return error
    db.session.add(device)
    db.session.flush()
    if not user.preferred_device_id:
        user.preferred_device_id = device.id
        user.preferred_device_type = device.device_type or user.preferred_device_type
    # v80: increment `devices_limit` usage on real device creation.
    # This is a usage-flow counter — `allowed_device_limit(user)` is
    # the canonical stock-based ceiling and stays unchanged. We use
    # `record_usage_for_user(...)` rather than the gated
    # `consume_quota_for_user(...)` so the counter keeps climbing
    # truthfully past the soft limit (the hard ceiling already
    # blocked anything that would actually be over-stock). Never
    # raises; never blocks the create on a quota bookkeeping error.
    _record_usage_for_user(user, 'devices_limit', 1, commit=False)
    db.session.commit()
    return api_ok({
        'device': _mobile_device_detail_payload(device),
        'devices': _device_summary_payload(user),
    }, status=201, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/devices/<int:device_id>')
def mobile_device_detail(device_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    device = _mobile_device_for_user(user, device_id)
    if not device:
        return api_error('Device was not found for this account.', code='device_not_found', status=404)
    latest = (
        Reading.query
        .filter_by(device_id=device.id)
        .order_by(Reading.created_at.desc(), Reading.id.desc())
        .first()
    )
    return api_ok({
        'device': _mobile_device_detail_payload(device),
        'latest': _mobile_reading_payload(latest),
        'cards': _mobile_reading_cards(latest),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.patch('/devices/<int:device_id>')
def mobile_device_update(device_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error
    device = _mobile_device_for_user(user, device_id)
    if not device:
        return api_error('Device was not found for this account.', code='device_not_found', status=404)
    error = _mobile_apply_device_fields(device, user, data)
    if error:
        return error
    if device.is_active and not user.preferred_device_id:
        user.preferred_device_id = device.id
        user.preferred_device_type = device.device_type or user.preferred_device_type
    db.session.commit()
    return api_ok({
        'device': _mobile_device_detail_payload(device),
        'devices': _device_summary_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/devices/<int:device_id>/setup')
def mobile_device_setup(device_id: int):
    """v49: subscriber-facing provider setup endpoint.

    Request body:
        {"fields": {"<provider_field_name>": "<value>", ...}}

    Behaviour:
      * Whitelisted against the device's provider spec — unknown keys
        are silently dropped (no arbitrary credentials_json injection).
      * Secret-classified keys go to ``credentials_json``, others to
        ``settings_json`` — identical shape to what the web
        ``/devices/manage/<id>/edit`` flow produces.
      * Empty values are treated as "no change"; never null out an
        existing stored credential by submitting a blank field.
      * Connection status is **not** changed; only a real sync can
        promote a device from ``setup_required`` to ``ok``.
      * Returns the updated device detail payload so the mobile can
        refresh in one round-trip.
    """
    user, err = _require_bearer_user()
    if err:
        return err
    device = _mobile_device_for_user(user, device_id)
    if not device:
        return api_error('Device was not found for this account.', code='device_not_found', status=404)

    data, error = _strict_json_object()
    if error:
        return error

    spec = _mobile_provider_spec(device.device_type)
    if not spec:
        return api_error('Device provider is not supported.', code='invalid_provider', status=400)

    raw_fields = data.get('fields')
    if raw_fields is None:
        # Tolerant fallback: callers may post the field values at the
        # top level. Filter out the always-present envelope keys.
        raw_fields = {k: v for k, v in data.items() if k != 'fields'}
    if not isinstance(raw_fields, dict):
        return _json_error('`fields` must be a JSON object.', code='invalid_fields', field='fields')

    _mobile_apply_provider_setup(device, spec, raw_fields)
    db.session.commit()

    return api_ok({
        'device': _mobile_device_detail_payload(device),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


def _mobile_sync_error_payload(exc: Exception) -> tuple[int, str, str]:
    """v50: classify a `sync_now_internal` failure into a tuple of
    `(http_status, error_code, user_message)` so the mobile UI can
    surface honest copy without inspecting backend exception types.

    Two distinct cases:
      * ``ValueError`` is raised by ``_device_sync_ready`` when the
        device is inactive or missing required credentials — that's a
        "setup not complete yet" condition. Returns 400 +
        ``setup_not_ready`` + the readiness message.
      * Anything else (provider auth failure, network error, vendor
        API outage, etc.) is a real sync attempt that failed. Returns
        502 + ``sync_failed`` + the exception's string form, trimmed
        so we never leak a stack trace into a notification banner.
    """
    if isinstance(exc, ValueError):
        return 400, 'setup_not_ready', str(exc) or 'تعذّر التحقق من جاهزية الجهاز.'
    raw = str(exc).strip() or 'فشلت محاولة المزامنة.'
    # Cap the message length so a verbose third-party exception doesn't
    # blow up the mobile snack-bar copy.
    return 502, 'sync_failed', raw[:240]


@mobile_core_api_bp.post('/devices/<int:device_id>/sync-now')
def mobile_device_sync_now(device_id: int):
    """v50: subscriber-facing "verify integration now" action.

    Reuses ``main.sync_now_internal(trigger='manual')`` so:
      * exactly the same readiness gating runs (`_device_sync_ready`
        rejects inactive devices + missing credentials);
      * exactly the same provider client runs (Deye client for `deye`,
        `fetch_snapshot_for_device` for everything else);
      * exactly the same persistence happens (a real `Reading` row,
        `connection_status = 'ok'`, `last_connected_at = utcnow()`),
        plus the existing notification / smart-event side-effects.

    The endpoint temporarily binds the target device into Flask's
    request ``g`` so the legacy ``get_current_device()`` /
    ``get_current_user()`` helpers used by ``sync_now_internal`` pick
    up the right scope — no scheduler or scope-overriding plumbing is
    altered. On success we re-read the device from the session so the
    returned payload reflects the freshly updated `connection_status`
    and `last_connected_at` columns.
    """
    user, err = _require_bearer_user()
    if err:
        return err
    device = _mobile_device_for_user(user, device_id)
    if not device:
        return api_error('Device was not found for this account.', code='device_not_found', status=404)
    if not bool(device.is_active):
        return api_error(
            'Device is not active. Re-enable it before syncing.',
            code='device_inactive',
            status=400,
        )

    # Bind the request-scoped helpers so sync_now_internal targets THIS
    # device + user. Restore on the way out so an unrelated handler
    # later in the request lifecycle doesn't pick up a stale scope.
    from flask import g
    from .main import sync_now_internal
    prev_user = getattr(g, 'current_user', None)
    prev_device = getattr(g, 'current_device', None)
    g.current_user = user
    g.current_device = device
    try:
        sync_now_internal(trigger='manual')
    except Exception as exc:  # noqa: BLE001 — classified below
        # Roll back any partial work the sync may have left in the
        # session so this endpoint's response is honest.
        try:
            db.session.rollback()
        except Exception:
            pass
        status, code, message = _mobile_sync_error_payload(exc)
        # Refresh the device payload so the mobile can show the
        # current (unchanged) status alongside the failure message.
        return api_error(
            message,
            code=code,
            status=status,
            device=_mobile_device_detail_payload(device),
        )
    finally:
        g.current_user = prev_user
        g.current_device = prev_device

    # Sync committed inside sync_now_internal — refresh the row so the
    # response reflects the updated `connection_status` / timestamps.
    db.session.refresh(device)
    return api_ok({
        'device': _mobile_device_detail_payload(device),
        'synced': True,
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.delete('/devices/<int:device_id>')
def mobile_device_delete(device_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    device = _mobile_device_for_user(user, device_id)
    if not device:
        return api_error('Device was not found for this account.', code='device_not_found', status=404)

    device.is_active = False
    device.updated_at = datetime.utcnow()
    if user.preferred_device_id == device.id:
        replacement = (
            AppDevice.query
            .filter(AppDevice.owner_user_id == user.id, AppDevice.id != device.id, AppDevice.is_active.is_(True))
            .order_by(AppDevice.id.asc())
            .first()
        )
        user.preferred_device_id = replacement.id if replacement else None
        user.preferred_device_type = replacement.device_type if replacement else user.preferred_device_type
    db.session.commit()
    return api_ok({
        'deleted': False,
        'deactivated': True,
        'device': _mobile_device_detail_payload(device),
        'devices': _device_summary_payload(user),
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/loads')
def mobile_loads_list():
    user, err = _require_bearer_user()
    if err:
        return err
    query, device, error = _mobile_loads_query(user)
    if error:
        return error
    rows = query.order_by(UserLoad.priority.asc(), UserLoad.id.asc()).all()
    return api_ok({
        'items': [_mobile_load_payload(row) for row in rows],
        'total': len(rows),
        'device': _mobile_device_payload(device),
        'scope': {
            'mode': 'device' if device else 'all',
            'device_id': device.id if device else None,
        },
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/loads')
def mobile_load_create():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error
    load = UserLoad()
    error = _mobile_apply_load_fields(load, user, data, creating=True)
    if error:
        return error
    db.session.add(load)
    db.session.commit()
    return api_ok({
        'load': _mobile_load_payload(load),
    }, status=201, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/loads/<int:load_id>')
def mobile_load_detail(load_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    load = _mobile_load_for_user(user, load_id)
    if not load:
        return api_error('Load was not found for this account.', code='load_not_found', status=404)
    return api_ok({'load': _mobile_load_payload(load)}, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.patch('/loads/<int:load_id>')
def mobile_load_update(load_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error
    load = _mobile_load_for_user(user, load_id)
    if not load:
        return api_error('Load was not found for this account.', code='load_not_found', status=404)
    error = _mobile_apply_load_fields(load, user, data)
    if error:
        return error
    db.session.commit()
    return api_ok({'load': _mobile_load_payload(load)}, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.delete('/loads/<int:load_id>')
def mobile_load_delete(load_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    load = _mobile_load_for_user(user, load_id)
    if not load:
        return api_error('Load was not found for this account.', code='load_not_found', status=404)
    deleted_id = load.id
    db.session.delete(load)
    db.session.commit()
    return api_ok({
        'deleted': True,
        'load_id': deleted_id,
        'note': 'The saved load row was removed. No readings, device history, scheduler jobs, or hardware controls were changed.',
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/loads/<int:load_id>/toggle')
def mobile_load_toggle(load_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error
    for key in data:
        if key not in {'is_enabled', 'enabled'}:
            return _json_error('Toggle field is not supported by the mobile API.', code='unsupported_field', field=key)
    load = _mobile_load_for_user(user, load_id)
    if not load:
        return api_error('Load was not found for this account.', code='load_not_found', status=404)
    if 'is_enabled' in data or 'enabled' in data:
        parsed, error = _boolean_or_error(data.get('is_enabled') if 'is_enabled' in data else data.get('enabled'), 'is_enabled')
        if error:
            return error
        load.is_enabled = parsed
    else:
        load.is_enabled = not load.is_enabled
    db.session.commit()
    return api_ok({
        'load': _mobile_load_payload(load),
        'control_type': 'persisted_preference',
        'executed_hardware_command': False,
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/loads/recommendations')
def mobile_load_recommendations():
    user, err = _require_bearer_user()
    if err:
        return err
    query, device, error = _mobile_loads_query(user)
    if error:
        return error
    enabled_count = query.filter_by(is_enabled=True).count()
    return api_ok({
        'available': False,
        'reason': 'mobile_recommendations_deferred',
        'message': 'Mobile load recommendations are not exposed yet because the existing recommendation helpers are coupled to the web dashboard/session context. This endpoint is read-only and does not run scheduler, energy recalculation, or hardware control.',
        'scope': {
            'mode': 'device' if device else 'all',
            'device_id': device.id if device else None,
        },
        'enabled_load_count': enabled_count,
        'items': [],
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/notifications/settings')
def mobile_notification_settings_get():
    user, err = _require_bearer_user()
    if err:
        return err
    return api_ok(_mobile_notification_settings_payload(), meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.patch('/notifications/settings')
def mobile_notification_settings_update():
    user, err = _require_bearer_user()
    if err:
        return err
    data, error = _strict_json_object()
    if error:
        return error

    allowed_settings = _mobile_notification_allowed_setting_keys()
    payload_settings = {}
    if 'settings' in data:
        if not isinstance(data.get('settings'), dict):
            return _json_error('Notification settings must be a JSON object.', code='invalid_settings', field='settings')
        payload_settings.update(data.get('settings') or {})

    supported_top_level = {'settings', 'rules'}
    for key, value in data.items():
        if key in supported_top_level:
            continue
        if key not in allowed_settings:
            return _json_error('Notification setting is not supported by the mobile API.', code='unsupported_field', field=key)
        payload_settings[key] = value

    for key in payload_settings:
        if key not in allowed_settings:
            return _json_error('Notification setting is not supported by the mobile API.', code='unsupported_field', field=f'settings.{key}')

    for key, value in payload_settings.items():
        kind = allowed_settings.get(key)
        if kind == 'checkbox':
            parsed, error = _boolean_or_error(value, key)
            if error:
                return error
            _upsert_setting(key, 'true' if parsed else 'false')
        else:
            if key.endswith('_channel') or key in {'day_deficit_channel'}:
                normalized, error = _mobile_normalize_channel(value, key)
                if error:
                    return error
                _upsert_setting(key, normalized)
            else:
                _upsert_setting(key, str(value if value is not None else '').strip())

    if 'rules' in data:
        rules, error = _mobile_validate_notification_rules(data.get('rules'))
        if error:
            return error
        _upsert_setting('notification_rules_json', json.dumps(rules or {}, ensure_ascii=False))

    db.session.commit()
    return api_ok(_mobile_notification_settings_payload(), meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.get('/notifications')
def mobile_notifications_list():
    user, err = _require_bearer_user()
    if err:
        return err
    page, page_size = pagination_args(default_size=20, max_size=100)
    query = _mobile_notification_event_query(user).order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    unread = _mobile_notification_event_query(user).filter_by(is_read=False).count()
    return api_ok({
        'items': [_mobile_notification_event_payload(row) for row in rows],
        'unread_count': unread,
        'order': 'newest_first',
    }, meta={**page_meta(page, page_size, total), 'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/notifications/<int:notification_id>/read')
def mobile_notification_mark_read(notification_id: int):
    user, err = _require_bearer_user()
    if err:
        return err
    event = _mobile_notification_event_query(user).filter_by(id=notification_id).first()
    if not event:
        return api_error('Notification was not found for this account.', code='notification_not_found', status=404)
    changed = 0
    if not event.is_read:
        event.is_read = True
        event.read_at = datetime.utcnow()
        event.status = 'read'
        changed = 1
        db.session.commit()
    unread = _mobile_notification_event_query(user).filter_by(is_read=False).count()
    return api_ok({
        'changed': changed,
        'notification': _mobile_notification_event_payload(event),
        'unread_count': unread,
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_core_api_bp.post('/notifications/read-all')
def mobile_notifications_read_all():
    user, err = _require_bearer_user()
    if err:
        return err
    rows = _mobile_notification_event_query(user).filter_by(is_read=False).all()
    now = datetime.utcnow()
    for event in rows:
        event.is_read = True
        event.read_at = now
        event.status = 'read'
    if rows:
        db.session.commit()
    return api_ok({
        'changed': len(rows),
        'unread_count': 0,
    }, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


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


def _mobile_allowed_methods_for(normalized_path: str):
    allowed_methods = _MOBILE_CORE_ALLOWED_METHODS.get(normalized_path)
    if allowed_methods:
        return allowed_methods
    parts = normalized_path.strip('/').split('/')
    if len(parts) == 2 and parts[0] == 'devices':
        try:
            int(parts[1])
            return _MOBILE_DEVICE_DETAIL_ALLOWED_METHODS
        except (TypeError, ValueError):
            return None
    if len(parts) == 2 and parts[0] == 'loads':
        try:
            int(parts[1])
            return _MOBILE_LOAD_DETAIL_ALLOWED_METHODS
        except (TypeError, ValueError):
            return None
    if len(parts) == 3 and parts[0] == 'loads' and parts[2] == 'toggle':
        try:
            int(parts[1])
            return _MOBILE_LOAD_TOGGLE_ALLOWED_METHODS
        except (TypeError, ValueError):
            return None
    # v49: subscriber provider-setup endpoint.
    if len(parts) == 3 and parts[0] == 'devices' and parts[2] == 'setup':
        try:
            int(parts[1])
            return _MOBILE_DEVICE_SETUP_ALLOWED_METHODS
        except (TypeError, ValueError):
            return None
    # v50: subscriber sync-now endpoint.
    if len(parts) == 3 and parts[0] == 'devices' and parts[2] == 'sync-now':
        try:
            int(parts[1])
            return _MOBILE_DEVICE_SYNC_NOW_ALLOWED_METHODS
        except (TypeError, ValueError):
            return None
    if len(parts) == 3 and parts[0] == 'notifications' and parts[2] == 'read':
        try:
            int(parts[1])
            return _MOBILE_NOTIFICATION_READ_ALLOWED_METHODS
        except (TypeError, ValueError):
            return None
    return None


@mobile_core_api_bp.route('/<path:mobile_path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def mobile_core_missing_or_method_not_allowed(mobile_path):
    normalized_path = '/' + (mobile_path or '').strip('/')
    allowed_methods = _mobile_allowed_methods_for(normalized_path)
    if allowed_methods:
        return api_error(
            'Method is not allowed for this mobile API endpoint.',
            code='method_not_allowed',
            status=405,
            allowed_methods=sorted(allowed_methods),
        )
    return api_error('Mobile API endpoint was not found.', code='not_found', status=404)
