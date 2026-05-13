"""v84 — Stripe Sandbox foundation.

A minimal, defensive Stripe wrapper. Every callable in this module
holds three invariants:

1. **No secret ever leaks.** The status report exposes "present" /
   "missing" booleans only. The secret key itself never appears in
   log lines, template variables, exception messages, or JSON
   responses.
2. **Missing env vars never crash the rest of the app.** Importing
   this module, calling `stripe_status()`, or hitting unrelated
   pages must remain safe when Stripe envs are absent. Failures are
   payment-route-local.
3. **Test mode only.** The wrapper hard-codes `mode='test'` and
   refuses to load live credentials. v84 is a sandbox foundation —
   live-mode wiring is a deliberate future step.

Env vars read (Render Environment Variables):
  * `STRIPE_PUBLIC_KEY`       — publishable test key (`pk_test_...`)
  * `STRIPE_SECRET_KEY`       — secret test key (`sk_test_...`)
  * `STRIPE_WEBHOOK_SECRET`   — optional, required for webhook verification

The module performs zero network calls until a real
`create_checkout_session(...)` or webhook event is processed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Stable provider tokens — used everywhere we persist payment
# metadata so finance can filter by provider without inspecting raw
# Stripe object structures.
PROVIDER_NAME = 'stripe'
PROVIDER_MODE = 'test'  # v84 is sandbox-only by design

# Prefixes Stripe uses to distinguish test vs live keys. We reject
# anything that doesn't look like a test key — defence in depth even
# if an operator accidentally pasted a live key into Render env vars.
_TEST_PUBLIC_PREFIXES = ('pk_test_', 'pk_sandbox_')
_TEST_SECRET_PREFIXES = ('sk_test_', 'sk_sandbox_', 'rk_test_')


@dataclass(frozen=True)
class StripeStatus:
    """Public, secret-safe readiness report. Surfaced verbatim by
    the admin status page and the JSON readiness endpoint.

    Every field is intentionally a boolean or a low-cardinality
    string — there's no path through this dataclass that leaks the
    secret value.
    """

    stripe_installed: bool
    public_key_present: bool
    secret_key_present: bool
    webhook_secret_present: bool
    mode: str
    public_key_looks_like_test: bool
    secret_key_looks_like_test: bool
    issues: list[str]

    @property
    def is_ready(self) -> bool:
        """True when the wrapper has everything it needs to create
        a Checkout Session in test mode. The webhook secret is NOT
        required for Checkout creation — only for receiving signed
        webhook events."""
        return (
            self.stripe_installed
            and self.public_key_present
            and self.secret_key_present
            and self.public_key_looks_like_test
            and self.secret_key_looks_like_test
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'provider': PROVIDER_NAME,
            'mode': self.mode,
            'stripe_installed': self.stripe_installed,
            'public_key_present': self.public_key_present,
            'secret_key_present': self.secret_key_present,
            'webhook_secret_present': self.webhook_secret_present,
            'public_key_looks_like_test': self.public_key_looks_like_test,
            'secret_key_looks_like_test': self.secret_key_looks_like_test,
            'is_ready': self.is_ready,
            'issues': list(self.issues),
        }


# ── Internal readers (NEVER surface the raw secret) ─────────────────


def _read_env(name: str) -> str:
    raw = os.environ.get(name)
    return (raw or '').strip()


def _public_key() -> str:
    return _read_env('STRIPE_PUBLIC_KEY')


def _secret_key() -> str:
    return _read_env('STRIPE_SECRET_KEY')


def _webhook_secret() -> str:
    return _read_env('STRIPE_WEBHOOK_SECRET')


def _import_stripe():
    """Return the `stripe` package or `None`. Never raises — a
    missing dependency must be a calm "stripe_installed=False" in
    the status report, not a 500 on the admin page."""
    try:
        import stripe  # type: ignore[import-not-found]
        return stripe
    except Exception:  # pragma: no cover - defensive
        return None


# ── Public surface ─────────────────────────────────────────────────


def stripe_status() -> StripeStatus:
    """Readiness probe used by the admin status page and a future
    JSON readiness endpoint. Pure computation; no network calls."""
    pkg = _import_stripe()
    pub = _public_key()
    sec = _secret_key()
    whk = _webhook_secret()
    issues: list[str] = []
    if pkg is None:
        issues.append('stripe package is not importable')
    if not pub:
        issues.append('STRIPE_PUBLIC_KEY env var is missing')
    if not sec:
        issues.append('STRIPE_SECRET_KEY env var is missing')
    public_looks_test = bool(
        pub and pub.startswith(_TEST_PUBLIC_PREFIXES)
    )
    secret_looks_test = bool(
        sec and sec.startswith(_TEST_SECRET_PREFIXES)
    )
    if pub and not public_looks_test:
        issues.append(
            'STRIPE_PUBLIC_KEY does not look like a test/sandbox key '
            '(expected pk_test_… or pk_sandbox_…)'
        )
    if sec and not secret_looks_test:
        issues.append(
            'STRIPE_SECRET_KEY does not look like a test/sandbox key '
            '(expected sk_test_… or sk_sandbox_…)'
        )
    return StripeStatus(
        stripe_installed=pkg is not None,
        public_key_present=bool(pub),
        secret_key_present=bool(sec),
        webhook_secret_present=bool(whk),
        mode=PROVIDER_MODE,
        public_key_looks_like_test=public_looks_test,
        secret_key_looks_like_test=secret_looks_test,
        issues=issues,
    )


def public_key_for_client() -> str:
    """Safe to expose on the front-end — Stripe publishable keys are
    public by design. Returns `''` when not configured so the
    template can branch cleanly without crashing."""
    return _public_key()


class StripeNotReady(Exception):
    """Raised by `create_checkout_session` when the wrapper isn't
    fully configured. The route handler catches this and returns a
    payment-local 503 — unrelated pages keep working."""


# v92d — permissive email shape validation. Stripe rejects the
# entire session create call if `customer_email` is malformed, so
# we pre-filter here. The pattern is loose on purpose (no full
# RFC 5322): catches the common typo cases (missing TLD, spaces,
# missing `@`) without rejecting valid-but-unusual addresses.
_EMAIL_SHAPE_RE = __import__('re').compile(
    r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$'
)


def _looks_like_email(value: str) -> bool:
    """Return True if `value` resembles a real email address.
    Used to gate `customer_email` before it reaches Stripe."""
    if not value:
        return False
    return bool(_EMAIL_SHAPE_RE.match(value))


def _configure_stripe():
    """Lazily set `stripe.api_key` from env. Returns the live module
    handle. Raises `StripeNotReady` when prerequisites are missing.
    Never logs the key."""
    status = stripe_status()
    if not status.is_ready:
        raise StripeNotReady(
            'Stripe is not ready: ' + '; '.join(status.issues)
            if status.issues else 'Stripe is not ready'
        )
    pkg = _import_stripe()
    if pkg is None:  # pragma: no cover — guarded by is_ready
        raise StripeNotReady('stripe package not importable')
    pkg.api_key = _secret_key()
    return pkg


def create_checkout_session(
    *,
    plan_label: str,
    unit_amount_cents: int,
    currency: str,
    success_url: str,
    cancel_url: str,
    customer_email: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session in test mode.

    The route handler resolves the canonical plan from
    `SubscriptionPlan.query.get(plan_id)` and passes the
    server-side `unit_amount_cents` + `currency` here — we never
    trust front-end pricing.

    Returns a tiny dict (`id`, `url`, plus the `provider`/`mode`
    tokens) — callers don't need the full Stripe object and we keep
    the contract narrow so secret-side fields can never leak
    through a careless template render.

    `metadata` is enriched with `provider='stripe'` + `mode='test'`
    + `kind='plan_checkout'` so finance can filter on these tokens
    if/when the webhook handler starts mutating records.
    """
    if unit_amount_cents <= 0:
        raise ValueError('unit_amount_cents must be a positive integer')
    if not currency or len(currency) > 8:
        raise ValueError('currency is required and must be short')
    if not plan_label:
        raise ValueError('plan_label is required')
    if not success_url or not cancel_url:
        raise ValueError('success_url + cancel_url are required')
    pkg = _configure_stripe()
    safe_metadata = {
        'provider': PROVIDER_NAME,
        'mode': PROVIDER_MODE,
        'kind': 'plan_checkout',
    }
    if metadata:
        # Coerce every value to a short string. Stripe metadata is
        # capped at 500 chars per value and 50 keys; we apply a
        # gentle clamp so an oversized incoming value never throws.
        for k, v in metadata.items():
            key = str(k)[:40]
            if not key or key in safe_metadata:
                continue
            safe_metadata[key] = str(v)[:500]
    try:
        session = pkg.checkout.Session.create(
            mode='payment',
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': currency.lower(),
                    'product_data': {'name': plan_label[:120]},
                    'unit_amount': int(unit_amount_cents),
                },
                'quantity': 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email or None,
            metadata=safe_metadata,
        )
    except Exception as exc:
        # Log a generic line — the underlying Stripe error may carry
        # request-id / fingerprint material that's safe-ish but we
        # keep it terse to be defensive.
        logger.warning(
            'stripe_checkout_session_create_failed err_class=%s',
            type(exc).__name__,
        )
        raise
    return {
        'id': getattr(session, 'id', None),
        'url': getattr(session, 'url', None),
        'provider': PROVIDER_NAME,
        'mode': PROVIDER_MODE,
    }


