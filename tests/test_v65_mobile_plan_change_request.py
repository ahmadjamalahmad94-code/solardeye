"""v65 — mobile plan-change request tests.

The two backend additions are thin wrappers around existing models:

  1. `_available_plans_payload(user)`           — list of active
     SubscriptionPlan rows with `is_current` marked against the
     user's tenant.
  2. `_pending_plan_change_request_payload(user)` — projection of
     the most recent `open` SupportCase(`case_type=
     'plan_change_request'`) for the user.
  3. `_parse_plan_change_subject(subject)` / `_resolve_plan_id_by_name(name)`
     — pure helpers powering the projection above.
  4. `mobile_account_request_plan_change`        — POST route that
     mirrors `billing.account_subscription_request_change` (cancel
     prior open cases then persist a new one).

Style mirrors v59 / v62 / v50: helper unit tests + route handler
tests via `Flask.test_request_context` + mocks. No DB, no
`create_app()` boot — every collaborator is monkeypatched.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Pure helper tests (no Flask context required)
# ═══════════════════════════════════════════════════════════════════════

def test_parse_subject_with_em_dash_message():
    """Web convention: `'طلب تغيير الخطة إلى Pro — note text'`."""
    from app.blueprints.mobile_api import _parse_plan_change_subject
    name, msg = _parse_plan_change_subject('طلب تغيير الخطة إلى Pro — أريد ترقية الباقة')
    assert name == 'Pro'
    assert msg == 'أريد ترقية الباقة'


def test_parse_subject_without_message():
    from app.blueprints.mobile_api import _parse_plan_change_subject
    name, msg = _parse_plan_change_subject('طلب تغيير الخطة إلى Pro')
    assert name == 'Pro'
    assert msg is None


def test_parse_subject_with_plain_hyphen_separator():
    """Forward-compat: a future drift to a plain hyphen still parses."""
    from app.blueprints.mobile_api import _parse_plan_change_subject
    name, msg = _parse_plan_change_subject('طلب تغيير الخطة إلى Pro - quick test')
    assert name == 'Pro'
    assert msg == 'quick test'


def test_parse_subject_returns_raw_when_prefix_missing():
    """Legacy / unrelated subjects must NOT crash the parser; they
    surface as the requested_plan_name placeholder so the mobile UI
    can render *something* honestly."""
    from app.blueprints.mobile_api import _parse_plan_change_subject
    name, msg = _parse_plan_change_subject('an unrelated subject')
    assert name == 'an unrelated subject'
    assert msg is None


def test_parse_subject_handles_empty_and_none():
    from app.blueprints.mobile_api import _parse_plan_change_subject
    for raw in (None, '', '   '):
        name, msg = _parse_plan_change_subject(raw)
        assert name == ''
        assert msg is None


def test_parse_subject_strips_surrounding_whitespace():
    from app.blueprints.mobile_api import _parse_plan_change_subject
    name, msg = _parse_plan_change_subject(
        '  طلب تغيير الخطة إلى Pro —    note with leading space   ',
    )
    assert name == 'Pro'
    assert msg == 'note with leading space'


# ═══════════════════════════════════════════════════════════════════════
# Payload helpers (use mocked queries)
# ═══════════════════════════════════════════════════════════════════════

def _fake_plan(plan_id, *, code='basic', name_ar='أساسي', name_en='Basic',
               price=0.0, currency='USD', max_devices=1, is_active=True):
    p = mock.Mock()
    p.id = plan_id
    p.code = code
    p.name_ar = name_ar
    p.name_en = name_en
    p.price = price
    p.currency = currency
    p.max_devices = max_devices
    p.is_active = is_active
    return p


def _fake_tenant(plan_id):
    t = mock.Mock()
    t.id = 700
    t.plan_id = plan_id
    return t


def _fake_user(*, id_=42, tenant_id=700, is_admin=False):
    u = mock.Mock()
    u.id = id_
    u.tenant_id = tenant_id
    u.is_admin = is_admin
    return u


def _plan_query_chain(rows):
    """`SubscriptionPlan.query.filter_by(is_active=True).order_by(..., ...).all()`."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = rows
    return chain


def _tenant_query_chain(tenant):
    """`TenantAccount.query.get(user.tenant_id)`."""
    q = mock.Mock()
    q.get.return_value = tenant
    return q


