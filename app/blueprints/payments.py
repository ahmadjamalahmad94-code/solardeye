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
    create_checkout_session, create_invoice_checkout_session,
    handle_event, public_key_for_client,
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
    # v92e — Stripe replaces `{CHECKOUT_SESSION_ID}` inside the
    # success_url query string only if the placeholder is sent
    # UNENCODED. `url_for(..., session_id='{CHECKOUT_SESSION_ID}')`
    # URL-encodes the braces to `%7B...%7D` and Stripe leaves them
    # alone, so the success page received the literal placeholder
    # instead of a real session id. We now build the success URL
    # by appending the placeholder verbatim.
    try:
        base_success = url_for('payments.checkout_success', _external=True)
        success_url = base_success + '?session_id={CHECKOUT_SESSION_ID}'
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


# ── v86: subscriber-driven invoice checkout ─────────────────────────


@payments_bp.route('/payments/stripe/checkout/invoice', methods=['POST'])
def create_invoice_checkout():
    """v86: subscriber-initiated checkout for an outstanding
    plan-change invoice.

    The subscriber clicks "Pay with sandbox card" on their
    subscription page when their plan-change request is in
    `payment_requested` state. We:
      1. resolve the case by id + verify it belongs to the
         requesting user (security boundary),
      2. resolve the pending `INV-…` ledger row for the exact
         amount (server-side source of truth),
      3. create a Stripe Checkout Session tagged with
         `kind='plan_change_invoice'` + `case_id` metadata so the
         webhook handler can flip the case to `payment_settled`
         on completion.

    Never trusts client-supplied amounts. Never mutates the case
    or ledger here — settlement is the webhook's job.
    """
    user = _active_user()
    if user is None:
        if _wants_json():
            return jsonify({'ok': False, 'code': 'auth_required'}), 401
        return redirect(url_for('auth.login'))
    try:
        case_id = int(request.form.get('case_id') or 0)
    except (TypeError, ValueError):
        case_id = 0
    if not case_id:
        msg = 'معرّف طلب تغيير الخطة مطلوب.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'case_id_required', 'message': msg}), 400
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    from ..models import SupportCase
    from ..services.plan_change_workbench import (
        STATUS_PAYMENT_REQUESTED, find_pending_invoice,
    )
    case = SupportCase.query.filter_by(
        id=case_id, case_type='plan_change_request',
    ).first()
    if not case:
        msg = 'طلب تغيير الخطة غير موجود.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'case_not_found', 'message': msg}), 404
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    # Security: the subscriber can only checkout invoices on their
    # OWN cases. Cross-user attempts are silently rejected as
    # "not found".
    if case.user_id != user.id:
        msg = 'طلب تغيير الخطة غير موجود.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'case_not_found', 'message': msg}), 404
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    if (case.status or '').lower() != STATUS_PAYMENT_REQUESTED:
        msg = 'هذا الطلب ليس في حالة "دفع مطلوب".'
        if _wants_json():
            return jsonify({
                'ok': False, 'code': 'case_not_pending_payment',
                'message': msg, 'current_status': case.status,
            }), 409
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    invoice = find_pending_invoice(case)
    if not invoice or not invoice.amount or invoice.amount <= 0:
        msg = 'لا يوجد مبلغ مستحق على هذا الطلب.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'no_pending_invoice', 'message': msg}), 400
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    try:
        success_url = url_for(
            'payments.checkout_success',
            session_id='{CHECKOUT_SESSION_ID}', _external=True,
        )
    except Exception:  # pragma: no cover
        success_url = '/payments/stripe/success?session_id={CHECKOUT_SESSION_ID}'
    try:
        cancel_url = url_for('payments.checkout_cancel', _external=True)
    except Exception:  # pragma: no cover
        cancel_url = '/payments/stripe/cancel'
    try:
        result = create_invoice_checkout_session(
            case_id=case.id,
            amount_value=float(invoice.amount),
            currency=(invoice.currency or 'USD'),
            case_label=(case.subject or f'plan_change_invoice_{case.id}'),
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=(getattr(user, 'email', None) or None),
            tenant_id=getattr(user, 'tenant_id', None),
            user_id=user.id,
            # v90 — render Stripe's hosted Checkout page in the
            # subscriber's UI language. Falls back to 'auto' inside
            # the gateway if the value is unrecognized.
            locale=(session.get('ui_lang') or request.args.get('lang') or 'ar'),
        )
    except StripeNotReady as exc:
        logger.warning('stripe_not_ready_invoice: %s', exc)
        msg = 'خدمة الدفع غير مهيّأة بعد. يرجى التواصل مع الدعم.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'stripe_not_ready', 'message': msg}), 503
        flash(msg, 'danger')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    except ValueError as exc:
        logger.info('stripe_invoice_input_invalid: %s', exc)
        msg = 'تعذّر إنشاء جلسة الدفع لمدخلات غير صالحة.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'invalid_input', 'message': msg}), 400
        flash(msg, 'warning')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    except Exception as exc:  # pragma: no cover - Stripe SDK errors
        logger.warning(
            'stripe_invoice_checkout_failed err_class=%s',
            type(exc).__name__,
        )
        msg = 'تعذّر إنشاء جلسة الدفع. حاول مرة أخرى لاحقاً.'
        if _wants_json():
            return jsonify({'ok': False, 'code': 'stripe_error', 'message': msg}), 502
        flash(msg, 'danger')
        return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))
    if _wants_json():
        return jsonify({
            'ok': True,
            'data': {
                'session_id': result.get('id'),
                'url': result.get('url'),
                'provider': result.get('provider'),
                'mode': result.get('mode'),
                'invoice_reference': invoice.reference,
                'amount': float(invoice.amount),
                'currency': invoice.currency or 'USD',
            },
        })
    checkout_url = result.get('url')
    if checkout_url:
        return redirect(checkout_url, code=303)
    flash('تعذّر استلام رابط الدفع من Stripe.', 'danger')
    return redirect(url_for('main.account_subscription', lang=session.get('ui_lang') or 'ar'))


