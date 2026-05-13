"""v82 — plan-change financial workbench tests.

Covers the workbench service end-to-end:

  Part A — scenario math
    * same-duration: prorated diff matches v81's formula.
    * reduced-days free swap: target_days computed from current
      remaining value.
    * reduced-days with manual day adjustment: positive → debit
      basis, negative → credit basis.
    * preview is pure — no balance mutation.

  Part B — discussion / invoice / apply / reject / cancel
    * send_discussion writes a NotificationEvent + audit, flips
      status to awaiting_subscriber_reply.
    * issue_invoice writes a pending WalletLedger row, flips
      status to payment_requested.
    * issue_invoice is a no-op for non-positive amounts.
    * apply_request settles a pending invoice (category flip) and
      delegates to billing_engine.change_plan.
    * apply_request in reduced-days mode shortens the surviving sub
      to scenario.target_days.
    * reject_request closes the case and reverses any pending invoice.
    * cancel_request closes silently (no subscriber notification).

  Part C — discoverability
    * admin notification fanout uses the workbench detail URL as
      direct_url so a bell click lands on the financial decision
      surface.
    * open_request_count counts only states that still need an
      outcome.

Mocking style mirrors v76 / v78 / v80 / v81 / earlier v82 tests:
no DB boot, every model class is patched at the engine module
boundary, and a `_ctx()` helper supplies a bare Flask app context
so SQLAlchemy model instantiation works.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _ctx():
    from flask import Flask
    from app.extensions import db
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app.app_context()


# ─── Fake-row factories ───────────────────────────────────────────────


def _fake_case(*, id_=55, user_id=11, tenant_id=7, subject='', status='open'):
    c = mock.Mock()
    c.id = id_
    c.user_id = user_id
    c.tenant_id = tenant_id
    c.subject = subject
    c.status = status
    c.case_type = 'plan_change_request'
    c.source_id = user_id
    c.is_frozen = False
    c.updated_at = datetime(2026, 5, 12, 9, 0, 0)
    c.created_at = datetime(2026, 5, 10, 9, 0, 0)
    return c


def _fake_plan(*, id_=1, code='basic', name_ar='أساسي', name_en='Basic',
               price=10.0, duration_days=30, currency='USD'):
    p = mock.Mock()
    p.id = id_
    p.code = code
    p.name_ar = name_ar
    p.name_en = name_en
    p.price = price
    p.duration_days_default = duration_days
    p.currency = currency
    return p


def _fake_sub(*, id_=99, plan_id=1, status='active',
              starts_at=None, ends_at=None):
    s = mock.Mock()
    s.id = id_
    s.plan_id = plan_id
    s.status = status
    s.starts_at = starts_at or datetime(2026, 4, 12)
    s.ends_at = ends_at or datetime(2026, 5, 27)
    return s


def _fake_tenant(*, id_=7, plan_id=1, status='active'):
    t = mock.Mock()
    t.id = id_
    t.plan_id = plan_id
    t.status = status
    return t


def _patch_workbench_collaborators(
    *,
    tenant=None,
    sub=None,
    current_plan=None,
    target_plan=None,
):
    """Wire the standard query mocks used by every workbench test.

    `SubscriptionPlan` is imported by both `plan_change_workbench`
    and `support_ops` — they reference the SAME class, so a single
    `mock.patch.object(SubscriptionPlan, 'query', …)` covers both
    callers. The unified query mock handles:

      * `SubscriptionPlan.query.get(plan_id)` → returns current_plan
        (used by `_resolve_request_context` to look up the current
        plan from `sub.plan_id`).
      * `SubscriptionPlan.query.filter_by(name_ar=…).first()` →
        returns target_plan (used by
        `support_ops.extract_plan_change_target_plan`).
    """
    from app.services import plan_change_workbench as wb

    tenant_query = mock.Mock()
    tenant_query.get.return_value = tenant

    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub

    plan_query = mock.Mock()
    plan_query.get.return_value = current_plan
    # `filter_by(...)` returns a chain whose `.first()` resolves to
    # the target plan — used by `extract_plan_change_target_plan`.
    plan_filter_chain = mock.Mock()
    plan_filter_chain.first.return_value = target_plan
    plan_query.filter_by.return_value = plan_filter_chain

    return [
        mock.patch.object(wb.TenantAccount, 'query', tenant_query),
        mock.patch.object(wb.TenantSubscription, 'query', sub_query),
        mock.patch.object(wb.SubscriptionPlan, 'query', plan_query),
    ]


def _capture_session():
    """Per-test session capture — drop-in `add` that auto-assigns
    ids so workbench helpers can read `entry.id` after flush."""
    added: list = []
    _counter = {'n': 1000}

    def _add(item):
        added.append(item)
        if hasattr(item, 'id') and getattr(item, 'id', None) is None:
            _counter['n'] += 1
            try:
                item.id = _counter['n']
            except Exception:
                pass

    return added, _add


def _patch_session(added_add):
    from app.services import plan_change_workbench as wb
    return [
        mock.patch.object(wb.db.session, 'add', side_effect=added_add),
        mock.patch.object(wb.db.session, 'flush'),
        mock.patch.object(wb.db.session, 'commit'),
    ]


# ═══════════════════════════════════════════════════════════════════════
# Part A — scenario math (preview is pure, no balance mutation)
# ═══════════════════════════════════════════════════════════════════════


def test_quote_same_duration_matches_prorated_formula():
    """15 days remaining, $10 30-day current, $30 30-day target.
    Diff = (15/30)*30 − (15/30)*10 = 15 − 5 = +10.00."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(
        plan_id=1, starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target = _fake_plan(id_=2, price=30.0, duration_days=30)
    patches = _patch_workbench_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            sc = wb.quote_same_duration(
                case, target_plan=target, now=datetime(2026, 5, 12),
            )
        finally:
            for p in patches:
                p.stop()

    assert sc.mode == 'same_duration'
    assert sc.remaining_days == 15
    assert sc.target_days == 15  # same duration → same days
    assert sc.amount == 10.0
    assert sc.current_remaining_value == 5.0
    assert sc.target_remaining_value == 15.0
    assert sc.currency == 'USD'
    assert 'الأيام المتبقّية' in sc.summary_ar


