"""v82 — plan-change financial workbench service.

The v81 wave gave operators a basic approve/reject surface on top of
``SupportCase(case_type='plan_change_request')``. This module turns
that into a real internal financial operations desk by exposing:

  * Two explicit pricing scenarios (same-duration diff, reduced-days
    swap) with optional manual day adjustment.
  * A discussion path that lets admins propose a scenario to the
    subscriber before applying it.
  * Persistent payment-request / invoice-like records anchored to the
    existing ``WalletLedger`` (no new table, no migration).
  * A clear lifecycle vocabulary so the admin queue can be filtered
    by state instead of just "open vs not".

Architecture
────────────
Heavy lifting lives in this service module — admin route handlers
stay thin and just call ``quote_*``, ``send_discussion``,
``issue_invoice``, ``apply_request``, ``reject_request``,
``cancel_request``. The math itself reuses the prorated formulas
already in `support_ops.compute_plan_change_quote` and the
canonical `billing_engine.change_plan` for the final apply.

Lifecycle states (stored as `SupportCase.status` strings; no schema
change required because `status` is already a `String(30)`):

  open                       — fresh submission
  under_review               — admin opened the workbench
  awaiting_subscriber_reply  — admin sent a discussion proposal
  payment_requested          — invoice issued, waiting for payment
  resolved                   — applied
  closed                     — rejected
  cancelled                  — closed without applying

Ledger references
─────────────────
  PCH-<tenant>-<case>   — final plan-change apply (matches v81)
  INV-<tenant>-<case>   — payment-request / invoice-like obligation
  REV-<tenant>-<case>   — reversal/counter-credit (when a pending
                          invoice is cancelled or the request is
                          rejected before settlement)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional

from ..extensions import db
from ..models import (
    AppUser, NotificationEvent, SubscriptionPlan, SupportAuditLog,
    SupportCase, TenantAccount, TenantSubscription, WalletLedger,
)


# ── Lifecycle vocabulary ─────────────────────────────────────────────


STATUS_OPEN = 'open'
STATUS_UNDER_REVIEW = 'under_review'
STATUS_AWAITING_SUBSCRIBER = 'awaiting_subscriber_reply'
STATUS_PAYMENT_REQUESTED = 'payment_requested'
# v85: transient state between "subscriber paid the invoice" and
# "admin (or future webhook) applied the plan change". Keeps the
# admin workbench queue surfaceable when there's settlement work
# pending application.
STATUS_PAYMENT_SETTLED = 'payment_settled'
STATUS_RESOLVED = 'resolved'
STATUS_CLOSED = 'closed'
STATUS_CANCELLED = 'cancelled'

LIFECYCLE_STATUSES = (
    STATUS_OPEN,
    STATUS_UNDER_REVIEW,
    STATUS_AWAITING_SUBSCRIBER,
    STATUS_PAYMENT_REQUESTED,
    STATUS_PAYMENT_SETTLED,
    STATUS_RESOLVED,
    STATUS_CLOSED,
    STATUS_CANCELLED,
)

# States considered "still pending an outcome" — the queue's KPI band
# and the sidebar badge anchor on this set. `payment_settled` IS
# included because the plan change hasn't been applied yet at that
# point — admin/webhook still needs to flip it to resolved.
ACTIVE_STATUSES = frozenset({
    STATUS_OPEN,
    STATUS_UNDER_REVIEW,
    STATUS_AWAITING_SUBSCRIBER,
    STATUS_PAYMENT_REQUESTED,
    STATUS_PAYMENT_SETTLED,
})


# Notification + ledger categories (kept stable so finance can filter).
EVENT_DISCUSSION = 'plan_change_discussion'
EVENT_INVOICE_ISSUED = 'plan_change_invoice_issued'
EVENT_APPLIED = 'plan_change_applied'
EVENT_REJECTED = 'plan_change_rejected'
EVENT_CANCELLED = 'plan_change_cancelled'

LEDGER_CATEGORY_PENDING = 'plan_change_pending'
LEDGER_CATEGORY_APPLIED = 'plan_change'
LEDGER_CATEGORY_REVERSAL = 'plan_change_reversal'

PRICING_MODE_SAME_DURATION = 'same_duration'
PRICING_MODE_REDUCED_DAYS = 'reduced_days'

# v87 — policy classification. The plan-change policy is asymmetric:
# downgrades MUST NOT generate a refund/wallet credit (the remaining
# value is converted to more days on the cheaper plan), upgrades offer
# two valid choices (keep days + pay diff, or accept fewer days + no
# payment), and a lateral switch is a clean move with no money or day
# loss. The classifier compares per-day prices.
POLICY_DOWNGRADE = 'downgrade'
POLICY_UPGRADE = 'upgrade'
POLICY_LATERAL = 'lateral'

# Eligibility reason strings. Stable so tests and the UI can branch on
# them without parsing free-text summaries.
ELIGIBILITY_DOWNGRADE_NO_REFUND = 'downgrade_no_refund_policy'
ELIGIBILITY_OK = 'ok'


# ── Audit / scenario shape ──────────────────────────────────────────


@dataclass
class Scenario:
    """Pure-data description of a proposed financial outcome.

    The workbench builds two scenarios at preview time and shows them
    to the operator. Whatever scenario the operator chooses gets
    stamped onto the SupportAuditLog row so the audit trail records
    the EXACT numbers presented to the operator at decision time.
    """

    mode: str
    label_ar: str
    label_en: str
    remaining_days: int
    target_days: int
    cycle_days_current: int
    cycle_days_target: int
    current_plan_price: float
    target_plan_price: float
    current_remaining_value: float
    target_remaining_value: float
    amount: float  # signed: + → subscriber owes; 0 → no money moves.
    #                 Under v87 policy this is NEVER negative for a
    #                 subscriber-driven path (downgrade does not refund).
    currency: str
    summary_ar: str
    summary_en: str
    # v87 — policy fields. `policy_kind` is the upgrade/downgrade/
    # lateral classification. `is_eligible` is False when this scenario
    # is refused by policy (e.g. downgrade same-duration would imply a
    # refund). `is_recommended` flags the primary path the subscriber
    # UI should default to. `eligibility_reason` is a stable string the
    # UI/mobile clients can branch on.
    policy_kind: str = POLICY_LATERAL
    is_eligible: bool = True
    is_recommended: bool = False
    eligibility_reason: str = ELIGIBILITY_OK
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['amount'] = round(self.amount, 2)
        return d


# ── Helpers ──────────────────────────────────────────────────────────


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.utcnow()


def _plan_label(plan: SubscriptionPlan | None) -> str:
    if not plan:
        return '—'
    return (
        getattr(plan, 'name_ar', None)
        or getattr(plan, 'name_en', None)
        or getattr(plan, 'code', None)
        or f'plan-{getattr(plan, "id", "")}'
    )


def _safe_currency(*candidates) -> str:
    for c in candidates:
        if c:
            s = str(c).strip()
            if s:
                return s
    return 'USD'


def _floor_cycle(plan: SubscriptionPlan | None) -> int:
    if plan is None:
        return 30
    return max(int(getattr(plan, 'duration_days_default', 30) or 30), 1)


def _audit(
    case: SupportCase, action: str, summary: str, *,
    actor_user_id: int | None, details: dict | None = None,
) -> None:
    """Append a structured audit row tied to the case.

    v88 hardening: `details_json` is built with a `default=str`
    fallback so any datetime / Decimal / Mock-like object that
    sneaks into `details` (e.g. via a future scenario field) gets
    stringified instead of raising `TypeError` and 500-ing the
    whole apply path. Audit row content is for ops/finance review,
    not machine consumption — a stringified value is acceptable
    when the alternative is losing the entire transaction.
    """
    try:
        details_json = json.dumps(
            details or {}, ensure_ascii=False, default=str,
        )
    except Exception:
        details_json = '{}'
    db.session.add(SupportAuditLog(
        case_type=getattr(case, 'case_type', None) or 'plan_change_request',
        source_id=getattr(case, 'source_id', None) or getattr(case, 'user_id', 0) or 0,
        actor_user_id=actor_user_id,
        action=action,
        summary=(summary or '')[:255],
        details_json=details_json,
        created_at=datetime.utcnow(),
    ))


def _notify_subscriber(
    case: SupportCase, *, event_type: str, title: str, message: str,
    actor_user_id: int | None = None,
) -> NotificationEvent | None:
    """Push a NotificationEvent to the subscriber owning the case.
    Returns the persisted instance or `None` when the case has no
    user attached.

    v88 hardening: `user_id` coercion is wrapped so a non-int
    `case.user_id` (corruption / mocking edge case) gracefully
    returns `None` instead of bubbling a `TypeError` out of the
    apply path. Title length is clamped (model column = 220).
    """
    user_id = getattr(case, 'user_id', None)
    if not user_id:
        return None
    try:
        target_user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    ev = NotificationEvent(
        event_type=event_type,
        target_user_id=target_user_id,
        tenant_id=getattr(case, 'tenant_id', None),
        source_type='plan_change_request',
        source_id=getattr(case, 'id', None),
        title=(title or '')[:220],
        message=message or '',
        direct_url='/account/subscription',
        status='new',
        created_at=datetime.utcnow(),
    )
    db.session.add(ev)
    return ev


# ── Scenarios ────────────────────────────────────────────────────────


def classify_change(
    current_plan: SubscriptionPlan | None,
    target_plan: SubscriptionPlan | None,
    *,
    cycle_days_current: int | None = None,
    cycle_days_target: int | None = None,
) -> str:
    """v87 / v93d — classify a (current, target) pair as upgrade/
    downgrade/lateral.

    v87 used **per-day price** which produced confusing labels when
    cycle lengths differed: a 256-day plan at $30 (≈$0.117/day) →
    90-day plan at $20 (≈$0.222/day) classified as UPGRADE even
    though the subscriber paid LESS total and intuitively saw it as
    "downgrade".

    v93d switches to **total cycle price** so the label matches the
    subscriber's mental model: cheaper total = downgrade, more
    expensive total = upgrade. The conversion math (per-day) is
    unaffected — only the upgrade/downgrade label changes.

    Edge case: under v93d, a "downgrade" to a shorter-cycle plan
    with higher per-day price will produce FEWER days on the new
    plan after conversion. The summary copy honestly states this:
    "Your remaining value converts to X days on the cheaper plan"
    without promising "more days".
    """
    if not current_plan or not target_plan:
        return POLICY_LATERAL
    cur_price = float(getattr(current_plan, 'price', 0) or 0)
    tgt_price = float(getattr(target_plan, 'price', 0) or 0)
    # Total cycle price is the comparison axis. Penny tolerance.
    if abs(tgt_price - cur_price) < 0.01:
        return POLICY_LATERAL
    return POLICY_UPGRADE if tgt_price > cur_price else POLICY_DOWNGRADE


def _resolve_request_context(case: SupportCase, *, target_plan: SubscriptionPlan | None, now: datetime | None) -> dict:
    """Common context shared by every scenario: tenant, current sub,
    current plan, target plan, remaining days, and the two cycle
    lengths used by the prorated math."""
    now = _now(now)
    from .support_ops import extract_plan_change_target_plan
    target = target_plan or extract_plan_change_target_plan(case)
    tenant = (
        TenantAccount.query.get(case.tenant_id)
        if getattr(case, 'tenant_id', None) else None
    )
    sub = None
    current_plan = None
    if tenant:
        sub = (
            TenantSubscription.query
            .filter_by(tenant_id=tenant.id)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if sub and sub.plan_id:
            current_plan = SubscriptionPlan.query.get(sub.plan_id)
    remaining_days = 0
    if sub and sub.ends_at:
        remaining_days = max(
            (sub.ends_at.date() - now.date()).days, 0,
        )
    cycle_current = 0
    if sub and sub.starts_at and sub.ends_at:
        cycle_current = max(
            (sub.ends_at.date() - sub.starts_at.date()).days, 0,
        )
    if cycle_current <= 0:
        cycle_current = _floor_cycle(current_plan)
    cycle_target = _floor_cycle(target)
    return {
        'now': now,
        'tenant': tenant,
        'subscription': sub,
        'current_plan': current_plan,
        'target_plan': target,
        'remaining_days': remaining_days,
        'cycle_days_current': cycle_current,
        'cycle_days_target': cycle_target,
        'current_plan_price': float(getattr(current_plan, 'price', 0) or 0),
        'target_plan_price': float(getattr(target, 'price', 0) or 0),
        'currency': _safe_currency(
            getattr(target, 'currency', None),
            getattr(current_plan, 'currency', None),
        ),
    }


def quote_same_duration(case: SupportCase, *, target_plan: SubscriptionPlan | None = None, now: datetime | None = None) -> Scenario:
    """Scenario A — keep the same remaining days.

    Math:
        current_remaining_value = (remaining/cycle_current) × current_price
        target_remaining_value  = (remaining/cycle_target)  × target_price
        amount = target_remaining_value - current_remaining_value

    v87 policy:
      * **upgrade** → eligible. ``amount > 0``: subscriber owes the
        difference. This is one of two valid upgrade paths.
      * **lateral** → eligible. ``amount ≈ 0``: clean switch.
      * **downgrade** → **NOT eligible**. The would-be negative diff
        is NOT shown as a credit/refund. The scenario is returned with
        ``is_eligible=False`` and ``amount=0`` so the subscriber never
        sees "same days + credit". The conversion-to-more-days path
        (``quote_reduced_days``) is the only offered downgrade path.
    """
    ctx = _resolve_request_context(case, target_plan=target_plan, now=now)
    remaining = ctx['remaining_days']
    cur_rv = (
        round((remaining / ctx['cycle_days_current']) * ctx['current_plan_price'], 2)
        if remaining > 0 and ctx['current_plan'] else 0.0
    )
    tgt_rv = (
        round((remaining / ctx['cycle_days_target']) * ctx['target_plan_price'], 2)
        if remaining > 0 and ctx['target_plan'] else 0.0
    )
    raw_amount = round(tgt_rv - cur_rv, 2)
    policy_kind = classify_change(
        ctx['current_plan'], ctx['target_plan'],
        cycle_days_current=ctx['cycle_days_current'],
        cycle_days_target=ctx['cycle_days_target'],
    )
    if policy_kind == POLICY_DOWNGRADE:
        # Refuse: this path would imply a refund/credit which v87
        # policy forbids. Zero the amount out so no caller can
        # accidentally use it to write a credit.
        amount = 0.0
        is_eligible = False
        is_recommended = False
        eligibility_reason = ELIGIBILITY_DOWNGRADE_NO_REFUND
        summary_ar = (
            'هذا المسار غير مُتاح للنزول إلى خطة أرخص. '
            'بدلاً من إرجاع المبلغ، تُحوَّل قيمتك المتبقّية إلى '
            'أيام إضافية على الخطة الجديدة.'
        )
        summary_en = (
            'This path is not offered when moving to a cheaper plan. '
            'Your remaining value is converted into more days on the '
            'new plan instead of being refunded.'
        )
    elif raw_amount > 0:
        amount = raw_amount
        is_eligible = True
        is_recommended = True
        eligibility_reason = ELIGIBILITY_OK
        summary_ar = (
            f'يحتفظ المشترك بنفس عدد الأيام المتبقّية ({remaining}). '
            f'فرق السعر المستحق: {amount:.2f} {ctx["currency"]}.'
        )
        summary_en = (
            f'Subscriber keeps the same remaining days ({remaining}). '
            f'Extra due: {amount:.2f} {ctx["currency"]}.'
        )
    else:
        # Lateral — amount is effectively zero.
        amount = 0.0
        is_eligible = True
        is_recommended = True
        eligibility_reason = ELIGIBILITY_OK
        summary_ar = (
            f'لا يوجد فرق مالي مستحق. الأيام المتبقّية: {remaining}.'
        )
        summary_en = (
            f'No financial difference. Remaining days: {remaining}.'
        )
    return Scenario(
        mode=PRICING_MODE_SAME_DURATION,
        label_ar='نفس الأيام المتبقّية',
        label_en='Same remaining days',
        remaining_days=remaining,
        target_days=remaining,
        cycle_days_current=ctx['cycle_days_current'],
        cycle_days_target=ctx['cycle_days_target'],
        current_plan_price=ctx['current_plan_price'],
        target_plan_price=ctx['target_plan_price'],
        current_remaining_value=cur_rv,
        target_remaining_value=tgt_rv,
        amount=amount,
        currency=ctx['currency'],
        summary_ar=summary_ar,
        summary_en=summary_en,
        policy_kind=policy_kind,
        is_eligible=is_eligible,
        is_recommended=is_recommended,
        eligibility_reason=eligibility_reason,
    )


def quote_reduced_days(case: SupportCase, *, target_plan: SubscriptionPlan | None = None, desired_target_days: int | None = None, now: datetime | None = None) -> Scenario:
    """Scenario B — convert the remaining VALUE into target-plan days.

    Math:
        target_per_day   = target_price / cycle_days_target
        free_target_days = floor(current_remaining_value / target_per_day)
        chosen           = desired_target_days or free_target_days
        amount           = (chosen − free_target_days) × target_per_day

    Under v87 policy this single math is reframed by `policy_kind`:

      * **downgrade** — `free_target_days` is GREATER than the
        remaining days (the cheaper plan stretches further). The
        scenario is **recommended and the only offered downgrade
        path**. ``amount = 0`` always for the default path; the
        subscriber receives MORE days on the new plan.
      * **upgrade** — `free_target_days` is LESS than the remaining
        days (the more expensive plan burns through value faster).
        The scenario is **recommended as option B**: the subscriber
        accepts fewer days and pays nothing extra. ``amount = 0`` for
        the default path.
      * **lateral** — `free_target_days ≈ remaining_days`. Not the
        recommended path (the same-duration scenario is); still
        eligible for completeness.

    `desired_target_days` is preserved for the admin workbench so
    operators can shape exceptional outcomes. When the operator
    requests **more** days than the free swap (`amount > 0`) the
    subscriber owes money. The subscriber-facing UI does NOT expose
    this knob — the free swap is the only offered option from that
    surface.

    Floor (not round) for `free_target_days` so the conversion never
    over-credits the subscriber: if the math says 73.6 days, the
    subscriber gets 73 days, never 74.
    """
    ctx = _resolve_request_context(case, target_plan=target_plan, now=now)
    remaining = ctx['remaining_days']
    cur_rv = (
        round((remaining / ctx['cycle_days_current']) * ctx['current_plan_price'], 2)
        if remaining > 0 and ctx['current_plan'] else 0.0
    )
    target_per_day = (
        ctx['target_plan_price'] / ctx['cycle_days_target']
        if ctx['target_plan'] else 0.0
    )
    # Floor so we never quietly over-credit the subscriber on the
    # conversion. The leftover sub-day fraction is intentionally
    # forfeited (matches "deterministic and transparent" in the
    # policy spec; a future wave can add a wallet-credit line for
    # the leftover sliver if accounting decides to capture it).
    free_target_days = (
        int(cur_rv // target_per_day) if target_per_day > 0 else 0
    )
    chosen = (
        int(desired_target_days)
        if desired_target_days is not None
        else free_target_days
    )
    chosen = max(chosen, 0)
    tgt_rv = round(chosen * target_per_day, 2)
    raw_amount = round(tgt_rv - cur_rv, 2)
    policy_kind = classify_change(
        ctx['current_plan'], ctx['target_plan'],
        cycle_days_current=ctx['cycle_days_current'],
        cycle_days_target=ctx['cycle_days_target'],
    )
    # The subscriber-facing path never asks the subscriber to pay for
    # extra days on the reduced-days scenario. When the operator's
    # `desired_target_days` would imply a debit (amount > 0) we still
    # surface it for the workbench, but `is_recommended` flips off.
    # When `amount < 0` (operator asked for fewer days than the free
    # swap) we clamp at zero in the surfaced amount so we never write
    # a refund through this path.
    amount = raw_amount if raw_amount > 0 else 0.0
    if policy_kind == POLICY_DOWNGRADE:
        is_recommended = (raw_amount <= 0)
        is_eligible = True
        eligibility_reason = ELIGIBILITY_OK
        if raw_amount > 0:
            summary_ar = (
                f'الباقة الجديدة على {chosen} يوماً '
                f'(أكثر من التحويل الافتراضي {free_target_days} يوم). '
                f'فرق إضافي مستحق: {amount:.2f} {ctx["currency"]}.'
            )
            summary_en = (
                f'Target plan for {chosen} day(s) '
                f'(more than the default conversion of {free_target_days}). '
                f'Extra due: {amount:.2f} {ctx["currency"]}.'
            )
        else:
            summary_ar = (
                f'يتم تحويل قيمتك المتبقّية ({cur_rv:.2f} {ctx["currency"]}) '
                f'إلى {chosen} يوماً على الخطة الجديدة. لا تُسترد أي مبالغ.'
            )
            summary_en = (
                f'Your remaining value ({cur_rv:.2f} {ctx["currency"]}) '
                f'is converted into {chosen} day(s) on the new plan. '
                f'No refund is issued.'
            )
    elif policy_kind == POLICY_UPGRADE:
        is_recommended = (raw_amount <= 0)
        is_eligible = True
        eligibility_reason = ELIGIBILITY_OK
        if raw_amount > 0:
            summary_ar = (
                f'الباقة الجديدة على {chosen} يوماً '
                f'(أكثر من التحويل المجاني {free_target_days} يوم). '
                f'فرق إضافي مستحق: {amount:.2f} {ctx["currency"]}.'
            )
            summary_en = (
                f'Target plan for {chosen} day(s) '
                f'(more than the free conversion of {free_target_days}). '
                f'Extra due: {amount:.2f} {ctx["currency"]}.'
            )
        else:
            summary_ar = (
                f'الانتقال إلى الخطة الأعلى بـ {chosen} يوماً بدلاً من '
                f'{remaining} يوماً، دون أي مبلغ إضافي.'
            )
            summary_en = (
                f'Move to the more expensive plan with {chosen} day(s) '
                f'instead of {remaining}, with no extra payment.'
            )
    else:
        # lateral
        is_recommended = False
        is_eligible = True
        eligibility_reason = ELIGIBILITY_OK
        summary_ar = (
            f'تحويل مكافئ — {chosen} يوماً على الخطة الجديدة دون فرق مالي.'
        )
        summary_en = (
            f'Equivalent swap — {chosen} day(s) on the new plan, '
            f'no financial difference.'
        )
    return Scenario(
        mode=PRICING_MODE_REDUCED_DAYS,
        label_ar=(
            'تحويل القيمة إلى أيام أكثر'
            if policy_kind == POLICY_DOWNGRADE
            else 'تقليل الأيام على الباقة الجديدة'
        ),
        label_en=(
            'Convert value into more days'
            if policy_kind == POLICY_DOWNGRADE
            else 'Reduce days on target plan'
        ),
        remaining_days=remaining,
        target_days=chosen,
        cycle_days_current=ctx['cycle_days_current'],
        cycle_days_target=ctx['cycle_days_target'],
        current_plan_price=ctx['current_plan_price'],
        target_plan_price=ctx['target_plan_price'],
        current_remaining_value=cur_rv,
        target_remaining_value=tgt_rv,
        amount=amount,
        currency=ctx['currency'],
        summary_ar=summary_ar,
        summary_en=summary_en,
        policy_kind=policy_kind,
        is_eligible=is_eligible,
        is_recommended=is_recommended,
        eligibility_reason=eligibility_reason,
        extra={
            'free_target_days': free_target_days,
            'target_per_day_price': round(target_per_day, 4),
            'days_delta_vs_remaining': chosen - remaining,
        },
    )


def build_scenario_set(case: SupportCase, *, target_plan: SubscriptionPlan | None = None, desired_target_days: int | None = None, now: datetime | None = None) -> dict[str, Scenario]:
    """Convenience: returns both scenarios in one call so the
    workbench template can render them side-by-side."""
    return {
        PRICING_MODE_SAME_DURATION: quote_same_duration(
            case, target_plan=target_plan, now=now,
        ),
        PRICING_MODE_REDUCED_DAYS: quote_reduced_days(
            case, target_plan=target_plan,
            desired_target_days=desired_target_days, now=now,
        ),
    }


def select_scenario(case: SupportCase, *, mode: str, target_plan: SubscriptionPlan | None = None, desired_target_days: int | None = None, now: datetime | None = None) -> Scenario:
    """Resolve `mode` to one of the two scenarios. Raises
    `ValueError` for unknown modes so a typo in a POST body fails
    loudly rather than silently producing a wrong charge."""
    if mode == PRICING_MODE_SAME_DURATION:
        return quote_same_duration(case, target_plan=target_plan, now=now)
    if mode == PRICING_MODE_REDUCED_DAYS:
        return quote_reduced_days(
            case, target_plan=target_plan,
            desired_target_days=desired_target_days, now=now,
        )
    raise ValueError(f'unknown pricing mode: {mode!r}')


# ── Workflow actions ─────────────────────────────────────────────────


def mark_under_review(case: SupportCase, *, actor_user_id: int | None, commit: bool = True) -> SupportCase:
    """Move a request from ``open`` to ``under_review`` so the queue
    KPI band can show how many requests an operator is actively
    holding. Idempotent: re-marking an already-under-review case is
    a no-op."""
    if case.status == STATUS_OPEN:
        case.status = STATUS_UNDER_REVIEW
        case.updated_at = datetime.utcnow()
        _audit(
            case, 'plan_change.under_review',
            'Admin opened the workbench',
            actor_user_id=actor_user_id,
        )
        if commit:
            db.session.commit()
    return case


def send_discussion(case: SupportCase, *, actor_user_id: int | None, body: str, scenario: Scenario | None = None, commit: bool = True) -> NotificationEvent | None:
    """Send a structured proposal to the subscriber, optionally
    embedding a scenario summary so they see the exact numbers the
    operator is proposing. Transitions the case to
    ``awaiting_subscriber_reply``.

    The discussion is recorded as both:
      * a ``NotificationEvent`` for the subscriber's bell, and
      * a ``SupportAuditLog`` row so the admin history is complete.
    """
    body = (body or '').strip()
    if not body:
        raise ValueError('discussion body is required')
    message = body
    if scenario is not None:
        message = (
            f'{body}\n\n— مقترح: {scenario.summary_ar}'
            if not body.endswith(scenario.summary_ar) else body
        )
    ev = _notify_subscriber(
        case,
        event_type=EVENT_DISCUSSION,
        title='مقترح لتغيير الخطة من الفريق',
        message=message,
        actor_user_id=actor_user_id,
    )
    case.status = STATUS_AWAITING_SUBSCRIBER
    case.updated_at = datetime.utcnow()
    _audit(
        case, 'plan_change.discussion',
        'Sent discussion proposal to subscriber',
        actor_user_id=actor_user_id,
        details={
            'body': body,
            'scenario': scenario.to_dict() if scenario else None,
        },
    )
    if commit:
        db.session.commit()
    return ev


def issue_invoice(case: SupportCase, *, actor_user_id: int | None, scenario: Scenario, commit: bool = True) -> WalletLedger | None:
    """Persist a payment-request / invoice-like obligation for a
    positive-amount scenario.

    Implementation: a `WalletLedger` row with
    ``category='plan_change_pending'`` and
    ``reference='INV-<tenant>-<case>'``. Finance views can filter
    on the category to surface unsettled obligations. When the
    request is applied, ``apply_request`` flips the category to
    ``plan_change`` (settled) and writes a settlement audit row.

    Returns ``None`` when the scenario amount is zero or negative —
    you don't bill someone for a refund. Use this helper only for
    debit-side obligations.
    """
    if scenario.amount <= 0:
        return None
    case_tenant_id = getattr(case, 'tenant_id', None)
    if case_tenant_id is None:
        return None
    # Defensive dedup: reuse an existing INV-… row for this case
    # instead of stacking duplicates on re-clicks.
    reference = f'INV-{case_tenant_id}-{case.id}'
    existing = WalletLedger.query.filter_by(reference=reference).first()
    entry: WalletLedger
    if existing:
        existing.amount = round(scenario.amount, 2)
        existing.currency = scenario.currency
        existing.note = (
            f'Plan change payment request — '
            f'mode={scenario.mode}, days={scenario.target_days}, '
            f'remaining={scenario.remaining_days}'
        )
        existing.category = LEDGER_CATEGORY_PENDING
        existing.entry_type = 'debit'
        entry = existing
    else:
        entry = WalletLedger(
            tenant_id=case_tenant_id,
            actor_user_id=actor_user_id,
            entry_type='debit',
            amount=round(scenario.amount, 2),
            currency=scenario.currency,
            note=(
                f'Plan change payment request — '
                f'mode={scenario.mode}, days={scenario.target_days}, '
                f'remaining={scenario.remaining_days}'
            ),
            reference=reference,
            category=LEDGER_CATEGORY_PENDING,
            is_recurring=False,
        )
        db.session.add(entry)
    case.status = STATUS_PAYMENT_REQUESTED
    case.updated_at = datetime.utcnow()
    _notify_subscriber(
        case,
        event_type=EVENT_INVOICE_ISSUED,
        title='طلب دفع لإتمام تغيير الخطة',
        message=(
            f'تم إصدار طلب دفع بمبلغ {scenario.amount:.2f} {scenario.currency} '
            f'لإتمام تغيير الخطة. '
            f'تفاصيل: {scenario.summary_ar}'
        ),
        actor_user_id=actor_user_id,
    )
    _audit(
        case, 'plan_change.invoice_issued',
        f'Issued payment request {reference}',
        actor_user_id=actor_user_id,
        details={
            'reference': reference,
            'scenario': scenario.to_dict(),
        },
    )
    if commit:
        db.session.commit()
    return entry


def find_pending_invoice(case: SupportCase) -> WalletLedger | None:
    """Return the open `INV-…` ledger entry for a case, if any."""
    case_tenant_id = getattr(case, 'tenant_id', None)
    if case_tenant_id is None:
        return None
    return WalletLedger.query.filter_by(
        reference=f'INV-{case_tenant_id}-{case.id}',
        category=LEDGER_CATEGORY_PENDING,
    ).first()


def _settle_pending_invoice(case: SupportCase, actor_user_id: int | None, scenario: Scenario | None) -> WalletLedger | None:
    """Flip an open invoice row from `plan_change_pending` to
    `plan_change` so finance reports it as settled. Returns the
    ledger row or ``None`` when there was no pending invoice."""
    pending = find_pending_invoice(case)
    if pending is None:
        return None
    pending.category = LEDGER_CATEGORY_APPLIED
    pending.note = (
        (pending.note or '') + ' · settled on apply'
    ).strip(' ·')
    _audit(
        case, 'plan_change.invoice_settled',
        f'Settled pending invoice {pending.reference}',
        actor_user_id=actor_user_id,
        details={
            'reference': pending.reference,
            'scenario': scenario.to_dict() if scenario else None,
        },
    )
    return pending


def _reverse_pending_invoice(case: SupportCase, actor_user_id: int | None, reason: str) -> WalletLedger | None:
    """When a request with a pending invoice is rejected or
    cancelled, write a matching credit entry that nets out the
    obligation. The pending row stays in place for traceability
    (category is updated to ``plan_change_reversal`` so a finance
    filter on the pending category cleanly excludes it)."""
    pending = find_pending_invoice(case)
    if pending is None:
        return None
    reversal = WalletLedger(
        tenant_id=pending.tenant_id,
        actor_user_id=actor_user_id,
        entry_type='credit',
        amount=round(float(pending.amount or 0), 2),
        currency=pending.currency,
        note=(
            f'Reversal of {pending.reference} — '
            f'{reason or "request closed without payment"}'
        ),
        reference=f'REV-{pending.tenant_id}-{case.id}',
        category=LEDGER_CATEGORY_REVERSAL,
        is_recurring=False,
    )
    pending.category = LEDGER_CATEGORY_REVERSAL
    pending.note = (pending.note or '') + ' · reversed'
    db.session.add(reversal)
    _audit(
        case, 'plan_change.invoice_reversed',
        f'Reversed pending invoice {pending.reference}',
        actor_user_id=actor_user_id,
        details={'reference': pending.reference, 'reason': reason},
    )
    return reversal


def apply_request(case: SupportCase, *, actor_user_id: int | None, scenario: Scenario | None = None, now: datetime | None = None, commit: bool = True) -> dict:
    """Apply an approved plan-change request.

    v87 policy: the financial side-effect is **exactly** the scenario
    amount, never anything else. We no longer let `billing_engine.
    change_plan` compute the ledger entry implicitly — that would
    re-introduce the wallet-credit on downgrade we explicitly forbade.
    Instead we:

      1. Mutate `tenant.plan_id`, `tenant.status`, `sub.plan_id`,
         `sub.status` directly so quota / "which plan am I on?" reads
         instantly reflect the switch.
      2. For `reduced_days` mode, set `sub.ends_at = now + target_days`
         (more days on cheaper plan / fewer days on expensive plan).
         For `same_duration` mode, leave `ends_at` alone.
      3. Write exactly one `WalletLedger` row with `amount = scenario.
         amount` (which is ≥ 0 under v87 policy). For zero amount we
         write no ledger entry at all.
      4. Apply the plan's new quotas via `_apply_quotas`.

    Any pending invoice for the case is flipped to settled
    automatically. The subscriber receives an `applied` notification.

    Refuses (raises `ValueError`) if a downgrade is requested via
    `same_duration` mode — that combo is forbidden by policy.
    """
    if not case:
        return {}
    now = _now(now)
    scenario = scenario or quote_same_duration(case, now=now)
    target = scenario_target_plan(case, scenario)
    tenant = (
        TenantAccount.query.get(case.tenant_id)
        if getattr(case, 'tenant_id', None) else None
    )
    if not (tenant and target):
        raise ValueError('apply_request requires resolvable tenant + target plan')
    # v87 — refuse the forbidden combo defensively. The subscriber UI
    # already hides this option, but a stale form post or a future
    # mobile client must not be able to bypass it.
    if (
        scenario.mode == PRICING_MODE_SAME_DURATION
        and scenario.policy_kind == POLICY_DOWNGRADE
    ):
        raise ValueError(
            'plan_change policy: same_duration downgrade is not allowed '
            '(would imply a refund). Use reduced_days conversion path.'
        )
    from .billing_engine import (
        _latest_subscription, _apply_quotas, _write_ledger,
        _append_note, _plan_label as _be_plan_label, _resolve_currency,
        REF_PLAN_CHANGE,
    )
    from datetime import timedelta
    sub = _latest_subscription(tenant)
    if not sub:
        # Edge case: no prior sub. Defer to billing_engine.activate
        # which writes the inception ledger entry.
        from .billing_engine import activate as _activate
        be_result = _activate(
            tenant, target, actor_user_id=actor_user_id,
            now=now, commit=False,
        )
        _settle_pending_invoice(case, actor_user_id, scenario)
        case.status = STATUS_RESOLVED
        case.is_frozen = True
        case.updated_at = now
        if commit:
            db.session.commit()
        out = be_result.to_dict()
        out['scenario'] = scenario.to_dict()
        out['case_status'] = case.status
        return out
    current_plan = SubscriptionPlan.query.get(sub.plan_id) if sub.plan_id else None
    # Apply the plan switch directly.
    tenant.plan_id = target.id
    tenant.status = 'active'
    sub.plan_id = target.id
    sub.status = 'active'
    sub.updated_at = now
    if scenario.mode == PRICING_MODE_REDUCED_DAYS:
        # Conversion path — `target_days` is authoritative regardless
        # of upgrade/downgrade direction.
        sub.ends_at = now + timedelta(days=int(scenario.target_days))
    # For same_duration mode we deliberately leave `ends_at` alone.
    _append_note(
        sub,
        f'Plan changed (v87 policy): {_be_plan_label(current_plan)} → '
        f'{_be_plan_label(target)} (mode={scenario.mode}, '
        f'days={scenario.target_days}, policy={scenario.policy_kind}, '
        f'amount={scenario.amount:+.2f})',
    )
    _apply_quotas(tenant, target)
    currency = _resolve_currency(
        getattr(target, 'currency', None),
        getattr(current_plan, 'currency', None),
    )
    ledger = None
    ledger_amount = round(float(scenario.amount or 0.0), 2)
    if ledger_amount >= 0.01:
        # Subscriber owes money — write a debit ledger row that
        # matches the scenario exactly. Settled when the invoice is
        # settled or paid through Stripe.
        ledger = _write_ledger(
            tenant_id=tenant.id, actor_user_id=actor_user_id,
            amount=ledger_amount, entry_type='debit', currency=currency,
            note=(
                f'Plan change applied (v87): '
                f'{_be_plan_label(current_plan)} → {_be_plan_label(target)} '
                f'(mode={scenario.mode}, days={scenario.target_days})'
            ),
            reference=f'{REF_PLAN_CHANGE}-{tenant.id}-{case.id}',
            category='plan_change',
        )
    # Zero-amount paths intentionally skip the ledger — there's no
    # money movement to record. The audit row below carries the full
    # scenario for traceability.
    _settle_pending_invoice(case, actor_user_id, scenario)
    case.status = STATUS_RESOLVED
    case.is_frozen = True
    case.updated_at = now
    # v93 — subscriber-facing message rewritten in consistent 2nd
    # person. The old wording mixed "اشتراكك" (you) and "المشترك"
    # (he/she) which looked awkward, especially when the same user
    # was both admin and subscriber.
    target_label_ar = _plan_label(target)
    parts_ar = [f'تم تحويل اشتراكك إلى {target_label_ar}.']
    if scenario.target_days:
        parts_ar.append(f'تبقى لك {scenario.target_days} يوماً.')
    if scenario.amount and scenario.amount > 0.01:
        parts_ar.append(
            f'المبلغ المُسوّى: {scenario.amount:.2f} {scenario.currency}.'
        )
    subscriber_message = ' '.join(parts_ar)
    _notify_subscriber(
        case,
        event_type=EVENT_APPLIED,
        title='تم تطبيق طلب تغيير الخطة',
        message=subscriber_message,
        actor_user_id=actor_user_id,
    )
    # v93 — also fan out an admin-perspective notification ("subscriber
    # X applied the plan change"). The subscriber message above is
    # written for the subscriber; the admin needs a 3rd-person
    # version that names the subscriber.
    try:
        from .support_ops import notify_admins_of_plan_change_applied
        subscriber = (
            AppUser.query.get(case.user_id) if case.user_id else None
        )
        notify_admins_of_plan_change_applied(
            case,
            subscriber=subscriber,
            target_plan=target,
            scenario=scenario,
            commit=False,
        )
    except Exception:
        # Defensive — admin fanout failure must never undo the
        # subscriber-facing apply.
        import logging as _logging
        _logging.getLogger(__name__).exception(
            'admin fanout for plan-change apply failed'
        )
    _audit(
        case, 'plan_change.apply',
        f'Applied via {scenario.mode}/{scenario.policy_kind} → '
        f'{_plan_label(target)}',
        actor_user_id=actor_user_id,
        details={
            'scenario': scenario.to_dict(),
            'ledger_entry_id': getattr(ledger, 'id', None),
            'final_ends_at': sub.ends_at.isoformat() if sub.ends_at else None,
        },
    )
    db.session.flush()
    if commit:
        db.session.commit()
    return {
        'action': 'change_plan',
        'tenant_id': tenant.id,
        'plan_id': target.id,
        'subscription_id': sub.id,
        'amount': ledger_amount,
        'currency': currency,
        'ledger_entry_id': getattr(ledger, 'id', None),
        'scenario': scenario.to_dict(),
        'case_status': case.status,
    }


def mark_invoice_settled(case: SupportCase, *, actor_user_id: int | None, note: str = '', commit: bool = True) -> dict:
    """v85: admin-side action that records "subscriber paid the
    invoice" without applying the plan change yet.

    Flips the case status from `payment_requested` → `payment_settled`
    and writes an audit row referencing the pending invoice. Does
    NOT yet write a counter-credit — that's correct because the
    pending debit IS the obligation; settlement is recorded by:

      * an `AdminActivityLog` / `SupportAuditLog` row showing
        "subscriber paid out-of-band"
      * the `plan_change_pending` ledger row staying in place until
        `apply_request` settles it (category → `plan_change`).

    A future payment-gateway webhook is the natural caller for this
    helper. For v85 it's surfaced as a manual admin action so
    operators can record receipts they've confirmed out-of-band.
    """
    if not case:
        return {}
    pending = find_pending_invoice(case)
    case.status = STATUS_PAYMENT_SETTLED
    case.updated_at = datetime.utcnow()
    _audit(
        case, 'plan_change.invoice_settled_pending_apply',
        'Invoice marked as settled by admin; awaiting plan apply',
        actor_user_id=actor_user_id,
        details={
            'invoice_reference': getattr(pending, 'reference', None),
            'invoice_id': getattr(pending, 'id', None),
            'note': note,
        },
    )
    # Subscriber notification: receipt acknowledgement.
    _notify_subscriber(
        case,
        event_type='plan_change_invoice_settled',
        title='تم استلام الدفعة',
        message=(
            'تم تأكيد استلام الدفعة لطلب تغيير الخطة. '
            'سيتم تطبيق التغيير قريباً.'
        ),
        actor_user_id=actor_user_id,
    )
    if commit:
        db.session.commit()
    return {
        'case_status': case.status,
        'invoice_reference': getattr(pending, 'reference', None),
    }


def reject_request(case: SupportCase, *, actor_user_id: int | None, reason: str = '', commit: bool = True) -> dict:
    """Close the request without applying it. Any pending invoice is
    reversed by a counter-credit so accounting nets out cleanly."""
    if not case:
        return {}
    reversal = _reverse_pending_invoice(case, actor_user_id, reason or 'rejected')
    case.status = STATUS_CLOSED
    case.is_frozen = True
    case.updated_at = datetime.utcnow()
    _notify_subscriber(
        case,
        event_type=EVENT_REJECTED,
        title='تعذّر تطبيق طلب تغيير الخطة',
        message=(
            ('لم تتم الموافقة على الطلب. ' + reason).strip()
            if reason else 'لم تتم الموافقة على طلب تغيير الخطة.'
        ),
        actor_user_id=actor_user_id,
    )
    _audit(
        case, 'plan_change.reject',
        f'Rejected request ({reason or "no reason given"})',
        actor_user_id=actor_user_id,
        details={'reason': reason, 'reversal_id': getattr(reversal, 'id', None)},
    )
    if commit:
        db.session.commit()
    return {'case_status': case.status, 'reversal_id': getattr(reversal, 'id', None)}


def cancel_request(case: SupportCase, *, actor_user_id: int | None, reason: str = '', commit: bool = True) -> dict:
    """Close without notifying the subscriber. Used for duplicates /
    operator clean-up. Any pending invoice is reversed."""
    if not case:
        return {}
    reversal = _reverse_pending_invoice(case, actor_user_id, reason or 'cancelled')
    case.status = STATUS_CANCELLED
    case.is_frozen = True
    case.updated_at = datetime.utcnow()
    _audit(
        case, 'plan_change.cancel',
        f'Admin cancelled request ({reason or "operator cleanup"})',
        actor_user_id=actor_user_id,
        details={'reason': reason, 'reversal_id': getattr(reversal, 'id', None)},
    )
    if commit:
        db.session.commit()
    return {'case_status': case.status, 'reversal_id': getattr(reversal, 'id', None)}


def scenario_target_plan(case: SupportCase, scenario: Scenario | None) -> SubscriptionPlan | None:
    """Resolve the target plan for a scenario. Falls back to parsing
    the case subject when the scenario object didn't carry an id."""
    from .support_ops import extract_plan_change_target_plan
    return extract_plan_change_target_plan(case)


