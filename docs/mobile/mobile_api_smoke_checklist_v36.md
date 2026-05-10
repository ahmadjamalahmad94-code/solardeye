# SolarDeye Mobile API Smoke Checklist v36

Use this checklist before handing the backend to a mobile app developer or before pushing a mobile-api-complete baseline.

## Environment

Recommended local command:

```powershell
$env:DATABASE_URL="sqlite:///solar_local.db"
python -m flask --app app run
```

Base URL:

```text
http://127.0.0.1:5000
```

## General Rules

- Do not call real external provider sync unless explicitly in a sandbox.
- Do not send real SMS or Telegram messages during smoke tests.
- Do not touch Flow Graph, dashboard templates, scheduler, notification dispatch/dedup, schema/migrations, or report/PDF logic.
- Use a dedicated QA subscriber account.
- Confirm every protected endpoint returns JSON, not HTML redirects.

## Auth Smoke Tests

1. Register a QA user.
   - Endpoint: `POST /api/mobile/auth/register`
   - Expect: `201`, `access_token`, `refresh_token`, safe `user`, `onboarding`.

2. Login with username.
   - Endpoint: `POST /api/mobile/auth/login`
   - Expect: `200`, `access_token`, `refresh_token`.

3. Login with email.
   - Endpoint: `POST /api/mobile/auth/login`
   - Expect: `200`.

4. Invalid login.
   - Expect: `401 invalid_credentials`.

5. Refresh access token.
   - Endpoint: `POST /api/mobile/auth/refresh`
   - Expect: `200`, new `access_token`.

6. Logout one refresh token.
   - Endpoint: `POST /api/mobile/auth/logout`
   - Expect: `ok: true`.

7. Current user.
   - Endpoint: `GET /api/mobile/auth/me`
   - With Bearer: `200`.
   - Without Bearer: `401 auth_required`.

## Profile and Onboarding

1. `GET /api/mobile/profile`
   - Expect: `user`, `onboarding`, `subscription`.
   - Confirm no `password_hash`.

2. `PATCH /api/mobile/profile`
   - Update `full_name`, `phone_country_code`, `phone_number`, `country_code`, `city`, `timezone`, `preferred_language`.
   - Expect: updated values in response.

3. Malformed profile JSON.
   - Expect: `400 invalid_json`.

4. Invalid timezone.
   - Expect: `400 invalid_timezone`.

5. `GET /api/mobile/onboarding`
   - Expect current completion state and system basics.

6. `POST/PATCH /api/mobile/onboarding`
   - Test `completed: false`, `completed: true`, and safe string values like `"false"`.
   - Invalid boolean should return `400 invalid_boolean`.

7. `GET /api/mobile/location-catalog`
   - Confirm countries, phone prefixes, cities, and timezones exist.
   - Confirm examples such as `PS +970`, `SA +966`, `EG +20`, `JO +962`.

8. `GET /api/mobile/device-providers`
   - Confirm provider fields contain `secret: true` metadata for sensitive fields.
   - Confirm no secret values are returned.

## Dashboard, Live, and Feed

1. `GET /api/mobile/dashboard`
   - With Bearer: `200`.
   - Without Bearer: `401 auth_required`.
   - Confirm `scope`, `latest`, `cards`, and `feed`.

2. `GET /api/mobile/dashboard?device_id=all`
   - Expect all-devices scope and optional `fleet`.

3. `GET /api/mobile/dashboard?device_id=<owned_id>`
   - Expect device scope.

4. `GET /api/mobile/dashboard?device_id=<foreign_id>`
   - Expect `404 device_not_found`.

5. `GET /api/mobile/live`
   - Expect lightweight cards only, no feed.

6. `GET /api/mobile/dashboard/feed?page=1&page_size=50`
   - Confirm pagination meta.
   - Confirm page size is bounded.

7. Confirm no endpoint triggers external sync, scheduler, hardware, or dispatch.

## Devices

1. `GET /api/mobile/devices`
   - Expect list, totals, selected device id, max devices.
   - Confirm no credentials, tokens, API keys, or `credentials_json`.

2. `POST /api/mobile/devices`
   - Create a QA device with `name`, `provider_code`, `timezone`.
   - Expect `201`, `connection_status: setup_required`.

3. Device limit.
   - If max devices reached, expect `403 device_limit_reached`.

4. `GET /api/mobile/devices/{id}`
   - Owned device: `200`.
   - Foreign device: `404 device_not_found`.
   - Invalid non-integer id: JSON `404` or route-level JSON handling, not HTML.

5. `PATCH /api/mobile/devices/{id}`
   - Update safe fields only.
   - Try `is_active`; expect `400 unsupported_field`.
   - Malformed JSON: `400 invalid_json`.

6. `DELETE /api/mobile/devices/{id}`
   - Expect soft deactivate: `deleted: false`, `deactivated: true`.
   - Confirm readings are not deleted.

## Loads and Controls

1. `GET /api/mobile/loads`
   - Expect user-owned loads only.

2. `GET /api/mobile/loads?device_id=<owned_id>`
   - Expect device-filtered loads.

3. `GET /api/mobile/loads?device_id=<foreign_id>`
   - Expect `404 device_not_found`.

4. `POST /api/mobile/loads`
   - Create QA load with `name`, `power_w`, `priority`, optional `device_id`.
   - Expect `201`.

