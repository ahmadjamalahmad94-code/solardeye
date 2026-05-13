"""v81 — plan-change admin workflow + admin notification filter.

Three product fixes verified here:

  Part A — submitting a plan-change request now fans out admin-visible
           `NotificationEvent` rows. Dedup prevents repeated submissions
           on the same case from spamming the queue.

  Part B — admin workflow helpers compute a prorated pricing diff,
           apply the plan change, write one explicit `WalletLedger`
           entry, mark the case resolved, and notify the subscriber.

  Part C — `_aggregated_notification_groups` filters out subscriber-
           targeted energy alerts (battery / phase / surplus) from
           the admin notification center while preserving admin-
           relevant items (support cases + plan-change events).

Style mirrors v65 / v68 / v74 / v76 / v78 / v80: mock-based, no DB
boot, no `create_app()`. Every model touched is patched at the
service layer so SQLAlchemy never resolves a real session.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── App context fixture ──────────────────────────────────────────────
#
# The helpers under test instantiate real SQLAlchemy model classes
# (`NotificationEvent`, `WalletLedger`) whose `__init__` registers them
# with the active session. Flask-SQLAlchemy's session helper requires
# an active Flask `app_context` even when we mock the DB connection
# elsewhere. We provide a tiny context manager that supplies one for
# the duration of each test without booting the real `create_app()`
# stack.

def _ctx():
    """Return a context manager that activates a bare Flask app
    context. Use as: `with _ctx(): ...`."""
    from flask import Flask
    from app.extensions import db
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app.app_context()


# ─── Fake-row factories ───────────────────────────────────────────────


def _fake_user(*, id_=11, is_admin=False, is_active=True, role='user',
               username='ahmad', full_name='أحمد', email=None):
    u = mock.Mock()
    u.id = id_
    u.is_admin = is_admin
    u.is_active = is_active
    u.role = role
    u.username = username
    u.full_name = full_name
    u.email = email
    return u


def _fake_plan(*, id_=2, code='pro', name_ar='برو', name_en='Pro',
               price=30.0, duration_days=30, currency='USD'):
    p = mock.Mock()
    p.id = id_
    p.code = code
    p.name_ar = name_ar
    p.name_en = name_en
    p.price = price
    p.duration_days_default = duration_days
    p.currency = currency
    return p


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
    return c


def _fake_subscription(*, plan_id=1, starts_at=None, ends_at=None,
                      status='active'):
    s = mock.Mock()
    s.plan_id = plan_id
    s.starts_at = starts_at or datetime(2026, 4, 12)
    s.ends_at = ends_at or datetime(2026, 5, 27)
    s.status = status
    s.updated_at = None
    return s


# ═══════════════════════════════════════════════════════════════════════
# Part A — admin notification on submission
# ═══════════════════════════════════════════════════════════════════════


def test_notify_admins_fans_out_one_event_per_admin():
    """Every active admin must receive exactly one notification keyed
    to the case; subscriber-targeted energy events are NOT created
    here."""
    from app.services import support_ops

    admin_ids = [1, 2, 3]
    case = _fake_case(id_=99, user_id=11, tenant_id=7)
    requester = _fake_user(id_=11)
    target = _fake_plan(id_=2, name_ar='برو')

    added: list = []
    existing_query = mock.Mock()
    existing_query.filter_by.return_value = existing_query
    existing_query.all.return_value = []

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

    assert len(out) == 3
    assert [ev.target_user_id for ev in out] == admin_ids
    # Every event is keyed to the case + the new event type so the
    # admin notification center can group and filter cleanly.
    for ev in out:
        assert ev.event_type == 'plan_change_request'
        assert ev.source_type == 'plan_change_request'
        assert ev.source_id == case.id
        assert 'برو' in ev.message


def test_notify_admins_dedup_skips_already_notified_admin():
    """Idempotency: if admin #2 already has an UNREAD notification
    for this case, a second submission must NOT create a duplicate
    event for that admin (others still get one)."""
    from app.services import support_ops

    admin_ids = [1, 2, 3]
    case = _fake_case(id_=99)
    existing_ev = mock.Mock()
    existing_ev.target_user_id = 2

    existing_query = mock.Mock()
    existing_query.filter_by.return_value = existing_query
    existing_query.all.return_value = [existing_ev]

    added: list = []
    with _ctx(), mock.patch.object(
        support_ops, '_admin_user_ids', return_value=admin_ids,
    ), mock.patch.object(
        support_ops.NotificationEvent, 'query', existing_query,
    ), mock.patch.object(
        support_ops.db.session, 'add', side_effect=added.append,
    ):
        out = support_ops.notify_admins_of_plan_change_request(case)

    assert len(out) == 2
    assert sorted(ev.target_user_id for ev in out) == [1, 3]


def test_notify_admins_no_op_when_no_admins_exist():
    """Defensive: a fresh deployment with zero active admins must
    not crash the submit route."""
    from app.services import support_ops

    case = _fake_case()
    with mock.patch.object(
        support_ops, '_admin_user_ids', return_value=[],
    ):
        assert support_ops.notify_admins_of_plan_change_request(case) == []


# ═══════════════════════════════════════════════════════════════════════
# Part B — workflow helpers (pricing + apply + reject)
# ═══════════════════════════════════════════════════════════════════════


def test_extract_plan_change_target_plan_parses_subject_name():
    """The subscriber subject is "طلب تغيير الخطة إلى <name>" with
    optional " — note". The helper must recover the target plan
    against the live catalog."""
    from app.services import support_ops

    case = _fake_case(subject='طلب تغيير الخطة إلى برو — رغبة بترقية')
    target = _fake_plan(id_=2, name_ar='برو')
    name_ar_query = mock.Mock()
    name_ar_query.filter_by.return_value = name_ar_query
    name_ar_query.first.return_value = target
    with _ctx(), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', name_ar_query,
    ):
        out = support_ops.extract_plan_change_target_plan(case)
    assert out is target


def test_extract_plan_change_target_plan_returns_none_when_marker_missing():
    from app.services import support_ops
    case = _fake_case(subject='شيء آخر تمامًا')
    assert support_ops.extract_plan_change_target_plan(case) is None


def test_compute_plan_change_quote_prorates_diff_correctly():
    """Pricing policy:
      * current_remaining_value = remaining_days / cycle * current_price
      * target_remaining_value  = remaining_days / target_cycle * target_price
      * extra_charge = target_remaining_value - current_remaining_value
    """
    from app.services import support_ops

    now = datetime(2026, 5, 12)
    # 15 days left in a 30-day cycle of a $10 plan; target is a 30-day
    # $30 plan. Current remaining-value = 15/30 * 10 = 5.00. Target
    # remaining-value = 15/30 * 30 = 15.00. Extra charge = +10.00.
    case = _fake_case(tenant_id=7)
    tenant = mock.Mock(); tenant.id = 7
    sub = _fake_subscription(
        plan_id=1,
        starts_at=datetime(2026, 4, 12),
        ends_at=datetime(2026, 5, 27),
    )
    current_plan = _fake_plan(
        id_=1, code='basic', name_ar='أساسي', price=10.0, duration_days=30,
    )
    target_plan = _fake_plan(
        id_=2, code='pro', name_ar='برو', price=30.0, duration_days=30,
    )
    tenant_query = mock.Mock()
    tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    plan_query = mock.Mock()
    plan_query.get.return_value = current_plan

    with _ctx(), mock.patch.object(
        support_ops.TenantAccount, 'query', tenant_query,
    ), mock.patch.object(
        support_ops.TenantSubscription, 'query', sub_query,
    ), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', plan_query,
    ):
        quote = support_ops.compute_plan_change_quote(
            case, target_plan=target_plan, now=now,
        )

    assert quote['remaining_days'] == 15
    assert quote['current_plan_price'] == 10.0
    assert quote['target_plan_price'] == 30.0
    # Cycle uses the actual `ends_at - starts_at` window (45 days
    # 2026-04-12 → 2026-05-27).
    assert quote['cycle_days_current'] == 45
    assert quote['cycle_days_target'] == 30
    # current_remaining_value = 15/45 * 10 = 3.33
    assert quote['current_remaining_value'] == 3.33
    # target_remaining_value = 15/30 * 30 = 15.00
    assert quote['target_remaining_value'] == 15.0
    assert quote['extra_charge'] == 11.67
    assert quote['currency'] == 'USD'


def test_compute_plan_change_quote_zero_days_yields_zero_diff():
    """A request submitted on the day the subscription ends must
    produce a zero diff so no spurious wallet entry is written."""
    from app.services import support_ops

    case = _fake_case(tenant_id=7)
    tenant = mock.Mock(); tenant.id = 7
    sub = _fake_subscription(
        plan_id=1,
        starts_at=datetime(2026, 4, 12),
        ends_at=datetime(2026, 5, 12),
    )
    current = _fake_plan(id_=1, price=10.0, duration_days=30)
    target = _fake_plan(id_=2, price=30.0, duration_days=30)

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    plan_query = mock.Mock(); plan_query.get.return_value = current

    with _ctx(), mock.patch.object(
        support_ops.TenantAccount, 'query', tenant_query,
    ), mock.patch.object(
        support_ops.TenantSubscription, 'query', sub_query,
    ), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', plan_query,
    ):
        quote = support_ops.compute_plan_change_quote(
            case, target_plan=target, now=datetime(2026, 5, 12),
        )

    assert quote['remaining_days'] == 0
    assert quote['extra_charge'] == 0.0


def test_apply_plan_change_request_writes_ledger_and_notifies_subscriber():
    """Apply path must:
      * switch tenant.plan_id + sub.plan_id
      * call apply_plan_quotas_to_tenant
      * write exactly one WalletLedger entry with the diff
      * mark the case resolved (and frozen)
      * create a subscriber notification
      * write an audit row
    """
    from app.services import support_ops

    case = _fake_case(id_=55, user_id=11, tenant_id=7, subject='')
    tenant = mock.Mock(); tenant.id = 7
    sub = _fake_subscription(plan_id=1)
    current = _fake_plan(id_=1, name_ar='أساسي', price=10.0, duration_days=30)
    target = _fake_plan(id_=2, name_ar='برو', price=30.0, duration_days=30)

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    plan_query = mock.Mock(); plan_query.get.return_value = current

    added: list = []
    notify_calls = []
    audit_calls = []

    def _audit(case_type, source_id, actor_user_id, action, summary, details=None, commit=True):
        audit_calls.append({
            'action': action, 'details': details, 'commit': commit,
        })

    def _notify(target_user_id, **kw):
        notify_calls.append({'user_id': target_user_id, **kw})

    with _ctx(), mock.patch.object(
        support_ops.TenantAccount, 'query', tenant_query,
    ), mock.patch.object(
        support_ops.TenantSubscription, 'query', sub_query,
    ), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', plan_query,
    ), mock.patch(
        'app.services.quota_engine.apply_plan_quotas_to_tenant',
    ) as quota_mock, mock.patch.object(
        support_ops, 'audit_case', side_effect=_audit,
    ), mock.patch.object(
        support_ops, 'notify_user', side_effect=_notify,
    ), mock.patch.object(
        support_ops.db.session, 'add', side_effect=added.append,
    ), mock.patch.object(
        support_ops.db.session, 'commit',
    ):
        result = support_ops.apply_plan_change_request(
            case, actor_user_id=42, target_plan=target,
            now=datetime(2026, 5, 12),
        )

    # Tenant + sub flipped to the target plan.
    assert tenant.plan_id == target.id
    assert tenant.status == 'active'
    assert sub.plan_id == target.id
    assert sub.status == 'active'
    # Plan quotas re-applied.
    quota_mock.assert_called_once()
    # Exactly one WalletLedger entry written.
    ledger_entries = [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ]
    assert len(ledger_entries) == 1
    entry = ledger_entries[0]
    assert entry.tenant_id == 7
    assert entry.actor_user_id == 42
    assert entry.category == 'plan_change'
    assert entry.reference == 'PCH-7-55'
    # The case is resolved + frozen.
    assert case.status == 'resolved'
    assert case.is_frozen is True
    # Subscriber got a notification keyed to the request.
    assert len(notify_calls) == 1
    assert notify_calls[0]['event_type'] == 'plan_change_applied'
    assert notify_calls[0]['source_id'] == case.id
    # Audit row written.
    assert audit_calls
    assert audit_calls[0]['action'] == 'plan_change.apply'


def test_apply_plan_change_skips_ledger_when_diff_is_zero():
    """If the diff rounds to 0.00, no WalletLedger entry is written
    (we don't pollute finance with no-op rows)."""
    from app.services import support_ops

    case = _fake_case(id_=55, tenant_id=7)
    tenant = mock.Mock(); tenant.id = 7
    sub = _fake_subscription(
        plan_id=1,
        starts_at=datetime(2026, 4, 12),
        ends_at=datetime(2026, 5, 12),  # 0 days remaining
    )
    current = _fake_plan(id_=1, price=10.0)
    target = _fake_plan(id_=2, price=30.0)

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    plan_query = mock.Mock(); plan_query.get.return_value = current
    added: list = []

    with _ctx(), mock.patch.object(
        support_ops.TenantAccount, 'query', tenant_query,
    ), mock.patch.object(
        support_ops.TenantSubscription, 'query', sub_query,
    ), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', plan_query,
    ), mock.patch(
        'app.services.quota_engine.apply_plan_quotas_to_tenant',
    ), mock.patch.object(
        support_ops, 'audit_case',
    ), mock.patch.object(
        support_ops, 'notify_user',
    ), mock.patch.object(
        support_ops.db.session, 'add', side_effect=added.append,
    ), mock.patch.object(
        support_ops.db.session, 'commit',
    ):
        support_ops.apply_plan_change_request(
            case, actor_user_id=42, target_plan=target,
            now=datetime(2026, 5, 12),
        )

    ledger_entries = [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ]
    assert ledger_entries == []


