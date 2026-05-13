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
    """Minimal v84 event handler — log the event type and a small
    safe identifier, do NOT mutate any subscription state.

    v84 is the sandbox foundation; auto-activation on
    `checkout.session.completed` is a deliberate future step that
    requires a clearly safe test-only flow. For now we just
    acknowledge receipt so Stripe doesn't retry indefinitely.
    """
    event_type = str(event.get('type') or 'unknown')
    event_id = str(event.get('id') or '')
    obj = (event.get('data') or {}).get('object') or {}
    obj_id = str(obj.get('id') or '')
    logger.info(
        'stripe_webhook_received type=%s event_id=%s object_id=%s mode=%s',
        event_type, event_id, obj_id, PROVIDER_MODE,
    )
    return {
        'received': True,
        'event_type': event_type,
        'event_id': event_id,
        'object_id': obj_id,
        'mode': PROVIDER_MODE,
        'handled': False,  # v84 deliberately does not mutate state
        'reason': (
            'v84 sandbox foundation does not auto-activate '
            'subscriptions; event acknowledged.'
        ),
    }
