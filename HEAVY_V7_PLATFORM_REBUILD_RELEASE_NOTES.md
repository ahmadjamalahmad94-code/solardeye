# Heavy v7.0 — Platform Rebuild, Security & UI Standardization

This release is a broad platform polish and hardening pass after the v6 support-mailbox work.

## Security and privacy

- Added app-wide CSRF protection for POST/PUT/PATCH/DELETE requests.
- Added automatic CSRF injection for existing forms and AJAX writes.
- Added secure response headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a restrictive `Permissions-Policy`.
- Added production cookie defaults: `HttpOnly`, `SameSite=Lax`, and secure cookies by default.
- Added `TELEGRAM_WEBHOOK_SECRET` validation support for Telegram webhook traffic.
- Locked debug/API probe tools behind administrator access and `DEBUG_TOOLS_ENABLED=true`.
- Sanitized raw debug payloads with recursive secret masking.
- Added `.gitignore` to keep `.env`, private keys, local databases, and OAuth client secret files out of the project.
- Cleaned `.env.example` so it contains placeholders only.

## Database and architecture hardening

- Added startup index creation for high-traffic support, notification, message, ticket, and reading tables.
- Added duplicate cleanup for `support_case` and a unique index on `(case_type, source_id)`.
- Moved shared security logic into `app/services/security.py`.
- Added shared language/label helpers in `app/services/labels.py`.
- Stopped support queue and stats pages from syncing every existing case on every page load; syncing now happens at startup and on writes.

## UI and UX polish

- Added Heavy v7 design tokens for colors, surfaces, borders, shadows, and motion timing.
- Standardized button radius, weight, hover states, focus states, and primary/secondary/danger/success variants.
- Added global card, table, form, and responsive layout improvements to prevent cards/tables from overflowing page bounds.
- Added mobile sidebar drawer instead of simply hiding the navigation.
- Added reduced-motion support for accessibility.
- Improved text wrapping, JSON/pre blocks, tables, and grid behavior across the site.
- Added shared badge classes and label helpers for translated statuses and priorities.

## Language improvements

- Added shared UI label dictionaries for Arabic and English.
- Added automatic English translation polish for common legacy Arabic labels still present in older templates.
- Replaced many raw status/priority/finance labels with localized labels.

## Secret handling in UI

- Deye app secret, Deye password, Deye password hash, Telegram bot token, SMS API key, and per-device secrets are no longer rendered back into inputs as plain text.
- Existing secrets are shown as masked placeholders and preserved on save when the field is left blank.
- Deye email, Plant ID, inverter/logger serials, battery serials, and device identifiers are masked in sensitive setup forms and preserved when left blank.

## New environment variables

```env
ADMIN_PASSWORD=replace-with-a-strong-password
CSRF_ENABLED=true
DEBUG_TOOLS_ENABLED=false
TELEGRAM_WEBHOOK_SECRET=replace-with-random-secret-if-using-telegram-webhook
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=Lax
```

## Post-deploy checks

1. Open `/admin/support-command-center` and verify support still loads quickly.
2. Open `/portal/support` and verify subscriber support still works.
3. Test login/logout after CSRF injection.
4. Test at least one POST form in:
   - Admin finance
   - Device edit
   - Channels
   - Support reply
5. Confirm secret fields show masked placeholders and do not erase stored secrets when saved blank.
6. If Telegram webhook is used, click “Enable webhook” after setting `TELEGRAM_WEBHOOK_SECRET`.
7. Keep `DEBUG_TOOLS_ENABLED=false` in production unless temporarily debugging.


## Runtime note

Static validation passed. Full runtime validation must be completed on the deployment environment where Flask dependencies and the production database are available.
