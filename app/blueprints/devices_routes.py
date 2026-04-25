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

devices_bp = Blueprint('devices_routes', __name__)

@devices_bp.route('/devices/select/<int:device_id>', methods=['POST'])
def select_device(device_id: int):
    device = AppDevice.query.filter_by(id=device_id, is_active=True).first()
    user = _active_user()
    if not device or (user and device.owner_user_id != user.id and not is_system_admin()):
        flash('الجهاز المطلوب غير متاح ضمن حسابك.', 'warning')
        return redirect(url_for('main.devices', lang=_lang()))
    session['current_device_id'] = device.id
    session['current_device_type'] = device.device_type or 'deye'
    flash(f'تم اختيار الجهاز: {device.name}', 'success')
    return redirect(request.referrer or url_for('main.dashboard', lang=_lang()))


@devices_bp.route('/devices/manage', methods=['GET', 'POST'])
def devices_manage():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    guard = _require_subscription_guard()
    if guard:
        return guard
    user = _active_user()
    if user is None:
        flash('يجب تسجيل الدخول أولًا.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        device = AppDevice(owner_user_id=user.id)
        _save_device_fields(device, user.id)
        db.session.add(device)
        db.session.flush()
        if not user.preferred_device_id:
            user.preferred_device_id = device.id
            session['current_device_id'] = device.id
            session['current_device_type'] = device.device_type or 'deye'
        db.session.commit()
        flash('تمت إضافة الجهاز بنجاح.', 'success')
        return redirect(url_for('main.devices_manage', lang=_lang()))

    devices_list = AppDevice.query.filter_by(owner_user_id=user.id).order_by(AppDevice.name.asc(), AppDevice.id.asc()).all()
    return render_template('devices_manage.html', devices_list=devices_list, ui_lang=_lang(), current_device_id=session.get('current_device_id'))


@devices_bp.route('/devices/manage/<int:device_id>/edit', methods=['GET', 'POST'])
def device_edit(device_id: int):
    user = _active_user()
    device = AppDevice.query.filter_by(id=device_id).first_or_404()
    if not (is_system_admin() or (user and device.owner_user_id == user.id)):
        flash('لا يمكنك تعديل هذا الجهاز.', 'warning')
        return redirect(url_for('main.devices_manage', lang=_lang()))

    if request.method == 'POST':
        _save_device_fields(device, device.owner_user_id or (user.id if user else None))
        db.session.commit()
        flash('تم تحديث الجهاز بنجاح.', 'success')
        return redirect(url_for('main.devices_manage', lang=_lang()))

    creds, device_settings = _device_payload(device)
    return render_template('device_form.html', device=device, device_creds=creds, device_settings=device_settings, mode='edit', ui_lang=_lang())


@devices_bp.route('/devices/manage/<int:device_id>/toggle', methods=['POST'])
def device_toggle(device_id: int):
    user = _active_user()
    device = AppDevice.query.filter_by(id=device_id).first_or_404()
    if not (is_system_admin() or (user and device.owner_user_id == user.id)):
        flash('لا يمكنك تعديل هذا الجهاز.', 'warning')
        return redirect(url_for('main.devices_manage', lang=_lang()))
    device.is_active = not bool(device.is_active)
    db.session.commit()
    flash('تم تحديث حالة الجهاز.', 'success')
    return redirect(url_for('main.devices_manage', lang=_lang()))


@devices_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding_wizard():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))

    step = (request.args.get('step') or request.form.get('step') or getattr(user, 'onboarding_step', None) or 'welcome').strip().lower()
    allowed_steps = ['welcome', 'device', 'notifications', 'finish']
    if step not in allowed_steps:
        step = 'welcome'

    if request.method == 'POST':
        action = (request.form.get('action') or 'next').strip().lower()
        if step == 'device' and action in {'next', 'save'}:
            existing = AppDevice.query.filter_by(owner_user_id=user.id).order_by(AppDevice.id.asc()).first()
            if existing is None:
                existing = AppDevice(owner_user_id=user.id)
                db.session.add(existing)
                db.session.flush()
            _save_device_fields(existing, user.id)
            if not user.preferred_device_id:
                user.preferred_device_id = existing.id
            session['current_device_id'] = user.preferred_device_id or existing.id
            session['current_device_type'] = existing.device_type or 'deye'
        elif step == 'notifications' and action in {'next', 'save'}:
            if request.form.get('enable_notifications') == 'on':
                _save_setting_value('notifications_enabled', 'true')
            elif request.form.get('disable_notifications') == 'on':
                _save_setting_value('notifications_enabled', 'false')

        if action == 'skip':
            next_step = {'welcome': 'device', 'device': 'notifications', 'notifications': 'finish', 'finish': 'finish'}.get(step, 'finish')
        elif action == 'back':
            next_step = {'finish': 'notifications', 'notifications': 'device', 'device': 'welcome', 'welcome': 'welcome'}.get(step, 'welcome')
        else:
            next_step = {'welcome': 'device', 'device': 'notifications', 'notifications': 'finish', 'finish': 'finish'}.get(step, 'finish')

        if step == 'finish' or action == 'complete':
            user.onboarding_completed = True
            user.onboarding_step = 'done'
            db.session.commit()
            flash('اكتمل الإعداد الأولي بنجاح ✨', 'success')
            return redirect(url_for('main.dashboard', lang=_lang()))

        user.onboarding_step = next_step
        db.session.commit()
        return redirect(url_for('main.onboarding_wizard', step=next_step, lang=_lang()))

    devices_list = AppDevice.query.filter_by(owner_user_id=user.id).order_by(AppDevice.id.asc()).all()
    wizard_device = devices_list[0] if devices_list else None
    wizard_creds, wizard_device_settings = _device_payload(wizard_device)
    settings = load_settings()
    return render_template('onboarding_wizard.html', step=step, user_obj=user, devices_list=devices_list, wizard_device=wizard_device, wizard_creds=wizard_creds, wizard_device_settings=wizard_device_settings, settings=settings, ui_lang=_lang())


@devices_bp.route('/onboarding/skip', methods=['POST'])
def onboarding_skip():
    user = _active_user()
    if user is None:
        return redirect(url_for('auth.login'))
    user.onboarding_completed = True
    user.onboarding_step = 'done'
    db.session.commit()
    flash('تم تخطي الإعداد الأولي، ويمكنك الرجوع إليه لاحقًا.', 'info')
    return redirect(url_for('main.dashboard', lang=_lang()))


@devices_bp.route('/devices')
def devices():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    latest = _latest_reading()
    devices_list = _device_collection()
    active_device = _active_device()
    settings = load_settings()
    battery_details = build_battery_details(latest)
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery_insights = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    system_status = build_system_status(latest, battery_insights)
    system_state = system_status['title']
    tz_name = current_app.config['LOCAL_TIMEZONE']
    production_summary = get_production_summary(tz_name)
    return render_template('devices.html', latest=latest, settings=settings, devices_list=devices_list, active_device=active_device,
                           battery_details=battery_details,
                           battery_insights=battery_insights,
                           system_state=system_state,
                           production_summary=production_summary,
                           format_energy=format_energy,
                           format_power=format_power,
                           format_local=lambda dt: format_local_datetime(dt, tz_name), ui_lang=_lang())


@devices_bp.route('/battery-lab')
def battery_lab():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    latest = _latest_reading()
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
        scoped_query(Reading)
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


