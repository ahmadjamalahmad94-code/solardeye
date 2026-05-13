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


# ════════════════════════════════════════════════════════════════════
# Sub-permissions catalog (granular controls under high-impact parents)
# ════════════════════════════════════════════════════════════════════
# Only the four parent permissions that materially change site structure
# or member access have sub-permissions. The other 9 parents stay binary.
#
# Semantics:
#   • If the parent permission is False  → ALL subs evaluate to False
#   • If the parent is True and the sub key is NOT present in storage
#       → the sub evaluates to True (backwards-compatible default: turning
#         on a parent grants every sub unless the admin explicitly opts out)
#   • If the sub key IS present in storage → its boolean value wins
#
# Storage: sub keys live in the SAME permissions_json dict as parent keys,
# using dot notation:  permissions_json["users.delete"] = false


@dataclass(frozen=True)
class SubPermissionSpec:
    key: str            # e.g. "users.delete"  (dot-notation)
    parent: str         # e.g. "can_manage_users"
    label_ar: str
    label_en: str
    is_dangerous: bool = False  # marks subs that should warn admins


SUB_PERMISSION_CATALOG: tuple[SubPermissionSpec, ...] = (
    # ─── can_manage_users ────────────────────────────────────────
    SubPermissionSpec('users.view_list',     'can_manage_users', 'عرض القائمة وفتح بروفايل أي حساب',  'View list and open any profile'),
    SubPermissionSpec('users.edit_data',     'can_manage_users', 'تعديل البيانات الشخصية',             'Edit personal data'),
    SubPermissionSpec('users.toggle_active', 'can_manage_users', 'تفعيل وتعطيل الحسابات',              'Enable / disable accounts'),
    SubPermissionSpec('users.reset_password','can_manage_users', 'إعادة تعيين كلمات المرور',           'Reset passwords'),
    SubPermissionSpec('users.change_role',   'can_manage_users', 'تغيير الدور والصلاحيات الفردية',     'Change role and individual permissions'),
    SubPermissionSpec('users.delete',        'can_manage_users', 'حذف المستخدمين نهائياً',             'Permanently delete users', is_dangerous=True),

    # ─── can_manage_roles ────────────────────────────────────────
    SubPermissionSpec('roles.create',              'can_manage_roles', 'إنشاء أدوار جديدة',                'Create new roles'),
    SubPermissionSpec('roles.edit_permissions',    'can_manage_roles', 'تعديل صلاحيات الأدوار',            'Edit role permissions'),
    SubPermissionSpec('roles.activate_deactivate', 'can_manage_roles', 'تفعيل وتعطيل الأدوار بدون حذف',    'Activate / deactivate without delete'),
    SubPermissionSpec('roles.delete',              'can_manage_roles', 'حذف الأدوار نهائياً',              'Delete roles permanently', is_dangerous=True),

    # ─── can_manage_system ───────────────────────────────────────
    SubPermissionSpec('system.edit_basic',       'can_manage_system', 'إعدادات عامة (اسم الموقع، الشعار)', 'General settings (site name, logo)'),
    SubPermissionSpec('system.edit_security',    'can_manage_system', 'مفاتيح التشفير وسياسات الأمان',     'Encryption keys and security policies', is_dangerous=True),
    SubPermissionSpec('system.maintenance_mode', 'can_manage_system', 'تشغيل وإيقاف وضع الصيانة',          'Toggle maintenance mode', is_dangerous=True),
    SubPermissionSpec('system.toggle_features',  'can_manage_system', 'تشغيل وإيقاف الميزات التجريبية',    'Toggle experimental features'),

    # ─── can_manage_finance ──────────────────────────────────────
    SubPermissionSpec('finance.view',    'can_manage_finance', 'عرض الكشوفات والمعاملات',  'View statements and transactions'),
    SubPermissionSpec('finance.credit',  'can_manage_finance', 'إيداع رصيد للمشتركين',     'Credit wallets'),
    SubPermissionSpec('finance.debit',   'can_manage_finance', 'خصم رصيد من المشتركين',    'Debit wallets'),
    SubPermissionSpec('finance.refund',  'can_manage_finance', 'استرداد الأموال للمشتركين','Refund subscribers', is_dangerous=True),
    SubPermissionSpec('finance.coupons', 'can_manage_finance', 'إنشاء قسائم الخصم',         'Create discount coupons'),
)
SUB_PERMISSION_KEYS = tuple(s.key for s in SUB_PERMISSION_CATALOG)
ALL_PERMISSION_KEYS = PERMISSION_KEYS + SUB_PERMISSION_KEYS

