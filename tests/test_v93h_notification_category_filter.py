"""v93h — granular notification filter categories.

The notification-center toolbar used to expose a single "System"
tab that lumped subscription/payment/quota events with battery,
load, weather and sundown alerts. Subscribers complained that
finding "did my payment go through?" required scrolling past 50
device alerts.

We now compute `notification_category` on every aggregator row.
It splits the legacy "system" notification_class into three:
    * 'financial'  → subscription, payment, plan-change, quotas
                     (this is what the new "System" tab shows)
    * 'weather'    → weather alerts (own tab)
    * 'energy'     → loads, battery, solar, sundown, sunrise,
                     daily report, periodic, inverter (own tab)

Support events (kind=message/ticket) keep their own category.

This test pins the classifier so a future refactor cannot
silently lump weather alerts back into the energy bucket or
re-merge financial into the energy bucket.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _cat(event_type, source_type='', kind='system'):
    from app.blueprints.notifications_routes import (
        _agg_notification_category,
    )
    return _agg_notification_category(event_type, source_type, kind)


def test_financial_events_classify_as_financial():
    # These are the user-facing "system" events the subscriber
    # actually wants to track: subscription, payment, plan
    # changes, and quota nearing limits.
    for et in (
        'plan_change_request_received',
        'plan_change_invoice_issued',
        'plan_change_invoice_settled',
        'plan_change_applied',
        'subscription_renewed',
        'subscription_expiring_soon',
        'payment_received',
        'invoice_issued',
        'quota_warning',
        'quota_exceeded',
        'wallet_topup',
        'billing_reminder',
    ):
        assert _cat(et) == 'financial', f'{et!r} should be financial'


def test_support_events_classify_as_support():
    # Kind takes precedence: a row with kind=message or
    # kind=ticket is always support regardless of event_type.
    assert _cat('message_received', kind='message') == 'support'
    assert _cat('ticket_reply',     kind='ticket')  == 'support'
    # Bare event_type also routes via prefix.
    assert _cat('support_message')  == 'support'
    assert _cat('ticket_update')    == 'support'
    assert _cat('conversation_new') == 'support'


def test_weather_events_classify_as_weather():
    # Weather alerts get their own tab so they are not buried
    # underneath energy chatter.
    assert _cat('weather_alert')    == 'weather'
    assert _cat('weather_warning')  == 'weather'
    assert _cat('weather_advisory') == 'weather'


def test_energy_events_classify_as_energy():
    # Everything else in the legacy "system" bucket — loads,
    # battery, solar production, sundown, sunrise, daily report
    # — falls through to 'energy'.
    for et in (
        'battery_status',
        'battery_warning',
        'night_discharge',
        'load_alert',
        'solar_status',
        'inverter_status',
        'energy_status_change',
        'pre_sunset',
        'sunrise_alert',
        'daily_report',
        'periodic_status',
    ):
        assert _cat(et) == 'energy', f'{et!r} should be energy'


def test_unknown_event_defaults_to_energy():
    # An unknown system-class event should land in the catch-all
    # energy bucket rather than getting hidden from the user.
    assert _cat('some_brand_new_alert') == 'energy'
    assert _cat('', source_type='', kind='system') == 'energy'


def test_category_is_orthogonal_to_class_for_support_and_financial():
    # The category mirrors the class for non-system events. This
    # is what makes the new tabs back-compatible with the existing
    # color theme (which is keyed off notification_class).
    from app.blueprints.notifications_routes import (
        _agg_notification_class,
    )
    et = 'plan_change_applied'
    assert _agg_notification_class(et, '', 'system') == 'financial'
    assert _cat(et) == 'financial'

    et = 'support_message'
    assert _agg_notification_class(et, '', 'system') == 'support'
    assert _cat(et) == 'support'
