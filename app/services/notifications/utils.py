"""Pure utility helpers extracted from blueprints/notifications.py.

These are stateless functions with no DB or Flask context dependencies,
making them the safest to extract. The blueprint re-exports them so
existing `from .notifications import _flag` patterns keep working.
"""
from __future__ import annotations

from datetime import datetime
from flask import current_app


def _flag(settings: dict | None, key: str, default: bool = True) -> bool:
    """Read a boolean flag from a settings dict, treating empty as default."""
    if settings is None:
        return default
    value = settings.get(key)
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {'1', 'true', 'on', 'yes', 'y'}:
        return True
    if text in {'0', 'false', 'off', 'no', 'n'}:
        return False
    return default


def _normalize_telegram_text(value: str | None) -> str:
    """Normalize a Telegram text payload by collapsing escape sequences."""
    text = str(value or '')
    text = text.replace('\r\n', '\n').replace('\\n', '\n').replace('\\t', '\t')
    return text.strip()


def _diag(fmt: str, *args):
    """Best-effort diagnostic logger — never raises."""
    try:
        msg = fmt % args if args else fmt
    except Exception:
        msg = str(fmt)
    try:
        current_app.logger.info('[notify] %s', msg)
    except Exception:
        try:
            print(f'[notify] {msg}', flush=True)
        except Exception:
            pass


def crossed_up(prev_soc: float, current_soc: float, step: int) -> list:
    """Return SoC step thresholds crossed in the upward direction."""
    return [level for level in range(step, 101, step) if prev_soc < level <= current_soc]


def crossed_down(prev_soc: float, current_soc: float, step: int) -> list:
    """Return SoC step thresholds crossed in the downward direction."""
    return [level for level in range(step, 0, -step) if prev_soc > level >= current_soc]


def _parse_hhmm_local(value, now_local):
    """Parse an HH:MM string into a datetime on the given local-day base."""
    try:
        hh, mm = [int(x) for x in str(value or '').split(':')[:2]]
        return now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None


def _weather_day_window(now_local, weather, start_hour=7):
    """Return True if the current local time falls in the daytime window."""
    if not now_local:
        return False
    sunset_dt = _parse_hhmm_local(getattr(weather, 'sunset_time', None), now_local) if weather else None
    day_start = now_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if sunset_dt:
        return day_start <= now_local <= sunset_dt
    return start_hour <= now_local.hour <= 19


def _night_weather_label(now_local, weather):
    """Return a compact night-time weather line."""
    temp = getattr(weather, 'temperature', None)
    return f"🌙 ليلًا الآن • {temp if temp is not None else '--'}°"


def _short_weather_line(now_local, weather):
    """Return a one-line weather string suitable for Telegram preview."""
    if not weather:
        return None
    if not _weather_day_window(now_local, weather, start_hour=7):
        return _night_weather_label(now_local, weather)
    temp = getattr(weather, 'temperature', None)
    cloud = getattr(weather, 'cloud_cover_percent', None)
    parts = []
    if temp is not None:
        parts.append(f"🌡 {temp}°")
    if cloud is not None:
        parts.append(f"☁ {cloud}%")
    return ' • '.join(parts) if parts else None


def _critical_margin_w(settings: dict | None) -> float:
    """Return the configured 'critical' margin in watts (default 100 W)."""
    if not settings:
        return 100.0
    raw = settings.get('sms_critical_margin_w') or settings.get('critical_margin_w') or 100
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 100.0
