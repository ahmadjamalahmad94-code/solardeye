"""Main routes blueprint — dashboard, statistics, reports, devices, etc."""
from __future__ import annotations
import csv
import io
import json
from urllib.parse import urlparse
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from werkzeug.security import generate_password_hash
from flask import Blueprint, Response, current_app, flash, g, has_request_context, jsonify, redirect, render_template, request, send_file, session, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from bidi.algorithm import get_display
import arabic_reshaper

from ..extensions import db
from ..models import AppDevice, AppUser, EventLog, NotificationLog, Reading, ServiceHeartbeat, Setting, SyncLog, UserLoad, SmartSnapshot, SubscriptionPlan, TenantAccount, TenantSubscription, DeviceType, InternalMailThread, InternalMailMessage, SupportTicket, SupportTicketMessage, TenantQuota, WalletLedger, AdminActivityLog, NotificationEvent, SupportCase, SupportAuditLog, CannedReply
from ..services.deye_client import DeyeClient
from ..services.scope import current_scope_ids, get_current_device, get_current_user, has_permission, is_system_admin, scoped_query, is_admin_scope
from ..services.utils import (
    format_local_datetime, human_duration_hours, safe_float,
    safe_power_w, to_json, utc_to_local,
)
from ..services.weather_service import fetch_weather
from ..services.subscriptions import ensure_user_tenant_and_subscription, current_subscription_for_user, user_has_active_subscription, activate_tenant_subscription, feature_enabled_for_user, plan_features
from ..services.security import preserve_secret_form_value, sanitize_response_payload
from ..services.backup_service import backup_settings, create_backup, list_backups, restore_backup, set_setting, save_uploaded_backup
from ..services.rbac import admin_landing_url
from ..services.support_ops import (
    audit_case, build_support_queue, case_url, notify_user, portal_case_url,
    sync_existing_cases, unread_counts, upsert_support_case, notification_items_for, support_queue_stats,
)
from ..services.platform_audit import audit_project
from ..services.energy_integrations import device_credentials, fetch_snapshot_for_device, missing_required, provider_by_code
from .helpers import (
    _to_12h_label, battery_percent_bar, build_battery_details, build_battery_insights,
    build_flow, build_period_chart, build_statistics_table, build_summary_chart,
    build_system_state, build_system_status, build_weather_insight, compute_energy_stats, filter_rows_for_view, format_energy,
    add_event_log, compute_actual_solar_surplus, format_power, format_time_short, get_recent_event_logs,
    get_runtime_battery_settings, get_production_summary, load_settings, log_event, maybe_log_energy_events,
    normalize_local_date, parse_selected_date, prune_old_logs, save_settings_from_form, shift_period,
)
from .notifications import (
    apply_form_settings_overrides, build_daily_morning_report_message,
    build_periodic_status_message, build_pre_sunset_message,
    dispatch_notification, load_notification_rules, log_notification,
    process_notifications, run_weather_checks, save_all_notification_settings_from_form, save_notification_settings_from_form,
    send_daily_weather_summary, send_periodic_status_update, send_pre_sunset_update,
    send_sms_message, send_telegram_message, send_telegram_menu, process_telegram_update, build_telegram_quick_reply,
)

main_bp = Blueprint('main', __name__)


def _is_admin_like_user(user) -> bool:
    role = (getattr(user, 'role', '') or '').strip().lower() if user else ''
    return bool(user and (getattr(user, 'is_admin', False) or role not in {'', 'user', 'subscriber', 'customer'}))


def _support_admin_label(admin):
    if not admin:
        return 'الموظف المسؤول'
    return (getattr(admin, 'full_name', None) or getattr(admin, 'username', None) or 'الموظف المسؤول').strip()


def _support_already_has_assignment_notice(messages):
    for msg in messages or []:
        if getattr(msg, 'sender_scope', '') == 'admin' and not getattr(msg, 'is_internal_note', False) and 'تم استلام' in (getattr(msg, 'body', '') or ''):
            return True
    return False


def _support_has_assignment_notice_for(messages, admin):
    label = _support_admin_label(admin) if admin else ''
    for msg in messages or []:
        body = getattr(msg, 'body', '') or ''
        if (getattr(msg, 'sender_scope', '') == 'admin' and not getattr(msg, 'is_internal_note', False)
                and 'تم استلام' in body and (not label or label in body)):
            return True
    return False


def _assignment_notice_body(kind, admin):
    name = _support_admin_label(admin)
    if kind == 'ticket':
        return f'تم استلام تذكرتك وتحويلها إلى المدير المسؤول {name}. سيتابعها معك حتى حل المشكلة بإذن الله.'
    return f'تم استلام رسالتك وتحويلها إلى المدير المسؤول {name}. سيتابعها معك قريبًا بإذن الله.'


def _latest_reading():
    return scoped_query(Reading).order_by(Reading.created_at.desc()).first()


def _active_device():
    return get_current_device()


def _active_user():
    return get_current_user()


def _require_subscription_guard():
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if is_system_admin():
        return None
    ensure_user_tenant_and_subscription(user, activated_by_user_id=user.id)
    if not user_has_active_subscription(user):
        flash('اشتراكك منتهي أو غير مفعل. راجع صفحة الاشتراك.', 'warning')
        return redirect(url_for('main.account_subscription', lang=_lang()))
    return None


def _plan_feature_enabled(feature_key: str) -> bool:
    user = _active_user()
    if user is None:
        return False
    if is_system_admin():
        return True
    return feature_enabled_for_user(user, feature_key)



def _admin_guard(permission: str = 'can_manage_users'):
    if is_system_admin():
        return None
    if has_permission(permission):
        return None
    flash('This page is not available for your role.' if _lang() == 'en' else 'هذه الصفحة غير متاحة ضمن صلاحيات دورك.', 'warning')
    return redirect(admin_landing_url(_lang()))






def _safe_admin_redirect(default_endpoint: str = 'main.admin_subscribers'):
    """Redirect back to the same admin screen after a POST, falling back safely."""
    target = (request.form.get('next') or request.args.get('next') or request.referrer or '').strip()
    if target:
        parsed = urlparse(target)
        if not parsed.netloc or parsed.netloc == request.host:
            return redirect(target)
    return redirect(url_for(default_endpoint, lang=_lang()))

def _redirect_by_role(user=None):
    user = user or _active_user()
    if _is_admin_like_user(user):
        return redirect(admin_landing_url(_lang()))
    return redirect(url_for('main.dashboard', lang=_lang()))


def _energy_portal_guard():
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))
    if _is_admin_like_user(user):
        flash('Admin console is separate from the subscriber energy portal.' if _lang() == 'en' else 'لوحة الإدارة منفصلة عن بوابة الطاقة.', 'info')
        return redirect(admin_landing_url(_lang()))
    return None

def _role_badge(role: str, is_active: bool):
    role = (role or 'user').strip().lower()
    if not is_active:
        return ('غير مفعل', 'danger')
    return ('مدير' if role == 'admin' else 'مستخدم', 'success' if role == 'admin' else 'warning')


def _available_devices_for_admin(user: AppUser | None = None):
    query = AppDevice.query.order_by(AppDevice.name.asc(), AppDevice.id.asc())
    if user is None:
        return query.all()
    return query.filter((AppDevice.owner_user_id.is_(None)) | (AppDevice.owner_user_id == user.id)).all()


def _assign_devices_to_user(user: AppUser, device_ids: list[int], preferred_device_id: int | None):
    selected_ids = set(device_ids)
    devices = AppDevice.query.order_by(AppDevice.id.asc()).all()
    # only allow assigning currently unowned devices or devices already owned by this user
    selectable = {dev.id for dev in devices if dev.owner_user_id in (None, user.id)}
    selected_ids &= selectable

    for dev in devices:
        if dev.id in selected_ids and dev.owner_user_id in (None, user.id):
            dev.owner_user_id = user.id
    for dev in devices:
        if dev.owner_user_id == user.id and dev.id not in selected_ids:
            dev.owner_user_id = None
    user_device_ids = sorted(dev.id for dev in devices if dev.owner_user_id == user.id)
    if preferred_device_id and preferred_device_id in user_device_ids:
        user.preferred_device_id = preferred_device_id
    elif user_device_ids:
        user.preferred_device_id = user_device_ids[0]
    else:
        user.preferred_device_id = None


def _device_collection():
    user = _active_user()
    if user is None:
        return AppDevice.query.filter_by(is_active=True).order_by(AppDevice.id.asc()).all()
    return AppDevice.query.filter_by(owner_user_id=user.id, is_active=True).order_by(AppDevice.name.asc(), AppDevice.id.asc()).all()




