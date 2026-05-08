# v33-alpha — True Multi-Device Fan-Out — Execution Plan

**Status:** PLAN ONLY. No code changes. Awaiting approval.

**Tag (future):** `v33-alpha-true-multidevice-fanout`

**Sub-scope only:**
1. Scheduler fan-out across active devices
2. Notification dedup keys include `device_id`
3. `/loads` add-action saves `device_id`
4. NO new tables (UserChannel / NotificationRule deferred to β / γ)

Everything else from the v33 master plan stays deferred.

---

## 1. The exact files and functions I will edit

| # | File | Function/area | Why |
|---|---|---|---|
| 1 | `app/scheduler.py` | `_build_job(app, fn_path)` | Stop calling `get_default_system_device`. Replace with a fan-out wrapper that decides per-job whether to fan out per device or run once globally. |
| 2 | `app/scheduler.py` | New helper `_fan_out_per_device(app, fn_path)` | Iterate `AppDevice.query.filter_by(is_active=True)`, group by provider account, set system scope per device, run job, isolate failures, reset scope. |
| 3 | `app/scheduler.py` | New helper `_provider_account_signature(device)` | Returns a hash key of `(api_provider, deye_app_id or email)` so devices sharing one cloud account get one auth call. |
| 4 | `app/scheduler.py` | New helper `_throttle_for_provider(provider_code)` | Returns `min_seconds_between_calls` per provider. Defaults: deye=0.5, solarman=1.0, tuya=0.3, others=0.0. |
| 5 | `app/blueprints/notifications.py` | `dispatch_notification(...)` | Append `device_id` suffix to the `event_key` if `current_scope_ids()` returns a device. |
| 6 | `app/blueprints/notifications.py` | `notification_exists(event_key, since)` | No change — already uses `scoped_query(NotificationLog)` which filters by current device. The dedup key change makes per-device dedup work because the key itself is now device-distinct. |
| 7 | `app/blueprints/notifications.py` | `_send_scheduled_notification(prefix, ...)` | The internal helper that fires scheduler-driven alerts. Confirm it routes through `dispatch_notification` so it inherits the new dedup behaviour. |
| 8 | `app/blueprints/notifications.py` | Top of each scheduler entrypoint (`run_advanced_notification_scheduler`, `run_weather_checks`, `send_daily_weather_summary`, `send_daily_morning_report`) | Add 1-line guard: log `device_id` from `current_scope_ids()` at start of each invocation. No iteration here — fan-out is done by the scheduler wrapper. |
| 9 | `app/blueprints/energy.py` | `loads_page()` — `if action == 'add':` branch | Pass `device_id=current_device_id` to the `UserLoad(...)` constructor. Reject when `aggregate_mode` is true and require the user to pick a target device first. |
| 10 | `app/templates/loads.html` | Add-load form | Add a hidden `device_id` field auto-populated from `current_device_id`; in aggregate mode, replace with a visible `<select>` of the user's devices. Render an inline warning when no device is selected. |
| 11 | `app/blueprints/main.py` | `sync_now_internal(trigger='auto')` | NO API change. The function still syncs **the current scope's device**. The fan-out at scheduler level is what loops over devices and re-invokes this function under each device's scope. This keeps the manual-sync path working unchanged. |
| 12 | `app/services/scope.py` | NO change | The existing `set_system_scope` / `current_scope_ids` are exactly the API the wrapper needs. |
| 13 | `app/services/service_monitor.py` | `heartbeat(service_key, …)` callers | Each per-device run writes a heartbeat with key `f'{fn_path}::device-{d.id}'` so the admin services-health page can show per-device status. (The function itself is unchanged; only callers add the suffix.) |
| 14 | `tests/test_v33_alpha.py` | New | Three test functions: `test_fanout_iterates_all_active_devices`, `test_dedup_key_per_device`, `test_loads_add_carries_device_id`. |
| 15 | `tests/fixtures/multidevice_alpha.py` | New | Builds 3 active devices on a test user with distinct provider signatures. |
| 16 | `docs/design-qa/v33/v33-alpha-execution-plan.md` | this file | — |
| 17 | `docs/design-qa/v33/v33-alpha-test-plan.md` | NEW | Detailed manual + automated test scripts (see §5 below). |
| 18 | `docs/design-qa/v33/v33-alpha-runbook.md` | NEW | Pre-deploy checklist, restart steps, rollback plan. |

