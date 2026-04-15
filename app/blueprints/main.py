"""Main routes blueprint — dashboard, statistics, reports, devices, etc."""
from __future__ import annotations
import csv
import io
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, session, url_for
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
from ..models import NotificationLog, Reading, Setting, SyncLog, UserLoad, TelegramLink
from ..services.deye_client import DeyeClient
from ..services.utils import (
    format_local_datetime, human_duration_hours, safe_float,
    safe_power_w, to_json, utc_to_local,
)
from ..services.weather_service import fetch_weather
from ..services.telegram_link_service import create_link_token, get_link_by_owner, get_owner_key, revoke_link, consume_link_token, touch_link_by_chat_id
from .helpers import (
    _to_12h_label, battery_percent_bar, build_battery_details, build_battery_insights,
    build_flow, build_period_chart, build_statistics_table, build_summary_chart,
    build_system_state, build_system_status, build_weather_insight, compute_energy_stats, filter_rows_for_view, format_energy,
    format_power, format_time_short, get_runtime_battery_settings, get_production_summary,
    load_settings, log_event, normalize_local_date, parse_selected_date, prune_old_logs,
    save_settings_from_form, shift_period,
)
from .notifications import (
    apply_form_settings_overrides, build_daily_morning_report_message,
    build_periodic_status_message, build_pre_sunset_message,
    dispatch_notification, load_notification_rules, log_notification,
    process_notifications, run_weather_checks, save_notification_settings_from_form,
    send_daily_weather_summary, send_periodic_status_update, send_pre_sunset_update,
    send_sms_message, send_telegram_message, send_telegram_menu, process_telegram_update, build_telegram_quick_reply,
)

main_bp = Blueprint('main', __name__)


def _current_owner_key() -> str:
    return get_owner_key(session.get('username'))


def _current_owner_label() -> str:
    return (session.get('username') or current_app.config.get('ADMIN_USERNAME') or 'admin').strip() or 'admin'


def _telegram_link_command(link: TelegramLink | None) -> str:
    if not link or not link.link_token:
        return ''
    return f"/start {link.link_token}"


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


def _lang():
    lang = (request.args.get('lang') or session.get('ui_lang') or 'ar').strip().lower()
    return 'en' if lang == 'en' else 'ar'


