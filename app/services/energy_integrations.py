from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSpec:
    code: str
    name: str
    provider: str
    auth_mode: str
    base_url: str | None
    healthcheck_endpoint: str | None
    sync_endpoint: str | None
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    status: str = 'ready'
    category: str = 'solar'
    docs_url: str = ''
    notes_ar: str = ''
    notes_en: str = ''
    mapping_schema: dict[str, Any] | None = None

    def as_device_type_payload(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'provider': self.provider,
            'auth_mode': self.auth_mode,
            'base_url': self.base_url,
            'healthcheck_endpoint': self.healthcheck_endpoint,
            'sync_endpoint': self.sync_endpoint,
            'required_fields_json': json.dumps(list(self.required_fields), ensure_ascii=False),
            'mapping_schema_json': json.dumps(self.mapping_schema or {}, ensure_ascii=False),
            'is_active': True,
        }


PROVIDER_CATALOG: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        code='deye',
        name='Deye Cloud',
        provider='deye',
        auth_mode='config',
        base_url='https://eu1-developer.deyecloud.com',
        healthcheck_endpoint='/openapi/v1/station/list',
        sync_endpoint='/openapi/v1/inverter/getInverterRealTimeData',
        required_fields=('deye_app_id', 'deye_app_secret', 'deye_email', 'deye_password_or_hash', 'deye_plant_id'),
        optional_fields=('deye_device_sn', 'deye_logger_sn', 'battery_capacity_kwh'),
        category='inverter_cloud',
        docs_url='https://developer.deyecloud.com/',
        notes_ar='المزوّد الحالي الأساسي. يستخدم منطق Deye الموجود في التطبيق للمزامنة الفعلية.',
        notes_en='Current primary provider. Live sync uses the existing Deye client in the app.',
        mapping_schema={'solar_power': 'pv_power', 'battery_soc': 'battery_soc', 'grid_power': 'grid_power', 'home_load': 'load_power'},
    ),
    ProviderSpec(
        code='solaredge_cloud',
        name='SolarEdge Monitoring API',
        provider='solaredge',
        auth_mode='api_key',
        base_url='https://monitoringapi.solaredge.com',
        healthcheck_endpoint='/site/{site_id}/overview.json',
        sync_endpoint='/site/{site_id}/overview.json',
        required_fields=('site_id', 'api_key'),
        category='inverter_cloud',
        docs_url='https://www.solaredge.com/en/products/software-tools/monitoring-platform',
        notes_ar='تكامل قراءة آمن للملخص العام من SolarEdge. يحتاج API Key و Site ID.',
        notes_en='Safe read integration for SolarEdge overview data. Requires API key and Site ID.',
        mapping_schema={'solar_power': 'overview.currentPower.power', 'daily_production': 'overview.lastDayData.energy', 'total_production': 'overview.lifeTimeData.energy'},
    ),
    ProviderSpec(
        code='enphase_enlighten',
        name='Enphase Enlighten API',
        provider='enphase',
        auth_mode='oauth2_api_key',
        base_url='https://api.enphaseenergy.com',
        healthcheck_endpoint='/api/v4/systems/{system_id}/summary',
        sync_endpoint='/api/v4/systems/{system_id}/summary',
        required_fields=('system_id', 'api_key', 'oauth_access_token'),
        category='inverter_cloud',
        docs_url='https://developer-v4.enphase.com/docs.html',
        notes_ar='مدعوم كـ Blueprint احترافي. المزامنة تحتاج OAuth access token من تطبيق Enphase.',
        notes_en='Professional blueprint. Sync requires an OAuth access token from an Enphase app.',
        mapping_schema={'solar_power': 'current_power', 'daily_production': 'energy_today', 'total_production': 'energy_lifetime'},
    ),
    ProviderSpec(
        code='victron_vrm',
        name='Victron VRM API',
        provider='victron',
        auth_mode='access_token',
        base_url='https://vrmapi.victronenergy.com',
        healthcheck_endpoint='/v2/installations/{installation_id}/system-overview',
        sync_endpoint='/v2/installations/{installation_id}/system-overview',
        required_fields=('installation_id', 'access_token'),
        category='hybrid_energy_system',
        docs_url='https://vrm-api-docs.victronenergy.com/',
        notes_ar='تكامل Fleet/VRM للأنظمة الهجينة. مناسب للمراقبة والتحكم المرحلي لاحقًا.',
        notes_en='Fleet/VRM integration for hybrid energy systems. Good for monitoring now and staged control later.',
        mapping_schema={'raw_data': 'records'},
    ),
    ProviderSpec(
        code='fronius_local',
        name='Fronius Solar API Local',
        provider='fronius',
        auth_mode='local_http',
        base_url='http://192.168.1.100',
        healthcheck_endpoint='/solar_api/v1/GetPowerFlowRealtimeData.fcgi',
        sync_endpoint='/solar_api/v1/GetPowerFlowRealtimeData.fcgi',
        required_fields=('local_base_url',),
        category='local_inverter',
        docs_url='https://www.fronius.com/en-au/australia/solar-energy/installers-partners/technical-data/all-products/system-monitoring/open-interfaces/fronius-solar-api-json-',
        notes_ar='تكامل محلي مباشر عبر الشبكة. لا يحتاج مفاتيح إذا كان الانفيرتر متاحًا داخل الشبكة.',
        notes_en='Direct LAN integration. No cloud key required when the inverter is reachable on the local network.',
        mapping_schema={'solar_power': 'Body.Data.Site.P_PV', 'home_load': 'Body.Data.Site.P_Load', 'grid_power': 'Body.Data.Site.P_Grid', 'daily_production': 'Body.Data.Site.E_Day'},
    ),
    ProviderSpec(
        code='sma_cloud',
        name='SMA Sunny Portal / ennexOS API',
        provider='sma',
        auth_mode='oauth2',
        base_url='https://api.smaapis.de',
        healthcheck_endpoint=None,
        sync_endpoint=None,
        required_fields=('client_id', 'client_secret', 'oauth_access_token', 'system_id'),
        category='inverter_cloud',
        docs_url='https://developer.sma.de/sma-apis',
        notes_ar='Blueprint رسمي للتجهيز. يحتاج OAuth delegation من SMA قبل المزامنة.',
        notes_en='Official-ready blueprint. Requires SMA OAuth delegation before sync.',
        mapping_schema={'raw_data': 'raw'},
    ),
    ProviderSpec(
        code='tesla_energy',
        name='Tesla Fleet API — Energy Sites',
        provider='tesla',
        auth_mode='oauth2_bearer',
        base_url='https://fleet-api.prd.na.vn.cloud.tesla.com',
        healthcheck_endpoint='/api/1/energy_sites/{energy_site_id}/site_info',
        sync_endpoint='/api/1/energy_sites/{energy_site_id}/site_info',
        required_fields=('energy_site_id', 'oauth_access_token'),
        category='battery_energy_site',
        docs_url='https://developer.tesla.com/docs/fleet-api/endpoints/energy',
        notes_ar='قراءة معلومات موقع الطاقة من Tesla Fleet API. يتطلب OAuth token صالح.',
        notes_en='Reads Tesla energy site information through Fleet API. Requires a valid OAuth token.',
        mapping_schema={'raw_data': 'response'},
    ),
    ProviderSpec(
        code='huawei_fusionsolar',
        name='Huawei FusionSolar Northbound',
        provider='huawei',
        auth_mode='northbound_api',
        base_url=None,
        healthcheck_endpoint=None,
        sync_endpoint=None,
        required_fields=('base_url', 'username', 'system_code'),
        optional_fields=('password', 'station_code'),
        category='inverter_cloud',
        docs_url='https://support.huawei.com/enterprise/en/doc/EDOC1100440661/253d3ba3/obtaining-northbound-api-documents',
        notes_ar='Blueprint رسمي للتجهيز. وثائق Northbound تُستخرج من FusionSolar حسب حساب الشركة.',
        notes_en='Official-ready blueprint. Northbound docs are obtained from FusionSolar per company account.',
        mapping_schema={'raw_data': 'raw'},
    ),
    ProviderSpec(
        code='shelly_gen2',
        name='Shelly Gen2+ Local RPC',
        provider='shelly',
        auth_mode='local_rpc_digest_optional',
        base_url='http://192.168.1.50',
        healthcheck_endpoint='/rpc/Shelly.GetStatus',
        sync_endpoint='/rpc/Shelly.GetStatus',
        required_fields=('local_base_url',),
        optional_fields=('username', 'password'),
        category='smart_load_meter',
        docs_url='https://shelly-api-docs.shelly.cloud/gen2/',
        notes_ar='مفيد لقراءة الأحمال الذكية والريليهات والمقابس داخل الشبكة المحلية.',
        notes_en='Useful for local smart plugs, relays, and load monitoring inside the LAN.',
        mapping_schema={'home_load': 'switch:0.apower', 'raw_data': 'raw'},
    ),

    ProviderSpec(
        code='solarman_openapi',
        name='SOLARMAN OpenAPI',
        provider='solarman',
        auth_mode='openapi_token',
        base_url='https://globalapi.solarmanpv.com',
        healthcheck_endpoint='/station/v1.0/list',
        sync_endpoint='/station/v1.0/realTime',
        required_fields=('station_id', 'access_token', 'app_id'),
        optional_fields=('app_secret', 'logger_sn', 'device_sn'),
        category='logger_cloud',
        docs_url='https://doc.solarmanpv.com/en/Documentation%20and%20Quick%20Guide',
        notes_ar='مناسب للأجهزة التي ترفع بياناتها إلى SOLARMAN عند توفر OpenAPI.',
        notes_en='For systems reporting to SOLARMAN when OpenAPI access is available.',
        mapping_schema={'solar_power': 'data.power', 'battery_soc': 'data.batterySoc', 'grid_power': 'data.gridPower', 'home_load': 'data.loadPower', 'daily_production': 'data.generationPowerDay', 'total_production': 'data.generationPowerTotal'},
    ),
    ProviderSpec(
        code='sungrow_isolarcloud',
        name='Sungrow iSolarCloud API',
        provider='sungrow',
        auth_mode='oauth2',
        base_url='https://gateway.isolarcloud.com',
        healthcheck_endpoint='/openapi/getPowerStationList',
        sync_endpoint='/openapi/getPowerStationRealKpi',
        required_fields=('station_id', 'access_token', 'app_key'),
        optional_fields=('app_secret', 'refresh_token', 'region'),
        category='inverter_cloud',
        docs_url='https://developer-api.isolarcloud.com/',
        notes_ar='يدعم بوابة مطوري Sungrow وتفويض OAuth حسب المنطقة.',
        notes_en='Uses the Sungrow Developer Portal with region-aware OAuth access.',
        mapping_schema={'solar_power': 'result_data.p83022', 'battery_soc': 'result_data.p13141', 'grid_power': 'result_data.p83118', 'home_load': 'result_data.load_power', 'daily_production': 'result_data.day_power', 'total_production': 'result_data.total_power'},
    ),
    ProviderSpec(
        code='goodwe_sems',
        name='GoodWe SEMS OpenAPI',
        provider='goodwe',
        auth_mode='organization_api',
        base_url=None,
        healthcheck_endpoint='/api/v1/PowerStation/GetMonitorDetailByPowerstationId',
        sync_endpoint='/api/v1/PowerStation/GetMonitorDetailByPowerstationId',
        required_fields=('base_url', 'account', 'password', 'powerstation_id'),
        optional_fields=('org_id',),
        category='inverter_cloud',
        docs_url='https://community.goodwe.com/static/images/2024-08-20597794.pdf',
        notes_ar='عادةً يحتاج حساب SEMS Organization وصلاحيات API.',
        notes_en='Usually requires a SEMS organization account with API privileges.',
        mapping_schema={'solar_power': 'data.kpi.power', 'battery_soc': 'data.inverter.batterySoc', 'grid_power': 'data.kpi.gridPower', 'home_load': 'data.kpi.loadPower', 'daily_production': 'data.kpi.powerDay', 'total_production': 'data.kpi.powerTotal'},
    ),
    ProviderSpec(
        code='growatt_v1',
        name='Growatt Server API v1',
        provider='growatt',
        auth_mode='api_token',
        base_url='https://server.growatt.com',
        healthcheck_endpoint='/v1/plant/list',
        sync_endpoint='/v1/plant/data',
        required_fields=('plant_id', 'api_token'),
        optional_fields=('user_id',),
        category='inverter_cloud',
        docs_url='https://growatt.pl/wp-content/uploads/2020/01/Growatt-Server-API-Guide.pdf',
        notes_ar='إطار API v1 عند توفر token رسمي من Growatt.',
        notes_en='API v1 blueprint for accounts with an official Growatt token.',
        mapping_schema={'solar_power': 'data.current_power', 'daily_production': 'data.today_energy', 'total_production': 'data.total_energy', 'status_text': 'error_msg'},
    ),
)

