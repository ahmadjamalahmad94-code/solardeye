import json
from datetime import datetime, timedelta

from app.extensions import db
from app.models import AppDevice, AppUser, SubscriptionPlan, TenantAccount, TenantSubscription


def plan_features(plan):
    if not plan or not getattr(plan, 'features_json', None):
        return {}
    try:
        return json.loads(plan.features_json or '{}')
    except Exception:
        return {}


def seed_default_plans():
    defaults = [
        {"code":"basic","name_ar":"الخطة الأساسية","name_en":"Basic","price":10.0,"currency":"USD","duration_days_default":30,"max_devices":1,"sort_order":1,"features_json":json.dumps({"can_manage_devices": True, "can_manage_integrations": True, "can_use_telegram": True, "can_use_sms": False, "can_view_diagnostics": False, "can_view_api_explorer": False, "quota_rules": {"devices_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 1}, "label_ar": "حد الأجهزة", "label_en": "Devices limit"}, "support_cases_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 10}, "label_ar": "حد طلبات الدعم", "label_en": "Support cases limit"}, "telegram_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 50}, "label_ar": "حد رسائل Telegram", "label_en": "Telegram messages limit"}}}, ensure_ascii=False)},
        {"code":"pro","name_ar":"الخطة الاحترافية","name_en":"Pro","price":20.0,"currency":"USD","duration_days_default":90,"max_devices":3,"sort_order":2,"features_json":json.dumps({"can_manage_devices": True, "can_manage_integrations": True, "can_use_telegram": True, "can_use_sms": True, "can_view_diagnostics": False, "can_view_api_explorer": False, "quota_rules": {"devices_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 3}, "label_ar": "حد الأجهزة", "label_en": "Devices limit"}, "support_cases_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 30}, "label_ar": "حد طلبات الدعم", "label_en": "Support cases limit"}, "sms_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 100}, "label_ar": "حد رسائل SMS", "label_en": "SMS messages limit"}, "telegram_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 250}, "label_ar": "حد رسائل Telegram", "label_en": "Telegram messages limit"}}}, ensure_ascii=False)},
        {"code":"platinum","name_ar":"الخطة البلاتينية","name_en":"Platinum","price":30.0,"currency":"USD","duration_days_default":365,"max_devices":10,"sort_order":3,"features_json":json.dumps({"can_manage_devices": True, "can_manage_integrations": True, "can_use_telegram": True, "can_use_sms": True, "can_view_diagnostics": True, "can_view_api_explorer": True, "quota_rules": {"devices_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 10}, "label_ar": "حد الأجهزة", "label_en": "Devices limit"}, "support_cases_limit": {"enabled": True, "unlimited": True, "limits": {}, "label_ar": "حد طلبات الدعم", "label_en": "Support cases limit"}, "sms_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 500}, "label_ar": "حد رسائل SMS", "label_en": "SMS messages limit"}, "telegram_limit": {"enabled": True, "unlimited": True, "limits": {}, "label_ar": "حد رسائل Telegram", "label_en": "Telegram messages limit"}, "api_calls_limit": {"enabled": True, "unlimited": False, "limits": {"monthly": 10000}, "label_ar": "حد استدعاءات API", "label_en": "API calls limit"}}}, ensure_ascii=False)},
    ]
    for item in defaults:
        if not SubscriptionPlan.query.filter_by(code=item['code']).first():
            db.session.add(SubscriptionPlan(**item))
    db.session.commit()


def get_default_plan():
    plan=SubscriptionPlan.query.filter_by(code='basic').first()
    if not plan:
        seed_default_plans()
        plan=SubscriptionPlan.query.filter_by(code='basic').first()
    return plan


def ensure_user_tenant_and_subscription(user, activated_by_user_id=None):
    if not user:
        return None, None
    tenant=None
    if getattr(user,'tenant_id',None):
        tenant=TenantAccount.query.get(user.tenant_id)
    if not tenant:
        tenant=TenantAccount(owner_user_id=user.id, display_name=user.full_name or user.username or "Tenant {}".format(user.id), status='trial')
        db.session.add(tenant)
        db.session.flush()
        user.tenant_id=tenant.id
        db.session.flush()
    plan=get_default_plan()
    if tenant.plan_id is None and plan:
        tenant.plan_id=plan.id
    sub=(TenantSubscription.query.filter_by(tenant_id=tenant.id).order_by(TenantSubscription.created_at.desc()).first())
    if not sub and plan:
        now=datetime.utcnow()
        sub=TenantSubscription(tenant_id=tenant.id, plan_id=plan.id, status='trial', activation_mode='trial', starts_at=now, trial_ends_at=now+timedelta(days=7), ends_at=now+timedelta(days=7), activated_by_user_id=activated_by_user_id, notes='Auto trial')
        db.session.add(sub)
    try:
        from .quota_engine import apply_plan_quotas_to_tenant
        if plan:
            apply_plan_quotas_to_tenant(tenant, plan, commit=False)
    except Exception:
        pass
    for device in AppDevice.query.filter_by(owner_user_id=user.id).all():
        if getattr(device,'tenant_id',None) != tenant.id:
            device.tenant_id=tenant.id
    db.session.commit()
    return tenant, sub


