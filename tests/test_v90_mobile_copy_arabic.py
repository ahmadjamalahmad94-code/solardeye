from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _make_app():
    from flask import Flask
    from app.blueprints.mobile_api import mobile_api_bp, mobile_core_api_bp

    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.config['MAX_READINGS_QUERY'] = 2000
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_api_bp)
    app.register_blueprint(mobile_core_api_bp)
    return app


def _fake_user():
    user = mock.Mock()
    user.id = 7
    user.tenant_id = 70
    user.is_admin = False
    user.role = 'subscriber'
    return user


def test_mobile_health_uses_clear_arabic_message():
    app = _make_app()
    client = app.test_client()

    response = client.get('/api/mobile/health?lang=ar')
    body = response.get_json()

    assert response.status_code == 200
    assert body['data']['message'] == 'واجهة الجوال جاهزة للعمل.'


def test_mobile_preview_auth_required_message_is_arabic():
    app = _make_app()
    client = app.test_client()

    response = client.get('/api/mobile/account/plan-change/preview?plan_id=3&lang=ar')
    body = response.get_json()

    assert response.status_code == 401
    assert body['message'] == 'يلزم إرسال رمز الدخول في ترويسة Bearer.'
    assert 'Authentication required' not in body['message']


def test_mobile_preview_invalid_plan_id_message_is_arabic():
    app = _make_app()
    client = app.test_client()

    with mock.patch(
        'app.blueprints.mobile_api._require_bearer_user',
        return_value=(_fake_user(), None),
    ):
        response = client.get('/api/mobile/account/plan-change/preview?plan_id=abc&lang=ar')

    body = response.get_json()
    assert response.status_code == 400
    assert body['message'] == 'رقم الباقة يجب أن يكون عددًا صحيحًا.'
    assert 'Plan id' not in body['message']


def test_mobile_change_password_missing_fields_are_arabic():
    app = _make_app()
    client = app.test_client()

    with mock.patch(
        'app.blueprints.mobile_api._require_bearer_user',
        return_value=(_fake_user(), None),
    ):
        response = client.post(
            '/api/mobile/account/change-password?lang=ar',
            json={},
        )

    body = response.get_json()
    assert response.status_code == 400
    assert body['message'] == 'كلمة المرور الحالية مطلوبة.'


def test_mobile_method_not_allowed_message_is_arabic():
    app = _make_app()
    client = app.test_client()

    response = client.post('/api/mobile/account/plan-change/preview?lang=ar')
    body = response.get_json()

    assert response.status_code == 405
    assert body['message'] == 'طريقة الطلب غير مسموحة لهذه الواجهة.'
    assert 'Method is not allowed' not in body['message']
