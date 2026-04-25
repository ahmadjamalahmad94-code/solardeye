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

notifications_routes_bp = Blueprint('notifications_routes', __name__)

@notifications_routes_bp.route('/alerts')
def alerts():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    logs = scoped_query(SyncLog).order_by(SyncLog.created_at.desc()).limit(200).all()
    return render_template('alerts.html', logs=logs,
                           format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']), ui_lang=_lang())


@notifications_routes_bp.route('/notifications/action', methods=['POST'])
def notifications_action():
    action = (request.args.get('action') or request.form.get('notification_action') or '').strip().lower()
    section = (request.args.get('section') or request.form.get('section') or '').strip().lower()
    if not action:
        flash('الإجراء المطلوب غير محدد.', 'warning')
        return redirect(url_for('main.notifications_settings'))
    try:
        settings = apply_form_settings_overrides(load_settings(), request.form)
        latest = _latest_reading()
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


@notifications_routes_bp.route('/channels', methods=['GET', 'POST'])
def channels():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    lang = request.args.get('lang') or request.form.get('lang')
    if request.method == 'POST':
        action = (request.form.get('channel_action') or '').strip().lower()
        section = (request.form.get('channel_section') or '').strip().lower()
        if action.startswith('save_'):
            section = action.removeprefix('save_')
        if section in CHANNEL_FORM_FIELDS:
            _save_channels_settings_from_form(request.form, section=section)
        settings = load_settings()

        if action == 'save_telegram':
            flash('تم حفظ إعدادات Telegram بنجاح', 'success')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'save_telegram_buttons':
            flash('تم حفظ أزرار Telegram بنجاح', 'success')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'save_sms':
            flash('تم حفظ إعدادات SMS بنجاح', 'success')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'set_webhook':
            ok, msg = _telegram_set_webhook(settings)
            flash(('تم تفعيل Webhook بنجاح' if ok else f'فشل تفعيل Webhook: {msg}'), 'success' if ok else 'danger')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'check_webhook':
            info = _telegram_webhook_info(settings)
            if info.get('ok'):
                extra = info.get('url') or 'لا يوجد رابط'
                flash(f"حالة Webhook سليمة. الرابط الحالي: {extra}", 'info')
            else:
                flash(f"فشل فحص Webhook: {info.get('description') or info.get('last_error_message') or 'خطأ غير معروف'}", 'danger')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'delete_webhook':
            ok, msg = _telegram_delete_webhook(settings)
            flash(('تم إلغاء Webhook بنجاح' if ok else f'فشل إلغاء Webhook: {msg}'), 'success' if ok else 'danger')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'telegram_test':
            ok, msg = send_telegram_message(settings, 'اختبار Telegram', 'هذه رسالة اختبار من صفحة ربط Telegram وSMS.')
            flash(('تم إرسال اختبار Telegram بنجاح' if ok else f'فشل إرسال اختبار Telegram: {msg}'), 'success' if ok else 'danger')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'telegram_menu':
            ok, msg = send_telegram_menu(settings)
            flash(('تم إرسال القائمة التفاعلية بنجاح' if ok else f'فشل إرسال القائمة التفاعلية: {msg}'), 'success' if ok else 'danger')
            return redirect(url_for('main.channels', lang=lang))

        if action == 'sms_test':
            ok, msg = send_sms_message(settings, 'اختبار SMS', 'هذه رسالة اختبار من صفحة ربط Telegram وSMS.')
            flash(('تم إرسال اختبار SMS بنجاح' if ok else f'فشل إرسال اختبار SMS: {msg}'), 'success' if ok else 'danger')
            return redirect(url_for('main.channels', lang=lang))

        flash('الإجراء المطلوب غير معروف', 'warning')
        return redirect(url_for('main.channels', lang=lang))

    latest = _latest_reading()
    settings = load_settings()
    weather = get_weather_for_latest(latest) if latest else None
    telegram_webhook_url = _telegram_webhook_target_url()
    webhook_info = _telegram_webhook_info(settings)

    return render_template(
        'channels.html',
        title='ربط Telegram و SMS',
        latest=latest,
        settings=settings,
        weather=weather,
        telegram_webhook_url=telegram_webhook_url,
        webhook_info=webhook_info,
    )


@notifications_routes_bp.route('/notifications', methods=['GET', 'POST'])
def notifications_settings():
    energy_guard = _energy_portal_guard()
    if energy_guard:
        return energy_guard
    settings = load_settings()
    if request.method == 'POST':
        section = (request.args.get('section') or request.form.get('settings_section') or '').strip().lower()
        try:
            if section:
                save_notification_settings_from_form(request.form, section=section)
                success_message = 'تم حفظ هذا القسم بنجاح'
            else:
                save_all_notification_settings_from_form(request.form)
                success_message = 'تم حفظ جميع إعدادات الإشعارات بنجاح'
        except Exception as exc:
            if _is_ajax_request():
                return _json_response(False, f'فشل حفظ الإعدادات: {exc}'), 400
            flash(f'فشل حفظ الإعدادات: {exc}', 'danger')
            return redirect(url_for('main.notifications_settings', tab=section or 'general'))

        if _is_ajax_request():
            return _json_response(True, success_message, saved_section=section or 'all')
        flash(success_message, 'success')
        return redirect(url_for('main.notifications_settings', tab=section or 'general'))

    settings = load_settings()
    rules = load_notification_rules(settings)
    recent_notifications = scoped_query(NotificationLog).order_by(NotificationLog.created_at.desc()).limit(30).all()
    notification_preview = session.pop('notification_preview', None)
    latest = _latest_reading()
    weather = get_weather_for_latest(latest) if latest else None
    telegram_webhook_url = _telegram_webhook_target_url()
    webhook_info = _telegram_webhook_info(settings)
    return render_template(
        'notifications.html', settings=settings, rules=rules,
        recent_notifications=recent_notifications,
        notification_preview=notification_preview,
        latest=latest,
        weather=weather,
        telegram_webhook_url=telegram_webhook_url,
        webhook_info=webhook_info,
        active_tab=(request.args.get('tab') or 'general'),
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )


@notifications_routes_bp.route('/notifications/test', methods=['POST'])
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


@notifications_routes_bp.route('/notifications/test-section', methods=['POST'])
def notifications_test_section():
    try:
        section = request.form.get('section', 'periodic').strip().lower()
        settings = apply_form_settings_overrides(load_settings(), request.form)
        latest = _latest_reading()
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


@notifications_routes_bp.route('/telegram/menu/send', methods=['POST'])
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


@notifications_routes_bp.route('/telegram/webhook', methods=['GET', 'POST'], strict_slashes=False)
def telegram_webhook():
    if request.method == 'GET':
        return Response(
            json.dumps({'ok': True, 'message': 'Telegram webhook is ready'}, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )

    secret = (current_app.config.get('TELEGRAM_WEBHOOK_SECRET') or '').strip()
    if secret:
        supplied = (request.headers.get('X-Telegram-Bot-Api-Secret-Token') or request.args.get('secret') or '').strip()
        if supplied != secret:
            return Response(
                json.dumps({'ok': False, 'error': 'invalid webhook secret'}, ensure_ascii=False),
                status=403,
                mimetype='application/json'
            )

    data = request.get_json(silent=True) or {}
    if not data:
        return Response(
            json.dumps({'ok': True, 'message': 'No update payload'}, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )

    settings = load_settings()
    try:
        ok, resp = process_telegram_update(settings, data)
        return Response(
            json.dumps({'ok': bool(ok), 'message': str(resp)}, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )
    except Exception as exc:
        current_app.logger.exception('Telegram webhook processing failed')
        return Response(
            json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False),
            status=200,
            mimetype='application/json'
        )


@notifications_routes_bp.route('/notifications/feed')
def notifications_feed():
    if not session.get('logged_in'):
        return jsonify({'count': 0, 'items': []})
    items = _support_notification_payload(limit=5, include_closed=False)
    user = _active_user()
    try:
        total, mail_count, ticket_count = unread_counts(user)
    except Exception:
        total = (getattr(g, 'mail_notification_count', 0) or 0) + (getattr(g, 'ticket_notification_count', 0) or 0)
        mail_count = getattr(g, 'mail_notification_count', 0) or 0
        ticket_count = getattr(g, 'ticket_notification_count', 0) or 0
    return jsonify({'count': total, 'mail_count': mail_count, 'ticket_count': ticket_count, 'items': items})


@notifications_routes_bp.route('/notification-center')
@notifications_routes_bp.route('/notifications/center')
def notification_center():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login', lang=_lang()))
    try:
        items = _support_notification_payload(limit=200, include_closed=True)
    except Exception as exc:
        current_app.logger.exception('notification_center failed: %s', exc)
        items = []
        flash('تعذر تحميل مركز الإشعارات، تم فتح الصفحة بوضع آمن.', 'warning')
    return render_template('notification_center.html', items=items, ui_lang=_lang(), format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']))


@notifications_routes_bp.route('/notifications/mark-read', methods=['POST'])
def notifications_mark_read():
    if not session.get('logged_in'):
        return jsonify({'ok': False}), 401
    user = _active_user()
    now = datetime.utcnow()
    event_id = int(request.form.get('event_id') or 0)
    q = NotificationEvent.query.filter_by(target_user_id=getattr(user, 'id', None), is_read=False)
    if event_id:
        q = q.filter_by(id=event_id)
    changed = 0
    for ev in q.all():
        ev.is_read = True
        ev.read_at = now
        ev.status = 'read'
        changed += 1
    db.session.commit()
    total, mail, ticket = unread_counts(user)
    return jsonify({'ok': True, 'changed': changed, 'count': total, 'mail_count': mail, 'ticket_count': ticket})