PROVIDER_MAP = {p.code: p for p in PROVIDER_CATALOG}
PROVIDER_ALIASES = {
    'solaredge': 'solaredge_cloud',
    'solar_edge': 'solaredge_cloud',
    'enphase': 'enphase_enlighten',
    'fronius': 'fronius_local',
    'sma': 'sma_cloud',
    'tesla': 'tesla_energy',
    'powerwall': 'tesla_energy',
    'huawei': 'huawei_fusionsolar',
    'fusionsolar': 'huawei_fusionsolar',
    'solarman': 'solarman_openapi',
    'sungrow': 'sungrow_isolarcloud',
    'goodwe': 'goodwe_sems',
    'growatt': 'growatt_v1',
    'shelly': 'shelly_gen2',
}


def provider_catalog() -> list[ProviderSpec]:
    return list(PROVIDER_CATALOG)


def provider_by_code(code: str | None) -> ProviderSpec | None:
    normalized = str(code or '').strip().lower()
    return PROVIDER_MAP.get(normalized) or PROVIDER_MAP.get(PROVIDER_ALIASES.get(normalized, ''))


def _safe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def device_credentials(device) -> dict[str, Any]:
    creds = _safe_json(getattr(device, 'credentials_json', None))
    settings = _safe_json(getattr(device, 'settings_json', None))
    merged = {}
    merged.update(settings)
    merged.update(creds)
    for attr in ('api_base_url', 'external_device_id', 'device_uid', 'station_id'):
        val = getattr(device, attr, None)
        if val not in (None, ''):
            merged[attr] = val
    return merged


