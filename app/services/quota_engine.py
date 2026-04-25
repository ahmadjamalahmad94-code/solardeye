from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flask import has_request_context

from ..extensions import db
from ..models import AppUser, TenantAccount, TenantQuota


QUOTA_LABELS = {
    'sms_limit': {'ar': 'حد رسائل SMS', 'en': 'SMS limit'},
    'telegram_limit': {'ar': 'حد رسائل Telegram', 'en': 'Telegram limit'},
    'support_cases_limit': {'ar': 'حد طلبات الدعم', 'en': 'Support cases limit'},
    'devices_limit': {'ar': 'حد الأجهزة', 'en': 'Devices limit'},
    'reports_limit': {'ar': 'حد التقارير', 'en': 'Reports limit'},
    'api_calls_limit': {'ar': 'حد استدعاءات API', 'en': 'API calls limit'},
    'storage_limit': {'ar': 'حد التخزين', 'en': 'Storage limit'},
}


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


def quota_label(quota_key: str, lang: str = 'ar') -> str:
    lang = 'en' if str(lang or '').startswith('en') else 'ar'
    key = (quota_key or '').strip()
    return QUOTA_LABELS.get(key, {}).get(lang) or key.replace('_', ' ')


def tenant_for_user(user: AppUser | None) -> TenantAccount | None:
    if not user or getattr(user, 'is_admin', False):
        return None
    tenant = TenantAccount.query.filter_by(owner_user_id=user.id).order_by(TenantAccount.id.asc()).first()
    if tenant:
        return tenant
    return TenantAccount.query.filter_by(display_name=getattr(user, 'username', '')).order_by(TenantAccount.id.asc()).first()


def quota_for_tenant(tenant_id: int | None, quota_key: str) -> TenantQuota | None:
    if not tenant_id or not quota_key:
        return None
    return TenantQuota.query.filter_by(tenant_id=tenant_id, quota_key=quota_key, status='active').order_by(TenantQuota.id.desc()).first()


def check_quota_for_user(user: AppUser | None, quota_key: str, amount: float = 1, *, lang: str = 'ar') -> tuple[bool, str, TenantQuota | None]:
    if not user or getattr(user, 'is_admin', False):
        return True, '', None
    amount = float(amount or 1)
    if amount <= 0:
        return True, '', None
    tenant = tenant_for_user(user)
    quota = quota_for_tenant(getattr(tenant, 'id', None), quota_key)
    if not quota:
        return True, '', None
    limit = float(quota.limit_value or 0)
    used = float(quota.used_value or 0)
    # A zero or negative limit means unlimited only when the row was intentionally left empty.
    if limit <= 0:
        return True, '', quota
    if used + amount > limit:
        exc = QuotaExceeded(quota_key, quota.quota_label or quota_label(quota_key, lang), limit, used, amount)
        return False, exc.message(lang), quota
    return True, '', quota


def consume_quota_for_user(user: AppUser | None, quota_key: str, amount: float = 1, *, lang: str = 'ar', commit: bool = False) -> tuple[bool, str, TenantQuota | None]:
    ok, message, quota = check_quota_for_user(user, quota_key, amount, lang=lang)
    if not ok:
        return False, message, quota
    if quota is not None:
        quota.used_value = float(quota.used_value or 0) + float(amount or 1)
        quota.updated_at = datetime.utcnow()
        if commit:
            db.session.commit()
    return True, '', quota


def consume_or_raise(user: AppUser | None, quota_key: str, amount: float = 1, *, lang: str = 'ar') -> TenantQuota | None:
    ok, message, quota = consume_quota_for_user(user, quota_key, amount, lang=lang, commit=False)
    if not ok:
        limit = float(getattr(quota, 'limit_value', 0) or 0)
        used = float(getattr(quota, 'used_value', 0) or 0)
        label = getattr(quota, 'quota_label', None) or quota_label(quota_key, lang)
        raise QuotaExceeded(quota_key, label, limit, used, amount)
    return quota
