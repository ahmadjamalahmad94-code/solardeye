from __future__ import annotations

import re
import json

# Heavy v10.1 split blueprint. The route logic is intentionally moved out of
# main.py while importing legacy helpers/services from main during the migration
# window. This keeps behavior stable while main.py shrinks safely.
from flask import Blueprint
from .main import *  # noqa: F401,F403 - transitional legacy dependency bridge
from . import main as _legacy_main

for _legacy_name in dir(_legacy_main):
    if _legacy_name.startswith('_') and not _legacy_name.startswith('__'):
        globals()[_legacy_name] = getattr(_legacy_main, _legacy_name)

from ..services.rbac import PERMISSION_KEYS, available_roles, permission_catalog, portal_pages, role_label, role_permissions, save_user_portal_visibility, seed_access_control, user_portal_visibility_map
from ..services.quota_engine import apply_plan_quotas_to_tenant, ensure_plan_quotas_for_tenant
from ..services.location_catalog import countries_for_template

users_bp = Blueprint('users_routes', __name__)

def _country_flag(code: str | None) -> str:
    code = (code or '').strip().upper()
    if len(code) != 2 or not code.isalpha():
        return '🌐'
    return ''.join(chr(127397 + ord(char)) for char in code)


def _phone_country_options(lang: str | None = None) -> list[dict]:
    is_en = (lang or _lang()) == 'en'
    rows = []
    for country in countries_for_template():
        code = (country.get('code') or '').strip()
        rows.append({
            **country,
            'flag': _country_flag(code),
            'label': country.get('name_en') if is_en else country.get('name_ar'),
        })
    return rows


def _is_admin_role_code(role: str | None) -> bool:
    role = (role or '').strip().lower()
    return role not in {'', 'user', 'subscriber', 'customer'}


def _staff_role_codes() -> set[str]:
    seed_access_control(commit=True)
    codes = {'admin'}
    for role in available_roles():
        code = (getattr(role, 'code', '') or '').strip().lower()
        if code and _is_admin_role_code(code):
            codes.add(code)
    return codes


def _is_staff_account(user) -> bool:
    role = (getattr(user, 'role', '') or '').strip().lower()
    return bool(user and (getattr(user, 'is_admin', False) or role in _staff_role_codes() or _is_admin_role_code(role)))


def _parse_user_permission_overrides(user) -> dict[str, bool]:
    try:
        parsed = json.loads(getattr(user, 'permissions_json', None) or '{}')
        if isinstance(parsed, dict):
            return {key: bool(parsed.get(key)) for key in PERMISSION_KEYS if key in parsed}
    except Exception:
        pass
    return {}


def _assigned_support_for_staff(user) -> tuple[list[dict], list[dict]]:
    thread_rows = []
    for thread in InternalMailThread.query.filter_by(assigned_admin_user_id=user.id).order_by(InternalMailThread.updated_at.desc(), InternalMailThread.id.desc()).all():
        tenant = TenantAccount.query.get(thread.tenant_id) if thread.tenant_id else None
        owner = AppUser.query.get(thread.created_by_user_id or getattr(tenant, 'owner_user_id', None))
        thread_rows.append({'thread': thread, 'tenant': tenant, 'owner': owner})
    ticket_rows = []
    for ticket in SupportTicket.query.filter_by(assigned_admin_user_id=user.id).order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).all():
        tenant = TenantAccount.query.get(ticket.tenant_id) if ticket.tenant_id else None
        owner = AppUser.query.get(ticket.opened_by_user_id or getattr(tenant, 'owner_user_id', None))
        ticket_rows.append({'ticket': ticket, 'tenant': tenant, 'owner': owner})
    return thread_rows, ticket_rows


def _staff_activity_rows(user) -> list[dict]:
    rows = []
    for item in AdminActivityLog.query.order_by(AdminActivityLog.created_at.desc(), AdminActivityLog.id.desc()).limit(120).all():
        if item.actor_user_id == user.id or item.target_id == user.id:
            rows.append({'item': item, 'actor': AppUser.query.get(item.actor_user_id) if item.actor_user_id else None})
    return rows[:30]


def _admin_staff_profile(user, tab: str):
    actor = _active_user()
    lang = _lang()
    is_en = lang == 'en'
    tab = tab if tab in {'profile', 'permissions', 'support', 'activity'} else 'profile'
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'save_staff_profile':
            username = (request.form.get('username') or user.username or '').strip()
            other = AppUser.query.filter(AppUser.username == username, AppUser.id != user.id).first()
            role = (request.form.get('role') or user.role or 'user').strip().lower()
            if other:
                flash('اسم المستخدم مستخدم من قبل.' if lang != 'en' else 'Username is already in use.', 'danger')
            elif actor and actor.id == user.id and role in {'user', 'subscriber', 'customer'}:
                flash('لا يمكنك إزالة نفسك من فريق الإدارة.' if lang != 'en' else 'You cannot remove your own staff access.', 'warning')
            else:
                user.username = username
                user.full_name = (request.form.get('full_name') or '').strip()
                user.email = (request.form.get('email') or '').strip()
                user.phone_country_code = (request.form.get('phone_country_code') or '').strip() or None
                user.phone_number = (request.form.get('phone_number') or '').strip() or None
                user.country = (request.form.get('country') or '').strip() or None
                user.city = (request.form.get('city') or '').strip() or None
                user.preferred_language = (request.form.get('preferred_language') or 'ar').strip() or 'ar'
                user.role = role or 'user'
                user.is_admin = _is_admin_role_code(user.role)
                if actor and actor.id == user.id:
                    user.is_active = True
                else:
                    user.is_active = request.form.get('is_active') == 'on'
                if request.form.get('password'):
                    user.password_hash = generate_password_hash((request.form.get('password') or '').strip())
                db.session.commit()
                _admin_write_log('staff.profile', f'Updated staff profile for user #{user.id}', 'app_user', user.id, {'user_id': user.id, 'role': user.role})
                flash('تم تحديث بيانات عضو الإدارة.' if lang != 'en' else 'Staff profile updated.', 'success')
            return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, staff=1, tab='profile'))
        if action == 'save_staff_permissions':
            if (user.role or '').strip().lower() == 'admin':
                user.permissions_json = json.dumps({key: True for key in PERMISSION_KEYS}, ensure_ascii=False)
                db.session.commit()
                flash('حساب المدير الكامل يملك كل الصلاحيات دائماً.' if lang != 'en' else 'Full admin keeps all permissions.', 'info')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, staff=1, tab='permissions'))
            perms = {key: request.form.get(key) == 'on' for key in PERMISSION_KEYS}
            if actor and actor.id == user.id and not perms.get('can_manage_users'):
                flash('لا يمكنك إزالة صلاحية إدارة المستخدمين من حسابك الحالي.' if lang != 'en' else 'You cannot remove user-management from your current account.', 'warning')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, staff=1, tab='permissions'))
            user.permissions_json = json.dumps(perms, ensure_ascii=False)
            user.is_admin = _is_admin_role_code(user.role)
            db.session.commit()
            _admin_write_log('staff.permissions', f'Updated staff permissions for user #{user.id}', 'app_user', user.id, {'user_id': user.id, 'permissions': perms})
            flash('تم تحديث صلاحيات عضو الإدارة.' if lang != 'en' else 'Staff permissions updated.', 'success')
            return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, staff=1, tab='permissions'))

    assigned_threads, assigned_tickets = _assigned_support_for_staff(user)
    role_perms = role_permissions(user.role)
    user_overrides = _parse_user_permission_overrides(user)
    permission_rows = []
    for perm in permission_catalog(lang):
        inherited = bool(role_perms.get(perm['key']))
        has_override = perm['key'] in user_overrides
        permission_rows.append({
            **perm,
            'inherited': inherited,
            'checked': bool(user_overrides[perm['key']]) if has_override else inherited,
            'has_override': has_override,
        })
    return render_template(
        'admin_staff_profile.html',
        user_obj=user,
        tab=tab,
        roles=available_roles(),
        role_label=role_label,
        permission_rows=permission_rows,
        assigned_threads=assigned_threads,
        assigned_tickets=assigned_tickets,
        activity_rows=_staff_activity_rows(user),
        country_options=_phone_country_options(lang),
        ui_lang=lang,
        is_full_admin=(user.role or '').strip().lower() == 'admin',
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
        activity_label=_activity_summary_label,
    )

