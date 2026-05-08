# v33-β — Live Fleet Dashboard — Execution Plan (PLAN ONLY)

**Status:** PLAN ONLY. No code has been written. Awaiting approval.

**Tag (future):** `v33-beta-live-fleet-dashboard`

---

## 0. Locked / protected components — must NOT be modified

The following must remain visually and functionally **identical** to their
current v32 / v33-α state. The β plan adds new components AROUND them but
never inside, never replacing them, never restyling them. If any change
in this phase appears to require touching one of these, **STOP** and ask
before editing.

### 0.1 The Flow Graph (HARD LOCK)

Location: `app/templates/dashboard.html`, lines ~125-180, inside
`<section class="d40-card d40-flow-card span-full">`.

Locked elements:
- `<section class="d40-card d40-flow-card span-full">` and its children
- `<div class="d40-flow-shell">`
- `<div class="d40-flow-side">` (the 6 left-rail stat tiles)
- `<div class="deye-flow-stage official-flow-stage">`
- `<svg class="flow-svg official-flow-svg" viewBox="0 0 900 560">`
- All `<path>` track lines (`#solarTrack`, `#gridTrack`, `#batteryTrack`, `#homeTrack`)
- All `<circle class="flow-dot ...">` and their `<animateMotion>` blocks
- All 5 `<div class="flow-box ...">` boxes (solar / grid / inverter / battery / home)
- All CSS selectors prefixed: `.d40-flow-*`, `.deye-flow-*`, `.official-flow-*`, `.flow-svg`, `.flow-box`, `.track-base`, `.track-animated`, `.flow-dot`, `.dot-use`, `.dot-charge`, `.dot-idle`, `.flow-state`, `.flow-value`, `.flow-title`, `.icon-wrap`, `.soc-tag`, `.energy-use`, `.energy-charge`, `.energy-idle`, `.active`, `.reverse` (when used inside the flow stage).
- The `data-bind="..."` hooks on flow-graph elements (`battery.mode_label`, `latest.solar_power`, `latest.home_load`, `battery.soc_label`, `latest.grid_power`, `production_summary.today_kwh`, `latest.solar_power_short`, `latest.grid_power_short`, `status.title_short`, `battery.soc_pct`, `battery.flow_w`, `latest.home_load_short`, `weather.icon`, `weather.temp`, `weather.cond`, `prediction.*`, `phase.*`, `hero.*`).

The `data-bind` attributes are how the existing live-update mechanism
talks to the flow graph. v33-β reuses this same protocol on its NEW
components — it does **not** modify any existing `data-bind` consumer.

### 0.2 Other locked surfaces in this phase
- All admin templates and admin CSS (untouched).
- All v32-redesigned subscriber pages **except** the dashboard (`/dashboard`) and live-data (`/live-data`) — and even there, only NEW sections are added; existing sections are untouched.
- The sidebar (`_sidebar.html`, `sidebar_rebuild_v11.css/js`).
- The build badge (`.dev-build-badge-v11`).
- All v33-α additions (scheduler fan-out, dedup keys, /loads device_id, scope.py guards, auth.py guards).

---

## 1. Live Device Rail / Fleet Switcher component

### 1.1 Visual spec

A horizontal bar (or, on mobile, a horizontal scrollable strip) of
device chips that lives **above** the existing dashboard hero AND above
the existing live-data hero. Lives ABOVE the existing `_device_switcher.html`
banner (which stays for backwards compat) on its first render, then
either replaces or absorbs that banner once the rail is verified.

```
┌─────────────────────────────────────────────────────────────────────┐
│ [📊 All Devices ●] [🏠 Roof  ☀1.5kW  🔋87%  online] [🏭 Workshop  ◯  stale]│
│                    [🌾 Farm  ☀ 0W   🔋45%  offline ⚠]                │
└─────────────────────────────────────────────────────────────────────┘
```

Each chip shows:
- Device icon (existing keyword-derived set: 🏠 🏭 🌾 🏪 🏢 🏘️)
- Device name
- Status dot (green=online ≤5min / amber=stale 5-30min / red=offline >30min)
- Battery SOC if available
- Solar input power if available
- Last-update relative time on hover
- Alert badge with count if there are unread warnings

