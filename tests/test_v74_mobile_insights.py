"""v74 — mobile smart insights endpoint tests.

The route in `app/blueprints/mobile_devices_api.py` is a thin
orchestration over four reused helpers:

  1. `_device_allowed`               — owner-scope guard (existing).
  2. `Reading.query...first()`       — latest reading resolution.
  3. `_extract_station_coords`       — v62 lazy wrapper.
  4. `fetch_weather`                 — v62 weather client.
  5. `build_pre_sunset_prediction`   — existing helper, untouched.
  6. `build_smart_energy_advice`     — existing helper, untouched.

The mobile-facing payload is built by three pure mappers
(`_mobile_advice_level`, `_mobile_energy_advice`,
`_mobile_solar_prediction`, `_mobile_weather_context`,
`_mobile_insights_payload`). Coverage style mirrors v59 / v62 /
v65 / v68 / v71: pure helper tests + route handler tests via
`Flask.test_request_context` + mocks. No DB, no `create_app()` boot.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# Helper unit tests (no Flask context required)
# ═══════════════════════════════════════════════════════════════════════

def test_advice_level_maps_emoji_prefix_to_stable_string():
    from app.blueprints.mobile_devices_api import _mobile_advice_level
    assert _mobile_advice_level('🟢 مطمئن') == 'good'
    assert _mobile_advice_level('🟡 تشغيل محدود بحذر') == 'caution'
    assert _mobile_advice_level('🟠 حافظ على الشحن') == 'warning'
    assert _mobile_advice_level('🔴 حرج') == 'critical'
    assert _mobile_advice_level('⚪ لا توجد بيانات') == 'unknown'
    # Defensive: unknown label without an emoji prefix falls back to unknown.
    assert _mobile_advice_level('plain text') == 'unknown'
    assert _mobile_advice_level('') == 'unknown'
    assert _mobile_advice_level(None) == 'unknown'


def test_energy_advice_picks_warning_then_recommendation():
    """The mapper prefers `smart_warning` + `smart_recommendation`
    when both are present (warning explains *why*, recommendation
    explains *what to do*). Headline always comes from status_label."""
    from app.blueprints.mobile_devices_api import _mobile_energy_advice
    out = _mobile_energy_advice({
        'status_label': '🟡 تشغيل محدود بحذر',
        'smart_warning': 'الوقت المتبقي قبل الغروب قصير.',
        'smart_recommendation': 'يفضل تجنب تشغيل حمل طويل الآن.',
        'decision_now': 'تشغيل صغير فقط إذا كان ضروريًا.',
    })
    assert out['headline'] == '🟡 تشغيل محدود بحذر'
    assert out['level'] == 'caution'
    # Both warning + recommendation appear, space-separated.
    assert 'الوقت المتبقي' in out['detail']
    assert 'يفضل تجنب' in out['detail']


def test_energy_advice_falls_back_to_decision_when_no_warning():
    from app.blueprints.mobile_devices_api import _mobile_energy_advice
    out = _mobile_energy_advice({
        'status_label': '🟢 مطمئن',
        'smart_warning': '',
        'smart_recommendation': '',
        'decision_now': 'الوضع الليلي مستقر حالياً.',
    })
    assert out['headline'] == '🟢 مطمئن'
    assert out['level'] == 'good'
    assert out['detail'] == 'الوضع الليلي مستقر حالياً.'


def test_energy_advice_tolerates_empty_or_garbage_input():
    from app.blueprints.mobile_devices_api import _mobile_energy_advice
    empty = _mobile_energy_advice({})
    assert empty == {'headline': '', 'detail': '', 'level': 'unknown'}
    not_dict = _mobile_energy_advice('garbage')  # type: ignore[arg-type]
    assert not_dict == {'headline': '', 'detail': '', 'level': 'unknown'}


def test_solar_prediction_compact_subset_locked():
    """The mapper must pick exactly five keys + round time-to-full.
    No admin-only / internal helper keys should leak through."""
    from app.blueprints.mobile_devices_api import _mobile_solar_prediction
    raw = {
        'sunset_time': '19:42',
        'effective_sunset_time': '18:42',
        'sunrise_time': '05:14',
        'time_to_full_hours': 2.512345,
        'will_full_before_sunset': True,
        'verdict': 'سيتم شحن البطارية قبل الغروب',
        'advice': 'الوضع جيد.',
        'level': 'success',
        # Admin / internal fields that must NOT leak:
        'capacity_kwh': 10.0,
        'reserve_percent': 20,
        'minutes_to_sunset': 150.7,
        'is_day': True,
        'weather_level': 'success',
        'weather_advice': 'الطقس مشمس.',
    }
    out = _mobile_solar_prediction(raw)
    assert out == {
        'sunset_time': '19:42',
        'effective_sunset_time': '18:42',
        'time_to_full_hours': 2.51,  # rounded to 2 decimals
        'will_full_before_sunset': True,
        'verdict': 'سيتم شحن البطارية قبل الغروب',
        'advice': 'الوضع جيد.',
    }


def test_solar_prediction_returns_none_when_helper_returned_none():
    """`build_pre_sunset_prediction(latest=None, ...)` returns `None`;
    the mapper must surface that as `None` so the route can branch
    without nil-checking the dict."""
    from app.blueprints.mobile_devices_api import _mobile_solar_prediction
    assert _mobile_solar_prediction(None) is None
    assert _mobile_solar_prediction({}) == {
        'sunset_time': None,
        'effective_sunset_time': None,
        'time_to_full_hours': None,
        'will_full_before_sunset': False,
        'verdict': None,
        'advice': None,
    }


def test_weather_context_compact_subset_locked():
    """Only three fields — never the full `WeatherSnapshot` shape."""
    from app.blueprints.mobile_devices_api import _mobile_weather_context
    snap = mock.Mock()
    snap.condition_ar = 'غائم جزئيًا'
    snap.icon = '⛅'
    snap.cloud_cover = 35.0
    # Unused fields the mapper must NOT touch:
    snap.temperature = 28.4
    snap.timeline = ['don\'t leak this']
    snap.sunset_time = '19:42'
    out = _mobile_weather_context(snap)
    assert set(out.keys()) == {'condition_ar', 'icon', 'cloud_cover_percent'}
    assert out == {
        'condition_ar': 'غائم جزئيًا',
        'icon': '⛅',
        'cloud_cover_percent': 35.0,
    }


def test_weather_context_handles_none_snapshot_defensively():
    from app.blueprints.mobile_devices_api import _mobile_weather_context
    out = _mobile_weather_context(None)
    assert out == {
        'condition_ar': '',
        'icon': '',
        'cloud_cover_percent': None,
    }


# ═══════════════════════════════════════════════════════════════════════
# Route handler tests (Flask test_request_context + mocks)
# ═══════════════════════════════════════════════════════════════════════

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


# ─── Auth + owner-scope ────────────────────────────────────────────────

def test_route_unauthenticated_returns_401():
    from app.blueprints.mobile_devices_api import device_insights
    app = _make_app()
    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(None):
        resp = device_insights(42)
        assert resp.status_code == 401
        body = resp.get_json()
        assert body['ok'] is False
        assert body['code'] == 'auth_required'


def test_route_foreign_owner_returns_404_device_not_found():
    """`_device_allowed` returns None → 404. Never leaks the device's
    existence to a non-owner."""
    from app.blueprints.mobile_devices_api import device_insights, AppDevice
    app = _make_app()
    user = _fake_user()
    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query', _device_query_returning(None)):
        resp = device_insights(42)
        assert resp.status_code == 404
        body = resp.get_json()
        assert body['code'] == 'device_not_found'


# ─── Unavailable cases ─────────────────────────────────────────────────

def test_route_returns_available_false_when_no_latest_reading():
    """The smart engine returns a `safe_empty` advice dict when
    `latest is None`, but the mobile contract wants an explicit
    `available=false, reason='reading_unavailable'` so the card
    renders a calm "no data yet" state instead of stale advice."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query',
                           _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(None)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
         ) as mock_coords, \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
         ) as mock_weather, \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_pre_sunset_prediction',
         ) as mock_pred, \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_smart_energy_advice',
         ) as mock_advice:
        resp = device_insights(42)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        data = body['data']
        assert data['available'] is False
        assert data['reason'] == 'reading_unavailable'
        assert data['device']['id'] == 42
        # No downstream helper was called — we short-circuited honestly.
        mock_coords.assert_not_called()
        mock_weather.assert_not_called()
        mock_pred.assert_not_called()
        mock_advice.assert_not_called()
        # Honest: no current/prediction/advice keys when unavailable.
        assert 'weather_context' not in data
        assert 'solar_prediction' not in data
        assert 'energy_advice' not in data


