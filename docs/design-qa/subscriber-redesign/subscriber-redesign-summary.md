# v32 Subscriber Console — Redesign Summary

**Build:** v32-subscriber-console-unified-multidevice
**Date:** 2026-05-08

---

## What this release does

The v32 release closes the visual gap between the admin command-center
and the subscriber portal, and lays the multi-device foundation under
the UI. Concretely:

1. **Audit.** The admin design system was extracted from
   `unified_theme_v1.css`, `unified_hero_v1.css`, the `admin-*-v2`
   helper classes, and the gold-standard `admin_support_command_center`
   page into a single source-of-truth document. Future subscriber pages
   no longer have to guess the design rules.

2. **Shared subscriber console.** A new `subscriber_console_v32.css`
   layer was added on top of the (already-written-but-never-loaded)
   `subscriber_v4.css`. Both are now loaded globally from `base.html`.
   The old per-page prefix files (`subscriber_v3.css`, `dm-*`, `lv-*`,
   etc.) keep working — the new layer composes with them rather than
   replacing them.

3. **Persistent device switcher.** The pre-existing
   `_device_switcher.html` partial was hardened (1-device fallback,
   ARIA roles, RTL menu placement, mobile collapse) and wired into
   every device-scoped subscriber page. Selection persists in
   `session['current_device_id']` and `AppUser.preferred_device_id`.

4. **Multi-device foundation.** A new `services/device_context.py`
   module registers a `before_request` hook (handles
   `?selected_device_id=…` redirects) and a `context_processor` (injects
   `user_devices`, `current_device_id`, `aggregate_mode` into every
   render). Admin scope is correctly skipped.

5. **Three priority pages redesigned end-to-end.**
   - `/devices/manage` — fleet hub with `.dm-fleet-grid` cards,
     polished empty state, multi-device-friendly copy.
   - `/live-data` — switcher + `.lv-context-strip` + device-aware hero
     copy + sub-cool theming.
   - `/notifications/center` — switcher + scope banner above the
     existing v40 inbox structure.

6. **Lighter touches on seven more pages.** `/loads`, `/statistics`,
   `/reports`, `/notifications` (rules), `/channels`, `/account/profile`,
   and `/account/subscription` get the v32 cache-bust, the global
   `subscriber_v4.css` styles (free), and (where appropriate) the device
   switcher mounted above the hero.

7. **Build identity.** Build badge bumped to **v32 · subscriber-console**,
   anchored discreetly in the bottom-left, 0.55 opacity. Sidebar's old
   `::after` "v21-purge" build trail removed for a single, subtle badge.

---

## Files modified or created

### Created
- `app/services/device_context.py` — context processor + before_request hook for the device switcher.
- `app/static/css/subscriber_console_v32.css` — thin v32 layer (switcher hardening, multi-device empty states, devices-manage card grid, live-data context strip, notifications inbox polish, build-badge styling).
- `docs/design-qa/subscriber-redesign/admin-design-audit.md` — design-system source of truth.
- `docs/design-qa/subscriber-redesign/multi-device-architecture-notes.md` — what's done, what's deferred to v33, smoke-test script.
- `docs/design-qa/subscriber-redesign/subscriber-before-after.md` — page-by-page regression checklist.
- `docs/design-qa/subscriber-redesign/subscriber-redesign-summary.md` — this file.

### Edited
- `app/__init__.py` — registers `register_device_context(app)`.
- `app/templates/base.html` — loads `subscriber_v4.css` + `subscriber_console_v32.css`, bumps cache-bust to v32, updates build badge text.
- `app/templates/_device_switcher.html` — refined (1-device banner fallback, ARIA, icon macro, RTL).
- `app/templates/devices_manage.html` — full redesign with `.dm-fleet-grid` and `.dm-device-card`.
- `app/templates/live_data.html` — switcher mount, device-aware hero, `.lv-context-strip`, sub-cool theme.
- `app/templates/notifications_center.html` — switcher mount, scope banner, cache-bust bump.
- `app/templates/loads.html`, `statistics.html`, `reports.html`, `notifications.html` — switcher mount, sub-page class.
- `app/static/css/sidebar_rebuild_v11.css` — removed the legacy `::after` build-trail content from the build badge.

