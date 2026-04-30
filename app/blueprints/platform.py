from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename
from uuid import uuid4
import json

from ..extensions import db
from ..models import NotificationLog, ServiceHeartbeat, SubscriptionPlan, SyncLog
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


@platform_bp.route('/admin/platform-review')
def admin_platform_review():
    guard = _admin_guard('can_view_logs')
    if guard:
        return guard
    project_root = Path(current_app.root_path).resolve().parent
    audit = audit_project(project_root)
    return render_template(
        'admin_platform_review.html',
        audit=audit,
        platform_status=_platform_status_summary(),
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
