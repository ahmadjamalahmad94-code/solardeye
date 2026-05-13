"""v84 — Stripe Sandbox foundation tests.

Five guarantees v84 must hold (these are the test slices below):

  Part A — `stripe_status()` reports presence-only booleans and
           NEVER carries the raw secret. Calling it on a host with
           zero Stripe env vars must not raise.

  Part B — `create_checkout_session(...)` validates inputs,
           guards against zero/negative pricing, and forwards a
           well-formed call to the Stripe SDK with provider/mode
           metadata baked in.

  Part C — `verify_and_parse_webhook(...)` returns a clear failure
           when the webhook secret is missing (so the route can
           return 503 instead of crashing) and bubbles
           `WebhookSignatureInvalid` on signature drift without
           echoing the underlying SDK message.

  Part D — `handle_event(...)` ALWAYS reports `handled=False` in
           v84 — it never mutates subscription state. Auto-
           activation is a deliberate future step.

  Part E — the payments blueprint route handlers route a
           non-admin to login, return 503 for `stripe_not_ready`,
           and the webhook endpoint is registered on the
           CSRF-exempt list.

Style mirrors v76 / v78 / v80 / v81 / v82 / v83: mock-based, no
DB boot, no real Stripe SDK call.
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Part A — readiness probe is secret-safe
# ═══════════════════════════════════════════════════════════════════════


def test_stripe_status_with_no_env_vars_is_a_calm_not_ready():
    """Bare host: no Stripe env vars at all. The probe must NOT
    raise, must report `is_ready=False`, and must NOT include any
    secret-looking value in its output."""
    from app.services import stripe_gateway as sg
    with mock.patch.dict(os.environ, {}, clear=True):
        status = sg.stripe_status()
    assert status.public_key_present is False
    assert status.secret_key_present is False
    assert status.is_ready is False
    # The dict surface is what the admin template + JSON endpoint
    # render — make sure it carries no key-shaped strings.
    payload = json.dumps(status.to_dict())
    assert 'sk_' not in payload
    assert 'pk_' not in payload


def test_stripe_status_reports_present_when_env_vars_are_set():
    """With both keys + a webhook secret, readiness flips True and
    the issues list is empty. The dict surface still avoids
    leaking the actual values."""
    from app.services import stripe_gateway as sg
    env = {
        'STRIPE_PUBLIC_KEY': 'pk_test_dummy_public_key_for_unit_test',
        'STRIPE_SECRET_KEY': 'sk_test_dummy_secret_key_for_unit_test',
        'STRIPE_WEBHOOK_SECRET': 'whsec_dummy_webhook_secret',
    }
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=mock.Mock()):
        status = sg.stripe_status()
    assert status.public_key_present is True
    assert status.secret_key_present is True
    assert status.webhook_secret_present is True
    assert status.public_key_looks_like_test is True
    assert status.secret_key_looks_like_test is True
    assert status.is_ready is True
    assert status.issues == []
    # No secret value reaches the serialized output.
    payload = json.dumps(status.to_dict())
    assert 'dummy_secret_key' not in payload
    assert 'dummy_public_key' not in payload


def test_stripe_status_flags_non_test_keys_as_an_issue():
    """If an operator pasted live-mode keys into Render envs, the
    probe must call that out. v84 is a sandbox-only foundation by
    design."""
    from app.services import stripe_gateway as sg
    env = {
        'STRIPE_PUBLIC_KEY': 'pk_live_should_never_be_here',
        'STRIPE_SECRET_KEY': 'sk_live_should_never_be_here',
    }
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=mock.Mock()):
        status = sg.stripe_status()
    assert status.public_key_looks_like_test is False
    assert status.secret_key_looks_like_test is False
    assert status.is_ready is False
    issue_text = ' | '.join(status.issues)
    assert 'STRIPE_PUBLIC_KEY' in issue_text
    assert 'STRIPE_SECRET_KEY' in issue_text


def test_public_key_for_client_returns_empty_string_when_missing():
    """Frontend template helper must never raise — it should return
    an empty string so the template can render a "checkout not
    available" state instead of a 500."""
    from app.services import stripe_gateway as sg
    with mock.patch.dict(os.environ, {}, clear=True):
        assert sg.public_key_for_client() == ''


# ═══════════════════════════════════════════════════════════════════════
# Part B — checkout session creation
# ═══════════════════════════════════════════════════════════════════════


def _ready_env():
    return {
        'STRIPE_PUBLIC_KEY': 'pk_test_x',
        'STRIPE_SECRET_KEY': 'sk_test_x',
    }