def _admin_write_log(action: str, summary: str, target_type: str | None = None, target_id: int | None = None, details: dict | None = None):
    """Write an admin activity row without allowing logging to break the user flow."""
    actor = _active_user()
    row = AdminActivityLog(
        actor_user_id=getattr(actor, 'id', None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        details_json=json.dumps(details or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('admin activity log failed: %s', exc)




def _hard_delete_user_account(user: AppUser, actor_id: int | None = None) -> dict:
    """Delete a subscriber and owned operational data.

    This is intentionally explicit instead of relying on DB cascades because the
    project has grown through additive migrations and some foreign keys are
    nullable. Admin/self deletion is blocked by the caller.
    """
    tenant_ids = []
    if getattr(user, 'tenant_id', None):
        tenant_ids.append(user.tenant_id)
    tenant_ids.extend([t.id for t in TenantAccount.query.filter_by(owner_user_id=user.id).all()])
    tenant_ids = sorted(set([tid for tid in tenant_ids if tid]))
    device_ids = [d.id for d in AppDevice.query.filter_by(owner_user_id=user.id).all()]

    # Support conversations and tickets owned by this user / tenant.
    mail_threads = InternalMailThread.query.filter(
        db.or_(InternalMailThread.created_by_user_id == user.id, InternalMailThread.tenant_id.in_(tenant_ids) if tenant_ids else False)
    ).all()
    thread_ids = [r.id for r in mail_threads]
    if thread_ids:
        InternalMailMessage.query.filter(InternalMailMessage.thread_id.in_(thread_ids)).delete(synchronize_session=False)
        SupportCase.query.filter(SupportCase.case_type == 'message', SupportCase.source_id.in_(thread_ids)).delete(synchronize_session=False)
        SupportAuditLog.query.filter(SupportAuditLog.case_type == 'message', SupportAuditLog.source_id.in_(thread_ids)).delete(synchronize_session=False)
        InternalMailThread.query.filter(InternalMailThread.id.in_(thread_ids)).delete(synchronize_session=False)

    tickets = SupportTicket.query.filter(
        db.or_(SupportTicket.opened_by_user_id == user.id, SupportTicket.tenant_id.in_(tenant_ids) if tenant_ids else False)
    ).all()
    ticket_ids = [r.id for r in tickets]
    if ticket_ids:
        SupportTicketMessage.query.filter(SupportTicketMessage.ticket_id.in_(ticket_ids)).delete(synchronize_session=False)
        SupportCase.query.filter(SupportCase.case_type == 'ticket', SupportCase.source_id.in_(ticket_ids)).delete(synchronize_session=False)
        SupportAuditLog.query.filter(SupportAuditLog.case_type == 'ticket', SupportAuditLog.source_id.in_(ticket_ids)).delete(synchronize_session=False)
        SupportTicket.query.filter(SupportTicket.id.in_(ticket_ids)).delete(synchronize_session=False)

    NotificationEvent.query.filter(db.or_(NotificationEvent.target_user_id == user.id, NotificationEvent.tenant_id.in_(tenant_ids) if tenant_ids else False)).delete(synchronize_session=False)

    if tenant_ids:
        WalletLedger.query.filter(WalletLedger.tenant_id.in_(tenant_ids)).delete(synchronize_session=False)
        TenantQuota.query.filter(TenantQuota.tenant_id.in_(tenant_ids)).delete(synchronize_session=False)
        TenantSubscription.query.filter(TenantSubscription.tenant_id.in_(tenant_ids)).delete(synchronize_session=False)

    # Device-linked operational data.
    if device_ids:
        Reading.query.filter(db.or_(Reading.user_id == user.id, Reading.device_id.in_(device_ids))).delete(synchronize_session=False)
        SyncLog.query.filter(db.or_(SyncLog.user_id == user.id, SyncLog.device_id.in_(device_ids))).delete(synchronize_session=False)
        NotificationLog.query.filter(db.or_(NotificationLog.user_id == user.id, NotificationLog.device_id.in_(device_ids))).delete(synchronize_session=False)
        EventLog.query.filter(db.or_(EventLog.user_id == user.id, EventLog.device_id.in_(device_ids))).delete(synchronize_session=False)
        SmartSnapshot.query.filter(db.or_(SmartSnapshot.user_id == user.id, SmartSnapshot.device_id.in_(device_ids))).delete(synchronize_session=False)
        UserLoad.query.filter(db.or_(UserLoad.user_id == user.id, UserLoad.device_id.in_(device_ids))).delete(synchronize_session=False)
        AppDevice.query.filter(AppDevice.id.in_(device_ids)).delete(synchronize_session=False)
    else:
        Reading.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        SyncLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        NotificationLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        EventLog.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        SmartSnapshot.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        UserLoad.query.filter_by(user_id=user.id).delete(synchronize_session=False)

    # Logs are kept but detached from the deleted user to preserve audit history.
    WalletLedger.query.filter_by(actor_user_id=user.id).update({'actor_user_id': None}, synchronize_session=False)
    AdminActivityLog.query.filter_by(actor_user_id=user.id).update({'actor_user_id': None}, synchronize_session=False)
    AdminActivityLog.query.filter_by(target_type='app_user', target_id=user.id).update({'target_id': None}, synchronize_session=False)
    SupportAuditLog.query.filter_by(actor_user_id=user.id).update({'actor_user_id': None}, synchronize_session=False)

    if tenant_ids:
        TenantAccount.query.filter(TenantAccount.id.in_(tenant_ids)).delete(synchronize_session=False)

    username = user.username
    db.session.delete(user)
    return {'username': username, 'tenant_ids': tenant_ids, 'device_ids': device_ids, 'thread_ids': thread_ids, 'ticket_ids': ticket_ids}


def _admin_counts_snapshot():
    users = AppUser.query.filter_by(is_admin=False).count()
    active_users = AppUser.query.filter_by(is_admin=False, is_active=True).count()
    trials = TenantSubscription.query.filter_by(status='trial').count()
    expiring = TenantSubscription.query.filter(TenantSubscription.ends_at.isnot(None)).count()
    open_threads = InternalMailThread.query.filter(InternalMailThread.status.in_(['open','pending'])).count()
    finance_rows = WalletLedger.query.count()
    return {
        'users': users, 'active_users': active_users, 'trials': trials, 'expiring': expiring,
        'open_threads': open_threads, 'finance_rows': finance_rows,
    }

def _service_health_snapshot(settings):
    from datetime import timedelta
    from ..services.utils import utc_to_local
    from ..services.scope import get_current_device

    now = datetime.now(UTC).replace(tzinfo=None)
    device = get_current_device()
    latest_reading = _latest_reading()
    latest_sync = scoped_query(SyncLog).order_by(SyncLog.created_at.desc()).first()
    latest_notification = scoped_query(NotificationLog).order_by(NotificationLog.created_at.desc()).first()
    recent_error = scoped_query(SyncLog).filter(SyncLog.level.in_(['danger', 'warning'])).order_by(SyncLog.created_at.desc()).first()
    jobs = ServiceHeartbeat.query.order_by(ServiceHeartbeat.service_label.asc()).all()
    sync_minutes = max(int(current_app.config.get('AUTO_SYNC_MINUTES', 5) or 5), 1)
    stale_after = timedelta(minutes=sync_minutes * 3)

    scheduler_status = 'ok' if jobs else 'warning'
    scheduler_message = 'Scheduler يعمل وتصلنا نبضات للخدمات الخلفية.' if jobs else 'لا توجد نبضات مسجلة بعد من الخدمات الخلفية.'

    auto_sync_status = 'ok'
    auto_sync_message = 'المزامنة التلقائية تبدو سليمة.'
    if latest_reading is None:
        auto_sync_status = 'warning'
        auto_sync_message = 'لا توجد قراءة حديثة ضمن نطاق الجهاز الحالي.'
    elif (now - latest_reading.created_at) > stale_after:
        auto_sync_status = 'failed'
        auto_sync_message = 'آخر قراءة قديمة نسبيًا مقارنة بجدول المزامنة.'

    notification_status = 'ok' if str(settings.get('notifications_enabled', 'true')).lower() == 'true' else 'warning'
    notification_message = 'الإشعارات مفعلة.' if notification_status == 'ok' else 'الإشعارات العامة معطلة حاليًا.'

    if recent_error and (now - recent_error.created_at) <= timedelta(hours=12):
        notification_message += f' آخر تحذير/خطأ: {recent_error.message}'

    return {
        'device_name': getattr(device, 'name', 'غير محدد'),
        'scheduler_status': scheduler_status,
        'scheduler_message': scheduler_message,
        'auto_sync_status': auto_sync_status,
        'auto_sync_message': auto_sync_message,
        'notification_status': notification_status,
        'notification_message': notification_message,
        'latest_reading': latest_reading,
        'latest_sync': latest_sync,
        'latest_notification': latest_notification,
        'recent_error': recent_error,
        'jobs': jobs,
    }

# ── Shared helpers ────────────────────────────────────────────────────────────

def extract_station_coords(latest):
    if not latest or not latest.raw_json:
        return None, None
    try:
        raw = json.loads(latest.raw_json)
        station = raw.get('station_summary') or {}
        lat = safe_float(station.get('locationLat'), None)
        lng = safe_float(station.get('locationLng'), None)
        if lat is None or lng is None:
            return None, None
        return lat, lng
    except Exception:
        return None, None


def get_weather_for_latest(latest):
    lat, lng = extract_station_coords(latest)
    if lat is None or lng is None:
        return None
    try:
        return fetch_weather(lat, lng, current_app.config['LOCAL_TIMEZONE'])
    except Exception:
        return None


from .helpers import build_pre_sunset_prediction  # noqa: F811
from .smart_engine import get_latest_historical_overview, save_smart_snapshot_from_reading


def _lang():
    raw = (request.args.get('lang') or request.form.get('lang') or session.get('ui_lang') or getattr(g, 'ui_lang', None) or 'ar')
    lang = 'en' if str(raw).strip().lower().startswith('en') else 'ar'
    session['ui_lang'] = lang
    g.ui_lang = lang
    return lang


def _serialize_loads():
    rows = scoped_query(UserLoad).order_by(UserLoad.priority.asc(), UserLoad.power_w.asc(), UserLoad.name.asc()).all()
    return rows


def _parse_hhmm_local(value, now_local):
    try:
        hh, mm = [int(x) for x in str(value or '').split(':')[:2]]
        return now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None


def _get_setting_value(key: str, default: str = '') -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value is not None else default


def _save_setting_value(key: str, value: str):
    row = Setting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))


def _load_suggestion_mode(now_local, weather=None):
    sunset_dt = _parse_hhmm_local(getattr(weather, 'sunset_time', None), now_local) if weather else None
    day_start = now_local.replace(hour=9, minute=0, second=0, microsecond=0)
    if sunset_dt and day_start <= now_local < sunset_dt:
        return 'day', sunset_dt
    return 'night', sunset_dt


def _manual_load_planner(latest, max_allowed_w=0, weather=None, now_local=None):
    loads = [r for r in _serialize_loads() if r.is_enabled]
    now_local = now_local or utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    mode, sunset_dt = _load_suggestion_mode(now_local, weather)
    current_load = float(latest.home_load or 0) if latest else 0.0
    surplus_data = compute_actual_solar_surplus(latest, weather=weather)
    raw_surplus = float(surplus_data.get('raw_surplus_w', 0) or 0)
    actual_surplus = float(surplus_data.get('actual_surplus_w', 0) or 0)
    battery_need = float(surplus_data.get('battery_charge_need_w', 0) or 0)
    target_cap = max(float(max_allowed_w or 0), 0.0)

    if mode == 'day':
        available = actual_surplus
        reason_ar = 'في النهار نعتمد الفائض الشمسي الفعلي بعد خصم احتياج شحن البطارية قبل الغروب.'
        reason_en = 'During the day we use the actual solar surplus after deducting the battery charging need before sunset.'
    else:
        available = max(target_cap - current_load, 0.0)
        reason_ar = 'في الليل نعتمد الحد الليلي المحفوظ مطروحًا منه سحب المنزل الحالي.'
        reason_en = 'At night we use the saved night limit minus the current home load.'

    fit, blocked = [], []
    for load in loads:
        item = {'id': load.id, 'name': load.name, 'power_w': float(load.power_w or 0), 'priority': int(load.priority or 1)}
        (fit if item['power_w'] <= available + 1e-9 else blocked).append(item)

    mode_ar = 'وضع النهار' if mode == 'day' else 'وضع الليل'
    mode_en = 'Day mode' if mode == 'day' else 'Night mode'
    return {
        'mode': mode,
        'mode_ar': mode_ar,
        'mode_en': mode_en,
        'current_load_w': round(current_load, 1),
        'surplus_w': round(raw_surplus, 1),
        'actual_surplus_w': round(actual_surplus, 1),
        'battery_charge_need_w': round(battery_need, 1),
        'max_allowed_w': round(target_cap, 1),
        'available_w': round(available, 1),
        'fit': fit,
        'blocked': blocked,
        'reason_ar': reason_ar,
        'reason_en': reason_en,
        'sunset_label': sunset_dt.strftime('%H:%M') if sunset_dt else '',
    }


def _smart_load_suggestions(latest, settings=None):
    settings = settings or load_settings()
    night_max_w = safe_float(settings.get('night_max_load_w'), 500)
    loads = [r for r in _serialize_loads() if r.is_enabled]
    if not latest:
        return {
            'available_w': 0.0, 'safe_available_w': 0.0, 'actual_surplus_w': 0.0, 'raw_surplus_w': 0.0,
            'battery_charge_need_w': 0.0, 'battery_soc': 0.0, 'can_run': [], 'hold': [],
            'headline_ar': 'بانتظار أول قراءة للنظام', 'headline_en': 'Waiting for the first system reading',
            'mode_ar': 'لا توجد بيانات', 'mode_en': 'No data yet', 'phase': 'night', 'night_max_w': night_max_w,
            'surplus_note_ar': 'سيتم الحساب بعد وصول أول قراءة.', 'surplus_note_en': 'The calculation will appear after the first reading.',
        }
    weather = get_weather_for_latest(latest)
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    phase, _ = _load_suggestion_mode(now_local, weather)
    battery_soc = float(latest.battery_soc or 0)
    surplus_data = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
    raw_surplus = float(surplus_data.get('raw_surplus_w', 0) or 0)
    actual_surplus = float(surplus_data.get('actual_surplus_w', 0) or 0)
    battery_need = float(surplus_data.get('battery_charge_need_w', 0) or 0)

    if phase == 'day':
        safe_available = actual_surplus
        mode_ar = 'يعتمد الاقتراح الآن على الفائض الشمسي الفعلي'
        mode_en = 'Suggestions now use the actual solar surplus'
        surplus_note_ar = f'خام: {int(round(raw_surplus))} واط • للبطارية: {int(round(battery_need))} واط • فعلي: {int(round(actual_surplus))} واط'
        surplus_note_en = f'Raw: {int(round(raw_surplus))}W • Battery: {int(round(battery_need))}W • Actual: {int(round(actual_surplus))}W'
    else:
        safe_available = max(night_max_w - float(latest.home_load or 0), 0.0)
        mode_ar = f'ليلًا: الحد المعتمد {int(round(night_max_w))} واط'
        mode_en = f'Night: saved limit {int(round(night_max_w))} W'
        surplus_note_ar = 'بعد الغروب نتوقف عن احتساب الفائض الفعلي ونعتمد الحد الليلي.'
        surplus_note_en = 'After sunset we stop using actual surplus and rely on the night limit.'

    can_run = []
    hold = []
    for load in loads:
        item = {'id': load.id, 'name': load.name, 'power_w': float(load.power_w or 0), 'priority': int(load.priority or 1)}
        if item['power_w'] <= safe_available + 1e-9:
            can_run.append(item)
        else:
            hold.append(item)

    if can_run:
        names_ar = '، '.join(x['name'] for x in can_run[:3])
        names_en = ', '.join(x['name'] for x in can_run[:3])
        headline_ar = f'يمكنك الآن تشغيل: {names_ar}'
        headline_en = f'You can run now: {names_en}'
    elif safe_available > 0:
        headline_ar = 'الفائض الفعلي الحالي لا يكفي لتشغيل حمل جديد بأمان'
        headline_en = 'The current actual surplus is not enough for a new load safely'
    else:
        headline_ar = 'يفضل تأجيل تشغيل الأحمال الإضافية الآن'
        headline_en = 'It is better to postpone extra loads for now'

    return {
        'available_w': round(raw_surplus, 1),
        'safe_available_w': round(safe_available, 1),
        'actual_surplus_w': round(actual_surplus, 1),
        'raw_surplus_w': round(raw_surplus, 1),
        'battery_charge_need_w': round(battery_need, 1),
        'battery_soc': round(battery_soc, 1),
        'can_run': can_run,
        'hold': hold,
        'headline_ar': headline_ar,
        'headline_en': headline_en,
        'mode_ar': mode_ar,
        'mode_en': mode_en,
        'phase': phase,
        'night_max_w': round(night_max_w, 1),
        'surplus_note_ar': surplus_note_ar,
        'surplus_note_en': surplus_note_en,
        'surplus_details_ar': surplus_data.get('details_ar', ''),
        'surplus_details_en': surplus_data.get('details_en', ''),
    }


# ── Routes ────────────────────────────────────────────────────────────────────









def _get_stats_context(request_args, tz_name):
    """Shared logic for statistics and reports."""
    selected_view = request_args.get('view', 'day').strip().lower()
    if selected_view not in {'day', 'week', 'month'}:
        selected_view = 'day'
    selected_date = parse_selected_date(request_args.get('date'), tz_name)

    # Limit query by date range for performance
    cfg = current_app.config
    max_rows = cfg.get('MAX_READINGS_QUERY', 2000)
    if selected_view == 'day':
        start = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif selected_view == 'week':
        days_since_sat = (selected_date.weekday() - 5) % 7
        start = (selected_date - timedelta(days=days_since_sat)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
    else:
        start = selected_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)

    # Convert local dates to UTC for query
    start_utc = start.replace(tzinfo=None) if start.tzinfo else start
    end_utc = end.replace(tzinfo=None) if end.tzinfo else end

    ordered = (scoped_query(Reading)
               .filter(Reading.created_at >= start_utc, Reading.created_at < end_utc)
               .order_by(Reading.created_at.asc())
               .limit(max_rows)
               .all())

    filtered_rows, title_hint = filter_rows_for_view(ordered, selected_view, selected_date, tz_name)
    prev_date = shift_period(selected_view, selected_date, -1)
    next_date = shift_period(selected_view, selected_date, 1)
    now_local = utc_to_local(datetime.now(UTC), tz_name)
    can_go_next = normalize_local_date(next_date, tz_name) <= normalize_local_date(now_local, tz_name)
    return selected_view, selected_date, filtered_rows, title_hint, prev_date, next_date, can_go_next














def sync_now_internal(trigger='manual'):
    device = get_current_device()
    current_user = get_current_user()
    ready, ready_message = _device_sync_ready(device, user=current_user)
    if not ready:
        raise ValueError(ready_message)
    previous = _latest_reading()
    provider_code = (getattr(device, 'api_provider', None) or getattr(device, 'device_type', None) or 'deye').strip().lower() if device else 'deye'

    if provider_code and provider_code != 'deye':
        snap = fetch_snapshot_for_device(device)
        user_id, device_id = current_scope_ids()
        reading = Reading(
            user_id=user_id,
            device_id=device_id,
            plant_id=getattr(device, 'station_id', None) or getattr(device, 'external_device_id', None) or str(getattr(device, 'id', '')),
            plant_name=getattr(device, 'plant_name', None) or getattr(device, 'name', '') or provider_code,
            solar_power=float(snap.get('solar_power') or 0),
            home_load=float(snap.get('home_load') or 0),
            battery_soc=float(snap.get('battery_soc') or 0),
            battery_power=float(snap.get('battery_power') or 0),
            grid_power=float(snap.get('grid_power') or 0),
            inverter_power=float(snap.get('inverter_power') or snap.get('solar_power') or 0),
            daily_production=float(snap.get('daily_production') or 0),
            monthly_production=float(snap.get('monthly_production') or 0),
            total_production=float(snap.get('total_production') or 0),
            status_text=str(snap.get('status_text') or provider_code),
            raw_json=to_json({'provider': provider_code, 'snapshot': snap}),
        )
        db.session.add(reading)
        if device:
            device.connection_status = 'ok'
            device.last_connected_at = datetime.utcnow()
        db.session.commit()
    else:
        allow_global_connection = bool(current_user and (getattr(current_user, 'is_admin', False) or getattr(current_user, 'role', '') == 'admin') and not has_request_context())
        client = DeyeClient(_device_runtime_settings(device, allow_global_connection=allow_global_connection))
        snapshot = client.snapshot()
        # Extract device_detail metrics for direct columns
        # Pull all fields directly from device_data (flat dict from device/latest)
        _d = snapshot.raw.get('device_data') or {}

        def _fv(key, default=None):
            v = _d.get(key)
            if v is None: return default
            try: return float(v)
            except: return default

        user_id, device_id = current_scope_ids()
        reading = Reading(
            user_id=user_id, device_id=device_id,
            plant_id=snapshot.plant_id, plant_name=snapshot.plant_name,
            solar_power=snapshot.solar_power, home_load=snapshot.home_load,
            battery_soc=snapshot.battery_soc, battery_power=snapshot.battery_power,
            grid_power=snapshot.grid_power, inverter_power=snapshot.inverter_power,
            daily_production=snapshot.daily_production,
            monthly_production=snapshot.monthly_production,
            total_production=snapshot.total_production,
            status_text=snapshot.status_text,
            # PV strings — from device/latest directly
            pv1_power=_fv('dcPowerPv1'),
            pv2_power=_fv('dcPowerPv2'),
            pv3_power=_fv('dcPowerPv3'),
            pv4_power=None,
            # Temperatures
            inverter_temp=_fv('acTemperature'),
            dc_temp=None,  # dcTemperature has firmware bug, skip
            # Grid/AC
            grid_voltage=_fv('acVoltageRua') or _fv('loadVoltageL1l2'),
            grid_frequency=_fv('acOutputFrequencyR'),
            raw_json=to_json(snapshot.raw),
        )
        db.session.add(reading)
        if device:
            device.connection_status = 'ok'
            device.last_connected_at = datetime.utcnow()
        db.session.commit()

    weather = get_weather_for_latest(reading)
    try:
        maybe_log_energy_events(reading, previous, weather=weather, settings=load_settings())
    except Exception as event_exc:
        log_event('warning', f'تعذر تسجيل الأحداث الذكية: {event_exc}')
    try:
        process_notifications(reading, previous)
    except Exception as notify_exc:
        log_event('warning', f'تعذر تنفيذ الإشعارات: {notify_exc}')
    if trigger == 'manual':
        log_event('success', 'تمت مزامنة قراءة جديدة بنجاح', {'provider': provider_code, 'reading_id': reading.id})
    else:
        log_event('info', 'مزامنة تلقائية', {'provider': provider_code, 'created_at': reading.created_at.isoformat()})
    # Prune old logs periodically (on every auto-sync)
    if trigger == 'auto':
        try:
            prune_old_logs()
        except Exception:
            pass
    return reading












def _wallet_balance_for_tenant(tenant_id: int | None) -> float:
    if not tenant_id:
        return 0.0
    total = 0.0
    for entry in WalletLedger.query.filter_by(tenant_id=tenant_id).all():
        total += entry.amount if entry.entry_type == 'credit' else -entry.amount
    return round(total, 2)


def _parse_dt_local(value: str | None):
    raw = (value or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def _admin_user_payload(user: AppUser):
    tenant, subscription = ensure_user_tenant_and_subscription(user, activated_by_user_id=getattr(_active_user(), 'id', None))
    devices = AppDevice.query.filter_by(owner_user_id=user.id).order_by(AppDevice.updated_at.desc(), AppDevice.id.desc()).all()
    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    tenant_id = getattr(tenant, 'id', None)
    # Defensive ownership: older support rows may have tenant_id but missing created_by/opened_by, or the opposite.
    all_threads = InternalMailThread.query.order_by(InternalMailThread.updated_at.desc(), InternalMailThread.id.desc()).all()
    tenant_threads = [t for t in all_threads if (tenant_id and t.tenant_id == tenant_id) or t.created_by_user_id == user.id]
    seen_thread_ids = set()
    thread_rows = []
    for thread in tenant_threads:
        if thread.id in seen_thread_ids:
            continue
        seen_thread_ids.add(thread.id)
        thread_rows.append({
            'thread': thread,
            'messages': InternalMailMessage.query.filter_by(thread_id=thread.id).order_by(InternalMailMessage.created_at.asc(), InternalMailMessage.id.asc()).all(),
            'assignee': AppUser.query.get(thread.assigned_admin_user_id) if thread.assigned_admin_user_id else None,
        })
    all_tickets = SupportTicket.query.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).all()
    tenant_tickets = [t for t in all_tickets if (tenant_id and t.tenant_id == tenant_id) or t.opened_by_user_id == user.id]
    seen_ticket_ids = set()
    ticket_rows = []
    for ticket in tenant_tickets:
        if ticket.id in seen_ticket_ids:
            continue
        seen_ticket_ids.add(ticket.id)
        ticket_rows.append({
            'ticket': ticket,
            'messages': SupportTicketMessage.query.filter_by(ticket_id=ticket.id).order_by(SupportTicketMessage.created_at.asc(), SupportTicketMessage.id.asc()).all(),
            'assignee': AppUser.query.get(ticket.assigned_admin_user_id) if ticket.assigned_admin_user_id else None,
            'device': AppDevice.query.get(ticket.related_device_id) if ticket.related_device_id else None,
        })
    finance_rows = WalletLedger.query.filter_by(tenant_id=getattr(tenant, 'id', None)).order_by(WalletLedger.created_at.desc(), WalletLedger.id.desc()).all()
    quota_rows = TenantQuota.query.filter_by(tenant_id=getattr(tenant, 'id', None)).order_by(TenantQuota.updated_at.desc(), TenantQuota.id.desc()).all()
    activity_rows = AdminActivityLog.query.order_by(
        AdminActivityLog.created_at.desc(),
        AdminActivityLog.id.desc(),
    ).limit(150).all()
    related_activities = []
    for item in activity_rows:
        details = {}
        try:
            details = json.loads(item.details_json or '{}') if item.details_json else {}
        except Exception:
            details = {}
        if details.get('tenant_id') == getattr(tenant, 'id', None) or details.get('user_id') == user.id or item.target_id == user.id:
            related_activities.append({'item': item, 'actor': AppUser.query.get(item.actor_user_id) if item.actor_user_id else None})
    feature_map = plan_features(SubscriptionPlan.query.get(tenant.plan_id) if tenant and tenant.plan_id else None)
    return {
        'tenant': tenant,
        'subscription': subscription,
        'devices': devices,
        'plans': plans,
        'thread_rows': thread_rows,
        'ticket_rows': ticket_rows,
        'finance_rows': finance_rows,
        'quota_rows': quota_rows,
        'activity_rows': related_activities[:40],
        'wallet_balance': _wallet_balance_for_tenant(getattr(tenant, 'id', None)),
        'feature_map': feature_map,
    }




















def _safe_json_loads(raw_value):
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


_DEVICE_CONNECTION_KEYS = {
    'deye_app_id', 'deye_app_secret', 'deye_email', 'deye_password', 'deye_password_hash',
    'deye_region', 'deye_plant_id', 'deye_device_sn', 'deye_logger_sn', 'deye_plant_name',
    'deye_battery_sn_main', 'deye_battery_sn_module',
}


def _device_runtime_settings(device: AppDevice | None = None, allow_global_connection: bool = False):
    settings = load_settings().copy()
    if not allow_global_connection:
        for key in _DEVICE_CONNECTION_KEYS:
            settings[key] = ''
    if device is None:
        return settings

    creds = _safe_json_loads(getattr(device, 'credentials_json', None))
    device_settings = _safe_json_loads(getattr(device, 'settings_json', None))

    mapping = {
        'deye_app_id': creds.get('deye_app_id') or creds.get('app_id') or '',
        'deye_app_secret': creds.get('deye_app_secret') or creds.get('app_secret') or '',
        'deye_email': creds.get('deye_email') or creds.get('email') or '',
        'deye_password': creds.get('deye_password') or creds.get('password') or '',
        'deye_password_hash': creds.get('deye_password_hash') or creds.get('password_hash') or '',
        'deye_region': device_settings.get('deye_region') or device_settings.get('region') or '',
        'deye_plant_id': device_settings.get('deye_plant_id') or device_settings.get('plant_id') or getattr(device, 'station_id', '') or '',
        'deye_device_sn': device_settings.get('deye_device_sn') or device_settings.get('device_sn') or getattr(device, 'device_uid', '') or '',
        'deye_logger_sn': device_settings.get('deye_logger_sn') or device_settings.get('logger_sn') or '',
        'deye_plant_name': device_settings.get('deye_plant_name') or device_settings.get('plant_name') or getattr(device, 'plant_name', '') or getattr(device, 'name', '') or '',
        'deye_battery_sn_main': device_settings.get('deye_battery_sn_main') or device_settings.get('battery_sn_main') or '',
        'deye_battery_sn_module': device_settings.get('deye_battery_sn_module') or device_settings.get('battery_sn_module') or '',
    }
    for key, value in mapping.items():
        if value not in (None, ''):
            settings[key] = value

    for key in ('battery_capacity_kwh', 'battery_reserve_percent'):
        value = device_settings.get(key)
        if value not in (None, ''):
            settings[key] = value

    if getattr(device, 'api_base_url', None):
        settings['api_base_url'] = device.api_base_url
    return settings


def _device_sync_ready(device: AppDevice | None = None, user=None):
    user = user or _active_user() or get_current_user()
    device = device or get_current_device()
    if device is None:
        return False, 'لا يوجد جهاز مربوط حاليًا بهذا الحساب.'
    if not bool(getattr(device, 'is_active', False)):
        return False, 'الجهاز الحالي غير مفعل.'

    provider_code = (getattr(device, 'api_provider', None) or getattr(device, 'device_type', None) or 'deye').strip().lower()
    if provider_code and provider_code != 'deye':
        spec = provider_by_code(provider_code)
        if not spec:
            return False, f'نوع التكامل غير مدعوم حاليًا: {provider_code}'
        missing = missing_required(spec, device_credentials(device))
        if missing:
            return False, 'أكمل إعدادات التكامل أولًا: ' + '، '.join(missing)
        return True, ''

    allow_global_connection = bool(user and (getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'admin') and not has_request_context())
    settings = _device_runtime_settings(device, allow_global_connection=allow_global_connection)

    required = {
        'deye_app_id': 'App ID',
        'deye_app_secret': 'App Secret',
        'deye_email': 'بريد Deye',
        'deye_plant_id': 'Plant ID',
    }
    missing = [label for key, label in required.items() if not str(settings.get(key, '') or '').strip()]
    if not (str(settings.get('deye_password', '') or '').strip() or str(settings.get('deye_password_hash', '') or '').strip()):
        missing.append('كلمة مرور Deye أو SHA-256')
    if missing:
        return False, 'أكمل إعدادات الجهاز الحالي أولًا: ' + '، '.join(missing)
    return True, ''


def _save_deye_settings_to_device(device: AppDevice, form_data=None):
    form_data = form_data or request.form
    creds = _safe_json_loads(getattr(device, 'credentials_json', None))
    device_settings = _safe_json_loads(getattr(device, 'settings_json', None))

    creds.update({
        'deye_app_id': preserve_secret_form_value(form_data, 'deye_app_id', creds.get('deye_app_id') or creds.get('app_id') or ''),
        'deye_app_secret': preserve_secret_form_value(form_data, 'deye_app_secret', creds.get('deye_app_secret') or creds.get('app_secret') or ''),
        'deye_email': preserve_secret_form_value(form_data, 'deye_email', creds.get('deye_email') or creds.get('email') or ''),
        'deye_password': preserve_secret_form_value(form_data, 'deye_password', creds.get('deye_password') or creds.get('password') or ''),
        'deye_password_hash': preserve_secret_form_value(form_data, 'deye_password_hash', creds.get('deye_password_hash') or creds.get('password_hash') or ''),
    })
    device_settings.update({
        'deye_region': (form_data.get('deye_region', '') or '').strip(),
        'deye_plant_id': preserve_secret_form_value(form_data, 'deye_plant_id', device_settings.get('deye_plant_id') or ''),
        'deye_device_sn': preserve_secret_form_value(form_data, 'deye_device_sn', device_settings.get('deye_device_sn') or ''),
        'deye_logger_sn': preserve_secret_form_value(form_data, 'deye_logger_sn', device_settings.get('deye_logger_sn') or ''),
        'deye_plant_name': (form_data.get('deye_plant_name', '') or '').strip(),
        'battery_capacity_kwh': (form_data.get('battery_capacity_kwh', '') or '').strip(),
        'battery_reserve_percent': (form_data.get('battery_reserve_percent', '') or '').strip(),
        'deye_battery_sn_main': preserve_secret_form_value(form_data, 'deye_battery_sn_main', device_settings.get('deye_battery_sn_main') or ''),
        'deye_battery_sn_module': preserve_secret_form_value(form_data, 'deye_battery_sn_module', device_settings.get('deye_battery_sn_module') or ''),
    })
    device.station_id = device_settings.get('deye_plant_id') or device.station_id
    device.device_uid = device_settings.get('deye_device_sn') or device.device_uid
    device.plant_name = device_settings.get('deye_plant_name') or device.plant_name or device.name
    device.credentials_json = json.dumps(creds, ensure_ascii=False)
    device.settings_json = json.dumps(device_settings, ensure_ascii=False)
    device.updated_at = datetime.utcnow()


def _device_payload(device: AppDevice | None):
    if device is None:
        return {}, {}
    creds = _safe_json_loads(getattr(device, 'credentials_json', None))
    settings = _safe_json_loads(getattr(device, 'settings_json', None))

    normalized_creds = {
        'deye_email': creds.get('deye_email') or creds.get('email') or '',
        'deye_password': creds.get('deye_password') or creds.get('password') or '',
        'deye_app_id': creds.get('deye_app_id') or creds.get('app_id') or '',
        'deye_app_secret': creds.get('deye_app_secret') or creds.get('app_secret') or '',
    }
    normalized_settings = {
        'deye_region': settings.get('deye_region') or settings.get('region') or 'EMEA',
        'api_base_url': settings.get('api_base_url') or getattr(device, 'api_base_url', '') or '',
    }
    return normalized_creds, normalized_settings


def _save_device_credentials(device: AppDevice, form_data=None):
    form_data = form_data or request.form
    existing_creds = _safe_json_loads(getattr(device, 'credentials_json', None))
    existing_settings = _safe_json_loads(getattr(device, 'settings_json', None))

    creds = {
        **existing_creds,
        'deye_email': preserve_secret_form_value(form_data, 'deye_email', existing_creds.get('deye_email') or existing_creds.get('email') or ''),
        'deye_password': preserve_secret_form_value(form_data, 'deye_password', existing_creds.get('deye_password') or existing_creds.get('password') or ''),
        'deye_password_hash': preserve_secret_form_value(form_data, 'deye_password_hash', existing_creds.get('deye_password_hash') or existing_creds.get('password_hash') or ''),
        'deye_app_id': preserve_secret_form_value(form_data, 'deye_app_id', existing_creds.get('deye_app_id') or existing_creds.get('app_id') or ''),
        'deye_app_secret': preserve_secret_form_value(form_data, 'deye_app_secret', existing_creds.get('deye_app_secret') or existing_creds.get('app_secret') or ''),
    }
    settings = {
        **existing_settings,
        'deye_region': (form_data.get('deye_region', 'EMEA') or 'EMEA').strip(),
        'api_base_url': (form_data.get('api_base_url', '') or '').strip(),
        'deye_plant_id': preserve_secret_form_value(form_data, 'station_id', existing_settings.get('deye_plant_id') or ''),
        'deye_device_sn': preserve_secret_form_value(form_data, 'device_uid', existing_settings.get('deye_device_sn') or ''),
        'deye_plant_name': (form_data.get('plant_name', '') or '').strip(),
    }

    device.credentials_json = json.dumps(creds, ensure_ascii=False)
    device.settings_json = json.dumps(settings, ensure_ascii=False)
    if settings.get('api_base_url'):
        device.api_base_url = settings.get('api_base_url')


def _save_device_fields(device: AppDevice, owner_user_id: int):
    device.name = (request.form.get('name', '') or '').strip() or device.name or 'My Solar Device'
    device.device_type = (request.form.get('device_type', 'deye') or 'deye').strip().lower()
    device.api_provider = (request.form.get('api_provider', device.device_type or 'deye') or 'deye').strip().lower()
    device.api_base_url = (request.form.get('api_base_url', '') or '').strip() or device.api_base_url
    device.external_device_id = preserve_secret_form_value(request.form, 'external_device_id', device.external_device_id or '') or None
    device.device_uid = preserve_secret_form_value(request.form, 'device_uid', device.device_uid or '') or None
    device.station_id = preserve_secret_form_value(request.form, 'station_id', device.station_id or '') or None
    device.plant_name = (request.form.get('plant_name', '') or '').strip() or None
    device.timezone = (request.form.get('timezone', current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')) or current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')).strip()
    device.auth_mode = (request.form.get('auth_mode', 'wizard') or 'wizard').strip().lower()
    device.notes = (request.form.get('notes', '') or '').strip()
    device.owner_user_id = owner_user_id
    device.is_active = request.form.get('is_active') == 'on'
    _save_device_credentials(device)
    device.updated_at = datetime.utcnow()


























def _telegram_webhook_target_url():
    try:
        root = (request.url_root or '').rstrip('/')
        if not root:
            return None
        return f"{root}/telegram/webhook"
    except Exception:
        return None


def _telegram_webhook_info(settings: dict):
    token = (settings.get('telegram_bot_token') or '').strip()
    base = (settings.get('telegram_api_url') or 'https://api.telegram.org').rstrip('/')
    if not token:
        return {'ok': False, 'description': 'Bot Token غير موجود'}
    try:
        r = requests.get(f"{base}/bot{token}/getWebhookInfo", timeout=20)
        data = r.json()
        result = data.get('result') or {}
        return {
            'ok': bool(data.get('ok')),
            'url': result.get('url', ''),
            'pending_update_count': result.get('pending_update_count', 0),
            'last_error_message': result.get('last_error_message', ''),
            'raw': data,
        }
    except Exception as exc:
        return {'ok': False, 'description': str(exc), 'url': '', 'pending_update_count': 0, 'last_error_message': ''}


def _telegram_set_webhook(settings: dict):
    token = (settings.get('telegram_bot_token') or '').strip()
    base = (settings.get('telegram_api_url') or 'https://api.telegram.org').rstrip('/')
    target = _telegram_webhook_target_url()
    if not token:
        return False, 'Bot Token غير موجود'
    if not target:
        return False, 'تعذر تحديد رابط الـ webhook'
    try:
        params = {'url': target}
        secret = (current_app.config.get('TELEGRAM_WEBHOOK_SECRET') or '').strip()
        if secret:
            params['secret_token'] = secret
        r = requests.get(f"{base}/bot{token}/setWebhook", params=params, timeout=20)
        data = r.json()
        return bool(data.get('ok')), data.get('description') or r.text[:500]
    except Exception as exc:
        return False, str(exc)


def _telegram_delete_webhook(settings: dict):
    token = (settings.get('telegram_bot_token') or '').strip()
    base = (settings.get('telegram_api_url') or 'https://api.telegram.org').rstrip('/')
    if not token:
        return False, 'Bot Token غير موجود'
    try:
        r = requests.get(f"{base}/bot{token}/deleteWebhook", timeout=20)
        data = r.json()
        return bool(data.get('ok')), data.get('description') or r.text[:500]
    except Exception as exc:
        return False, str(exc)


def _upsert_channel_setting(key: str, value: str):
    row = Setting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))


