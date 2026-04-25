from __future__ import annotations

from .deye_adapter import DeyeDeviceAdapter
from .http_adapter import UniversalHttpDeviceAdapter


def get_adapter(device_type='deye', device=None, settings=None):
    normalized = (device_type or getattr(device, 'api_provider', None) or getattr(device, 'device_type', None) or 'deye').strip().lower()
    if normalized == 'deye':
        return DeyeDeviceAdapter(device=device, settings=settings or {})
    return UniversalHttpDeviceAdapter(device=device)
