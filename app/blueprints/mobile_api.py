from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from ..models import NotificationEvent, Reading
from ..services.energy_integrations import provider_catalog
from ..services.rbac import portal_pages, portal_page_visible, role_label
from ..services.scope import get_current_device, get_current_user, get_user_permissions
from ..services.security import csrf_token, sanitize_response_payload
from ..services.utils import format_local_datetime

mobile_api_bp = Blueprint('mobile_api', __name__, url_prefix='/api/v1/mobile')


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _require_login():
    user = get_current_user()
    if not session.get('logged_in') or not user:
        return None, jsonify({'ok': False, 'message': 'Authentication required'}), 401
    return user, None, None


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
    providers = [{'code': p.code, 'name': p.name, 'auth_mode': p.auth_mode, 'category': p.category, 'status': p.status} for p in provider_catalog()]
    return jsonify({
        'ok': True,
        'version': '10.0',
        'csrf_token': csrf_token(),
        'user': {'id': user.id, 'username': user.username, 'full_name': user.full_name, 'role': user.role, 'role_label': role_label(user.role, lang)},
        'permissions': get_user_permissions(user),
        'navigation': pages,
        'providers': providers,
    })


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
    return jsonify({'ok': True, 'device': {'id': getattr(device, 'id', None), 'name': getattr(device, 'name', None), 'type': getattr(device, 'device_type', None)}, 'latest': _reading_payload(latest)})


@mobile_api_bp.get('/notifications')
def notifications():
    user, error, status = _require_login()
    if error:
        return error, status
    rows = NotificationEvent.query.filter_by(target_user_id=user.id).order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc()).limit(30).all()
    return jsonify({'ok': True, 'items': [sanitize_response_payload({'id': r.id, 'title': r.title, 'message': r.message, 'url': r.direct_url, 'is_read': r.is_read, 'created_at': r.created_at.isoformat() if r.created_at else None}) for r in rows]})


@mobile_api_bp.get('/health')
def health():
    return jsonify({'ok': True, 'version': '10.0', 'message': 'SolarDeye mobile API is ready'})
