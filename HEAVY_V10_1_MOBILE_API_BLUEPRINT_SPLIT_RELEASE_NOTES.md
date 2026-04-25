# Heavy v10.1 — Mobile API & Blueprint Split Foundation

## Scope
This release creates the first real mobile API foundation and performs the first large safe split of `app/blueprints/main.py`.

## Blueprint split
`main.py` was reduced from about 4006 lines to under 2200 lines by moving route logic into dedicated modules while keeping lightweight compatibility stubs for legacy `url_for('main.*')` endpoints.

New route modules:

- `app/blueprints/energy.py`
- `app/blueprints/devices_routes.py`
- `app/blueprints/support.py`
- `app/blueprints/billing.py`
- `app/blueprints/notifications_routes.py`
- `app/blueprints/users_routes.py`

`main.py` now acts as a legacy helper/stub bridge during the migration window. This keeps old templates and redirects stable while the implementation moves into proper blueprints.

## Mobile API foundation
New endpoints:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/devices`
- `GET /api/v1/devices/<id>`
- `GET /api/v1/devices/<id>/latest`
- `GET /api/v1/devices/<id>/history`
- `GET /api/v1/devices/<id>/alerts`
- `GET /api/v1/support/cases`
- `POST /api/v1/support/cases`
- `GET /api/v1/support/cases/<type>/<id>`
- `POST /api/v1/support/cases/<type>/<id>/reply`
- `POST /api/v1/support/cases/<type>/<id>/reopen`
- `GET /api/v1/notifications`
- `POST /api/v1/notifications/mark-read`
- `POST /api/v1/notifications/push-tokens`
- `DELETE /api/v1/notifications/push-tokens`
- `POST /api/v1/notifications/push-tokens/unregister`
- `GET /api/v1/openapi.json`
- `GET /api/v1/docs`

## Mobile auth
Added signed access-token authentication with persistent refresh tokens.

New models:

- `MobileRefreshToken`
- `MobilePushToken`

New services:

- `app/services/api_responses.py`
- `app/services/mobile_auth.py`

## Push token foundation
Android/Firebase push token registration is now supported at the database/API level. Actual FCM delivery can be added in the next release after Firebase project credentials are provided.

## Security
- `/api/v1/*` JSON mobile routes use bearer/refresh-token auth and are CSRF-exempt.
- Browser POST forms remain CSRF protected.
- Telegram webhook stays exempt via endpoint-specific exemption.
- Sensitive response payloads continue to be sanitized.

## API docs
OpenAPI JSON and a lightweight human-readable docs page were added.

## Validation performed
- Python compile passed.
- Jinja template parse passed.
- JavaScript syntax check passed.
- i18n audit passed with 0 legacy Arabic template findings.
- `main.py` line count is below the requested threshold.
