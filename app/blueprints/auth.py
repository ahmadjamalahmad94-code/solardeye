from __future__ import annotations
from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from ..extensions import db
from ..models import Device, User

auth_bp = Blueprint('auth', __name__)


def _get_login_user(username: str):
    return User.query.filter_by(username=username).first()


def _ensure_env_admin_user():
    username = current_app.config.get('ADMIN_USERNAME', 'admin')
    password = current_app.config.get('ADMIN_PASSWORD', 'admin123')
    user = User.query.filter_by(username=username).first()
    if user:
        return user
    user = User(username=username, password_hash=generate_password_hash(password), is_active=True, is_admin=True)
    db.session.add(user)
    db.session.commit()
    return user


def _pick_user_device(user: User | None):
    if not user:
        return None
    if user.preferred_device_id:
        device = Device.query.filter_by(id=user.preferred_device_id, owner_user_id=user.id, is_active=True).first()
        if device:
            return device
    return Device.query.filter_by(owner_user_id=user.id, is_active=True).order_by(Device.id.asc()).first()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = _get_login_user(username)

        ok = False
        if user and user.is_active:
            try:
                ok = check_password_hash(user.password_hash, password)
            except Exception:
                ok = user.password_hash == password
        elif username == current_app.config['ADMIN_USERNAME'] and password == current_app.config['ADMIN_PASSWORD']:
            user = _ensure_env_admin_user()
            ok = True

        if ok and user:
            session.clear()
            session.permanent = True
            session['logged_in'] = True
            session['username'] = user.username
            session['user_id'] = user.id
            device = _pick_user_device(user)
            if device:
                session['current_device_id'] = device.id
                session['current_device_type'] = device.device_type
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
    g.current_user = None
    g.current_device = None
    if session.get('user_id'):
        g.current_user = User.query.filter_by(id=session.get('user_id'), is_active=True).first()
        if g.current_user and session.get('current_device_id'):
            g.current_device = Device.query.filter_by(id=session.get('current_device_id'), owner_user_id=g.current_user.id).first()
        if g.current_user and not g.current_device:
            g.current_device = _pick_user_device(g.current_user)
            if g.current_device:
                session['current_device_id'] = g.current_device.id
                session['current_device_type'] = g.current_device.device_type
    if not session.get('logged_in'):
        wants_json = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.accept_mimetypes.best == 'application/json'
            or request.path.startswith('/telegram/webhook')
            or request.path.startswith('/telegram/multilink-webhook')
        )
        if wants_json:
            return jsonify({'ok': False, 'message': 'انتهت جلسة تسجيل الدخول. أعد تسجيل الدخول ثم جرّب مرة أخرى.'}), 401
        return redirect(url_for('auth.login'))