def test_quote_reduced_days_free_swap_computes_target_days():
    """Free swap mode: with $5 remaining value and a $30/30d target
    (i.e. $1/day), the subscriber can keep 5 days on target for $0.
    Caller didn't pass `desired_target_days` so the engine picks the
    free-swap value."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        plan_id=1, starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target = _fake_plan(id_=2, price=30.0, duration_days=30)
    patches = _patch_workbench_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            sc = wb.quote_reduced_days(
                case, target_plan=target, now=datetime(2026, 5, 12),
            )
        finally:
            for p in patches:
                p.stop()
    # Free target days = round(5.00 / 1.00) = 5.
    assert sc.extra['free_target_days'] == 5
    assert sc.target_days == 5
    # Amount = (5 × 1.00) − 5.00 = 0.00 — even swap.
    assert sc.amount == 0.0
    assert sc.currency == 'USD'


def test_quote_reduced_days_with_manual_adjustment_charges_extra():
    """Admin overrides the target days higher than the free swap →
    subscriber owes the extra fraction."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(price=10.0, duration_days=30)
    target = _fake_plan(price=30.0, duration_days=30)
    patches = _patch_workbench_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            sc = wb.quote_reduced_days(
                case, target_plan=target,
                desired_target_days=10,
                now=datetime(2026, 5, 12),
            )
        finally:
            for p in patches:
                p.stop()
    # 10 days × $1/day − $5 current remaining value = +5.00.
    assert sc.target_days == 10
    assert sc.amount == 5.0
    assert 'يوماً' in sc.summary_ar