# Quick-lookup map: parent → list[SubPermissionSpec]
SUBS_BY_PARENT: dict[str, tuple[SubPermissionSpec, ...]] = {
    parent: tuple(s for s in SUB_PERMISSION_CATALOG if s.parent == parent)
    for parent in PERMISSION_KEYS
}
# Quick-lookup map: sub key → SubPermissionSpec
SUB_PERMISSION_BY_KEY: dict[str, SubPermissionSpec] = {
    s.key: s for s in SUB_PERMISSION_CATALOG
}


def parent_of_sub(sub_key: str) -> str | None:
    """Return the parent permission key for a given sub key, or None."""
    spec = SUB_PERMISSION_BY_KEY.get(sub_key)
    return spec.parent if spec else None


def subs_for_parent(parent_key: str) -> tuple[SubPermissionSpec, ...]:
    """Return the sub-permissions defined under a parent (empty tuple if none)."""
    return SUBS_BY_PARENT.get(parent_key, ())


def has_sub_permissions(parent_key: str) -> bool:
    """True if the parent permission has granular sub-permissions defined."""
    return bool(SUBS_BY_PARENT.get(parent_key))


def sub_permission_catalog(lang: str = 'ar') -> list[dict[str, Any]]:
    """Localized list of sub-permissions for templates / API."""
    is_en = (lang or 'ar') == 'en'
    return [
        {
            'key': s.key,
            'parent': s.parent,
            'label': s.label_en if is_en else s.label_ar,
            'is_dangerous': s.is_dangerous,
        }
        for s in SUB_PERMISSION_CATALOG
    ]

STAFF_ROLE_PRESETS = (
    {
        'code': 'general_manager', 'name_ar': 'مدير عام', 'name_en': 'General Manager', 'summary_ar': 'إشراف تشغيلي كامل بدون صلاحيات إعدادات النظام الحساسة.', 'summary_en': 'Full operational oversight without sensitive system settings.', 'is_system': True, 'sort_order': 2,
        'permissions': {'can_manage_users': True, 'can_manage_roles': True, 'can_manage_portal_visibility': True, 'can_manage_devices': True, 'can_manage_integrations': True, 'can_configure_integrations': True, 'can_manage_support': True, 'can_manage_finance': True, 'can_manage_subscriptions': True, 'can_manage_backups': True, 'can_view_logs': True, 'can_access_mobile_api': True},
    },
    {
        'code': 'assistant_manager', 'name_ar': 'مساعد مدير', 'name_en': 'Assistant Manager', 'summary_ar': 'متابعة المستخدمين والدعم والأجهزة والسجلات التشغيلية.', 'summary_en': 'Users, support, devices, and operational logs.', 'is_system': True, 'sort_order': 5,
        'permissions': {'can_manage_users': True, 'can_manage_portal_visibility': True, 'can_manage_devices': True, 'can_manage_support': True, 'can_manage_subscriptions': True, 'can_view_logs': True, 'can_access_mobile_api': True},
    },
    {
        'code': 'technical_support', 'name_ar': 'دعم فني', 'name_en': 'Technical Support', 'summary_ar': 'متابعة التذاكر والمراسلات ومراجعة الأجهزة دون صلاحيات مالية.', 'summary_en': 'Tickets, messages, and device review without finance access.', 'is_system': True, 'sort_order': 12,
        'permissions': {'can_manage_support': True, 'can_manage_devices': True, 'can_view_logs': True, 'can_access_mobile_api': True},
    },
    {
        'code': 'finance_manager', 'name_ar': 'مدير مالي', 'name_en': 'Finance Manager', 'summary_ar': 'إدارة الحسابات والاشتراكات والباقات والتقارير المالية.', 'summary_en': 'Finance, subscriptions, plans, and financial reporting.', 'is_system': True, 'sort_order': 21,
        'permissions': {'can_manage_finance': True, 'can_manage_subscriptions': True, 'can_manage_users': True, 'can_view_logs': True},
    },
    {
        'code': 'marketing_manager', 'name_ar': 'مدير تسويق', 'name_en': 'Marketing Manager', 'summary_ar': 'متابعة المشتركين والدعم الأساسي بدون حذف أو إعدادات حساسة.', 'summary_en': 'Subscriber follow-up and basic support without sensitive settings.', 'is_system': True, 'sort_order': 25,
        'permissions': {'can_manage_users': True, 'can_manage_support': True, 'can_manage_subscriptions': True, 'can_access_mobile_api': True},
    },
    {
        'code': 'developer', 'name_ar': 'مطوّر النظام', 'name_en': 'Developer', 'summary_ar': 'إدارة التكاملات وصحة الخدمات والنسخ الاحتياطية والسجلات التقنية.', 'summary_en': 'Integrations, service health, backups, and technical logs.', 'is_system': True, 'sort_order': 35,
        'permissions': {'can_manage_devices': True, 'can_manage_integrations': True, 'can_configure_integrations': True, 'can_manage_backups': True, 'can_view_logs': True},
    },
)