def _get_path(payload: Any, path: str | None, default=None):
    if not path:
        return default
    cur = payload
    for part in str(path).split('.'):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return default
        if cur is None:
            return default
    return cur


def _float(value, default=0.0):
    try:
        if value in (None, ''):
            return default
        return float(value)
    except Exception:
        return default


def _build_endpoint(spec: ProviderSpec, endpoint: str | None, creds: dict[str, Any]) -> str | None:
    if not endpoint:
        return None
    out = endpoint
    for key, value in creds.items():
        out = out.replace('{' + key + '}', str(value))
    return out


def _base_url(spec: ProviderSpec, creds: dict[str, Any]) -> str | None:
    return (creds.get('local_base_url') or creds.get('base_url') or spec.base_url or '').rstrip('/') or None


def build_request(spec: ProviderSpec, endpoint: str | None, creds: dict[str, Any]) -> tuple[str, dict[str, str], dict[str, Any]]:
    base = _base_url(spec, creds)
    ep = _build_endpoint(spec, endpoint, creds)
    if not base or not ep:
        raise ValueError('Missing base URL or endpoint for this provider.')
    url = urljoin(base + '/', ep.lstrip('/'))
    headers: dict[str, str] = {'Accept': 'application/json'}
    params: dict[str, Any] = {}
    token = creds.get('oauth_access_token') or creds.get('access_token') or creds.get('bearer_token')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if spec.code == 'solaredge_cloud' and creds.get('api_key'):
        params['api_key'] = creds.get('api_key')
    if spec.code == 'enphase_enlighten' and creds.get('api_key'):
        headers['key'] = str(creds.get('api_key'))
    return url, headers, params


