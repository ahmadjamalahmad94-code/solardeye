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

    # ── Insights aside data ──────────────────────────────────────────
    insights = {
        'plans_total': len(plans),
        'plans_active': sum(1 for p in plans if p.is_active),
        'plans_inactive': sum(1 for p in plans if not p.is_active),
        'subs_total': 0,
        'subs_active': 0,
        'subs_trial': 0,
        'subs_expired': 0,
        'revenue_total': 0.0,
        'avg_price': 0.0,
        'cheapest': None,
        'priciest': None,
        'most_popular': None,
        'longest_duration': None,
    }
    distribution = []  # [{plan, count, active, pct}]
    try:
        # Aggregate subscriptions per plan
        plan_sub_counts = {}
        plan_active_counts = {}
        all_subs = TenantSubscription.query.all()
        for sub in all_subs:
            insights['subs_total'] += 1
            st = (sub.status or 'trial').lower()
            if st == 'active':
                insights['subs_active'] += 1
            elif st == 'trial':
                insights['subs_trial'] += 1
            elif st in ('expired', 'suspended'):
                insights['subs_expired'] += 1
            plan_sub_counts[sub.plan_id] = plan_sub_counts.get(sub.plan_id, 0) + 1
            if st == 'active':
                plan_active_counts[sub.plan_id] = plan_active_counts.get(sub.plan_id, 0) + 1
        # Total revenue across all wallets
        try:
            total_credits = sum((e.amount or 0) for e in WalletLedger.query.filter_by(entry_type='credit').all())
            insights['revenue_total'] = round(total_credits, 2)
        except Exception:
            pass
        # Distribution rows for chart
        max_count = max(plan_sub_counts.values()) if plan_sub_counts else 0
        for p in plans:
            cnt = plan_sub_counts.get(p.id, 0)
            act = plan_active_counts.get(p.id, 0)
            pct = round(cnt / max_count * 100) if max_count else 0
            distribution.append({'plan': p, 'count': cnt, 'active': act, 'pct': pct})
        # Comparisons
        priced_plans = [p for p in plans if p.price and p.price > 0]
        if priced_plans:
            insights['avg_price'] = round(sum(p.price for p in priced_plans) / len(priced_plans), 2)
            insights['cheapest'] = min(priced_plans, key=lambda p: p.price)
            insights['priciest'] = max(priced_plans, key=lambda p: p.price)
        if plans:
            insights['longest_duration'] = max(plans, key=lambda p: (p.duration_days_default or 0))
        if plan_sub_counts:
            top_plan_id = max(plan_sub_counts, key=plan_sub_counts.get)
            insights['most_popular'] = next((p for p in plans if p.id == top_plan_id), None)
            insights['most_popular_count'] = plan_sub_counts.get(top_plan_id, 0)
    except Exception as exc:
        current_app.logger.warning('admin_plans insights failed: %s', exc)

    return render_template(
        'admin_plans_phase1a.html',
        plans=plans,
        insights=insights,
        distribution=distribution,
        ui_lang=_lang(),
    )


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
    # Aside enrichment: subscriber stats, revenue, recent activations
    plan_stats = {'subs_total': 0, 'subs_active': 0, 'subs_trial': 0, 'subs_expired': 0, 'devices': 0, 'revenue': 0.0, 'avg_days_left': 0}
    recent_subs = []
    try:
        sub_rows = TenantSubscription.query.filter_by(plan_id=plan.id).all()
        plan_stats['subs_total'] = len(sub_rows)
        days_left_acc = 0
        days_left_count = 0
        now_utc = datetime.utcnow()
        for sub in sub_rows:
            status = (sub.status or 'trial').lower()
            if status == 'active':
                plan_stats['subs_active'] += 1
            elif status == 'trial':
                plan_stats['subs_trial'] += 1
            elif status in ('expired', 'suspended'):
                plan_stats['subs_expired'] += 1
            if sub.ends_at:
                d = (sub.ends_at.date() - now_utc.date()).days
                if d > 0:
                    days_left_acc += d
                    days_left_count += 1
        plan_stats['avg_days_left'] = round(days_left_acc / days_left_count) if days_left_count else 0
        tenant_ids = [s.tenant_id for s in sub_rows]
        if tenant_ids:
            tenants_owned = TenantAccount.query.filter(TenantAccount.id.in_(tenant_ids)).all()
            owner_ids = [t.owner_user_id for t in tenants_owned if t.owner_user_id]
            if owner_ids:
                plan_stats['devices'] = AppDevice.query.filter(AppDevice.owner_user_id.in_(owner_ids), AppDevice.is_active.is_(True)).count()
            try:
                ledger = WalletLedger.query.filter(WalletLedger.tenant_id.in_(tenant_ids), WalletLedger.entry_type == 'credit').all()
                plan_stats['revenue'] = round(sum(e.amount or 0 for e in ledger), 2)
            except Exception:
                pass
        recent_rows = TenantSubscription.query.filter_by(plan_id=plan.id).order_by(TenantSubscription.created_at.desc()).limit(5).all()
        for sub in recent_rows:
            tenant = TenantAccount.query.get(sub.tenant_id)
            owner = AppUser.query.get(tenant.owner_user_id) if tenant and tenant.owner_user_id else None
            recent_subs.append({'sub': sub, 'tenant': tenant, 'owner': owner})
    except Exception as exc:
        current_app.logger.warning('plan-edit aside stats failed: %s', exc)
    completeness = [
        {'key': 'name_ar', 'label_en': 'Arabic name set',  'label_ar': 'الاسم بالعربية',  'ok': bool((plan.name_ar or '').strip())},
        {'key': 'name_en', 'label_en': 'English name set', 'label_ar': 'الاسم بالإنجليزية', 'ok': bool((plan.name_en or '').strip())},
        {'key': 'price',   'label_en': 'Price configured', 'label_ar': 'تم تحديد السعر',   'ok': (plan.price or 0) > 0 or plan.code in ('free', 'trial')},
        {'key': 'days',    'label_en': 'Duration set',     'label_ar': 'تم تحديد المدة',  'ok': (plan.duration_days_default or 0) >= 1},
        {'key': 'devices', 'label_en': 'Device cap set',   'label_ar': 'حد الأجهزة محدد', 'ok': (plan.max_devices or 0) >= 1},
        {'key': 'active',  'label_en': 'Plan is active',   'label_ar': 'الباقة مفعّلة',   'ok': bool(plan.is_active)},
    ]
    completeness_done = sum(1 for c in completeness if c['ok'])
    completeness_pct = round(completeness_done / len(completeness) * 100) if completeness else 0
    return render_template(
        'admin_plan_form_phase1a.html',
        plan=plan,
        plan_quota_rows=plan_quota_rows_for_template(plan, _lang()),
        plan_stats=plan_stats,
        recent_subs=recent_subs,
        completeness=completeness,
        completeness_done=completeness_done,
        completeness_pct=completeness_pct,
        ui_lang=_lang(),
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )


@billing_bp.route('/admin/subscribers')
def admin_subscribers():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    rows=[]
    subscriber_roles = ('', 'user', 'subscriber', 'customer')
    users=AppUser.query.filter(
        db.or_(AppUser.is_admin.is_(False), AppUser.is_admin.is_(None)),
        db.or_(AppUser.role.is_(None), AppUser.role.in_(subscriber_roles)),
    ).order_by(AppUser.created_at.desc(), AppUser.id.desc()).all()
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
        support_scope = db.or_(SupportCase.tenant_id == tenant.id, SupportCase.user_id == user.id)
        support_open = db.or_(SupportCase.status.is_(None), ~SupportCase.status.in_(('closed', 'resolved')))
        open_message_count = SupportCase.query.filter(support_scope, support_open, SupportCase.case_type == 'message').count()
        open_ticket_count = SupportCase.query.filter(support_scope, support_open, SupportCase.case_type == 'ticket').count()
        rows.append({'user':user,'tenant':tenant,'subscription':sub,'plan':plan,'status':status,'days_left':days_left,'device_count':AppDevice.query.filter_by(owner_user_id=user.id, is_active=True).count(),'open_message_count':open_message_count,'open_ticket_count':open_ticket_count})
    active_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    return render_template('admin_subscribers_phase1a.html', rows=rows, stats=stats, plans=active_plans, ui_lang=_lang())


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


@billing_bp.route('/admin/subscribers/<int:user_id>/extend', methods=['POST'])
def admin_subscriber_extend(user_id):
    admin_user = _active_user()
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    user = AppUser.query.get_or_404(user_id)
    tenant, sub = ensure_user_tenant_and_subscription(user, activated_by_user_id=admin_user.id if admin_user else None)
    amount = int(request.form.get('amount') or 0)
    unit = (request.form.get('unit') or 'days').strip()
    notes = (request.form.get('notes') or '').strip()
    if amount <= 0:
        flash('أدخل مدة صحيحة لإضافتها', 'warning')
        return redirect(url_for('main.admin_subscribers', lang=_lang()))
    base = sub.ends_at if sub and sub.ends_at and sub.ends_at > datetime.utcnow() else datetime.utcnow()
    if unit == 'months':
        delta_days = amount * 30
    elif unit == 'years':
        delta_days = amount * 365
    else:
        delta_days = amount
    if sub:
        sub.ends_at = base + timedelta(days=delta_days)
        if unit == 'trial_days':
            sub.status = 'trial'
            sub.trial_ends_at = sub.ends_at
        elif sub.status in ['expired', 'suspended', 'trial']:
            sub.status = 'active'
        sub.notes = ((sub.notes or '') + ('\n' if sub.notes else '') + (notes or f'Extended by {amount} {unit}')).strip()
        sub.updated_at = datetime.utcnow()
    if tenant:
        tenant.status = 'trial' if unit == 'trial_days' else 'active'
        tenant.updated_at = datetime.utcnow()

    # Auto-generate ledger entry for paid extensions (skip free trial extensions)
    if sub and unit != 'trial_days' and tenant:
        try:
            from ..services.subscriptions import _create_subscription_ledger_entry
            plan_obj = SubscriptionPlan.query.get(sub.plan_id) if sub.plan_id else None
            if plan_obj and float(plan_obj.price or 0) > 0:
                _create_subscription_ledger_entry(
                    tenant, plan_obj, delta_days, sub,
                    activated_by_user_id=admin_user.id if admin_user else None,
                    is_renewal=True,
                )
        except Exception as exc:
            current_app.logger.warning('Auto-ledger for extend failed: %s', exc)

    db.session.commit()
    flash('تمت إضافة مدة الاشتراك بنجاح', 'success')
    return redirect(url_for('main.admin_subscribers', lang=_lang()))


