from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..models import AppDevice, AppUser


auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == current_app.config['ADMIN_USERNAME'] and password == current_app.config['ADMIN_PASSWORD']:
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username

            app_user = AppUser.query.filter_by(username=username).first()
            if app_user:
                session['user_id'] = app_user.id
                session['current_device_type'] = app_user.preferred_device_type or 'deye'
                device = AppDevice.query.filter_by(owner_user_id=app_user.id, is_active=True).order_by(AppDevice.id.asc()).first()
                if device:
                    session['current_device_id'] = device.id
                    session['current_device_type'] = device.device_type or 'deye'
            flash('تم تسجيل الدخول بنجاح', 'success')
            return redirect(url_for('main.dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('تم تسجيل الخروج', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.before_app_request
def protect_routes():
    public_endpoints = {'auth.login', 'static', 'main.telegram_webhook', 'main.telegram_multilink_webhook'}
    ep = request.endpoint or ''
    if ep in public_endpoints or ep.startswith('static'):
        return
    if not session.get('logged_in'):
        wants_json = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.accept_mimetypes.best == 'application/json'
            or request.path.startswith('/telegram/webhook')
            or request.path.startswith('/telegram/multilink-webhook')
        )
        if wants_json:
            return jsonify({
                'ok': False,
                'message': 'انتهت جلسة تسجيل الدخول. أعد تسجيل الدخول ثم جرّب مرة أخرى.'
            }), 401
        return redirect(url_for('auth.login'))