DEFAULT_ROLES = (
    {
        'code': 'admin', 'name_ar': 'مدير النظام', 'name_en': 'Full Admin', 'summary_ar': 'تحكم كامل في المنصة وكل الصلاحيات.', 'summary_en': 'Full platform control.', 'is_system': True, 'sort_order': 1,
        'permissions': {key: True for key in PERMISSION_KEYS},
    },
    {
        'code': 'support_admin', 'name_ar': 'مسؤول الدعم', 'name_en': 'Support Admin', 'summary_ar': 'إدارة الدعم والتذاكر وسجل العمليات.', 'summary_en': 'Support, tickets, and operational logs.', 'is_system': True, 'sort_order': 10,
        'permissions': {'can_manage_support': True, 'can_view_logs': True, 'can_access_mobile_api': True},
    },
    {
        'code': 'finance_admin', 'name_ar': 'مسؤول المالية', 'name_en': 'Finance Admin', 'summary_ar': 'إدارة الحسابات والاشتراكات والمحافظ.', 'summary_en': 'Finance, subscriptions, and wallet operations.', 'is_system': True, 'sort_order': 20,
        'permissions': {'can_manage_finance': True, 'can_manage_subscriptions': True, 'can_view_logs': True},
    },
    {
        'code': 'integration_admin', 'name_ar': 'مسؤول التكاملات', 'name_en': 'Integration Admin', 'summary_ar': 'إدارة الأجهزة والتكاملات وحالة الخدمات.', 'summary_en': 'Devices, integrations, and service health.', 'is_system': True, 'sort_order': 30,
        'permissions': {'can_manage_devices': True, 'can_manage_integrations': True, 'can_configure_integrations': True, 'can_view_logs': True},
    },
    {
        'code': 'user', 'name_ar': 'مشترك', 'name_en': 'Subscriber', 'summary_ar': 'بوابة المشترك الأساسية.', 'summary_en': 'Default subscriber portal access.', 'is_system': True, 'sort_order': 100,
        'permissions': {'can_access_mobile_api': True},
    },
)
DEFAULT_ROLE_CATALOG = DEFAULT_ROLES[:1] + STAFF_ROLE_PRESETS + DEFAULT_ROLES[1:]
DELETED_ROLE_CODES_SETTING = 'access_control.deleted_role_codes'

