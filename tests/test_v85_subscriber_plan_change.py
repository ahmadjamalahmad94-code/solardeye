"""v85 — subscriber-driven plan-change flow tests.

Covers the four execution paths the spec demands:

  Part A — preview is pure
    * preview() returns both scenarios without creating a case,
      writing a ledger row, or mutating any model state.
    * Defensive blocked_reason handling for the three edge cases:
      no active subscription, target plan unavailable, target plan
      == current plan.

  Part B — confirm dispatches to the right execution path
    * reduced_days  → direct apply (case status=resolved + ledger)
    * same_duration with positive amount → invoice (case status=
      payment_requested + pending ledger row)
    * same_duration with zero amount → direct apply (case status=
      resolved, no ledger entry written by change_plan)
    * same_duration with credit (negative amount) → direct apply
      (case status=resolved + credit ledger row)
    * Unknown mode / unavailable target / same-plan → blocked
      result with explicit blocked_reason.

  Part C — accounting precision
    * The billing engine is the canonical writer of the financial
      mutation. confirm() never writes a `WalletLedger` row
      directly; it delegates to apply_request() / issue_invoice().
    * Backend is the source of truth for amount + currency;
      a client-supplied "amount" field would be ignored (the
      service doesn't read one).

  Part D — admin monitoring + lifecycle
    * Prior open subscriber-side cases are auto-cancelled on
      confirm so the admin queue doesn't pile up duplicates.
    * The new STATUS_PAYMENT_SETTLED state is present in the
      LIFECYCLE + ACTIVE vocabulary so the workbench's queue can
      filter by it.
    * mark_invoice_settled flips the case + writes an audit row
      without changing the subscription (mutation happens later
      via apply_request).

Style mirrors v76 / v78 / v80 / v81 / v82 / v83 / v84: mock-based,
no DB boot, no `create_app()`. Models are patched at the workbench
module boundary; a tiny Flask `app_context` covers SQLAlchemy
model instantiation.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _ctx():
    """Bare Flask app context — required so model `__init__` can
    register with the session even though we mock the session
    itself."""
    from flask import Flask
    from app.extensions import db
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app.app_context()


# ─── Fake-row factories ───────────────────────────────────────────────


def _fake_user(*, id_=11, tenant_id=7, is_admin=False, email=None,
               full_name='أحمد', username='ahmad'):
    u = mock.Mock()
    u.id = id_
    u.tenant_id = tenant_id
    u.is_admin = is_admin
    u.email = email
    u.full_name = full_name
    u.username = username
    return u


def _fake_tenant(*, id_=7, plan_id=1, status='active'):
    t = mock.Mock()
    t.id = id_
    t.plan_id = plan_id
    t.status = status
    return t


def _fake_plan(*, id_=1, code='basic', name_ar='أساسي', name_en='Basic',
               price=10.0, duration_days=30, currency='USD', is_active=True):
    p = mock.Mock()
    p.id = id_
    p.code = code
    p.name_ar = name_ar
    p.name_en = name_en
    p.price = price
    p.duration_days_default = duration_days
    p.currency = currency
    p.is_active = is_active
    return p


def _fake_sub(*, id_=10, plan_id=1, status='active',
              starts_at=None, ends_at=None):
    s = mock.Mock()
    s.id = id_
    s.plan_id = plan_id
    s.status = status
    s.starts_at = starts_at or datetime(2026, 4, 12)
    s.ends_at = ends_at or datetime(2026, 5, 27)
    s.notes = ''
    return s


def _patch_models(*, tenant=None, sub=None, current_plan=None, target_plan=None):
    """Unified query mocks. `SubscriptionPlan.query.get(id)` →
    current_plan; `.filter_by(name_ar=…).first()` → target_plan
    (used by extract_plan_change_target_plan)."""
    from app.services import plan_change_workbench as wb
    from app.services import subscriber_plan_change as spc

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub

    plan_query = mock.Mock()
    plan_query.get.side_effect = lambda pid: {
        getattr(current_plan, 'id', None): current_plan,
        getattr(target_plan, 'id', None): target_plan,
    }.get(int(pid) if pid is not None else None)
    plan_filter_chain = mock.Mock()
    plan_filter_chain.first.return_value = target_plan
    plan_query.filter_by.return_value = plan_filter_chain

    # Also mock SupportCase.query.filter_by(...).filter(...).all() for
    # the prior-cancel scan and the find_pending_invoice helper.
    case_query = mock.Mock()
    case_query.filter_by.return_value = case_query
    case_query.filter.return_value = case_query
    case_query.all.return_value = []
    case_query.first.return_value = None

    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = None

    return [
        mock.patch.object(spc.TenantAccount, 'query', tenant_query),
        mock.patch.object(wb.TenantAccount, 'query', tenant_query),
        mock.patch.object(wb.TenantSubscription, 'query', sub_query),
        mock.patch.object(spc.SubscriptionPlan, 'query', plan_query),
        mock.patch.object(wb.SubscriptionPlan, 'query', plan_query),
        mock.patch.object(wb.SupportCase, 'query', case_query),
        mock.patch.object(spc.SupportCase, 'query', case_query),
        mock.patch.object(wb.WalletLedger, 'query', ledger_query),
    ]


def _capture_session():
    """Drop-in `db.session.add` that records every model
    instantiation. Auto-assigns ids so workbench helpers can read
    `entry.id` after their flush()."""
    added: list = []
    _counter = {'n': 2000}

    def _add(item):
        added.append(item)
        if hasattr(item, 'id') and getattr(item, 'id', None) is None:
            _counter['n'] += 1
            try:
                item.id = _counter['n']
            except Exception:
                pass

    return added, _add


def _patch_session(_add):
    from app.services import plan_change_workbench as wb
    from app.services import subscriber_plan_change as spc
    return [
        mock.patch.object(wb.db.session, 'add', side_effect=_add),
        mock.patch.object(wb.db.session, 'flush'),
        mock.patch.object(wb.db.session, 'commit'),
        mock.patch.object(spc.db.session, 'add', side_effect=_add),
        mock.patch.object(spc.db.session, 'flush'),
        mock.patch.object(spc.db.session, 'commit'),
    ]


# ═══════════════════════════════════════════════════════════════════════
# Part A — preview is pure
# ═══════════════════════════════════════════════════════════════════════


def test_preview_returns_both_scenarios_without_mutation():
    """A subscriber on Basic ($10 / 30 days) looking at Pro
    ($30 / 30 days) with 15 days remaining sees:
       * same_duration → +10.00 USD owed
       * reduced_days  → 5 free target days
    Neither preview should write a single model row."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(
        plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target = _fake_plan(id_=2, price=30.0, duration_days=30, name_ar='برو')
    added, _add = _capture_session()
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            for p in _patch_session(_add):
                p.start()
            try:
                # Deterministic preview — `now` propagates into the
                # workbench scenario math so the test doesn't drift
                # with the real wall clock.
                result = spc.preview(
                    user, target_plan_id=2,
                    now=datetime(2026, 5, 12),
                )
            finally:
                pass
        finally:
            for p in patches:
                p.stop()
    assert result.blocked_reason is None
    assert result.can_apply_directly is True
    assert result.target_plan_id == 2
    assert result.target_plan_label == 'برو'
    # Pure read — no model instantiation reached the session.
    assert added == []
    # Math: 15 days remaining → +10.00 USD diff at same duration.
    assert result.remaining_days == 15
    assert result.same_duration['amount'] == 10.0
    # Reduced-days free swap: 5 USD / 1 USD per day = 5 days.
    assert result.reduced_days['target_days'] == 5
    assert result.reduced_days['amount'] == 0.0


