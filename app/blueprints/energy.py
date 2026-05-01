from __future__ import annotations

# Heavy v10.1 split blueprint. The route logic is intentionally moved out of
# main.py while importing legacy helpers/services from main during the migration
# window. This keeps behavior stable while main.py shrinks safely.
from flask import Blueprint
from ..services.landing_content import get_landing_settings, build_landing_plan_cards
from .main import *  # noqa: F401,F403 - transitional legacy dependency bridge
from . import main as _legacy_main

for _legacy_name in dir(_legacy_main):
    if _legacy_name.startswith('_') and not _legacy_name.startswith('__'):
        globals()[_legacy_name] = getattr(_legacy_main, _legacy_name)

energy_bp = Blueprint('energy', __name__)

@energy_bp.route('/')
def index():
    # Heavy v10.5.27: the root URL is a public landing page.
    # Logged-in users still see the landing page, but CTAs point them back to
    # their proper dashboard instead of forcing an automatic redirect.
    user = _active_user() if session.get('logged_in') else None
    is_admin_user = bool(user and (getattr(user, 'is_admin', False) or (getattr(user, 'role', '') or '').strip().lower() == 'admin'))
    dashboard_url = url_for('main.admin_dashboard', lang=_lang()) if is_admin_user else url_for('main.dashboard', lang=_lang())
    return render_template(
        'landing.html',
        ui_lang=_lang(),
        landing_logged_in=bool(session.get('logged_in')),
        landing_is_admin=is_admin_user,
        landing_dashboard_url=dashboard_url,
        landing_register_url=url_for('auth.register', lang=_lang()),
        landing_login_url=url_for('auth.login', lang=_lang()),
        landing=get_landing_settings(),
        landing_plans=build_landing_plan_cards(_lang()),
    )


@energy_bp.route('/admin/dashboard')
def admin_dashboard():
    guard = _admin_guard()
    if guard:
        return guard
    total_users = AppUser.query.filter_by(is_admin=False).count()
    total_tenants = TenantAccount.query.count()
    active_subs = TenantSubscription.query.filter(TenantSubscription.status.in_(['active', 'trial'])).count()
    total_plans = SubscriptionPlan.query.filter_by(is_active=True).count()
    total_devices = AppDevice.query.filter_by(is_active=True).count()
    recent_subscribers = AppUser.query.filter_by(is_admin=False).order_by(AppUser.created_at.desc()).limit(5).all()
    heartbeat_rows = ServiceHeartbeat.query.order_by(ServiceHeartbeat.updated_at.desc()).limit(6).all()
    return render_template('admin_dashboard.html', total_users=total_users, total_tenants=total_tenants, active_subs=active_subs, total_plans=total_plans, total_devices=total_devices, recent_subscribers=recent_subscribers, heartbeat_rows=heartbeat_rows)


@energy_bp.route('/dashboard')
def dashboard():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
    from datetime import UTC, datetime, timedelta
    from ..services.utils import utc_to_local
    from zoneinfo import ZoneInfo
    active_device = _active_device()
    settings = _device_runtime_settings(active_device, allow_global_connection=False)
    device_ready, device_ready_message = _device_sync_ready(active_device)
    latest = _latest_reading() if device_ready else None
    logs = scoped_query(SyncLog).order_by(SyncLog.created_at.desc()).limit(8).all() if active_device else []
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
    selected_day_label = day_local.strftime('%Y-%m-%d')
    today_label = now_local.strftime('%Y-%m-%d')
    if selected_day_label == today_label:
        day_readings = (
            scoped_query(Reading)
            .filter(Reading.created_at < day_end_utc)
            .order_by(Reading.created_at.desc())
            .limit(240)
            .all()
        )[::-1]
        day_readings = [row for row in day_readings if row.created_at >= day_start_utc]
    else:
        day_readings = (scoped_query(Reading)
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
    # احتياط: خذ آخر 24 قراءة فقط إذا كان الجهاز الحالي صالحًا وله قراءات داخل نطاقه
    if not readings_hourly and active_device and device_ready:
        readings_hourly = scoped_query(Reading).order_by(Reading.created_at.desc()).limit(24).all()[::-1]

    labels = [format_time_short(r.created_at, tz_name) for r in readings_hourly]
    solar_values = [r.solar_power for r in readings_hourly]
    load_values = [r.home_load for r in readings_hourly]
    battery_soc_values = [r.battery_soc for r in readings_hourly]
    grid_values = [r.grid_power for r in readings_hourly]

    # battery power للرسم البياني
    battery_power_values = [r.battery_power for r in readings_hourly]

    flow = build_flow(latest)
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    battery_details = build_battery_details(latest)
    weather = get_weather_for_latest(latest)
    weather_insight = build_weather_insight(weather, battery_insights)
    solar_prediction = build_pre_sunset_prediction(latest, weather, settings)
    smart_overview = get_latest_historical_overview(latest, weather=weather, settings=settings, context='dashboard')

    production_summary = get_production_summary(tz_name)
    smart_loads = _smart_load_suggestions(latest)
    actual_surplus = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
    recent_events = get_recent_event_logs(8)

    # Heavy v40 — smart day-phase classifier (drives the new dashboard hero)
    from ..services.utils import classify_day_phase
    day_phase = classify_day_phase(
        now_local,
        sunrise_text=(weather.sunrise_time if weather and getattr(weather, 'sunrise_time', None) else None),
        sunset_text=(weather.sunset_time if weather and getattr(weather, 'sunset_time', None) else None),
    )

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
        weather=weather, weather_insight=weather_insight, solar_prediction=solar_prediction, smart_overview=smart_overview,
        production_summary=production_summary, smart_loads=smart_loads, actual_surplus=actual_surplus, recent_events=recent_events,
        day_phase=day_phase,
        human_duration_hours=human_duration_hours, format_energy=format_energy,
        format_power=format_power, _to_12h_label=_to_12h_label,
        format_local=lambda dt: format_local_datetime(dt, tz_name),
        ui_lang=_lang(), active_device=active_device,
        device_ready=device_ready, device_ready_message=device_ready_message,
    )


