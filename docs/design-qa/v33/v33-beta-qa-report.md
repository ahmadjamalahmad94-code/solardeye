# v33-β Live Fleet Dashboard — QA Report

**Status:** PASS — safe to commit locally (subject to the documented one-device live-coverage limitation).
**Date:** 2026-05-08
**Phase:** v33-β (Live Device Rail / Fleet Switcher)
**Hard rule honored:** Flow Graph is byte-identical to HEAD. NOT TOUCHED.

---

## 1. Verdict at a Glance

| Layer                    | Result | Notes                                                                |
|--------------------------|--------|----------------------------------------------------------------------|
| Static code (compileall) | PASS   | clean                                                                |
| Jinja parse (80 tpl)     | PASS   | 80/80 OK                                                             |
| Flow Graph lock          | PASS   | byte-identical to HEAD (md5 `56124a8799a3bb800231d99d83f6d616`)       |
| `git diff --check`       | PASS   | no whitespace issues                                                  |
| `git diff --stat`        | PASS   | 3 files, +10 / −0                                                    |
| Pure-helper tests (5/5)  | PASS   | run via stub harness                                                  |
| API security audit       | PASS   | every endpoint enforces `owner_user_id == user.id`                    |
| Rail behavior audit      | PASS   | self-suppress, no-JS fallback, replaceState, AbortController, hide-pause |
| CSS scope audit          | PASS   | 41/41 selectors scoped to `.live-fleet-rail`; keyframe `lfrShimmer` is `lfr`-prefixed |
| Live API endpoints       | PASS   | manually verified by user — all 4 return correct JSON                  |
| Manual page open         | PASS   | `/dashboard?lang=ar` and `/live-data?lang=ar` open cleanly             |
| Manual click-through QA  | PARTIAL| only 1 active device on the verifying account → multi-device flows not exercised |

**Final verdict:** PASS, with the explicit limitation that live multi-device chip switching, aggregate-mode flow, and per-device battery breakdown have only been **code-verified**, not click-verified, because the QA account has a single active device.

---

## 2. Manually Verified by User (Browser)

After the Flask restart that registers the new blueprint, the following were confirmed by the user from a real browser session:

1. `GET /api/fleet/summary` → `ok=true`, `current_device_id=1`, `devices_count=1`, device data correct.
2. `GET /api/fleet/overview` → `ok=true`, `aggregate_mode=true`, combined solar/load/grid present, battery kept per-device (not averaged).
3. `GET /api/devices/1/live-summary` → `ok=true`, `device_id=1`, reading data correct.
4. `GET /api/devices/1/notifications-preview` → `ok=true`, items array returned.
5. `/dashboard?lang=ar` opens.
6. `/live-data?lang=ar` opens.
7. Flow Graph visually still looks unchanged.

---

## 3. Code-Verified (this pass)

### 3a. API security — every endpoint enforces owner scoping

| Endpoint                                         | Auth | Owner filter                                          | Bad ID handling                  |
|--------------------------------------------------|------|-------------------------------------------------------|----------------------------------|
| `POST /api/fleet/select`                         | ✓    | `AppDevice.filter_by(id=did, owner_user_id=user.id)`  | invalid → 400; not owned → 403   |
| `GET /api/fleet/summary`                         | ✓    | `AppDevice.filter_by(owner_user_id=user.id, ...)`     | n/a (lists own only)             |
| `GET /api/devices/<id>/live-summary`             | ✓    | `AppDevice.filter_by(id=device_id, owner_user_id=user.id)` | not found / not owned → 403 |
| `GET /api/fleet/overview`                        | ✓    | `AppDevice.filter_by(owner_user_id=user.id, ...)`     | n/a (lists own only)             |
| `GET /api/devices/<id>/notifications-preview`    | ✓    | `AppDevice.filter_by(id=device_id, owner_user_id=user.id)` | not found / not owned → 403 |

