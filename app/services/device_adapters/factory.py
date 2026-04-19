from .deye_adapter import DeyeDeviceAdapter


def get_adapter(device_type='deye', device=None):
    normalized = (device_type or 'deye').strip().lower()
    if normalized == 'deye':
        return DeyeDeviceAdapter(device=device)
    return DeyeDeviceAdapter(device=device)
