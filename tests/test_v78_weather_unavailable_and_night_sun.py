"""v78 — weather unavailable diagnosis hardening + night pre-sunset fix.

Two narrow subscriber-facing fixes:

  Part A — weather unavailable diagnosis is now stricter on
           ``device_weather``:
             * `latest is None` → `reading_unavailable` (was previously
               folded into `station_coords_unavailable`).
             * `latest` exists but `_extract_station_coords` returns
               `(None, None)` → `station_coords_unavailable`.
             * `fetch_weather` raises → `weather_unreachable`.
             * `fetch_weather` returns `None` defensively →
               `weather_unreachable` (was previously a crash path).

  Part B — `build_pre_sunset_prediction` no longer rolls to tomorrow's
           sunset overnight. Subscribers used to see a misleading
           "remaining to sunset: 19 ساعة" string at 23:00; the helper
           now clamps `remaining_hours` to 0 whenever the sun is
           geometrically down and surfaces sunrise-oriented copy in
           `remaining_label`.

Style mirrors v59 / v62 / v68 / v74 / v76: mock-based, no DB,
no `create_app()` boot.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest import mock

from zoneinfo import ZoneInfo

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── Test app + lightweight mocks (mirrors v62 / v74) ───────────────────

def _make_app():
    from flask import Flask
    from app.blueprints.mobile_devices_api import mobile_devices_api_bp
    app = Flask(__name__)
    app.config['MAX_READINGS_QUERY'] = 2000
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    app.register_blueprint(mobile_devices_api_bp)
    return app


def _fake_user(*, id_=1, is_admin=False):
    user = mock.Mock()
    user.id = id_
    user.is_admin = is_admin
    return user


def _fake_device(*, id_=42, name='Roof Inverter', timezone='Asia/Hebron'):
    dev = mock.Mock()
    dev.id = id_
    dev.name = name
    dev.timezone = timezone
    return dev


def _patch_user(user):
    return mock.patch(
        'app.blueprints.mobile_devices_api.user_from_bearer_or_session',
        return_value=user,
    )


def _device_query_returning(device):
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.first.return_value = device
    return chain


def _reading_query_returning(reading):
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = reading
    q = mock.Mock()
    q.filter_by.return_value = chain
    return q


# ═══════════════════════════════════════════════════════════════════════
# Part A — weather endpoint unavailable diagnosis
# ═══════════════════════════════════════════════════════════════════════


def test_weather_route_returns_reading_unavailable_when_no_latest_reading():
    """v78: a freshly-added device with no `Reading` row yet must
    surface `reading_unavailable` — NOT `station_coords_unavailable`.
    Before v78 the two states were conflated; the client could not
    tell "waiting for first sync" apart from "provider has no coords"."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(None)), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
         ) as mock_fetch:
        resp = device_weather(42)
    body = resp.get_json()
    assert body['ok'] is True
    data = body['data']
    assert data['available'] is False
    assert data['reason'] == 'reading_unavailable'
    # The user is still told *which* device this is so the screen
    # header doesn't read as a generic empty state.
    assert data['device']['id'] == 42
    # Locked: no wasted Open-Meteo call.
    mock_fetch.assert_not_called()


def test_weather_route_still_returns_station_coords_unavailable_with_reading_present():
    """v78 regression-lock: when the device DOES have a reading but
    the vendor blob is missing `locationLat`/`locationLng`, the
    route still surfaces `station_coords_unavailable` — the two
    cases now diverge instead of being folded together."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json='{}')
    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(None, None),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
         ) as mock_fetch:
        resp = device_weather(42)
    data = resp.get_json()['data']
    assert data['available'] is False
    assert data['reason'] == 'station_coords_unavailable'
    mock_fetch.assert_not_called()


def test_weather_route_returns_weather_unreachable_when_fetch_raises():
    """v78 regression-lock: vendor outage / timeout still surfaces
    `weather_unreachable`. The exception text must never leak."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json='{}')
    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             side_effect=RuntimeError('vendor-secret-stack-trace-XYZ'),
         ):
        resp = device_weather(42)
    data = resp.get_json()['data']
    assert data['available'] is False
    assert data['reason'] == 'weather_unreachable'
    # Critical: vendor exception text must not be leaked to the
    # client. The mobile contract is the stable `reason` code only.
    assert 'vendor-secret-stack-trace' not in str(data)


