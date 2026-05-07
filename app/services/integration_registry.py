from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class IntegrationProvider:
    code: str
    name: str
    provider: str
    category: str
    auth_mode: str
    base_url: str | None
    healthcheck_endpoint: str | None
    sync_endpoint: str | None
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    mapping_schema: dict[str, str]
    docs_url: str
    maturity: str = 'supported'
    notes_ar: str = ''
    notes_en: str = ''

    def to_device_type_payload(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'name': self.name,
            'provider': self.provider,
            'auth_mode': self.auth_mode,
            'base_url': self.base_url,
            'healthcheck_endpoint': self.healthcheck_endpoint,
            'sync_endpoint': self.sync_endpoint,
            'required_fields_json': json.dumps(list(self.required_fields), ensure_ascii=False),
            'mapping_schema_json': json.dumps(self.mapping_schema, ensure_ascii=False),
            'is_active': True,
        }

    def as_ui(self) -> dict[str, Any]:
        data = asdict(self)
        data['required_fields'] = list(self.required_fields)
        data['optional_fields'] = list(self.optional_fields)
        return data


SUPPORTED_INTEGRATIONS: tuple[IntegrationProvider, ...] = (
    # 1. Deye Cloud
    # FIX: docs_url pointed to base_url itself; corrected to developer portal.
    # FIX: sync_endpoint updated to /device/detail (confirmed from official sample code).
    IntegrationProvider(
        code='deye',
        name='Deye Cloud',
        provider='deye',
        category='Hybrid inverter / solar cloud',
        auth_mode='config',
        base_url='https://eu1-developer.deyecloud.com',
        healthcheck_endpoint='/openapi/v1/station/list',
        sync_endpoint='/openapi/v1/device/detail',
        required_fields=('deye_app_id', 'deye_app_secret', 'deye_email', 'deye_password_or_hash', 'deye_plant_id'),
        optional_fields=('deye_device_sn', 'deye_logger_sn', 'deye_battery_sn'),
        mapping_schema={
            'solar_power': 'derived.solar_power',
            'battery_soc': 'derived.battery_soc',
            'battery_power': 'derived.battery_power',
            'grid_power': 'derived.grid_power',
            'home_load': 'derived.home_load',
            'daily_production': 'derived.daily_production',
            'total_production': 'derived.total_production',
        },
        docs_url='https://developer.deyecloud.com/api',
        notes_en='Current primary platform integration. Other regions: us1/ap1-developer.deyecloud.com',
    ),
    # 2. SolarEdge Monitoring API
    # FIX: docs_url updated to stable PDF link.
    # INFO: v2 API at /v2 prefix uses X-Account-Key + X-API-Key headers.
    IntegrationProvider(
        code='solaredge',
        name='SolarEdge Monitoring API',
        provider='solaredge',
        category='PV inverter / cloud monitoring',
        auth_mode='api_key',
        base_url='https://monitoringapi.solaredge.com',
        healthcheck_endpoint='/site/{site_id}/details',
        sync_endpoint='/site/{site_id}/overview',
        required_fields=('api_key', 'site_id'),
        optional_fields=('account_key', 'equipment_id'),
        mapping_schema={
            'solar_power': 'overview.currentPower.power',
            'daily_production': 'overview.lastDayData.energy',
            'monthly_production': 'overview.lastMonthData.energy',
            'total_production': 'overview.lifeTimeData.energy',
            'status_text': 'overview.status',
        },
        docs_url='https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf',
        notes_en=(
            'v1 API: api_key as URL param, 300 req/token rate limit. '
            'v2 at /v2 prefix requires X-Account-Key + X-API-Key headers; '
            'add account_key to credentials for v2 migration.'
        ),
    ),
    # 3. Enphase Enlighten API v4
    # FIX: client_id + client_secret are REQUIRED for OAuth2 token acquisition.
    #      Moved from optional to required. access_token is ephemeral (cached).
    IntegrationProvider(
        code='enphase',
        name='Enphase Enlighten API v4',
        provider='enphase',
        category='Microinverter / battery cloud monitoring',
        auth_mode='oauth2',
        base_url='https://api.enphaseenergy.com/api/v4',
        healthcheck_endpoint='/systems/{system_id}/summary',
        sync_endpoint='/systems/{system_id}/summary',
        required_fields=('client_id', 'client_secret', 'api_key', 'system_id'),
        optional_fields=('access_token', 'refresh_token'),
        mapping_schema={
            'solar_power': 'current_power',
            'daily_production': 'energy_today',
            'total_production': 'energy_lifetime',
            'status_text': 'status',
        },
        docs_url='https://developer-v4.enphase.com/docs.html',
        notes_en=(
            'OAuth2: client_id + client_secret at POST /oauth/token. '
            'api_key sent as query param on every request. '
            'access_token is short-lived; store refresh_token for renewal. '
            'Plan tiers (Watt/Kilowatt/Partner) control available endpoints.'
        ),
    ),
    # 4. Victron VRM API -- VERIFIED: base_url and endpoints correct.
    IntegrationProvider(
        code='victron_vrm',
        name='Victron VRM API',
        provider='victron',
        category='Battery / inverter / ESS monitoring',
        auth_mode='bearer_token',
        base_url='https://vrmapi.victronenergy.com/v2',
        healthcheck_endpoint='/installations/{installation_id}',
        sync_endpoint='/installations/{installation_id}/stats',
        required_fields=('access_token', 'installation_id'),
        optional_fields=('user_id',),
        mapping_schema={
            'solar_power': 'records.PvInverters.power',
            'battery_soc': 'records.Battery.soc',
            'battery_power': 'records.Battery.power',
            'grid_power': 'records.Grid.power',
            'home_load': 'records.Load.power',
        },
        docs_url='https://vrm-api-docs.victronenergy.com/',
        notes_en='Designed for Victron ESS and VRM installations.',
    ),
    # 5. Fronius Solar API (Local) -- VERIFIED: local LAN endpoints correct.
    IntegrationProvider(
        code='fronius_local',
        name='Fronius Solar API',
        provider='fronius',
        category='Local inverter REST API',
        auth_mode='local_network',
        base_url='http://{host}/solar_api/v1',
        healthcheck_endpoint='/GetInverterInfo.cgi',
        sync_endpoint='/GetPowerFlowRealtimeData.fcgi',
        required_fields=('host',),
        optional_fields=('meter_id', 'inverter_id'),
        mapping_schema={
            'solar_power': 'Body.Data.Site.P_PV',
            'battery_soc': 'Body.Data.Inverters.1.SOC',
            'battery_power': 'Body.Data.Site.P_Akku',
            'grid_power': 'Body.Data.Site.P_Grid',
            'home_load': 'Body.Data.Site.P_Load',
            'daily_production': 'Body.Data.Site.E_Day',
            'total_production': 'Body.Data.Site.E_Total',
        },
        docs_url='https://www.fronius.com/en-au/australia/solar-energy/installers-partners/technical-data/all-products/system-monitoring/open-interfaces/fronius-solar-api-json-',
        notes_en='Local LAN API served directly by the inverter or Datamanager.',
    ),
    # 6. Tesla Energy Fleet API
    # FIX: region added to required_fields; adapter must pick correct base_url.
    # INFO: EU base = fleet-api.prd.eu.vn.cloud.tesla.com
    IntegrationProvider(
        code='tesla_energy',
        name='Tesla Energy Fleet API',
        provider='tesla',
        category='Powerwall / energy site cloud API',
        auth_mode='oauth2',
        base_url='https://fleet-api.prd.na.vn.cloud.tesla.com',
        healthcheck_endpoint='/api/1/products',
        sync_endpoint='/api/1/energy_sites/{energy_site_id}/live_status',
        required_fields=('access_token', 'energy_site_id', 'region'),
        optional_fields=('refresh_token', 'client_id', 'client_secret'),
        mapping_schema={
            'solar_power': 'response.solar_power',
            'battery_soc': 'response.percentage_charged',
            'battery_power': 'response.battery_power',
            'grid_power': 'response.grid_power',
            'home_load': 'response.load_power',
            'status_text': 'response.storm_mode_active',
        },
        docs_url='https://developer.tesla.com/docs/fleet-api/endpoints/energy',
        notes_en=(
            'Base URL is region-specific: '
            'NA=fleet-api.prd.na.vn.cloud.tesla.com, '
            'EU=fleet-api.prd.eu.vn.cloud.tesla.com. '
            'App must be registered per-region. '
            'Adapter must select correct URL from region field.'
        ),
    ),
    # 7. SMA Monitoring API
    # CRITICAL FIX: base_url was 'https://api.sma.energy' (does NOT exist).
    # Correct production URL: https://monitoring.smaapis.de
    # Auth token URL: https://auth.smaapis.de/oauth2/token
    # Rate limiting active from 01 Jul 2025.
    IntegrationProvider(
        code='sma',
        name='SMA Monitoring API',
        provider='sma',
        category='Sunny Portal / ennexOS cloud API',
        auth_mode='oauth2',
        base_url='https://monitoring.smaapis.de',
        healthcheck_endpoint='/v1/plants/{plant_id}',
        sync_endpoint='/v1/plants/{plant_id}/livedata/overview',
        required_fields=('client_id', 'client_secret', 'plant_id'),
        optional_fields=('access_token', 'refresh_token'),
        mapping_schema={
            'solar_power': 'measurements.pv_power',
            'battery_soc': 'measurements.battery_soc',
            'grid_power': 'measurements.grid_power',
            'home_load': 'measurements.load_power',
        },
        docs_url='https://developer.sma.de/sma-apis',
        maturity='provider-ready',
        notes_en=(
            'OAuth2 token: POST https://auth.smaapis.de/oauth2/token. '
            'Production monitoring API: monitoring.smaapis.de. '
            'Sandbox: sandbox.smaapis.de/monitoring. '
            'Rate limiting active from 01 Jul 2025 per 5-min interval.'
        ),
    ),
    # 8. SOLARMAN OpenAPI
    # FIX: email + password_sha256 added to required_fields (needed for token acquisition).
    #      access_token moved to optional (cached post-auth).
    # INFO: Domain migrated from api.solarmanpv.com -> globalapi.solarmanpv.com (Jan 2024).
    IntegrationProvider(
        code='solarman',
        name='SOLARMAN OpenAPI',
        provider='solarman',
        category='Logger / inverter cloud platform',
        auth_mode='oauth2_like',
        base_url='https://globalapi.solarmanpv.com',
        healthcheck_endpoint='/station/v1.0/list',
        sync_endpoint='/station/v1.0/realTime',
        required_fields=('app_id', 'app_secret', 'email', 'password_sha256', 'station_id'),
        optional_fields=('access_token', 'logger_sn', 'device_sn'),
        mapping_schema={
            'solar_power': 'data.power',
            'battery_soc': 'data.batterySoc',
            'grid_power': 'data.gridPower',
            'home_load': 'data.loadPower',
            'daily_production': 'data.generationPowerDay',
            'total_production': 'data.generationPowerTotal',
        },
        docs_url='https://doc.solarmanpv.com/en/Documentation%20and%20Quick%20Guide',
        maturity='provider-ready',
        notes_en=(
            'Token endpoint: POST /account/v1.0/token '
            '(appId, appSecret, email, SHA256(password)). '
            'Domain migrated from api.solarmanpv.com to globalapi.solarmanpv.com (Jan 2024). '
            'access_token is cached post-auth.'
        ),
    ),
    # 9. Huawei FusionSolar Northbound API -- VERIFIED: base_url=None correct.
    IntegrationProvider(
        code='huawei_fusionsolar',
        name='Huawei FusionSolar Northbound API',
        provider='huawei',
        category='Smart PV / cloud northbound API',
        auth_mode='northbound_api',
        base_url=None,
        healthcheck_endpoint='/thirdData/getStationList',
        sync_endpoint='/thirdData/getStationRealKpi',
        required_fields=('base_url', 'username', 'password', 'system_code'),
        optional_fields=('station_dn',),
        mapping_schema={
            'solar_power': 'data.ongrid_power',
            'battery_soc': 'data.battery_soc',
            'grid_power': 'data.grid_power',
            'home_load': 'data.load_power',
            'daily_production': 'data.day_power',
            'total_production': 'data.total_power',
        },
        docs_url='https://support.huawei.com/enterprise/en/doc/EDOC1100440661/253d3ba3/obtaining-northbound-api-documents',
        maturity='provider-ready',
        notes_en='Requires Northbound access enabled from the FusionSolar company account.',
    ),
    # 10. Sungrow iSolarCloud API
    # FIX: Notes updated with verified regional gateway URLs.
    # INFO: AU=augateway.isolarcloud.com, EU=gateway-eu.isolarcloud.com
    IntegrationProvider(
        code='sungrow_isolarcloud',
        name='Sungrow iSolarCloud API',
        provider='sungrow',
        category='Cloud monitoring / OAuth API',
        auth_mode='oauth2',
        base_url='https://gateway.isolarcloud.com',
        healthcheck_endpoint='/openapi/getPowerStationList',
        sync_endpoint='/openapi/getPowerStationRealKpi',
        required_fields=('app_key', 'access_token', 'station_id', 'region'),
        optional_fields=('app_secret', 'refresh_token'),
        mapping_schema={
            'solar_power': 'result_data.p83022',
            'battery_soc': 'result_data.p13141',
            'grid_power': 'result_data.p83118',
            'home_load': 'result_data.load_power',
            'daily_production': 'result_data.day_power',
            'total_production': 'result_data.total_power',
        },
        docs_url='https://developer-api.isolarcloud.com/',
        maturity='provider-ready',
        notes_en=(
            'Base URL is region-specific: '
            'Global=gateway.isolarcloud.com, '
            'AU=augateway.isolarcloud.com, '
            'EU=gateway-eu.isolarcloud.com. '
            'Adapter must select correct gateway from region field.'
        ),
    ),
    # 11. GoodWe SEMS OpenAPI
    # FIX: token added to optional_fields (cached after CrossLogin auth).
    # INFO: Auth via CrossLogin at semsportal.com; regional base URLs confirmed.
    IntegrationProvider(
        code='goodwe_sems',
        name='GoodWe SEMS OpenAPI',
        provider='goodwe',
        category='SEMS organization cloud API',
        auth_mode='organization_api',
        base_url=None,
        healthcheck_endpoint='/api/v1/PowerStation/GetMonitorDetailByPowerstationId',
        sync_endpoint='/api/v1/PowerStation/GetMonitorDetailByPowerstationId',
        required_fields=('base_url', 'account', 'password', 'powerstation_id'),
        optional_fields=('org_id', 'token'),
        mapping_schema={
            'solar_power': 'data.kpi.power',
            'battery_soc': 'data.inverter.batterySoc',
            'grid_power': 'data.kpi.gridPower',
            'home_load': 'data.kpi.loadPower',
            'daily_production': 'data.kpi.powerDay',
            'total_production': 'data.kpi.powerTotal',
        },
        docs_url='https://community.goodwe.com/static/images/2024-08-20597794.pdf',
        maturity='provider-ready',
        notes_en=(
            'Auth via CrossLogin: POST semsportal.com/api/v1/Common/CrossLogin. '
            'Regional base URLs: EU=eu.semsportal.com, HK=hk.semsportal.com, '
            'Global=semsportal.com. '
            'API access usually limited to organization accounts.'
        ),
    ),
    # 12. Growatt Open API v1
    # CRITICAL FIX: base_url was 'https://server.growatt.com' (legacy password-based API).
    # Correct Open API base: https://openapi.growatt.com (token-based, confirmed).
    # FIX: endpoints updated to match Open API v1 naming.
    # Regional: CN=openapi-cn.growatt.com, US=openapi-us.growatt.com, AU=openapi-au.growatt.com
    IntegrationProvider(
        code='growatt_v1',
        name='Growatt Open API v1',
        provider='growatt',
        category='Cloud monitoring API',
        auth_mode='api_token',
        base_url='https://openapi.growatt.com',
        healthcheck_endpoint='/plant_list_v1',
        sync_endpoint='/plant_energy_v1',
        required_fields=('api_token', 'plant_id'),
        optional_fields=('user_id', 'region'),
        mapping_schema={
            'solar_power': 'data.current_power',
            'daily_production': 'data.today_energy',
            'total_production': 'data.total_energy',
            'status_text': 'error_msg',
        },
        docs_url='https://growatt.pl/wp-content/uploads/2020/01/Growatt-Server-API-Guide.pdf',
        maturity='provider-ready',
        notes_en=(
            'Official Growatt Open API (token-based v1). '
            'Regional: EU/Global=openapi.growatt.com, CN=openapi-cn.growatt.com, '
            'US=openapi-us.growatt.com, AU=openapi-au.growatt.com. '
            'Token via ShinePhone > Settings > Account Management > API Key.'
        ),
    ),
    # 13. Shelly Gen2+ (Local RPC API)
    # NOTE: Listed in INTEGRATIONS_SUPPORTED_PROVIDERS.md but was MISSING from registry.
    # Shelly Gen2 uses RPC over HTTP (POST /rpc or GET /rpc/Method.Name).
    # Auth token set in Shelly dashboard under Settings > Authentication.
    IntegrationProvider(
        code='shelly_gen2',
        name='Shelly Gen2+ Local API',
        provider='shelly',
        category='Local smart-load / energy meter',
        auth_mode='local_network',
        base_url='http://{host}/rpc',
        healthcheck_endpoint='/Shelly.GetStatus',
        sync_endpoint='/Switch.GetStatus',
        required_fields=('host',),
        optional_fields=('auth_token', 'switch_id', 'em_id'),
        mapping_schema={
            'current_power': 'apower',
            'voltage': 'voltage',
            'current': 'current',
            'daily_energy': 'aenergy.total',
            'relay_state': 'output',
        },
        docs_url='https://shelly-api-docs.shelly.cloud/gen2/',
        notes_en=(
            'RPC over HTTP: GET http://{host}/rpc/Shelly.GetStatus. '
            'For energy meters use /EM.GetStatus; for relays use /Switch.GetStatus. '
            'Auth token optional; set in device Settings > Authentication.'
        ),
    ),
    # 14. Solcast Solar Forecast API
    # High-accuracy rooftop PV forecast and irradiance data.
    # Free tier: 10 API calls/day. Paid plans for higher frequency.
    IntegrationProvider(
        code='solcast',
        name='Solcast Solar Forecast API',
        provider='solcast',
        category='Solar irradiance / PV power forecast',
        auth_mode='api_key',
        base_url='https://api.solcast.com.au',
        healthcheck_endpoint='/rooftop_sites',
        sync_endpoint='/rooftop_sites/{resource_id}/forecasts',
        required_fields=('api_key', 'resource_id'),
        optional_fields=('hours', 'period', 'format'),
        mapping_schema={
            'pv_estimate': 'forecasts.0.pv_estimate',
            'pv_estimate10': 'forecasts.0.pv_estimate10',
            'pv_estimate90': 'forecasts.0.pv_estimate90',
            'period_end': 'forecasts.0.period_end',
        },
        docs_url='https://docs.solcast.com.au/',
        notes_en=(
            'API key sent as Authorization: Bearer {api_key} header. '
            'resource_id is the rooftop site UUID from Solcast Toolkit. '
            'Also supports /estimated_actuals endpoint for live data. '
            'Free tier: 10 calls/day; commercial plans available.'
        ),
    ),
    # 15. Tuya Smart IoT Platform
    # Cloud API for smart loads, plugs, switches, and energy monitoring devices.
    # Regional base URLs vary; adapter must resolve from region field.
    IntegrationProvider(
        code='tuya_iot',
        name='Tuya Smart IoT Platform',
        provider='tuya',
        category='Smart loads / IoT device control',
        auth_mode='oauth2',
        base_url='https://openapi.tuyaeu.com',
        healthcheck_endpoint='/v1.0/iot-03/devices/{device_id}',
        sync_endpoint='/v1.0/iot-03/devices/{device_id}/status',
        required_fields=('client_id', 'client_secret', 'device_id', 'region'),
        optional_fields=('access_token',),
        mapping_schema={
            'switch_state': 'result.0.value',
            'current_power': 'result.cur_power.value',
            'current': 'result.cur_current.value',
            'voltage': 'result.cur_voltage.value',
            'daily_energy': 'result.add_ele.value',
        },
        docs_url='https://developer.tuya.com/en/docs/iot/open-apis',
        maturity='provider-ready',
        notes_en=(
            'Regional base URLs: EU=openapi.tuyaeu.com, US=openapi.tuyaus.com, '
            'CN=openapi.tuyacn.com, IN=openapi.tuyain.com. '
            'Auth: POST /v1.0/token with client_id + sign (HMAC-SHA256). '
            'Device commands via POST /v1.0/iot-03/devices/{id}/commands.'
        ),
    ),
    # 16. Octopus Energy API (UK)
    # Real-time tariff rates, smart meter consumption, agile pricing.
    # REST API uses HTTP Basic Auth with api_key as username.
    IntegrationProvider(
        code='octopus_energy',
        name='Octopus Energy API',
        provider='octopus',
        category='UK smart tariff / electricity data',
        auth_mode='api_key',
        base_url='https://api.octopus.energy/v1',
        healthcheck_endpoint='/accounts/{account_number}',
        sync_endpoint='/electricity-meter-points/{mpan}/meters/{serial_number}/consumption',
        required_fields=('api_key', 'account_number'),
        optional_fields=('mpan', 'meter_serial', 'tariff_code', 'product_code'),
        mapping_schema={
            'consumption': 'results.0.consumption',
            'interval_start': 'results.0.interval_start',
            'interval_end': 'results.0.interval_end',
            'unit_rate': 'unit_rate_inc_vat',
            'standing_charge': 'standing_charge_inc_vat',
        },
        docs_url='https://developer.octopus.energy/',
        maturity='provider-ready',
        notes_en=(
            'HTTP Basic Auth: api_key as username, empty password. '
            'GraphQL API also available at /v1/graphql for richer queries. '
            'Products endpoint: /v1/products/{product_code}/electricity-tariffs/{tariff_code}/. '
            'Primarily UK market; Agile tariff gives half-hourly price data.'
        ),
    ),
    # 17. Sonnen Battery Local API v2
    # Local LAN API for sonnenbatterie home storage systems.
    # Auth token found in sonnen dashboard under Software Integration.
    IntegrationProvider(
        code='sonnen_local',
        name='Sonnen Battery Local API v2',
        provider='sonnen',
        category='Local battery / home energy storage',
        auth_mode='local_network',
        base_url='http://{host}/api/v2',
        healthcheck_endpoint='/status',
        sync_endpoint='/latestdata',
        required_fields=('host',),
        optional_fields=('auth_token',),
        mapping_schema={
            'battery_soc': 'USOC',
            'battery_power': 'Pac_total_W',
            'grid_power': 'GridFeedIn_W',
            'home_load': 'Consumption_W',
            'solar_power': 'Production_W',
            'battery_status': 'BatteryCharging',
        },
        docs_url='https://github.com/Udhold/SonnenBatteryAPI',
        notes_en=(
            'API v2 served at http://{host}/api/v2/. '
            'Auth-Token header required if authentication enabled in dashboard. '
            'Token available under: Sonnen Dashboard > Software-Integration. '
            '/status for system state; /latestdata for real-time power values.'
        ),
    ),
    # 18. PVOutput Community API
    # Upload and retrieve solar PV generation/consumption data.
    # Free donation-based platform; API key + system ID required.
    IntegrationProvider(
        code='pvoutput',
        name='PVOutput Community API',
        provider='pvoutput',
        category='Community PV data sharing / upload',
        auth_mode='api_key',
        base_url='https://pvoutput.org/service/r2',
        healthcheck_endpoint='/getsystem.jsp',
        sync_endpoint='/getstatus.jsp',
        required_fields=('api_key', 'system_id'),
        optional_fields=('date', 'extended'),
        mapping_schema={
            'solar_power': 'v2',
            'daily_production': 'v1',
            'consumption': 'v4',
            'current_load': 'v3',
            'temperature': 'v5',
            'voltage': 'v6',
        },
        docs_url='https://pvoutput.org/help/api_specification.html',
        maturity='provider-ready',
        notes_en=(
            'Auth headers on every request: X-Pvoutput-Apikey + X-Pvoutput-SystemId. '
            'Upload: POST /addstatus.jsp; batch upload: /addbatchstatus.jsp (max 30). '
            'Retrieve: GET /getstatus.jsp. '
            'Donated accounts get higher rate limits and extended data fields.'
        ),
    ),
)



def integration_catalog() -> list[IntegrationProvider]:
    return list(SUPPORTED_INTEGRATIONS)


def integration_by_code(code: str | None) -> IntegrationProvider | None:
    normalized = (code or '').strip().lower()
    for item in SUPPORTED_INTEGRATIONS:
        if item.code == normalized or item.provider == normalized:
            return item
    return None


def seed_supported_integrations(db, DeviceType, overwrite: bool = False) -> dict[str, int]:
    created = 0
    updated = 0
    for provider in SUPPORTED_INTEGRATIONS:
        payload = provider.to_device_type_payload()
        row = DeviceType.query.filter_by(code=payload['code']).first()
        if not row:
            row = DeviceType(**payload)
            db.session.add(row)
            created += 1
            continue
        changed = False
        for key, value in payload.items():
            current = getattr(row, key, None)
            if overwrite or current in (None, ''):
                if current != value:
                    setattr(row, key, value)
                    changed = True
        if changed:
            db.session.add(row)
            updated += 1
    db.session.commit()
    return {'created': created, 'updated': updated, 'total': len(SUPPORTED_INTEGRATIONS)}