# ── Webhook handling ───────────────────────────────────────────────


class WebhookNotConfigured(Exception):
    """Raised when `STRIPE_WEBHOOK_SECRET` is missing. The webhook
    route turns this into a 503 — only the webhook fails, the rest
    of the app stays up."""


class WebhookSignatureInvalid(Exception):
    """Raised when Stripe's signature header doesn't match the
    configured secret. The webhook route turns this into 400."""


def verify_and_parse_webhook(payload: bytes, signature_header: str) -> dict[str, Any]:
    """Verify Stripe's `Stripe-Signature` header against
    `STRIPE_WEBHOOK_SECRET` and return the parsed event as a dict.

    `payload` must be the **raw** request bytes — Flask gives this
    via `request.get_data()` (NOT `request.json`, which would
    re-serialize and break the signature).
    """
    secret = _webhook_secret()
    if not secret:
        raise WebhookNotConfigured(
            'STRIPE_WEBHOOK_SECRET env var is missing — '
            'webhook signature cannot be verified'
        )
    pkg = _import_stripe()
    if pkg is None:
        raise WebhookNotConfigured('stripe package not importable')
    try:
        event = pkg.Webhook.construct_event(
            payload=payload,
            sig_header=signature_header or '',
            secret=secret,
        )
    except Exception as exc:
        # Includes both stripe.error.SignatureVerificationError and
        # plain ValueError on bad payload. We swallow the underlying
        # message — never let signature drift become a verbose log
        # line that an attacker can grep for.
        logger.warning(
            'stripe_webhook_verify_failed err_class=%s',
            type(exc).__name__,
        )
        raise WebhookSignatureInvalid('webhook signature failed verification') from exc
    return _event_to_safe_dict(event)