# ── Diagnostic: list Stripe sessions for plan-change debugging ──

@payments_bp.route('/payments/stripe/diagnostics/sessions', methods=['GET'])
def diagnostics_list_sessions():
    """v92j (v92k expanded) — admin/diagnostic endpoint.

    Lists the most recent Stripe Checkout Sessions visible with the
    current `STRIPE_SECRET_KEY`. By default no filter is applied
    so we can confirm:
      * The API key actually sees sessions at all (proves which
        Stripe account / mode we're talking to).
      * What metadata each session carries (so we can spot whether
        the `kind`/`case_id` tags were missing or different).

    Query params:
      * `kind=plan_change_invoice` — narrow to plan-change sessions
      * `all=1`                   — show every session even if no
                                    metadata.kind is set
    """
    user = _active_user()
    if user is None:
        return jsonify({'ok': False, 'code': 'auth_required'}), 401
    kind_filter = (request.args.get('kind') or '').strip()
    show_all = (request.args.get('all') or '').strip() == '1'
    try:
        from ..services.stripe_gateway import (
            _configure_stripe, StripeNotReady, PROVIDER_MODE, PROVIDER_NAME,
        )
        pkg = _configure_stripe()
    except StripeNotReady:
        return jsonify({'ok': False, 'code': 'stripe_not_ready'}), 503
    except Exception:
        logger.exception('diagnostics: configure failed')
        return jsonify({'ok': False, 'code': 'internal_error'}), 500
    try:
        listing = pkg.checkout.Session.list(limit=50)
    except Exception:
        logger.exception('diagnostics: list failed')
        return jsonify({'ok': False, 'code': 'list_failed'}), 500
    raw_sessions = (getattr(listing, 'data', None) or [])
    # v92m — ALWAYS deep-retrieve each session because Stripe's
    # `list()` response returns a shallow view that omits
    # `metadata` (and other extension fields) even when the
    # server stored them. The earlier `deep=1` opt-in was easy
    # to miss in the URL → users got the misleading empty-metadata
    # JSON. Now we always fetch the canonical record.
    rows = []
    raw_count = 0
    for sess in raw_sessions:
        raw_count += 1
        try:
            metadata = getattr(sess, 'metadata', None) or {}
            if hasattr(metadata, 'to_dict_recursive'):
                try:
                    metadata = metadata.to_dict_recursive()
                except Exception:
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            # Force a single retrieve per session.
            retrieved_metadata: dict = {}
            retrieve_error: str | None = None
            try:
                session_id = getattr(sess, 'id', None)
                if session_id:
                    full = pkg.checkout.Session.retrieve(session_id)
                    full_md = getattr(full, 'metadata', None) or {}
                    if hasattr(full_md, 'to_dict_recursive'):
                        try:
                            full_md = full_md.to_dict_recursive()
                        except Exception:
                            full_md = {}
                    if isinstance(full_md, dict):
                        retrieved_metadata = full_md
                        # Promote retrieved metadata into the
                        # shallow one so filters see the truth.
                        if not metadata and full_md:
                            metadata = full_md
            except Exception as r_exc:
                retrieve_error = type(r_exc).__name__
            sess_kind = str(metadata.get('kind') or '')
            # Apply optional kind filter (v92j default was hard-
            # filtered to plan_change_invoice — v92k makes the
            # filter explicit so we can SEE ALL sessions).
            if kind_filter and sess_kind != kind_filter:
                continue
            if not show_all and not kind_filter and not sess_kind:
                # Default view: hide truly-untagged sessions unless
                # the caller asked for `all=1`.
                continue
            row = {
                'session_id': getattr(sess, 'id', None),
                'payment_status': getattr(sess, 'payment_status', None),
                'status': getattr(sess, 'status', None),
                'mode': getattr(sess, 'mode', None),
                'amount_total': getattr(sess, 'amount_total', None),
                'currency': getattr(sess, 'currency', None),
                'created': getattr(sess, 'created', None),
                'customer_email': getattr(sess, 'customer_email', None),
                'metadata_from_list': metadata,
                'metadata_from_retrieve': retrieved_metadata,
                'retrieve_error': retrieve_error,
            }
            rows.append(row)
        except Exception:
            continue
    return jsonify({
        'ok': True,
        'data': {
            'sessions': rows,
            'count': len(rows),
            'raw_total_seen_on_this_key': raw_count,
            'provider': PROVIDER_NAME,
            'mode': PROVIDER_MODE,
            'kind_filter': kind_filter or None,
            'show_all': show_all,
            'hint': (
                'No sessions visible at all → the STRIPE_SECRET_KEY '
                'on this deployment doesn\'t match the account where '
                'the payment was made.'
                if raw_count == 0 else
                ('Sessions visible but none plan_change_invoice → the '
                 'payment used a non-plan-change checkout, OR metadata '
                 'never got attached.'
                 if not rows else
                 'Plan-change sessions visible — compare case_id values.'
                )
            ),
        },
    })