def test_v87b_legacy_apply_path_refuses_downgrade_and_writes_no_ledger():
    """v87b — POLICY GUARD. The legacy `support_ops.apply_plan_change_request`
    used to delegate to `billing_engine.change_plan` which writes a
    wallet credit on a downgrade. v87 forbids that semantics
    (downgrades must convert remaining value to MORE days on the
    cheaper plan, never refund). This test locks in the new policy
    guard: a downgrade through the legacy path must raise ValueError
    and write NO ledger row + leave the tenant/subscription unchanged."""
    from app.services import support_ops

    case = _fake_case(id_=55, user_id=11, tenant_id=7, subject='')
    tenant = mock.Mock(); tenant.id = 7; tenant.plan_id = 1; tenant.status = 'active'
    # Downgrade: current is $30/30d ($1/d), target is $10/30d ($0.333/d).
    sub = _fake_subscription(plan_id=1)
    current = _fake_plan(id_=1, name_ar='برو', price=30.0, duration_days=30)
    target  = _fake_plan(id_=2, name_ar='أساسي', price=10.0, duration_days=30)

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    plan_query = mock.Mock(); plan_query.get.return_value = current
    added: list = []

    raised = False
    with _ctx(), mock.patch.object(
        support_ops.TenantAccount, 'query', tenant_query,
    ), mock.patch.object(
        support_ops.TenantSubscription, 'query', sub_query,
    ), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', plan_query,
    ), mock.patch(
        'app.services.billing_engine.change_plan',
    ) as change_plan_mock, mock.patch(
        'app.services.quota_engine.apply_plan_quotas_to_tenant',
    ), mock.patch.object(
        support_ops, 'audit_case',
    ), mock.patch.object(
        support_ops, 'notify_user',
    ), mock.patch.object(
        support_ops.db.session, 'add', side_effect=added.append,
    ), mock.patch.object(
        support_ops.db.session, 'commit',
    ):
        try:
            support_ops.apply_plan_change_request(
                case, actor_user_id=42, target_plan=target,
                now=datetime(2026, 5, 12),
            )
        except ValueError as exc:
            raised = True
            assert 'downgrade' in str(exc).lower() or 'refund' in str(exc).lower()
    # Legacy path refused — and critically, billing_engine.change_plan
    # was never reached, so no credit ledger row was written.
    assert raised, 'legacy path must refuse downgrades under v87 policy'
    change_plan_mock.assert_not_called()
    # No state mutation either: tenant + sub untouched, no rows added.
    assert tenant.plan_id == 1
    assert sub.plan_id == 1
    assert case.status == 'open'
    assert added == []