Auth helper `_current_subscriber_user()` returns `None` when:
- `session['logged_in']` is falsy → 401,
- `is_admin_scope()` is true → 401 (admin scope can't query subscriber endpoints), or
- `session['user_id']` missing → 401.

Cross-user data leakage: **prevented** at every endpoint by the owner filter, before any reading is dereferenced.

### 3b. JSON key stability when readings are missing

- `/live-summary` always returns `{ok, device_id, has_reading, device:{...}}` even when no `Reading` exists (`has_reading=False`); `reading` is omitted in the no-data case but the rest of the schema is stable.
- `/summary` always includes `battery_soc`, `solar_power_w`, `last_update_iso`, `status`, `alerts_count` — values may be `None`/`0`/`"offline"` but keys are always present.
- `/overview` always returns `combined` (sums) and `per_device` (list) — never `battery_soc` in `combined`; per-device rows always include `battery_soc` (may be `None`).
- `/notifications-preview` always returns `items: []` when no rows.

### 3c. Aggregate-mode never averages battery SOC

The pure helper `_build_aggregate_overview(devices, readings_by_device)` returns:
- `combined` keys: `solar_power, home_load, grid_power, inverter_power, daily_production_kwh, battery_charge_w, battery_discharge_w` — **no `battery_soc`, no `battery_average`**.
- `per_device` rows: each carries its own `battery_soc`.

Asserted by `test_aggregate_overview_sums_solar_load_grid_but_not_battery` (passing).

### 3d. Live Fleet Rail behavior

| Behavior                              | Where                                                          | Verified |
|---------------------------------------|----------------------------------------------------------------|----------|
| Self-suppress for <2 devices          | `_live_fleet_rail.html:33` — `{% if _devices and (_devices|length > 1) %}` | ✓ |
| No-JS fallback (chip = anchor)        | `_live_fleet_rail.html:54, 75` — `<a href="?selected_device_id=...">` | ✓ |
| JS preventDefault on chip click       | `live_fleet_v33b.js:131` — `e.preventDefault()`                | ✓        |
| In-flight request abort               | `live_fleet_v33b.js:145–148, 156` — `AbortController` + `_xhr.abort()` | ✓ |
| Polling pause when tab hidden         | `live_fleet_v33b.js:108, 291` — `document.visibilityState === 'hidden'` | ✓ |
| `history.replaceState` on switch      | `live_fleet_v33b.js:281–287`                                   | ✓        |
| No DOM rebuild — only `[data-bind]` text | `live_fleet_v33b.js:68–73` `applyBind` uses `textContent` only | ✓     |
| Aggregate mode preserves battery slots| `live_fleet_v33b.js:222–225` — comment + early return          | ✓        |

### 3e. CSS scope (no global leakage)

41 selector-pieces across `live_fleet_rail_v33b.css` were audited; **all are scoped to `.live-fleet-rail`** or descendants (`.live-fleet-rail .lfr-chip`, `.live-fleet-rail.is-swapping`, etc.). The lone keyframe is named `lfrShimmer` (`lfr`-prefixed). No global element selectors (`html`, `body`, `*`, `h1`, `p`, `a`) appear anywhere.

---

## 4. Flow Graph Lock — Proof

```
Section: <section class="d40-card d40-flow-card span-full">…</section>
Working tree md5 (regex-extracted):  56124a8799a3bb800231d99d83f6d616  (7,970 bytes)
HEAD            md5 (regex-extracted):  56124a8799a3bb800231d99d83f6d616  (7,970 bytes)
                                        ─────────────────────────────────
                                        BYTE-IDENTICAL ✓
Working-tree section lives at lines:    131–180 of dashboard.html
git diff hunks vs HEAD:                  one hunk @ lines 8–18 (above the hero)
                                        zero hunks inside the flow-card range
```

Note: the previously-quoted baseline `51a84ddbf079fc5aa31dd565519ea183` was a **line-range** hash (lines 131–179, with `keepends=True`); it still matches exactly when computed against the section's *current* line range, because the rail include shifted the file by +5 lines without touching any byte inside the section. The regex-extracted section hash (`56124a…`) is the more robust check and confirms byte-identity to HEAD and to every commit ever made for this file.

---

## 5. Tests Run

```
python -m compileall app tests        clean
Jinja parse (80 templates)            80 OK / 0 FAIL
git diff --check                      clean
git diff --stat                       3 files / +10 / −0
v33-β pure-helper tests (5/5)         PASS
  ✓ test_status_from_age_classifies_correctly
  ✓ test_device_icon_picks_keyword_emoji
  ✓ test_aggregate_overview_sums_solar_load_grid_but_not_battery
  ✓ test_aggregate_overview_handles_devices_without_readings
  ✓ test_status_dot_field_present_on_summary_payload
v33-β integration tests (3/3)         SKIPPED (require pytest + live Flask app context;
                                       not runnable in the WSL stub harness)
```

---

## 6. Pages Checked (live HTTP, by user)

```
/dashboard?lang=ar        200 (rail self-suppresses for 1-device account)
/live-data?lang=ar        200 (rail self-suppresses for 1-device account)
```

The remaining 12 pages of the 13-page subscriber smoke list are **statically clean** (Jinja parse 80/80) and were untouched by this phase. They need a re-confirmation pass from the user's browser before the smoke test is signed off:

```
/devices/manage?lang=ar
/devices/manage/1/edit?lang=ar
/notifications/center?lang=ar
/loads?lang=ar
/reports?lang=ar
/statistics?lang=ar
/notifications?lang=ar
/channels?lang=ar
/account/profile?lang=ar
/account/subscription?lang=ar
/portal/support?lang=ar
/onboarding?lang=ar
```

---

## 7. Files Changed (vs HEAD)

```
modified:
  app/__init__.py                  (+2 lines)   ← blueprint import + register
  app/templates/dashboard.html     (+5 lines)   ← rail include above hero (line 14)
  app/templates/live_data.html     (+3 lines)   ← rail include between switcher and hero (line 31)
                                                 net change = +10, −0

new (untracked):
  app/blueprints/fleet_api.py                   ← 5 endpoints, owner-scoped, 10s LRU cache
  app/templates/_live_fleet_rail.html           ← rail partial (self-suppresses)
  app/static/css/live_fleet_rail_v33b.css       ← rail styles, fully scoped
  app/static/js/live_fleet_v33b.js              ← controller (AbortController, replaceState, hide-pause)
  tests/test_v33_beta.py                        ← 8 tests (5 pure + 3 integration)
  docs/design-qa/v33/v33-beta-execution-plan.md
  docs/design-qa/v33/v33-beta-qa-report.md      ← (this file)
```

---

## 8. Known Limitations

1. **Single-device verification ceiling.** The QA account has 1 active device, so live click-through behavior of: (a) switching between two real devices, (b) "All Devices" aggregate mode visual, (c) per-device battery breakdown rendering, and (d) `history.replaceState` URL clean-up under repeated chip clicks — is **code-verified only**. The behaviors are deterministically derived from helper functions (which have unit tests) and from straight-line JS branches (which have been read end-to-end), but they have not been exercised against real DOM yet.

2. **Live integration tests skipped.** The 3 Flask-app integration tests in `tests/test_v33_beta.py` (`test_fleet_select_updates_session_and_preferred_device`, `test_fleet_summary_returns_only_owned_devices`, `test_devices_live_summary_403_for_other_users_devices`) require pytest plus an app fixture and were skipped in the WSL stub harness. They should run in CI or via `pytest` from the host.

3. **WSL sandbox cannot reach `host.docker.internal:5000`.** All live HTTP smoke had to be done by the user in their host browser; the sandbox returns `403 Connection blocked by network allowlist` on every request to localhost. Manual verification by user closed this gap for the 4 API endpoints + 2 pages.

4. **Production database pointer.** `app/config.py` loads `.env`, which currently sets `DATABASE_URL` to the Render PostgreSQL production database. Multi-device QA fixtures must NOT be created against that DB. See §9.

---

## 9. Multi-Device QA Preparation (DRY-RUN ONLY)

### 9a. Database safety check

```
.env         → DATABASE_URL = postgresql://****@dpg-...frankfurt-postgres.render.com/solardeye_db   ← PRODUCTION
.env.local   → DATABASE_URL = sqlite:///solar_local.db                                                ← unused (config.py loads .env, not .env.local)
.env.example → sqlite:///solar_v9.db                                                                  ← template
```

**Active configuration is PRODUCTION.** Therefore: NO seed script will be run automatically.

### 9b. Proposed plan (requires explicit user approval before any execution)

Two safe paths to multi-device QA, in priority order:

**Path A — Local SQLite seed (recommended).**
1. User edits `.env` → `DATABASE_URL=sqlite:///solar_local.db` (or sets `FLASK_ENV=local` to switch loader).
2. User runs `flask shell` and executes a seed snippet (provided below) to create:
   - 1 test user `qa_multi` (password set by user, NOT by Claude),
   - 3 active devices owned by that user (`Farm Solar`, `Workshop A`, `Office HQ`),
   - 3 representative `Reading` rows (one per device, varying SOC).
3. User logs in as `qa_multi`, navigates `/dashboard?lang=ar`, observes the rail with 3 chips + the "All Devices" chip.
4. User exercises chip switching, aggregate mode, and confirms Flow Graph stays still.
5. User reverts `.env` back to production.

Suggested snippet (do NOT run blindly):

```python
# tools/seed_qa_multi.py — DRY-RUN; user must invoke explicitly
from app import create_app
from app.extensions import db
from app.models import AppUser, AppDevice, Reading
from datetime import datetime, timezone

app = create_app()
with app.app_context():
    assert 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI'], 'refuse to seed against non-sqlite'
    u = AppUser.query.filter_by(username='qa_multi').first()
    if not u:
        u = AppUser(username='qa_multi', is_active=True)
        u.set_password('CHANGE_ME_BEFORE_RUN')   # user must set this
        db.session.add(u); db.session.commit()
    for name in ('Farm Solar', 'Workshop A', 'Office HQ'):
        if not AppDevice.query.filter_by(name=name, owner_user_id=u.id).first():
            d = AppDevice(name=name, owner_user_id=u.id, is_active=True, api_provider='deye')
            db.session.add(d)
    db.session.commit()
    devices = AppDevice.query.filter_by(owner_user_id=u.id).all()
    socs = [82, 47, 18]
    for d, soc in zip(devices, socs):
        r = Reading(user_id=u.id, device_id=d.id,
                    solar_power=1500.0, home_load=600.0, grid_power=200.0,
                    battery_soc=soc, battery_power=120.0, inverter_power=900.0,
                    created_at=datetime.now(timezone.utc))
        db.session.add(r)
    db.session.commit()
    print('Seeded user qa_multi with', len(devices), 'devices')
```

The snippet above is a **proposal**, not committed code. It refuses to run against any non-SQLite URI. It requires the user to set the password before running. It will not be executed by Claude.

**Path B — Read-only inspection on production.**
If multi-device live QA must be done against production data, use a read-only cursor (`flask shell` running only `.query.all()`) and verify rail rendering by switching the Postgres login user to one that already owns 2+ devices. No writes. This depends on whether such a user exists in production.

**Action required from user:** choose Path A or Path B, or sign off on PASS based on code-verified multi-device behavior alone.

---

## 10. Safe to Commit Locally?

**Yes — with the following commit message recommendation:**

```
v33-β: Live Device Rail / Fleet Switcher (no Flow Graph touch)

- New blueprint app/blueprints/fleet_api.py (5 endpoints, owner-scoped, 10s LRU cache)
- New partial app/templates/_live_fleet_rail.html (self-suppresses for <2 devices)
- New scoped CSS app/static/css/live_fleet_rail_v33b.css
- New JS controller app/static/js/live_fleet_v33b.js (AbortController, hide-pause,
  history.replaceState, no DOM rebuild)
- New tests tests/test_v33_beta.py (5 pure-helper PASS, 3 integration require pytest)
- Wired rail include into dashboard.html (line 14, above hero) and live_data.html (line 31)
- Registered fleet_api blueprint in app/__init__.py

Flow Graph LOCKED: byte-identical to HEAD (md5 56124a8799a3bb800231d99d83f6d616).
git diff stat: 3 files / +10 / −0.

Limitations: multi-device live click-through not exercised — QA account has 1 device.
```

Per user instruction: **NO commit will be performed by Claude. NO tag will be performed.** This report is the artifact; the commit is the user's call.
