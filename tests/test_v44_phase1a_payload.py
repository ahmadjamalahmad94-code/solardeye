"""v44 phase 1a — structured payload for scheduled energy events.

Covers, without a live database:
  P1  ``mirror_energy_notification_to_center`` writes JSON to
      ``NotificationEvent.result`` when a payload is provided.
  P2  Omitted payload leaves ``result=None`` (v43 behaviour intact).
  P3  Oversized payloads (> :data:`MAX_PAYLOAD_BYTES`) are dropped
      silently; the row is still committed.
  P4  Non-JSON-serialisable payloads are dropped silently; the row
      is still committed.
  P5  ``daily-report-*`` event keys classify as ``daily_report``
      (alongside the existing ``morning-report-*`` mapping).
  P6  Both mobile payload builders expose a parsed ``payload`` dict
      for rows that have ``result`` set, and ``None`` otherwise.
  P7  ``_build_scheduled_event_payload`` only returns a payload for the
      four whitelisted scheduled families (periodic_day,
      periodic_night, pre_sunset, daily_report) and ``None`` for any
      other prefix.

All DB collaborators (``db.session``, ``AppUser.query``) are
monkeypatched — the tests do not require a running database.
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── P5: classifier upgrade ──────────────────────────────────────────

def test_event_type_for_dispatch_key_daily_report_prefix_maps_to_daily_report():
    from app.services.notifications import event_type_for_dispatch_key as cls
    # The legacy morning-report mapping must still work.
    assert cls('morning-report-2026-05-11') == 'daily_report'
    # The new daily-report prefix (used by ``send_daily_morning_report``)
    # must now ALSO map to daily_report.
    assert cls('daily-report-2026-05-11') == 'daily_report'
    assert cls('daily-report-2026-12-31::dev42') == 'daily_report'


# ─── P7: scheduled payload builder whitelist ─────────────────────────


class _StubReading:
    """Minimal stand-in for ``app.models.Reading`` with the float fields
    the payload builder reads. The builder doesn't touch any other
    attributes."""
    def __init__(
        self,
        battery_soc=78.5,
        solar_power=1230.0,
        home_load=410.0,
        daily_production=12.5,
        monthly_production=345.0,
        total_production=9876.5,
    ):
        self.battery_soc = battery_soc
        self.solar_power = solar_power
        self.home_load = home_load
        self.daily_production = daily_production
        self.monthly_production = monthly_production
        self.total_production = total_production


def _scope_patch(user_id=901, device_id=42):
    """Patch ``current_scope_ids`` used inside
    ``_build_scheduled_event_payload``."""
    return mock.patch(
        'app.blueprints.notifications.current_scope_ids',
        return_value=(user_id, device_id),
    )


def test_build_payload_periodic_day_has_soc_solar_home_and_optional_weather():
    from app.blueprints.notifications import _build_scheduled_event_payload
    weather = mock.Mock(condition_ar='غيوم خفيفة 30%')
    with _scope_patch(device_id=42):
        payload = _build_scheduled_event_payload(
            'periodic_day', latest=_StubReading(), weather=weather,
        )
    assert payload is not None
    assert payload['v'] == 1
    assert payload['device_id'] == 42
    assert isinstance(payload['ts_utc'], str)
    assert payload['soc'] == 78.5
    assert payload['solar_w'] == 1230.0
    assert payload['home_w'] == 410.0
    assert payload['weather_summary'] == 'غيوم خفيفة 30%'


def test_build_payload_periodic_night_omits_weather_when_absent():
    from app.blueprints.notifications import _build_scheduled_event_payload
    with _scope_patch():
        payload = _build_scheduled_event_payload(
            'periodic_night', latest=_StubReading(), weather=None,
        )
    assert payload is not None
    assert payload['soc'] == 78.5
    assert 'weather_summary' not in payload


def test_build_payload_pre_sunset_echoes_prediction_fields():
    from app.blueprints.notifications import _build_scheduled_event_payload
    prediction = {
        'minutes_to_sunset': 47.0,
        'soc': 78,
        'will_full_before_sunset': False,
        'time_to_full_hours': 2.1,
    }
    with _scope_patch():
        payload = _build_scheduled_event_payload(
            'pre_sunset', prediction=prediction,
        )
    assert payload is not None
    assert payload['minutes_to_sunset'] == 47.0
    assert payload['soc_now'] == 78
    assert payload['will_full_before_sunset'] is False
    assert payload['time_to_full_hours'] == 2.1


def test_build_payload_daily_report_uses_reading_accumulators():
    from app.blueprints.notifications import _build_scheduled_event_payload
    with _scope_patch():
        payload = _build_scheduled_event_payload(
            'daily_report', latest=_StubReading(),
        )
    assert payload is not None
    assert payload['yesterday_kwh'] == 12.5
    assert payload['month_kwh'] == 345.0
    assert payload['lifetime_kwh'] == 9876.5


def test_build_payload_returns_none_for_non_whitelisted_prefix():
    from app.blueprints.notifications import _build_scheduled_event_payload
    with _scope_patch():
        # ``load_alert`` and ``battery_test`` are scheduled families but
        # intentionally OUT of the v44 phase 1a whitelist — they must
        # not get a payload yet.
        assert _build_scheduled_event_payload(
            'load_alert', latest=_StubReading()
        ) is None
        assert _build_scheduled_event_payload(
            'battery_test', latest=_StubReading()
        ) is None
        # And random/unknown prefixes definitely don't.
        assert _build_scheduled_event_payload(
            'mystery', latest=_StubReading()
        ) is None


# ─── P1 + P2 + P3 + P4: mirror payload contract ──────────────────────


def _capture_mirror_call(*, payload=None, simulate_exception=False):
    """Helper that runs ``mirror_energy_notification_to_center`` with a
    fully mocked DB collaborator stack and returns the captured kwargs
    that the ``NotificationEvent`` constructor received."""
    from app.services.notifications.mobile_mirror import (
        mirror_energy_notification_to_center,
    )

    captured: dict = {}

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
        if simulate_exception:
            mock_db.session.commit.side_effect = RuntimeError(
                'DB exploded'
            )
        result = mirror_energy_notification_to_center(
            event_type='daily_report',
            title='تقرير الصباح',
            message='ملخص اليوم.',
            user_id=901,
            device_id=42,
            level='info',
            payload=payload,
        )
    return result, captured


def test_p1_payload_dict_is_serialised_into_result_as_json():
    payload = {
        'v': 1,
        'device_id': 42,
        'ts_utc': '2026-05-11T15:30:00+00:00',
        'yesterday_kwh': 12.5,
        'month_kwh': 345.0,
        'lifetime_kwh': 9876.5,
    }
    ok, captured = _capture_mirror_call(payload=payload)
    assert ok is True
    raw = captured['result']
    assert isinstance(raw, str)
    parsed = json.loads(raw)
    assert parsed == payload


def test_p1_ensure_ascii_false_preserves_arabic_in_payload():
    payload = {
        'v': 1,
        'device_id': 1,
        'weather_summary': 'غيوم خفيفة 30%',
    }
    ok, captured = _capture_mirror_call(payload=payload)
    assert ok is True
    raw = captured['result']
    # Arabic must appear as Arabic, NOT as \u-escapes.
    assert 'غيوم' in raw
    assert '\\u' not in raw


def test_p2_omitting_payload_leaves_result_none():
    ok, captured = _capture_mirror_call(payload=None)
    assert ok is True
    assert captured['result'] is None


def test_p3_oversized_payload_is_dropped_silently_row_still_committed():
    from app.services.notifications.mobile_mirror import MAX_PAYLOAD_BYTES
    huge = {
        'v': 1,
        'device_id': 1,
        # 10 KiB > 8 KiB cap — gets dropped by the serializer.
        'noise': 'x' * (MAX_PAYLOAD_BYTES + 2 * 1024),
    }
    ok, captured = _capture_mirror_call(payload=huge)
    assert ok is True
    # Notification still mirrors, but result is empty (no structured
    # echo) — Telegram/SMS path is unaffected.
    assert captured['result'] is None


def test_p4_non_serializable_payload_is_dropped_silently():
    """The mirror's serializer uses ``json.dumps(..., default=str)`` as a
    safety net, so many "exotic" values (sets, datetimes, Decimals)
    survive via their ``str()`` form. But any value whose ``str()`` /
    ``__str__`` raises still defeats the serializer — and that failure
    must be swallowed without breaking the mirror."""
    class _StrExplodes:
        def __str__(self):  # pragma: no cover - executed by json default
            raise RuntimeError('cannot stringify')

    payload = {
        'v': 1,
        'device_id': 1,
        'forbidden': _StrExplodes(),
    }
    ok, captured = _capture_mirror_call(payload=payload)
    assert ok is True
    assert captured['result'] is None


def test_p4_non_mapping_payload_is_rejected_safely():
    # Passing e.g. a list as payload (caller bug) — the serializer
    # refuses it without breaking the mirror.
    ok, captured = _capture_mirror_call(payload=[1, 2, 3])  # type: ignore[arg-type]
    assert ok is True
    assert captured['result'] is None


# ─── P6: mobile payload builders expose parsed payload ────────────────


def _stub_event(**overrides):
    """Build a ``mock.Mock`` shaped like a NotificationEvent row, with
    sensible defaults the payload builders read from."""
    from datetime import datetime
    defaults = dict(
        id=1,
        event_type='daily_report',
        source_type='energy',
        source_id=42,
        title='تقرير الصباح',
        message='ملخص اليوم.',
        direct_url=None,
        status='new',
        is_read=False,
        appeared_in_bell=False,
        delivered_to_user=False,
        created_at=datetime(2026, 5, 11, 6, 30),
        read_at=None,
        result=None,
    )
    defaults.update(overrides)
    return mock.Mock(**defaults)


def test_p6_v1_builder_returns_parsed_payload_dict_when_result_set():
    from app.blueprints.mobile_api import _mobile_notification_event_payload
    structured = {
        'v': 1,
        'device_id': 42,
        'yesterday_kwh': 12.5,
        'month_kwh': 345.0,
        'lifetime_kwh': 9876.5,
    }
    event = _stub_event(result=json.dumps(structured, ensure_ascii=False))
    out = _mobile_notification_event_payload(event)
    assert out['payload'] == structured


def test_p6_v1_builder_returns_none_when_result_missing():
    from app.blueprints.mobile_api import _mobile_notification_event_payload
    out_none = _mobile_notification_event_payload(_stub_event(result=None))
    out_empty = _mobile_notification_event_payload(_stub_event(result=''))
    out_garbage = _mobile_notification_event_payload(
        _stub_event(result='not-json')
    )
    out_list = _mobile_notification_event_payload(
        _stub_event(result='[1, 2, 3]')  # JSON array, not object
    )
    assert out_none['payload'] is None
    assert out_empty['payload'] is None
    assert out_garbage['payload'] is None
    assert out_list['payload'] is None


def test_p6_v1_builder_preserves_existing_fields_unchanged():
    """Additive: every pre-v44 field still appears in the response."""
    from app.blueprints.mobile_api import _mobile_notification_event_payload
    event = _stub_event(result=json.dumps({'v': 1}))
    out = _mobile_notification_event_payload(event)
    for field in (
        'id', 'event_type', 'source_type', 'source_id', 'title',
        'message', 'url', 'status', 'is_read', 'appeared_in_bell',
        'delivered_to_user', 'created_at', 'read_at', 'payload',
    ):
        assert field in out, f'missing expected field: {field}'


def test_p6_alternate_v1_notifications_builder_also_exposes_payload():
    from app.blueprints.mobile_notifications_api import _notification_payload
    structured = {'v': 1, 'device_id': 42, 'soc': 78.5}
    event = _stub_event(result=json.dumps(structured, ensure_ascii=False))
    out = _notification_payload(event)
    assert out['payload'] == structured
    # Empty / malformed → None
    assert _notification_payload(_stub_event(result=None))['payload'] is None
    assert _notification_payload(_stub_event(result='oops'))['payload'] is None


# ─── v43 backward compatibility ──────────────────────────────────────


def test_v43_mirror_signature_back_compat_no_payload_kwarg():
    """The mirror must still accept the v43 keyword-only signature
    (no ``payload`` kwarg) so any existing call site that hasn't been
    updated continues to work unchanged."""
    from app.services.notifications.mobile_mirror import (
        mirror_energy_notification_to_center,
    )
    with mock.patch(
        'app.services.notifications.mobile_mirror.db'
    ), mock.patch(
        'app.services.notifications.mobile_mirror.AppUser'
    ) as mock_user, mock.patch(
        'app.services.notifications.mobile_mirror.NotificationEvent',
    ) as mock_event:
        mock_user.query.filter_by.return_value.first.return_value = (
            mock.Mock(tenant_id=None)
        )
        ok = mirror_energy_notification_to_center(
            event_type='battery_status',
            title='شحن البطارية',
            message='وصلت البطارية إلى 80%.',
            user_id=901,
            device_id=42,
        )
        assert ok is True
        # ``result`` must default to None when no payload is supplied.
        _, kwargs = mock_event.call_args
        assert kwargs['result'] is None