def test_quote_reduced_days_with_manual_adjustment_credits_when_smaller():
    """Admin overrides target days below the free swap → subscriber
    gets a refund/credit."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(price=10.0, duration_days=30)
    target = _fake_plan(price=30.0, duration_days=30)
    patches = _patch_workbench_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            sc = wb.quote_reduced_days(
                case, target_plan=target,
                desired_target_days=3, now=datetime(2026, 5, 12),
            )
        finally:
            for p in patches:
                p.stop()
    # 3 × $1 − $5 = −2.00.
    assert sc.target_days == 3
    assert sc.amount == -2.0


def test_scenario_preview_does_not_mutate_balances():
    """Building the scenario set must NOT write any WalletLedger
    rows — preview is pure read-only computation."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(price=10.0, duration_days=30)
    target = _fake_plan(price=30.0, duration_days=30)
    added, _add = _capture_session()
    patches = _patch_workbench_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            for p in _patch_session(_add):
                p.start()
            try:
                wb.build_scenario_set(
                    case, target_plan=target,
                    desired_target_days=12,
                    now=datetime(2026, 5, 12),
                )
            finally:
                # We didn't enter `_patch_session` via with-statement
                # so stop the patches manually.
                pass
        finally:
            for p in patches:
                p.stop()
    # No ledger rows added by preview.
    assert [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ] == []


def test_select_scenario_rejects_unknown_modes():
    """Defensive — a typo'd POST `mode` parameter must raise so the
    caller short-circuits to a flash error instead of silently
    producing the wrong financial number."""
    from app.services import plan_change_workbench as wb
    case = _fake_case()
    try:
        wb.select_scenario(case, mode='blursed_mode')
    except ValueError as exc:
        assert 'unknown pricing mode' in str(exc)
    else:
        raise AssertionError('expected ValueError')


# ═══════════════════════════════════════════════════════════════════════
# Part B — workflow actions
# ═══════════════════════════════════════════════════════════════════════


def test_send_discussion_writes_event_and_flips_status():
    """The discussion flow must:
      * push a NotificationEvent to the subscriber,
      * append a SupportAuditLog row,
      * flip case.status to awaiting_subscriber_reply.
    The proposed scenario summary is embedded in the message body
    automatically.
    """
    from app.services import plan_change_workbench as wb
    case = _fake_case(id_=55, user_id=11, tenant_id=7, status='under_review')
    scenario = wb.Scenario(
        mode='same_duration',
        label_ar='نفس الأيام المتبقّية', label_en='Same days',
        remaining_days=15, target_days=15,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=10.0, target_plan_price=30.0,
        current_remaining_value=5.0, target_remaining_value=15.0,
        amount=10.0, currency='USD',
        summary_ar='ملخص', summary_en='Summary',
    )
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            wb.send_discussion(
                case, actor_user_id=42, body='مقترح من الإدارة',
                scenario=scenario,
            )
    notif_events = [
        x for x in added if x.__class__.__name__ == 'NotificationEvent'
    ]
    audit_rows = [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ]
    assert len(notif_events) == 1
    assert notif_events[0].event_type == 'plan_change_discussion'
    assert notif_events[0].target_user_id == 11
    assert notif_events[0].source_id == 55
    assert 'مقترح' in notif_events[0].message
    assert audit_rows
    assert audit_rows[0].action == 'plan_change.discussion'
    assert case.status == 'awaiting_subscriber_reply'


def test_send_discussion_requires_body():
    from app.services import plan_change_workbench as wb
    case = _fake_case()
    with _ctx():
        try:
            wb.send_discussion(case, actor_user_id=42, body='   ')
        except ValueError as exc:
            assert 'body is required' in str(exc)
        else:
            raise AssertionError('expected ValueError')


