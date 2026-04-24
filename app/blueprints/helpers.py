"""
Shared helper functions used across blueprints.
Pure functions — no Flask context required except where noted.
"""
from __future__ import annotations
import json
import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import current_app

from ..extensions import db
from ..models import EventLog, NotificationLog, Reading, Setting, SyncLog
from ..services.scope import current_scope_ids, scoped_query
from ..services.security import preserve_secret_form_value
from ..services.utils import (
    format_local_datetime,
    human_duration_hours,
    safe_float,
    safe_power_w,
    search_battery_metrics,
    extract_device_detail_metrics,
    to_json,
    utc_to_local,
)


# ── Settings ──────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    items = Setting.query.all()
    settings = {item.key: item.value for item in items}
    cfg = current_app.config
    defaults = {
        'deye_app_id': cfg['DEYE_APP_ID'],
        'deye_app_secret': cfg['DEYE_APP_SECRET'],
        'deye_email': cfg['DEYE_EMAIL'],
        'deye_password': cfg['DEYE_PASSWORD'],
        'deye_password_hash': cfg['DEYE_PASSWORD_HASH'],
        'deye_region': cfg['DEYE_REGION'],
        'deye_plant_id': cfg['DEYE_PLANT_ID'],
        'deye_device_sn': cfg['DEYE_DEVICE_SN'],
        'deye_plant_name': cfg['DEYE_PLANT_NAME'],
        'battery_capacity_kwh': str(cfg['BATTERY_CAPACITY_KWH']),
        'battery_reserve_percent': str(cfg['BATTERY_RESERVE_PERCENT']),
        'deye_logger_sn': cfg.get('DEYE_LOGGER_SN', ''),
        'deye_battery_sn_main': cfg['DEYE_BATTERY_SN_MAIN'],
        'deye_battery_sn_module': cfg['DEYE_BATTERY_SN_MODULE'],
        'telegram_bot_token': '',
        'telegram_chat_id': '',
        'telegram_api_url': 'https://api.telegram.org',
        'tg_btn_status': 'true',
        'tg_btn_loads': 'true',
        'tg_btn_weather': 'true',
        'tg_btn_clouds': 'true',
        'tg_btn_battery_eta': 'true',
        'tg_btn_surplus': 'true',
        'tg_btn_decision': 'true',
        'tg_btn_smart': 'true',
        'tg_btn_sunset': 'true',
        'tg_btn_night_risk': 'true',
        'tg_btn_last_sync': 'true',
        'sms_api_url': '',
        'sms_api_key': '',
        'sms_sender': '',
        'sms_recipients': '',
        'notifications_enabled': 'true',
        'notification_rules_json': '',
        'daytime_solar_min_w': '50',
        'weather_enabled': 'true',
        'weather_daily_summary_enabled': 'true',
        'weather_daily_summary_channel': 'telegram',
        'weather_change_alerts_enabled': 'true',
        'weather_change_alerts_channel': 'telegram',
        'weather_cloud_threshold': '60',
        'periodic_status_enabled': 'true',
        'periodic_status_interval_minutes': '30',
        'periodic_status_channel': 'telegram',
        'periodic_status_include_weather': 'true',
        'periodic_status_last_sent_at': '',
        'pre_sunset_enabled': 'false',
        'pre_sunset_interval_minutes': '30',
        'pre_sunset_channel': 'telegram',
        'pre_sunset_subtract_hour': 'true',
        'pre_sunset_only_if_not_full': 'false',
        'pre_sunset_last_sent_at': '',
        'night_max_load_w': '500',
        'periodic_day_enabled': 'true',
        'periodic_day_interval_value': '1',
        'periodic_day_interval_unit': 'hours',
        'periodic_day_schedule_mode': 'interval',
        'periodic_day_specific_hours': '08:00,10:00,12:00,14:00,16:00',
        'periodic_day_time_start': '08:00',
        'periodic_day_time_end': 'sunset',
        'periodic_day_channel': 'telegram',
        'periodic_day_include_progress': 'true',
        'periodic_day_include_summary': 'true',
        'periodic_day_include_device': 'true',
        'periodic_day_include_weather': 'true',
        'periodic_day_include_loads': 'true',
        'periodic_day_include_sunset': 'true',
        'periodic_night_enabled': 'true',
        'periodic_night_interval_value': '1',
        'periodic_night_interval_unit': 'hours',
        'periodic_night_schedule_mode': 'interval',
        'periodic_night_specific_hours': '20:00,22:00,00:00,02:00,04:00,06:00',
        'periodic_night_time_start': 'sunset',
        'periodic_night_time_end': '08:00',
        'periodic_night_channel': 'telegram',
        'periodic_night_include_progress': 'true',
        'periodic_night_include_summary': 'true',
        'periodic_night_include_device': 'true',
        'periodic_night_include_loads': 'true',
        'periodic_night_include_eta': 'true',
        'pre_sunset_schedule_mode': 'interval',
        'pre_sunset_specific_hours': '13:00,14:00,15:00,16:00',
        'pre_sunset_time_start': '13:00',
        'pre_sunset_time_end': 'sunset',
        'pre_sunset_include_soc': 'true',
        'pre_sunset_include_charge_power': 'true',
        'pre_sunset_include_eta': 'true',
        'pre_sunset_include_advice': 'true',
        'night_discharge_enabled': 'true',
        'night_discharge_schedule_mode': 'threshold',
        'night_discharge_interval_value': '1',
        'night_discharge_interval_unit': 'hours',
        'night_discharge_time_start': 'sunset',
        'night_discharge_time_end': '08:00',
        'night_discharge_channel': 'telegram',
        'night_discharge_percent_step': '5',
        'night_discharge_include_device': 'true',
        'night_discharge_include_energy': 'true',
        'load_alert_enabled': 'true',
        'load_alert_schedule_mode': 'interval',
        'load_alert_interval_value': '1',
        'load_alert_interval_unit': 'hours',
        'load_alert_specific_hours': '09:00,11:00,13:00,15:00',
        'load_alert_time_start': '08:00',
        'load_alert_time_end': 'sunset',
        'load_alert_channel': 'telegram',
        'load_alert_include_allowed': 'true',
        'load_alert_include_blocked': 'true',
        'load_alert_max_items': '4',
        'weather_test_enabled': 'true',
        'weather_test_schedule_mode': 'interval',
        'weather_test_interval_value': '1',
        'weather_test_interval_unit': 'hours',
        'weather_test_time_start': '06:00',
        'weather_test_time_end': 'sunset',
        'weather_test_channel': 'telegram',
        'weather_test_include_next_hour': 'true',
        'weather_test_include_smart_tip': 'true',
        'battery_test_enabled': 'true',
        'battery_test_schedule_mode': 'manual',
        'battery_test_interval_value': '1',
        'battery_test_interval_unit': 'hours',
        'battery_test_time_start': '00:00',
        'battery_test_time_end': '23:59',
        'battery_test_channel': 'telegram',
        'battery_test_include_day_summary': 'true',
        'battery_test_include_sunset': 'true',
        'battery_test_include_loads': 'true',
        'daily_report_enabled': 'true',
        'daily_report_time': '07:00',
        'daily_report_channel': 'telegram',
        'daily_report_include_totals': 'true',
        'daily_report_include_yesterday': 'true',
        'daily_report_include_device': 'true',
        'charge_step_percent': '10',
        'actual_surplus_enabled': 'true',
        'event_logging_enabled': 'true',
        'event_log_retention_days': '60',
        'sms_critical_enabled': 'true',
        'sms_critical_cooldown_minutes': '120',
        'sms_critical_battery_enabled': 'true',
        'sms_critical_battery_threshold_percent': '20',
        'sms_critical_runtime_enabled': 'true',
        'sms_critical_runtime_threshold_hours': '2',
        'sms_critical_sync_enabled': 'true',
        'sms_critical_sync_stale_minutes': '30',
        'sms_critical_day_zero_enabled': 'true',
        'sms_critical_day_zero_threshold_w': '50',
        'sms_critical_day_zero_duration_minutes': '20',
        'sms_critical_day_zero_min_home_w': '150',
        'sms_critical_no_load_enabled': 'true',
        'sms_critical_no_load_duration_minutes': '15',
        'sms_critical_evening_load_enabled': 'true',
        'sms_critical_evening_load_threshold_w': '500',
        'sms_critical_evening_load_duration_minutes': '20',
        'sms_critical_evening_start': 'sunset',
        'sms_critical_evening_end': '23:59',
        'sms_critical_morning_deficit_enabled': 'true',
        'sms_critical_morning_deficit_threshold_w': '100',
        'sms_critical_morning_deficit_duration_minutes': '30',
        'sms_critical_morning_start': '06:00',
        'sms_critical_morning_end': '10:00',
        'sms_critical_emergency_enabled': 'true',
        'sms_critical_emergency_battery_percent': '10',
        'last_sms_type': '',
        'last_sms_sent_at': '',
        'last_sms_signature': '',
    }
    for key, value in defaults.items():
        settings.setdefault(key, value)
    return settings


