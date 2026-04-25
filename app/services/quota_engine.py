from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..extensions import db
from ..models import AppUser, SubscriptionPlan, TenantAccount, TenantQuota


QUOTA_CATALOG = [
    {
        'key': 'sms_limit',
        'label_ar': 'حد رسائل SMS',
        'label_en': 'SMS messages limit',
        'description_ar': 'عدد رسائل SMS المسموح استخدامها خلال الفترة المحددة.',
        'description_en': 'Allowed SMS messages during the selected period.',
        'unit_ar': 'رسالة',
        'unit_en': 'messages',
        'default_monthly': 50,
    },
    {
        'key': 'telegram_limit',
        'label_ar': 'حد رسائل Telegram',
        'label_en': 'Telegram messages limit',
        'description_ar': 'عدد رسائل أو تنبيهات Telegram المسموحة خلال الفترة.',
        'description_en': 'Allowed Telegram messages or alerts during the period.',
        'unit_ar': 'رسالة',
        'unit_en': 'messages',
        'default_monthly': 50,
    },
    {
        'key': 'support_cases_limit',
        'label_ar': 'حد طلبات الدعم',
        'label_en': 'Support cases limit',
        'description_ar': 'عدد طلبات الدعم التي يمكن فتحها خلال الفترة.',
        'description_en': 'Allowed support cases during the period.',
        'unit_ar': 'طلب',
        'unit_en': 'cases',
        'default_monthly': 50,
    },
    {
        'key': 'devices_limit',
        'label_ar': 'حد الأجهزة',
        'label_en': 'Devices limit',
        'description_ar': 'أقصى عدد أجهزة يمكن إضافتها أو ربطها.',
        'description_en': 'Maximum devices that can be added or linked.',
        'unit_ar': 'جهاز',
        'unit_en': 'devices',
        'default_monthly': 1,
    },
    {
        'key': 'reports_limit',
        'label_ar': 'حد التقارير',
        'label_en': 'Reports limit',
        'description_ar': 'عدد التقارير أو ملفات التصدير المسموحة.',
        'description_en': 'Allowed generated reports or exports.',
        'unit_ar': 'تقرير',
        'unit_en': 'reports',
        'default_monthly': 10,
    },
    {
        'key': 'api_calls_limit',
        'label_ar': 'حد استدعاءات API',
        'label_en': 'API calls limit',
        'description_ar': 'عدد استدعاءات API المسموحة لهذا المشترك.',
        'description_en': 'Allowed API calls for this subscriber.',
        'unit_ar': 'استدعاء',
        'unit_en': 'calls',
        'default_monthly': 1000,
    },
    {
        'key': 'storage_limit',
        'label_ar': 'حد التخزين',
        'label_en': 'Storage limit',
        'description_ar': 'حجم التخزين أو الملفات المسموحة.',
        'description_en': 'Storage or file allowance.',
        'unit_ar': 'ميجابايت',
        'unit_en': 'MB',
        'default_monthly': 500,
    },
]

QUOTA_LABELS = {item['key']: {'ar': item['label_ar'], 'en': item['label_en']} for item in QUOTA_CATALOG}
PERIODS = ['daily', 'weekly', 'monthly', 'yearly', 'manual']
PLAN_PERIODS = ['daily', 'monthly', 'yearly']


class QuotaExceeded(Exception):
    def __init__(self, quota_key: str, label: str, limit: float, used: float, requested: float):
        self.quota_key = quota_key
        self.label = label
        self.limit = float(limit or 0)
        self.used = float(used or 0)
        self.requested = float(requested or 0)
        super().__init__(self.message('ar'))

    def message(self, lang: str = 'ar') -> str:
        if str(lang or '').startswith('en'):
            return f'{self.label} quota is exhausted. Used {self.used:g} of {self.limit:g}; requested {self.requested:g} more.'
        return f'انتهى الحد المسموح لـ {self.label}. المستخدم {self.used:g} من {self.limit:g}، والمطلوب {self.requested:g} إضافية.'


def _lang(lang: str = 'ar') -> str:
    return 'en' if str(lang or '').startswith('en') else 'ar'


def quota_catalog(lang: str = 'ar') -> list[dict[str, Any]]:
    is_en = _lang(lang) == 'en'
    rows = []
    for item in QUOTA_CATALOG:
        row = dict(item)
        row['label'] = item['label_en'] if is_en else item['label_ar']
        row['description'] = item['description_en'] if is_en else item['description_ar']
        row['unit'] = item['unit_en'] if is_en else item['unit_ar']
        rows.append(row)
    return rows


def quota_label(quota_key: str, lang: str = 'ar') -> str:
    lang = _lang(lang)
    key = (quota_key or '').strip()
    return QUOTA_LABELS.get(key, {}).get(lang) or key.replace('_', ' ')


def quota_description(quota_key: str, lang: str = 'ar') -> str:
    lang = _lang(lang)
    for item in QUOTA_CATALOG:
        if item['key'] == quota_key:
            return item['description_en'] if lang == 'en' else item['description_ar']
    return ''


