from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for

from ..extensions import db
from ..services.backup_service import backup_settings, create_backup, list_backups, restore_backup, set_setting, save_uploaded_backup
from ..services.platform_audit import audit_project
from ..services.scope import has_permission, is_system_admin
from ..services.rbac import admin_landing_url
from ..services.utils import format_local_datetime

platform_bp = Blueprint('platform', __name__)


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _admin_guard(permission: str = 'can_view_logs'):
    if is_system_admin() or has_permission(permission):
        return None
    flash('This page is not available for your account.' if _lang() == 'en' else 'هذه الصفحة غير متاحة لحسابك.', 'warning')
    return redirect(admin_landing_url(_lang()))


@platform_bp.route('/admin/platform-review')
def admin_platform_review():
    guard = _admin_guard('can_view_logs')
    if guard:
        return guard
    audit = audit_project(current_app.root_path.rsplit('/app', 1)[0])
    return render_template('admin_platform_review.html', audit=audit, ui_lang=_lang())


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
