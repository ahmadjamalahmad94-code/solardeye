"""v62 — mobile weather endpoint tests.

The new route in `app/blueprints/mobile_devices_api.py` is a thin
wrapper around three things:

  1. `_device_allowed`         — owner-scope guard (existing).
  2. `extract_station_coords`  — reads lat/lng off the latest
                                 reading's vendor blob (existing).
  3. `fetch_weather`           — Open-Meteo client (existing).

Coverage is split into two layers, mirroring v59:

  * **Helper unit tests** — pure mappers (`_slot_for_mobile`,
    `_mobile_weather_payload`, `_mobile_weather_unavailable`). Lock
    the response shape without booting Flask.
  * **Route handler tests** — drive `device_weather(device_id)`
    inside a `Flask.test_request_context` with the auth helper, the
    `AppDevice` / `Reading` queries, `extract_station_coords`, and
    `fetch_weather` all mocked. Lock the success + unavailable +
    owner-scope + auth wiring.

No DB, no `create_app()` boot — same lightweight style as
`test_v59_mobile_reports_summary.py`.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Helper unit tests (no Flask context)
# ═══════════════════════════════════════════════════════════════════════


def _make_snapshot(**overrides):
    """Return a `WeatherSnapshot` populated with realistic test
    values. `WeatherSnapshot` is a dataclass — the real class is
    imported here so we lock against the actual field set rather
    than a parallel structure."""
    from app.services.weather_service import WeatherSnapshot
    defaults = dict(
        temperature=28.4,
        wind_speed=3.2,
        cloud_cover=35.0,
        precipitation_probability=5.0,
        code=2,
        condition_ar='غائم جزئيًا',
        category='partly_cloudy',
        icon='⛅',
        current_time='2026-05-12T10:00:00',
        morning={
            'time': '2026-05-12T09:00:00',
            'temperature': 26.0, 'cloud_cover': 20.0,
            'precipitation_probability': 0.0,
            'condition_ar': 'مشمس', 'category': 'sunny', 'icon': '☀️',
            'solar_rating': 'إنتاج قوي',
            'advice': 'وقت ممتاز لتشغيل الأجهزة الثقيلة.',
        },
        noon={
            'time': '2026-05-12T12:00:00',
            'temperature': 29.5, 'cloud_cover': 30.0,
            'precipitation_probability': 0.0,
            'condition_ar': 'غائم جزئيًا', 'category': 'partly_cloudy',
            'icon': '⛅',
            'solar_rating': 'إنتاج متوسط',
            'advice': 'يفضل تخفيف الأحمال الثقيلة.',
        },
        afternoon={
            'time': '2026-05-12T15:00:00',
            'temperature': 30.2, 'cloud_cover': 45.0,
            'precipitation_probability': 5.0,
            'condition_ar': 'غائم جزئيًا', 'category': 'partly_cloudy',
            'icon': '⛅',
            'solar_rating': 'إنتاج متوسط',
            'advice': 'يفضل تخفيف الأحمال الثقيلة.',
        },
        next_hour={
            'time': '2026-05-12T11:00:00',
            'temperature': 29.0, 'cloud_cover': 40.0,
            'precipitation_probability': 5.0,
            'condition_ar': 'غائم جزئيًا', 'category': 'partly_cloudy',
            'icon': '⛅',
            'solar_rating': 'إنتاج متوسط',
            'advice': 'يفضل تخفيف الأحمال الثقيلة.',
        },
        sunset_time='19:42',
        effective_sunset_time='18:42',
        sunrise_time='05:14',
        effective_sunrise_time='05:14',
        timeline=[
            {
                'time_label': '8:00 ص', 'temperature': 25.0,
                'cloud_cover': 18.0, 'precipitation_probability': 0.0,
                'condition_ar': 'مشمس', 'category': 'sunny', 'icon': '☀️',
                'solar_rating': 'إنتاج قوي',
                'advice': 'وقت ممتاز لتشغيل الأجهزة الثقيلة.',
            },
            {
                'time_label': '10:00 ص', 'temperature': 27.5,
                'cloud_cover': 22.0, 'precipitation_probability': 0.0,
                'condition_ar': 'غائم جزئيًا', 'category': 'partly_cloudy',
                'icon': '⛅',
                'solar_rating': 'إنتاج متوسط',
                'advice': 'يفضل تخفيف الأحمال الثقيلة.',
            },
        ],
    )
    defaults.update(overrides)
    return WeatherSnapshot(**defaults)


def _fake_device(*, id_=42, name='Roof Inverter', timezone='Asia/Hebron'):
    dev = mock.Mock()
    dev.id = id_
    dev.name = name
    dev.timezone = timezone
    return dev


# ─── _slot_for_mobile ──────────────────────────────────────────────────

def test_slot_filter_returns_only_contract_keys():
    """The slot filter must NOT silently leak future backend fields
    into the mobile payload — only the documented contract keys."""
    from app.blueprints.mobile_devices_api import (
        _slot_for_mobile, _MOBILE_WEATHER_SLOT_KEYS,
    )
    raw = {
        'time': '2026-05-12T11:00:00',
        'time_label': '11:00 ص',
        'temperature': 29.0,
        'cloud_cover': 40.0,
        'precipitation_probability': 5.0,
        'condition_ar': 'غائم جزئيًا',
        'category': 'partly_cloudy',
        'icon': '⛅',
        'solar_rating': 'إنتاج متوسط',
        'advice': 'يفضل تخفيف الأحمال الثقيلة.',
        # Hypothetical future field the contract has not opted into yet.
        'experimental_humidity_percent': 62,
    }
    slot = _slot_for_mobile(raw)
    assert set(slot.keys()) == set(_MOBILE_WEATHER_SLOT_KEYS)
    assert 'experimental_humidity_percent' not in slot
    assert slot['solar_rating'] == 'إنتاج متوسط'
    assert slot['advice'].startswith('يفضل')


def test_slot_filter_returns_none_for_non_dict():
    """`WeatherSnapshot.next_hour` is initialised even on cold
    payloads, but the helper must still handle None/garbage."""
    from app.blueprints.mobile_devices_api import _slot_for_mobile
    assert _slot_for_mobile(None) is None
    assert _slot_for_mobile('not a dict') is None
    assert _slot_for_mobile(42) is None


def test_slot_filter_preserves_missing_keys_as_none():
    """Sparse slot (e.g. a timeline entry with no precipitation) ->
    keys present, values `None`. The mobile parser keeps a stable
    shape regardless of which optional fields were filled."""
    from app.blueprints.mobile_devices_api import _slot_for_mobile
    slot = _slot_for_mobile({
        'time_label': '12:00 م',
        'temperature': 30.0,
        'cloud_cover': 50.0,
        # `precipitation_probability` deliberately missing
        'condition_ar': 'غائم جزئيًا',
        'category': 'partly_cloudy',
        'icon': '⛅',
        'solar_rating': 'إنتاج متوسط',
        'advice': 'يفضل تخفيف الأحمال الثقيلة.',
    })
    assert slot['precipitation_probability'] is None
    assert slot['time_label'] == '12:00 م'


# ─── _mobile_weather_payload ───────────────────────────────────────────

def test_payload_success_shape_locked():
    from app.blueprints.mobile_devices_api import _mobile_weather_payload
    device = _fake_device()
    snapshot = _make_snapshot()
    payload = _mobile_weather_payload(
        device, snapshot, '2026-05-12T10:00:00',
    )
    assert payload['available'] is True
    assert payload['generated_at'] == '2026-05-12T10:00:00'

    # Device summary
    assert payload['device'] == {
        'id': 42,
        'name': 'Roof Inverter',
        'timezone': 'Asia/Hebron',
    }

    # Current conditions — values pass through, no rounding.
    cur = payload['current']
    assert cur['temperature_c'] == 28.4
    assert cur['wind_speed'] == 3.2
    assert cur['cloud_cover_percent'] == 35.0
    assert cur['precipitation_probability_percent'] == 5.0
    assert cur['condition_ar'] == 'غائم جزئيًا'
    assert cur['category'] == 'partly_cloudy'
    assert cur['icon'] == '⛅'
    assert cur['code'] == 2
    assert cur['current_time'] == '2026-05-12T10:00:00'

    # Sun times
    sun = payload['sun']
    assert sun['sunrise_time'] == '05:14'
    assert sun['sunset_time'] == '19:42'
    assert sun['effective_sunrise_time'] == '05:14'
    assert sun['effective_sunset_time'] == '18:42'

    # Next-hour slot
    assert payload['next_hour']['time'] == '2026-05-12T11:00:00'
    assert payload['next_hour']['solar_rating'] == 'إنتاج متوسط'

    # Day-parts present in canonical order keys
    assert set(payload['day_parts'].keys()) == {'morning', 'noon', 'afternoon'}
    assert payload['day_parts']['morning']['condition_ar'] == 'مشمس'
    assert payload['day_parts']['noon']['icon'] == '⛅'
    assert payload['day_parts']['afternoon']['solar_rating'] == 'إنتاج متوسط'

    # Timeline preserved + filtered to the contract.
    assert isinstance(payload['timeline'], list)
    assert len(payload['timeline']) == 2
    assert payload['timeline'][0]['time_label'] == '8:00 ص'
    assert payload['timeline'][0]['solar_rating'] == 'إنتاج قوي'


def test_payload_handles_empty_timeline():
    """Snapshot with empty `timeline` → empty list in payload, not None."""
    from app.blueprints.mobile_devices_api import _mobile_weather_payload
    device = _fake_device()
    snapshot = _make_snapshot(timeline=[])
    payload = _mobile_weather_payload(device, snapshot, '2026-05-12T10:00:00')
    assert payload['timeline'] == []


def test_payload_tolerates_none_day_part_slots():
    """`_slot_from_hourly` returns its own fallback dict, but defensive
    code: when day_parts come back as None the payload must keep the
    key with `None` value — never crash, never invent a fallback."""
    from app.blueprints.mobile_devices_api import _mobile_weather_payload
    device = _fake_device()
    snapshot = _make_snapshot(morning=None, noon=None, afternoon=None,
                              next_hour=None)
    payload = _mobile_weather_payload(device, snapshot, '2026-05-12T10:00:00')
    assert payload['day_parts'] == {'morning': None, 'noon': None, 'afternoon': None}
    assert payload['next_hour'] is None


def test_payload_passes_through_missing_sun_times_as_none():
    """Some Open-Meteo regions / dates return empty sunrise / sunset
    lists. The snapshot's fields are already `None` in that case —
    the mobile payload preserves them as `None` rather than fabricating
    a sunrise/sunset string."""
    from app.blueprints.mobile_devices_api import _mobile_weather_payload
    device = _fake_device()
    snapshot = _make_snapshot(
        sunrise_time=None, sunset_time=None,
        effective_sunrise_time=None, effective_sunset_time=None,
    )
    payload = _mobile_weather_payload(device, snapshot, '2026-05-12T10:00:00')
    assert payload['sun']['sunrise_time'] is None
    assert payload['sun']['sunset_time'] is None


# ─── _mobile_weather_unavailable ───────────────────────────────────────

def test_unavailable_payload_carries_stable_reason_code():
    from app.blueprints.mobile_devices_api import _mobile_weather_unavailable
    device = _fake_device()
    payload = _mobile_weather_unavailable(
        reason='station_coords_unavailable',
        message='Weather data is not available for this device yet.',
        device=device,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['available'] is False
    assert payload['reason'] == 'station_coords_unavailable'
    assert payload['message'].startswith('Weather data is not')
    assert payload['device']['id'] == 42
    assert payload['generated_at'] == '2026-05-12T10:00:00'
    # Honest: no fabricated current / sun / timeline blocks.
    assert 'current' not in payload
    assert 'sun' not in payload
    assert 'timeline' not in payload


def test_unavailable_payload_supports_weather_unreachable_reason():
    from app.blueprints.mobile_devices_api import _mobile_weather_unavailable
    device = _fake_device()
    payload = _mobile_weather_unavailable(
        reason='weather_unreachable',
        message='Weather service could not be reached right now.',
        device=device,
        generated_at='2026-05-12T10:00:00',
    )
    assert payload['reason'] == 'weather_unreachable'
    assert payload['available'] is False


# ═══════════════════════════════════════════════════════════════════════
# Route handler tests (Flask test_request_context + mocks)
# ═══════════════════════════════════════════════════════════════════════


def _make_app():
    """Build a minimal Flask app with just the device blueprint
    mounted. No DB, no scheduler, no `create_app()` boot."""
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


def _patch_user(user):
    return mock.patch(
        'app.blueprints.mobile_devices_api.user_from_bearer_or_session',
        return_value=user,
    )


def _device_query_returning(device):
    """Chain-mock for `AppDevice.query.filter_by(...).filter_by(...).first()`."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.first.return_value = device
    return chain