def tenant_for_user(user: AppUser | None) -> TenantAccount | None:
    if not user or getattr(user, 'is_admin', False):
        return None
    tenant = TenantAccount.query.filter_by(owner_user_id=user.id).order_by(TenantAccount.id.asc()).first()
    if tenant:
        return tenant
    if getattr(user, 'tenant_id', None):
        return TenantAccount.query.get(user.tenant_id)
    return TenantAccount.query.filter_by(display_name=getattr(user, 'username', '')).order_by(TenantAccount.id.asc()).first()


def quotas_for_tenant(tenant_id: int | None, quota_key: str | None = None) -> list[TenantQuota]:
    if not tenant_id:
        return []
    q = TenantQuota.query.filter_by(tenant_id=tenant_id)
    if quota_key:
        q = q.filter_by(quota_key=quota_key)
    return q.order_by(TenantQuota.quota_key.asc(), TenantQuota.reset_period.asc(), TenantQuota.id.asc()).all()



def effective_quota_rows(tenant_id: int | None, quota_key: str) -> list[TenantQuota]:
    rows = [q for q in quotas_for_tenant(tenant_id, quota_key) if (q.status or 'active') == 'active']
    # A subscriber-level override/manual row should replace plan-generated rows
    # for the same key. This keeps plan defaults clean while allowing per-user exceptions.
    overrides = [q for q in rows if (getattr(q, 'source', None) or 'manual') != 'plan']
    return overrides or rows

def quota_for_tenant(tenant_id: int | None, quota_key: str) -> TenantQuota | None:
    rows = [q for q in quotas_for_tenant(tenant_id, quota_key) if (q.status or 'active') == 'active']
    return rows[-1] if rows else None


def _quota_is_unlimited(q: TenantQuota) -> bool:
    return bool(getattr(q, 'is_unlimited', False)) or (q.reset_period or '').lower() == 'unlimited' or (float(q.limit_value or 0) <= 0 and 'unlimited' in (q.notes or '').lower())


def check_quota_for_user(user: AppUser | None, quota_key: str, amount: float = 1, *, lang: str = 'ar') -> tuple[bool, str, TenantQuota | None]:
    if not user or getattr(user, 'is_admin', False):
        return True, '', None
    amount = float(amount or 1)
    if amount <= 0:
        return True, '', None
    tenant = tenant_for_user(user)
    rows = effective_quota_rows(getattr(tenant, 'id', None), quota_key)
    if not rows:
        return True, '', None
    for quota in rows:
        if _quota_is_unlimited(quota):
            continue
        limit = float(quota.limit_value or 0)
        used = float(quota.used_value or 0)
        if limit <= 0 or used + amount > limit:
            exc = QuotaExceeded(quota_key, quota.quota_label or quota_label(quota_key, lang), limit, used, amount)
            return False, exc.message(lang), quota
    return True, '', rows[0]


def consume_quota_for_user(user: AppUser | None, quota_key: str, amount: float = 1, *, lang: str = 'ar', commit: bool = False) -> tuple[bool, str, TenantQuota | None]:
    ok, message, first_quota = check_quota_for_user(user, quota_key, amount, lang=lang)
    if not ok:
        return False, message, first_quota
    tenant = tenant_for_user(user)
    rows = effective_quota_rows(getattr(tenant, 'id', None), quota_key)
    for quota in rows:
        if _quota_is_unlimited(quota):
            continue
        quota.used_value = float(quota.used_value or 0) + float(amount or 1)
        quota.updated_at = datetime.utcnow()
    if rows and commit:
        db.session.commit()
    return True, '', (rows[0] if rows else None)


def consume_or_raise(user: AppUser | None, quota_key: str, amount: float = 1, *, lang: str = 'ar') -> TenantQuota | None:
    ok, message, quota = consume_quota_for_user(user, quota_key, amount, lang=lang, commit=False)
    if not ok:
        limit = float(getattr(quota, 'limit_value', 0) or 0)
        used = float(getattr(quota, 'used_value', 0) or 0)
        label = getattr(quota, 'quota_label', None) or quota_label(quota_key, lang)
        raise QuotaExceeded(quota_key, label, limit, used, amount)
    return quota


def _load_features(plan: SubscriptionPlan | None) -> dict[str, Any]:
    if not plan or not getattr(plan, 'features_json', None):
        return {}
    try:
        return json.loads(plan.features_json or '{}') or {}
    except Exception:
        return {}


def plan_quota_rules(plan: SubscriptionPlan | None) -> dict[str, Any]:
    features = _load_features(plan)
    rules = features.get('quota_rules') or {}
    return rules if isinstance(rules, dict) else {}


