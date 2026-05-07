from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename
from uuid import uuid4
import json

from ..extensions import db
from ..models import AppDevice, AppUser, NotificationLog, ServiceHeartbeat, SubscriptionPlan, SyncLog
from ..services.backup_service import backup_settings, create_backup, list_backups, restore_backup, set_setting, save_uploaded_backup
from ..services.platform_audit import audit_project
from ..services.scope import has_permission, is_system_admin
from ..services.rbac import admin_landing_url
from ..services.service_monitor import service_display_name, service_message
from ..services.utils import format_local_datetime
from ..services.landing_content import (
    get_landing_settings,
    save_landing_settings,
    save_landing_section,
    plan_landing_meta,
    update_plan_landing_meta,
    set_setting_value,
    SOCIAL_LINKS,
)

platform_bp = Blueprint('platform', __name__)


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _admin_guard(permission: str = 'can_view_logs'):
    if is_system_admin() or has_permission(permission):
        return None
    flash('This page is not available for your account.' if _lang() == 'en' else 'هذه الصفحة غير متاحة لحسابك.', 'warning')
    return redirect(admin_landing_url(_lang()))


def _platform_status_summary() -> dict:
    heartbeats = ServiceHeartbeat.query.order_by(ServiceHeartbeat.service_label.asc(), ServiceHeartbeat.service_key.asc()).all()
    hb_map = {row.service_key: row for row in heartbeats}
    scheduler_obj = getattr(current_app, 'scheduler', None)
    scheduler_jobs = []
    scheduler_visible = False
    scheduler_hb = hb_map.get('scheduler')
    scheduler_recent = False
    try:
        scheduler_visible = bool(scheduler_obj and scheduler_obj.running)
        scheduler_jobs = scheduler_obj.get_jobs() if scheduler_obj else []
    except Exception:
        scheduler_visible = False
        scheduler_jobs = []
    try:
        scheduler_recent = bool(
            scheduler_hb
            and scheduler_hb.last_seen_at
            and (datetime.utcnow() - scheduler_hb.last_seen_at) <= timedelta(minutes=45)
            and scheduler_hb.status in ['ok', 'running', 'success']
        )
    except Exception:
        scheduler_recent = False
    scheduler_running = scheduler_visible or scheduler_recent
    service_items = [
        {'key': 'scheduler', 'status': 'ok' if scheduler_running else ('warning' if current_app.config.get('DISABLE_INTERNAL_SCHEDULER') else 'failed'), 'heartbeat': scheduler_hb},
        {'key': 'deye_auto_sync', 'heartbeat': hb_map.get('app.blueprints.main.sync_now_internal') or hb_map.get('deye_auto_sync')},
        {'key': 'advanced_notifications_check', 'heartbeat': hb_map.get('app.blueprints.notifications.run_advanced_notification_scheduler')},
        {'key': 'weather_change_check', 'heartbeat': hb_map.get('app.blueprints.notifications.run_weather_checks')},
        {'key': 'database_backup', 'heartbeat': hb_map.get('database_backup') or hb_map.get('app.services.backup_service.scheduled_backup_job')},
        {'key': 'database_backup_drive', 'heartbeat': hb_map.get('database_backup_drive')},
    ]
    cards = []
    ok_count = warning_count = failed_count = 0
    last_seen_values = []
    for item in service_items:
        hb = item.get('heartbeat')
        status = item.get('status') or (hb.status if hb else 'warning')
        if status in ['ok', 'success', 'running']:
            ok_count += 1
        elif status == 'warning':
            warning_count += 1
        else:
            failed_count += 1
        if hb and hb.last_seen_at:
            last_seen_values.append(hb.last_seen_at)
        cards.append({
            'key': item['key'],
            'label': service_display_name(item['key'], _lang()),
            'status': status,
            'message': service_message(hb.message, _lang()) if hb else ('Waiting for first heartbeat.' if _lang() == 'en' else 'بانتظار أول نبضة.'),
            'last_seen_at': hb.last_seen_at if hb else None,
        })
    latest_sync = SyncLog.query.order_by(SyncLog.created_at.desc()).first()
    latest_notif = NotificationLog.query.order_by(NotificationLog.created_at.desc()).first()
    return {
        'scheduler_running': scheduler_running,
        'scheduler_jobs_count': len(scheduler_jobs),
        'ok_count': ok_count,
        'warning_count': warning_count,
        'failed_count': failed_count,
        'cards': cards,
        'latest_sync': latest_sync,
        'latest_notif': latest_notif,
        'last_seen_at': max(last_seen_values) if last_seen_values else None,
    }