def _event_to_safe_dict(event) -> dict[str, Any]:
    """Convert a Stripe `Event` object into a plain dict the route
    handler can introspect without depending on the SDK's lazy
    attribute proxies. Drops nothing — the route handler decides
    what to log."""
    if hasattr(event, 'to_dict_recursive'):
        try:
            return event.to_dict_recursive()
        except Exception:  # pragma: no cover
            pass
    if hasattr(event, 'to_dict'):
        try:
            return dict(event.to_dict())
        except Exception:  # pragma: no cover
            pass
    return dict(event) if isinstance(event, dict) else {}


def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    """v84 sandbox-foundation event handler, extended in v86 to
    settle plan-change invoices.

    What still does NOT happen here (deliberate, locked by tests):
      * No automatic subscription activation.
      * No `apply_request(...)` call — plan apply remains a
        separate explicit admin step.

    What v86 adds: when a `checkout.session.completed` event
    arrives with our `kind='plan_change_invoice'` metadata, we
    call `plan_change_workbench.mark_invoice_settled(...)` on the
    referenced case. This flips the case status from
    `payment_requested` → `payment_settled` so the admin queue
    surfaces the receipt; the operator (or a future
    `subscription.applied` automation) clicks Apply afterwards.
    """
    event_type = str(event.get('type') or 'unknown')
    event_id = str(event.get('id') or '')
    obj = (event.get('data') or {}).get('object') or {}
    obj_id = str(obj.get('id') or '')
    logger.info(
        'stripe_webhook_received type=%s event_id=%s object_id=%s mode=%s',
        event_type, event_id, obj_id, PROVIDER_MODE,
    )
    result = {
        'received': True,
        'event_type': event_type,
        'event_id': event_id,
        'object_id': obj_id,
        'mode': PROVIDER_MODE,
        'handled': False,
        'reason': 'event_type_not_handled',
    }
    # v86: settle plan-change invoices on completed checkout.
    if event_type == 'checkout.session.completed':
        metadata = (obj.get('metadata') or {}) if isinstance(obj, dict) else {}
        kind = str(metadata.get('kind') or '').strip()
        if kind == 'plan_change_invoice':
            case_id_raw = metadata.get('case_id')
            try:
                case_id = int(case_id_raw) if case_id_raw is not None else None
            except (TypeError, ValueError):
                case_id = None
            if case_id:
                settle_outcome = _settle_plan_change_invoice(case_id)
                result.update(settle_outcome)
                result['handled'] = settle_outcome.get('settled', False)
                if result['handled']:
                    result['reason'] = 'plan_change_invoice_settled'
                else:
                    result['reason'] = settle_outcome.get(
                        'skip_reason', 'settle_failed',
                    )
    return result