def _quota_key_options(lang: str = 'ar'):
    is_en = (lang or 'ar') == 'en'
    rows = [
        {
            'key': 'sms_limit',
            'label_ar': 'حد رسائل SMS',
            'label_en': 'SMS messages limit',
            'description_ar': 'عدد رسائل SMS المسموح للمشترك استخدامها ضمن الفترة المحددة.',
            'description_en': 'How many SMS messages this subscriber can use during the selected period.',
            'unit_ar': 'رسالة',
            'unit_en': 'messages',
            'default_limit': 50,
            'reset_period': 'monthly',
        },
        {
            'key': 'telegram_limit',
            'label_ar': 'حد رسائل Telegram',
            'label_en': 'Telegram messages limit',
            'description_ar': 'عدد رسائل أو تنبيهات Telegram المسموحة لهذا المشترك.',
            'description_en': 'Allowed Telegram messages or alerts for this subscriber.',
            'unit_ar': 'رسالة',
            'unit_en': 'messages',
            'default_limit': 100,
            'reset_period': 'monthly',
        },
        {
            'key': 'devices_limit',
            'label_ar': 'حد الأجهزة',
            'label_en': 'Devices limit',
            'description_ar': 'أقصى عدد أجهزة يستطيع المشترك إضافتها أو ربطها.',
            'description_en': 'Maximum number of devices the subscriber can add or connect.',
            'unit_ar': 'جهاز',
            'unit_en': 'devices',
            'default_limit': 1,
            'reset_period': 'manual',
        },
        {
            'key': 'reports_limit',
            'label_ar': 'حد التقارير',
            'label_en': 'Reports limit',
            'description_ar': 'عدد التقارير أو ملفات التصدير المسموحة خلال الفترة.',
            'description_en': 'Allowed report or export generation during the period.',
            'unit_ar': 'تقرير',
            'unit_en': 'reports',
            'default_limit': 10,
            'reset_period': 'monthly',
        },
        {
            'key': 'support_cases_limit',
            'label_ar': 'حد طلبات الدعم',
            'label_en': 'Support cases limit',
            'description_ar': 'عدد طلبات الدعم التي يمكن فتحها خلال الفترة.',
            'description_en': 'How many support cases can be opened during the period.',
            'unit_ar': 'طلب',
            'unit_en': 'cases',
            'default_limit': 5,
            'reset_period': 'monthly',
        },
        {
            'key': 'api_calls_limit',
            'label_ar': 'حد استدعاءات API',
            'label_en': 'API calls limit',
            'description_ar': 'عدد استدعاءات API المسموح بها لهذا المشترك.',
            'description_en': 'Allowed API calls for this subscriber.',
            'unit_ar': 'استدعاء',
            'unit_en': 'calls',
            'default_limit': 1000,
            'reset_period': 'monthly',
        },
        {
            'key': 'storage_limit',
            'label_ar': 'حد التخزين',
            'label_en': 'Storage limit',
            'description_ar': 'حجم التخزين أو الملفات المسموح بها لهذا المشترك.',
            'description_en': 'Storage or file allowance for this subscriber.',
            'unit_ar': 'ميجابايت',
            'unit_en': 'MB',
            'default_limit': 500,
            'reset_period': 'manual',
        },
        {
            'key': 'custom',
            'label_ar': 'كوتا مخصصة',
            'label_en': 'Custom quota',
            'description_ar': 'استخدمها فقط عندما تحتاج حدًا خاصًا غير موجود في القائمة.',
            'description_en': 'Use only when you need a special limit that is not listed.',
            'unit_ar': 'وحدة',
            'unit_en': 'units',
            'default_limit': 0,
            'reset_period': 'manual',
        },
    ]
    normalized = []
    for row in rows:
        item = dict(row)
        item['label'] = item['label_en'] if is_en else item['label_ar']
        item['description'] = item['description_en'] if is_en else item['description_ar']
        item['unit'] = item['unit_en'] if is_en else item['unit_ar']
        normalized.append(item)
    return normalized


def _quota_option_map(lang: str = 'ar'):
    return {row['key']: row for row in _quota_key_options(lang)}


