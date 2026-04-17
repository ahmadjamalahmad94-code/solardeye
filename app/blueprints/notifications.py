"""Notification sending, rules, and processing logic."""
from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta

import requests
from flask import current_app, request, url_for

from ..extensions import db
from ..models import NotificationLog, Reading, Setting, UserLoad
from ..services.utils import format_local_datetime, human_duration_hours, safe_float, safe_power_w, utc_to_local
from .helpers import (
    battery_percent_bar, build_battery_insights, build_pre_sunset_prediction,
    build_system_state, compute_actual_solar_surplus, format_energy, format_power, get_runtime_battery_settings,
    load_settings, _to_12h_label, _upsert_setting,
)
from ..services.weather_service import fetch_weather
from .smart_engine import build_smart_energy_advice


# ── Notification rules ────────────────────────────────────────────────────────

def default_notification_rules() -> dict:
    charge = {str(level): 'telegram' for level in range(10, 101, 10)}
    discharge = {str(level): 'telegram' for level in range(95, 4, -5)}
    discharge.update({'20': 'both', '15': 'both', '10': 'both', '5': 'both'})
    return {
        'charge': charge,
        'discharge': discharge,
        'day_deficit': {'enabled': True, 'channel': 'telegram'},
        'night_thresholds': {'300': 'telegram', '400': 'both', '500': 'both'},
    }