# ── Queue / counts ───────────────────────────────────────────────────


def open_request_count() -> int:
    """Total plan-change requests still awaiting an outcome — used
    by the sidebar badge."""
    return (
        SupportCase.query
        .filter_by(case_type='plan_change_request')
        .filter(SupportCase.status.in_(tuple(ACTIVE_STATUSES)))
        .count()
    )


def workbench_queue(*, status: str | None = None, limit: int = 200) -> list[SupportCase]:
    """Return plan-change requests for the admin queue, ordered by
    most-recent activity. Pass a single ``status`` to filter the
    queue (used by the KPI band tabs)."""
    q = SupportCase.query.filter_by(case_type='plan_change_request')
    if status and status != 'all':
        q = q.filter(SupportCase.status == status)
    return (
        q.order_by(SupportCase.updated_at.desc(), SupportCase.id.desc())
        .limit(limit)
        .all()
    )


def case_audit_history(case: SupportCase, *, limit: int = 50) -> list[SupportAuditLog]:
    """Return the audit trail for a case, newest first. Used by the
    workbench detail panel."""
    return (
        SupportAuditLog.query
        .filter_by(case_type=case.case_type, source_id=case.source_id)
        .order_by(SupportAuditLog.created_at.desc(), SupportAuditLog.id.desc())
        .limit(limit)
        .all()
    )


def workbench_detail_url(case_id: int, lang: str = 'ar') -> str:
    """Single source of truth for the detail page path so admin
    notification fanout and the sidebar use the same URL pattern."""
    from flask import url_for
    return url_for(
        'billing.admin_plan_change_request_detail',
        case_id=case_id, lang=lang,
    )