def _smart_analysis() -> dict:
    """Collects live DB metrics and generates predictive alerts with root causes and fix steps."""
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)

    total_users     = AppUser.query.count()
    total_devices   = AppDevice.query.filter_by(is_active=True).count()
    offline_devices = AppDevice.query.filter(
        AppDevice.connection_status.in_(['error', 'failed', 'offline']),
        AppDevice.is_active == True
    ).count()

    sync_total  = SyncLog.query.filter(SyncLog.created_at >= since_24h).count()
    sync_errors = SyncLog.query.filter(
        SyncLog.created_at >= since_24h,
        SyncLog.level.in_(['error', 'warn', 'warning'])
    ).count()
    sync_rate = round((1 - sync_errors / max(sync_total, 1)) * 100)

    notif_total  = NotificationLog.query.filter(NotificationLog.created_at >= since_24h).count()
    notif_failed = NotificationLog.query.filter(
        NotificationLog.created_at >= since_24h,
        NotificationLog.status.in_(['failed', 'error'])
    ).count()
    notif_rate = round((1 - notif_failed / max(notif_total, 1)) * 100)

    heartbeats   = ServiceHeartbeat.query.all()
    hb_map       = {hb.service_key: hb for hb in heartbeats}
    services_ok  = sum(1 for hb in heartbeats if hb.status in ['ok', 'success', 'running'])
    service_score = round(services_ok / max(len(heartbeats), 1) * 100) if heartbeats else 50

    predictions = []

    # ── Scheduler ───────────────────────────────────────────────
    scheduler_hb = hb_map.get('scheduler')
    if scheduler_hb and scheduler_hb.last_seen_at:
        age_min = (now - scheduler_hb.last_seen_at).total_seconds() / 60
        if age_min > 45:
            predictions.append({
                'level': 'critical', 'icon': '⚠️',
                'ar':  f'المجدول الداخلي لم يُسجَّل منذ {int(age_min)} دقيقة — كل الخدمات المجدولة ستتوقف',
                'en':  f'Scheduler missing for {int(age_min)} min — all scheduled jobs will stop',
                'action_ar': 'أعد تشغيل السيرفر',
                'action_en': 'Restart the server',
                'cause_ar': 'المجدول الداخلي يرسل نبضة كل 30 دقيقة عند تشغيله. غياب النبضة يعني أن الجدولة لم تبدأ أو تعطلت بعد إقلاع الخادم.',
                'cause_en': 'APScheduler sends a heartbeat every 30 min when running. Missing heartbeat means the scheduler did not start or crashed after server boot.',
                'fix_steps_ar': [
                    'أعد تشغيل التطبيق عبر مدير الخدمة أو شغّل ملف التشغيل المحلي',
                    'تحقق من سجلات الإقلاع لأي خطأ استيراد أو تشغيل',
                    'إذا استمر: تأكد أن خيار تعطيل المجدول الداخلي غير مفعّل في ملف البيئة',
                    'راجع أن مكتبة المجدول الداخلي مثبتة في البيئة',
                ],
                'fix_steps_en': [
                    'Restart Flask: supervisorctl restart app or python run.py',
                    'Check startup logs for ImportError or RuntimeError',
                    'Verify DISABLE_INTERNAL_SCHEDULER is not True in .env',
                    'Confirm APScheduler is installed: pip show apscheduler',
                ],
                'scope_ar': f'يؤثر على 6 خدمات مجدولة — مزامنة، إشعارات، طقس، نسخ احتياطي، ورفع إلى درايف',
                'scope_en': 'Affects all 6 scheduled services: sync, notifications, weather, backup, Drive upload',
            })
    elif not scheduler_hb:
        predictions.append({
            'level': 'warning', 'icon': '🔁',
            'ar':  'لا توجد نبضة للمجدول — ربما لم يبدأ بعد',
            'en':  'No scheduler heartbeat recorded yet',
            'action_ar': 'تحقق من سجلات الإقلاع',
            'action_en': 'Check startup logs',
            'cause_ar': 'المجدول يُسجّل نبضته عند البدء. غياب أي سجل يعني أنه لم يبدأ أصلاً.',
            'cause_en': 'Scheduler records its heartbeat on startup. No record means it never started.',
            'fix_steps_ar': ['شغّل التطبيق وراقب شاشة الأوامر', 'ابحث في السجلات عن رسالة بدء المجدول'],
            'fix_steps_en': ['Start the app and watch terminal output', 'Search for "Scheduler started" in logs'],
            'scope_ar': 'لا تعمل أي من الخدمات التلقائية حتى يبدأ المجدول',
            'scope_en': 'No automated services run until the scheduler starts',
        })

    # ── Sync errors ──────────────────────────────────────────────
    if sync_errors > 3:
        lvl = 'critical' if sync_errors > 10 else 'warning'
        fail_pct = 100 - sync_rate
        predictions.append({
            'level': lvl, 'icon': '🔄',
            'ar':  f'{sync_errors} خطأ في المزامنة خلال 24 ساعة (نسبة النجاح: {sync_rate}%)',
            'en':  f'{sync_errors} sync errors in 24 h (success rate {sync_rate}%)',
            'action_ar': 'راجع سجلات المزامنة',
            'action_en': 'Check sync logs',
            'cause_ar': f'نسبة الفشل {fail_pct}% — أسباب شائعة: انتهاء صلاحية بيانات اعتماد الواجهة البرمجية، تغيير في بنية الاستجابة، انقطاع الشبكة، أو تجاوز حد الطلبات.',
            'cause_en': f'{fail_pct}% failure rate — common causes: expired API credentials, changed response structure, network interruption, or rate limiting.',
            'fix_steps_ar': [
                'افتح سجلات المزامنة وابحث عن رسالة الخطأ المتكررة',
                'تحقق من صلاحية بيانات اعتماد الواجهة البرمجية في إعدادات الجهاز',
                'اختبر الاتصال يدوياً من صفحة الأجهزة',
                'إذا كان الخطأ تجاوز حد الطلبات: أبطئ دورة المزامنة في الإعدادات',
            ],
            'fix_steps_en': [
                'Open sync logs and find the most frequent error message',
                'Verify API credentials are valid in device settings',
                'Test connection manually from the devices page',
                'If error is rate limit: slow down sync interval in settings',
            ],
            'scope_ar': f'يؤثر على جميع الأجهزة المتصلة — {total_devices} جهاز نشط',
            'scope_en': f'Affects all connected devices — {total_devices} active devices',
        })

    # ── Notification failures ────────────────────────────────────
    if notif_failed > 2:
        fail_pct = 100 - notif_rate
        predictions.append({
            'level': 'warning', 'icon': '🔔',
            'ar':  f'{notif_failed} إشعار فاشل خلال 24 ساعة ({notif_rate}% نجاح)',
            'en':  f'{notif_failed} notification failures in 24 h ({notif_rate}% success)',
            'action_ar': 'راجع إعدادات تيليجرام',
            'action_en': 'Check Telegram settings',
            'cause_ar': f'نسبة فشل {fail_pct}% في الإشعارات — أسباب شائعة: رمز البوت منتهٍ، معرف المحادثة خاطئ، البوت محظور من تيليجرام، أو رقم الرسائل النصية غير صحيح.',
            'cause_en': f'{fail_pct}% notification failure — common causes: expired Bot token, wrong Chat ID, bot blocked by Telegram, or invalid SMS number.',
            'fix_steps_ar': [
                'راجع سجل الإشعارات وانظر حقل رد المزود للخطأ',
                'اختبر رمز البوت يدوياً عبر رابط فحص تيليجرام',
                'تأكد أن المستخدم لم يحظر البوت في تيليجرام',
                'إذا كانت القناة رسائل نصية: تحقق من رصيد الحساب لدى المزود',
            ],
            'fix_steps_en': [
                'Check notification log and look at response_text field for the error',
                'Test Bot Token manually: https://api.telegram.org/bot{TOKEN}/getMe',
                'Ensure the user has not blocked the bot in Telegram',
                'For SMS: verify account balance with the SMS provider',
            ],
            'scope_ar': f'يؤثر على {total_users} مستخدم يعتمدون على الإشعارات الآنية',
            'scope_en': f'Affects {total_users} users relying on real-time alerts',
        })

    # ── Offline devices ──────────────────────────────────────────
    if offline_devices > 0:
        predictions.append({
            'level': 'warning', 'icon': '📡',
            'ar':  f'{offline_devices} {"جهاز منقطع" if offline_devices == 1 else "أجهزة منقطعة"} — بيانات هذه الأجهزة متوقفة',
            'en':  f'{offline_devices} device{"s" if offline_devices > 1 else ""} offline',
            'action_ar': 'راجع صفحة الأجهزة',
            'action_en': 'Check devices page',
            'cause_ar': 'الجهاز يُسجَّل منقطعاً عندما تفشل آخر محاولة مزامنة — أسباب: بيانات اعتماد منتهية، تغيير عنوان الشبكة، أو الجهاز الفعلي مغلق.',
            'cause_en': 'Device is marked offline when the last sync attempt failed — causes: expired credentials, changed IP, or physical device offline.',
            'fix_steps_ar': [
                'افتح صفحة الأجهزة وانقر على الجهاز المنقطع',
                'راجع سجل المزامنة للخطأ الأخير',
                'اختبر بيانات الاعتماد يدوياً',
                'تحقق من الاتصال الشبكي للجهاز الفعلي',
            ],
            'fix_steps_en': [
                'Open devices page and click the offline device',
                'Check sync log for the last error',
                'Test credentials manually',
                'Verify network connectivity of the physical device',
            ],
            'scope_ar': f'{offline_devices} من أصل {total_devices} جهاز — المستخدمون المرتبطون بها لا يرون بيانات حية',
            'scope_en': f'{offline_devices} of {total_devices} devices — users linked to them see no live data',
        })

    # ── Backup overdue ───────────────────────────────────────────
    backup_hb = hb_map.get('database_backup') or hb_map.get('app.services.backup_service.scheduled_backup_job')
    if backup_hb and backup_hb.last_seen_at:
        backup_age_h = (now - backup_hb.last_seen_at).total_seconds() / 3600
        if backup_age_h > 26:
            predictions.append({
                'level': 'warning', 'icon': '💾',
                'ar':  f'آخر نسخة احتياطية منذ {int(backup_age_h)} ساعة — النسخ اليومي قد تأخر',
                'en':  f'Last backup was {int(backup_age_h)}h ago — daily backup may have been missed',
                'action_ar': 'راجع صفحة النسخ الاحتياطية',
                'action_en': 'Check backups page',
                'cause_ar': 'النسخ الاحتياطي مبرمج يومياً. التأخر قد يعني: فشل المجدول، نفاد مساحة القرص، أو خطأ في مسار الحفظ.',
                'cause_en': 'Backup runs daily. Delay may mean: scheduler failure, disk space exhausted, or backup path error.',
                'fix_steps_ar': [
                    'شغّل نسخة احتياطية يدوية من صفحة النسخ الاحتياطية',
                    'تحقق من مساحة القرص المتاحة',
                    'راجع سجلات المجدول لرسالة الخطأ',
                    'تأكد من صلاحيات الكتابة على مجلد النسخ',
                ],
                'fix_steps_en': [
                    'Trigger a manual backup from the backups page',
                    'Check available disk space',
                    'Review scheduler logs for error messages',
                    'Verify write permissions on the backup folder',
                ],
                'scope_ar': 'مخاطرة بفقدان بيانات تمتد لـ ' + str(int(backup_age_h)) + ' ساعة في حال حدوث عطل',
                'scope_en': f'Risk of losing up to {int(backup_age_h)}h of data if a failure occurs now',
            })

    data_score = round((sync_rate + notif_rate) / 2) if (sync_total + notif_total) > 0 else 90

    return {
        'total_users': total_users,
        'total_devices': total_devices,
        'offline_devices': offline_devices,
        'sync_total': sync_total,
        'sync_errors': sync_errors,
        'sync_rate': sync_rate,
        'notif_total': notif_total,
        'notif_failed': notif_failed,
        'notif_rate': notif_rate,
        'predictions': predictions,
        'service_score': service_score,
        'data_score': data_score,
    }