def test_v87b_legacy_apply_path_still_works_for_upgrades_and_laterals():
    """The guard must NOT regress the legitimate upgrade flow.
    Upgrades and lateral switches continue to delegate to
    `billing_engine.change_plan` exactly as before; only the
    downgrade combo is refused."""
    from app.services import support_ops

    case = _fake_case(id_=55, user_id=11, tenant_id=7, subject='')
    tenant = mock.Mock(); tenant.id = 7
    sub = _fake_subscription(plan_id=1)
    # Upgrade: $10/30d → $30/30d.
    current = _fake_plan(id_=1, name_ar='أساسي', price=10.0, duration_days=30)
    target  = _fake_plan(id_=2, name_ar='برو',   price=30.0, duration_days=30)

    tenant_query = mock.Mock(); tenant_query.get.return_value = tenant
    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = sub
    plan_query = mock.Mock(); plan_query.get.return_value = current

    fake_result = mock.Mock()
    fake_result.action = 'change_plan'
    fake_result.amount = 10.0
    fake_result.currency = 'USD'
    fake_result.ledger_entry_id = None
    fake_result.to_dict.return_value = {'action': 'change_plan'}

    with _ctx(), mock.patch.object(
        support_ops.TenantAccount, 'query', tenant_query,
    ), mock.patch.object(
        support_ops.TenantSubscription, 'query', sub_query,
    ), mock.patch.object(
        support_ops.SubscriptionPlan, 'query', plan_query,
    ), mock.patch(
        'app.services.billing_engine.change_plan',
        return_value=fake_result,
    ) as change_plan_mock, mock.patch(
        'app.services.quota_engine.apply_plan_quotas_to_tenant',
    ), mock.patch.object(
        support_ops, 'audit_case',
    ), mock.patch.object(
        support_ops, 'notify_user',
    ), mock.patch.object(
        support_ops.db.session, 'add',
    ), mock.patch.object(
        support_ops.db.session, 'commit',
    ):
        result = support_ops.apply_plan_change_request(
            case, actor_user_id=42, target_plan=target,
            now=datetime(2026, 5, 12),
        )
    # Upgrade reaches the engine unchanged.
    change_plan_mock.assert_called_once()
    assert case.status == 'resolved'
    assert result.get('case_status') == 'resolved'