def _serialize_loads():
    rows = UserLoad.query.order_by(UserLoad.priority.asc(), UserLoad.power_w.asc(), UserLoad.name.asc()).all()
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
    now_local = now_local or (utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC))
    mode, sunset_dt = _load_suggestion_mode(now_local, weather)
    current_load = float(latest.home_load or 0) if latest else 0.0
    solar = float(latest.solar_power or 0) if latest else 0.0
    surplus = max(solar - current_load, 0.0)
    target_cap = max(float(max_allowed_w or 0), 0.0)
    if mode == 'day':
        available = surplus
        reason_ar = 'يعتمد الاقتراح نهارًا على الفائض الشمسي الحالي.'
        reason_en = 'Daytime planning uses the current solar surplus.'
    else:
        available = max(target_cap - current_load, 0.0)
        reason_ar = 'ليلًا يُحسب المتبقي من الحد الذي حددته بعد خصم الحمل الحالي.'
        reason_en = 'At night the remaining margin is based on your custom max draw minus the current load.'

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
        'surplus_w': round(surplus, 1),
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
            'available_w': 0.0, 'safe_available_w': 0.0, 'battery_soc': 0.0, 'can_run': [], 'hold': [],
            'headline_ar': 'بانتظار أول قراءة للنظام', 'headline_en': 'Waiting for the first system reading',
            'mode_ar': 'لا توجد بيانات', 'mode_en': 'No data yet', 'phase': 'night', 'night_max_w': night_max_w,
        }
    weather = get_weather_for_latest(latest)
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    phase, _ = _load_suggestion_mode(now_local, weather)
    solar = float(latest.solar_power or 0)
    home = float(latest.home_load or 0)
    battery_soc = float(latest.battery_soc or 0)
    surplus = max(solar - home, 0.0)

    if phase == 'day':
        safe_available = surplus
        mode_ar = 'يعتمد الاقتراح الآن على الفائض الشمسي'
        mode_en = 'Suggestions now use solar surplus'
    else:
        safe_available = max(night_max_w - home, 0.0)
        mode_ar = f'ليلًا: الحد المعتمد {int(round(night_max_w))} واط'
        mode_en = f'Night: saved limit {int(round(night_max_w))} W'

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
        headline_ar = 'الفائض الحالي لا يكفي لتشغيل حمل جديد بأمان'
        headline_en = 'The current surplus is not enough for a new load safely'
    else:
        headline_ar = 'يفضل تأجيل تشغيل الأحمال الإضافية الآن'
        headline_en = 'It is better to postpone extra loads for now'

    return {
        'available_w': round(surplus, 1),
        'safe_available_w': round(safe_available, 1),
        'battery_soc': round(battery_soc, 1),
        'can_run': can_run,
        'hold': hold,
        'headline_ar': headline_ar,
        'headline_en': headline_en,
        'mode_ar': mode_ar,
        'mode_en': mode_en,
        'phase': phase,
        'night_max_w': round(night_max_w, 1),
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@main_bp.route('/')
def index():
    return redirect(url_for('main.dashboard'))


@main_bp.route('/dashboard')
def dashboard():
    from datetime import UTC, datetime, timedelta
    from ..services.utils import utc_to_local
    from zoneinfo import ZoneInfo
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    logs = SyncLog.query.order_by(SyncLog.created_at.desc()).limit(8).all()
    settings = load_settings()
    tz_name = current_app.config['LOCAL_TIMEZONE']

    # اختيار اليوم من المعامل — افتراضياً اليوم الحالي
    selected_day_str = request.args.get('day', '')
    now_local = utc_to_local(datetime.now(UTC), tz_name) or datetime.now(UTC)
    if selected_day_str:
        try:
            from datetime import date
            sel = date.fromisoformat(selected_day_str)
            day_local = datetime(sel.year, sel.month, sel.day, tzinfo=ZoneInfo(tz_name))
        except Exception:
            day_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        day_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    day_start_utc = day_local.astimezone(UTC).replace(tzinfo=None)
    day_end_utc = (day_local + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None)

    # كل قراءات اليوم المختار
    day_readings = (Reading.query
                    .filter(Reading.created_at >= day_start_utc, Reading.created_at < day_end_utc)
                    .order_by(Reading.created_at.asc()).all())

    # تصفية كل ساعة — نأخذ أقرب قراءة لكل ساعة
    def _hourly_sample(rows):
        if not rows: return []
        buckets = {}
        for r in rows:
            local_t = utc_to_local(r.created_at, tz_name)
            if local_t:
                h = local_t.replace(minute=0, second=0, microsecond=0)
                buckets[h] = r  # آخر قراءة في الساعة
        return [v for _, v in sorted(buckets.items())]

    readings_hourly = _hourly_sample(day_readings)
    # احتياط: لو ما في بيانات لليوم المختار، خذ آخر 24 قراءة
    if not readings_hourly:
        readings_hourly = Reading.query.order_by(Reading.created_at.desc()).limit(24).all()[::-1]

    labels = [format_time_short(r.created_at, tz_name) for r in readings_hourly]
    solar_values = [r.solar_power for r in readings_hourly]
    load_values = [r.home_load for r in readings_hourly]
    battery_soc_values = [r.battery_soc for r in readings_hourly]
    grid_values = [r.grid_power for r in readings_hourly]

    # battery power للرسم البياني
    battery_power_values = [r.battery_power for r in readings_hourly]

    selected_day_label = day_local.strftime('%Y-%m-%d')

    flow = build_flow(latest)
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    battery_details = build_battery_details(latest)
    weather = get_weather_for_latest(latest)
    weather_insight = build_weather_insight(weather, battery_insights)
    solar_prediction = build_pre_sunset_prediction(latest, weather, settings)

    production_summary = get_production_summary(tz_name)
    smart_loads = _smart_load_suggestions(latest)

    return render_template(
        'dashboard.html',
        latest=latest, settings=settings, labels=labels,
        solar_values=solar_values, load_values=load_values,
        battery_soc_values=battery_soc_values, grid_values=grid_values,
        battery_power_values=battery_power_values,
        selected_day_label=selected_day_label,
        logs=logs, flow=flow, battery_insights=battery_insights,
        battery_details=battery_details, battery_capacity_kwh=battery_capacity_kwh,
        battery_reserve_percent=battery_reserve_percent, system_state=system_state, system_status=system_status,
        weather=weather, weather_insight=weather_insight, solar_prediction=solar_prediction,
        production_summary=production_summary, smart_loads=smart_loads,
        human_duration_hours=human_duration_hours, format_energy=format_energy,
        format_power=format_power, _to_12h_label=_to_12h_label,
        format_local=lambda dt: format_local_datetime(dt, tz_name),
        ui_lang=_lang(),
    )


@main_bp.route('/api/live')
def api_live():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    if not latest:
        return {'ok': False}
    weather = get_weather_for_latest(latest)
    settings = load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    solar_prediction = build_pre_sunset_prediction(latest, weather, settings)
    tz_name = current_app.config['LOCAL_TIMEZONE']
    return {
        'ok': True,
        'latest': {
            'solar_power': latest.solar_power, 'home_load': latest.home_load,
            'battery_soc': latest.battery_soc, 'grid_power': latest.grid_power,
            'daily_production': latest.daily_production, 'total_production': latest.total_production,
            'status_text': latest.status_text,
            'created_at': format_local_datetime(latest.created_at, tz_name),
            'pv1_power': latest.pv1_power,
            'pv2_power': latest.pv2_power,
            'inverter_temp': latest.inverter_temp,
            'grid_voltage': latest.grid_voltage,
            'grid_frequency': latest.grid_frequency,
        },
        'battery': battery_insights,
        'system_state': system_state,
        'system_status': system_status,
        'weather': None if not weather else {
            'icon': weather.icon, 'condition_ar': weather.condition_ar,
            'temperature': weather.temperature, 'cloud_cover': weather.cloud_cover,
            'next_hour': weather.next_hour, 'morning': weather.morning,
            'noon': weather.noon, 'afternoon': weather.afternoon, 'timeline': weather.timeline,
            'sunset_time': weather.sunset_time, 'effective_sunset_time': weather.effective_sunset_time,
        },
        'solar_prediction': None if not solar_prediction else {
            'sunset_time': _to_12h_label(solar_prediction.get('sunset_time')),
            'effective_sunset_time': _to_12h_label(solar_prediction.get('effective_sunset_time')),
            'remaining_hours_text': solar_prediction.get('remaining_label'),
            'time_to_full_text': human_duration_hours(solar_prediction.get('time_to_full_hours')),
            'verdict': solar_prediction.get('verdict'),
            'will_full_before_sunset': solar_prediction.get('will_full_before_sunset'),
            'advice': solar_prediction.get('advice'),
            'weather_advice': solar_prediction.get('weather_advice'),
        },
    }


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

    ordered = (Reading.query
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


@main_bp.route('/statistics')
def statistics():
    tz_name = current_app.config['LOCAL_TIMEZONE']
    selected_view, selected_date, filtered_rows, title_hint, prev_date, next_date, can_go_next = _get_stats_context(request.args, tz_name)
    stats = compute_energy_stats(filtered_rows)
    chart = build_period_chart(filtered_rows, tz_name, selected_view)
    table_rows = build_statistics_table(filtered_rows, tz_name, selected_view)
    summary_chart = build_summary_chart(table_rows)
    return render_template(
        'statistics.html',
        selected_view=selected_view, selected_date=selected_date, title_hint=title_hint,
        stats=stats, chart=chart, table_rows=table_rows, summary_chart=summary_chart,
        prev_date=prev_date, next_date=next_date, can_go_next=can_go_next,
        format_energy=format_energy, format_power=format_power,
        format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang(),
    )


@main_bp.route('/reports')
def reports():
    tz_name = current_app.config['LOCAL_TIMEZONE']
    selected_view, selected_date, filtered_rows, title_hint, prev_date, next_date, can_go_next = _get_stats_context(request.args, tz_name)
    stats = compute_energy_stats(filtered_rows)
    chart = build_period_chart(filtered_rows, tz_name, selected_view)
    table_rows = build_statistics_table(filtered_rows, tz_name, selected_view)
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    weather = get_weather_for_latest(latest)

    home = max(stats['home_consumed_kwh'], 0.01)
    # Total energy that fed the home: solar direct + battery discharge
    solar_to_home  = stats['solar_to_home_kwh']
    battery_to_home = stats['battery_to_home_kwh']
    grid_to_home   = stats['grid_to_home_kwh']
    total_supplied = solar_to_home + battery_to_home + grid_to_home
    total_supplied = max(total_supplied, 0.01)

    # Shares as % of what actually fed the home (not of consumption which may differ due to measurement)
    solar_share      = round(min((solar_to_home  / total_supplied) * 100, 100), 1)
    battery_share    = round(min((battery_to_home / total_supplied) * 100, 100), 1)
    grid_share       = round(min((grid_to_home   / total_supplied) * 100, 100), 1)
    # Self-sufficiency = % of home energy NOT from grid
    self_sufficiency = round(max(0.0, 100.0 - grid_share), 1)
    avg_load = round((stats['home_consumed_kwh'] / max(len(filtered_rows), 1)) * 1000, 1) if filtered_rows else 0.0
    solar_surplus = round(max(stats['solar_generated_kwh'] - stats['solar_to_home_kwh'], 0.0), 2)

    smart_loads = _smart_load_suggestions(latest)
    return render_template(
        'reports.html',
        selected_view=selected_view, selected_date=selected_date, title_hint=title_hint,
        stats=stats, chart=chart, table_rows=table_rows,
        prev_date=prev_date, next_date=next_date, can_go_next=can_go_next,
        latest=latest, weather=weather,
        solar_share=solar_share, battery_share=battery_share, grid_share=grid_share,
        self_sufficiency=self_sufficiency, avg_load=avg_load, solar_surplus=solar_surplus,
        smart_loads=smart_loads,
        format_energy=format_energy, format_power=format_power,
        format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang(),
    )


@main_bp.route('/statistics/export/csv')
def export_statistics_csv():
    tz_name = current_app.config['LOCAL_TIMEZONE']
    selected_view, selected_date, filtered_rows, title_hint, *_ = _get_stats_context(request.args, tz_name)
    stats = compute_energy_stats(filtered_rows)
    table_rows = build_statistics_table(filtered_rows, tz_name, selected_view)

    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(['النطاق', title_hint])
    writer.writerow([])
    writer.writerow(['المؤشر', 'القيمة'])
    for label, key in [
        ('إنتاج الشمس kWh', 'solar_generated_kwh'), ('استهلاك المنزل kWh', 'home_consumed_kwh'),
        ('من الشمس إلى البيت kWh', 'solar_to_home_kwh'), ('من الشمس إلى البطارية kWh', 'solar_to_battery_kwh'),
        ('من البطارية إلى البيت kWh', 'battery_to_home_kwh'), ('من الشبكة إلى البيت kWh', 'grid_to_home_kwh'),
        ('متوسط البطارية %', 'avg_battery_soc'), ('أعلى إنتاج لحظي W', 'max_solar_w'),
    ]:
        writer.writerow([label, stats[key]])
    writer.writerow([])
    writer.writerow(['الفترة', 'شمس kWh', 'منزل kWh', 'شمس→بيت', 'شمس→بطارية', 'بطارية→بيت', 'شبكة→بيت', 'متوسط SOC'])
    for row in table_rows:
        writer.writerow([row['label'], row['solar_generated_kwh'], row['home_consumed_kwh'],
                         row['solar_to_home_kwh'], row['solar_to_battery_kwh'],
                         row['battery_to_home_kwh'], row['grid_to_home_kwh'], row['avg_battery_soc']])
    output = sio.getvalue().encode('utf-8-sig')
    filename = f"statistics_{selected_view}_{selected_date.strftime('%Y-%m-%d')}.csv"
    return Response(output, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename={filename}'})


@main_bp.route('/statistics/export/pdf')
def export_statistics_pdf():
    tz_name = current_app.config['LOCAL_TIMEZONE']
    selected_view, selected_date, filtered_rows, title_hint, *_ = _get_stats_context(request.args, tz_name)
    stats = compute_energy_stats(filtered_rows)
    table_rows = build_statistics_table(filtered_rows, tz_name, selected_view)

    def ar(text):
        try:
            return get_display(arabic_reshaper.reshape(str(text)))
        except Exception:
            return str(text)

    def _register_pdf_fonts():
        from pathlib import Path
        base_dir = Path(current_app.root_path)
        candidates = [
            (
                'NotoArabic',
                'NotoArabicBold',
                base_dir / 'static' / 'fonts' / 'NotoSansArabic-Regular.ttf',
                base_dir / 'static' / 'fonts' / 'NotoSansArabic-Bold.ttf',
            ),
            (
                'NotoArabic',
                'NotoArabicBold',
                Path('/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf'),
                Path('/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf'),
            ),
            (
                'Amiri',
                'AmiriBold',
                Path('/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Regular.ttf'),
                Path('/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Bold.ttf'),
            ),
        ]
        for regular_name, bold_name, regular_path, bold_path in candidates:
            try:
                if regular_path.exists() and bold_path.exists():
                    try:
                        pdfmetrics.getFont(regular_name)
                    except Exception:
                        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
                    try:
                        pdfmetrics.getFont(bold_name)
                    except Exception:
                        pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                    return regular_name, bold_name
            except Exception:
                continue
        return 'Helvetica', 'Helvetica-Bold'

    font_name, font_bold = _register_pdf_fonts()

    def fmt_energy_plain(v):
        try:
            v = float(v or 0)
        except Exception:
            v = 0.0
        if abs(v) >= 1000:
            return f"{v/1000:.2f} MWh"
        return f"{v:.2f} kWh"

    def fmt_percent_plain(v):
        try:
            return f"{float(v or 0):.1f}%"
        except Exception:
            return "0.0%"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title='تقرير منصة الطاقة الشمسية',
    )
    width, height = A4
    content_width = width - doc.leftMargin - doc.rightMargin

    base_styles = getSampleStyleSheet()
    styles = {
        'title': ParagraphStyle(
            'ArabicTitle',
            parent=base_styles['Title'],
            fontName=font_bold,
            fontSize=24,
            leading=30,
            textColor=colors.HexColor('#14284b'),
            alignment=1,
            spaceAfter=4,
        ),
        'subtitle': ParagraphStyle(
            'ArabicSubtitle',
            parent=base_styles['Normal'],
            fontName=font_name,
            fontSize=11,
            leading=16,
            textColor=colors.HexColor('#62748b'),
            alignment=1,
            spaceAfter=12,
        ),
        'section': ParagraphStyle(
            'ArabicSection',
            parent=base_styles['Heading2'],
            fontName=font_bold,
            fontSize=16,
            leading=22,
            textColor=colors.HexColor('#14284b'),
            alignment=2,
            spaceAfter=8,
        ),
        'body': ParagraphStyle(
            'ArabicBody',
            parent=base_styles['Normal'],
            fontName=font_name,
            fontSize=11.5,
            leading=18,
            textColor=colors.HexColor('#22324d'),
            alignment=2,
        ),
        'body_bold': ParagraphStyle(
            'ArabicBodyBold',
            parent=base_styles['Normal'],
            fontName=font_bold,
            fontSize=11.5,
            leading=18,
            textColor=colors.HexColor('#14284b'),
            alignment=2,
        ),
        'card_title': ParagraphStyle(
            'CardTitle',
            parent=base_styles['Normal'],
            fontName=font_name,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor('#5b6b84'),
            alignment=1,
        ),
        'card_value': ParagraphStyle(
            'CardValue',
            parent=base_styles['Normal'],
            fontName=font_bold,
            fontSize=20,
            leading=24,
            textColor=colors.HexColor('#14284b'),
            alignment=1,
        ),
        'card_hint': ParagraphStyle(
            'CardHint',
            parent=base_styles['Normal'],
            fontName=font_name,
            fontSize=8.5,
            leading=10,
            textColor=colors.HexColor('#8a97ab'),
            alignment=1,
        ),
        'table_header': ParagraphStyle(
            'TableHeader',
            parent=base_styles['Normal'],
            fontName=font_bold,
            fontSize=9.2,
            leading=12,
            textColor=colors.HexColor('#173057'),
            alignment=1,
        ),
        'table_cell': ParagraphStyle(
            'TableCell',
            parent=base_styles['Normal'],
            fontName=font_name,
            fontSize=9.4,
            leading=12,
            textColor=colors.HexColor('#26354d'),
            alignment=1,
        ),
    }

    def P(text, style='body'):
        return Paragraph(ar(text), styles[style])

    def metric_card(title, value, hint='', bg='#f3f7fd', accent='#8ab4f8'):
        card = Table(
            [[P(title, 'card_title')], [P(value, 'card_value')], [P(hint or ' ', 'card_hint')]],
            colWidths=[4.35 * cm],
            rowHeights=[0.7 * cm, 0.95 * cm, 0.45 * cm],
        )
        card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg)),
            ('LINEABOVE', (0, 0), (-1, 0), 3, colors.HexColor(accent)),
            ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d7e3f4')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROUNDEDCORNERS', [12, 12, 12, 12]),
        ]))
        return card

    story = []
    story.append(P('تقرير منصة الطاقة الشمسية', 'title'))
    story.append(P(f'التاريخ: {selected_date.strftime("%Y-%m-%d")}   •   الفترة: {title_hint}', 'subtitle'))

    cards = [
        metric_card('إنتاج الشمس', fmt_energy_plain(stats['solar_generated_kwh']), 'إجمالي التوليد خلال الفترة', '#eef6ff', '#f59e0b'),
        metric_card('استهلاك المنزل', fmt_energy_plain(stats['home_consumed_kwh']), 'إجمالي الاستهلاك خلال الفترة', '#fdf2f8', '#ec4899'),
        metric_card('شحن البطارية من الشمس', fmt_energy_plain(stats['solar_to_battery_kwh']), 'الطاقة المخزنة في البطارية', '#effaf6', '#10b981'),
        metric_card('متوسط البطارية', fmt_percent_plain(stats['avg_battery_soc']), 'متوسط نسبة الشحن', '#f5f3ff', '#8b5cf6'),
    ]
    cards_table = Table([cards], colWidths=[4.35 * cm] * 4, hAlign='CENTER')
    cards_table.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(cards_table)
    story.append(Spacer(1, 0.45 * cm))

    summary_items = [
        f"• من الشمس إلى البيت: {fmt_energy_plain(stats['solar_to_home_kwh'])}",
        f"• من الشبكة إلى البيت: {fmt_energy_plain(stats['grid_to_home_kwh'])}",
        f"• من البطارية إلى البيت: {fmt_energy_plain(stats['battery_to_home_kwh'])}",
        f"• أعلى إنتاج لحظي: {format_power(stats['max_solar_w'])} واط",
    ]
    summary_rows = [[P('ملخص الفترة', 'section')]] + [[P(item, 'body')] for item in summary_items]
    summary_block = Table(summary_rows, colWidths=[content_width])
    summary_block.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#d9e4f2')),
        ('LINEABOVE', (0, 0), (-1, 0), 3, colors.HexColor('#c7d8ee')),
        ('LEFTPADDING', (0, 0), (-1, -1), 16),
        ('RIGHTPADDING', (0, 0), (-1, -1), 16),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ROUNDEDCORNERS', [12, 12, 12, 12]),
    ]))
    story.append(summary_block)
    story.append(Spacer(1, 0.4 * cm))

    story.append(P('الجدول التحليلي', 'section'))

    headers = ['SOC', 'شبكة ← بيت', 'بطارية ← بيت', 'شمس ← بطارية', 'شمس ← بيت', 'المنزل', 'الشمس', 'الفترة']
    table_data = [[P(h, 'table_header') for h in headers]]
    for row in table_rows[:24]:
        table_data.append([
            P(f"{row['avg_battery_soc']}%", 'table_cell'),
            P(f"{float(row['grid_to_home_kwh'] or 0):.2f}", 'table_cell'),
            P(f"{float(row['battery_to_home_kwh'] or 0):.2f}", 'table_cell'),
            P(f"{float(row['solar_to_battery_kwh'] or 0):.2f}", 'table_cell'),
            P(f"{float(row['solar_to_home_kwh'] or 0):.2f}", 'table_cell'),
            P(f"{float(row['home_consumed_kwh'] or 0):.2f}", 'table_cell'),
            P(f"{float(row['solar_generated_kwh'] or 0):.2f}", 'table_cell'),
            P(str(row['label']), 'table_cell'),
        ])

    analytic_table = Table(
        table_data,
        colWidths=[1.7 * cm, 2.15 * cm, 2.15 * cm, 2.15 * cm, 2.15 * cm, 1.85 * cm, 1.85 * cm, 2.35 * cm],
        repeatRows=1,
        hAlign='CENTER',
    )
    analytic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9f1fb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#173057')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#d3deed')),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, colors.HexColor('#dce5f2')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('ROUNDEDCORNERS', [10, 10, 10, 10]),
    ]))
    story.append(analytic_table)

    def _paint_page(canv, _doc):
        canv.saveState()
        canv.setFillColor(colors.HexColor('#f8fbff'))
        canv.rect(0, 0, width, height, stroke=0, fill=1)
        canv.setFillColor(colors.HexColor('#dbe8f7'))
        canv.roundRect(doc.leftMargin, height - 1.0 * cm, content_width, 0.08 * cm, 0.04 * cm, stroke=0, fill=1)
        canv.setStrokeColor(colors.HexColor('#e6eef9'))
        canv.setLineWidth(0.8)
        canv.line(doc.leftMargin, 1.0 * cm, width - doc.rightMargin, 1.0 * cm)
        canv.setFont(font_name, 8)
        canv.setFillColor(colors.HexColor('#7b8aa4'))
        footer = ar('منصة الطاقة الشمسية • تقرير تحليلي')
        canv.drawRightString(width - doc.rightMargin, 0.62 * cm, footer)
        canv.restoreState()

    doc.build(story, onFirstPage=_paint_page, onLaterPages=_paint_page)
    buf.seek(0)
    filename = f"taqrir_{selected_view}_{selected_date.strftime('%Y-%m-%d')}.pdf"
    return Response(buf.getvalue(), mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename={filename}'})


@main_bp.route('/deye', methods=['GET', 'POST'])
def deye_settings():
    settings = load_settings()
    if request.method == 'POST':
        save_settings_from_form(request.form)
        flash('تم حفظ إعدادات الربط', 'success')
        return redirect(url_for('main.deye_settings'))
    return render_template('deye_settings.html', settings=settings)


@main_bp.route('/test-connection', methods=['POST'])
def test_connection():
    client = DeyeClient(load_settings())
    try:
        token = client.obtain_token()
        account = client.account_info(token)
        stations = client.station_list(token)
        log_event('success', 'تم اختبار الاتصال مع Deye بنجاح', {'account': account, 'stations_count': len(stations)})
        flash(f'تم الاتصال بنجاح. عدد المحطات: {len(stations)}', 'success')
    except Exception as exc:
        log_event('danger', f'فشل اختبار الاتصال: {exc}')
        flash(f'فشل اختبار الاتصال: {exc}', 'danger')
    return redirect(url_for('main.deye_settings'))


def sync_now_internal(trigger='manual'):
    client = DeyeClient(load_settings())
    snapshot = client.snapshot()
    previous = Reading.query.order_by(Reading.created_at.desc()).first()
    # Extract device_detail metrics for direct columns
    # Pull all fields directly from device_data (flat dict from device/latest)
    _d = snapshot.raw.get('device_data') or {}
    _dr = snapshot.raw.get('derived') or {}

    def _fv(key, default=None):
        v = _d.get(key)
        if v is None: return default
        try: return float(v)
        except: return default

    reading = Reading(
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
    db.session.commit()
    try:
        process_notifications(reading, previous)
    except Exception as notify_exc:
        log_event('warning', f'تعذر تنفيذ الإشعارات: {notify_exc}')
    if trigger == 'manual':
        log_event('success', 'تمت مزامنة قراءة جديدة بنجاح', snapshot.raw)
    else:
        log_event('info', 'مزامنة تلقائية', {'created_at': reading.created_at.isoformat()})
    # Prune old logs periodically (on every auto-sync)
    if trigger == 'auto':
        try:
            prune_old_logs()
        except Exception:
            pass
    return reading


@main_bp.route('/sync-now', methods=['POST'])
def sync_now():
    try:
        sync_now_internal(trigger='manual')
        flash('تمت المزامنة وجلب البيانات بنجاح', 'success')
    except Exception as exc:
        log_event('danger', f'فشلت المزامنة: {exc}')
        flash(f'فشلت المزامنة: {exc}', 'danger')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/diagnostics')
def diagnostics():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    raw_data = {}
    raw_text = '{}'
    if latest and latest.raw_json:
        try:
            raw_data = json.loads(latest.raw_json)
            raw_text = to_json(raw_data)
        except Exception:
            raw_data = {'raw_text': latest.raw_json}
            raw_text = latest.raw_json
    return render_template('diagnostics.html', latest=latest, raw_data=raw_data, raw_text=raw_text,
                           format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']), ui_lang=_lang())


@main_bp.route('/live-data')
def live_data():
    from datetime import UTC, datetime, timedelta
    from ..services.utils import utc_to_local
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    tz_name = current_app.config['LOCAL_TIMEZONE']
    settings = load_settings()

    # استخراج device_data من raw_json
    d = {}
    if latest and latest.raw_json:
        try:
            raw = json.loads(latest.raw_json)
            d = raw.get('device_data') or {}
        except Exception:
            pass

    # حساب الاستهلاك اليومي من القراءات المحلية — آخر 30 يوم
    daily_consumption_history = []
    try:
        now_local = utc_to_local(datetime.now(UTC), tz_name)
        for days_ago in range(0, 30):
            day = (now_local - timedelta(days=days_ago)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            day_end = day + timedelta(days=1)
            # تحويل للـ UTC
            from zoneinfo import ZoneInfo
            day_utc = day.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC).replace(tzinfo=None)
            day_end_utc = day_end.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC).replace(tzinfo=None)
            rows = (Reading.query
                    .filter(Reading.created_at >= day_utc, Reading.created_at < day_end_utc)
                    .order_by(Reading.created_at.asc()).all())
            if not rows:
                continue
            # استخدام القيم اليومية من أحدث قراءة في اليوم (من device/latest مباشرة)
            last_row = rows[-1]
            last_d = {}
            if last_row.raw_json:
                try:
                    last_d = json.loads(last_row.raw_json).get('device_data') or {}
                except Exception:
                    pass
            prod = last_d.get('dailyProductionActive') or 0
            cons = last_d.get('dailyConsumption') or 0
            chg  = last_d.get('dailyChargingEnergy') or 0
            dis  = last_d.get('dailyDischargingEnergy') or 0
            daily_consumption_history.append({
                'date': day.strftime('%Y-%m-%d'),
                'production': format_energy(float(prod)),
                'consumption': format_energy(float(cons)),
                'charging': format_energy(float(chg)),
                'discharging': format_energy(float(dis)),
            })
    except Exception:
        daily_consumption_history = []

    return render_template('live_data.html',
                           latest=latest, d=d, settings=settings,
                           daily_consumption_history=daily_consumption_history,
                           format_energy=format_energy,
                           format_power=format_power,
                           format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang())


@main_bp.route('/devices')
def devices():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    settings = load_settings()
    battery_details = build_battery_details(latest)
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    tz_name = current_app.config['LOCAL_TIMEZONE']
    production_summary = get_production_summary(tz_name)
    return render_template('devices.html', latest=latest, settings=settings,
                           battery_details=battery_details,
                           battery_insights=battery_insights,
                           system_state=system_state,
                           production_summary=production_summary,
                           format_energy=format_energy,
                           format_power=format_power,
                           format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang())


@main_bp.route('/battery-lab')
def battery_lab():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    tz_name = current_app.config['LOCAL_TIMEZONE']
    battery_details = build_battery_details(latest)
    settings = load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)

    # نجمع القراءات على مستوى الساعة بدل كل 5-10 دقائق حتى يكون الرسم أهدأ وأسهل للقراءة.
    local_tz = ZoneInfo(tz_name)
    now_local = datetime.now(local_tz)
    since_utc = now_local.replace(minute=0, second=0, microsecond=0).astimezone(UTC) - timedelta(hours=47)
    hourly_rows = (
        Reading.query
        .filter(Reading.created_at >= since_utc)
        .order_by(Reading.created_at.asc())
        .all()
    )

    grouped_by_hour = {}
    for row in hourly_rows:
        local_dt = utc_to_local(row.created_at, tz_name)
        hour_key = local_dt.strftime('%Y-%m-%d %H:00')
        grouped_by_hour[hour_key] = row  # نحتفظ بآخر قراءة داخل كل ساعة

    hourly_points = list(grouped_by_hour.values())[-48:]
    labels = [utc_to_local(r.created_at, tz_name).strftime('%I:%M %p').lstrip('0').replace('AM', 'ص').replace('PM', 'م') for r in hourly_points]
    soc_values = [round(float(r.battery_soc or 0), 1) for r in hourly_points]
    power_values = [round(float(r.battery_power or 0), 1) for r in hourly_points]

    voltage_values, current_values = [], []
    for r in hourly_points:
        d = build_battery_details(r)
        voltage_values.append(d.get('battery_voltage'))
        current_values.append(d.get('battery_current'))

    return render_template(
        'battery_lab.html',
        latest=latest, battery_details=battery_details, battery_insights=battery_insights,
        labels=labels, soc_values=soc_values, power_values=power_values,
        voltage_values=voltage_values, current_values=current_values,
        format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang(),
    )




@main_bp.route('/loads', methods=['GET', 'POST'])
def loads_page():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    weather = get_weather_for_latest(latest)
    settings = load_settings()
    tz_name = current_app.config['LOCAL_TIMEZONE']
    now_local = utc_to_local(datetime.now(UTC), tz_name) or datetime.now(UTC)
    saved_night_max_w = safe_float(settings.get('night_max_load_w'), 500)
    raw_sim = request.form.get('simulate_max_w') if request.method == 'POST' else request.args.get('simulate_max_w')
    simulate_max_w = safe_float(raw_sim, saved_night_max_w)
    simulation = _manual_load_planner(latest, simulate_max_w, weather=weather, now_local=now_local) if simulate_max_w > 0 else None

    if request.method == 'POST':
        action = (request.form.get('action') or 'add').strip()
        if action == 'add':
            name = (request.form.get('name') or '').strip()
            power_w = safe_float(request.form.get('power_w'), 0)
            priority = int(safe_float(request.form.get('priority'), 1) or 1)
            if name and power_w > 0:
                db.session.add(UserLoad(name=name, power_w=power_w, priority=max(priority, 1), is_enabled=True))
                db.session.commit()
                flash('تمت إضافة الحمل بنجاح', 'success')
            else:
                flash('أدخل اسم الجهاز والقدرة بشكل صحيح', 'warning')
            return redirect(url_for('main.loads_page', lang=_lang(), simulate_max_w=int(simulate_max_w or 0) if simulate_max_w > 0 else None))
        elif action == 'toggle':
            row = UserLoad.query.get(int(request.form.get('load_id') or 0))
            if row:
                row.is_enabled = not row.is_enabled
                db.session.commit()
                flash('تم تحديث حالة الحمل', 'success')
            return redirect(url_for('main.loads_page', lang=_lang(), simulate_max_w=int(simulate_max_w or 0) if simulate_max_w > 0 else None))
        elif action == 'delete':
            row = UserLoad.query.get(int(request.form.get('load_id') or 0))
            if row:
                db.session.delete(row)
                db.session.commit()
                flash('تم حذف الحمل', 'success')
            return redirect(url_for('main.loads_page', lang=_lang(), simulate_max_w=int(simulate_max_w or 0) if simulate_max_w > 0 else None))
        elif action == 'save_night_limit':
            save_value = safe_float(request.form.get('night_max_w'), 0)
            if save_value > 0:
                _save_setting_value('night_max_load_w', str(int(round(save_value))))
                db.session.commit()
                saved_night_max_w = save_value
                simulate_max_w = save_value
                simulation = _manual_load_planner(latest, simulate_max_w, weather=weather, now_local=now_local)
                flash('تم حفظ أقصى حمل ليلي بنجاح', 'success')
            else:
                flash('أدخل قيمة صحيحة للحمل الليلي', 'warning')
            return redirect(url_for('main.loads_page', lang=_lang(), simulate_max_w=int(simulate_max_w or 0) if simulate_max_w > 0 else None))
        elif action == 'simulate':
            if simulate_max_w <= 0:
                flash('حدد قيمة أقصى حمل للتجربة أولاً', 'warning')
            else:
                flash('تم تحديث تجربة اقتراح الأحمال', 'success')
        elif action == 'send_telegram_loads':
            settings = load_settings()
            title = '⚡ اقتراح الأحمال الآن'
            if simulation and simulate_max_w > 0:
                lines = [
                    '🧪 تجربة اقتراح الأحمال',
                    simulation.get('mode_ar', ''),
                    f"🔌 الحد المحدد: {int(round(simulation.get('max_allowed_w', 0)))}W" if simulation.get('mode') == 'night' else f"☀️ الفائض الشمسي: {int(round(simulation.get('available_w', 0)))}W",
                    f"🏠 الحمل الحالي: {int(round(simulation.get('current_load_w', 0)))}W",
                    f"⚡ المتاح: {int(round(simulation.get('available_w', 0)))}W",
                    '',
                ]
                fit = simulation.get('fit') or []
                if fit:
                    lines.append('يمكنك تشغيل الآن فقط الأجهزة الأقل من المتاح:')
                    for row in fit[:8]:
                        lines.append(f"✔ {row.get('name')} — {int(round(float(row.get('power_w') or 0)))}W")
                else:
                    lines.append('⚠️ لا يوجد جهاز مناسب ضمن هذا الحد حاليًا.')
                message = '\n'.join(lines)
            else:
                message = build_telegram_quick_reply('loads', latest, weather)
            ok, _resp = send_telegram_message(settings, title, message)
            if ok:
                send_telegram_menu(settings)
                flash('تم إرسال اقتراح الأحمال إلى Telegram', 'success')
            else:
                flash('فشل إرسال اقتراح الأحمال إلى Telegram. راجع إعدادات البوت.', 'warning')
            return redirect(url_for('main.loads_page', lang=_lang(), simulate_max_w=int(simulate_max_w or 0) if simulate_max_w > 0 else None))

    loads = _serialize_loads()
    smart_loads = _smart_load_suggestions(latest, settings=settings)
    return render_template('loads.html', latest=latest, loads=loads, smart_loads=smart_loads, simulation=simulation,
                           saved_night_max_w=saved_night_max_w,
                           format_power=format_power, format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang())


@main_bp.route('/alerts')
def alerts():
    logs = SyncLog.query.order_by(SyncLog.created_at.desc()).limit(200).all()
    return render_template('alerts.html', logs=logs,
                           format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']), ui_lang=_lang())





def _telegram_multilink_secret():
    return current_app.config.get('TELEGRAM_WEBHOOK_SECRET') or 'multilink'

def _build_telegram_multilink_context():
    link = None
    try:
        from ..services.telegram_link_service import get_current_owner_link
        link = get_current_owner_link()
    except Exception:
        link = None
    webhook_url = None
    try:
        root = (request.url_root or '').rstrip('/')
        if root:
            webhook_url = f"{root}{url_for('main.telegram_multilink_webhook', secret=_telegram_multilink_secret())}"
    except Exception:
        webhook_url = None
    return link, webhook_url

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

@main_bp.route('/notifications/action', methods=['POST'])
def notifications_action():
    action = (request.args.get('action') or request.form.get('notification_action') or '').strip().lower()
    section = (request.args.get('section') or request.form.get('section') or '').strip().lower()
    if not action:
        flash('الإجراء المطلوب غير محدد.', 'warning')
        return redirect(url_for('main.notifications_settings'))
    try:
        settings = apply_form_settings_overrides(load_settings(), request.form)
        latest = Reading.query.order_by(Reading.created_at.desc()).first()
        weather = get_weather_for_latest(latest)
        if section == 'quick_telegram':
            payload = {'section':'quick_telegram','title':'اختبار إشعار','message':'هذه رسالة اختبار من منصة الطاقة الشمسية.','channel':'telegram','rule_name':'اختبار Telegram','event_key':f"test-telegram-{int(datetime.now(UTC).timestamp())}",'level':'info','success_message':'تم إرسال اختبار Telegram بنجاح','preview_message':'هذه رسالة الاختبار السريعة لقناة Telegram'}
        elif section == 'quick_both':
            payload = {'section':'quick_both','title':'اختبار إشعار','message':'هذه رسالة اختبار من منصة الطاقة الشمسية.','channel':'both','rule_name':'اختبار القناتين','event_key':f"test-both-{int(datetime.now(UTC).timestamp())}",'level':'info','success_message':'تم إرسال اختبار القناتين','preview_message':'هذه رسالة الاختبار السريعة للقناتين'}
        elif section == 'telegram_menu':
            payload = {'section':'telegram_menu','title':'📋 قائمة Telegram','message':'اختر ما تريد فحصه الآن من الأزرار التالية:','channel':'telegram','rule_name':'قائمة Telegram','event_key':f"test-telegram-menu-{int(datetime.now(UTC).timestamp())}",'level':'info','success_message':'تم إرسال قائمة Telegram بنجاح','preview_message':'سيتم إرسال قائمة أزرار Telegram التفاعلية إلى المحادثة.'}
        else:
            payload = _build_notification_test_payload(section, settings, latest, weather)
        if action == 'preview':
            _store_notification_preview(payload)
            flash(payload.get('preview_message') or 'تم تحديث المعاينة بنجاح', 'info')
            return redirect(url_for('main.notifications_settings'))
        if action != 'send':
            flash('الإجراء غير معروف.', 'warning')
            return redirect(url_for('main.notifications_settings'))
        if section == 'telegram_menu':
            ok, resp = send_telegram_menu(settings)
            flash(payload.get('success_message') if ok else f'فشل إرسال قائمة Telegram: {resp}', 'success' if ok else 'danger')
            log_notification(payload['event_key'], payload['rule_name'], payload['title'], payload['message'], 'telegram', 'success' if ok else 'danger', resp, force=True)
            return redirect(url_for('main.notifications_settings'))
        dispatch_notification(settings, payload['event_key'], payload['rule_name'], payload['title'], payload['message'], payload.get('channel','telegram'), payload.get('level','info'), dedupe_minutes=0)
        _store_notification_preview(payload)
        flash(payload.get('success_message') or 'تم إرسال الاختبار بنجاح', 'success')
        return redirect(url_for('main.notifications_settings'))
    except Exception as exc:
        flash(f'خطأ أثناء تنفيذ الطلب: {exc}', 'danger')
        return redirect(url_for('main.notifications_settings'))

@main_bp.route('/notifications', methods=['GET', 'POST'])
def notifications_settings():
    settings = load_settings()
    if request.method == 'POST':
        save_notification_settings_from_form(request.form)
        if _is_ajax_request():
            return _json_response(True, 'تم حفظ إعدادات الإشعارات بنجاح')
        flash('تم حفظ إعدادات الإشعارات بنجاح', 'success')
        return redirect(url_for('main.notifications_settings'))
    rules = load_notification_rules(settings)
    recent_notifications = NotificationLog.query.order_by(NotificationLog.created_at.desc()).limit(30).all()
    notification_preview = session.pop('notification_preview', None)
    telegram_link = get_link_by_owner(_current_owner_key())
    webhook_url = url_for('main.telegram_webhook', secret=(settings.get('telegram_webhook_secret') or current_app.config['SECRET_KEY'][:24]), _external=True)
    return render_template(
        'notifications.html', settings=settings, rules=rules,
        recent_notifications=recent_notifications,
        notification_preview=notification_preview,
        telegram_link=telegram_link,
        telegram_link_command=_telegram_link_command(telegram_link),
        telegram_webhook_url=webhook_url,
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )


@main_bp.route('/notifications/test', methods=['POST'])
def notifications_test_send():
    try:
        settings = load_settings()
        channel = request.form.get('channel', 'telegram').strip().lower()
        title = 'اختبار إشعار'
        message = 'هذه رسالة اختبار من منصة الطاقة الشمسية.'
        results = []
        if channel in {'telegram', 'both'}:
            ok, resp = send_telegram_message(settings, title, message)
            results.append(f"Telegram: {'نجح' if ok else 'فشل'}")
            log_notification('test_telegram', 'اختبار Telegram', title, message, 'telegram', 'success' if ok else 'danger', resp, force=True)
        if channel in {'sms', 'both'}:
            ok, resp = send_sms_message(settings, title, message)
            results.append(f"SMS: {'نجح' if ok else 'فشل'}")
            log_notification('test_sms', 'اختبار SMS', title, message, 'sms', 'success' if ok else 'danger', resp, force=True)
        message = ' | '.join(results) if results else 'لم يتم اختيار قناة'
        if _is_ajax_request():
            return _json_response(bool(results), message)
        flash(message, 'info' if results else 'warning')
        return redirect(url_for('main.notifications_settings'))
    except Exception as exc:
        if _is_ajax_request():
            return _json_response(False, f'خطأ أثناء اختبار الإشعار: {exc}'), 500
        flash(f'خطأ أثناء اختبار الإشعار: {exc}', 'danger')
        return redirect(url_for('main.notifications_settings'))


@main_bp.route('/notifications/test-section', methods=['POST'])
def notifications_test_section():
    try:
        section = request.form.get('section', 'periodic').strip().lower()
        settings = apply_form_settings_overrides(load_settings(), request.form)
        latest = Reading.query.order_by(Reading.created_at.desc()).first()
        weather = get_weather_for_latest(latest)
        now_ts = int(datetime.now(UTC).timestamp())
        sent_message = ''
        sent_title = ''
        sent_channel = 'telegram'

        if section in ('periodic', 'periodic_day'):
            sent_title, sent_message = build_periodic_status_message(latest, weather, settings=settings, phase_override='day')
            sent_channel = settings.get('periodic_day_channel', 'telegram')
            dispatch_notification(settings, f'test-periodic-day-{now_ts}', 'اختبار دوري نهاري', sent_title, sent_message, sent_channel, 'info', dedupe_minutes=0)
            result_message = 'تم إرسال اختبار التحديث الدوري النهاري'
        elif section in ('periodic_night', 'night'):
            sent_title, sent_message = build_periodic_status_message(latest, weather, settings=settings, phase_override='night')
            sent_channel = settings.get('periodic_night_channel', 'telegram')
            dispatch_notification(settings, f'test-periodic-night-{now_ts}', 'اختبار دوري ليلي', sent_title, sent_message, sent_channel, 'info', dedupe_minutes=0)
            result_message = 'تم إرسال اختبار التحديث الدوري الليلي'
        elif section in ('charge', 'battery'):
            sent_title = '🧪 اختبار حالة البطارية'
            sent_channel = settings.get('battery_test_channel', 'telegram')
            _sent_title2, base_message = build_periodic_status_message(latest, weather, settings=settings, phase_override='day')
            sent_message = base_message
            dispatch_notification(settings, f'test-battery-{now_ts}', 'اختبار البطارية', sent_title, sent_message, sent_channel, 'warning', dedupe_minutes=0)
            result_message = 'تم إرسال اختبار حالة البطارية'
        elif section == 'weather':
            from ..blueprints.notifications import _format_weather_check
            sent_title = '☁️ اختبار تنبيه الطقس'
            sent_message = _format_weather_check(latest, weather, settings=settings)
            sent_channel = settings.get('weather_test_channel', 'telegram')
            dispatch_notification(settings, f'test-weather-{now_ts}', 'اختبار الطقس', sent_title, sent_message, sent_channel, 'info', dedupe_minutes=0)
            result_message = 'تم إرسال اختبار تنبيه الطقس'
        elif section == 'sunset':
            sent_title, sent_message, level = build_pre_sunset_message(latest, weather, settings=settings)
            sent_channel = settings.get('pre_sunset_channel', 'telegram')
            dispatch_notification(settings, f'test-sunset-{now_ts}', 'اختبار الغروب', sent_title, sent_message, sent_channel, level, dedupe_minutes=0)
            result_message = 'تم إرسال اختبار تحليل الغروب'
        elif section == 'daily_report':
            sent_title, sent_message = build_daily_morning_report_message(latest, settings=settings)
            sent_channel = settings.get('daily_report_channel', 'telegram')
            dispatch_notification(settings, f'test-daily-report-{now_ts}', 'اختبار تقرير الصباح', sent_title, sent_message, sent_channel, 'info', dedupe_minutes=0)
            result_message = 'تم إرسال تقرير الصباح التجريبي'
        elif section == 'discharge':
            sent_title = '🌙 تنبيه التفريغ الليلي'
            _sent_title2, sent_message = build_periodic_status_message(latest, weather, settings=settings, phase_override='night')
            sent_channel = settings.get('night_discharge_channel', 'telegram')
            dispatch_notification(settings, f'test-discharge-{now_ts}', 'اختبار التفريغ', sent_title, sent_message, sent_channel, 'warning', dedupe_minutes=0)
            result_message = 'تم إرسال اختبار التفريغ الليلي'
        elif section == 'load':
            sent_title = '⚡ إشعار الأحمال القابلة للتشغيل والممنوعة'
            sent_message = build_telegram_quick_reply('loads', latest, weather, settings=settings)
            sent_channel = settings.get('load_alert_channel', 'telegram')
            dispatch_notification(settings, f'test-load-{now_ts}', 'اختبار الأحمال', sent_title, sent_message, sent_channel, 'info', dedupe_minutes=0)
            result_message = 'تم إرسال اختبار إشعار الأحمال'
        else:
            if _is_ajax_request():
                return _json_response(False, 'قسم الاختبار غير معروف'), 400
            flash('قسم الاختبار غير معروف', 'warning')
            return redirect(url_for('main.notifications_settings'))

        if _is_ajax_request():
            return _json_response(True, result_message, title=sent_title, preview=sent_message, channel=sent_channel)
        flash(result_message, 'success')
        return redirect(url_for('main.notifications_settings'))
    except Exception as exc:
        if _is_ajax_request():
            return _json_response(False, f'خطأ أثناء اختبار القسم: {exc}'), 500
        flash(f'خطأ أثناء اختبار القسم: {exc}', 'danger')
        return redirect(url_for('main.notifications_settings'))





@main_bp.route('/channels', methods=['GET'])
def channels():
    telegram_link, telegram_webhook_url = _build_telegram_multilink_context()

    sms_settings = {}
    try:
        from .helpers import load_settings
        settings = load_settings()
        sms_settings = {
            'provider': settings.get('sms_provider', ''),
            'sender_name': settings.get('sms_sender_name', ''),
            'test_phone': settings.get('sms_test_phone', ''),
            'enabled': str(settings.get('sms_enabled', 'false')).lower() == 'true',
        }
    except Exception:
        sms_settings = {
            'provider': '',
            'sender_name': '',
            'test_phone': '',
            'enabled': False,
        }

    return render_template(
        'channels.html',
        telegram_link=telegram_link,
        telegram_webhook_url=telegram_webhook_url,
        sms_settings=sms_settings,
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )

@main_bp.route('/telegram/link/create', methods=['POST'])
def telegram_link_create():
    settings = load_settings()
    if not (settings.get('telegram_bot_token') or '').strip():
        flash('أدخل أولًا Bot Token الخاص بـ Telegram ثم احفظ الإعدادات.', 'warning')
        return redirect(url_for('main.notifications_settings'))
    expiry_minutes = int(safe_float(settings.get('telegram_link_expiry_minutes', '10'), 10) or 10)
    link = create_link_token(_current_owner_key(), _current_owner_label(), expiry_minutes=expiry_minutes)
    flash('تم إنشاء رمز ربط جديد. انسخ الأمر وأرسله إلى البوت في المحادثة الخاصة.', 'success')
    return redirect(url_for('main.notifications_settings'))


@main_bp.route('/telegram/link/revoke', methods=['POST'])
def telegram_link_revoke():
    ok, message = revoke_link(_current_owner_key())
    flash(message, 'success' if ok else 'warning')
    return redirect(url_for('main.notifications_settings'))


@main_bp.route('/telegram/link/test', methods=['POST'])
def telegram_link_test():
    settings = load_settings()
    link = get_link_by_owner(_current_owner_key())
    if not link or not link.telegram_chat_id or link.link_status != 'linked':
        flash('اربط حساب Telegram أولًا قبل إرسال الاختبار.', 'warning')
        return redirect(url_for('main.notifications_settings'))
    ok, resp = send_telegram_message(settings, 'اختبار Telegram', 'تمت رسالة الاختبار من داخل المنصة بنجاح ✅', chat_id=link.telegram_chat_id)
    flash('تم إرسال رسالة الاختبار إلى Telegram.' if ok else f'فشل إرسال الاختبار: {resp}', 'success' if ok else 'danger')
    return redirect(url_for('main.notifications_settings'))


@main_bp.route('/telegram/link/menu', methods=['POST'])
def telegram_link_menu():
    settings = load_settings()
    link = get_link_by_owner(_current_owner_key())
    if not link or not link.telegram_chat_id or link.link_status != 'linked':
        flash('اربط حساب Telegram أولًا قبل إرسال القائمة التفاعلية.', 'warning')
        return redirect(url_for('main.notifications_settings'))
    ok, resp = send_telegram_menu(settings, chat_id=link.telegram_chat_id, intro='تم إرسال القائمة التفاعلية الخاصة بحسابك ✅')
    flash('تم إرسال القائمة التفاعلية إلى Telegram.' if ok else f'فشل إرسال القائمة: {resp}', 'success' if ok else 'danger')
    return redirect(url_for('main.notifications_settings'))



@main_bp.route('/telegram/link/send-menu', methods=['POST'])
def telegram_link_send_menu():
    try:
        settings = load_settings()
        owner_key = None
        try:
            owner_key = get_owner_key()
        except Exception:
            owner_key = 'default'
        link = None
        try:
            link = get_link_by_owner(owner_key)
        except Exception:
            link = None
        if not link or not getattr(link, 'telegram_chat_id', None):
            flash('لا يوجد ربط Telegram نشط لإرسال القائمة.', 'warning')
            return redirect(url_for('main.channels'))
        ok, resp = send_telegram_menu(settings, chat_id=str(link.telegram_chat_id))
        flash('تم إرسال القائمة بنجاح.' if ok else f'فشل إرسال القائمة: {resp}', 'success' if ok else 'danger')
    except Exception as exc:
        flash(f'خطأ أثناء إرسال القائمة: {exc}', 'danger')
    return redirect(url_for('main.channels'))

@main_bp.route('/telegram/multilink-webhook/<secret>', methods=['POST'])
def telegram_multilink_webhook(secret):
    settings = load_settings()
    expected = (settings.get('telegram_webhook_secret') or current_app.config['SECRET_KEY'][:24]).strip()
    if not expected or secret != expected:
        return jsonify({'ok': False, 'message': 'invalid secret'}), 403

    update = request.get_json(silent=True) or {}
    callback = update.get('callback_query') or {}
    message = update.get('message') or callback.get('message') or {}
    chat = message.get('chat') or {}
    user = message.get('from') or callback.get('from') or {}

    chat_type = str(chat.get('type') or '').strip().lower()
    chat_id = str(chat.get('id') or '').strip()
    text = str(message.get('text') or '').strip()

    # ربط المحادثة الخاصة فقط
    if chat_type and chat_type != 'private':
        if callback.get('id'):
            try:
                _telegram_api_call(settings, 'answerCallbackQuery', {'callback_query_id': callback.get('id'), 'text': 'استخدم المحادثة الخاصة مع البوت للربط.'})
            except Exception:
                pass
        return jsonify({'ok': True, 'message': 'ignored-non-private'})

    if text.startswith('/start link_'):
        token = text.split(maxsplit=1)[1].strip() if ' ' in text else ''
        ok, reply, _link = consume_link_token(token, {
            'telegram_user_id': str(user.get('id') or '').strip(),
            'telegram_chat_id': chat_id,
            'telegram_username': user.get('username') or '',
            'telegram_first_name': user.get('first_name') or '',
            'telegram_last_name': user.get('last_name') or '',
        })
        send_telegram_message(settings, 'ربط Telegram', reply, chat_id=chat_id)
        return jsonify({'ok': ok, 'message': reply})

    link = touch_link_by_chat_id(chat_id)
    if not link:
        if chat_id:
            send_telegram_message(settings, 'ربط Telegram', 'هذه المحادثة غير مربوطة بعد. أنشئ رمز ربط من داخل المنصة ثم أرسل أمر /start المخصص.', chat_id=chat_id)
        return jsonify({'ok': True, 'message': 'unlinked-chat'})

    ok, resp = process_telegram_update(settings, update)
    return jsonify({'ok': ok, 'message': resp})

@main_bp.route('/telegram/menu/send', methods=['POST'])
def telegram_send_menu_route():
    try:
        settings = load_settings()
        ok, _resp = send_telegram_menu(settings)
        message = 'تم إرسال قائمة الأزرار إلى Telegram' if ok else 'فشل إرسال قائمة Telegram'
        if _is_ajax_request():
            return _json_response(ok, message)
        flash(message, 'success' if ok else 'warning')
        return redirect(request.referrer or url_for('main.notifications_settings'))
    except Exception as exc:
        if _is_ajax_request():
            return _json_response(False, f'خطأ أثناء إرسال القائمة: {exc}'), 500
        flash(f'خطأ أثناء إرسال القائمة: {exc}', 'danger')
        return redirect(request.referrer or url_for('main.notifications_settings'))


@main_bp.route('/telegram/multilink-webhook', methods=['GET', 'POST'])
def telegram_multilink_webhook_2():
    if request.method == 'GET':
        return {'ok': True, 'message': 'Telegram webhook is ready'}
    settings = load_settings()
    payload = request.get_json(silent=True) or {}
    ok, resp = process_telegram_update(settings, payload)
    return {'ok': ok, 'message': resp[:200] if isinstance(resp, str) else 'processed'}


@main_bp.route('/plant-info')
def plant_info():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    settings = load_settings()
    tz_name = current_app.config['LOCAL_TIMEZONE']
    production_summary = get_production_summary(tz_name)
    return render_template('plant_info.html', latest=latest, settings=settings,
                           production_summary=production_summary,
                           format_energy=format_energy,
                           format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang())


@main_bp.route('/api/raw-debug')
def api_raw_debug():
    latest = Reading.query.order_by(Reading.created_at.desc()).first()
    if not latest:
        return {'ok': False, 'error': 'No reading found'}
    try:
        raw = json.loads(latest.raw_json) if latest.raw_json else {}
    except Exception:
        raw = {'raw_text': latest.raw_json}

    # Also try live device list call for debugging
    device_list_result = []
    device_detail_test = {}
    try:
        from ..services.deye_client import DeyeClient
        settings = load_settings()
        client = DeyeClient(settings)
        token = client.obtain_token()
        device_list_result = client.station_device_list(token)
        # Try device_sn directly
        if client.device_sn:
            device_detail_test = client.device_original_data(token, client.device_sn)
    except Exception as e:
        device_list_result = [{'error': str(e)}]

    return {
        'created_at': latest.created_at.isoformat(),
        'daily_production_stored': latest.daily_production,
        'monthly_production_stored': latest.monthly_production,
        'total_production_stored': latest.total_production,
        'solar_power': latest.solar_power,
        'battery_soc': latest.battery_soc,
        'device_list_live': device_list_result,
        'device_detail_test': device_detail_test,
        'top_level_keys': list(raw.keys()) if isinstance(raw, dict) else [],
        'raw': raw,
    }


@main_bp.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='الصفحة غير موجودة'), 404


@main_bp.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='حدث خطأ في الخادم'), 500
