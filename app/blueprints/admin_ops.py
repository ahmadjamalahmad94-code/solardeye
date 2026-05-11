from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import AppDevice, AppUser, DeviceType, NotificationLog, ServiceHeartbeat, SubscriptionPlan, SupportCase, SyncLog, TenantAccount, TenantSubscription
from ..services.backup_service import backup_settings
from ..services.i18n import translate
from ..services.labels import label
from ..services.scope import has_permission, is_system_admin
from ..services.rbac import admin_landing_url
from ..services.service_monitor import service_display_name, service_message, service_source_label
from ..services.subscriptions import ensure_user_tenant_and_subscription
from ..services.utils import format_local_datetime
from ..services.web_design_qa import build_web_design_qa

admin_ops_bp = Blueprint('admin_ops', __name__)


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _admin_guard(permission: str = 'can_manage_users'):
    if is_system_admin() or has_permission(permission):
        return None
    flash('This page is not available for your account.' if _lang() == 'en' else 'هذه الصفحة غير متاحة لحسابك.', 'warning')
    return redirect(admin_landing_url(_lang()))


@admin_ops_bp.route('/admin/subscribers')
def admin_subscribers_v9():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    subscriber_roles = ('', 'user', 'subscriber', 'customer')
    users = AppUser.query.filter(
        db.or_(AppUser.is_admin.is_(False), AppUser.is_admin.is_(None)),
        db.or_(AppUser.role.is_(None), AppUser.role.in_(subscriber_roles)),
    ).order_by(AppUser.created_at.desc(), AppUser.id.desc()).all()
    plans = {p.id: p for p in SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()}
    user_ids = [user.id for user in users]
    tenant_ids = {user.tenant_id for user in users if getattr(user, 'tenant_id', None)}
    tenants_by_id = {
        tenant.id: tenant
        for tenant in (
            TenantAccount.query.filter(TenantAccount.id.in_(tenant_ids)).all()
            if tenant_ids else []
        )
    }
    for user in users:
        if not getattr(user, 'tenant_id', None) or user.tenant_id not in tenants_by_id:
            tenant, _ = ensure_user_tenant_and_subscription(user)
            if tenant:
                tenants_by_id[tenant.id] = tenant
                tenant_ids.add(tenant.id)
    subscription_rows = (
        TenantSubscription.query
        .filter(TenantSubscription.tenant_id.in_(tenant_ids))
        .order_by(TenantSubscription.tenant_id.asc(), TenantSubscription.created_at.desc(), TenantSubscription.id.desc())
        .all()
        if tenant_ids else []
    )
    subscriptions_by_tenant = {}
    for sub in subscription_rows:
        subscriptions_by_tenant.setdefault(sub.tenant_id, sub)
    device_counts = {
        owner_id: count
        for owner_id, count in (
            db.session.query(AppDevice.owner_user_id, db.func.count(AppDevice.id))
            .filter(AppDevice.owner_user_id.in_(user_ids), AppDevice.is_active.is_(True))
            .group_by(AppDevice.owner_user_id)
            .all()
            if user_ids else []
        )
    }
    support_open = db.or_(SupportCase.status.is_(None), ~SupportCase.status.in_(('closed', 'resolved')))
    support_cases = (
        SupportCase.query
        .with_entities(SupportCase.id, SupportCase.tenant_id, SupportCase.user_id, SupportCase.case_type)
        .filter(
            support_open,
            db.or_(SupportCase.tenant_id.in_(tenant_ids), SupportCase.user_id.in_(user_ids)),
        )
        .all()
        if tenant_ids or user_ids else []
    )
    stats = {'total': 0, 'active': 0, 'trial': 0, 'expired': 0, 'suspended': 0, 'disabled': 0}
    rows = []
    now = datetime.utcnow()
    for user in users:
        tenant = tenants_by_id.get(user.tenant_id)
        sub = subscriptions_by_tenant.get(getattr(tenant, 'id', None))
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
        open_message_count = 0
        open_ticket_count = 0
        for case in support_cases:
            if case.tenant_id == getattr(tenant, 'id', None) or case.user_id == user.id:
                if case.case_type == 'message':
                    open_message_count += 1
                elif case.case_type == 'ticket':
                    open_ticket_count += 1
        rows.append({
            'user': user,
            'tenant': tenant,
            'subscription': sub,
            'plan': plan,
            'status': status,
            'days_left': days_left,
            'device_count': device_counts.get(user.id, 0),
            'open_message_count': open_message_count,
            'open_ticket_count': open_ticket_count,
        })
    active_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    return render_template('admin_subscribers_phase1a.html', rows=rows, stats=stats, plans=active_plans, ui_lang=_lang())