def test_weather_route_returns_weather_unreachable_when_fetch_returns_none():
    """v78 new defensive path: a `None` return (rather than a raised
    exception) from the weather wrapper must also be treated as
    unreachable instead of crashing the payload builder downstream."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json='{}')
    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=None,
         ):
        resp = device_weather(42)
    data = resp.get_json()['data']
    assert data['available'] is False
    assert data['reason'] == 'weather_unreachable'


def test_insights_route_returns_weather_unreachable_when_fetch_returns_none():
    """v78 mirror: same defensive None-return handling on the v74
    insights endpoint so the helpers downstream never trip on a
    missing snapshot."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json='{}', id=99)
    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query', _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=None,
         ):
        resp = device_insights(42)
    data = resp.get_json()['data']
    assert data['available'] is False
    assert data['reason'] == 'weather_unreachable'


# ═══════════════════════════════════════════════════════════════════════
# Part B — build_pre_sunset_prediction night fix
# ═══════════════════════════════════════════════════════════════════════


def _make_helper_app():
    """Minimal Flask app with the LOCAL_TIMEZONE config the helper
    reads inside its body."""
    from flask import Flask
    app = Flask(__name__)
    app.config['LOCAL_TIMEZONE'] = 'Asia/Hebron'
    return app


class _FrozenDatetime(datetime):
    """Subclass `datetime` so `datetime.now(tz)` can be deterministic
    inside the helper while every other `datetime.*` method (
    `fromisoformat`, `strftime`, arithmetic) keeps working
    unchanged."""

    _frozen = None

    @classmethod
    def freeze_to(cls, value):
        cls._frozen = value

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        assert cls._frozen is not None, (
            'Test must call _FrozenDatetime.freeze_to(...) before '
            'calling build_pre_sunset_prediction.'
        )
        if tz is not None:
            return cls._frozen.astimezone(tz)
        return cls._frozen


def _fake_latest(*, soc=70.0, solar_power=0.0):
    latest = mock.Mock()
    latest.solar_power = solar_power
    latest.battery_soc = soc
    latest.raw_json = None
    return latest


def _patch_helper_collaborators():
    """Patch the helpers that touch the DB / scope so the function
    under test runs as a pure unit. `load_settings` returns a tiny
    dict, the battery helpers return calm zero-flow numbers, and the
    SunContext import is allowed to fail (the helper already wraps
    it in try/except, so its absence falls through to the legacy
    branch)."""
    return [
        mock.patch(
            'app.blueprints.helpers.load_settings',
            return_value={'pre_sunset_subtract_hour': 'true'},
        ),
        mock.patch(
            'app.blueprints.helpers.get_runtime_battery_settings',
            return_value=(10.0, 20.0),
        ),
        mock.patch(
            'app.blueprints.helpers.build_battery_insights',
            return_value={
                'remaining_to_full_kwh': 4.0,
                'charge_power_w': 0,
                'discharge_power_w': 400,
            },
        ),
    ]


def _call_prediction(latest, *, weather=None, frozen_now=None):
    """Invoke `build_pre_sunset_prediction` with a frozen "now" so
    the night-detection assertions are deterministic regardless of
    when the suite runs."""
    from app.blueprints.helpers import build_pre_sunset_prediction
    app = _make_helper_app()
    _FrozenDatetime.freeze_to(frozen_now)
    patches = _patch_helper_collaborators()
    with app.test_request_context('/'), \
         mock.patch('app.blueprints.helpers.datetime', _FrozenDatetime):
        for p in patches:
            p.start()
        try:
            return build_pre_sunset_prediction(latest, weather=weather)
        finally:
            for p in patches:
                p.stop()


def test_prediction_night_fallback_does_not_count_down_to_tomorrows_sunset():
    """Core v78 fix. At 23:00 Asia/Hebron with no weather payload,
    the previous helper produced `remaining_hours ≈ 19` (rolled to
    tomorrow's 18:00) and a misleading subscriber-facing
    `remaining_label`. The fixed helper clamps to 0 and pivots the
    label to sunrise-oriented copy."""
    tz = ZoneInfo('Asia/Hebron')
    now = datetime(2026, 5, 12, 23, 0, 0, tzinfo=tz)
    out = _call_prediction(_fake_latest(), frozen_now=now)
    assert out is not None
    assert out['remaining_hours'] == 0.0
    assert out['is_night'] is True
    assert out['sun_state'] == 'night'
    # Subscriber-facing label must not claim "19 hours to sunset".
    label = out['remaining_label']
    assert 'الشمس غائبة' in label
    assert '19' not in label
    # Sunrise-oriented copy is now present because
    # `hours_until_sunrise` is populated by the sunrise fallback.
    assert 'الشروق بعد' in label


def test_prediction_pre_dawn_fallback_also_clamps_to_zero():
    """At 02:00 (well before the 06:00 fallback sunrise), the sun
    is still below the horizon. The helper must report 0 remaining
    to sunset and surface `is_night=True`, not "remaining = 15h
    until tonight's sunset"."""
    tz = ZoneInfo('Asia/Hebron')
    now = datetime(2026, 5, 12, 2, 0, 0, tzinfo=tz)
    out = _call_prediction(_fake_latest(), frozen_now=now)
    assert out['remaining_hours'] == 0.0
    assert out['is_night'] is True
    assert out['sun_state'] == 'night'