@billing_bp.route('/account/subscription')
def account_subscription():
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))
    tenant, sub = ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    plan = SubscriptionPlan.query.get(tenant.plan_id) if tenant and tenant.plan_id else None
    ensure_plan_quotas_for_tenant(tenant, plan, commit=True)
    all_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    # pre-parse features for each plan so the template doesn't need a from_json filter
    from ..services.subscriptions import plan_features as _plan_features
    plan_features_map = {p.id: _plan_features(p) for p in all_plans}
    # compute remaining days for hero ring
    now_dt = datetime.utcnow()
    days_left_num = 0
    if sub and sub.ends_at:
        delta = (sub.ends_at.date() - now_dt.date()).days
        days_left_num = max(delta, 0)
    total_days = (plan.duration_days_default or 30) if plan else 30
    pct_left = min(max(round(days_left_num / total_days * 100), 0), 100) if total_days else 0
    # pending plan-change requests
    pending_request = SupportCase.query.filter_by(
        user_id=user.id, case_type='plan_change_request', status='open'
    ).order_by(SupportCase.created_at.desc()).first()
    return render_template(
        'account_subscription_phase1a.html',
        user=user, tenant=tenant, subscription=sub, plan=plan,
        quota_rows=quota_summary_rows(getattr(tenant, 'id', None), _lang()),
        all_plans=all_plans,
        plan_features_map=plan_features_map,
        days_left_num=days_left_num,
        pct_left=pct_left,
        pending_request=pending_request,
        ui_lang=_lang(),
    )


@billing_bp.route('/account/subscription/request-change', methods=['POST'])
def account_subscription_request_change():
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))
    tenant, sub = ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    plan_id = int(request.form.get('plan_id') or 0)
    message = (request.form.get('message') or '').strip()
    target_plan = SubscriptionPlan.query.get(plan_id) if plan_id else None
    if not target_plan:
        flash('الخطة المطلوبة غير موجودة', 'warning')
        return redirect(url_for('billing.account_subscription', lang=_lang()))
    # cancel older open requests for the same user
    SupportCase.query.filter_by(
        user_id=user.id, case_type='plan_change_request', status='open'
    ).update({'status': 'cancelled'})
    plan_name = target_plan.name_ar or target_plan.name_en or target_plan.code
    case = SupportCase(
        case_type='plan_change_request',
        source_id=user.id,
        tenant_id=getattr(tenant, 'id', None),
        user_id=user.id,
        subject=f'طلب تغيير الخطة إلى {plan_name}',
        priority='normal',
        status='open',
    )
    # store target plan info and user note in case subject extended form
    case.subject = f'طلب تغيير الخطة إلى {plan_name}' + (f' — {message}' if message else '')
    db.session.add(case)
    db.session.flush()
    # v81: fan out an admin-visible notification so operators see the
    # request in the admin notification center. Each active admin gets
    # exactly one event keyed to this case; the dedup inside
    # `notify_admins_of_plan_change_request` prevents a re-render from
    # spamming the queue.
    try:
        from ..services.support_ops import notify_admins_of_plan_change_request
        notify_admins_of_plan_change_request(
            case, requester=user, target_plan=target_plan, commit=False,
        )
    except Exception:
        current_app.logger.exception('plan_change_request admin notify failed')
    db.session.commit()
    flash(f'تم إرسال طلب تغيير الخطة إلى "{plan_name}" بنجاح. سيتواصل معك الفريق قريبًا.', 'success')
    return redirect(url_for('billing.account_subscription', lang=_lang()))


# v81: ── Admin plan-change-request workflow ──────────────────────────
#
# A real admin workflow on top of `SupportCase(case_type='plan_change_request')`
# rows so operators can review, approve, and reject requests with a
# clear pricing breakdown and a transparent wallet/ledger entry. The
# heavy lifting (pricing, ledger, subscriber notification, audit log)
# lives in `support_ops` so the route handlers stay thin.


def _plan_change_request_or_404(case_id: int):
    case = SupportCase.query.filter_by(
        id=int(case_id), case_type='plan_change_request',
    ).first()
    if not case:
        return None
    return case


@billing_bp.route('/admin/plan-change-requests', methods=['GET'])
def admin_plan_change_requests():
    guard = _admin_guard('can_manage_subscriptions')
    if guard:
        return guard
    from ..services.support_ops import (
        compute_plan_change_quote, extract_plan_change_target_plan,
    )
    cases = (
        SupportCase.query
        .filter_by(case_type='plan_change_request')
        .order_by(SupportCase.status.asc(), SupportCase.updated_at.desc(), SupportCase.id.desc())
        .limit(200)
        .all()
    )
    rows = []
    for c in cases:
        user = AppUser.query.get(c.user_id) if c.user_id else None
        target = extract_plan_change_target_plan(c)
        quote = compute_plan_change_quote(c, target_plan=target)
        rows.append({
            'case': c,
            'user': user,
            'target_plan': target,
            'quote': quote,
        })
    return render_template(
        'admin_plan_change_requests.html',
        rows=rows,
        ui_lang=_lang(),
        summary=_admin_counts_snapshot(),
    )


@billing_bp.route('/admin/plan-change-requests/<int:case_id>/approve', methods=['POST'])
def admin_plan_change_request_approve(case_id: int):
    guard = _admin_guard('can_manage_subscriptions')
    if guard:
        return guard
    case = _plan_change_request_or_404(case_id)
    if not case:
        flash('طلب تغيير الخطة غير موجود.', 'warning')
        return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))
    if (case.status or '').lower() != 'open':
        flash('لا يمكن تطبيق طلب مغلق أو منتهي.', 'warning')
        return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))
    from ..services.support_ops import apply_plan_change_request
    actor = _active_user()
    result = apply_plan_change_request(
        case,
        actor_user_id=getattr(actor, 'id', None),
        commit=True,
    )
    extra = float(result.get('extra_charge') or 0)
    currency = result.get('currency') or 'USD'
    if abs(extra) >= 0.01:
        flash(
            f'تم تطبيق تغيير الخطة. الفرق المسجّل: {extra:.2f} {currency}.',
            'success',
        )
    else:
        flash('تم تطبيق تغيير الخطة دون فرق مالي.', 'success')
    return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))


@billing_bp.route('/admin/plan-change-requests/<int:case_id>/reject', methods=['POST'])
def admin_plan_change_request_reject(case_id: int):
    guard = _admin_guard('can_manage_subscriptions')
    if guard:
        return guard
    case = _plan_change_request_or_404(case_id)
    if not case:
        flash('طلب تغيير الخطة غير موجود.', 'warning')
        return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))
    from ..services.support_ops import reject_plan_change_request
    actor = _active_user()
    reason = (request.form.get('reason') or '').strip()
    reject_plan_change_request(
        case,
        actor_user_id=getattr(actor, 'id', None),
        reason=reason,
        commit=True,
    )
    flash('تم رفض طلب تغيير الخطة وإبلاغ المشترك.', 'success')
    return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))


@billing_bp.route('/admin/plan-change-requests/<int:case_id>/cancel', methods=['POST'])
def admin_plan_change_request_cancel(case_id: int):
    """Soft-close without notifying the subscriber. Use when the
    request was a duplicate / superseded by another admin action."""
    guard = _admin_guard('can_manage_subscriptions')
    if guard:
        return guard
    case = _plan_change_request_or_404(case_id)
    if not case:
        flash('طلب تغيير الخطة غير موجود.', 'warning')
        return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))
    from ..services.support_ops import audit_case
    actor = _active_user()
    case.status = 'cancelled'
    case.is_frozen = True
    case.updated_at = datetime.utcnow()
    audit_case(
        case.case_type, case.source_id,
        getattr(actor, 'id', None),
        'plan_change.cancel',
        'Admin closed plan-change request without applying',
        commit=False,
    )
    db.session.commit()
    flash('تم إغلاق طلب تغيير الخطة دون تطبيقه.', 'success')
    return redirect(url_for('billing.admin_plan_change_requests', lang=_lang()))


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


