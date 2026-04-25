# Supported Energy Integration Catalog — Heavy v9.0

The v9 integration catalog is intentionally read-first. Remote control commands must not be enabled until read telemetry is stable and the owner has granted explicit permissions.

| Provider | Code | Current support | Required setup |
|---|---:|---|---|
| Deye Cloud | `deye` | Active sync through existing Deye client | Deye OpenAPI credentials |
| SolarEdge Monitoring API | `solaredge_cloud` | Read blueprint + HTTP sync mapping | API key + site ID |
| Enphase Enlighten API v4 | `enphase_enlighten` | OAuth/API-key read blueprint | OAuth token + Enphase app key + system ID |
| Victron VRM API | `victron_vrm` | VRM read blueprint | Access token + installation ID |
| Fronius Solar API | `fronius_local` | Local LAN read mapping | Local inverter/Datamanager URL |
| Tesla Energy Fleet API | `tesla_energy` | Energy-site read blueprint | OAuth token + energy site ID |
| SMA API | `sma_cloud` | Provider-ready blueprint | SMA OAuth delegation |
| Huawei FusionSolar | `huawei_fusionsolar` | Northbound-ready blueprint | Northbound account + system code |
| SOLARMAN OpenAPI | `solarman_openapi` | Provider-ready blueprint | OpenAPI app/access token + station ID |
| Sungrow iSolarCloud | `sungrow_isolarcloud` | Provider-ready blueprint | Developer app + OAuth token + station ID |
| GoodWe SEMS | `goodwe_sems` | Organization API-ready blueprint | SEMS organization API access |
| Growatt v1 | `growatt_v1` | Token API-ready blueprint | Official API token + plant ID |
| Shelly Gen2+ | `shelly_gen2` | Local smart-load/meter read mapping | Local device URL |

## Credential safety

Credentials are stored in `AppDevice.credentials_json` or environment configuration and should never be displayed directly in templates. v9 cards and tables use masked identifiers and scroll-safe containers.