**Files NOT touched in α:**
- `app/models.py` — no new columns or tables.
- `app/__init__.py:_migrate_database` — no new migrations.
- `app/templates/_device_switcher.html` — already aggregate-aware in v32.
- `app/templates/notifications_center.html`, `live_data.html`, `notifications.html`, `channels.html`, `account_*.html` — α adds no new UI to these.
- All admin templates and CSS — untouched.

---

## 2. Fan-out helper structure

### 2a. Job classification (decided at scheduler-build time)

Two job classes:

```python
GLOBAL_JOBS = {
    # runs once per cycle, no device scope set
    'database_backup_maintenance',
}

PER_DEVICE_JOBS = {
    # fan out across all active devices each cycle
    'deye_auto_sync',
    'advanced_notifications_check',
    'weather_change_check',
    'weather_daily_summary',
    'daily_morning_report',
}
```

`_build_job(app, fn_path, job_id)` reads `job_id` and dispatches to either `_run_once_global(...)` or `_run_per_device(...)`. The existing `_build_job` becomes a thin router; the actual work moves into the two new helpers.

### 2b. The fan-out helper (proposed shape, NOT code)

```
def _run_per_device(app, fn_path):
    with app.app_context():
        devices = AppDevice.query.filter_by(is_active=True) \
                                 .order_by(AppDevice.id.asc()).all()
        if not devices:
            log_skip('no active devices'); return

        # Group by provider account so we can reuse one auth token
        groups = group_by(_provider_account_signature, devices)

        # Heartbeat-overall: 'started'
        heartbeat(fn_path, status='running', extra={'device_count': len(devices)})

        successes, failures = [], []

        for sig, group in groups.items():
            min_sleep = _throttle_for_provider(group[0].api_provider or 'deye')
            for d in group:
                tokens = set_system_scope(d.owner_user_id, d.id)
                try:
                    _invoke(fn_path)             # imports + calls fn
                    heartbeat(f'{fn_path}::device-{d.id}', status='ok',
                              extra={'device_name': d.name, 'owner': d.owner_user_id})
                    successes.append(d.id)
                except Exception as exc:
                    log_event('warning',
                              f'{fn_path} failed for device_id={d.id}: {exc}')
                    SyncLog(level='error', message=f'{fn_path} fail: {exc}',
                            user_id=d.owner_user_id, device_id=d.id).save()
                    heartbeat(f'{fn_path}::device-{d.id}', status='failed',
                              extra={'error': str(exc)[:200]})
                    failures.append(d.id)
                finally:
                    reset_system_scope(tokens)
                    if min_sleep > 0:
                        time.sleep(min_sleep)

        heartbeat(fn_path,
                  status='ok' if not failures else 'partial',
                  extra={'ok': len(successes), 'fail': len(failures)})
```

### 2c. The global-job helper

```
def _run_once_global(app, fn_path):
    with app.app_context():
        # No scope set; job is intentionally device-blind
        heartbeat(fn_path, status='running')
        try:
            _invoke(fn_path)
            heartbeat(fn_path, status='ok')
        except Exception as exc:
            heartbeat(fn_path, status='failed', extra={'error': str(exc)[:200]})
            raise
```

### 2d. `_invoke(fn_path)` (existing logic preserved)

The current logic from `_build_job` that does:
```python
module_path, fn_name = fn_path.rsplit('.', 1)
mod = importlib.import_module(module_path)
if fn_path == 'app.blueprints.main.sync_now_internal':
    getattr(mod, fn_name)(trigger='auto')
else:
    getattr(mod, fn_name)()
```
moves into a small `_invoke(fn_path)` helper. No behavioural change.

### 2e. Why this shape (not `concurrent.futures`)

- APScheduler `max_instances: 1` and `coalesce: True` already serialize cycles. Adding a thread pool inside a single cycle would let two devices for the same Deye account hit the cloud in parallel — breaking the rate-limit guard.
- Sequential-within-group is the safest first step.
- Cross-group parallelism (one Deye + one Tuya simultaneously) is a clean follow-up once the sequential version is verified at scale.

---

## 3. How I will avoid provider rate-limit bursts

### 3a. Two safeguards layered

1. **Per-account token reuse.** All devices in the same provider-account group share one `obtain_token()` call. Today `DeyeClient.__init__` does NOT cache tokens between instances; v33-α's wrapper holds the token outside the client and passes it in via a new `token=` argument (or a small wrapper that monkey-patches the cached token). The simpler path: **one DeyeClient per group, called multiple times**, since the token is already in `self.session.headers` after the first auth.

