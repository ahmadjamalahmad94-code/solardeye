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


def decode_weather(code: int | None):
    if code is None:
        return ('غير معروف', 'unknown', ICON_MAP['unknown'])
    label, category = WEATHER_CODE_MAP.get(int(code), ('غير معروف', 'unknown'))
    return label, category, ICON_MAP.get(category, ICON_MAP['unknown'])


def solar_rating_from_cloud(cloud_cover: float | None) -> str:
    cloud = float(cloud_cover or 0)
    if cloud < 20:
        return 'إنتاج قوي'
    if cloud < 50:
        return 'إنتاج متوسط'
    if cloud < 80:
        return 'إنتاج ضعيف'
    return 'إنتاج منخفض جدًا'


def advice_from_cloud(cloud_cover: float | None) -> str:
    cloud = float(cloud_cover or 0)
    if cloud < 20:
        return 'وقت ممتاز لتشغيل الأجهزة الثقيلة.'
    if cloud < 50:
        return 'يفضل تخفيف الأحمال الثقيلة.'
    if cloud < 80:
        return 'يفضل تأجيل الأحمال الثقيلة مؤقتًا.'
    return 'تجنب تشغيل الأجهزة الثقيلة حتى يتحسن الشحن.'


def _slot_from_hourly(times, temps, codes, clouds, pops, hour_selector: int):
    for idx, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        if dt.hour == hour_selector:
            label, category, icon = decode_weather(codes[idx] if idx < len(codes) else None)
            cloud = clouds[idx] if idx < len(clouds) else None
            return {
                'time': t,
                'temperature': temps[idx] if idx < len(temps) else None,
                'cloud_cover': cloud,
                'precipitation_probability': pops[idx] if idx < len(pops) else None,
                'condition_ar': label,
                'category': category,
                'icon': icon,
                'solar_rating': solar_rating_from_cloud(cloud),
                'advice': advice_from_cloud(cloud),
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
    r = requests.get(url, params=params, timeout=20)
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
    if sunset_list:
        try:
            sunset_dt = datetime.fromisoformat(sunset_list[0])
            sunset_time = sunset_dt.strftime('%H:%M')
            effective_sunset_time = (sunset_dt.replace(second=0, microsecond=0) - timedelta(hours=1)).strftime('%H:%M')
        except Exception:
            pass
    if sunrise_list:
        try:
            sunrise_dt = datetime.fromisoformat(sunrise_list[0])
            sunrise_time = sunrise_dt.strftime('%H:%M')
            effective_sunrise_time = sunrise_dt.replace(second=0, microsecond=0).strftime('%H:%M')
        except Exception:
            pass

    next_hour = None
    timeline = []
    selected_hours = [8, 10, 12, 14, 16, 18]
    for idx, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except Exception:
            continue
        if next_hour is None and dt > now:
            next_hour = _slot_from_hourly(times, temps, codes, clouds, pops, dt.hour)
        if dt.date() == now.date() and dt.hour in selected_hours:
            label, cat, ic = decode_weather(codes[idx] if idx < len(codes) else None)
            cloud = clouds[idx] if idx < len(clouds) else None
            timeline.append({
                'time_label': dt.strftime('%I:%M').lstrip('0') + (' ص' if dt.hour < 12 else ' م'),
                'temperature': temps[idx] if idx < len(temps) else None,
                'cloud_cover': cloud,
                'precipitation_probability': pops[idx] if idx < len(pops) else None,
                'condition_ar': label,
                'category': cat,
                'icon': ic,
                'solar_rating': solar_rating_from_cloud(cloud),
                'advice': advice_from_cloud(cloud),
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
        morning=_slot_from_hourly(times, temps, codes, clouds, pops, 9),
        noon=_slot_from_hourly(times, temps, codes, clouds, pops, 12),
        afternoon=_slot_from_hourly(times, temps, codes, clouds, pops, 15),
        next_hour=next_hour,
        sunset_time=sunset_time,
        effective_sunset_time=effective_sunset_time,
        sunrise_time=sunrise_time,
        effective_sunrise_time=effective_sunrise_time,
        timeline=timeline,
    )
