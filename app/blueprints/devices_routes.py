from __future__ import annotations

# Heavy v10.1 split blueprint. The route logic is intentionally moved out of
# main.py while importing legacy helpers/services from main during the migration
# window. This keeps behavior stable while main.py shrinks safely.
from flask import Blueprint
from ..services.energy_integrations import provider_catalog
from .main import *  # noqa: F401,F403 - transitional legacy dependency bridge
from . import main as _legacy_main

for _legacy_name in dir(_legacy_main):
    if _legacy_name.startswith('_') and not _legacy_name.startswith('__'):
        globals()[_legacy_name] = getattr(_legacy_main, _legacy_name)



# Heavy v10.5.19 — dynamic device providers UI helpers.
_DEVICE_FIELD_LABELS_AR = {
    'deye_app_id': 'Deye App ID', 'deye_app_secret': 'Deye App Secret', 'deye_email': 'بريد Deye', 'deye_password_or_hash': 'كلمة مرور Deye أو SHA-256',
    'deye_device_sn': 'Device SN', 'deye_logger_sn': 'Logger SN', 'deye_plant_id': 'Plant ID', 'battery_capacity_kwh': 'سعة البطارية kWh',
    'site_id': 'Site ID', 'api_key': 'API Key', 'system_id': 'System ID', 'oauth_access_token': 'OAuth Access Token', 'installation_id': 'Installation ID',
    'access_token': 'Access Token', 'local_base_url': 'الرابط المحلي للجهاز', 'client_id': 'Client ID', 'client_secret': 'Client Secret',
    'energy_site_id': 'Energy Site ID', 'base_url': 'Base URL', 'username': 'اسم المستخدم', 'password': 'كلمة المرور', 'system_code': 'System Code', 'station_code': 'Station Code',
    'app_id': 'App ID', 'app_secret': 'App Secret', 'logger_sn': 'Logger SN', 'device_sn': 'Device SN', 'station_id': 'Station ID',
    'app_key': 'App Key', 'refresh_token': 'Refresh Token', 'region': 'المنطقة', 'account': 'الحساب', 'powerstation_id': 'Power Station ID',
    'org_id': 'Organization ID', 'inverter_sn': 'Inverter SN', 'api_secret': 'API Secret', 'dtu_base_url': 'OpenDTU URL', 'mqtt_host': 'MQTT Host',
    'mqtt_username': 'MQTT Username', 'mqtt_password': 'MQTT Password', 'entity_id': 'Entity ID', 'device_id': 'Device ID', 'serial_number': 'Serial Number',
}
_DEVICE_FIELD_LABELS_EN = {
    'deye_app_id': 'Deye App ID', 'deye_app_secret': 'Deye App Secret', 'deye_email': 'Deye email', 'deye_password_or_hash': 'Deye password or SHA-256',
    'deye_device_sn': 'Device SN', 'deye_logger_sn': 'Logger SN', 'deye_plant_id': 'Plant ID', 'battery_capacity_kwh': 'Battery capacity kWh',
    'site_id': 'Site ID', 'api_key': 'API key', 'system_id': 'System ID', 'oauth_access_token': 'OAuth access token', 'installation_id': 'Installation ID',
    'access_token': 'Access token', 'local_base_url': 'Local device URL', 'client_id': 'Client ID', 'client_secret': 'Client secret',
    'energy_site_id': 'Energy site ID', 'base_url': 'Base URL', 'username': 'Username', 'password': 'Password', 'system_code': 'System code', 'station_code': 'Station code',
    'app_id': 'App ID', 'app_secret': 'App secret', 'logger_sn': 'Logger SN', 'device_sn': 'Device SN', 'station_id': 'Station ID',
    'app_key': 'App key', 'refresh_token': 'Refresh token', 'region': 'Region', 'account': 'Account', 'powerstation_id': 'Power station ID',
    'org_id': 'Organization ID', 'inverter_sn': 'Inverter SN', 'api_secret': 'API secret', 'dtu_base_url': 'OpenDTU URL', 'mqtt_host': 'MQTT host',
    'mqtt_username': 'MQTT username', 'mqtt_password': 'MQTT password', 'entity_id': 'Entity ID', 'device_id': 'Device ID', 'serial_number': 'Serial number',
}
_DEVICE_FIELD_HINTS_AR = {
    'deye_password_or_hash': 'يمكنك إدخال كلمة المرور أو SHA-256 حسب طريقة الربط.',
    'local_base_url': 'مثال: http://192.168.1.50 — يجب أن يكون الجهاز متاحًا من الشبكة.',
    'base_url': 'رابط API الأساسي من شركة الجهاز أو مزود الخدمة.',
    'oauth_access_token': 'يفضل أن يكون Token مخصص للقراءة فقط.',
    'access_token': 'يفضل أن يكون Token مخصص للقراءة فقط.',
    'api_key': 'لا يتم عرضه كاملًا لاحقًا للحفاظ على الخصوصية.',
    'api_secret': 'سيتم حفظه بشكل مخفي ولا يظهر كاملًا.',
    'app_secret': 'سيتم حفظه بشكل مخفي ولا يظهر كاملًا.',
    'client_secret': 'سيتم حفظه بشكل مخفي ولا يظهر كاملًا.',
}
_DEVICE_FIELD_HINTS_EN = {
    'deye_password_or_hash': 'Enter the Deye password or SHA-256 hash depending on your connection method.',
    'local_base_url': 'Example: http://192.168.1.50 — device must be reachable from the network.',
    'base_url': 'Base API URL from the provider.',
    'oauth_access_token': 'Prefer a read-only token.',
    'access_token': 'Prefer a read-only token.',
    'api_key': 'Stored privately and masked later.',
    'api_secret': 'Stored privately and masked later.',
    'app_secret': 'Stored privately and masked later.',
    'client_secret': 'Stored privately and masked later.',
}


