from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _make_app():
    from flask import Flask
    from app.blueprints.mobile_api import mobile_core_api_bp
    app = Flask(__name__)
    app.config['MAX_READINGS_QUERY'] = 2000
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_core_api_bp)
    return app


def _fake_user(*, id_=42, tenant_id=700, is_admin=False):
    u = mock.Mock()
    u.id = id_
    u.tenant_id = tenant_id
    u.is_admin = is_admin
    u.role = 'subscriber'
    u.username = 'user42'
    u.full_name = 'User 42'
    return u


def _fake_tenant(plan_id=1):
    t = mock.Mock()
    t.id = 700
    t.plan_id = plan_id
    return t


def _patch_bearer_user(user):
    return mock.patch(
        'app.blueprints.mobile_api._require_bearer_user',
        return_value=(user, None),
    )


def _patch_account_payload(payload):
    return mock.patch(
        'app.blueprints.mobile_api._account_payload',
        return_value=payload,
    )


def _patch_ensure_tenant(tenant):
    return mock.patch(
        'app.blueprints.mobile_api.ensure_user_tenant_and_subscription',
        return_value=(tenant, None),
    )


def test_legacy_endpoint_plan_id_only_returns_preview_bridge_without_case_creation():
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan,
    )

    app = _make_app()
    user = _fake_user()
    target_plan = mock.Mock()
    target_plan.id = 3
    target_plan.is_active = True
    plan_query = mock.Mock()
    plan_query.get.return_value = target_plan
    preview_result = mock.Mock()
    preview_result.blocked_reason = None
    preview_result.to_dict.return_value = {
        'policy_kind': 'upgrade',
        'target_plan_id': 3,
        'same_duration': {'amount': 8.23},
        'reduced_days': {'target_days': 49},
    }
    db_mock = mock.Mock()
    base_payload = {'subscription': {'status': 'active'}}

    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 3},
    ), _patch_bearer_user(user), _patch_account_payload(base_payload), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query), \
         mock.patch('app.blueprints.mobile_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_api.ensure_user_tenant_and_subscription'), \
         mock.patch('app.services.subscriber_plan_change.preview', return_value=preview_result):
        resp = mobile_account_request_plan_change()

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['meta']['compat'] == 'legacy_bridge'
    assert body['meta']['flow'] == 'preview'
    assert body['data']['subscription']['status'] == 'active'
    assert body['data']['plan_change_preview']['policy_kind'] == 'upgrade'
    db_mock.session.add.assert_not_called()
    db_mock.session.commit.assert_not_called()


def test_legacy_endpoint_mode_confirm_returns_account_payload_plus_result():
    from app.blueprints.mobile_api import mobile_account_request_plan_change

    app = _make_app()
    user = _fake_user()
    confirm_result = mock.Mock()
    confirm_result.outcome = 'payment_required'
    confirm_result.blocked_reason = None
    confirm_result.to_dict.return_value = {
        'outcome': 'payment_required',
        'case_status': 'payment_requested',
        'amount': 8.23,
        'currency': 'USD',
        'invoice_reference': 'INV-700-9',
        'target_plan_id': 3,
    }
    base_payload = {'subscription': {'status': 'active'}}

    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 3, 'mode': 'same_duration'},
    ), _patch_bearer_user(user), _patch_account_payload(base_payload), \
         mock.patch('app.services.subscriber_plan_change.confirm', return_value=confirm_result):
        resp = mobile_account_request_plan_change()

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['meta']['compat'] == 'legacy_bridge'
    assert body['meta']['flow'] == 'confirm'
    assert body['data']['subscription']['status'] == 'active'
    assert body['data']['plan_change_result']['outcome'] == 'payment_required'
    assert body['data']['plan_change_result']['invoice_reference'] == 'INV-700-9'


def test_legacy_endpoint_downgrade_same_duration_returns_400_with_preview():
    from app.blueprints.mobile_api import mobile_account_request_plan_change

    app = _make_app()
    user = _fake_user()
    confirm_result = mock.Mock()
    confirm_result.outcome = 'blocked'
    confirm_result.blocked_reason = 'downgrade_same_duration_not_allowed'
    confirm_result.to_dict.return_value = {
        'outcome': 'blocked',
        'blocked_reason': 'downgrade_same_duration_not_allowed',
        'target_plan_id': 1,
    }
    preview_result = mock.Mock()
    preview_result.to_dict.return_value = {
        'policy_kind': 'downgrade',
        'reduced_days': {'target_days': 98},
    }
    base_payload = {'subscription': {'status': 'active'}}

    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 1, 'mode': 'same_duration'},
    ), _patch_bearer_user(user), _patch_account_payload(base_payload), \
         mock.patch('app.services.subscriber_plan_change.confirm', return_value=confirm_result), \
         mock.patch('app.services.subscriber_plan_change.preview', return_value=preview_result):
        resp = mobile_account_request_plan_change()

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert body['code'] == 'downgrade_same_duration_not_allowed'
    assert body['meta']['flow'] == 'confirm'
    assert body['data']['plan_change_result']['blocked_reason'] == 'downgrade_same_duration_not_allowed'
    assert body['data']['plan_change_preview']['policy_kind'] == 'downgrade'


def test_legacy_endpoint_with_message_keeps_triage_fallback():
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan, SupportCase,
    )

    app = _make_app()
    user = _fake_user(id_=42)
    target_plan = mock.Mock()
    target_plan.id = 2
    target_plan.is_active = True
    target_plan.name_ar = 'برو'
    target_plan.name_en = 'Pro'
    target_plan.code = 'pro'

    plan_query = mock.Mock()
    plan_query.get.return_value = target_plan
    # v88c — legacy mobile route now uses find-or-reuse on the
    # UNIQUE (case_type, source_id) index. With first()=None the
    # INSERT branch is taken, matching the original test intent.
    case_query = mock.Mock()
    case_query.filter_by.return_value = case_query
    case_query.first.return_value = None
    db_mock = mock.Mock()

    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 2, 'message': 'please upgrade me'},
    ), _patch_bearer_user(user), _patch_account_payload({'subscription': {'status': 'active'}}), \
         _patch_ensure_tenant(_fake_tenant(plan_id=1)), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query), \
         mock.patch.object(SupportCase, 'query', case_query), \
         mock.patch('app.blueprints.mobile_api.db', db_mock), \
         mock.patch('app.blueprints.mobile_api.notify_admins_of_plan_change_request', create=True):
        resp = mobile_account_request_plan_change()

    assert resp.status_code == 201
    body = resp.get_json()
    assert body['ok'] is True
    assert body['meta']['compat_fallback'] == 'legacy_triage'
    assert body['meta']['flow'] == 'legacy_request'
    db_mock.session.add.assert_called_once()
    db_mock.session.commit.assert_called_once()


def test_legacy_endpoint_unknown_mode_returns_structured_error():
    from app.blueprints.mobile_api import mobile_account_request_plan_change

    app = _make_app()
    user = _fake_user()
    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 3, 'mode': 'something_else'},
    ), _patch_bearer_user(user):
        resp = mobile_account_request_plan_change()

    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert body['code'] == 'unknown_mode'
