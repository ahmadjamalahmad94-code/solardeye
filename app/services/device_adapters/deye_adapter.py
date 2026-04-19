
from .base import BaseDeviceAdapter


class DeyeAdapter(BaseDeviceAdapter):
    device_type = 'deye'

    def fetch_reading(self, *args, **kwargs):
        # Foundation-safe placeholder. Runtime logic still uses the current
        # stable Deye path until the next multi-user phase.
        return None