CHANNEL_FORM_FIELDS = {
    'telegram': {
        'text': ['telegram_bot_token', 'telegram_chat_id', 'telegram_api_url'],
        'checkbox': [],
    },
    'telegram_buttons': {
        'text': [],
        'checkbox': [
            'tg_btn_status', 'tg_btn_loads', 'tg_btn_weather', 'tg_btn_clouds',
            'tg_btn_battery_eta', 'tg_btn_surplus', 'tg_btn_decision', 'tg_btn_smart',
            'tg_btn_sunset', 'tg_btn_night_risk', 'tg_btn_last_sync',
        ],
    },
    'sms': {
        'text': ['sms_api_url', 'sms_api_key', 'sms_sender', 'sms_recipients'],
        'checkbox': [],
    },
}


def _save_channels_settings_from_form(form, section: str | None = None):
    section = (section or '').strip().lower()
    config = CHANNEL_FORM_FIELDS.get(section)
    if not config:
        return False
    existing = load_settings()
    sensitive_fields = {'telegram_bot_token', 'telegram_chat_id', 'sms_api_key', 'sms_recipients'}
    for field in config.get('text', []):
        if field in sensitive_fields:
            value = preserve_secret_form_value(form, field, existing.get(field, ''))
        else:
            value = (form.get(field, '') or '').strip()
        _upsert_channel_setting(field, value)
    for key in config.get('checkbox', []):
        _upsert_channel_setting(key, 'true' if form.get(key) == 'on' else 'false')
    db.session.commit()
    return True


