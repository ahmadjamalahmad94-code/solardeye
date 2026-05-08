# v33 — True Multi-Device Engine — Architecture Plan

**Status:** PLANNING ONLY. No code changes have been made. Implementation
will follow once this plan is reviewed and approved.

**Tag (future):** `v33-true-multidevice-engine`

**Core principle:**
> Selected device is only a UI viewing/filtering concept. It must NOT
> limit which devices sync, analyse, or send notifications. All active
> devices must operate independently, on their own timezone, with their
> own credentials, their own loads, their own notification rules, and
> their own deduplication state.

---

## 1. Current single-device assumptions (verified inventory)

I read the running code line-by-line. Here is every place that today
silently assumes "one active device per user" or "one active device per
installation":

### 1a. Scheduler entrypoints (`app/scheduler.py:35-37`)
Every job runs under one fixed scope:
```python
system_user   = get_default_system_user()
system_device = get_default_system_device(system_user)
scope_tokens  = set_system_scope(system_user.id, system_device.id)
```
`get_default_system_device` returns the **first active device** of the
first active user. Multi-device users only get their primary device's
data refreshed on schedule.

Affected jobs (6):
- `deye_auto_sync` (every 5 min)
- `advanced_notifications_check` (every 30 s)
- `weather_change_check` (every 10 min)
- `weather_daily_summary` (07:00 cron)
- `daily_morning_report` (09:05 cron)
- `database_backup_maintenance` (02:15 cron — global, not device-scoped)

### 1b. `sync_now_internal` (`app/blueprints/main.py:649`)
```python
device       = get_current_device()
current_user = get_current_user()
ready, msg   = _device_sync_ready(device, user=current_user)
```
Reads exactly one device from the current scope and syncs that one. No
loop over `AppDevice.query.filter_by(is_active=True)`.

### 1c. `run_advanced_notification_scheduler` (`notifications.py:1515`)
```python
settings = load_settings()                  # GLOBAL Setting table
latest, weather = _get_weather_for_latest()  # latest reading in current scope
if not latest:
    return
```
Uses **global** settings + **current-device-scoped** latest reading. So
if device B has a fresher reading, device A's settings still drive the
decisions, and device B's reading is invisible.

### 1d. `process_notifications` (`notifications.py:1807`)
Scoped properly *per current device* (uses scoped_query for
NotificationLog), but called only once per `sync_now_internal` —
which itself runs only for one device.

### 1e. `dispatch_notification` deduplication keys
```python
event_key = f'charge-{level}-{day_key}'
event_key = f'discharge-{level}-{day_key}'
event_key = f'day-deficit-{hour_key}'
event_key = f'periodic-status-{int(now.timestamp())}'
event_key = f'pre-sunset-{int(now.timestamp())}'
event_key = f'weather-sunny-{bucket}'
event_key = f'weather-cloudy-{bucket}'
event_key = f'weather-rain-{bucket}'
```
**None contain a device id.** With multi-device fan-out, device A
hitting "battery 50%" will suppress device B's identical alert via
`notification_exists(event_key)` (which uses `scoped_query` — but in a
scheduler job the scope is the system_device, not the actual device the
event belongs to).

### 1f. `load_settings()` (`helpers.py:31`)
Returns rows from the **global** `Setting` table merged with `current_app.config` defaults. Channels (`telegram_bot_token`, `telegram_chat_id`, `sms_*`), notification rules (`notification_rules_json`), weather config — all global. There is exactly ONE Telegram bot, ONE SMS endpoint, ONE notification-rule blob for the entire installation.

### 1g. `_device_runtime_settings(device)` (`main.py:888`)
This IS the merge layer that already does it right: starts from global, then overlays `device.credentials_json` + `device.settings_json` for connection + battery settings. **Only used by `sync_now_internal`.** v33 must extend this pattern to channels and notification rules.

### 1h. `device_form` per-device settings_json keys today
Used keys observed: `deye_region`, `deye_plant_id`, `deye_device_sn`, `deye_logger_sn`, `deye_plant_name`, `deye_battery_sn_main`, `deye_battery_sn_module`, `battery_capacity_kwh`, `battery_reserve_percent`, `api_base_url`. **No timezone there** — `AppDevice.timezone` is a top-level column (good).