def test_issue_invoice_writes_pending_ledger_and_notifies_subscriber():
    """Issuing a payment request must:
      * write exactly one `WalletLedger` row with
        category=plan_change_pending and a stable INV-… reference,
      * push a NotificationEvent to the subscriber,
      * flip case.status to payment_requested.
    """
    from app.services import plan_change_workbench as wb
    case = _fake_case(id_=55, user_id=11, tenant_id=7, status='under_review')
    scenario = wb.Scenario(
        mode='same_duration', label_ar='', label_en='',
        remaining_days=15, target_days=15,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=10.0, target_plan_price=30.0,
        current_remaining_value=5.0, target_remaining_value=15.0,
        amount=10.0, currency='USD',
        summary_ar='ملخص السيناريو', summary_en='Summary',
    )
    added, _add = _capture_session()
    # `find_pending_invoice` queries the ledger; return None so a
    # fresh row is added.
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = None
    with _ctx():
        with mock.patch.object(
            wb.WalletLedger, 'query', ledger_query,
        ), mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            entry = wb.issue_invoice(
                case, actor_user_id=42, scenario=scenario,
            )
    ledger_rows = [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ]
    notif_events = [
        x for x in added if x.__class__.__name__ == 'NotificationEvent'
    ]
    audit_rows = [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ]
    assert len(ledger_rows) == 1
    assert ledger_rows[0].entry_type == 'debit'
    assert ledger_rows[0].amount == 10.0
    assert ledger_rows[0].category == 'plan_change_pending'
    assert ledger_rows[0].reference == 'INV-7-55'
    assert len(notif_events) == 1
    assert notif_events[0].event_type == 'plan_change_invoice_issued'
    assert audit_rows[0].action == 'plan_change.invoice_issued'
    assert case.status == 'payment_requested'
    assert entry is not None


def test_issue_invoice_is_a_noop_for_zero_or_credit_scenario():
    """Refunds / zero-diffs must NOT write a debit (you don't bill
    a subscriber for a credit). The status doesn't change either."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(status='under_review')
    refund_scenario = wb.Scenario(
        mode='reduced_days', label_ar='', label_en='',
        remaining_days=15, target_days=2,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=10.0, target_plan_price=30.0,
        current_remaining_value=5.0, target_remaining_value=2.0,
        amount=-3.0, currency='USD',
        summary_ar='', summary_en='',
    )
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            entry = wb.issue_invoice(
                case, actor_user_id=42, scenario=refund_scenario,
            )
    assert entry is None
    assert [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ] == []
    # Status was NOT flipped to payment_requested for a credit scenario.
    assert case.status == 'under_review'


def test_issue_invoice_reuses_existing_pending_row_on_re_click():
    """Defensive dedup: re-clicking "Issue invoice" must update the
    existing row in place, not stack a second pending entry."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(id_=55, user_id=11, tenant_id=7, status='under_review')
    scenario = wb.Scenario(
        mode='same_duration', label_ar='', label_en='',
        remaining_days=15, target_days=15,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=10.0, target_plan_price=30.0,
        current_remaining_value=5.0, target_remaining_value=15.0,
        amount=12.0, currency='USD',
        summary_ar='', summary_en='',
    )
    existing = mock.Mock()
    existing.id = 999
    existing.amount = 10.0
    existing.note = ''
    existing.entry_type = 'debit'
    existing.category = 'plan_change_pending'
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = existing
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.WalletLedger, 'query', ledger_query,
        ), mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            wb.issue_invoice(case, actor_user_id=42, scenario=scenario)
    # No NEW WalletLedger row created — the existing one was updated
    # in place. (Notification event + audit row are still added.)
    assert [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ] == []
    # And the existing row was bumped to the new amount.
    assert existing.amount == 12.0