@platform_bp.route('/admin/platform-review')
def admin_platform_review():
    guard = _admin_guard('can_view_logs')
    if guard:
        return guard
    project_root = Path(current_app.root_path).resolve().parent
    audit = audit_project(project_root)
    smart = _smart_analysis()
    ps    = _platform_status_summary()

    # ── Compute overall health score ──────────────────────────────
    high_risk = audit['summary']['high_risk_templates']
    sec_score  = max(0, 100 - high_risk * 25)
    oversized  = len(audit['python']['oversized'])
    code_score = max(0, 100 - oversized * 15 - max(0, audit['summary']['inline_styles'] - 30) // 5)
    overall    = round(0.35 * smart['service_score'] + 0.30 * sec_score + 0.20 * smart['data_score'] + 0.15 * code_score)

    return render_template(
        'admin_platform_review.html',
        audit=audit,
        smart=smart,
        platform_status=ps,
        overall=overall,
        sec_score=sec_score,
        code_score=code_score,
        ui_lang=_lang(),
        format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']),
    )



def _logo_upload_dir() -> Path:
    folder = Path(current_app.static_folder) / 'uploads' / 'branding'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


_LOGO_ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif'}
_LOGO_MAX_BYTES = 5 * 1024 * 1024


def _save_uploaded_logo(file_storage) -> str | None:
    """Save the uploaded logo file and return a public URL or None on failure."""
    if not file_storage or not (file_storage.filename or '').strip():
        return None
    filename = secure_filename(file_storage.filename) or ''
    ext = Path(filename).suffix.lower()
    if ext not in _LOGO_ALLOWED_EXTENSIONS:
        flash('صيغة الشعار غير مدعومة. الصيغ المسموحة: PNG, JPG, WEBP, SVG, GIF.', 'warning')
        return None
    folder = _logo_upload_dir()
    target_name = f'site_logo_{uuid4().hex[:10]}{ext}'
    target_path = folder / target_name
    file_storage.save(target_path)
    try:
        size = target_path.stat().st_size
    except OSError:
        size = 0
    if size > _LOGO_MAX_BYTES:
        try:
            target_path.unlink()
        except OSError:
            pass
        flash('حجم الشعار أكبر من 5MB.', 'warning')
        return None
    return url_for('static', filename=f'uploads/branding/{target_name}')


def _create_blank_plan() -> SubscriptionPlan:
    """Create a new plan with safe defaults, suitable for inline editing."""
    suffix = uuid4().hex[:6]
    last = SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.desc()).first()
    next_order = (last.sort_order or 0) + 10 if last else 10
    plan = SubscriptionPlan(
        code=f'plan_{suffix}',
        name_ar='باقة جديدة',
        name_en='New plan',
        price=0.0,
        currency='USD',
        duration_days_default=30,
        max_devices=10,
        is_active=True,
        sort_order=next_order,
        features_json=json.dumps({}, ensure_ascii=False),
    )
    db.session.add(plan)
    db.session.flush()
    return plan