def _upsert_setting(key: str, value: str):
    item = Setting.query.filter_by(key=key).first()
    if item:
        item.value = value
    else:
        db.session.add(Setting(key=key, value=value))


def save_settings_from_form(form):
    existing = load_settings()
    fields = [
        'deye_app_id', 'deye_app_secret', 'deye_email', 'deye_password',
        'deye_password_hash', 'deye_region', 'deye_plant_id', 'deye_device_sn',
        'deye_logger_sn', 'deye_plant_name', 'battery_capacity_kwh', 'battery_reserve_percent',
        'deye_battery_sn_main', 'deye_battery_sn_module',
    ]
    sensitive_fields = {'deye_app_id', 'deye_app_secret', 'deye_email', 'deye_password', 'deye_password_hash', 'deye_plant_id', 'deye_device_sn', 'deye_logger_sn', 'deye_battery_sn_main', 'deye_battery_sn_module'}
    for field in fields:
        if field in sensitive_fields:
            value = preserve_secret_form_value(form, field, existing.get(field, ''))
        else:
            value = form.get(field, '').strip()
        _upsert_setting(field, value)
    db.session.commit()


# ── Logging ───────────────────────────────────────────────────────────────────

def log_event(level: str, message: str, raw=None):
    user_id, device_id = current_scope_ids()
    db.session.add(SyncLog(user_id=user_id, device_id=device_id, level=level, message=message, raw_json=to_json(raw or {})))
    db.session.commit()


def add_event_log(event_type: str, title: str, details: str = '', severity: str = 'info', event_key: str = '', value_before=None, value_after=None, raw=None):
    settings = load_settings()
    if str(settings.get('event_logging_enabled', 'true')).lower() != 'true':
        return None
    user_id, device_id = current_scope_ids()
    row = EventLog(
        user_id=user_id,
        device_id=device_id,
        event_key=(event_key or event_type)[:160],
        event_type=(event_type or 'system')[:60],
        severity=(severity or 'info')[:20],
        title=(title or 'حدث جديد')[:200],
        details=details or '',
        value_before='' if value_before is None else str(value_before),
        value_after='' if value_after is None else str(value_after),
        raw_json=to_json(raw or {}),
    )
    db.session.add(row)
    db.session.commit()
    return row


def get_recent_event_logs(limit: int = 10):
    return scoped_query(EventLog).order_by(EventLog.created_at.desc()).limit(max(int(limit or 10), 1)).all()


def _round_w(value) -> float:
    try:
        return round(float(value or 0), 1)
    except Exception:
        return 0.0


def compute_actual_solar_surplus(latest: Reading | None, weather=None, settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    empty = {
        'raw_surplus_w': 0.0,
        'battery_charge_need_w': 0.0,
        'actual_surplus_w': 0.0,
        'battery_priority_w': 0.0,
        'battery_priority_active': False,
        'battery_remaining_wh': 0.0,
        'remaining_hours_to_sunset': None,
        'remaining_label': 'غير متاح',
        'phase': 'night',
        'headline_ar': 'لا توجد بيانات كافية',
        'headline_en': 'Not enough data',
        'details_ar': 'بانتظار أول قراءة.',
        'details_en': 'Waiting for the first reading.',
    }
    if not latest:
        return empty

    solar = float(latest.solar_power or 0)
    home = float(latest.home_load or 0)
    raw_surplus = max(solar - home, 0.0)

    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    sunset_dt = None
    if weather and getattr(weather, 'sunset_time', None):
        try:
            sunset_dt = datetime.fromisoformat(now_local.strftime('%Y-%m-%d') + 'T' + weather.sunset_time + ':00')
            if now_local.tzinfo is not None and sunset_dt.tzinfo is None:
                sunset_dt = sunset_dt.replace(tzinfo=now_local.tzinfo)
        except Exception:
            sunset_dt = None
    day_start = now_local.replace(hour=6, minute=0, second=0, microsecond=0)
    is_day = bool(sunset_dt and day_start <= now_local < sunset_dt)

    battery_capacity_kwh, _reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, _reserve_percent)
    remaining_wh = max(float(battery.get('remaining_to_full_kwh', 0) or 0) * 1000.0, 0.0)

    remaining_hours = None
    battery_need_w = 0.0
    if is_day and sunset_dt is not None:
        remaining_hours = max((sunset_dt - now_local).total_seconds() / 3600.0, 0.0)
        if remaining_hours > 0:
            battery_need_w = remaining_wh / remaining_hours

    actual_surplus = raw_surplus
    battery_priority_active = False
    if str(settings.get('actual_surplus_enabled', 'true')).lower() == 'true' and is_day and remaining_hours and remaining_hours > 0:
        actual_surplus = max(raw_surplus - battery_need_w, 0.0)
        battery_priority_active = battery_need_w > 0.5 and raw_surplus > 0

    if not is_day:
        phase = 'night'
        headline_ar = 'ليلًا لا يتم احتساب فائض شمسي فعلي للأحمال'
        headline_en = 'At night there is no actual solar surplus for loads'
        details_ar = 'يتم إيقاف هذا المؤشر بعد الغروب ويعتمد القرار الليلي على الحد المحفوظ.'
        details_en = 'This indicator stops after sunset and the night decision uses the saved limit.'
    elif raw_surplus <= 0:
        phase = 'day'
        headline_ar = 'لا يوجد فائض شمسي خام حاليًا'
        headline_en = 'There is no raw solar surplus right now'
        details_ar = 'إنتاج الشمس لا يغطي سحب المنزل بالكامل حاليًا.'
        details_en = 'Solar production is not fully covering the home load right now.'
    elif battery_priority_active and actual_surplus < raw_surplus:
        phase = 'day'
        headline_ar = 'جزء من الفائض محجوز لشحن البطارية قبل الغروب'
        headline_en = 'Part of the surplus is reserved to charge the battery before sunset'
        details_ar = 'تم خصم احتياج شحن البطارية من الفائض الخام حتى لا نعتبر كل الفائض متاحًا للأحمال.'
        details_en = 'Battery charging need was deducted from the raw surplus so not all surplus is treated as available for loads.'
    else:
        phase = 'day'
        headline_ar = 'معظم الفائض الحالي متاح للأحمال'
        headline_en = 'Most of the current surplus is available for loads'
        details_ar = 'لا توجد أولوية شحن كبيرة تمنع استخدام الفائض الحالي.'
        details_en = 'There is no major charging priority blocking the current surplus usage.'

    return {
        'raw_surplus_w': _round_w(raw_surplus),
        'battery_charge_need_w': _round_w(battery_need_w),
        'actual_surplus_w': _round_w(actual_surplus),
        'battery_priority_w': _round_w(max(raw_surplus - actual_surplus, 0.0)),
        'battery_priority_active': bool(battery_priority_active),
        'battery_remaining_wh': _round_w(remaining_wh),
        'remaining_hours_to_sunset': remaining_hours,
        'remaining_label': human_duration_hours(remaining_hours) if remaining_hours is not None and remaining_hours > 0 else ('الشمس غائبة' if not is_day else 'أقل من ساعة'),
        'phase': phase,
        'headline_ar': headline_ar,
        'headline_en': headline_en,
        'details_ar': details_ar,
        'details_en': details_en,
    }