2. **`_throttle_for_provider(provider_code)` sleep between devices in the same group.** Defaults:
   - `deye` → 0.5 s
   - `solarman` → 1.0 s
   - `tuya` → 0.3 s
   - unknown → 0.0 s
   These are the conservative numbers based on public docs (Deye allows 60 req/min per account = 1/sec; we leave 50% headroom).

### 3b. What we explicitly do NOT do in α

- We don't add a true sliding-window rate limiter. If a future v33-β user comes with a 100-device Deye account, we will revisit. For α the constant-sleep approach is enough.
- We don't introduce a Redis/IPC-shared throttle. The scheduler runs in a single process today; in-process state is sufficient.

### 3c. Detection of 429s

If a provider call returns 429 / "Too Many Requests" / similar, the per-device exception handler catches it, logs a `SyncLog(level='warning', message='rate_limited')`, and continues to the next device. The next cycle (5 min later) retries that device naturally.

### 3d. Backoff escalation
Single-cycle backoff only. If a device hits 429 three cycles in a row, the wrapper writes a `connection_status='throttled'` on the AppDevice and skips it for the next cycle. Reset on next successful sync. This avoids the noisy-neighbor hammer pattern.

---

## 4. How I will log per-device success/failure

### 4a. Three log channels, all already in the codebase

1. **`SyncLog`** — one row per device per cycle, with `user_id`, `device_id`, `level` (`info`/`warning`/`error`), and `message`. Already device-scoped. Already used by /admin/system-logs view.
2. **`heartbeat()` (`service_monitor`)** — feeds the /admin/services-health dashboard. v33-α adds per-device sub-keys: `f'{fn_path}::device-{d.id}'`. Each row stores `status` (`running`/`ok`/`partial`/`failed`), `last_seen_at`, `details_json` (device name, owner id, error msg). Falls under the existing `ServiceHeartbeat` model — no new schema.
3. **`log_event()`** (existing console + structured log helper) — emits `INFO` lines like `[v33-α] cycle=advanced_notifications_check device_id=12 ok=true elapsed=0.42s`.

### 4b. Per-cycle summary line

At the end of each cycle, one summary log:
```
[v33-α] fan_out fn=advanced_notifications_check
        groups=2 devices=5 ok=4 fail=1
        failed_ids=[7] elapsed=2.18s
```

### 4c. Admin observability
The /admin/services-health page already lists each `ServiceHeartbeat` row. With per-device sub-keys, the admin will see one row per (job × device) instead of one row per job — surfacing isolation problems immediately.

### 4d. No new tables for logging
We piggyback on `SyncLog`, `ServiceHeartbeat`, `EventLog`. All three already have `device_id`/`user_id`.

---

## 5. Test plan with 3 active devices

### 5a. Test fixture (`tests/fixtures/multidevice_alpha.py`)

```
Build:
  user A: id=901  qa.alpha.three  (subscriber)
  device A1: id=9001  Roof       provider=deye   creds=(app1, email1@test) tz=Asia/Hebron
  device A2: id=9002  Workshop   provider=deye   creds=(app1, email1@test) tz=Asia/Riyadh
  device A3: id=9003  Farm       provider=solarman creds=(token9003)      tz=Asia/Hebron
  All 3 active. preferred_device_id = 9001.
  Pre-seed:
    - one Reading per device (different timestamps, different battery_soc).
    - empty NotificationLog.
    - one UserLoad each, scoped to its device_id.
```

A1 and A2 share a Deye account → expect ONE `obtain_token` call per group, two `station_latest` calls.
A3 is a different provider → its own group.

### 5b. Manual smoke test (after Flask restart)

Three sequenced tests:

**T1: scheduler fan-out touches all 3 devices**
1. Note current `Reading` row counts per device.
2. Trigger `deye_auto_sync` manually (force run).
3. After 30 s, check:
   - device A1 has +1 Reading.
   - device A2 has +1 Reading.
   - device A3 has +1 Reading.
   - SyncLog has 3 new info rows (or 3 warning rows, but distributed across all 3 device_ids).
   - heartbeat keys exist: `app.blueprints.main.sync_now_internal::device-9001`, `…-9002`, `…-9003`.

**T2: failure isolation**
1. Mark A2's `credentials_json` as broken ({"deye_app_secret": "bad"}).
2. Trigger `deye_auto_sync`.
3. Confirm:
   - A1 has +1 Reading (still ok).
   - A2 has 0 new Reading + a SyncLog level=error row.
   - A3 has +1 Reading (still ok).
   - heartbeat for A2 is `failed`, others `ok`.
4. Restore A2 credentials, next cycle restores it.