def _is_ajax_request():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _json_response(ok: bool, message: str, **extra):
    payload = {'ok': ok, 'message': message}
    payload.update(extra)
    return jsonify(payload)



def _build_notification_test_payload(section: str, settings: dict, latest, weather):
    now_ts = int(datetime.now(UTC).timestamp())
    section = (section or '').strip().lower()
    if section in ('periodic', 'periodic_day'):
        title, message = build_periodic_status_message(latest, weather, settings=settings, phase_override='day')
        return {'section':'periodic_day','title':title,'message':message,'channel':settings.get('periodic_day_channel','telegram'),'rule_name':'اختبار دوري نهاري','event_key':f'test-periodic-day-{now_ts}','level':'info','success_message':'تم إرسال اختبار التحديث الدوري النهاري','preview_message':'تم تحديث معاينة التحديث الدوري النهاري'}
    if section in ('periodic_night', 'night'):
        title, message = build_periodic_status_message(latest, weather, settings=settings, phase_override='night')
        return {'section':'periodic_night','title':title,'message':message,'channel':settings.get('periodic_night_channel','telegram'),'rule_name':'اختبار دوري ليلي','event_key':f'test-periodic-night-{now_ts}','level':'info','success_message':'تم إرسال اختبار التحديث الدوري الليلي','preview_message':'تم تحديث معاينة التحديث الدوري الليلي'}
    if section in ('charge', 'battery'):
        _title, base_message = build_periodic_status_message(latest, weather, settings=settings, phase_override='day')
        return {'section':'charge','title':'🧪 اختبار حالة البطارية','message':base_message,'channel':settings.get('battery_test_channel','telegram'),'rule_name':'اختبار البطارية','event_key':f'test-battery-{now_ts}','level':'warning','success_message':'تم إرسال اختبار حالة البطارية','preview_message':'تم تحديث معاينة حالة البطارية'}
    if section == 'weather':
        from ..blueprints.notifications import _format_weather_check
        return {'section':'weather','title':'☁️ اختبار تنبيه الطقس','message':_format_weather_check(latest, weather, settings=settings),'channel':settings.get('weather_test_channel','telegram'),'rule_name':'اختبار الطقس','event_key':f'test-weather-{now_ts}','level':'info','success_message':'تم إرسال اختبار تنبيه الطقس','preview_message':'تم تحديث معاينة تنبيه الطقس'}
    if section == 'sunset':
        title, message, level = build_pre_sunset_message(latest, weather, settings=settings)
        return {'section':'sunset','title':title,'message':message,'channel':settings.get('pre_sunset_channel','telegram'),'rule_name':'اختبار الغروب','event_key':f'test-sunset-{now_ts}','level':level,'success_message':'تم إرسال اختبار تحليل الغروب','preview_message':'تم تحديث معاينة تحليل الغروب'}
    if section == 'daily_report':
        title, message = build_daily_morning_report_message(latest, settings=settings)
        return {'section':'daily_report','title':title,'message':message,'channel':settings.get('daily_report_channel','telegram'),'rule_name':'اختبار تقرير الصباح','event_key':f'test-daily-report-{now_ts}','level':'info','success_message':'تم إرسال تقرير الصباح التجريبي','preview_message':'تم تحديث معاينة تقرير الصباح'}
    if section == 'discharge':
        _title, message = build_periodic_status_message(latest, weather, settings=settings, phase_override='night')
        return {'section':'discharge','title':'🌙 تنبيه التفريغ الليلي','message':message,'channel':settings.get('night_discharge_channel','telegram'),'rule_name':'اختبار التفريغ','event_key':f'test-discharge-{now_ts}','level':'warning','success_message':'تم إرسال اختبار التفريغ الليلي','preview_message':'تم تحديث معاينة التفريغ الليلي'}
    if section == 'load':
        return {'section':'load','title':'⚡ إشعار الأحمال القابلة للتشغيل والممنوعة','message':build_telegram_quick_reply('loads', latest, weather, settings=settings),'channel':settings.get('load_alert_channel','telegram'),'rule_name':'اختبار الأحمال','event_key':f'test-load-{now_ts}','level':'info','success_message':'تم إرسال اختبار إشعار الأحمال','preview_message':'تم تحديث معاينة إشعار الأحمال'}
    raise ValueError('قسم الاختبار غير معروف')

