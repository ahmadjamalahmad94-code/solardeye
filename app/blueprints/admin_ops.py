from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import AppDevice, AppUser, DeviceType, NotificationLog, ServiceHeartbeat, SubscriptionPlan, SyncLog, TenantAccount, TenantSubscription
from ..services.backup_service import backup_settings
from ..services.i18n import translate
from ..services.labels import label
from ..services.scope import has_permission, is_system_admin
from ..services.service_monitor import service_display_name, service_message
from ..services.subscriptions import ensure_user_tenant_and_subscription
from ..services.utils import format_local_datetime

admin_ops_bp = Blueprint('admin_ops', __name__)


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _admin_guard(permission: str = 'can_manage_users'):
    if is_system_admin() or has_permission(permission):
        return None
    flash('This page is not available for your account.' if _lang() == 'en' else 'هذه الصفحة غير متاحة لحسابك.', 'warning')
    return redirect(url_for('main.admin_dashboard', lang=_lang()))


@admin_ops_bp.route('/admin/subscribers')
def admin_subscribers_v9():
    guard = _admin_guard('can_manage_users')
    if guard:
        return guard
    users = AppUser.query.filter_by(is_admin=False).order_by(AppUser.created_at.desc(), AppUser.id.desc()).all()
    plans = {p.id: p for p in SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()}
    stats = {'total': 0, 'active': 0, 'trial': 0, 'expired': 0, 'suspended': 0, 'disabled': 0}
    rows = []
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
        rows.append({
            'user': user,
            'tenant': tenant,
            'subscription': sub,
            'plan': plan,
            'status': status,
            'days_left': days_left,
            'device_count': AppDevice.query.filter_by(owner_user_id=user.id).count(),
        })
    return render_template('admin_subscribers_phase1a.html', rows=rows, stats=stats, ui_lang=_lang())


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
    return render_template('admin_devices_center.html', rows=rows, device_types=device_types, device_stats=device_stats, ui_lang=_lang(), format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']))