def _provider_specs_for_ui(lang=None):
    lang = 'en' if (lang or _lang()) == 'en' else 'ar'
    labels = _DEVICE_FIELD_LABELS_EN if lang == 'en' else _DEVICE_FIELD_LABELS_AR
    hints = _DEVICE_FIELD_HINTS_EN if lang == 'en' else _DEVICE_FIELD_HINTS_AR
    items = []
    for spec in provider_catalog():
        fields = []
        for name in list(spec.required_fields or ()) + list(spec.optional_fields or ()):  # keep provider ordering
            fields.append({
                'name': name,
                'label': labels.get(name, name.replace('_', ' ').title()),
                'required': name in (spec.required_fields or ()),
                'secret': any(word in name.lower() for word in ['password', 'secret', 'token', 'key']),
                'hint': hints.get(name, ''),
            })
        items.append({
            'code': spec.code,
            'name': spec.name,
            'provider': spec.provider,
            'auth_mode': spec.auth_mode,
            'base_url': spec.base_url or '',
            'category': spec.category,
            'notes': spec.notes_en if lang == 'en' else spec.notes_ar,
            'fields': fields,
        })
    return items


def _device_provider_spec(code: str | None):
    code = (code or 'deye').strip().lower()
    for spec in provider_catalog():
        if spec.code == code:
            return spec
    return next((s for s in provider_catalog() if s.code == 'deye'), None)


