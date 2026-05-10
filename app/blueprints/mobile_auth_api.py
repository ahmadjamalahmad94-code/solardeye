from __future__ import annotations

from flask import Blueprint, request
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import AppDevice, AppUser
from ..services.api_responses import api_error, api_ok
from ..services.energy_integrations import provider_catalog
from ..services.location_catalog import find_country, timezones_for_template
from ..services.mobile_auth import authenticate_username_password, issue_refresh_token, refresh_access_token, revoke_refresh_token, token_payload, user_from_bearer_or_session
from ..services.access_state import account_access_state
from ..services.subscriptions import ensure_user_tenant_and_subscription

mobile_auth_api_bp = Blueprint('mobile_auth_api', __name__, url_prefix='/api/v1/auth')
mobile_auth_api_v2_bp = Blueprint('mobile_auth_api_v2', __name__, url_prefix='/api/mobile/auth')


def _json():
    return request.get_json(silent=True) or {}


def _provider_for(code: str | None):
    provider_code = (code or 'deye').strip().lower() or 'deye'
    providers = provider_catalog()
    return next((item for item in providers if item.code == provider_code), providers[0] if providers else None)


def _normalize_language(value: str | None) -> str:
    return 'en' if str(value or '').strip().lower().startswith('en') else 'ar'


def _clean_phone(value: str | None) -> str:
    allowed = set('+ -()')
    return ''.join(ch for ch in (value or '') if ch.isdigit() or ch in allowed).strip()


def _create_setup_device(user: AppUser, provider_code: str | None) -> AppDevice | None:
    spec = _provider_for(provider_code)
    if not spec:
        return None
    base_name = (user.full_name or user.username or 'My Energy Site').strip()
    device = AppDevice(
        owner_user_id=user.id,
        name=f'{base_name} - {spec.name}',
        device_type=spec.code,
        api_provider=spec.provider or spec.code,
        api_base_url=spec.base_url or None,
        timezone=user.timezone or 'Asia/Hebron',
        auth_mode='wizard',
        is_active=True,
        connection_status='setup_required',
        notes='Created from the mobile registration flow. Complete provider credentials during onboarding.',
    )
    db.session.add(device)
    db.session.flush()
    user.preferred_device_id = device.id
    user.preferred_device_type = device.device_type or spec.code
    return device


def _registration_payload(user: AppUser) -> dict:
    return {
        'id': user.id,
        'username': user.username,
        'full_name': user.full_name,
        'email': user.email,
        'role': user.role,
        'is_admin': bool(user.is_admin),
        'is_active': bool(user.is_active),
        'preferred_language': user.preferred_language or 'ar',
        'country': user.country or '',
        'city': user.city or '',
        'timezone': user.timezone or '',
        'phone_country_code': user.phone_country_code or '',
        'phone_number': user.phone_number or '',
    }