PORTAL_PAGES = (
    {'page_key': 'dashboard', 'endpoint': 'main.dashboard', 'label_ar': 'النظرة العامة', 'label_en': 'Overview', 'icon': '🏠', 'group_key': 'portal', 'sort_order': 1, 'is_locked': True},
    {'page_key': 'devices_manage', 'endpoint': 'main.devices_manage', 'label_ar': 'أجهزتي', 'label_en': 'My Devices', 'icon': '🔌', 'group_key': 'portal', 'sort_order': 2},
    {'page_key': 'profile', 'endpoint': 'main.account_profile', 'label_ar': 'الملف الشخصي', 'label_en': 'Profile', 'icon': '👤', 'group_key': 'portal', 'sort_order': 3},
    {'page_key': 'onboarding', 'endpoint': 'main.onboarding_wizard', 'label_ar': 'معالج الإعداد', 'label_en': 'Setup Wizard', 'icon': '🧭', 'group_key': 'portal', 'sort_order': 4},
    {'page_key': 'subscription', 'endpoint': 'main.account_subscription', 'label_ar': 'اشتراكي', 'label_en': 'Subscription', 'icon': '💳', 'group_key': 'portal', 'sort_order': 5},
    {'page_key': 'statistics', 'endpoint': 'main.statistics', 'label_ar': 'الإحصائيات', 'label_en': 'Statistics', 'icon': '📊', 'group_key': 'monitoring', 'sort_order': 10},
    {'page_key': 'reports', 'endpoint': 'main.reports', 'label_ar': 'التقارير', 'label_en': 'Reports', 'icon': '🧾', 'group_key': 'monitoring', 'sort_order': 11},
    {'page_key': 'live_data', 'endpoint': 'main.live_data', 'label_ar': 'البيانات الحية', 'label_en': 'Live Data', 'icon': '📡', 'group_key': 'monitoring', 'sort_order': 12},
    {'page_key': 'loads', 'endpoint': 'main.loads_page', 'label_ar': 'الأحمال', 'label_en': 'Loads', 'icon': '💡', 'group_key': 'monitoring', 'sort_order': 13},
    # v93p — Battery Lab promoted to a top-level portal page on
    # explicit owner request. It surfaces SOC trace, voltage curve,
    # cycles, SOH, AC-IN diagnostics, and the new station-tier
    # generator inference. Locked-by-default like Dashboard so a
    # plan admin can hide it for tiers that shouldn't see it.
    {'page_key': 'battery_lab', 'endpoint': 'main.battery_lab', 'label_ar': 'مختبر البطارية', 'label_en': 'Battery Lab', 'icon': '🔋', 'group_key': 'monitoring', 'sort_order': 13.5},
    {'page_key': 'notifications', 'endpoint': 'main.notifications_settings', 'label_ar': 'الإشعارات', 'label_en': 'Notifications', 'icon': '📲', 'group_key': 'monitoring', 'sort_order': 14},
    {'page_key': 'channels', 'endpoint': 'main.channels', 'label_ar': 'Telegram و SMS', 'label_en': 'Telegram & SMS', 'icon': '🔗', 'group_key': 'monitoring', 'sort_order': 15},
    {'page_key': 'support', 'endpoint': 'main.portal_support', 'label_ar': 'الدعم والمراسلات', 'label_en': 'Support Center', 'icon': '💬', 'group_key': 'monitoring', 'sort_order': 16},
)
PORTAL_ENDPOINT_TO_KEY = {p['endpoint']: p['page_key'] for p in PORTAL_PAGES}
PORTAL_ENDPOINT_TO_KEY.update({
    'main.portal_messages': 'support', 'main.portal_tickets': 'support',
    'energy.dashboard': 'dashboard',
    'devices_routes.devices_manage': 'devices_manage',
    'devices_routes.device_edit': 'devices_manage',
    'devices_routes.device_toggle': 'devices_manage',
    'devices_routes.account_profile': 'profile',
    'devices_routes.onboarding_wizard': 'onboarding',
    'billing.account_subscription': 'subscription',
    'energy.statistics': 'statistics',
    'energy.reports': 'reports',
    'energy.live_data': 'live_data',
    'energy.loads_page': 'loads',
    # v93p — battery_lab endpoint aliases. The route is registered
    # by `devices_routes.battery_lab` and re-exposed via main_compat
    # as `main.battery_lab`, so both names need to map to the same
    # portal page key for active-state highlighting.
    'devices_routes.battery_lab': 'battery_lab',
    'main.battery_lab': 'battery_lab',
    'notifications_routes.notifications_settings': 'notifications',
    'notifications_routes.channels': 'channels',
    'support.portal_support': 'support',
    'support.portal_messages': 'support',
    'support.portal_tickets': 'support',
})