def test_route_returns_available_false_when_coords_missing():
    """`extract_station_coords` returns `(None, None)` →
    `available=false, reason='station_coords_unavailable'`. No
    `fetch_weather` call, no smart-engine work."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json=None, id=99)
    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query',
                           _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(None, None),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
         ) as mock_weather, \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_pre_sunset_prediction',
         ) as mock_pred, \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_smart_energy_advice',
         ) as mock_advice:
        resp = device_insights(42)
        assert resp.status_code == 200
        body = resp.get_json()
        data = body['data']
        assert data['available'] is False
        assert data['reason'] == 'station_coords_unavailable'
        mock_weather.assert_not_called()
        mock_pred.assert_not_called()
        mock_advice.assert_not_called()


def test_route_returns_available_false_when_weather_fetch_raises():
    """Open-Meteo unreachable → `available=false,
    reason='weather_unreachable'`. The exception text never leaks
    to the response."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json='{}', id=99)
    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query',
                           _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             side_effect=RuntimeError('open-meteo timed out'),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_pre_sunset_prediction',
         ) as mock_pred, \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_smart_energy_advice',
         ) as mock_advice:
        resp = device_insights(42)
        assert resp.status_code == 200
        body = resp.get_json()
        data = body['data']
        assert data['available'] is False
        assert data['reason'] == 'weather_unreachable'
        # No vendor stack trace in the body.
        assert 'open-meteo' not in str(data).lower()
        # Helpers never ran since weather failed.
        mock_pred.assert_not_called()
        mock_advice.assert_not_called()