def _store_notification_preview(payload: dict):
    session['notification_preview'] = {'section':payload.get('section',''),'title':payload.get('title',''),'message':payload.get('message',''),'channel':payload.get('channel','telegram')}















@main_bp.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='الصفحة غير موجودة'), 404


@main_bp.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='حدث خطأ في الخادم'), 500






























def _portal_support_rows(user):
    """Unified, user-scoped support timeline for portal users.
    Reads mail + tickets using both user_id and tenant_id for backward compatibility,
    and hides internal admin notes from subscribers.
    """
    rows = []
    if user is None:
        return rows
    tenant, _subscription = ensure_user_tenant_and_subscription(user, activated_by_user_id=getattr(user, 'id', None))
    tenant_id = getattr(tenant, 'id', None)

    if tenant_id:
        thread_q = InternalMailThread.query.filter(db.or_(InternalMailThread.created_by_user_id == user.id, InternalMailThread.tenant_id == tenant_id))
        ticket_q = SupportTicket.query.filter(db.or_(SupportTicket.opened_by_user_id == user.id, SupportTicket.tenant_id == tenant_id))
    else:
        thread_q = InternalMailThread.query.filter(InternalMailThread.created_by_user_id == user.id)
        ticket_q = SupportTicket.query.filter(SupportTicket.opened_by_user_id == user.id)

    for thread in thread_q.order_by(InternalMailThread.updated_at.desc(), InternalMailThread.id.desc()).all():
        messages = InternalMailMessage.query.filter_by(thread_id=thread.id, is_internal_note=False).order_by(InternalMailMessage.created_at.asc(), InternalMailMessage.id.asc()).all()
        rows.append({
            'kind': 'mail',
            'id': thread.id,
            'subject': thread.subject,
            'category': thread.category,
            'priority': thread.priority,
            'status': thread.status,
            'updated_at': thread.updated_at or thread.last_reply_at or thread.created_at,
            'messages': messages,
            'item': thread,
            'assignee': AppUser.query.get(thread.assigned_admin_user_id) if thread.assigned_admin_user_id else None,
        })

    for ticket in ticket_q.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).all():
        messages = SupportTicketMessage.query.filter_by(ticket_id=ticket.id, is_internal_note=False).order_by(SupportTicketMessage.created_at.asc(), SupportTicketMessage.id.asc()).all()
        rows.append({
            'kind': 'ticket',
            'id': ticket.id,
            'subject': ticket.subject,
            'category': ticket.category,
            'priority': ticket.priority,
            'status': ticket.status,
            'updated_at': ticket.updated_at or ticket.last_reply_at or ticket.created_at,
            'messages': messages,
            'item': ticket,
            'assignee': AppUser.query.get(ticket.assigned_admin_user_id) if ticket.assigned_admin_user_id else None,
        })

    rows.sort(key=lambda row: row.get('updated_at') or datetime.min, reverse=True)
    return rows






