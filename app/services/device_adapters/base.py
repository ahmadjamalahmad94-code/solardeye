class BaseDeviceAdapter:
    device_type = 'base'

    def __init__(self, device=None):
        self.device = device

    def fetch_latest(self):
        raise NotImplementedError('fetch_latest must be implemented by device adapters')
