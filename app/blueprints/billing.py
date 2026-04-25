from __future__ import annotations

# Heavy v10.1 split blueprint. The route logic is intentionally moved out of
# main.py while importing legacy helpers/services from main during the migration
# window. This keeps behavior stable while main.py shrinks safely.
from flask import Blueprint
from .main import *  # noqa: F401,F403 - transitional legacy dependency bridge
from . import main as _legacy_main

for _legacy_name in dir(_legacy_main):
    if _legacy_name.startswith('_') and not _legacy_name.startswith('__'):
        globals()[_legacy_name] = getattr(_legacy_main, _legacy_name)

from ..services.quota_engine import (
    apply_plan_quotas_to_plan_subscribers,
    apply_plan_quotas_to_tenant,
    ensure_plan_quotas_for_tenant,
    merge_features_with_quota_rules,
    parse_plan_quota_rules_from_form,
    plan_quota_rows_for_template,
    quota_summary_rows,
)

billing_bp = Blueprint('billing', __name__)

@billing_bp.route('/admin/plans')
def admin_plans():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    return render_template('admin_plans_phase1a.html', plans=plans, ui_lang=_lang())


@billing_bp.route('/admin/plans/new', methods=['GET','POST'])
def admin_plan_create():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    plan = None
    if request.method == 'POST':
        plan = SubscriptionPlan(
            code=request.form.get('code','').strip(),
            name_ar=request.form.get('name_ar','').strip(),
            name_en=request.form.get('name_en','').strip(),
            price=float(request.form.get('price') or 0),
            currency=request.form.get('currency','USD').strip() or 'USD',
            duration_days_default=int(request.form.get('duration_days_default') or 30),
            max_devices=int(request.form.get('max_devices') or 1),
            is_active=request.form.get('is_active') == 'on',
            sort_order=int(request.form.get('sort_order') or 0),
            features_json=merge_features_with_quota_rules({
                'can_manage_devices': request.form.get('can_manage_devices') == 'on',
                'can_manage_integrations': request.form.get('can_manage_integrations') == 'on',
                'can_use_telegram': request.form.get('can_use_telegram') == 'on',
                'can_use_sms': request.form.get('can_use_sms') == 'on',
                'can_view_diagnostics': request.form.get('can_view_diagnostics') == 'on',
                'can_view_api_explorer': request.form.get('can_view_api_explorer') == 'on',
            }, parse_plan_quota_rules_from_form(request.form)),
        )
        db.session.add(plan)
        db.session.commit()
        flash('تم إنشاء الخطة بنجاح', 'success')
        return redirect(url_for('main.admin_plans', lang=_lang()))
    return render_template('admin_plan_form_phase1a.html', plan=plan, plan_quota_rows=plan_quota_rows_for_template(plan, _lang()), ui_lang=_lang())


@billing_bp.route('/admin/plans/<int:plan_id>/edit', methods=['GET','POST'])
def admin_plan_edit(plan_id):
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    plan = SubscriptionPlan.query.get_or_404(plan_id)
    if request.method == 'POST':
        plan.code=request.form.get('code','').strip()
        plan.name_ar=request.form.get('name_ar','').strip()
        plan.name_en=request.form.get('name_en','').strip()
        plan.price=float(request.form.get('price') or 0)
        plan.currency=request.form.get('currency','USD').strip() or 'USD'
        plan.duration_days_default=int(request.form.get('duration_days_default') or 30)
        plan.max_devices=int(request.form.get('max_devices') or 1)
        plan.is_active=request.form.get('is_active') == 'on'
        plan.sort_order=int(request.form.get('sort_order') or 0)
        plan.features_json=merge_features_with_quota_rules({
            'can_manage_devices': request.form.get('can_manage_devices') == 'on',
            'can_manage_integrations': request.form.get('can_manage_integrations') == 'on',
            'can_use_telegram': request.form.get('can_use_telegram') == 'on',
            'can_use_sms': request.form.get('can_use_sms') == 'on',
            'can_view_diagnostics': request.form.get('can_view_diagnostics') == 'on',
            'can_view_api_explorer': request.form.get('can_view_api_explorer') == 'on',
        }, parse_plan_quota_rules_from_form(request.form))
        apply_plan_quotas_to_plan_subscribers(plan, commit=False)
        db.session.commit()
        flash('تم تحديث الخطة وحدود الكوتا للمشتركين المرتبطين بها', 'success')
        return redirect(url_for('main.admin_plans', lang=_lang()))
    return render_template('admin_plan_form_phase1a.html', plan=plan, plan_quota_rows=plan_quota_rows_for_template(plan, _lang()), ui_lang=_lang())