def _support_case_query_chain(case):
    """`SupportCase.query.filter_by(...).order_by(...).first()`."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = case
    return chain


def test_available_plans_marks_current_plan():
    """Plan rows are rendered as dicts with stable keys; the user's
    current plan (resolved via `TenantAccount.plan_id`) carries
    `is_current=True` — every other plan is `False`."""
    from app.blueprints.mobile_api import (
        _available_plans_payload, SubscriptionPlan, TenantAccount,
    )

    app = _make_app()
    user = _fake_user(tenant_id=700)
    basic = _fake_plan(1, code='basic', name_ar='أساسي', name_en='Basic')
    pro = _fake_plan(2, code='pro', name_ar='برو', name_en='Pro',
                     price=29.0, max_devices=3)

    # `flask_sqlalchemy.Model.query` is a descriptor that requires a
    # Flask app context to resolve, even when we override it with
    # mock.patch.object. We wrap the helper call in a test request
    # context (same pattern v62 uses for its route tests).
    with app.test_request_context('/'), \
         mock.patch.object(SubscriptionPlan, 'query',
                           _plan_query_chain([basic, pro])), \
         mock.patch.object(TenantAccount, 'query',
                           _tenant_query_chain(_fake_tenant(plan_id=1))), \
         mock.patch('app.blueprints.mobile_api.plan_features',
                    return_value=['can_view_dashboard']):
        plans = _available_plans_payload(user)

    assert len(plans) == 2
    assert {p['id']: p['is_current'] for p in plans} == {1: True, 2: False}
    # Locked contract keys.
    for entry in plans:
        for key in ('id', 'code', 'name_ar', 'name_en', 'price', 'currency',
                    'max_devices', 'features', 'is_current'):
            assert key in entry
    assert plans[1]['features'] == ['can_view_dashboard']


def test_available_plans_returns_empty_when_no_active_plans():
    from app.blueprints.mobile_api import (
        _available_plans_payload, SubscriptionPlan, TenantAccount,
    )
    app = _make_app()
    user = _fake_user(tenant_id=None)
    with app.test_request_context('/'), \
         mock.patch.object(SubscriptionPlan, 'query',
                           _plan_query_chain([])), \
         mock.patch.object(TenantAccount, 'query',
                           _tenant_query_chain(None)), \
         mock.patch('app.blueprints.mobile_api.plan_features',
                    return_value=[]):
        plans = _available_plans_payload(user)
    assert plans == []


def test_pending_plan_change_request_is_null_when_absent():
    from app.blueprints.mobile_api import (
        _pending_plan_change_request_payload, SupportCase,
    )
    app = _make_app()
    user = _fake_user()
    with app.test_request_context('/'), \
         mock.patch.object(SupportCase, 'query',
                           _support_case_query_chain(None)):
        payload = _pending_plan_change_request_payload(user)
    assert payload is None


def test_pending_plan_change_request_parses_subject_with_message():
    """The web flow stores `'طلب تغيير الخطة إلى Pro — note text'`
    in `SupportCase.subject`. The mobile projection recovers the
    plan name + message and best-effort resolves the plan id."""
    from app.blueprints.mobile_api import (
        _pending_plan_change_request_payload, SupportCase, SubscriptionPlan,
    )
    app = _make_app()
    user = _fake_user()
    case = mock.Mock()
    case.id = 555
    case.status = 'open'
    case.subject = 'طلب تغيير الخطة إلى Pro — testing note'
    case.created_at = datetime(2026, 5, 12, 12, 0, 0)

    # Resolve "Pro" to a real plan id.
    resolved_plan = _fake_plan(2, code='pro', name_ar='برو', name_en='Pro')
    name_query = mock.Mock()
    name_query.filter.return_value.first.return_value = resolved_plan

    with app.test_request_context('/'), \
         mock.patch.object(SupportCase, 'query',
                           _support_case_query_chain(case)), \
         mock.patch.object(SubscriptionPlan, 'query', name_query):
        payload = _pending_plan_change_request_payload(user)

    assert payload is not None
    assert payload['id'] == 555
    assert payload['status'] == 'open'
    assert payload['requested_plan_id'] == 2
    assert payload['requested_plan_name'] == 'Pro'
    assert payload['message'] == 'testing note'
    assert payload['created_at'] == '2026-05-12T12:00:00'


def test_pending_plan_change_request_handles_missing_plan_lookup():
    """When the recovered name no longer matches an active plan
    (e.g. plan renamed admin-side), `requested_plan_id` stays
    `None` but the textual name + message are still surfaced."""
    from app.blueprints.mobile_api import (
        _pending_plan_change_request_payload, SupportCase, SubscriptionPlan,
    )
    app = _make_app()
    user = _fake_user()
    case = mock.Mock()
    case.id = 9
    case.status = 'open'
    case.subject = 'طلب تغيير الخطة إلى DeletedPlanName'
    case.created_at = datetime(2026, 5, 12, 12, 0, 0)

    # Plan lookup returns None.
    name_query = mock.Mock()
    name_query.filter.return_value.first.return_value = None

    with app.test_request_context('/'), \
         mock.patch.object(SupportCase, 'query',
                           _support_case_query_chain(case)), \
         mock.patch.object(SubscriptionPlan, 'query', name_query):
        payload = _pending_plan_change_request_payload(user)

    assert payload['requested_plan_id'] is None
    assert payload['requested_plan_name'] == 'DeletedPlanName'
    assert payload['message'] is None


# ═══════════════════════════════════════════════════════════════════════
# Capabilities advertisement
# ═══════════════════════════════════════════════════════════════════════

def test_account_capabilities_advertises_plan_change_request():
    from app.blueprints.mobile_api import _account_capabilities_payload
    caps = _account_capabilities_payload()
    assert caps['plan_change_request'] is True


# ═══════════════════════════════════════════════════════════════════════
# Route handler tests (Flask test_request_context + mocks)
# ═══════════════════════════════════════════════════════════════════════

def _make_app():
    from flask import Flask
    from app.blueprints.mobile_api import mobile_core_api_bp
    app = Flask(__name__)
    app.config['MAX_READINGS_QUERY'] = 2000
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_core_api_bp)
    return app


def _patch_bearer_user(user):
    """`_require_bearer_user` reads the `Authorization` header and
    calls `verify_access_token`. The route bodies expect the helper
    to return `(user, None)`; we patch the wrapper directly."""
    return mock.patch(
        'app.blueprints.mobile_api._require_bearer_user',
        return_value=(user, None),
    )


def _patch_account_payload(payload):
    """`mobile_account_request_plan_change` calls `_account_payload`
    to build the success body. The route's own logic is what we
    care about; the payload helpers are exercised elsewhere."""
    return mock.patch(
        'app.blueprints.mobile_api._account_payload',
        return_value=payload,
    )


def _patch_ensure_tenant(tenant):
    return mock.patch(
        'app.blueprints.mobile_api.ensure_user_tenant_and_subscription',
        return_value=(tenant, None),
    )


def test_route_missing_plan_id_returns_400_plan_id_required():
    from app.blueprints.mobile_api import mobile_account_request_plan_change
    app = _make_app()
    user = _fake_user()
    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'message': 'hi'},
    ), _patch_bearer_user(user):
        resp = mobile_account_request_plan_change()
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['ok'] is False
    assert body['code'] == 'plan_id_required'


def test_route_unknown_plan_returns_404_plan_not_found():
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan,
    )
    app = _make_app()
    user = _fake_user()

    # SubscriptionPlan.query.get(plan_id) → None
    plan_query = mock.Mock()
    plan_query.get.return_value = None

    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 9999},
    ), _patch_bearer_user(user), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query):
        resp = mobile_account_request_plan_change()
    assert resp.status_code == 404
    body = resp.get_json()
    assert body['ok'] is False
    assert body['code'] == 'plan_not_found'


def test_route_inactive_plan_returns_404_plan_not_found():
    """Same error code for `is_active=False` — the user-facing UI
    shouldn't see deactivated plans as a separate state."""
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan,
    )
    app = _make_app()
    user = _fake_user()
    inactive_plan = _fake_plan(7, is_active=False)
    plan_query = mock.Mock()
    plan_query.get.return_value = inactive_plan
    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 7},
    ), _patch_bearer_user(user), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query):
        resp = mobile_account_request_plan_change()
    assert resp.status_code == 404
    assert resp.get_json()['code'] == 'plan_not_found'