**T3: notification dedup per device**
1. Inject low-battery (`battery_soc=18`) into the latest Reading for both A1 and A2 (same day).
2. Trigger `advanced_notifications_check`.
3. Confirm `NotificationLog`:
   - one row with `device_id=9001`, `event_key='discharge-20-{day}-9001'`
   - one row with `device_id=9002`, `event_key='discharge-20-{day}-9002'`
4. Trigger again 30 s later.
5. Confirm dedup (`dedupe_minutes`) prevents new rows for same key; A1 and A2 still independent.

**T4: /loads add carries device_id**
1. Log in as user A. `current_device_id = 9001`.
2. Add a load "Fridge 150W" via /loads form.
3. Confirm new `UserLoad` row has `device_id=9001`.
4. Switch to A2 via `?selected_device_id=9002`.
5. Add "AC 1500W" via /loads form.
6. Confirm new row has `device_id=9002`.
7. Switch to aggregate mode (`?selected_device_id=__all__`).
8. Try to submit /loads add form → expect inline warning "Pick a device first" and form does not submit.

**T5: backwards compat — single-device user**
1. Log in as a different test user with one device.
2. Visit all 13 subscriber pages.
3. Confirm:
   - single-device banner above hero.
   - no aggregate mode shown.
   - all data exactly as v32.
4. Wait for one scheduler cycle.
5. Confirm: their device gets exactly one Reading per cycle, dedup keys include device_id, no behaviour change visible.

**T6: 13-page subscriber smoke (regression)**
Repeat the v32 final smoke test on all 13 subscriber pages — every page must still return HTTP 200 and render its v32 design intact.

### 5c. Automated tests (`tests/test_v33_alpha.py`)

```
def test_fanout_iterates_all_active_devices(monkeypatch, multidevice_alpha):
    """fan_out_per_device calls _invoke once per active device."""
    calls = []
    monkeypatch.setattr('app.scheduler._invoke', lambda fn: calls.append(current_scope_ids()))
    _run_per_device(app, 'app.blueprints.main.sync_now_internal')
    assert sorted(d for _,d in calls) == [9001, 9002, 9003]

def test_failure_in_one_device_does_not_abort_others(monkeypatch, multidevice_alpha):
    def boom(fn_path):
        if current_scope_ids()[1] == 9002: raise RuntimeError('simulated')
    monkeypatch.setattr('app.scheduler._invoke', boom)
    _run_per_device(app, 'app.blueprints.main.sync_now_internal')
    failures = SyncLog.query.filter_by(level='error').all()
    assert {f.device_id for f in failures} == {9002}
    assert {f.device_id for f in SyncLog.query.filter(SyncLog.level != 'error').all()} >= {9001, 9003}

def test_dedup_key_per_device(multidevice_alpha):
    set_system_scope(901, 9001); dispatch_notification(load_settings(), 'discharge-20', 'r','t','m','telegram','warning'); reset_system_scope(...)
    set_system_scope(901, 9002); dispatch_notification(load_settings(), 'discharge-20', 'r','t','m','telegram','warning'); reset_system_scope(...)
    rows = NotificationLog.query.filter(NotificationLog.event_key.startswith('discharge-20')).all()
    assert {r.device_id for r in rows} == {9001, 9002}
    assert all('::device-' in r.event_key for r in rows)

def test_loads_add_uses_current_device(multidevice_alpha, client):
    login(client, 'qa.alpha.three')
    client.post('/loads', data={'action':'add','name':'Fridge','power_w':150,'priority':1,'lang':'ar'})
    rows = UserLoad.query.filter_by(user_id=901, device_id=9001).all()
    assert any(r.name == 'Fridge' for r in rows)

def test_loads_add_in_aggregate_requires_device(multidevice_alpha, client):
    login(client, 'qa.alpha.three')
    client.get('/?selected_device_id=__all__')
    resp = client.post('/loads', data={'action':'add','name':'AC','power_w':1500,'priority':1})
    assert resp.status_code == 400
    assert 'pick a device' in resp.data.decode().lower() or 'اختر' in resp.data.decode()
```

### 5d. Pass criteria
- All 4 manual tests T1–T5 pass.
- T6 regression smoke is green (13/13 HTTP 200).
- All 5 automated tests pass.
- `python -m compileall -f app/` clean.
- `python -m pytest tests/test_v33_alpha.py -v` all green.
- Admin pages remain non-regressive.

---

## 6. What stays deferred to v33-β / γ / δ / ε / ζ

