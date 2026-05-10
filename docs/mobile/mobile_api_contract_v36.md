# SolarDeye Mobile API Contract v36

This document describes the current mobile API baseline for building a React Native or Expo client.

## Architecture Rules

- Flask backend and the database are the single source of truth.
- The mobile app must never connect directly to SQLite/PostgreSQL.
- The mobile app must not duplicate solar, scheduler, notification, weather, or energy decision logic.
- Mobile endpoints are JSON APIs. UI templates, Flow Graph, scheduler jobs, and report/PDF rendering are not part of this contract.
- Mobile clients should call backend endpoints and render the returned state.

## Base URL

Use the deployed or local Flask base URL:

```text
http://127.0.0.1:5000
```

All current first-class mobile endpoints use:

```text
/api/mobile/...
```

Some older but usable compatibility endpoints remain under:

```text
/api/v1/...
```

## Auth Model

Mobile auth uses Bearer access tokens plus refresh tokens.

Send authenticated requests with:

```http
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json
```

Access tokens are stateless and expire naturally. Refresh tokens are stored server-side and can be revoked.

`POST /api/mobile/account/logout-all` revokes refresh tokens only. It does not claim already-issued stateless access tokens are revoked immediately.

## Response Envelope

Successful responses use:

```json
{
  "ok": true,
  "data": {},
  "meta": {},
  "errors": []
}
```

Error responses use:

```json
{
  "ok": false,
  "code": "error_code",
  "message": "Readable error",
  "errors": []
}
```

Common errors:

- `auth_required`
- `invalid_token`
- `invalid_json`
- `missing_field`
- `unsupported_field`
- `invalid_boolean`
- `invalid_number`
- `invalid_device_id`
- `device_not_found`
- `load_not_found`
- `notification_not_found`
- `invalid_credentials`
- `invalid_refresh_token`
- `invalid_current_password`
- `weak_password`
- `method_not_allowed`
- `not_found`

## Auth Endpoints

### `POST /api/mobile/auth/register`

Creates a subscriber/mobile user.

Request summary:

```json
{
  "username": "subscriber1",
  "email": "subscriber@example.com",
  "password": "YOUR_STRONG_PASSWORD_HERE",
  "full_name": "Subscriber Name",
  "preferred_language": "ar",
  "country": "PS",
  "city": "Gaza",
  "timezone": "Asia/Hebron",
  "phone_country_code": "+970",
  "phone_number": "599043337",
  "has_energy_system": true,
  "preferred_device_type": "deye",
  "device_label": "iPhone"
}
```

