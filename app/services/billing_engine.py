"""v82 — canonical subscription billing engine.

One service module owns every paid-change to a `TenantSubscription`
so the audit story is consistent across admin tools and the
subscriber-facing plan-change workflow:

  ┌──────────────────────┐
  │ admin / api / portal │──┐
  └──────────────────────┘  │
                            ▼
                  ┌─────────────────────┐
                  │  billing_engine.*   │  ── writes WalletLedger
                  │  (this module)      │  ── mutates TenantSubscription
                  └─────────────────────┘  ── re-applies plan quotas
                            │              ── returns an audit dict
                            ▼
                ┌──────────────────────┐
                │ persistent storage:  │
                │   TenantSubscription │
                │   WalletLedger       │
                │   TenantQuota        │
                └──────────────────────┘

Design principles
─────────────────
* **Every charge or credit has a ledger entry.** No silent mutations.
* **Every state transition is reversible from the ledger.** The
  ``reference`` field carries a stable token (``ACT-…``, ``REN-…``,
  ``EXT-…``, ``PCH-…``, ``REA-…``) so finance can reconstruct the
  exact action that produced any line.
* **Pro-ration is explicit, not hidden inside the helper.** Every
  lifecycle action returns an audit dict containing
  ``{amount, currency, basis, days, plan_id}`` so callers can show
  the operator exactly what was charged.
* **Trials never produce a ledger entry.** Subscribers don't pay
  for trial windows.
* **Cancellation does not refund.** The subscriber keeps access until
  ``ends_at``; only the status flips. A separate manual refund flow
  remains the operator's call.

v82 deliberately does NOT introduce a new schema table. The existing
``TenantSubscription``, ``WalletLedger`` and ``AdminActivityLog`` rows
cover the audit surface this engine needs. ``TenantSubscription.notes``
accumulates a human-readable trail and ``WalletLedger.reference`` is
the deterministic action token.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from ..extensions import db
from ..models import (
    AppUser, SubscriptionPlan, TenantAccount, TenantSubscription, WalletLedger,
)


# Stable reference prefixes — one per lifecycle action. Finance can
# bucket / filter / reconstruct from these tokens alone.
REF_ACTIVATE = 'ACT'
REF_RENEW = 'REN'
REF_EXTEND = 'EXT'
REF_PLAN_CHANGE = 'PCH'
REF_REACTIVATE = 'REA'


# ── Audit + result shape ─────────────────────────────────────────────


@dataclass
class BillingResult:
    """Return value of every lifecycle action.

    Always set:
      * ``action`` — `'activate'`, `'renew'`, `'extend'`, …
      * ``tenant_id``
      * ``plan_id`` (the plan the subscriber is on AFTER the action)
      * ``subscription_id`` (the active sub row's id AFTER the action)
      * ``amount`` (signed; positive = subscriber charged,
                    negative = subscriber credited, 0 = no money moved)
      * ``currency``
      * ``ledger_entry_id`` (None when no money moved)
      * ``basis`` — human-readable explanation of how ``amount`` was
                    derived. Surfaced verbatim on admin screens.
    """

    action: str
    tenant_id: int
    plan_id: Optional[int]
    subscription_id: Optional[int]
    amount: float
    currency: str
    ledger_entry_id: Optional[int]
    basis: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'action': self.action,
            'tenant_id': self.tenant_id,
            'plan_id': self.plan_id,
            'subscription_id': self.subscription_id,
            'amount': round(self.amount, 2),
            'currency': self.currency,
            'ledger_entry_id': self.ledger_entry_id,
            'basis': self.basis,
            **self.extra,
        }


# ── Internal helpers ─────────────────────────────────────────────────


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.utcnow()


def _plan_label(plan: SubscriptionPlan | None) -> str:
    if not plan:
        return '—'
    return (
        getattr(plan, 'name_en', None)
        or getattr(plan, 'name_ar', None)
        or getattr(plan, 'code', None)
        or f'plan-{getattr(plan, "id", "")}'
    )


def _plan_cycle_days(plan: SubscriptionPlan | None) -> int:
    """Return the canonical cycle length for a plan, with a safe
    floor of 1 so we never divide by zero. Defaults to 30 when the
    plan didn't ship a value."""
    if plan is None:
        return 30
    raw = int(getattr(plan, 'duration_days_default', 30) or 30)
    return max(raw, 1)


def _resolve_currency(*candidates) -> str:
    """First non-empty currency among ``candidates``, defaulting to
    ``'USD'``."""
    for c in candidates:
        if c:
            s = str(c).strip()
            if s:
                return s
    return 'USD'


def _append_note(sub: TenantSubscription, line: str) -> None:
    """Append a single audit line to ``sub.notes`` without losing
    the prior trail. Defensive against non-string `notes` so tests
    that use a `mock.Mock()` sub don't trip on ``Mock.rstrip()``."""
    if not line:
        return
    current = getattr(sub, 'notes', None)
    if isinstance(current, str) and current:
        sub.notes = (current.rstrip() + '\n' + line).strip()
    else:
        sub.notes = line


def _write_ledger(
    *, tenant_id: int, actor_user_id: int | None, amount: float,
    entry_type: str, currency: str, note: str, reference: str,
    category: str,
) -> WalletLedger | None:
    """Add and flush a WalletLedger row, returning the persisted
    instance. Returns ``None`` when ``amount`` rounds to 0 (we don't
    pollute finance with no-op entries)."""
    if abs(amount) < 0.01:
        return None
    entry = WalletLedger(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        entry_type=entry_type,
        amount=round(abs(amount), 2),
        currency=currency,
        note=note,
        reference=reference,
        category=category,
        is_recurring=False,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def _apply_quotas(tenant: TenantAccount, plan: SubscriptionPlan | None) -> None:
    """Re-apply plan-derived quotas so the new plan's limits take
    effect immediately. Manual / override quota rows are preserved
    (`apply_plan_quotas_to_tenant` only touches `source='plan'` rows)."""
    if not tenant or not plan:
        return
    try:
        from .quota_engine import apply_plan_quotas_to_tenant
        apply_plan_quotas_to_tenant(tenant, plan, commit=False)
    except Exception:
        # Quota helper failures must never block a billing action.
        # Finance + sub state are the source of truth; quotas are a
        # second-tier projection.
        pass


def _latest_subscription(tenant: TenantAccount) -> TenantSubscription | None:
    return (
        TenantSubscription.query
        .filter_by(tenant_id=tenant.id)
        .order_by(TenantSubscription.created_at.desc())
        .first()
    )


# ── Lifecycle actions ────────────────────────────────────────────────


def activate(
    tenant: TenantAccount,
    plan: SubscriptionPlan,
    *,
    days: int | None = None,
    actor_user_id: int | None = None,
    notes: str = '',
    activation_mode: str = 'manual',
    now: datetime | None = None,
    commit: bool = True,
) -> BillingResult:
    """First-time / standalone activation.

    Creates a fresh ``TenantSubscription`` row at ``[now, now+days]``,
    flips ``tenant.plan_id`` and ``tenant.status``, re-applies plan
    quotas, writes a full-price ledger debit (skipped when the plan
    is free).

    For trial activations pass ``activation_mode='trial'`` — the
    ledger entry is skipped automatically because the cycle is free.
    """
    if tenant is None or plan is None:
        raise ValueError('activate requires both tenant and plan')
    cycle = int(days or _plan_cycle_days(plan))
    started = _now(now)
    ends = started + timedelta(days=cycle)
    is_trial = activation_mode == 'trial'
    sub = TenantSubscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status='trial' if is_trial else 'active',
        activation_mode=activation_mode,
        starts_at=started,
        trial_ends_at=ends if is_trial else None,
        ends_at=ends,
        activated_by_user_id=actor_user_id,
        notes=notes or (
            f'Activated {_plan_label(plan)} ({cycle}d)'
            if not is_trial else
            f'Trial {_plan_label(plan)} ({cycle}d)'
        ),
    )
    tenant.plan_id = plan.id
    tenant.status = 'trial' if is_trial else 'active'
    db.session.add(sub)
    _apply_quotas(tenant, plan)
    db.session.flush()
    currency = _resolve_currency(getattr(plan, 'currency', None))
    price = float(getattr(plan, 'price', 0) or 0)
    amount = 0.0 if is_trial else price
    ledger = None
    if not is_trial:
        ledger = _write_ledger(
            tenant_id=tenant.id, actor_user_id=actor_user_id,
            amount=amount, entry_type='debit', currency=currency,
            note=f'Activated {_plan_label(plan)} ({cycle}d)',
            reference=f'{REF_ACTIVATE}-{tenant.id}-{sub.id}',
            category='subscription',
        )
    if commit:
        db.session.commit()
    return BillingResult(
        action='activate',
        tenant_id=tenant.id,
        plan_id=plan.id,
        subscription_id=sub.id,
        amount=amount,
        currency=currency,
        ledger_entry_id=getattr(ledger, 'id', None),
        basis=(
            f'Trial — no charge ({cycle}d).'
            if is_trial else
            f'Full plan price for {cycle}-day cycle: {price:.2f} {currency}.'
        ),
        extra={'cycle_days': cycle, 'is_trial': is_trial},
    )


def renew(
    tenant: TenantAccount,
    plan: SubscriptionPlan | None = None,
    *,
    days: int | None = None,
    actor_user_id: int | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> BillingResult:
    """Renew the tenant's current subscription.

    Behaviour:
      * If the current sub is still active and ``ends_at`` is in the
        future, the new cycle stacks on top: ``new_starts = ends_at``,
        so the subscriber doesn't lose unused time.
      * If the current sub is expired / missing, the new cycle starts
        at ``now``. (This case is functionally identical to
        ``activate`` and is included as a convenience.)
      * If ``plan`` is omitted, renews on the current plan.

    A renewal always charges the plan's full price for the chosen
    ``days`` window. If you want a prorated extension of the existing
    cycle, use ``extend`` instead.
    """
    if tenant is None:
        raise ValueError('renew requires a tenant')
    started_now = _now(now)
    current = _latest_subscription(tenant)
    if plan is None:
        plan = (
            SubscriptionPlan.query.get(current.plan_id)
            if current and current.plan_id else
            (SubscriptionPlan.query.get(tenant.plan_id) if tenant.plan_id else None)
        )
    if plan is None:
        raise ValueError('renew requires a plan (no current plan on tenant)')
    cycle = int(days or _plan_cycle_days(plan))
    # Stacking start: pick whichever is later.
    base_start = started_now
    if (
        current
        and current.ends_at
        and current.ends_at > started_now
        and (current.status or '').lower() in {'active', 'trial'}
    ):
        base_start = current.ends_at
    starts = base_start
    ends = starts + timedelta(days=cycle)
    sub = TenantSubscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status='active',
        activation_mode='manual',
        starts_at=starts,
        ends_at=ends,
        activated_by_user_id=actor_user_id,
        notes=f'Renewed {_plan_label(plan)} ({cycle}d)',
    )
    tenant.plan_id = plan.id
    tenant.status = 'active'
    db.session.add(sub)
    _apply_quotas(tenant, plan)
    db.session.flush()
    currency = _resolve_currency(getattr(plan, 'currency', None))
    price = float(getattr(plan, 'price', 0) or 0)
    ledger = _write_ledger(
        tenant_id=tenant.id, actor_user_id=actor_user_id,
        amount=price, entry_type='debit', currency=currency,
        note=f'Renewed {_plan_label(plan)} ({cycle}d)',
        reference=f'{REF_RENEW}-{tenant.id}-{sub.id}',
        category='renewal',
    )
    if commit:
        db.session.commit()
    return BillingResult(
        action='renew',
        tenant_id=tenant.id,
        plan_id=plan.id,
        subscription_id=sub.id,
        amount=price,
        currency=currency,
        ledger_entry_id=getattr(ledger, 'id', None),
        basis=(
            f'Stacked renewal — new cycle starts at {starts.isoformat()} '
            f'({cycle}d, {price:.2f} {currency}).'
        ),
        extra={
            'cycle_days': cycle, 'starts_at': starts, 'ends_at': ends,
            'stacked_from_previous': base_start != started_now,
        },
    )


def extend(
    tenant: TenantAccount,
    *,
    extra_days: int,
    actor_user_id: int | None = None,
    notes: str = '',
    is_trial_extension: bool = False,
    now: datetime | None = None,
    commit: bool = True,
) -> BillingResult:
    """Extend the current subscription by ``extra_days``.

    v82 fix: the prior admin tool charged the FULL plan price for any
    extension (even a 5-day bump on a $20 90-day plan). The engine now
    charges a PRORATED fraction of the plan price:
        amount = (extra_days / plan.duration_days_default) × plan.price

    When ``is_trial_extension=True`` the subscription stays in
    ``trial`` status and the ledger entry is skipped — used by the
    admin "trial_days" extend mode.
    """
    if tenant is None:
        raise ValueError('extend requires a tenant')
    if extra_days <= 0:
        raise ValueError('extend requires a positive extra_days')
    started_now = _now(now)
    current = _latest_subscription(tenant)
    if not current:
        raise ValueError('extend requires an existing subscription')
    base = (
        current.ends_at
        if current.ends_at and current.ends_at > started_now
        else started_now
    )
    new_ends = base + timedelta(days=int(extra_days))
    current.ends_at = new_ends
    if is_trial_extension:
        current.status = 'trial'
        current.trial_ends_at = new_ends
        tenant.status = 'trial'
    else:
        if (current.status or '').lower() in {'expired', 'suspended', 'trial'}:
            current.status = 'active'
        tenant.status = 'active'
    current.updated_at = started_now
    _append_note(
        current,
        notes or f'Extended by {extra_days} day(s)'
        + (' (trial)' if is_trial_extension else ''),
    )
    plan = SubscriptionPlan.query.get(current.plan_id) if current.plan_id else None
    currency = _resolve_currency(getattr(plan, 'currency', None))
    amount = 0.0
    ledger = None
    if not is_trial_extension and plan is not None:
        cycle = _plan_cycle_days(plan)
        price = float(getattr(plan, 'price', 0) or 0)
        amount = round((int(extra_days) / cycle) * price, 2)
        ledger = _write_ledger(
            tenant_id=tenant.id, actor_user_id=actor_user_id,
            amount=amount, entry_type='debit', currency=currency,
            note=(
                f'Extended {_plan_label(plan)} by {extra_days} day(s) '
                f'(prorated from {cycle}-day cycle)'
            ),
            reference=f'{REF_EXTEND}-{tenant.id}-{current.id}',
            category='renewal',
        )
    db.session.flush()
    if commit:
        db.session.commit()
    return BillingResult(
        action='extend',
        tenant_id=tenant.id,
        plan_id=getattr(plan, 'id', None),
        subscription_id=current.id,
        amount=amount,
        currency=currency,
        ledger_entry_id=getattr(ledger, 'id', None),
        basis=(
            'Trial extension — no charge.'
            if is_trial_extension else
            (
                f'Prorated {extra_days}/{_plan_cycle_days(plan)} of plan '
                f'price ({float(getattr(plan, "price", 0) or 0):.2f} {currency}) '
                f'= {amount:.2f} {currency}.'
                if plan else
                'No plan attached — no ledger entry written.'
            )
        ),
        extra={'extra_days': int(extra_days), 'new_ends_at': new_ends},
    )


def change_plan(
    tenant: TenantAccount,
    target_plan: SubscriptionPlan,
    *,
    actor_user_id: int | None = None,
    reference_token: str | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> BillingResult:
    """Mid-cycle plan switch.

    Mirrors the v81 prorated-diff policy:
        current_remaining_value = (remaining_days / current_cycle) × current_price
        target_remaining_value  = (remaining_days / target_cycle)  × target_price
        amount = target_remaining_value − current_remaining_value

    ``amount > 0`` → debit (subscriber owes more).
    ``amount < 0`` → credit (wallet refund).
    ``|amount| < 0.01`` → no ledger entry.

    The subscriber's ``ends_at`` is preserved so they don't lose any
    paid time. Use ``reference_token`` to carry a stable trace from
    the originating case (e.g. plan-change support case id) — when
    omitted the engine falls back to ``PCH-<tenant>-<sub>``.
    """
    if tenant is None or target_plan is None:
        raise ValueError('change_plan requires tenant + target_plan')
    started_now = _now(now)
    sub = _latest_subscription(tenant)
    if not sub:
        # No prior sub → treat as a fresh activation on the target.
        return activate(
            tenant, target_plan, actor_user_id=actor_user_id, now=now,
            commit=commit,
        )
    current_plan = SubscriptionPlan.query.get(sub.plan_id) if sub.plan_id else None
    # Pro-rated values.
    remaining_days = 0
    if sub.ends_at:
        remaining_days = max((sub.ends_at.date() - started_now.date()).days, 0)
    # Cycle prefers the real subscription window, falling back to the
    # plan's default duration so wonky / hand-edited subs still produce
    # a sensible number.
    cycle_current = 0
    if sub.starts_at and sub.ends_at:
        cycle_current = max((sub.ends_at.date() - sub.starts_at.date()).days, 0)
    if cycle_current <= 0:
        cycle_current = _plan_cycle_days(current_plan)
    cycle_target = _plan_cycle_days(target_plan)
    current_price = float(getattr(current_plan, 'price', 0) or 0)
    target_price = float(getattr(target_plan, 'price', 0) or 0)
    current_remaining_value = (
        round((remaining_days / cycle_current) * current_price, 2)
        if remaining_days > 0 and current_plan else 0.0
    )
    target_remaining_value = (
        round((remaining_days / cycle_target) * target_price, 2)
        if remaining_days > 0 else 0.0
    )
    amount = round(target_remaining_value - current_remaining_value, 2)
    # Apply mutation.
    tenant.plan_id = target_plan.id
    tenant.status = 'active'
    sub.plan_id = target_plan.id
    sub.status = 'active'
    sub.updated_at = started_now
    _append_note(
        sub,
        f'Plan changed: {_plan_label(current_plan)} → {_plan_label(target_plan)} '
        f'({remaining_days}d remaining, diff {amount:+.2f})',
    )
    _apply_quotas(tenant, target_plan)
    currency = _resolve_currency(
        getattr(target_plan, 'currency', None),
        getattr(current_plan, 'currency', None),
    )
    entry_type = 'debit' if amount > 0 else 'credit'
    ledger = None
    if abs(amount) >= 0.01:
        ref = reference_token or f'{REF_PLAN_CHANGE}-{tenant.id}-{sub.id}'
        ledger = _write_ledger(
            tenant_id=tenant.id, actor_user_id=actor_user_id,
            amount=amount, entry_type=entry_type, currency=currency,
            note=(
                f'Plan change applied: {_plan_label(current_plan)} → '
                f'{_plan_label(target_plan)} ({remaining_days} day(s) remaining)'
            ),
            reference=ref, category='plan_change',
        )
    db.session.flush()
    if commit:
        db.session.commit()
    return BillingResult(
        action='change_plan',
        tenant_id=tenant.id,
        plan_id=target_plan.id,
        subscription_id=sub.id,
        amount=amount,
        currency=currency,
        ledger_entry_id=getattr(ledger, 'id', None),
        basis=(
            f'Remaining {remaining_days} day(s). '
            f'Current remaining value {current_remaining_value:.2f}, '
            f'target remaining value {target_remaining_value:.2f}. '
            f'Diff = {amount:+.2f} {currency}.'
        ),
        extra={
            'remaining_days': remaining_days,
            'current_plan_id': getattr(current_plan, 'id', None),
            'current_plan_price': current_price,
            'target_plan_price': target_price,
            'cycle_days_current': cycle_current,
            'cycle_days_target': cycle_target,
            'current_remaining_value': current_remaining_value,
            'target_remaining_value': target_remaining_value,
        },
    )


def reactivate(
    tenant: TenantAccount,
    plan: SubscriptionPlan | None = None,
    *,
    days: int | None = None,
    actor_user_id: int | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> BillingResult:
    """Reactivate an expired / cancelled subscription.

    Creates a fresh `TenantSubscription` row starting at ``now``
    (we don't backfill missed time). When ``plan`` is omitted, uses
    the last plan the subscriber held. Charges the full plan price.

    The result's ``action`` is ``'reactivate'`` (not ``'activate'``)
    and its reference token is ``REA-…`` so finance can tell a
    reactivation apart from a first-time activation in reports.
    """
    if tenant is None:
        raise ValueError('reactivate requires a tenant')
    current = _latest_subscription(tenant)
    if plan is None:
        plan = (
            SubscriptionPlan.query.get(current.plan_id)
            if current and current.plan_id else
            (SubscriptionPlan.query.get(tenant.plan_id) if tenant.plan_id else None)
        )
    if plan is None:
        raise ValueError('reactivate requires a plan (no prior plan on tenant)')
    started = _now(now)
    cycle = int(days or _plan_cycle_days(plan))
    ends = started + timedelta(days=cycle)
    sub = TenantSubscription(
        tenant_id=tenant.id,
        plan_id=plan.id,
        status='active',
        activation_mode='manual',
        starts_at=started,
        ends_at=ends,
        activated_by_user_id=actor_user_id,
        notes=f'Reactivated {_plan_label(plan)} ({cycle}d)',
    )
    tenant.plan_id = plan.id
    tenant.status = 'active'
    db.session.add(sub)
    _apply_quotas(tenant, plan)
    db.session.flush()
    currency = _resolve_currency(getattr(plan, 'currency', None))
    price = float(getattr(plan, 'price', 0) or 0)
    ledger = _write_ledger(
        tenant_id=tenant.id, actor_user_id=actor_user_id,
        amount=price, entry_type='debit', currency=currency,
        note=f'Reactivated {_plan_label(plan)} ({cycle}d)',
        reference=f'{REF_REACTIVATE}-{tenant.id}-{sub.id}',
        category='subscription',
    )
    if commit:
        db.session.commit()
    return BillingResult(
        action='reactivate',
        tenant_id=tenant.id,
        plan_id=plan.id,
        subscription_id=sub.id,
        amount=price,
        currency=currency,
        ledger_entry_id=getattr(ledger, 'id', None),
        basis=(
            f'Reactivated on {_plan_label(plan)} for {cycle}-day cycle '
            f'({price:.2f} {currency}).'
        ),
        extra={'cycle_days': cycle},
    )


def cancel(
    tenant: TenantAccount,
    *,
    actor_user_id: int | None = None,
    reason: str = '',
    now: datetime | None = None,
    commit: bool = True,
) -> BillingResult:
    """Cancel the current subscription.

    Policy:
      * Subscriber keeps access until ``ends_at`` (no time taken away).
      * ``status`` flips to ``cancelled`` on both the subscription
        and the tenant.
      * NO automatic refund. A refund is a separate, deliberate
        finance action (use a manual ledger entry).

    Returns a result with ``amount=0`` and no ledger entry.
    """
    if tenant is None:
        raise ValueError('cancel requires a tenant')
    started_now = _now(now)
    sub = _latest_subscription(tenant)
    if sub:
        sub.status = 'cancelled'
        sub.updated_at = started_now
        _append_note(
            sub,
            f'Cancelled ({reason})' if reason else 'Cancelled',
        )
    tenant.status = 'cancelled'
    tenant.updated_at = started_now
    if commit:
        db.session.commit()
    plan = (
        SubscriptionPlan.query.get(sub.plan_id)
        if sub and sub.plan_id else None
    )
    currency = _resolve_currency(getattr(plan, 'currency', None))
    return BillingResult(
        action='cancel',
        tenant_id=tenant.id,
        plan_id=getattr(plan, 'id', None),
        subscription_id=getattr(sub, 'id', None),
        amount=0.0,
        currency=currency,
        ledger_entry_id=None,
        basis=(
            'Cancellation — no refund issued. Access continues until '
            'the existing end date.'
        ),
        extra={'reason': reason},
    )
