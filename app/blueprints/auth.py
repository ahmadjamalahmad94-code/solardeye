from __future__ import annotations

from datetime import datetime
import secrets
from urllib.parse import urlencode

import requests

from flask import (
    Blueprint,
    current_app,
    g,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import AppDevice, AppUser, InternalMailThread, InternalMailMessage, SupportTicket, SupportTicketMessage, NotificationEvent
from ..services.subscriptions import ensure_user_tenant_and_subscription, feature_enabled_for_user
from ..services.support_ops import unread_counts


auth_bp = Blueprint('auth', __name__)


def _login_user(app_user: AppUser):
    session.permanent = True
    session['logged_in'] = True
    session['username'] = app_user.username
    session['user_id'] = app_user.id
    session['current_device_type'] = app_user.preferred_device_type or 'deye'

    device = None
    if getattr(app_user, 'preferred_device_id', None):
        device = AppDevice.query.filter_by(id=app_user.preferred_device_id, owner_user_id=app_user.id, is_active=True).first()
    if device is None:
        device = AppDevice.query.filter_by(owner_user_id=app_user.id, is_active=True).order_by(AppDevice.id.asc()).first()
    if device and not bool(getattr(app_user, 'is_admin', False) or getattr(app_user, 'role', '') == 'admin'):
        session['current_device_id'] = device.id
        session['current_device_type'] = device.device_type or 'deye'
        if app_user.preferred_device_id != device.id:
            app_user.preferred_device_id = device.id
    else:
        session.pop('current_device_id', None)
    app_user.last_login_at = datetime.utcnow()
    db.session.commit()


def _create_default_device_for_user(user: AppUser, name: str | None = None):
    base_name = (name or user.full_name or user.username or 'My Solar Device').strip()
    device = AppDevice(
        owner_user_id=user.id,
        name=f"{base_name} Device",
        device_type='deye',
        api_provider='deye',
        api_base_url=current_app.config.get('DEYE_BASE_URL', ''),
        timezone=current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron'),
        auth_mode='wizard',
        is_active=True,
        notes='تم إنشاؤه تلقائيًا عند التسجيل لأول مرة.',
    )
    db.session.add(device)
    db.session.flush()
    user.preferred_device_id = device.id
    user.preferred_device_type = device.device_type or 'deye'
    return device

def _random_username_from_email(email: str) -> str:
    base = (email.split('@')[0] if email else 'user').strip().lower() or 'user'
    safe = ''.join(ch for ch in base if ch.isalnum() or ch in ('_', '.'))[:30] or 'user'
    candidate = safe
    idx = 1
    while AppUser.query.filter_by(username=candidate).first() is not None:
        idx += 1
        candidate = f"{safe[:24]}{idx}"
    return candidate


def _login_after_social(user: AppUser):
    _login_user(user)
    flash('تم تسجيل الدخول عبر Google بنجاح', 'success')
    if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'admin':
        return redirect(url_for('main.admin_dashboard'))
    if not getattr(user, 'onboarding_completed', False):
        return redirect(url_for('main.onboarding_wizard'))
    return redirect(url_for('main.dashboard'))



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        app_user = AppUser.query.filter_by(username=username, is_active=True).first()
        password_ok = False

        if username == current_app.config['ADMIN_USERNAME'] and password == current_app.config['ADMIN_PASSWORD']:
            password_ok = True
        elif app_user and app_user.password_hash:
            try:
                password_ok = check_password_hash(app_user.password_hash, password)
            except Exception:
                password_ok = (app_user.password_hash == password)

        if password_ok:
            if app_user is None:
                app_user = AppUser.query.filter_by(username=current_app.config['ADMIN_USERNAME']).first()
            if app_user:
                _login_user(app_user)
                flash('تم تسجيل الدخول بنجاح', 'success')
                if getattr(app_user, 'is_admin', False) or getattr(app_user, 'role', '') == 'admin':
                    return redirect(url_for('main.admin_dashboard'))
                if not getattr(app_user, 'onboarding_completed', False):
                    return redirect(url_for('main.onboarding_wizard'))
                return redirect(url_for('main.dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not username or not password:
            flash('اسم المستخدم وكلمة المرور مطلوبان.', 'warning')
        elif len(password) < 6:
            flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل.', 'warning')
        elif password != confirm_password:
            flash('تأكيد كلمة المرور غير مطابق.', 'danger')
        elif AppUser.query.filter_by(username=username).first():
            flash('اسم المستخدم مستخدم من قبل.', 'danger')
        elif email and AppUser.query.filter_by(email=email).first():
            flash('البريد الإلكتروني مستخدم من قبل.', 'danger')
        else:
            user = AppUser(
                username=username,
                password_hash=generate_password_hash(password),
                full_name=full_name,
                email=email,
                role='user',
                preferred_device_type='deye',
                is_active=True,
                is_admin=False,
                onboarding_completed=False,
                onboarding_step='welcome',
            )
            db.session.add(user)
            db.session.flush()
            _create_default_device_for_user(user, full_name or username)
            db.session.commit()
            _login_user(user)
            flash('تم إنشاء الحساب بنجاح. أهلاً بك ✨', 'success')
            return redirect(url_for('main.onboarding_wizard'))
    return render_template('register.html')



@auth_bp.route('/auth/google/start')
def google_start():
    client_id = current_app.config.get('GOOGLE_CLIENT_ID', '')
    redirect_uri = current_app.config.get('GOOGLE_REDIRECT_URI', '')
    auth_uri = current_app.config.get('GOOGLE_AUTH_URI', 'https://accounts.google.com/o/oauth2/auth')
    if not client_id or not redirect_uri:
        flash('Google OAuth غير مُفعّل بعد. أضف GOOGLE_CLIENT_ID و GOOGLE_REDIRECT_URI أولًا.', 'warning')
        return redirect(url_for('auth.login'))

    state = secrets.token_urlsafe(24)
    session['google_oauth_state'] = state
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'online',
        'include_granted_scopes': 'true',
        'prompt': 'select_account',
    }
    return redirect(f"{auth_uri}?{urlencode(params)}")


@auth_bp.route('/auth/google/callback')
def google_callback():
    error = request.args.get('error', '').strip()
    if error:
        flash(f'فشل تسجيل الدخول عبر Google: {error}', 'danger')
        return redirect(url_for('auth.login'))

    code = request.args.get('code', '').strip()
    state = request.args.get('state', '').strip()
    expected_state = session.pop('google_oauth_state', None)
    if not code or not state or not expected_state or state != expected_state:
        flash('طلب Google غير صالح أو انتهت صلاحيته.', 'danger')
        return redirect(url_for('auth.login'))

    client_id = current_app.config.get('GOOGLE_CLIENT_ID', '')
    client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET', '')
    redirect_uri = current_app.config.get('GOOGLE_REDIRECT_URI', '')
    token_uri = current_app.config.get('GOOGLE_TOKEN_URI', 'https://oauth2.googleapis.com/token')
    userinfo_uri = current_app.config.get('GOOGLE_USERINFO_URI', 'https://openidconnect.googleapis.com/v1/userinfo')
    if not client_id or not client_secret or not redirect_uri:
        flash('بيانات Google OAuth غير مكتملة داخل الإعدادات.', 'danger')
        return redirect(url_for('auth.login'))

    try:
        token_resp = requests.post(
            token_uri,
            data={
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            },
            timeout=20,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get('access_token', '')
        if not access_token:
            raise ValueError('missing_access_token')
        profile_resp = requests.get(
            userinfo_uri,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=20,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()
    except Exception as exc:
        flash(f'تعذر إكمال Google OAuth: {exc}', 'danger')
        return redirect(url_for('auth.login'))

    email = (profile.get('email') or '').strip().lower()
    subject = (profile.get('sub') or '').strip()
    full_name = (profile.get('name') or '').strip() or email.split('@')[0]
    if not email or not subject:
        flash('لم يرجع Google البريد أو المعرّف المطلوب.', 'danger')
        return redirect(url_for('auth.login'))

    user = AppUser.query.filter_by(oauth_provider='google', oauth_subject=subject).first()
    if user is None:
        user = AppUser.query.filter_by(email=email).first()
    if user is None:
        user = AppUser(
            username=_random_username_from_email(email),
            password_hash='',
            full_name=full_name,
            email=email,
            role='user',
            preferred_device_type='deye',
            is_active=True,
            is_admin=False,
            onboarding_completed=False,
            onboarding_step='welcome',
            oauth_provider='google',
            oauth_subject=subject,
        )
        db.session.add(user)
        db.session.flush()
        _create_default_device_for_user(user, full_name)
    else:
        user.oauth_provider = 'google'
        user.oauth_subject = subject
        if not user.email:
            user.email = email
        if not user.full_name:
            user.full_name = full_name

    db.session.commit()
    return _login_after_social(user)

@auth_bp.route('/auth/facebook/start')
def facebook_start():
    if not current_app.config.get('FACEBOOK_APP_ID'):
        flash('تسجيل الدخول عبر Facebook غير مُفعّل بعد. أضف مفاتيح Meta أولًا.', 'warning')
        return redirect(url_for('auth.login'))
    flash('تم تجهيز مسار Facebook، ويتبقى ربط المفاتيح الرسمية والـ callback الفعلي.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/auth/facebook/callback')
def facebook_callback():
    flash('Facebook callback scaffold جاهز، لكنه يحتاج App ID/Secret وتفعيل من Meta.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('تم تسجيل الخروج', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.before_app_request
def protect_routes():
    public_endpoints = {
        'auth.login',
        'auth.register',
        'auth.google_start',
        'auth.google_callback',
        'auth.facebook_start',
        'auth.facebook_callback',
        'static',
        'main.telegram_webhook',
        'main.telegram_multilink_webhook',
        'main.index',
    }
    ep = request.endpoint or ''
    if ep in public_endpoints or ep.startswith('static'):
        return
    g.current_user = None
    g.current_device = None
    g.is_admin = False
    g.permissions = {}
    g.plan_features = {}
    if session.get('logged_in'):
        if session.get('user_id'):
            g.current_user = AppUser.query.filter_by(id=session.get('user_id'), is_active=True).first()
        if g.current_user is None and session.get('username'):
            g.current_user = AppUser.query.filter_by(username=session.get('username'), is_active=True).first()
        if session.get('current_device_id') and g.current_user is not None:
            if bool(getattr(g.current_user, 'is_admin', False) or getattr(g.current_user, 'role', '') == 'admin'):
                g.current_device = AppDevice.query.filter_by(id=session.get('current_device_id'), is_active=True).first()
            else:
                g.current_device = AppDevice.query.filter_by(
                    id=session.get('current_device_id'),
                    owner_user_id=g.current_user.id,
                    is_active=True,
                ).first()
        if g.current_device is None and g.current_user is not None:
            g.current_device = AppDevice.query.filter_by(owner_user_id=g.current_user.id, is_active=True).order_by(AppDevice.id.asc()).first()
            if g.current_device:
                session['current_device_id'] = g.current_device.id
            elif not bool(getattr(g.current_user, 'is_admin', False) or getattr(g.current_user, 'role', '') == 'admin'):
                session.pop('current_device_id', None)
        g.is_admin = bool(getattr(g.current_user, 'is_admin', False) or getattr(g.current_user, 'role', '') == 'admin')
        if g.current_user and getattr(g.current_user, 'permissions_json', None):
            try:
                import json as _json
                g.permissions = _json.loads(g.current_user.permissions_json or '{}')
            except Exception:
                g.permissions = {}
        if g.current_user is not None and not g.is_admin:
            try:
                ensure_user_tenant_and_subscription(g.current_user, activated_by_user_id=g.current_user.id)
                for key in ('can_manage_devices','can_manage_integrations','can_use_telegram','can_use_sms','can_view_diagnostics','can_view_api_explorer'):
                    g.plan_features[key] = feature_enabled_for_user(g.current_user, key)
            except Exception:
                g.plan_features = {}

        g.current_user_display = (getattr(g.current_user, 'full_name', None) or getattr(g.current_user, 'username', '') or '').strip()
        g.mail_notification_count = 0
        g.ticket_notification_count = 0
        if g.current_user is not None:
            try:
                _total, g.mail_notification_count, g.ticket_notification_count = unread_counts(g.current_user)
            except Exception:
                # Fallback keeps older databases usable before Heavy v6 migration completes.
                g.mail_notification_count = 0
                g.ticket_notification_count = 0

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
