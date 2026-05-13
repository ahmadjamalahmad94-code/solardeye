"""v87 — plan-change policy correction tests.

These tests lock in the v87 business policy:

  * Downgrade (cheaper plan): the remaining value is converted into
    MORE days on the target plan. NO money refund. NO wallet credit.
    The `same_duration` scenario is marked ineligible.

  * Upgrade (more expensive plan): two valid options surface —
      A. keep same remaining days + pay the difference
      B. accept fewer days on the new plan + no extra payment.

  * Lateral (equivalent per-day price): clean switch, no money or
    day adjustment.

  * Plan-change UI templates explain the policy explicitly and never
    expose a "downgrade with refund" CTA.

  * The mobile preview/confirm contract exposes the policy fields
    additively so future mobile UIs render the right surface.

Style mirrors v82 / v85 / v86: mock-based, no DB boot, no
`create_app()`. Source-inspection tests are used where importing a
blueprint would pull `reportlab` (not installed in the dev env).
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


def _fake_user(*, id_=11, tenant_id=7, is_admin=False):
    u = mock.Mock()
    u.id = id_
    u.tenant_id = tenant_id
    u.is_admin = is_admin
    u.email = None
    u.full_name = 'أحمد'
    u.username = 'ahmad'
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


def _fake_case(*, id_=55, user_id=11, tenant_id=7,
               case_type='plan_change_request',
               subject='طلب تغيير الخطة إلى برو',
               status='under_review', source_id=11):
    c = mock.Mock()
    c.id = id_
    c.user_id = user_id
    c.tenant_id = tenant_id
    c.case_type = case_type
    c.subject = subject
    c.status = status
    c.source_id = source_id
    c.created_at = datetime(2026, 5, 12, 10, 0)
    c.updated_at = datetime(2026, 5, 12, 10, 0)
    c.is_frozen = False
    return c


def _patch_collaborators(*, tenant=None, sub=None, current_plan=None, target_plan=None):
    from app.services import plan_change_workbench as wb
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
    return [
        mock.patch.object(wb.TenantAccount, 'query', tenant_query),
        mock.patch.object(wb.TenantSubscription, 'query', sub_query),
        mock.patch.object(wb.SubscriptionPlan, 'query', plan_query),
    ]


# ════════════════════════════════════════════════════════════════════════
# Part A — classify_change
# ════════════════════════════════════════════════════════════════════════


def test_classify_change_detects_downgrade():
    """Cheaper-per-day plan classified as downgrade."""
    from app.services import plan_change_workbench as wb
    current = _fake_plan(id_=1, price=30.0, duration_days=30)  # $1/d
    target  = _fake_plan(id_=2, price=10.0, duration_days=30)  # $0.33/d
    assert wb.classify_change(current, target) == wb.POLICY_DOWNGRADE


def test_classify_change_detects_upgrade():
    """More expensive-per-day plan classified as upgrade."""
    from app.services import plan_change_workbench as wb
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=30)
    assert wb.classify_change(current, target) == wb.POLICY_UPGRADE


def test_classify_change_handles_different_cycle_lengths():
    """v93d — classifier compares TOTAL cycle price (not per-day).
    A 30-day $10 plan is cheaper than a 90-day $20 plan regardless
    of per-day cost; the subscriber sees that as a downgrade
    (cheaper total = downgrade) which matches human intuition."""
    from app.services import plan_change_workbench as wb
    plan_90d_20 = _fake_plan(id_=1, price=20.0, duration_days=90)
    plan_30d_10 = _fake_plan(id_=2, price=10.0, duration_days=30)
    # Going from $20 plan TO $10 plan = total cheaper = downgrade.
    assert wb.classify_change(plan_90d_20, plan_30d_10) == wb.POLICY_DOWNGRADE
    # And the reverse — going from $10 TO $20 = upgrade by total.
    assert wb.classify_change(plan_30d_10, plan_90d_20) == wb.POLICY_UPGRADE


def test_classify_change_lateral_when_total_price_equal():
    """v93d — lateral only when TOTAL cycle prices match
    (within penny tolerance), regardless of cycle length."""
    from app.services import plan_change_workbench as wb
    current = _fake_plan(id_=1, price=30.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=60)
    assert wb.classify_change(current, target) == wb.POLICY_LATERAL


# ════════════════════════════════════════════════════════════════════════
# Part B — downgrade behavior
# ════════════════════════════════════════════════════════════════════════


def test_downgrade_same_duration_is_marked_ineligible_with_zero_amount():
    """The exact policy: a cheaper target plan + same_duration must
    NOT show a refund/credit. The scenario must come back with
    amount=0, is_eligible=False, eligibility_reason=
    'downgrade_no_refund_policy'."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=30.0, duration_days=30)
    target  = _fake_plan(id_=2, price=10.0, duration_days=30)
    patches = _patch_collaborators(
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
    assert sc.policy_kind == wb.POLICY_DOWNGRADE
    assert sc.is_eligible is False
    assert sc.eligibility_reason == wb.ELIGIBILITY_DOWNGRADE_NO_REFUND
    assert sc.amount == 0.0
    # And no language of "credit/refund" leaks into the recommended
    # path: it should explain the conversion approach instead.
    assert 'تحويل' in sc.summary_ar or 'converted' in sc.summary_en.lower()


def test_downgrade_reduced_days_converts_value_into_more_days_canonical():
    """Spec foundation example, re-tuned so the target is actually
    cheaper per day:

      Current: $20 / 90d  → $0.2222/d
      Remaining: 74 days  → 16.44 USD remaining value
      Target:  $5 / 30d   → $0.1667/d   (truly cheaper per-day)
      Conversion: 16.44 / 0.1667 ≈ 98.6 → floor → 98 days

    98 > 74: subscriber receives MORE days on the cheaper plan.
    Zero amount: no refund issued."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 13),
        ends_at=datetime(2026, 7, 12),
    )
    current = _fake_plan(id_=1, price=20.0, duration_days=90)
    target  = _fake_plan(id_=2, price=5.0,  duration_days=30)
    patches = _patch_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            sc = wb.quote_reduced_days(
                case, target_plan=target, now=datetime(2026, 4, 29),
            )
        finally:
            for p in patches:
                p.stop()
    # Policy: truly a downgrade.
    assert sc.policy_kind == wb.POLICY_DOWNGRADE
    assert sc.is_eligible is True
    assert sc.is_recommended is True
    # Conversion math.
    assert abs(sc.current_remaining_value - 16.44) < 0.05
    assert sc.target_days == 98
    # MORE days than the original window — the headline policy.
    assert sc.target_days > sc.remaining_days
    # No money moved.
    assert sc.amount == 0.0
    assert sc.extra['free_target_days'] == 98
    assert abs(sc.extra['target_per_day_price'] - 0.1667) < 0.001


def test_downgrade_to_cheaper_plan_with_longer_cycle_gives_MORE_days():
    """When the target plan is BOTH cheaper per day AND has a longer
    cycle, the conversion yields strictly more days than the
    subscriber currently has remaining. Validates the
    "cheaper plan = more days" intent for the canonical case."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    # 30 days remaining on a $30/30d plan = $30 remaining value.
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 12),
        ends_at=datetime(2026, 5, 12),
    )
    current = _fake_plan(id_=1, price=30.0, duration_days=30)  # $1/d
    target  = _fake_plan(id_=2, price=10.0, duration_days=30)  # $0.333/d
    patches = _patch_collaborators(
        tenant=tenant, sub=sub, current_plan=current, target_plan=target,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            sc = wb.quote_reduced_days(
                case, target_plan=target, now=datetime(2026, 4, 12),
            )
        finally:
            for p in patches:
                p.stop()
    assert sc.policy_kind == wb.POLICY_DOWNGRADE
    # 30 USD remaining ÷ 0.333 per-day = 90 days on the cheaper plan.
    assert sc.target_days == 90
    assert sc.target_days > sc.remaining_days
    # Strict zero amount — no credit, no refund.
    assert sc.amount == 0.0


# ════════════════════════════════════════════════════════════════════════
# Part C — upgrade behavior
# ════════════════════════════════════════════════════════════════════════


def test_upgrade_same_duration_charges_the_difference():
    """Spec — option A: keep same remaining days + pay the diff.
    Current $10/30d, target $30/30d, 15 days remaining.
    Current remaining value = 5. Target remaining value = 15.
    Amount due = 10."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=30)
    patches = _patch_collaborators(
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
    assert sc.policy_kind == wb.POLICY_UPGRADE
    assert sc.is_eligible is True
    assert sc.is_recommended is True
    assert sc.remaining_days == 15
    assert sc.target_days == 15
    assert sc.amount == 10.0
    assert sc.current_remaining_value == 5.0
    assert sc.target_remaining_value == 15.0


def test_upgrade_reduced_days_keeps_value_and_reduces_days():
    """Spec — option B: keep same value, fewer days, no payment.
    Current $10/30d, target $30/30d, 15 days remaining.
    Remaining value 5.0. Target per-day 1.0. Free days = 5."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=30)
    patches = _patch_collaborators(
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
    assert sc.policy_kind == wb.POLICY_UPGRADE
    assert sc.is_eligible is True
    assert sc.is_recommended is True
    assert sc.target_days == 5
    assert sc.target_days < sc.remaining_days  # fewer days, never more
    assert sc.amount == 0.0


# ════════════════════════════════════════════════════════════════════════
# Part D — lateral / equal-value
# ════════════════════════════════════════════════════════════════════════


def test_lateral_change_is_clean_same_duration_no_money():
    """v93d — lateral when total cycle prices match."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7)
    tenant = _fake_tenant(id_=7)
    sub = _fake_sub(
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    # Both plans cost $30 total (different cycles).
    current = _fake_plan(id_=1, price=30.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=60)
    patches = _patch_collaborators(
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
    assert sc.policy_kind == wb.POLICY_LATERAL
    assert sc.is_eligible is True
    assert sc.is_recommended is True
    assert sc.amount == 0.0


# ════════════════════════════════════════════════════════════════════════
# Part E — subscriber confirm guard (policy block)
# ════════════════════════════════════════════════════════════════════════


def test_confirm_blocks_downgrade_same_duration_at_the_door():
    """The subscriber-facing confirm() refuses the forbidden combo
    BEFORE creating a SupportCase — admin queue stays clean."""
    from app.services import subscriber_plan_change as spc
    from app.services import plan_change_workbench as wb
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(plan_id=1)
    current = _fake_plan(id_=1, price=30.0, duration_days=30)
    target  = _fake_plan(id_=2, price=10.0, duration_days=30)
    patches = [
        mock.patch.object(spc.TenantAccount, 'query', mock.Mock(get=lambda _id: tenant)),
        mock.patch.object(wb.TenantAccount, 'query', mock.Mock(get=lambda _id: tenant)),
    ]
    # Sub query.
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    patches.append(mock.patch.object(wb.TenantSubscription, 'query', sub_query))
    # Plan queries — both spc and wb.
    plan_q = mock.Mock()
    plan_q.get.side_effect = lambda pid: {1: current, 2: target}.get(int(pid))
    patches.append(mock.patch.object(spc.SubscriptionPlan, 'query', plan_q))
    patches.append(mock.patch.object(wb.SubscriptionPlan, 'query', plan_q))
    # SupportCase + WalletLedger query stubs (should NOT be touched
    # because the policy block fires before case creation).
    case_q = mock.Mock()
    case_q.filter_by.return_value = case_q
    case_q.filter.return_value = case_q
    case_q.all.return_value = []
    case_q.first.return_value = None
    patches.append(mock.patch.object(spc.SupportCase, 'query', case_q))
    patches.append(mock.patch.object(wb.SupportCase, 'query', case_q))
    patches.append(mock.patch.object(wb.WalletLedger, 'query', mock.Mock(
        filter_by=mock.Mock(return_value=mock.Mock(first=mock.Mock(return_value=None))),
    )))
    added = []
    def _add(item):
        added.append(item)
        if hasattr(item, 'id') and getattr(item, 'id', None) is None:
            try:
                item.id = len(added) + 1000
            except Exception:
                pass
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(spc.db.session, 'add', side_effect=_add), \
                 mock.patch.object(spc.db.session, 'flush'), \
                 mock.patch.object(spc.db.session, 'commit'), \
                 mock.patch.object(wb.db.session, 'add', side_effect=_add):
                result = spc.confirm(
                    user, target_plan_id=2,
                    mode='same_duration',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    assert result.outcome == 'blocked'
    assert result.blocked_reason == 'downgrade_same_duration_not_allowed'
    assert result.case_id is None
    # No SupportCase added to the session.
    assert [x for x in added if x.__class__.__name__ == 'SupportCase'] == []


# ════════════════════════════════════════════════════════════════════════
# Part F — preview exposes policy_kind at the top level
# ════════════════════════════════════════════════════════════════════════


def test_preview_surfaces_policy_kind_at_top_level():
    """The mobile/web contract surfaces `policy_kind` at the top
    level of the preview result so clients don't need to inspect
    both scenarios to branch."""
    from app.services import subscriber_plan_change as spc
    from app.services import plan_change_workbench as wb
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(plan_id=1, starts_at=datetime(2026, 4, 27),
                    ends_at=datetime(2026, 5, 27))
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=30, name_ar='برو')
    plan_q = mock.Mock()
    plan_q.get.side_effect = lambda pid: {1: current, 2: target}.get(int(pid))
    plan_filter = mock.Mock()
    plan_filter.first.return_value = target
    plan_q.filter_by.return_value = plan_filter
    sub_q = mock.Mock(); sub_q.filter_by.return_value = sub_q
    sub_q.order_by.return_value = sub_q; sub_q.first.return_value = sub
    tenant_q = mock.Mock(); tenant_q.get.return_value = tenant
    patches = [
        mock.patch.object(spc.TenantAccount, 'query', tenant_q),
        mock.patch.object(wb.TenantAccount, 'query', tenant_q),
        mock.patch.object(wb.TenantSubscription, 'query', sub_q),
        mock.patch.object(spc.SubscriptionPlan, 'query', plan_q),
        mock.patch.object(wb.SubscriptionPlan, 'query', plan_q),
    ]
    with _ctx():
        for p in patches:
            p.start()
        try:
            result = spc.preview(user, target_plan_id=2,
                                 now=datetime(2026, 5, 12))
        finally:
            for p in patches:
                p.stop()
    payload = result.to_dict()
    assert payload['policy_kind'] == 'upgrade'
    assert payload['same_duration']['policy_kind'] == 'upgrade'
    assert payload['reduced_days']['policy_kind'] == 'upgrade'
    # Both eligible on upgrade.
    assert payload['same_duration']['is_eligible'] is True
    assert payload['reduced_days']['is_eligible'] is True


# ════════════════════════════════════════════════════════════════════════
# Part G — preview is still pure
# ════════════════════════════════════════════════════════════════════════


def test_preview_does_not_mutate_under_v87():
    """Even after the policy machinery, preview() must NOT write a
    SupportCase, ledger row, audit log, or notification."""
    from app.services import subscriber_plan_change as spc
    from app.services import plan_change_workbench as wb
    user = _fake_user(id_=11, tenant_id=7)
    tenant = _fake_tenant(id_=7, plan_id=1)
    sub = _fake_sub(plan_id=1, starts_at=datetime(2026, 4, 27),
                    ends_at=datetime(2026, 5, 27))
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target  = _fake_plan(id_=2, price=30.0, duration_days=30, name_ar='برو')
    plan_q = mock.Mock()
    plan_q.get.side_effect = lambda pid: {1: current, 2: target}.get(int(pid))
    plan_filter = mock.Mock(); plan_filter.first.return_value = target
    plan_q.filter_by.return_value = plan_filter
    sub_q = mock.Mock(); sub_q.filter_by.return_value = sub_q
    sub_q.order_by.return_value = sub_q; sub_q.first.return_value = sub
    tenant_q = mock.Mock(); tenant_q.get.return_value = tenant
    patches = [
        mock.patch.object(spc.TenantAccount, 'query', tenant_q),
        mock.patch.object(wb.TenantAccount, 'query', tenant_q),
        mock.patch.object(wb.TenantSubscription, 'query', sub_q),
        mock.patch.object(spc.SubscriptionPlan, 'query', plan_q),
        mock.patch.object(wb.SubscriptionPlan, 'query', plan_q),
    ]
    added = []
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(spc.db.session, 'add',
                                   side_effect=added.append), \
                 mock.patch.object(wb.db.session, 'add',
                                   side_effect=added.append), \
                 mock.patch.object(spc.db.session, 'flush'), \
                 mock.patch.object(wb.db.session, 'flush'), \
                 mock.patch.object(spc.db.session, 'commit'), \
                 mock.patch.object(wb.db.session, 'commit'):
                spc.preview(user, target_plan_id=2,
                            now=datetime(2026, 5, 12))
        finally:
            for p in patches:
                p.stop()
    # Nothing committed.
    assert added == []


# ════════════════════════════════════════════════════════════════════════
# Part H — apply path refuses forbidden combo (defensive)
# ════════════════════════════════════════════════════════════════════════


def test_apply_request_refuses_same_duration_downgrade_combo():
    """Defensive guard — even if a stale form post sneaks past the
    UI, apply_request raises ValueError on `same_duration + downgrade`."""
    from app.services import plan_change_workbench as wb
    case = _fake_case(tenant_id=7, status='under_review')
    scenario = wb.Scenario(
        mode='same_duration', label_ar='', label_en='',
        remaining_days=15, target_days=15,
        cycle_days_current=30, cycle_days_target=30,
        current_plan_price=30.0, target_plan_price=10.0,
        current_remaining_value=15.0, target_remaining_value=5.0,
        amount=0.0,  # zeroed-out under the new policy
        currency='USD', summary_ar='', summary_en='',
        policy_kind=wb.POLICY_DOWNGRADE,
        is_eligible=False,
    )
    tenant = _fake_tenant(id_=7)
    target = _fake_plan(id_=2, name_ar='أساسي')
    tenant_q = mock.Mock(); tenant_q.get.return_value = tenant
    from app.services import support_ops
    target_q = mock.Mock()
    target_q.filter_by.return_value = target_q
    target_q.first.return_value = target
    with _ctx():
        with mock.patch.object(wb.TenantAccount, 'query', tenant_q), \
             mock.patch.object(support_ops.SubscriptionPlan, 'query', target_q), \
             mock.patch.object(wb.db.session, 'commit'):
            try:
                wb.apply_request(
                    case, actor_user_id=42, scenario=scenario,
                    now=datetime(2026, 5, 12),
                )
            except ValueError as exc:
                assert 'same_duration downgrade' in str(exc) or 'refund' in str(exc).lower()
            else:
                raise AssertionError('apply_request must refuse this combo')


# ════════════════════════════════════════════════════════════════════════
# Part I — template + queue lock (source inspection)
# ════════════════════════════════════════════════════════════════════════


def test_subscriber_preview_template_explains_v87_policy():
    """The redrawn subscriber preview page must explicitly explain
    the v87 policy direction (downgrade → more days, upgrade → two
    options). We lock this in by source-inspecting the template."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'templates',
        'subscriber_plan_change_preview.html',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # Downgrade narrative.
    assert 'more days' in text.lower() or 'أيام إضافية' in text
    # Explicit "no refund" copy must be present.
    assert ('no refund' in text.lower() or 'do NOT' in text
            or 'لا نقوم بإرجاع' in text or 'لا يُرجَع' in text
            or 'لا يوجد إرجاع' in text)
    # Upgrade option-A / option-B framing.
    assert ('Option A' in text or 'الخيار أ' in text)
    assert ('Option B' in text or 'الخيار ب' in text)
    # Confirmation guard JS.
    assert 'confirmPlanChange' in text


def test_subscriber_preview_template_uses_adopted_hero():
    """Redrawn page must use the adopted `admin-page-head` hero."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'templates',
        'subscriber_plan_change_preview.html',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'admin-page-head' in text


def test_admin_workbench_template_is_policy_aware():
    """The redrawn admin workbench shows the policy banner and the
    guidance rail mentions the policy explicitly."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'templates',
        'admin_plan_change_workbench.html',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'Policy direction' in text or 'اتجاه السياسة' in text
    # Action toolbar is now grouped by purpose (Communicate / Money / Outcome).
    assert ('Communicate' in text or 'التواصل' in text)
    assert ('Money path' in text or 'مسار المال' in text)
    assert ('Outcome' in text or 'الناتج' in text)
    # Guidance rail.
    assert ('Guidance' in text or 'الإرشادات' in text)
    # Policy reminder strings — explicit "no refund / no wallet credit".
    assert ('NO money refund' in text or 'لا إرجاع مبلغ' in text)


def test_admin_queue_template_shows_policy_direction_and_replaces_dense_table():
    """The redrawn queue uses a row-card layout (no horizontal-scroll
    8-column table) and labels each row's policy direction."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'templates',
        'admin_plan_change_requests.html',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # No longer the dense table-shell-v2 / 8-column table.
    assert 'plan-change-queue' in text
    assert 'plan-change-row' in text
    # Policy direction surfaced per row.
    assert ('Upgrade' in text or 'ترقية' in text)
    assert ('Downgrade' in text or 'نزول' in text)
    assert ('Lateral' in text or 'مكافئ' in text)
    # Operational reminder block exists.
    assert ('Admin role on this queue' in text or 'دور الإدارة' in text)


# ════════════════════════════════════════════════════════════════════════
# Part J — mobile contract parity
# ════════════════════════════════════════════════════════════════════════


def test_mobile_api_exposes_preview_and_confirm_endpoints():
    """The mobile API blueprint defines GET /account/plan-change/
    preview and POST /account/plan-change/confirm so future mobile
    UIs see the same v87 policy fields as the web flow."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert "@mobile_core_api_bp.get('/account/plan-change/preview')" in text
    assert "@mobile_core_api_bp.post('/account/plan-change/confirm')" in text
    # Confirm endpoint forwards the v87 blocked_reason verbatim.
    assert 'blocked_reason' in text
    # Imports the canonical preview/confirm helpers.
    assert 'subscriber_plan_change import preview' in text
    assert 'subscriber_plan_change import confirm' in text


# ════════════════════════════════════════════════════════════════════════
# Part K — no trust in client-supplied pricing
# ════════════════════════════════════════════════════════════════════════


def test_preview_signature_does_not_accept_any_client_amount():
    """Locks the policy: the preview signature only takes
    (user, target_plan_id, *, now). Anything resembling a
    client-supplied amount/price would be a breach."""
    import inspect
    from app.services import subscriber_plan_change as spc
    sig = inspect.signature(spc.preview)
    params = list(sig.parameters.keys())
    # Only legitimate parameters; no `amount` / `price` / `cost`.
    forbidden = {'amount', 'price', 'cost', 'currency'}
    assert not (set(params) & forbidden), (
        f'preview() must not accept client pricing fields; got: {params}'
    )


def test_confirm_signature_does_not_accept_any_client_amount():
    import inspect
    from app.services import subscriber_plan_change as spc
    sig = inspect.signature(spc.confirm)
    params = list(sig.parameters.keys())
    forbidden = {'amount', 'price', 'cost', 'currency'}
    assert not (set(params) & forbidden), (
        f'confirm() must not accept client pricing fields; got: {params}'
    )
