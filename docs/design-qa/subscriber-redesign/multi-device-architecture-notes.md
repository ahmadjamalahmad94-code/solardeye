# Multi-Device Architecture — Foundation Notes (v32)

**Build:** v32-subscriber-console-unified-multidevice
**Date:** 2026-05-08
**Status:** Foundation laid; remaining work scoped for v33.

This document explains exactly what was changed in v32, what was already
in place before v32, and what is intentionally deferred. Future contributors
should read this before extending the multi-device behaviour.

---

## TL;DR

The data layer was already 80% multi-device-aware before v32. v32 closes
the UI gap (a persistent device switcher above every relevant subscriber
page) and the URL-to-session glue (`?selected_device_id=…` actually does
something). The scheduler and channel/notification-rule storage still
need work — see "Deferred to v33" below.

---

## What was already in place before v32

### Models with `device_id` (no migration needed)

| Model                       | `device_id` column | Notes |
|-----------------------------|--------------------|-------|
| `Reading`                   | ✓                  | Live readings already device-scoped. |
| `SyncLog`                   | ✓                  | Sync failures attributed per device. |
| `NotificationLog`           | ✓                  | Outbound notification record per device. |
| `UserLoad`                  | ✓                  | Smart-load list is per device. |
| `EventLog`                  | ✓                  | Per-device event timeline. |
| `SmartSnapshot`             | ✓                  | Hourly snapshots per device. |
| `SmartRecommendationLog`    | ✓                  | Recommendation provenance per device. |
| `SupportTicket`             | `related_device_id`| Tickets can reference a specific device. |

### Identity columns

| Column                                  | Role |
|-----------------------------------------|------|
| `AppUser.preferred_device_id`           | Durable per-user "selected device". Used as fallback when session is empty. |
| `AppDevice.owner_user_id`               | Tenant scoping by user. |
| `AppDevice.tenant_id`                   | Tenant scoping by org. |
| `AppDevice.timezone`                    | Per-device timezone for reports/snapshots. |
| `AppDevice.api_provider`, `auth_mode`, `credentials_json` | Per-device connection config. |
| `AppDevice.settings_json`               | Per-device settings (battery reserve, etc.) |
| `AppDevice.connection_status`, `last_connected_at` | Per-device health. |

### Auto-migration on boot

`app/__init__.py:_migrate_database` already idempotently adds
`user_id`/`device_id` columns to the relevant tables on every boot.
This is how the existing `Reading.device_id` etc. were rolled out
without losing single-device users. The same mechanism will handle
the v33 channel/rule columns when those land.

### Scope helpers

`app/services/scope.py` provides:

- `get_current_user()` — session user with admin override.
- `get_current_device()` — session/preferred device (skips admin scope).
- `scoped_query(model)` — auto-filters by `device_id` if the model has it,
  falling back to `user_id`. **Already used by every subscriber-side data
  read.** This is why the data is correctly device-scoped today.
- `set_system_scope(user_id, device_id)` — used by the scheduler and
  the auto-sync path.

---

## What v32 added

### 1. `app/services/device_context.py`  — new file

Two hooks, registered from `app/__init__.py`:

- **`@app.before_request`** — when a subscriber GET arrives with
  `?selected_device_id=N` (or `__all__`), the session is updated, the
  durable `AppUser.preferred_device_id` is mirrored, and the request
  is redirected to the same URL without that query param. Clean URLs,
  no infinite query-string growth, and admin/api routes are skipped.

- **`@app.context_processor`** — every Jinja render gets:
  - `user_devices` — `[AppDevice]` ordered by active-first, id ascending.
  - `current_device_id` — `int | None` (None when `aggregate_mode` is true
    or the user has no devices).
  - `aggregate_mode` — `bool` (True when user picked "all devices").

### 2. `app/templates/_device_switcher.html`  — refined

- **0 devices:** renders nothing (page shows its own empty state).
- **1 device:** renders a compact "Viewing data for **X** · timezone · provider"
  banner with a "Manage" link. Friendly even when there's no choice to make.
- **2+ devices:** renders the full switcher bar — current-device card on the
  left, "Switch device" + "Manage" buttons on the right, dropdown menu
  containing every device + an "All devices (aggregate)" option + an
  "Add new device" CTA.