| Phase | Scope | Why deferred |
|---|---|---|
| **β** | `NotificationRule` model + migration + per-device rules UI | New table + non-trivial backfill. α keeps using global `notification_rules_json` as fallback. |
| **γ** | `UserChannel` model + migration + per-device channel matrix | Same reasoning. α keeps using global `telegram_*` / `sms_*` settings. Notifications dispatched in α use global channels for everyone — but dedup is per-device, which already eliminates the noisy cross-device spam. |
| **δ** | Aggregate-mode page logic on /live-data, /statistics, /reports, /loads list | Substantial template + route work. α keeps "all devices" mode visible only as a UI label; computed aggregates come later. |
| **ε** | Onboarding multi-device branch | α-blocked-on-β/γ for channel/rule setup of additional devices. |
| **ζ** | Dashboard fleet snapshot row | Pure additive UI, no urgency. |

---

## 7. Backwards compatibility gates (must hold for α)

1. **Single-device users** see no behavioural change. Soft single-banner stays. Same Reading cadence, same notifications, same channels.
2. **Existing v32 templates** unchanged in α except `loads.html` (small device-id field).
3. **Admin pages** untouched. `is_admin_scope()` short-circuit still active in `services.device_context`.
4. **Existing routes** keep their signatures. `sync_now_internal(trigger='auto')` keeps the same API; the scheduler just calls it under each device's scope.
5. **Existing global Settings** still readable. Channels and rules read from `Setting` table for now; α only adds device-id to dedup keys, doesn't touch the resolver.
6. **DB schema** unchanged. No new tables, no new columns, no migrations.
7. **Render compat** preserved (no new dependencies).

---

## 8. Risks and how they are mitigated

| Risk | Mitigation |
|---|---|
| Provider 429 from too-fast loops | `_throttle_for_provider` sleep between devices in a group; `connection_status='throttled'` after 3 strikes. |
| One device's exception aborting the cycle | `try/except` wraps each device individually; failure recorded in SyncLog + heartbeat. |
| Scheduler cycle time blowing up at scale | α targets ≤ 50 active devices total. Above that, the v33 master plan §15 triggers (round-robin staggering). |
| Cross-device notification suppression (the bug we're fixing) | Dedup key now includes `device_id`. Verified by automated test `test_dedup_key_per_device`. |
| Stale `g.current_device` leaking into a scheduler-driven render | Scheduler runs without a request context. `g` is unavailable. Scope is set only via `set_system_scope` ContextVars. |
| User adds a load while in aggregate mode without picking a device | `loads_page` rejects with 400 + inline warning. UI hides the form behind a "Pick a device" prompt in aggregate mode. |
| α merged but Flask not restarted | Same risk as v32. The α runbook explicitly notes that the new scheduler wiring requires `python app.py` restart. |

---

## 9. Pre-merge checklist

- [ ] `python -m compileall -f app/` clean.
- [ ] All 5 automated tests in `tests/test_v33_alpha.py` pass.
- [ ] All 6 manual tests T1–T6 pass with the 3-device fixture.
- [ ] 13-page subscriber smoke test all 200 OK.
- [ ] Admin 4-page recheck (dashboard / support / devices / design-qa) all visually identical to v32 baseline.
- [ ] No new dependencies in `requirements.txt`.
- [ ] No null-byte corruption in any touched file.
- [ ] `git diff --check` clean (no whitespace / merge marks).
- [ ] No secrets added to tracked files.
- [ ] Runbook documents the restart step + rollback path.

---

## 10. Approval gate

This plan is **for review only**. I will not write any code or modify any
files until you reply "approved" (or "approved with changes: …").

Once approved, the implementation order will be:

1. Write `tests/fixtures/multidevice_alpha.py` first (so tests can be
   authored before code).
2. Write `tests/test_v33_alpha.py` with failing tests.
3. Edit `app/scheduler.py` — add `_run_per_device`, `_run_once_global`,
   helper functions; rewrite `_build_job` to route.
4. Edit `app/blueprints/notifications.py` — append device_id to dedup
   key in `dispatch_notification`.
5. Edit `app/blueprints/energy.py` — fix `loads_page` add branch.
6. Edit `app/templates/loads.html` — device picker in aggregate mode.
7. Run `python -m compileall -f app/`.
8. Run `pytest tests/test_v33_alpha.py -v`.
9. Restart Flask. Run manual T1–T6 in the browser.
10. Write `docs/design-qa/v33/v33-alpha-test-plan.md` and
    `v33-alpha-runbook.md` with actual results.
11. Tag `v33-alpha-true-multidevice-fanout`.

End of v33-α execution plan. NO code has been changed.
