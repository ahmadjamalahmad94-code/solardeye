"""v83 — sidebar discoverability + navigation cleanup tests.

A disciplined navigation pass — adds three admin entries the
product surfaces deserve, deliberately leaves Battery Lab as a
secondary diagnostic page, and verifies the canonical sidebar
contract holds.

Test strategy
─────────────
We don't render the Jinja template (that would need a full
`create_app()` boot + request context). Instead we read the
sidebar source as text and assert that:

  * the three new admin labels are present (Arabic and English),
  * each new entry is wired to a real, current Flask endpoint,
  * Battery Lab is intentionally NOT in the subscriber section,
  * the legacy `components/sidebar.html` stub is not imported
    anywhere in the live template tree.

This catches the high-value navigation regressions (renamed
endpoint, dropped entry, accidentally promoting a diagnostic
page) without booting Flask.
"""
from __future__ import annotations

import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


_SIDEBAR_PATH = os.path.join(_REPO_ROOT, 'app', 'templates', '_sidebar.html')
_LEGACY_STUB_PATH = os.path.join(
    _REPO_ROOT, 'app', 'templates', 'components', 'sidebar.html',
)
_TEMPLATE_DIR = os.path.join(_REPO_ROOT, 'app', 'templates')


def _read(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as fh:
        return fh.read()


# ─── Admin additions ──────────────────────────────────────────────────


def test_sidebar_renders_admin_subscriptions_entry():
    """v83: the admin queue at `billing.admin_subscriptions` was
    operational but had no sidebar entry. Now it does, wired to
    both the new and legacy endpoint names so active-state
    highlighting works after old session URLs."""
    src = _read(_SIDEBAR_PATH)
    assert 'الاشتراكات' in src
    assert "'Subscriptions'" in src or '"Subscriptions"' in src
    assert "'billing.admin_subscriptions'" in src
    assert "'main.admin_subscriptions'" in src


def test_sidebar_renders_admin_internal_mail_entry():
    """v83: `support.admin_internal_mail` is now a top-level admin
    nav entry instead of being reachable only by URL. Carries a
    badge tied to `g.mail_notification_count`."""
    src = _read(_SIDEBAR_PATH)
    assert 'البريد الداخلي للإدارة' in src
    assert "'Internal Mail'" in src or '"Internal Mail"' in src
    assert "'support.admin_internal_mail'" in src
    assert 'g.mail_notification_count' in src


def test_sidebar_renders_admin_tickets_entry():
    """v83: `support.admin_tickets` is now a top-level admin nav
    entry with a ticket-count badge."""
    src = _read(_SIDEBAR_PATH)
    assert 'التذاكر' in src
    assert "'Tickets'" in src or '"Tickets"' in src
    assert "'support.admin_tickets'" in src
    assert 'g.ticket_notification_count' in src


def test_sidebar_admin_section_groups_billing_surfaces_together():
    """Visual contract: the three billing surfaces (Subscribers /
    Plan-change requests / Subscriptions) sit in one logical block,
    not scattered across the admin menu. Locks the ordering so a
    future refactor doesn't accidentally split them apart."""
    src = _read(_SIDEBAR_PATH)
    idx_subscribers = src.find("'subscribers'")
    idx_plan_change = src.find("'plan_change_requests'")
    idx_subscriptions = src.find("'subscriptions'")
    # All three exist.
    assert idx_subscribers >= 0
    assert idx_plan_change >= 0
    assert idx_subscriptions >= 0
    # Ordering: Subscribers → Plan-change → Subscriptions.
    assert idx_subscribers < idx_plan_change < idx_subscriptions


def test_sidebar_admin_section_groups_support_surfaces_together():
    """Internal Mail + Tickets sit adjacent to Support Center so
    operators see the three support-flow surfaces as one bucket."""
    src = _read(_SIDEBAR_PATH)
    idx_support = src.find("'support.admin_support_command_center'")
    idx_internal_mail = src.find("'support.admin_internal_mail'")
    idx_tickets = src.find("'support.admin_tickets'")
    assert idx_support >= 0
    assert idx_internal_mail >= 0
    assert idx_tickets >= 0
    # Support Center → Internal Mail → Tickets.
    assert idx_support < idx_internal_mail < idx_tickets


# ─── Subscriber section — Battery Lab is now promoted (v93p) ──────


def test_sidebar_promotes_battery_lab_to_subscriber_section():
    """v93p — reversal of the v83 product judgment, on owner
    request. Battery Lab is now a first-class subscriber portal
    page so subscribers don't need to type the URL to reach the
    SOC trace, voltage curve, cycles, SOH, AC-IN diagnostics and
    the v93o station-tier generator inference.

    It still respects `portal_page_visible('battery_lab')` so a
    plan admin can hide it for tiers that shouldn't see it. The
    page is registered in `PORTAL_PAGES` with `page_key =
    "battery_lab"` and `endpoint = "main.battery_lab"`."""
    src = _read(_SIDEBAR_PATH)
    # nav_item is wired to the canonical endpoint + alias.
    assert 'devices_routes.battery_lab' in src
    assert "'battery_lab'" in src
    assert 'مختبر البطارية' in src
    assert 'Battery Lab' in src
    # Active-state matches both endpoint variants.
    assert "'main.battery_lab'" in src

    # And PORTAL_PAGES carries the page so portal_page_visible
    # gating can hide/show it per plan.
    from app.services.rbac import PORTAL_PAGES, PORTAL_ENDPOINT_TO_KEY
    keys = {p['page_key'] for p in PORTAL_PAGES}
    assert 'battery_lab' in keys
    assert PORTAL_ENDPOINT_TO_KEY.get('main.battery_lab') == 'battery_lab'
    assert PORTAL_ENDPOINT_TO_KEY.get('devices_routes.battery_lab') == 'battery_lab'


# ─── Items intentionally NOT in the top-level sidebar ───────────────


def test_sidebar_does_not_expose_api_probe_at_top_level():
    """API Probe is a developer/diagnostic tool — kept reachable
    via its existing URL, but never a top-level nav entry."""
    src = _read(_SIDEBAR_PATH)
    assert "'api_probe'" not in src
    assert 'api_probe.api_probe_page' not in src


def test_sidebar_does_not_expose_diagnostics_at_top_level():
    """Diagnostics is an admin-side technical surface, reachable
    from the system-logs / services-health paths. Not a top-level
    nav entry."""
    src = _read(_SIDEBAR_PATH)
    assert "'energy.diagnostics'" not in src
    assert "'main.diagnostics'" not in src
    # The subscriber Support entry IS expected to bundle the portal
    # message + ticket endpoints inside ITS `endpoint_names` for
    # active-state matching — that's correct and not a violation of
    # the "not a top-level entry" rule. Verify the subscriber portal
    # surface is the unified Support Center, not three separate items.
    assert src.count("portal_messages") <= 2  # at most: inside Support
    assert src.count("portal_tickets") <= 2


def test_sidebar_does_not_expose_alerts_as_top_level_nav():
    """v83: the /alerts surface is superseded by Notification Center
    + Notification Settings. We confirm it has no top-level
    sidebar entry. (Deep-links into /alerts from inside the
    notification center are legitimate cross-nav, not main-nav.)"""
    src = _read(_SIDEBAR_PATH)
    # nav_item wired to alerts: should never appear.
    assert "url_for('main.alerts'" not in src
    assert "url_for('notifications_routes.alerts'" not in src


# ─── Legacy stub detection ──────────────────────────────────────────


def test_legacy_components_sidebar_is_not_referenced_anywhere():
    """`app/templates/components/sidebar.html` is a 17-line static
    stub left over from an earlier design pass. v83 confirms no
    other template imports it, so it's effectively dead. We leave
    the file in place per the spec (don't delete unless certain)
    and lock the contract that no live template should start
    using it again."""
    assert os.path.exists(_LEGACY_STUB_PATH)
    # Walk every template and assert no `include` / `extends` /
    # `import` references this path.
    for root, _dirs, files in os.walk(_TEMPLATE_DIR):
        for fname in files:
            if not fname.endswith('.html'):
                continue
            full = os.path.join(root, fname)
            if os.path.samefile(full, _LEGACY_STUB_PATH):
                continue
            body = _read(full)
            assert 'components/sidebar.html' not in body, (
                f'{full} unexpectedly references the legacy stub'
            )


# ─── Active-state endpoint integrity ────────────────────────────────


def test_new_admin_entries_use_endpoints_that_actually_exist():
    """Compile-time check: every endpoint name we wired into the
    new sidebar entries resolves to a real route handler. Catches
    a stale endpoint name without booting Flask — we just inspect
    the blueprint source files for the `def` and the route
    decorator pattern."""
    # Map: endpoint name → (module path, handler name).
    expected = {
        'billing.admin_subscriptions': (
            'app/blueprints/billing.py', 'def admin_subscriptions(',
        ),
        'support.admin_internal_mail': (
            'app/blueprints/support.py', 'def admin_internal_mail(',
        ),
        'support.admin_tickets': (
            'app/blueprints/support.py', 'def admin_tickets(',
        ),
    }
    for endpoint, (rel_path, def_signature) in expected.items():
        full = os.path.join(_REPO_ROOT, rel_path.replace('/', os.sep))
        assert os.path.exists(full), f'missing blueprint file: {full}'
        body = _read(full)
        assert def_signature in body, (
            f'{endpoint} expected handler `{def_signature}` in {rel_path}'
        )


# ─── Sidebar count integrity ────────────────────────────────────────


def _admin_branch_slice(src: str) -> str:
    """Return the admin block of the nav section.

    The sidebar template uses `{% if g.is_admin %}` twice: once as
    a class-attribute switch on the `<aside>` element, and once
    inside the `<nav>` to split admin vs subscriber entries. The
    nav split is the one we care about. We anchor on the marker
    that uniquely sits right before the nav switch."""
    nav_anchor = src.find('<nav class="sd-nav-v11"')
    assert nav_anchor >= 0
    admin_start = src.find('{% if g.is_admin %}', nav_anchor)
    admin_end = src.find('{% else %}', admin_start)
    assert admin_start > nav_anchor
    assert admin_end > admin_start
    return src[admin_start:admin_end]


def _subscriber_branch_slice(src: str) -> str:
    """The subscriber branch sits between `{% else %}` and the
    closing `</nav>`. We anchor on `</nav>` because the branch
    contains nested `{% if portal_page_visible(...) %}{% endif %}`
    pairs that would confuse a naive first-endif scan."""
    nav_anchor = src.find('<nav class="sd-nav-v11"')
    admin_start = src.find('{% if g.is_admin %}', nav_anchor)
    else_start = src.find('{% else %}', admin_start)
    nav_close = src.find('</nav>', else_start)
    return src[else_start:nav_close]


def test_admin_sidebar_entry_count_is_disciplined():
    """Spec rule: don't bloat the admin sidebar. Lock a sensible
    upper bound on the number of `nav_item` invocations inside the
    admin branch so a future wave can't accidentally flood the menu
    without that being a deliberate, test-visible change."""
    src = _read(_SIDEBAR_PATH)
    admin_block = _admin_branch_slice(src)
    count = len(re.findall(r'\bnav_item\s*\(', admin_block))
    assert 10 <= count <= 24, (
        f'admin sidebar has {count} nav_item entries; expected 10..24'
    )


def test_subscriber_sidebar_keeps_minimal_top_level_count():
    """Subscriber-side: 10 expected portal pages from PORTAL_PAGES
    plus the (always-shown) Notification Center. Lock the upper
    bound so a hypothetical leak of admin entries into the
    subscriber branch fails loudly."""
    src = _read(_SIDEBAR_PATH)
    sub_block = _subscriber_branch_slice(src)
    count = len(re.findall(r'\bnav_item\s*\(', sub_block))
    assert 5 <= count <= 14, (
        f'subscriber sidebar has {count} nav_item entries; expected 5..14'
    )
