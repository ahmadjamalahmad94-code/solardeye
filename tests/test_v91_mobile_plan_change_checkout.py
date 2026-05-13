"""v91 — mobile-native Stripe checkout-session endpoint tests.

The Flutter app calls `POST /api/mobile/account/plan-change/checkout`
after a `payment_required` outcome from `/confirm`. That endpoint:
  * Authenticates via bearer token (not session cookie).
  * Validates ownership of the SupportCase + payment_requested
    status + a positive pending invoice.
  * Builds a Stripe Checkout Session via
    `create_invoice_checkout_session` with `locale='ar'`.
  * Returns the hosted URL so the app can hand it to url_launcher.

These tests use source inspection to lock the route shape because
importing `mobile_api` transitively pulls `main.py → reportlab`
which is not installed in the dev environment.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def test_mobile_checkout_route_is_registered_in_mobile_api():
    """The mobile blueprint declares the new endpoint under
    /api/mobile/account/plan-change/checkout."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert "@mobile_core_api_bp.post('/account/plan-change/checkout')" in text
    assert 'def mobile_account_plan_change_checkout' in text


def test_mobile_checkout_route_uses_bearer_auth_not_session():
    """The route must call `_require_bearer_user()` so a bearer
    token from the mobile app is sufficient. Falling back to the
    web `_active_user()` (session-cookie only) would always return
    `auth_required` for app traffic."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # Locate the function body.
    start = text.index('def mobile_account_plan_change_checkout(')
    end = text.index('@mobile_core_api_bp.get(\'/onboarding\')', start)
    body = text[start:end]
    assert '_require_bearer_user()' in body
    assert '_active_user()' not in body


def test_mobile_checkout_route_validates_ownership_and_state():
    """Defensive cross-user lockout + state guard. A subscriber must
    only checkout their OWN case in `payment_requested` state with
    a positive pending invoice."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    start = text.index('def mobile_account_plan_change_checkout(')
    end = text.index('@mobile_core_api_bp.get(\'/onboarding\')', start)
    body = text[start:end]
    # Ownership check.
    assert 'case.user_id != user.id' in body
    # Status guard.
    assert 'STATUS_PAYMENT_REQUESTED' in body
    assert "code='case_not_pending_payment'" in body
    # Invoice presence guard.
    assert 'find_pending_invoice' in body
    assert "code='no_pending_invoice'" in body


def test_mobile_checkout_route_uses_invoice_gateway_with_arabic_locale():
    """The route must build the session through the shared
    `create_invoice_checkout_session` helper and pass `locale` so
    the Stripe-hosted page renders in the subscriber's language."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    start = text.index('def mobile_account_plan_change_checkout(')
    end = text.index('@mobile_core_api_bp.get(\'/onboarding\')', start)
    body = text[start:end]
    assert 'create_invoice_checkout_session' in body
    assert 'locale=' in body
    # The success/cancel URLs must be the existing payments routes
    # so the post-payment flow is consistent with web.
    assert "'payments.checkout_success'" in body
    assert "'payments.checkout_cancel'" in body


def test_mobile_checkout_route_returns_stable_payload_fields():
    """Success response must expose `url`, `session_id`, and the
    invoice context fields the Flutter client renders."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    start = text.index('def mobile_account_plan_change_checkout(')
    end = text.index('@mobile_core_api_bp.get(\'/onboarding\')', start)
    body = text[start:end]
    for field in (
        "'url'", "'session_id'", "'invoice_reference'",
        "'amount'", "'currency'",
    ):
        assert field in body, f'missing field {field!r} in checkout payload'


def test_mobile_dispatcher_allowlist_includes_checkout_endpoint():
    """The catch-all routes 404/405 helper must know about the new
    endpoint so a wrong-method request yields a structured 405."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert "'/account/plan-change/checkout':" in text


def test_stripe_gateway_supports_locale_parameter():
    """v92b — `create_invoice_checkout_session` accepts a `locale`
    kwarg and forwards it to Stripe. Stripe does NOT support Arabic
    in its Checkout locale allowlist, so the gateway maps:
      * 'en*'                → 'en'
      * any Stripe-supported → forwarded verbatim
      * Arabic or anything   → 'auto' (Stripe picks from headers)
    Passing 'ar' literally would make Stripe reject the session
    with `invalid_request_error`."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'services', 'stripe_gateway.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'locale: Optional[str] = None' in text
    assert "stripe_locale = 'auto'" in text
    assert "stripe_locale = 'en'" in text
    # v92b — Arabic must NOT be forwarded as a literal 'ar' anymore;
    # the supported-locale allowlist is the new gatekeeper.
    assert '_STRIPE_SUPPORTED_LOCALES' in text
    # Arabic is explicitly not in the allowlist.
    assert "'ar'" not in text.split('_STRIPE_SUPPORTED_LOCALES')[1].split('}')[0]


def test_json_error_helper_forwards_extra_kwargs():
    """`_json_error` must accept and forward arbitrary extra fields
    (e.g. `current_status=...`, `detail=...`) so the new endpoint
    can attach context without inventing a parallel response."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    start = text.index('def _json_error(')
    end = text.index('def _normalize_language(', start)
    body = text[start:end]
    assert '**extra' in body
    assert '**extra)' in body
