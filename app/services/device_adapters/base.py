from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeviceSnapshot:
    plant_id: str = ''
    plant_name: str = ''
    solar_power: float = 0.0
    home_load: float = 0.0
    battery_soc: float = 0.0
    battery_power: float = 0.0
    grid_power: float = 0.0
    inverter_power: float = 0.0
    daily_production: float = 0.0
    monthly_production: float = 0.0
    total_production: float = 0.0
    status_text: str = 'unknown'
    raw: dict[str, Any] = field(default_factory=dict)


class BaseDeviceAdapter:
    device_type = 'base'

    def __init__(self, device=None):
        self.device = device

    def fetch_latest(self) -> DeviceSnapshot:
        raise NotImplementedError('fetch_latest must be implemented by device adapters')