def _save_device_fields(device: AppDevice, owner_user_id: int):
    """Dynamic provider-aware device save. Keeps Deye compatibility intact."""
    provider_code = (request.form.get('device_type') or request.form.get('provider_code') or device.device_type or 'deye').strip().lower()
    spec = _device_provider_spec(provider_code)
    device.name = (request.form.get('name', '') or '').strip() or device.name or (spec.name if spec else 'My Solar Device')
    device.device_type = provider_code
    device.api_provider = (getattr(spec, 'provider', None) or request.form.get('api_provider') or provider_code or 'custom').strip().lower()
    device.api_base_url = (request.form.get('api_base_url', '') or getattr(spec, 'base_url', '') or device.api_base_url or '').strip() or None
    device.timezone = (request.form.get('timezone', current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')) or current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')).strip()
    device.auth_mode = (getattr(spec, 'auth_mode', None) or request.form.get('auth_mode', 'wizard') or 'wizard').strip().lower()
    device.notes = (request.form.get('notes', '') or '').strip()
    device.owner_user_id = owner_user_id
    device.is_active = request.form.get('is_active') == 'on'

    existing_creds = _safe_json_loads(getattr(device, 'credentials_json', None))
    existing_settings = _safe_json_loads(getattr(device, 'settings_json', None))
    creds = dict(existing_creds)
    settings = dict(existing_settings)
    settings.update({
        'provider_code': provider_code,
        'provider_name': getattr(spec, 'name', provider_code) if spec else provider_code,
        'api_provider': device.api_provider,
        'api_base_url': device.api_base_url or '',
        'auth_mode': device.auth_mode,
        'timezone': device.timezone,
    })

    all_fields = []
    if spec:
        all_fields = list(spec.required_fields or ()) + list(spec.optional_fields or ())
    # Also preserve common identifiers for older forms.
    for extra in ['station_id', 'device_uid', 'external_device_id', 'plant_name', 'deye_plant_id', 'deye_device_sn', 'deye_logger_sn']:
        if extra not in all_fields:
            all_fields.append(extra)

    for field in all_fields:
        form_key = f'provider_field_{field}'
        value = preserve_secret_form_value(request.form, form_key, settings.get(field) or creds.get(field) or '')
        if value in (None, ''):
            # fall back to legacy field names if they exist in older templates/postbacks
            value = preserve_secret_form_value(request.form, field, settings.get(field) or creds.get(field) or '')
        if any(word in field.lower() for word in ['password', 'secret', 'token', 'key']) or field in {'deye_email', 'username', 'account'}:
            if value:
                creds[field] = value
        else:
            if value:
                settings[field] = value

    # Deye compatibility mappings used by current sync engine.
    if provider_code == 'deye':
        if creds.get('deye_password_or_hash') and not creds.get('deye_password') and not creds.get('deye_password_hash'):
            creds['deye_password'] = creds.get('deye_password_or_hash')
        if settings.get('deye_plant_id'):
            device.station_id = settings.get('deye_plant_id')
        else:
            device.station_id = preserve_secret_form_value(request.form, 'station_id', device.station_id or '') or device.station_id
        if settings.get('deye_device_sn'):
            device.device_uid = settings.get('deye_device_sn')
        else:
            device.device_uid = preserve_secret_form_value(request.form, 'device_uid', device.device_uid or '') or device.device_uid
        device.plant_name = (request.form.get('plant_name', '') or settings.get('deye_plant_name') or device.plant_name or device.name).strip()
    else:
        device.station_id = settings.get('station_id') or settings.get('site_id') or settings.get('system_id') or settings.get('installation_id') or settings.get('powerstation_id') or device.station_id
        device.device_uid = settings.get('device_uid') or settings.get('device_sn') or settings.get('inverter_sn') or settings.get('serial_number') or settings.get('device_id') or device.device_uid
        device.external_device_id = settings.get('external_device_id') or settings.get('entity_id') or settings.get('energy_site_id') or device.external_device_id
        device.plant_name = (request.form.get('plant_name', '') or settings.get('plant_name') or settings.get('station_name') or device.plant_name or device.name).strip()

    device.credentials_json = json.dumps(creds, ensure_ascii=False)
    device.settings_json = json.dumps(settings, ensure_ascii=False)
    device.updated_at = datetime.utcnow()


def _device_payload(device: AppDevice | None):
    if device is None:
        return {}, {}
    creds = _safe_json_loads(getattr(device, 'credentials_json', None))
    settings = _safe_json_loads(getattr(device, 'settings_json', None))
    # Keep legacy keys for Deye templates and add generic provider payload for dynamic forms.
    normalized_creds = {
        **creds,
        'deye_email': creds.get('deye_email') or creds.get('email') or '',
        'deye_password': creds.get('deye_password') or creds.get('password') or '',
        'deye_app_id': creds.get('deye_app_id') or creds.get('app_id') or '',
        'deye_app_secret': creds.get('deye_app_secret') or creds.get('app_secret') or '',
    }
    normalized_settings = {
        **settings,
        'deye_region': settings.get('deye_region') or settings.get('region') or 'EMEA',
        'api_base_url': settings.get('api_base_url') or getattr(device, 'api_base_url', '') or '',
    }
    return normalized_creds, normalized_settings

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
    return render_template('devices_manage.html', devices_list=devices_list, provider_specs=_provider_specs_for_ui(_lang()), ui_lang=_lang(), current_device_id=session.get('current_device_id'))


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
    return render_template('device_form.html', device=device, device_creds=creds, device_settings=device_settings, provider_specs=_provider_specs_for_ui(_lang()), mode='edit', ui_lang=_lang())


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