def current_subscription_for_user(user):
    if not user or not getattr(user,'tenant_id',None):
        return None
    return TenantSubscription.query.filter_by(tenant_id=user.tenant_id).order_by(TenantSubscription.created_at.desc()).first()


def compute_subscription_status(sub):
    if not sub: return 'expired'
    if sub.status == 'cancelled': return 'cancelled'
    if sub.ends_at and sub.ends_at < datetime.utcnow(): return 'expired'
    return sub.status or 'active'


def user_has_active_subscription(user):
    return compute_subscription_status(current_subscription_for_user(user)) in ('trial','active')


def allowed_device_limit(user):
    if not user or not getattr(user,'tenant_id',None):
        return 0
    tenant=TenantAccount.query.get(user.tenant_id)
    if not tenant: return 0
    if tenant.max_devices_override is not None: return tenant.max_devices_override
    plan=SubscriptionPlan.query.get(tenant.plan_id) if tenant.plan_id else None
    return (plan.max_devices if plan else 0) or 0


def feature_enabled_for_user(user, feature_key):
    if not user or not getattr(user,'tenant_id',None):
        return False
    tenant=TenantAccount.query.get(user.tenant_id)
    if not tenant or not tenant.plan_id: return False
    plan=SubscriptionPlan.query.get(tenant.plan_id)
    return bool(plan_features(plan).get(feature_key, False))


def _create_subscription_ledger_entry(tenant, plan, days, sub, activated_by_user_id=None, is_renewal=False):
    """Auto-generate a WalletLedger entry for a subscription activation/renewal."""
    try:
        from app.models import WalletLedger
    except Exception:
        return None
    price = float(getattr(plan, 'price', 0) or 0)
    if price <= 0:
        return None
    try:
        prefix = 'REN' if is_renewal else 'SUB'
        plan_lbl = plan.name_en or plan.name_ar or plan.code or 'plan-{}'.format(plan.id)
        category = 'renewal' if is_renewal else 'subscription'
        note_action = 'Renewed' if is_renewal else 'Activated'
        ref = '{}-{}-{}'.format(prefix, tenant.id, (sub.id if sub else 0))
        note = '{} {} ({}d) - auto-generated from subscription'.format(note_action, plan_lbl, days)
        ledger = WalletLedger(
            tenant_id=tenant.id,
            actor_user_id=activated_by_user_id,
            entry_type='debit',
            amount=price,
            currency=(getattr(plan, 'currency', None) or 'USD'),
            note=note,
            reference=ref,
            category=category,
            is_recurring=False,
        )
        db.session.add(ledger)
        return ledger
    except Exception:
        return None


def activate_tenant_subscription(tenant, plan, days, activated_by_user_id=None, notes=''):
    """v82: this helper is now a thin wrapper around the canonical
    `billing_engine` lifecycle actions.

    Behaviour is preserved for every existing caller:
      * First-time / unrelated-plan activations create a fresh sub
        row charging the full plan price and use the `ACT-…` ledger
        reference.
      * Repeats on the same plan are routed through `renew(...)` so
        they get the new stacking semantics + the `REN-…` reference.
        Net effect for finance is the same charge, but the reference
        token now distinguishes activation from renewal cleanly.
    """
    prior = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant.id)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )
    is_renewal = bool(
        prior and prior.plan_id == plan.id
        and prior.status in ('active', 'expired')
    )
    from .billing_engine import activate as _activate, renew as _renew
    if is_renewal:
        result = _renew(
            tenant, plan, days=days,
            actor_user_id=activated_by_user_id, commit=True,
        )
    else:
        result = _activate(
            tenant, plan, days=days,
            actor_user_id=activated_by_user_id, notes=notes,
            activation_mode='manual', commit=True,
        )
    sub_id = result.subscription_id
    return TenantSubscription.query.get(sub_id) if sub_id else None