def test_preview_blocks_when_target_plan_missing():
    from app.services import subscriber_plan_change as spc
    user = _fake_user(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub()
    current = _fake_plan(id_=1)
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=None,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.preview(user, target_plan_id=999)
        finally:
            for p in patches:
                p.stop()
    assert result.blocked_reason == 'target_plan_unavailable'
    assert result.can_apply_directly is False


def test_preview_blocks_when_target_equals_current_plan():
    from app.services import subscriber_plan_change as spc
    user = _fake_user(tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(plan_id=1)
    current = _fake_plan(id_=1)
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=current,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.preview(user, target_plan_id=1)
        finally:
            for p in patches:
                p.stop()
    assert result.blocked_reason == 'same_plan_already_active'


def test_preview_blocks_when_no_active_subscription():
    from app.services import subscriber_plan_change as spc
    user = _fake_user(tenant_id=None)
    patches = _patch_models(
        tenant=None, sub=None, current_plan=None, target_plan=None,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.preview(user, target_plan_id=2)
        finally:
            for p in patches:
                p.stop()
    assert result.blocked_reason == 'no_active_subscription'


# ═══════════════════════════════════════════════════════════════════════
# Part B — confirm dispatch paths
# ═══════════════════════════════════════════════════════════════════════


def test_confirm_reduced_days_applies_directly():
    """v87 — reduced_days is the direct-execute path: no payment
    required, plan switched immediately. Under the new policy we
    DO NOT call billing_engine.change_plan (that path implicitly
    wrote a credit on downgrades); the workbench's apply_request
    writes its own ledger (or none, for a zero-amount free swap).

    Upgrade reduced_days with default `desired_target_days` → free
    swap (amount=0) → no ledger row written."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(
        plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target = _fake_plan(id_=2, price=30.0, duration_days=30, name_ar='برو')
    added, _add = _capture_session()
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                spc.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                spc.db.session, 'flush',
            ), mock.patch.object(
                spc.db.session, 'commit',
            ), mock.patch(
                'app.services.billing_engine._latest_subscription',
                return_value=sub,
            ), mock.patch(
                'app.services.billing_engine._apply_quotas',
            ), mock.patch(
                'app.services.billing_engine._write_ledger',
            ) as write_ledger_mock, mock.patch(
                'app.services.billing_engine.change_plan',
            ) as change_plan_mock:
                result = spc.confirm(
                    user, target_plan_id=2,
                    mode='reduced_days',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    # Reduced-days → applied immediately.
    assert result.outcome == 'applied'
    assert result.scenario_mode == 'reduced_days'
    assert result.case_status == 'resolved'
    assert result.extra.get('target_days') == 5
    # v87 — billing_engine.change_plan must NOT be invoked.
    change_plan_mock.assert_not_called()
    # Zero-amount free swap → no ledger entry either.
    write_ledger_mock.assert_not_called()


def test_confirm_same_duration_with_positive_amount_creates_invoice():
    """Positive diff → payment_required outcome, pending ledger row
    written, case flipped to payment_requested. No subscription
    mutation yet (admin/webhook applies after settlement)."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(
        plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target = _fake_plan(id_=2, price=30.0, duration_days=30, name_ar='برو')
    added, _add = _capture_session()
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                spc.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                spc.db.session, 'flush',
            ), mock.patch.object(
                spc.db.session, 'commit',
            ):
                result = spc.confirm(
                    user, target_plan_id=2,
                    mode='same_duration',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    assert result.outcome == 'payment_required'
    assert result.amount == 10.0
    assert result.currency == 'USD'
    assert result.case_status == 'payment_requested'
    # The pending invoice ledger row was written exactly once.
    ledger_rows = [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ]
    assert len(ledger_rows) == 1
    invoice = ledger_rows[0]
    assert invoice.entry_type == 'debit'
    assert invoice.amount == 10.0
    assert invoice.category == 'plan_change_pending'
    assert invoice.reference.startswith('INV-7-')
    assert result.invoice_reference == invoice.reference


def test_confirm_same_duration_with_zero_amount_applies_directly():
    """When same-duration produces a zero diff (equal plans), the
    spec says we can execute directly — no invoice, no payment
    gate."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    # Both plans same price → diff is 0.
    sub = _fake_sub(
        plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=20.0, duration_days=30)
    target = _fake_plan(id_=2, price=20.0, duration_days=30, name_ar='Twin')
    added, _add = _capture_session()
    fake_engine_result = mock.Mock()
    fake_engine_result.amount = 0.0
    fake_engine_result.currency = 'USD'
    fake_engine_result.ledger_entry_id = None
    fake_engine_result.to_dict.return_value = {'amount': 0.0}
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                spc.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                spc.db.session, 'flush',
            ), mock.patch.object(
                spc.db.session, 'commit',
            ), mock.patch(
                'app.services.billing_engine.change_plan',
                return_value=fake_engine_result,
            ):
                result = spc.confirm(
                    user, target_plan_id=2,
                    mode='same_duration',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    assert result.outcome == 'applied'
    assert result.case_status == 'resolved'
    assert result.amount == 0.0
    # No pending invoice ledger row.
    pending_rows = [
        x for x in added
        if x.__class__.__name__ == 'WalletLedger'
        and getattr(x, 'category', '') == 'plan_change_pending'
    ]
    assert pending_rows == []


def test_confirm_same_duration_on_downgrade_is_blocked_under_v87_policy():
    """v87 — downgrading via `same_duration` is FORBIDDEN. The path
    would have produced a refund/wallet credit; v87 policy explicitly
    bans that semantics. The subscriber must use `reduced_days`
    (value-to-more-days conversion) instead.

    The block happens BEFORE any case row is created, so no admin
    queue rows are left behind."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(
        plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    # Downgrade: current is $30/30d ($1/d), target is $10/30d ($0.33/d).
    current = _fake_plan(id_=1, price=30.0, duration_days=30)
    target = _fake_plan(id_=2, price=10.0, duration_days=30, name_ar='أساسي')
    added, _add = _capture_session()
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                spc.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                spc.db.session, 'flush',
            ), mock.patch.object(
                spc.db.session, 'commit',
            ), mock.patch(
                'app.services.billing_engine.change_plan',
            ) as change_plan_mock:
                result = spc.confirm(
                    user, target_plan_id=2,
                    mode='same_duration',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    # Policy block before any case row is created.
    assert result.outcome == 'blocked'
    assert result.blocked_reason == 'downgrade_same_duration_not_allowed'
    assert result.case_id is None
    # billing_engine.change_plan must NOT be reached.
    change_plan_mock.assert_not_called()
    # No case row was added to the session.
    assert [x for x in added if x.__class__.__name__ == 'SupportCase'] == []


def test_confirm_blocks_on_unknown_mode():
    from app.services import subscriber_plan_change as spc
    user = _fake_user(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub()
    current = _fake_plan(id_=1)
    target = _fake_plan(id_=2, name_ar='Pro')
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.confirm(user, target_plan_id=2, mode='gibberish')
        finally:
            for p in patches:
                p.stop()
    assert result.outcome == 'blocked'
    assert result.blocked_reason == 'unknown_pricing_mode'
    assert result.case_id is None


def test_confirm_blocks_when_target_is_current_plan():
    """Safety lock — same plan is not a meaningful change."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(plan_id=1)
    current = _fake_plan(id_=1)
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=current,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.confirm(
                user, target_plan_id=1, mode='same_duration',
            )
        finally:
            for p in patches:
                p.stop()
    assert result.outcome == 'blocked'
    assert result.blocked_reason == 'same_plan_already_active'


def test_confirm_blocks_when_no_active_subscription():
    from app.services import subscriber_plan_change as spc
    user = _fake_user(tenant_id=None)
    patches = _patch_models(
        tenant=None, sub=None, current_plan=None, target_plan=None,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.confirm(
                user, target_plan_id=2, mode='same_duration',
            )
        finally:
            for p in patches:
                p.stop()
    assert result.outcome == 'blocked'
    assert result.blocked_reason == 'no_active_subscription'


# ═══════════════════════════════════════════════════════════════════════
# Part C — accounting precision (backend = source of truth)
# ═══════════════════════════════════════════════════════════════════════


def test_confirm_does_not_trust_client_supplied_amount():
    """The confirm() signature accepts ONLY ids and the mode. No
    amount field exists — verified by inspecting the function
    signature at runtime."""
    import inspect
    from app.services.subscriber_plan_change import confirm
    sig = inspect.signature(confirm)
    forbidden = {'amount', 'price', 'unit_amount', 'unit_amount_cents'}
    assert set(sig.parameters.keys()).isdisjoint(forbidden)


def test_confirm_invoice_carries_full_audit_metadata():
    """Lock the invoice ledger entry's fields so finance reports
    can filter on them. The invoice MUST carry:
      * tenant_id
      * category='plan_change_pending'
      * reference matching INV-<tenant>-<case>
      * note describing the scenario
    """
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(
        plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0)
    target = _fake_plan(id_=2, price=30.0, name_ar='برو')
    added, _add = _capture_session()
    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                spc.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                spc.db.session, 'flush',
            ), mock.patch.object(
                spc.db.session, 'commit',
            ):
                spc.confirm(
                    user, target_plan_id=2,
                    mode='same_duration',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledger_rows = [
        x for x in added
        if x.__class__.__name__ == 'WalletLedger'
        and getattr(x, 'category', '') == 'plan_change_pending'
    ]
    assert len(ledger_rows) == 1
    inv = ledger_rows[0]
    assert inv.tenant_id == 7
    assert inv.reference.startswith('INV-7-')
    assert 'mode=same_duration' in inv.note
    assert 'remaining=15' in inv.note


# ═══════════════════════════════════════════════════════════════════════
# Part D — lifecycle + admin monitoring
# ═══════════════════════════════════════════════════════════════════════


def test_lifecycle_vocabulary_includes_payment_settled():
    """v85: new state STATUS_PAYMENT_SETTLED is part of the
    lifecycle vocabulary AND counted as an active state so it
    surfaces in the admin queue."""
    from app.services.plan_change_workbench import (
        LIFECYCLE_STATUSES, ACTIVE_STATUSES, STATUS_PAYMENT_SETTLED,
    )
    assert STATUS_PAYMENT_SETTLED == 'payment_settled'
    assert STATUS_PAYMENT_SETTLED in LIFECYCLE_STATUSES
    assert STATUS_PAYMENT_SETTLED in ACTIVE_STATUSES


def test_mark_invoice_settled_flips_status_without_applying():
    """v85: settlement is a separate step from plan application.
    `mark_invoice_settled` must:
      * flip the case to payment_settled,
      * write an audit row referencing the pending invoice,
      * notify the subscriber,
      * NOT mutate tenant.plan_id (apply_request does that later).
    """
    from app.services import plan_change_workbench as wb
    case = mock.Mock()
    case.id = 55
    case.case_type = 'plan_change_request'
    case.source_id = 11
    case.user_id = 11
    case.tenant_id = 7
    case.status = wb.STATUS_PAYMENT_REQUESTED
    case.is_frozen = False
    pending = mock.Mock()
    pending.id = 999
    pending.reference = 'INV-7-55'
    pending.category = 'plan_change_pending'

    added, _add = _capture_session()
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = pending
    with _ctx(), mock.patch.object(
        wb.WalletLedger, 'query', ledger_query,
    ), mock.patch.object(
        wb.db.session, 'add', side_effect=_add,
    ), mock.patch.object(
        wb.db.session, 'commit',
    ):
        out = wb.mark_invoice_settled(
            case, actor_user_id=42, note='cash received in office',
        )
    assert case.status == 'payment_settled'
    assert out['case_status'] == 'payment_settled'
    assert out['invoice_reference'] == 'INV-7-55'
    # Audit row + subscriber notification — both added.
    audit_rows = [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ]
    assert audit_rows
    assert audit_rows[0].action == 'plan_change.invoice_settled_pending_apply'
    notif_events = [
        x for x in added if x.__class__.__name__ == 'NotificationEvent'
    ]
    assert notif_events
    assert notif_events[0].event_type == 'plan_change_invoice_settled'
    # No new ledger row was added (pending stays in place; apply
    # later will flip its category).
    assert [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ] == []


def test_confirm_cancels_prior_open_subscriber_cases():
    """Operator hygiene: when a subscriber confirms a fresh plan
    change, any prior open subscriber-side cases on the same
    tenant get auto-cancelled so the admin queue doesn't pile up
    stale entries."""
    from app.services import subscriber_plan_change as spc
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub()
    current = _fake_plan(id_=1, price=10.0)
    target = _fake_plan(id_=2, price=10.0, name_ar='Twin')
    # Prior open cases.
    old_case = mock.Mock()
    old_case.status = 'open'
    old_case.updated_at = None
    case_query = mock.Mock()
    case_query.filter_by.return_value = case_query
    case_query.filter.return_value = case_query
    case_query.all.return_value = [old_case]
    case_query.first.return_value = None

    fake_engine_result = mock.Mock()
    fake_engine_result.amount = 0.0
    fake_engine_result.currency = 'USD'
    fake_engine_result.ledger_entry_id = None
    fake_engine_result.to_dict.return_value = {'amount': 0.0}

    patches = _patch_models(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    added, _add = _capture_session()
    with _ctx():
        for p in patches:
            p.start()
        try:
            from app.services import plan_change_workbench as wb
            with mock.patch.object(
                wb.SupportCase, 'query', case_query,
            ), mock.patch.object(
                spc.SupportCase, 'query', case_query,
            ), mock.patch.object(
                spc.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                spc.db.session, 'flush',
            ), mock.patch.object(
                spc.db.session, 'commit',
            ), mock.patch(
                'app.services.billing_engine.change_plan',
                return_value=fake_engine_result,
            ):
                spc.confirm(
                    user, target_plan_id=2,
                    mode='same_duration',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    # The prior case was cancelled.
    assert old_case.status == 'cancelled'
    assert old_case.updated_at is not None


# ═══════════════════════════════════════════════════════════════════════
# Sanity locks
# ═══════════════════════════════════════════════════════════════════════


def test_confirm_result_outcome_vocabulary_is_stable():
    """Spec lock: the three outcome values are part of the contract.
    A rename would silently break callers that branch on these
    strings (route handler flashes, future mobile API client)."""
    from app.services.subscriber_plan_change import confirm
    import inspect
    src = inspect.getsource(confirm)
    assert "outcome='applied'" in src
    assert "outcome='payment_required'" in src
    assert "outcome='blocked'" in src


def test_legacy_request_change_route_redirects_to_preview():
    """Source-inspection lock: the legacy POST endpoint must
    redirect to the new preview page, not create a vague case.

    We read the file as text rather than importing the module so
    this test doesn't transitively pull in the `main.py` blueprint
    (which depends on reportlab — not always installed in dev)."""
    billing_path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'billing.py',
    )
    with open(billing_path, 'r', encoding='utf-8') as fh:
        src = fh.read()
    # Walk the source line-by-line from `def …():` until the first
    # non-indented non-blank line. That's the legacy function body
    # alone — comments between functions (which may mention
    # `SupportCase(`) are intentionally excluded.
    marker = 'def account_subscription_request_change():'
    start = src.find(marker)
    assert start >= 0, 'legacy route handler missing'
    lines = src[start:].splitlines()
    body_lines = [lines[0]]
    for line in lines[1:]:
        if line == '' or line.startswith(' ') or line.startswith('\t'):
            body_lines.append(line)
        else:
            break
    body = '\n'.join(body_lines)
    # The legacy route is now a thin funnel — every plan-change
    # submission becomes a deliberate preview-then-confirm action.
    assert 'account_subscription_change_preview' in body
    # And it must NOT do any of the old vague-case mutation work:
    # constructing a SupportCase row, db.session.add'ing it, or
    # fanning out admin notifications about a vague request.
    assert 'SupportCase(' not in body
    assert 'db.session.add' not in body
    assert 'notify_admins_of_plan_change_request' not in body