### 1i. Session-driven scope (`auth.py:507-519`)
```python
if session.get('current_device_id') and g.current_user is not None:
    g.current_device = AppDevice.query.filter_by(...).first()
```
Sets `g.current_device` from session. This is fine for **viewing**; v33
must make sure **no scheduler/sync/notification path silently inherits
it**.

### 1j. Smart engine (`smart_engine.py:104-148`)
Uses `current_scope_ids()` and `scoped_query(SmartSnapshot)`. Already
device-aware. ✅

### 1k. Weather (`main.py:391`, `weather_service.py:121`)
`get_weather_for_latest(latest)` extracts coords from the **passed-in
Reading** and calls `fetch_weather(lat, lng, tz)`. Already device-scoped
via the Reading. ✅ (The bug is just that the *caller* only knows one device.)

---

## 2. All callers of `get_default_system_device` (and equivalents)

```
app/scheduler.py:36                  system_device = get_default_system_device(system_user)
app/services/scope.py:40             def get_default_system_device(user)  ← definition
app/services/scope.py:96-107         get_current_device fallback to first active device for user
```

`get_default_system_device` is the **only** scheduler-level call. Every
other "first active device" pick is via `get_current_device()` which
already prefers `g.current_device` → `session['current_device_id']` →
preferred_device_id → first-active-device.

**v33 plan:** scheduler will stop calling `get_default_system_device`
entirely and instead iterate `AppDevice.query.filter_by(is_active=True)`.

---

## 3. Scheduler jobs and how they run today

| Job ID                          | Trigger          | Today's scope                       | Device-aware fix needed |
|---------------------------------|------------------|-------------------------------------|--------------------------|
| `deye_auto_sync`                | every 5 min      | one system_device                   | ✅ fan-out per active device |
| `advanced_notifications_check`  | every 30 s       | one system_device                   | ✅ fan-out per active device |
| `weather_change_check`          | every 10 min     | one system_device                   | ✅ fan-out per active device (each has own coords) |
| `weather_daily_summary`         | 07:00 cron       | one system_device                   | ✅ fan-out per active device per timezone |
| `daily_morning_report`          | 09:05 cron       | one system_device                   | ✅ fan-out per active device per timezone |
| `database_backup_maintenance`   | 02:15 cron       | global                              | ❌ leave as-is — DB-wide, not device |

---

## 4. How to safely iterate over all active devices

### 4a. The pattern (rejected naïve form)
```python
for device in AppDevice.query.filter_by(is_active=True).all():
    scope = set_system_scope(device.owner_user_id, device.id)
    try:
        run_job_for_device(device)
    finally:
        reset_system_scope(scope)
```
This is correct semantically but has three real problems:

1. **Provider rate limits.** Deye / SolarMan / Tuya limit per *account*,
   not per device. If user A has 5 Deye devices and we sync them
   sequentially every 5 min, we spike that account 5× → 429s.
2. **Long jobs blocking each other.** APScheduler runs jobs serially
   per `max_instances=1`. A user with 100 devices would block the
   scheduler for minutes per cycle.
3. **Failure isolation.** One device throwing a credential error must
   NOT abort the loop for the rest.

### 4b. v33 fan-out plan
Three layers of grouping:

```
ALL active devices
  ├── grouped by provider_credentials_signature
  │     (e.g. SHA256 of deye_app_id + deye_email)
  │     → one obtain_token() per group, reuse for all devices in group
  └── grouped by owner_user_id
        → notifications + reports get owner-aware deduplication
```

**Pseudo-code:**
```python
def fan_out_sync():
    devices = AppDevice.query.filter_by(is_active=True).order_by(AppDevice.id.asc()).all()
    groups = defaultdict(list)
    for d in devices:
        groups[_provider_account_signature(d)].append(d)

    for sig, group in groups.items():
        try:
            token = _obtain_provider_token(group[0])  # one token per account
        except ProviderError as exc:
            log_event('warning', f'Skipping group {sig}: {exc}')
            continue
        for d in group:
            tokens = set_system_scope(d.owner_user_id, d.id)
            try:
                _sync_one_device(d, token=token)
            except Exception as exc:
                log_event('warning', f'Sync failed for device {d.id}: {exc}')
            finally:
                reset_system_scope(tokens)
```

