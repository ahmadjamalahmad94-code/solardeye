import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def to_json(data) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return '{}'


def flatten_items(data, parent_key=''):
    items = {}
    if isinstance(data, Mapping):
        for key, value in data.items():
            new_key = f'{parent_key}.{key}' if parent_key else str(key)
            items.update(flatten_items(value, new_key))
    elif isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        for idx, value in enumerate(data):
            new_key = f'{parent_key}[{idx}]' if parent_key else f'[{idx}]'
            items.update(flatten_items(value, new_key))
    else:
        items[parent_key] = data
    return items


def first_match(data, aliases, default=None):
    flat = flatten_items(data)
    alias_set = [a.lower() for a in aliases]
    for key, value in flat.items():
        low = key.lower()
        for alias in alias_set:
            if low.endswith(alias) or f'.{alias}' in low or low == alias:
                if value is not None and value != '':
                    return value
    return default


def safe_float(value, default=0.0):
    try:
        if isinstance(value, str):
            value = value.replace(',', '').strip()
        return float(value)
    except Exception:
        return default


def _extract_number_and_unit(value: str):
    text = str(value).strip().replace(',', '')
    match = re.search(r'([-+]?\d+(?:\.\d+)?)\s*([a-zA-Z%]+)?', text)
    if not match:
        return None, ''
    return float(match.group(1)), (match.group(2) or '').lower()


def safe_power_w(value, default=0.0):
    try:
        if isinstance(value, (int, float)):
            return float(value)
        num, unit = _extract_number_and_unit(str(value))
        if num is None:
            return default
        if unit == 'kw':
            return num * 1000
        if unit == 'mw':
            return num * 1_000_000
        return num
    except Exception:
        return default


def safe_energy_kwh(value, default=0.0):
    try:
        if isinstance(value, (int, float)):
            return float(value)
        num, unit = _extract_number_and_unit(str(value))
        if num is None:
            return default
        if unit == 'mwh':
            return num * 1000
        if unit == 'wh':
            return num / 1000
        return num
    except Exception:
        return default


def best_value_by_keywords(data, include_keywords, exclude_keywords=None, parser=safe_float, default=0.0):
    include_keywords = [k.lower() for k in include_keywords]
    exclude_keywords = [k.lower() for k in (exclude_keywords or [])]
    flat = flatten_items(data)
    for key, value in flat.items():
        low = key.lower()
        if all(k in low for k in include_keywords) and not any(k in low for k in exclude_keywords):
            parsed = parser(value, default)
            if parsed not in (None, default):
                return parsed
    return default


def possible_station_lists(data):
    results = []
    if isinstance(data, list):
        if data and all(isinstance(item, Mapping) for item in data):
            results.append(data)
        for item in data:
            results.extend(possible_station_lists(item))
    elif isinstance(data, Mapping):
        for value in data.values():
            results.extend(possible_station_lists(value))
    return results


def choose_best_station_list(data):
    candidates = possible_station_lists(data)
    if not candidates:
        return []
    def score(lst):
        top = lst[0] if lst and isinstance(lst[0], Mapping) else {}
        keys = ' '.join(str(k).lower() for k in top.keys())
        s = 0
        for word in ['station', 'plant', 'name', 'power', 'day', 'month', 'total']:
            if word in keys:
                s += 1
        return (s, len(lst))
    return sorted(candidates, key=score, reverse=True)[0]


def utc_to_local(dt: datetime | None, tz_name: str = 'Asia/Hebron') -> datetime | None:
    if not dt:
        return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        try:
            tz = ZoneInfo('Asia/Hebron')
        except Exception:
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def _arabic_ampm(dt: datetime) -> str:
    return 'صباحًا' if dt.strftime('%p') == 'AM' else 'مساءً'

def format_local_time_12h(dt: datetime | None, tz_name: str = 'Asia/Hebron', with_seconds: bool = False) -> str:
    local = utc_to_local(dt, tz_name)
    if not local:
        return 'لا يوجد'
    fmt = '%I:%M:%S' if with_seconds else '%I:%M'
    return f"{local.strftime(fmt)} {_arabic_ampm(local)}"

def format_local_datetime(dt: datetime | None, tz_name: str = 'Asia/Hebron') -> str:
    local = utc_to_local(dt, tz_name)
    if not local:
        return 'لا يوجد'
    return f"{local.strftime('%Y-%m-%d %I:%M:%S')} {_arabic_ampm(local)}"


