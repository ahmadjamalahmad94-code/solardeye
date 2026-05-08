"""v33-α three-device fixture builder.

Used by tests/test_v33_alpha.py. Creates a deterministic 3-device
shape that exercises every code path in the fan-out wrapper:

    user A  qa.alpha.three  id=901
      A1  Roof      provider=deye      account=(app1, email1)   tz=Asia/Hebron
      A2  Workshop  provider=deye      account=(app1, email1)   tz=Asia/Riyadh
      A3  Farm      provider=solarman  account=(token9003)      tz=Asia/Hebron

A1 and A2 share a Deye account → expect ONE provider-group when
fan-out is invoked. A3 is its own group.

This module DOES NOT touch the production database. It returns plain
Python AppDevice-like objects that the unit tests can substitute via
monkeypatching `AppDevice.query`. Integration tests that need a real
DB build their own session via ``conftest_sqlite`` (in conftest.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FakeAppDevice:
    """Stand-in for AppDevice. Exposes the same attributes the
    fan-out code reads, without touching SQLAlchemy."""
    id: int
    owner_user_id: int
    name: str
    api_provider: str
    device_type: str
    timezone: str
    is_active: bool = True
    credentials_json: str = ''
    settings_json: str = ''
    connection_status: str = 'ok'
    last_connected_at: Any = None
    plant_name: str = ''
    station_id: str = ''
    external_device_id: str = ''


@dataclass
class FakeAppUser:
    id: int
    username: str
    role: str = 'user'
    is_admin: bool = False
    is_active: bool = True
    preferred_device_id: int | None = None


def build_fixture():
    """Return (user, devices) tuple for the standard 3-device shape."""
    user = FakeAppUser(id=901, username='qa.alpha.three',
                       preferred_device_id=9001)
    a1 = FakeAppDevice(
        id=9001, owner_user_id=901, name='Roof',
        api_provider='deye', device_type='deye', timezone='Asia/Hebron',
        credentials_json='{"deye_app_id":"app1","deye_email":"shared@example.test"}',
        plant_name='Plant A1', station_id='ST-1',
    )
    a2 = FakeAppDevice(
        id=9002, owner_user_id=901, name='Workshop',
        api_provider='deye', device_type='deye', timezone='Asia/Riyadh',
        credentials_json='{"deye_app_id":"app1","deye_email":"shared@example.test"}',
        plant_name='Plant A2', station_id='ST-2',
    )
    a3 = FakeAppDevice(
        id=9003, owner_user_id=901, name='Farm',
        api_provider='solarman', device_type='solarman', timezone='Asia/Hebron',
        credentials_json='{"solarman_token":"token9003"}',
        plant_name='Plant A3', station_id='ST-3',
    )
    return user, [a1, a2, a3]