def _reading_query_returning(reading):
    """Chain-mock for
    `Reading.query.filter_by(device_id=…).order_by(…).first()`."""
    chain = mock.Mock()
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.first.return_value = reading
    q = mock.Mock()
    q.filter_by.return_value = chain
    # `Reading.query.filter_by(...).order_by(...).first()` chain:
    # `Reading.query` → q, `q.filter_by(...)` → chain, then chain
    # rolls onto itself for `.order_by(...).first()`.
    return q


# ─── Unauthenticated / owner-scope ─────────────────────────────────────

def test_route_unauthenticated_returns_401():
    from app.blueprints.mobile_devices_api import device_weather
    app = _make_app()
    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(None):
        resp = device_weather(42)
        assert resp.status_code == 401
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'auth_required'


def test_route_device_not_found_for_foreign_owner():
    """`_device_allowed` returns None when the device doesn't belong
    to the requesting user. Route must return 404 `device_not_found`
    — never expose the device's existence to a different user, never
    leak weather coords to a non-owner."""
    from app.blueprints.mobile_devices_api import device_weather, AppDevice
    app = _make_app()
    user = _fake_user()
    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(None)):
        resp = device_weather(42)
        assert resp.status_code == 404
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'device_not_found'


# ─── Unavailable: no coords ────────────────────────────────────────────