### 4c. Failure isolation
- Each `_sync_one_device(d)` is wrapped in its own `try/except`.
- A single failure writes a `SyncLog(level='error')` for that device and continues.
- Heartbeat writes per device: `heartbeat(f'sync-{d.id}', …)`.

### 4d. Concurrency
v33 will keep APScheduler `max_instances: 1` for the fan-out wrapper
itself, but inside the wrapper devices run sequentially within their
provider group. Cross-group parallelism (one Deye account + one Tuya
account) can be added later via `concurrent.futures.ThreadPoolExecutor`
once we measure single-thread cycle time.

### 4e. Rate-limit-aware throttle
Per provider, configurable `min_seconds_between_calls` (default 0.5 s
for Deye, 1.0 s for SolarMan). Sleep between devices in the same group.
Skip a group entirely if its `last_call_at` is within `min_seconds`.

---

## 5. Per-device timezone / location / settings

### 5a. Already per-device (on `AppDevice`)
- `timezone` (column)
- `api_provider`, `api_base_url`
- `auth_mode`
- `credentials_json` (provider account)
- `settings_json` (battery capacity, reserve %, plant/station/serial)
- `connection_status`, `last_connected_at`
- `notes`

### 5b. Per-device location (already-present, indirectly)
Coordinates are extracted from the latest `Reading.raw_json` for that
device (`extract_station_coords(latest)`). v33 keeps this. Each device's
weather call uses its own coords + own timezone.

### 5c. Battery capacity / reserve
Already per-device via `settings_json.battery_capacity_kwh` and
`battery_reserve_percent`. `_device_runtime_settings` overlays them
correctly. No change.

### 5d. Notification thresholds (today are GLOBAL)
Today: `notification_rules_json` is in the global `Setting` table.
Battery low/high % thresholds are one-size-fits-all.
v33: introduce `NotificationRule` model (see §10) keyed by
`(user_id, device_id_or_NULL, rule_key)`. NULL means "applies to all my
devices unless overridden".

### 5e. Channels (today are GLOBAL)
Today: `telegram_bot_token`, `telegram_chat_id`, `sms_recipients` are
single global rows.
v33: introduce `UserChannel` model (see §10).

---

## 6. Per-device data isolation — already mostly correct

### 6a. Tables that already have `device_id` and use scoped_query
- `Reading` ✅ — `scoped_query(Reading)` filters by current device
- `SyncLog` ✅
- `NotificationLog` ✅ (but dedupe keys need device-aware suffixes — §1e)
- `UserLoad` ✅
- `EventLog` ✅
- `SmartSnapshot` ✅
- `SmartRecommendationLog` ✅
- `SupportTicket.related_device_id` ✅

### 6b. Statistics / Reports / Live data
Routes use `scoped_query(...)` against device-aware models. As long as
the request's scope is set correctly (via `g.current_device` from the
session/preferred-device), per-device isolation is automatic.

### 6c. Loads page
`UserLoad.device_id` is set on `add` action — but currently the
`loads_page` route saves new rows with NO device_id (line 1439:
`UserLoad(name=..., power_w=..., priority=..., is_enabled=True)`).
That means new loads are **not** scoped to the current device.
**v33 must fix:** pass `device_id=current_device_id` when inserting.

### 6d. Notifications-rule UI page
`/notifications` (rules) reads/writes the **global** `notification_rules_json` Setting.
**v33 must replace** this with read/write of the new `NotificationRule`
table, scoped to the current device (or "applies to all my devices" for
the user-default flag).

---

## 7. All-devices aggregate mode

### 7a. The challenge
"Show me totals across all my devices" must not double-count, must
clearly label which device contributed which row, and must not leak
between users.

### 7b. v33 design
The session value `current_device_id == '__all__'` (already wired in
v32) will trigger an **aggregate** mode:

| Page | In aggregate mode |
|---|---|
| `/live-data` | Show a small grid: one card per active device, plus a "Combined" header summing solar/load/grid (NOT battery — averaging SOC across devices is misleading). |
| `/statistics` | Summed kWh metrics with a per-device breakdown table below. Each row labelled with device name. |
| `/reports` | Same as statistics. CSV/PDF exports include a `device` column. |
| `/loads` | List loads from all devices, grouped by device name (header rows). Add-load form requires picking a device. |
| `/notifications` (rules) | Show all rules, grouped by device. Edit one device at a time. |
| `/notifications/center` | Inbox already shows all NotificationEvent rows for the user — aggregate is the natural mode here. Add a "device" filter chip per device. |
| `/devices/manage` | Aggregate is meaningless here — already shows the fleet grid by definition. |
| `/devices/manage/N/edit` | Aggregate is meaningless — single device by URL. |