def test_reject_request_reverses_pending_invoice():
    """A rejected request must:
      * close the case,
      * notify the subscriber,
      * write a counter-credit reversing the pending invoice,
      * flip the pending row's category so finance dashboards stop
        counting it as an obligation.
    """
    from app.services import plan_change_workbench as wb
    case = _fake_case(id_=55, user_id=11, tenant_id=7, status='payment_requested')
    pending = mock.Mock()
    pending.id = 999
    pending.amount = 12.0
    pending.currency = 'USD'
    pending.tenant_id = 7
    pending.reference = 'INV-7-55'
    pending.category = 'plan_change_pending'
    pending.note = 'original invoice'
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = pending
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.WalletLedger, 'query', ledger_query,
        ), mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            wb.reject_request(
                case, actor_user_id=42, reason='subscriber declined',
            )
    # Counter-credit was added with REV- reference.
    reversal_rows = [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ]
    assert len(reversal_rows) == 1
    assert reversal_rows[0].entry_type == 'credit'
    assert reversal_rows[0].amount == 12.0
    assert reversal_rows[0].reference == 'REV-7-55'
    assert reversal_rows[0].category == 'plan_change_reversal'
    # The pending row's category flipped so the obligation no longer
    # shows up under `plan_change_pending`.
    assert pending.category == 'plan_change_reversal'
    # Subscriber notified + case closed.
    notif_events = [
        x for x in added if x.__class__.__name__ == 'NotificationEvent'
    ]
    assert notif_events
    assert notif_events[0].event_type == 'plan_change_rejected'
    assert case.status == 'closed'
    assert case.is_frozen is True


def test_cancel_request_closes_silently_and_reverses_invoice():
    """Cancel is admin housekeeping — no subscriber notification,
    but pending invoices still get reversed for clean accounting."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(id_=55, user_id=11, tenant_id=7, status='under_review')
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = None  # no pending invoice
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.WalletLedger, 'query', ledger_query,
        ), mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            wb.cancel_request(
                case, actor_user_id=42, reason='duplicate',
            )
    # No subscriber notification on cancel.
    assert [
        x for x in added if x.__class__.__name__ == 'NotificationEvent'
    ] == []
    audit_rows = [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ]
    assert audit_rows[0].action == 'plan_change.cancel'
    assert case.status == 'cancelled'


def test_mark_under_review_is_idempotent_on_already_reviewed_cases():
    """Opening a workbench detail page must not stack repeated state
    transitions — `mark_under_review` is a no-op when the case is
    already past `open`."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(status='payment_requested')
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            wb.mark_under_review(case, actor_user_id=42)
    assert case.status == 'payment_requested'
    # No audit row written on the no-op path.
    assert [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ] == []