# --- Heavy v5: floating notification center for mail and tickets ---
def _support_notification_items(limit=5, include_closed=False):
    user = _active_user()
    if user is None:
        return []
    items = []
    try:
        if is_system_admin():
            thread_q = InternalMailThread.query
            ticket_q = SupportTicket.query
            if not include_closed:
                thread_q = thread_q.filter(InternalMailThread.status != 'closed')
                ticket_q = ticket_q.filter(SupportTicket.status != 'closed')
            for thread in thread_q.order_by(InternalMailThread.updated_at.desc(), InternalMailThread.id.desc()).limit(50).all():
                msg = InternalMailMessage.query.filter_by(thread_id=thread.id, is_internal_note=False).order_by(InternalMailMessage.created_at.desc(), InternalMailMessage.id.desc()).first()
                if not msg or (not include_closed and msg.sender_scope != 'user'):
                    continue
                sender = AppUser.query.get(thread.created_by_user_id) if thread.created_by_user_id else None
                tenant = TenantAccount.query.get(thread.tenant_id) if thread.tenant_id else None
                owner_id = thread.created_by_user_id or getattr(tenant, 'owner_user_id', None) or getattr(sender, 'id', None)
                items.append({'kind':'mail','id':thread.id,'title':thread.subject,'status':thread.status or 'open','priority':thread.priority or 'normal','sender':(getattr(sender,'full_name',None) or getattr(sender,'username',None) or getattr(tenant,'display_name',None) or 'مشترك'),'details':msg.body,'created_at':msg.created_at,'url':(url_for('main.admin_user_profile', user_id=owner_id, lang=_lang(), tab='support') + f'#case-mail-{thread.id}') if owner_id else (url_for('main.admin_internal_mail', lang=_lang()) + f'#thread-{thread.id}')})
            for ticket in ticket_q.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).limit(50).all():
                msg = SupportTicketMessage.query.filter_by(ticket_id=ticket.id, is_internal_note=False).order_by(SupportTicketMessage.created_at.desc(), SupportTicketMessage.id.desc()).first()
                if not msg or (not include_closed and msg.sender_scope != 'user'):
                    continue
                sender = AppUser.query.get(ticket.opened_by_user_id) if ticket.opened_by_user_id else None
                tenant = TenantAccount.query.get(ticket.tenant_id) if ticket.tenant_id else None
                owner_id = ticket.opened_by_user_id or getattr(tenant, 'owner_user_id', None) or getattr(sender, 'id', None)
                items.append({'kind':'ticket','id':ticket.id,'title':ticket.subject,'status':ticket.status or 'open','priority':ticket.priority or 'normal','sender':(getattr(sender,'full_name',None) or getattr(sender,'username',None) or getattr(tenant,'display_name',None) or 'مشترك'),'details':msg.body,'created_at':msg.created_at,'url':(url_for('main.admin_user_profile', user_id=owner_id, lang=_lang(), tab='support') + f'#case-ticket-{ticket.id}') if owner_id else (url_for('main.admin_tickets', lang=_lang()) + f'#ticket-{ticket.id}')})
        else:
            tenant, _subscription = ensure_user_tenant_and_subscription(user, activated_by_user_id=getattr(user, 'id', None))
            tenant_id = getattr(tenant, 'id', None)
            if tenant_id:
                thread_q = InternalMailThread.query.filter(db.or_(InternalMailThread.created_by_user_id == user.id, InternalMailThread.tenant_id == tenant_id))
                ticket_q = SupportTicket.query.filter(db.or_(SupportTicket.opened_by_user_id == user.id, SupportTicket.tenant_id == tenant_id))
            else:
                thread_q = InternalMailThread.query.filter_by(created_by_user_id=user.id)
                ticket_q = SupportTicket.query.filter_by(opened_by_user_id=user.id)
            if not include_closed:
                thread_q = thread_q.filter(InternalMailThread.status != 'closed')
                ticket_q = ticket_q.filter(SupportTicket.status != 'closed')
            for thread in thread_q.order_by(InternalMailThread.updated_at.desc(), InternalMailThread.id.desc()).limit(50).all():
                msg = InternalMailMessage.query.filter_by(thread_id=thread.id, is_internal_note=False).order_by(InternalMailMessage.created_at.desc(), InternalMailMessage.id.desc()).first()
                if not msg or (not include_closed and msg.sender_scope != 'admin'):
                    continue
                items.append({'kind':'mail','id':thread.id,'title':thread.subject,'status':thread.status or 'open','priority':thread.priority or 'normal','sender':'الإدارة' if msg.sender_scope == 'admin' else (g.current_user_display or user.username),'details':msg.body,'created_at':msg.created_at,'url':url_for('main.portal_support', lang=_lang(), type='mail') + f'#case-mail-{thread.id}'})
            for ticket in ticket_q.order_by(SupportTicket.updated_at.desc(), SupportTicket.id.desc()).limit(50).all():
                msg = SupportTicketMessage.query.filter_by(ticket_id=ticket.id, is_internal_note=False).order_by(SupportTicketMessage.created_at.desc(), SupportTicketMessage.id.desc()).first()
                if not msg or (not include_closed and msg.sender_scope != 'admin'):
                    continue
                items.append({'kind':'ticket','id':ticket.id,'title':ticket.subject,'status':ticket.status or 'open','priority':ticket.priority or 'normal','sender':'الإدارة' if msg.sender_scope == 'admin' else (g.current_user_display or user.username),'details':msg.body,'created_at':msg.created_at,'url':url_for('main.portal_support', lang=_lang(), type='ticket') + f'#case-ticket-{ticket.id}'})
    except Exception:
        return []
    items.sort(key=lambda item: item.get('created_at') or datetime.min, reverse=True)
    return items[:limit] if limit else items


