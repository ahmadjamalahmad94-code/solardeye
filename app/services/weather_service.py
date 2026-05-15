from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import requests

WEATHER_CODE_MAP = {
    0: ('مشمس', 'sunny'),
    1: ('غائم جزئيًا', 'partly_cloudy'),
    2: ('غائم جزئيًا', 'partly_cloudy'),
    3: ('غائم', 'cloudy'),
    45: ('ضباب', 'fog'),
    48: ('ضباب', 'fog'),
    51: ('رذاذ خفيف', 'rain'),
    53: ('رذاذ', 'rain'),
    55: ('رذاذ كثيف', 'rain'),
    61: ('مطر خفيف', 'rain'),
    63: ('مطر', 'rain'),
    65: ('مطر غزير', 'rain'),
    71: ('ثلج خفيف', 'snow'),
    73: ('ثلج', 'snow'),
    75: ('ثلج كثيف', 'snow'),
    80: ('زخات خفيفة', 'rain'),
    81: ('زخات', 'rain'),
    82: ('زخات غزيرة', 'rain'),
    95: ('عاصفة رعدية', 'storm'),
    96: ('عاصفة وبرد خفيف', 'storm'),
    99: ('عاصفة وبرد', 'storm'),
}

ICON_MAP = {
    'sunny': '☀️',
    'partly_cloudy': '⛅',
    'cloudy': '☁️',
    'rain': '🌧️',
    'fog': '🌫️',
    'snow': '❄️',
    'storm': '⛈️',
    'unknown': '🌤️',
}

@dataclass
class WeatherSnapshot:
    temperature: float | None
    wind_speed: float | None
    cloud_cover: float | None
    precipitation_probability: float | None
    code: int | None
    condition_ar: str
    category: str
    icon: str
    current_time: str | None
    morning: dict
    noon: dict
    afternoon: dict
    next_hour: dict
    sunset_time: str | None
    effective_sunset_time: str | None
    sunrise_time: str | None
    effective_sunrise_time: str | None
    timeline: list[dict] = field(default_factory=list)
    # v102d — which day the `timeline` covers. After today's
    # sunset we switch to tomorrow's sunrise→sunset window so the
    # chart stays useful at night ("شو هيكون الوضع بالغد").
    # Values: 'today' | 'tomorrow'.
    timeline_for_day: str = 'today'


def decode_weather(code: int | None):
    if code is None:
        return ('غير معروف', 'unknown', ICON_MAP['unknown'])
    label, category = WEATHER_CODE_MAP.get(int(code), ('غير معروف', 'unknown'))
    return label, category, ICON_MAP.get(category, ICON_MAP['unknown'])


def solar_rating_from_cloud(cloud_cover: float | None, *, is_daylight: bool = True) -> str:
    """Map cloud cover → Arabic solar production rating.

    v93k — `is_daylight=False` overrides cloud-based rating with a
    night-appropriate label. Without this guard, a clear night sky
    (cloud_cover≈1%) was scoring "إنتاج قوي" — which is nonsense
    when the sun is below the horizon.
    """
    if not is_daylight:
        return 'لا إنتاج · ليلًا'
    cloud = float(cloud_cover or 0)
    if cloud < 20:
        return 'إنتاج قوي'
    if cloud < 50:
        return 'إنتاج متوسط'
    if cloud < 80:
        return 'إنتاج ضعيف'
    return 'إنتاج منخفض جدًا'


def advice_from_cloud(cloud_cover: float | None, *, is_daylight: bool = True) -> str:
    """Map cloud cover → Arabic actionable advice.

    v93k — `is_daylight=False` overrides cloud-based advice with a
    night-appropriate copy so we never tell the user "وقت ممتاز
    لتشغيل الأجهزة الثقيلة" at 8 PM with the sun below the horizon.
    """
    if not is_daylight:
        return 'الشمس غاربة — لا يوجد إنتاج شمسي حتى الشروق.'
    cloud = float(cloud_cover or 0)
    if cloud < 20:
        return 'وقت ممتاز لتشغيل الأجهزة الثقيلة.'
    if cloud < 50:
        return 'يفضل تخفيف الأحمال الثقيلة.'
    if cloud < 80:
        return 'يفضل تأجيل الأحمال الثقيلة مؤقتًا.'
    return 'تجنب تشغيل الأجهزة الثقيلة حتى يتحسن الشحن.'