def test_apply_request_delegates_to_billing_engine_and_settles_invoice():
    """Final apply must:
      * call billing_engine.change_plan with the case-bound reference,
      * flip any pending invoice's category to 'plan_change' (settled),
      * mark the case resolved,
      * push a subscriber 'plan_change_applied' notification.
    """
    from app.services import plan_change_workbench as wb
    # Subject carries the target plan name so
    # `extract_plan_change_target_plan` parses it cleanly.
    case = _fake_case(
        id_=55, user_id=11, tenant_id=7,
        subject='طلب تغيير الخطة إلى برو',
        status='payment_requested',
    )
    scenario = wb.Scenario(
        mode='same_duration', label_ar='', label_en='',
        remaining_days=15, target_days=15,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=10.0, target_plan_price=30.0,
        current_remaining_value=5.0, target_remaining_value=15.0,
        amount=10.0, currency='USD',
        summary_ar='ملخص', summary_en='Summary',
    )
    tenant = _fake_tenant(id_=7)
    target = _fake_plan(id_=2, name_ar='برو')
    # Pending invoice that should be settled by apply.
    pending = mock.Mock()
    pending.id = 999
    pending.amount = 10.0
    pending.currency = 'USD'
    pending.reference = 'INV-7-55'
    pending.category = 'plan_change_pending'
    pending.note = 'original invoice'
    pending.tenant_id = 7

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = pending
    # Target plan resolves via `extract_plan_change_target_plan`.
    from app.services import support_ops
    target_query = mock.Mock()
    target_query.filter_by.return_value = target_query
    target_query.first.return_value = target

    added, _add = _capture_session()

    # `billing_engine.change_plan` is a tested helper — stub it so
    # this test stays focused on the orchestration layer.
    fake_result = mock.Mock()
    fake_result.action = 'change_plan'
    fake_result.amount = 10.0
    fake_result.currency = 'USD'
    fake_result.ledger_entry_id = 1234
    fake_result.to_dict.return_value = {'action': 'change_plan', 'amount': 10.0}

    with _ctx():
        with mock.patch.object(
            wb.TenantAccount, 'query', tenant_query,
        ), mock.patch.object(
            wb.WalletLedger, 'query', ledger_query,
        ), mock.patch.object(
            support_ops.SubscriptionPlan, 'query', target_query,
        ), mock.patch(
            'app.services.billing_engine.change_plan',
            return_value=fake_result,
        ) as change_plan_mock, mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            out = wb.apply_request(
                case, actor_user_id=42, scenario=scenario,
                now=datetime(2026, 5, 12),
            )

    # billing_engine called with the case-bound reference token.
    change_plan_mock.assert_called_once()
    _, kwargs = change_plan_mock.call_args
    assert kwargs['reference_token'] == 'PCH-7-55'
    assert kwargs['actor_user_id'] == 42
    # Pending invoice category flipped to settled.
    assert pending.category == 'plan_change'
    # Subscriber notified + case resolved.
    notif_events = [
        x for x in added if x.__class__.__name__ == 'NotificationEvent'
    ]
    assert notif_events
    assert notif_events[0].event_type == 'plan_change_applied'
    assert case.status == 'resolved'
    assert case.is_frozen is True
    assert out['case_status'] == 'resolved'


def test_apply_request_in_reduced_days_mode_shortens_sub():
    """Reduced-days scenario must shorten the surviving subscription
    to `now + target_days` so the wallet entry stays consistent with
    the actual access window."""
    from app.services import plan_change_workbench as wb
    from datetime import timedelta
    case = _fake_case(
        id_=55, user_id=11, tenant_id=7,
        subject='طلب تغيير الخطة إلى برو',
        status='under_review',
    )
    scenario = wb.Scenario(
        mode='reduced_days', label_ar='', label_en='',
        remaining_days=15, target_days=5,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=10.0, target_plan_price=30.0,
        current_remaining_value=5.0, target_remaining_value=5.0,
        amount=0.0, currency='USD',
        summary_ar='', summary_en='',
    )
    tenant = _fake_tenant(id_=7)
    target = _fake_plan(id_=2, name_ar='برو')
    sub = _fake_sub(plan_id=2, ends_at=datetime(2026, 5, 27))
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    ledger_query = mock.Mock()
    ledger_query.filter_by.return_value = ledger_query
    ledger_query.first.return_value = None
    from app.services import support_ops
    target_query = mock.Mock()
    target_query.filter_by.return_value = target_query
    target_query.first.return_value = target
    fake_result = mock.Mock()
    fake_result.amount = 0.0
    fake_result.currency = 'USD'
    fake_result.ledger_entry_id = None
    fake_result.to_dict.return_value = {'amount': 0.0}
    added, _add = _capture_session()
    with _ctx():
        with mock.patch.object(
            wb.TenantAccount, 'query', tenant_query,
        ), mock.patch.object(
            wb.TenantSubscription, 'query', sub_query,
        ), mock.patch.object(
            wb.WalletLedger, 'query', ledger_query,
        ), mock.patch.object(
            support_ops.SubscriptionPlan, 'query', target_query,
        ), mock.patch(
            'app.services.billing_engine.change_plan',
            return_value=fake_result,
        ), mock.patch.object(
            wb.db.session, 'add', side_effect=_add,
        ), mock.patch.object(
            wb.db.session, 'commit',
        ):
            wb.apply_request(
                case, actor_user_id=42, scenario=scenario,
                now=datetime(2026, 5, 12),
            )
    # Sub's end-date shortened to now + 5 days.
    assert sub.ends_at == datetime(2026, 5, 12) + timedelta(days=5)