def _settle_plan_change_invoice(case_id: int, *, auto_apply: bool = False, actor_user_id: int | None = None, note: str | None = None) -> dict[str, Any]:
    """Internal helper: look up the plan-change case + flip it to
    `payment_settled` via the workbench. Never raises; returns a
    small dict the webhook/success-fallback handler folds into its
    response.

    v92f — `auto_apply=True` chains the workbench's `apply_request`
    right after settlement so the plan switch is actually applied
    on the subscriber's account. This is what the
    `checkout_success` redirect-fallback path uses (since the
    Stripe webhook may not be wired on Render Sandbox); the
    webhook path keeps `auto_apply=False` and leaves the apply
    step to the admin workflow, matching v86 behavior.
    """
    try:
        from ..models import SupportCase
        from . import plan_change_workbench as wb
        case = SupportCase.query.filter_by(
            id=case_id, case_type='plan_change_request',
        ).first()
        if case is None:
            return {'settled': False, 'skip_reason': 'case_not_found'}
        current_status = (case.status or '').lower()
        # The case may already be in `payment_settled` or `resolved`
        # (idempotency — webhook + redirect-fallback may both fire).
        if current_status == wb.STATUS_RESOLVED:
            return {
                'settled': False, 'applied': False,
                'skip_reason': 'case_already_resolved',
                'case_id': case.id, 'case_status': case.status,
            }
        settled_this_call = False
        if current_status == wb.STATUS_PAYMENT_REQUESTED:
            wb.mark_invoice_settled(
                case, actor_user_id=actor_user_id,
                note=note or 'Settled by Stripe sandbox',
                commit=True,
            )
            settled_this_call = True
            # v92g — admin fanout: "حد خلص دفع". Defensive try so a
            # notification failure can't undo the settlement.
            try:
                from .support_ops import (
                    notify_admins_of_plan_change_payment,
                )
                from .plan_change_workbench import find_pending_invoice
                pending = find_pending_invoice(case)
                # Pending may already be flipped to LEDGER_CATEGORY_APPLIED
                # by mark_invoice_settled — fall back to the case for amount.
                amount = float(getattr(pending, 'amount', 0) or 0) if pending else None
                currency = (getattr(pending, 'currency', None) or 'USD') if pending else 'USD'
                notify_admins_of_plan_change_payment(
                    case, amount=amount, currency=currency, commit=True,
                )
            except Exception as notif_exc:
                logger.warning(
                    'admin_payment_notif_failed err_class=%s case_id=%s',
                    type(notif_exc).__name__, case.id,
                )
        elif current_status != wb.STATUS_PAYMENT_SETTLED:
            # Some other state (open / under_review / closed /
            # cancelled). The webhook ack must NOT silently flip
            # those — return a non-settled outcome so the v86
            # idempotency contract is preserved.
            return {
                'settled': False, 'applied': False,
                'skip_reason': f'case_already_in_{case.status}',
                'case_id': case.id, 'case_status': case.status,
            }
        elif not auto_apply:
            # `payment_settled` reached but caller is the webhook
            # (auto_apply=False). The webhook contract from v86 is
            # to ack idempotently — do NOT chain apply, do NOT
            # re-settle, just report the no-op so `result['reason']`
            # carries an "already" string.
            return {
                'settled': False, 'applied': False,
                'skip_reason': 'case_already_settled',
                'case_id': case.id, 'case_status': case.status,
            }
        # If asked to chain the apply step, do it now. `apply_request`
        # is idempotent at the case level — we only invoke it when
        # the case sits at `payment_settled` (either set just above
        # or already there from a prior settle).
        applied = False
        ledger_entry_id = None
        if auto_apply:
            current_status = (case.status or '').lower()
            if current_status == wb.STATUS_PAYMENT_SETTLED:
                try:
                    apply_result = wb.apply_request(
                        case, actor_user_id=actor_user_id, commit=True,
                    )
                    applied = True
                    if isinstance(apply_result, dict):
                        ledger_entry_id = apply_result.get('ledger_entry_id')
                except Exception as apply_exc:
                    logger.warning(
                        'stripe_invoice_apply_failed err_class=%s case_id=%s',
                        type(apply_exc).__name__, case.id,
                    )
        return {
            'settled': settled_this_call,
            'applied': applied,
            'case_id': case.id,
            'case_status': case.status,
            'ledger_entry_id': ledger_entry_id,
        }
    except Exception as exc:
        logger.warning(
            'stripe_invoice_settle_failed err_class=%s',
            type(exc).__name__,
        )
        return {'settled': False, 'skip_reason': 'internal_error'}