@billing_bp.route('/admin/subscribers')
def admin_subscribers():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    rows=[]
    users=AppUser.query.filter_by(is_admin=False).order_by(AppUser.created_at.desc(), AppUser.id.desc()).all()
    plans = {p.id: p for p in SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()}
    stats = {'total': 0, 'active': 0, 'trial': 0, 'expired': 0, 'suspended': 0, 'disabled': 0}
    now = datetime.utcnow()
    for user in users:
        tenant, sub = ensure_user_tenant_and_subscription(user)
        status = (sub.status if sub else getattr(tenant, 'status', 'trial')) or 'trial'
        stats['total'] += 1
        if not user.is_active:
            stats['disabled'] += 1
        if status in stats:
            stats[status] += 1
        plan = plans.get(sub.plan_id) if sub and sub.plan_id else plans.get(getattr(tenant, 'plan_id', None))
        days_left = None
        if sub and sub.ends_at:
            days_left = (sub.ends_at.date() - now.date()).days
        rows.append({'user':user,'tenant':tenant,'subscription':sub,'plan':plan,'status':status,'days_left':days_left,'device_count':AppDevice.query.filter_by(owner_user_id=user.id).count()})
    return render_template('admin_subscribers_phase1a.html', rows=rows, stats=stats, ui_lang=_lang())


@billing_bp.route('/admin/subscribers/<int:user_id>/activate', methods=['GET','POST'])
def admin_subscriber_activate(user_id):
    admin_user = _active_user()
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    user = AppUser.query.get_or_404(user_id)
    tenant, sub = ensure_user_tenant_and_subscription(user, activated_by_user_id=admin_user.id if admin_user else None)
    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.sort_order.asc()).all()
    if request.method == 'POST':
        plan = SubscriptionPlan.query.get_or_404(int(request.form.get('plan_id')))
        days = int(request.form.get('days') or plan.duration_days_default or 30)
        activate_tenant_subscription(tenant, plan, days, activated_by_user_id=admin_user.id if admin_user else None, notes=request.form.get('notes','').strip())
        ensure_plan_quotas_for_tenant(tenant, plan, commit=True)
        flash('تم تفعيل اشتراك المشترك وتطبيق حدود الخطة تلقائيًا', 'success')
        return redirect(url_for('main.admin_subscribers', lang=_lang()))
    return render_template('admin_subscriber_activate_phase1a.html', user=user, tenant=tenant, subscription=sub, plans=plans, ui_lang=_lang())


@billing_bp.route('/account/subscription')
def account_subscription():
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))
    tenant, sub = ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    plan = SubscriptionPlan.query.get(tenant.plan_id) if tenant and tenant.plan_id else None
    ensure_plan_quotas_for_tenant(tenant, plan, commit=True)
    return render_template('account_subscription_phase1a.html', user=user, tenant=tenant, subscription=sub, plan=plan, quota_rows=quota_summary_rows(getattr(tenant, 'id', None), _lang()), ui_lang=_lang())


@billing_bp.route('/admin/subscriptions')
def admin_subscriptions():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    rows = []
    subscriptions = TenantSubscription.query.order_by(TenantSubscription.updated_at.desc(), TenantSubscription.id.desc()).all()
    for sub in subscriptions:
        tenant = TenantAccount.query.get(sub.tenant_id)
        plan = SubscriptionPlan.query.get(sub.plan_id) if sub.plan_id else None
        owner = AppUser.query.get(tenant.owner_user_id) if tenant and tenant.owner_user_id else None
        rows.append({'subscription': sub, 'tenant': tenant, 'plan': plan, 'owner': owner})
    return render_template('admin_subscriptions.html', rows=rows, ui_lang=_lang(), summary=_admin_counts_snapshot())


