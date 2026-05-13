"""v93j — admin notification center surfaces admin-perspective only.

The bug we're fixing: when an admin logged in and opened their
notification center, they saw rows like "تم تطبيق طلب تغيير
الخطة — تم تحويل اشتراكك إلى الخطة البلاتينية" — which is
2nd-person Arabic wording aimed at the subscriber, not the
admin. The admin should instead see "قام المشترك X بتطبيق تغيير
خطته إلى Y" (3rd person).

Root cause: the aggregator's admin whitelist included the source
type `plan_change_request`, which is shared by BOTH subscriber-
targeted and admin-targeted plan-change `NotificationEvent`s. The
subscriber's notification therefore matched the admin filter and
leaked into admin view.

v93j fix:
    1. Drop subscriber-perspective event types from
       `ADMIN_RELEVANT_EVENT_TYPES`.
    2. Drop `plan_change_request` from
       `ADMIN_RELEVANT_SOURCE_TYPES`.
    3. Add admin-perspective event types
       (`plan_change_applied_admin`,
       `plan_change_payment_settled_admin`,
       `plan_change_request_admin`) for defence in depth — the
       fanout helpers already target each admin via
       `target_user_id`, but the whitelist keeps admins covered
       if a future fanout misses someone.
    4. Flag each aggregator row with `is_admin_perspective` so the
       template can render an "إدارة" chip + violet accent for
       admin-authored notifications.

This test pins the whitelist contract + the per-row classifier so
a future refactor cannot silently re-introduce the bug.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def test_subscriber_event_types_excluded_from_admin_whitelist():
    """The four subscriber-perspective plan-change event types MUST
    NOT be in the admin event-type whitelist. Their wording
    ("تم تحويل اشتراكك", "تبقى لك ... يوماً") addresses the
    subscriber and looks wrong in admin view.
    """
    from app.services.support_ops import ADMIN_RELEVANT_EVENT_TYPES
    forbidden = {
        'plan_change_applied',          # "تم تحويل اشتراكك"
        'plan_change_rejected',         # subscriber rejection notice
        'plan_change_discussion',       # subscriber-facing discussion
        'plan_change_invoice_issued',   # "تم طلب الدفع منك"
    }
    assert ADMIN_RELEVANT_EVENT_TYPES.isdisjoint(forbidden), (
        f'Subscriber-perspective event types leaked back into admin '
        f'whitelist: {ADMIN_RELEVANT_EVENT_TYPES & forbidden}'
    )


def test_admin_event_types_present_in_whitelist():
    """The admin-perspective fanout event types must be on the
    whitelist so admins see them reliably (belt-and-suspenders
    next to per-admin target_user_id fanout)."""
    from app.services.support_ops import ADMIN_RELEVANT_EVENT_TYPES
    required = {
        'support',
        'plan_change_request',                # admin initial fanout
        'plan_change_applied_admin',          # "قام المشترك X بـ..."
        'plan_change_payment_settled_admin',  # "تم استلام دفعة..."
    }
    missing = required - ADMIN_RELEVANT_EVENT_TYPES
    assert not missing, f'admin whitelist missing: {missing}'


def test_plan_change_request_source_type_NOT_whitelisted():
    """The shared `plan_change_request` source_type must be off the
    admin source-type whitelist. Both subscriber-targeted and
    admin-targeted notifications carry it; whitelisting it leaked
    subscriber wording into admin view (the v93j bug)."""
    from app.services.support_ops import ADMIN_RELEVANT_SOURCE_TYPES
    assert 'plan_change_request' not in ADMIN_RELEVANT_SOURCE_TYPES, (
        'plan_change_request source_type was re-added to the admin '
        'whitelist — this is the exact regression v93j fixed.'
    )


def test_aggregator_marks_admin_perspective_rows():
    """`_aggregated_notification_groups` should set
    `is_admin_perspective=True` for rows whose event_type ends with
    `_admin`. That flag drives the violet accent + "إدارة" chip on
    the notification-center row.

    We can't easily exercise the SQLAlchemy aggregator here without
    a DB, so we instead verify the classification rule by reading
    the source — the line that derives `is_admin_perspective` from
    `event_type.lower().endswith('_admin')` must exist exactly so
    a refactor can't silently drop it.
    """
    import inspect
    from app.blueprints import notifications_routes as nr
    src = inspect.getsource(nr._aggregated_notification_groups)
    # Whatever spacing/quoting we use, the substring is stable.
    assert "endswith('_admin')" in src or 'endswith("_admin")' in src, (
        'aggregator no longer derives is_admin_perspective from '
        'event_type suffix — admin chip + violet accent will break.'
    )
    assert "'is_admin_perspective'" in src, (
        'aggregator group dict no longer carries is_admin_perspective.'
    )