def maybe_log_energy_events(current: Reading | None, previous: Reading | None, weather=None, settings: dict | None = None):
    settings = settings or load_settings()
    if not current:
        return
    current_surplus = compute_actual_solar_surplus(current, weather=weather, settings=settings)
    previous_surplus = compute_actual_solar_surplus(previous, weather=weather, settings=settings) if previous else None

    current_phase = current_surplus.get('phase', 'night')
    previous_phase = previous_surplus.get('phase', 'night') if previous_surplus else None
    if previous_phase and current_phase != previous_phase:
        add_event_log(
            event_type='phase_change',
            event_key='phase-change',
            severity='info',
            title='تغير وضع النظام بين النهار والليل',
            details=f'انتقل النظام من {previous_phase} إلى {current_phase}.',
            value_before=previous_phase,
            value_after=current_phase,
            raw={'current_phase': current_phase, 'previous_phase': previous_phase},
        )

    prev_priority = bool(previous_surplus.get('battery_priority_active')) if previous_surplus else None
    curr_priority = bool(current_surplus.get('battery_priority_active'))
    if prev_priority is not None and prev_priority != curr_priority:
        add_event_log(
            event_type='battery_priority',
            event_key='battery-priority',
            severity='warning' if curr_priority else 'success',
            title='تغيرت أولوية شحن البطارية قبل الغروب',
            details=(
                f'أصبح جزء من الفائض محجوزًا لشحن البطارية ({current_surplus.get("battery_charge_need_w", 0):.1f} واط).'
                if curr_priority else
                'لم تعد البطارية تحجز جزءًا مهمًا من الفائض الحالي.'
            ),
            value_before='مفعلة' if prev_priority else 'غير مفعلة',
            value_after='مفعلة' if curr_priority else 'غير مفعلة',
            raw={'current': current_surplus, 'previous': previous_surplus},
        )

    prev_actual = float(previous_surplus.get('actual_surplus_w', 0) or 0) if previous_surplus else None
    curr_actual = float(current_surplus.get('actual_surplus_w', 0) or 0)
    if prev_actual is not None:
        if prev_actual <= 0 < curr_actual:
            add_event_log(
                event_type='actual_surplus',
                event_key='actual-surplus-start',
                severity='success',
                title='بدأ توفر فائض شمسي فعلي للأحمال',
                details=f'الفائض الفعلي الحالي {curr_actual:.1f} واط بعد خصم أولوية شحن البطارية.',
                value_before=f'{prev_actual:.1f}',
                value_after=f'{curr_actual:.1f}',
                raw={'current': current_surplus, 'previous': previous_surplus},
            )
        elif prev_actual > 0 >= curr_actual:
            add_event_log(
                event_type='actual_surplus',
                event_key='actual-surplus-end',
                severity='warning',
                title='انتهى الفائض الشمسي الفعلي المتاح للأحمال',
                details='لم يعد هناك فائض فعلي متاح بعد خصم احتياج البطارية أو بسبب ارتفاع سحب المنزل.',
                value_before=f'{prev_actual:.1f}',
                value_after=f'{curr_actual:.1f}',
                raw={'current': current_surplus, 'previous': previous_surplus},
            )
        elif abs(curr_actual - prev_actual) >= 300:
            add_event_log(
                event_type='actual_surplus_shift',
                event_key='actual-surplus-shift',
                severity='info',
                title='تغير واضح في الفائض الشمسي الفعلي',
                details=f'تغير الفائض الفعلي من {prev_actual:.1f} إلى {curr_actual:.1f} واط.',
                value_before=f'{prev_actual:.1f}',
                value_after=f'{curr_actual:.1f}',
                raw={'current': current_surplus, 'previous': previous_surplus},
            )

    prev_status = (previous.status_text or '').strip() if previous else ''
    curr_status = (current.status_text or '').strip()
    if prev_status and curr_status and prev_status != curr_status:
        add_event_log(
            event_type='status_change',
            event_key='status-change',
            severity='info',
            title='تغيرت الحالة العامة للنظام',
            details=f'انتقلت الحالة من "{prev_status}" إلى "{curr_status}".',
            value_before=prev_status,
            value_after=curr_status,
        )


def prune_old_logs():
    """Delete old SyncLog and NotificationLog rows to keep DB size manageable."""
    cfg = current_app.config
    sync_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=cfg.get('SYNCLOG_RETENTION_DAYS', 30))
    notif_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=cfg.get('NOTIFICATIONLOG_RETENTION_DAYS', 90))
    event_retention_days = max(int(safe_float(load_settings().get('event_log_retention_days'), 60) or 60), 7)
    event_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=event_retention_days)
    try:
        SyncLog.query.filter(SyncLog.created_at < sync_cutoff).delete()
        NotificationLog.query.filter(NotificationLog.created_at < notif_cutoff).delete()
        EventLog.query.filter(EventLog.created_at < event_cutoff).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


# ── Battery ───────────────────────────────────────────────────────────────────

def get_runtime_battery_settings(settings: dict | None = None) -> tuple[float, float]:
    settings = settings or load_settings()
    capacity = safe_float(settings.get('battery_capacity_kwh'), current_app.config.get('BATTERY_CAPACITY_KWH', 5))
    reserve = safe_float(settings.get('battery_reserve_percent'), current_app.config.get('BATTERY_RESERVE_PERCENT', 20))
    try:
        capacity = float(capacity or 5)
    except Exception:
        capacity = float(current_app.config.get('BATTERY_CAPACITY_KWH', 5) or 5)
    try:
        reserve = float(reserve or 20)
    except Exception:
        reserve = float(current_app.config.get('BATTERY_RESERVE_PERCENT', 20) or 20)
    return capacity, max(min(reserve, 95), 0)


