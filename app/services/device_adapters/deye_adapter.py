from .base import BaseDeviceAdapter


class DeyeDeviceAdapter(BaseDeviceAdapter):
    device_type = 'deye'

    def fetch_latest(self):
        return None
