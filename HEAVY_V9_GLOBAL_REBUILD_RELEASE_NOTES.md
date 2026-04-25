# Heavy v9.0 — Global-Grade Platform Rebuild

This release is a structural and quality jump after the v8 review pass. It focuses on architecture separation, global energy-device integrations, scheduler reliability, full bilingual UI cleanup, and stricter UI containment.

## 1. Architecture split

`main.py` remains as the compatibility route container, but high-risk operational areas are now split into dedicated blueprints registered before the legacy main blueprint:

- `app/blueprints/platform.py`
  - `/admin/platform-review`
  - `/admin/backups`
  - backup download routes
- `app/blueprints/integrations.py`
  - `/admin/integrations`
  - integration device test route
- `app/blueprints/admin_ops.py`
  - `/admin/subscribers`
  - `/admin/services-health`

This keeps old links working while serving key pages from smaller modules.

## 2. Scheduler fix

Fixed the `has_request_context` failure that broke `deye_auto_sync` by ensuring it is imported and used safely. Scheduler heartbeat labels now display user-facing names like `Auto Sync` instead of raw internal keys.

## 3. Services Health polish

- Removed raw labels such as `deye_auto_sync` from prominent UI.
- Service messages are translated in English mode.
- `فشلت المهمة:` becomes `Job failed:`.
- Recent scheduler heartbeat is considered valid even if APScheduler is not visible in the current worker.

## 4. Global energy integrations

Added a professional integrations hub and provider catalog for:

- Deye Cloud
- SolarEdge Monitoring API
- Enphase Enlighten API v4
- Victron VRM API
- Fronius Solar API local/LAN
- Tesla Energy Fleet API
- SMA Data Exchange / Sunny Portal-ready blueprint
- Huawei FusionSolar Northbound-ready blueprint
- SOLARMAN OpenAPI
- Sungrow iSolarCloud API
- GoodWe SEMS OpenAPI
- Growatt Server API v1
- Shelly Gen2+ Local RPC for smart load/meter readings

The hub supports one-click provider seeding, registered device types, credential-safe testing, and masked display.

## 5. Non-Deye sync framework

`sync_now_internal()` now supports non-Deye devices through `app/services/energy_integrations.py` using provider mappings. Deye keeps its existing proven client path.

## 6. English/Arabic cleanup

Expanded translation coverage for:

- Subscribers CRM
- Services Health
- Scheduler messages
- Integration Hub
- backup/recovery actions
- device-provider labels

The i18n audit reports zero untranslated legacy Arabic templates.

## 7. UI containment

Added v9 CSS hardening so cards, tables, long names, raw JSON blocks, and provider cards do not expand beyond page bounds. Long content now scrolls internally.

## 8. Validation performed

- Python compile: OK
- Jinja parse: OK
- JavaScript syntax: OK
- i18n audit: OK
- `__pycache__`, `.pyc`, `.env`, and local DB files removed from package

Runtime was not executed in the sandbox because Flask dependencies are not installed here. Validate on Render after deployment.

## 9. Post-deploy checks

1. `/admin/services-health`
2. `/admin/integrations`
3. `/admin/subscribers?lang=en`
4. `/admin/platform-review`
5. `/sync-now` or manual sync for Deye device
6. Integration test for a configured non-Deye device
7. English/Arabic switch from admin and subscriber portals