def build_battery_insights(latest: Reading | None, battery_capacity_kwh: float, reserve_percent: float) -> dict:
    reserve_percent = max(min(float(reserve_percent or 20), 95), 0)
    reserve_kwh = battery_capacity_kwh * reserve_percent / 100
    empty = {
        'capacity_kwh': round(battery_capacity_kwh, 2),
        'reserve_percent': reserve_percent,
        'reserve_kwh': round(reserve_kwh, 2),
        'stored_kwh': 0.0,
        'usable_now_kwh': 0.0,
        'remaining_to_full_kwh': round(battery_capacity_kwh, 2),
        'charge_eta': 'غير متاح',
        'discharge_eta': 'غير متاح',
        'mode_label': 'ثابتة',
        'charge_power_w': 0.0,
        'discharge_power_w': 0.0,
    }
    if not latest:
        return empty

    soc = max(min(float(latest.battery_soc or 0), 100), 0)
    stored_kwh = battery_capacity_kwh * soc / 100
    remaining_to_full_kwh = max(battery_capacity_kwh - stored_kwh, 0)
    usable_now_kwh = max(stored_kwh - reserve_kwh, 0)

    charge_power_w = 0.0
    discharge_power_w = 0.0
    if latest.raw_json:
        try:
            raw = json.loads(latest.raw_json)
            derived = raw.get('derived', {}) if isinstance(raw, dict) else {}
            charge_power_w = abs(safe_power_w(derived.get('chargePower'), 0.0))
            discharge_power_w = abs(safe_power_w(derived.get('dischargePower'), 0.0))
        except Exception:
            pass

    # Fallback: use battery_power field
    if charge_power_w <= 0 and discharge_power_w <= 0:
        battery_power = float(latest.battery_power or 0)
        if battery_power > 0 and float(latest.home_load or 0) > float(latest.solar_power or 0):
            discharge_power_w = abs(battery_power)
        elif battery_power > 0:
            charge_power_w = abs(battery_power)
        elif battery_power < 0:
            discharge_power_w = abs(battery_power)

    mode_label = 'ثابتة'
    charge_eta = 'غير متاح'
    discharge_eta = 'غير متاح'
    if charge_power_w > 0 and discharge_power_w <= 0:
        mode_label = 'يتم الشحن'
        charge_eta = human_duration_hours(remaining_to_full_kwh / (charge_power_w / 1000) if charge_power_w else None)
    elif discharge_power_w > 0 and charge_power_w <= 0:
        mode_label = 'يتم التفريغ'
        discharge_eta = human_duration_hours(usable_now_kwh / (discharge_power_w / 1000) if discharge_power_w else None)
    elif charge_power_w > 0 and discharge_power_w > 0:
        if charge_power_w >= discharge_power_w:
            mode_label = 'يتم الشحن'
            charge_eta = human_duration_hours(remaining_to_full_kwh / (charge_power_w / 1000))
        else:
            mode_label = 'يتم التفريغ'
            discharge_eta = human_duration_hours(usable_now_kwh / (discharge_power_w / 1000))

    return {
        'capacity_kwh': round(battery_capacity_kwh, 2),
        'reserve_percent': reserve_percent,
        'reserve_kwh': round(reserve_kwh, 2),
        'stored_kwh': round(stored_kwh, 2),
        'usable_now_kwh': round(usable_now_kwh, 2),
        'remaining_to_full_kwh': round(remaining_to_full_kwh, 2),
        'charge_eta': charge_eta,
        'discharge_eta': discharge_eta,
        'mode_label': mode_label,
        'charge_power_w': round(abs(charge_power_w), 1),
        'discharge_power_w': round(abs(discharge_power_w), 1),
    }


