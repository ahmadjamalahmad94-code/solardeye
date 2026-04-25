from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flask import abort, flash, g, request, session, url_for, redirect

from ..extensions import db
from ..models import AppRole, PortalPageSetting, Setting


@dataclass(frozen=True)
class PermissionSpec:
    key: str
    label_ar: str
    label_en: str
    group_ar: str = 'الإدارة'
    group_en: str = 'Administration'


PERMISSION_CATALOG: tuple[PermissionSpec, ...] = (
    PermissionSpec('can_manage_users', 'إدارة المشتركين والمستخدمين', 'Manage subscribers and users'),
    PermissionSpec('can_manage_roles', 'إدارة الأدوار والصلاحيات', 'Manage roles and permissions'),
    PermissionSpec('can_manage_portal_visibility', 'إخفاء وإظهار صفحات المشترك', 'Manage subscriber page visibility'),
    PermissionSpec('can_manage_devices', 'إدارة الأجهزة', 'Manage devices'),
    PermissionSpec('can_manage_integrations', 'إدارة التكاملات', 'Manage integrations'),
    PermissionSpec('can_configure_integrations', 'إعداد التكاملات', 'Configure integrations'),
    PermissionSpec('can_manage_support', 'إدارة الدعم والتذاكر', 'Manage support and tickets'),
    PermissionSpec('can_manage_finance', 'إدارة المالية والمحفظة', 'Manage finance and wallet'),
    PermissionSpec('can_manage_subscriptions', 'إدارة الاشتراكات والخطط', 'Manage subscriptions and plans'),
    PermissionSpec('can_manage_backups', 'إدارة النسخ الاحتياطي والاستعادة', 'Manage backup and recovery'),
    PermissionSpec('can_view_logs', 'عرض السجلات وصحة الخدمات', 'View logs and service health'),
    PermissionSpec('can_manage_system', 'إعدادات النظام الحساسة', 'Manage sensitive system settings'),
    PermissionSpec('can_access_mobile_api', 'استخدام واجهات تطبيق الموبايل', 'Use mobile app APIs'),
)
PERMISSION_KEYS = tuple(p.key for p in PERMISSION_CATALOG)

DEFAULT_ROLES = (
    {
        'code': 'admin', 'name_ar': 'مدير كامل', 'name_en': 'Full Admin', 'summary_ar': 'تحكم كامل في المنصة.', 'summary_en': 'Full platform control.', 'is_system': True, 'sort_order': 1,
        'permissions': {key: True for key in PERMISSION_KEYS},
    },
    {
        'code': 'support_admin', 'name_ar': 'مدير دعم', 'name_en': 'Support Admin', 'summary_ar': 'الدعم، التذاكر، وسجل العمليات.', 'summary_en': 'Support, tickets, and operational logs.', 'is_system': True, 'sort_order': 10,
        'permissions': {'can_manage_support': True, 'can_view_logs': True, 'can_access_mobile_api': True},
    },
    {
        'code': 'finance_admin', 'name_ar': 'مدير مالية', 'name_en': 'Finance Admin', 'summary_ar': 'المالية، الاشتراكات، والمحفظة.', 'summary_en': 'Finance, subscriptions, and wallet operations.', 'is_system': True, 'sort_order': 20,
        'permissions': {'can_manage_finance': True, 'can_manage_subscriptions': True, 'can_view_logs': True},
    },
    {
        'code': 'integration_admin', 'name_ar': 'مدير تكاملات', 'name_en': 'Integration Admin', 'summary_ar': 'الأجهزة والتكاملات وصحة الخدمات.', 'summary_en': 'Devices, integrations, and service health.', 'is_system': True, 'sort_order': 30,
        'permissions': {'can_manage_devices': True, 'can_manage_integrations': True, 'can_configure_integrations': True, 'can_view_logs': True},
    },
    {
        'code': 'user', 'name_ar': 'مشترك', 'name_en': 'Subscriber', 'summary_ar': 'بوابة المشترك الأساسية.', 'summary_en': 'Default subscriber portal access.', 'is_system': True, 'sort_order': 100,
        'permissions': {'can_access_mobile_api': True},
    },
)