def reconcile_paid_session_for_case(case_id: int, *, auto_apply: bool = True, actor_user_id: int | None = None) -> dict[str, Any]:
    """v92h — manual reconciliation for a case where the payment
    happened but the redirect/webhook never updated the case.

    Common reason on Render Sandbox: the subscriber paid BEFORE
    the v92f auto-apply was deployed, or the redirect was
    interrupted (browser closed, deep-link to mobile app, etc.).
    The user sees the "مطلوب دفع" banner still showing even
    though Stripe knows the payment went through.

    This helper asks Stripe directly: "show me the most recent
    Checkout Sessions whose metadata.case_id matches this case",
    finds one with `payment_status='paid'`, then runs the standard
    `_settle_plan_change_invoice` settle + (optionally) apply
    chain. Idempotent — if the case is already resolved we ack.

    Never raises; returns a structured dict the route handler can
    turn into a flash + redirect or a JSON response.
    """
    result: dict[str, Any] = {
        'reconciled': False,
        'paid': False,
        'settled': False,
        'applied': False,
        'reason': None,
        'case_id': case_id,
    }
    if not case_id:
        result['reason'] = 'missing_case_id'
        return result
    try:
        pkg = _configure_stripe()
    except StripeNotReady:
        result['reason'] = 'stripe_not_ready'
        return result
    # Pull recent sessions and filter by metadata.case_id. Stripe's
    # listing endpoint doesn't support metadata search server-side
    # so we walk the first page (up to 100) which is more than
    # enough for the "subscriber just paid" timeframe.
    try:
        listing = pkg.checkout.Session.list(limit=100)
    except Exception as exc:
        logger.warning(
            'stripe_session_list_failed err_class=%s',
            type(exc).__name__,
        )
        result['reason'] = 'session_list_failed'
        return result
    target_case_id_str = str(case_id)
    paid_session = None
    # v92i — wrap the iteration so a single malformed session entry
    # can never tear down the whole reconcile call. Each metadata
    # access is also wrapped individually because the Stripe SDK's
    # lazy attribute proxies have raised AttributeError in the
    # field on some account states.
    sessions = []
    try:
        sessions = list(getattr(listing, 'data', None) or [])
    except Exception:
        sessions = []
    # v92j — diagnostic trail: log a compact summary of every
    # session we see + decide on. This is the only way to debug
    # "I paid but reconcile says no paid session found" without
    # storing the session_id on our side.
    inspected_count = 0
    candidate_case_ids: list[str] = []
    for sess in sessions:
        try:
            metadata = getattr(sess, 'metadata', None) or {}
            if hasattr(metadata, 'to_dict_recursive'):
                try:
                    metadata = metadata.to_dict_recursive()
                except Exception:
                    metadata = {}
            if not isinstance(metadata, dict):
                try:
                    metadata = dict(metadata)
                except Exception:
                    metadata = {}
            # v92l — Stripe `list()` sometimes returns a shallow
            # session whose metadata appears empty even when the
            # server stored the keys. If metadata looks empty,
            # explicitly `retrieve()` the session to get the
            # canonical record before deciding to skip.
            if not metadata:
                try:
                    session_id_for_retrieve = getattr(sess, 'id', None)
                    if session_id_for_retrieve:
                        full = pkg.checkout.Session.retrieve(
                            session_id_for_retrieve,
                        )
                        full_md = getattr(full, 'metadata', None) or {}
                        if hasattr(full_md, 'to_dict_recursive'):
                            try:
                                full_md = full_md.to_dict_recursive()
                            except Exception:
                                full_md = {}
                        if isinstance(full_md, dict) and full_md:
                            metadata = full_md
                except Exception:
                    pass
            sess_case_id = str(metadata.get('case_id') or '')
            sess_kind = str(metadata.get('kind') or '')
            sess_payment_status = str(
                getattr(sess, 'payment_status', '') or ''
            ).lower()
            inspected_count += 1
            # Build a short id list so the log shows what case_ids
            # were actually visible to us. Capped to first 20 so a
            # long account history doesn't bloat the log line.
            if sess_kind == 'plan_change_invoice' and len(candidate_case_ids) < 20:
                candidate_case_ids.append(
                    f'{sess_case_id}:{sess_payment_status}',
                )
            if sess_case_id != target_case_id_str:
                continue
            if sess_kind != 'plan_change_invoice':
                continue
            if sess_payment_status == 'paid':
                paid_session = sess
                break
        except Exception as inner_exc:
            logger.warning(
                'stripe_session_iter_skipped err_class=%s',
                type(inner_exc).__name__,
            )
            continue
    logger.info(
        'stripe_reconcile_scan case_id=%s target_match=%s '
        'sessions_seen=%s plan_change_candidates=%s',
        case_id, paid_session is not None,
        inspected_count, candidate_case_ids,
    )
    if paid_session is None:
        result['reason'] = 'no_paid_session_found'
        return result
    result['paid'] = True
    try:
        result['session_id'] = getattr(paid_session, 'id', None)
    except Exception:
        result['session_id'] = None
    try:
        settle_outcome = _settle_plan_change_invoice(
            case_id,
            auto_apply=auto_apply,
            actor_user_id=actor_user_id,
            note='Reconciled by subscriber after sandbox payment',
        )
    except Exception as settle_exc:
        logger.exception(
            'stripe_reconcile_settle_raised case_id=%s err_class=%s',
            case_id, type(settle_exc).__name__,
        )
        result['reason'] = 'settle_raised'
        return result
    if not isinstance(settle_outcome, dict):
        settle_outcome = {}
    result.update(settle_outcome)
    result['reconciled'] = True
    if settle_outcome.get('applied'):
        result['reason'] = 'reconciled_and_applied'
    elif settle_outcome.get('settled'):
        result['reason'] = 'reconciled_settled_pending_apply'
    elif settle_outcome.get('skip_reason') == 'case_already_resolved':
        result['reason'] = 'already_applied'
    else:
        result['reason'] = settle_outcome.get(
            'skip_reason', 'reconcile_failed',
        )
    return result