def build_battery_details(latest: Reading | None) -> dict:
    details = {
        # Battery BMS
        'battery_voltage': None, 'battery_current': None, 'battery_temp': None,
        'battery_cycles': None, 'battery_soh': None, 'battery_status': None,
        'battery_health': None, 'battery_total_capacity_ah': None, 'battery_type': None,
        'battery_capacity_ah': None,
        'battery_sn_main': current_app.config.get('DEYE_BATTERY_SN_MAIN', ''),
        'battery_sn_module': current_app.config.get('DEYE_BATTERY_SN_MODULE', ''),
        # Inverter & temperatures — initialized to None so templates can safely check
        'inverter_temp': None, 'dc_temp': None,
        # Grid
        'grid_voltage_l1': None, 'grid_voltage_l2': None, 'grid_voltage_l3': None,
        'grid_current_l1': None, 'grid_frequency': None, 'ac_output_power': None,
        # PV strings
        'pv1_voltage': None, 'pv1_current': None, 'pv1_power': None,
        'pv2_voltage': None, 'pv2_current': None, 'pv2_power': None,
        'pv3_voltage': None, 'pv3_current': None, 'pv3_power': None,
        'pv4_voltage': None, 'pv4_current': None, 'pv4_power': None,
    }
    if latest and latest.raw_json:
        try:
            raw = json.loads(latest.raw_json)
            derived = raw.get('derived', {}) if isinstance(raw, dict) else {}

            if isinstance(derived, dict):
                # Battery details — now come from device/latest via derived dict
                if derived.get('batteryVoltage') is not None:
                    details['battery_voltage'] = derived['batteryVoltage']
                if derived.get('batteryCurrent') is not None:
                    details['battery_current'] = derived['batteryCurrent']
                if derived.get('batteryTemp') is not None:
                    details['battery_temp'] = derived['batteryTemp']
                if derived.get('batteryCapacityAh') is not None:
                    details['battery_total_capacity_ah'] = derived['batteryCapacityAh']
                if derived.get('batteryType'):
                    details['battery_type'] = derived['batteryType']
                # Inverter temperatures
                if derived.get('acTemperature') is not None:
                    details['inverter_temp'] = derived['acTemperature']
                if derived.get('dcTemperature') is not None:
                    details['dc_temp'] = derived['dcTemperature']
                # Grid
                if derived.get('acVoltage') is not None:
                    details['grid_voltage_l1'] = derived['acVoltage']
                if derived.get('acFrequency') is not None:
                    details['grid_frequency'] = derived['acFrequency']
                if derived.get('acCurrent') is not None:
                    details['grid_current_l1'] = derived['acCurrent']
                # PV strings
                for k in ['dcPowerPv1', 'dcPowerPv2', 'dcPowerPv3',
                           'dcVoltagePv1', 'dcVoltagePv2',
                           'dcCurrentPv1', 'dcCurrentPv2']:
                    if derived.get(k) is not None:
                        # map to details keys
                        mapped = k.replace('dcPower', 'pv').replace('dcVoltage', 'pv').replace('dcCurrent', 'pv')
                        mapped = mapped.replace('Pv1', '1_power' if 'Power' in k else ('1_voltage' if 'Voltage' in k else '1_current'))
                        mapped = mapped.replace('Pv2', '2_power' if 'Power' in k else ('2_voltage' if 'Voltage' in k else '2_current'))
                        mapped = mapped.replace('Pv3', '3_power')
                        # simpler direct mapping
                        key_map = {
                            'dcPowerPv1': 'pv1_power', 'dcPowerPv2': 'pv2_power', 'dcPowerPv3': 'pv3_power',
                            'dcVoltagePv1': 'pv1_voltage', 'dcVoltagePv2': 'pv2_voltage',
                            'dcCurrentPv1': 'pv1_current', 'dcCurrentPv2': 'pv2_current',
                        }
                        details[key_map[k]] = derived[k]
                # Energy counters + extra device fields
                for k in ['dailyChargingEnergy', 'dailyDischargingEnergy',
                          'totalChargingEnergy', 'totalDischargingEnergy',
                          'dailyConsumption', 'cumulativeConsumption']:
                    if derived.get(k) is not None:
                        details[k] = derived[k]
                # Pull extra fields from device_data directly
                _dd = raw.get('device_data') or {}
                for k in ['ratedPower', 'powerFactor', 'loadVoltageL1l2',
                          'totalProductiongenerator', 'dailyProductiongenerator',
                          'cumulativeEnergyPurchased', 'cumulativeConsumption',
                          'chargeCurrentLimit', 'dischargeCurrentLimit',
                          'bmsChargeVoltage', 'bmsDischargeVoltage']:
                    v = _dd.get(k)
                    if v is not None:
                        try: details[k] = float(v)
                        except: details[k] = v
                # SNs and status
                details['battery_sn_main']   = derived.get('batterySnMain')   or details['battery_sn_main']
                details['battery_sn_module']  = derived.get('batterySnModule') or details['battery_sn_module']
                bat_status_api = str(derived.get('batteryStatus') or '').lower()
                if 'discharg' in bat_status_api:
                    details['battery_status'] = 'يتم التفريغ'
                elif 'charg' in bat_status_api:
                    details['battery_status'] = 'يتم الشحن'
                elif safe_power_w(derived.get('dischargePower'), 0) > 0:
                    details['battery_status'] = 'يتم التفريغ'
                elif safe_power_w(derived.get('chargePower'), 0) > 0:
                    details['battery_status'] = 'يتم الشحن'

        except Exception:
            pass

    cfg = current_app.config
    _fill = {
        'battery_voltage': ('BATTERY_KNOWN_VOLTAGE', float),
        'battery_current': ('BATTERY_KNOWN_CURRENT', float),
        'battery_health': ('BATTERY_KNOWN_HEALTH', float),
        'battery_total_capacity_ah': ('BATTERY_KNOWN_CAPACITY_AH', float),
        'battery_cycles': ('BATTERY_KNOWN_CYCLES', int),
        'battery_temp': ('BATTERY_KNOWN_TEMPERATURE', float),
    }
    for key, (cfg_key, cast) in _fill.items():
        if details.get(key) in (None, '', 'غير متاح'):
            raw_val = cfg.get(cfg_key, '')
            if raw_val not in ('', None):
                try:
                    details[key] = cast(raw_val)
                except Exception:
                    details[key] = raw_val

    if details['battery_soh'] in (None, '', 'غير متاح') and details['battery_health'] not in (None, '', 'غير متاح'):
        details['battery_soh'] = details['battery_health']

    # Sanitise battery_status (sometimes the API returns a number)
    status_value = details.get('battery_status')
    if isinstance(status_value, (int, float)) or (
        isinstance(status_value, str) and status_value.strip().replace('.', '', 1).isdigit()
    ):
        details['battery_status'] = None

    if not details.get('battery_status'):
        details['battery_status'] = 'ثابتة'
        if latest and latest.raw_json:
            try:
                raw = json.loads(latest.raw_json)
                derived = raw.get('derived', {}) if isinstance(raw, dict) else {}
                if safe_power_w(derived.get('dischargePower'), 0) > 0:
                    details['battery_status'] = 'يتم التفريغ'
                elif safe_power_w(derived.get('chargePower'), 0) > 0:
                    details['battery_status'] = 'يتم الشحن'
            except Exception:
                pass
    return details


# ── Power flow ────────────────────────────────────────────────────────────────

def build_flow(latest: Reading | None) -> dict:
    empty = {'solar_to_home': 0.0, 'solar_to_battery': 0.0, 'battery_to_home': 0.0, 'grid_to_home': 0.0, 'home_to_grid': 0.0}
    if not latest:
        return empty
    solar = max(float(latest.solar_power or 0), 0)
    home = max(float(latest.home_load or 0), 0)
    charge_power = discharge_power = purchase_power = feed_in_power = 0.0
    if latest.raw_json:
        try:
            raw = json.loads(latest.raw_json)
            derived = raw.get('derived', {}) if isinstance(raw, dict) else {}
            charge_power = abs(safe_power_w(derived.get('chargePower'), 0.0))
            discharge_power = abs(safe_power_w(derived.get('dischargePower'), 0.0))
            purchase_power = abs(safe_power_w(derived.get('purchasePower'), 0.0))
            feed_in_power = abs(safe_power_w(derived.get('feedInPower'), 0.0))
        except Exception:
            pass
    return {
        'solar_to_home': round(min(solar, home), 1),
        'solar_to_battery': round(max(charge_power, 0.0), 1),
        'battery_to_home': round(max(discharge_power, 0.0), 1),
        'grid_to_home': round(max(purchase_power, 0.0), 1),
        'home_to_grid': round(max(feed_in_power, 0.0), 1),
    }


def build_system_status(latest: Reading | None, battery: dict | None = None) -> dict:
    if not latest:
        return {'title': 'لا توجد بيانات', 'description': 'نفّذ مزامنة أولًا لعرض الحالة.', 'tone': 'muted'}
    battery = battery or {}
    mode = battery.get('mode_label', 'ثابتة')
    solar = max(float(latest.solar_power or 0), 0)
    home = max(float(latest.home_load or 0), 0)
    soc = max(min(float(latest.battery_soc or 0), 100), 0)
    grid = float(latest.grid_power or 0)

    if mode == 'يتم الشحن' and solar >= home:
        return {'title': 'يتم شحن البطارية', 'description': 'يتم الشحن والاستخدام المنزلي بشكل طبيعي.', 'tone': 'good'}
    if solar >= max(home * 0.85, 80) and soc >= 25:
        return {'title': 'يعمل بشكل طبيعي', 'description': 'الطاقة الشمسية تغطي أغلب الاستهلاك الحالي.', 'tone': 'good'}
    if mode == 'يتم التفريغ' and soc > 25 and solar < home:
        return {'title': 'يتم استخدام البطارية', 'description': 'البطارية تغذي البيت الآن لتغطية الفرق.', 'tone': 'info'}
    if solar < 120 and soc <= 25:
        return {'title': 'يعتمد على الكهرباء', 'description': 'يفضل تخفيف الأحمال حتى يرتفع الشحن.', 'tone': 'warn'}
    if solar < home:
        return {'title': 'إنتاج شمسي ضعيف', 'description': 'الاستهلاك الحالي أعلى من دخل الشمس.', 'tone': 'warn'}
    if grid > 0:
        return {'title': 'يوجد ضخ للشبكة', 'description': 'الإنتاج أعلى من الاستهلاك الحالي.', 'tone': 'good'}
    return {'title': 'تشغيل مستقر', 'description': 'النظام يعمل بحالة مستقرة الآن.', 'tone': 'muted'}


def build_system_state(latest: Reading | None, battery: dict | None = None) -> str:
    return build_system_status(latest, battery).get('title', 'لا توجد بيانات')