def test_reject_plan_change_request_closes_case_and_notifies():
    """Reject path: status=closed, frozen, subscriber notified, no
    ledger entry, audit recorded."""
    from app.services import support_ops

    case = _fake_case(id_=55, user_id=11, tenant_id=7)
    notify_calls = []
    audit_calls = []
    added: list = []

    with _ctx(), mock.patch.object(
        support_ops, 'notify_user',
        side_effect=lambda target_user_id, **kw: notify_calls.append(
            {'user_id': target_user_id, **kw}
        ),
    ), mock.patch.object(
        support_ops, 'audit_case',
        side_effect=lambda *a, **kw: audit_calls.append({'args': a, **kw}),
    ), mock.patch.object(
        support_ops.db.session, 'add', side_effect=added.append,
    ), mock.patch.object(
        support_ops.db.session, 'commit',
    ):
        out = support_ops.reject_plan_change_request(
            case, actor_user_id=42, reason='غير متوفّر حالياً',
        )

    assert case.status == 'closed'
    assert case.is_frozen is True
    assert out['reason'] == 'غير متوفّر حالياً'
    # Subscriber notification carries the rejected event type.
    assert len(notify_calls) == 1
    assert notify_calls[0]['event_type'] == 'plan_change_rejected'
    assert notify_calls[0]['user_id'] == 11
    # No ledger entry created.
    ledger_entries = [
        x for x in added if x.__class__.__name__ == 'WalletLedger'
    ]
    assert ledger_entries == []
    # Audit row recorded.
    assert audit_calls
    assert audit_calls[0]['args'][3] == 'plan_change.reject'


