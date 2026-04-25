# Heavy v9.0 — Global Platform Rebuild, Integrations & Deep Hardening

## Scope
Heavy v9.0 focuses on deep platform review, architecture splitting, global energy integrations, scheduler reliability, English/Arabic language cleanup, and UI hardening.

## Key changes

### Scheduler reliability
- Fixed `has_request_context` NameError in `app/blueprints/main.py`.
- Scheduler now calls `sync_now_internal(trigger='auto')` for auto-sync jobs.
- Services Health renders service names/messages through the dedicated service monitor translator.

### Architecture split
- Added `app/blueprints/integrations.py` for energy integrations.
- Added `app/blueprints/platform.py` for platform review and backup/recovery routes.
- Added/kept `app/blueprints/admin_ops.py` for v9 admin operations: subscribers, services health, devices.
- `main.py` is still large but now has fewer direct admin/platform responsibilities. Continue moving support, billing, reports, and portal routes in future v9.x patches.

### Energy integrations
- Added `app/services/energy_integrations.py` with provider blueprints:
  - Deye Cloud
  - SolarEdge Monitoring API
  - Enphase Enlighten API
  - Victron VRM API
  - Fronius Solar API Local
  - SMA Sunny Portal / ennexOS API
  - Tesla Fleet API Energy Sites
  - Huawei FusionSolar Northbound
  - Shelly Gen2+ Local RPC
- Added a redesigned Integrations Hub at `/admin/integrations`.
- Added safe device connection tests for configured providers.
- Non-Deye sync now has a generic read-only snapshot path where the provider endpoint is simple and configured.
- OAuth/vendor-specific providers are added as professional blueprints and do not enable risky commands.

### UI hardening
- Added v9 CSS scroll locks for cards, sections, service cards, provider cards, thread messages, and KPI text.
- Long content now scrolls inside cards instead of stretching the page.
- Added Integration Hub cards and stable responsive layouts.
- Kept previous v7/v8 classes active for compatibility.

### Language cleanup
- Added service/status translation entries for scheduler, auto-sync, heartbeat, and failure messages.
- Services Health now avoids raw Arabic in English mode for scheduler/job messages.
- i18n audit reports zero possible untranslated legacy Arabic templates.

### Platform review
- Enhanced `app/services/platform_audit.py`:
  - Audits templates, CSRF, inline styles, sensitive render patterns, Python file size, route distribution, blueprint count, and architecture split score.
  - Reduced false positives around CSRF token rendering.

## Validation performed
- Python compile: OK
- Jinja template parse: OK
- JavaScript syntax check: OK
- i18n audit: 0 possible untranslated legacy Arabic templates
- CSRF direct form coverage: 59/59 POST forms
- Secret-like file scan: 0 hard-coded obvious secrets detected
- Platform audit summary: 52 templates, 36 Python files, 10 blueprints, 81 routes, 0 high-risk templates

## Important after deployment
1. Hard refresh the browser.
2. Open `/admin/services-health` and verify `deye_auto_sync` heartbeat changes from failed to OK after the next scheduler run.
3. Open `/admin/integrations`, seed provider blueprints, then test a configured device.
4. Review `/admin/platform-review` for the latest static health score.
5. Continue reviewing service-by-service as planned.
