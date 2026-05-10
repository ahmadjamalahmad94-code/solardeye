# SolarDeye Mobile App Build Handoff v36

This handoff is for building the SolarDeye mobile app on another machine using the current Flask backend as the source of truth.

## Backend Base URL

Local development:

```text
http://127.0.0.1:5000
```

LAN testing from a phone should use the development machine IP:

```text
http://<dev-machine-lan-ip>:5000
```

Production should use the deployed HTTPS domain.

## Hard Architecture Rules

- The mobile app must never connect directly to the database.
- The Flask backend owns auth, users, devices, readings, notification settings, support, and account/security state.
- The mobile app should not duplicate scheduler, energy, notification, weather, or solar decision logic.
- The app should render backend-provided state and call explicit APIs for user actions.
- No SMS, Telegram, provider sync, or hardware command should run from passive screen refresh.

## Auth Flow

1. Register or login.
2. Store `access_token` and `refresh_token`.
3. Use `Authorization: Bearer <access_token>` for all protected calls.
4. When an endpoint returns `invalid_token`, call refresh once.
5. If refresh fails, clear tokens and return to login.

Recommended storage:

- Access token: secure memory plus short-lived secure storage if needed.
- Refresh token: Keychain/Keystore via Expo SecureStore or a similar secure storage provider.

Do not store tokens in plain AsyncStorage.

## First App Startup Flow

Recommended sequence:

1. Check secure storage for refresh token.
2. If access token is missing or expired, call `POST /api/mobile/auth/refresh`.
3. Call `GET /api/mobile/bootstrap`.
4. Use bootstrap to initialize:
   - user profile
   - subscription state
   - onboarding state
   - devices
   - permissions/navigation
   - provider metadata
   - location catalog
5. Route user to onboarding, dashboard, or restricted/account state screen based on backend response.

## Endpoint Groups

### Auth

- `POST /api/mobile/auth/register`
- `POST /api/mobile/auth/login`
- `POST /api/mobile/auth/refresh`
- `POST /api/mobile/auth/logout`
- `GET /api/mobile/auth/me`

### Bootstrap and Catalogs

- `GET /api/mobile/bootstrap`
- `GET /api/mobile/location-catalog`
- `GET /api/mobile/device-providers`

### Profile and Onboarding

- `GET /api/mobile/profile`
- `PATCH /api/mobile/profile`
- `GET /api/mobile/onboarding`
- `POST /api/mobile/onboarding`
- `PATCH /api/mobile/onboarding`

### Account and Security

- `GET /api/mobile/account`
- `PATCH /api/mobile/account`
- `POST /api/mobile/account/change-password`
- `POST /api/mobile/account/logout-all`
- `DELETE /api/mobile/account`

### Devices

- `GET /api/mobile/devices`
- `POST /api/mobile/devices`
- `GET /api/mobile/devices/{device_id}`
- `PATCH /api/mobile/devices/{device_id}`
- `DELETE /api/mobile/devices/{device_id}`

### Dashboard and Live Data

- `GET /api/mobile/dashboard`
- `GET /api/mobile/live`
- `GET /api/mobile/dashboard/feed`

### Loads and Controls

- `GET /api/mobile/loads`
- `POST /api/mobile/loads`
- `GET /api/mobile/loads/{load_id}`
- `PATCH /api/mobile/loads/{load_id}`
- `DELETE /api/mobile/loads/{load_id}`
- `POST /api/mobile/loads/{load_id}/toggle`
- `GET /api/mobile/loads/recommendations`

### Notifications

- `GET /api/mobile/notifications/settings`
- `PATCH /api/mobile/notifications/settings`
- `GET /api/mobile/notifications`
- `POST /api/mobile/notifications/{notification_id}/read`
- `POST /api/mobile/notifications/read-all`

### Support

Current stable support APIs are under `/api/v1/support`, not `/api/mobile/support`.