PORTAL_PAGES = (
    {'page_key': 'dashboard', 'endpoint': 'main.dashboard', 'label_ar': 'النظرة العامة', 'label_en': 'Overview', 'icon': '🏠', 'group_key': 'portal', 'sort_order': 1, 'is_locked': True},
    {'page_key': 'devices_manage', 'endpoint': 'main.devices_manage', 'label_ar': 'أجهزتي', 'label_en': 'My Devices', 'icon': '🔌', 'group_key': 'portal', 'sort_order': 2},
    {'page_key': 'onboarding', 'endpoint': 'main.onboarding_wizard', 'label_ar': 'معالج الإعداد', 'label_en': 'Setup Wizard', 'icon': '🧭', 'group_key': 'portal', 'sort_order': 3},
    {'page_key': 'subscription', 'endpoint': 'main.account_subscription', 'label_ar': 'اشتراكي', 'label_en': 'Subscription', 'icon': '💳', 'group_key': 'portal', 'sort_order': 4},
    {'page_key': 'statistics', 'endpoint': 'main.statistics', 'label_ar': 'الإحصائيات', 'label_en': 'Statistics', 'icon': '📊', 'group_key': 'monitoring', 'sort_order': 10},
    {'page_key': 'reports', 'endpoint': 'main.reports', 'label_ar': 'التقارير', 'label_en': 'Reports', 'icon': '🧾', 'group_key': 'monitoring', 'sort_order': 11},
    {'page_key': 'live_data', 'endpoint': 'main.live_data', 'label_ar': 'البيانات الحية', 'label_en': 'Live Data', 'icon': '📡', 'group_key': 'monitoring', 'sort_order': 12},
    {'page_key': 'loads', 'endpoint': 'main.loads_page', 'label_ar': 'الأحمال', 'label_en': 'Loads', 'icon': '💡', 'group_key': 'monitoring', 'sort_order': 13},
    {'page_key': 'notifications', 'endpoint': 'main.notifications_settings', 'label_ar': 'الإشعارات', 'label_en': 'Notifications', 'icon': '📲', 'group_key': 'monitoring', 'sort_order': 14},
    {'page_key': 'channels', 'endpoint': 'main.channels', 'label_ar': 'Telegram و SMS', 'label_en': 'Telegram & SMS', 'icon': '🔗', 'group_key': 'monitoring', 'sort_order': 15},
    {'page_key': 'support', 'endpoint': 'main.portal_support', 'label_ar': 'الدعم والمراسلات', 'label_en': 'Support Center', 'icon': '💬', 'group_key': 'monitoring', 'sort_order': 16},
)
PORTAL_ENDPOINT_TO_KEY = {p['endpoint']: p['page_key'] for p in PORTAL_PAGES}
PORTAL_ENDPOINT_TO_KEY.update({
    'main.portal_messages': 'support', 'main.portal_tickets': 'support',
    'energy.dashboard': 'dashboard',
    'devices_routes.devices_manage': 'devices_manage',
    'devices_routes.onboarding_wizard': 'onboarding',
    'billing.account_subscription': 'subscription',
    'energy.statistics': 'statistics',
    'energy.reports': 'reports',
    'energy.live_data': 'live_data',
    'energy.loads_page': 'loads',
    'notifications_routes.notifications_settings': 'notifications',
    'notifications_routes.channels': 'channels',
    'support.portal_support': 'support',
    'support.portal_messages': 'support',
    'support.portal_tickets': 'support',
})


def _parse_permissions(raw: Any) -> dict[str, bool]:
    if isinstance(raw, dict):
        return {k: bool(v) for k, v in raw.items() if k in PERMISSION_KEYS}
    try:
        parsed = json.loads(raw or '{}')
        if isinstance(parsed, dict):
            return {k: bool(v) for k, v in parsed.items() if k in PERMISSION_KEYS}
    except Exception:
        pass
    return {}


def permission_catalog(lang: str = 'ar') -> list[dict[str, str]]:
    is_en = (lang or 'ar') == 'en'
    return [{'key': p.key, 'label': p.label_en if is_en else p.label_ar, 'group': p.group_en if is_en else p.group_ar} for p in PERMISSION_CATALOG]


def all_permission_defaults(value: bool = False) -> dict[str, bool]:
    return {key: bool(value) for key in PERMISSION_KEYS}


def role_permissions(role_code: str | None) -> dict[str, bool]:
    code = (role_code or 'user').strip().lower() or 'user'
    if code == 'admin':
        return all_permission_defaults(True)
    row = AppRole.query.filter_by(code=code, is_active=True).first()
    if row:
        perms = all_permission_defaults(False)
        perms.update(_parse_permissions(row.permissions_json))
        return perms
    for role in DEFAULT_ROLES:
        if role['code'] == code:
            perms = all_permission_defaults(False)
            perms.update(role.get('permissions') or {})
            return perms
    return role_permissions('user')