def verify_and_settle_checkout_session(session_id: str, *, auto_apply: bool = True, actor_user_id: int | None = None) -> dict[str, Any]:
    """v92f — redirect-fallback companion to the webhook.

    The Stripe webhook is the authoritative path for marking an
    invoice settled, but on Render Sandbox the webhook is often not
    wired. So when Stripe redirects the subscriber back to
    `/payments/stripe/success?session_id=<id>`, the route handler
    calls this helper which:

      1. Retrieves the Checkout Session from Stripe.
      2. Confirms `payment_status == 'paid'` AND
         `metadata.kind == 'plan_change_invoice'`.
      3. Settles the invoice + (by default) applies the plan
         change via `_settle_plan_change_invoice(..., auto_apply=True)`.

    Idempotent: re-hitting the success URL after the plan is already
    applied returns `applied=False` with `skip_reason='case_already_resolved'`.

    Never raises. Returns a result dict the success route folds into
    the template so the page can show "تم الدفع وطُبّقت الخطة" instead
    of the generic "ستُطبَّق قريباً".
    """
    result: dict[str, Any] = {
        'verified': False,
        'paid': False,
        'settled': False,
        'applied': False,
        'reason': None,
        'case_status': None,
    }
    if not session_id:
        result['reason'] = 'missing_session_id'
        return result
    # Defensive: reject the literal placeholder if it ever leaks
    # through again (pre-v92e behavior).
    if '{' in session_id or '%7B' in session_id:
        result['reason'] = 'placeholder_session_id'
        return result
    try:
        pkg = _configure_stripe()
    except StripeNotReady:
        result['reason'] = 'stripe_not_ready'
        return result
    try:
        sess = pkg.checkout.Session.retrieve(session_id)
    except Exception as exc:
        logger.warning(
            'stripe_session_retrieve_failed err_class=%s session_id=%s',
            type(exc).__name__, session_id[:32],
        )
        result['reason'] = 'session_retrieve_failed'
        return result
    payment_status = str(getattr(sess, 'payment_status', '') or '').lower()
    metadata = getattr(sess, 'metadata', None) or {}
    if hasattr(metadata, 'to_dict_recursive'):
        try:
            metadata = metadata.to_dict_recursive()
        except Exception:
            metadata = {}
    kind = str(metadata.get('kind') or '').strip()
    raw_case_id = metadata.get('case_id')
    try:
        case_id = int(raw_case_id) if raw_case_id is not None else None
    except (TypeError, ValueError):
        case_id = None
    result['verified'] = True
    result['paid'] = payment_status == 'paid'
    result['payment_status'] = payment_status
    result['kind'] = kind
    result['case_id'] = case_id
    if kind != 'plan_change_invoice':
        result['reason'] = 'not_plan_change_invoice'
        return result
    if not case_id:
        result['reason'] = 'missing_case_id'
        return result
    if not result['paid']:
        result['reason'] = f'payment_status_{payment_status or "unknown"}'
        return result
    # All checks passed — settle + (optionally) apply.
    settle_outcome = _settle_plan_change_invoice(
        case_id,
        auto_apply=auto_apply,
        actor_user_id=actor_user_id,
        note='Settled by Stripe redirect-fallback after sandbox payment',
    )
    result.update(settle_outcome)
    if settle_outcome.get('applied'):
        result['reason'] = 'settled_and_applied'
    elif settle_outcome.get('settled'):
        result['reason'] = 'settled_pending_apply'
    elif settle_outcome.get('skip_reason') == 'case_already_resolved':
        result['reason'] = 'already_applied'
    else:
        result['reason'] = settle_outcome.get(
            'skip_reason', 'settle_failed',
        )
    return result