### 7c. What aggregate mode must NOT do
- Average battery SOC across devices (mathematically ambiguous).
- Combine solar production with consumption from a different device.
- Show one device's notification settings as if applied to all unless
  the rule has `device_id IS NULL` (the "all my devices" flag).

### 7d. Aggregate computation pattern
```python
if aggregate_mode and user_devices:
    rows_per_device = {d.id: scoped_query_for_device(d.id, ...) for d in user_devices}
    combined = sum_or_concat(rows_per_device)
else:
    rows = scoped_query(...).all()
```

---

## 8. Database models — already ready (no change needed)

```
AppUser                  ← identity, preferred_device_id, timezone, country
AppDevice                ← per-device identity + credentials + settings + tz
Reading                  ← device_id ✓
SyncLog                  ← device_id ✓
NotificationLog          ← device_id ✓ (but dedupe keys need device suffix — §10)
UserLoad                 ← device_id ✓
EventLog                 ← device_id ✓
SmartSnapshot            ← device_id ✓
SmartRecommendationLog   ← device_id ✓
SupportTicket            ← related_device_id ✓
```

All migrations already in `app/__init__.py:_migrate_database` and
applied idempotently on every boot. Nothing to migrate for these.

---

## 9. Models / settings that still need per-device support

### 9a. `Setting` table → split into per-user / per-device tables
Today the `Setting` table holds:
- Provider connection defaults (deye_app_id, deye_email, etc.) — already overridden per device via `device.credentials_json`. ✅
- Notification channels (`telegram_bot_token`, `sms_*`) — **need migration** to a new `UserChannel` table.
- Notification rules (`notification_rules_json`, threshold percents, etc.) — **need migration** to a new `NotificationRule` table.
- Weather config (`weather_enabled`, `weather_change_alerts_enabled`, etc.) — keep global per installation OR move to `UserChannel`-style; design choice in §10.
- Battery defaults — **already** overridden per device via `device.settings_json`. ✅

### 9b. Backfill rules
- For each existing user with at least one device:
  - Create one `UserChannel(user_id, device_id=NULL, channel_type='telegram', config_json=<global telegram_*>, is_enabled=...)` if global telegram is enabled.
  - Same for SMS.
  - Create per-rule rows in `NotificationRule(user_id, device_id=NULL, rule_key, …)` from `notification_rules_json`.
- Mark each migrated row with `source='migrated_from_global_v33'` for audit.

---

## 10. NotificationRule per device (proposed model)

```python
class NotificationRule(db.Model):
    __tablename__ = 'notification_rule'
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey('app_user.id'), nullable=False, index=True)
    device_id   = Column(Integer, ForeignKey('app_device.id'), nullable=True, index=True)  # NULL = "all my devices"
    rule_key    = Column(String(80), nullable=False, index=True)   # e.g. 'battery_low', 'periodic_day', 'weather_change'
    is_enabled  = Column(Boolean, default=True, nullable=False)
    threshold   = Column(Float, nullable=True)                      # e.g. 20 for battery_low at 20%
    severity    = Column(String(20), default='info')               # info / warning / critical
    channels    = Column(String(120), default='telegram')           # csv of channel_type
    cooldown_s  = Column(Integer, default=3600)                     # min seconds between fires for same key+device
    schedule_mode  = Column(String(30), default='manual')           # interval / cron / manual / always
    schedule_value = Column(String(80), nullable=True)              # e.g. '15' for every-15-min, or HH:MM for cron
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'device_id', 'rule_key', name='uq_user_device_rule'),)
```

### 10a. Resolution
For a given event `(user_id, device_id, rule_key)`:
1. Look for a row with `device_id = N` (per-device override).
2. Else look for a row with `device_id IS NULL` (user default).
3. Else fall back to system defaults for `rule_key`.

### 10b. Dedup key change (critical)
Today: `event_key = f'charge-{level}-{day_key}'`
v33: `event_key = f'charge-{level}-{day_key}-{device_id}'`
Migration: bump `notification_dedup_key_version` and reset older keys.