def _night_decoration(condition_ar: str, category: str, icon: str) -> tuple[str, str, str]:
    """v93k — When a slot is after sunset / before sunrise, the
    Open-Meteo weather_code may still return `0` (clear), which the
    WEATHER_CODE_MAP labels as "مشمس" with a ☀️ icon — wrong at
    night. We swap to a night-aware label/icon only for the bright
    categories (`sunny`, `partly_cloudy`); other categories
    (rain/snow/fog/storm) keep their natural label since they read
    the same way day or night.
    """
    if category == 'sunny':
        return ('ليلًا', 'night_clear', '🌙')
    if category == 'partly_cloudy':
        return ('ليلًا · غائم جزئيًا', 'night_partly_cloudy', '☁️')
    return (condition_ar, category, icon)


def _is_daylight_dt(slot_dt: datetime, sunrise_dt: datetime | None, sunset_dt: datetime | None) -> bool:
    """v93k — return whether `slot_dt` falls inside the daylight
    window. We use the natural sunrise + sunset (not effective_*)
    because the consumer-facing rating should match the visible
    sun position, not the production-efficiency curve. A slot
    exactly at sunset still counts as night (sun has set)."""
    if sunrise_dt is None or sunset_dt is None:
        # Conservative fallback: anything strictly between 06:00 and
        # 18:00 is daylight if we have no real sunrise/sunset data.
        return 6 <= slot_dt.hour < 18
    # Compare in the slot's own day. Open-Meteo sometimes gives a
    # sunrise/sunset of a different date than the slot when timezones
    # are weird; we project sunrise/sunset onto the slot's date.
    try:
        sr = slot_dt.replace(hour=sunrise_dt.hour, minute=sunrise_dt.minute, second=0, microsecond=0)
        ss = slot_dt.replace(hour=sunset_dt.hour, minute=sunset_dt.minute, second=0, microsecond=0)
    except Exception:
        return 6 <= slot_dt.hour < 18
    return sr <= slot_dt < ss


def _slot_from_hourly(times, temps, codes, clouds, pops, hour_selector: int, *, sunrise_dt=None, sunset_dt=None):
    for idx, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        if dt.hour == hour_selector:
            label, category, icon = decode_weather(codes[idx] if idx < len(codes) else None)
            cloud = clouds[idx] if idx < len(clouds) else None
            is_day = _is_daylight_dt(dt, sunrise_dt, sunset_dt)
            # v93k — replace "مشمس · ☀️" with "ليلًا · 🌙" for clear
            # post-sunset hours so the next-hour card doesn't claim
            # the sun is shining at 8 PM.
            if not is_day:
                label, category, icon = _night_decoration(label, category, icon)
            return {
                'time': t,
                'temperature': temps[idx] if idx < len(temps) else None,
                'cloud_cover': cloud,
                'precipitation_probability': pops[idx] if idx < len(pops) else None,
                'condition_ar': label,
                'category': category,
                'icon': icon,
                'solar_rating': solar_rating_from_cloud(cloud, is_daylight=is_day),
                'advice': advice_from_cloud(cloud, is_daylight=is_day),
            }
    return {
        'time': None, 'temperature': None, 'cloud_cover': None,
        'precipitation_probability': None, 'condition_ar': 'غير متاح',
        'category': 'unknown', 'icon': ICON_MAP['unknown'],
        'solar_rating': 'غير متاح', 'advice': 'لا تتوفر بيانات كافية.'
    }