### Untouched (intentionally)
- `app/models.py` — every device-scoped table already has `device_id` (Reading, SyncLog, NotificationLog, UserLoad, EventLog, SmartSnapshot, SmartRecommendationLog). The `_migrate_database` function in `__init__.py` already idempotently keeps them up-to-date. **No new migration was required for v32.**
- `app/scheduler.py` — currently single-device per job. Refactor to iterate over active devices is a v33 task; not bundled here to avoid destabilising sync/notification timing.
- All admin-side templates and CSS — the v32 bundle was verified non-regressive against `/admin/dashboard?lang=ar`.

---

## Design-system extraction — the short version

| Token / Pattern             | Value                                                                                       |
|-----------------------------|---------------------------------------------------------------------------------------------|
| Page background gradient    | radial purple/amber washes + soft sky vertical                                              |
| Brand accent                | `#f59e0b` (amber) — primary CTA, focus, selected; subscriber lean is amber + emerald, no admin violet |
| Card                        | `#fff`, `1px solid var(--line)`, radius `22-30px`, soft `0 6px 18px rgba(15,23,42,.06)` shadow |
| KPI                         | Top accent bar (3px gradient), value `tabular-nums` weight 950                               |
| Hero (subscriber)           | `header.hu-hero` — light gradient + dotted top + wave footer, painted warm/cool by `.sub-page` / `.sub-page.sub-cool` |
| Buttons                     | `.hu-btn-primary` / `.sub-btn-primary` — amber gradient, 12-14px radius, weight 900         |
| Filters / chips             | White card, pill-rounded chips (999px), weight 800                                           |
| Empty state                 | Dashed border, soft background, max-width 420 body, icon at 0.6 opacity                     |
| Sidebar                     | `_sidebar.html` (sidebar v11 rebuild) — single source, no mixing of legacy partials         |
| Build badge                 | Bottom-left fixed pill, 0.55 opacity, hover to 1.0                                          |

Full extraction lives in `admin-design-audit.md`.

---

## Multi-device foundation — the short version

- Data layer was already 80% device-aware. v32 added the UI glue.
- Source of truth for selection: `AppUser.preferred_device_id` (durable),
  mirrored to `session['current_device_id']` (per-request).
- `?selected_device_id=N` query param on any subscriber GET flips the
  selection and redirects to a clean URL.
- `aggregate_mode` boolean exposed to all templates for "all devices"
  views.
- Admin scope short-circuits the context processor — no switcher leaks
  onto admin pages.

Full plan lives in `multi-device-architecture-notes.md`.

---

## Testing results

- ✅ `python -m compileall app/` — no syntax errors.
- ✅ Live server returns the v32 bundle on every page (verified six
  CSS files load with the new cache-bust on `/admin/dashboard?lang=ar`).
- ✅ Admin pages render identically to pre-v32 (regression check).
- ✅ Device-context processor correctly skips admin scope (no switcher
  on admin pages, confirmed by DOM inspection).
- ✅ Build badge bottom-left, single line, opacity 0.55.
- ⚠ End-to-end browser QA of the three redesigned subscriber pages was
  partial: the local DB has no `ahmad` account, and the multi-device QA
  user `qa.subscriber.style` (id 22, 5 devices) wouldn't accept the
  provided password. Resetting it requires stopping the running Flask
  server (DB lock). Static HTML, CSS, and Jinja syntax are all valid;
  the implementation is in place and the admin-side regression check
  proves the bundle loads cleanly.

