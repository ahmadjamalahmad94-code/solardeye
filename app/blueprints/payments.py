"""v84 — Stripe Sandbox payment routes.

Five tiny endpoints — admin status, checkout-session creation,
success/cancel result pages, and a signature-verified webhook
skeleton. The financial math is owned by the existing
`SubscriptionPlan` rows (server-side source of truth); this
blueprint never trusts pricing the client posts.

Endpoint map
────────────
  GET  /admin/payments/stripe/status      — admin-gated readiness page (HTML)
  GET  /admin/payments/stripe/status.json — same data, JSON
  POST /payments/stripe/checkout/session  — create test Checkout Session
  GET  /payments/stripe/success           — neutral confirmation page
  GET  /payments/stripe/cancel            — neutral cancel page
  POST /webhooks/stripe                   — signature-verified webhook
"""
from __future__ import annotations

import logging

from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)

from ..extensions import db  # noqa: F401 — imported for parity with other blueprints
from ..models import AppUser, SubscriptionPlan
from ..services.stripe_gateway import (
    PROVIDER_MODE, PROVIDER_NAME, StripeNotReady,
    WebhookNotConfigured, WebhookSignatureInvalid,
    create_checkout_session, handle_event, public_key_for_client,
    stripe_status, verify_and_parse_webhook,
)

logger = logging.getLogger(__name__)


payments_bp = Blueprint('payments', __name__)


# ── Helpers ─────────────────────────────────────────────────────────


def _active_user():
    """Resolve the logged-in user from the session — same pattern as
    `main._active_user`. Re-implemented locally to keep this
    blueprint self-contained and free of legacy `main.py` import."""
    uid = session.get('user_id')
    if not uid:
        return None
    return AppUser.query.get(uid)


def _is_admin(user) -> bool:
    if not user:
        return False
    return bool(getattr(user, 'is_admin', False))


def _admin_or_redirect():
    """Return None when the request is an admin; otherwise return a
    redirect/abort response the caller should yield. Keeps the
    admin-status route narrow without bringing in the heavier
    `_admin_guard` helper."""
    user = _active_user()
    if not _is_admin(user):
        return redirect(url_for('auth.login'))
    return None


def _wants_json() -> bool:
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
        or request.path.endswith('.json')
    )


# ── Admin readiness probe ───────────────────────────────────────────


@payments_bp.route('/admin/payments/stripe/status', methods=['GET'])
def admin_stripe_status():
    """Operator-facing readiness probe. Surfaces the
    `stripe_status()` booleans verbatim — no secret value ever
    appears here."""
    guard = _admin_or_redirect()
    if guard:
        return guard
    status = stripe_status()
    if _wants_json() or request.path.endswith('.json'):
        return jsonify(status.to_dict())
    return render_template(
        'admin_stripe_status.html',
        status=status.to_dict(),
        ui_lang=session.get('ui_lang') or 'ar',
    )


@payments_bp.route('/admin/payments/stripe/status.json', methods=['GET'])
def admin_stripe_status_json():
    guard = _admin_or_redirect()
    if guard:
        return guard
    return jsonify(stripe_status().to_dict())


# ── Checkout Session creation ───────────────────────────────────────


