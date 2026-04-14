from __future__ import annotations
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

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
    public_endpoints = {'auth.login', 'static'}
    ep = request.endpoint or ''
    if ep in public_endpoints or ep.startswith('static'):
        return
    if not session.get('logged_in'):
        wants_json = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )
        if wants_json:
            return jsonify({
                'ok': False,
                'message': 'انتهت جلسة تسجيل الدخول. أعد تسجيل الدخول ثم جرّب مرة أخرى.'
            }), 401
        return redirect(url_for('auth.login'))
