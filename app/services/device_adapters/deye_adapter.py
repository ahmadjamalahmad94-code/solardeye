from __future__ import annotations
from .base import BaseDeviceAdapter
from ..deye_client import DeyeClient


class DeyeDeviceAdapter(BaseDeviceAdapter):
    adapter_name = 'deye'

    def fetch_snapshot(self):
        client = DeyeClient(self.build_runtime_settings())
        return client.snapshot()