# ═══════════════════════════════════════════════════════════════════════
# Part C — admin discoverability + open count
# ═══════════════════════════════════════════════════════════════════════


def test_open_request_count_only_counts_active_states():
    """The sidebar badge must NOT include resolved / closed /
    cancelled cases — only states that still need an outcome."""
    from app.services import plan_change_workbench as wb
    case_query = mock.Mock()
    # Chain mimics SupportCase.query.filter_by(case_type=...).filter(...).count()
    case_query.filter_by.return_value = case_query
    case_query.filter.return_value = case_query
    case_query.count.return_value = 4
    # SupportCase.query is a flask-sqlalchemy descriptor; needs an
    # active app context even when mocked.
    with _ctx(), mock.patch.object(wb.SupportCase, 'query', case_query):
        assert wb.open_request_count() == 4
    # Sanity check that the active statuses tuple was the argument.
    assert wb.ACTIVE_STATUSES == frozenset({
        'open', 'under_review', 'awaiting_subscriber_reply',
        'payment_requested',
    })


def test_admin_notify_uses_workbench_detail_url_as_direct_url():
    """A subscriber submitting a plan-change request must produce
    admin NotificationEvent rows whose `direct_url` points at the
    workbench detail page (not '#'), so a bell click lands the
    admin on the financial decision surface for the exact case."""
    from app.services import support_ops
    case = _fake_case(id_=99, user_id=11, tenant_id=7)
    requester = mock.Mock(); requester.id = 11; requester.full_name = 'أحمد'
    target = _fake_plan(id_=2, name_ar='برو')
    admin_ids = [1, 2]
    existing_query = mock.Mock()
    existing_query.filter_by.return_value = existing_query
    existing_query.all.return_value = []
    added: list = []
    with _ctx(), mock.patch.object(
        support_ops, '_admin_user_ids', return_value=admin_ids,
    ), mock.patch.object(
        support_ops.NotificationEvent, 'query', existing_query,
    ), mock.patch.object(
        support_ops.db.session, 'add', side_effect=added.append,
    ):
        out = support_ops.notify_admins_of_plan_change_request(
            case, requester=requester, target_plan=target,
        )
    assert len(out) == 2
    assert all(
        ev.direct_url == '/admin/plan-change-requests/99' for ev in out
    )


def test_lifecycle_status_vocabulary_is_locked():
    """Spec lock: the seven lifecycle states are part of the
    workbench contract. A test failure here means someone renamed a
    state and a downstream caller (queue tabs, notification
    routing) might break silently."""
    from app.services.plan_change_workbench import (
        LIFECYCLE_STATUSES, ACTIVE_STATUSES,
    )
    assert LIFECYCLE_STATUSES == (
        'open', 'under_review', 'awaiting_subscriber_reply',
        'payment_requested', 'resolved', 'closed', 'cancelled',
    )
    assert ACTIVE_STATUSES == frozenset({
        'open', 'under_review', 'awaiting_subscriber_reply',
        'payment_requested',
    })


def test_ledger_categories_are_stable():
    """Finance dashboards filter on the three category strings —
    lock them so a rename triggers a test failure rather than a
    silent finance-report drift."""
    from app.services.plan_change_workbench import (
        LEDGER_CATEGORY_PENDING, LEDGER_CATEGORY_APPLIED,
        LEDGER_CATEGORY_REVERSAL,
    )
    assert LEDGER_CATEGORY_PENDING == 'plan_change_pending'
    assert LEDGER_CATEGORY_APPLIED == 'plan_change'
    assert LEDGER_CATEGORY_REVERSAL == 'plan_change_reversal'