# ── Finance category constants ────────────────────────────────────────────────
FINANCE_CATEGORIES = {
    # Customer wallet / liability
    'customer_deposit': {'label_ar': 'إيداع مشترك', 'label_en': 'Customer Deposit', 'type': 'credit', 'account': 'liability', 'icon': '🏦', 'color': '#2563eb'},
    'refund':          {'label_ar': 'استرداد نقدي', 'label_en': 'Refund',          'type': 'debit',  'account': 'refund',    'icon': '↩',  'color': '#dc2626'},
    'wallet_adjustment': {'label_ar': 'تسوية محفظة', 'label_en': 'Wallet Adjustment', 'type': 'both', 'account': 'liability', 'icon': '⚖', 'color': '#64748b'},
    # Earned revenue
    'subscription':   {'label_ar': 'رسوم اشتراك', 'label_en': 'Subscription Service', 'type': 'debit', 'account': 'revenue', 'icon': '📦', 'color': '#10b981'},
    'renewal':        {'label_ar': 'تجديد اشتراك', 'label_en': 'Renewal',            'type': 'debit', 'account': 'revenue', 'icon': '🔄', 'color': '#34d399'},
    'sms':            {'label_ar': 'رسائل قصيرة',  'label_en': 'SMS Messages',       'type': 'debit', 'account': 'revenue', 'icon': '✉',  'color': '#0ea5e9'},
    'extra_service':  {'label_ar': 'خدمات إضافية', 'label_en': 'Extra Services',     'type': 'debit', 'account': 'revenue', 'icon': '⭐', 'color': '#6ee7b7'},
    'setup_fee':      {'label_ar': 'رسوم إعداد',   'label_en': 'Setup Fee',          'type': 'debit', 'account': 'revenue', 'icon': '🧾', 'color': '#14b8a6'},
    'other_income':   {'label_ar': 'إيرادات أخرى', 'label_en': 'Other Income',       'type': 'credit','account': 'revenue', 'icon': '$',  'color': '#a7f3d0'},
    # Company expenses
    'hosting':        {'label_ar': 'استضافة وخوادم', 'label_en': 'Hosting & Servers', 'type': 'debit','account': 'expense','icon': '🖥', 'color': '#f43f5e'},
    'development':    {'label_ar': 'تطوير برمجي',    'label_en': 'Development',       'type': 'debit','account': 'expense','icon': '💻', 'color': '#fb7185'},
    'maintenance':    {'label_ar': 'صيانة',          'label_en': 'Maintenance',       'type': 'debit','account': 'expense','icon': '🔧', 'color': '#fda4af'},
    'salary':         {'label_ar': 'رواتب الموظفين', 'label_en': 'Staff Salaries',    'type': 'debit','account': 'expense','icon': '👥', 'color': '#f59e0b'},
    'admin_salary':   {'label_ar': 'رواتب الإدارة',  'label_en': 'Management Salaries','type': 'debit','account': 'expense','icon': '👔', 'color': '#d97706'},
    'vendor_payment': {'label_ar': 'دفعة لمورد',     'label_en': 'Vendor Payment',    'type': 'debit','account': 'expense','icon': '🏢', 'color': '#ef4444'},
    'marketing':      {'label_ar': 'تسويق',          'label_en': 'Marketing',         'type': 'debit','account': 'expense','icon': '📣', 'color': '#fbbf24'},
    'tools':          {'label_ar': 'أدوات وتراخيص',  'label_en': 'Tools & Licenses',  'type': 'debit','account': 'expense','icon': '🛠', 'color': '#fde68a'},
    'taxes':          {'label_ar': 'ضرائب ورسوم',    'label_en': 'Taxes & Fees',      'type': 'debit','account': 'expense','icon': '％', 'color': '#7c3aed'},
    'other_expense':  {'label_ar': 'مصاريف أخرى',    'label_en': 'Other Expenses',    'type': 'debit','account': 'expense','icon': '📤', 'color': '#94a3b8'},
    'general':        {'label_ar': 'عام',            'label_en': 'General',           'type': 'both', 'account': 'other',  'icon': '📋', 'color': '#64748b'},
}


# ─────────────────────────────────────────────────────────────────
# Payment methods catalog (used in admin_finance entry form)
# Each method has: key, label_ar, label_en, icon (emoji), color
# ─────────────────────────────────────────────────────────────────
PAYMENT_METHODS = [
    {'key': 'cash',          'label_ar': 'نقد',              'label_en': 'Cash',           'icon': '💵', 'color': '#10b981'},
    {'key': 'bank_transfer', 'label_ar': 'تحويل بنكي',       'label_en': 'Bank Transfer',  'icon': '🏦', 'color': '#2563eb'},
    {'key': 'bank_card',     'label_ar': 'بطاقة بنكية',      'label_en': 'Bank Card',      'icon': '💳', 'color': '#0ea5e9'},
    {'key': 'paypal',        'label_ar': 'PayPal',           'label_en': 'PayPal',         'icon': '🅿', 'color': '#003087'},
    {'key': 'check',         'label_ar': 'شيك',              'label_en': 'Check',          'icon': '📃', 'color': '#7c3aed'},
    {'key': 'crypto',        'label_ar': 'عملة رقمية',       'label_en': 'Cryptocurrency', 'icon': '₿',  'color': '#f7931a'},
    {'key': 'wallet',        'label_ar': 'محفظة إلكترونية',  'label_en': 'E-Wallet',       'icon': '📱', 'color': '#14b8a6'},
    {'key': 'other',         'label_ar': 'أخرى',             'label_en': 'Other',          'icon': '⚙', 'color': '#64748b'},
]
PAYMENT_METHODS_MAP = {pm['key']: pm for pm in PAYMENT_METHODS}


def _finance_company_tenant():
    """Return an internal tenant row used for company-only ledger entries."""
    tenant = TenantAccount.query.filter_by(display_name='Company Operations').first()
    if tenant:
        return tenant
    tenant = TenantAccount(display_name='Company Operations', status='internal')
    db.session.add(tenant)
    db.session.flush()
    return tenant


def _finance_category_meta(category: str) -> dict:
    return FINANCE_CATEGORIES.get(category or 'general', FINANCE_CATEGORIES['general'])


def _finance_account_for(entry: WalletLedger) -> str:
    meta = _finance_category_meta(entry.category)
    account = meta.get('account')
    if account and account != 'other':
        return account
    if entry.entry_type == 'credit':
        return 'revenue'
    return 'expense'


def _finance_signed_wallet_amount(entry: WalletLedger) -> float:
    account = _finance_account_for(entry)
    if account in {'liability', 'revenue', 'refund'}:
        return float(entry.amount or 0) if entry.entry_type == 'credit' else -float(entry.amount or 0)
    return 0.0


