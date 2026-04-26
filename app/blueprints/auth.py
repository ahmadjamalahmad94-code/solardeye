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
from ..services.rbac import admin_landing_url
from ..services.access_state import account_access_state
from ..services.energy_integrations import PROVIDER_CATALOG
from ..services.location_catalog import countries_for_template, timezones_for_template, find_country


auth_bp = Blueprint('auth', __name__)




def _is_admin_like_user(user: AppUser | None) -> bool:
    if not user or not bool(getattr(user, 'is_active', True)):
        return False
    role = (getattr(user, 'role', '') or '').strip().lower()
    # Empty/unknown roles must NOT become admin. Only explicit staff roles do.
    return bool(getattr(user, 'is_admin', False) or role not in {'', 'user', 'subscriber', 'customer'})

def _login_user(app_user: AppUser):
    session.permanent = True
    session['logged_in'] = True
    session['username'] = app_user.username
    session['user_id'] = app_user.id
    if getattr(app_user, 'preferred_language', None):
        session['ui_lang'] = app_user.preferred_language
    session['current_device_type'] = app_user.preferred_device_type or 'deye'

    device = None
    if getattr(app_user, 'preferred_device_id', None):
        device = AppDevice.query.filter_by(id=app_user.preferred_device_id, owner_user_id=app_user.id, is_active=True).first()
    if device is None:
        device = AppDevice.query.filter_by(owner_user_id=app_user.id, is_active=True).order_by(AppDevice.id.asc()).first()
    if device and not _is_admin_like_user(app_user):
        session['current_device_id'] = device.id
        session['current_device_type'] = device.device_type or 'deye'
        if app_user.preferred_device_id != device.id:
            app_user.preferred_device_id = device.id
    else:
        session.pop('current_device_id', None)
    app_user.last_login_at = datetime.utcnow()
    db.session.commit()