def _support_notification_payload(limit=5, include_closed=False):
    user = _active_user()
    if user is None:
        return []
    try:
        rows = notification_items_for(user, is_system_admin(), limit=limit or 200, include_read=include_closed, lang=_lang())
        payload = []
        for ev in rows:
            payload.append({
                'event_id': ev.id,
                'kind': ev.source_type or ev.event_type or 'support',
                'id': ev.source_id,
                'title': ev.title or '',
                'status': ev.status or 'new',
                'priority': '',
                'sender': '',
                'details': (ev.message or '')[:240],
                'created_at': format_local_datetime(ev.created_at) if ev.created_at else '',
                'url': ev.direct_url or '#',
                'is_read': bool(ev.is_read),
            })
        if payload or not include_closed:
            return payload
    except Exception:
        pass
    # Safe fallback for older data before notification_event is populated.
    payload = []
    for item in _support_notification_items(limit=limit, include_closed=include_closed):
        created = item.get('created_at')
        payload.append({'kind':item.get('kind'),'id':item.get('id'),'title':item.get('title') or '','status':item.get('status') or 'open','priority':item.get('priority') or 'normal','sender':item.get('sender') or '','details':(item.get('details') or '')[:240],'created_at':format_local_datetime(created) if created else '','url':item.get('url') or '#', 'is_read': False})
    return payload





# --- Heavy v6.1: Support & Operations Command Center ---
def _support_source_for(case_type: str, source_id: int):
    if case_type == 'message':
        return InternalMailThread.query.get(source_id)
    if case_type == 'ticket':
        return SupportTicket.query.get(source_id)
    return None


def _support_owner_id_for_source(case_type: str, source):
    if not source:
        return None
    owner_id = getattr(source, 'created_by_user_id', None) if case_type == 'message' else getattr(source, 'opened_by_user_id', None)
    if owner_id:
        return owner_id
    tenant = TenantAccount.query.get(getattr(source, 'tenant_id', None)) if getattr(source, 'tenant_id', None) else None
    return getattr(tenant, 'owner_user_id', None)


def _support_messages_for_source(case_type: str, source):
    if not source:
        return []
    if case_type == 'message':
        return InternalMailMessage.query.filter_by(thread_id=source.id).order_by(InternalMailMessage.created_at.asc(), InternalMailMessage.id.asc()).all()
    if case_type == 'ticket':
        return SupportTicketMessage.query.filter_by(ticket_id=source.id).order_by(SupportTicketMessage.created_at.asc(), SupportTicketMessage.id.asc()).all()
    return []