- `GET /api/v1/support/cases`
- `POST /api/v1/support/cases`
- `GET /api/v1/support/cases/{kind}/{case_id}`
- `POST /api/v1/support/cases/{kind}/{case_id}/reply`
- `POST /api/v1/support/cases/{kind}/{case_id}/reopen`
- `GET /api/v1/support/canned-replies`

## Recommended Mobile Screens

1. Splash/session restore.
2. Login.
3. Register.
4. Onboarding profile/location.
5. Onboarding device setup.
6. Dashboard.
7. Live data.
8. Device list.
9. Device detail/edit.
10. Loads list.
11. Load create/edit.
12. Notifications settings.
13. Notification center.
14. Channels/settings placeholder or web handoff if needed.
15. Support cases.
16. Support thread.
17. Account/profile.
18. Security/change password.
19. Subscription/status.

## What Is Ready

- Mobile auth with Bearer tokens and refresh tokens.
- Mobile registration and login.
- Profile and onboarding APIs.
- Location catalog and provider metadata.
- Dashboard/live/feed read-only APIs.
- Device management APIs with safe fields.
- Loads CRUD and persisted enabled/disabled preference.
- Notification settings APIs with global-scope warning.
- Notification center list/read/read-all.
- Account/security summary, update, password change, logout-all.
- Support case flow under `/api/v1/support`.

## Deferred or Unsupported

- Direct database access.
- Per-device notification settings.
- Mobile load recommendations are currently deferred.
- Direct inverter/hardware control.
- Scheduler manipulation.
- Provider sync/test connection from mobile.
- Real Telegram/SMS test sends from passive endpoints.
- Account deletion.
- Report/PDF generation from mobile.
- Moving support to `/api/mobile/support` namespace.

## Known Contract Notes

### Notification settings are global

The current settings store is global/account-platform scoped. The mobile UI must not imply per-device notification rules until the backend schema supports them.

### Load recommendations are deferred

`GET /api/mobile/loads/recommendations` returns `available: false` and does not run new recommendation logic.

### Support is under `/api/v1/support`

The mobile app can use it now, but keep the API client organized so support can be mirrored under `/api/mobile/support` later without a large rewrite.

### Logout-all revokes refresh tokens only

`POST /api/mobile/account/logout-all` revokes stored refresh tokens for the account. Existing stateless access tokens expire naturally.

### Account deletion is unsupported

`DELETE /api/mobile/account` returns `account_deletion_not_supported` and does not delete data.

## UI and State Guidance

- Treat all backend booleans as authoritative.
- For destructive-looking actions, show confirmation first.
- Use backend error codes for user-facing messages.
- For `account_restricted` or `can_write: false`, make screens read-only and explain the account state.
- For notification settings, show an explicit global-scope note.
- For load toggles, explain that this is a saved preference, not direct hardware switching.
- For account deletion, show "not available yet" rather than a destructive action.

## API Client Suggestions

Create grouped API modules:

```text
api/auth.ts
api/bootstrap.ts
api/profile.ts
api/account.ts
api/devices.ts
api/dashboard.ts
api/loads.ts
api/notifications.ts
api/support.ts
```

Centralize:

- base URL
- Bearer header injection
- refresh-token retry
- JSON error parsing
- network timeout handling
- logout/token clearing

## Minimal Build Order

1. Auth client and secure token storage.
2. Bootstrap/profile/onboarding screens.
3. Dashboard and live data read-only screens.
4. Devices list/detail/create/edit/deactivate.
5. Loads list/create/edit/toggle.
6. Notifications settings and center.
7. Account/security screens.
8. Support cases and threads.
9. Offline/empty/loading/error polish.

## Final Pre-Handoff Checks

Before moving mobile development to another machine:

```powershell
python -m compileall app tests
git diff --check
```

Also run the checklist in:

```text
docs/mobile/mobile_api_smoke_checklist_v36.md
```

Expected documentation files:

```text
docs/mobile/mobile_api_contract_v36.md
docs/mobile/mobile_api_smoke_checklist_v36.md
docs/mobile/mobile_app_build_handoff_v36.md
```