@mobile_auth_api_bp.post('/register')
@mobile_auth_api_v2_bp.post('/register')
def mobile_register():
    data = _json()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    full_name = (data.get('full_name') or '').strip() or None
    preferred_language = _normalize_language(data.get('preferred_language') or data.get('language'))
    country_code = (data.get('country_code') or '').strip().upper()
    country = (data.get('country') or '').strip()
    city = (data.get('city') or '').strip()
    timezone = (data.get('timezone') or '').strip()
    phone_country_code = (data.get('phone_country_code') or '').strip()
    phone_number = _clean_phone(data.get('phone_number'))
    has_energy_system = str(data.get('has_energy_system', 'yes')).strip().lower() not in {'0', 'false', 'no', 'none'}
    preferred_device_type = (data.get('preferred_device_type') or data.get('provider_code') or 'deye').strip().lower() or 'deye'

    if not username or not password:
        return api_error('Username and password are required.', code='missing_registration_fields', status=400)
    if len(username) < 3:
        return api_error('Username must be at least 3 characters.', code='username_too_short', status=400)
    if len(password) < 6:
        return api_error('Password must be at least 6 characters.', code='password_too_short', status=400)
    if AppUser.query.filter_by(username=username).first():
        return api_error('Username is already in use.', code='username_taken', status=409)
    if email and AppUser.query.filter(db.func.lower(AppUser.email) == email).first():
        return api_error('Email is already in use.', code='email_taken', status=409)

    selected_country = find_country(country_code or country)
    if selected_country:
        country = selected_country.get('name_en') if preferred_language == 'en' else selected_country.get('name_ar')
        phone_country_code = phone_country_code or selected_country.get('dial') or ''
        timezone = timezone if timezone in timezones_for_template() else (selected_country.get('timezone') or 'Asia/Hebron')
    elif timezone and timezone not in timezones_for_template():
        return api_error('Timezone is not supported.', code='invalid_timezone', status=400)
    elif not timezone:
        timezone = 'Asia/Hebron'

    known_provider_codes = {item.code for item in provider_catalog()}
    if preferred_device_type not in known_provider_codes:
        preferred_device_type = 'deye'

    user = AppUser(
        username=username,
        password_hash=generate_password_hash(password),
        full_name=full_name,
        email=email or None,
        phone_country_code=phone_country_code or None,
        phone_number=phone_number or None,
        country=country or None,
        city=city or None,
        timezone=timezone,
        preferred_language=preferred_language,
        role='user',
        preferred_device_type=preferred_device_type,
        is_active=True,
        is_admin=False,
        onboarding_completed=False,
        onboarding_step='device' if has_energy_system else 'profile',
    )
    db.session.add(user)
    db.session.flush()
    if has_energy_system:
        _create_setup_device(user, preferred_device_type)
    db.session.commit()
    ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)

    refresh = issue_refresh_token(
        user,
        device_label=data.get('device_label') or '',
        ip_address=request.remote_addr or '',
        user_agent=request.headers.get('User-Agent', ''),
    )
    payload = token_payload(user, refresh)
    payload['user'] = _registration_payload(user)
    payload['onboarding'] = {
        'completed': bool(user.onboarding_completed),
        'step': user.onboarding_step or 'welcome',
        'needs_profile_location': not bool(user.country and user.city and user.timezone),
        'needs_device_link': has_energy_system and not bool(user.preferred_device_id),
    }
    return api_ok(payload, status=201, meta={'api_version': 'v1', 'namespace': 'api/mobile'})


@mobile_auth_api_v2_bp.post('/login')
@mobile_auth_api_bp.post('/login')
def mobile_login():
    data = _json()
    username = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return api_error('Username and password are required.', code='missing_credentials', status=400)
    user = authenticate_username_password(username, password)
    if not user:
        return api_error('Invalid username or password.', code='invalid_credentials', status=401)
    refresh = issue_refresh_token(user, device_label=data.get('device_label') or '', ip_address=request.remote_addr or '', user_agent=request.headers.get('User-Agent', ''))
    return api_ok(token_payload(user, refresh), meta={'api_version': 'v1'})


@mobile_auth_api_v2_bp.post('/refresh')
@mobile_auth_api_bp.post('/refresh')
def mobile_refresh():
    data = _json()
    user, access = refresh_access_token(data.get('refresh_token'))
    if not user or not access:
        return api_error('Refresh token is invalid or expired.', code='invalid_refresh_token', status=401)
    payload = token_payload(user)
    payload['access_token'] = access
    return api_ok(payload, meta={'api_version': 'v1'})


@mobile_auth_api_v2_bp.post('/logout')
@mobile_auth_api_bp.post('/logout')
def mobile_logout():
    data = _json()
    changed = revoke_refresh_token(data.get('refresh_token')) if data.get('refresh_token') else False
    return api_ok({'revoked': changed})


@mobile_auth_api_v2_bp.get('/me')
@mobile_auth_api_bp.get('/me')
def mobile_me():
    user = user_from_bearer_or_session()
    if not user:
        return api_error('Authentication required.', code='auth_required', status=401)
    state = account_access_state(user)
    return api_ok({
        'id': user.id,
        'username': user.username,
        'full_name': user.full_name,
        'email': user.email,
        'role': user.role,
        'is_admin': bool(user.is_admin),
        'is_active': bool(user.is_active),
        'preferred_language': user.preferred_language or 'ar',
        'country': user.country or '',
        'city': user.city or '',
        'timezone': user.timezone or '',
        'phone_country_code': user.phone_country_code or '',
        'phone_number': user.phone_number or '',
        'selected_device_id': user.preferred_device_id,
        'onboarding': {
            'completed': bool(user.onboarding_completed),
            'step': user.onboarding_step or ('done' if user.onboarding_completed else 'welcome'),
        },
        'account_restricted': bool(state.get('restricted')),
        'restriction_reason': state.get('reason') or '',
        'can_write': not bool(state.get('restricted')),
    })
