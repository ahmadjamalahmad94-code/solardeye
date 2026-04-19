
class BaseDeviceAdapter:
    device_type = 'base'

    def __init__(self, device=None):
        self.device = device

    def fetch_reading(self, *args, **kwargs):
        raise NotImplementedError
