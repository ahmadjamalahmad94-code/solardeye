"""v86 — open-loops final closure tests.

Six loops closed in this wave, each gets a focused test slice:

  E. Mobile parity — `mobile_account_request_plan_change` now
     fans out admin notifications via
     `notify_admins_of_plan_change_request`. Pre-v86 mobile
     submissions were invisible to admins.

  F. API quota coverage — the three mobile blueprints
     (`mobile_devices_api_bp`, `mobile_notifications_api_bp`,
     `mobile_support_api_bp`) now register the shared
     `record_api_quota_for_current_request` hook the same way
     `mobile_core_api_bp` already did in v80.

  G. Web device-limit enforcement — `devices_routes.devices_manage`
     POST now refuses creation when the subscriber is already at
     `allowed_device_limit(user)`. Mobile already had this gate;
     web had drifted.

  B3/B5. Subscriber payment-required surfacing — the subscription
     page now fetches ALL active plan-change cases (not just
     `status='open'`) and surfaces the pending invoice amount +
     a "Pay with sandbox card" button.

  C4. Workbench Mark-settled button — admin workbench template
     now exposes the `mark_invoice_settled` action when the case
     is in `payment_requested` state.

  D. Stripe invoice checkout — new
     `create_invoice_checkout_session(...)` helper + route
     `POST /payments/stripe/checkout/invoice` lets the subscriber
     pay an outstanding plan-change invoice in test mode. The
     webhook `handle_event(...)` now flips the case to
     `payment_settled` on `checkout.session.completed` when the
     event carries `kind='plan_change_invoice'` metadata.

Style mirrors v80 / v81 / v82 / v84 / v85: mock-based, no DB
boot, app-context fixture covers SQLAlchemy model instantiation.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _ctx():
    from flask import Flask
    from app.extensions import db
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app.app_context()


# ═══════════════════════════════════════════════════════════════════════
# E. Mobile parity — admin notify fanout
# ═══════════════════════════════════════════════════════════════════════


def test_mobile_plan_change_request_now_calls_admin_notify():
    """Source-inspection lock: the mobile route's body must call
    `notify_admins_of_plan_change_request` after creating the
    case. Pre-v86 it skipped the fanout."""
    import inspect
    # Read the file as text so importing it doesn't pull in heavy
    # main.py dependencies (reportlab in dev).
    mobile_path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(mobile_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    marker = 'def mobile_account_request_plan_change():'
    start = src.find(marker)
    assert start >= 0, 'mobile plan-change route missing'
    lines = src[start:].splitlines()
    body_lines = [lines[0]]
    for line in lines[1:]:
        if line == '' or line.startswith(' ') or line.startswith('\t'):
            body_lines.append(line)
        else:
            break
    body = '\n'.join(body_lines)
    # v86 fix: fanout is present.
    assert 'notify_admins_of_plan_change_request' in body
    # Still creates the case (the legacy core behaviour is
    # preserved — v86 is additive on the notification side).
    assert 'SupportCase(' in body


# ═══════════════════════════════════════════════════════════════════════
# F. API quota coverage on remaining mobile blueprints
# ═══════════════════════════════════════════════════════════════════════


def test_record_api_quota_helper_exists_and_is_safe_with_no_request():
    """The shared helper must exist, be callable, and NEVER raise
    even when there's no active Flask request context."""
    from app.services import quota_engine
    assert callable(getattr(quota_engine, 'record_api_quota_for_current_request', None))
    # Calling without a request context must be a calm no-op.
    quota_engine.record_api_quota_for_current_request()


def test_record_api_quota_skips_auth_and_health_paths():
    """The skip set must exclude auth namespaces and health
    endpoints from both the v80 core blueprint and the v86
    extension blueprints. A subscriber whose quota is exhausted
    must still be able to authenticate and ping health."""
    from app.services.quota_engine import (
        _API_QUOTA_SKIP_PATHS, _API_QUOTA_SKIP_PREFIXES,
    )
    assert '/api/mobile/health' in _API_QUOTA_SKIP_PATHS
    assert '/health' in _API_QUOTA_SKIP_PATHS
    assert '/api/mobile/auth/' in _API_QUOTA_SKIP_PREFIXES
    assert '/api/v1/mobile/auth/' in _API_QUOTA_SKIP_PREFIXES


