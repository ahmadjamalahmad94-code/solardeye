"""
Deye Cloud OpenAPI v1 — Personal Account Client

Working endpoints confirmed:
  POST /account/token
  POST /account/info  
  POST /station/list
  POST /station/latest      → realtime power + SOC (no production totals)
  POST /device/latest       → FULL data: PV, battery, temperatures, production totals
  POST /device/measurePoints
  POST /station/device      → device list with deviceId
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import requests
from flask import current_app
from .utils import sha256_hex, safe_float, choose_best_station_list


class DeyeAPIError(Exception):
    pass


# Translation maps for API English values → Arabic
_INVERTER_STATUS = {
    'grid connected': 'متصل بالشبكة',
    'off grid': 'منفصل عن الشبكة',
    'standby': 'وضع الانتظار',
    'fault': 'خطأ في الجهاز',
    'normal': 'يعمل بشكل طبيعي',
}
_BATTERY_STATUS = {
    'charging': 'يتم الشحن',
    'discharging': 'يتم التفريغ',
    'standby': 'ثابتة',
    'idle': 'ثابتة',
    'full': 'مشحونة بالكامل',
}
_GRID_STATUS = {
    'static': 'مفصول',
    'normal': 'متصل',
    'lost': 'مقطوع',
    'fault': 'خطأ',
}
_CONNECTION_STATUS = {
    'normal': 'متصل',
    'offline': 'غير متصل',
    'fault': 'خطأ',
}

def _tr_inv(val: str) -> str:
    return _INVERTER_STATUS.get(val.lower().strip(), val)

def _tr_bat(val: str) -> str:
    return _BATTERY_STATUS.get(val.lower().strip(), val)

def _tr_conn(val: str) -> str:
    k = val.lower().strip()
    return _CONNECTION_STATUS.get(k, _INVERTER_STATUS.get(k, val))


@dataclass
class DeyeSnapshot:
    plant_id: str
    plant_name: str
    status_text: str
    solar_power: float
    home_load: float
    battery_soc: float
    battery_power: float
    grid_power: float
    inverter_power: float
    daily_production: float
    monthly_production: float
    total_production: float
    raw: dict


class DeyeClient:
    BASE = 'https://eu1-developer.deyecloud.com/v1.0'

    def __init__(self, settings: dict | None = None):
        cfg = current_app.config
        s = settings or {}
        self.app_id        = s.get('deye_app_id')        or cfg['DEYE_APP_ID']
        self.app_secret    = s.get('deye_app_secret')    or cfg['DEYE_APP_SECRET']
        self.email         = s.get('deye_email')         or cfg['DEYE_EMAIL']
        self.password      = s.get('deye_password')      or cfg['DEYE_PASSWORD']
        self.password_hash = s.get('deye_password_hash') or cfg['DEYE_PASSWORD_HASH']
        self.plant_id      = str(s.get('deye_plant_id')  or cfg['DEYE_PLANT_ID'] or '')
        self.device_sn     = str(s.get('deye_device_sn') or cfg['DEYE_DEVICE_SN'] or '')
        self.logger_sn     = str(s.get('deye_logger_sn') or cfg.get('DEYE_LOGGER_SN', '') or '')
        self.plant_name    = s.get('deye_plant_name')    or cfg['DEYE_PLANT_NAME'] or ''
        self.battery_sn_main   = str(s.get('deye_battery_sn_main')   or cfg['DEYE_BATTERY_SN_MAIN'] or '')
        self.battery_sn_module = str(s.get('deye_battery_sn_module') or cfg['DEYE_BATTERY_SN_MODULE'] or '')
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def _url(self, path): return f"{self.BASE}{path}"

    def _ensure_credentials(self):
        missing = [k for k, v in {
            'DEYE_APP_ID': self.app_id,
            'DEYE_APP_SECRET': self.app_secret,
            'DEYE_EMAIL': self.email,
        }.items() if not v or 'PUT_YOUR' in str(v)]
        if not (self.password_hash or self.password):
            missing.append('DEYE_PASSWORD')
        if missing:
            raise DeyeAPIError('البيانات الناقصة: ' + ', '.join(missing))

    def obtain_token(self) -> str:
        self._ensure_credentials()
        pw_hash = self.password_hash or sha256_hex(self.password)
        r = self.session.post(
            self._url('/account/token'),
            params={'appId': self.app_id},
            json={'appSecret': self.app_secret, 'email': self.email, 'password': pw_hash},
            timeout=30,
        )
        data = self._handle(r)
        token = (data.get('accessToken') or data.get('token') or
                 (data.get('data') or {}).get('accessToken') or
                 (data.get('data') or {}).get('token'))
        if not token:
            raise DeyeAPIError('لم يُعطَ Access Token من Deye')
        return token

    def account_info(self, token: str) -> dict:
        return self._handle(self.session.post(self._url('/account/info'),
            headers={'Authorization': f'Bearer {token}'}, timeout=30))

    def station_list(self, token: str) -> list[dict]:
        data = self._handle(self.session.post(self._url('/station/list'),
            headers={'Authorization': f'Bearer {token}'},
            json={'page': 1, 'size': 20}, timeout=30))
        return [i for i in choose_best_station_list(data) if isinstance(i, dict)]

    def station_latest(self, token: str, station_id=None) -> dict:
        sid = station_id or self.plant_id
        if not sid:
            raise DeyeAPIError('لا يوجد Plant ID')
        return self._handle(self.session.post(self._url('/station/latest'),
            headers={'Authorization': f'Bearer {token}'},
            json={'stationId': int(sid)}, timeout=30))

    def device_latest(self, token: str, device_sn: str) -> dict:
        """POST /device/latest — returns full device data as key/value list."""
        r = self.session.post(self._url('/device/latest'),
            headers={'Authorization': f'Bearer {token}'},
            json={'deviceList': [device_sn]}, timeout=30)
        return self._handle(r)

    def device_history_this_month(self, token: str, device_sn: str) -> dict:
        """
        Get daily production for current month via granularity=2.
        granularity=2: startAt/endAt in YYYY-MM-DD, returns one entry per day.
        Sum of dailyProductionActive = monthly total.
        """
        from datetime import datetime, date
        today = date.today()
        month_start = today.replace(day=1).strftime('%Y-%m-%d')
        today_str = today.strftime('%Y-%m-%d')
        try:
            r = self.session.post(self._url('/device/history'),
                headers={'Authorization': f'Bearer {token}'},
                json={'deviceSn': device_sn, 'granularity': 2,
                      'startAt': month_start, 'endAt': today_str,
                      'measurePoints': ['dailyProductionActive',
                                        'dailyConsumption',
                                        'dailyChargingEnergy',
                                        'dailyDischargingEnergy']},
                timeout=30)
            return self._handle(r)
        except Exception:
            return {}

    def device_history_yearly(self, token: str, device_sn: str) -> dict:
        """
        Get monthly production for current year via granularity=3.
        granularity=3: startAt/endAt in YYYY-MM, returns one entry per month.
        Sum = yearly total.
        """
        from datetime import date
        year = str(date.today().year)
        month = date.today().strftime('%Y-%m')
        try:
            r = self.session.post(self._url('/device/history'),
                headers={'Authorization': f'Bearer {token}'},
                json={'deviceSn': device_sn, 'granularity': 3,
                      'startAt': f'{year}-01', 'endAt': month,
                      'measurePoints': ['dailyProductionActive', 'dailyConsumption']},
                timeout=30)
            return self._handle(r)
        except Exception:
            return {}

    def station_device_list(self, token: str) -> list[dict]:
        """POST /station/device — returns all devices with deviceId."""
        if not self.plant_id:
            return []
        try:
            data = self._handle(self.session.post(self._url('/station/device'),
                headers={'Authorization': f'Bearer {token}'},
                json={'page': 1, 'size': 20, 'stationIds': [int(self.plant_id)]},
                timeout=30))
            return data.get('deviceListItems') or []
        except Exception:
            return []

    @staticmethod
    def parse_device_data(device_latest_response: dict) -> dict:
        """
        Parse /device/latest response (key/value list format) into a flat dict.
        Returns: {key: float_value, ...}
        """
        result = {}
        device_list = device_latest_response.get('deviceDataList') or []
        if not device_list:
            return result
        device = device_list[0]
        for item in device.get('dataList') or []:
            key = item.get('key')
            val = item.get('value')
            if key and val is not None:
                try:
                    result[key] = float(val)
                except (ValueError, TypeError):
                    result[key] = val  # keep string values (batteryStatus, inverterStatus...)
        result['_deviceSn']   = device.get('deviceSn', '')
        result['_deviceType'] = device.get('deviceType', '')
        result['_deviceState'] = device.get('deviceState', 0)
        return result

    def snapshot(self) -> DeyeSnapshot:
        token = self.obtain_token()

        # ── Get station info ──────────────────────────────────────────────────
        stations = self.station_list(token)
        station_summary = self._find_station(stations)

        # ── Get full device data from /device/latest ──────────────────────────
        d = {}  # flat dict of all device measurements
        if self.device_sn:
            try:
                dev_resp = self.device_latest(token, self.device_sn)
                d = self.parse_device_data(dev_resp)
            except Exception:
                pass

        # ── History for monthly/yearly production ────────────────────────────
        monthly_history = {}
        yearly_history = {}
        if self.device_sn:
            try:
                monthly_history = self.device_history_this_month(token, self.device_sn)
            except Exception:
                pass
            try:
                yearly_history = self.device_history_yearly(token, self.device_sn)
            except Exception:
                pass

        # ── Fallback to station/latest if device/latest empty ─────────────────
        station_rt = {}
        if not d and self.plant_id:
            try:
                station_rt = self.station_latest(token, self.plant_id)
            except Exception:
                pass

        def _f(key, default=0.0):
            """Get float value from device data dict."""
            v = d.get(key)
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        # ── Power values (W) ──────────────────────────────────────────────────
        # dcPowerPv1 + dcPowerPv2 + dcPowerPv3 = total solar input
        pv1_power = _f('dcPowerPv1')
        pv2_power = _f('dcPowerPv2')
        pv3_power = _f('dcPowerPv3')

        if d:
            # Use totalDcInputPower if available, else sum PVs
            solar_power = _f('totalDcInputPower') or (pv1_power + pv2_power + pv3_power)
            # inverterOutputPowerL1l2 = actual AC output to loads
            home_load = _f('totalConsumptionPower') or _f('inverterOutputPowerL1l2') or _f('upsLoadPower')
            battery_soc = _f('soc') or _f('bmsSoc')
        else:
            # Fallback to station/latest
            solar_power = safe_float(station_rt.get('generationPower') or
                                     station_summary.get('generationPower'), 0)
            home_load   = safe_float(station_rt.get('consumptionPower'), 0)
            battery_soc = safe_float(station_rt.get('batterySOC') or
                                     station_summary.get('batterySOC'), 0)

        # ── Battery power & sign convention ──────────────────────────────────
        # batteryStatus: "Charging" / "Discharging" / "Standby"
        # batteryPower: negative = charging (power going INTO battery), positive = discharging
        # batteryCurrent: negative = charging
        battery_status_str = str(d.get('batteryStatus') or '').lower()
        raw_batt_power = _f('batteryPower')  # W, negative=charging in Deye convention
        bms_current    = _f('bmsCurrent')    # A, negative=charging

        # Normalize: charge_power > 0 = charging, discharge_power > 0 = discharging
        if 'charg' in battery_status_str and 'dis' not in battery_status_str:
            charge_power    = abs(raw_batt_power)
            discharge_power = 0.0
            battery_power   = charge_power   # positive = charging
        elif 'discharg' in battery_status_str:
            discharge_power = abs(raw_batt_power)
            charge_power    = 0.0
            battery_power   = -discharge_power  # negative = discharging
        elif raw_batt_power < 0:
            charge_power    = abs(raw_batt_power)
            discharge_power = 0.0
            battery_power   = raw_batt_power
        elif raw_batt_power > 0:
            discharge_power = raw_batt_power
            charge_power    = 0.0
            battery_power   = -raw_batt_power
        else:
            charge_power = discharge_power = battery_power = 0.0

        # ── Grid power ────────────────────────────────────────────────────────
        grid_power_raw = _f('totalGridPower')
        grid_feedin    = _f('gridTiePower')
        # gridStatus: "Static" = no grid connection (BATTERY_BACKUP system)
        grid_status = str(d.get('gridStatus') or '').lower()
        if 'static' in grid_status or abs(grid_power_raw) < 5:
            grid_power = 0.0
        else:
            grid_power = grid_power_raw

        inverter_power = _f('inverterOutputPowerL1l2') or solar_power

        # ── Production totals ─────────────────────────────────────────────────
        # dailyProductionActive = today's kWh ✅
        # cumulativeProductionActive = all-time total kWh ✅
        # No monthly available from API → computed locally
        daily_prod = _f('dailyProductionActive')
        total_prod = _f('cumulativeProductionActive')
        def _parse_history_sum(hist_data: dict, key: str) -> float:
            """Sum a measure across all days in history response."""
            total = 0.0
            try:
                # Response structure: {deviceDataItems: [{dataList: [{key, value}], startAt, ...}]}
                items = (hist_data.get('deviceDataItems') or
                         hist_data.get('stationDataItems') or
                         hist_data.get('dataList') or [])
                for item in items:
                    for v in (item.get('dataList') or []):
                        if v.get('key') == key:
                            total += safe_float(v.get('value'), 0)
            except Exception:
                pass
            return round(total, 2)

        monthly_prod = _parse_history_sum(monthly_history, 'dailyProductionActive')
        yearly_prod_from_history = _parse_history_sum(yearly_history, 'dailyProductionActive')

        # ── Status ────────────────────────────────────────────────────────────
        _raw_status = str(d.get('inverterStatus') or station_summary.get('connectionStatus') or 'NORMAL')
        inv_status = _tr_inv(_raw_status) if _raw_status else 'يعمل بشكل طبيعي'
        plant_name = str(station_summary.get('name') or self.plant_name or 'محطة Deye')
        plant_id   = str(station_summary.get('id') or self.plant_id)

        return DeyeSnapshot(
            plant_id=plant_id, plant_name=plant_name,
            status_text=inv_status,
            solar_power=solar_power, home_load=home_load,
            battery_soc=battery_soc, battery_power=battery_power,
            grid_power=grid_power, inverter_power=inverter_power,
            daily_production=daily_prod,
            monthly_production=monthly_prod,
            total_production=total_prod,
            raw={
                'latest': station_rt or {},
                'station_summary': station_summary,
                'stations': stations,
                'device_data': d,   # full flat device dict
                'derived': {
                    'chargePower':       charge_power,
                    'dischargePower':    discharge_power,
                    'batteryPowerSigned': battery_power,
                    'purchasePower':     max(-grid_power, 0),
                    'feedInPower':       max(grid_power, 0),
                    'gridPowerSigned':   grid_power,
                    # PV strings
                    'dcPowerPv1': pv1_power,
                    'dcPowerPv2': pv2_power,
                    'dcPowerPv3': pv3_power,
                    'dcVoltagePv1': _f('dcVoltagePv1'),
                    'dcVoltagePv2': _f('dcVoltagePv2'),
                    'dcCurrentPv1': _f('dcCurrentPv1'),
                    'dcCurrentPv2': _f('dcCurrentPv2'),
                    # Battery details
                    'batteryVoltage':    _f('batteryVoltage') or _f('bmsVoltage'),
                    'batteryCurrent':    bms_current,
                    'batteryTemp':       _f('bmsTemperature') or _f('temperatureBattery'),
                    'batteryStatus':     _tr_bat(str(d.get('batteryStatus') or '')),
                    'batteryCapacityAh': _f('batteryRatedCapacity'),
                    'batteryType':       d.get('batteryType', ''),
                    # Temperatures
                    'acTemperature': _f('acTemperature'),
                    'dcTemperature': _f('dcTemperature'),
                    # Energy counters
                    'dailyChargingEnergy':   _f('dailyChargingEnergy'),
                    'dailyDischargingEnergy': _f('dailyDischargingEnergy'),
                    'totalChargingEnergy':   _f('totalChargingEnergy'),
                    'totalDischargingEnergy': _f('totalDischargingEnergy'),
                    'dailyConsumption':      _f('dailyConsumption'),
                    'cumulativeConsumption': _f('cumulativeConsumption'),
                    # Grid
                    'acVoltage':       _f('acVoltageRua') or _f('loadVoltageL1l2'),
                    'acFrequency':     _f('acOutputFrequencyR'),
                    'acCurrent':       _f('acCurrentRua'),
                    # Alerts
                    'inverterStatus':  _tr_inv(str(d.get('inverterStatus') or '')),
                    'gridRelayStatus': d.get('gridRelayStatus', ''),
                    # Battery SN
                    'batterySnMain':   self.battery_sn_main,
                    'batterySnModule': self.battery_sn_module,
                },
                'monthly_history': monthly_history,
                'yearly_history': yearly_history,
            },
        )

    def _find_station(self, stations: list[dict]) -> dict:
        if not stations:
            return {}
        for item in stations:
            if not isinstance(item, dict): continue
            if str(item.get('id', '')) == self.plant_id: return item
            if (item.get('name') or '').lower() == self.plant_name.lower(): return item
        return stations[0] if isinstance(stations[0], dict) else {}

    def _handle(self, response: requests.Response) -> dict:
        try:
            data = response.json()
        except Exception as e:
            raise DeyeAPIError(f'رد غير JSON. HTTP {response.status_code}') from e
        if not response.ok:
            raise DeyeAPIError(f'HTTP {response.status_code}: {data}')
        code = str(data.get('code', '')) if isinstance(data, dict) else ''
        if code and code not in ('1000000', '0'):
            raise DeyeAPIError(data.get('msg', f'خطأ من Deye: {code}'))
        return data