def _parse_permissions(raw: Any) -> dict[str, bool]:
    """Parse a permissions blob (dict or JSON string) into a clean dict.

    Accepts BOTH parent permission keys (e.g. ``can_manage_users``)
    and dot-notation sub keys (e.g. ``users.delete``). Anything else
    is dropped silently to keep storage tight.
    """
    if isinstance(raw, dict):
        return {k: bool(v) for k, v in raw.items() if k in ALL_PERMISSION_KEYS}
    try:
        parsed = json.loads(raw or '{}')
        if isinstance(parsed, dict):
            return {k: bool(v) for k, v in parsed.items() if k in ALL_PERMISSION_KEYS}
    except Exception:
        pass
    return {}


def resolve_effective_permission(stored: dict[str, bool], key: str) -> bool:
    """Resolve a permission key (parent OR sub) against a stored dict.

    Sub-permission semantics:
      • If the parent is False  → the sub is False (no inheritance bypass)
      • If the parent is True and the sub key is missing → True (default ON)
      • If the sub key is explicitly stored → its value wins

    Parent keys just return their stored value (default False).
    """
    if key in PERMISSION_KEYS:
        return bool(stored.get(key, False))
    if key in SUB_PERMISSION_KEYS:
        parent = parent_of_sub(key)
        if not parent:
            return False
        if not bool(stored.get(parent, False)):
            return False
        # Parent ON → sub defaults to ON unless explicitly set False
        if key in stored:
            return bool(stored[key])
        return True
    return False


def permission_catalog(lang: str = 'ar') -> list[dict[str, str]]:
    is_en = (lang or 'ar') == 'en'
    return [{'key': p.key, 'label': p.label_en if is_en else p.label_ar, 'group': p.group_en if is_en else p.group_ar} for p in PERMISSION_CATALOG]


def all_permission_defaults(value: bool = False) -> dict[str, bool]:
    return {key: bool(value) for key in PERMISSION_KEYS}


def role_permissions(role_code: str | None) -> dict[str, bool]:
    code = (role_code or 'user').strip().lower() or 'user'
    if code == 'admin':
        return all_permission_defaults(True)
    row = AppRole.query.filter_by(code=code).first()
    if row:
        if not row.is_active:
            return all_permission_defaults(False)
        perms = all_permission_defaults(False)
        perms.update(_parse_permissions(row.permissions_json))
        return perms
    for role in DEFAULT_ROLE_CATALOG:
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
    return [_FallbackRole(r) for r in DEFAULT_ROLE_CATALOG]


def admin_landing_url(lang: str = 'ar') -> str:
    # Always send admins to the unified command center first.
    # Per-area shortcuts live inside the dashboard itself.
    try:
        return url_for('main.admin_dashboard', lang=lang)
    except Exception:
        return '/admin/dashboard'


def role_label(code: str, lang: str = 'ar') -> str:
    row = AppRole.query.filter_by(code=(code or 'user')).first()
    if row:
        return row.name_en if (lang or 'ar') == 'en' else row.name_ar
    for role in DEFAULT_ROLE_CATALOG:
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
    deleted_role_codes: set[str] = set()
    deleted_row = Setting.query.filter_by(key=DELETED_ROLE_CODES_SETTING).first()
    if deleted_row and deleted_row.value:
        try:
            parsed_deleted = json.loads(deleted_row.value or '[]')
            if isinstance(parsed_deleted, list):
                deleted_role_codes = {str(code).strip().lower() for code in parsed_deleted if str(code).strip()}
        except Exception:
            deleted_role_codes = set()
    for data in DEFAULT_ROLE_CATALOG:
        row = AppRole.query.filter_by(code=data['code']).first()
        if row is None:
            if data['code'] in deleted_role_codes:
                continue
            row = AppRole(code=data['code'], created_at=datetime.utcnow())
            db.session.add(row)
            changed = True
            row.is_active = True
        row.name_ar = row.name_ar or data['name_ar']
        row.name_en = row.name_en or data['name_en']
        row.summary_ar = row.summary_ar or data.get('summary_ar', '')
        row.summary_en = row.summary_en or data.get('summary_en', '')
        row.is_system = bool(data.get('is_system', False))
        row.sort_order = data.get('sort_order', row.sort_order or 100)
        if not row.permissions_json:
            row.permissions_json = json.dumps(data.get('permissions') or {}, ensure_ascii=False)
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