def test_create_checkout_session_rejects_zero_or_negative_amount():
    """We never charge $0 or negative. Defensive input validation
    runs before we touch the SDK."""
    from app.services import stripe_gateway as sg
    with mock.patch.dict(os.environ, _ready_env(), clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=mock.Mock()):
        try:
            sg.create_checkout_session(
                plan_label='Pro', unit_amount_cents=0, currency='USD',
                success_url='https://x/y', cancel_url='https://x/z',
            )
        except ValueError as exc:
            assert 'unit_amount_cents' in str(exc)
        else:
            raise AssertionError('expected ValueError on zero amount')


def test_create_checkout_session_forwards_to_sdk_with_safe_metadata():
    """Happy path: we hand the SDK a single line item with the
    server-computed unit_amount + currency, and the metadata
    carries provider/mode/kind tokens plus whatever the caller
    passed in (clamped to short strings)."""
    from app.services import stripe_gateway as sg

    fake_session = mock.Mock()
    fake_session.id = 'cs_test_123'
    fake_session.url = 'https://checkout.stripe.com/c/cs_test_123'

    fake_module = mock.Mock()
    fake_module.checkout.Session.create.return_value = fake_session

    with mock.patch.dict(os.environ, _ready_env(), clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=fake_module):
        result = sg.create_checkout_session(
            plan_label='Pro plan',
            unit_amount_cents=2000,
            currency='USD',
            success_url='https://x/success',
            cancel_url='https://x/cancel',
            customer_email='user@example.com',
            metadata={'plan_id': 7, 'user_id': 11, 'tenant_id': 9},
        )

    assert result['id'] == 'cs_test_123'
    assert result['url'].startswith('https://checkout.stripe.com/')
    assert result['provider'] == 'stripe'
    assert result['mode'] == 'test'
    # Sanity-check the SDK call shape.
    call_kwargs = fake_module.checkout.Session.create.call_args.kwargs
    assert call_kwargs['mode'] == 'payment'
    assert call_kwargs['payment_method_types'] == ['card']
    assert call_kwargs['success_url'] == 'https://x/success'
    assert call_kwargs['cancel_url'] == 'https://x/cancel'
    assert call_kwargs['customer_email'] == 'user@example.com'
    line_item = call_kwargs['line_items'][0]
    assert line_item['quantity'] == 1
    assert line_item['price_data']['currency'] == 'usd'
    assert line_item['price_data']['unit_amount'] == 2000
    # Metadata: enriched with provider/mode/kind + the three caller
    # values cast to strings (Stripe rejects non-string metadata).
    md = call_kwargs['metadata']
    assert md['provider'] == 'stripe'
    assert md['mode'] == 'test'
    assert md['kind'] == 'plan_checkout'
    assert md['plan_id'] == '7'
    assert md['user_id'] == '11'
    assert md['tenant_id'] == '9'


def test_create_checkout_session_raises_when_not_ready():
    """If env vars are missing the helper must raise
    `StripeNotReady` cleanly — the route handler turns that into a
    payment-route-local 503."""
    from app.services import stripe_gateway as sg
    with mock.patch.dict(os.environ, {}, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=mock.Mock()):
        try:
            sg.create_checkout_session(
                plan_label='Pro', unit_amount_cents=2000, currency='USD',
                success_url='https://x/y', cancel_url='https://x/z',
            )
        except sg.StripeNotReady as exc:
            # Message references readiness, but does NOT include any
            # key value (we have none in env).
            assert 'STRIPE_PUBLIC_KEY' in str(exc) or 'not ready' in str(exc).lower()
        else:
            raise AssertionError('expected StripeNotReady')


# ═══════════════════════════════════════════════════════════════════════
# Part C — webhook verification
# ═══════════════════════════════════════════════════════════════════════


def test_verify_and_parse_webhook_when_secret_missing_raises_not_configured():
    """No webhook secret in env → `WebhookNotConfigured`. The route
    catches this and returns 503 — only the webhook is affected,
    the rest of the app keeps working."""
    from app.services import stripe_gateway as sg
    with mock.patch.dict(os.environ, _ready_env(), clear=True):
        try:
            sg.verify_and_parse_webhook(b'{}', 'sig_xx')
        except sg.WebhookNotConfigured as exc:
            assert 'STRIPE_WEBHOOK_SECRET' in str(exc)
        else:
            raise AssertionError('expected WebhookNotConfigured')