@billing_bp.route('/admin/finance', methods=['GET', 'POST'])
def admin_finance():
    import calendar as _cal
    from datetime import datetime as _dt, timedelta as _td

    guard = _admin_guard('can_manage_finance')
    if guard:
        return guard

    if request.method == 'POST':
        tenant_id = int(request.form.get('tenant_id') or 0)
        amount    = float(request.form.get('amount') or 0)
        operation_type = (request.form.get('operation_type') or '').strip()
        category = (request.form.get('category') or 'general').strip()
        if operation_type == 'customer_deposit':
            category = 'customer_deposit'
            entry_type = 'credit'
        elif operation_type == 'service_charge':
            entry_type = 'debit'
        elif operation_type == 'refund':
            category = 'refund'
            entry_type = 'debit'
        elif operation_type in {'operating_expense', 'salary', 'vendor_payment'}:
            if operation_type == 'salary' and category == 'general':
                category = 'salary'
            elif operation_type == 'vendor_payment' and category == 'general':
                category = 'vendor_payment'
            entry_type = 'debit'
        elif operation_type == 'other_income':
            entry_type = 'credit'
        else:
            entry_type = (request.form.get('entry_type') or FINANCE_CATEGORIES.get(category, {}).get('type') or 'credit').strip()

        if amount:
            if not tenant_id:
                company_tenant = _finance_company_tenant()
                tenant_id = company_tenant.id
            actor = _active_user()

            # ── Handle file upload (invoice/receipt attachment) ──
            attachment_path = None
            attachment_name = None
            uploaded = request.files.get('attachment') if request.files else None
            if uploaded and getattr(uploaded, 'filename', '') and uploaded.filename.strip():
                try:
                    import os as _os
                    import uuid as _uuid
                    from werkzeug.utils import secure_filename as _secure
                    raw_name = uploaded.filename
                    safe_name = _secure(raw_name) or 'attachment'
                    ext = _os.path.splitext(safe_name)[1].lower()
                    # Whitelist of allowed extensions
                    allowed = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.heic', '.bmp'}
                    if ext in allowed:
                        # Build target dir under static/uploads/finance/
                        upload_dir = _os.path.join(current_app.root_path, 'static', 'uploads', 'finance')
                        _os.makedirs(upload_dir, exist_ok=True)
                        unique_name = f"{_dt.utcnow().strftime('%Y%m%d_%H%M%S')}_{_uuid.uuid4().hex[:8]}{ext}"
                        full_path = _os.path.join(upload_dir, unique_name)
                        uploaded.save(full_path)
                        attachment_path = f'uploads/finance/{unique_name}'
                        attachment_name = raw_name[:240]
                    else:
                        flash(f'صيغة الملف غير مدعومة: {ext}', 'warning')
                except Exception as exc:
                    current_app.logger.warning('Finance attachment upload failed: %s', exc)

            payment_method = (request.form.get('payment_method') or '').strip() or None

            # ── Salary employee: prepend employee name to the note for traceability ──
            note_text = (request.form.get('note') or '').strip()
            if operation_type == 'salary':
                emp_id = (request.form.get('employee_id') or '').strip()
                emp_other = (request.form.get('employee_name_other') or '').strip()
                emp_label = ''
                if emp_id == 'other' and emp_other:
                    emp_label = emp_other
                elif emp_id and emp_id != 'other':
                    try:
                        emp_user = AppUser.query.get(int(emp_id))
                        if emp_user:
                            emp_label = emp_user.full_name or emp_user.username or f'User #{emp_user.id}'
                    except Exception:
                        pass
                if emp_label:
                    note_text = (f'[{emp_label}] ' + note_text).strip()

            entry = WalletLedger(
                tenant_id        = tenant_id,
                actor_user_id    = getattr(actor, 'id', None),
                entry_type       = entry_type,
                amount           = amount,
                currency         = (request.form.get('currency') or 'USD').strip() or 'USD',
                note             = note_text,
                reference        = (request.form.get('reference') or '').strip() or None,
                category         = category,
                is_recurring     = request.form.get('is_recurring') == 'on',
                recurring_period = (request.form.get('recurring_period') or '').strip() or None,
                payment_method   = payment_method,
                attachment_path  = attachment_path,
                attachment_name  = attachment_name,
            )
            db.session.add(entry)
            db.session.commit()
            _admin_write_log('finance.entry', f'Added finance entry {amount} {entry.currency}',
                             'wallet_ledger', entry.id,
                             {'tenant_id': tenant_id, 'entry_type': entry.entry_type,
                              'category': entry.category, 'operation_type': operation_type,
                              'payment_method': payment_method,
                              'has_attachment': bool(attachment_path)})
            flash('تم حفظ الحركة المالية', 'success')
            return redirect(url_for('billing.admin_finance', lang=_lang()))

    # ── Period filter ─────────────────────────────────────────────────────
    period   = (request.args.get('period') or 'all').strip()
    now      = _dt.utcnow()
    if period == 'today':
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end   = None
    elif period == 'week':
        period_start = now - _td(days=now.weekday())
        period_start = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
        period_end   = None
    elif period == 'month':
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end   = None
    elif period == 'year':
        period_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end   = None
    elif period == 'custom':
        from_str = request.args.get('from_date', '')
        to_str   = request.args.get('to_date', '')
        try:    period_start = _dt.strptime(from_str, '%Y-%m-%d')
        except: period_start = None
        try:    period_end   = _dt.strptime(to_str,   '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except: period_end   = None
    else:  # 'all'
        period_start = None
        period_end   = None

    from_date = request.args.get('from_date', '')
    to_date   = request.args.get('to_date',   '')

    # ── Build base ledger query ────────────────────────────────────────────
    q = WalletLedger.query
    if period_start:
        q = q.filter(WalletLedger.created_at >= period_start)
    if period_end:
        q = q.filter(WalletLedger.created_at <= period_end)
    all_entries = q.order_by(WalletLedger.created_at.desc()).all()

    # ── Accounting totals ─────────────────────────────────────────────────
    total_credit = sum(e.amount for e in all_entries if e.entry_type == 'credit')
    total_debit  = sum(e.amount for e in all_entries if e.entry_type == 'debit')
    deposits_total = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'liability' and e.entry_type == 'credit')
    earned_revenue = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'revenue')
    refunds_total = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'refund')
    operating_expenses = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'expense')
    net_profit = earned_revenue - operating_expenses
    cash_in = deposits_total + sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'revenue' and e.entry_type == 'credit')
    cash_out = refunds_total + operating_expenses
    cash_net = cash_in - cash_out

    # ── Category breakdown ─────────────────────────────────────────────────
    from collections import defaultdict
    cat_totals = defaultdict(float)
    cat_credit_totals = defaultdict(float)
    cat_debit_totals = defaultdict(float)
    for e in all_entries:
        cat = e.category or 'general'
        cat_totals[cat] += e.amount
        account = _finance_account_for(e)
        if account == 'revenue':
            cat_credit_totals[cat] += e.amount
        elif account in {'expense', 'refund'}:
            cat_debit_totals[cat] += e.amount
    max_cat = max(
        (cat_credit_totals[k] + cat_debit_totals[k] for k in FINANCE_CATEGORIES),
        default=1,
    ) or 1
    category_breakdown = []
    for cat_key, meta in FINANCE_CATEGORIES.items():
        credit = cat_credit_totals.get(cat_key, 0.0)
        debit = cat_debit_totals.get(cat_key, 0.0)
        total = credit + debit
        if total > 0:
            category_breakdown.append({
                'key':      cat_key,
                'label_ar': meta.get('label_ar', cat_key),
                'label_en': meta.get('label_en', cat_key),
                'icon':     meta.get('icon', '📋'),
                'color':    meta.get('color', '#64748b'),
                'credit':   credit,
                'debit':    debit,
                'total':    total,
                'pct':      round(total / max_cat * 100),
            })
    category_breakdown.sort(key=lambda x: x['total'], reverse=True)

    # ── Monthly chart (last 6 months) ──────────────────────────────────────
    import calendar as _cal
    monthly_chart = []
    for i in range(5, -1, -1):
        month_dt = now.replace(day=1) - _td(days=i * 28)
        m_start  = month_dt.replace(day=1, hour=0, minute=0, second=0)
        last_day = _cal.monthrange(m_start.year, m_start.month)[1]
        m_end    = m_start.replace(day=last_day, hour=23, minute=59, second=59)
        m_entries = [e for e in WalletLedger.query.filter(
            WalletLedger.created_at >= m_start,
            WalletLedger.created_at <= m_end
        ).all()]
        m_credit = sum(float(e.amount or 0) for e in m_entries if _finance_account_for(e) == 'revenue')
        m_debit  = sum(float(e.amount or 0) for e in m_entries if _finance_account_for(e) == 'expense')
        m_deposit = sum(float(e.amount or 0) for e in m_entries if _finance_account_for(e) == 'liability' and e.entry_type == 'credit')
        m_refund = sum(float(e.amount or 0) for e in m_entries if _finance_account_for(e) == 'refund')
        monthly_chart.append({
            'label':  m_start.strftime('%b'),
            'credit': m_credit,
            'debit':  m_debit,
            'net':    m_credit - m_debit,
            'deposits': m_deposit,
            'refunds': m_refund,
        })
    max_bar = max((max(m['credit'], m['debit']) for m in monthly_chart), default=1) or 1

    # ── Plan revenue breakdown ─────────────────────────────────────────────
    plan_breakdown = []
    plans = SubscriptionPlan.query.filter_by(is_active=True).all()
    for plan in plans:
        plan_subs = TenantSubscription.query.filter_by(plan_id=plan.id, status='active').count()
        mrr = plan_subs * float(plan.price or 0)
        if mrr > 0:
            plan_breakdown.append({
                'plan':     plan,
                'name_ar':  plan.name_ar,
                'name_en':  plan.name_en,
                'currency': plan.currency or 'USD',
                'count':    plan_subs,
                'mrr':      mrr,
                'revenue':  mrr,
            })
    plan_breakdown.sort(key=lambda x: x['mrr'], reverse=True)
    total_mrr = sum(p['mrr'] for p in plan_breakdown)
    max_plan_rev = max((p['revenue'] for p in plan_breakdown), default=1) or 1
    active_sub_count = TenantSubscription.query.filter_by(status='active').count()
    trial_sub_count = TenantSubscription.query.filter_by(status='trial').count()
    tenant_count = TenantAccount.query.count()

    # ── Recurring expenses ─────────────────────────────────────────────────
    recurring_entries = WalletLedger.query.filter_by(is_recurring=True).all()
    recurring_monthly = 0.0
    for r in recurring_entries:
        if _finance_account_for(r) not in {'expense', 'revenue'}:
            continue
        if r.recurring_period == 'monthly':
            recurring_monthly += r.amount
        elif r.recurring_period == 'quarterly':
            recurring_monthly += r.amount / 3
        elif r.recurring_period == 'yearly':
            recurring_monthly += r.amount / 12

    # ── Staff/admin list (for salary entry employee dropdown) ─────────────
    staff_users = AppUser.query.filter(
        (AppUser.is_admin == True) | (AppUser.role.in_(['admin', 'manager', 'staff']))
    ).order_by(AppUser.full_name.asc(), AppUser.username.asc()).all()

    # ── Tenant wallets ─────────────────────────────────────────────────────
    wallets = []
    tenants = TenantAccount.query.order_by(TenantAccount.id.desc()).limit(20).all()
    for t in tenants:
        entries = WalletLedger.query.filter_by(tenant_id=t.id).all()
        balance = sum(_finance_signed_wallet_amount(e) for e in entries)
        wallets.append({'tenant': t, 'balance': balance})
    top_tenants = [(w['tenant'], w['balance']) for w in wallets]

    # ── Ledger rows for the finance v3 template ───────────────────────────
    tenant_ids = {e.tenant_id for e in all_entries if e.tenant_id}
    tenant_ids = {e.tenant_id for e in all_entries if e.tenant_id}
    tenant_map = {t.id: t for t in TenantAccount.query.filter(TenantAccount.id.in_(tenant_ids)).all()} if tenant_ids else {}

    rows = []
    for e in all_entries:
        meta    = _finance_category_meta(e.category)
        account = _finance_account_for(e)
        rows.append({
            'entry':   e,
            'tenant':  tenant_map.get(e.tenant_id),
            'meta':    meta,
            'account': account,
        })

    # ── Period stats (daily / weekly / monthly / yearly) ──────────────────
    class _Stats:
        def __init__(self, revenue=0.0, expenses=0.0):
            self.revenue  = revenue
            self.expenses = expenses

    def _compute_stats(start):
        es = WalletLedger.query.filter(WalletLedger.created_at >= start).all()
        rev = sum(float(e.amount or 0) for e in es if _finance_account_for(e) == 'revenue')
        exp = sum(float(e.amount or 0) for e in es if _finance_account_for(e) == 'expense')
        return _Stats(rev, exp)

    daily_start   = now.replace(hour=0, minute=0, second=0, microsecond=0)
    weekly_start  = (now - _td(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    monthly_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    yearly_start  = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    daily_stats   = _compute_stats(daily_start)
    weekly_stats  = _compute_stats(weekly_start)
    monthly_stats = _compute_stats(monthly_start)
    yearly_stats  = _compute_stats(yearly_start)

    customer_liability = deposits_total
    monthly_data       = monthly_chart
    max_monthly        = max_bar

    # ── Year-over-Year comparison (12 months current vs 12 months previous) ─
    cur_year  = now.year
    yoy_labels   = []
    yoy_current  = []
    yoy_previous = []
    month_short_ar = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
                      'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
    month_short_en = ['Jan','Feb','Mar','Apr','May','Jun',
                      'Jul','Aug','Sep','Oct','Nov','Dec']
    is_en_lang = (_lang() or 'ar') == 'en'
    yoy_labels = month_short_en if is_en_lang else month_short_ar

    for m in range(1, 13):
        # Current year — month range
        c_start = _dt(cur_year, m, 1)
        c_last  = _cal.monthrange(cur_year, m)[1]
        c_end   = _dt(cur_year, m, c_last, 23, 59, 59)
        c_entries = WalletLedger.query.filter(
            WalletLedger.created_at >= c_start,
            WalletLedger.created_at <= c_end
        ).all()
        c_revenue = sum(float(e.amount or 0) for e in c_entries if _finance_account_for(e) == 'revenue')

        # Previous year — same month
        p_start = _dt(cur_year - 1, m, 1)
        p_last  = _cal.monthrange(cur_year - 1, m)[1]
        p_end   = _dt(cur_year - 1, m, p_last, 23, 59, 59)
        p_entries = WalletLedger.query.filter(
            WalletLedger.created_at >= p_start,
            WalletLedger.created_at <= p_end
        ).all()
        p_revenue = sum(float(e.amount or 0) for e in p_entries if _finance_account_for(e) == 'revenue')

        yoy_current.append(round(c_revenue, 2))
        yoy_previous.append(round(p_revenue, 2))

    def format_local(dt):
        if not dt:
            return '—'
        return dt.strftime('%Y-%m-%d %H:%M')

    now_month = now.month
    now_year  = now.year

    return render_template(
        'admin_finance.html',
        ui_lang             = _lang(),
        summary             = _admin_counts_snapshot(),
        rows                = rows,
        deposits_total      = deposits_total,
        earned_revenue      = earned_revenue,
        refunds_total       = refunds_total,
        operating_expenses  = operating_expenses,
        net_profit          = net_profit,
        cash_in             = cash_in,
        cash_out            = cash_out,
        cash_net            = cash_net,
        customer_liability  = customer_liability,
        period              = period,
        period_start        = period_start,
        period_end          = period_end,
        from_date           = from_date,
        to_date             = to_date,
        monthly_data        = monthly_data,
        max_monthly         = max_monthly,
        category_breakdown  = category_breakdown,
        FINANCE_CATEGORIES  = FINANCE_CATEGORIES,
        PAYMENT_METHODS     = PAYMENT_METHODS,
        PAYMENT_METHODS_MAP = PAYMENT_METHODS_MAP,
        plan_breakdown      = plan_breakdown,
        total_mrr           = total_mrr,
        max_plan_rev        = max_plan_rev,
        active_sub_count    = active_sub_count,
        trial_sub_count     = trial_sub_count,
        tenant_count        = tenant_count,
        recurring_entries   = recurring_entries,
        recurring_monthly   = recurring_monthly,
        recurring_count     = len(recurring_entries),
        top_tenants         = top_tenants,
        tenants             = tenants,
        staff_users         = staff_users,
        daily_stats         = daily_stats,
        weekly_stats        = weekly_stats,
        monthly_stats       = monthly_stats,
        yearly_stats        = yearly_stats,
        format_local        = format_local,
        cur_year            = cur_year,
        now_month           = now_month,
        now_year            = now_year,
        yoy_labels          = yoy_labels,
        yoy_current         = yoy_current,
        yoy_previous        = yoy_previous,
        mrr                 = total_mrr,
        net_balance         = net_profit,
        total_revenue       = earned_revenue,
    )


@billing_bp.route('/admin/finance/export-pdf')
def admin_finance_export_pdf():
    """Pro creative PDF export with full Arabic support and rich design.

    Query params:
      mode         month|quarter|range|year
      month, quarter, year, from_date, to_date
      lang         ar|en (default: ar)
      filter_type  all|expenses|revenue|salaries|subscriptions|refunds|deposits
      inc_summary, inc_category, inc_monthly, inc_ledger,
      inc_wallets, inc_subscribers     (any non-'0' value enables)
    """
    from datetime import datetime as _dt
    guard = _admin_guard('can_manage_finance')
    if guard:
        return guard

    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
        from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame,
            NextPageTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
            PageBreak)
        from reportlab.graphics.shapes import Drawing, Circle, String, Polygon, Rect
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return 'reportlab not installed. Run: pip install reportlab', 500

    import io, os, calendar as _cal, math

    # ── Arabic shaping (lib if available, else builtin) ──
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display as _bidi_display
        _AR_LIB = True
    except Exception:
        arabic_reshaper = None
        _bidi_display = None
        _AR_LIB = False

    _AR_FORMS = {
        'ء': ['ﺀ', 'ﺀ', 'ﺀ', 'ﺀ'],
        'آ': ['ﺁ', 'ﺂ', 'ﺁ', 'ﺂ'],
        'أ': ['ﺃ', 'ﺄ', 'ﺃ', 'ﺄ'],
        'ؤ': ['ﺅ', 'ﺆ', 'ﺅ', 'ﺆ'],
        'إ': ['ﺇ', 'ﺈ', 'ﺇ', 'ﺈ'],
        'ئ': ['ﺉ', 'ﺊ', 'ﺋ', 'ﺌ'],
        'ا': ['ﺍ', 'ﺎ', 'ﺍ', 'ﺎ'],
        'ب': ['ﺏ', 'ﺐ', 'ﺑ', 'ﺒ'],
        'ة': ['ﺓ', 'ﺔ', 'ﺓ', 'ﺔ'],
        'ت': ['ﺕ', 'ﺖ', 'ﺗ', 'ﺘ'],
        'ث': ['ﺙ', 'ﺚ', 'ﺛ', 'ﺜ'],
        'ج': ['ﺝ', 'ﺞ', 'ﺟ', 'ﺠ'],
        'ح': ['ﺡ', 'ﺢ', 'ﺣ', 'ﺤ'],
        'خ': ['ﺥ', 'ﺦ', 'ﺧ', 'ﺨ'],
        'د': ['ﺩ', 'ﺪ', 'ﺩ', 'ﺪ'],
        'ذ': ['ﺫ', 'ﺬ', 'ﺫ', 'ﺬ'],
        'ر': ['ﺭ', 'ﺮ', 'ﺭ', 'ﺮ'],
        'ز': ['ﺯ', 'ﺰ', 'ﺯ', 'ﺰ'],
        'س': ['ﺱ', 'ﺲ', 'ﺳ', 'ﺴ'],
        'ش': ['ﺵ', 'ﺶ', 'ﺷ', 'ﺸ'],
        'ص': ['ﺹ', 'ﺺ', 'ﺻ', 'ﺼ'],
        'ض': ['ﺽ', 'ﺾ', 'ﺿ', 'ﻀ'],
        'ط': ['ﻁ', 'ﻂ', 'ﻃ', 'ﻄ'],
        'ظ': ['ﻅ', 'ﻆ', 'ﻇ', 'ﻈ'],
        'ع': ['ﻉ', 'ﻊ', 'ﻋ', 'ﻌ'],
        'غ': ['ﻍ', 'ﻎ', 'ﻏ', 'ﻐ'],
        'ف': ['ﻑ', 'ﻒ', 'ﻓ', 'ﻔ'],
        'ق': ['ﻕ', 'ﻖ', 'ﻗ', 'ﻘ'],
        'ك': ['ﻙ', 'ﻚ', 'ﻛ', 'ﻜ'],
        'ل': ['ﻝ', 'ﻞ', 'ﻟ', 'ﻠ'],
        'م': ['ﻡ', 'ﻢ', 'ﻣ', 'ﻤ'],
        'ن': ['ﻥ', 'ﻦ', 'ﻧ', 'ﻨ'],
        'ه': ['ﻩ', 'ﻪ', 'ﻫ', 'ﻬ'],
        'و': ['ﻭ', 'ﻮ', 'ﻭ', 'ﻮ'],
        'ي': ['ﻱ', 'ﻲ', 'ﻳ', 'ﻴ'],
        'ى': ['ﻯ', 'ﻰ', 'ﻯ', 'ﻰ'],
    }
    _AR_NON_CONNECT_NEXT = set('ءآأإادذرزو')

    def _is_arabic_letter(ch):
        return ch in _AR_FORMS

    def _has_arabic(s):
        if not s: return False
        for ch in str(s):
            if '؀' <= ch <= 'ۿ' or 'ݐ' <= ch <= 'ݿ' or 'ﭐ' <= ch <= '﻿':
                return True
        return False

    def _builtin_shape(text):
        if not text:
            return text
        out = []
        i = 0; n = len(text)
        while i < n:
            ch = text[i]
            if _is_arabic_letter(ch) or ch == ' ' or ('؀' <= ch <= 'ۿ'):
                j = i
                while j < n and (_is_arabic_letter(text[j]) or text[j] == ' ' or ('؀' <= text[j] <= 'ۿ')):
                    j += 1
                run = text[i:j]
                shaped = []
                for k, c in enumerate(run):
                    if not _is_arabic_letter(c):
                        shaped.append(c); continue
                    forms = _AR_FORMS.get(c, [c, c, c, c])
                    p = k - 1
                    while p >= 0 and run[p] == ' ':
                        p -= 1
                    has_prev = p >= 0 and _is_arabic_letter(run[p]) and run[p] not in _AR_NON_CONNECT_NEXT
                    nxt = k + 1
                    while nxt < len(run) and run[nxt] == ' ':
                        nxt += 1
                    has_next = nxt < len(run) and _is_arabic_letter(run[nxt]) and c not in _AR_NON_CONNECT_NEXT
                    if has_prev and has_next:
                        shaped.append(forms[3])
                    elif has_prev and not has_next:
                        shaped.append(forms[1])
                    elif not has_prev and has_next:
                        shaped.append(forms[2])
                    else:
                        shaped.append(forms[0])
                out.append(''.join(reversed(shaped)))
                i = j
            else:
                j = i
                while j < n and not (_is_arabic_letter(text[j]) or ('؀' <= text[j] <= 'ۿ')):
                    j += 1
                out.append(text[i:j])
                i = j
        return ''.join(out)

    def AR(text):
        if text is None: return ''
        s = str(text)
        if _AR_LIB:
            try:
                return _bidi_display(arabic_reshaper.reshape(s))
            except Exception:
                pass
        try:
            return _builtin_shape(s)
        except Exception:
            return s

    # ── Font registration ──
    AR_FONT = 'Helvetica'
    AR_FONT_BOLD = 'Helvetica-Bold'
    candidate_dirs = [
        os.path.join(current_app.root_path, 'static', 'fonts'),
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static', 'fonts')),
    ]
    for d in candidate_dirs:
        rp = os.path.join(d, 'NotoSansArabic-Regular.ttf')
        bp = os.path.join(d, 'NotoSansArabic-Bold.ttf')
        try:
            if os.path.exists(rp):
                pdfmetrics.registerFont(TTFont('NotoArabic', rp))
                AR_FONT = 'NotoArabic'
            if os.path.exists(bp):
                pdfmetrics.registerFont(TTFont('NotoArabicBold', bp))
                AR_FONT_BOLD = 'NotoArabicBold'
            if AR_FONT == 'NotoArabic':
                break
        except Exception as exc:
            current_app.logger.warning('Font registration error: %s', exc)

    # ── Language ──
    lang = (request.args.get('lang') or _lang() or 'ar').strip().lower()
    is_en = lang == 'en'

    def L(en, ar):
        if is_en:
            return str(en)
        return AR(ar)

    def P(text):
        return str(text) if is_en else AR(text)

    def _pdf_account_label(account):
        raw = (account or '').strip()
        if is_en:
            return (raw or '-').upper()
        labels = {
            'revenue': 'إيراد',
            'expense': 'مصروف',
            'liability': 'التزام',
            'refund': 'استرداد',
            'other': 'أخرى',
        }
        return AR(labels.get(raw.lower(), raw or '-'))

    def _pdf_status_label(status):
        raw = (status or 'unknown').strip()
        if is_en:
            return raw.upper()
        labels = {
            'active': 'نشط',
            'trial': 'تجريبي',
            'inactive': 'غير نشط',
            'suspended': 'موقوف',
            'pending': 'قيد الانتظار',
            'expired': 'منتهي',
            'cancelled': 'ملغي',
            'canceled': 'ملغي',
            'unknown': 'غير معروف',
        }
        return AR(labels.get(raw.lower(), raw or 'غير معروف'))

    def _pdf_plan_label(plan_obj):
        if not plan_obj:
            return '-'
        if is_en:
            return (plan_obj.name_en or plan_obj.code or '-')
        raw = (plan_obj.name_ar or '').strip()
        if not raw:
            raw = {
                'free': 'مجاني',
                'trial': 'تجريبي',
                'basic': 'أساسي',
                'starter': 'مبتدئ',
                'pro': 'احترافي',
                'professional': 'احترافي',
                'business': 'أعمال',
                'enterprise': 'مؤسسات',
            }.get((plan_obj.code or '').lower(), plan_obj.code or '-')
        return AR(raw)

    # ── Date range ──
    now = _dt.utcnow()
    mode = (request.args.get('mode') or 'month').strip()
    year = int(request.args.get('year', now.year))

    AR_MONTHS = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
                 'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
    EN_MONTHS = ['January','February','March','April','May','June',
                 'July','August','September','October','November','December']

    def month_label(m, y):
        if is_en:
            return '{} {}'.format(EN_MONTHS[m-1], y)
        return '{} {}'.format(AR_MONTHS[m-1], y)

    if mode == 'range':
        try:    date_start = _dt.strptime(request.args.get('from_date',''), '%Y-%m-%d')
        except: date_start = now.replace(day=1, hour=0, minute=0, second=0)
        try:    date_end   = _dt.strptime(request.args.get('to_date',''), '%Y-%m-%d').replace(hour=23,minute=59,second=59)
        except: date_end   = now
        period_label = '{} - {}'.format(date_start.strftime('%Y-%m-%d'), date_end.strftime('%Y-%m-%d')) if is_en else \
            'من {} إلى {}'.format(date_start.strftime('%Y-%m-%d'), date_end.strftime('%Y-%m-%d'))
        filename_tag = '{}_{}'.format(date_start.strftime('%Y%m%d'), date_end.strftime('%Y%m%d'))
    elif mode == 'quarter':
        quarter = int(request.args.get('quarter', (now.month - 1) // 3 + 1))
        q_months = {1:(1,3), 2:(4,6), 3:(7,9), 4:(10,12)}
        m_start, m_end = q_months.get(quarter, (1,3))
        date_start = _dt(year, m_start, 1)
        last_day = _cal.monthrange(year, m_end)[1]
        date_end = _dt(year, m_end, last_day, 23, 59, 59)
        quarter_ar = {1: 'الربع الأول', 2: 'الربع الثاني', 3: 'الربع الثالث', 4: 'الربع الرابع'}
        period_label = 'Q{} {}'.format(quarter, year) if is_en else '{} {}'.format(quarter_ar.get(quarter, 'الربع الأول'), year)
        filename_tag = '{}_Q{}'.format(year, quarter)
    elif mode == 'year':
        date_start = _dt(year, 1, 1)
        date_end = _dt(year, 12, 31, 23, 59, 59)
        period_label = ('Full Year {}'.format(year)) if is_en else 'السنة الكاملة {}'.format(year)
        filename_tag = '{}_annual'.format(year)
    else:
        month = int(request.args.get('month', now.month))
        date_start = _dt(year, month, 1)
        last_day = _cal.monthrange(year, month)[1]
        date_end = _dt(year, month, last_day, 23, 59, 59)
        period_label = month_label(month, year)
        filename_tag = '{}_{:02d}'.format(year, month)

    # ── Section toggles ──
    inc_summary     = request.args.get('inc_summary')     not in ('0', None, '')
    inc_category    = request.args.get('inc_category')    not in ('0', None, '')
    inc_monthly     = request.args.get('inc_monthly')     not in ('0', None, '')
    inc_ledger      = request.args.get('inc_ledger')      not in ('0', None, '')
    inc_wallets     = request.args.get('inc_wallets')     not in ('0', None, '')
    inc_subscribers = request.args.get('inc_subscribers') not in ('0', None, '')
    if not any([inc_summary, inc_category, inc_monthly, inc_ledger, inc_wallets, inc_subscribers]):
        inc_summary = True

    filter_type = (request.args.get('filter_type') or 'all').strip().lower()

    # ── Query ──
    base_q = WalletLedger.query.filter(
        WalletLedger.created_at >= date_start,
        WalletLedger.created_at <= date_end,
    ).order_by(WalletLedger.created_at.asc())
    all_entries = base_q.all()

    SALARY_CATS = {'salary', 'admin_salary'}
    SUB_CATS = {'subscription', 'renewal'}
    def _matches_filter(e, ft):
        acc = _finance_account_for(e)
        if ft == 'all':           return True
        if ft == 'expenses':      return acc == 'expense'
        if ft == 'revenue':       return acc == 'revenue'
        if ft == 'refunds':       return acc == 'refund'
        if ft == 'deposits':      return acc == 'liability' and e.entry_type == 'credit'
        if ft == 'salaries':      return (e.category or '') in SALARY_CATS
        if ft == 'subscriptions': return (e.category or '') in SUB_CATS
        return True
    filtered_entries = [e for e in all_entries if _matches_filter(e, filter_type)]

    earned  = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'revenue')
    expense = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'expense')
    deposit = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'liability' and e.entry_type == 'credit')
    refund  = sum(float(e.amount or 0) for e in all_entries if _finance_account_for(e) == 'refund')
    net     = earned - expense

    # ════════════════════════════════════════════════════════════════
    # Pro Creative PDF Design
    # ════════════════════════════════════════════════════════════════
    buf = io.BytesIO()
    PORTRAIT_SIZE = A4
    LANDSCAPE_SIZE = landscape(A4)
    doc = BaseDocTemplate(buf, pagesize=PORTRAIT_SIZE,
                          rightMargin=1.4*cm, leftMargin=1.4*cm,
                          topMargin=1.6*cm, bottomMargin=1.8*cm,
                          title='SolarDeye Accounting Report',
                          author='SolarDeye')
    styles = getSampleStyleSheet()
    C = colors.HexColor

    body_align = TA_RIGHT if not is_en else TA_LEFT

    PALETTE = {
        'ink':'#0f172a','ink_soft':'#475569','muted':'#94a3b8','border':'#e2e8f0',
        'bg_soft':'#f8fafc','blue':'#2563eb','green':'#10b981','green_soft':'#dcfce7',
        'red':'#ef4444','red_soft':'#fee2e2','amber':'#f59e0b','amber_soft':'#fef3c7',
        'purple':'#8b5cf6','teal':'#14b8a6',
    }

    title_style = ParagraphStyle('T', parent=styles['Title'],
        fontName=AR_FONT_BOLD, fontSize=22, leading=28, spaceAfter=8,
        alignment=TA_CENTER, textColor=C(PALETTE['ink']))
    subtitle_style = ParagraphStyle('ST', parent=styles['Normal'],
        fontName=AR_FONT, fontSize=11, leading=16, spaceAfter=14,
        alignment=TA_CENTER, textColor=C(PALETTE['ink_soft']))
    sub_style = ParagraphStyle('S', parent=styles['Normal'],
        fontName=AR_FONT, fontSize=9.5, spaceAfter=10,
        alignment=TA_CENTER, textColor=C(PALETTE['muted']))
    section_sub_style = ParagraphStyle('HS', parent=styles['Normal'],
        fontName=AR_FONT, fontSize=9, spaceAfter=10, leading=13,
        alignment=body_align, textColor=C(PALETTE['muted']))
    cell_style = ParagraphStyle('CELL', parent=styles['Normal'],
        fontName=AR_FONT, fontSize=8.4, leading=11,
        alignment=TA_CENTER, textColor=C(PALETTE['ink']))
    cover_brand = ParagraphStyle('CV', parent=styles['Normal'],
        fontName=AR_FONT_BOLD, fontSize=34, leading=40, spaceAfter=4,
        alignment=TA_CENTER, textColor=C(PALETTE['ink']))
    cover_eyebrow = ParagraphStyle('CE', parent=styles['Normal'],
        fontName=AR_FONT_BOLD, fontSize=11, leading=15, spaceAfter=20,
        alignment=TA_CENTER, textColor=C(PALETTE['blue']))
    cover_period = ParagraphStyle('CP', parent=styles['Normal'],
        fontName=AR_FONT_BOLD, fontSize=18, leading=24, spaceAfter=18,
        alignment=TA_CENTER, textColor=C(PALETTE['ink']))

    def _pdf_cell(text):
        return Paragraph(str(text or '-'), cell_style)

    def _make_logo(size=80):
        d = Drawing(size, size)
        cx, cy = size/2, size/2
        r_in, r_out = size*0.30, size*0.46
        for i in range(8):
            a = i * (math.pi / 4)
            x1, y1 = cx + r_in*math.cos(a),  cy + r_in*math.sin(a)
            x2, y2 = cx + r_out*math.cos(a-0.18), cy + r_out*math.sin(a-0.18)
            x3, y3 = cx + r_out*math.cos(a+0.18), cy + r_out*math.sin(a+0.18)
            d.add(Polygon(points=[x1,y1,x2,y2,x3,y3], fillColor=C(PALETTE['amber']), strokeColor=None))
        d.add(Circle(cx=cx, cy=cy, r=size*0.28, fillColor=C('#fbbf24'),
                     strokeColor=C(PALETTE['amber']), strokeWidth=1.5))
        d.add(String(cx, cy - size*0.10, 'SD', fontName='Helvetica-Bold',
                     fontSize=size*0.30, fillColor=C(PALETTE['ink']), textAnchor='middle'))
        return d

    def _kpi_card(title, value, color_key):
        clr = PALETTE.get(color_key, PALETTE['blue'])
        title_p = Paragraph(title, ParagraphStyle('KT', fontName=AR_FONT_BOLD,
            fontSize=8.5, alignment=TA_CENTER, textColor=C(PALETTE['ink_soft']), leading=11))
        value_p = Paragraph(value, ParagraphStyle('KV', fontName=AR_FONT_BOLD,
            fontSize=14, alignment=TA_CENTER, textColor=C(PALETTE['ink']), leading=18))
        cur_p = Paragraph(L('USD', 'دولار'), ParagraphStyle('KC', fontName=AR_FONT,
            fontSize=7, alignment=TA_CENTER, textColor=C(PALETTE['muted']), leading=9))
        cell = Table([[title_p],[value_p],[cur_p]], colWidths=[None], rowHeights=[14, 22, 12])
        cell.setStyle(TableStyle([
            ('LINEABOVE',(0,0),(-1,0), 3, C(clr)),
            ('BACKGROUND',(0,0),(-1,-1), C(PALETTE['bg_soft'])),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1), 4),
            ('BOTTOMPADDING',(0,0),(-1,-1), 4),
            ('BOX',(0,0),(-1,-1), 0.5, C(PALETTE['border'])),
        ]))
        return cell

    def _section_header(text, icon, color_key):
        clr = PALETTE.get(color_key, PALETTE['blue'])
        icon_p = Paragraph('<font color="white">{}</font>'.format(icon),
            ParagraphStyle('SI', fontName='Helvetica-Bold', fontSize=14, alignment=TA_CENTER, leading=22))
        title_p = Paragraph(text, ParagraphStyle('SH', fontName=AR_FONT_BOLD,
            fontSize=13, alignment=body_align, textColor=C(PALETTE['ink']), leading=18))
        if is_en:
            row = [[icon_p, title_p]]
            cw = [1.0*cm, 16.5*cm]
        else:
            row = [[title_p, icon_p]]
            cw = [16.5*cm, 1.0*cm]
        h = Table(row, colWidths=cw, rowHeights=[0.85*cm])
        h.setStyle(TableStyle([
            ('BACKGROUND',(0 if is_en else 1, 0),(0 if is_en else 1, 0), C(clr)),
            ('BACKGROUND',(1 if is_en else 0, 0),(1 if is_en else 0, 0), C(PALETTE['bg_soft'])),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,-1), 12),
            ('RIGHTPADDING',(0,0),(-1,-1), 12),
        ]))
        return h

    def _make_table(rows, col_widths, header_bg='#1e293b'):
        t = Table(rows, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), C(header_bg)),
            ('TEXTCOLOR',(0,0),(-1,0), colors.white),
            ('FONTNAME',(0,0),(-1,0), AR_FONT_BOLD),
            ('FONTSIZE',(0,0),(-1,0), 10),
            ('TOPPADDING',(0,0),(-1,0), 8),
            ('BOTTOMPADDING',(0,0),(-1,0), 8),
            ('FONTNAME',(0,1),(-1,-1), AR_FONT),
            ('FONTSIZE',(0,1),(-1,-1), 9.5),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [C(PALETTE['bg_soft']), colors.white]),
            ('GRID',(0,0),(-1,-1), 0.4, C(PALETTE['border'])),
            ('TOPPADDING',(0,1),(-1,-1), 7),
            ('BOTTOMPADDING',(0,1),(-1,-1), 7),
            ('LEFTPADDING',(0,0),(-1,-1), 8),
            ('RIGHTPADDING',(0,0),(-1,-1), 8),
        ]))
        return t

    filter_label_map = {
        'all':           ('All Transactions', 'كل الحركات'),
        'expenses':      ('Expenses Only',    'المصاريف فقط'),
        'revenue':       ('Revenue Only',     'الإيرادات فقط'),
        'salaries':      ('Salaries Only',    'الرواتب فقط'),
        'subscriptions': ('Subscriptions',    'الاشتراكات'),
        'refunds':       ('Refunds',          'الاستردادات'),
        'deposits':      ('Deposits',         'الإيداعات'),
    }
    flt_en, flt_ar = filter_label_map.get(filter_type, filter_label_map['all'])

    story = []
    # ── COVER PAGE ──
    story.append(Spacer(1, 1.5*cm))
    logo_tbl = Table([[_make_logo(80)]], colWidths=[18*cm], rowHeights=[2.6*cm])
    logo_tbl.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story.append(logo_tbl)
    story.append(Paragraph(L('SOLARDEYE  ·  ACCOUNTING REPORT', 'سولار دي آي  ·  تقرير محاسبي'), cover_eyebrow))
    story.append(Paragraph(L('Financial Statement', 'البيان المالي'), cover_brand))
    story.append(Paragraph(P(period_label), cover_period))
    story.append(Paragraph(L('Filter: {}'.format(flt_en), 'الفلتر: {}'.format(flt_ar)), subtitle_style))
    story.append(Spacer(1, 0.6*cm))

    cards_row = [
        _kpi_card(L('Earned Revenue', 'الإيرادات المكتسبة'), '{:,.2f}'.format(earned), 'green'),
        _kpi_card(L('Operating Costs', 'مصاريف التشغيل'), '{:,.2f}'.format(expense), 'red'),
        _kpi_card(L('Net P&L', 'صافي الربح والخسارة'), '{:+,.2f}'.format(net), 'green' if net >= 0 else 'red'),
        _kpi_card(L('Customer Deposits', 'إيداعات المشتركين'), '{:,.2f}'.format(deposit), 'blue'),
    ]
    kpi_grid = Table([cards_row], colWidths=[4.4*cm]*4, rowHeights=[2.6*cm])
    kpi_grid.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1), 4),('RIGHTPADDING',(0,0),(-1,-1), 4)]))
    story.append(kpi_grid)
    story.append(Spacer(1, 1.0*cm))
    info_para = Paragraph(L(
        'Issued: {} UTC  ·  Document #: SD-{}  ·  Transactions: {}'.format(now.strftime('%Y-%m-%d %H:%M'), filename_tag, len(all_entries)),
        'تاريخ الإصدار: {}  ·  رقم المستند: {}  ·  عدد الحركات: {}'.format(now.strftime('%Y-%m-%d %H:%M'), filename_tag, len(all_entries))
    ), sub_style)
    story.append(info_para)
    story.append(PageBreak())

    # ── SECTION 1: P&L SUMMARY ──
    if inc_summary:
        story.append(_section_header(L('Profit & Loss Summary', 'ملخص الأرباح والخسائر'), '$', 'blue'))
        story.append(Paragraph(L(
            'Financial overview of revenue, expenses, refunds and deposits during the report period.',
            'نظرة مالية شاملة على الإيرادات والمصاريف والاستردادات والإيداعات خلال فترة التقرير.'
        ), section_sub_style))
        rows = [
            [L('Account Item', 'البند'), L('Account Type', 'نوع الحساب'), L('Amount (USD)', 'المبلغ (دولار)')],
            [L('Customer Deposits', 'إيداعات المشتركين'), L('Liability', 'التزام'), '{:,.2f}'.format(deposit)],
            [L('Earned Revenue', 'إيرادات الخدمات المكتسبة'), L('Revenue', 'إيراد'), '{:,.2f}'.format(earned)],
            [L('Refunds Issued', 'الاستردادات الصادرة'), L('Contra Revenue', 'عكس إيراد'), '({:,.2f})'.format(refund)],
            [L('Operating Expenses', 'مصاريف التشغيل'), L('Expense', 'مصروف'), '({:,.2f})'.format(expense)],
            [L('Net Profit / Loss', 'صافي الربح / الخسارة'), '', '{:+,.2f}'.format(net)],
        ]
        t = _make_table(rows, [7*cm, 5*cm, 5.5*cm], header_bg=PALETTE['ink'])
        net_color = PALETTE['green_soft'] if net >= 0 else PALETTE['red_soft']
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,-1),(-1,-1), C(net_color)),
            ('FONTNAME',(0,-1),(-1,-1), AR_FONT_BOLD),
            ('FONTSIZE',(0,-1),(-1,-1), 11),
            ('TOPPADDING',(0,-1),(-1,-1), 10),
            ('BOTTOMPADDING',(0,-1),(-1,-1), 10),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.5*cm))

    # ── SECTION 2: CATEGORY BREAKDOWN ──
    if inc_category and all_entries:
        from collections import defaultdict
        cat_totals = defaultdict(float)
        for e in all_entries:
            cat_totals[e.category or 'general'] += float(e.amount or 0)
        if cat_totals:
            story.append(_section_header(L('Category Breakdown', 'تحليل الفئات'), '#', 'purple'))
            story.append(Paragraph(L(
                'Transaction totals broken down by accounting category, with each category share.',
                'إجمالي الحركات موزع حسب الفئة المحاسبية، مع نسبة كل فئة من المجموع.'
            ), section_sub_style))
            rows = [[L('Category', 'الفئة'), L('Account', 'الحساب'),
                     L('Total (USD)', 'الإجمالي (دولار)'), L('Share %', 'النسبة %')]]
            total_all = sum(cat_totals.values()) or 1
            for cat_key, total in sorted(cat_totals.items(), key=lambda x: -x[1]):
                meta = _finance_category_meta(cat_key)
                lbl = meta.get('label_en', cat_key) if is_en else AR(meta.get('label_ar', cat_key))
                acc = _pdf_account_label(meta.get('account', '-'))
                pct = (total / total_all) * 100
                rows.append([lbl, acc, '{:,.2f}'.format(total), '{:.1f}%'.format(pct)])
            ct = _make_table(rows, [6.5*cm, 4*cm, 4*cm, 3*cm], header_bg=PALETTE['purple'])
            story.append(ct)
            story.append(Spacer(1, 0.5*cm))

    # ── SECTION 3: MONTHLY (year mode) ──
    if inc_monthly and mode == 'year':
        story.append(_section_header(L('Monthly Breakdown', 'التفصيل الشهري'), 'M', 'teal'))
        story.append(Paragraph(L(
            'Month-by-month performance for the selected year.',
            'الأداء الشهري للسنة المختارة.'
        ), section_sub_style))
        rows = [[L('Month', 'الشهر'), L('Revenue', 'الإيرادات'),
                 L('Expenses', 'المصاريف'), L('Net', 'الصافي')]]
        for m in range(1, 13):
            m_s = _dt(year, m, 1)
            m_e = _dt(year, m, _cal.monthrange(year, m)[1], 23, 59, 59)
            m_entries = [e for e in all_entries if m_s <= (e.created_at or _dt.min) <= m_e]
            m_rev = sum(float(e.amount or 0) for e in m_entries if _finance_account_for(e) == 'revenue')
            m_exp = sum(float(e.amount or 0) for e in m_entries if _finance_account_for(e) == 'expense')
            if m_rev > 0 or m_exp > 0:
                rows.append([P(month_label(m, year)), '{:,.2f}'.format(m_rev),
                             '{:,.2f}'.format(m_exp), '{:+,.2f}'.format(m_rev-m_exp)])
        if len(rows) > 1:
            mt = _make_table(rows, [5*cm, 4.5*cm, 4.5*cm, 3.5*cm], header_bg=PALETTE['teal'])
            story.append(mt)
            story.append(Spacer(1, 0.5*cm))

    # ── SECTION 4: LEDGER ──
    if inc_ledger and filtered_entries:
        story.append(NextPageTemplate('landscape'))
        story.append(PageBreak())
        story.append(_section_header(
            L('Transaction Ledger ({}) - {} entries'.format(flt_en, len(filtered_entries)),
              'دفتر الأستاذ ({}) - {} حركة'.format(flt_ar, len(filtered_entries))),
            'L', 'blue'))
        story.append(Paragraph(L(
            'Detailed list of accounting entries matching the selected filter.',
            'قائمة تفصيلية بالحركات المحاسبية التي تطابق الفلتر المختار.'
        ), section_sub_style))
        tids = {e.tenant_id for e in filtered_entries if e.tenant_id}
        tmap = {t.id: t for t in TenantAccount.query.filter(TenantAccount.id.in_(tids)).all()} if tids else {}
        rows = [[L('Date','التاريخ'), L('Subscriber','المشترك'),
                 L('Type','النوع'), L('Category','الفئة'),
                 L('Reference','المرجع'), L('Amount','المبلغ'), L('Notes','البيان')]]
        for e in filtered_entries:
            meta = _finance_category_meta(e.category)
            ten = tmap.get(e.tenant_id)
            tname = (ten.display_name if ten else '-')
            if tname != '-' and _has_arabic(tname):
                tname = AR(tname)
            cat_label = meta.get('label_en', e.category or '') if is_en else AR(meta.get('label_ar', e.category or ''))
            type_label = ('CREDIT' if e.entry_type == 'credit' else 'DEBIT') if is_en else AR('دائن' if e.entry_type == 'credit' else 'مدين')
            note = (e.note or '')[:60]
            if note and _has_arabic(note):
                note = AR(note)
            rows.append([
                _pdf_cell(e.created_at.strftime('%Y-%m-%d') if e.created_at else '-'),
                _pdf_cell(tname), _pdf_cell(type_label), _pdf_cell(cat_label),
                _pdf_cell(e.reference or '-'),
                _pdf_cell('{:,.2f}'.format(float(e.amount or 0))),
                _pdf_cell(note),
            ])
        lt = _make_table(rows, [2.6*cm, 4.2*cm, 2.2*cm, 3.4*cm, 4.0*cm, 2.8*cm, 7.7*cm],
                         header_bg=PALETTE['ink'])
        story.append(lt)
        story.append(Spacer(1, 0.5*cm))
        story.append(NextPageTemplate('portrait'))

    # ── SECTION 5: WALLETS ──
    if inc_wallets:
        story.append(PageBreak())
        story.append(_section_header(L('Subscriber Wallets', 'محافظ المشتركين'), 'W', 'amber'))
        story.append(Paragraph(L(
            'Current balance for each subscriber wallet, computed from all ledger entries.',
            'الرصيد الحالي لكل محفظة مشترك، محسوب من جميع حركات دفتر الأستاذ.'
        ), section_sub_style))
        tenants_all = TenantAccount.query.order_by(TenantAccount.id.asc()).all()
        rows = [[L('#','#'), L('Subscriber','المشترك'), L('Status','الحالة'),
                 L('Plan','الخطة'), L('Balance (USD)','الرصيد (دولار)')]]
        n = 0
        for t in tenants_all:
            if t.display_name == 'Company Operations':
                continue
            n += 1
            t_entries = WalletLedger.query.filter_by(tenant_id=t.id).all()
            balance = sum(_finance_signed_wallet_amount(e) for e in t_entries)
            plan_obj = SubscriptionPlan.query.get(t.plan_id) if t.plan_id else None
            plan_name = _pdf_plan_label(plan_obj)
            tname = t.display_name or 'Tenant {}'.format(t.id)
            if _has_arabic(tname):
                tname = AR(tname)
            status_text = _pdf_status_label(t.status)
            rows.append([str(n), tname, status_text, plan_name, '{:+,.2f}'.format(balance)])
        if n > 0:
            wt = _make_table(rows, [1.2*cm, 5.5*cm, 3*cm, 4*cm, 3.8*cm], header_bg=PALETTE['amber'])
            story.append(wt)
            story.append(Spacer(1, 0.5*cm))

    # ── SECTION 6: SUBSCRIBERS ──
    if inc_subscribers:
        story.append(PageBreak())
        story.append(_section_header(L('Subscribers Directory', 'دليل المشتركين'), 'S', 'green'))
        story.append(Paragraph(L(
            'Complete list of registered subscribers with their plan and status.',
            'قائمة كاملة بالمشتركين المسجلين مع خططهم وحالاتهم.'
        ), section_sub_style))
        rows = [[L('#','#'), L('Name','الاسم'), L('Status','الحالة'),
                 L('Plan','الخطة'), L('Created','تاريخ الإنشاء')]]
        all_t = TenantAccount.query.order_by(TenantAccount.id.asc()).all()
        n = 0
        for t in all_t:
            if t.display_name == 'Company Operations':
                continue
            n += 1
            plan_obj = SubscriptionPlan.query.get(t.plan_id) if t.plan_id else None
            plan_name = _pdf_plan_label(plan_obj)
            tname = t.display_name or 'Tenant {}'.format(t.id)
            if _has_arabic(tname):
                tname = AR(tname)
            status_text = _pdf_status_label(t.status)
            created = t.created_at.strftime('%Y-%m-%d') if getattr(t, 'created_at', None) else '-'
            rows.append([str(n), tname, status_text, plan_name, created])
        if n > 0:
            st = _make_table(rows, [1.2*cm, 6*cm, 3*cm, 4*cm, 3.3*cm], header_bg=PALETTE['green'])
            story.append(st)

    # ── Footer ──
    def _on_page(canvas_obj, doc_obj):
        canvas_obj.saveState()
        if doc_obj.page == 1:
            canvas_obj.restoreState()
            return
        page_w, page_h = canvas_obj._pagesize
        canvas_obj.setFillColor(C(PALETTE['bg_soft']))
        canvas_obj.rect(0, 0, page_w, 1.2*cm, fill=1, stroke=0)
        canvas_obj.setFont(AR_FONT, 8)
        canvas_obj.setFillColor(C(PALETTE['muted']))
        page_text = ('Page {}'.format(doc_obj.page)) if is_en else AR('صفحة {}'.format(doc_obj.page))
        brand_text = 'SolarDeye Accounting' if is_en else AR('محاسبة سولار دي آي')
        canvas_obj.drawCentredString(page_w/2, 0.45*cm, brand_text + '  ·  ' + page_text)
        canvas_obj.setStrokeColor(C(PALETTE['amber']))
        canvas_obj.setLineWidth(2)
        canvas_obj.line(1.4*cm, page_h - 1.0*cm, page_w - 1.4*cm, page_h - 1.0*cm)
        canvas_obj.restoreState()

    portrait_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='portrait_frame')
    landscape_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        LANDSCAPE_SIZE[0] - doc.leftMargin - doc.rightMargin,
        LANDSCAPE_SIZE[1] - doc.topMargin - doc.bottomMargin,
        id='landscape_frame',
    )
    doc.addPageTemplates([
        PageTemplate(id='portrait', frames=[portrait_frame], onPage=_on_page, pagesize=PORTRAIT_SIZE),
        PageTemplate(id='landscape', frames=[landscape_frame], onPage=_on_page, pagesize=LANDSCAPE_SIZE),
    ])

    doc.build(story)
    buf.seek(0)
    from flask import send_file
    download_name = 'solardeya_accounting_{}.pdf'.format(filename_tag) if is_en else 'تقرير_محاسبي_{}.pdf'.format(filename_tag)
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=download_name)