# ── Formatting ────────────────────────────────────────────────────────────────

def format_power(value) -> str:
    try:
        return f"{float(value):,.1f}"
    except Exception:
        return '0.0'


def format_energy(value) -> str:
    try:
        value = float(value)
    except Exception:
        return '0.00 kWh'
    if value >= 1000:
        return f"{value / 1000:.2f} MWh"
    return f"{value:,.2f} kWh"


def format_time_short(dt, tz_name: str) -> str:
    local = utc_to_local(dt, tz_name)
    return (local.strftime('%I:%M %p').replace('AM', 'ص').replace('PM', 'م')) if local else '--:--'


def _to_12h_label(label: str | None) -> str:
    if not label:
        return '--'
    try:
        dt = datetime.strptime(label, '%H:%M')
        return dt.strftime('%I:%M %p').replace('AM', 'صباحًا').replace('PM', 'مساءً')
    except Exception:
        return label


def battery_percent_bar(percent) -> str:
    try:
        p = max(min(float(percent or 0), 100), 0)
    except Exception:
        p = 0
    filled = int(round(p / 10))
    return '[' + ('█' * filled) + ('░' * (10 - filled)) + f'] {int(round(p))}%'


# ── Statistics helpers ────────────────────────────────────────────────────────

def energy_parts_from_reading(reading: Reading | None) -> dict:
    if not reading:
        return {'solar_to_home_w': 0.0, 'solar_to_battery_w': 0.0, 'battery_to_home_w': 0.0, 'grid_to_home_w': 0.0}
    flow = build_flow(reading)
    return {
        'solar_to_home_w': float(flow['solar_to_home']),
        'solar_to_battery_w': float(flow['solar_to_battery']),
        'battery_to_home_w': float(flow['battery_to_home']),
        'grid_to_home_w': float(flow['grid_to_home']),
    }


def compute_energy_stats(readings: list) -> dict:
    empty = {
        'samples': 0, 'solar_generated_kwh': 0.0, 'home_consumed_kwh': 0.0,
        'solar_to_home_kwh': 0.0, 'solar_to_battery_kwh': 0.0,
        'battery_to_home_kwh': 0.0, 'grid_to_home_kwh': 0.0,
        'avg_battery_soc': 0.0, 'max_solar_w': 0.0,
        'data_gaps': 0,
    }
    if not readings:
        return empty
    totals = {k: 0.0 for k in ['solar_generated_kwh', 'home_consumed_kwh', 'solar_to_home_kwh', 'solar_to_battery_kwh', 'battery_to_home_kwh', 'grid_to_home_kwh']}
    soc_sum = 0.0
    max_solar = 0.0
    data_gaps = 0
    ordered = sorted(readings, key=lambda r: r.created_at)
    for i, row in enumerate(ordered):
        soc_sum += float(row.battery_soc or 0)
        max_solar = max(max_solar, float(row.solar_power or 0))
        if i == 0:
            continue
        prev = ordered[i - 1]
        dt_hours = max((row.created_at - prev.created_at).total_seconds() / 3600.0, 0)
        if dt_hours <= 0:
            continue
        if dt_hours > 1:
            data_gaps += 1
            continue
        parts = energy_parts_from_reading(prev)
        totals['solar_generated_kwh'] += max(float(prev.solar_power or 0), 0) * dt_hours / 1000
        totals['home_consumed_kwh'] += max(float(prev.home_load or 0), 0) * dt_hours / 1000
        totals['solar_to_home_kwh'] += parts['solar_to_home_w'] * dt_hours / 1000
        totals['solar_to_battery_kwh'] += parts['solar_to_battery_w'] * dt_hours / 1000
        totals['battery_to_home_kwh'] += parts['battery_to_home_w'] * dt_hours / 1000
        totals['grid_to_home_kwh'] += parts['grid_to_home_w'] * dt_hours / 1000
    return {
        'samples': len(readings),
        'data_gaps': data_gaps,
        **{k: round(v, 2) for k, v in totals.items()},
        'avg_battery_soc': round(soc_sum / len(readings), 1),
        'max_solar_w': round(max_solar, 1),
    }


def build_period_chart(readings: list, tz_name: str, mode: str) -> dict:
    buckets: dict = {}
    ordered = sorted(readings, key=lambda r: r.created_at)
    if mode == 'day':
        grouped: dict = {}
        for row in ordered:
            local = utc_to_local(row.created_at, tz_name)
            if not local:
                continue
            grouped.setdefault(local.strftime('%H:00'), []).append(row)
        for key, rows in grouped.items():
            buckets[key] = {
                'solar': round(sum(max(float(r.solar_power or 0), 0) for r in rows) / len(rows), 1),
                'home': round(sum(max(float(r.home_load or 0), 0) for r in rows) / len(rows), 1),
                'battery': round(sum(float(r.battery_power or 0) for r in rows) / len(rows), 1),
                'grid': round(sum(float(r.grid_power or 0) for r in rows) / len(rows), 1),
                'soc': round(sum(float(r.battery_soc or 0) for r in rows) / len(rows), 1),
            }
    else:
        grouped: dict = {}
        for row in ordered:
            local = utc_to_local(row.created_at, tz_name)
            if not local:
                continue
            grouped.setdefault(local.strftime('%m/%d'), []).append(row)
        for key, rows in grouped.items():
            stats = compute_energy_stats(rows)
            buckets[key] = {
                'solar': stats['solar_generated_kwh'], 'home': stats['home_consumed_kwh'],
                'battery': stats['battery_to_home_kwh'], 'grid': stats['grid_to_home_kwh'],
                'soc': stats['avg_battery_soc'],
            }
    labels = list(buckets.keys())
    return {
        'labels': labels,
        'solar': [round(v['solar'], 2) for v in buckets.values()],
        'home': [round(v['home'], 2) for v in buckets.values()],
        'battery': [round(v['battery'], 2) for v in buckets.values()],
        'grid': [round(v['grid'], 2) for v in buckets.values()],
        'soc': [round(v['soc'], 2) for v in buckets.values()],
    }


def build_summary_chart(table_rows: list) -> dict:
    return {
        'labels': [r['label'] for r in table_rows],
        'solar': [r['solar_generated_kwh'] for r in table_rows],
        'home': [r['home_consumed_kwh'] for r in table_rows],
        'battery': [r['battery_to_home_kwh'] for r in table_rows],
        'grid': [r['grid_to_home_kwh'] for r in table_rows],
    }


def build_statistics_table(rows: list, tz_name: str, selected_view: str) -> list:
    groups: dict = {}
    for row in sorted(rows, key=lambda r: r.created_at):
        local = utc_to_local(row.created_at, tz_name)
        if not local:
            continue
        key = local.strftime('%H:00') if selected_view == 'day' else local.strftime('%Y-%m-%d')
        groups.setdefault(key, []).append(row)
    return [{'label': key, **compute_energy_stats(group_rows)} for key, group_rows in groups.items()]


# ── Date/period helpers ───────────────────────────────────────────────────────

def same_local_day(dt: datetime, target_local: datetime, tz_name: str) -> bool:
    local = utc_to_local(dt, tz_name)
    return bool(local and local.date() == target_local.date())


def same_local_month(dt: datetime, target_local: datetime, tz_name: str) -> bool:
    local = utc_to_local(dt, tz_name)
    return bool(local and local.year == target_local.year and local.month == target_local.month)