def test_record_api_quota_skips_options_and_unauth_and_admin():
    """Three idempotent skip conditions inside the hook body. We
    drive the hook directly without booting the full app so this
    test stays fast."""
    from flask import Flask, g
    from app.services import quota_engine as qe
    app = Flask(__name__)

    # 1) OPTIONS preflight skip.
    with app.test_request_context('/api/v1/devices/42/history', method='OPTIONS'), \
         mock.patch.object(qe, 'track_api_call_for_user') as tracker:
        qe.record_api_quota_for_current_request()
        tracker.assert_not_called()

    # 2) Unauthenticated request skip.
    with app.test_request_context('/api/v1/devices/42/history'), \
         mock.patch(
             'app.services.mobile_auth.user_from_bearer_or_session',
             return_value=None,
         ), mock.patch.object(qe, 'track_api_call_for_user') as tracker:
        qe.record_api_quota_for_current_request()
        tracker.assert_not_called()

    # 3) Admin user skip.
    admin = mock.Mock(); admin.is_admin = True
    with app.test_request_context('/api/v1/devices/42/history'), \
         mock.patch(
             'app.services.mobile_auth.user_from_bearer_or_session',
             return_value=admin,
         ), mock.patch.object(qe, 'track_api_call_for_user') as tracker:
        qe.record_api_quota_for_current_request()
        tracker.assert_not_called()


def test_record_api_quota_bumps_for_authenticated_subscriber():
    """Happy path: protected path + non-admin user → tracker is
    called exactly once. A second invocation in the same request
    cycle is a no-op (idempotency guard on `g`)."""
    from flask import Flask
    from app.services import quota_engine as qe
    app = Flask(__name__)
    user = mock.Mock(); user.is_admin = False
    with app.test_request_context('/api/v1/devices/42/history'), \
         mock.patch(
             'app.services.mobile_auth.user_from_bearer_or_session',
             return_value=user,
         ), mock.patch.object(qe, 'track_api_call_for_user') as tracker:
        qe.record_api_quota_for_current_request()
        # Second invocation in same request → no double-count.
        qe.record_api_quota_for_current_request()
        tracker.assert_called_once()


def test_three_remaining_mobile_blueprints_register_the_hook():
    """v80 only hooked `mobile_core_api_bp`. v86 closes the gap by
    registering the same hook on the three sister blueprints. We
    verify by source inspection so the test doesn't have to boot
    the full app."""
    for module_rel in (
        'app/blueprints/mobile_devices_api.py',
        'app/blueprints/mobile_notifications_api.py',
        'app/blueprints/mobile_support_api.py',
    ):
        full = os.path.join(_REPO_ROOT, module_rel.replace('/', os.sep))
        with open(full, 'r', encoding='utf-8') as fh:
            src = fh.read()
        assert 'before_request' in src, f'{module_rel} missing before_request'
        assert 'record_api_quota_for_current_request' in src, (
            f'{module_rel} does not register the v86 shared hook'
        )


# ═══════════════════════════════════════════════════════════════════════
# G. Web device-limit enforcement
# ═══════════════════════════════════════════════════════════════════════