def _apply_plan_form(plan: SubscriptionPlan, form, prefix: str) -> None:
    """Apply form fields to a plan in-place. Used both for inline edits and
    the catch-all save action."""
    try:
        if form.get(f'{prefix}_price') not in (None, ''):
            plan.price = float(form.get(f'{prefix}_price'))
    except Exception:
        pass
    if form.get(f'{prefix}_currency'):
        plan.currency = (form.get(f'{prefix}_currency') or 'USD').strip() or 'USD'
    if form.get(f'{prefix}_name_ar'):
        plan.name_ar = form.get(f'{prefix}_name_ar').strip()
    if form.get(f'{prefix}_name_en'):
        plan.name_en = form.get(f'{prefix}_name_en').strip()
    update_plan_landing_meta(plan, form, prefix)


@platform_bp.route('/admin/landing-settings', methods=['GET', 'POST'])
def admin_landing_settings():
    guard = _admin_guard('can_manage_system')
    if guard:
        return guard

    if request.method == 'POST':
        action = (request.form.get('action') or 'save_all').strip()
        is_en = _lang() == 'en'

        if action == 'save_hero':
            save_landing_section('hero', request.form)
            logo_url = _save_uploaded_logo(request.files.get('site_logo_file'))
            if logo_url:
                set_setting_value('site_logo', logo_url)
            elif request.form.get('clear_logo') == '1':
                set_setting_value('site_logo', '')
            db.session.commit()
            flash('Hero section updated.' if is_en else 'تم حفظ قسم الواجهة الرئيسية.', 'success')

        elif action == 'save_footer':
            save_landing_section('footer', request.form)
            db.session.commit()
            flash('Footer & social updated.' if is_en else 'تم حفظ الفوتر وروابط التواصل.', 'success')

        elif action == 'save_plan':
            try:
                plan_id = int(request.form.get('plan_id') or 0)
            except Exception:
                plan_id = 0
            plan = SubscriptionPlan.query.get(plan_id)
            if not plan:
                flash('Plan not found.' if is_en else 'الباقة غير موجودة.', 'warning')
            else:
                _apply_plan_form(plan, request.form, f'plan_{plan.id}')
                db.session.commit()
                flash('Plan updated.' if is_en else 'تم حفظ الباقة.', 'success')

        elif action == 'add_plan':
            plan = _create_blank_plan()
            db.session.commit()
            flash('Plan added.' if is_en else 'تمت إضافة باقة جديدة.', 'success')
            return redirect(url_for('platform.admin_landing_settings', lang=_lang()) + f'#plan-{plan.id}')

        elif action == 'delete_plan':
            try:
                plan_id = int(request.form.get('plan_id') or 0)
            except Exception:
                plan_id = 0
            plan = SubscriptionPlan.query.get(plan_id)
            if plan:
                db.session.delete(plan)
                db.session.commit()
                flash('Plan removed.' if is_en else 'تم حذف الباقة.', 'success')
            else:
                flash('Plan not found.' if is_en else 'الباقة غير موجودة.', 'warning')

        else:
            # Backwards-compatible "save everything" action used by older forms.
            save_landing_settings(request.form)
            logo_url = _save_uploaded_logo(request.files.get('site_logo_file'))
            if logo_url:
                set_setting_value('site_logo', logo_url)
            for plan in SubscriptionPlan.query.all():
                _apply_plan_form(plan, request.form, f'plan_{plan.id}')
            db.session.commit()
            flash('Settings saved.' if is_en else 'تم حفظ كل الإعدادات.', 'success')

        return redirect(url_for('platform.admin_landing_settings', lang=_lang()))

    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    plan_rows = [
        {
            'plan': plan,
            'meta': plan_landing_meta(plan, _lang()),
            'meta_ar': plan_landing_meta(plan, 'ar'),
            'meta_en': plan_landing_meta(plan, 'en'),
        }
        for plan in plans
    ]
    return render_template(
        'admin_landing_settings.html',
        landing=get_landing_settings(),
        plan_rows=plan_rows,
        social_links=SOCIAL_LINKS,
        ui_lang=_lang(),
    )