def parse_selected_date(raw_value: str | None, tz_name: str) -> datetime:
    if raw_value:
        try:
            parsed = datetime.strptime(raw_value, '%Y-%m-%d')
            return utc_to_local(parsed, tz_name) or parsed.replace(tzinfo=UTC)
        except Exception:
            pass
    return utc_to_local(datetime.now(UTC), tz_name) or datetime.now(UTC)


def normalize_local_date(value: datetime, tz_name: str) -> datetime:
    local = utc_to_local(value, tz_name) if value.tzinfo else value
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def filter_rows_for_view(rows: list, selected_view: str, selected_date: datetime, tz_name: str):
    target = normalize_local_date(selected_date, tz_name)
    if selected_view == 'day':
        filtered = [r for r in rows if same_local_day(r.created_at, target, tz_name)]
        hint = f"يوم {target.strftime('%Y-%m-%d')}"
    elif selected_view == 'week':
        # Week starts Saturday (weekday 5 in Python where Mon=0)
        days_since_sat = (target.weekday() - 5) % 7
        start = target - timedelta(days=days_since_sat)
        end = start + timedelta(days=7)
        filtered = [r for r in rows if (lambda l: l and start <= l.replace(hour=0, minute=0, second=0, microsecond=0) < end)(utc_to_local(r.created_at, tz_name))]
        hint = f"أسبوع يبدأ من {start.strftime('%Y-%m-%d')}"
    else:
        filtered = [r for r in rows if same_local_month(r.created_at, target, tz_name)]
        hint = f"شهر {target.strftime('%Y-%m')}"
    return filtered, hint


def shift_period(selected_view: str, selected_date: datetime, delta: int) -> datetime:
    if selected_view == 'day':
        return selected_date + timedelta(days=delta)
    if selected_view == 'week':
        # Keep alignment to Saturday
        return selected_date + timedelta(days=7 * delta)
    year, month = selected_date.year, selected_date.month + delta
    while month < 1:
        month += 12; year -= 1
    while month > 12:
        month -= 12; year += 1
    return selected_date.replace(year=year, month=month, day=min(selected_date.day, 28))


def build_weather_insight(weather, battery_insights: dict | None = None) -> dict | None:
    if not weather:
        return None
    battery_insights = battery_insights or {}
    soc = float(battery_insights.get('stored_kwh', 0) or 0)
    cloud = float(getattr(weather, 'cloud_cover', 0) or 0)
    if cloud < 20:
        headline = 'أفضل وقت لتشغيل الأجهزة بين منتصف الصباح والظهر.'
    elif cloud < 50:
        headline = 'يفضل تشغيل الأحمال المتوسطة فقط حتى الظهر.'
    elif cloud < 80:
        headline = 'خفف الأحمال الثقيلة لأن الدخل الشمسي متذبذب.'
    else:
        headline = 'ينصح بتأجيل الأجهزة الثقيلة حتى ضمان شحن البطارية.'
    if cloud >= 50 and soc < 2:
        headline = 'الطقس غير مستقر والبطارية منخفضة، يفضل تأجيل أي حمل ثقيل.'
    return {'headline': headline, 'slots': getattr(weather, 'timeline', [])}


# ── Sunset prediction ─────────────────────────────────────────────────────────
# (imported lazily to avoid circular deps with weather_service)