def test_web_devices_manage_now_enforces_allowed_device_limit():
    """Source-inspection lock: the POST branch must call
    `allowed_device_limit(user)` and refuse when at-stock. Mobile
    has had this since v76; web had drifted."""
    devices_path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'devices_routes.py',
    )
    with open(devices_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    # The POST branch of `devices_manage` must reference both the
    # limit helper AND a flash + redirect that bails out before
    # creating the AppDevice row.
    marker = 'def devices_manage():'
    start = src.find(marker)
    assert start >= 0
    # Slice the function body via indent walk.
    lines = src[start:].splitlines()
    body_lines = [lines[0]]
    for line in lines[1:]:
        if line == '' or line.startswith(' ') or line.startswith('\t'):
            body_lines.append(line)
        else:
            break
    body = '\n'.join(body_lines)
    assert 'allowed_device_limit' in body
    # The check must appear BEFORE the `AppDevice(owner_user_id=...)`
    # construction — otherwise we'd be enforcing post-mutation.
    check_idx = body.find('allowed_device_limit')
    create_idx = body.find('AppDevice(owner_user_id=user.id)')
    assert 0 < check_idx < create_idx, (
        'enforcement must run before the device row is constructed'
    )


# ═══════════════════════════════════════════════════════════════════════
# B3/B5. Subscriber subscription page surfacing
# ═══════════════════════════════════════════════════════════════════════


def test_subscription_view_fetches_all_active_plan_change_cases():
    """The view used to filter on `status='open'` only — missing
    `payment_requested` / `payment_settled` / `under_review` /
    `awaiting_subscriber_reply`. v86 widens the filter to the
    workbench ACTIVE_STATUSES set."""
    billing_path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'billing.py',
    )
    with open(billing_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    marker = 'def account_subscription():'
    start = src.find(marker)
    assert start >= 0
    lines = src[start:].splitlines()
    body_lines = [lines[0]]
    for line in lines[1:]:
        if line == '' or line.startswith(' ') or line.startswith('\t'):
            body_lines.append(line)
        else:
            break
    body = '\n'.join(body_lines)
    # The widened query reads through the shared ACTIVE_STATUSES set.
    assert 'ACTIVE_STATUSES' in body
    # And pending_invoice is now resolved + passed to the template.
    assert 'find_pending_invoice' in body
    assert 'pending_invoice' in body


def test_subscription_template_renders_pay_with_card_when_invoice_exists():
    """Lock the new banner contract: the template surfaces the
    invoice amount and a "Pay with sandbox card" form pointing at
    `payments.create_invoice_checkout`."""
    tmpl_path = os.path.join(
        _REPO_ROOT, 'app', 'templates', 'account_subscription_phase1a.html',
    )
    with open(tmpl_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    assert 'pending_invoice' in src
    assert "payments.create_invoice_checkout" in src
    # The amount is rendered via the `%.2f` formatter (no
    # raw float strings leak through).
    assert "'%.2f'|format(pending_invoice.amount" in src


# ═══════════════════════════════════════════════════════════════════════
# C4. Workbench Mark-settled button
# ═══════════════════════════════════════════════════════════════════════


def test_workbench_template_shows_settle_button_when_payment_requested():
    """The admin workbench detail page must expose the
    `mark_invoice_settled` action as a button — pre-v86 the route
    existed but had no UI surface."""
    tmpl_path = os.path.join(
        _REPO_ROOT, 'app', 'templates', 'admin_plan_change_workbench.html',
    )
    with open(tmpl_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    assert 'admin_plan_change_request_settle' in src
    # The form is gated on the case status — the operator only sees
    # it when the case is actually in `payment_requested`.
    assert "status == 'payment_requested'" in src


# ═══════════════════════════════════════════════════════════════════════
# D. Stripe Sandbox invoice checkout
# ═══════════════════════════════════════════════════════════════════════


def test_create_invoice_checkout_session_stamps_plan_change_invoice_metadata():
    """The new helper must mark the Stripe session with
    `kind='plan_change_invoice'` + `case_id` so the webhook can
    settle the right case on completion."""
    from app.services import stripe_gateway as sg
    fake_session = mock.Mock()
    fake_session.id = 'cs_inv_test_001'
    fake_session.url = 'https://checkout.stripe.com/c/cs_inv_test_001'
    fake_module = mock.Mock()
    fake_module.checkout.Session.create.return_value = fake_session
    env = {'STRIPE_PUBLIC_KEY': 'pk_test_x', 'STRIPE_SECRET_KEY': 'sk_test_x'}
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=fake_module):
        result = sg.create_invoice_checkout_session(
            case_id=55,
            amount_value=12.50,
            currency='USD',
            case_label='Plan change for tenant 7',
            success_url='https://x/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://x/cancel',
            customer_email='user@example.com',
            tenant_id=7,
            user_id=11,
        )
    assert result['id'] == 'cs_inv_test_001'
    call_kwargs = fake_module.checkout.Session.create.call_args.kwargs
    # Cents conversion — 12.50 → 1250.
    assert call_kwargs['line_items'][0]['price_data']['unit_amount'] == 1250
    # Metadata stamps the invoice-kind discriminator + case id +
    # provider/mode tokens.
    md = call_kwargs['metadata']
    assert md['provider'] == 'stripe'
    assert md['mode'] == 'test'
    assert md['kind'] == 'plan_change_invoice'
    assert md['case_id'] == '55'
    assert md['tenant_id'] == '7'
    assert md['user_id'] == '11'


def test_create_invoice_checkout_session_rejects_invalid_inputs():
    """Defensive input validation runs before the SDK is touched."""
    from app.services import stripe_gateway as sg
    fake_module = mock.Mock()
    env = {'STRIPE_PUBLIC_KEY': 'pk_test_x', 'STRIPE_SECRET_KEY': 'sk_test_x'}
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=fake_module):
        # Zero amount.
        try:
            sg.create_invoice_checkout_session(
                case_id=1, amount_value=0, currency='USD',
                case_label='x', success_url='https://x/s', cancel_url='https://x/c',
            )
        except ValueError as exc:
            assert 'amount_value' in str(exc)
        else:
            raise AssertionError('expected ValueError on zero amount')
        # Missing case_id.
        try:
            sg.create_invoice_checkout_session(
                case_id=0, amount_value=10.0, currency='USD',
                case_label='x', success_url='https://x/s', cancel_url='https://x/c',
            )
        except ValueError as exc:
            assert 'case_id' in str(exc)
        else:
            raise AssertionError('expected ValueError on missing case_id')


def test_handle_event_settles_plan_change_invoice_on_checkout_completed():
    """`checkout.session.completed` with our `kind` + `case_id`
    metadata must call `mark_invoice_settled` on the matching
    case. Idempotency is enforced by the workbench helper, but the
    handler also short-circuits when the case is not in
    `payment_requested` to avoid noisy double-flips."""
    from app.services import stripe_gateway as sg
    from app.services import plan_change_workbench as wb
    # Fake case in payment_requested state.
    case = mock.Mock()
    case.id = 55
    case.case_type = 'plan_change_request'
    case.status = wb.STATUS_PAYMENT_REQUESTED
    case_query = mock.Mock()
    case_query.filter_by.return_value = case_query
    case_query.first.return_value = case
    event = {
        'type': 'checkout.session.completed',
        'id': 'evt_test_1',
        'data': {
            'object': {
                'id': 'cs_inv_test_001',
                'metadata': {
                    'kind': 'plan_change_invoice',
                    'case_id': '55',
                    'provider': 'stripe',
                    'mode': 'test',
                },
            },
        },
    }
    with _ctx(), mock.patch.object(
        sg, '_settle_plan_change_invoice', wraps=sg._settle_plan_change_invoice,
    ) as wrapped_settle, mock.patch.object(
        wb.SupportCase, 'query', case_query,
    ), mock.patch.object(
        wb, 'mark_invoice_settled', return_value={'case_status': 'payment_settled'},
    ) as mark_mock:
        result = sg.handle_event(event)
    wrapped_settle.assert_called_once_with(55)
    mark_mock.assert_called_once()
    assert result['handled'] is True
    assert result['event_type'] == 'checkout.session.completed'
    assert result.get('reason') == 'plan_change_invoice_settled'


def test_handle_event_is_idempotent_when_case_already_settled():
    """If a second webhook fires for the same case (or the admin
    already marked it settled out-of-band), the handler must
    acknowledge without re-flipping the state."""
    from app.services import stripe_gateway as sg
    from app.services import plan_change_workbench as wb
    case = mock.Mock()
    case.id = 55
    case.case_type = 'plan_change_request'
    case.status = wb.STATUS_PAYMENT_SETTLED  # already advanced
    case_query = mock.Mock()
    case_query.filter_by.return_value = case_query
    case_query.first.return_value = case
    event = {
        'type': 'checkout.session.completed',
        'data': {
            'object': {
                'id': 'cs_x',
                'metadata': {'kind': 'plan_change_invoice', 'case_id': '55'},
            },
        },
    }
    with _ctx(), mock.patch.object(
        wb.SupportCase, 'query', case_query,
    ), mock.patch.object(
        wb, 'mark_invoice_settled',
    ) as mark_mock:
        result = sg.handle_event(event)
    # No re-flip — mark_invoice_settled is not called when the case
    # has already advanced past `payment_requested`.
    mark_mock.assert_not_called()
    assert result['handled'] is False
    assert 'already' in (result.get('reason') or '').lower()


def test_handle_event_does_not_handle_non_invoice_checkout_events():
    """v84 plan-checkout sessions (kind='plan_checkout') must NOT
    be settled by this path — they're a separate purchase flow
    that doesn't tie to a plan-change case. The handler reports
    `handled=False` with a meaningful reason."""
    from app.services import stripe_gateway as sg
    event = {
        'type': 'checkout.session.completed',
        'id': 'evt_x',
        'data': {
            'object': {
                'id': 'cs_x',
                'metadata': {'kind': 'plan_checkout', 'plan_id': '2'},
            },
        },
    }
    result = sg.handle_event(event)
    assert result['handled'] is False


def test_payments_invoice_checkout_route_is_registered():
    """Source-inspection lock — the route function exists and is
    wired under `/payments/stripe/checkout/invoice`."""
    payments_path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'payments.py',
    )
    with open(payments_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    assert "@payments_bp.route('/payments/stripe/checkout/invoice'" in src
    assert 'def create_invoice_checkout(' in src
    # The route must NEVER trust a client-supplied amount — it
    # reads the amount from `find_pending_invoice(case)`.
    marker = 'def create_invoice_checkout():'
    start = src.find(marker)
    assert start >= 0
    lines = src[start:].splitlines()
    body_lines = [lines[0]]
    for line in lines[1:]:
        if line == '' or line.startswith(' ') or line.startswith('\t'):
            body_lines.append(line)
        else:
            break
    body = '\n'.join(body_lines)
    assert 'find_pending_invoice' in body
    # Security boundary: the route checks case.user_id == user.id.
    assert 'case.user_id' in body