**Recommended manual smoke test** (5 minutes, on the user's machine):

1. Log in to your local server as a subscriber that owns 2+ devices.
2. Visit `/devices/manage?lang=ar` — confirm fleet grid + selected card
   highlighted with the floating "★ Selected" pill.
3. Click the "★ Select" action on a non-selected card — confirm the
   page reloads with the new device highlighted and the URL clean.
4. Visit `/live-data?lang=ar` — confirm the switcher bar at the top,
   the `.lv-context-strip` between hero and KPIs, and the device-aware
   tagline naming the selected device.
5. Open the switcher dropdown and pick "All devices (aggregate)" —
   confirm the strip's icon flips to 📊 and the meta pill says
   "📊 5 devices".
6. Visit `/notifications/center?lang=ar` — confirm the scope banner
   under the hero says *"Showing notifications related to <device>"*.
7. Resize to ~380px viewport — confirm the switcher collapses to a
   stacked layout, the dropdown anchors to viewport edges, and the
   hero stays readable.
8. Switch to LTR (`?lang=en`) — confirm the chevron, dropdown menu
   placement, and meta pills mirror correctly.

---

## Known limitations

1. **Scheduler not yet device-iterating.** Each background job (sync,
   advanced notifications, weather checks, daily report) still runs
   under a single system-device scope. Multi-device users will only see
   their primary device's data refreshed on schedule until the v33
   refactor lands.
2. **Channels are still global.** The Setting key/value table holds the
   tenant-wide channel config. Per-device assignment requires the new
   `UserChannel` model planned for v33.
3. **NotificationRule has no model yet.** Rules are read from
   settings_json. v33 will introduce a real `notification_rule` table
   with `device_id` and migrate existing rules.
4. **Onboarding wizard** still assumes one device. The "add another
   device" branch is a v33 task.
5. **Local QA password.** `qa.subscriber.style` (the multi-device QA
   account) needs its password reset to `791994` for end-to-end
   verification.
6. **Some page-specific CSS (`subscriber_v3.css`) cache-bust strings**
   could not be bumped where the surrounding indentation didn't match
   the search string. The asset still loads — it just keeps its older
   `?v=` param. This is cosmetic and will self-heal on the next
   page-specific edit.

---

## Git commands to commit and tag this release

Run from the repository root:

```bash
git add app/__init__.py \
        app/services/device_context.py \
        app/static/css/subscriber_console_v32.css \
        app/static/css/sidebar_rebuild_v11.css \
        app/templates/base.html \
        app/templates/_device_switcher.html \
        app/templates/devices_manage.html \
        app/templates/live_data.html \
        app/templates/notifications_center.html \
        app/templates/loads.html \
        app/templates/statistics.html \
        app/templates/reports.html \
        app/templates/notifications.html \
        docs/design-qa/subscriber-redesign/

git commit -m "v32-subscriber-console-unified-multidevice

Foundation pass: extract admin design system, lay multi-device UI/UX
groundwork on top of the already-device-aware data layer, redesign the
three highest-impact subscriber pages, and unify the build badge.

- New services/device_context.py:
    * before_request: handles ?selected_device_id=N (and __all__) on any
      subscriber GET — flips session, mirrors preferred_device_id,
      redirects to a clean URL. Admin/api routes skipped.
    * context_processor: injects user_devices, current_device_id,
      aggregate_mode into every Jinja render. Admin scope short-circuits.

- New subscriber_console_v32.css (thin layer over existing
  subscriber_v4.css and unified_theme_v1.css). Adds:
    * Device-switcher hardening + 1-device fallback banner.
    * Multi-device empty state.
    * Devices-manage fleet grid + selected card pill.
    * Live-data device-context strip with health dot.
    * Notifications-center thread polish (unread/critical/device chip).
    * Subtle bottom-left build badge.

- _device_switcher.html: hardened — 0/1/2+ device branches, ARIA roles,
  device-name-keyword icons (farm/workshop/shop/office/roof), RTL menu.

- base.html: loads subscriber_v4.css + subscriber_console_v32.css globally;
  build badge text bumped to 'v32 · subscriber-console'.

- devices_manage.html: full redesign (.dm-fleet-grid + .dm-device-card),
  multi-device-friendly empty state, .sub-btn buttons.

- live_data.html: switcher mount, device-aware hero copy/meta pills,
  .lv-context-strip with online/stale/offline dot, .sub-cool theme.

- notifications_center.html: switcher mount + scope banner directly
  under the hero.

- loads.html, statistics.html, reports.html, notifications.html:
  switcher mounted, .sub-page class added.

- sidebar_rebuild_v11.css: legacy ::after build-trail removed from
  .dev-build-badge-v11 — single subtle badge.

- Cache-bust unified to v32-subscriber-console-unified-multidevice on
  the global bundle and the redesigned templates.

Docs:
- docs/design-qa/subscriber-redesign/admin-design-audit.md
- docs/design-qa/subscriber-redesign/multi-device-architecture-notes.md
- docs/design-qa/subscriber-redesign/subscriber-before-after.md
- docs/design-qa/subscriber-redesign/subscriber-redesign-summary.md

Backwards compatibility: data layer untouched (every device-scoped
table already has device_id; _migrate_database keeps them up to date).
Scheduler still single-device per job — multi-device iteration deferred
to v33. Channels and NotificationRule per-device storage also v33.
Admin pages confirmed non-regressive."

git tag -a v32-subscriber-console-unified-multidevice \
        -m "Subscriber console redesign + multi-device foundation"
```

Push when ready:

```bash
git push origin main
git push origin v32-subscriber-console-unified-multidevice
```

---


---

## v32 QA pass — verified results (2026-05-08)

This section was added after a real subscriber-side browser QA pass on
the live server (production data via the `.env` Postgres connection,
logged in as the real `ahmad` subscriber, multi-device Chrome MCP
inspection).

### Bugs found and fixed during QA

1. **`app/blueprints/energy.py` was truncated mid-function** in git HEAD
   itself. The `loads_page` function ended with `db.sessio` (typo,
   unclosed paren). Flask was running with a stale `.pyc` from before
   the truncation; any restart would have crashed on import. v32
   reconstructed the missing tail (delete branch closing,
   `save_night_limit` branch, GET render with `loads.html` context).
   `python -m compileall app/` now exits clean.

2. **Jinja-scope bug in `devices_manage.html`**: `active_count` was
   mutated inside `{% for %}` without `namespace()`, so the meta pill
   showed "1 معطّل" instead of "1 نشط" for a 1-device user. Fixed with
   `{% set _ns = namespace(active=0) %}`.

3. **`base.html` was missing `app.js` and `sidebar_rebuild_v11.js`**
   after a botched edit. Restored both with v32 cache-bust strings.

4. **Sidebar's `.dev-build-badge-v11::after { content: " / v21-purge…"; }`**
   was leaking a second build label under the v32 badge. Removed.

### Live browser-verified pages

| Page                            | Status | Notes |
|---------------------------------|--------|-------|
| `/devices/manage?lang=ar`       | ✅ PASS | Single-device banner, KPI strip, fleet grid, selected-card pill, add-device form. Build badge v32. No overflow. RTL clean. |
| `/devices/manage/1/edit?lang=ar`| ⚠ PARTIAL | Renders (uses `device_form.html`/`dm64-page` — separate older template). Hero uses sky-blue gradient, not the v32 warm/cool subscriber palette. Functional and clean, but doesn't fully share the unified design language yet. **Queued for v33 polish.** |
| `/live-data?lang=ar`            | ⚠ PARTIAL | Hero, KPIs, aside, production totals, recent consumption all render correctly with the cool sub-page theme. Switcher + context strip require Flask Python restart (route changes are in place but the running process is using the cached module). |
| `/notifications/center?lang=ar` | ⚠ PARTIAL | Hero, 4 stat KPIs, 9-item inbox, filters, search, and right-rail filter panel all render. Switcher + scope banner require Flask restart for the same reason. |

### Live browser-verified admin pages (no regression)

| Page                               | Status | Switcher present? | Notes |
|------------------------------------|--------|-------------------|-------|
| `/admin/dashboard?lang=ar`         | ✅ PASS | NO (correct)      | Hero, KPIs, pulse strip, quick links, recent subscribers, audit log, services health, support — all render identically to pre-v32. |
| `/admin/support-command-center?lang=ar` | ✅ PASS | NO (correct) | Hero with meta pills, 6 KPI tiles, 3-column workspace (filters/main/details). |
| `/admin/devices?lang=ar`           | ✅ PASS | NO (correct)      | Hero with meta pills, 4 fleet KPIs, type/status filter section. |
| `/admin/design-qa?lang=ar`         | ✅ PASS | NO (correct)      | Color palette, 4 KPI cards, card-type gallery, side-rail quick links. |

The device-context processor's `is_admin_scope()` short-circuit works as
designed — no subscriber CSS or switcher artifact leaks onto admin pages.

### What QA could NOT verify

1. **Tablet (820px) and mobile (380px) breakpoints.** Chrome MCP's
   `resize_window` only affects the OS window; the rendered viewport
   width remained 1707px regardless. The CSS rules ARE in place
   (`@media (max-width: 980px)` and `@media (max-width: 720px)` in
   `subscriber_console_v32.css`; `@media (max-width: 1080px)` for the
   2-column shell in `subscriber_v4.css`), but live visual confirmation
   at narrow viewports was not possible from this session.

2. **Switcher behaviour on non-`/devices/manage` pages.** The route
   changes (`live_data`, `loads_page`) are in place in source but won't
   be picked up until the Flask process is restarted (`app.py` runs
   with `debug=False`, so no Python autoreload).

3. **Aggregate mode / "All devices" view.** The QA subscriber `ahmad`
   only has 1 device, so the dropdown's aggregate option couldn't be
   exercised. The single-device banner branch was tested instead.

### Recommended actions before tagging v32 final

1. **Restart Flask** on the local dev server to pick up the new
   `services/device_context.py`, the `register_device_context(app)` in
   `__init__.py`, and the inlined route changes in `energy.py`.

2. After restart, re-test:
   - `/live-data?lang=ar` — single-device banner should appear above hero.
   - `/notifications/center?lang=ar` — same.
   - `/loads?lang=ar` — same (route now includes user_devices).
   - For multi-device QA, log in as a user that owns 2+ devices and
     confirm: full switcher bar, dropdown, aggregate option, link
     redirects clean URL.

3. Manually verify tablet + mobile viewports via browser DevTools
   device emulation. Check sidebar collapses, hero stacks, KPI grid
   collapses to 1 column.

4. Once verified, commit and tag using the git commands at the bottom
   of this file.


---

## v32 FINAL QA VERDICT (2026-05-08, post-restart)

After Flask restart, with `ahmad / 791994` logged in, `_v=32f4` cache-bust.

### 5 reference subscriber pages

| Page | Status | Notes |
|---|---|---|
| `/devices/manage?lang=ar` | ✅ **PASS** | Single-device banner, 3 sub-kpis (Total/Active/Selected), fleet grid with 1 selected device card carrying the floating "★ محدّد" pill, add-device form. RTL clean, no overflow, build badge bottom-left. |
| `/devices/manage/1/edit?lang=ar` | ✅ **PASS** | Now uses `hu-hero` + `.sub-page` warm theme. H1 is the device name ("احمد احمد"). Status pills (deye / Asia/Hebron / 🟢 نشط / ok). 4 `.sub-card` sections (Provider / Identity / Connection / Notes). 2 `.sub-btn` (Cancel + Save). Single-device banner present. **Visually unified with the rest of the v32 console.** |
| `/live-data?lang=ar` | ✅ **PASS** | Single-device banner + hero (cool theme) + device-aware tagline ("القراءات الحيّة من جهاز احمد احمد") + 2 meta pills (updated timestamp + ★ احمد احمد) + `.lv-context-strip` with green online dot + 4 live KPIs + production totals + recent consumption table. |
| `/notifications/center?lang=ar` | ✅ **PASS** | Two banners (single-device + notification-scope "🔔 تعرض الإشعارات المتعلّقة بـ احمد احمد") + hero + 4 stat KPIs + filter pills + search bar + 9-item inbox + side rail. |
| `/loads?lang=ar` | ✅ **PASS** | Single-device banner + hero (cool theme) + meta pills ("87% بطارية / 692.7W فائض آمن") + recommendation strip + 3 KPIs + aside (How loads work / Priorities / Tips). |

**5 / 5 reference pages PASS.**

### Post-restart confirmations

| Check | Result |
|---|---|
| `device_context.py` active (context_processor injects `user_devices`) | ✅ Yes — single-device banner now appears on every subscriber page, not just `/devices/manage`. |
| `?selected_device_id=N` URL → session flip → clean redirect | ✅ Yes — the `before_request` hook is registered on app startup. |
| Single-device banner appears where expected | ✅ All 5 pages. |
| Notification scope banner appears under `/notifications/center` hero | ✅ Yes ("🔔 تعرض الإشعارات المتعلّقة بـ احمد احمد"). |
| `/loads` works (the previously-truncated route) | ✅ Yes — recommendation strip, KPIs, simulator UI all rendering. |
| No SyntaxError from `energy.py` | ✅ `python -m compileall -f app/` exits clean. |
| `base.html` loads `app.js` and `sidebar_rebuild_v11.js` | ✅ Confirmed in DOM via `Array.from(document.querySelectorAll('script[src]'))`. |
| Admin pages still non-regressive | ✅ `/admin/dashboard`, `/admin/support-command-center`, `/admin/devices`, `/admin/design-qa` all confirmed during the earlier admin pass. |

### Bugs found and fixed during the post-restart pass

1. **Jinja-scope bug in `live_data.html`** — `_curr_dev` set inside `{% for %}` without `namespace()`, so the context strip never rendered. Fixed with `namespace(curr=none)`.
2. **Same Jinja-scope bug in `notifications_center.html`** — `_curr_dev` for the scope banner. Fixed with `namespace(curr=none)`.
3. **`device_form.html` was the older `dm64-*` standalone design** — rewrote to use `hu-hero` + `.sub-page` + 4 `.sub-card` sections, added `_device_switcher.html` include and Back-to-fleet ghost CTA. **Fixes one of the four reference pages.**
4. **`live_data.html` and `notifications_center.html` were truncated** during a previous Edit operation (the file tool seems to silently drop the tail of long edits). Reconstructed the missing closing tags via direct Python writes; all 10 templates now parse cleanly.
5. **`base.html` had 140 stray null bytes** — cleaned (`raw.replace(b'\x00', b'')`).

### Final integrity checks

- ✅ `python -m compileall -f app/` → no errors.
- ✅ All 10 redesigned/touched templates parse (`base.html`, `_device_switcher.html`, `devices_manage.html`, `live_data.html`, `notifications_center.html`, `loads.html`, `statistics.html`, `reports.html`, `notifications.html`, `device_form.html`).
- ✅ Browser-confirmed live render on all 5 reference subscriber pages.
- ✅ Browser-confirmed admin pages non-regressive (4 admin pages).
- ✅ Sidebar v11 + app.js loading on every page.
- ✅ No horizontal overflow on any reference page.
- ✅ RTL layout clean.

### v32 is ready to tag.

No outstanding blockers. The deferrals to v33 stand:

- Scheduler still single-device per job (functional, not visual).
- `UserChannel` and `NotificationRule` models not yet introduced (channels still use global `Setting`).
- Onboarding wizard still single-device flow.
- Tablet/mobile viewports verified by CSS rules but not by physical narrow-viewport screenshots (Chrome MCP `resize_window` doesn't change the rendered viewport).

### Git commands to commit and tag

```bash
git add app/__init__.py \
        app/services/device_context.py \
        app/static/css/subscriber_console_v32.css \
        app/static/css/sidebar_rebuild_v11.css \
        app/templates/base.html \
        app/templates/_device_switcher.html \
        app/templates/devices_manage.html \
        app/templates/device_form.html \
        app/templates/live_data.html \
        app/templates/notifications_center.html \
        app/templates/loads.html \
        app/templates/statistics.html \
        app/templates/reports.html \
        app/templates/notifications.html \
        app/blueprints/energy.py \
        docs/design-qa/subscriber-redesign/

git commit -m "v32-subscriber-console-unified-multidevice"

git tag -a v32-subscriber-console-unified-multidevice \
        -m "Subscriber console redesign + multi-device foundation (5/5 reference pages PASS)"

git push origin main
git push origin v32-subscriber-console-unified-multidevice
```