def _activity_summary_label(item, lang: str = 'ar') -> str:
    raw = (getattr(item, 'summary', None) or getattr(item, 'action', None) or '').strip()
    if (lang or 'ar') == 'en':
        return raw or 'Activity update'
    patterns = [
        ('Added finance entry', 'تمت إضافة حركة مالية'),
        ('Updated mail thread', 'تم تحديث محادثة دعم'),
        ('Updated ticket', 'تم تحديث تذكرة دعم'),
        ('Updated subscription', 'تم تعديل الاشتراك'),
        ('Updated profile', 'تم تعديل بيانات الحساب'),
        ('Created quota', 'تم إنشاء كوتا'),
        ('Updated quota', 'تم تحديث كوتا'),
        ('Created support case', 'تم إنشاء حالة دعم'),
        ('Admin updated support message', 'تم تحديث رسالة دعم'),
        ('Admin updated support ticket', 'تم تحديث تذكرة دعم'),
        ('Bulk action', 'تم تنفيذ إجراء جماعي'),
    ]
    out = raw or 'عملية على الحساب'
    for en, ar in patterns:
        out = out.replace(en, ar)
    out = out.replace('for tenant', 'للمشترك').replace('thread', 'محادثة').replace('ticket', 'تذكرة')
    return out


def _subscription_day_info(subscription) -> dict:
    if not subscription:
        return {'days_left': None, 'target': None, 'status': 'none'}
    today = datetime.utcnow().date()
    status = (getattr(subscription, 'status', '') or '').strip()
    target = getattr(subscription, 'trial_ends_at', None) if status == 'trial' else getattr(subscription, 'ends_at', None)
    if target is None:
        target = getattr(subscription, 'ends_at', None) or getattr(subscription, 'trial_ends_at', None)
    if not target:
        return {'days_left': None, 'target': None, 'status': status or 'unknown'}
    days = (target.date() - today).days
    return {'days_left': days, 'target': target, 'status': 'expired' if days < 0 else status}


def _portal_rows_for_user(user, lang: str = 'ar') -> list[dict]:
    visibility = user_portal_visibility_map(getattr(user, 'id', None))
    rows = []
    for page in portal_pages(include_locked=True):
        key = getattr(page, 'page_key', None) if not isinstance(page, dict) else page.get('page_key')
        rows.append({
            'page_key': key,
            'endpoint': getattr(page, 'endpoint', '') if not isinstance(page, dict) else page.get('endpoint',''),
            'label': (getattr(page, 'label_en', '') if (lang or 'ar') == 'en' else getattr(page, 'label_ar', '')) if not isinstance(page, dict) else (page.get('label_en') if (lang or 'ar') == 'en' else page.get('label_ar')),
            'label_ar': getattr(page, 'label_ar', '') if not isinstance(page, dict) else page.get('label_ar',''),
            'label_en': getattr(page, 'label_en', '') if not isinstance(page, dict) else page.get('label_en',''),
            'icon': getattr(page, 'icon', '•') if not isinstance(page, dict) else page.get('icon','•'),
            'is_locked': bool(getattr(page, 'is_locked', False) if not isinstance(page, dict) else page.get('is_locked', False)),
            'is_visible': bool(visibility.get(key, True)),
        })
    return rows