def human_duration_hours(hours: float | None) -> str:
    if hours is None or math.isinf(hours) or math.isnan(hours):
        return 'غير متاح'
    if hours < 0:
        return 'غير متاح'
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    if h <= 0:
        return f'{m} دقيقة'
    if m == 0:
        return f'{h} ساعة'
    return f'{h} ساعة و {m} دقيقة'


def search_battery_metrics(data: dict) -> dict:
    flat = flatten_items(data)
    found = {}
    rules = {
        'battery_voltage': (['battery', 'volt'], ['pv', 'grid']),
        'battery_current': (['battery', 'current'], ['pv', 'grid']),
        'battery_temp': (['battery', 'temp'], ['ambient', 'room']),
        'battery_cycles': (['cycle'], []),
        'battery_soh': (['soh'], []),
        'battery_status': (['battery', 'status'], []),
        'battery_health': (['battery', 'health'], []),
        'battery_total_capacity_ah': (['total', 'capacity'], []),
        'battery_type': (['device', 'type'], []),
    }
    for key, value in flat.items():
        low = key.lower()
        for target, (must_have, must_not) in rules.items():
            if all(word in low for word in must_have) and not any(word in low for word in must_not):
                found[target] = value
    return found


def extract_device_detail_metrics(raw: dict) -> dict:
    """
    Extract rich device metrics from the 'device_detail' key in raw_json.
    These come from the /device/originalData endpoint.
    Returns a flat dict with standardized keys.
    """
    device = raw.get('device_detail', {}) if isinstance(raw, dict) else {}
    if not device:
        return {}

    result = {}
    flat = flatten_items(device)

    def _get(*keys, cast=float, default=None):
        for k in keys:
            v = flat.get(k)
            if v is None:
                # try case-insensitive
                kl = k.lower()
                for fk, fv in flat.items():
                    if fk.lower() == kl and fv is not None and fv != '':
                        v = fv
                        break
            if v is not None and v != '':
                try:
                    return cast(v)
                except Exception:
                    pass
        return default

    # PV strings
    for i in range(1, 5):
        v = _get(f'PV{i}_V', f'pv{i}Voltage', f'PV{i}Volt')
        c = _get(f'PV{i}_I', f'pv{i}Current', f'PV{i}Curr')
        p = _get(f'PV{i}_P', f'pv{i}Power')
        if v is not None: result[f'pv{i}_voltage'] = v
        if c is not None: result[f'pv{i}_current'] = c
        if p is None and v and c: p = round(v * c, 1)
        if p is not None: result[f'pv{i}_power'] = p

    # Grid
    result['grid_voltage_l1'] = _get('G_V_L1', 'gridVoltageL1', 'gridV1', 'acVoltageL1')
    result['grid_voltage_l2'] = _get('G_V_L2', 'gridVoltageL2', 'gridV2', 'acVoltageL2')
    result['grid_voltage_l3'] = _get('G_V_L3', 'gridVoltageL3', 'gridV3', 'acVoltageL3')
    result['grid_current_l1'] = _get('G_I_L1', 'gridCurrentL1', 'gridI1')
    result['grid_frequency'] = _get('G_F', 'gridFrequency', 'gridFreq', 'frequency', 'F_AC')
    result['ac_output_power'] = _get('AC_P_T', 'acOutputPower', 'acPower', 'activePower')

    # Temperatures
    result['inverter_temp'] = _get('INV_T', 'inverterTemperature', 'inverterTemp', 'acTemp')
    result['dc_temp'] = _get('DC_T', 'dcTemperature', 'dcTemp')

    # Battery BMS
    result['battery_voltage'] = _get('BMS_V', 'bmsVoltage', 'batteryVoltage', 'BatVolt')
    result['battery_current'] = _get('BMS_I', 'bmsCurrent', 'batteryCurrent', 'BatCurr')
    result['battery_temp'] = _get('BMS_T', 'bmsTemp', 'batteryTemp', 'BatTemp')
    result['battery_soc_bms'] = _get('BMS_SOC', 'bmsSoc')
    result['battery_soh'] = _get('BMS_SOH', 'bmsSoh', 'batteryHealth', 'batterySOH')
    result['battery_cycles'] = _get('BMS_CYCLE', 'bmsCycles', 'batteryCycles', 'cycles', cast=int)
    result['battery_capacity_ah'] = _get('BMS_CAP', 'bmsCapacity', 'batteryCapacityAh', 'totalCapacity')

    # Remove None values
    return {k: v for k, v in result.items() if v is not None}
