from __future__ import annotations
import json
from typing import Any


class DeviceAdapterError(Exception):
    pass


class BaseDeviceAdapter:
    adapter_name = 'base'

    def __init__(self, device=None, global_settings: dict | None = None):
        self.device = device
        self.global_settings = global_settings or {}

    def credentials_dict(self) -> dict[str, Any]:
        try:
            return json.loads(self.device.credentials_json or '{}') if self.device else {}
        except Exception:
            return {}

    def settings_dict(self) -> dict[str, Any]:
        try:
            return json.loads(self.device.settings_json or '{}') if self.device else {}
        except Exception:
            return {}

    def build_runtime_settings(self) -> dict[str, Any]:
        merged = dict(self.global_settings or {})
        merged.update(self.settings_dict())
        merged.update(self.credentials_dict())
        if self.device:
            if getattr(self.device, 'station_id', None):
                merged.setdefault('deye_plant_id', self.device.station_id)
            if getattr(self.device, 'external_device_id', None):
                merged.setdefault('deye_device_sn', self.device.external_device_id)
            if getattr(self.device, 'plant_name', None):
                merged.setdefault('deye_plant_name', self.device.plant_name)
            if getattr(self.device, 'api_base_url', None):
                merged.setdefault('api_base_url', self.device.api_base_url)
        return merged

    def fetch_snapshot(self):
        raise NotImplementedError