def available_roles(include_inactive: bool = False):
    q = AppRole.query.order_by(AppRole.sort_order.asc(), AppRole.name_en.asc(), AppRole.code.asc())
    if not include_inactive:
        q = q.filter_by(is_active=True)
    rows = q.all()
    if rows:
        return rows
    class _FallbackRole:
        def __init__(self, data):
            self.code = data['code']; self.name_ar = data['name_ar']; self.name_en = data['name_en']; self.summary_ar = data.get('summary_ar',''); self.summary_en = data.get('summary_en',''); self.permissions_json = json.dumps(data.get('permissions') or {}); self.is_system = data.get('is_system', False); self.is_active = True
    return [_FallbackRole(r) for r in DEFAULT_ROLES]


def admin_landing_url(lang: str = 'ar') -> str:
    try:
        from .scope import has_permission
        if has_permission('can_manage_users'):
            return url_for('main.admin_subscribers', lang=lang)
        if has_permission('can_manage_support'):
            return url_for('main.admin_support_command_center', lang=lang)
        if has_permission('can_manage_devices'):
            return url_for('admin_ops.admin_devices_center_v9', lang=lang)
        if has_permission('can_manage_integrations'):
            return url_for('integrations.admin_integrations', lang=lang)
        if has_permission('can_manage_finance'):
            return url_for('main.admin_finance', lang=lang)
        if has_permission('can_manage_backups'):
            return url_for('platform.admin_backups', lang=lang)
        if has_permission('can_view_logs'):
            return url_for('admin_ops.admin_services_health_v9', lang=lang)
    except Exception:
        pass
    return url_for('main.admin_dashboard', lang=lang)


def role_label(code: str, lang: str = 'ar') -> str:
    row = AppRole.query.filter_by(code=(code or 'user')).first()
    if row:
        return row.name_en if (lang or 'ar') == 'en' else row.name_ar
    for role in DEFAULT_ROLES:
        if role['code'] == code:
            return role['name_en'] if (lang or 'ar') == 'en' else role['name_ar']
    return code or 'user'


def portal_pages(include_locked: bool = True):
    rows = PortalPageSetting.query.order_by(PortalPageSetting.sort_order.asc(), PortalPageSetting.id.asc()).all()
    if not rows:
        return [dict(p, is_visible=True) for p in PORTAL_PAGES if include_locked or not p.get('is_locked')]
    return [r for r in rows if include_locked or not r.is_locked]


USER_PORTAL_VISIBILITY_PREFIX = 'user_portal_visibility:'


def _portal_page_row(page_key: str):
    row = PortalPageSetting.query.filter_by(page_key=page_key).first()
    if row is None:
        seed_access_control(commit=False)
        row = PortalPageSetting.query.filter_by(page_key=page_key).first()
    return row


def _user_visibility_setting_key(user_id: int | None) -> str | None:
    try:
        uid = int(user_id or 0)
    except Exception:
        uid = 0
    return f'{USER_PORTAL_VISIBILITY_PREFIX}{uid}' if uid else None


def _load_user_visibility(user_id: int | None) -> dict[str, bool]:
    key = _user_visibility_setting_key(user_id)
    if not key:
        return {}
    row = Setting.query.filter_by(key=key).first()
    if not row or not row.value:
        return {}
    try:
        parsed = json.loads(row.value or '{}')
        if isinstance(parsed, dict):
            return {str(k): bool(v) for k, v in parsed.items()}
    except Exception:
        pass
    return {}


def save_user_portal_visibility(user_id: int, visible_keys: set[str] | list[str] | tuple[str, ...]):
    key = _user_visibility_setting_key(user_id)
    if not key:
        return False
    visible = {str(k) for k in (visible_keys or [])}
    payload = {}
    for page in portal_pages(include_locked=True):
        page_key = getattr(page, 'page_key', None) if not isinstance(page, dict) else page.get('page_key')
        is_locked = bool(getattr(page, 'is_locked', False) if not isinstance(page, dict) else page.get('is_locked'))
        if not page_key:
            continue
        payload[page_key] = True if is_locked else (page_key in visible)
    row = Setting.query.filter_by(key=key).first()
    if row is None:
        row = Setting(key=key)
        db.session.add(row)
    row.value = json.dumps(payload, ensure_ascii=False)
    row.updated_at = datetime.utcnow()
    return True


