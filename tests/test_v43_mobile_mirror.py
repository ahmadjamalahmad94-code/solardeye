"""v43 — mobile Notification Center mirror tests.

Covers:
  M1  event_type_for_dispatch_key classifies every prefix the
      ``dispatch_notification`` call sites use today.
  M2  ``::devN`` device-aware suffix does not break classification.
  M3  event_type_for_scheduled maps every scheduled prefix.
  M4  mirror_energy_notification_to_center skips honestly when the
      caller has no user_id (admin/global scope).
  M5  mirror_energy_notification_to_center skips empty payloads.
  M6  mirror_energy_notification_to_center DB write failure is
      swallowed (Telegram/SMS path must never be affected).
  M7  Successful mirror writes a NotificationEvent row with the
      classification fields the mobile API needs (event_type,
      source_type='energy', target_user_id, is_read=False).

These tests run WITHOUT a live database — the mirror module's
collaborators (``db.session``, ``AppUser.query``) are monkeypatched.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

# Make ``app`` importable when pytest is run from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── M1 + M2: dispatch_key classifier ─────────────────────────────────

def test_event_type_for_dispatch_key_classifies_every_known_prefix():
    from app.services.notifications import event_type_for_dispatch_key as cls

    cases = {
        # exact prefixes used by dispatch_notification call sites
        # in app/blueprints/notifications.py
        'charge-50-2026-05-08':           'battery_status',
        'discharge-15-2026-05-08':        'night_discharge',
        'day-deficit-12':                 'solar_status',
        'night-load-300-22':              'load_alert',
        'weather-sunny-12':               'weather_alert',
        'weather-cloudy-12':              'weather_alert',
        'weather-rain-12':                'weather_alert',
        'weather-daily-summary-2026':     'weather_alert',
        # The live ``periodic-status-`` dispatch is mapped to the
        # whitelist's catch-all so every emitted value is on the
        # mobile classifier's recommended list.
        'periodic-status-1715000000':     'energy_status_change',
        'pre-sunset-1715000000':          'pre_sunset',
        'morning-report-2026-05-08':      'daily_report',
        'inv-temp-high-12':               'inverter_status',
        'bms-temp-high-12':               'battery_warning',
        'pv-high-12':                     'solar_status',
    }
    for key, expected in cases.items():
        assert cls(key) == expected, f'classifier mismatch for key={key}'


def test_event_type_for_dispatch_key_strips_device_suffix():
    """The dedup helper appends ``::devN`` — classifier must not break."""
    from app.services.notifications import event_type_for_dispatch_key as cls
    assert cls('charge-50-2026-05-08::dev42') == 'battery_status'
    assert cls('night-load-300-22::dev7') == 'load_alert'
    assert cls('weather-rain-12::dev1') == 'weather_alert'


def test_event_type_for_dispatch_key_unknown_falls_back():
    from app.services.notifications import (
        event_type_for_dispatch_key,
        DEFAULT_EVENT_TYPE,
    )
    assert event_type_for_dispatch_key('mystery-event') == DEFAULT_EVENT_TYPE
    assert event_type_for_dispatch_key('') == DEFAULT_EVENT_TYPE
    assert event_type_for_dispatch_key(None) == DEFAULT_EVENT_TYPE


# ─── M3: scheduled prefix classifier ──────────────────────────────────

def test_event_type_for_scheduled_maps_every_scheduler_prefix():
    """Every prefix passed by ``_send_scheduled_notification`` call
    sites must resolve to a stable mobile-side event_type."""
    from app.services.notifications import event_type_for_scheduled as cls
    cases = {
        'periodic_day':   'periodic_day',
        'periodic_night': 'periodic_night',
        'pre_sunset':     'pre_sunset',
        'load_alert':     'load_alert',
        'battery_test':   'battery_warning',
        'daily_report':   'daily_report',
    }
    for prefix, expected in cases.items():
        assert cls(prefix) == expected, f'scheduled mismatch for prefix={prefix}'


def test_event_type_for_scheduled_unknown_falls_back():
    from app.services.notifications import (
        event_type_for_scheduled,
        DEFAULT_EVENT_TYPE,
    )
    assert event_type_for_scheduled('made_up') == DEFAULT_EVENT_TYPE
    assert event_type_for_scheduled('') == DEFAULT_EVENT_TYPE


# ─── M4 + M5: skip rules ──────────────────────────────────────────────

def test_mirror_skips_when_user_id_missing():
    """Admin / global scope path: no per-user owner → skip honestly."""
    from app.services.notifications.mobile_mirror import (
        mirror_energy_notification_to_center,
    )
    with mock.patch(
        'app.services.notifications.mobile_mirror.db'
    ) as mock_db:
        result = mirror_energy_notification_to_center(
            event_type='battery_status',
            title='شحن البطارية 80%',
            message='وصلت البطارية إلى 80%.',
            user_id=None,  # admin/global scope
            device_id=42,
        )
    assert result is False
    mock_db.session.add.assert_not_called()
    mock_db.session.commit.assert_not_called()


def test_mirror_skips_when_title_and_message_both_empty():
    from app.services.notifications.mobile_mirror import (
        mirror_energy_notification_to_center,
    )
    with mock.patch(
        'app.services.notifications.mobile_mirror.db'
    ) as mock_db:
        result = mirror_energy_notification_to_center(
            event_type='battery_status',
            title='',
            message='   ',
            user_id=901,
            device_id=42,
        )
    assert result is False
    mock_db.session.add.assert_not_called()


# ─── M6: DB failure isolation ─────────────────────────────────────────

def test_mirror_swallows_db_failure_and_does_not_raise():
    """Telegram/SMS sending must NEVER be affected by a DB hiccup. The
    helper logs the failure, rolls back, and returns False — without
    raising."""
    from app.services.notifications.mobile_mirror import (
        mirror_energy_notification_to_center,
    )
    with mock.patch(
        'app.services.notifications.mobile_mirror.db'
    ) as mock_db, mock.patch(
        'app.services.notifications.mobile_mirror.AppUser'
    ) as mock_user_model, mock.patch(
        'app.services.notifications.mobile_mirror.NotificationEvent'
    ):
        # User lookup succeeds (returns a fake user with tenant_id None)
        mock_user_model.query.filter_by.return_value.first.return_value = (
            mock.Mock(tenant_id=None)
        )
        # Commit blows up — simulates DB outage / lock / migration drift.
        mock_db.session.commit.side_effect = RuntimeError('DB exploded')

        result = mirror_energy_notification_to_center(
            event_type='battery_status',
            title='شحن البطارية',
            message='وصلت البطارية إلى 80%.',
            user_id=901,
            device_id=42,
            level='info',
        )

    assert result is False, 'mirror must report failure, not raise it'
    mock_db.session.rollback.assert_called_once()


# ─── M7: success writes the row mobile API filters on ────────────────

def test_mirror_writes_notification_event_with_classification_fields():
    """A successful mirror writes a NotificationEvent that the mobile
    API will surface in /api/mobile/notifications with the energy
    classification fields the Flutter classifier reads."""
    from app.services.notifications.mobile_mirror import (
        ENERGY_SOURCE_TYPE,
        mirror_energy_notification_to_center,
    )

    captured = {}

    def fake_constructor(**kwargs):
        captured.update(kwargs)
        return mock.Mock(**kwargs)

    with mock.patch(
        'app.services.notifications.mobile_mirror.db'
    ) as mock_db, mock.patch(
        'app.services.notifications.mobile_mirror.AppUser'
    ) as mock_user_model, mock.patch(
        'app.services.notifications.mobile_mirror.NotificationEvent',
        side_effect=fake_constructor,
    ):
        mock_user_model.query.filter_by.return_value.first.return_value = (
            mock.Mock(tenant_id=7)
        )
        result = mirror_energy_notification_to_center(
            event_type='load_alert',
            title='حمل ليلي مرتفع',
            message='الحمل الليلي 350 واط.',
            user_id=901,
            device_id=42,
            level='warning',
        )

    assert result is True
    mock_db.session.add.assert_called_once()
    mock_db.session.commit.assert_called_once()

    # The fields the mobile classifier needs:
    assert captured['event_type'] == 'load_alert'
    assert captured['source_type'] == ENERGY_SOURCE_TYPE
    assert captured['target_user_id'] == 901
    assert captured['source_id'] == 42
    assert captured['tenant_id'] == 7
    assert captured['title'] == 'حمل ليلي مرتفع'
    assert captured['message'] == 'الحمل الليلي 350 واط.'
    assert captured['is_read'] is False
    # warning level is reflected in status (status carries severity since
    # NotificationEvent does not have a dedicated severity column).
    assert captured['status'] == 'warning'


def test_mirror_uses_critical_status_for_danger_level():
    """``level='danger'`` from the dispatch site should land as
    ``status='critical'`` so the mobile classifier can promote
    severity in the energy tab."""
    from app.services.notifications.mobile_mirror import (
        mirror_energy_notification_to_center,
    )
    captured = {}

    def fake_constructor(**kwargs):
        captured.update(kwargs)
        return mock.Mock(**kwargs)

    with mock.patch(
        'app.services.notifications.mobile_mirror.db'
    ), mock.patch(
        'app.services.notifications.mobile_mirror.AppUser'
    ) as mock_user_model, mock.patch(
        'app.services.notifications.mobile_mirror.NotificationEvent',
        side_effect=fake_constructor,
    ):
        mock_user_model.query.filter_by.return_value.first.return_value = (
            mock.Mock(tenant_id=None)
        )
        mirror_energy_notification_to_center(
            event_type='night_discharge',
            title='تفريغ البطارية 10%',
            message='انخفضت البطارية إلى 10%.',
            user_id=901,
            level='danger',
        )

    assert captured['status'] == 'critical'