---

## 11. Channel routing per device or global fallback

### 11a. Proposed `UserChannel` model
```python
class UserChannel(db.Model):
    __tablename__ = 'user_channel'
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey('app_user.id'), nullable=False, index=True)
    device_id    = Column(Integer, ForeignKey('app_device.id'), nullable=True, index=True)  # NULL = "applies to all my devices"
    channel_type = Column(String(30), nullable=False, index=True)   # 'telegram' / 'sms' / 'email' / 'push'
    is_enabled   = Column(Boolean, default=True, nullable=False)
    config_json  = Column(Text, nullable=True)                       # token, chat_id, recipients, etc.
    last_test_at = Column(DateTime, nullable=True)
    last_test_ok = Column(Boolean, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'device_id', 'channel_type', name='uq_user_device_channel'),)
```

### 11b. Resolution
For a notification destined to `(user_id, device_id, channel_type)`:
1. Per-device channel: `WHERE user_id=U AND device_id=D AND channel_type=C AND is_enabled=true`
2. Else user-default channel: `WHERE user_id=U AND device_id IS NULL AND channel_type=C AND is_enabled=true`
3. Else: skip (don't dispatch).

### 11c. UX in `/channels` page (v33 update)
- Default view: user-default channels (the "applies to all my devices"
  set).
- Above the list, the device-switcher partial. Picking a device shows
  per-device overrides for that device with an "inherit from default"
  toggle on each.

### 11d. Backwards compat
On boot, the migration backfills one `(user_id, device_id=NULL,
channel_type)` row per active channel from the global `Setting`. After
that, existing single-device users see no behavioural change — their
"global" channel becomes their "default for all my devices".

---

## 12. UI changes for the fleet overview

### 12a. `/devices/manage` (already polished in v32)
Add a **Fleet health summary** strip above the existing fleet grid:
- "Last sync ≤ 5 min ago" pill (green/amber/red dots).
- "Pending notifications" count.
- "Provider quota usage" if known per provider.

### 12b. New `/dashboard` aggregate hero
On the subscriber dashboard, add a **fleet snapshot row** (only when user has 2+ devices):
- Combined solar production (sum)
- Average battery SOC (per-device average, clearly labelled)
- Combined home load (sum)
- Combined grid net (sum)
- Per-device sparkline beneath

### 12c. Device switcher already covers most of this (v32)
The switcher dropdown already lists all devices + "All devices (aggregate)" — v33 wires the aggregate mode to actually compute aggregate values on all the device-scoped pages.

### 12d. New `/account/profile` device-summary card (optional)
A small "X devices · Y active · Z synced today" card under the profile.

---

## 13. Backwards compatibility

### 13a. Single-device users (the historical norm)
- 0 changes to URLs, route signatures, or template public APIs.
- The device switcher renders as a soft single-device banner (already done in v32).
- `current_device_id` defaults to `preferred_device_id` defaults to "first active device".
- All scoped data reads continue to work because every device-scoped
  table already has `device_id`.

### 13b. Existing data
- No data migration changes existing rows; new tables (`UserChannel`,
  `NotificationRule`) are additive.
- The dedupe-key change for `NotificationLog` is forward-only — old keys
  stay in the table; new keys include `device_id` suffix.

### 13c. Existing route handlers
- All current routes keep working. The scheduler change is internal.
- New v33 routes:
  - `/api/devices/<id>/sync-now` — POST, manual sync of one device.
  - `/api/notification-rules` — CRUD for the new model.
  - `/api/user-channels` — CRUD for the new model.

### 13d. Render compat
- No new dependencies.
- PostgreSQL (Render) and SQLite (local dev) both supported by the
  proposed columns/types.

---

## 14. Safety plan to avoid cross-user / cross-device leaks

### 14a. Hard rules
1. **Every scoped query MUST go through `scoped_query()`** when the
   model has `device_id` or `user_id`. Direct `Model.query.filter_by(...)`
   is allowed only for user-management / admin contexts.
2. **`scoped_query` falls back to user_id when device_id is None.**
   In aggregate mode (current_device_id is None but user_id is set), it
   filters by user only — which is the intended behaviour.
3. **Scheduler scope is set per device, then reset.** Never relies on
   request-context state. The `set_system_scope`/`reset_system_scope`
   pair must be inside a `try/finally`.
4. **NotificationLog dedupe keys MUST include `device_id`** to prevent
   cross-device suppression.
5. **Notification dispatch MUST resolve channel per (user, device,
   channel_type)** — never use the global `Setting` rows directly.

### 14b. Audit at fan-out boundary
At the start of each fan-out iteration, log:
```
[sync] device_id=N user_id=U scope_set
[sync] device_id=N rows_inserted=R
[sync] device_id=N scope_reset
```
This is the trail used to verify isolation in the test plan (§15).

### 14c. Forbidden patterns (lint with grep, fail CI)
- `AppDevice.query.first()` outside admin contexts → must be `filter_by(owner_user_id=user.id)`.
- `Reading.query` (without `scoped_query`) on subscriber pages → ban.
- `Setting.query.filter_by(key='telegram_*')` outside the migration
  helper → ban (use `UserChannel` resolver instead).

### 14d. Test fixtures
A new `tests/fixtures/multidevice.py` will create:
- 3 users
- 5 devices distributed across them (user1: 1, user2: 3, user3: 1)
- Pre-seeded readings, NotificationLog rows, UserLoad, etc.

Each test asserts that user2's device3 sync does NOT touch user1's
device1's tables.

---

## 15. Testing plan with at least 3 active devices

### 15a. Seed data (idempotent migration, dev-only)
Create or ensure:

| User              | Devices                         |
|-------------------|---------------------------------|
| `qa.subscriber.style` (existing) | 5 devices already (1 active, 4 disabled) — flip 2 more to active |
| `ahmad`           | add 2 more devices (Workshop, Farm)                              |
| New `qa.tri-device` | 3 fresh devices (Roof / Workshop / Farm) all active             |

Each device gets distinct `timezone`, `country`, `city`,
`battery_capacity_kwh`, fake credentials.

### 15b. Manual smoke-test plan
For each of the 3 multi-device users:

1. **Switcher round-trip**
   - Visit `/live-data?lang=ar`.
   - Open switcher dropdown → pick each of the 3 devices in turn.
   - Confirm hero tagline + context strip + KPIs update to that device's data.
   - Pick "All devices (aggregate)".
   - Confirm aggregate header + per-device breakdown.

2. **Per-device sync isolation**
   - On `/devices/manage`, click "★ Select" on device A; trigger manual sync.
   - Confirm only device A's `Reading` and `SyncLog` rows grew.
   - Repeat for B and C.

3. **Notification dedup per device**
   - Drop device A's battery to 19% → expect 1 telegram alert
     (`battery_low_20-{day}-{A.id}`).
   - Drop device B's battery to 19% on the same day → expect a SECOND
     alert with key `battery_low_20-{day}-{B.id}` (NOT suppressed).

4. **Channel routing per device**
   - Set device A's channel override to `email`, device B's to
     `telegram`, device C's to nothing (inherit default = telegram).
   - Trigger an event on each → confirm:
     - A → email arrives, no telegram.
     - B → telegram arrives, no email.
     - C → telegram arrives via default.

5. **Aggregate live-data**
   - Switch to aggregate mode.
   - Confirm: solar = sum of A+B+C, load = sum of A+B+C, battery shows
     a per-device breakdown table (NOT a single average).

6. **Backwards compat**
   - Log in as a single-device test user.
   - Confirm: no switcher, soft single-banner only, all pages render
     identically.

### 15c. Automated tests (proposed)
- `tests/test_v33_fanout.py` — assert that `fan_out_sync()` calls
  `_sync_one_device` exactly N times for N active devices, and that
  failures in one don't abort others.
- `tests/test_v33_dedup_per_device.py` — assert event_keys include
  device_id; same event on two devices fires twice.
- `tests/test_v33_channel_resolution.py` — three-tier resolution
  (per-device → user-default → none).
- `tests/test_v33_aggregate_no_leak.py` — user A in aggregate mode never
  sees user B's data.

### 15d. Performance budget
- Cycle time for 50 active devices in the most expensive job
  (`advanced_notifications_check`, every 30 s) must be < 25 s.
- Provider rate-limit guard ensures we don't burst beyond 1 req/sec
  per Deye account.

---

## 16. Phased delivery (proposed)

| Phase | Deliverable | Risk |
|-------|-------------|------|
| **v33-α: scheduler fan-out** | `app/scheduler.py` + new `fan_out_sync()` helper. No model changes. NotificationLog dedup keys updated to include device_id. Manual + 3-device test of sync + notification isolation. | Medium — touches scheduler timing |
| **v33-β: NotificationRule model + migration** | New table, backfill from `notification_rules_json`, new admin/subscriber rules UI. Old global rules marked `legacy=true` for one cycle. | Low — additive |
| **v33-γ: UserChannel model + migration** | New table, backfill from global `Setting` rows, new `/channels` UI. | Low — additive |
| **v33-δ: aggregate-mode page logic** | Update `/live-data`, `/statistics`, `/reports`, `/loads` route handlers to compute aggregates when `current_device_id` is None and `aggregate_mode=True`. Update templates. | Medium — visible UX change |
| **v33-ε: onboarding multi-device branch** | Wizard adds "Add another device" path that skips profile/channel steps already configured. | Low |
| **v33-ζ: dashboard fleet snapshot** | Add per-device sparkline strip + combined hero metrics. | Low |

Each phase is independently shippable. v33-α alone closes the biggest gap (scheduler isolation) and unlocks meaningful multi-device behaviour.

---

## 17. Out of scope for v33 (explicitly deferred)

- Cross-tenant device sharing.
- Real-time push (WebSocket) live-data — current 30-second poll stays.
- Per-device billing / per-device quota deduction (today plans cap by
  count only, which is fine).
- Removing the legacy Setting key/value table — kept for backwards
  reads during the v33-β/γ migration window.

---

## 18. Files this plan will eventually touch (no edits yet)

```
app/scheduler.py                            ← fan-out wrapper
app/blueprints/main.py                      ← sync_now_internal → split into _sync_one_device
app/blueprints/notifications.py             ← scheduler entrypoints, dedup keys, channel resolution
app/blueprints/notifications_routes.py      ← rules UI uses NotificationRule
app/blueprints/devices_routes.py            ← /loads add-load: pass device_id
app/blueprints/energy.py                    ← live-data/loads/statistics/reports aggregate logic
app/services/scope.py                       ← no signature change; possibly new helper for aggregate
app/services/device_context.py              ← already done for v32; minor aggregate-mode polish
app/services/channel_resolver.py            ← NEW: resolves (user,device,channel) → config
app/services/rule_resolver.py               ← NEW: resolves (user,device,rule_key) → config
app/models.py                               ← + UserChannel, + NotificationRule, NotificationLog dedup_key_version field
app/__init__.py                             ← _migrate_database adds the two new tables + their FK columns
app/templates/channels.html                 ← per-device channel matrix
app/templates/notifications.html            ← per-device rule UI
app/templates/_device_switcher.html         ← already aggregate-aware in v32; polish copy
app/templates/dashboard.html                ← fleet snapshot row
docs/design-qa/v33/v33-architecture-plan.md ← this file
docs/design-qa/v33/v33-test-plan.md         ← detailed test scripts
docs/design-qa/v33/v33-migration-runbook.md ← step-by-step boot migration
tests/test_v33_fanout.py                    ← NEW
tests/test_v33_dedup_per_device.py          ← NEW
tests/test_v33_channel_resolution.py        ← NEW
tests/test_v33_aggregate_no_leak.py         ← NEW
tests/fixtures/multidevice.py               ← NEW
```

---

## 19. Decisions needed from you before implementation

1. **Channel scope** — should `/channels` show "global to all my
   devices" OR force-per-device? **Recommended:** show global by
   default, allow per-device override.
2. **Aggregate battery SOC** — show **average**, **min**, **per-device
   breakdown**, or all three? **Recommended:** per-device breakdown
   only; an average is misleading.
3. **Provider rate-limit values** — confirm Deye allows ≥ 1 req/sec
   per account? Without this, 50-device accounts may hit 429s.
4. **Scheduler interval at scale** — the `advanced_notifications_check`
   runs every 30 s today. With 50 devices this becomes 50× the work.
   **Recommended:** stagger to one device per tick (round-robin) once
   we exceed N devices.
5. **Deprecate legacy global `notification_rules_json`** after v33-β
   migration — when? **Recommended:** keep it readable for one full
   release cycle (v34), then remove the read path in v35.

---

End of v33 architecture plan. No code has been changed in this pass.