Response summary:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {},
  "onboarding": {}
}
```

### `POST /api/mobile/auth/login`

Login by username or email.

Request:

```json
{
  "username": "subscriber1",
  "password": "YOUR_STRONG_PASSWORD_HERE",
  "device_label": "Pixel"
}
```

Response includes `access_token` and `refresh_token`.

### `POST /api/mobile/auth/refresh`

Request:

```json
{
  "refresh_token": "..."
}
```

Response returns a fresh `access_token`.

### `POST /api/mobile/auth/logout`

Revokes one refresh token when supplied.

Request:

```json
{
  "refresh_token": "..."
}
```

### `GET /api/mobile/auth/me`

Returns a safe user summary for the Bearer token.

## Bootstrap and Catalogs

### `GET /api/mobile/bootstrap`

Authenticated bootstrap for the mobile app.

Response includes:

- `version`
- `auth_strategy`
- `user`
- `subscription`
- `onboarding`
- `devices`
- `permissions`
- `navigation`
- `providers`
- `location_catalog`

No secrets are returned.

### `GET /api/mobile/location-catalog`

Returns country, city, timezone, and phone-prefix metadata.

Response includes:

- `countries`
- `phone_prefixes`
- `cities`
- `timezones`
- `timezone_groups`

### `GET /api/mobile/device-providers`

Returns provider metadata only.

Sensitive provider fields are marked with:

```json
{ "secret": true }
```

Secret values are not returned.

## Profile and Onboarding

### `GET /api/mobile/profile`

Returns:

- `user`
- `onboarding`
- `subscription`

### `PATCH /api/mobile/profile`

Updates safe profile fields:

- `full_name`
- `email`
- `phone_country_code`
- `phone_number`
- `country`
- `country_code`
- `city`
- `timezone`
- `preferred_language`

Malformed JSON returns `invalid_json`.

### `GET /api/mobile/onboarding`

Returns onboarding state, profile state, system basics, and selected/current device state.

### `POST/PATCH /api/mobile/onboarding`

Updates safe onboarding fields:

- `onboarding_step` or `step`
- `onboarding_completed` or `completed`
- `selected_device_id` or `current_device_id`
- `preferred_device_type`
- `system_basics.battery_capacity_kwh`
- `system_basics.battery_reserve_percent`

Boolean values are parsed strictly.

## Account and Security

### `GET /api/mobile/account`

Returns safe account summary:

- `user`
- `role`
- `subscription`
- `devices`
- `capabilities`

No password hash, token value, API key, provider credential, or raw secret is returned.

### `PATCH /api/mobile/account`

Updates the same safe fields as profile. Unsupported fields return `unsupported_field`.

### `POST /api/mobile/account/change-password`

Request:

```json
{
  "current_password": "old-password",
  "new_password": "new-password"
}
```

Errors:

- `missing_field`
- `invalid_current_password`
- `weak_password`
- `invalid_json`

Passwords are never returned.

### `POST /api/mobile/account/logout-all`

Revokes all server-stored refresh tokens for the authenticated user.

Response summary:

```json
{
  "supported": true,
  "revoked_refresh_tokens": 2,
  "access_tokens_revoked": false,
  "access_token_note": "Access tokens are stateless and expire automatically."
}
```

### `DELETE /api/mobile/account`

Account deletion is not implemented.

Response uses:

```json
{
  "code": "account_deletion_not_supported",
  "supported": false
}
```

## Devices

### `GET /api/mobile/devices`

Lists authenticated user's devices.

Response includes:

- `items`
- `total`
- `active`
- `selected_device_id`
- `max_devices`

No credentials or provider secrets are returned.

### `POST /api/mobile/devices`

Creates a setup-required device using safe fields:

- `name`
- `device_type` / `provider_code` / `provider` / `api_provider`
- `timezone`
- `plant_name`
- `safe_settings.battery_capacity_kwh`
- `safe_settings.battery_reserve_percent`

Subscription device limit is enforced.

### `GET /api/mobile/devices/{device_id}`

Returns one owned device plus latest stored reading summary.

Foreign devices return `device_not_found`.

### `PATCH /api/mobile/devices/{device_id}`

Updates safe editable fields only. `is_active` is not editable here.

### `DELETE /api/mobile/devices/{device_id}`

Soft-deactivates the device. It does not delete readings.

## Dashboard, Live, and Feed

### `GET /api/mobile/dashboard`

Returns selected-device or all-devices dashboard data using stored backend readings.

Query:

```text
?device_id=123
?device_id=all
?scope=all
?limit=48
```

Response includes:

- `scope`
- `device`
- `devices`
- `latest`
- `cards`
- `feed`
- `fleet` when all-devices mode is used

### `GET /api/mobile/live`

Returns lightweight current summary:

- `scope`
- `device`
- `latest`
- `cards`
- `empty`
- `generated_at`

### `GET /api/mobile/dashboard/feed`

Paginated reading feed, newest first.

Query:

```text
?page=1&page_size=50
```

`page_size` is bounded by the backend.

## Loads and Controls

### `GET /api/mobile/loads`

Lists user loads. Optional device filter:

```text
?device_id=123
?device_id=all
```

### `POST /api/mobile/loads`

Creates a saved load preference.

Safe fields:

- `name`
- `power_w` / `wattage` / `watts` / `power`
- `priority`
- `device_id`
- `is_enabled` / `enabled`

### `GET /api/mobile/loads/{load_id}`

Returns one owned load.

### `PATCH /api/mobile/loads/{load_id}`

Updates safe fields only.

### `DELETE /api/mobile/loads/{load_id}`

Deletes the saved load row following existing web behavior. It does not delete readings, device history, scheduler jobs, or hardware state.

### `POST /api/mobile/loads/{load_id}/toggle`

Persists enabled/disabled preference only.

It does not send commands to inverter, relay, scheduler, or hardware.

### `GET /api/mobile/loads/recommendations`

Currently deferred. Returns:

```json
{
  "available": false,
  "reason": "mobile_recommendations_deferred",
  "items": []
}
```

## Notifications

### `GET /api/mobile/notifications/settings`

Returns current notification settings and rules.

Important: notification settings are currently global/account-platform scoped. They are not per-device settings because the current settings storage has no device-specific schema.

No Telegram bot token, SMS API key, API secret, provider credential, or raw secret is returned.

### `PATCH /api/mobile/notifications/settings`

Updates safe existing settings only.

Supports:

- `settings`
- `rules`

Unknown fields return `unsupported_field`.

Threshold channel values are:

```json
"telegram" | "sms" | "both" | "none"
```

Night threshold keys must be numeric watt thresholds. Charge and discharge threshold keys must be numeric percentages from `0` to `100`.

Invalid threshold keys return `invalid_threshold`.

This endpoint does not send notifications and does not touch scheduler/dispatch/dedup logic.

### `GET /api/mobile/notifications`

Paginated notification center events for the authenticated user.

Query:

```text
?page=1&page_size=20
```

### `POST /api/mobile/notifications/{notification_id}/read`

Marks one owned notification as read.

### `POST /api/mobile/notifications/read-all`

Marks all user-visible unread notifications as read for the authenticated user only.

## Support

Support is currently usable under the compatibility namespace:

```text
/api/v1/support/...
```

Endpoints:

- `GET /api/v1/support/cases`
- `POST /api/v1/support/cases`
- `GET /api/v1/support/cases/{kind}/{case_id}`
- `POST /api/v1/support/cases/{kind}/{case_id}/reply`
- `POST /api/v1/support/cases/{kind}/{case_id}/reopen`
- `GET /api/v1/support/canned-replies`

Known contract note: support may later move or mirror to `/api/mobile/support`, but the current stable implementation is `/api/v1/support`.

## Legacy Compatibility

Current compatibility endpoints include:

- `GET /api/v1/mobile/health`
- `GET /api/v1/mobile/bootstrap`
- `GET /api/v1/mobile/summary`
- `GET /api/v1/mobile/notifications`
- `/api/v1/auth/...`
- `/api/v1/support/...`

Prefer `/api/mobile/...` for new mobile app work when an equivalent endpoint exists.

## Safety and Deferred Features

Ready:

- Auth/register/login/refresh/logout/me.
- Profile, location, onboarding, account security.
- Device list/create/update/detail/deactivate.
- Dashboard/live/feed read-only data.
- Loads CRUD and persisted enable/disable preference.
- Notification settings and notification center read state.
- Support through `/api/v1/support`.

Deferred or unsupported:

- Direct DB access from mobile.
- Direct inverter/hardware control.
- Scheduler manipulation.
- Provider sync/test connection from mobile.
- Telegram/SMS test sends from passive endpoints.
- Per-device notification settings.
- Mobile load recommendations.
- Account deletion.
- Report/PDF generation APIs.

## Secret Handling

Never store or display raw secrets in the mobile app beyond initial user entry.

The backend must not return:

- `password_hash`
- access token values except through auth responses
- refresh token values except through auth/register/login responses
- Telegram bot token
- SMS API key
- provider credentials
- raw `credentials_json`
- raw unsafe settings

## Client Implementation Notes

- Keep access tokens in secure memory/storage appropriate for the mobile platform.
- Store refresh tokens in secure storage such as Keychain/Keystore through Expo SecureStore or equivalent.
- Retry once with refresh on `invalid_token`, then force login if refresh fails.
- Treat `account_restricted` and `can_write` from auth payloads as UI state.
- Do not call destructive or mutating endpoints from background refresh.
- Use explicit user action for mutating operations.