def _create_default_device_for_user(user: AppUser, name: str | None = None, device_type: str | None = None):
    base_name = (name or user.full_name or user.username or 'My Energy Site').strip()
    provider_code = (device_type or user.preferred_device_type or 'deye').strip() or 'deye'
    spec = next((p for p in PROVIDER_CATALOG if p.code == provider_code), None)
    device = AppDevice(
        owner_user_id=user.id,
        name=f"{base_name} — {spec.name if spec else provider_code}",
        device_type=provider_code,
        api_provider=(spec.provider if spec else provider_code),
        api_base_url=(spec.base_url if spec else current_app.config.get('DEYE_BASE_URL', '')),
        timezone=getattr(user, 'timezone', None) or current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron'),
        auth_mode='wizard',
        is_active=True,
        connection_status='setup_required',
        notes='تم إنشاؤه كبداية من التسجيل. أكمل بيانات الربط من معالج الإعداد.',
    )
    db.session.add(device)
    db.session.flush()
    user.preferred_device_id = device.id
    user.preferred_device_type = device.device_type or provider_code
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
    if _is_admin_like_user(user):
        return redirect(admin_landing_url(session.get('ui_lang') or 'ar'))
    if account_access_state(user).get('restricted'):
        flash('حسابك في وضع مشاهدة فقط. فعّل حسابك أو اشتراكك للاستفادة من خدماتنا.', 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    if not getattr(user, 'onboarding_completed', False):
        return redirect(url_for('main.onboarding_wizard'))
    return redirect(url_for('main.dashboard'))



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        app_user = AppUser.query.filter_by(username=username).first()
        password_ok = False

        configured_admin_password = (current_app.config.get('ADMIN_PASSWORD') or '').strip()
        if configured_admin_password and username == current_app.config['ADMIN_USERNAME'] and password == configured_admin_password:
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
                if _is_admin_like_user(app_user):
                    return redirect(admin_landing_url(session.get('ui_lang') or 'ar'))
                if account_access_state(app_user).get('restricted'):
                    flash('حسابك في وضع مشاهدة فقط. فعّل حسابك أو اشتراكك للاستفادة من خدماتنا.', 'warning')
                    return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
                if not getattr(app_user, 'onboarding_completed', False):
                    return redirect(url_for('main.onboarding_wizard'))
                return redirect(url_for('main.dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    country_options = countries_for_template()
    timezone_options = timezones_for_template()
    provider_options = [
        {'code': p.code, 'name': p.name, 'category': p.category, 'notes_ar': p.notes_ar, 'notes_en': p.notes_en}
        for p in PROVIDER_CATALOG[:22]
    ]
    form_values = request.form if request.method == 'POST' else {}

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        country_code = request.form.get('country_code', '').strip().upper()
        country = request.form.get('country', '').strip()
        city = request.form.get('city', '').strip()
        timezone = request.form.get('timezone', 'Asia/Hebron').strip() or 'Asia/Hebron'
        phone_country_code = request.form.get('phone_country_code', '').strip()
        phone_number = ''.join(ch for ch in (request.form.get('phone_number', '') or '') if ch.isdigit() or ch in ('+', ' ', '-', '(', ')')).strip()
        preferred_language = request.form.get('preferred_language', session.get('ui_lang') or 'ar').strip() or 'ar'
        has_energy_system = request.form.get('has_energy_system', 'yes').strip()
        preferred_device_type = request.form.get('preferred_device_type', 'deye').strip() or 'deye'
        next_step = request.form.get('next_step', 'setup').strip() or 'setup'

        allowed_provider_codes = {p['code'] for p in provider_options}
        if preferred_device_type not in allowed_provider_codes:
            preferred_device_type = 'deye'
        selected_country = find_country(country_code or country)
        if selected_country:
            country = selected_country['name_en'] if preferred_language == 'en' else selected_country['name_ar']
            if not phone_country_code:
                phone_country_code = selected_country.get('dial') or ''
            if timezone not in timezone_options:
                timezone = selected_country.get('timezone') or 'Asia/Hebron'
        elif timezone not in timezone_options:
            timezone = 'Asia/Hebron'
        if preferred_language not in {'ar', 'en'}:
            preferred_language = 'ar'

        if not username or not password:
            flash('اسم المستخدم وكلمة المرور مطلوبان.', 'warning')
        elif len(password) < 6:
            flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل.', 'warning')
        elif password != confirm_password:
            flash('تأكيد كلمة المرور غير مطابق.', 'danger')
        elif not country or not city:
            flash('الدولة والمدينة مطلوبتان لضبط الطقس والتوقيت بدقة.', 'warning')
        elif phone_number and len(''.join(ch for ch in phone_number if ch.isdigit())) < 6:
            flash('رقم الهاتف قصير جدًا. أدخل رقمًا صحيحًا أو اتركه فارغًا.', 'warning')
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
                phone_country_code=phone_country_code,
                phone_number=phone_number,
                country=country,
                city=city,
                timezone=timezone,
                preferred_language=preferred_language,
                role='user',
                preferred_device_type=preferred_device_type,
                is_active=True,
                is_admin=False,
                onboarding_completed=(has_energy_system == 'no'),
                onboarding_step='welcome' if has_energy_system != 'no' else 'explore_services',
            )
            db.session.add(user)
            db.session.flush()
            if has_energy_system != 'no':
                _create_default_device_for_user(user, full_name or username, preferred_device_type)
            db.session.commit()
            session['ui_lang'] = preferred_language
            _login_user(user)
            flash('تم إنشاء الحساب بنجاح. جهزنا ملفك حسب موقعك وتفضيلاتك ✨', 'success')
            if has_energy_system == 'no' or next_step == 'explore':
                flash('يمكنك استكشاف الخدمات الآن وإضافة جهاز لاحقًا من صفحة أجهزتي.', 'info')
                return redirect(url_for('main.account_subscription', lang=preferred_language))
            return redirect(url_for('main.onboarding_wizard', lang=preferred_language))
    return render_template('register.html', country_options=country_options, timezone_options=timezone_options, provider_options=provider_options, form_values=form_values)



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
        'energy.index',
    }
    ep = request.endpoint or ''
    public_paths = {'/', '/index', '/landing'}
    if (request.path or '') in public_paths:
        return
    if ep in public_endpoints or ep.startswith('static'):
        return
    g.current_user = None
    g.current_device = None
    g.is_admin = False
    g.permissions = {}
    g.plan_features = {}
    if session.get('logged_in'):
        if session.get('user_id'):
            # Security: keep the actual session user even if the account was disabled.
            # Falling back to a default/system admin during a browser request can expose admin pages.
            g.current_user = AppUser.query.filter_by(id=session.get('user_id')).first()
        if g.current_user is None and session.get('username'):
            g.current_user = AppUser.query.filter_by(username=session.get('username')).first()
        if session.get('current_device_id') and g.current_user is not None:
            if _is_admin_like_user(g.current_user):
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
            elif not _is_admin_like_user(g.current_user):
                session.pop('current_device_id', None)
        g.is_admin = _is_admin_like_user(g.current_user)
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

    # Security: subscriber sessions must never render /admin/* pages, even if a notification contains an old admin URL.
    if session.get('logged_in') and (request.path or '').startswith('/admin') and (g.current_user is None or not g.is_admin):
        flash('هذه الصفحة خاصة بالإدارة. تم تحويلك إلى بوابتك.', 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))

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