@energy_bp.route('/api/live')
def api_live():
    device = _active_device()
    ready, _ = _device_sync_ready(device)
    latest = _latest_reading() if ready else None
    tz_name = current_app.config['LOCAL_TIMEZONE']
    # Heavy v40 — day phase is always returned, even if there's no reading,
    # so the dashboard hero can keep its sky animation alive.
    from datetime import UTC, datetime as _dt
    from ..services.utils import utc_to_local, classify_day_phase
    now_local = utc_to_local(_dt.now(UTC), tz_name) or _dt.now(UTC)
    weather_for_phase = get_weather_for_latest(latest) if latest else None
    day_phase_payload = classify_day_phase(
        now_local,
        sunrise_text=(weather_for_phase.sunrise_time if weather_for_phase and getattr(weather_for_phase, 'sunrise_time', None) else None),
        sunset_text=(weather_for_phase.sunset_time if weather_for_phase and getattr(weather_for_phase, 'sunset_time', None) else None),
    )
    if not latest:
        return {'ok': False, 'empty': True, 'day_phase': day_phase_payload}
    weather = weather_for_phase
    settings = load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    solar_prediction = build_pre_sunset_prediction(latest, weather, settings)
    actual_surplus = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
    return {
        'ok': True,
        'day_phase': day_phase_payload,
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
        'actual_surplus': actual_surplus,
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


@energy_bp.route('/statistics')
def statistics():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
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


@energy_bp.route('/reports')
def reports():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
    tz_name = current_app.config['LOCAL_TIMEZONE']
    selected_view, selected_date, filtered_rows, title_hint, prev_date, next_date, can_go_next = _get_stats_context(request.args, tz_name)
    stats = compute_energy_stats(filtered_rows)
    chart = build_period_chart(filtered_rows, tz_name, selected_view)
    table_rows = build_statistics_table(filtered_rows, tz_name, selected_view)
    latest = _latest_reading()
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


@energy_bp.route('/statistics/export/csv')
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


@energy_bp.route('/statistics/export/pdf')
def export_statistics_pdf():
    """Pixel-style report mirroring the statistics page mock.
    Two-column layout, vector illustrations, donut chart, bar chart, and
    energy-flow diagram drawn directly on the canvas. Arabic encoding pipeline
    (ar() / arabic_reshaper / get_display / _register_pdf_fonts) is preserved
    exactly as before so RTL text continues to render correctly."""
    import math as _math

    tz_name = current_app.config['LOCAL_TIMEZONE']
    selected_view, selected_date, filtered_rows, title_hint, *_ = _get_stats_context(request.args, tz_name)
    stats = compute_energy_stats(filtered_rows)
    table_rows = build_statistics_table(filtered_rows, tz_name, selected_view)
    chart = build_period_chart(filtered_rows, tz_name, selected_view)

    # ── Arabic shaping (UNTOUCHED) ─────────────────────────────────────────
    def ar(text):
        try:
            return get_display(arabic_reshaper.reshape(str(text)))
        except Exception:
            return str(text)

    def _register_pdf_fonts():
        from pathlib import Path
        base_dir = Path(current_app.root_path)
        candidates = [
            ('NotoArabic', 'NotoArabicBold',
             base_dir / 'static' / 'fonts' / 'NotoSansArabic-Regular.ttf',
             base_dir / 'static' / 'fonts' / 'NotoSansArabic-Bold.ttf'),
            ('NotoArabic', 'NotoArabicBold',
             Path('/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf'),
             Path('/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf')),
            ('Amiri', 'AmiriBold',
             Path('/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Regular.ttf'),
             Path('/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Bold.ttf')),
        ]
        for regular_name, bold_name, regular_path, bold_path in candidates:
            try:
                if regular_path.exists() and bold_path.exists():
                    try: pdfmetrics.getFont(regular_name)
                    except Exception: pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
                    try: pdfmetrics.getFont(bold_name)
                    except Exception: pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                    return regular_name, bold_name
            except Exception:
                continue
        return 'Helvetica', 'Helvetica-Bold'

    font_name, font_bold = _register_pdf_fonts()

    def fmt_num(v, dp=2):
        try: return f"{float(v or 0):.{dp}f}"
        except Exception: return "0.00"
    def fmt_pct(v):
        try: return f"{float(v or 0):.1f}%"
        except Exception: return "0.0%"

    # ── Dashboard color palette ────────────────────────────────────────────
    INK         = '#0b1220'
    INK_SOFT    = '#1f2a44'
    MUTED       = '#5e6f8c'
    LINE        = '#e3eaf6'
    LINE_STRONG = '#cfd9ec'
    BG          = '#f5f8ff'
    AMBER       = '#f59e0b'
    AMBER_SOFT  = '#fbbf24'
    AMBER_BG    = '#fef3c7'
    ROSE        = '#f43f5e'
    ROSE_BG     = '#ffe4e6'
    EMERALD     = '#10b981'
    EMERALD_SOFT = '#34d399'
    EMERALD_BG  = '#d1fae5'
    SKY         = '#2563eb'
    SKY_SOFT    = '#60a5fa'
    SKY_BG      = '#dbeafe'
    VIOLET      = '#6d3aff'
    VIOLET_BG   = '#ede9fe'

    width, height = A4

    PAD     = 18
    GAP     = 12
    LEFT_W  = 178
    RIGHT_W = width - 2 * PAD - LEFT_W - GAP

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle('تقرير منصة الطاقة الشمسية')

    # ────────────── Drawing helpers ──────────────
    def hex_color(h):
        if isinstance(h, str): return colors.HexColor(h)
        return h

    def paint_bg():
        c.setFillColor(hex_color(BG))
        c.rect(0, 0, width, height, stroke=0, fill=1)
        try:
            c.setFillColorRGB(0.43, 0.23, 1.0, alpha=0.05)
            c.circle(width * 0.10, height * 1.02, 240, stroke=0, fill=1)
            c.setFillColorRGB(0.96, 0.62, 0.04, alpha=0.05)
            c.circle(width * 0.92, height * 1.02, 220, stroke=0, fill=1)
            c.setFillColorRGB(0.06, 0.72, 0.51, alpha=0.04)
            c.circle(width * 0.50, -60, 280, stroke=0, fill=1)
        except Exception:
            pass

    def card(x, y, w, h, fill='#ffffff', border=LINE, radius=14, shadow=True):
        if shadow:
            try:
                c.setFillColorRGB(0.06, 0.09, 0.16, alpha=0.05)
                c.roundRect(x, y - 2, w, h, radius, stroke=0, fill=1)
            except Exception:
                pass
        c.setFillColor(hex_color(fill))
        c.setStrokeColor(hex_color(border))
        c.setLineWidth(0.7)
        c.roundRect(x, y, w, h, radius, stroke=1, fill=1)

    def soft_chip(x, y, label, fill='#dbeafe', text_color='#1d4ed8', font=None, size=8.5, padx=8, pady=5, icon=None):
        f = font or font_bold
        s = ar(label)
        c.setFont(f, size)
        tw = c.stringWidth(s, f, size)
        w = tw + padx * 2 + (16 if icon else 0)
        h = size + pady * 2
        c.setFillColor(hex_color(fill))
        c.roundRect(x, y, w, h, h / 2, stroke=0, fill=1)
        c.setFillColor(hex_color(text_color))
        text_x = x + w - padx
        if icon == 'bolt':
            c.setFillColor(hex_color(text_color))
            bx = x + padx
            by = y + h / 2
            c.setLineWidth(1.4)
            c.setStrokeColor(hex_color(text_color))
            path = c.beginPath()
            path.moveTo(bx + 2, by + 4)
            path.lineTo(bx - 1, by)
            path.lineTo(bx + 1, by)
            path.lineTo(bx - 2, by - 4)
            c.drawPath(path, stroke=1, fill=0)
            c.setFillColor(hex_color(text_color))
            text_x = x + w - padx
        c.setFont(f, size)
        c.setFillColor(hex_color(text_color))
        c.drawRightString(text_x, y + pady + 1, s)
        return w, h

    def draw_text(s, x, y, font, size, color, align='left'):
        c.setFont(font, size)
        c.setFillColor(hex_color(color))
        s_a = ar(s)
        if align == 'center': c.drawCentredString(x, y, s_a)
        elif align == 'right': c.drawRightString(x, y, s_a)
        else: c.drawString(x, y, s_a)

    def section_title(s, x, y, accent_color=SKY, w=None):
        draw_text(s, x, y, font_bold, 10.5, INK_SOFT, align='right' if w is None else 'right')
        c.setFillColor(hex_color(accent_color))
        c.roundRect((x - 28) if w is None else (x + (w or 0) - 32 - 6), y - 5, 32, 2.4, 1.2, stroke=0, fill=1)

    # ────────────── Icons (vector mini-icons) ──────────────
    def icon_sun(cx, cy, color=AMBER, size=10):
        c.setFillColor(hex_color(color))
        c.circle(cx, cy, size * 0.55, stroke=0, fill=1)
        c.setStrokeColor(hex_color(color))
        c.setLineWidth(1.3)
        for ang in range(0, 360, 45):
            rx = _math.cos(_math.radians(ang)) * size
            ry = _math.sin(_math.radians(ang)) * size
            c.line(cx + rx * 0.72, cy + ry * 0.72, cx + rx, cy + ry)

    def icon_home(cx, cy, color=SKY, size=11):
        c.setStrokeColor(hex_color(color))
        c.setFillColor(hex_color(color))
        c.setLineWidth(1.2)
        p = c.beginPath()
        p.moveTo(cx - size, cy - 1)
        p.lineTo(cx, cy + size * 0.85)
        p.lineTo(cx + size, cy - 1)
        c.drawPath(p, stroke=1, fill=0)
        c.rect(cx - size * 0.7, cy - size * 0.85, size * 1.4, size * 0.85, stroke=1, fill=0)
        c.setFillColor(hex_color(color))
        c.rect(cx - size * 0.18, cy - size * 0.85, size * 0.36, size * 0.55, stroke=0, fill=1)

    def icon_battery(cx, cy, color=EMERALD, size=10, fill_ratio=0.6):
        c.setStrokeColor(hex_color(color))
        c.setFillColor(colors.white)
        c.setLineWidth(1.3)
        bw, bh = size * 1.4, size * 0.8
        c.roundRect(cx - bw / 2, cy - bh / 2, bw, bh, 1.5, stroke=1, fill=1)
        c.rect(cx + bw / 2, cy - bh / 4, 1.6, bh / 2, stroke=0, fill=1)
        c.setFillColor(hex_color(color))
        c.roundRect(cx - bw / 2 + 1.5, cy - bh / 2 + 1.5, (bw - 3) * fill_ratio, bh - 3, 0.6, stroke=0, fill=1)

    def icon_grid(cx, cy, color='#94a3b8', size=10):
        c.setStrokeColor(hex_color(color))
        c.setFillColor(hex_color(color))
        c.setLineWidth(1.3)
        c.line(cx - size * 0.55, cy - size * 0.85, cx, cy + size * 0.55)
        c.line(cx + size * 0.55, cy - size * 0.85, cx, cy + size * 0.55)
        c.line(cx - size * 0.85, cy - size * 0.85, cx + size * 0.85, cy - size * 0.85)
        c.line(cx - size * 0.85, cy - size * 0.85, cx - size * 0.55, cy + size * 0.55)
        c.line(cx + size * 0.85, cy - size * 0.85, cx + size * 0.55, cy + size * 0.55)
        c.line(cx - size * 0.55, cy + size * 0.55, cx + size * 0.55, cy + size * 0.55)

    def icon_chart(cx, cy, color=SKY, size=10):
        c.setFillColor(hex_color(color))
        c.rect(cx - size * 0.85, cy - size * 0.85, size * 0.4, size * 1.3, stroke=0, fill=1)
        c.rect(cx - size * 0.25, cy - size * 0.85, size * 0.4, size * 0.85, stroke=0, fill=1)
        c.rect(cx + size * 0.35, cy - size * 0.85, size * 0.4, size * 1.7, stroke=0, fill=1)

    def icon_bolt(cx, cy, color=AMBER, size=10):
        c.setFillColor(hex_color(color))
        p = c.beginPath()
        p.moveTo(cx + 2, cy + size)
        p.lineTo(cx - size * 0.6, cy)
        p.lineTo(cx - 1, cy)
        p.lineTo(cx - size * 0.5, cy - size)
        p.lineTo(cx + size * 0.6, cy)
        p.lineTo(cx + 1, cy)
        p.close()
        c.drawPath(p, stroke=0, fill=1)

    def icon_doc(cx, cy, color=SKY, size=10):
        c.setStrokeColor(hex_color(color))
        c.setFillColor(colors.white)
        c.setLineWidth(1.2)
        c.rect(cx - size * 0.7, cy - size * 0.95, size * 1.4, size * 1.9, stroke=1, fill=1)
        c.setStrokeColor(hex_color(color))
        for i in range(3):
            yy = cy + size * 0.5 - i * size * 0.45
            c.line(cx - size * 0.4, yy, cx + size * 0.4, yy)

    def icon_table(cx, cy, color=SKY, size=10):
        c.setStrokeColor(hex_color(color))
        c.setFillColor(colors.white)
        c.setLineWidth(1.2)
        c.rect(cx - size, cy - size * 0.8, size * 2, size * 1.6, stroke=1, fill=1)
        c.line(cx - size, cy + size * 0.3, cx + size, cy + size * 0.3)
        c.line(cx, cy - size * 0.8, cx, cy + size * 0.8)

    def icon_shield(cx, cy, color=EMERALD, size=10):
        c.setFillColor(hex_color(color))
        p = c.beginPath()
        p.moveTo(cx, cy + size)
        p.lineTo(cx - size * 0.85, cy + size * 0.5)
        p.lineTo(cx - size * 0.85, cy - size * 0.4)
        p.lineTo(cx, cy - size)
        p.lineTo(cx + size * 0.85, cy - size * 0.4)
        p.lineTo(cx + size * 0.85, cy + size * 0.5)
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        c.setStrokeColor(colors.white); c.setLineWidth(1.4)
        c.line(cx - size * 0.3, cy, cx - size * 0.05, cy - size * 0.3)
        c.line(cx - size * 0.05, cy - size * 0.3, cx + size * 0.4, cy + size * 0.25)

    def icon_clock(cx, cy, color=SKY, size=10):
        c.setStrokeColor(hex_color(color))
        c.setFillColor(colors.white)
        c.setLineWidth(1.3)
        c.circle(cx, cy, size * 0.85, stroke=1, fill=1)
        c.line(cx, cy, cx, cy + size * 0.55)
        c.line(cx, cy, cx + size * 0.4, cy)

    # ────────────── Hero illustration (left top card) ──────────────
    def draw_hero_illustration(x, y, w, h):
        card(x, y, w, h, radius=18)
        # decorative dots
        c.setFillColor(hex_color(LINE_STRONG))
        for i in range(5):
            for j in range(5):
                if (i + j) % 2 == 0:
                    c.circle(x + w - 14 - i * 6, y + h - 14 - j * 6, 0.9, stroke=0, fill=1)
        # plant in bottom-left
        c.setStrokeColor(hex_color(EMERALD))
        c.setLineWidth(1.4)
        c.line(x + 22, y + 12, x + 22, y + 32)
        c.setFillColor(hex_color(EMERALD))
        c.circle(x + 17, y + 28, 4, stroke=0, fill=1)
        c.circle(x + 27, y + 30, 4, stroke=0, fill=1)
        c.setFillColor(hex_color(EMERALD_SOFT))
        c.circle(x + 19, y + 22, 3.5, stroke=0, fill=1)
        c.circle(x + 25, y + 24, 3.5, stroke=0, fill=1)
        # sparkle
        c.setStrokeColor(hex_color(AMBER_SOFT)); c.setLineWidth(1.3)
        sx, sy = x + 16, y + h - 28
        c.line(sx - 4, sy, sx + 4, sy); c.line(sx, sy - 4, sx, sy + 4)
        c.line(sx - 3, sy - 3, sx + 3, sy + 3); c.line(sx - 3, sy + 3, sx + 3, sy - 3)
        # sun (right side)
        cx = x + w - 50
        cy = y + h - 60
        icon_sun(cx, cy, color=AMBER_SOFT, size=20)
        # solar panel (center)
        px = x + w / 2 - 35
        py = y + 50
        # back/shadow
        c.setFillColor(hex_color('#0e3b86'))
        c.roundRect(px - 2, py - 2, 70, 50, 4, stroke=0, fill=1)
        # face
        c.setFillColor(hex_color(SKY))
        c.setStrokeColor(hex_color('#1e3a8a')); c.setLineWidth(0.6)
        c.roundRect(px, py, 70, 50, 3, stroke=1, fill=1)
        # cells grid
        c.setStrokeColor(hex_color('#1e40af')); c.setLineWidth(0.4)
        for i in range(1, 4):
            c.line(px + i * 70 / 4, py, px + i * 70 / 4, py + 50)
        c.line(px, py + 25, px + 70, py + 25)
        # cell highlights
        c.setFillColor(hex_color(SKY_SOFT))
        c.rect(px + 2, py + 27, 14, 20, stroke=0, fill=1)
        c.rect(px + 19, py + 27, 14, 20, stroke=0, fill=1)
        # stand
        c.setStrokeColor(hex_color('#1e3a8a')); c.setLineWidth(1.6)
        c.line(px + 35, py, px + 25, py - 16)
        c.line(px + 35, py, px + 45, py - 16)

    # ────────────── Quick stats list (left, 4 rows) ──────────────
    def draw_quick_stats_row(x, y, w, h, accent, accent_bg, draw_icon, value, title, hint):
        # icon box
        ibx, iby, ibw, ibh = x + 6, y + (h - 32) / 2, 32, 32
        c.setFillColor(hex_color(accent_bg))
        c.roundRect(ibx, iby, ibw, ibh, 8, stroke=0, fill=1)
        draw_icon(ibx + ibw / 2, iby + ibh / 2)
        # text columns (RTL: title and value on the right)
        text_right = x + w - 6
        draw_text(title, text_right, y + h - 14, font_name, 8.4, MUTED, align='right')
        draw_text(value, text_right, y + h - 30, font_bold, 14.5, INK, align='right')
        if hint:
            draw_text(hint, text_right, y + 6, font_name, 7.4, MUTED, align='right')

    # ────────────── Battery donut card ──────────────
    def draw_battery_donut_card(x, y, w, h, soc_pct):
        card(x, y, w, h, radius=14)
        # title
        draw_text('حالة البطارية', x + w / 2, y + h - 18, font_bold, 10.5, INK_SOFT, align='center')
        # donut
        cx, cy = x + w / 2, y + h / 2 - 8
        outer_r, inner_r = 38, 28
        ring_w = outer_r - inner_r
        # background ring
        c.setStrokeColor(hex_color('#eef2f9'))
        c.setLineWidth(ring_w)
        c.circle(cx, cy, (outer_r + inner_r) / 2, stroke=1, fill=0)
        # progress arc
        try:
            soc = max(0.0, min(100.0, float(soc_pct or 0)))
        except Exception:
            soc = 0.0
        if soc > 0:
            c.setStrokeColor(hex_color(SKY))
            c.setLineWidth(ring_w)
            extent = -soc / 100.0 * 360.0  # negative for clockwise from top
            c.arc(cx - (outer_r + inner_r) / 2, cy - (outer_r + inner_r) / 2,
                  cx + (outer_r + inner_r) / 2, cy + (outer_r + inner_r) / 2,
                  90, extent)
        # center text
        draw_text(f'{soc:.1f}%', cx, cy - 1, font_bold, 14, INK, align='center')
        draw_text('نسبة الشحن الحالية', cx, cy - 14, font_name, 7, MUTED, align='center')
        # legend bottom
        ly = y + 12
        c.setFillColor(hex_color(EMERALD))
        c.roundRect(x + 14, ly + 1, 12, 8, 2, stroke=0, fill=1)
        draw_text('مستوى الشحن', x + w - 12, ly + 1, font_name, 7.5, MUTED, align='right')

    # ────────────── Trust badge (left bottom) ──────────────
    def draw_trust_badge(x, y, w, h):
        card(x, y, w, h, fill='#f5f9ff', border=LINE, radius=12)
        ix = x + 12
        iy = y + h / 2 + 6
        c.setFillColor(hex_color(EMERALD_BG))
        c.roundRect(ix - 11, iy - 11, 22, 22, 5, stroke=0, fill=1)
        icon_shield(ix, iy, color=EMERALD, size=8)
        draw_text('بيانات موثوقة', x + w - 10, y + h - 15, font_bold, 9.5, INK_SOFT, align='right')
        draw_text('جميع البيانات محسوبة بدقة عالية', x + w - 10, y + h - 28, font_name, 7.2, MUTED, align='right')
        draw_text('لتوفير رؤية موثوقة لأداء النظام', x + w - 10, y + h - 39, font_name, 7.2, MUTED, align='right')

    # ────────────── Title + chip (right top) ──────────────
    def draw_right_title(x, y, w):
        # chip top-right
        chip_label = ar('تحليل الطاقة')
        c.setFont(font_bold, 9)
        chip_w = c.stringWidth(chip_label, font_bold, 9) + 28
        chip_h = 22
        chip_x = x + w - chip_w
        chip_y = y - chip_h
        c.setFillColor(hex_color(SKY_BG))
        c.roundRect(chip_x, chip_y, chip_w, chip_h, chip_h / 2, stroke=0, fill=1)
        c.setFillColor(hex_color(SKY))
        c.circle(chip_x + 11, chip_y + chip_h / 2, 4.5, stroke=0, fill=1)
        c.setFillColor(colors.white)
        # bolt inside circle
        cb = c.beginPath()
        bx, by = chip_x + 11, chip_y + chip_h / 2
        cb.moveTo(bx + 1, by + 2.5); cb.lineTo(bx - 1.5, by - 0.2)
        cb.lineTo(bx + 0.3, by - 0.2); cb.lineTo(bx - 1, by - 2.5)
        cb.lineTo(bx + 1.8, by); cb.lineTo(bx + 0.2, by); cb.close()
        c.drawPath(cb, stroke=0, fill=1)
        c.setFillColor(hex_color(SKY))
        c.drawRightString(chip_x + chip_w - 10, chip_y + 6.5, chip_label)

        # title (right-aligned)
        draw_text('تقرير منصة الطاقة الشمسية', x + w, y - 60, font_bold, 22, INK, align='right')
        # subtitle / date range
        date_str = selected_date.strftime('%Y-%m-%d')
        # date pill
        sub_text = f'الفترة: يوم {date_str}   إلى التاريخ {date_str}'
        c.setFont(font_name, 9.5)
        sub_w = c.stringWidth(ar(sub_text), font_name, 9.5)
        sub_x = x + w - sub_w - 24
        sub_y = y - 90
        # mini calendar icon
        c.setFillColor(hex_color(SKY))
        c.roundRect(x + w - 16, sub_y - 2, 12, 12, 2, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.rect(x + w - 14, sub_y + 7, 8, 1.5, stroke=0, fill=1)
        c.rect(x + w - 14, sub_y + 1, 8, 5, stroke=0, fill=1)
        draw_text(sub_text, x + w - 22, sub_y + 1, font_name, 9.5, INK_SOFT, align='right')

    # ────────────── Energy flow card ──────────────
    def draw_energy_flow_card(x, y, w, h):
        card(x, y, w, h, radius=14)
        # title row
        draw_text('تدفق الطاقة', x + w - 14, y + h - 18, font_bold, 10.5, INK_SOFT, align='right')
        # tiny "flow" icon
        c.setFillColor(hex_color(SKY))
        c.roundRect(x + w - 78, y + h - 22, 14, 14, 3, stroke=0, fill=1)
        c.setStrokeColor(colors.white); c.setLineWidth(1.2)
        c.line(x + w - 75, y + h - 15, x + w - 70, y + h - 15)
        c.line(x + w - 70, y + h - 15, x + w - 70, y + h - 11)

        # diagram center
        cx_top = x + w / 2
        cy_top = y + h - 50
        cx_mid = x + w / 2
        cy_mid = y + h / 2 - 8
        cx_left = x + 38
        cx_right = x + w - 38
        cy_side = cy_mid

        # solar generated value (top)
        try:
            v_solar = float(stats.get('solar_generated_kwh') or 0)
            v_batt = float(stats.get('battery_to_home_kwh') or 0)
            v_grid = float(stats.get('grid_to_home_kwh') or 0)
            v_home = float(stats.get('home_consumed_kwh') or 0)
        except Exception:
            v_solar = v_batt = v_grid = v_home = 0.0

        # SUN node
        c.setFillColor(hex_color(AMBER_BG))
        c.circle(cx_top, cy_top, 14, stroke=0, fill=1)
        icon_sun(cx_top, cy_top, color=AMBER, size=9)
        draw_text(f'{v_solar:.2f}', cx_top, cy_top - 28, font_bold, 11, INK, align='center')
        draw_text('إنتاج الشمس', cx_top, cy_top - 40, font_name, 7.2, MUTED, align='center')

        # HOME center node (larger)
        c.setFillColor(hex_color(SKY_BG))
        c.circle(cx_mid, cy_mid, 22, stroke=0, fill=1)
        c.setFillColor(hex_color(SKY))
        c.circle(cx_mid, cy_mid, 18, stroke=0, fill=1)
        icon_home(cx_mid, cy_mid, color=colors.white, size=10)

        # BATTERY node (left)
        c.setFillColor(hex_color(EMERALD_BG))
        c.circle(cx_left, cy_side, 13, stroke=0, fill=1)
        icon_battery(cx_left, cy_side, color=EMERALD, size=8, fill_ratio=0.7)
        draw_text(f'{v_batt:.2f}', cx_left, cy_side - 24, font_bold, 10, INK, align='center')
        draw_text('من البطارية', cx_left, cy_side - 36, font_name, 7, MUTED, align='center')

        # GRID node (right)
        c.setFillColor(hex_color(VIOLET_BG))
        c.circle(cx_right, cy_side, 13, stroke=0, fill=1)
        icon_grid(cx_right, cy_side, color=VIOLET, size=8)
        draw_text(f'{v_grid:.2f}', cx_right, cy_side - 24, font_bold, 10, INK, align='center')
        draw_text('من الشبكة', cx_right, cy_side - 36, font_name, 7, MUTED, align='center')

        # HOME bottom
        cx_bot = x + w / 2
        cy_bot = y + 36
        draw_text(f'{v_home:.2f}', cx_bot, cy_bot - 4, font_bold, 11, INK, align='center')
        draw_text('استهلاك المنزل', cx_bot, cy_bot - 16, font_name, 7.2, MUTED, align='center')

        # dashed connectors
        c.setStrokeColor(hex_color(LINE_STRONG))
        c.setLineWidth(1.0)
        c.setDash(2, 2)
        # sun → home
        c.line(cx_top, cy_top - 14, cx_mid, cy_mid + 22)
        # battery → home
        c.line(cx_left + 13, cy_side, cx_mid - 22, cy_mid)
        # grid → home
        c.line(cx_right - 13, cy_side, cx_mid + 22, cy_mid)
        # home → bottom (estimate consumption)
        c.line(cx_mid, cy_mid - 22, cx_bot, cy_bot + 8)
        c.setDash()

        # arrowheads
        def arrow(px, py, dx, dy, color):
            c.setFillColor(hex_color(color))
            ang = _math.atan2(dy, dx)
            sz = 4
            p = c.beginPath()
            p.moveTo(px, py)
            p.lineTo(px - sz * _math.cos(ang - 0.4), py - sz * _math.sin(ang - 0.4))
            p.lineTo(px - sz * _math.cos(ang + 0.4), py - sz * _math.sin(ang + 0.4))
            p.close()
            c.drawPath(p, stroke=0, fill=1)
        arrow(cx_mid - 22, cy_mid + 1, cx_mid - 22 - cx_left + 13, 0, EMERALD)
        arrow(cx_mid + 22, cy_mid + 1, cx_mid + 22 - cx_right + 13, 0, VIOLET)
        arrow(cx_mid, cy_mid + 22, 0, 22, AMBER)
        arrow(cx_bot, cy_bot + 8, 0, -8, SKY)

    # ────────────── 24-hour bar chart ──────────────
    def draw_trend_chart(x, y, w, h):
        card(x, y, w, h, radius=14)
        # title row
        # chart icon left
        c.setFillColor(hex_color(SKY_BG))
        c.roundRect(x + w - 24, y + h - 22, 14, 14, 3, stroke=0, fill=1)
        icon_chart(x + w - 17, y + h - 15, color=SKY, size=4.5)
        draw_text('اتجاه إنتاج الشمس', x + w - 32, y + h - 18, font_bold, 10.5, INK_SOFT, align='right')

        # total label
        try: total = float(stats.get('solar_generated_kwh') or 0)
        except Exception: total = 0
        # right-aligned total
        draw_text('إجمالي التوليد:', x + w - 14, y + h - 38, font_name, 8.5, MUTED, align='right')
        draw_text(f'{total:.2f}', x + w - 84, y + h - 38, font_bold, 11, SKY, align='right')

        # bars area
        bx, by = x + 14, y + 22
        bw, bh = w - 28, h - 70
        labels = chart.get('labels') or []
        solar = chart.get('solar') or []
        if not labels or not solar:
            # fallback: 24 hours empty
            labels = [f'{i:02d}:00' for i in range(24)]
            solar = [0] * 24
        # baseline grid
        c.setStrokeColor(hex_color('#eef2f9')); c.setLineWidth(0.5)
        for i in range(4):
            yy = by + bh * i / 4
            c.line(bx, yy, bx + bw, yy)
        # bars
        max_v = max([float(v or 0) for v in solar] + [1])
        n = len(solar)
        bar_gap = max(1, (bw / n) * 0.18)
        bar_w = max(1.5, (bw / n) - bar_gap)
        for i, v in enumerate(solar):
            try: vv = float(v or 0)
            except Exception: vv = 0
            ratio = vv / max_v if max_v > 0 else 0
            bh_i = max(0.8, bh * ratio)
            bxi = bx + i * (bar_w + bar_gap)
            # gradient effect: darker bottom, lighter top — fake with two stacked rects
            c.setFillColor(hex_color(SKY))
            c.roundRect(bxi, by, bar_w, bh_i, min(1.5, bar_w / 2), stroke=0, fill=1)
            c.setFillColor(hex_color(EMERALD_SOFT))
            tip = max(0.6, min(bh_i * 0.35, 6))
            c.roundRect(bxi, by + bh_i - tip, bar_w, tip, min(1.5, bar_w / 2), stroke=0, fill=1)
        # x-axis labels every ~3 hours
        c.setFillColor(hex_color(MUTED))
        c.setFont(font_name, 6.4)
        step = max(1, n // 8)
        for i in range(0, n, step):
            xx = bx + i * (bar_w + bar_gap) + bar_w / 2
            c.drawCentredString(xx, by - 9, str(labels[i]))

    # ────────────── Summary grid (4 mini stats) ──────────────
    def draw_summary_card(x, y, w, h):
        card(x, y, w, h, radius=14)
        # title icon (doc)
        c.setFillColor(hex_color(SKY_BG))
        c.roundRect(x + w - 26, y + h - 22, 14, 14, 3, stroke=0, fill=1)
        icon_doc(x + w - 19, y + h - 15, color=SKY, size=4.5)
        draw_text('ملخص الفترة', x + w - 34, y + h - 18, font_bold, 10.5, INK_SOFT, align='right')

        # 4 cells in 2x2
        cells = [
            ('من الشمس إلى البيت:',  fmt_num(stats['solar_to_home_kwh']),  AMBER, AMBER_BG, lambda cx, cy: icon_sun(cx, cy, AMBER, 6)),
            ('من الشبكة إلى البيت:', fmt_num(stats['grid_to_home_kwh']),   VIOLET, VIOLET_BG, lambda cx, cy: icon_grid(cx, cy, VIOLET, 6)),
            ('من البطارية إلى البيت:', fmt_num(stats['battery_to_home_kwh']), EMERALD, EMERALD_BG, lambda cx, cy: icon_battery(cx, cy, EMERALD, 6, 0.7)),
            ('أعلى إنتاج لحظي:', f"{stats.get('max_solar_w', 0)} واط", AMBER, AMBER_BG, lambda cx, cy: icon_bolt(cx, cy, AMBER, 6)),
        ]
        col_gap, row_gap = 10, 8
        cell_w = (w - 28 - col_gap) / 2
        cell_h = (h - 50 - row_gap) / 2
        ox = x + 14
        oy = y + 14
        for idx, (title, val, accent, bg, draw_ic) in enumerate(cells):
            r = idx // 2
            cidx = idx % 2
            cx = ox + (1 - cidx) * (cell_w + col_gap)  # RTL: first cell on right
            cy = oy + (1 - r) * (cell_h + row_gap)
            # cell card
            c.setFillColor(hex_color('#f8fbff'))
            c.setStrokeColor(hex_color(LINE)); c.setLineWidth(0.5)
            c.roundRect(cx, cy, cell_w, cell_h, 10, stroke=1, fill=1)
            # icon circle on left side
            c.setFillColor(hex_color(bg))
            c.circle(cx + 18, cy + cell_h / 2, 13, stroke=0, fill=1)
            draw_ic(cx + 18, cy + cell_h / 2)
            # title + value (right side)
            draw_text(title, cx + cell_w - 8, cy + cell_h - 16, font_name, 8, MUTED, align='right')
            draw_text(val, cx + cell_w - 8, cy + 8, font_bold, 13, accent, align='right')

    # ────────────── Analytical table ──────────────
    def draw_analytical_table(x, y, w, h):
        card(x, y, w, h, radius=14)
        c.setFillColor(hex_color(SKY_BG))
        c.roundRect(x + w - 26, y + h - 22, 14, 14, 3, stroke=0, fill=1)
        icon_table(x + w - 19, y + h - 15, color=SKY, size=4.5)
        draw_text('الجدول التحليلي', x + w - 34, y + h - 18, font_bold, 10.5, INK_SOFT, align='right')

        # column setup (RTL — period on the right)
        headers = [
            ('الفترة',          icon_clock,   SKY),
            ('الشمس',           icon_sun,     AMBER),
            ('المنزل',          icon_home,    SKY),
            ('شمس بيت',        icon_sun,     AMBER),
            ('شمس بطارية',     icon_battery, EMERALD),
            ('بطارية بيت',     icon_battery, EMERALD),
            ('شبكة بيت',       icon_grid,    VIOLET),
        ]
        n_cols = len(headers)
        tx = x + 12
        ty = y + 14
        tw = w - 24
        col_w = tw / n_cols
        # header row
        head_h = 28
        head_y = y + h - 38 - head_h
        c.setFillColor(hex_color('#f5f9ff'))
        c.roundRect(tx, head_y, tw, head_h, 8, stroke=0, fill=1)
        for i, (lbl, ic, color) in enumerate(headers):
            cx = tx + tw - (i + 0.5) * col_w  # rightmost first
            # icon
            ic(cx, head_y + head_h - 10, color=color, size=5.5)
            draw_text(lbl, cx, head_y + 6, font_bold, 8, INK_SOFT, align='center')
        # underline accent
        c.setFillColor(hex_color(SKY_SOFT))
        c.rect(tx, head_y, tw, 1.4, stroke=0, fill=1)

        # rows
        max_rows = 6
        rows = list(table_rows[:max_rows]) if table_rows else []
        row_h = (head_y - ty - 10) / max(1, max_rows)
        for r_idx, row in enumerate(rows):
            ry = head_y - (r_idx + 1) * row_h
            if r_idx % 2 == 1:
                c.setFillColor(hex_color('#fafcff'))
                c.rect(tx, ry, tw, row_h, stroke=0, fill=1)
            cells_vals = [
                str(row.get('label', '')),
                fmt_num(row.get('solar_generated_kwh', 0)),
                fmt_num(row.get('home_consumed_kwh', 0)),
                fmt_num(row.get('solar_to_home_kwh', 0)),
                fmt_num(row.get('solar_to_battery_kwh', 0)),
                fmt_num(row.get('battery_to_home_kwh', 0)),
                fmt_num(row.get('grid_to_home_kwh', 0)),
            ]
            for i, val in enumerate(cells_vals):
                cx = tx + tw - (i + 0.5) * col_w
                font = font_bold if i == 0 else font_name
                color = SKY if i == 0 else INK_SOFT
                draw_text(val, cx, ry + row_h / 2 - 3, font, 8.5, color, align='center')
        if not rows:
            draw_text('لا توجد بيانات كافية لهذه الفترة بعد.',
                      tx + tw / 2, head_y - 30, font_name, 9, MUTED, align='center')

    # ════════════ COMPOSE PAGE ════════════
    paint_bg()

    # left column origin
    lx = PAD
    rx = PAD + LEFT_W + GAP
    # top y
    top_y = height - PAD

    # Right column title block (compute height first so left hero matches its level)
    title_block_h = 110
    draw_right_title(rx, top_y, RIGHT_W)

    # LEFT — hero illustration  (slightly extends below right title)
    hero_h = 240
    hero_y = top_y - hero_h
    draw_hero_illustration(lx, hero_y, LEFT_W, hero_h)

    # LEFT — quick stats label
    qs_label_y = hero_y - 12
    draw_text('نظرة سريعة', lx + LEFT_W - 6, qs_label_y, font_bold, 10.5, INK_SOFT, align='right')
    c.setFillColor(hex_color(SKY))
    c.rect(lx + LEFT_W - 38, qs_label_y - 5, 32, 2.4, stroke=0, fill=1)

    # LEFT — quick stats rows
    stat_h = 50
    stat_y = qs_label_y - 10
    stats_list = [
        (lambda cx, cy: icon_sun(cx, cy, AMBER, 8),       AMBER,   AMBER_BG,   fmt_num(stats['solar_generated_kwh']),   'إنتاج الشمس',          'إجمالي التوليد خلال الفترة'),
        (lambda cx, cy: icon_home(cx, cy, SKY, 7),         SKY,     SKY_BG,     fmt_num(stats['home_consumed_kwh']),     'استهلاك المنزل',        'إجمالي الاستهلاك خلال الفترة'),
        (lambda cx, cy: icon_battery(cx, cy, EMERALD, 7, 0.65), EMERALD, EMERALD_BG, fmt_num(stats['solar_to_battery_kwh']),  'البطارية من الشمس شحن', 'الطاقة المخزنة في البطارية'),
        (lambda cx, cy: icon_chart(cx, cy, VIOLET, 6),     VIOLET,  VIOLET_BG,  fmt_pct(stats['avg_battery_soc']),       'متوسط البطارية',        'متوسط نسبة الشحن'),
    ]
    for ic, accent, accent_bg, val, title_txt, hint in stats_list:
        stat_y -= stat_h + 4
        draw_quick_stats_row(lx, stat_y, LEFT_W, stat_h, accent, accent_bg, ic, val, title_txt, hint)

    # LEFT — battery donut card
    donut_h = 150
    donut_y = stat_y - donut_h - 12
    draw_battery_donut_card(lx, donut_y, LEFT_W, donut_h, stats.get('avg_battery_soc'))

    # LEFT — trust badge
    trust_h = 60
    trust_y = donut_y - trust_h - 10
    if trust_y > PAD + 20:
        draw_trust_badge(lx, trust_y, LEFT_W, trust_h)

    # RIGHT — energy flow + trend chart row
    charts_top = top_y - title_block_h - 10
    charts_h = 220
    flow_w = (RIGHT_W - 10) * 0.42
    trend_w = (RIGHT_W - 10) * 0.58
    draw_energy_flow_card(rx, charts_top - charts_h, flow_w, charts_h)
    draw_trend_chart(rx + flow_w + 10, charts_top - charts_h, trend_w, charts_h)

    # RIGHT — summary card
    summary_top = charts_top - charts_h - 12
    summary_h = 130
    draw_summary_card(rx, summary_top - summary_h, RIGHT_W, summary_h)

    # RIGHT — analytical table
    table_top = summary_top - summary_h - 12
    table_h = max(140, table_top - PAD - 30)
    draw_analytical_table(rx, table_top - table_h, RIGHT_W, table_h)

    # Footer
    c.setStrokeColor(hex_color(LINE)); c.setLineWidth(0.6)
    c.line(PAD, PAD + 12, width - PAD, PAD + 12)
    c.setFont(font_name, 7.5)
    c.setFillColor(hex_color(MUTED))
    c.drawRightString(width - PAD, PAD + 2, ar('منصة الطاقة الشمسية • تقرير تحليلي'))
    c.drawString(PAD, PAD + 2, ar(f'صفحة 1'))

    c.showPage()
    c.save()
    buf.seek(0)
    filename = f"taqrir_{selected_view}_{selected_date.strftime('%Y-%m-%d')}.pdf"
    return Response(buf.getvalue(), mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@energy_bp.route('/deye', methods=['GET', 'POST'])
def deye_settings():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
    device = _active_device()
    if device is None:
        flash('لا يوجد جهاز مربوط بهذا الحساب بعد. أضف جهازك أولًا.', 'warning')
        return redirect(url_for('main.devices_manage', lang=_lang()))
    settings = _device_runtime_settings(device, allow_global_connection=False)
    ready, ready_message = _device_sync_ready(device)
    if request.method == 'POST':
        _save_deye_settings_to_device(device, request.form)
        db.session.commit()
        flash('تم حفظ إعدادات الربط لهذا الجهاز.', 'success')
        return redirect(url_for('main.deye_settings', lang=_lang()))
    return render_template('deye_settings.html', settings=settings, current_device=device, device_ready=ready, device_ready_message=ready_message, ui_lang=_lang())


@energy_bp.route('/test-connection', methods=['POST'])
def test_connection():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    device = _active_device()
    ready, ready_message = _device_sync_ready(device)
    if not ready:
        flash(ready_message, 'warning')
        return redirect(url_for('main.deye_settings', lang=_lang()))
    client = DeyeClient(_device_runtime_settings(device, allow_global_connection=False))
    try:
        token = client.obtain_token()
        account = client.account_info(token)
        stations = client.station_list(token)
        log_event('success', 'تم اختبار الاتصال مع Deye بنجاح', {'account': account, 'stations_count': len(stations)})
        flash(f'تم الاتصال بنجاح. عدد المحطات: {len(stations)}', 'success')
    except Exception as exc:
        log_event('danger', f'فشل اختبار الاتصال: {exc}')
        flash(f'فشل اختبار الاتصال: {exc}', 'danger')
    return redirect(url_for('main.deye_settings', lang=_lang()))


@energy_bp.route('/sync-now', methods=['POST'])
def sync_now():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    try:
        sync_now_internal(trigger='manual')
        flash('تمت المزامنة وجلب البيانات بنجاح', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    except Exception as exc:
        log_event('danger', f'فشلت المزامنة: {exc}')
        flash(f'فشلت المزامنة: {exc}', 'danger')
    return redirect(url_for('main.dashboard', lang=_lang()))


@energy_bp.route('/diagnostics')
def diagnostics():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
    latest = _latest_reading()
    raw_data = {}
    raw_text = '{}'
    if latest and latest.raw_json:
        try:
            raw_data = json.loads(latest.raw_json)
            raw_text = to_json(raw_data)
        except Exception:
            raw_data = {'raw_text': latest.raw_json}
            raw_text = latest.raw_json
    raw_data = sanitize_response_payload(raw_data)
    return render_template('diagnostics.html', latest=latest, raw_data=raw_data, raw_text=raw_text, debug_tools_enabled=current_app.config.get('DEBUG_TOOLS_ENABLED') and is_system_admin(),
                           format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']), ui_lang=_lang())


@energy_bp.route('/live-data')
def live_data():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
    from datetime import UTC, datetime, timedelta
    from ..services.utils import utc_to_local
    latest = _latest_reading()
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
            rows = (scoped_query(Reading)
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


@energy_bp.route('/loads', methods=['GET', 'POST'])
def loads_page():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    latest = _latest_reading()
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
                db.sessio