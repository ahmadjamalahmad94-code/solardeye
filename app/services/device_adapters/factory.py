
from .deye_adapter import DeyeAdapter


def get_adapter(device_type: str):
    device_type = (device_type or 'deye').strip().lower()
    if device_type == 'deye':
        return DeyeAdapter
    return DeyeAdapter