# ─── Success: full insights payload ───────────────────────────────────

def _fake_weather_snapshot():
    snap = mock.Mock()
    snap.condition_ar = 'غائم جزئيًا'
    snap.icon = '⛅'
    snap.cloud_cover = 35.0
    snap.temperature = 28.4
    snap.sunset_time = '19:42'
    return snap


def _fake_prediction_dict():
    return {
        'sunset_time': '19:42',
        'effective_sunset_time': '18:42',
        'sunrise_time': '05:14',
        'effective_sunrise_time': '05:14',
        'remaining_hours': 2.0,
        'remaining_label': 'ساعتان تقريباً',
        'minutes_to_sunset': 120.0,
        'hours_until_sunrise': 11.0,
        'sunrise_remaining_label': '11 ساعة',
        'time_to_full_hours': 1.5,
        'will_full_before_sunset': True,
        'verdict': 'سيتم شحن البطارية قبل الغروب',
        'advice': 'الوضع جيد.',
        'level': 'success',
        'is_day': True,
        'weather_advice': 'الطقس مشمس.',
        'weather_level': 'success',
        'capacity_kwh': 10.0,
        'reserve_percent': 20,
    }


def _fake_advice_dict():
    return {
        'status_label': '🟢 مطمئن',
        'smart_warning': '',
        'smart_recommendation': 'يمكن تشغيل الأحمال الخفيفة باعتدال.',
        'decision_now': 'الوضع الليلي مستقر حالياً.',
        'historical_hint': 'بناءً على آخر 12 يومًا...',
        'confidence_label': 'ثقة جيدة',
        'confidence_message': 'يعتمد',
        'confidence_band': 'high',
        'matched_count': 12,
        'predicted_risk_level': 'منخفض',
        'predicted_risk_code': 'low',
        'scenario_title': 'الساعة القادمة',
        'scenario_summary': 'إنتاج مستقر',
        'scenario_detail': 'بناءً على أنماط الأرشيف',
        'historical_is_actionable': True,
    }