@payments_bp.route('/payments/stripe/checkout/session', methods=['POST'])
def create_checkout():
    """Create a Stripe Checkout Session in test mode.

    Authenticated users only. The client posts ``plan_id`` (a
    canonical `SubscriptionPlan.id`); the backend resolves the
    plan, reads `plan.price` + `plan.currency` as the financial
    source of truth, and never trusts a client-supplied amount.

    Returns JSON for API callers / a redirect for browser callers.
    Failures are payment-route-local — the rest of the app stays up.
    """
    user = _active_user()
    if user is None:
        if _wants_json():
            return jsonify({'ok': False, 'code': 'auth_required'}), 401
        return redirect(url_for('auth.login'))
    try:
        plan_id = int(request.form.get('plan_id') or 0)
    except (TypeError, ValueError):
        plan_id = 0
    plan = SubscriptionPlan.query.get(plan_id) if plan_id else None
    if not plan or not getattr(plan, 'is_active', True):
        msg = 'الخطة المطلوبة غير موجودة.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'plan_not_found', 'message': msg}), 400
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    price = float(getattr(plan, 'price', 0) or 0)
    if price <= 0:
        msg = 'لا يمكن إنشاء جلسة دفع لخطة مجانية.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'plan_not_paid', 'message': msg}), 400
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    currency = (getattr(plan, 'currency', None) or 'USD').strip().lower()
    # Stripe expects amounts in the smallest currency unit (cents
    # for USD). We multiply at the boundary; the resulting integer
    # is what Stripe will charge.
    unit_amount = int(round(price * 100))
    plan_label = (
        getattr(plan, 'name_en', None)
        or getattr(plan, 'name_ar', None)
        or getattr(plan, 'code', None)
        or f'plan-{plan.id}'
    )
    try:
        success_url = url_for(
            'payments.checkout_success',
            session_id='{CHECKOUT_SESSION_ID}',
            _external=True,
        )
    except Exception:  # pragma: no cover - falls back to relative
        success_url = '/payments/stripe/success?session_id={CHECKOUT_SESSION_ID}'
    try:
        cancel_url = url_for('payments.checkout_cancel', _external=True)
    except Exception:  # pragma: no cover
        cancel_url = '/payments/stripe/cancel'
    try:
        result = create_checkout_session(
            plan_label=plan_label,
            unit_amount_cents=unit_amount,
            currency=currency,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=(getattr(user, 'email', None) or None),
            metadata={
                'plan_id': plan.id,
                'user_id': user.id,
                'tenant_id': getattr(user, 'tenant_id', None) or 0,
            },
        )
    except StripeNotReady as exc:
        logger.warning('stripe_not_ready: %s', exc)
        msg = 'خدمة الدفع غير مهيّأة بعد. يرجى التواصل مع الدعم.'
        if _wants_json():
            return jsonify({
                'ok': False,
                'code': 'stripe_not_ready',
                'message': msg,
            }), 503
        flash(msg, 'danger')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    except ValueError as exc:
        # Input validation failure — surface a sanitized message.
        logger.info('stripe_checkout_input_invalid: %s', exc)
        msg = 'تعذّر إنشاء جلسة الدفع لمدخلات غير صالحة.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'invalid_input', 'message': msg}), 400
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    except Exception as exc:  # pragma: no cover - Stripe SDK errors
        # NEVER include the exception message in the user-facing
        # response — Stripe error messages can carry request ids
        # and request-shape hints we don't want public.
        logger.warning(
            'stripe_checkout_failed err_class=%s', type(exc).__name__,
        )
        msg = 'تعذّر إنشاء جلسة الدفع. حاول مرة أخرى لاحقاً.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'stripe_error', 'message': msg}), 502
        flash(msg, 'danger')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    # Browser → 303 redirect to the Stripe-hosted Checkout page.
    # API caller → JSON envelope.
    if _wants_json():
        return jsonify({
            'ok': True,
            'data': {
                'session_id': result.get('id'),
                'url': result.get('url'),
                'provider': result.get('provider'),
                'mode': result.get('mode'),
            },
        })
    checkout_url = result.get('url')
    if checkout_url:
        return redirect(checkout_url, code=303)
    flash('تعذّر استلام رابط الدفع من Stripe.', 'danger')
    return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))


# ── Result pages — neutral, no DB mutation ─────────────────────────


@payments_bp.route('/payments/stripe/success', methods=['GET'])
def checkout_success():
    """Neutral confirmation page reached when Stripe redirects the
    subscriber back after a successful test payment. v84 does NOT
    auto-activate the subscription — operators settle the request
    explicitly through the existing admin workflow once the webhook
    handler is wired to mutate state."""
    return render_template(
        'payment_success.html',
        session_id=request.args.get('session_id', '').strip(),
        provider=PROVIDER_NAME,
        mode=PROVIDER_MODE,
        ui_lang=session.get('ui_lang') or 'ar',
    )


@payments_bp.route('/payments/stripe/cancel', methods=['GET'])
def checkout_cancel():
    """Subscriber clicked Cancel on the Stripe Checkout page. No
    state mutation — they can re-attempt from the subscription
    page."""
    return render_template(
        'payment_cancel.html',
        provider=PROVIDER_NAME,
        mode=PROVIDER_MODE,
        ui_lang=session.get('ui_lang') or 'ar',
    )


# ── Webhook ─────────────────────────────────────────────────────────


@payments_bp.route('/webhooks/stripe', methods=['POST'])
def stripe_webhook():
    """Stripe POSTs signed events here. v84 verifies the signature
    against `STRIPE_WEBHOOK_SECRET` and acknowledges receipt —
    state mutation is a deliberate future step.

    Failure modes:
      * No webhook secret configured → 503 (only the webhook route
        fails, not the rest of the app).
      * Signature mismatch / bad payload → 400.
      * Internal handler error → 500 (logged with class name only).
    """
    payload = request.get_data() or b''
    signature = request.headers.get('Stripe-Signature', '')
    try:
        event = verify_and_parse_webhook(payload, signature)
    except WebhookNotConfigured as exc:
        logger.warning('stripe_webhook_not_configured: %s', exc)
        return jsonify({
            'ok': False,
            'code': 'webhook_not_configured',
            'message': 'Stripe webhook is not configured on this deployment.',
        }), 503
    except WebhookSignatureInvalid:
        # The verify helper already logged the error class — no
        # need to repeat. Return a clean 400 without echoing the
        # signature header so an attacker probing the endpoint
        # learns nothing useful.
        return jsonify({
            'ok': False,
            'code': 'signature_invalid',
        }), 400
    try:
        result = handle_event(event)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            'stripe_webhook_handler_failed err_class=%s',
            type(exc).__name__,
        )
        return jsonify({'ok': False, 'code': 'handler_error'}), 500
    return jsonify({'ok': True, 'data': result})
