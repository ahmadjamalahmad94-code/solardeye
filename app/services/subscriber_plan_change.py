"""v85 — subscriber-driven plan-change flow.

A thin orchestration layer that lets a subscriber be the primary
decision-maker for their plan change while preserving the accounting
precision and admin traceability v81/v82 already built.

Two operations:

  preview(user, target_plan_id)
      Pure read. Returns both scenario calculations + plan + sub
      facts. NEVER creates a case, NEVER mutates balances, NEVER
      writes audit rows. Safe to call repeatedly from the
      subscriber UI.

  confirm(user, target_plan_id, mode, desired_target_days)
      The subscriber commits to a scenario. Atomically:
        * Creates or reuses a `SupportCase(case_type='plan_change_request')`
          anchored to the subscriber.
        * Dispatches to one of three execution paths:

            mode='reduced_days'         → execute immediately via
                                          billing_engine.change_plan
                                          + shorten ends_at.
                                          Status → `resolved`.

            mode='same_duration' &      → create payment-request
              amount > 0                  invoice via workbench
                                          issue_invoice.
                                          Status → `payment_requested`.

            mode='same_duration' &      → execute immediately (no
              amount ≤ 0                  money owed; nothing to bill).
                                          Status → `resolved`.

      Returns a `ConfirmResult` dataclass with all fields the route
      handler / mobile API client needs to render the outcome.

Design invariants
─────────────────
* **Backend is the source of truth for pricing.** The caller only
  passes IDs (`target_plan_id`) + the chosen mode + an optional
  reduced-days override. Amount-due is always computed server-side
  from `SubscriptionPlan` rows.
* **No mutation on preview.** Verified by tests; the function only
  reads from `SubscriptionPlan` / `TenantSubscription`.
* **Every confirm path writes a full audit trail.** The case carries
  the scenario, billing_engine writes the ledger entry, the workbench
  audit_case helper records the subscriber-driven decision.
* **Admin notification is informational, not blocking.** The default
  flow does NOT require admin approval. Admin is monitor/audit/
  exception handler.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..extensions import db
from ..models import AppUser, SubscriptionPlan, SupportCase, TenantAccount
from . import plan_change_workbench as wb

logger = logging.getLogger(__name__)


# ── Result shapes ───────────────────────────────────────────────────


@dataclass
class PreviewResult:
    """Pure-data preview surface. Both scenarios are computed and
    returned even when one would be ineligible — the UI decides
    what to show. Carries the resolved target plan + current plan
    + current subscription identifiers so the template can render
    the full breakdown without a second query.

    v87 — `policy_kind` is one of `upgrade`/`downgrade`/`lateral`
    and tells the UI which path is primary:
      * `downgrade` → reduced_days (conversion to more days) is the
        only offered subscriber path; same_duration is marked
        `is_eligible=False` and must not be shown as a CTA.
      * `upgrade` → both scenarios are eligible; same_duration is
        option A (keep days + pay), reduced_days is option B
        (accept fewer days + no payment).
      * `lateral` → same_duration is the primary path; reduced_days
        is shown only for completeness.
    """
    target_plan_id: int
    target_plan_label: str
    current_plan_id: Optional[int]
    current_plan_label: str
    remaining_days: int
    currency: str
    same_duration: dict[str, Any]
    reduced_days: dict[str, Any]
    can_apply_directly: bool
    blocked_reason: Optional[str] = None
    policy_kind: str = 'lateral'

    def to_dict(self) -> dict[str, Any]:
        return {
            'target_plan_id': self.target_plan_id,
            'target_plan_label': self.target_plan_label,
            'current_plan_id': self.current_plan_id,
            'current_plan_label': self.current_plan_label,
            'remaining_days': self.remaining_days,
            'currency': self.currency,
            'same_duration': self.same_duration,
            'reduced_days': self.reduced_days,
            'can_apply_directly': self.can_apply_directly,
            'blocked_reason': self.blocked_reason,
            'policy_kind': self.policy_kind,
        }


@dataclass
class ConfirmResult:
    """Outcome of a confirm() call. The route handler renders the
    `outcome` value as the UI state:

      * `'applied'`           — plan switched immediately
      * `'payment_required'`  — invoice issued, awaiting payment
      * `'blocked'`           — refused (safety/validation)
    """
    outcome: str
    case_id: Optional[int]
    case_status: Optional[str]
    target_plan_id: Optional[int]
    scenario_mode: Optional[str]
    amount: float
    currency: str
    invoice_reference: Optional[str] = None
    ledger_entry_id: Optional[int] = None
    blocked_reason: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'outcome': self.outcome,
            'case_id': self.case_id,
            'case_status': self.case_status,
            'target_plan_id': self.target_plan_id,
            'scenario_mode': self.scenario_mode,
            'amount': round(self.amount, 2),
            'currency': self.currency,
            'invoice_reference': self.invoice_reference,
            'ledger_entry_id': self.ledger_entry_id,
            'blocked_reason': self.blocked_reason,
            **self.extra,
        }


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_subscriber_context(user: AppUser):
    """Returns `(tenant, current_sub, current_plan)` for a subscriber
    or `(None, None, None)` if anything is missing — never raises."""
    if not user or getattr(user, 'is_admin', False):
        return None, None, None
    tenant_id = getattr(user, 'tenant_id', None)
    if not tenant_id:
        return None, None, None
    tenant = TenantAccount.query.get(tenant_id)
    if not tenant:
        return None, None, None
    from ..models import TenantSubscription
    sub = (
        TenantSubscription.query
        .filter_by(tenant_id=tenant.id)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )
    current_plan = (
        SubscriptionPlan.query.get(sub.plan_id) if sub and sub.plan_id else None
    )
    return tenant, sub, current_plan


def _build_synthetic_case(user: AppUser, target_plan: SubscriptionPlan, status: str = wb.STATUS_OPEN, *, subject: str | None = None, commit: bool = False) -> SupportCase:
    """Anchor a `SupportCase` for this confirm via find-or-reuse.

    v88c — ROOT CAUSE FIX. The database carries a UNIQUE INDEX on
    `(case_type, source_id)` (see `_ensure_database_indexes` in
    `app/__init__.py`), which means each user can only have ONE
    `plan_change_request` row in the `support_case` table — period,
    regardless of status. Inserting a second row with the same
    `(case_type, source_id)` raises `IntegrityError` and 500s the
    confirm route.

    Previously this function did a raw INSERT every time, relying
    on `_cancel_prior_open_cases` to "clean up". But that helper
    only flips `status` to `'cancelled'`; the rows stay in place,
    so the UNIQUE INDEX is never freed.

    The correct pattern (matching `support_ops.audit_case`'s lookup
    behavior) is **find-or-reuse**: if a row with the same
    `(case_type='plan_change_request', source_id=user.id)` already
    exists, reset its fields (subject, status, priority, frozen
    flag, updated_at) and reuse it. Otherwise, insert a new row.

    This:
      * Respects the UNIQUE INDEX — no IntegrityError.
      * Preserves `case.id` across multiple confirms, so the
        audit history accumulates on the same case row instead of
        scattering across orphan rows.
      * Keeps the "one active plan-change case per subscriber"
        invariant the index was designed to enforce.
    """
    tenant_id = getattr(user, 'tenant_id', None)
    plan_label = (
        getattr(target_plan, 'name_ar', None)
        or getattr(target_plan, 'name_en', None)
        or getattr(target_plan, 'code', None)
        or f'plan-{target_plan.id}'
    )
    final_subject = subject or f'طلب تغيير الخطة إلى {plan_label}'
    existing = SupportCase.query.filter_by(
        case_type='plan_change_request',
        source_id=user.id,
    ).first()
    if existing is not None:
        # Recycle the existing row. We deliberately reset
        # `is_frozen` so a previously-resolved/closed case can be
        # reopened by a fresh subscriber-driven confirm.
        existing.tenant_id = tenant_id
        existing.user_id = user.id
        existing.subject = final_subject
        existing.priority = 'normal'
        existing.status = status
        existing.is_frozen = False
        existing.updated_at = datetime.utcnow()
        db.session.flush()
        if commit:
            db.session.commit()
        return existing
    case = SupportCase(
        case_type='plan_change_request',
        source_id=user.id,
        tenant_id=tenant_id,
        user_id=user.id,
        subject=final_subject,
        priority='normal',
        status=status,
    )
    db.session.add(case)
    db.session.flush()
    if commit:
        db.session.commit()
    return case


def _cancel_prior_open_cases(user: AppUser) -> int:
    """Mark prior open subscriber-side plan-change cases as
    `cancelled` so the queue stays clean when the subscriber starts
    a fresh confirm. Returns the count cancelled (informational)."""
    if not user:
        return 0
    rows = SupportCase.query.filter_by(
        user_id=user.id, case_type='plan_change_request',
    ).filter(
        SupportCase.status.in_((
            wb.STATUS_OPEN, wb.STATUS_UNDER_REVIEW,
            wb.STATUS_AWAITING_SUBSCRIBER,
        )),
    ).all()
    for r in rows:
        r.status = wb.STATUS_CANCELLED
        r.updated_at = datetime.utcnow()
    return len(rows)


# ── Public API ─────────────────────────────────────────────────────


def preview(user: AppUser, target_plan_id: int, *, now: Optional[datetime] = None) -> PreviewResult:
    """Return both scenarios for the (user, target_plan) pair.

    Pure read. No mutation. Safe to render multiple times.

    `now` is exposed for tests so the prorated math is
    deterministic; route handlers leave it `None` and the
    workbench falls back to `datetime.utcnow()`.

    `blocked_reason` is populated when the call can't produce a
    meaningful preview (no tenant, target plan missing/inactive,
    target plan == current plan). The UI should branch on this
    field before showing scenario cards.
    """
    tenant, sub, current_plan = _resolve_subscriber_context(user)
    target_plan = SubscriptionPlan.query.get(int(target_plan_id)) if target_plan_id else None
    if not tenant or not sub:
        return PreviewResult(
            target_plan_id=int(target_plan_id or 0),
            target_plan_label='—',
            current_plan_id=None,
            current_plan_label='—',
            remaining_days=0, currency='USD',
            same_duration={}, reduced_days={},
            can_apply_directly=False,
            blocked_reason='no_active_subscription',
        )
    if not target_plan or not getattr(target_plan, 'is_active', True):
        return PreviewResult(
            target_plan_id=int(target_plan_id or 0),
            target_plan_label='—',
            current_plan_id=getattr(current_plan, 'id', None),
            current_plan_label=_label(current_plan),
            remaining_days=0, currency=_currency(current_plan),
            same_duration={}, reduced_days={},
            can_apply_directly=False,
            blocked_reason='target_plan_unavailable',
        )
    if current_plan and target_plan.id == current_plan.id:
        return PreviewResult(
            target_plan_id=target_plan.id,
            target_plan_label=_label(target_plan),
            current_plan_id=current_plan.id,
            current_plan_label=_label(current_plan),
            remaining_days=0, currency=_currency(current_plan),
            same_duration={}, reduced_days={},
            can_apply_directly=False,
            blocked_reason='same_plan_already_active',
        )
    # Build a transient (un-persisted) case object the workbench
    # quote helpers can read. We never commit this — it's only used
    # to feed the same scenario math the admin workbench uses.
    transient_case = SupportCase(
        case_type='plan_change_request',
        source_id=user.id,
        tenant_id=tenant.id,
        user_id=user.id,
        subject=f'preview:{user.id}:{target_plan.id}',
        status='preview',
    )
    same = wb.quote_same_duration(transient_case, target_plan=target_plan, now=now)
    reduced = wb.quote_reduced_days(transient_case, target_plan=target_plan, now=now)
    # Both scenarios carry the same `policy_kind`; surface it at the
    # top level so client code (HTML/JSON) doesn't need to peek
    # inside either dict to branch on policy.
    return PreviewResult(
        target_plan_id=target_plan.id,
        target_plan_label=_label(target_plan),
        current_plan_id=getattr(current_plan, 'id', None),
        current_plan_label=_label(current_plan),
        remaining_days=same.remaining_days,
        currency=same.currency,
        same_duration=same.to_dict(),
        reduced_days=reduced.to_dict(),
        can_apply_directly=True,
        policy_kind=same.policy_kind,
    )


def confirm(
    user: AppUser,
    target_plan_id: int,
    *,
    mode: str,
    desired_target_days: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    now: Optional[datetime] = None,
    commit: bool = True,
) -> ConfirmResult:
    """Subscriber commits to a scenario. Executes the right
    dispatch path based on the chosen mode + computed amount.

    `actor_user_id` defaults to `user.id` (the subscriber acts on
    their own account). The admin-side `mark_invoice_settled` /
    `apply_request` paths can call this with an explicit
    `actor_user_id` to attribute the decision to staff.
    """
    actor_user_id = actor_user_id if actor_user_id is not None else getattr(user, 'id', None)
    tenant, sub, current_plan = _resolve_subscriber_context(user)
    target_plan = SubscriptionPlan.query.get(int(target_plan_id)) if target_plan_id else None
    if not tenant or not sub:
        return ConfirmResult(
            outcome='blocked', case_id=None, case_status=None,
            target_plan_id=int(target_plan_id or 0), scenario_mode=mode,
            amount=0.0, currency='USD',
            blocked_reason='no_active_subscription',
        )
    if not target_plan or not getattr(target_plan, 'is_active', True):
        return ConfirmResult(
            outcome='blocked', case_id=None, case_status=None,
            target_plan_id=int(target_plan_id or 0), scenario_mode=mode,
            amount=0.0, currency=_currency(current_plan),
            blocked_reason='target_plan_unavailable',
        )
    if current_plan and target_plan.id == current_plan.id:
        return ConfirmResult(
            outcome='blocked', case_id=None, case_status=None,
            target_plan_id=target_plan.id, scenario_mode=mode,
            amount=0.0, currency=_currency(current_plan),
            blocked_reason='same_plan_already_active',
        )
    if mode not in (wb.PRICING_MODE_SAME_DURATION, wb.PRICING_MODE_REDUCED_DAYS):
        return ConfirmResult(
            outcome='blocked', case_id=None, case_status=None,
            target_plan_id=target_plan.id, scenario_mode=mode,
            amount=0.0, currency=_currency(current_plan),
            blocked_reason='unknown_pricing_mode',
        )
    # v87 — policy preflight. We classify the change before creating
    # a case so we can refuse a forbidden combo without polluting the
    # admin queue with cancelled rows.
    policy_kind = wb.classify_change(current_plan, target_plan)
    if (
        mode == wb.PRICING_MODE_SAME_DURATION
        and policy_kind == wb.POLICY_DOWNGRADE
    ):
        return ConfirmResult(
            outcome='blocked', case_id=None, case_status=None,
            target_plan_id=target_plan.id, scenario_mode=mode,
            amount=0.0, currency=_currency(current_plan),
            blocked_reason='downgrade_same_duration_not_allowed',
            extra={'policy_kind': policy_kind},
        )
    # Cancel prior open subscriber-side cases so the queue stays
    # clean. The new confirm gets its own fresh case.
    _cancel_prior_open_cases(user)
    plan_label = _label(target_plan)
    case = _build_synthetic_case(
        user, target_plan,
        status=wb.STATUS_UNDER_REVIEW,
        subject=f'طلب تغيير الخطة إلى {plan_label}',
    )
    # v92g — subscriber + admin "تم استلام الطلب" notifications.
    # Subscriber gets a calm "we received your request" event so
    # they have a record of the submission in their bell even
    # before the apply / payment-request step finishes. Admins
    # get the standard plan-change fanout so the workbench queue
    # surfaces the new request alongside the legacy mobile path.
    # Both fanouts are wrapped defensively — a notification
    # failure must never block the actual plan-change apply.
    try:
        wb._notify_subscriber(
            case,
            event_type='plan_change_request_received',
            title='تم استلام طلب تغيير الخطة',
            message=f'استلمنا طلبك لتغيير الخطة إلى {plan_label}. '
                    'سنحدّثك فور إكمال الخطوة التالية (دفع أو تطبيق).',
            actor_user_id=actor_user_id,
        )
    except Exception:
        logger.exception('subscriber receipt notification failed')
    try:
        from .support_ops import notify_admins_of_plan_change_request
        notify_admins_of_plan_change_request(
            case,
            requester=user,
            target_plan=target_plan,
            commit=False,
        )
    except Exception:
        logger.exception('admin fanout for plan-change submission failed')
    # Compute the canonical scenario AFTER the case is anchored —
    # the workbench math is identical to the preview but now lives
    # in the audit trail.
    scenario = wb.select_scenario(
        case, mode=mode, target_plan=target_plan,
        desired_target_days=desired_target_days,
        now=now,
    )
    # Dispatch.
    amount = float(scenario.amount or 0.0)
    if mode == wb.PRICING_MODE_REDUCED_DAYS:
        # Reduced-days is direct execution: the subscriber explicitly
        # opted out of paying the full difference by accepting fewer
        # days on the target plan. We apply immediately + record any
        # incidental credit/debit through the billing engine.
        wb._audit(
            case, 'plan_change.subscriber_chose_reduced_days',
            f'Subscriber chose reduced-days → {scenario.target_days}d on {plan_label}',
            actor_user_id=actor_user_id,
            details={'scenario': scenario.to_dict()},
        )
        result = wb.apply_request(
            case, actor_user_id=actor_user_id,
            scenario=scenario, now=now, commit=False,
        )
        if commit:
            db.session.commit()
        return ConfirmResult(
            outcome='applied',
            case_id=case.id, case_status=case.status,
            target_plan_id=target_plan.id, scenario_mode=mode,
            amount=amount, currency=scenario.currency,
            ledger_entry_id=result.get('ledger_entry_id') if isinstance(result, dict) else None,
            extra={
                'target_days': scenario.target_days,
                'free_target_days': scenario.extra.get('free_target_days'),
            },
        )
    # mode == same_duration
    if amount > 0.01:
        # Subscriber owes money — create an invoice, do NOT apply
        # the plan change yet. The admin workbench (or a future
        # payment webhook) flips status to `resolved` once the
        # invoice settles via apply_request().
        wb._audit(
            case, 'plan_change.subscriber_chose_same_duration',
            f'Subscriber chose same-duration → owes {amount:.2f} {scenario.currency}',
            actor_user_id=actor_user_id,
            details={'scenario': scenario.to_dict()},
        )
        invoice = wb.issue_invoice(
            case, actor_user_id=actor_user_id, scenario=scenario, commit=False,
        )
        if commit:
            db.session.commit()
        return ConfirmResult(
            outcome='payment_required',
            case_id=case.id, case_status=case.status,
            target_plan_id=target_plan.id, scenario_mode=mode,
            amount=amount, currency=scenario.currency,
            invoice_reference=getattr(invoice, 'reference', None),
            ledger_entry_id=getattr(invoice, 'id', None),
        )
    # Same-duration with zero or credit → execute directly. There's
    # no money to bill, only an optional refund credit landing in
    # the wallet (handled by billing_engine.change_plan).
    wb._audit(
        case, 'plan_change.subscriber_chose_same_duration',
        f'Subscriber chose same-duration → {amount:+.2f} {scenario.currency}',
        actor_user_id=actor_user_id,
        details={'scenario': scenario.to_dict()},
    )
    result = wb.apply_request(
        case, actor_user_id=actor_user_id,
        scenario=scenario, now=now, commit=False,
    )
    if commit:
        db.session.commit()
    return ConfirmResult(
        outcome='applied',
        case_id=case.id, case_status=case.status,
        target_plan_id=target_plan.id, scenario_mode=mode,
        amount=amount, currency=scenario.currency,
        ledger_entry_id=result.get('ledger_entry_id') if isinstance(result, dict) else None,
    )


# ── Small label helpers ────────────────────────────────────────────


def _label(plan: SubscriptionPlan | None) -> str:
    if not plan:
        return '—'
    return (
        getattr(plan, 'name_ar', None)
        or getattr(plan, 'name_en', None)
        or getattr(plan, 'code', None)
        or f'plan-{getattr(plan, "id", "")}'
    )


def _currency(plan: SubscriptionPlan | None) -> str:
    if not plan:
        return 'USD'
    return (getattr(plan, 'currency', None) or 'USD').strip() or 'USD'
