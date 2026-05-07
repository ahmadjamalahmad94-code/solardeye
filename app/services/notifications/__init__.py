"""Notification subsystem — split from blueprints/notifications.py.

This package groups the pure-helper utilities that used to live in
blueprints/notifications.py. The blueprint file remains as a facade
that re-exports everything for backward compat with `from .notifications
import X` patterns scattered across the codebase.
"""
from .utils import (
    crossed_down,
    crossed_up,
    _critical_margin_w,
    _diag,
    _flag,
    _night_weather_label,
    _normalize_telegram_text,
    _parse_hhmm_local,
    _short_weather_line,
    _weather_day_window,
)

__all__ = [
    'crossed_down',
    'crossed_up',
    '_critical_margin_w',
    '_diag',
    '_flag',
    '_night_weather_label',
    '_normalize_telegram_text',
    '_parse_hhmm_local',
    '_short_weather_line',
    '_weather_day_window',
]
