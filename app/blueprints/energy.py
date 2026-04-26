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
    smart_overview = get_latest_historical_overview(latest, weather=weather, settings=settings, context='dashboard')

    production_summary = get_production_summary(tz_name)
    smart_loads = _smart_load_suggestions(latest)
    actual_surplus = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
    recent_events = get_recent_event_logs(8)

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
    if not latest:
        return {'ok': False, 'empty': True}
    weather = get_weather_for_latest(latest)
    settings = load_settings()
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    solar_prediction = build_pre_sunset_prediction(latest, weather, settings)
    actual_surplus = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
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


@energy_bp.route('/plant-info')
def plant_info():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    latest = _latest_reading()
    settings = load_settings()
    tz_name = current_app.config['LOCAL_TIMEZONE']
    production_summary = get_production_summary(tz_name)
    return render_template('plant_info.html', latest=latest, settings=settings,
                           production_summary=production_summary,
                           format_energy=format_energy,
                           format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang())


@energy_bp.route('/api/raw-debug')
def api_raw_debug():
    if not is_system_admin() or not current_app.config.get('DEBUG_TOOLS_ENABLED'):
        return {'ok': False, 'error': 'Debug tools are disabled.'}, 403
    latest = _latest_reading()
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

    payload = {
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
    return sanitize_response_payload(payload)