@platform_bp.route('/admin/backups', methods=['GET', 'POST'])
def admin_backups():
    guard = _admin_guard('can_manage_backups')
    if guard:
        return guard
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'save_settings':
            set_setting('backup_enabled', 'true' if request.form.get('backup_enabled') == 'on' else 'false')
            freq = (request.form.get('backup_frequency') or 'daily').strip().lower()
            if freq not in {'daily', 'weekly', 'monthly'}:
                freq = 'daily'
            set_setting('backup_frequency', freq)
            set_setting('backup_keep_local', str(max(int(request.form.get('backup_keep_local') or 12), 1)))
            set_setting('backup_drive_enabled', 'true' if request.form.get('backup_drive_enabled') == 'on' else 'false')
            set_setting('backup_drive_folder_id', (request.form.get('backup_drive_folder_id') or '').strip())
            db.session.commit()
            flash('Backup settings updated.' if _lang() == 'en' else 'تم تحديث إعدادات النسخ الاحتياطي.', 'success')
        elif action == 'backup_now':
            try:
                create_backup(reason='manual', upload_drive=request.form.get('upload_drive') == 'on')
                flash('Backup created successfully.' if _lang() == 'en' else 'تم إنشاء نسخة احتياطية بنجاح.', 'success')
            except Exception as exc:
                current_app.logger.exception('Manual backup failed: %s', exc)
                flash('Could not create the backup.' if _lang() == 'en' else 'تعذر إنشاء النسخة الاحتياطية.', 'danger')
        elif action == 'upload_backup':
            file = request.files.get('backup_file')
            try:
                saved = save_uploaded_backup(file)
                flash((f'Backup uploaded for restore: {saved.get("filename")}' if _lang() == 'en' else f'تم رفع نسخة احتياطية للاستعادة: {saved.get("filename")}'), 'success')
            except Exception as exc:
                current_app.logger.exception('Backup upload failed: %s', exc)
                flash('Could not upload the backup file.' if _lang() == 'en' else 'تعذر رفع ملف النسخة الاحتياطية.', 'danger')
        elif action == 'restore':
            filename = (request.form.get('filename') or '').strip()
            confirm = (request.form.get('confirm_restore') or '').strip().upper()
            if confirm != 'RESTORE':
                flash('Type RESTORE to confirm.' if _lang() == 'en' else 'اكتب RESTORE لتأكيد الاستعادة.', 'warning')
            else:
                try:
                    restore_backup(filename)
                    flash('Database restored from backup.' if _lang() == 'en' else 'تم استعادة قاعدة البيانات من النسخة الاحتياطية.', 'success')
                except Exception as exc:
                    current_app.logger.exception('Backup restore failed: %s', exc)
                    flash('Could not restore the backup.' if _lang() == 'en' else 'تعذر استعادة النسخة الاحتياطية.', 'danger')
        return redirect(url_for('platform.admin_backups', lang=_lang()))
    return render_template('admin_backups.html', settings=backup_settings(), backups=list_backups(), ui_lang=_lang(), format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE']))

@platform_bp.route('/admin/backups/download/<path:filename>')
def admin_backup_download(filename: str):
    guard = _admin_guard('can_manage_backups')
    if guard:
        return guard
    for row in list_backups():
        if row['name'] == filename:
            return send_file(row['path'], as_attachment=True, download_name=row['name'])
    return redirect(url_for('platform.admin_backups', lang=_lang()))