# ── Reconcile path — subscriber-triggered payment verification ───


@payments_bp.route('/payments/stripe/reconcile/<int:case_id>', methods=['POST'])
def reconcile_invoice(case_id: int):
    """v92h — subscriber-triggered reconciliation for cases where
    the payment happened but the case is still in
    `payment_requested`.

    v92i — wrapped in a defensive try/except so the route never
    returns a bare 500. Any unexpected exception is logged with
    full traceback via `logger.exception` and the subscriber gets
    a controlled flash + redirect to the subscription page.

    Security: only the case owner can reconcile their own case.
    """
    fallback_redirect = url_for(
        'main.account_subscription',
        lang=session.get('ui_lang') or 'ar',
    )

    def _flash_and_back(msg: str, level: str = 'warning'):
        if _wants_json():
            return jsonify({'ok': False, 'message': msg}), 400
        flash(msg, level)
        return redirect(fallback_redirect)

    try:
        user = _active_user()
        if user is None:
            if _wants_json():
                return jsonify({'ok': False, 'code': 'auth_required'}), 401
            return redirect(url_for('auth.login'))
        from ..models import SupportCase
        case = SupportCase.query.filter_by(
            id=case_id, case_type='plan_change_request',
        ).first()
        if not case or case.user_id != user.id:
            msg = 'طلب تغيير الخطة غير موجود.'
            if _wants_json():
                return jsonify({'ok': False, 'code': 'case_not_found', 'message': msg}), 404
            flash(msg, 'warning')
            return redirect(fallback_redirect)
        try:
            from ..services.stripe_gateway import (
                reconcile_paid_session_for_case,
            )
        except Exception:
            logger.exception(
                'stripe_reconcile: import failed (case_id=%s)', case_id,
            )
            return _flash_and_back('خدمة الدفع غير متاحة حالياً.')
        try:
            outcome = reconcile_paid_session_for_case(
                case_id, auto_apply=True, actor_user_id=user.id,
            )
        except Exception:
            logger.exception(
                'stripe_reconcile: gateway call raised (case_id=%s)', case_id,
            )
            return _flash_and_back(
                'تعذّر التحقّق من الدفعة الآن. الرجاء المحاولة مجدداً بعد قليل.'
            )
        logger.info(
            'stripe_reconcile case_id=%s reason=%s applied=%s case_status=%s',
            case_id,
            outcome.get('reason'),
            outcome.get('applied'),
            outcome.get('case_status'),
        )
        if _wants_json():
            ok = bool(
                outcome.get('applied')
                or outcome.get('settled')
                or outcome.get('reason') == 'already_applied'
            )
            return jsonify({'ok': ok, 'data': outcome})
        # Human-friendly flash mapping.
        reason = outcome.get('reason')
        if outcome.get('applied') or reason == 'reconciled_and_applied':
            flash('تم تأكيد دفعتك وتطبيق الخطة الجديدة على اشتراكك.', 'success')
        elif reason == 'already_applied':
            flash('الخطة الجديدة مُفعَّلة بالفعل على اشتراكك.', 'success')
        elif outcome.get('settled') or reason == 'reconciled_settled_pending_apply':
            flash('تم تأكيد دفعتك. الخطة الجديدة ستُطبَّق خلال لحظات.', 'success')
        elif reason == 'no_paid_session_found':
            flash(
                'لم نجد دفعة مكتملة لهذا الطلب على Stripe. '
                'لو سددت للتو وما يزال هذا التنبيه ظاهراً، انتظر دقيقة وحاول مجدداً.',
                'warning',
            )
        elif reason == 'stripe_not_ready':
            flash('خدمة الدفع غير مهيّأة. الرجاء التواصل مع الدعم.', 'warning')
        else:
            flash('تعذّر تأكيد الدفعة الآن. الرجاء المحاولة مجدداً بعد قليل.', 'warning')
        return redirect(fallback_redirect)
    except Exception:
        # Final safety net — ANY uncaught exception in the route
        # produces a controlled response. The full traceback is
        # logged so ops can diagnose without exposing internals.
        logger.exception(
            'stripe_reconcile: unhandled error in route (case_id=%s)',
            case_id,
        )
        return _flash_and_back(
            'حدث خطأ غير متوقّع أثناء التحقّق من الدفعة. الرجاء المحاولة مجدداً.'
        )