def test_route_success_returns_full_insights_payload():
    """Happy path: reading + coords + weather all resolve. Route
    binds scope, calls both helpers, flattens the output."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device(timezone='Asia/Hebron')
    reading = mock.Mock(raw_json='{}', id=99)
    snapshot = _fake_weather_snapshot()
    pred_dict = _fake_prediction_dict()
    advice_dict = _fake_advice_dict()

    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query',
                           _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=snapshot,
         ) as mock_fetch, \
         mock.patch(
             'app.blueprints.mobile_devices_api.load_settings',
             return_value={},
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_pre_sunset_prediction',
             return_value=pred_dict,
         ) as mock_pred, \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_smart_energy_advice',
             return_value=advice_dict,
         ) as mock_advice:
        resp = device_insights(42)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    data = body['data']
    assert data['available'] is True
    assert data['device'] == {
        'id': 42,
        'name': 'Roof Inverter',
        'timezone': 'Asia/Hebron',
    }

    # weather_context — compact, three keys only.
    assert data['weather_context'] == {
        'condition_ar': 'غائم جزئيًا',
        'icon': '⛅',
        'cloud_cover_percent': 35.0,
    }

    # solar_prediction — exactly six keys, time_to_full rounded.
    sp = data['solar_prediction']
    assert set(sp.keys()) == {
        'sunset_time', 'effective_sunset_time', 'time_to_full_hours',
        'will_full_before_sunset', 'verdict', 'advice',
    }
    assert sp['sunset_time'] == '19:42'
    assert sp['effective_sunset_time'] == '18:42'
    assert sp['time_to_full_hours'] == 1.5
    assert sp['will_full_before_sunset'] is True
    assert sp['verdict'] == 'سيتم شحن البطارية قبل الغروب'
    assert sp['advice'] == 'الوضع جيد.'

    # energy_advice — exactly three keys, level mapped from emoji.
    ea = data['energy_advice']
    assert set(ea.keys()) == {'headline', 'detail', 'level'}
    assert ea['headline'] == '🟢 مطمئن'
    assert ea['level'] == 'good'
    # No warning → falls back to recommendation.
    assert 'يمكن تشغيل الأحمال الخفيفة' in ea['detail']

    # Locked: helpers were called with the resolved coords + snapshot
    # so the prediction + advice both saw the same weather.
    mock_fetch.assert_called_once_with(31.5, 35.1, 'Asia/Hebron')
    mock_pred.assert_called_once()
    mock_advice.assert_called_once()
    # `generated_at` is always present so the mobile UI can show a
    # "last refreshed" caption.
    assert 'generated_at' in data


def test_route_success_does_not_leak_internal_prediction_keys():
    """Regression lock: even when the prediction dict carries lots of
    internal keys (`capacity_kwh`, `reserve_percent`, `minutes_to_sunset`,
    `weather_advice`, `weather_level`, `is_day`, etc.), the response
    `solar_prediction` block surfaces only the documented six."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    app = _make_app()
    user = _fake_user()
    device = _fake_device()
    reading = mock.Mock(raw_json='{}', id=99)
    snapshot = _fake_weather_snapshot()
    # Verbose prediction dict with many internal keys.
    pred = _fake_prediction_dict()
    pred['capacity_kwh'] = 999.0
    pred['reserve_percent'] = 42

    with app.test_request_context('/api/v1/devices/42/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query',
                           _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=snapshot,
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.load_settings',
             return_value={},
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_pre_sunset_prediction',
             return_value=pred,
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_smart_energy_advice',
             return_value=_fake_advice_dict(),
         ):
        resp = device_insights(42)

    body = resp.get_json()
    sp_keys = set(body['data']['solar_prediction'].keys())
    # Locked: capacity_kwh / reserve_percent / weather_advice etc.
    # must NOT leak.
    forbidden = {
        'capacity_kwh', 'reserve_percent', 'minutes_to_sunset',
        'hours_until_sunrise', 'is_day', 'weather_advice',
        'weather_level', 'level', 'remaining_hours', 'remaining_label',
        'sunrise_time', 'effective_sunrise_time',
        'sunrise_remaining_label',
    }
    assert sp_keys.isdisjoint(forbidden)


def test_route_binds_g_scope_and_restores_after():
    """The smart_engine snapshot save reads `g.current_user/device`
    via `current_scope_ids`. The route binds them for the duration
    of the helper calls (mirroring v50 sync-now's pattern) and
    restores on the way out so unrelated handlers later in the
    request lifecycle don't pick up a stale scope."""
    from app.blueprints.mobile_devices_api import (
        device_insights, AppDevice, Reading,
    )
    from flask import g
    app = _make_app()
    user = _fake_user(id_=7)
    device = _fake_device(id_=99)
    reading = mock.Mock(raw_json='{}', id=99)

    seen_in_helper = {}

    def _capture_scope(*args, **kwargs):
        # When the helper runs, `g.current_user/device` MUST be set.
        seen_in_helper['user'] = getattr(g, 'current_user', None)
        seen_in_helper['device'] = getattr(g, 'current_device', None)
        return _fake_prediction_dict()

    with app.test_request_context('/api/v1/devices/99/insights'), \
         _patch_user(user), \
         mock.patch.object(AppDevice, 'query',
                           _device_query_returning(device)), \
         mock.patch.object(Reading, 'query',
                           _reading_query_returning(reading)), \
         mock.patch(
             'app.blueprints.mobile_devices_api._extract_station_coords',
             return_value=(31.5, 35.1),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.fetch_weather',
             return_value=_fake_weather_snapshot(),
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.load_settings',
             return_value={},
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_pre_sunset_prediction',
             side_effect=_capture_scope,
         ), \
         mock.patch(
             'app.blueprints.mobile_devices_api.build_smart_energy_advice',
             return_value=_fake_advice_dict(),
         ):
        # Pre-condition: g.current_user/device are unset for this
        # request — the route must set + restore them itself.
        assert getattr(g, 'current_user', None) is None
        assert getattr(g, 'current_device', None) is None
        device_insights(99)
        # Post-condition: scope is restored (unset again).
        assert getattr(g, 'current_user', None) is None
        assert getattr(g, 'current_device', None) is None

    # The helper saw THIS user + THIS device during execution.
    assert seen_in_helper['user'] is user
    assert seen_in_helper['device'] is device
