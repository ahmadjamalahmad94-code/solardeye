"""v93k — weather slots must not claim solar production at night.

The bug: at 8 PM, with the sun set at 7:30 PM and 1% cloud cover,
the mobile weather screen was showing:
    "الساعة القادمة · 20:00 · مشمس · 21.4°"
    "إنتاج قوي"
    "وقت ممتاز لتشغيل الأجهزة الثقيلة."

All three lines are wrong:
    1. "مشمس" + ☀️ is the wrong label/icon for clear sky at night.
    2. "إنتاج قوي" is impossible after sunset.
    3. The advice tells the user to run heavy appliances — exactly
       what we tell people NOT to do after sunset (battery hours).

Root cause: `solar_rating_from_cloud` and `advice_from_cloud` only
read cloud cover. A clear night sky (1% clouds) scored "إنتاج قوي"
because the function didn't know whether the sun was up.

v93k threads sunrise/sunset through `_slot_from_hourly` + the
hourly timeline, adds a `_is_daylight_dt` predicate, and gives the
two cloud functions an `is_daylight` keyword-only argument that
overrides the cloud-based label with night-appropriate copy.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _import():
    from app.services.weather_service import (
        solar_rating_from_cloud,
        advice_from_cloud,
        _is_daylight_dt,
        _night_decoration,
        _slot_from_hourly,
    )
    return (
        solar_rating_from_cloud, advice_from_cloud, _is_daylight_dt,
        _night_decoration, _slot_from_hourly,
    )


def test_solar_rating_returns_night_label_when_not_daylight():
    rating, *_ = _import()
    # Clear sky (1% clouds) at night must NOT score "إنتاج قوي".
    out = rating(1.0, is_daylight=False)
    assert 'ليلًا' in out or 'لا إنتاج' in out, (
        f'night-time rating must be a night label, got {out!r}'
    )
    assert 'قوي' not in out, (
        'night-time rating must never read "قوي" — there is no sun.'
    )


def test_advice_returns_night_copy_when_not_daylight():
    _, advice, *_ = _import()
    out = advice(1.0, is_daylight=False)
    assert 'الشمس' in out or 'الشروق' in out or 'ليل' in out, (
        f'night-time advice must reference the sun being down, got {out!r}'
    )
    assert 'وقت ممتاز' not in out, (
        'must not tell the user to run heavy appliances at night.'
    )


def test_solar_rating_is_unchanged_at_daylight():
    """Defensive: the new is_daylight kwarg defaults True so all
    existing callers keep their behaviour."""
    rating, *_ = _import()
    assert rating(1.0) == 'إنتاج قوي'
    assert rating(1.0, is_daylight=True) == 'إنتاج قوي'
    assert rating(60.0, is_daylight=True) == 'إنتاج ضعيف'


def test_is_daylight_dt_handles_evening_after_sunset():
    _, _, is_day, *_ = _import()
    # Sunrise at 05:48, sunset at 19:30 (matches the user's screenshot).
    sunrise = datetime(2026, 5, 13, 5, 48)
    sunset = datetime(2026, 5, 13, 19, 30)
    slot_8pm = datetime(2026, 5, 13, 20, 0)
    assert is_day(slot_8pm, sunrise, sunset) is False, (
        '20:00 with 19:30 sunset must be classified as night.'
    )
    slot_noon = datetime(2026, 5, 13, 12, 0)
    assert is_day(slot_noon, sunrise, sunset) is True, (
        '12:00 with 19:30 sunset must be classified as daytime.'
    )
    slot_530am = datetime(2026, 5, 13, 5, 30)
    assert is_day(slot_530am, sunrise, sunset) is False, (
        '05:30 before 05:48 sunrise must be classified as night.'
    )


def test_night_decoration_swaps_sunny_label_and_icon():
    *_, decorate, _ = _import()
    label, cat, ic = decorate('مشمس', 'sunny', '☀️')
    assert label == 'ليلًا'
    assert cat == 'night_clear'
    assert ic == '🌙'


def test_night_decoration_preserves_rain_label():
    """Rain/snow/storm read the same way at night, so we don't override."""
    *_, decorate, _ = _import()
    label, cat, ic = decorate('مطر خفيف', 'rain', '🌧️')
    assert label == 'مطر خفيف'
    assert cat == 'rain'
    assert ic == '🌧️'


def test_slot_from_hourly_honours_sunset_for_evening_hour():
    """End-to-end: `_slot_from_hourly` for 20:00 with sunset at
    19:30 must produce a night-appropriate slot — the exact
    regression the user reported."""
    *_, slot_from_hourly = _import()
    # Build the minimal hourly arrays the helper expects. Indexes
    # are aligned by position; we only need the 20:00 row.
    times = ['2026-05-13T20:00']
    temps = [21.4]
    codes = [0]      # weather code 0 = clear → "مشمس · ☀️" in WEATHER_CODE_MAP
    clouds = [1.0]   # 1% cloud cover — would normally score "إنتاج قوي"
    pops = [0.0]
    sunrise = datetime(2026, 5, 13, 5, 48)
    sunset = datetime(2026, 5, 13, 19, 30)
    slot = slot_from_hourly(
        times, temps, codes, clouds, pops, 20,
        sunrise_dt=sunrise, sunset_dt=sunset,
    )
    assert 'قوي' not in slot['solar_rating'], (
        f'evening slot still claims strong production: {slot}'
    )
    assert 'وقت ممتاز' not in slot['advice'], (
        f'evening slot still tells user to run heavy appliances: {slot}'
    )
    assert slot['icon'] == '🌙', (
        f"evening slot still shows ☀️ icon: {slot['icon']!r}"
    )
    assert slot['condition_ar'] == 'ليلًا', (
        f"evening slot still labelled 'مشمس': {slot['condition_ar']!r}"
    )
