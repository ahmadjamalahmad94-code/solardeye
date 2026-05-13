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
    amount: float  # signed: + → subscriber owes; − → subscriber credited
    currency: str
    summary_ar: str
    summary_en: str
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
    """Append a structured audit row tied to the case."""
    db.session.add(SupportAuditLog(
        case_type=case.case_type,
        source_id=case.source_id,
        actor_user_id=actor_user_id,
        action=action,
        summary=summary[:255],
        details_json=json.dumps(details or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    ))


def _notify_subscriber(
    case: SupportCase, *, event_type: str, title: str, message: str,
    actor_user_id: int | None = None,
) -> NotificationEvent | None:
    """Push a NotificationEvent to the subscriber owning the case.
    Returns the persisted instance or `None` when the case has no
    user attached."""
    user_id = getattr(case, 'user_id', None)
    if not user_id:
        return None
    ev = NotificationEvent(
        event_type=event_type,
        target_user_id=int(user_id),
        tenant_id=getattr(case, 'tenant_id', None),
        source_type='plan_change_request',
        source_id=case.id,
        title=title[:220],
        message=message,
        direct_url='/account/subscription',
        status='new',
        created_at=datetime.utcnow(),
    )
    db.session.add(ev)
    return ev


# ── Scenarios ────────────────────────────────────────────────────────


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
    """Scenario A — preserve the remaining period; charge or credit
    the prorated difference.

    Formula (identical to v81 / billing_engine.change_plan):
        current_remaining_value = (remaining/cycle_current) × current_price
        target_remaining_value  = (remaining/cycle_target)  × target_price
        amount = target_remaining_value - current_remaining_value
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
    amount = round(tgt_rv - cur_rv, 2)
    if amount > 0:
        summary_ar = (
            f'يحتفظ المشترك بنفس عدد الأيام المتبقّية ({remaining}). '
            f'فرق السعر المستحق: {amount:.2f} {ctx["currency"]}.'
        )
        summary_en = (
            f'Subscriber keeps the same remaining days ({remaining}). '
            f'Extra due: {amount:.2f} {ctx["currency"]}.'
        )
    elif amount < 0:
        summary_ar = (
            f'يحتفظ المشترك بنفس عدد الأيام المتبقّية ({remaining}). '
            f'رصيد للمشترك: {abs(amount):.2f} {ctx["currency"]}.'
        )
        summary_en = (
            f'Subscriber keeps the same remaining days ({remaining}). '
            f'Credit due: {abs(amount):.2f} {ctx["currency"]}.'
        )
    else:
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
    )


def quote_reduced_days(case: SupportCase, *, target_plan: SubscriptionPlan | None = None, desired_target_days: int | None = None, now: datetime | None = None) -> Scenario:
    """Scenario B — keep the same remaining VALUE but on the target
    plan. The operator can optionally choose a specific number of
    target days (``desired_target_days``); when omitted, we compute
    the largest free swap.

    Math:
        target_per_day = target_price / cycle_days_target
        free_target_days = round(current_remaining_value / target_per_day)
        amount = (chosen_target_days - free_target_days) × target_per_day

    ``amount > 0`` → subscriber owes more (asked for more days).
    ``amount < 0`` → subscriber refunded (asked for fewer days).
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
    free_target_days = (
        int(round(cur_rv / target_per_day)) if target_per_day > 0 else 0
    )
    chosen = (
        int(desired_target_days)
        if desired_target_days is not None
        else free_target_days
    )
    chosen = max(chosen, 0)
    tgt_rv = round(chosen * target_per_day, 2)
    amount = round(tgt_rv - cur_rv, 2)
    if amount > 0:
        summary_ar = (
            f'الباقة الجديدة على {chosen} يوماً. مبلغ إضافي مستحق: '
            f'{amount:.2f} {ctx["currency"]}.'
        )
        summary_en = (
            f'Target plan for {chosen} day(s). Extra due: '
            f'{amount:.2f} {ctx["currency"]}.'
        )
    elif amount < 0:
        summary_ar = (
            f'الباقة الجديدة على {chosen} يوماً. رصيد للمشترك: '
            f'{abs(amount):.2f} {ctx["currency"]}.'
        )
        summary_en = (
            f'Target plan for {chosen} day(s). Credit due: '
            f'{abs(amount):.2f} {ctx["currency"]}.'
        )
    else:
        summary_ar = (
            f'تبادل مجاني — {chosen} يوماً على الباقة الجديدة دون مبلغ إضافي.'
        )
        summary_en = (
            f'Even swap — {chosen} day(s) on the target plan, no extra charge.'
        )
    return Scenario(
        mode=PRICING_MODE_REDUCED_DAYS,
        label_ar='تقليل الأيام على الباقة الجديدة',
        label_en='Reduce days on target plan',
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
        extra={'free_target_days': free_target_days, 'target_per_day_price': round(target_per_day, 4)},
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
    """Apply an approved plan-change request through the canonical
    billing engine.

    The scenario passed in determines the financial effect:
      * ``mode=same_duration`` → reuses ``billing_engine.change_plan``
        with the v81 reference token.
      * ``mode=reduced_days`` → applies the plan switch in-place
        but ALSO shortens the subscription's ``ends_at`` to
        ``now + scenario.target_days``.

    Any pending invoice for the case is flipped to settled
    automatically. The subscriber receives an `applied` notification.
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
    from .billing_engine import change_plan as _change_plan, extend as _extend
    from datetime import timedelta
    result = _change_plan(
        tenant, target,
        actor_user_id=actor_user_id,
        reference_token=f'PCH-{tenant.id}-{case.id}',
        now=now,
        commit=False,
    )
    # Reduced-days mode: shrink the surviving cycle to the chosen
    # target_days. Use the latest subscription row (which `change_plan`
    # mutated in-place) to set the new ``ends_at``.
    if scenario.mode == PRICING_MODE_REDUCED_DAYS:
        sub = (
            TenantSubscription.query
            .filter_by(tenant_id=tenant.id)
            .order_by(TenantSubscription.created_at.desc())
            .first()
        )
        if sub:
            sub.ends_at = now + timedelta(days=int(scenario.target_days))
            sub.updated_at = now
    # Settle any pending invoice tied to this case (flip category +
    # write a settlement audit row).
    _settle_pending_invoice(case, actor_user_id, scenario)
    # Mark resolved + notify subscriber.
    case.status = STATUS_RESOLVED
    case.is_frozen = True
    case.updated_at = now
    _notify_subscriber(
        case,
        event_type=EVENT_APPLIED,
        title='تم تطبيق طلب تغيير الخطة',
        message=(
            f'تم تحويل اشتراكك إلى {_plan_label(target)}. '
            f'{scenario.summary_ar}'
        ),
        actor_user_id=actor_user_id,
    )
    _audit(
        case, 'plan_change.apply',
        f'Applied via {scenario.mode} → {_plan_label(target)}',
        actor_user_id=actor_user_id,
        details={
            'scenario': scenario.to_dict(),
            'billing_result': result.to_dict(),
        },
    )
    if commit:
        db.session.commit()
    out = result.to_dict()
    out['scenario'] = scenario.to_dict()
    out['case_status'] = case.status
    return out


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
