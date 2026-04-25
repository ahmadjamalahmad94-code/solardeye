from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from ..extensions import db
from ..models import AdminActivityLog, AppDevice, DeviceType
from ..services.energy_integrations import provider_catalog, provider_category_label, test_connection_for_device
from ..services.scope import get_current_user, has_permission, is_system_admin

integrations_bp = Blueprint('integrations', __name__)


def _lang() -> str:
    raw = request.args.get('lang') or session.get('ui_lang') or 'ar'
    return 'en' if str(raw).lower().startswith('en') else 'ar'


def _admin_guard(permission: str = 'can_manage_integrations'):
    if is_system_admin() or has_permission(permission):
        return None
    flash('This page is not available for your account.' if _lang() == 'en' else 'هذه الصفحة غير متاحة لحسابك.', 'warning')
    return redirect(url_for('main.admin_dashboard', lang=_lang()))


def _audit(action: str, summary: str, target_type: str | None = None, target_id: int | None = None, details: dict | None = None):
    actor = get_current_user()
    db.session.add(AdminActivityLog(
        actor_user_id=getattr(actor, 'id', None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        details_json=json.dumps(details or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    ))


def _upsert_device_type_from_form(code: str):
    row = DeviceType.query.filter_by(code=code).first()
    created = row is None
    if row is None:
        row = DeviceType(code=code, created_at=datetime.utcnow())
        db.session.add(row)
    row.name = (request.form.get('name') or code).strip()
    row.provider = (request.form.get('provider') or 'custom').strip()
    row.auth_mode = (request.form.get('auth_mode') or 'api_key').strip()
    row.base_url = (request.form.get('base_url') or '').strip() or None
    row.healthcheck_endpoint = (request.form.get('healthcheck_endpoint') or '').strip() or None
    row.sync_endpoint = (request.form.get('sync_endpoint') or '').strip() or None
    row.required_fields_json = json.dumps([x.strip() for x in (request.form.get('required_fields') or '').split(',') if x.strip()], ensure_ascii=False)
    row.mapping_schema_json = request.form.get('mapping_schema_json') or '{}'
    row.is_active = request.form.get('is_active') == 'on'
    row.updated_at = datetime.utcnow()
    return row, created


@integrations_bp.route('/admin/integrations', methods=['GET', 'POST'])
def admin_integrations():
    guard = _admin_guard('can_manage_integrations')
    if guard:
        return guard
    if request.method == 'POST':
        action = (request.form.get('action') or 'save_custom').strip()
        if action == 'seed_provider':
            code = (request.form.get('provider_code') or '').strip().lower()
            spec = next((p for p in provider_catalog() if p.code == code), None)
            if not spec:
                flash('Unknown provider.' if _lang() == 'en' else 'المزوّد غير معروف.', 'danger')
                return redirect(url_for('integrations.admin_integrations', lang=_lang()))
            payload = spec.as_device_type_payload()
            row = DeviceType.query.filter_by(code=spec.code).first()
            created = row is None
            if row is None:
                row = DeviceType(code=spec.code, created_at=datetime.utcnow())
                db.session.add(row)
            for key, value in payload.items():
                setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            _audit('integration.seed', f'Seeded integration provider {spec.code}', 'device_type', getattr(row, 'id', None), {'provider': spec.provider})
            db.session.commit()
            flash(('Provider added to the catalog.' if created else 'Provider refreshed from the official blueprint.') if _lang() == 'en' else ('تمت إضافة المزوّد للكتالوج.' if created else 'تم تحديث المزوّد من المخطط الرسمي.'), 'success')
            return redirect(url_for('integrations.admin_integrations', lang=_lang()))

        code = (request.form.get('code') or '').strip().lower()
        if code:
            row, created = _upsert_device_type_from_form(code)
            _audit('integration.create' if created else 'integration.update', f'Updated integration type {row.code}', 'device_type', row.id, {'provider': row.provider})
            db.session.commit()
            flash('Integration type saved.' if _lang() == 'en' else 'تم حفظ نوع التكامل بنجاح.', 'success')
            return redirect(url_for('integrations.admin_integrations', lang=_lang()))

    rows = DeviceType.query.order_by(DeviceType.name.asc(), DeviceType.id.asc()).all()
    devices = AppDevice.query.order_by(AppDevice.updated_at.desc(), AppDevice.id.desc()).limit(200).all()
    return render_template(
        'admin_integrations.html',
        rows=rows,
        devices=devices,
        providers=provider_catalog(),
        category_label=provider_category_label,
        ui_lang=_lang(),
    )


@integrations_bp.route('/admin/integrations/test-device/<int:device_id>', methods=['POST'])
def admin_test_device_integration(device_id: int):
    guard = _admin_guard('can_manage_integrations')
    if guard:
        return guard
    device = AppDevice.query.get_or_404(device_id)
    result = test_connection_for_device(device)
    device.connection_status = 'ok' if result.get('ok') else 'failed'
    device.last_connected_at = datetime.utcnow() if result.get('ok') else device.last_connected_at
    db.session.commit()
    if request.headers.get('Accept', '').lower().find('json') >= 0:
        return jsonify(result)
    flash(result.get('message') or ('Connection test completed.' if _lang() == 'en' else 'تم تنفيذ فحص الاتصال.'), 'success' if result.get('ok') else 'warning')
    return redirect(url_for('integrations.admin_integrations', lang=_lang()))