def _support_add_admin_message(case_type: str, source, body: str, actor_id: int | None, *, is_internal_note: bool = False):
    body = (body or '').strip()
    if not source or not body:
        return None
    if case_type == 'message':
        msg = InternalMailMessage(thread_id=source.id, sender_user_id=actor_id, sender_scope='admin', is_internal_note=is_internal_note, body=body)
    elif case_type == 'ticket':
        msg = SupportTicketMessage(ticket_id=source.id, sender_user_id=actor_id, sender_scope='admin', is_internal_note=is_internal_note, body=body)
    else:
        return None
    db.session.add(msg)
    source.last_reply_at = datetime.utcnow()
    return msg


def _support_add_public_message(case_type: str, source, body: str, actor_id: int | None):
    return _support_add_admin_message(case_type, source, body, actor_id, is_internal_note=False)


def _support_label_maps(is_en: bool = False):
    if is_en:
        return {
            'status': {'new': 'New', 'open': 'Open', 'assigned': 'Assigned', 'pending': 'Pending', 'in_progress': 'In progress', 'waiting_user': 'Waiting user', 'resolved': 'Resolved', 'closed': 'Closed'},
            'priority': {'low': 'Low', 'normal': 'Normal', 'high': 'High', 'urgent': 'Urgent'},
            'type': {'message': 'Message', 'ticket': 'Ticket'},
        }
    return {
        'status': {'new': 'جديد', 'open': 'مفتوح', 'assigned': 'مخصص', 'pending': 'قيد الانتظار', 'in_progress': 'قيد المتابعة', 'waiting_user': 'بانتظار المستخدم', 'resolved': 'تم الحل', 'closed': 'مغلق'},
        'priority': {'low': 'منخفض', 'normal': 'عادي', 'high': 'مهم', 'urgent': 'عاجل'},
        'type': {'message': 'رسالة', 'ticket': 'تذكرة'},
    }


def _suggest_status_for_canned(title: str, body: str):
    haystack = f'{title or ""} {body or ""}'
    if 'معلومات' in haystack or 'بانتظار' in haystack:
        return 'waiting_user'
    if 'إغلاق' in haystack or 'اغلاق' in haystack:
        return 'closed'
    if 'حل' in haystack:
        return 'resolved'
    if 'تحويل' in haystack or 'استلام' in haystack:
        return 'assigned'
    return ''


# --- Heavy v10.1 compatibility route stubs ---
@main_bp.route('/')
def index(*args, **kwargs):
    from .energy import index as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/dashboard')
def admin_dashboard(*args, **kwargs):
    from .energy import admin_dashboard as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/dashboard')
def dashboard(*args, **kwargs):
    from .energy import dashboard as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/api/live')
def api_live(*args, **kwargs):
    from .energy import api_live as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/statistics')
def statistics(*args, **kwargs):
    from .energy import statistics as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/reports')
def reports(*args, **kwargs):
    from .energy import reports as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/statistics/export/csv')
def export_statistics_csv(*args, **kwargs):
    from .energy import export_statistics_csv as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/statistics/export/pdf')
def export_statistics_pdf(*args, **kwargs):
    from .energy import export_statistics_pdf as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/deye', methods=['GET', 'POST'])
def deye_settings(*args, **kwargs):
    from .energy import deye_settings as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/test-connection', methods=['POST'])
def test_connection(*args, **kwargs):
    from .energy import test_connection as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/sync-now', methods=['POST'])
def sync_now(*args, **kwargs):
    from .energy import sync_now as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/diagnostics')
def diagnostics(*args, **kwargs):
    from .energy import diagnostics as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/live-data')
def live_data(*args, **kwargs):
    from .energy import live_data as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users/<int:user_id>', methods=['GET', 'POST'])
def admin_user_profile(*args, **kwargs):
    from .users_routes import admin_user_profile as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users', methods=['GET', 'POST'])
def admin_users(*args, **kwargs):
    from .users_routes import admin_users as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users/legacy', methods=['GET', 'POST'])
def admin_users_legacy(*args, **kwargs):
    from .users_routes import admin_users_legacy as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users/new', methods=['GET', 'POST'])
def admin_user_create(*args, **kwargs):
    from .users_routes import admin_user_create as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
def admin_user_edit(*args, **kwargs):
    from .users_routes import admin_user_edit as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
def admin_user_toggle(*args, **kwargs):
    from .users_routes import admin_user_toggle as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def admin_user_delete(*args, **kwargs):
    from .users_routes import admin_user_delete as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/devices/select/<int:device_id>', methods=['POST'])
def select_device(*args, **kwargs):
    from .devices_routes import select_device as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/devices/manage', methods=['GET', 'POST'])
def devices_manage(*args, **kwargs):
    from .devices_routes import devices_manage as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/devices/manage/<int:device_id>/edit', methods=['GET', 'POST'])
def device_edit(*args, **kwargs):
    from .devices_routes import device_edit as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/devices/manage/<int:device_id>/toggle', methods=['POST'])
def device_toggle(*args, **kwargs):
    from .devices_routes import device_toggle as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding_wizard(*args, **kwargs):
    from .devices_routes import onboarding_wizard as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/onboarding/skip', methods=['POST'])
def onboarding_skip(*args, **kwargs):
    from .devices_routes import onboarding_skip as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/system-logs')
def admin_system_logs(*args, **kwargs):
    from .users_routes import admin_system_logs as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/devices')
def devices(*args, **kwargs):
    from .devices_routes import devices as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/battery-lab')
def battery_lab(*args, **kwargs):
    from .devices_routes import battery_lab as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/loads', methods=['GET', 'POST'])
def loads_page(*args, **kwargs):
    from .energy import loads_page as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/alerts')
def alerts(*args, **kwargs):
    from .notifications_routes import alerts as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notifications/action', methods=['POST'])
def notifications_action(*args, **kwargs):
    from .notifications_routes import notifications_action as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/channels', methods=['GET', 'POST'])
def channels(*args, **kwargs):
    from .notifications_routes import channels as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notifications', methods=['GET', 'POST'])
def notifications_settings(*args, **kwargs):
    from .notifications_routes import notifications_settings as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notifications/test', methods=['POST'])
def notifications_test_send(*args, **kwargs):
    from .notifications_routes import notifications_test_send as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notifications/test-section', methods=['POST'])
def notifications_test_section(*args, **kwargs):
    from .notifications_routes import notifications_test_section as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/telegram/menu/send', methods=['POST'])
def telegram_send_menu_route(*args, **kwargs):
    from .notifications_routes import telegram_send_menu_route as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/telegram/webhook', methods=['GET', 'POST'], strict_slashes=False)
def telegram_webhook(*args, **kwargs):
    from .notifications_routes import telegram_webhook as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/plant-info')
def plant_info(*args, **kwargs):
    from .energy import plant_info as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/api/raw-debug')
def api_raw_debug(*args, **kwargs):
    from .energy import api_raw_debug as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/plans')
def admin_plans(*args, **kwargs):
    from .billing import admin_plans as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/plans/new', methods=['GET','POST'])
def admin_plan_create(*args, **kwargs):
    from .billing import admin_plan_create as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/plans/<int:plan_id>/edit', methods=['GET','POST'])
def admin_plan_edit(*args, **kwargs):
    from .billing import admin_plan_edit as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/subscribers')
def admin_subscribers(*args, **kwargs):
    from .billing import admin_subscribers as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/subscribers/<int:user_id>/activate', methods=['GET','POST'])
def admin_subscriber_activate(*args, **kwargs):
    from .billing import admin_subscriber_activate as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/account/subscription')
def account_subscription(*args, **kwargs):
    from .billing import account_subscription as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/subscriptions')
def admin_subscriptions(*args, **kwargs):
    from .billing import admin_subscriptions as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/mail', methods=['GET', 'POST'])
def admin_internal_mail(*args, **kwargs):
    from .support import admin_internal_mail as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/finance', methods=['GET', 'POST'])
def admin_finance(*args, **kwargs):
    from .billing import admin_finance as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/activity-log')
def admin_activity_log(*args, **kwargs):
    from .users_routes import admin_activity_log as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/roles')
def admin_roles(*args, **kwargs):
    from .users_routes import admin_roles as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/tickets', methods=['GET', 'POST'])
def admin_tickets(*args, **kwargs):
    from .support import admin_tickets as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/quotas', methods=['GET', 'POST'])
def admin_quotas(*args, **kwargs):
    from .billing import admin_quotas as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/support', methods=['GET', 'POST'])
@main_bp.route('/portal/support', methods=['GET', 'POST'])
def portal_support(*args, **kwargs):
    from .support import portal_support as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/portal/messages', methods=['GET', 'POST'])
def portal_messages(*args, **kwargs):
    from .support import portal_messages as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/portal/tickets', methods=['GET', 'POST'])
def portal_tickets(*args, **kwargs):
    from .support import portal_tickets as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notifications/feed')
def notifications_feed(*args, **kwargs):
    from .notifications_routes import notifications_feed as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notification-center')
@main_bp.route('/notifications/center')
def notification_center(*args, **kwargs):
    from .notifications_routes import notification_center as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/support-command-center')
def admin_support_command_center(*args, **kwargs):
    from .support import admin_support_command_center as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/support-command-center/action', methods=['POST'])
def admin_support_command_action(*args, **kwargs):
    from .support import admin_support_command_action as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/admin/support-command-center/reopen', methods=['POST'])
def admin_support_reopen(*args, **kwargs):
    from .support import admin_support_reopen as _impl
    return _impl(*args, **kwargs)

@main_bp.route('/notifications/mark-read', methods=['POST'])
def notifications_mark_read(*args, **kwargs):
    from .notifications_routes import notifications_mark_read as _impl
    return _impl(*args, **kwargs)