def normalize_snapshot(spec: ProviderSpec, payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload or {}
    if spec.code == 'solaredge_cloud':
        overview = raw.get('overview') or {}
        return {
            'provider': spec.code,
            'solar_power': _float(_get_path(raw, 'overview.currentPower.power')) * 1000 if _float(_get_path(raw, 'overview.currentPower.power')) < 100 else _float(_get_path(raw, 'overview.currentPower.power')),
            'daily_production': _float(_get_path(raw, 'overview.lastDayData.energy')),
            'monthly_production': _float(_get_path(raw, 'overview.lastMonthData.energy')),
            'total_production': _float(_get_path(raw, 'overview.lifeTimeData.energy')),
            'status_text': str(overview.get('status') or 'ok'),
            'raw': raw,
        }
    if spec.code == 'fronius_local':
        site = _get_path(raw, 'Body.Data.Site', {}) or {}
        return {
            'provider': spec.code,
            'solar_power': max(_float(site.get('P_PV')), 0.0),
            'home_load': abs(_float(site.get('P_Load'))),
            'grid_power': _float(site.get('P_Grid')),
            'daily_production': _float(site.get('E_Day')),
            'total_production': _float(site.get('E_Total')),
            'status_text': 'ok',
            'raw': raw,
        }
    if spec.code == 'shelly_gen2':
        # Shelly keys contain ':' and are intentionally accessed directly.
        switch0 = raw.get('switch:0') or {}
        meter0 = raw.get('em:0') or raw.get('em1:0') or {}
        return {
            'provider': spec.code,
            'home_load': _float(switch0.get('apower') or meter0.get('act_power')),
            'status_text': 'ok' if raw else 'empty',
            'raw': raw,
        }
    return {'provider': spec.code, 'status_text': 'ok' if raw else 'empty', 'raw': raw}


def missing_required(spec: ProviderSpec, creds: dict[str, Any]) -> list[str]:
    missing = []
    aliases = {
        'local_base_url': ('local_base_url', 'base_url', 'api_base_url'),
        'oauth_access_token': ('oauth_access_token', 'access_token', 'bearer_token'),
        'energy_site_id': ('energy_site_id', 'site_id', 'external_device_id'),
        'installation_id': ('installation_id', 'station_id', 'external_device_id'),
        'system_id': ('system_id', 'station_id', 'external_device_id'),
        'site_id': ('site_id', 'station_id', 'external_device_id'),
    }
    for field in spec.required_fields:
        candidates = aliases.get(field, (field,))
        if not any(str(creds.get(candidate) or '').strip() for candidate in candidates):
            missing.append(field)
    return missing




def provider_category_label(category: str | None, lang: str = 'ar') -> str:
    value = str(category or '').strip()
    labels = {
        'inverter_cloud': {'ar': 'انفيرتر سحابي', 'en': 'Cloud inverter'},
        'hybrid_energy_system': {'ar': 'نظام طاقة هجين', 'en': 'Hybrid energy system'},
        'local_inverter': {'ar': 'انفيرتر محلي', 'en': 'Local inverter'},
        'battery_energy_site': {'ar': 'موقع بطاريات وطاقة', 'en': 'Battery energy site'},
        'smart_load_meter': {'ar': 'قياس أحمال ذكي', 'en': 'Smart load meter'},
        'logger_cloud': {'ar': 'مسجل بيانات سحابي', 'en': 'Cloud data logger'},
        'solar': {'ar': 'طاقة شمسية', 'en': 'Solar'},
    }
    lang = 'en' if str(lang or '').lower().startswith('en') else 'ar'
    return labels.get(value, {'ar': value, 'en': value.replace('_', ' ').title()}).get(lang, value)

def test_connection_for_device(device, timeout: int = 12) -> dict[str, Any]:
    code = getattr(device, 'api_provider', None) or getattr(device, 'device_type', None)
    spec = provider_by_code(code)
    if not spec:
        return {'ok': False, 'status': 'unsupported', 'message': f'Unsupported provider: {code}'}
    creds = device_credentials(device)
    missing = missing_required(spec, creds)
    if missing:
        return {'ok': False, 'status': 'missing_credentials', 'message': 'Missing: ' + ', '.join(missing), 'provider': spec.code}
    if not spec.healthcheck_endpoint:
        return {'ok': True, 'status': 'configured', 'message': 'Provider blueprint is configured. Live API test requires OAuth/vendor-specific activation.', 'provider': spec.code}
    try:
        url, headers, params = build_request(spec, spec.healthcheck_endpoint, creds)
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        text = resp.text[:500]
        ok = 200 <= resp.status_code < 300
        data = resp.json() if ok and resp.text else {}
        return {
            'ok': ok,
            'status': 'ok' if ok else 'failed',
            'message': f'HTTP {resp.status_code}',
            'provider': spec.code,
            'preview': normalize_snapshot(spec, data) if ok and isinstance(data, dict) else text,
        }
    except Exception as exc:
        logger.exception('Integration test failed for provider=%s device=%s', spec.code, getattr(device, 'id', None))
        return {'ok': False, 'status': 'failed', 'message': str(exc), 'provider': spec.code}


def fetch_snapshot_for_device(device, timeout: int = 15) -> dict[str, Any]:
    code = getattr(device, 'api_provider', None) or getattr(device, 'device_type', None)
    spec = provider_by_code(code)
    if not spec:
        raise ValueError(f'Unsupported provider: {code}')
    creds = device_credentials(device)
    missing = missing_required(spec, creds)
    if missing:
        raise ValueError('Missing required credentials: ' + ', '.join(missing))
    if not spec.sync_endpoint:
        raise ValueError(f'{spec.name} is configured as a blueprint only; sync endpoint is not enabled yet.')
    url, headers, params = build_request(spec, spec.sync_endpoint, creds)
    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json() if resp.text else {}
    if not isinstance(data, dict):
        data = {'records': data}
    snap = normalize_snapshot(spec, data)
    snap['fetched_at'] = datetime.utcnow().isoformat()
    return snap