def fetch_weather(lat: float, lng: float, timezone: str = 'Asia/Hebron') -> WeatherSnapshot:
    url = 'https://api.open-meteo.com/v1/forecast'
    params = {
        'latitude': lat,
        'longitude': lng,
        'current': 'temperature_2m,weather_code,cloud_cover,wind_speed_10m',
        'hourly': 'temperature_2m,weather_code,cloud_cover,precipitation_probability',
        'daily': 'sunrise,sunset',
        'forecast_days': 2,
        'timezone': timezone,
    }
    # v102d-fix — every Open-Meteo call (success or failure) ticks the
    # quota monitor so subscribers get a heads-up notification when
    # we approach / hit the daily ceiling. HTTP 429 (or anything 5xx
    # accompanied by the rate-limit error string Open-Meteo returns)
    # is treated as `exhausted=True` so the 100% notification fires
    # immediately even when our local counter is below the cap (the
    # limit is shared across whoever else is calling the same IP).
    try:
        r = requests.get(url, params=params, timeout=20)
    except Exception:
        try:
            from .api_quota_monitor import API_OPEN_METEO, record_call
            record_call(API_OPEN_METEO, success=False)
        except Exception:
            pass
        raise
    try:
        from .api_quota_monitor import API_OPEN_METEO, record_call
        is_429 = r.status_code == 429
        record_call(API_OPEN_METEO, success=r.ok, exhausted=is_429)
    except Exception:
        pass
    r.raise_for_status()
    data = r.json()

    current = data.get('current', {}) or {}
    hourly = data.get('hourly', {}) or {}
    times = hourly.get('time', []) or []
    temps = hourly.get('temperature_2m', []) or []
    codes = hourly.get('weather_code', []) or []
    clouds = hourly.get('cloud_cover', []) or []
    pops = hourly.get('precipitation_probability', []) or []

    condition_ar, category, icon = decode_weather(current.get('weather_code'))
    now = datetime.fromisoformat(current['time']) if current.get('time') else datetime.now(UTC)

    daily = data.get('daily', {}) or {}
    sunset_list = daily.get('sunset', []) or []
    sunrise_list = daily.get('sunrise', []) or []
    sunset_time = None
    effective_sunset_time = None
    sunrise_time = None
    effective_sunrise_time = None
    # v93k — keep the parsed datetimes around so the slot/timeline
    # builders can ask `is this hour daylight?` before claiming
    # "إنتاج قوي" at 8 PM.
    sunset_dt = None
    sunrise_dt = None
    if sunset_list:
        try:
            sunset_dt = datetime.fromisoformat(sunset_list[0])
            sunset_time = sunset_dt.strftime('%H:%M')
            effective_sunset_time = (sunset_dt.replace(second=0, microsecond=0) - timedelta(hours=1)).strftime('%H:%M')
        except Exception:
            sunset_dt = None
    if sunrise_list:
        try:
            sunrise_dt = datetime.fromisoformat(sunrise_list[0])
            sunrise_time = sunrise_dt.strftime('%H:%M')
            effective_sunrise_time = sunrise_dt.replace(second=0, microsecond=0).strftime('%H:%M')
        except Exception:
            sunrise_dt = None

    # v102d — sunrise/sunset for tomorrow (index 1 of the 2-day
    # forecast) so the timeline can roll forward after sunset.
    tomorrow_sunset_dt = None
    tomorrow_sunrise_dt = None
    if len(sunset_list) > 1:
        try:
            tomorrow_sunset_dt = datetime.fromisoformat(sunset_list[1])
        except Exception:
            tomorrow_sunset_dt = None
    if len(sunrise_list) > 1:
        try:
            tomorrow_sunrise_dt = datetime.fromisoformat(sunrise_list[1])
        except Exception:
            tomorrow_sunrise_dt = None

    # Pick which day's sunrise→sunset window the timeline should
    # cover. Past today's sunset (and we have tomorrow's data),
    # show tomorrow; otherwise show today.
    past_sunset_today = sunset_dt is not None and now >= sunset_dt
    if past_sunset_today and tomorrow_sunrise_dt is not None and tomorrow_sunset_dt is not None:
        timeline_for_day = 'tomorrow'
        target_sunrise_dt = tomorrow_sunrise_dt
        target_sunset_dt = tomorrow_sunset_dt
    else:
        timeline_for_day = 'today'
        target_sunrise_dt = sunrise_dt
        target_sunset_dt = sunset_dt

    next_hour = None
    timeline = []
    # v102d — full daylight arc instead of the old fixed 6-hour
    # window. Hours that fall between the target day's sunrise and
    # sunset (inclusive on both ends, rounded to the hour mark).
    if target_sunrise_dt is not None and target_sunset_dt is not None:
        target_date = target_sunrise_dt.date()
        hour_start = target_sunrise_dt.hour
        hour_end = target_sunset_dt.hour
    else:
        # Fallback: keep the legacy 6 fixed hours so the screen
        # never empties when sunrise/sunset are missing.
        target_date = now.date()
        hour_start = 8
        hour_end = 18

    # Use today's sunrise/sunset for the daylight check on entries
    # the timeline includes (since `_is_daylight_dt` operates on
    # absolute datetimes, today vs tomorrow doesn't matter — the
    # same target dt has the right window picked from the dt's
    # own day).
    for idx, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        if next_hour is None and dt > now:
            next_hour = _slot_from_hourly(
                times, temps, codes, clouds, pops, dt.hour,
                sunrise_dt=sunrise_dt, sunset_dt=sunset_dt,
            )
        if dt.date() == target_date and hour_start <= dt.hour <= hour_end:
            label, cat, ic = decode_weather(codes[idx] if idx < len(codes) else None)
            cloud = clouds[idx] if idx < len(clouds) else None
            is_day = _is_daylight_dt(
                dt,
                target_sunrise_dt or sunrise_dt,
                target_sunset_dt or sunset_dt,
            )
            # v93k — night-decorate clear/partly-cloudy categories
            # so a 6 PM slot after a 5:48 PM sunset doesn't read
            # "مشمس · ☀️".
            if not is_day:
                label, cat, ic = _night_decoration(label, cat, ic)
            timeline.append({
                'time_label': dt.strftime('%I:%M').lstrip('0') + (' ص' if dt.hour < 12 else ' م'),
                'temperature': temps[idx] if idx < len(temps) else None,
                'cloud_cover': cloud,
                'precipitation_probability': pops[idx] if idx < len(pops) else None,
                'condition_ar': label,
                'category': cat,
                'icon': ic,
                'solar_rating': solar_rating_from_cloud(cloud, is_daylight=is_day),
                'advice': advice_from_cloud(cloud, is_daylight=is_day),
            })
    if next_hour is None:
        next_hour = {'time': None, 'temperature': None, 'cloud_cover': None, 'precipitation_probability': None, 'condition_ar': 'غير متاح', 'category': 'unknown', 'icon': ICON_MAP['unknown'], 'solar_rating': 'غير متاح', 'advice': 'لا توجد بيانات.'}

    return WeatherSnapshot(
        temperature=current.get('temperature_2m'),
        wind_speed=current.get('wind_speed_10m'),
        cloud_cover=current.get('cloud_cover'),
        precipitation_probability=next_hour.get('precipitation_probability'),
        code=current.get('weather_code'),
        condition_ar=condition_ar,
        category=category,
        icon=icon,
        current_time=current.get('time'),
        # v93k — pass sunrise/sunset so morning/noon/afternoon slots
        # don't accidentally fall outside the daylight window if the
        # user is in a polar timezone with weird daily cycles.
        morning=_slot_from_hourly(times, temps, codes, clouds, pops, 9, sunrise_dt=sunrise_dt, sunset_dt=sunset_dt),
        noon=_slot_from_hourly(times, temps, codes, clouds, pops, 12, sunrise_dt=sunrise_dt, sunset_dt=sunset_dt),
        afternoon=_slot_from_hourly(times, temps, codes, clouds, pops, 15, sunrise_dt=sunrise_dt, sunset_dt=sunset_dt),
        next_hour=next_hour,
        sunset_time=sunset_time,
        effective_sunset_time=effective_sunset_time,
        sunrise_time=sunrise_time,
        effective_sunrise_time=effective_sunrise_time,
        timeline=timeline,
        timeline_for_day=timeline_for_day,
    )
