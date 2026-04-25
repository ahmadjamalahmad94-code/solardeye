# Heavy v10.0 — Platform RBAC, Mobile Readiness & Integration Expansion

This release focuses on operational control, a calmer interface, safer permissions, and Android-readiness.

## Highlights

- Fixed desktop sidebar: compact, stable, and non-scrolling on desktop while keeping mobile drawer behavior.
- Added a real RBAC layer with custom roles and translated permissions.
- Added subscriber page visibility controls: hide/show portal pages from the subscriber sidebar and direct access.
- Added `/admin/roles` as the new roles, permissions, and subscriber visibility console.
- Added Android-ready mobile API endpoints under `/api/v1/mobile`.
- Continued safe modular split of large routes by adding active access-control and mobile API blueprints.
- Expanded energy provider catalog and universal adapter support for more solar/energy ecosystems.
- Improved security with lightweight rate limiting for login/admin/API write endpoints.
- Unified spacing, card overflow behavior, button focus states, and reduced-motion behavior.
- Updated frontend cache version to `10.0`.

## New/changed files

- `app/services/rbac.py`
- `app/blueprints/access_control.py`
- `app/blueprints/mobile_api.py`
- `app/templates/admin_roles.html`
- `app/services/energy_integrations.py`
- `app/services/device_adapters/http_adapter.py`
- `app/services/security.py`
- `app/templates/_sidebar.html`
- `app/templates/base.html`
- `app/static/css/style.css`

## Android API endpoints

- `GET /api/v1/mobile/bootstrap`
- `GET /api/v1/mobile/summary`
- `GET /api/v1/mobile/notifications`
- `GET /api/v1/mobile/health`

## Notes

`main.py` is still retained for backward compatibility, but v10 moves new access-control and mobile API responsibilities into dedicated blueprints. Future releases can continue extracting legacy admin/support/energy routes safely.
