from __future__ import annotations

from flask import Blueprint, request, session

from ..models import AppDevice, NotificationEvent, Reading, SubscriptionPlan, TenantAccount
from ..services.energy_integrations import provider_catalog
from ..services.location_catalog import countries_for_template, phone_prefixes_for_template, timezones_grouped_for_template, timezones_for_template
from ..services.rbac import portal_pages, portal_page_visible, role_label
from ..services.scope import get_current_device, get_user_permissions
from ..services.security import csrf_token, sanitize_response_payload
from ..services.subscriptions import allowed_device_limit, compute_subscription_status, current_subscription_for_user, ensure_user_tenant_and_subscription, plan_features
from ..services.mobile_auth import user_from_bearer_or_session
from ..services.api_responses import api_error, api_ok

mobile_api_bp = Blueprint('mobile_api', __name__, url_prefix='/api/v1/mobile')
mobile_core_api_bp = Blueprint('mobile_core_api', __name__, url_prefix='/api/mobile')


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _require_login():
    user = user_from_bearer_or_session()
    if not user:
        return None, api_error('Authentication required.', code='auth_required', status=401), 401
    return user, None, None


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
    }


def _provider_payloads():
    rows = []
    for spec in provider_catalog():
        rows.append({
            'code': spec.code,
            'name': spec.name,
            'provider': spec.provider,
            'auth_mode': spec.auth_mode,
            'category': spec.category,
            'status': spec.status,
            'base_url': spec.base_url or '',
            'required_fields': list(spec.required_fields or ()),
            'optional_fields': list(spec.optional_fields or ()),
            'notes_ar': spec.notes_ar,
            'notes_en': spec.notes_en,
        })
    return rows


def _location_payload():
    return {
        'countries': countries_for_template(),
        'phone_prefixes': phone_prefixes_for_template(),
        'timezones': timezones_for_template(),
        'timezone_groups': timezones_grouped_for_template(),
    }


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
