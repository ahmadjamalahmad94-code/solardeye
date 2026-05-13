"""v88 — plan-change root-cause hotfix tests.

Covers:
  * Web confirm route no longer 500s on bad input or service errors.
  * Mobile preview/confirm endpoints return structured errors when
    their service layer raises.
  * Dispatcher allowlist includes the v87 mobile endpoints so a
    wrong-method request returns a structured 405 (not a vague 404).
  * Old mobile endpoint still functions and now advertises its
    successor via `meta.superseded_by`.
  * `_audit` / `_notify_subscriber` are defensive against odd
    inputs that historically could 500 the apply path.
  * Subscriber preview template carries product-language explainers
    and NO raw developer-style formula blocks.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ════════════════════════════════════════════════════════════════════════
# Part A — web confirm route hardening (source-inspection lock)
# ════════════════════════════════════════════════════════════════════════


def test_web_confirm_route_parses_plan_id_defensively():
    """The v88 hardening introduces a `_fail('plan_id_required')` and
    `_fail('plan_id_invalid')` path BEFORE the `int(...)` cast, so a
    non-numeric plan_id no longer 500s. Locked via source inspection
    since importing the blueprint would pull `reportlab` (not in the
    dev env)."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'billing.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert "_fail('plan_id_required')" in text
    assert "_fail('plan_id_invalid')" in text
    assert "_fail('desired_target_days_invalid')" in text
    # The route still wraps the service call so unexpected exceptions
    # become a structured 'internal_error' response — never a bare 500.
    assert "_fail('internal_error', status=500)" in text
    # The try/except keeps `logger.exception` so ops can still see
    # the original traceback.
    assert "account_subscription_change_confirm: unexpected error" in text


def test_web_confirm_route_clamps_desired_days_to_safe_range():
    """A user could historically submit `desired_target_days=99999...`
    and cause a `timedelta(days=N)` OverflowError deeper in
    apply_request. The v88 route refuses values outside [0, 10_000]
    upfront."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'billing.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'desired_days > 10_000' in text or 'desired_days > 10000' in text


# ════════════════════════════════════════════════════════════════════════
# Part B — service-layer defensive helpers
# ════════════════════════════════════════════════════════════════════════


def test_audit_helper_survives_non_serializable_details():
    """`_audit` used to call `json.dumps(details)` without a default,
    so a Mock / datetime object inside `details` would 500 the apply
    path. v88 adds `default=str` and an outer try/except."""
    from flask import Flask
    from app.extensions import db
    from app.services import plan_change_workbench as wb

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    case = mock.Mock()
    case.case_type = 'plan_change_request'
    case.source_id = 42
    case.user_id = 42

    added = []
    with app.app_context():
        with mock.patch.object(wb.db.session, 'add', side_effect=added.append):
            # Mock object inside details would be non-serializable by
            # default; the `default=str` fallback must rescue it.
            wb._audit(
                case, 'plan_change.test',
                'unit test summary',
                actor_user_id=42,
                details={'odd_field': mock.Mock(), 'another': object()},
            )
    audit_rows = [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ]
    assert len(audit_rows) == 1
    # The row's details_json must be valid JSON (a string),
    # demonstrating the fallback fired without raising.
    import json
    parsed = json.loads(audit_rows[0].details_json)
    assert isinstance(parsed, dict)
    assert 'odd_field' in parsed


def test_audit_helper_falls_back_when_case_fields_missing():
    """A corrupted/mocked case missing `case_type` or `source_id`
    used to fail the NOT NULL constraint at flush. v88 substitutes
    safe defaults so the audit row still writes."""
    from flask import Flask
    from app.extensions import db
    from app.services import plan_change_workbench as wb

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    case = mock.Mock()
    case.case_type = None
    case.source_id = None
    case.user_id = 99

    added = []
    with app.app_context():
        with mock.patch.object(wb.db.session, 'add', side_effect=added.append):
            wb._audit(
                case, 'plan_change.test',
                'summary', actor_user_id=1, details={},
            )
    audit_rows = [
        x for x in added if x.__class__.__name__ == 'SupportAuditLog'
    ]
    assert audit_rows
    row = audit_rows[0]
    assert row.case_type == 'plan_change_request'  # default fallback
    assert row.source_id == 99  # falls back to user_id


def test_notify_subscriber_returns_none_when_user_id_is_not_int():
    """`_notify_subscriber` did `int(user_id)` which used to raise
    `TypeError` for a non-int. v88 wraps the coercion."""
    from flask import Flask
    from app.extensions import db
    from app.services import plan_change_workbench as wb

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    case = mock.Mock()
    case.user_id = 'not-an-int'
    case.tenant_id = 7
    case.id = 55
    added = []
    with app.app_context():
        with mock.patch.object(wb.db.session, 'add', side_effect=added.append):
            ret = wb._notify_subscriber(
                case, event_type='plan_change_applied',
                title='t', message='m',
            )
    assert ret is None
    assert [x for x in added if x.__class__.__name__ == 'NotificationEvent'] == []


# ════════════════════════════════════════════════════════════════════════
# Part C — mobile contract: dispatcher allowlist + new endpoints
# ════════════════════════════════════════════════════════════════════════


def test_mobile_dispatcher_allowlist_includes_v87_endpoints():
    """The mobile catch-all (`mobile_core_missing_or_method_not_allowed`)
    uses `_MOBILE_CORE_ALLOWED_METHODS` to decide between a structured
    405 and a 404. The new v87 endpoints must be in that allowlist so
    a wrong-method request (e.g. `POST /account/plan-change/preview`)
    returns a 405 the mobile shell can render, not a vague 404 that
    collapses into 'connection failed'."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert "'/account/plan-change/preview':" in text
    assert "'/account/plan-change/confirm':" in text