# ── Result pages — neutral, no DB mutation ─────────────────────────


@payments_bp.route('/payments/stripe/success', methods=['GET'])
def checkout_success():
    """Confirmation page reached when Stripe redirects the subscriber
    back after a successful test payment.

    v92f — redirect-fallback verification. The Stripe webhook is the
    authoritative path for marking the invoice settled + applying
    the plan change, but on Render Sandbox the webhook is often
    not wired (the Stripe dashboard's webhook endpoint isn't
    configured to point at the deployment). The result was that
    the subscriber paid successfully, saw a green check, returned
    to their account page and STILL saw the pending-invoice banner
    — because nothing on the backend knew the payment had
    happened.

    This route now actively verifies the session with Stripe and,
    if the payment is confirmed, settles the invoice + applies
    the plan change right here. Idempotent: if the webhook already
    fired (or the user re-opens this URL later), we ack without
    double-applying.
    """
    session_id = request.args.get('session_id', '').strip()
    actor = _active_user()
    actor_user_id = getattr(actor, 'id', None)
    verification = None
    if session_id and '{' not in session_id and '%7B' not in session_id:
        try:
            from ..services.stripe_gateway import (
                verify_and_settle_checkout_session,
            )
            verification = verify_and_settle_checkout_session(
                session_id, auto_apply=True,
                actor_user_id=actor_user_id,
            )
            logger.info(
                'stripe_redirect_verify session_id=%s reason=%s '
                'applied=%s case_status=%s',
                session_id[:32],
                (verification or {}).get('reason'),
                (verification or {}).get('applied'),
                (verification or {}).get('case_status'),
            )
        except Exception as exc:
            logger.warning(
                'stripe_redirect_verify_failed err_class=%s',
                type(exc).__name__,
            )
    return render_template(
        'payment_success.html',
        session_id=session_id,
        provider=PROVIDER_NAME,
        mode=PROVIDER_MODE,
        ui_lang=session.get('ui_lang') or 'ar',
        verification=verification,
        # v92g — `source=mobile` from the checkout URL flips the
        # template into mobile mode (back-to-app CTA, auto-redirect
        # to the `zynavolt://` scheme, no sidebar).
        source=(request.args.get('source') or '').strip().lower(),
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
        source=(request.args.get('source') or '').strip().lower(),
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