@admin_ops_bp.route('/admin/services-health')
def admin_services_health_v9():
    guard = _admin_guard('can_view_logs')
    if guard:
        return guard
    heartbeats = ServiceHeartbeat.query.order_by(ServiceHeartbeat.service_label.asc(), ServiceHeartbeat.service_key.asc()).all()
    hb_map = {row.service_key: row for row in heartbeats}
    latest_sync = SyncLog.query.order_by(SyncLog.created_at.desc()).first()
    latest_notif = NotificationLog.query.order_by(NotificationLog.created_at.desc()).first()
    scheduler_obj = getattr(current_app, 'scheduler', None)
    scheduler_jobs = []
    scheduler_visible = False
    scheduler_hb = hb_map.get('scheduler')
    scheduler_recent = False
    try:
        scheduler_visible = bool(scheduler_obj and scheduler_obj.running)
        scheduler_jobs = [{'id': j.id, 'label': service_display_name(j.id, _lang()), 'next_run_time': getattr(j, 'next_run_time', None)} for j in scheduler_obj.get_jobs()] if scheduler_obj else []
    except Exception:
        scheduler_visible = False
    try:
        scheduler_recent = bool(scheduler_hb and scheduler_hb.last_seen_at and (datetime.utcnow() - scheduler_hb.last_seen_at) <= timedelta(minutes=45) and scheduler_hb.status in ['ok', 'running'])
    except Exception:
        scheduler_recent = False
    scheduler_running = scheduler_visible or scheduler_recent
    service_cards = [
        {'key': 'scheduler', 'status': 'ok' if scheduler_running else ('warning' if current_app.config.get('DISABLE_INTERNAL_SCHEDULER') else 'failed'), 'heartbeat': scheduler_hb, 'details': scheduler_jobs},
        {'key': 'deye_auto_sync', 'heartbeat': hb_map.get('app.blueprints.main.sync_now_internal') or hb_map.get('deye_auto_sync')},
        {'key': 'advanced_notifications_check', 'heartbeat': hb_map.get('app.blueprints.notifications.run_advanced_notification_scheduler')},
        {'key': 'weather_change_check', 'heartbeat': hb_map.get('app.blueprints.notifications.run_weather_checks')},
        {'key': 'database_backup', 'heartbeat': hb_map.get('database_backup') or hb_map.get('app.services.backup_service.scheduled_backup_job')},
        {'key': 'database_backup_drive', 'heartbeat': hb_map.get('database_backup_drive')},
    ]
    heartbeat_rows = []
    for row in heartbeats:
        heartbeat_rows.append({
            'row': row,
            'label': service_display_name(row.service_key or row.service_label, _lang()),
            'message': service_message(row.message, _lang()),
            'source_label': service_source_label(row.source, _lang()),
        })
    return render_template(
        'admin_services_health.html',
        heartbeats=heartbeats,
        heartbeat_rows=heartbeat_rows,
        service_cards=service_cards,
        latest_sync=latest_sync,
        latest_notif=latest_notif,
        scheduler_jobs=scheduler_jobs,
        scheduler_running=scheduler_running,
        ui_lang=_lang(),
        service_display_name=service_display_name,
        service_message=service_message,
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )

@admin_ops_bp.route('/admin/devices')
def admin_devices_center_v9():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    q = AppDevice.query.order_by(AppDevice.updated_at.desc(), AppDevice.id.desc())
    device_type = (request.args.get('device_type') or '').strip()
    status = (request.args.get('status') or '').strip()
    if device_type:
        q = q.filter_by(device_type=device_type)
    if status:
        q = q.filter_by(connection_status=status)
    rows = []
    for dev in q.all():
        owner = AppUser.query.get(dev.owner_user_id) if dev.owner_user_id else None
        tenant = TenantAccount.query.get(dev.tenant_id) if dev.tenant_id else None
        rows.append({'device': dev, 'owner': owner, 'tenant': tenant})
    device_types = DeviceType.query.order_by(DeviceType.name.asc()).all()
    device_stats = {
        'total': len(rows),
        'connected': sum(1 for row in rows if (getattr(row['device'], 'connection_status', '') or '').lower() in ['ok', 'connected', 'ready']),
        'inactive': sum(1 for row in rows if not bool(getattr(row['device'], 'is_active', True))),
        'types': len(device_types),
    }
    # ── Insights for aside ─────────────────────────────────────────
    from datetime import datetime, timedelta
    now_utc = datetime.utcnow()
    type_counts = {}
    status_counts = {}
    fresh_count = 0   # last seen <= 1h
    recent_count = 0  # last seen 1-24h
    stale_count = 0   # 1-7 days
    very_stale_count = 0  # > 7 days
    never_count = 0   # never connected
    for row in rows:
        dev = row['device']
        t = (getattr(dev, 'device_type', None) or 'other').lower()
        type_counts[t] = type_counts.get(t, 0) + 1
        st = (getattr(dev, 'connection_status', None) or 'new').lower()
        status_counts[st] = status_counts.get(st, 0) + 1
        last = getattr(dev, 'last_connected_at', None)
        if not last:
            never_count += 1
            continue
        delta = now_utc - last
        if delta < timedelta(hours=1):
            fresh_count += 1
        elif delta < timedelta(hours=24):
            recent_count += 1
        elif delta < timedelta(days=7):
            stale_count += 1
        else:
            very_stale_count += 1
    type_mix = sorted(type_counts.items(), key=lambda x: -x[1])
    status_mix = sorted(status_counts.items(), key=lambda x: -x[1])
    health = {
        'fresh': fresh_count,
        'recent': recent_count,
        'stale': stale_count,
        'very_stale': very_stale_count,
        'never': never_count,
    }
    return render_template(
        'admin_devices_center.html',
        rows=rows, device_types=device_types, device_stats=device_stats,
        type_mix=type_mix, status_mix=status_mix, health=health,
        ui_lang=_lang(),
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )


@admin_ops_bp.route('/admin/design-qa')
def admin_design_qa():
    """Web-only Design QA audit center.

    Keeps this page focused on server-rendered web routes/templates. It does
    not grade machine-client endpoints or background systems.
    """
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    qa = build_web_design_qa(current_app)
    return render_template('admin_design_qa.html', ui_lang=_lang(), qa=qa)