def parse_plan_quota_rules_from_form(form) -> dict[str, Any]:
    rules: dict[str, Any] = {}
    for item in QUOTA_CATALOG:
        key = item['key']
        enabled = form.get(f'quota_enabled_{key}') == 'on'
        unlimited = form.get(f'quota_unlimited_{key}') == 'on'
        limits = {}
        for period in PLAN_PERIODS:
            raw = (form.get(f'quota_{period}_{key}') or '').strip()
            if raw:
                try:
                    value = float(raw)
                except Exception:
                    value = 0
                if value > 0:
                    limits[period] = value
        if enabled or unlimited or limits:
            rules[key] = {
                'enabled': bool(enabled),
                'unlimited': bool(unlimited),
                'limits': limits,
                'label_ar': item['label_ar'],
                'label_en': item['label_en'],
                'description_ar': item['description_ar'],
                'description_en': item['description_en'],
            }
    return rules


def merge_features_with_quota_rules(base_features: dict[str, Any], rules: dict[str, Any]) -> str:
    features = dict(base_features or {})
    features['quota_rules'] = rules or {}
    return json.dumps(features, ensure_ascii=False)


def plan_quota_rows_for_template(plan: SubscriptionPlan | None, lang: str = 'ar') -> list[dict[str, Any]]:
    rules = plan_quota_rules(plan)
    rows = []
    for item in quota_catalog(lang):
        rule = rules.get(item['key'], {})
        rows.append({
            'meta': item,
            'rule': rule,
            'enabled': bool(rule.get('enabled')),
            'unlimited': bool(rule.get('unlimited')),
            'daily': rule.get('limits', {}).get('daily', ''),
            'monthly': rule.get('limits', {}).get('monthly', ''),
            'yearly': rule.get('limits', {}).get('yearly', ''),
        })
    return rows


def apply_plan_quotas_to_tenant(tenant: TenantAccount | None, plan: SubscriptionPlan | None, *, commit: bool = False) -> list[TenantQuota]:
    if not tenant or not plan:
        return []
    rules = plan_quota_rules(plan)
    touched: list[TenantQuota] = []
    now = datetime.utcnow()
    for item in QUOTA_CATALOG:
        key = item['key']
        rule = rules.get(key) or {}
        # Do not delete manual/override rows; only manage rows previously created from a plan.
        if not rule or not rule.get('enabled'):
            continue
        periods = []
        if rule.get('unlimited'):
            periods.append(('unlimited', 0.0, True))
        else:
            for period, limit in (rule.get('limits') or {}).items():
                try:
                    limit_value = float(limit or 0)
                except Exception:
                    limit_value = 0
                if period in PLAN_PERIODS and limit_value > 0:
                    periods.append((period, limit_value, False))
        for period, limit_value, is_unlimited in periods:
            quota = TenantQuota.query.filter_by(tenant_id=tenant.id, quota_key=key, reset_period=period, source='plan').first()
            if not quota:
                quota = TenantQuota(tenant_id=tenant.id, quota_key=key, reset_period=period, used_value=0, source='plan')
                db.session.add(quota)
            quota.quota_label = rule.get('label_ar') or item['label_ar']
            quota.limit_value = float(limit_value or 0)
            quota.status = 'active'
            quota.source = 'plan'
            quota.source_plan_id = plan.id
            quota.is_unlimited = bool(is_unlimited)
            quota.notes = 'من الخطة: ' + (plan.name_ar or plan.code)
            quota.updated_at = now
            touched.append(quota)
    if commit:
        db.session.commit()
    return touched


def apply_plan_quotas_to_plan_subscribers(plan: SubscriptionPlan | None, *, commit: bool = False) -> int:
    if not plan:
        return 0
    tenants = TenantAccount.query.filter_by(plan_id=plan.id).all()
    count = 0
    for tenant in tenants:
        apply_plan_quotas_to_tenant(tenant, plan, commit=False)
        count += 1
    if commit:
        db.session.commit()
    return count


def quota_summary_rows(tenant_id: int | None, lang: str = 'ar') -> list[dict[str, Any]]:
    rows = []
    for q in quotas_for_tenant(tenant_id):
        limit = float(q.limit_value or 0)
        used = float(q.used_value or 0)
        unlimited = _quota_is_unlimited(q)
        percent = 0 if unlimited or limit <= 0 else round((used / limit) * 100, 1)
        rows.append({
            'quota': q,
            'label': q.quota_label or quota_label(q.quota_key, lang),
            'description': quota_description(q.quota_key, lang),
            'limit': limit,
            'used': used,
            'remaining': '∞' if unlimited else max(limit - used, 0),
            'percent': percent,
            'is_unlimited': unlimited,
            'source_label': quota_source_label(q, lang),
        })
    return rows


def quota_source_label(q: TenantQuota, lang: str = 'ar') -> str:
    lang = _lang(lang)
    source = (getattr(q, 'source', None) or 'manual').strip()
    if source == 'plan':
        return 'From plan' if lang == 'en' else 'من الخطة'
    if source == 'override':
        return 'Subscriber override' if lang == 'en' else 'معدل لهذا المشترك'
    return 'Custom' if lang == 'en' else 'مخصص'