def build_pre_sunset_prediction(latest, weather=None, settings=None):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    if not latest:
        return None
    settings = settings or load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    subtract_hour = str(settings.get('pre_sunset_subtract_hour', 'true')).lower() == 'true'
    try:
        now_local = datetime.now(ZoneInfo(current_app.config['LOCAL_TIMEZONE']))
    except Exception:
        now_local = datetime.now()

    sunset_label = effective_sunset_label = None
    sunrise_label = effective_sunrise_label = None
    remaining_hours = None
    hours_until_sunrise = None
    is_day = False

    if weather and getattr(weather, 'sunset_time', None):
        sunset_label = weather.sunset_time
        try:
            sunset_raw = datetime.fromisoformat(now_local.strftime('%Y-%m-%d') + 'T' + weather.sunset_time + ':00')
            if now_local.tzinfo is not None and sunset_raw.tzinfo is None:
                sunset_raw = sunset_raw.replace(tzinfo=now_local.tzinfo)
            effective_raw = sunset_raw - timedelta(hours=1 if subtract_hour else 0)
            effective_sunset_label = effective_raw.strftime('%H:%M')
            remaining_hours = max((effective_raw - now_local).total_seconds() / 3600, 0.0)
        except Exception:
            remaining_hours = None

    if weather and getattr(weather, 'sunrise_time', None):
        sunrise_label = weather.sunrise_time
        try:
            sunrise_raw = datetime.fromisoformat(now_local.strftime('%Y-%m-%d') + 'T' + weather.sunrise_time + ':00')
            if now_local.tzinfo is not None and sunrise_raw.tzinfo is None:
                sunrise_raw = sunrise_raw.replace(tzinfo=now_local.tzinfo)
            if now_local >= sunrise_raw:
                sunrise_raw = sunrise_raw + timedelta(days=1)
            effective_sunrise_raw = sunrise_raw
            effective_sunrise_label = effective_sunrise_raw.strftime('%H:%M')
            hours_until_sunrise = max((effective_sunrise_raw - now_local).total_seconds() / 3600, 0.0)
        except Exception:
            hours_until_sunrise = None

    if remaining_hours is None:
        fallback = now_local.replace(hour=18, minute=0, second=0, microsecond=0)
        effective = fallback - timedelta(hours=1 if subtract_hour else 0)
        if now_local > fallback:
            effective = effective + timedelta(days=1)
            fallback = fallback + timedelta(days=1)
        sunset_label = fallback.strftime('%H:%M')
        effective_sunset_label = effective.strftime('%H:%M')
        remaining_hours = max((effective - now_local).total_seconds() / 3600, 0.0)

    if hours_until_sunrise is None:
        sunrise_fallback = now_local.replace(hour=6, minute=0, second=0, microsecond=0)
        if now_local >= sunrise_fallback:
            sunrise_fallback = sunrise_fallback + timedelta(days=1)
        sunrise_label = sunrise_fallback.strftime('%H:%M')
        effective_sunrise_label = sunrise_fallback.strftime('%H:%M')
        hours_until_sunrise = max((sunrise_fallback - now_local).total_seconds() / 3600, 0.0)

    if weather and getattr(weather, 'sunrise_time', None) and getattr(weather, 'sunset_time', None):
        try:
            sunrise_check = datetime.fromisoformat(now_local.strftime('%Y-%m-%d') + 'T' + weather.sunrise_time + ':00')
            sunset_check = datetime.fromisoformat(now_local.strftime('%Y-%m-%d') + 'T' + weather.sunset_time + ':00')
            if now_local.tzinfo is not None:
                if sunrise_check.tzinfo is None:
                    sunrise_check = sunrise_check.replace(tzinfo=now_local.tzinfo)
                if sunset_check.tzinfo is None:
                    sunset_check = sunset_check.replace(tzinfo=now_local.tzinfo)
            is_day = sunrise_check <= now_local < sunset_check
        except Exception:
            is_day = bool((latest.solar_power or 0) > 50 and remaining_hours and remaining_hours > 0)
    else:
        is_day = bool((latest.solar_power or 0) > 50 and remaining_hours and remaining_hours > 0)

    charge_power_w = float(battery.get('charge_power_w', 0) or 0)
    discharge_power_w = float(battery.get('discharge_power_w', 0) or 0)
    soc = float(latest.battery_soc or 0)

    time_to_full_hours = None
    if charge_power_w > 0:
        time_to_full_hours = battery.get('remaining_to_full_kwh', 0) / (charge_power_w / 1000)

    will_full_before_sunset = bool(
        time_to_full_hours is not None and remaining_hours is not None and time_to_full_hours <= remaining_hours
    )
    remaining_label = 'الشمس غائبة' if (remaining_hours is not None and remaining_hours <= 0) else human_duration_hours(remaining_hours)
    sunrise_label_human = human_duration_hours(hours_until_sunrise) if hours_until_sunrise is not None else 'غير متاح'

    if not is_day:
        if hours_until_sunrise is not None and hours_until_sunrise <= 1.5:
            verdict, advice, level = 'قرب الشروق', 'المتبقي للشروق قصير نسبيًا، يمكن التفكير بأحمال خفيفة جدًا بحذر.', 'warning'
        else:
            verdict, advice, level = 'فترة ليلية', 'يعتمد القرار الآن على صمود البطارية حتى الشروق.', 'danger'
    elif soc >= 99:
        verdict, advice, level = 'البطارية ممتلئة', 'شحن مكتمل.', 'success'
    elif discharge_power_w > 0 and charge_power_w <= 0:
        verdict, advice, level = 'يتم السحب من البطارية ولا تشحن', 'يفضّل تخفيف الأحمال.', 'danger'
    elif charge_power_w <= 0:
        verdict, advice, level = 'لا يوجد شحن فعلي', 'راقب الإنتاج الشمسي.', 'warning'
    elif will_full_before_sunset:
        verdict, advice, level = 'سيتم شحن البطارية قبل الغروب', 'الوضع جيد.', 'success'
    else:
        verdict, advice, level = 'لن تكتمل البطارية قبل الغروب', 'يفضّل تقليل الاستهلاك.', 'warning'

    weather_advice = weather_level = None
    cond_text = str(getattr(weather, 'condition_ar', '') or '')
    try:
        cloud_val = float(getattr(weather, 'cloud_cover', None) or 0) if weather else 0
    except Exception:
        cloud_val = 0

    if 'ممطر' in cond_text:
        weather_advice, weather_level = 'اليوم ممطر، الإنتاج قد ينخفض.', 'danger'
    elif ('غائم' in cond_text and 'جزئي' not in cond_text) or cloud_val >= 85:
        weather_advice, weather_level = 'اليوم غائم بشكل كامل.', 'danger'
    elif 'غائم جزئي' in cond_text or cloud_val >= 40:
        weather_advice, weather_level = 'غائم جزئيًا، الدخل الشمسي قد يتذبذب.', 'warning'
    elif 'مشمس' in cond_text:
        weather_advice, weather_level = 'الطقس مشمس.', 'success'

    return {
        'sunset_time': sunset_label, 'effective_sunset_time': effective_sunset_label,
        'sunrise_time': sunrise_label, 'effective_sunrise_time': effective_sunrise_label,
        'remaining_hours': remaining_hours, 'remaining_label': remaining_label,
        'minutes_to_sunset': None if remaining_hours is None else round(remaining_hours * 60, 1),
        'hours_until_sunrise': hours_until_sunrise, 'sunrise_remaining_label': sunrise_label_human,
        'time_to_full_hours': time_to_full_hours, 'will_full_before_sunset': will_full_before_sunset,
        'verdict': verdict, 'advice': advice, 'level': level, 'is_day': bool(is_day),
        'weather_advice': weather_advice, 'weather_level': weather_level,
        'capacity_kwh': battery_capacity_kwh, 'reserve_percent': battery_reserve_percent,
        'charge_power_w': charge_power_w, 'discharge_power_w': discharge_power_w, 'soc': soc,
    }


# ── Local production summary (computed from stored readings) ──────────────────

def get_production_summary(tz_name: str) -> dict:
    """
    Compute energy totals from stored readings.
    Week starts on Saturday.
    Returns dict with: today_kwh, week_kwh, month_kwh, year_kwh, total_kwh, last_updated
    """
    from datetime import UTC, datetime
    from ..models import Reading

    now_local = utc_to_local(datetime.now(UTC), tz_name) or datetime.now(UTC)

    # Date boundaries in local time, then converted to naive UTC because DB stores UTC-naive values.
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_saturday = (today_start.weekday() - 5) % 7  # Monday=0 ... Saturday=5
    week_start = today_start - timedelta(days=days_since_saturday)
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    def _to_naive_utc(local_dt):
        """Convert local datetime to naive UTC for DB queries."""
        try:
            aware = local_dt.replace(tzinfo=ZoneInfo(tz_name))
            return aware.astimezone(UTC).replace(tzinfo=None)
        except Exception:
            return local_dt.replace(tzinfo=None)

    today_utc = _to_naive_utc(today_start)
    week_utc = _to_naive_utc(week_start)
    month_utc = _to_naive_utc(month_start)
    year_utc = _to_naive_utc(year_start)

    def _integrate_kwh(rows):
        total = 0.0
        for i in range(1, len(rows)):
            prev, curr = rows[i - 1], rows[i]
            dt_h = (curr.created_at - prev.created_at).total_seconds() / 3600.0
            if 0 < dt_h <= 1.5:  # ignore gaps > 1.5h
                total += max(float(prev.solar_power or 0), 0.0) * dt_h / 1000.0
        return round(total, 2)

    def _calc_kwh(start_utc):
        rows = (
            Reading.query
            .filter(Reading.created_at >= start_utc)
            .order_by(Reading.created_at.asc())
            .all()
        )
        return _integrate_kwh(rows), len(rows)

    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    api_daily = float(latest.daily_production or 0) if latest else 0.0
    api_monthly = float(latest.monthly_production or 0) if latest else 0.0
    api_total = float(latest.total_production or 0) if latest else 0.0

    today_kwh, today_count = _calc_kwh(today_utc)
    week_kwh, week_count = _calc_kwh(week_utc)
    month_kwh, month_count = _calc_kwh(month_utc)
    year_kwh, year_count = _calc_kwh(year_utc)

    final_today = api_daily if api_daily > 0 else today_kwh
    final_month = api_monthly if api_monthly > 0 else month_kwh
    total_kwh = api_total if api_total > 0 else year_kwh

    return {
        'today_kwh': round(final_today, 2),
        'week_kwh': round(week_kwh, 2),
        'month_kwh': round(final_month, 2),
        'year_kwh': round(year_kwh, 2),
        'total_kwh': round(total_kwh, 2),
        'today_count': today_count,
        'week_count': week_count,
        'month_count': month_count,
        'year_count': year_count,
        'week_starts_on': 'Saturday',
        'api_daily': api_daily,
        'api_monthly': api_monthly,
        'api_total': api_total,
        'source': 'api' if api_daily > 0 else 'calculated',
        'accumulating': api_daily == 0 and today_count <= 2,
        'last_updated': format_local_datetime(latest.created_at, tz_name) if latest else None,
    }