def test_route_non_integer_plan_id_returns_plan_id_invalid():
    from app.blueprints.mobile_api import mobile_account_request_plan_change
    app = _make_app()
    user = _fake_user()
    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 'pro'},
    ), _patch_bearer_user(user):
        resp = mobile_account_request_plan_change()
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'plan_id_invalid'


def test_route_happy_path_cancels_prior_then_creates_new_case():
    """Locks the cancel-then-create pattern: the prior open case
    must be cancelled before a new SupportCase is added, and the
    response must carry the refreshed `_account_payload`."""
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan, SupportCase,
    )
    app = _make_app()
    user = _fake_user(id_=42)
    target_plan = _fake_plan(2, code='pro', name_ar='برو', name_en='Pro')

    plan_query = mock.Mock()
    plan_query.get.return_value = target_plan

    # Track the cancel-update call on SupportCase.query.filter_by(...).update(...).
    cancel_chain = mock.Mock()
    case_query = mock.Mock()
    case_query.filter_by.return_value = cancel_chain
    cancel_chain.update.return_value = 1  # one prior case cancelled

    refreshed_payload = {
        'user': {'id': 42},
        'pending_plan_change_request': {
            'id': 555, 'status': 'open',
            'requested_plan_id': 2,
            'requested_plan_name': 'برو',
            'message': 'please upgrade me',
            'created_at': '2026-05-12T12:00:00',
        },
    }

    fake_tenant = _fake_tenant(plan_id=1)
    db_mock = mock.Mock()

    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 2, 'message': 'please upgrade me'},
    ), _patch_bearer_user(user), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query), \
         mock.patch.object(SupportCase, 'query', case_query), \
         _patch_ensure_tenant(fake_tenant), \
         _patch_account_payload(refreshed_payload), \
         mock.patch('app.blueprints.mobile_api.db', db_mock):
        resp = mobile_account_request_plan_change()

    # Cancel-then-create order locked.
    case_query.filter_by.assert_called_once_with(
        user_id=42,
        case_type='plan_change_request',
        status='open',
    )
    cancel_chain.update.assert_called_once_with({'status': 'cancelled'})

    # Exactly one new SupportCase added + committed.
    assert db_mock.session.add.call_count == 1
    db_mock.session.commit.assert_called_once()

    # Inspect the SupportCase the route built.
    added_case = db_mock.session.add.call_args[0][0]
    assert added_case.case_type == 'plan_change_request'
    assert added_case.user_id == 42
    assert added_case.tenant_id == 700
    assert added_case.source_id == 42
    assert added_case.status == 'open'
    assert added_case.priority == 'normal'
    # Subject convention matches the web flow exactly so the admin
    # triage queue reads both submission channels identically.
    assert added_case.subject == 'طلب تغيير الخطة إلى برو — please upgrade me'

    # Refreshed account payload is returned with 201.
    assert resp.status_code == 201
    data = resp.get_json()['data']
    assert data['pending_plan_change_request']['id'] == 555
    assert data['pending_plan_change_request']['requested_plan_id'] == 2