def test_route_returns_available_false_when_coords_unavailable():
    """When the latest reading lacks `station_summary.locationLat/Lng`,
    `extract_station_coords` returns `(None, None)`. The route must
    honestly report `available=false, reason='station_coords_unavailable'`
    instead of fabricating a default location."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()

    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(mock.Mock(raw_json=None))), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(None, None),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
         ) as mock_fetch:
        resp = device_weather(42)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        data = body['data']
        assert data['available'] is False
        assert data['reason'] == 'station_coords_unavailable'
        assert data['device']['id'] == 42
        # Locked: when coords are unavailable, fetch_weather must NOT
        # be called (no wasted Open-Meteo call, no fabricated payload).
        mock_fetch.assert_not_called()
        # Honest: no current / sun / timeline blocks present.
        assert 'current' not in data
        assert 'sun' not in data
        assert 'timeline' not in data


# ─── Unavailable: weather fetch fails ──────────────────────────────────

def test_route_returns_available_false_when_weather_fetch_raises():
    """When Open-Meteo is unreachable (network error / vendor outage
    / timeout), `fetch_weather` raises. The route must catch and
    return `available=false, reason='weather_unreachable'` — the
    raw exception text never leaks to the client."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()

    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(mock.Mock(raw_json='{}'))), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             side_effect=RuntimeError('open-meteo timed out'),
         ):
        resp = device_weather(42)
        assert resp.status_code == 200
        body = resp.get_json()
        data = body['data']
        assert data['available'] is False
        assert data['reason'] == 'weather_unreachable'
        assert data['message'] == 'Weather service could not be reached right now.'
        # Honest: no vendor stack trace, no `current`/`sun`/`timeline`
        # in the unavailable payload.
        assert 'current' not in data
        assert 'open-meteo' not in str(data).lower()