def load_notification_rules(settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    rules = default_notification_rules()
    raw = settings.get('notification_rules_json', '')
    if raw:
        try:
            incoming = json.loads(raw)
            if isinstance(incoming, dict):
                for key, value in incoming.items():
                    if isinstance(value, dict) and isinstance(rules.get(key), dict):
                        rules[key].update(value)
                    else:
                        rules[key] = value
        except Exception:
            pass
    return rules


NOTIFICATION_SECTION_FIELDS = {
    'periodic_day': {
        'text': [
            'periodic_day_schedule_mode', 'periodic_day_interval_value', 'periodic_day_interval_unit',
            'periodic_day_specific_hours', 'periodic_day_time_start', 'periodic_day_time_end', 'periodic_day_channel',
        ],
        'checkbox': [
            'periodic_day_enabled', 'periodic_day_include_progress', 'periodic_day_include_summary',
            'periodic_day_include_device', 'periodic_day_include_weather', 'periodic_day_include_loads',
            'periodic_day_include_sunset',
        ],
    },
    'periodic_night': {
        'text': [
            'periodic_night_schedule_mode', 'periodic_night_interval_value', 'periodic_night_interval_unit',
            'periodic_night_specific_hours', 'periodic_night_time_start', 'periodic_night_time_end', 'periodic_night_channel',
        ],
        'checkbox': [
            'periodic_night_enabled', 'periodic_night_include_progress', 'periodic_night_include_summary',
            'periodic_night_include_device', 'periodic_night_include_loads', 'periodic_night_include_eta',
        ],
    },
    'sunset': {
        'text': [
            'pre_sunset_schedule_mode', 'pre_sunset_interval_minutes', 'pre_sunset_channel',
            'pre_sunset_specific_hours', 'pre_sunset_time_start', 'pre_sunset_time_end', 'charge_step_percent',
        ],
        'checkbox': [
            'pre_sunset_enabled', 'pre_sunset_include_soc', 'pre_sunset_include_charge_power',
            'pre_sunset_include_eta', 'pre_sunset_include_advice', 'pre_sunset_subtract_hour',
            'pre_sunset_only_if_not_full',
        ],
    },
    'discharge': {
        'text': [
            'night_discharge_schedule_mode', 'night_discharge_interval_value', 'night_discharge_interval_unit',
            'night_discharge_time_start', 'night_discharge_time_end', 'night_discharge_channel',
            'night_discharge_percent_step',
        ],
        'checkbox': [
            'night_discharge_enabled', 'night_discharge_include_device', 'night_discharge_include_energy',
        ],
    },
    'load': {
        'text': [
            'night_max_load_w', 'load_alert_schedule_mode', 'load_alert_interval_value', 'load_alert_interval_unit',
            'load_alert_specific_hours', 'load_alert_time_start', 'load_alert_time_end', 'load_alert_channel',
            'load_alert_max_items',
        ],
        'checkbox': [
            'load_alert_enabled', 'load_alert_include_allowed', 'load_alert_include_blocked',
        ],
    },
    'weather': {
        'text': [
            'weather_cloud_threshold', 'weather_test_schedule_mode', 'weather_test_interval_value',
            'weather_test_interval_unit', 'weather_test_time_start', 'weather_test_time_end', 'weather_test_channel',
        ],
        'checkbox': [
            'weather_test_enabled', 'weather_test_include_next_hour', 'weather_test_include_smart_tip',
        ],
    },
    'battery': {
        'text': [
            'battery_test_schedule_mode', 'battery_test_interval_value', 'battery_test_interval_unit',
            'battery_test_time_start', 'battery_test_time_end', 'battery_test_channel',
        ],
        'checkbox': [
            'battery_test_enabled', 'battery_test_include_day_summary', 'battery_test_include_sunset',
            'battery_test_include_loads',
        ],
    },
    'daily_report': {
        'text': ['daily_report_time', 'daily_report_channel'],
        'checkbox': ['daily_report_enabled', 'daily_report_include_totals', 'daily_report_include_yesterday', 'daily_report_include_device'],
    },
    'rules': {
        'text': ['charge_step_percent', 'night_discharge_percent_step', 'day_deficit_channel'],
        'checkbox': ['day_deficit_enabled'],
        'special': 'rules',
    },
}

ALL_NOTIFICATION_TEXT_FIELDS = [
    'daytime_solar_min_w', 'weather_cloud_threshold', 'battery_reserve_percent',
    'periodic_status_interval_minutes', 'periodic_status_channel',
    'weather_daily_summary_channel', 'weather_change_alerts_channel',
    'pre_sunset_interval_minutes', 'pre_sunset_channel',
    'night_max_load_w',
    'periodic_day_interval_value', 'periodic_day_interval_unit', 'periodic_day_schedule_mode', 'periodic_day_specific_hours', 'periodic_day_time_start', 'periodic_day_time_end', 'periodic_day_channel',
    'periodic_night_interval_value', 'periodic_night_interval_unit', 'periodic_night_schedule_mode', 'periodic_night_specific_hours', 'periodic_night_time_start', 'periodic_night_time_end', 'periodic_night_channel',
    'pre_sunset_schedule_mode', 'pre_sunset_specific_hours', 'pre_sunset_time_start', 'pre_sunset_time_end',
    'night_discharge_schedule_mode', 'night_discharge_interval_value', 'night_discharge_interval_unit', 'night_discharge_time_start', 'night_discharge_time_end', 'night_discharge_channel', 'night_discharge_percent_step',
    'load_alert_schedule_mode', 'load_alert_interval_value', 'load_alert_interval_unit', 'load_alert_specific_hours', 'load_alert_time_start', 'load_alert_time_end', 'load_alert_channel', 'load_alert_max_items',
    'weather_test_schedule_mode', 'weather_test_interval_value', 'weather_test_interval_unit', 'weather_test_time_start', 'weather_test_time_end', 'weather_test_channel',
    'battery_test_schedule_mode', 'battery_test_interval_value', 'battery_test_interval_unit', 'battery_test_time_start', 'battery_test_time_end', 'battery_test_channel',
    'daily_report_time', 'daily_report_channel', 'charge_step_percent',
]

SECTION_LAST_SENT_KEYS = {
    'periodic_day': ['periodic_day_last_sent_at'],
    'periodic_night': ['periodic_night_last_sent_at'],
    'sunset': ['pre_sunset_last_sent_at'],
    'discharge': ['night_discharge_last_sent_at'],
    'load': ['load_alert_last_sent_at'],
    'weather': ['weather_test_last_sent_at'],
    'battery': ['battery_test_last_sent_at'],
    'daily_report': ['daily_report_last_sent_at'],
}

ALL_NOTIFICATION_CHECKBOX_FIELDS = [
    'notifications_enabled', 'weather_enabled', 'weather_daily_summary_enabled',
    'weather_change_alerts_enabled', 'periodic_status_enabled',
    'periodic_status_include_weather', 'pre_sunset_enabled',
    'pre_sunset_subtract_hour', 'pre_sunset_only_if_not_full',
    'periodic_day_enabled', 'periodic_day_include_progress', 'periodic_day_include_summary', 'periodic_day_include_device', 'periodic_day_include_weather', 'periodic_day_include_loads', 'periodic_day_include_sunset',
    'periodic_night_enabled', 'periodic_night_include_progress', 'periodic_night_include_summary', 'periodic_night_include_device', 'periodic_night_include_loads', 'periodic_night_include_eta',
    'pre_sunset_include_soc', 'pre_sunset_include_charge_power', 'pre_sunset_include_eta', 'pre_sunset_include_advice',
    'night_discharge_enabled', 'night_discharge_include_device', 'night_discharge_include_energy',
    'load_alert_enabled', 'load_alert_include_allowed', 'load_alert_include_blocked',
    'weather_test_enabled', 'weather_test_include_next_hour', 'weather_test_include_smart_tip',
    'battery_test_enabled', 'battery_test_include_day_summary', 'battery_test_include_sunset', 'battery_test_include_loads',
    'daily_report_enabled', 'daily_report_include_totals', 'daily_report_include_yesterday', 'daily_report_include_device',
]


def _save_notification_rules_from_form(form):
    rules: dict = {'charge': {}, 'discharge': {}, 'day_deficit': {}, 'night_thresholds': {}}
    charge_step = max(int(safe_float(form.get('charge_step_percent'), 10) or 10), 1)
    discharge_step = max(int(safe_float(form.get('night_discharge_percent_step'), 5) or 5), 1)
    for level in range(charge_step, 101, charge_step):
        rules['charge'][str(level)] = form.get(f'charge_{level}', 'none')
    for level in range(100 - discharge_step, 0, -discharge_step):
        rules['discharge'][str(level)] = form.get(f'discharge_{level}', 'none')
    rules['day_deficit'] = {
        'enabled': form.get('day_deficit_enabled') == 'on',
        'channel': form.get('day_deficit_channel', 'telegram'),
    }
    for level in [300, 400, 500]:
        rules['night_thresholds'][str(level)] = form.get(f'night_{level}', 'none')
    _upsert_setting('notification_rules_json', json.dumps(rules, ensure_ascii=False))


def save_notification_settings_from_form(form, section: str | None = None):
    section = (section or '').strip().lower()
    if section and section in NOTIFICATION_SECTION_FIELDS:
        config = NOTIFICATION_SECTION_FIELDS[section]
        text_fields = config.get('text', [])
        checkbox_fields = config.get('checkbox', [])
    else:
        text_fields = ALL_NOTIFICATION_TEXT_FIELDS
        checkbox_fields = ALL_NOTIFICATION_CHECKBOX_FIELDS

    for field in text_fields:
        _upsert_setting(field, (form.get(field, '') or '').strip())

    for key in checkbox_fields:
        _upsert_setting(key, 'true' if form.get(key) == 'on' else 'false')

    if (section == 'rules') or (not section):
        _save_notification_rules_from_form(form)

    for key in SECTION_LAST_SENT_KEYS.get(section, []):
        _upsert_setting(key, '')

    db.session.commit()


CHECKBOX_SETTING_KEYS = [
    'notifications_enabled', 'weather_enabled', 'weather_daily_summary_enabled',
    'weather_change_alerts_enabled', 'periodic_status_enabled',
    'periodic_status_include_weather', 'pre_sunset_enabled',
    'pre_sunset_subtract_hour', 'pre_sunset_only_if_not_full',
    'periodic_day_enabled', 'periodic_day_include_progress', 'periodic_day_include_summary', 'periodic_day_include_device', 'periodic_day_include_weather', 'periodic_day_include_loads', 'periodic_day_include_sunset',
    'periodic_night_enabled', 'periodic_night_include_progress', 'periodic_night_include_summary', 'periodic_night_include_device', 'periodic_night_include_loads', 'periodic_night_include_eta',
    'pre_sunset_include_soc', 'pre_sunset_include_charge_power', 'pre_sunset_include_eta', 'pre_sunset_include_advice',
    'night_discharge_enabled', 'night_discharge_include_device', 'night_discharge_include_energy',
    'load_alert_enabled', 'load_alert_include_allowed', 'load_alert_include_blocked',
    'weather_test_enabled', 'weather_test_include_next_hour', 'weather_test_include_smart_tip',
    'battery_test_enabled', 'battery_test_include_day_summary', 'battery_test_include_sunset', 'battery_test_include_loads',
    'daily_report_enabled', 'daily_report_include_totals', 'daily_report_include_yesterday', 'daily_report_include_device',
]


def apply_form_settings_overrides(base_settings: dict, form) -> dict:
    effective = dict(base_settings or {})
    if not form:
        return effective
    for key in form.keys():
        values = form.getlist(key)
        if key in CHECKBOX_SETTING_KEYS:
            effective[key] = 'true' if (form.get(key) == 'on' or 'on' in values) else 'false'
        else:
            effective[key] = form.get(key, '')
    for key in CHECKBOX_SETTING_KEYS:
        if key in form or any(k == key for k in form.keys()):
            effective[key] = 'true' if form.get(key) == 'on' else 'false'
    return effective


def _flag(settings: dict | None, key: str, default: bool = True) -> bool:
    if settings is None:
        return default
    value = settings.get(key)
    if value is None or value == '':
        return default
    return str(value).lower() == 'true'


def _normalize_telegram_text(value: str | None) -> str:
    text = str(value or '')
    text = text.replace('\r\n', '\n').replace('\\n', '\n').replace('\\t', '\t')
    return text.strip()


# ── Sending ───────────────────────────────────────────────────────────────────

def send_telegram_message(settings: dict, title: str, message: str):
    token = (settings.get('telegram_bot_token') or '').strip()
    chat_id = (settings.get('telegram_chat_id') or '').strip()
    base = (settings.get('telegram_api_url') or 'https://api.telegram.org').rstrip('/')
    if not token or not chat_id:
        return False, 'بيانات Telegram غير مكتملة'
    url = f"{base}/bot{token}/sendMessage"
    clean_title = _normalize_telegram_text(title)
    clean_message = _normalize_telegram_text(message)
    payload = {
        'chat_id': chat_id,
        'text': f"*{clean_title}*\n\n{clean_message}",
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True,
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        ok = r.ok and r.json().get('ok', True)
        return ok, r.text[:500]
    except Exception as exc:
        return False, str(exc)


def send_sms_message(settings: dict, title: str, message: str):
    api_url = (settings.get('sms_api_url') or '').strip()
    api_key = (settings.get('sms_api_key') or '').strip()
    sender = (settings.get('sms_sender') or '').strip()
    recipients = [x.strip() for x in (settings.get('sms_recipients') or '').replace(';', ',').split(',') if x.strip()]
    if not api_url or not recipients:
        return False, 'بيانات SMS غير مكتملة'
    try:
        r = requests.post(api_url, json={'api_key': api_key, 'sender': sender, 'to': recipients, 'message': f"{title} - {message}"}, timeout=20)
        return r.ok, r.text[:500]
    except Exception as exc:
        return False, str(exc)


def notification_exists(event_key: str, minutes: int = 1440) -> bool:
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes)
    return NotificationLog.query.filter(
        NotificationLog.event_key == event_key,
        NotificationLog.created_at >= since,
    ).first() is not None


def log_notification(event_key, rule_name, title, message, channel, level, response_text='', force=False):
    if not force and notification_exists(event_key):
        return False
    db.session.add(NotificationLog(
        event_key=event_key, rule_name=rule_name, title=title, message=message,
        channel=channel, level=level, response_text=response_text,
        status='sent' if level != 'danger' else 'failed',
    ))
    db.session.commit()
    return True


def dispatch_notification(settings, event_key, rule_name, title, message, channel_pref, level='info', dedupe_minutes=1440):
    channel_pref = (channel_pref or 'none').lower()
    if channel_pref in ('', 'none'):
        return
    if dedupe_minutes > 0 and notification_exists(event_key, dedupe_minutes):
        return
    for channel in (['telegram', 'sms'] if channel_pref == 'both' else [channel_pref]):
        if channel == 'telegram':
            ok, resp = send_telegram_message(settings, title, message)
        elif channel == 'sms':
            ok, resp = send_sms_message(settings, title, message)
        else:
            continue
        log_notification(event_key + ':' + channel, rule_name, title, message, channel, 'success' if ok else 'danger', resp, force=True)


# ── Threshold helpers ─────────────────────────────────────────────────────────

def crossed_up(prev_soc: float, current_soc: float, step: int) -> list:
    return [level for level in range(step, 101, step) if prev_soc < level <= current_soc]


def crossed_down(prev_soc: float, current_soc: float, step: int) -> list:
    return [level for level in range(step, 0, -step) if prev_soc > level >= current_soc]


# ── Message builders ──────────────────────────────────────────────────────────


def _parse_hhmm_local(value, now_local):
    try:
        hh, mm = [int(x) for x in str(value or '').split(':')[:2]]
        return now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None


def _weather_day_window(now_local, weather, start_hour=7):
    if not now_local:
        return False
    sunset_dt = _parse_hhmm_local(getattr(weather, 'sunset_time', None), now_local) if weather else None
    day_start = now_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if sunset_dt is None:
        return now_local >= day_start and now_local.hour < 18
    return day_start <= now_local < sunset_dt


def _night_weather_label(now_local, weather):
    temp = getattr(weather, 'temperature', None)
    return f"🌙 ليلًا الآن • {temp if temp is not None else '--'}°"


def _short_weather_line(now_local, weather):
    if not weather:
        return None
    if not _weather_day_window(now_local, weather, start_hour=7):
        return _night_weather_label(now_local, weather)
    temp = weather.temperature if weather.temperature is not None else '--'
    cloud = weather.cloud_cover if weather.cloud_cover is not None else '--'
    return f"{weather.icon} {weather.condition_ar} • {temp}° • غيوم {cloud}%"


def _telegram_api_call(settings: dict, method: str, payload: dict):
    token = (settings.get('telegram_bot_token') or '').strip()
    base = (settings.get('telegram_api_url') or 'https://api.telegram.org').rstrip('/')
    if not token:
        return False, 'بيانات Telegram غير مكتملة', {}
    url = f"{base}/bot{token}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=20)
        data = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
        return bool(r.ok and data.get('ok', True)), r.text[:500], data
    except Exception as exc:
        return False, str(exc), {}


def _telegram_menu_markup(settings: dict | None = None):
    settings = settings or load_settings()
    rows = []

    def on(key: str, default: bool = True):
        raw = str(settings.get(key, 'true' if default else 'false')).strip().lower()
        return raw != 'false'

    row1 = []
    if on('tg_btn_status'):
        row1.append({'text': '📊 الحالة', 'callback_data': 'tg:status'})
    if on('tg_btn_loads'):
        row1.append({'text': '⚡ الأحمال', 'callback_data': 'tg:loads'})
    if row1:
        rows.append(row1)

    row2 = []
    if on('tg_btn_weather'):
        row2.append({'text': '🌤️ الطقس', 'callback_data': 'tg:weather'})
    if on('tg_btn_clouds'):
        row2.append({'text': '☁️ الغيوم', 'callback_data': 'tg:clouds'})
    if row2:
        rows.append(row2)

    row3 = []
    if on('tg_btn_battery_eta'):
        row3.append({'text': '🔋 وقت الشحن / النفاذ', 'callback_data': 'tg:battery_eta'})
    if on('tg_btn_surplus'):
        row3.append({'text': '☀️ الفائض الشمسي', 'callback_data': 'tg:surplus'})
    if row3:
        rows.append(row3)

    row4 = []
    if on('tg_btn_decision'):
        row4.append({'text': '🎯 القرار الآن', 'callback_data': 'tg:decision'})
    if on('tg_btn_smart'):
        row4.append({'text': '💡 النصيحة الذكية', 'callback_data': 'tg:smart'})
    if row4:
        rows.append(row4)

    row5 = []
    if on('tg_btn_sunset'):
        row5.append({'text': '🌇 قبل الغروب', 'callback_data': 'tg:sunset'})
    if on('tg_btn_night_risk'):
        row5.append({'text': '🌙 خطر الليلة', 'callback_data': 'tg:night_risk'})
    if row5:
        rows.append(row5)

    row6 = []
    if on('tg_btn_last_sync'):
        row6.append({'text': '🔄 آخر مزامنة', 'callback_data': 'tg:last_sync'})
    row6.append({'text': '📋 القائمة', 'callback_data': 'tg:menu'})
    rows.append(row6)

    return {'inline_keyboard': rows}


def send_telegram_menu(settings: dict, chat_id: str | None = None, intro: str | None = None):
    chat_id = (chat_id or settings.get('telegram_chat_id') or '').strip()
    if not chat_id:
        return False, 'معرّف المحادثة غير موجود'
    text = intro or 'اختر ما تريد فحصه الآن من الأزرار التالية:'
    ok, resp, _ = _telegram_api_call(settings, 'sendMessage', {
        'chat_id': chat_id,
        'text': text,
        'reply_markup': _telegram_menu_markup(settings),
    })
    return ok, resp


def _format_periodic_preview(latest, weather=None):
    title, message = build_periodic_status_message(latest, weather)
    return f"{title}\n\n{message}"


def _format_weather_check(latest, weather=None, settings=None):
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    if not weather:
        return '🌤️ لا توجد بيانات طقس متاحة حاليًا.'
    if not _weather_day_window(now_local, weather, start_hour=7):
        return _night_weather_label(now_local, weather)
    next_hour = weather.next_hour if hasattr(weather, 'next_hour') else {}
    lines = [f"{weather.icon} {weather.condition_ar} • {weather.temperature if weather.temperature is not None else '--'}°"]
    if _flag(settings, 'weather_test_include_next_hour', True):
        lines.append(f"🕒 خلال ساعة: {(next_hour or {}).get('condition_ar', 'غير متاح')}")
    if _flag(settings, 'weather_test_include_smart_tip', True):
        lines.append('💡 نصيحة ذكية: الساعات القادمة مناسبة للإنتاج حتى الغروب.' if _weather_day_window(now_local, weather, start_hour=6) else '💡 لا حاجة لتنبيه الطقس خارج فترة النهار.')
    return "\n".join(lines)


def _format_cloud_check(weather=None):
    if not weather:
        return '☁️ لا توجد بيانات غيوم متاحة حاليًا.'
    cloud = weather.cloud_cover if weather.cloud_cover is not None else '--'
    next_cloud = (weather.next_hour or {}).get('cloud_cover', '--') if hasattr(weather, 'next_hour') else '--'
    return f"☁️ الغيوم الآن: {cloud}%\n🔜 الغيوم بعد ساعة: {next_cloud}%"


def _format_battery_eta(latest, settings=None):
    if not latest:
        return '🔋 لا توجد قراءة بطارية متاحة.'
    settings = settings or load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    mode = battery.get('mode_label', 'غير متاح')
    if mode == 'يتم الشحن':
        eta = battery.get('charge_eta', 'غير متاح')
        return f"🔋 البطارية تشحن الآن\n⏳ وقت الامتلاء: {eta}"
    if mode == 'يتم التفريغ':
        eta = battery.get('discharge_eta', 'غير متاح')
        return f"🌙 البطارية في وضع السحب\n⏳ وقت النفاد: {eta}"
    charge_eta = battery.get('charge_eta', 'غير متاح')
    discharge_eta = battery.get('discharge_eta', 'غير متاح')
    return "\n".join([
        f"🔋 حالة البطارية: {mode}",
        f"⏳ وقت الامتلاء: {charge_eta}",
        f"⏳ وقت النفاد: {discharge_eta}",
    ])


def _format_solar_surplus(latest, weather=None, settings=None):
    if not latest:
        return '☀️ لا توجد قراءة طاقة متاحة.'
    settings = settings or load_settings()
    surplus_data = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
    solar = max(float(latest.solar_power or 0), 0.0)
    home = max(float(latest.home_load or 0), 0.0)
    raw_surplus = float(surplus_data.get('raw_surplus_w', 0) or 0)
    battery_need = float(surplus_data.get('battery_charge_need_w', 0) or 0)
    actual_surplus = float(surplus_data.get('actual_surplus_w', 0) or 0)
    is_day = bool(surplus_data.get('is_day'))
    lines = [
        f"☀️ الإنتاج الآن: {format_power(solar)} واط",
        f"🏠 الحمل الحالي: {format_power(home)} واط",
    ]
    if is_day:
        lines += [
            f"⚡ الفائض الخام: {format_power(max(raw_surplus, 0))} واط" if raw_surplus >= 0 else f"⚠️ العجز الحالي: {format_power(abs(raw_surplus))} واط",
            f"🔋 احتياج الشحن قبل الغروب: {format_power(max(battery_need, 0))} واط",
            f"✅ الفائض الفعلي المتاح: {format_power(max(actual_surplus, 0))} واط",
        ]
    else:
        lines.append('🌙 ليلًا: لا يوجد فائض شمسي، ويعتمد القرار على البطارية والحد الليلي.')
    return "\n".join(lines)


def _format_load_suggestions_telegram(latest, settings=None):
    if not latest:
        return '⚡ لا توجد قراءة حديثة لاقتراح الأحمال.'
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    weather = None
    try:
        _, weather = _get_weather_for_latest()
    except Exception:
        weather = None
    loads = UserLoad.query.filter_by(is_enabled=True).order_by(UserLoad.priority.asc(), UserLoad.power_w.asc(), UserLoad.name.asc()).all()
    if not loads:
        return '⚡ لا توجد أحمال مضافة ومفعلة بعد.'
    sunset_dt = _parse_hhmm_local(getattr(weather, 'sunset_time', None), now_local) if weather else None
    is_day = bool(sunset_dt and now_local.replace(hour=9, minute=0, second=0, microsecond=0) <= now_local < sunset_dt)
    solar = max(float(latest.solar_power or 0), 0.0)
    home = max(float(latest.home_load or 0), 0.0)
    soc = float(latest.battery_soc or 0)
    battery_power = float(latest.battery_power or 0)
    if is_day:
        surplus_data = compute_actual_solar_surplus(latest, weather=weather, settings=(settings or load_settings()))
        available = max(float(surplus_data.get('actual_surplus_w', 0) or 0), 0.0)
        raw_surplus = max(float(surplus_data.get('raw_surplus_w', 0) or 0), 0.0)
        battery_need = max(float(surplus_data.get('battery_charge_need_w', 0) or 0), 0.0)
        mode = f"☀️ نهارًا: الفائض الفعلي {int(round(available))}W (خام {int(round(raw_surplus))}W • للبطارية {int(round(battery_need))}W)"
    else:
        night_cap = safe_float((settings or load_settings()).get('night_max_load_w') or load_settings().get('night_max_allowed_w', '500'), 500)
        available = max(night_cap - home, 0.0)
        mode = f'🌙 ليلًا: الحد المسموح {int(round(night_cap))}W'
    fit = [x for x in loads if float(x.power_w or 0) <= available + 1e-9]
    lines = [mode, f"🏠 الحمل الحالي: {int(round(home))}W", f"⚡ المتاح: {int(round(max(available,0)))}W"]
    if fit and _flag(settings, 'load_alert_include_allowed', True):
        lines += ['', 'يمكنك تشغيل الآن:']
        for row in fit[:6]:
            lines.append(f"✔ {row.name} — {int(round(float(row.power_w or 0)))}W")
    elif not fit:
        lines += ['', '⚠️ لا يوجد جهاز مناسب ضمن الهامش الحالي.']
    if _flag(settings, 'load_alert_include_blocked', True):
        blocked = [x for x in loads if float(x.power_w or 0) > available + 1e-9]
        if blocked:
            lines += ['', '⚠️ لا ينصح:']
            for row in blocked[:4]:
                lines.append(f"✖ {row.name} — {int(round(float(row.power_w or 0)))}W")
    return "\n".join(lines)


def _format_pre_sunset_telegram(latest, weather=None, settings=None):
    title, message, _level = build_pre_sunset_message(latest, weather, settings=settings)
    return f"{title}\n\n{message}"


def _format_night_risk_telegram(latest, weather=None, settings=None):
    settings = settings or load_settings()
    if not latest:
        return '🌙 لا توجد قراءة متاحة لتقييم الليلة.'
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    advice = build_smart_energy_advice(latest, weather=weather, settings=settings, context='periodic_night')
    lines = [
        '🌙 خطر الليلة',
        f"🔋 البطارية الآن: {round(float(latest.battery_soc or 0), 1)}%",
        f"📊 تقييم الحالة: {advice.get('status_label', '—')}",
    ]
    if battery.get('discharge_eta'):
        lines.append(f"⏳ وقت النفاد المتوقع: {battery.get('discharge_eta')}")
    if advice.get('smart_warning'):
        lines.append(f"⚠️ {advice.get('smart_warning')}")
    if advice.get('decision_now'):
        lines.append(f"🎯 {advice.get('decision_now')}")
    return "\n".join(lines)


def _format_last_sync_telegram(latest):
    if not latest:
        return '🔄 لا توجد أي مزامنة محفوظة حتى الآن.'
    return "\n".join([
        '🔄 آخر مزامنة',
        f"🕒 آخر تحديث: {format_local_datetime(latest.created_at, current_app.config['LOCAL_TIMEZONE'])}",
    ])


def _safe_decision_telegram(latest, weather=None, settings=None):
    try:
        advice = build_smart_energy_advice(latest, weather=weather, settings=settings, context='periodic_day')
        return "\\n".join([
            "🎯 القرار الآن",
            f"📊 تقييم الحالة: {advice.get('status_label', '—')}",
            f"🎯 {advice.get('decision_now', 'لا توجد توصية حالياً.')}",
        ])
    except Exception:
        return '🎯 تعذر توليد القرار الآن حاليًا.'

def _safe_smart_telegram(latest, weather=None, settings=None):
    try:
        advice = build_smart_energy_advice(latest, weather=weather, settings=settings, context='periodic_day')
        lines = [
            "💡 النصيحة الذكية",
            f"📊 تقييم الحالة: {advice.get('status_label', '—')}",
        ]
        if advice.get('smart_warning'):
            lines.append(f"⚠️ {advice.get('smart_warning')}")
        if advice.get('smart_recommendation'):
            lines.append(f"💡 {advice.get('smart_recommendation')}")
        lines.append(f"🎯 {advice.get('decision_now', 'لا توجد توصية حالياً.')}")
        return "\\n".join(lines)
    except Exception:
        return '💡 تعذر توليد النصيحة الذكية حاليًا.'

def _safe_night_risk_telegram(latest, weather=None, settings=None):
    try:
        return _format_night_risk_telegram(latest, weather=weather, settings=settings)
    except Exception:
        return '🌙 تعذر تقييم خطر الليلة حاليًا.'

def _safe_last_sync_telegram(latest):
    try:
        return _format_last_sync_telegram(latest)
    except Exception:
        return '🔄 تعذر قراءة وقت آخر مزامنة الآن.'

def build_telegram_quick_reply(action: str, latest=None, weather=None, settings=None):
    action = (action or '').strip().lower()
    if latest is None:
        latest, weather = _get_weather_for_latest()
    if action == 'status':
        title, message = build_periodic_status_message(latest, weather, settings=settings); return f'{title}\n\n{message}'
    if action == 'loads':
        return _format_load_suggestions_telegram(latest, settings=settings)
    if action == 'weather':
        return _format_weather_check(latest, weather, settings=settings)
    if action == 'clouds':
        return _format_cloud_check(weather)
    if action == 'battery_eta':
        return _format_battery_eta(latest, settings=settings)
    if action == 'surplus':
        return _format_solar_surplus(latest, weather=weather, settings=settings)
    if action == 'sunset':
        return _format_pre_sunset_telegram(latest, weather=weather, settings=settings)
    if action == 'night_risk':
        return _safe_night_risk_telegram(latest, weather=weather, settings=settings)
    if action == 'last_sync':
        return _safe_last_sync_telegram(latest)
    if action == 'decision':
        return _safe_decision_telegram(latest, weather=weather, settings=settings)
    if action == 'smart':
        return _safe_smart_telegram(latest, weather=weather, settings=settings)
    return 'اختر زرًا من القائمة لعرض البيانات.'


def process_telegram_update(settings: dict, update: dict):
    ok = True
    resp_text = 'ignored'
    callback = update.get('callback_query') or {}
    message = update.get('message') or callback.get('message') or {}
    chat = message.get('chat') or {}
    chat_id = str(chat.get('id') or '').strip()

    if callback:
        callback_id = callback.get('id')
        data = str(callback.get('data') or '')
        action = data.split(':', 1)[1] if ':' in data else data
        if callback_id:
            _telegram_api_call(settings, 'answerCallbackQuery', {'callback_query_id': callback_id, 'text': 'تم الاستلام ✅', 'show_alert': False})
        if action == 'menu':
            return send_telegram_menu(settings, chat_id=chat_id)
        text = _normalize_telegram_text(build_telegram_quick_reply(action, settings=settings))
        if not text or not str(text).strip():
            text = 'تعذر تجهيز الرد الآن.'
        ok, resp_text, _ = _telegram_api_call(settings, 'sendMessage', {
            'chat_id': chat_id or settings.get('telegram_chat_id'),
            'text': text,
            'reply_markup': _telegram_menu_markup(settings),
        })
        return ok, resp_text

    txt = str(message.get('text') or '').strip().lower()
    if not txt:
        return True, 'no-text'
    mapping = {
        '/start': 'menu', '/menu': 'menu', 'الحالة': 'status', '/status': 'status',
        'الاحمال': 'loads', 'الأحمال': 'loads', '/loads': 'loads',
        'الطقس': 'weather', '/weather': 'weather',
        'الغيوم': 'clouds', '/clouds': 'clouds',
        'الشحن': 'battery_eta', 'مدة الشحن': 'battery_eta', '/battery': 'battery_eta',
        'الفائض': 'surplus', 'الفائض الشمسي': 'surplus', '/surplus': 'surplus',
        'القرار الآن': 'decision', '/decision': 'decision', 'قرار': 'decision',
        'نصيحة': 'smart', 'النصيحة الذكية': 'smart', '/smart': 'smart',
        'قبل الغروب': 'sunset', '/sunset': 'sunset',
        'خطر الليلة': 'night_risk', '/night': 'night_risk',
        'آخر مزامنة': 'last_sync', '/sync': 'last_sync',
    }
    action = mapping.get(txt, 'menu')
    if action == 'menu':
        return send_telegram_menu(settings, chat_id=chat_id)
    text = _normalize_telegram_text(build_telegram_quick_reply(action, settings=settings))
    ok, resp_text, _ = _telegram_api_call(settings, 'sendMessage', {
        'chat_id': chat_id or settings.get('telegram_chat_id'),
        'text': text,
        'reply_markup': _telegram_menu_markup(settings),
    })
    return ok, resp_text


def _periodic_load_suggestion(latest, phase_override=None, settings=None):
    loads = UserLoad.query.filter_by(is_enabled=True).order_by(UserLoad.priority.asc(), UserLoad.power_w.asc(), UserLoad.name.asc()).all()
    if not latest or not loads:
        return None
    _, weather = _get_weather_for_latest()
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    is_day = _weather_day_window(now_local, weather, start_hour=9) if phase_override is None else (phase_override == 'day')
    solar = max(float(latest.solar_power or 0), 0.0)
    home = max(float(latest.home_load or 0), 0.0)
    battery_soc = float(latest.battery_soc or 0)
    battery_power = float(latest.battery_power or 0)
    if is_day:
        surplus_data = compute_actual_solar_surplus(latest, weather=weather, settings=(settings or load_settings()))
        available = max(float(surplus_data.get('actual_surplus_w', 0) or 0), 0.0)
        raw_surplus = max(float(surplus_data.get('raw_surplus_w', 0) or 0), 0.0)
        battery_need = max(float(surplus_data.get('battery_charge_need_w', 0) or 0), 0.0)
        prefix = f"☀️ الأحمال نهارًا (فعلي {int(round(available))}W من خام {int(round(raw_surplus))}W بعد خصم {int(round(battery_need))}W للبطارية)"
    else:
        night_cap = safe_float((settings or load_settings()).get('night_max_load_w') or load_settings().get('night_max_allowed_w', '500'), 500)
        available = max(night_cap - home, 0.0)
        prefix = '🌙 الأحمال ليلًا'
    available = max(0.0, available)
    fit = [x for x in loads if float(x.power_w or 0) <= available + 1e-9]
    if not fit:
        return f"{prefix}: لا يوجد حمل إضافي آمن الآن"
    names = '، '.join(f"{x.name} ({int(round(float(x.power_w or 0)))}W)" for x in fit[:3])
    return f"{prefix}: الحمل الحالي {int(round(home))}W | المتاح {int(round(max(available,0)))}W\nينصح فقط بالأجهزة الأقل من المتاح: {names}"


def build_pre_sunset_message(latest, weather=None, settings=None):
    settings = settings or load_settings()
    prediction = build_pre_sunset_prediction(latest, weather, settings)
    if not latest or not prediction:
        return '🌇 تحليل ما قبل الغروب', 'لا توجد بيانات كافية.', 'warning'
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    lines = []
    if _flag(settings, 'pre_sunset_include_soc', True):
        lines.append(f"🔋 نسبة البطارية: {int(round(float(latest.battery_soc or 0)))}%")
    if _flag(settings, 'pre_sunset_include_charge_power', True):
        lines.append(f"⚡ الشحن الحالي: {format_power(battery.get('charge_power_w', 0))} واط")
    lines += [f"🕕 الغروب الفعلي للحساب: {_to_12h_label(prediction.get('effective_sunset_time'))}", f"🕒 المتبقي للغروب: {prediction.get('remaining_label')}"]
    if prediction.get('time_to_full_hours') is not None and _flag(settings, 'pre_sunset_include_eta', True):
        lines.append(f"⏳ وقت الامتلاء: {human_duration_hours(prediction.get('time_to_full_hours'))}")
    lines += ['', f"{'✅' if prediction.get('level') == 'success' else '⚠️'} النتيجة:", prediction.get('verdict', 'غير متاح')]
    if prediction.get('advice') and _flag(settings, 'pre_sunset_include_advice', True):
        lines += ['', f"💡 نصيحة: {prediction.get('advice')}"]
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    if prediction.get('weather_advice') and _weather_day_window(now_local, weather, start_hour=7):
        lines += ['', f"🌤️ الطقس: {prediction.get('weather_advice')}"]
    return '🌇 تحليل ما قبل الغروب', "\n".join(lines), prediction.get('level', 'warning')


def build_periodic_status_message(latest, weather=None, settings=None, phase_override=None):
    if not latest:
        return '🔔 التحديث الدوري للطاقة', 'لا توجد قراءة محفوظة حاليًا.'
    settings = settings or load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_state = build_system_state(latest, battery)
    solar = max(float(latest.solar_power or 0), 0)
    home = max(float(latest.home_load or 0), 0)
    soc = float(latest.battery_soc or 0)

    # استخراج بيانات device/latest الإضافية
    d = {}
    if latest.raw_json:
        try:
            d = json.loads(latest.raw_json).get('device_data') or {}
        except Exception:
            pass
    def _fv(k, default=None):
        v = d.get(k)
        if v is None: return default
        try: return float(v)
        except: return None

    inv_temp = _fv('acTemperature')
    bms_temp = _fv('bmsTemperature')
    pv1_power = _fv('dcPowerPv1', 0)
    rated_power = _fv('ratedPower', 6000)
    daily_prod = _fv('dailyProductionActive', 0)
    daily_cons = _fv('dailyConsumption', 0)
    daily_charge = _fv('dailyChargingEnergy', 0)
    daily_discharge = _fv('dailyDischargingEnergy', 0)
    batt_voltage = _fv('batteryVoltage') or _fv('bmsVoltage')
    pv_pct = (solar / rated_power * 100) if rated_power and rated_power > 0 else 0

    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    is_day = _weather_day_window(now_local, weather, start_hour=9) if phase_override is None else (phase_override == 'day')

    lines = []
    if _flag(settings, 'periodic_day_include_progress' if is_day else 'periodic_night_include_progress', True):
        lines.append(battery_percent_bar(soc))
    lines += [f"🔋 الحالة: {battery.get('mode_label', 'ثابتة')} | {system_state}", '', f"🏠  استهلاك المنزل: {format_power(home)} واط", f"🔋  طاقة البطارية: {format_energy(battery.get('stored_kwh', 0))} (SOC: {soc:.0f}%)"]
    if is_day:
        lines.insert(3, f"☀️  الشمس الآن: {format_power(solar)} واط ({pv_pct:.0f}% من القدرة القصوى)")
    else:
        lines.insert(3, "🌙 ليلًا الآن")

    mode = battery.get('mode_label')
    include_eta = _flag(settings, 'periodic_day_include_eta' if is_day else 'periodic_night_include_eta', True)
    if include_eta:
        if mode == 'يتم الشحن':
            lines.append(f"⏳ وقت الامتلاء: {battery.get('charge_eta', 'غير متاح')}")
        elif mode == 'يتم التفريغ':
            lines.append(f"⏳ وقت النفاد: {battery.get('discharge_eta', 'غير متاح')}")

    # بيانات إضافية من device/latest
    extras = []
    if daily_prod is not None and daily_prod > 0:
        extras.append(f"⚡ إنتاج اليوم: {format_energy(daily_prod)}")
    if daily_cons is not None and daily_cons > 0:
        extras.append(f"🏠 استهلاك اليوم: {format_energy(daily_cons)}")
    if daily_charge is not None and daily_charge > 0:
        extras.append(f"🔼 شحن اليوم: {format_energy(daily_charge)}")
    if daily_discharge is not None and daily_discharge > 0:
        extras.append(f"🔽 تفريغ اليوم: {format_energy(daily_discharge)}")
    if extras and _flag(settings, 'periodic_day_include_summary' if is_day else 'periodic_night_include_summary', True):
        lines += ['', '📅 ملخص اليوم:'] + extras

    # تحذيرات الحرارة
    warnings = []
    if inv_temp is not None and inv_temp > 70:
        warnings.append(f"🌡️⚠️ حرارة الانفيرتر مرتفعة: {inv_temp:.1f}°م")
    elif inv_temp is not None:
        warnings.append(f"🌡️ حرارة الانفيرتر: {inv_temp:.1f}°م")
    if bms_temp is not None:
        warnings.append(f"🌡️ حرارة البطارية: {bms_temp:.1f}°م")
    if batt_voltage is not None:
        warnings.append(f"⚡ جهد البطارية: {batt_voltage:.2f} V")
    if warnings and _flag(settings, 'periodic_day_include_device' if is_day else 'periodic_night_include_device', True):
        lines += ['', '🔧 حالة الجهاز:'] + warnings

    # تحليل الغروب يظهر نهارًا فقط
    solar_prediction = build_pre_sunset_prediction(latest, weather, settings)
    if solar_prediction and is_day and _flag(settings, 'periodic_day_include_sunset', True):
        lines += [
            '',
            f"🌇 الغروب: {_to_12h_label(solar_prediction.get('sunset_time'))} | الفعلي: {_to_12h_label(solar_prediction.get('effective_sunset_time'))}",
            f"⏱️  المتبقي: {human_duration_hours(solar_prediction.get('remaining_hours'))}",
            f"🔮 التحليل: {solar_prediction.get('verdict')}",
        ]
        if solar_prediction.get('advice'):
            lines.append(f"💡 {solar_prediction.get('advice')}")
        if solar_prediction.get('weather_advice') and _weather_day_window(now_local, weather, start_hour=7):
            lines.append(f"🌤️ {solar_prediction.get('weather_advice')}")

    if weather and _flag(settings, 'periodic_day_include_weather' if is_day else 'periodic_night_include_weather', True):
        weather_line = _short_weather_line(now_local, weather)
        if weather_line:
            lines += ['', f"🌤️ الطقس: {weather_line}"]
            if _weather_day_window(now_local, weather, start_hour=7):
                lines.append(f"☁️ الغيوم: {weather.cloud_cover if weather.cloud_cover is not None else '--'}%")
    load_line = _periodic_load_suggestion(latest, phase_override=('day' if is_day else 'night'), settings=settings) if _flag(settings, 'periodic_day_include_loads' if is_day else 'periodic_night_include_loads', True) else None
    if load_line:
        lines += ['', load_line]
    return '🔔 التحديث الدوري للطاقة', "\n".join(lines)


# ── Scheduled senders ─────────────────────────────────────────────────────────


def _schedule_interval_minutes(value, unit):
    try:
        raw = max(int(float(value or 1)), 1)
    except Exception:
        raw = 1
    unit = (unit or 'hours').strip().lower()
    if unit in ('minute', 'minutes', 'min', 'mins', 'دقيقة', 'دقائق'):
        return raw
    return raw * 60


def _parse_iso_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def _resolve_schedule_token(token, now_local, weather=None):
    token = (token or '').strip().lower()
    if not token:
        return None
    if token == 'sunset':
        return _parse_hhmm_local(getattr(weather, 'sunset_time', None), now_local) if weather else None
    return _parse_hhmm_local(token, now_local)


def _is_within_schedule_window(now_local, start_token, end_token, weather=None):
    start_dt = _resolve_schedule_token(start_token, now_local, weather)
    end_dt = _resolve_schedule_token(end_token, now_local, weather)

    if start_dt is None and end_dt is None:
        return True
    if start_dt is not None and end_dt is None:
        return now_local >= start_dt
    if start_dt is None and end_dt is not None:
        return now_local <= end_dt

    # نطاق يعبر منتصف الليل
    if start_dt > end_dt:
        return now_local >= start_dt or now_local <= end_dt
    return start_dt <= now_local <= end_dt


def _schedule_matches(prefix, settings, now_local, weather=None):
    mode = (settings.get(f'{prefix}_schedule_mode', 'manual') or 'manual').strip().lower()
    start_token = settings.get(f'{prefix}_time_start', '')
    end_token = settings.get(f'{prefix}_time_end', '')
    last_sent_raw = settings.get(f'{prefix}_last_sent_at', '')
    last_sent = _parse_iso_utc(last_sent_raw)
    now_utc = datetime.now(UTC)

    current_app.logger.info(
        'schedule check: prefix=%s mode=%s enabled=%s now_local=%s start=%s end=%s last_sent=%s',
        prefix,
        mode,
        settings.get(f'{prefix}_enabled', ''),
        now_local.isoformat(),
        start_token or '-',
        end_token or '-',
        last_sent_raw or '-',
    )

    if mode == 'manual':
        current_app.logger.info('schedule skip: prefix=%s reason=manual_mode', prefix)
        return False

    within_window = _is_within_schedule_window(now_local, start_token, end_token, weather)
    if not within_window:
        current_app.logger.info('schedule skip: prefix=%s reason=outside_window current=%s start=%s end=%s', prefix, now_local.strftime('%H:%M'), start_token or '-', end_token or '-')
        return False

    if mode == 'interval':
        interval_minutes = _schedule_interval_minutes(
            settings.get(f'{prefix}_interval_value', '1'),
            settings.get(f'{prefix}_interval_unit', 'hours'),
        )
        elapsed_seconds = (now_utc - last_sent).total_seconds() if last_sent else None
        due = (last_sent is None) or (elapsed_seconds >= interval_minutes * 60)
        current_app.logger.info(
            'schedule interval: prefix=%s interval_minutes=%s elapsed_seconds=%s due=%s',
            prefix,
            interval_minutes,
            elapsed_seconds if elapsed_seconds is not None else '-',
            due,
        )
        return due

    if mode in ('specific', 'specific_hours'):
        allowed = []
        for item in str(settings.get(f'{prefix}_specific_hours', '') or '').split(','):
            item = item.strip()
            if item:
                allowed.append(item)
        current_hm = now_local.strftime('%H:%M')
        if current_hm not in allowed:
            current_app.logger.info('schedule skip: prefix=%s reason=specific_hour_not_matched current=%s allowed=%s', prefix, current_hm, ','.join(allowed) or '-')
            return False
        same_minute = bool(last_sent and last_sent.astimezone(now_local.tzinfo).strftime('%Y-%m-%d %H:%M') == now_local.strftime('%Y-%m-%d %H:%M'))
        current_app.logger.info('schedule specific: prefix=%s current=%s same_minute=%s', prefix, current_hm, same_minute)
        return not same_minute

    if mode == 'threshold':
        interval_minutes = _schedule_interval_minutes(
            settings.get(f'{prefix}_interval_value', '60'),
            settings.get(f'{prefix}_interval_unit', 'hours'),
        )
        elapsed_seconds = (now_utc - last_sent).total_seconds() if last_sent else None
        due = (last_sent is None) or (elapsed_seconds >= interval_minutes * 60)
        current_app.logger.info(
            'schedule threshold: prefix=%s interval_minutes=%s elapsed_seconds=%s due=%s',
            prefix,
            interval_minutes,
            elapsed_seconds if elapsed_seconds is not None else '-',
            due,
        )
        return due

    current_app.logger.info('schedule skip: prefix=%s reason=unknown_mode mode=%s', prefix, mode)
    return False


def _send_scheduled_notification(prefix, title, message, channel, level='info'):
    settings = load_settings()
    now = datetime.now(UTC)
    clean_title = _normalize_telegram_text(title)
    clean_message = _normalize_telegram_text(message)
    current_app.logger.info('scheduled notification send: %s via %s', prefix, channel or 'telegram')
    dispatch_notification(
        settings,
        f'{prefix}-{int(now.timestamp())}',
        prefix,
        clean_title,
        clean_message,
        channel or 'telegram',
        level,
        dedupe_minutes=0,
    )
    _upsert_setting(f'{prefix}_last_sent_at', now.isoformat())
    db.session.commit()


def run_advanced_notification_scheduler():
    settings = load_settings()
    if str(settings.get('notifications_enabled', 'true')).lower() != 'true':
        current_app.logger.info('advanced scheduler skipped: notifications disabled')
        return

    latest, weather = _get_weather_for_latest()
    if not latest:
        current_app.logger.info('advanced scheduler skipped: no latest reading')
        return

    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    is_day = _weather_day_window(now_local, weather, start_hour=9)
    current_app.logger.info('advanced scheduler tick at %s is_day=%s weather_available=%s', now_local.isoformat(), is_day, bool(weather))

    # 1) التحديث الدوري النهاري
    periodic_day_enabled = str(settings.get('periodic_day_enabled', 'true')).lower() == 'true'
    current_app.logger.info('periodic_day state: enabled=%s channel=%s mode=%s', periodic_day_enabled, settings.get('periodic_day_channel', 'telegram'), settings.get('periodic_day_schedule_mode', 'manual'))
    if periodic_day_enabled:
        due_day = is_day and _schedule_matches('periodic_day', settings, now_local, weather)
        current_app.logger.info('periodic_day decision: is_day=%s due=%s', is_day, due_day)
        if due_day:
            title, message = build_periodic_status_message(latest, weather, settings=settings, phase_override='day')
            _send_scheduled_notification('periodic_day', title, message, settings.get('periodic_day_channel', 'telegram'), 'info')
        else:
            current_app.logger.info('periodic_day skipped after checks')
    else:
        current_app.logger.info('periodic_day skipped: disabled')

    # 2) التحديث الدوري الليلي
    periodic_night_enabled = str(settings.get('periodic_night_enabled', 'true')).lower() == 'true'
    current_app.logger.info('periodic_night state: enabled=%s channel=%s mode=%s', periodic_night_enabled, settings.get('periodic_night_channel', 'telegram'), settings.get('periodic_night_schedule_mode', 'manual'))
    if periodic_night_enabled:
        due_night = (not is_day) and _schedule_matches('periodic_night', settings, now_local, weather)
        current_app.logger.info('periodic_night decision: is_day=%s due=%s', is_day, due_night)
        if due_night:
            title, message = build_periodic_status_message(latest, weather, settings=settings, phase_override='night')
            _send_scheduled_notification('periodic_night', title, message, settings.get('periodic_night_channel', 'telegram'), 'info')
        else:
            current_app.logger.info('periodic_night skipped after checks')
    else:
        current_app.logger.info('periodic_night skipped: disabled')

    # 3) تحليل ما قبل الغروب
    if str(settings.get('pre_sunset_enabled', 'false')).lower() == 'true':
        if _schedule_matches('pre_sunset', settings, now_local, weather):
            try:
                prediction = build_pre_sunset_prediction(latest, weather, settings)
                if not (
                    prediction
                    and str(settings.get('pre_sunset_only_if_not_full', 'false')).lower() == 'true'
                    and prediction.get('will_full_before_sunset')
                ):
                    title, message, level = build_pre_sunset_message(latest, weather, settings=settings)
                    _send_scheduled_notification('pre_sunset', title, message, settings.get('pre_sunset_channel', 'telegram'), level)
            except Exception:
                pass

    # 4) اقتراح الأحمال
    if str(settings.get('load_alert_enabled', 'true')).lower() == 'true':
        if _schedule_matches('load_alert', settings, now_local, weather):
            title = '⚡ اقتراح الأحمال'
            message = build_telegram_quick_reply('loads', latest, weather, settings=settings)
            _send_scheduled_notification('load_alert', title, message, settings.get('load_alert_channel', 'telegram'), 'info')

    # 5) اختبار البطارية
    if str(settings.get('battery_test_enabled', 'true')).lower() == 'true':
        if _schedule_matches('battery_test', settings, now_local, weather):
            _dummy_title, base_message = build_periodic_status_message(latest, weather, settings=settings, phase_override='day')
            title = '🧪 اختبار حالة البطارية'
            _send_scheduled_notification('battery_test', title, base_message, settings.get('battery_test_channel', 'telegram'), 'warning')

    # 6) التقرير الصباحي
    if str(settings.get('daily_report_enabled', 'true')).lower() == 'true':
        report_time = (settings.get('daily_report_time', '07:00') or '07:00').strip()
        if now_local.strftime('%H:%M') == report_time:
            last_sent = _parse_iso_utc(settings.get('daily_report_last_sent_at', ''))
            same_minute = last_sent and last_sent.astimezone(now_local.tzinfo).strftime('%Y-%m-%d %H:%M') == now_local.strftime('%Y-%m-%d %H:%M')
            if not same_minute:
                title, message = build_daily_morning_report_message(latest, settings=settings)
                _send_scheduled_notification('daily_report', title, message, settings.get('daily_report_channel', 'telegram'), 'info')

def _get_weather_for_latest():
    from ..services.weather_service import fetch_weather
    from .helpers import load_settings
    from ..services.utils import safe_float
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    if not latest or not latest.raw_json:
        return latest, None
    import json as _json
    try:
        raw = _json.loads(latest.raw_json)
        station = raw.get('station_summary') or {}
        lat = safe_float(station.get('locationLat'), None)
        lng = safe_float(station.get('locationLng'), None)
        if lat is None or lng is None:
            return latest, None
        weather = fetch_weather(lat, lng, current_app.config['LOCAL_TIMEZONE'])
        return latest, weather
    except Exception:
        return latest, None


def send_periodic_status_update(force=False, channel_override=None):
    settings = load_settings()
    if str(settings.get('notifications_enabled', 'true')).lower() != 'true' and not force:
        return
    if str(settings.get('periodic_status_enabled', 'true')).lower() != 'true' and not force:
        return
    try:
        interval = max(int(float(settings.get('periodic_status_interval_minutes', '30') or 30)), 5)
    except Exception:
        interval = 30
    now = datetime.now(UTC)
    last_sent_raw = settings.get('periodic_status_last_sent_at', '')
    if not force:
        if last_sent_raw:
            try:
                last = datetime.fromisoformat(last_sent_raw)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if (now - last).total_seconds() < interval * 60:
                    return
            except Exception:
                pass
    latest, weather = _get_weather_for_latest()
    title, message = build_periodic_status_message(latest, weather)
    channel = channel_override or settings.get('periodic_status_channel', 'telegram')
    dispatch_notification(settings, f'periodic-status-{int(now.timestamp())}', 'التحديث الدوري', title, message, channel, 'info', dedupe_minutes=0)
    _upsert_setting('periodic_status_last_sent_at', now.isoformat())
    db.session.commit()


def send_pre_sunset_update(force=False, channel_override=None):
    settings = load_settings()
    if str(settings.get('notifications_enabled', 'true')).lower() != 'true' and not force:
        return
    if str(settings.get('pre_sunset_enabled', 'false')).lower() != 'true' and not force:
        return
    try:
        interval = max(int(float(settings.get('pre_sunset_interval_minutes', '30') or 30)), 5)
    except Exception:
        interval = 30
    now = datetime.now(UTC)
    last_sent_raw = settings.get('pre_sunset_last_sent_at', '')
    if not force:
        if last_sent_raw:
            try:
                last = datetime.fromisoformat(last_sent_raw)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if (now - last).total_seconds() < interval * 60:
                    return
            except Exception:
                pass
    latest, weather = _get_weather_for_latest()
    settings = load_settings()
    prediction = build_pre_sunset_prediction(latest, weather, settings)
    if prediction and str(settings.get('pre_sunset_only_if_not_full', 'false')).lower() == 'true' and prediction.get('will_full_before_sunset'):
        return
    title, message, level = build_pre_sunset_message(latest, weather)
    channel = channel_override or settings.get('pre_sunset_channel', 'telegram')
    dispatch_notification(settings, f'pre-sunset-{int(now.timestamp())}', 'تحليل ما قبل الغروب', title, message, channel, level, dedupe_minutes=0)
    _upsert_setting('pre_sunset_last_sent_at', now.isoformat())
    db.session.commit()


def send_daily_weather_summary(force=False):
    settings = load_settings()
    if str(settings.get('weather_enabled', 'true')).lower() != 'true':
        return
    if str(settings.get('weather_daily_summary_enabled', 'true')).lower() != 'true' and not force:
        return
    latest, weather = _get_weather_for_latest()
    if not weather:
        return
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    if not force and not _weather_day_window(now_local, weather, start_hour=7):
        return

    def _one_line(label, item):
        temp = item.get('temperature') if isinstance(item, dict) else None
        cond = item.get('condition_ar') if isinstance(item, dict) else 'غير متاح'
        return f"{label}: {cond} {temp if temp not in (None, '') else '--'}°"

    event_key = f"weather-daily-{now_local.strftime('%Y-%m-%d')}"
    message = "\n".join([
        _one_line('9ص', weather.morning),
        _one_line('12م', weather.noon),
        _one_line('3م', weather.afternoon),
        f"الآن: {weather.condition_ar} {weather.temperature if weather.temperature is not None else '--'}°",
    ])
    dispatch_notification(settings, event_key, 'ملخص الطقس اليومي', '☁️ ملخص الطقس اليومي', message, settings.get('weather_daily_summary_channel', 'telegram'), 'info', dedupe_minutes=24 * 60)


def run_weather_checks(force=False):
    settings = load_settings()
    if str(settings.get('weather_enabled', 'true')).lower() != 'true':
        return
    if str(settings.get('weather_change_alerts_enabled', 'true')).lower() != 'true' and not force:
        return
    latest, weather = _get_weather_for_latest()
    if not weather:
        return
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    if not force and not _weather_day_window(now_local, weather, start_hour=7):
        return
    next_hour = weather.next_hour or {}
    next_cat = next_hour.get('category') or 'unknown'
    next_label = next_hour.get('condition_ar') or 'غير معروف'
    next_cloud = next_hour.get('cloud_cover')
    next_pop = next_hour.get('precipitation_probability')
    cloud_threshold = safe_float(settings.get('weather_cloud_threshold'), 60)
    bucket = now_local.strftime('%Y-%m-%d-%H') + ('-a' if now_local.minute < 30 else '-b')
    channel = settings.get('weather_change_alerts_channel', 'telegram')
    if next_cat in {'sunny', 'partly_cloudy'}:
        dispatch_notification(settings, f'weather-sunny-{bucket}', 'تغير الطقس', '☀️ طقس أفضل خلال ساعة', f'{next_label} خلال ساعة.', channel, 'info', dedupe_minutes=30)
    if next_cat in {'cloudy', 'fog'} or (next_cloud is not None and float(next_cloud or 0) >= cloud_threshold):
        dispatch_notification(settings, f'weather-cloudy-{bucket}', 'تغير الطقس', '☁️ غيوم متوقعة خلال ساعة', f'{next_label} • غيوم {next_cloud if next_cloud is not None else "--"}%.', channel, 'warning', dedupe_minutes=30)
    if next_cat in {'rain', 'storm'} or (next_pop is not None and float(next_pop or 0) >= 50):
        dispatch_notification(settings, f'weather-rain-{bucket}', 'تغير الطقس', '🌧️ احتمال مطر خلال ساعة', f'احتمال الهطول {next_pop if next_pop is not None else "--"}%.', channel, 'warning', dedupe_minutes=30)


def build_daily_morning_report_message(latest, settings=None):
    settings = settings or load_settings()
    if not latest:
        return '☀️ تقرير الصباح اليومي', 'لا توجد قراءة حديثة.'
    d = {}
    if latest.raw_json:
        try:
            d = json.loads(latest.raw_json).get('device_data') or {}
        except Exception:
            pass

    def _fv(k, default=0):
        v = d.get(k)
        if v is None: return default
        try: return float(v)
        except: return default

    battery_capacity_kwh, _ = get_runtime_battery_settings(settings)
    cap_kwh = float(battery_capacity_kwh or 5)
    total_prod = _fv('cumulativeProductionActive')
    total_cons = _fv('cumulativeConsumption')
    total_charge = _fv('totalChargingEnergy')
    total_discharge = _fv('totalDischargingEnergy')
    daily_prod = _fv('dailyProductionActive')
    daily_cons = _fv('dailyConsumption')
    daily_charge = _fv('dailyChargingEnergy')
    daily_discharge = _fv('dailyDischargingEnergy')
    soc = float(latest.battery_soc or 0)
    inv_temp = _fv('acTemperature', 0)
    bms_temp = _fv('bmsTemperature', 0)
    cycles = int(total_charge / cap_kwh) if cap_kwh > 0 and total_charge > 0 else 0
    now = datetime.now(UTC)
    tz_name = current_app.config['LOCAL_TIMEZONE']
    now_local = utc_to_local(now, tz_name) or now
    lines = [f"🌅 تقرير صباح يوم {now_local.strftime('%Y-%m-%d')}"]
    if _flag(settings, 'daily_report_include_totals', True):
        lines += ['', '📊 الإجماليات الكلية منذ بدء التشغيل:', f"  ☀️  إجمالي الإنتاج الشمسي: {format_energy(total_prod)}", f"  🏠  إجمالي الاستهلاك الكلي: {format_energy(total_cons)}", f"  🔼  إجمالي شحن البطارية: {format_energy(total_charge)}", f"  🔽  إجمالي تفريغ البطارية: {format_energy(total_discharge)}", f"  🔄  دورات الشحن التقريبية: {cycles} دورة"]
    if _flag(settings, 'daily_report_include_yesterday', True):
        lines += ['', '📅 اليوم السابق (آخر قراءة):', f"  ☀️  الإنتاج الشمسي: {format_energy(daily_prod)}", f"  🏠  استهلاك المنزل: {format_energy(daily_cons)}", f"  🔼  شحن البطارية: {format_energy(daily_charge)}", f"  🔽  تفريغ البطارية: {format_energy(daily_discharge)}"]
    if _flag(settings, 'daily_report_include_device', True):
        lines += ['', '🔧 حالة الجهاز الآن:', f"  🔋  نسبة البطارية: {soc:.0f}%"]
        if inv_temp > 0: lines.append(f"  🌡️  حرارة الانفيرتر: {inv_temp:.1f}°م{'  ⚠️' if inv_temp > 70 else ''}")
        if bms_temp > 0: lines.append(f"  🌡️  حرارة BMS: {bms_temp:.1f}°م")
    return '☀️ تقرير الصباح اليومي', "\n".join(lines)


def send_daily_morning_report(force=False):
    """تقرير الصباح الشامل — يُرسَل الساعة 9 صباحاً."""
    settings = load_settings()
    if str(settings.get('notifications_enabled', 'true')).lower() != 'true' and not force:
        return
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    event_key = f"daily-report-{now.strftime('%Y-%m-%d')}"
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    if not latest:
        return
    title, message = build_daily_morning_report_message(latest, settings=settings)
    channel = settings.get('periodic_status_channel', 'telegram')
    dispatch_notification(settings, event_key, 'تقرير الصباح', title, message, channel, 'info', dedupe_minutes=23 * 60)
    return



def process_notifications(current: Reading, previous: Reading | None):
    settings = load_settings()
    if str(settings.get('notifications_enabled', 'true')).lower() != 'true':
        return
    rules = load_notification_rules(settings)
    current_soc = float(current.battery_soc or 0)
    prev_soc = float(previous.battery_soc) if previous else current_soc
    now_local = utc_to_local(current.created_at, current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    day_key = now_local.strftime('%Y-%m-%d')
    hour_key = now_local.strftime('%Y-%m-%d-%H')

    for level in crossed_up(prev_soc, current_soc, 10):
        channel = rules['charge'].get(str(level), 'none')
        dispatch_notification(settings, f'charge-{level}-{day_key}', 'شحن البطارية', f'🔋 شحن البطارية {level}%', f'وصلت البطارية إلى {level}%.', channel, 'success')

    for level in crossed_down(prev_soc, current_soc, 5):
        channel = rules['discharge'].get(str(level), 'none')
        dispatch_notification(settings, f'discharge-{level}-{day_key}', 'تفريغ البطارية', f'⚠️ تفريغ البطارية {level}%', f'انخفضت البطارية إلى {level}%.', channel, 'danger' if level <= 15 else 'warning')

    solar = max(float(current.solar_power or 0), 0)
    load = max(float(current.home_load or 0), 0)
    solar_min = safe_float(settings.get('daytime_solar_min_w'), 50)
    if solar >= solar_min and load > solar:
        conf = rules.get('day_deficit', {})
        if conf.get('enabled'):
            dispatch_notification(settings, f'day-deficit-{hour_key}', 'عجز شمسي نهاري', '☀️ الاستهلاك أعلى من الإنتاج الشمسي', f'الإنتاج {format_power(solar)} واط، الحمل {format_power(load)} واط.', conf.get('channel', 'telegram'), 'warning', dedupe_minutes=60)

    if solar < solar_min:
        for threshold, channel in sorted(rules.get('night_thresholds', {}).items(), key=lambda x: int(x[0])):
            thr = safe_float(threshold, 0)
            if load > thr:
                dispatch_notification(settings, f'night-load-{int(thr)}-{hour_key}', 'حمل ليلي مرتفع', f'🌙 حمل ليلي مرتفع فوق {int(thr)} واط', f'الحمل الليلي {format_power(load)} واط.', channel, 'danger' if thr >= 500 else 'warning', dedupe_minutes=60)

    # تنبيهات حرارة الانفيرتر والبطارية (من device/latest)
    d = {}
    if current.raw_json:
        try:
            d = json.loads(current.raw_json).get('device_data') or {}
        except Exception:
            pass

    def _fv2(k, default=None):
        v = d.get(k)
        if v is None: return default
        try: return float(v)
        except: return None

    inv_temp = _fv2('acTemperature')
    bms_temp = _fv2('bmsTemperature')
    rated_power = _fv2('ratedPower', 6000)
    pv_use_pct = (solar / rated_power * 100) if rated_power and rated_power > 0 else 0

    if inv_temp is not None and inv_temp > 75:
        dispatch_notification(settings, f'inv-temp-high-{hour_key}',
            'حرارة الانفيرتر مرتفعة', f'🌡️⚠️ حرارة الانفيرتر {inv_temp:.1f}°م',
            f'وصلت حرارة الانفيرتر إلى {inv_temp:.1f}°م — تجاوزت الحد الطبيعي (75°م).',
            rules.get('discharge', {}).get('10', 'telegram') or 'telegram', 'danger', dedupe_minutes=60)

    if bms_temp is not None and bms_temp > 40:
        dispatch_notification(settings, f'bms-temp-high-{hour_key}',
            'حرارة البطارية مرتفعة', f'🌡️⚠️ حرارة BMS {bms_temp:.1f}°م',
            f'وصلت حرارة البطارية إلى {bms_temp:.1f}°م — تجاوزت الحد الطبيعي (40°م).',
            'telegram', 'danger', dedupe_minutes=60)

    if pv_use_pct > 90 and solar > 100:
        dispatch_notification(settings, f'pv-high-{hour_key}',
            'استخدام عالٍ للانفيرتر', f'⚡ الجهاز يعمل على {pv_use_pct:.0f}% من طاقته',
            f'الإنتاج الحالي {format_power(solar)} واط من أصل {int(rated_power/1000)}kW ({pv_use_pct:.0f}%).',
            'telegram', 'info', dedupe_minutes=120)

    try:
        send_periodic_status_update()
    except Exception as exc:
        from .helpers import log_event
        log_event('warning', f'تعذر التحديث الدوري: {exc}')

    try:
        send_pre_sunset_update()
    except Exception as exc:
        from .helpers import log_event
        log_event('warning', f'تعذر تحليل الغروب: {exc}')