def test_route_happy_path_without_message_omits_separator():
    """The v89 bridge changed `plan_id`-only calls into a preview
    bridge. To exercise the preserved legacy triage path we include a
    `message`; the created subject must still avoid a dangling
    separator when the note is omitted elsewhere."""
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan, SupportCase,
    )
    app = _make_app()
    user = _fake_user(id_=42)
    target_plan = _fake_plan(2, code='pro', name_ar='برو', name_en='Pro')
    plan_query = mock.Mock()
    plan_query.get.return_value = target_plan
    case_query = mock.Mock()
    cancel_chain = mock.Mock()
    case_query.filter_by.return_value = cancel_chain
    cancel_chain.update.return_value = 0

    db_mock = mock.Mock()
    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 2, 'message': 'legacy please'},  # forces triage fallback
    ), _patch_bearer_user(user), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query), \
         mock.patch.object(SupportCase, 'query', case_query), \
         _patch_ensure_tenant(_fake_tenant(plan_id=1)), \
         _patch_account_payload({}), \
         mock.patch('app.blueprints.mobile_api.db', db_mock):
        mobile_account_request_plan_change()
    added_case = db_mock.session.add.call_args[0][0]
    assert added_case.subject == 'طلب تغيير الخطة إلى برو — legacy please'


def test_route_long_message_is_capped_at_240_chars():
    """A pathological 5 KB message must not blow up the subject;
    the route caps the appended note at 240 chars (matches the v50
    error-message cap pattern)."""
    from app.blueprints.mobile_api import (
        mobile_account_request_plan_change, SubscriptionPlan, SupportCase,
    )
    app = _make_app()
    user = _fake_user(id_=42)
    target_plan = _fake_plan(2, code='pro', name_ar='برو', name_en='Pro')
    plan_query = mock.Mock()
    plan_query.get.return_value = target_plan
    case_query = mock.Mock()
    cancel_chain = mock.Mock()
    case_query.filter_by.return_value = cancel_chain
    cancel_chain.update.return_value = 0

    huge = 'X' * 10_000
    db_mock = mock.Mock()
    with app.test_request_context(
        '/api/mobile/account/subscription/request-change',
        method='POST',
        json={'plan_id': 2, 'message': huge},
    ), _patch_bearer_user(user), \
         mock.patch.object(SubscriptionPlan, 'query', plan_query), \
         mock.patch.object(SupportCase, 'query', case_query), \
         _patch_ensure_tenant(_fake_tenant(plan_id=1)), \
         _patch_account_payload({}), \
         mock.patch('app.blueprints.mobile_api.db', db_mock):
        mobile_account_request_plan_change()
    added_case = db_mock.session.add.call_args[0][0]
    # 'X' × 240 only — the rest is dropped.
    assert added_case.subject.endswith('X' * 240)
    assert 'X' * 241 not in added_case.subject