# ─── Success: full payload ─────────────────────────────────────────────

def test_route_success_returns_full_weather_payload():
    """Happy path: coords resolve and Open-Meteo returns a snapshot.
    The route serialises every documented field of the snapshot
    onto the mobile contract."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device(timezone='Asia/Hebron')
    snapshot = _make_snapshot()

    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(mock.Mock(raw_json='{}'))), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=snapshot,
         ) as mock_fetch:
        resp = device_weather(42)
        assert resp.status_code == 200
        body = resp.get_json()
        data = body['data']
        assert data['available'] is True
        # Locked: fetch_weather is called with the resolved coords +
        # the device's timezone (NOT the app default when one is set).
        mock_fetch.assert_called_once_with(31.5, 35.1, 'Asia/Hebron')

        # Spot-check the locked contract keys (full shape is unit-
        # tested by `test_payload_success_shape_locked`).
        for key in ('device', 'current', 'sun',
                    'next_hour', 'day_parts', 'timeline',
                    'generated_at'):
            assert key in data
        assert data['current']['temperature_c'] == 28.4
        assert data['sun']['sunset_time'] == '19:42'
        assert data['day_parts']['morning']['solar_rating'] == 'إنتاج قوي'
        assert len(data['timeline']) == 2


def test_route_falls_back_to_app_timezone_when_device_has_none():
    """If the device row has no timezone set, the route uses the app
    config's `LOCAL_TIMEZONE`. We never call `fetch_weather` with an
    empty/None timezone (Open-Meteo requires a valid IANA name)."""
    from app.blueprints.mobile_devices_api import (
        device_weather, AppDevice, Reading,
    )
    app = _make_app()
    app.config['LOCAL_TIMEZONE'] = 'Asia/Hebron'
    user = _fake_user()
    device = _fake_device(timezone='')  # honest empty
    snapshot = _make_snapshot()

    with app.test_request_context('/api/v1/devices/42/weather'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(mock.Mock(raw_json='{}'))), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=snapshot,
         ) as mock_fetch:
        device_weather(42)
        mock_fetch.assert_called_once_with(31.5, 35.1, 'Asia/Hebron')
