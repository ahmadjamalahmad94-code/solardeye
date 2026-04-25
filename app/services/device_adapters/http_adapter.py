from __future__ import annotations

import json
from urllib.parse import urlencode

import requests

from .base import BaseDeviceAdapter, DeviceSnapshot
from ..integration_registry import integration_by_code


def _loads(value, fallback=None):
    if fallback is None:
        fallback = {}
    if not value:
        return fallback
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _json_path(data, path: str | None, default=None):
    if not path:
        return default
    cur = data
    for part in str(path).split('.'):
        if part == '':
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except Exception:
                return default
        elif isinstance(cur, dict):
            if part in cur:
                cur = cur.get(part)
            else:
                return default
        else:
            return default
    return cur


def _float(value, default=0.0):
    if value in (None, ''):
        return default
    try:
        return float(value)
    except Exception:
        return default


class UniversalHttpDeviceAdapter(BaseDeviceAdapter):
    """Conservative provider adapter for cloud/local energy APIs.

    The adapter intentionally uses read-only endpoints and short timeouts. Each
    provider is configured through DeviceType mapping_schema_json, so new APIs can
    be added without changing the core sync pipeline.
    """

    device_type = 'universal_http'

    def _settings(self):
        settings = _loads(getattr(self.device, 'settings_json', None))
        credentials = _loads(getattr(self.device, 'credentials_json', None))
        merged = {}
        merged.update(settings)
        merged.update(credentials)
        for attr in ('api_base_url', 'external_device_id', 'station_id', 'plant_name', 'device_uid'):
            val = getattr(self.device, attr, None)
            if val not in (None, ''):
                merged[attr] = val
        return merged

    def _url(self, provider, endpoint: str | None, settings: dict) -> str:
        base = (getattr(self.device, 'api_base_url', None) or provider.base_url or settings.get('base_url') or '').strip()
        if not base:
            raise ValueError('Missing integration base URL')
        if '{host}' in base:
            host = settings.get('host') or settings.get('inverter_host') or settings.get('ip')
            if not host:
                raise ValueError('Missing local device host')
            base = base.format(host=host)
        endpoint = endpoint or provider.sync_endpoint or ''
        for key, value in settings.items():
            endpoint = endpoint.replace('{' + str(key) + '}', str(value))
            base = base.replace('{' + str(key) + '}', str(value))
        if endpoint and not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        return base.rstrip('/') + endpoint

    def _headers(self, provider, settings):
        headers = {'Accept': 'application/json', 'User-Agent': 'SolarDeye/9.0'}
        token = settings.get('access_token') or settings.get('api_token') or settings.get('bearer_token')
        if provider.auth_mode in {'oauth2', 'bearer_token', 'api_token'} and token:
            headers['Authorization'] = f'Bearer {token}'
        if provider.code == 'enphase' and settings.get('api_key'):
            headers['key'] = str(settings.get('api_key'))
        if settings.get('api_key_header') and settings.get('api_key'):
            headers[str(settings.get('api_key_header'))] = str(settings.get('api_key'))
        return headers

    def _params(self, provider, settings):
        params = {}
        if provider.code == 'solaredge' and settings.get('api_key'):
            params['api_key'] = settings.get('api_key')
        if provider.code == 'growatt_v1' and settings.get('api_token'):
            params['token'] = settings.get('api_token')
        if provider.code == 'growatt_v1' and settings.get('plant_id'):
            params['plant_id'] = settings.get('plant_id')
        if provider.code in {'huawei_fusionsolar', 'sungrow_isolarcloud', 'solarman'}:
            # These providers often require signed/authenticated POST flows. The
            # generic client remains GET-only unless the installer supplies a
            # custom query string in settings_json.
            pass
        extra = settings.get('query_params')
        if isinstance(extra, dict):
            params.update(extra)
        return params

    def fetch_latest(self) -> DeviceSnapshot:
        provider = integration_by_code(getattr(self.device, 'api_provider', None) or getattr(self.device, 'device_type', None))
        if not provider:
            raise ValueError(f'Unsupported integration provider: {getattr(self.device, "api_provider", "") or getattr(self.device, "device_type", "")}')
        settings = self._settings()
        url = self._url(provider, provider.sync_endpoint, settings)
        params = self._params(provider, settings)
        response = requests.get(url, headers=self._headers(provider, settings), params=params, timeout=12)
        response.raise_for_status()
        raw = response.json()
        mapping = _loads(getattr(self.device, 'mapping_schema_json', None), None) if hasattr(self.device, 'mapping_schema_json') else None
        mapping = mapping or provider.mapping_schema
        snapshot = DeviceSnapshot(
            plant_id=str(settings.get('plant_id') or settings.get('site_id') or settings.get('system_id') or settings.get('station_id') or settings.get('energy_site_id') or getattr(self.device, 'station_id', '') or ''),
            plant_name=str(getattr(self.device, 'plant_name', '') or settings.get('plant_name') or provider.name),
            solar_power=_float(_json_path(raw, mapping.get('solar_power'))),
            home_load=_float(_json_path(raw, mapping.get('home_load'))),
            battery_soc=_float(_json_path(raw, mapping.get('battery_soc'))),
            battery_power=_float(_json_path(raw, mapping.get('battery_power'))),
            grid_power=_float(_json_path(raw, mapping.get('grid_power'))),
            inverter_power=_float(_json_path(raw, mapping.get('inverter_power'))),
            daily_production=_float(_json_path(raw, mapping.get('daily_production'))),
            monthly_production=_float(_json_path(raw, mapping.get('monthly_production'))),
            total_production=_float(_json_path(raw, mapping.get('total_production'))),
            status_text=str(_json_path(raw, mapping.get('status_text'), 'ok') or 'ok'),
            raw={'provider': provider.code, 'url': url.split('?')[0], 'raw': raw},
        )
        return snapshot

    def healthcheck(self) -> dict:
        provider = integration_by_code(getattr(self.device, 'api_provider', None) or getattr(self.device, 'device_type', None))
        if not provider:
            raise ValueError('Unsupported provider')
        settings = self._settings()
        endpoint = provider.healthcheck_endpoint or provider.sync_endpoint
        url = self._url(provider, endpoint, settings)
        response = requests.get(url, headers=self._headers(provider, settings), params=self._params(provider, settings), timeout=10)
        return {'ok': response.ok, 'status_code': response.status_code, 'url': url.split('?')[0]}