@billing_bp.route('/admin/finance', methods=['GET', 'POST'])
def admin_finance():
    guard = _admin_guard('can_manage_finance')
    if guard:
        return guard
    if request.method == 'POST':
        tenant_id = int(request.form.get('tenant_id') or 0)
        amount = float(request.form.get('amount') or 0)
        if tenant_id and amount:
            actor = _active_user()
            entry = WalletLedger(tenant_id=tenant_id, actor_user_id=getattr(actor, 'id', None), entry_type=(request.form.get('entry_type') or 'credit').strip(), amount=amount, currency=(request.form.get('currency') or 'USD').strip() or 'USD', note=(request.form.get('note') or '').strip(), reference=(request.form.get('reference') or '').strip() or None)
            db.session.add(entry)
            db.session.commit()
            _admin_write_log('finance.entry', f'Added finance entry {amount} {entry.currency}', 'wallet_ledger', entry.id, {'tenant_id': tenant_id, 'entry_type': entry.entry_type})
            flash('تم حفظ الحركة المالية', 'success')
            return redirect(url_for('main.admin_finance', lang=_lang()))
    tenants = TenantAccount.query.order_by(TenantAccount.display_name.asc()).all()
    rows = []
    for entry in WalletLedger.query.order_by(WalletLedger.created_at.desc(), WalletLedger.id.desc()).all():
        tenant = TenantAccount.query.get(entry.tenant_id)
        actor = AppUser.query.get(entry.actor_user_id) if entry.actor_user_id else None
        rows.append({'entry': entry, 'tenant': tenant, 'actor': actor})
    totals = {}
    for tenant in tenants:
        total = 0.0
        for entry in WalletLedger.query.filter_by(tenant_id=tenant.id).all():
            total += entry.amount if entry.entry_type == 'credit' else -entry.amount
        totals[tenant.id] = total
    return render_template('admin_finance.html', rows=rows, tenants=tenants, totals=totals, ui_lang=_lang())


@billing_bp.route('/admin/quotas', methods=['GET', 'POST'])
def admin_quotas():
    guard = _admin_guard('can_manage_finance')
    if guard:
        return guard
    actor = _active_user()
    if request.method == 'POST':
        quota_id = int(request.form.get('quota_id') or 0)
        if quota_id:
            quota = TenantQuota.query.get(quota_id)
            if quota:
                quota.limit_value = float(request.form.get('limit_value') or quota.limit_value or 0)
                quota.used_value = float(request.form.get('used_value') or quota.used_value or 0)
                quota.status = (request.form.get('status') or quota.status).strip()
                quota.reset_period = (request.form.get('reset_period') or quota.reset_period).strip()
                quota.notes = (request.form.get('notes') or quota.notes or '').strip()
                db.session.commit()
                _admin_write_log('quota.update', f'Updated quota #{quota.id}', 'tenant_quota', quota.id, {'tenant_id': quota.tenant_id, 'quota_key': quota.quota_key})
                flash('تم تحديث الكوتا', 'success')
        else:
            tenant_id = int(request.form.get('tenant_id') or 0)
            quota_key = (request.form.get('quota_key') or '').strip()
            if tenant_id and quota_key:
                quota = TenantQuota(
                    tenant_id=tenant_id,
                    quota_key=quota_key,
                    quota_label=(request.form.get('quota_label') or quota_key).strip(),
                    limit_value=float(request.form.get('limit_value') or 0),
                    used_value=float(request.form.get('used_value') or 0),
                    reset_period=(request.form.get('reset_period') or 'manual').strip(),
                    status=(request.form.get('status') or 'active').strip(),
                    notes=(request.form.get('notes') or '').strip() or None,
                )
                db.session.add(quota)
                db.session.commit()
                _admin_write_log('quota.create', f'Created quota #{quota.id}', 'tenant_quota', quota.id, {'tenant_id': tenant_id, 'quota_key': quota_key})
                flash('تم إنشاء الكوتا', 'success')
    rows=[]
    for quota in TenantQuota.query.order_by(TenantQuota.updated_at.desc(), TenantQuota.id.desc()).all():
        tenant = TenantAccount.query.get(quota.tenant_id)
        percent = 0
        if quota.limit_value and quota.limit_value > 0:
            percent = round((quota.used_value / quota.limit_value) * 100, 1)
        rows.append({'quota': quota, 'tenant': tenant, 'percent': percent})
    return render_template('admin_quotas.html', rows=rows, tenants=TenantAccount.query.order_by(TenantAccount.display_name.asc()).all(), ui_lang=_lang())