# v86: ── Invoice checkout for plan-change payment requests ──────────


def create_invoice_checkout_session(
    *,
    case_id: int,
    amount_value: float,
    currency: str,
    case_label: str,
    success_url: str,
    cancel_url: str,
    customer_email: Optional[str] = None,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    locale: Optional[str] = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session that bills the exact
    prorated amount on a plan-change invoice (`INV-…` ledger row).

    Differences from `create_checkout_session`:
      * `kind='plan_change_invoice'` metadata so the webhook
        handler recognises completed checkouts and flips the case
        status to `payment_settled` via `mark_invoice_settled`.
      * `case_id` is preserved verbatim in the metadata so the
        webhook can resolve the originating request.
    """
    if amount_value <= 0:
        raise ValueError('amount_value must be a positive number')
    if not currency or len(currency) > 8:
        raise ValueError('currency is required and must be short')
    if not case_label:
        raise ValueError('case_label is required')
    if not success_url or not cancel_url:
        raise ValueError('success_url + cancel_url are required')
    if not case_id:
        raise ValueError('case_id is required')
    pkg = _configure_stripe()
    unit_amount = int(round(float(amount_value) * 100))
    safe_metadata: dict[str, Any] = {
        'provider': PROVIDER_NAME,
        'mode': PROVIDER_MODE,
        'kind': 'plan_change_invoice',
        'case_id': str(case_id),
    }
    if tenant_id is not None:
        safe_metadata['tenant_id'] = str(tenant_id)
    if user_id is not None:
        safe_metadata['user_id'] = str(user_id)
    # v92p — explicit pre-create log of the EXACT metadata dict we
    # are about to send to Stripe. If user pays and Stripe still
    # shows empty metadata, this proves our payload was correct
    # vs. proves it was already wrong on our side.
    logger.info(
        'stripe_invoice_checkout: about_to_create '
        'safe_metadata_keys=%s safe_metadata=%r case_id=%s amount=%s',
        list(safe_metadata.keys()), safe_metadata, case_id, amount_value,
    )
    # v92b — Stripe Checkout's `locale` parameter has a **strict
    # allowlist** of supported values. Arabic is NOT in that list
    # (Stripe-supported list as of 2026-05: auto, bg, cs, da, de,
    # el, en, en-GB, es, es-419, et, fi, fil, fr, fr-CA, hr, hu,
    # id, it, ja, ko, lt, lv, ms, mt, nb, nl, pl, pt, pt-BR, ro,
    # ru, sk, sl, sv, th, tr, vi, zh, zh-HK, zh-TW). Passing
    # `locale='ar'` makes Stripe reject the session creation with
    # an `invalid_request_error`, which v90 surfaced to the
    # subscriber as "تعذّر إنشاء جلسة الدفع".
    #
    # The fix: only forward values Stripe actually supports. Map
    # English → 'en', everything else (including Arabic) → 'auto'
    # so Stripe picks the closest supported language from the
    # browser's `Accept-Language` header.
    _STRIPE_SUPPORTED_LOCALES = {
        'auto', 'bg', 'cs', 'da', 'de', 'el', 'en', 'en-GB',
        'es', 'es-419', 'et', 'fi', 'fil', 'fr', 'fr-CA',
        'hr', 'hu', 'id', 'it', 'ja', 'ko', 'lt', 'lv',
        'ms', 'mt', 'nb', 'nl', 'pl', 'pt', 'pt-BR', 'ro',
        'ru', 'sk', 'sl', 'sv', 'th', 'tr', 'vi', 'zh',
        'zh-HK', 'zh-TW',
    }
    stripe_locale = 'auto'
    if locale:
        normalized = str(locale).lower().strip()
        if normalized.startswith('en'):
            stripe_locale = 'en'
        elif normalized in _STRIPE_SUPPORTED_LOCALES:
            stripe_locale = normalized
        # Arabic and any other unsupported language → keep 'auto'.
    # v92d — Stripe rejects the entire session if `customer_email`
    # is provided but malformed (e.g. `user@icloud` missing the TLD).
    # The error surfaces as a confusing "تعذّر إنشاء جلسة الدفع"
    # message to the subscriber even though the rest of the
    # invoice is fine. The pragmatic fix: validate cheaply with a
    # permissive regex, and if the email doesn't look real, simply
    # OMIT it — Stripe's hosted Checkout will then prompt the
    # subscriber to enter their email themselves, which is a much
    # better UX than a hard failure.
    safe_email: Optional[str] = None
    if customer_email:
        normalized_email = str(customer_email).strip()
        # Loose but practical email shape: <local>@<domain>.<tld>
        # with no whitespace in any segment. Catches the
        # `user@icloud` (missing tld) case + most other typos.
        if _looks_like_email(normalized_email):
            safe_email = normalized_email
        else:
            logger.info(
                'stripe_invoice_checkout: dropping malformed customer_email %r',
                normalized_email[:120],
            )
    try:
        session = pkg.checkout.Session.create(
            mode='payment',
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': currency.lower(),
                    'product_data': {'name': case_label[:120]},
                    'unit_amount': unit_amount,
                },
                'quantity': 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=safe_email,
            metadata=safe_metadata,
            locale=stripe_locale,
        )
        # v92p — confirm what Stripe ECHOED back on the create
        # response. If we sent X but Stripe responds with Y={},
        # the bug is server-side; if Stripe echoes X, the bug is
        # in our DIAGNOSTICS path (and the original payment worked).
        try:
            echo_md = getattr(session, 'metadata', None) or {}
            if hasattr(echo_md, 'to_dict_recursive'):
                try:
                    echo_md = echo_md.to_dict_recursive()
                except Exception:
                    echo_md = {}
            logger.info(
                'stripe_invoice_checkout: created session_id=%s '
                'metadata_echoed=%r match_keys=%s',
                getattr(session, 'id', None),
                echo_md if isinstance(echo_md, dict) else str(echo_md)[:200],
                bool(echo_md) and set(echo_md.keys()) >= set(safe_metadata.keys()),
            )
        except Exception:
            pass
    except Exception as exc:
        # v92c — capture Stripe's actual error message + offending
        # parameter so the next failure pinpoints the real cause
        # instead of just naming the exception class. Stripe's
        # `InvalidRequestError` carries `user_message`, `param`,
        # `code`, and `request_id` attributes — we surface all of
        # them when present.
        detail_parts = [f'err_class={type(exc).__name__}']
        for attr in ('user_message', 'param', 'code', 'request_id'):
            value = getattr(exc, attr, None)
            if value:
                detail_parts.append(f'{attr}={value!r}')
        raw_message = str(exc) or ''
        if raw_message:
            detail_parts.append(f'message={raw_message[:200]!r}')
        # Also log the resolved locale we sent so we can confirm at
        # a glance whether the v92b fix actually took effect.
        detail_parts.append(f'sent_locale={stripe_locale!r}')
        detail_parts.append(f'currency={currency.lower()!r}')
        detail_parts.append(f'unit_amount={unit_amount!r}')
        logger.warning(
            'stripe_invoice_checkout_failed %s',
            ' '.join(detail_parts),
        )
        raise
    return {
        'id': getattr(session, 'id', None),
        'url': getattr(session, 'url', None),
        'provider': PROVIDER_NAME,
        'mode': PROVIDER_MODE,
    }