def test_prediction_daytime_fallback_still_counts_down_to_today_sunset():
    """v78 must NOT break the legitimate daytime fallback. At 12:00
    local, the helper should still return a positive
    `remaining_hours` so the dashboard countdown stays accurate."""
    tz = ZoneInfo('Asia/Hebron')
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=tz)
    out = _call_prediction(_fake_latest(solar_power=1500.0), frozen_now=now)
    assert out['remaining_hours'] > 0
    assert out['is_night'] is False
    assert out['sun_state'] == 'day'
    # Daytime label is the humanized duration, not the night pivot.
    assert 'الشمس غائبة' not in out['remaining_label']


def test_prediction_with_weather_sunset_already_passed_reads_as_night():
    """When real weather data IS available but its sunset time has
    already passed (e.g. 19:00 sunset, now 22:00), the helper must
    behave identically to the fallback night path: clamp to 0,
    surface `is_night=True`, pivot the label."""
    tz = ZoneInfo('Asia/Hebron')
    now = datetime(2026, 5, 12, 22, 0, 0, tzinfo=tz)
    weather = mock.Mock()
    weather.sunset_time = '19:00'
    weather.sunrise_time = '05:30'
    weather.cloud_cover = 20
    weather.condition_ar = 'صافٍ'
    out = _call_prediction(
        _fake_latest(), weather=weather, frozen_now=now,
    )
    assert out['remaining_hours'] == 0.0
    assert out['is_night'] is True
    # Sunrise label is computed from the weather sunrise, not the
    # 06:00 fallback — verify the helper preferred the real value.
    assert out['sunrise_time'] == '05:30'
    # The human "X ساعة" sunrise label exists and is meaningful.
    assert out['sunrise_remaining_label']
    assert out['sunrise_remaining_label'] != 'غير متاح'


def test_prediction_with_weather_sunrise_missing_falls_back_cleanly():
    """v78 regression-lock: when only the sunset is present and the
    sunrise field is missing, the helper still produces a valid
    `hours_until_sunrise` from the 06:00 fallback."""
    tz = ZoneInfo('Asia/Hebron')
    now = datetime(2026, 5, 12, 22, 0, 0, tzinfo=tz)
    weather = mock.Mock()
    weather.sunset_time = '19:00'
    weather.sunrise_time = None
    weather.cloud_cover = 20
    weather.condition_ar = 'صافٍ'
    out = _call_prediction(
        _fake_latest(), weather=weather, frozen_now=now,
    )
    assert out['hours_until_sunrise'] is not None
    assert out['hours_until_sunrise'] > 0


def test_prediction_daytime_with_weather_keeps_full_countdown():
    """v78 must NOT regress the daytime path when weather is
    present. At 12:00 local with a 19:00 sunset, `remaining_hours`
    should still report ~6 hours so the dashboard countdown stays
    accurate."""
    tz = ZoneInfo('Asia/Hebron')
    now = datetime(2026, 5, 12, 12, 0, 0, tzinfo=tz)
    weather = mock.Mock()
    weather.sunset_time = '19:00'
    weather.sunrise_time = '05:30'
    weather.cloud_cover = 20
    weather.condition_ar = 'صافٍ'
    out = _call_prediction(
        _fake_latest(solar_power=1500.0),
        weather=weather, frozen_now=now,
    )
    assert out['remaining_hours'] is not None
    assert out['remaining_hours'] > 5.0
    assert out['remaining_hours'] < 7.0
    assert out['is_night'] is False
    assert out['sun_state'] == 'day'


def test_mobile_solar_prediction_surfaces_is_night_and_clears_sunset_claims():
    """v78: the mobile mapper now propagates `is_night` and, at
    night, forces `will_full_before_sunset=False` +
    `time_to_full_hours=None` because the sunset heuristic no longer
    applies."""
    from app.blueprints.mobile_devices_api import _mobile_solar_prediction
    night = {
        'sunset_time': '19:00',
        'effective_sunset_time': '18:00',
        # Stale residual values the helper might have computed before
        # the night clamp — the mapper must scrub them at night.
        'time_to_full_hours': 2.5,
        'will_full_before_sunset': True,
        'verdict': 'فترة ليلية',
        'advice': 'البطارية تحمل النظام حتى الشروق.',
        'is_night': True,
    }
    out = _mobile_solar_prediction(night)
    assert out['is_night'] is True
    assert out['time_to_full_hours'] is None
    assert out['will_full_before_sunset'] is False
    # Day-side keys still carried through.
    assert out['verdict'] == 'فترة ليلية'
