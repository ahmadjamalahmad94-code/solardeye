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
    IntegrationProvider(
        code='deye',
        name='Deye Cloud',
        provider='deye',
        category='Hybrid inverter / solar cloud',
        auth_mode='config',
        base_url='https://eu1-developer.deyecloud.com',
        healthcheck_endpoint='/openapi/v1/station/list',
        sync_endpoint='/openapi/v1/inverter/getInverterRealTimeData',
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
        docs_url='https://eu1-developer.deyecloud.com',
        notes_ar='التكامل الحالي الأساسي للموقع.',
        notes_en='Current primary platform integration.',
    ),
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
        optional_fields=('equipment_id',),
        mapping_schema={
            'solar_power': 'overview.currentPower.power',
            'daily_production': 'overview.lastDayData.energy',
            'monthly_production': 'overview.lastMonthData.energy',
            'total_production': 'overview.lifeTimeData.energy',
            'status_text': 'overview.status',
        },
        docs_url='https://knowledge-center.solaredge.com/en/solaredge-monitoring-api',
        notes_ar='قراءة إنتاج الموقع من SolarEdge Monitoring API.',
        notes_en='Reads site production from the SolarEdge Monitoring API.',
    ),
    IntegrationProvider(
        code='enphase',
        name='Enphase Enlighten API v4',
        provider='enphase',
        category='Microinverter / battery cloud monitoring',
        auth_mode='oauth2',
        base_url='https://api.enphaseenergy.com/api/v4',
        healthcheck_endpoint='/systems/{system_id}/summary',
        sync_endpoint='/systems/{system_id}/summary',
        required_fields=('access_token', 'api_key', 'system_id'),
        optional_fields=('client_id', 'client_secret', 'refresh_token'),
        mapping_schema={
            'solar_power': 'current_power',
            'daily_production': 'energy_today',
            'total_production': 'energy_lifetime',
            'status_text': 'status',
        },
        docs_url='https://developer-v4.enphase.com/docs.html',
        notes_ar='يعتمد على OAuth2 و API key حسب وثائق Enphase.',
        notes_en='Uses OAuth2 bearer token and Enphase application API key.',
    ),
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
        notes_ar='مناسب لأنظمة Victron ESS و VRM.',
        notes_en='Designed for Victron ESS and VRM installations.',
    ),
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
        notes_ar='واجهة محلية مباشرة من الانفيرتر أو Datamanager.',
        notes_en='Local LAN API served directly by the inverter or Datamanager.',
    ),
    IntegrationProvider(
        code='tesla_energy',
        name='Tesla Energy Fleet API',
        provider='tesla',
        category='Powerwall / energy site cloud API',
        auth_mode='oauth2',
        base_url='https://fleet-api.prd.na.vn.cloud.tesla.com',
        healthcheck_endpoint='/api/1/products',
        sync_endpoint='/api/1/energy_sites/{energy_site_id}/live_status',
        required_fields=('access_token', 'energy_site_id'),
        optional_fields=('refresh_token', 'client_id'),
        mapping_schema={
            'solar_power': 'response.solar_power',
            'battery_soc': 'response.percentage_charged',
            'battery_power': 'response.battery_power',
            'grid_power': 'response.grid_power',
            'home_load': 'response.load_power',
            'status_text': 'response.storm_mode_active',
        },
        docs_url='https://developer.tesla.com/docs/fleet-api/endpoints/energy',
        notes_ar='يعتمد على Tesla Fleet API وOAuth.',
        notes_en='Uses Tesla Fleet API OAuth access for energy sites.',
    ),
    IntegrationProvider(
        code='sma',
        name='SMA Data Exchange API',
        provider='sma',
        category='Sunny Portal / cloud API',
        auth_mode='oauth2',
        base_url='https://api.sma.energy',
        healthcheck_endpoint='/plants/{plant_id}',
        sync_endpoint='/plants/{plant_id}/measurements/latest',
        required_fields=('access_token', 'plant_id'),
        optional_fields=('client_id', 'client_secret', 'refresh_token'),
        mapping_schema={
            'solar_power': 'measurements.pv_power',
            'battery_soc': 'measurements.battery_soc',
            'grid_power': 'measurements.grid_power',
            'home_load': 'measurements.load_power',
        },
        docs_url='https://developer.sma.de/sma-apis',
        maturity='provider-ready',
        notes_ar='إطار جاهز لمفاتيح SMA الرسمية؛ قد تختلف مسارات القياسات حسب الصلاحيات.',
        notes_en='Ready for official SMA API credentials; measurement paths can vary by granted product.',
    ),
    IntegrationProvider(
        code='solarman',
        name='SOLARMAN OpenAPI',
        provider='solarman',
        category='Logger / inverter cloud platform',
        auth_mode='oauth2_like',
        base_url='https://globalapi.solarmanpv.com',
        healthcheck_endpoint='/station/v1.0/list',
        sync_endpoint='/station/v1.0/realTime',
        required_fields=('app_id', 'app_secret', 'access_token', 'station_id'),
        optional_fields=('logger_sn', 'device_sn'),
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
        notes_ar='يدعم الكثير من لواقط Solarman/Deye/Solis عبر OpenAPI عند توفر الاعتماد.',
        notes_en='Supports many Solarman/Deye/Solis loggers when OpenAPI access is available.',
    ),
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
        notes_ar='يتطلب تفعيل Northbound من حساب الشركة في FusionSolar.',
        notes_en='Requires Northbound access enabled from the FusionSolar company account.',
    ),
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
        notes_ar='يعتمد على بوابة مطوري Sungrow وتفويض OAuth.',
        notes_en='Uses Sungrow developer portal and OAuth authorization.',
    ),
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
        optional_fields=('org_id',),
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
        notes_ar='متاح غالبًا لحسابات SEMS Organization وليس كل الحسابات الفردية.',
        notes_en='Usually available to SEMS organization accounts, not every individual account.',
    ),
    IntegrationProvider(
        code='growatt_v1',
        name='Growatt Server API v1',
        provider='growatt',
        category='Cloud monitoring API',
        auth_mode='api_token',
        base_url='https://server.growatt.com',
        healthcheck_endpoint='/v1/plant/list',
        sync_endpoint='/v1/plant/data',
        required_fields=('api_token', 'plant_id'),
        optional_fields=('user_id',),
        mapping_schema={
            'solar_power': 'data.current_power',
            'daily_production': 'data.today_energy',
            'total_production': 'data.total_energy',
            'status_text': 'error_msg',
        },
        docs_url='https://growatt.pl/wp-content/uploads/2020/01/Growatt-Server-API-Guide.pdf',
        maturity='provider-ready',
        notes_ar='إطار V1 الرسمي عند توفر token API من Growatt.',
        notes_en='Framework for Growatt V1 API when an API token is available.',
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