The "All Devices" chip sits at the start (RTL: rightmost) of the rail,
visually distinct (📊 icon, violet accent matching v32's aggregate-mode tone).

### 1.2 Where it appears
- `/dashboard` — directly under the existing top bar, above the `d40-hero`.
- `/live-data` — directly under the page header area, above the existing
  hero (`hu-hero`). Replaces the v32 single-device banner when 2+ devices
  exist; falls back to the existing single-banner when only 1 device.
- **Not** on `/devices/manage`, `/devices/manage/<id>/edit`, `/notifications/center`, `/loads`, `/reports`, `/statistics`, `/notifications`, `/channels`, `/account/*`, `/portal/support`, `/onboarding` — those keep the v32 `_device_switcher.html` partial.

### 1.3 RTL + responsive
- `dir="rtl"` puts "All devices" chip on the right (visually first) on Arabic.
- Below 720px viewport: rail collapses to a scrollable strip with snap-points (`scroll-snap-type: x mandatory`).
- Below 380px: chips shrink to icon + name only; SOC/solar pills move to a hover/long-press tooltip.

### 1.4 Saas style (matches v32)
- Container: white card, `border: 1px solid var(--line)`, `border-radius: 16px`, `box-shadow: 0 4px 16px rgba(15,23,42,.06)`, `padding: 10px 14px`.
- Active chip: amber gradient (`#ffcf4d → #f59e0b`), text `#0b1531`, weight 900.
- Inactive chip: `#f8fafc` background, weight 800, status dot.
- Hover: `translateY(-1px)` + larger shadow.

---

## 2. Instant switching (no full page reload)

### 2.1 Strategy
- **First-class:** AJAX partial fetch via a small `liveFleet.switch(deviceId|null)` JS controller.
- **Fallback:** classic `?selected_device_id=N` link (already wired in v33-α). If JS is disabled, clicking a chip is a normal link that hits the existing `before_request` redirect and reloads the page — same behaviour as v33-α.
- **Result:** zero regression. JS-on users get instant switching; JS-off users get the v33-α path.

### 2.2 What gets refreshed via AJAX (DASHBOARD)
1. Hero meta pills (phase chip, sunrise/sunset, plant name).
2. Flow Graph **values only** (via existing `data-bind` hooks — same protocol the live-poll already uses; the SVG paths/boxes are untouched).
3. Vitals strip (battery/solar/home/grid/today totals on the side rail of the flow graph — these have `data-bind` already).
4. Weather card values.
5. Production summary card values.
6. Smart engine recommendation card values.
7. NOT refreshed via AJAX in β: the chart canvases (Chart.js) — they re-init on full reload to avoid memory leaks; β keeps current behaviour for charts. Charts will be in v33-γ if needed.

### 2.3 What gets refreshed via AJAX (LIVE-DATA)
1. Hero copy + meta pills (device-aware tagline, ★ device chip, last update).
2. `.lv-context-strip` (status dot, device name, last-reading time).
3. Section 1 KPIs (solar, battery, home, grid).
4. Section 2 production totals (today, month, all-time).
5. Recent consumption table is full-reload only (low-priority, β keeps reload for it).

### 2.4 The protocol
A single endpoint, `POST /api/fleet/select`, accepts `{device_id: int | "__all__"}` and:
1. Updates `session['current_device_id']`.
2. Updates `AppUser.preferred_device_id`.
3. Returns `{ok: true, device_id: N, aggregate: bool, summary: {...}}` — a small payload for the rail to update its own active state.

Then the JS calls one of:
- `GET /api/devices/<id>/live-summary` for single-device pages.
- `GET /api/fleet/overview` for aggregate mode.

The JSON is rendered into the existing `data-bind` slots; no DOM
restructuring. This is exactly how the existing live-poll already works
(`data-live-url` on `<main>`).

### 2.5 No-reload UX guarantees
- URL reflects the new state via `history.replaceState` so deep-linking still works.
- ARIA live region announces "Switched to Workshop" for accessibility.
- Skeleton shimmer on cards during the ~200-500ms swap.
- Cancel any in-flight previous-device request when a new chip is clicked.

---

## 3. All Devices / Fleet overview (aggregate mode)

### 3.1 Combined values shown (DASHBOARD)
- Solar → **sum** (clearly labelled "Combined solar (3 devices)")
- Home load → **sum** (same labelling)
- Grid → **sum**
- Battery → **per-device row** under the flow graph; NEVER a misleading average
- Today total kWh → **sum**

### 3.2 What aggregate mode does NOT touch
- The Flow Graph itself: kept showing the COMBINED values via `data-bind`. The flow-line animation activates if any device has flow on that line. **NO structural changes to the SVG.**
- The right-rail stats: shown as "all devices combined" with a subtitle hint.
- Battery box: shows `Σ` symbol with the count of devices contributing, plus a small per-device dropdown panel below the flow graph with one row per device (name · SOC · current power flow).

### 3.3 Aggregate mode on `/live-data`
- Page hero meta pill: "📊 N devices combined" (already implemented in v32).
- `.lv-context-strip` shows: "📊 Aggregate: 3 devices · last update 14:32 (Workshop)" (last-update is the most-recent across the fleet).
- KPIs at top: combined values.
- A **new** "per-device breakdown" section below KPIs: one row per device with all 4 KPIs, clearly labelled. Each row's name is a chip that switches the rail to that device.

### 3.4 Notifications labelling in aggregate
- `/notifications/center` (untouched in β) — already shows `NotificationEvent` rows for the user. β only adds a subtle device chip on each row from the `device_id` column when present.
- Dashboard alerts strip (if any) gets a "[Workshop]" prefix per item.

---

## 4. Backend endpoints (proposed)

All endpoints are **user-scoped** (require `session['logged_in']`) and
**device-safe** (only return data for devices the logged-in user owns).
All endpoints are read-only `GET` except the explicit "select" mutation.

### 4.1 New endpoints

| Method | Path | Purpose | Returns |
|---|---|---|---|
| `POST` | `/api/fleet/select` | Set the user's active-view device or aggregate token | `{ok, device_id, aggregate, rail_payload}` |
| `GET` | `/api/fleet/summary` | Lightweight rail data: per-device tiny summary | `{devices: [{id, name, icon, status, soc, solar_w, last_update_iso, alerts_count}, ...]}` |
| `GET` | `/api/devices/<int:id>/live-summary` | Full live snapshot for ONE device (replaces the heavy `data-live-url` call when switching) | shape mirrors what `energy.api_live` already returns |
| `GET` | `/api/fleet/overview` | Combined values for the dashboard in aggregate mode + per-device breakdown rows | `{combined: {...}, per_device: [...]}` |
| `GET` | `/api/devices/<int:id>/notifications-preview` | Last 5 unread notifications for one device (badge + dropdown peek on the rail chip) | `{count, items: [{title, level, ts}, ...]}` |

### 4.2 Existing endpoints reused (NO change)
- `GET /api/live` (the existing live-poll) — already refreshes the dashboard via `data-bind`. β does NOT change it. The rail simply re-triggers it after switching.
- `?selected_device_id=N` redirect via `before_request` (v32) — kept as the no-JS fallback.

### 4.3 Endpoint security audit
For each new endpoint:
1. `_require_subscription_guard()` — preserves current paywall.
2. `is_admin_scope()` short-circuit — admin URLs never hit these.
3. Device ownership check: `AppDevice.query.filter_by(id=N, owner_user_id=user.id, is_active=True)` — if not found → `403`.
4. Aggregate endpoints filter by `owner_user_id` only.
5. Rate-limit: 60 req/min/user via existing `_light_rate_limit` mechanism.

### 4.4 Caching strategy
- `/api/fleet/summary` caches in-memory for 10s per user (Flask `g`-scoped LRU).
- `/api/devices/<id>/live-summary` does NOT cache — it must reflect latest reading.
- `/api/fleet/overview` caches 10s per user.
- All cache keys include `user_id` to avoid cross-user leak.

---

## 5. UI integration — exact files

### 5.1 New files

```
app/static/css/live_fleet_rail_v33b.css      ← rail container + chip styles
app/static/js/live_fleet_v33b.js             ← liveFleet.switch() controller
app/templates/_live_fleet_rail.html          ← partial: the rail itself
app/blueprints/fleet_api.py                  ← NEW blueprint for /api/fleet/* and /api/devices/<id>/live-summary
docs/design-qa/v33/v33-beta-execution-plan.md ← this file (already created)
docs/design-qa/v33/v33-beta-test-plan.md     ← detailed test scripts
docs/design-qa/v33/v33-beta-runbook.md       ← restart + rollback steps
tests/test_v33_beta.py                       ← endpoint + AJAX integration tests
```

### 5.2 Modified files

```
app/__init__.py                              ← register fleet_api_bp
app/templates/base.html                      ← <link> + <script> for the new rail asset bundle
app/templates/dashboard.html                 ← {% include '_live_fleet_rail.html' %} above the existing hero
                                               (NO changes to the d40-flow-card section — verified by checksum diff)
app/templates/live_data.html                 ← {% include '_live_fleet_rail.html' %} replacing the single-device banner spot when 2+ devices
                                               (NO changes to the existing hu-hero, lv-context-strip, lv-section blocks)
```

That's it. Total touched: 3 modified + 4 new (excluding docs and tests).

### 5.3 Reuse vs new

`_device_switcher.html` (v32 partial) is **kept as-is** for the 7 other
subscriber pages it serves (`/loads`, `/reports`, `/statistics`,
`/notifications`, etc.). The new `_live_fleet_rail.html` is a
purpose-built component for the dashboard + live-data — it is denser,
shows live values, and supports inline switching without reload.
Reusing the v32 partial would mean shoehorning live values into a
component designed as a navigation hint; cleaner to make a sibling.

### 5.4 JS architecture

`live_fleet_v33b.js` exposes a single `window.liveFleet` namespace:

```javascript
window.liveFleet = {
  switch(deviceId)            // POSTs /api/fleet/select, then refreshes the page
  refreshRail()               // GETs /api/fleet/summary, updates chip data
  applyLiveSummary(payload)   // updates all data-bind slots from a payload
  _xhr                        // last in-flight fetch, abortable
  _activeDeviceId             // current view's device id, mirrors session
};
```

The script attaches click handlers to every `[data-fleet-chip]`. On
click:
1. Optimistic UI: pulse the chip, show skeleton on data sections.
2. POST `/api/fleet/select`.
3. On success, GET `/api/devices/<id>/live-summary` (or `/api/fleet/overview` if aggregate).
4. Apply payload to `data-bind` slots.
5. Update URL via `history.replaceState`.
6. Announce via ARIA live region.

Rail polls every 30s for `summary` (status dots + alert badges only) so
chips reflect freshness even when the user isn't interacting.

### 5.5 CSS architecture

`live_fleet_rail_v33b.css` is a single thin file scoped under
`.live-fleet-rail` parent class. **Zero global styles. Zero overrides
of existing classes.** Custom properties from
`unified_theme_v1.css` (`--u-amber`, `--u-line`, etc.) are reused.

Loaded conditionally via `base.html` only on dashboard + live-data
pages (CSS is fetched but rules only match when the rail partial
renders, so the cost is one HTTP request that's gzipped to ~3 KB).

---

## 6. UX guidance

### 6.1 Helper text and tooltips

A small ℹ icon at the start of the rail, with hover tooltip:
> "All your active devices are running in the background. Switching
> here only changes what you see — it does NOT pause or activate
> anything."

Arabic:
> "كل أجهزتك النشطة تعمل في الخلفية. التبديل هنا يغير العرض فقط — لا
> يوقف أو يشغّل أي جهاز."

The tooltip uses the existing `help_tooltip_v1.js` system (already in
`base.html`) — no new helper machinery.

### 6.2 Make scope clear
- When viewing a single device: small "Viewing: 🏠 Roof" pill below the rail.
- When viewing aggregate: amber-violet pill "Viewing: 📊 All 3 devices combined".

### 6.3 Avoid clutter
- Rail height fixed at ~64px on desktop, 56px on mobile.
- Each chip max-width 240px on desktop; ellipsis on long names.
- Status dots and SOC are the only colour accents per chip; everything else is greyscale.

### 6.4 Loading states
- Initial page load: chips render server-side with last-known summary.
- After a switch: skeleton shimmer on the data sections (not on chips themselves).
- Errors (network drop): chip turns red with ⚠ subscript; click again to retry.

---

## 7. Testing plan

### 7.1 Pre-restart unit tests (against the new fleet_api.py)

```
tests/test_v33_beta.py:
  test_fleet_summary_returns_only_owned_devices
  test_fleet_summary_status_dots_match_last_update
  test_fleet_select_updates_session_and_preferred_device
  test_fleet_select_aggregate_token_persists
  test_devices_live_summary_403_for_other_users_devices
  test_fleet_overview_combines_correctly_for_solar_load_grid
  test_fleet_overview_battery_is_per_device_not_averaged
  test_endpoints_under_user_rate_limit
```

### 7.2 Manual browser tests (post-restart, with 3+ active devices)

**T1 Rail visibility & chip data**
- Visit `/dashboard?lang=ar` — confirm rail with 3 device chips + "All Devices" chip.
- Each chip shows status dot, SOC, solar pill, name.
- Hover a chip → see "last update" tooltip.

**T2 Instant switching (JS on)**
- Click "Workshop" chip → no full page reload.
- URL changes to `?... ` (preserved current path).
- Hero, KPIs, weather, production summary all update.
- **Flow Graph values update via existing `data-bind`** (animation stays untouched).
- Rail's active chip flips to Workshop.

**T3 Aggregate mode**
- Click "📊 All Devices" chip.
- Combined solar/load/grid values shown in flow graph.
- Battery shows `Σ 3` symbol with per-device dropdown.
- Per-device breakdown section appears below the flow card.

**T4 No-JS fallback**
- Disable JS in browser.
- Click a chip → full reload via `?selected_device_id=N`.
- Page renders with new device, rail's active chip reflects it.
- All v33-α functionality intact.

**T5 Live-data page**
- Visit `/live-data?lang=ar` — same rail visible.
- Switch via chip → KPIs and context strip update without reload.

**T6 Cross-device isolation**
- User A sees only their own devices in the rail.
- User A's `/api/fleet/summary` returns 0 of User B's devices.
- Direct URL `/api/devices/<B_id>/live-summary` from User A's session → 403.

**T7 Background-sync still happens for ALL devices**
- Switch view to Roof for 2 minutes.
- Confirm `Reading` rows still being written for Workshop and Farm.
- Confirm `NotificationLog` rows still firing per-device for Workshop and Farm.
- (Same v33-α scheduler fan-out — unchanged. β just verifies it.)

**T8 Locked Flow Graph integrity**
- Visual diff of dashboard before & after β: the flow graph SVG, paths,
  dots, boxes, animation timing, and CSS must be PIXEL-IDENTICAL when
  the same device is selected.
- Inspect `<svg class="flow-svg official-flow-svg">` HTML in DOM and
  confirm zero attribute / structure diff.

**T9 Regression: 13-page subscriber smoke test**
- All 13 subscriber pages from v32/v33-α list still return HTTP 200 in
  both single-device AND aggregate mode.

### 7.3 RTL + responsive

- Arabic mode: rail chips wrap correctly, "All Devices" is at the visual right.
- 1440px desktop: rail visible in one row.
- 820px tablet: rail with 4-5 chips visible, scrollable.
- 380px mobile: rail with 2 chips visible, swipe-scroll-snap works.

### 7.4 Test fixture
Reuse `tests/fixtures/multidevice_alpha.py` (3-device shape from v33-α) +
extend with simulated readings (varying ages: fresh, stale, offline).

---

## 8. Risks and rollback plan

### 8.1 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| AJAX swap accidentally re-renders Flow Graph SVG and breaks the animation | Medium | The applyLiveSummary() function ONLY updates `data-bind` text values; it never touches DOM structure. Locked-component test (T8) catches regressions. |
| `/api/fleet/select` race condition when user clicks multiple chips fast | Medium | `_xhr.abort()` cancels in-flight previous request before sending new one. |
| Provider rate limit pressure from polling | Low | β polls only `/api/fleet/summary` (read-only DB) every 30s. No external provider calls per poll. |
| New `fleet_api_bp` blueprint name collides with existing endpoint | Low | Pre-flight: grep all `Blueprint('...')` names; `fleet` is currently free. |
| Mobile rail crowds the screen | Medium | Designed-for-mobile from start: scrollable strip, 2-chip viewport, not stacked. |
| User has 50+ devices, rail unusable | Low (v33-β scope assumes ≤ 10) | Document the limit; v33-γ would add a search/filter inside the rail. |
| Aggregate-mode battery confusion (sum vs per-device) | High | Explicit per-device breakdown; never show a single SOC number for "all devices". UI copy: "Battery is shown per-device (averaging is misleading)." |
| Cross-user data leak via the new endpoints | High → Low | Every endpoint enforces `owner_user_id == session.user_id` filter. Tests T6 verify. |
| Flow Graph DOM accidentally edited | High | This plan documents the lock. Pre-merge reviewer checks the dashboard.html diff for ANY change inside `<section class="d40-card d40-flow-card span-full">` — if any, REJECT. |

### 8.2 Rollback plan

If anything regresses:
1. **Quick rollback (template-level)**: comment out the
   `{% include '_live_fleet_rail.html' %}` lines in `dashboard.html` and
   `live_data.html`. Templates auto-reload. The pages immediately revert
   to v33-α appearance.
2. **Full rollback**: `git revert v33-beta-live-fleet-dashboard` —
   removes the rail + endpoints in one commit.
3. **JS-only rollback**: rename `live_fleet_v33b.js` to disable it.
   Pages keep the rail but switching falls back to no-JS reload behaviour
   (which is v33-α behaviour).
4. The JS controller has a top-level `try/catch` that logs to console
   and falls back to navigation on any unexpected error.

---

## 9. Out of scope (explicit)

- `UserChannel` model + per-device channel matrix → v33-γ.
- `NotificationRule` model + per-device rules UI → v33-γ.
- Onboarding multi-device branch → v33-ε.
- Redesigning any subscriber page besides dashboard + live-data → v33-δ or later.
- Billing / subscription logic → no change.
- Charts (Chart.js) — left as full-reload during β.
- Auto-commit / auto-tag — explicit user instruction was no auto.

---

## 10. Approval gate

This plan is **for review only**. No code, no template edits, no new
files (other than this doc). Implementation order once approved:

1. Write `tests/test_v33_beta.py` first (TDD: failing tests).
2. Build `app/blueprints/fleet_api.py` until tests pass.
3. Register `fleet_api_bp` in `app/__init__.py`.
4. Build `app/templates/_live_fleet_rail.html` with the chips and skeleton.
5. Build `app/static/css/live_fleet_rail_v33b.css`.
6. Build `app/static/js/live_fleet_v33b.js` (the controller).
7. Wire `_live_fleet_rail.html` into `dashboard.html` (above the hero,
   NOT inside the flow-card).
8. Wire it into `live_data.html` (above the hu-hero, replacing the
   single-device banner only when 2+ devices).
9. Add the rail's CSS+JS to `base.html` (loaded only on dashboard +
   live-data via a small `{% if request.endpoint in [...] %}` guard).
10. `python -m compileall -f app/`.
11. Run `tests/test_v33_beta.py`.
12. Restart Flask.
13. Manual T1–T9 with a 3-device subscriber.
14. Visual diff of the Flow Graph before vs after to prove the lock.
15. 13-page subscriber smoke test (regression).
16. Write `v33-beta-test-plan.md` and `v33-beta-runbook.md` with actual
    results.
17. Stop and report back. Do not commit. Do not tag.

---

## 11. Open decisions (need your call before coding)

1. **Rail polling cadence.** I recommended 30s for `/api/fleet/summary`. Lower (10s) is more live but more DB queries; higher (60s) is gentler. Confirm 30s or override.
2. **Battery in aggregate mode.** I recommended per-device breakdown only (no average). Confirm or pick a different display.
3. **Mobile rail layout.** Horizontal scroll-snap (recommended) vs vertical stacked. Confirm scroll-snap.
4. **No-JS fallback.** Must always remain functional? (Recommended yes.) Confirm.
5. **Polling pause when tab is hidden.** Should we use `document.visibilityState === 'hidden'` to skip polling? (Recommended yes; saves DB load.) Confirm.
6. **Chart refresh in β.** Keep on full reload for β (recommended), or move to AJAX in β? Confirm β stays full-reload for charts.

---

End of v33-β execution plan. NO code has been written.