# ═══════════════════════════════════════════════════════════════════════
# Part C — admin notification center filter
# ═══════════════════════════════════════════════════════════════════════


def test_admin_relevant_vocabularies_cover_plan_change_workflow():
    """Spec lock: the two whitelists shared with the notification
    center must surface admin-perspective plan-change events.

    v93j note — the lists are tighter than they were in v81. We
    deliberately exclude the *subscriber*-perspective event types
    (`plan_change_applied`, `plan_change_rejected`,
    `plan_change_discussion`, `plan_change_invoice_issued`) and
    we removed the shared `plan_change_request` source-type
    because those carry 2nd-person Arabic wording aimed at the
    subscriber ("تم تحويل اشتراكك") and would look wrong in admin
    view. Admins still see plan-change activity reliably because
    admin-perspective events (`plan_change_request`,
    `plan_change_applied_admin`,
    `plan_change_payment_settled_admin`) are fanned out per-admin
    via `target_user_id`.
    """
    from app.services.support_ops import (
        ADMIN_RELEVANT_EVENT_TYPES,
        ADMIN_RELEVANT_SOURCE_TYPES,
    )
    # Admin-perspective event types — these MUST be surfaced to
    # admins. `plan_change_request` is the initial-fanout admin
    # event_type produced by `notify_admins_of_plan_change_request`.
    assert 'support' in ADMIN_RELEVANT_EVENT_TYPES
    assert 'plan_change_request' in ADMIN_RELEVANT_EVENT_TYPES
    assert 'plan_change_applied_admin' in ADMIN_RELEVANT_EVENT_TYPES
    assert 'plan_change_payment_settled_admin' in ADMIN_RELEVANT_EVENT_TYPES
    # Subscriber-perspective event types — these MUST NOT be on
    # the admin whitelist; their wording addresses the subscriber.
    assert 'plan_change_applied' not in ADMIN_RELEVANT_EVENT_TYPES
    assert 'plan_change_rejected' not in ADMIN_RELEVANT_EVENT_TYPES
    # Source-type vocabulary spans the support flow only. The
    # `plan_change_request` source_type is intentionally OMITTED
    # because both subscriber-targeted and admin-targeted plan-
    # change notifications share it; whitelisting it leaked
    # subscriber wording into admin view.
    assert {'message', 'ticket'}.issubset(ADMIN_RELEVANT_SOURCE_TYPES)
    assert 'plan_change_request' not in ADMIN_RELEVANT_SOURCE_TYPES


def test_admin_relevant_vocabularies_exclude_subscriber_energy_types():
    """The whole point of v81 Part 3: subscriber energy event_types
    must NOT be on the admin-relevant whitelist."""
    from app.services.support_ops import ADMIN_RELEVANT_EVENT_TYPES
    forbidden = {
        'phase_change', 'battery_priority',
        'actual_surplus', 'actual_surplus_shift', 'status_change',
    }
    assert ADMIN_RELEVANT_EVENT_TYPES.isdisjoint(forbidden)


# ═══════════════════════════════════════════════════════════════════════
# Sanity: existing Telegram/SMS/support flows still use their
# pre-v81 helpers (no accidental switchover).
# ═══════════════════════════════════════════════════════════════════════


def test_v81_did_not_replace_consume_quota_for_user_with_record_usage():
    """Defensive: the v81 wave did not touch Telegram / SMS / support
    quota paths. Spot-check the import surface at
    `app.blueprints.notifications` still references the gated
    `consume_quota_for_user` helper. The plan-change workflow uses
    the new tracker helpers; existing channel quotas keep their
    blocking semantics intact."""
    import inspect
    from app.blueprints import notifications as nmod
    src = inspect.getsource(nmod)
    assert 'consume_quota_for_user' in src
