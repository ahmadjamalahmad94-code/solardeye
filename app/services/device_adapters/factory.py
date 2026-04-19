from __future__ import annotations
from .base import DeviceAdapterError
from .deye_adapter import DeyeDeviceAdapter


def get_device_adapter(device=None, global_settings: dict | None = None):
    device_type = ((getattr(device, 'device_type', None) or getattr(device, 'api_provider', None) or 'deye')).strip().lower()
    if device_type == 'deye':
        return DeyeDeviceAdapter(device=device, global_settings=global_settings)
    raise DeviceAdapterError(f"نوع الجهاز غير مدعوم حاليًا: {device_type}")
