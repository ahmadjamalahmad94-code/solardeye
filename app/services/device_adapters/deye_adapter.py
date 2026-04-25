from __future__ import annotations

from .base import BaseDeviceAdapter, DeviceSnapshot
from ..deye_client import DeyeClient


class DeyeDeviceAdapter(BaseDeviceAdapter):
    device_type = 'deye'

    def __init__(self, device=None, settings=None):
        super().__init__(device=device)
        self.settings = settings or {}

    def fetch_latest(self) -> DeviceSnapshot:
        snap = DeyeClient(self.settings).snapshot()
        return DeviceSnapshot(
            plant_id=snap.plant_id,
            plant_name=snap.plant_name,
            solar_power=snap.solar_power,
            home_load=snap.home_load,
            battery_soc=snap.battery_soc,
            battery_power=snap.battery_power,
            grid_power=snap.grid_power,
            inverter_power=snap.inverter_power,
            daily_production=snap.daily_production,
            monthly_production=snap.monthly_production,
            total_production=snap.total_production,
            status_text=snap.status_text,
            raw=snap.raw,
        )