@users_bp.route('/admin/users/<int:user_id>', methods=['GET', 'POST'])
def admin_user_profile(user_id: int):
    requested_tab = (request.args.get('tab') or 'profile').strip()
    guard = _admin_guard('can_manage_support' if requested_tab == 'support' else 'can_manage_users')
    if guard:
        return guard
    user = AppUser.query.filter_by(id=user_id).first_or_404()
    if _is_staff_account(user):
        return _admin_staff_profile(user, requested_tab)
    actor = _active_user()
    tenant, subscription = ensure_user_tenant_and_subscription(user, activated_by_user_id=getattr(actor, 'id', None))
    if tenant and getattr(tenant, 'plan_id', None):
        ensure_plan_quotas_for_tenant(tenant, SubscriptionPlan.query.get(tenant.plan_id), commit=True)

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'save_profile':
            username = (request.form.get('username') or user.username or '').strip()
            other = AppUser.query.filter(AppUser.username == username, AppUser.id != user.id).first()
            if other:
                flash('اسم المستخدم مستخدم من قبل.', 'danger')
            else:
                user.username = username
                user.full_name = (request.form.get('full_name') or '').strip()
                user.email = (request.form.get('email') or '').strip()
                user.country = (request.form.get('country') or '').strip() or None
                user.city = (request.form.get('city') or '').strip() or None
                user.timezone = (request.form.get('timezone') or 'Asia/Hebron').strip() or 'Asia/Hebron'
                user.preferred_language = (request.form.get('preferred_language') or 'ar').strip() or 'ar'
                user.is_active = request.form.get('is_active') == 'on'
                role = (request.form.get('role') or user.role or 'user').strip().lower()
                user.role = role or 'user'
                user.is_admin = _is_admin_role_code(user.role)
                if request.form.get('password'):
                    user.password_hash = generate_password_hash((request.form.get('password') or '').strip())
                db.session.commit()
                _admin_write_log('user.profile', f'Updated profile for user #{user.id}', 'app_user', user.id, {'user_id': user.id, 'tenant_id': tenant.id})
                flash('تم تحديث البيانات الشخصية.', 'success')
        elif action == 'save_subscription':
            plan_id = int(request.form.get('plan_id') or 0) or None
            sub_status = (request.form.get('subscription_status') or getattr(subscription, 'status', 'trial')).strip()
            tenant.status = (request.form.get('tenant_status') or tenant.status or 'trial').strip()
            tenant.max_devices_override = int(request.form.get('max_devices_override') or 0) or None
            selected_plan = None
            if plan_id:
                tenant.plan_id = plan_id
                selected_plan = SubscriptionPlan.query.get(plan_id)
                if subscription:
                    subscription.plan_id = plan_id
                if selected_plan:
                    apply_plan_quotas_to_tenant(tenant, selected_plan, commit=False)
            if subscription:
                subscription.status = sub_status
                subscription.starts_at = _parse_dt_local(request.form.get('starts_at')) or subscription.starts_at
                subscription.ends_at = _parse_dt_local(request.form.get('ends_at')) or subscription.ends_at
                subscription.trial_ends_at = _parse_dt_local(request.form.get('trial_ends_at')) or subscription.trial_ends_at
                subscription.notes = (request.form.get('subscription_notes') or subscription.notes or '').strip() or None
            db.session.commit()
            _admin_write_log('subscription.profile', f'Updated subscription for tenant #{tenant.id}', 'tenant_subscription', getattr(subscription, 'id', None), {'tenant_id': tenant.id, 'user_id': user.id})
            flash('تم تحديث بيانات الاشتراك وتطبيق حدود الخطة تلقائيًا.', 'success')
        elif action == 'finance_entry':
            amount = float(request.form.get('amount') or 0)
            if amount:
                entry = WalletLedger(tenant_id=tenant.id, actor_user_id=getattr(actor, 'id', None), entry_type=(request.form.get('entry_type') or 'credit').strip(), amount=amount, currency=(request.form.get('currency') or 'USD').strip() or 'USD', note=(request.form.get('note') or '').strip() or None, reference=(request.form.get('reference') or '').strip() or None)
                db.session.add(entry)
                db.session.commit()
                _admin_write_log('finance.profile', f'Added finance entry for tenant #{tenant.id}', 'wallet_ledger', entry.id, {'tenant_id': tenant.id, 'user_id': user.id, 'entry_type': entry.entry_type})
                flash('تمت إضافة حركة مالية للمشترك.', 'success')
        elif action == 'quota_delete':
            lang = _lang()
            quota_id = int(request.form.get('quota_id') or 0)
            quota = TenantQuota.query.filter_by(id=quota_id, tenant_id=tenant.id).first() if quota_id else None
            if not quota:
                flash('لم يتم العثور على الحد المطلوب حذفه.' if lang != 'en' else 'Quota was not found.', 'warning')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, tab='quotas'))
            deleted_key = quota.quota_key
            db.session.delete(quota)
            db.session.commit()
            _admin_write_log('quota.profile.delete', f'Deleted quota #{quota_id}', 'tenant_quota', quota_id, {'tenant_id': tenant.id, 'user_id': user.id, 'quota_key': deleted_key})
            flash('تم حذف الحد بنجاح.' if lang != 'en' else 'Quota deleted successfully.', 'success')
        elif action == 'quota_entry':
            lang = _lang()
            options = _quota_option_map(lang)
            preset_key = (request.form.get('quota_key_preset') or '').strip()
            custom_key = (request.form.get('quota_key_custom') or request.form.get('quota_key') or '').strip()
            quota_key = custom_key if preset_key == 'custom' else preset_key
            quota_key = (quota_key or '').strip().lower().replace(' ', '_')
            quota_key = re.sub(r'[^a-z0-9_\-]', '', quota_key)
            if not quota_key:
                flash('اختر نوع الكوتا أو اكتب مفتاحًا مخصصًا صحيحًا.' if lang != 'en' else 'Choose a quota type or enter a valid custom key.', 'warning')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, tab='quotas'))
            try:
                limit_value = float(request.form.get('limit_value') or 0)
            except Exception:
                flash('قيمة الحد غير صحيحة. أدخل رقمًا واضحًا مثل 50 أو 100.' if lang != 'en' else 'Invalid limit value. Enter a clear number like 50 or 100.', 'danger')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, tab='quotas'))
            if limit_value < 0:
                flash('الحد لا يمكن أن يكون رقمًا سالبًا.' if lang != 'en' else 'Limit cannot be negative.', 'danger')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=lang, tab='quotas'))
            selected = options.get(preset_key) or options.get(quota_key) or {}
            quota_id = int(request.form.get('quota_id') or 0)
            quota = TenantQuota.query.filter_by(id=quota_id, tenant_id=tenant.id).first() if quota_id else None
            if quota is None:
                quota = TenantQuota.query.filter_by(tenant_id=tenant.id, quota_key=quota_key).first()
            created = False
            if quota is None:
                quota = TenantQuota(tenant_id=tenant.id, quota_key=quota_key, used_value=0)
                db.session.add(quota)
                created = True
            quota.quota_key = quota_key
            quota.quota_label = (request.form.get('quota_label') or selected.get('label_ar') or selected.get('label') or quota_key).strip()
            quota.limit_value = limit_value
            quota.status = (request.form.get('status') or quota.status or 'active').strip()
            quota.reset_period = (request.form.get('reset_period') or selected.get('reset_period') or quota.reset_period or 'manual').strip()
            quota.source = 'override'
            quota.source_plan_id = getattr(tenant, 'plan_id', None)
            quota.is_unlimited = False
            notes = (request.form.get('notes') or '').strip()
            quota.notes = notes or (selected.get('description_ar') if lang != 'en' else selected.get('description_en')) or quota.notes
            db.session.commit()
            _admin_write_log('quota.profile.create' if created else 'quota.profile.update', ('Created' if created else 'Updated') + f' quota #{quota.id}', 'tenant_quota', quota.id, {'tenant_id': tenant.id, 'user_id': user.id, 'quota_key': quota.quota_key})
            flash('تم إنشاء الكوتا بنجاح.' if created and lang != 'en' else ('تم تحديث الكوتا بنجاح.' if lang != 'en' else ('Quota created successfully.' if created else 'Quota updated successfully.')), 'success')
        elif action == 'portal_visibility':
            visible_keys = set(request.form.getlist('visible_pages'))
            save_user_portal_visibility(user.id, visible_keys)
            db.session.commit()
            _admin_write_log('subscriber.portal_visibility', f'Updated portal visibility for user #{user.id}', 'app_user', user.id, {'tenant_id': tenant.id, 'user_id': user.id, 'visible_pages': sorted(visible_keys)})
            flash('تم تحديث الصفحات الظاهرة لهذا المشترك.', 'success')
        elif action == 'mail_reply':
            thread = InternalMailThread.query.get(int(request.form.get('thread_id') or 0))
            body = (request.form.get('body') or '').strip()
            belongs_to_user = bool(thread and (
                (getattr(thread, 'tenant_id', None) and thread.tenant_id == tenant.id) or
                getattr(thread, 'created_by_user_id', None) == user.id
            ))
            if thread and belongs_to_user:
                if not thread.tenant_id:
                    thread.tenant_id = tenant.id
                if not thread.created_by_user_id:
                    thread.created_by_user_id = user.id
                old_status = (thread.status or 'open').strip()
                new_status = (request.form.get('status') or old_status or 'open').strip()
                if old_status in ('closed', 'resolved'):
                    flash('هذه المحادثة مغلقة ومجمّدة، لا يمكن إضافة ردود جديدة.', 'warning')
                    return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support') + f'#case-mail-{thread.id}')
                old_assignee_id = thread.assigned_admin_user_id
                assignment_only = bool(request.form.get('assignment_only'))
                requested_assignee_id = int(request.form.get('assigned_admin_user_id') or 0) or None
                if assignment_only and not requested_assignee_id:
                    flash('اختر المدير المسؤول أولًا ثم اضغط اعتماد المدير.', 'warning')
                    return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support') + f'#case-mail-{thread.id}')
                final_assignee_id = requested_assignee_id or thread.assigned_admin_user_id or getattr(actor, 'id', None)
                thread_messages = InternalMailMessage.query.filter_by(thread_id=thread.id).order_by(InternalMailMessage.created_at.asc(), InternalMailMessage.id.asc()).all()
                assigned_admin = AppUser.query.get(final_assignee_id) if final_assignee_id else None
                if body and not assignment_only:
                    db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', is_internal_note=bool(request.form.get('is_internal_note')), body=body))
                if assignment_only:
                    if final_assignee_id and (old_assignee_id != final_assignee_id or not _support_has_assignment_notice_for(thread_messages, assigned_admin)):
                        db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=final_assignee_id, sender_scope='admin', is_internal_note=False, body=_assignment_notice_body('mail', assigned_admin)))
                        flash('تم اعتماد المدير المسؤول وإشعار المشترك.', 'success')
                    elif final_assignee_id:
                        flash('هذا المدير معتمد مسبقًا لهذه المحادثة.', 'info')
                elif final_assignee_id and old_assignee_id != final_assignee_id and not _support_already_has_assignment_notice(thread_messages):
                    db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=final_assignee_id, sender_scope='admin', is_internal_note=False, body=_assignment_notice_body('mail', assigned_admin)))
                if new_status in ('closed', 'resolved') and old_status not in ('closed', 'resolved') and not body:
                    db.session.add(InternalMailMessage(thread_id=thread.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', is_internal_note=False, body='تم إغلاق المحادثة بعد حل الطلب.'))
                thread.status = new_status
                thread.assigned_admin_user_id = final_assignee_id
                thread.last_reply_at = datetime.utcnow()
                thread.updated_at = datetime.utcnow()
                upsert_support_case('message', thread, None if (bool(request.form.get('is_internal_note')) and body) else 'admin')
                notify_user(user.id, source_type='message', source_id=thread.id, tenant_id=thread.tenant_id, title='تحديث على رسالة الدعم', message=thread.subject, direct_url=portal_case_url('message', thread.id, _lang()))
                audit_case('message', thread.id, getattr(actor, 'id', None), 'message.admin_update', 'Admin updated support message', {'status': thread.status}, commit=False)
                db.session.commit()
                _admin_write_log('mail.profile.reply', f'Updated mail thread #{thread.id}', 'internal_mail_thread', thread.id, {'tenant_id': tenant.id, 'user_id': user.id, 'status': thread.status})
                flash('تم إرسال الرد وتحديث المحادثة.', 'success')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support') + f'#case-mail-{thread.id}')
            flash('تعذر إرسال الرد: المحادثة غير مرتبطة بهذا المشترك.', 'danger')
            return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support'))
        elif action == 'ticket_reply':
            ticket = SupportTicket.query.get(int(request.form.get('ticket_id') or 0))
            body = (request.form.get('body') or '').strip()
            belongs_to_user = bool(ticket and (
                (getattr(ticket, 'tenant_id', None) and ticket.tenant_id == tenant.id) or
                getattr(ticket, 'opened_by_user_id', None) == user.id
            ))
            if ticket and belongs_to_user:
                if not ticket.tenant_id:
                    ticket.tenant_id = tenant.id
                if not ticket.opened_by_user_id:
                    ticket.opened_by_user_id = user.id
                old_status = (ticket.status or 'open').strip()
                new_status = (request.form.get('status') or old_status or 'open').strip()
                if old_status in ('closed', 'resolved'):
                    flash('هذه التذكرة مغلقة ومجمّدة، لا يمكن إضافة ردود جديدة.', 'warning')
                    return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support') + f'#case-ticket-{ticket.id}')
                old_assignee_id = ticket.assigned_admin_user_id
                assignment_only = bool(request.form.get('assignment_only'))
                requested_assignee_id = int(request.form.get('assigned_admin_user_id') or 0) or None
                if assignment_only and not requested_assignee_id:
                    flash('اختر المدير المسؤول أولًا ثم اضغط اعتماد المدير.', 'warning')
                    return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support') + f'#case-ticket-{ticket.id}')
                final_assignee_id = requested_assignee_id or ticket.assigned_admin_user_id or getattr(actor, 'id', None)
                ticket_messages = SupportTicketMessage.query.filter_by(ticket_id=ticket.id).order_by(SupportTicketMessage.created_at.asc(), SupportTicketMessage.id.asc()).all()
                assigned_admin = AppUser.query.get(final_assignee_id) if final_assignee_id else None
                if body and not assignment_only:
                    db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', is_internal_note=bool(request.form.get('is_internal_note')), body=body))
                if assignment_only:
                    if final_assignee_id and (old_assignee_id != final_assignee_id or not _support_has_assignment_notice_for(ticket_messages, assigned_admin)):
                        db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=final_assignee_id, sender_scope='admin', is_internal_note=False, body=_assignment_notice_body('ticket', assigned_admin)))
                        flash('تم اعتماد المدير المسؤول وإشعار المشترك.', 'success')
                    elif final_assignee_id:
                        flash('هذا المدير معتمد مسبقًا لهذه التذكرة.', 'info')
                elif final_assignee_id and old_assignee_id != final_assignee_id and not _support_already_has_assignment_notice(ticket_messages):
                    db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=final_assignee_id, sender_scope='admin', is_internal_note=False, body=_assignment_notice_body('ticket', assigned_admin)))
                if new_status in ('closed', 'resolved') and old_status not in ('closed', 'resolved') and not body:
                    db.session.add(SupportTicketMessage(ticket_id=ticket.id, sender_user_id=getattr(actor, 'id', None), sender_scope='admin', is_internal_note=False, body='تم إغلاق التذكرة بعد حل المشكلة.'))
                ticket.status = new_status
                ticket.assigned_admin_user_id = final_assignee_id
                ticket.last_reply_at = datetime.utcnow()
                ticket.updated_at = datetime.utcnow()
                upsert_support_case('ticket', ticket, None if (bool(request.form.get('is_internal_note')) and body) else 'admin')
                notify_user(user.id, source_type='ticket', source_id=ticket.id, tenant_id=ticket.tenant_id, title='تحديث على التذكرة', message=ticket.subject, direct_url=portal_case_url('ticket', ticket.id, _lang()))
                audit_case('ticket', ticket.id, getattr(actor, 'id', None), 'ticket.admin_update', 'Admin updated support ticket', {'status': ticket.status}, commit=False)
                db.session.commit()
                _admin_write_log('ticket.profile.reply', f'Updated ticket #{ticket.id}', 'support_ticket', ticket.id, {'tenant_id': tenant.id, 'user_id': user.id, 'status': ticket.status})
                flash('تم إرسال الرد وتحديث التذكرة.', 'success')
                return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support') + f'#case-ticket-{ticket.id}')
            flash('تعذر إرسال الرد: التذكرة غير مرتبطة بهذا المشترك.', 'danger')
            return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab='support'))

        return redirect(url_for('main.admin_user_profile', user_id=user.id, lang=_lang(), tab=request.args.get('tab') or 'profile'))

    payload = _admin_user_payload(user)
    payload['quota_key_options'] = _quota_key_options(_lang())
    payload['portal_page_rows'] = _portal_rows_for_user(user, _lang())
    payload['subscription_day_info'] = _subscription_day_info(subscription)
    tab = (request.args.get('tab') or 'profile').strip()
    is_en = _lang() == 'en'
    canned_replies = CannedReply.query.filter_by(is_active=True).order_by(CannedReply.title.asc()).all()
    canned_rows = [{'item': r, 'suggested_status': _suggest_status_for_canned(r.title, r.body)} for r in canned_replies]
    return render_template(
        'admin_user_profile.html',
        user_obj=user,
        tab=tab,
        admin_users=AppUser.query.filter_by(is_admin=True).order_by(AppUser.username.asc()).all(),
        role_badge=_role_badge,
        canned_replies=canned_replies,
        canned_rows=canned_rows,
        labels=_support_label_maps(is_en),
        status_options=['open', 'assigned', 'in_progress', 'waiting_user', 'resolved', 'closed'],
        priority_options=['low', 'normal', 'high', 'urgent'],
        ui_lang=_lang(),
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
        activity_label=_activity_summary_label,
        **payload,
    )