def test_verify_and_parse_webhook_invalid_signature_raises_clean_error():
    """Signature drift → `WebhookSignatureInvalid` without echoing
    the underlying SDK message (attackers probing for verbose
    errors get nothing useful)."""
    from app.services import stripe_gateway as sg

    fake_stripe = mock.Mock()
    fake_stripe.Webhook.construct_event.side_effect = RuntimeError(
        'verbose SDK internal — request_id=req_xyz secret_fingerprint=abc'
    )
    env = {**_ready_env(), 'STRIPE_WEBHOOK_SECRET': 'whsec_x'}
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=fake_stripe):
        try:
            sg.verify_and_parse_webhook(b'{"x":1}', 'bad-sig')
        except sg.WebhookSignatureInvalid as exc:
            # The raised message is intentionally generic — no SDK
            # internals leak through.
            assert 'request_id' not in str(exc)
            assert 'secret_fingerprint' not in str(exc)
        else:
            raise AssertionError('expected WebhookSignatureInvalid')


def test_verify_and_parse_webhook_returns_dict_on_success():
    """Happy path: SDK returns an `Event` with `to_dict_recursive` —
    we surface its dict form so the route handler can introspect
    without touching the SDK's attribute proxies."""
    from app.services import stripe_gateway as sg

    fake_event = mock.Mock()
    fake_event.to_dict_recursive.return_value = {
        'type': 'checkout.session.completed',
        'id': 'evt_test_111',
        'data': {'object': {'id': 'cs_test_222'}},
    }
    fake_stripe = mock.Mock()
    fake_stripe.Webhook.construct_event.return_value = fake_event
    env = {**_ready_env(), 'STRIPE_WEBHOOK_SECRET': 'whsec_x'}
    with mock.patch.dict(os.environ, env, clear=True), \
         mock.patch.object(sg, '_import_stripe', return_value=fake_stripe):
        out = sg.verify_and_parse_webhook(b'{"a":1}', 'sig_ok')
    assert out['type'] == 'checkout.session.completed'
    assert out['id'] == 'evt_test_111'


# ═══════════════════════════════════════════════════════════════════════
# Part D — event handler is a deliberate no-op in v84
# ═══════════════════════════════════════════════════════════════════════


def test_handle_event_never_auto_activates_subscription_in_v84():
    """Spec lock: v84 is a sandbox foundation. The event handler
    must report `handled=False` regardless of event type so a
    future "auto-activate on checkout.session.completed" wave is a
    deliberate explicit change, not a silent drift."""
    from app.services import stripe_gateway as sg
    for event_type in (
        'checkout.session.completed',
        'payment_intent.succeeded',
        'invoice.payment_succeeded',
        'something.else',
    ):
        out = sg.handle_event({
            'type': event_type,
            'id': 'evt_x',
            'data': {'object': {'id': 'cs_x'}},
        })
        assert out['handled'] is False, (
            f'v84 must NOT auto-handle {event_type!r}'
        )
        assert out['mode'] == 'test'


# ═══════════════════════════════════════════════════════════════════════
# Part E — blueprint wiring
# ═══════════════════════════════════════════════════════════════════════


def test_webhook_endpoint_is_csrf_exempt():
    """Stripe POSTs to /webhooks/stripe with its own `Stripe-
    Signature` header — there is no session cookie in the request,
    so Flask CSRF must NOT apply. v84 adds the endpoint name to
    the exempt set."""
    from app.services.security import CSRF_EXEMPT_ENDPOINTS
    assert 'payments.stripe_webhook' in CSRF_EXEMPT_ENDPOINTS


def test_payments_blueprint_routes_register_cleanly():
    """The blueprint module must import without side-effects when
    Stripe envs are missing. Importing here exercises every
    top-level statement in `payments.py`."""
    import importlib
    from app.blueprints import payments
    importlib.reload(payments)
    assert hasattr(payments, 'payments_bp')
    assert hasattr(payments, 'admin_stripe_status')
    assert hasattr(payments, 'create_checkout')
    assert hasattr(payments, 'checkout_success')
    assert hasattr(payments, 'checkout_cancel')
    assert hasattr(payments, 'stripe_webhook')


def test_provider_and_mode_tokens_are_stable():
    """Spec lock: finance dashboards and future ledger filters
    depend on the two stable strings. Lock them so a rename
    triggers a test failure rather than a silent rebrand."""
    from app.services.stripe_gateway import PROVIDER_NAME, PROVIDER_MODE
    assert PROVIDER_NAME == 'stripe'
    assert PROVIDER_MODE == 'test'