def test_mobile_preview_route_wraps_service_call_with_logger_exception():
    """The mobile preview endpoint used to bubble service errors up
    as a Flask HTML 500 — which the mobile shell renders as
    'فشل الاتصال بالخادم'. v88 wraps the service call so unexpected
    exceptions become a structured `{code: 'internal_error', status: 500}`
    JSON payload + a logged traceback."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'mobile_account_plan_change_preview: unexpected error' in text
    assert "code='internal_error', status=500" in text


def test_mobile_confirm_route_wraps_service_call_with_logger_exception():
    """Same hardening for the confirm endpoint."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert 'mobile_account_plan_change_confirm: unexpected error' in text
    # Clamp on desired_target_days range to prevent overflow.
    assert 'desired_days > 10_000' in text or 'desired_days > 10000' in text


def test_legacy_mobile_endpoint_advertises_replacement_in_meta():
    """The old `/account/subscription/request-change` still works
    (backwards compatibility for older app builds) but its response
    now carries `meta.superseded_by` so newer clients know about the
    v87 subscriber-driven endpoints."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'mobile_api.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert "'superseded_by'" in text
    assert "/api/mobile/account/plan-change/preview" in text
    assert "/api/mobile/account/plan-change/confirm" in text


# ════════════════════════════════════════════════════════════════════════
# Part D — subscriber preview template explainer
# ════════════════════════════════════════════════════════════════════════


def test_subscriber_preview_template_drops_raw_formula_blocks():
    """The v87 template carried two `<p style="font-family:ui-monospace…">`
    blocks with raw `(remaining_days ÷ current_cycle_days) × …`
    formulas. v88 replaces them with product-language explainers."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'templates',
        'subscriber_plan_change_preview.html',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # The developer-style formulas (with the specific identifiers
    # `current_cycle_days`, `target_per_day`, etc.) must be gone.
    assert '(remaining_days ÷ current_cycle_days)' not in text
    assert 'amount_due = target_remaining_value' not in text
    assert 'current_remaining_value ÷ target_per_day' not in text
    # And the page must NOT carry a monospace developer-formula
    # paragraph anywhere on the explainer rail.
    assert 'font-family:ui-monospace,monospace' not in text


def test_subscriber_preview_template_explains_per_day_logic_in_plain_words():
    """Replacement copy must explicitly call out the per-day pricing
    so subscribers understand WHY a cheaper yearly plan gives more
    days AND why a cheaper monthly plan can still give fewer days."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'templates',
        'subscriber_plan_change_preview.html',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # Downgrade narrative — "more days because per-day is lower".
    assert 'Why you get more days' in text or 'لماذا تحصل على أيام أكثر' in text
    # Upgrade narrative — "fewer days because per-day is higher".
    assert (
        'Why fewer days on a more expensive plan' in text
        or 'لماذا تقلّ الأيام على الخطة الأعلى' in text
    )
    # Explicit copy about cycle length affecting per-day cost (so a
    # 1-month plan can be more expensive per day than a 12-month plan).
    assert (
        'shorter' in text.lower()
        or 'دورتها أقصر' in text
        or 'cycle is shorter' in text
    )


# ════════════════════════════════════════════════════════════════════════
# Part E — precise error contract
# ════════════════════════════════════════════════════════════════════════


def test_web_confirm_wraps_early_auth_and_tenant_calls():
    """v88b — the v88 try/except only protected `_confirm()`. If
    `_active_user()` or `ensure_user_tenant_and_subscription()`
    raised (corrupt session, transient DB error), the route still
    surfaced a bare Flask 500 HTML page. v88b extends the safety
    net to wrap those early calls too."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'billing.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # The route now logs and returns `_fail('internal_error', status=500)`
    # if _active_user itself raises.
    assert '_active_user failed' in text
    # And similarly for ensure_user_tenant_and_subscription.
    assert 'ensure_user_tenant_and_subscription failed' in text


def test_app_level_error_handlers_registered():
    """v88b — there must be an app-level 500/404/405 handler so an
    uncaught exception in ANY blueprint (billing, payments,
    mobile_api, etc.) returns a controlled response, not Flask's
    default 'Internal Server Error' HTML page."""
    path = os.path.join(
        _REPO_ROOT, 'app', '__init__.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    assert '@app.errorhandler(500)' in text
    assert '@app.errorhandler(404)' in text
    assert '@app.errorhandler(405)' in text
    # The handler must branch on Accept / X-Requested-With so API
    # callers get JSON while browser users get the error template.
    assert '_wants_json_response' in text
    # And it must log the original exception so ops can diagnose.
    assert 'Unhandled 500 on' in text


def test_web_confirm_json_failure_payload_carries_machine_code():
    """In JSON mode, every controlled failure returns
    `{'ok': False, 'code': '<stable-string>', 'message': '<ar>'}`."""
    path = os.path.join(
        _REPO_ROOT, 'app', 'blueprints', 'billing.py',
    )
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    # The helper builds a JSON body keyed by `code` for machine
    # consumption + `message` for human display.
    assert "'ok': False" in text
    assert "'code': code" in text
    assert "'message': msg" in text