def user_portal_visibility_map(user_id: int | None) -> dict[str, bool]:
    overrides = _load_user_visibility(user_id)
    result = {}
    for page in portal_pages(include_locked=True):
        page_key = getattr(page, 'page_key', None) if not isinstance(page, dict) else page.get('page_key')
        is_locked = bool(getattr(page, 'is_locked', False) if not isinstance(page, dict) else page.get('is_locked'))
        global_visible = bool(getattr(page, 'is_visible', True) if not isinstance(page, dict) else page.get('is_visible', True))
        if not page_key:
            continue
        if is_locked:
            result[page_key] = True
        elif not global_visible:
            result[page_key] = False
        else:
            result[page_key] = bool(overrides.get(page_key, True))
    return result


def portal_page_visible_for_user(user, page_key: str) -> bool:
    row = _portal_page_row(page_key)
    if row and row.is_locked:
        return True
    if row and not row.is_visible:
        return False
    uid = getattr(user, 'id', None)
    if not uid:
        return True if row is None else bool(row.is_visible)
    return bool(user_portal_visibility_map(uid).get(page_key, True))


def portal_page_visible(page_key: str) -> bool:
    try:
        from .scope import get_current_user
        current = get_current_user()
        if current is not None:
            return portal_page_visible_for_user(current, page_key)
    except Exception:
        pass
    row = _portal_page_row(page_key)
    if row and row.is_locked:
        return True
    return True if row is None else bool(row.is_visible)


def seed_access_control(commit: bool = True):
    changed = False
    for data in DEFAULT_ROLES:
        row = AppRole.query.filter_by(code=data['code']).first()
        if row is None:
            row = AppRole(code=data['code'], created_at=datetime.utcnow())
            db.session.add(row)
            changed = True
        row.name_ar = row.name_ar or data['name_ar']
        row.name_en = row.name_en or data['name_en']
        row.summary_ar = row.summary_ar or data.get('summary_ar', '')
        row.summary_en = row.summary_en or data.get('summary_en', '')
        row.is_system = bool(data.get('is_system', False))
        row.sort_order = data.get('sort_order', row.sort_order or 100)
        if not row.permissions_json:
            row.permissions_json = json.dumps(data.get('permissions') or {}, ensure_ascii=False)
        row.is_active = True
    for data in PORTAL_PAGES:
        row = PortalPageSetting.query.filter_by(page_key=data['page_key']).first()
        if row is None:
            row = PortalPageSetting(page_key=data['page_key'], created_at=datetime.utcnow())
            db.session.add(row)
            changed = True
        for key in ['endpoint','label_ar','label_en','icon','group_key','sort_order','is_locked']:
            setattr(row, key, data.get(key, getattr(row, key, None)))
        if row.is_visible is None:
            row.is_visible = True
    if commit and changed:
        db.session.commit()


def _template_has_permission(permission: str) -> bool:
    try:
        from .scope import has_permission as _hp, is_system_admin as _isa
        return bool(_isa() or _hp(permission))
    except Exception:
        return False


def register_access_control(app):
    @app.context_processor
    def _access_control_context():
        return {
            'available_roles': available_roles,
            'permission_catalog': permission_catalog,
            'role_permissions': role_permissions,
            'role_label': role_label,
            'portal_page_visible': portal_page_visible,
            'portal_page_visible_for_user': portal_page_visible_for_user,
            'user_portal_visibility_map': user_portal_visibility_map,
            'portal_pages': portal_pages,
            'permission_keys': PERMISSION_KEYS,
            'has_permission': _template_has_permission,
            'admin_landing_url': admin_landing_url,
        }

    @app.before_request
    def _portal_page_guard():
        if not session.get('logged_in'):
            return None
        # Admins are governed by permission guards in each route.
        try:
            from .scope import get_current_user
            current = get_current_user()
            if current and bool(getattr(current, 'is_admin', False) or (getattr(current, 'role', '') or '').strip().lower() == 'admin'):
                return None
        except Exception:
            pass
        if bool(session.get('is_admin_scope', False)):
            return None
        endpoint = request.endpoint or ''
        page_key = PORTAL_ENDPOINT_TO_KEY.get(endpoint)
        if not page_key:
            return None
        if portal_page_visible(page_key):
            return None
        lang = 'en' if (request.args.get('lang') or session.get('ui_lang') or 'ar') == 'en' else 'ar'
        flash('This page is currently hidden for subscriber accounts.' if lang == 'en' else 'هذه الصفحة مخفية حاليًا عن حسابات المشتركين.', 'warning')
        if endpoint != 'main.dashboard' and portal_page_visible('dashboard'):
            return redirect(url_for('main.dashboard', lang=lang))
        abort(403)