@users_bp.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    # v7.2.1: Subscribers CRM is the primary daily management screen.
    # Keep legacy POST compatibility for old bookmarked forms.
    if request.method == 'POST':
        return admin_users_legacy()
    return redirect(url_for('main.admin_subscribers', lang=_lang()))


@users_bp.route('/admin/users/legacy', methods=['GET', 'POST'])
def admin_users_legacy():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    actor = _active_user()
    if request.method == 'POST':
        action = (request.form.get('bulk_action') or '').strip()
        selected_ids = []
        for raw in request.form.getlist('user_ids'):
            try:
                selected_ids.append(int(raw))
            except Exception:
                pass
        selected_ids = sorted(set(selected_ids))
        if not selected_ids:
            flash('اختر مستخدمًا واحدًا على الأقل لتنفيذ العملية.', 'warning')
            return redirect(url_for('users_routes.admin_team', lang=_lang()))
        if action == 'quick_permissions':
            user = AppUser.query.filter(AppUser.id.in_(selected_ids)).first()
            if not user or not _is_staff_account(user):
                flash('عضو الإدارة غير موجود.', 'warning')
                return redirect(url_for('users_routes.admin_team', lang=_lang()))
            role = (request.form.get('role') or user.role or 'user').strip().lower()
            if actor and actor.id == user.id and role in {'user', 'subscriber', 'customer'}:
                flash('لا يمكنك إزالة نفسك من فريق الإدارة.', 'warning')
                return redirect(url_for('users_routes.admin_team', lang=_lang()))
            if role == 'admin':
                perms = {key: True for key in PERMISSION_KEYS}
            else:
                perms = {key: request.form.get(key) == 'on' for key in PERMISSION_KEYS}
            if actor and actor.id == user.id and not perms.get('can_manage_users'):
                flash('لا يمكنك إزالة صلاحية إدارة المستخدمين من حسابك الحالي.', 'warning')
                return redirect(url_for('users_routes.admin_team', lang=_lang()))
            user.role = role or user.role or 'user'
            user.is_admin = _is_admin_role_code(user.role)
            user.permissions_json = json.dumps(perms, ensure_ascii=False)
            db.session.commit()
            _admin_write_log('staff.quick_permissions', f'Quick permissions update for user #{user.id}', 'app_user', user.id, {'user_id': user.id, 'role': user.role, 'permissions': perms})
            flash('تم تحديث صلاحيات عضو الإدارة.', 'success')
            return redirect(url_for('users_routes.admin_team', lang=_lang()))
        if action == 'send_staff_message':
            recipient = AppUser.query.filter(AppUser.id.in_(selected_ids)).first()
            subject = (request.form.get('subject') or '').strip()
            body = (request.form.get('body') or '').strip()
            priority = (request.form.get('priority') or 'normal').strip()
            if not recipient or not _is_staff_account(recipient):
                flash('اختر عضو إدارة صحيح لإرسال الرسالة.', 'warning')
                return redirect(url_for('users_routes.admin_team', lang=_lang()))
            if not subject or not body:
                flash('عنوان الرسالة ونصها مطلوبان.', 'warning')
                return redirect(url_for('users_routes.admin_team', lang=_lang()))
            thread = InternalMailThread(
                created_by_user_id=getattr(actor, 'id', None),
                assigned_admin_user_id=recipient.id,
                subject=subject,
                category='admin_internal',
                priority=priority if priority in {'normal', 'important', 'urgent'} else 'normal',
                status='open',
                last_reply_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(thread)
            db.session.flush()
            db.session.add(InternalMailMessage(
                thread_id=thread.id,
                sender_user_id=getattr(actor, 'id', None),
                sender_scope='admin',
                is_internal_note=True,
                body=body,
            ))
            try:
                notify_user(recipient.id, source_type='message', source_id=thread.id, tenant_id=None, title='رسالة داخلية من الإدارة', message=subject, direct_url=url_for('main.admin_user_profile', user_id=recipient.id, lang=_lang(), staff=1, tab='support') + f'#case-mail-{thread.id}')
            except Exception:
                pass
            db.session.commit()
            _admin_write_log('staff.message', f'Sent internal staff message #{thread.id}', 'internal_mail_thread', thread.id, {'recipient_user_id': recipient.id})
            flash('تم إرسال الرسالة الداخلية.', 'success')
            return redirect(url_for('users_routes.admin_team', lang=_lang()))
        if action not in {'activate', 'disable', 'soft_delete', 'hard_delete', 'remove_staff'}:
            flash('إجراء جماعي غير معروف.', 'warning')
            return redirect(url_for('users_routes.admin_team', lang=_lang()))
        changed = 0
        skipped = 0
        if action == 'hard_delete':
            try:
                create_backup(reason='pre_bulk_hard_delete', upload_drive=False)
            except Exception as exc:
                current_app.logger.warning('Pre-bulk-delete backup skipped: %s', exc)
        for user in AppUser.query.filter(AppUser.id.in_(selected_ids)).all():
            if actor and user.id == actor.id and action in {'disable', 'soft_delete', 'hard_delete'}:
                skipped += 1
                continue
            if action == 'hard_delete':
                if user.is_admin or user.username == current_app.config.get('ADMIN_USERNAME'):
                    skipped += 1
                    continue
                _hard_delete_user_account(user, getattr(actor, 'id', None))
                changed += 1
            elif action == 'activate':
                user.is_active = True
                changed += 1
            elif action == 'disable':
                user.is_active = False
                changed += 1
            elif action == 'remove_staff':
                if (actor and user.id == actor.id) or (user.role or '').strip().lower() == 'admin' or user.username == current_app.config.get('ADMIN_USERNAME'):
                    skipped += 1
                    continue
                user.role = 'user'
                user.is_admin = False
                user.is_active = False
                user.permissions_json = None
                changed += 1
            elif action == 'soft_delete':
                if user.is_admin or _is_staff_account(user):
                    skipped += 1
                    continue
                # حذف آمن: نخفي الحساب بدون كسر علاقات التذاكر والمالية والأجهزة.
                user.is_active = False
                if not (user.username or '').startswith('deleted_'):
                    user.username = f'deleted_{user.id}_{user.username or "user"}'[:80]
                if user.email and not user.email.startswith('deleted_'):
                    user.email = f'deleted_{user.id}_{user.email}'[:120]
                changed += 1
        db.session.commit()
        _admin_write_log('users.bulk', f'Bulk action {action} on users', 'app_user', None, {'action': action, 'user_ids': selected_ids, 'changed': changed, 'skipped': skipped})
        flash(f'تم تنفيذ العملية على {changed} مستخدم. تم تخطي {skipped}.', 'success')
        return redirect(url_for('users_routes.admin_team', lang=_lang()))

    seed_access_control(commit=True)
    staff_roles = _staff_role_codes()
    all_users = AppUser.query.order_by(AppUser.created_at.desc(), AppUser.id.desc()).all()
    users = [user for user in all_users if _is_staff_account(user)]
    devices = AppDevice.query.order_by(AppDevice.name.asc(), AppDevice.id.asc()).all()
    device_map = {}
    for dev in devices:
        device_map.setdefault(dev.owner_user_id, []).append(dev)

    support_map = {}
    for thread in InternalMailThread.query.filter(InternalMailThread.status != 'closed').all():
        if thread.assigned_admin_user_id:
            support_map.setdefault(thread.assigned_admin_user_id, {'mail': 0, 'tickets': 0})['mail'] += 1
    for ticket in SupportTicket.query.filter(SupportTicket.status != 'closed').all():
        if ticket.assigned_admin_user_id:
            support_map.setdefault(ticket.assigned_admin_user_id, {'mail': 0, 'tickets': 0})['tickets'] += 1

    stats = {
        'total': len(users),
        'roles': len(staff_roles),
        'active': sum(1 for user in users if user.is_active),
        'disabled': sum(1 for user in users if not user.is_active),
        'with_support': sum(1 for user in users if support_map.get(user.id, {}).get('mail', 0) or support_map.get(user.id, {}).get('tickets', 0)),
    }
    permission_rows_by_user = {}
    catalog = permission_catalog(_lang())
    for user in users:
        role_perms = role_permissions(user.role)
        overrides = _parse_user_permission_overrides(user)
        permission_rows_by_user[user.id] = [
            {
                **perm,
                'checked': bool(overrides[perm['key']]) if perm['key'] in overrides else bool(role_perms.get(perm['key'])),
            }
            for perm in catalog
        ]

    return render_template(
        'admin_users.html',
        users=users,
        stats=stats,
        device_map=device_map,
        support_map=support_map,
        role_badge=_role_badge,
        role_label=role_label,
        permission_rows_by_user=permission_rows_by_user,
        ui_lang=_lang(),
    )


@users_bp.route('/admin/team', methods=['GET', 'POST'])
def admin_team():
    return admin_users_legacy()


@users_bp.route('/admin/users/new', methods=['GET', 'POST'])
def admin_user_create():
    guard = _admin_guard()
    if guard:
        return guard
    seed_access_control(commit=True)
    default_role = (request.args.get('role') or 'assistant_manager').strip().lower() or 'assistant_manager'
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        country = request.form.get('country', '').strip()
        city = request.form.get('city', '').strip()
        phone_country_code = request.form.get('phone_country_code', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        role = (request.form.get('role', 'user') or 'user').strip().lower()
        is_active = request.form.get('is_active') == 'on'
        if not username or not password:
            flash('اسم المستخدم وكلمة المرور مطلوبان.', 'warning')
        elif AppUser.query.filter_by(username=username).first():
            flash('اسم المستخدم مستخدم من قبل.', 'danger')
        else:
            user = AppUser(
                username=username,
                password_hash=generate_password_hash(password),
                full_name=full_name,
                email=email,
                country=country or None,
                city=city or None,
                phone_country_code=phone_country_code or None,
                phone_number=phone_number or None,
                role=role or 'user',
                preferred_device_type='deye',
                is_active=is_active,
                is_admin=_is_admin_role_code(role),
            )
            db.session.add(user)
            db.session.commit()
            flash('تم إنشاء المستخدم بنجاح.', 'success')
            target = 'main.admin_subscribers' if role in {'user', 'subscriber', 'customer'} else 'users_routes.admin_team'
            return redirect(url_for(target, lang=_lang()))

    return render_template('admin_user_form.html', mode='create', user_obj=None, default_role=default_role, country_options=_phone_country_options(_lang()), ui_lang=_lang())


@users_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
def admin_user_edit(user_id: int):
    guard = _admin_guard()
    if guard:
        return guard
    seed_access_control(commit=True)
    user = AppUser.query.filter_by(id=user_id).first_or_404()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        country = request.form.get('country', '').strip()
        city = request.form.get('city', '').strip()
        phone_country_code = request.form.get('phone_country_code', '').strip()
        phone_number = request.form.get('phone_number', '').strip()
        role = (request.form.get('role', 'user') or 'user').strip().lower()
        is_active = request.form.get('is_active') == 'on'
        other = AppUser.query.filter(AppUser.username == username, AppUser.id != user.id).first()
        if not username:
            flash('اسم المستخدم مطلوب.', 'warning')
        elif other:
            flash('اسم المستخدم مستخدم من قبل.', 'danger')
        else:
            user.username = username
            user.full_name = full_name
            user.email = email
            user.country = country or None
            user.city = city or None
            user.phone_country_code = phone_country_code or None
            user.phone_number = phone_number or None
            user.role = role or 'user'
            user.is_admin = _is_admin_role_code(user.role)
            user.is_active = is_active
            if password:
                user.password_hash = generate_password_hash(password)
            db.session.commit()
            flash('تم تحديث المستخدم بنجاح.', 'success')
            target = 'main.admin_subscribers' if role in {'user', 'subscriber', 'customer'} else 'users_routes.admin_team'
            return redirect(url_for(target, lang=_lang()))

    return render_template('admin_user_form.html', mode='edit', user_obj=user, default_role=user.role or 'user', country_options=_phone_country_options(_lang()), ui_lang=_lang())


@users_bp.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
def admin_user_toggle(user_id: int):
    guard = _admin_guard()
    if guard:
        return guard
    user = AppUser.query.filter_by(id=user_id).first_or_404()
    if user.username == current_app.config.get('ADMIN_USERNAME') and user.is_admin:
        flash('لا يمكن تعطيل مدير النظام الأساسي.', 'warning')
        return _safe_admin_redirect()
    user.is_active = not bool(user.is_active)
    db.session.commit()
    flash('تم تحديث حالة المستخدم.', 'success')
    return _safe_admin_redirect()


@users_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def admin_user_delete(user_id: int):
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    actor = _active_user()
    user = AppUser.query.filter_by(id=user_id).first_or_404()
    if actor and user.id == actor.id:
        flash('لا يمكن حذف حسابك الحالي.', 'warning')
        return _safe_admin_redirect()
    if user.is_admin or user.username == current_app.config.get('ADMIN_USERNAME'):
        flash('لا يمكن حذف مدير النظام الأساسي.', 'warning')
        return _safe_admin_redirect()
    try:
        # Keep a local restore point before destructive deletion.
        create_backup(reason=f'pre_delete_user_{user.id}', upload_drive=False)
    except Exception as exc:
        current_app.logger.warning('Pre-delete backup skipped: %s', exc)
    try:
        result = _hard_delete_user_account(user, getattr(actor, 'id', None))
        db.session.commit()
        _admin_write_log('user.hard_delete', f'Hard deleted user account', 'app_user', None, result)
        flash('تم حذف المستخدم نهائيًا.', 'success')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Hard delete user failed: %s', exc)
        user = AppUser.query.filter_by(id=user_id).first()
        if user:
            user.is_active = False
            db.session.commit()
        flash('تعذر حذف المستخدم بسبب بيانات مرتبطة. تم تعطيله بدلًا من ذلك حفاظًا على السجلات.', 'warning')
    return _safe_admin_redirect()


@users_bp.route('/admin/system-logs')
def admin_system_logs():
    guard = _admin_guard()
    if guard:
        return guard
    settings = load_settings()
    health = _service_health_snapshot(settings)
    service_logs = SyncLog.query.order_by(SyncLog.created_at.desc()).limit(200).all()
    event_logs = EventLog.query.order_by(EventLog.created_at.desc()).limit(200).all()
    notification_logs = NotificationLog.query.order_by(NotificationLog.created_at.desc()).limit(200).all()
    return render_template(
        'admin_system_logs.html',
        settings=settings,
        health=health,
        service_logs=service_logs,
        event_logs=event_logs,
        notification_logs=notification_logs,
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
        activity_label=_activity_summary_label,
        ui_lang=_lang(),
    )


@users_bp.route('/admin/activity-log')
def admin_activity_log():
    guard = _admin_guard('can_view_logs')
    if guard:
        return guard
    rows = []
    for item in AdminActivityLog.query.order_by(AdminActivityLog.created_at.desc(), AdminActivityLog.id.desc()).all():
        actor = AppUser.query.get(item.actor_user_id) if item.actor_user_id else None
        rows.append({'item': item, 'actor': actor})
    return render_template('admin_activity_log.html', rows=rows, ui_lang=_lang())


@users_bp.route('/admin/roles')
def admin_roles():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    admin_users = AppUser.query.filter_by(is_admin=True).order_by(AppUser.username.asc()).all()
    role_matrix = [
        {'role': 'super_admin', 'summary': 'Full platform control', 'perms': ['manage_users','manage_plans','manage_devices','manage_integrations','manage_finance','manage_support','view_logs']},
        {'role': 'finance_admin', 'summary': 'Billing, quotas, and credits', 'perms': ['manage_finance','manage_subscriptions','view_logs']},
        {'role': 'support_admin', 'summary': 'Internal mail, tickets, and replies', 'perms': ['manage_support','reply_messages','view_logs']},
        {'role': 'integration_admin', 'summary': 'Devices, APIs, and service health', 'perms': ['manage_devices','manage_integrations','view_logs']},
    ]
    return render_template('admin_roles.html', admin_users=admin_users, role_matrix=role_matrix, ui_lang=_lang())