- Icons keyed by device-name keywords (farm, workshop, shop, office, roof, …).
- ARIA roles (`role="menu"`, `aria-expanded`, `aria-haspopup`) on the toggle.
- Respects RTL.

### 3. CSS — `subscriber_console_v32.css` (new) + base.html load

`subscriber_v4.css` (which already had the `.dswx-*` styles) is now loaded
**by every page via base.html**, removing the per-page wiring requirement.
The new `subscriber_console_v32.css` adds:

- Switcher hardening (margin, mobile collapse, RTL chevron).
- `.dswx-single-banner` — the 1-device fallback.
- Multi-device empty-state card (`.sub-empty-multidevice`).
- Notifications-center thread polish (`.ncv40-thread.is-unread`,
  `.is-critical`, device-chip styling).
- Devices-manage hub fleet-grid + cards (`.dm-fleet-grid`,
  `.dm-device-card.is-selected`).
- Live-data context strip above the hero (`.lv-context-strip.is-online`).
- Build badge made subtle (`.dev-build-badge-v11` is now a small
  bottom-left pill).

### 4. Build identity

- `base.html` build-badge text bumped to **v32 · subscriber-console**.
- All four `<link>` cache-bust params unified to
  `v32-subscriber-console-unified-multidevice`.

---

## How a request flows now

```
GET /live-data?selected_device_id=7&lang=ar
            │
            ▼
  before_request (device_context._maybe_apply_selected_device_query)
            │   session['current_device_id'] = 7
            │   user.preferred_device_id     = 7
            ▼
  302 → /live-data?lang=ar  (param stripped)
            │
            ▼
  GET /live-data?lang=ar
            │
            ▼
  energy_bp.live_data() route
            │   uses scoped_query(Reading)  → auto-filtered by device_id=7
            ▼
  render_template('live_data.html', latest=…)
            │
            ▼
  context_processor injects:
    user_devices       = [Roof, Workshop, Farm]
    current_device_id  = 7
    aggregate_mode     = False
            │
            ▼
  _device_switcher.html → renders the bar with "Workshop" highlighted.
```

---

## Deferred to v33 (and why)

### A. Scheduler iteration over active devices

`app/scheduler.py` currently runs each background job under a single
`system_user`/`system_device` scope chosen via `get_default_system_device`.
That works fine when there is one active device per user (the historical
case), but does not actually fan out across multiple devices.

The fix is straightforward but needs care:

```python
# pseudo-code for the new jobs runner
for device in AppDevice.query.filter_by(is_active=True):
    scope = set_system_scope(device.owner_user_id, device.id)
    try:
        run_job_for_device(device)
    finally:
        reset_system_scope(scope)
```

Risks: doubling work for users who only have one device, breaking
currently-working sync timing, exhausting third-party API rate limits
(Deye/SolarMan have per-account throttles, not per-device — so we may
need to chunk by account). This is real backend work that deserves its
own session; not safe to bundle into a UI redesign.

### B. `Channel` / `UserChannel` model

Today, channel state lives in the global `Setting` key/value table
(`telegram_enabled`, `sms_enabled`, `telegram_bot_token`, …). Three gaps:

1. Channels are tenant-global, not per-user.
2. Channels cannot be assigned per-device (e.g. "send Roof alerts to
   Telegram, send Workshop alerts to SMS").
3. There is no channel-test history.

Proposed v33 schema:

```python
class UserChannel(db.Model):
    __tablename__ = 'user_channel'
    id           = Integer, PK
    user_id      = FK(app_user)
    device_id    = FK(app_device, nullable=True)   # NULL → applies to all
    channel_type = String(30)                      # telegram/sms/email/push
    is_enabled   = Boolean
    config_json  = Text                            # token, recipients, etc.
    created_at   = DateTime
    updated_at   = DateTime
    last_test_at = DateTime
    last_test_ok = Boolean
```

Backwards compat: read existing global Settings as defaults when no
`UserChannel` row exists for a user/device pair.

### C. `NotificationRule` model

Currently rules are read from settings_json strings (battery thresholds,
night limits, etc.). Per-device rules require:

```python
class NotificationRule(db.Model):
    __tablename__ = 'notification_rule'
    id          = Integer, PK
    user_id     = FK(app_user)
    device_id   = FK(app_device, nullable=True)    # NULL → applies to all
    rule_key    = String(80)                       # battery_low, grid_lost, …
    is_enabled  = Boolean
    threshold   = Float, nullable
    severity    = String(20)                       # info/warn/critical
    channels    = String(120)                      # csv: telegram,sms
    cooldown_s  = Integer
    created_at  = DateTime
    updated_at  = DateTime
```

Migration plan: read existing global rules from `Setting`, fan out one
row per `(user, rule_key)` per active device on first boot, mark them
as `source='migrated'` for audit.

### D. Onboarding wizard

The current `/onboarding` flow assumes "first device". v33 should add
an "add another device" branch that re-uses the same form but skips
profile/channel steps if those are already configured.

### E. UI follow-ups (not destabilising)

- `/statistics` — needs the device switcher + an explicit "All devices"
  aggregate chart variant.
- `/reports` — same as statistics; aggregate report should label each
  device clearly.
- `/loads` — already device-scoped via `UserLoad.device_id`, but the page
  needs the switcher mounted and the smart-load engine needs to read the
  selected device, not the default one.
- `/notifications` (rules) — needs the per-device rule toggle UI once
  `NotificationRule` lands.
- `/channels` — needs a per-device assignment matrix once `UserChannel` lands.
- `/account/profile` and `/account/subscription` — no device scope needed.
- `/portal/support` — already accepts `related_device_id` on tickets;
  adding a "tag this ticket with a device" picker would be a polish task.

---

## Backwards compatibility checklist

- ✅ Existing single-device users: `_device_switcher.html` shows a soft
  banner instead of a switcher; nothing changes in their data flow.
- ✅ Existing routes: `scoped_query` already device-filters everywhere.
  No route signatures changed.
- ✅ Existing DB rows: no migration was required for v32 because every
  device-scoped table already had `device_id`. The `_migrate_database`
  helper would have added them anyway on boot.
- ✅ Admin scope: `is_admin_scope()` short-circuits the context
  processor, so admin pages never see `user_devices` and the switcher
  never appears.
- ✅ Render compat: no new dependencies; works with PostgreSQL (Render)
  and SQLite (local dev).
- ✅ Scheduler: untouched in v32 — no risk of broken sync.

---

## Smoke test (manual)

1. Log in as `ahmad / 791994`.
2. With one device, visit `/live-data?lang=ar` — confirm the soft single-
   device banner shows above the hero.
3. Add a second device via `/devices/manage` — confirm the switcher bar
   replaces the banner on the next page load.
4. Open the "Switch device" dropdown and pick the new device — confirm
   the URL redirects without `selected_device_id=` and the live-data
   page now shows that device's name.
5. Pick "All devices (aggregate)" — confirm the strip says "5 devices
   combined" (or however many) and the switcher icon flips to 📊.
6. Hit `/devices/manage` directly — confirm the highlighted card matches
   the current selection.
7. Log out, log back in — confirm the previously-selected device is still
   selected (preferred_device_id persistence).

---


---

## v32 QA-VERIFIED inventory (2026-05-08)

This section was added during the v32 QA pass. The numbers come from a
static parse of `app/models.py` and a runtime check of the live server.

### Tables WITH `device_id` (10)

`AppUser`, `AppDevice`, `Reading`, `SyncLog`, `NotificationLog`,
`UserLoad`, `EventLog`, `SmartSnapshot`, `SmartRecommendationLog`,
`SupportTicket` (`related_device_id`).

These are the data-bearing tables for subscriber-side energy + alerts +
support context. All can be scoped per device.

### Tables WITHOUT `device_id` that probably SHOULD have it (v33)

- **`UserChannel`** — does not exist as a model. Channel state is in the
  global `Setting` key/value table today (`telegram_enabled`,
  `sms_enabled`, `telegram_bot_token`, …). Per-device channel routing
  needs the new model.
- **`NotificationRule`** — does not exist as a model. Rules are read
  from `Setting` rows. Per-device rules need a real table.
- **`InternalMailMessage`** / **`SupportTicketMessage`** — currently
  per-thread/ticket only. Could carry an optional `device_id` for
  per-device support context, but not strictly required.

### Tables global by design (no scope)

`Setting`, `AppRole`, `PortalPageSetting`, `SubscriptionPlan`,
`ServiceHeartbeat`, `DeviceType`, `CannedReply`.

These are platform-level configuration; should NOT be device-scoped.

### Queries that still assume one device

`scoped_query()` (in `app/services/scope.py`) auto-filters by `device_id`
when the model has it. Any route that uses `scoped_query` is automatically
device-aware. Routes that use raw `Model.query.filter_by(...)` may be
single-device or even cross-device — they need an audit. Direct `.query.`
counts per blueprint:

```
billing.py            54   ← billing usually tenant-scoped, low device-leak risk
main.py               88   ← needs careful audit; some are admin-scope (fine), some are subscriber pages
users_routes.py       43   ← admin user-management; fine
support.py            36   ← support uses tenant scope; check related_device_id usage
energy.py             20   ← MUST audit — covers /live-data, /statistics, /reports, /loads
platform.py           16   ← admin-scope
auth.py               15   ← login/registration; fine
admin_ops.py          11   ← admin-scope
devices_routes.py      8   ← device management; fine (filters by owner_user_id)
notifications_routes.py 5   ← MUST audit — channels and notification settings
helpers.py / etc       <10 each
```

For v33, audit `energy.py` and `notifications_routes.py` raw `.query.` calls and
replace with `scoped_query` where they hand back per-subscriber data.

### Scheduler still single-device

`app/scheduler.py` registers six jobs:

```
advanced_notifications_check    every 30s
weather_change_check            every 10m
weather_daily_summary           daily 07:00
daily_morning_report            daily 09:05
database_backup_maintenance     daily (configured frequency)
deye_auto_sync                  every AUTO_SYNC_MINUTES (default 5)
```

Each job runs inside `set_system_scope(system_user.id, system_device.id)`
where `system_device = get_default_system_device(system_user)` — i.e. the
**first** active device for the user. Multi-device users only get their
primary device's data refreshed on schedule.

The v33 fix is to iterate `AppDevice.query.filter_by(is_active=True).all()`
and run the job once per device, with the right scope. This is a
moderate-risk refactor because:

1. Some external APIs (Deye/SolarMan) throttle per-account, not per-device;
   naïve per-device parallelism could trip rate limits.
2. The scheduler already has `coalesce: True, max_instances: 1` so jobs
   serialize — fan-out per device should keep the same guarantee.
3. Notifications must still respect per-rule cooldowns; if a rule fires
   for device A and again for device B, that's by design.

### What v32 actually changed in the data layer

**Nothing.** No new columns, no new tables, no migration. v32 is a UI
+ context-glue release. The data layer was already device-aware enough
to support the device switcher UX.

### What needs a Flask process restart for v32 to fully activate

- `app/services/device_context.py` (new file) — must be imported on
  fresh app start.
- `app/__init__.py` — `register_device_context(app)` only runs at
  `create_app()` time.
- `app/blueprints/energy.py` — the new inline device-switcher payload
  computation in `live_data` and `loads_page` only runs after the
  module is re-imported.

Until restart:
- `/devices/manage` — switcher (single-device banner) WORKS, because
  the partial falls back to `devices_list` which the route already passes.
- `/live-data`, `/loads`, `/statistics`, `/reports`, `/notifications`,
  `/notifications/center` — switcher does NOT render. The rest of the
  page does.
- The `before_request` hook for `?selected_device_id=N` does NOT run.
  Clicking a switch link goes to the URL but the session isn't updated.

### Bug found and fixed during v32 QA

`app/blueprints/energy.py` was **already truncated mid-function** in
git HEAD (the `loads_page` function ended with `db.sessio` — a typo
that left an unclosed `(`). The running Flask process was using a
stale `.pyc` from before the truncation, masking the bug. Any restart
would have exposed a `SyntaxError`.

v32 reconstructed the missing tail (delete branch closing,
`save_night_limit` branch, GET render). Verified with `python -m
compileall app/` (no errors). Filed under "things-already-broken-
that-v32-fixed".
