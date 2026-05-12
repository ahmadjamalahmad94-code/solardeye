"""Notification subsystem — split from blueprints/notifications.py.

This package groups the pure-helper utilities that used to live in
blueprints/notifications.py. The blueprint file remains as a facade
that re-exports everything for backward compat with `from .notifications
import X` patterns scattered across the codebase.

v43 added :mod:`mobile_mirror` to persist already-decided energy /
load / solar / weather Telegram dispatches into the mobile
Notification Center (``NotificationEvent``).
"""
from .mobile_mirror import (
    DEFAULT_EVENT_TYPE,
    ENERGY_SOURCE_TYPE,
    event_type_for_dispatch_key,
    event_type_for_scheduled,
    mirror_energy_notification_to_center,
)
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
    # v43: mobile mirror surface
    'DEFAULT_EVENT_TYPE',
    'ENERGY_SOURCE_TYPE',
    'event_type_for_dispatch_key',
    'event_type_for_scheduled',
    'mirror_energy_notification_to_center',
]
