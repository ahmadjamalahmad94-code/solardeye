"""v82 — canonical subscription billing engine tests.

Covers the six lifecycle actions and the shared invariants the new
`billing_engine` service must hold:

  Part A — `activate`     : new sub row, full-price ledger, trial path skips charge.
  Part B — `renew`        : new sub row stacks on top of an active end-date
                            so the subscriber doesn't lose paid time.
  Part C — `extend`       : prorated fraction of plan price (fixes the
                            existing full-price bug). Trial extension
                            skips the ledger.
  Part D — `change_plan`  : prorated diff identical to v81's math; uses
                            an explicit reference_token when supplied.
  Part E — `reactivate`   : new sub at `now`, full-price ledger, REA-… ref.
  Part F — `cancel`       : flips status without a ledger entry.

Style mirrors v76 / v78 / v80 / v81: mock-based, no DB boot, no
`create_app()`. Each test wraps the engine call in a bare Flask app
context (`_ctx`) so SQLAlchemy model instantiation works without a
real engine.
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


def _ctx():
    """Return a context manager that activates a bare Flask app
    context. Required because the engine instantiates real
    `TenantSubscription` / `WalletLedger` model classes whose
    `__init__` registers them with the active session — that lookup
    fails outside an app context even when the session itself is
    mocked."""
    from flask import Flask
    from app.extensions import db
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app.app_context()


# ─── Fake-row factories ───────────────────────────────────────────────


def _fake_tenant(*, id_=7, plan_id=1, status='active'):
    t = mock.Mock()
    t.id = id_
    t.plan_id = plan_id
    t.status = status
    return t


def _fake_plan(
    *, id_=1, code='basic', name_ar='أساسي', name_en='Basic',
    price=10.0, duration_days=30, currency='USD',
):
    p = mock.Mock()
    p.id = id_
    p.code = code
    p.name_ar = name_ar
    p.name_en = name_en
    p.price = price
    p.duration_days_default = duration_days
    p.currency = currency
    return p


def _fake_sub(
    *, id_=99, plan_id=1, status='active',
    starts_at=None, ends_at=None, notes='',
):
    s = mock.Mock()
    s.id = id_
    s.plan_id = plan_id
    s.status = status
    s.starts_at = starts_at or datetime(2026, 4, 12)
    s.ends_at = ends_at or datetime(2026, 5, 12)
    s.trial_ends_at = None
    s.updated_at = None
    s.notes = notes
    return s


def _capture_session():
    """Drop-in helpers that capture every `db.session.add` call and
    keep ledger entry ids deterministic so tests can introspect.
    Returns `(added_list, patched_add, patched_flush, patched_commit)`.
    """
    added: list = []
    _counter = {'n': 100}

    def _add(item):
        added.append(item)
        # Mimic the auto-id behaviour of a real commit so engine code
        # can read `entry.id` immediately after `flush`.
        if hasattr(item, 'id') and getattr(item, 'id', None) is None:
            _counter['n'] += 1
            try:
                item.id = _counter['n']
            except Exception:
                pass

    return added, _add


def _patch_engine_collaborators(*, current_sub=None, current_plan=None):
    """Bundle the standard mocks every engine test needs:

      * `TenantSubscription.query` resolves the supplied `current_sub`.
      * `SubscriptionPlan.query.get(...)` resolves `current_plan`.
      * `apply_plan_quotas_to_tenant` is a no-op so the quota engine
        never runs.
    """
    from app.services import billing_engine

    sub_query = mock.Mock()
    sub_query.filter_by.return_value = sub_query
    sub_query.order_by.return_value = sub_query
    sub_query.first.return_value = current_sub

    plan_query = mock.Mock()
    plan_query.get.return_value = current_plan

    return [
        mock.patch.object(
            billing_engine.TenantSubscription, 'query', sub_query,
        ),
        mock.patch.object(
            billing_engine.SubscriptionPlan, 'query', plan_query,
        ),
        mock.patch(
            'app.services.quota_engine.apply_plan_quotas_to_tenant',
        ),
    ]


# ═══════════════════════════════════════════════════════════════════════
# Part A — activate
# ═══════════════════════════════════════════════════════════════════════


def test_activate_creates_new_sub_and_writes_full_price_debit():
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=None, status='trial')
    plan = _fake_plan(id_=1, price=20.0, duration_days=30, currency='USD')
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=None, current_plan=None)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.activate(
                    tenant, plan, days=30, actor_user_id=42,
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()

    # Tenant flipped to active on the new plan.
    assert tenant.plan_id == 1
    assert tenant.status == 'active'
    # A new TenantSubscription was created.
    subs = [x for x in added if x.__class__.__name__ == 'TenantSubscription']
    assert len(subs) == 1
    assert subs[0].plan_id == 1
    assert subs[0].status == 'active'
    assert subs[0].activation_mode == 'manual'
    # A full-price WalletLedger debit was written.
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert len(ledgers) == 1
    entry = ledgers[0]
    assert entry.entry_type == 'debit'
    assert entry.amount == 20.0
    assert entry.category == 'subscription'
    assert entry.reference.startswith('ACT-7-')
    # Result shape carries everything needed for the admin UI.
    assert result.action == 'activate'
    assert result.amount == 20.0
    assert result.currency == 'USD'
    assert result.ledger_entry_id is not None
    assert '20.00 USD' in result.basis


def test_activate_trial_skips_ledger_entry():
    """Trials are free — no money moves, even though a new
    subscription row is still written."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=None, status='trial')
    plan = _fake_plan(id_=1, price=20.0, duration_days=7)
    added, _add = _capture_session()
    patches = _patch_engine_collaborators()
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.activate(
                    tenant, plan, days=7, activation_mode='trial',
                    actor_user_id=42, now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers == []
    assert result.amount == 0.0
    assert result.extra['is_trial'] is True
    assert tenant.status == 'trial'
    subs = [x for x in added if x.__class__.__name__ == 'TenantSubscription']
    assert subs[0].status == 'trial'
    assert subs[0].trial_ends_at is not None


def test_activate_free_plan_skips_ledger_entry():
    """A paid activation on a free plan (price=0) must also skip the
    ledger — `_write_ledger` floors at 0.01."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=None, status='trial')
    plan = _fake_plan(id_=1, price=0.0, duration_days=30)
    added, _add = _capture_session()
    patches = _patch_engine_collaborators()
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.activate(
                    tenant, plan, days=30, now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers == []
    assert result.amount == 0.0


# ═══════════════════════════════════════════════════════════════════════
# Part B — renew
# ═══════════════════════════════════════════════════════════════════════


def test_renew_stacks_new_cycle_on_top_of_active_end_date():
    """The new cycle should start at the current `ends_at` when the
    sub is still active — subscriber doesn't lose paid time."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='active')
    plan = _fake_plan(id_=1, price=20.0, duration_days=30, currency='USD')
    current_sub = _fake_sub(
        id_=10, plan_id=1, status='active',
        starts_at=datetime(2026, 4, 12),
        ends_at=datetime(2026, 5, 27),  # 15 days in the future
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=current_sub, current_plan=plan)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.renew(
                    tenant, plan, days=30, actor_user_id=42,
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    subs = [x for x in added if x.__class__.__name__ == 'TenantSubscription']
    assert len(subs) == 1
    new_sub = subs[0]
    # Stacked: starts at the previous `ends_at`.
    assert new_sub.starts_at == datetime(2026, 5, 27)
    assert new_sub.ends_at == datetime(2026, 5, 27) + timedelta(days=30)
    assert result.extra['stacked_from_previous'] is True
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert len(ledgers) == 1
    assert ledgers[0].amount == 20.0
    assert ledgers[0].category == 'renewal'
    assert ledgers[0].reference.startswith('REN-7-')


def test_renew_starts_now_when_previous_sub_expired():
    """If the prior sub is already in the past, the new cycle starts
    today — there's nothing to stack on."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='expired')
    plan = _fake_plan(id_=1, price=20.0, duration_days=30)
    expired_sub = _fake_sub(
        id_=10, plan_id=1, status='expired',
        starts_at=datetime(2026, 3, 12),
        ends_at=datetime(2026, 4, 12),  # already in the past
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=expired_sub, current_plan=plan)
    now = datetime(2026, 5, 12)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.renew(
                    tenant, plan, days=30, now=now,
                )
        finally:
            for p in patches:
                p.stop()
    subs = [x for x in added if x.__class__.__name__ == 'TenantSubscription']
    assert subs[0].starts_at == now
    assert result.extra['stacked_from_previous'] is False


# ═══════════════════════════════════════════════════════════════════════
# Part C — extend (prorated)
# ═══════════════════════════════════════════════════════════════════════


def test_extend_charges_prorated_fraction_of_plan_price():
    """Pre-v82 bug: extending by 5 days on a $20 30-day plan charged
    the FULL $20. v82 charges (5/30) * 20 = 3.33."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='active')
    plan = _fake_plan(id_=1, price=20.0, duration_days=30)
    current_sub = _fake_sub(
        id_=10, plan_id=1, status='active',
        ends_at=datetime(2026, 5, 27),
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=current_sub, current_plan=plan)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.extend(
                    tenant, extra_days=5, actor_user_id=42,
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    # `ends_at` advanced by 5 days from the prior end (still in
    # future, so we anchor on it instead of `now`).
    assert current_sub.ends_at == datetime(2026, 5, 27) + timedelta(days=5)
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert len(ledgers) == 1
    # 5 / 30 * 20.00 = 3.33 (rounded).
    assert ledgers[0].amount == 3.33
    assert ledgers[0].category == 'renewal'
    assert ledgers[0].reference == 'EXT-7-10'
    assert result.action == 'extend'
    assert result.amount == 3.33
    assert 'Prorated 5/30' in result.basis


def test_extend_trial_extension_skips_ledger():
    """Trial extensions never produce a ledger entry."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='trial')
    plan = _fake_plan(id_=1, price=20.0, duration_days=30)
    current_sub = _fake_sub(
        id_=10, plan_id=1, status='trial',
        ends_at=datetime(2026, 5, 27),
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=current_sub, current_plan=plan)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.extend(
                    tenant, extra_days=7, is_trial_extension=True,
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers == []
    assert current_sub.status == 'trial'
    assert tenant.status == 'trial'
    assert result.amount == 0.0
    assert result.basis == 'Trial extension — no charge.'


def test_extend_requires_existing_sub():
    """An extend on a tenant with no subscription must raise instead
    of silently doing nothing."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=None, status='trial')
    patches = _patch_engine_collaborators(current_sub=None, current_plan=None)
    with _ctx():
        for p in patches:
            p.start()
        try:
            try:
                billing_engine.extend(tenant, extra_days=5)
            except ValueError as exc:
                assert 'existing subscription' in str(exc)
            else:
                raise AssertionError('expected ValueError')
        finally:
            for p in patches:
                p.stop()


# ═══════════════════════════════════════════════════════════════════════
# Part D — change_plan
# ═══════════════════════════════════════════════════════════════════════


def test_change_plan_writes_prorated_diff_and_preserves_end_date():
    """Mirrors v81's quote math. With 15 days remaining on a $10 30-day
    plan switching to a $30 30-day plan, the diff is
    (15/30)*30 − (15/30)*10 = 15 − 5 = +10.00."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='active')
    current_plan = _fake_plan(id_=1, price=10.0, duration_days=30)
    target_plan = _fake_plan(id_=2, price=30.0, duration_days=30)
    current_sub = _fake_sub(
        id_=10, plan_id=1, status='active',
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),  # 15 days remaining at now=2026-05-12
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(
        current_sub=current_sub, current_plan=current_plan,
    )
    preserved_ends_at = current_sub.ends_at
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.change_plan(
                    tenant, target_plan, actor_user_id=42,
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    # Tenant + sub flipped to target.
    assert tenant.plan_id == 2
    assert current_sub.plan_id == 2
    # End date preserved — subscriber keeps paid time.
    assert current_sub.ends_at == preserved_ends_at
    # One diff ledger entry written.
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert len(ledgers) == 1
    assert ledgers[0].entry_type == 'debit'
    assert ledgers[0].amount == 10.0
    assert ledgers[0].category == 'plan_change'
    # No reference_token passed → defaults to PCH-<tenant>-<sub>.
    assert ledgers[0].reference == 'PCH-7-10'
    assert result.amount == 10.0
    assert result.extra['remaining_days'] == 15


def test_change_plan_honours_explicit_reference_token():
    """Used by the v81 support-case path so finance can trace each
    plan-change line back to the originating support case id, not
    just the sub id."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1)
    current_plan = _fake_plan(id_=1, price=10.0, duration_days=30)
    target_plan = _fake_plan(id_=2, price=30.0, duration_days=30)
    current_sub = _fake_sub(
        id_=10, plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(
        current_sub=current_sub, current_plan=current_plan,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                billing_engine.change_plan(
                    tenant, target_plan,
                    reference_token='PCH-7-CASE99',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers[0].reference == 'PCH-7-CASE99'


def test_change_plan_credit_when_downgrading_mid_cycle():
    """Downgrade: target_remaining < current_remaining → ledger
    `credit`, amount stored as positive, result.amount stays
    negative so the engine API is unambiguous."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1)
    current_plan = _fake_plan(id_=1, price=30.0, duration_days=30)
    target_plan = _fake_plan(id_=2, price=10.0, duration_days=30)
    current_sub = _fake_sub(
        id_=10, plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(
        current_sub=current_sub, current_plan=current_plan,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.change_plan(
                    tenant, target_plan, now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert len(ledgers) == 1
    assert ledgers[0].entry_type == 'credit'
    # (15/30)*30 - (15/30)*10 = 15 - 5 = -10.00 from subscriber's POV.
    assert ledgers[0].amount == 10.0  # stored as positive magnitude
    assert result.amount == -10.0     # signed result on the API


def test_change_plan_zero_diff_skips_ledger():
    """Switching between two equally-priced plans with the same cycle
    produces no diff — no ledger row written."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1)
    current_plan = _fake_plan(id_=1, price=20.0, duration_days=30)
    target_plan = _fake_plan(id_=2, price=20.0, duration_days=30)
    current_sub = _fake_sub(
        id_=10, plan_id=1,
        starts_at=datetime(2026, 4, 27),
        ends_at=datetime(2026, 5, 27),
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(
        current_sub=current_sub, current_plan=current_plan,
    )
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                billing_engine.change_plan(
                    tenant, target_plan, now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers == []


def test_change_plan_falls_back_to_activate_when_no_prior_sub():
    """Edge case: a tenant with no prior subscription that requests
    a plan change is treated as a first-time activation."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=None, status='trial')
    target = _fake_plan(id_=2, price=30.0, duration_days=30)
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=None, current_plan=None)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.change_plan(
                    tenant, target, now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    assert result.action == 'activate'
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    # Full price, ACT- reference.
    assert len(ledgers) == 1
    assert ledgers[0].reference.startswith('ACT-7-')


# ═══════════════════════════════════════════════════════════════════════
# Part E — reactivate
# ═══════════════════════════════════════════════════════════════════════


def test_reactivate_creates_fresh_sub_with_rea_reference():
    """Reactivation creates a fresh cycle starting at `now` (no
    backfill of missed time) and uses the REA- reference token so
    finance can distinguish a reactivation from a first activation."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='cancelled')
    plan = _fake_plan(id_=1, price=20.0, duration_days=30)
    expired_sub = _fake_sub(
        id_=10, plan_id=1, status='cancelled',
        starts_at=datetime(2026, 3, 12),
        ends_at=datetime(2026, 4, 12),
    )
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=expired_sub, current_plan=plan)
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.reactivate(
                    tenant, plan, days=30, actor_user_id=42,
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    subs = [x for x in added if x.__class__.__name__ == 'TenantSubscription']
    assert subs[0].starts_at == datetime(2026, 5, 12)
    assert subs[0].ends_at == datetime(2026, 5, 12) + timedelta(days=30)
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers[0].reference.startswith('REA-7-')
    assert result.action == 'reactivate'
    assert tenant.status == 'active'


# ═══════════════════════════════════════════════════════════════════════
# Part F — cancel
# ═══════════════════════════════════════════════════════════════════════


def test_cancel_flips_status_without_writing_ledger():
    """Cancellation is policy-locked: status flips on both tenant and
    sub, no refund is auto-issued, `ends_at` is preserved."""
    from app.services import billing_engine
    tenant = _fake_tenant(id_=7, plan_id=1, status='active')
    sub = _fake_sub(
        id_=10, plan_id=1, status='active',
        ends_at=datetime(2026, 5, 27),
    )
    plan = _fake_plan(id_=1, currency='USD')
    added, _add = _capture_session()
    patches = _patch_engine_collaborators(current_sub=sub, current_plan=plan)
    preserved_ends_at = sub.ends_at
    with _ctx():
        for p in patches:
            p.start()
        try:
            with mock.patch.object(
                billing_engine.db.session, 'add', side_effect=_add,
            ), mock.patch.object(
                billing_engine.db.session, 'flush',
            ), mock.patch.object(
                billing_engine.db.session, 'commit',
            ):
                result = billing_engine.cancel(
                    tenant, actor_user_id=42, reason='No longer needed',
                    now=datetime(2026, 5, 12),
                )
        finally:
            for p in patches:
                p.stop()
    ledgers = [x for x in added if x.__class__.__name__ == 'WalletLedger']
    assert ledgers == []
    assert sub.status == 'cancelled'
    assert tenant.status == 'cancelled'
    # End date preserved — subscriber keeps access.
    assert sub.ends_at == preserved_ends_at
    assert result.amount == 0.0
    assert result.action == 'cancel'
    assert result.extra['reason'] == 'No longer needed'


# ═══════════════════════════════════════════════════════════════════════
# Sanity locks — preserved behaviours
# ═══════════════════════════════════════════════════════════════════════


def test_v82_engine_action_vocabulary_is_complete():
    """Spec lock: the six lifecycle actions exposed by the engine
    must all be importable and callable as module-level functions.
    A missing action here means a contract regression."""
    from app.services import billing_engine
    for name in ('activate', 'renew', 'extend', 'change_plan',
                 'reactivate', 'cancel'):
        fn = getattr(billing_engine, name, None)
        assert callable(fn), f'billing_engine.{name} missing'


def test_v82_engine_reference_prefixes_are_stable():
    """Finance depends on the reference prefixes for filtering. Lock
    them so a rename triggers a test failure rather than a silent
    history break."""
    from app.services import billing_engine
    assert billing_engine.REF_ACTIVATE == 'ACT'
    assert billing_engine.REF_RENEW == 'REN'
    assert billing_engine.REF_EXTEND == 'EXT'
    assert billing_engine.REF_PLAN_CHANGE == 'PCH'
    assert billing_engine.REF_REACTIVATE == 'REA'