5. Invalid load power.
   - Negative, zero, or too large values should return JSON validation errors.

6. `PATCH /api/mobile/loads/{id}`
   - Update safe fields.
   - Unsupported field returns `400 unsupported_field`.

7. `POST /api/mobile/loads/{id}/toggle`
   - Test `is_enabled: false` and string `"false"`.
   - Confirm `executed_hardware_command: false`.
   - Confirm no scheduler/hardware action.

8. `DELETE /api/mobile/loads/{id}`
   - Expect saved load row removed.
   - Confirm no readings or device history are removed.

9. `GET /api/mobile/loads/recommendations`
   - Expect `available: false`, `reason: mobile_recommendations_deferred`.

## Notifications and Settings

1. `GET /api/mobile/notifications/settings`
   - Expect `200`.
   - Confirm `scope: global` or equivalent scope note.
   - Confirm no bot token, SMS API key, API secret, or provider credentials.

2. `PATCH /api/mobile/notifications/settings`
   - Update one safe setting.
   - Unknown field returns `400 unsupported_field`.
   - Malformed JSON returns `400 invalid_json`.

3. Threshold channel values.
   - Test values: `telegram`, `sms`, `both`, `none`.
   - Invalid value returns validation error.

4. Threshold key validation.
   - `rules.night_thresholds.not_a_number` returns `400 invalid_threshold`.
   - `rules.night_thresholds.500` succeeds with valid channel.
   - `rules.charge.abc` returns `400 invalid_threshold`.
   - `rules.charge.101` returns `400 invalid_threshold`.
   - `rules.discharge.-1` returns `400 invalid_threshold`.

5. `GET /api/mobile/notifications?page=1&page_size=20`
   - Expect user-visible notification events only.
   - Confirm pagination meta.

6. `POST /api/mobile/notifications/{id}/read`
   - Owned notification: `200`.
   - Foreign notification: `404 notification_not_found`.

7. `POST /api/mobile/notifications/read-all`
   - Confirm it affects authenticated user's visible notifications only.

8. Confirm no notification send/test/dispatch/scheduler behavior occurs.

## Account and Security

1. `GET /api/mobile/account`
   - Expect user, role, subscription, devices, capabilities.
   - Confirm no `password_hash`, token value, API key, provider credential, or raw secret.

2. `PATCH /api/mobile/account`
   - Update safe profile-style fields only.
   - Try `username`; expect `400 unsupported_field`.
   - Malformed JSON: `400 invalid_json`.

3. `POST /api/mobile/account/change-password`
   - Missing `current_password` or `new_password`: `400 missing_field`.
   - Wrong current password: `401 invalid_current_password`.
   - Weak password: `400 weak_password`.
   - Successful change: old password no longer logs in; new password logs in.
   - Confirm password values are not returned.

4. `POST /api/mobile/account/logout-all`
   - Expect `supported: true`.
   - Confirm refresh token is revoked.
   - Confirm response says `access_tokens_revoked: false`.

5. `DELETE /api/mobile/account`
   - Expect `501 account_deletion_not_supported`.
   - Confirm account still exists.

## Support

Support currently uses `/api/v1/support`.

1. `GET /api/v1/support/cases`
   - Expect user-visible cases only.

2. `POST /api/v1/support/cases`
   - Create QA support case.

3. `GET /api/v1/support/cases/{kind}/{id}`
   - Open created case.

4. `POST /api/v1/support/cases/{kind}/{id}/reply`
   - Send a QA reply.

5. Closed case behavior.
   - Subscriber reply to a closed case should return `409 support_case_closed`.

## JSON Error and Method Checks

For each endpoint group:

- Missing Bearer returns JSON `401 auth_required`.
- Malformed JSON on mutating endpoints returns `400 invalid_json`.
- Unsupported fields return `400 unsupported_field`.
- Wrong methods return JSON `405 method_not_allowed`.
- Unknown `/api/mobile/nope` returns JSON `404 not_found`.

## Ownership Isolation Checks

Create or use two QA users:

- User A
- User B

Confirm:

- User A cannot read User B devices.
- User A cannot update/delete User B devices.
- User A cannot read/update/delete User B loads.
- User A cannot mark User B notifications as read.
- `read-all` affects only User A visible notifications.
- Support cases are filtered to user-visible cases.

## Secret Leakage Checks

Search every response body for:

- `password_hash`
- `credentials_json`
- `api_key`
- `api_secret`
- `bot_token`
- `telegram_token`
- `sms_api_key`
- `refresh_token` outside auth/register/login responses
- provider passwords or tokens

Expected: no secret leakage.

## Protected Systems Checks

After smoke tests, confirm no changes were made to:

- Flow Graph files or markup.
- `app/templates/dashboard.html` interactive hero.
- `app/templates/_live_fleet_rail.html`.
- Scheduler logic.
- Energy calculation logic.
- Notification dispatch/dedup.
- Schema/migrations.
- Report/PDF backend.

Recommended commands:

```powershell
python -m compileall app tests
git diff --check
git diff --name-only
```

Expected for documentation-only work:

```text
docs/mobile/mobile_api_contract_v36.md
docs/mobile/mobile_api_smoke_checklist_v36.md
docs/mobile/mobile_app_build_handoff_v36.md
```
