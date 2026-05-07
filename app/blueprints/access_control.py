from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import AppRole, AppUser, PortalPageSetting, Setting
from ..services.rbac import DELETED_ROLE_CODES_SETTING, PERMISSION_KEYS, available_roles, permission_catalog, portal_pages, role_permissions, seed_access_control
from ..services.scope import has_permission, is_system_admin
from ..services.rbac import admin_landing_url

access_control_bp = Blueprint('access_control', __name__)


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _guard():
    if is_system_admin() or has_permission('can_manage_roles') or has_permission('can_manage_users'):
        return None
    flash('This page is not available for your account.' if _lang() == 'en' else 'هذه الصفحة غير متاحة لحسابك.', 'warning')
    return redirect(admin_landing_url(_lang()))


def _perms_from_form() -> dict[str, bool]:
    return {key: request.form.get(key) == 'on' for key in PERMISSION_KEYS}


_PROTECTED_ROLE_CODES = {'admin', 'super_admin', 'user', 'subscriber', 'customer'}


def _deleted_role_codes() -> set[str]:
    row = Setting.query.filter_by(key=DELETED_ROLE_CODES_SETTING).first()
    if not row or not row.value:
        return set()
    try:
        parsed = json.loads(row.value or '[]')
        if isinstance(parsed, list):
            return {str(code).strip().lower() for code in parsed if str(code).strip()}
    except Exception:
        pass
    return set()


def _save_deleted_role_codes(codes: set[str]):
    row = Setting.query.filter_by(key=DELETED_ROLE_CODES_SETTING).first()
    if row is None:
        row = Setting(key=DELETED_ROLE_CODES_SETTING)
        db.session.add(row)
    row.value = json.dumps(sorted(codes), ensure_ascii=False)
    row.updated_at = datetime.utcnow()


@access_control_bp.route('/admin/roles', methods=['GET', 'POST'])
def admin_roles_v10():
    guard = _guard()
    if guard:
        return guard
    seed_access_control(commit=True)
    lang = _lang()
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'create_role':
            code = (request.form.get('code') or '').strip().lower().replace(' ', '_')
            if not code:
                flash('Role code is required.' if lang == 'en' else 'كود الدور مطلوب.', 'warning')
            elif AppRole.query.filter_by(code=code).first():
                flash('Role code already exists.' if lang == 'en' else 'كود الدور موجود مسبقًا.', 'warning')
            else:
                row = AppRole(
                    code=code,
                    name_ar=(request.form.get('name_ar') or code).strip(),
                    name_en=(request.form.get('name_en') or code).strip(),
                    summary_ar=(request.form.get('summary_ar') or '').strip(),
                    summary_en=(request.form.get('summary_en') or '').strip(),
                    permissions_json=json.dumps(_perms_from_form(), ensure_ascii=False),
                    is_system=False,
                    is_active=request.form.get('is_active') == 'on',
                    sort_order=int(request.form.get('sort_order') or 100),
                    created_at=datetime.utcnow(),
                )
                db.session.add(row)
                deleted_codes = _deleted_role_codes()
                if code in deleted_codes:
                    deleted_codes.discard(code)
                    _save_deleted_role_codes(deleted_codes)
                db.session.commit()
                flash('Role created.' if lang == 'en' else 'تم إنشاء الدور.', 'success')
        elif action == 'update_role':
            role_id = int(request.form.get('role_id') or 0)
            row = AppRole.query.get(role_id)
            if row:
                row.name_ar = (request.form.get('name_ar') or row.name_ar or row.code).strip()
                row.name_en = (request.form.get('name_en') or row.name_en or row.code).strip()
                row.summary_ar = (request.form.get('summary_ar') or '').strip()
                row.summary_en = (request.form.get('summary_en') or '').strip()
                row.permissions_json = json.dumps(_perms_from_form(), ensure_ascii=False)
                row.is_active = True if row.code in _PROTECTED_ROLE_CODES else (request.form.get('is_active') == 'on')
                row.sort_order = int(request.form.get('sort_order') or row.sort_order or 100)
                row.updated_at = datetime.utcnow()
                db.session.commit()
                flash('Role updated.' if lang == 'en' else 'تم تحديث الدور.', 'success')
        elif action == 'delete_role':
            # Granular sub-permission gate: roles.delete
            from ..services.scope import has_permission
            if not has_permission('roles.delete'):
                flash('You do not have permission to delete roles.' if lang == 'en' else 'لا تملك صلاحية حذف الأدوار.', 'danger')
            else:
                role_id = int(request.form.get('role_id') or 0)
                row = AppRole.query.get(role_id)
                # Block only the truly indispensable role codes; permit deleting other roles.
                if row and row.code not in _PROTECTED_ROLE_CODES:
                    deleted_codes = _deleted_role_codes()
                    deleted_codes.add(row.code)
                    _save_deleted_role_codes(deleted_codes)
                    AppUser.query.filter_by(role=row.code).update({'role': 'user', 'is_admin': False})
                    db.session.delete(row)
                    db.session.commit()
                    flash('Role deleted and assigned users moved to Subscriber.' if lang == 'en' else 'تم حذف الدور ونقل المستخدمين المرتبطين إلى دور مشترك.', 'success')
                else:
                    flash('This role is protected and cannot be deleted.' if lang == 'en' else 'لا يمكن حذف هذا الدور لأنه دور أساسي محمي.', 'warning')
        elif action == 'portal_visibility':
            visible_keys = set(request.form.getlist('visible_pages'))
            for page in portal_pages(include_locked=True):
                if getattr(page, 'is_locked', False):
                    page.is_visible = True
                else:
                    page.is_visible = getattr(page, 'page_key', '') in visible_keys
                page.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Subscriber navigation visibility updated.' if lang == 'en' else 'تم تحديث ظهور صفحات المشترك.', 'success')
        return redirect(url_for('access_control.admin_roles_v10', lang=lang))

    roles = available_roles(include_inactive=True)
    admin_users = AppUser.query.filter(AppUser.is_admin == True).order_by(AppUser.username.asc()).all()
    return render_template(
        'admin_roles.html',
        roles=roles,
        admin_users=admin_users,
        role_matrix=[],
        permission_rows=permission_catalog(lang),
        portal_page_rows=portal_pages(include_locked=True),
        role_permissions=role_permissions,
        ui_lang=lang,
    )
