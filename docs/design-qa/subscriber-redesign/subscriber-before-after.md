# Subscriber Redesign — Before / After (v32)

**Build:** v32-subscriber-console-unified-multidevice
**Date:** 2026-05-08

This document captures the visual & UX deltas across the v32 subscriber
redesign. Use it as the regression checklist for any future change to
these pages.

---

## /devices/manage — device fleet hub

| Aspect              | Before                                                                                              | After                                                                                                                                                  |
|---------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| KPI strip           | Three custom cards with hard-coded inline `style="…"` blocks repeated 3× (≈40 inline rules each).   | Three (or four) `.sub-kpi` cards with token-driven colour variants (`is-cool`, `is-warm`). Single source of truth — same component used elsewhere.    |
| Devices list        | Single dense table, hard-coded inline avatar, micro-pills with manual borders.                      | Polished `.dm-fleet-grid` of `.dm-device-card` tiles. Selected card highlighted with floating "★ Selected" pill. Each tile shows type, timezone, last sync, connection — read at a glance. |
| Empty state         | A small `.dm-empty` block with one emoji + line of text.                                            | Full-card `.sub-empty-multidevice` with a primary CTA, friendlier copy, and a top-edge accent bar.                                                    |
| Multi-device cue    | "Selected" KPI showed only the device name. No path to switch from this page besides the list.       | New persistent device-switcher (or single-device banner) sits above the hero, plus the in-card "★ Select" action. Switching works from anywhere.       |
| Buttons             | Inline `.dm-btn ghost sm` micro-icons.                                                              | `.sub-btn-primary` / `.sub-btn-ghost` full-width action row at the bottom of each card. Touch-friendly, label always visible.                          |
| Form section        | `<button class="dm-btn primary">＋ Add device</button>` — old prefix.                                | Same form, but submit/reset buttons now use `.sub-btn-*` so they match the rest of the redesign.                                                       |

---

## /live-data — real-time energy snapshot

| Aspect              | Before                                                                                              | After                                                                                                                                                  |
|---------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| Hero copy           | Generic "see your solar production…" line, no device context.                                       | Device-aware tagline: *"Live readings from **Workshop**, refreshed every 30 seconds"*. Falls back to the generic copy when no device is selected.      |
| Hero meta           | One pill: "🔄 updated …".                                                                            | Three: updated timestamp, **★ device name** chip, and (in aggregate mode) **📊 N devices** chip.                                                       |
| Device switcher     | Not present.                                                                                        | Persistent `.dswx-bar` above the hero (or `.dswx-single-banner` for 1-device users).                                                                   |
| Status visibility   | The user had to infer "is this stale?" from the formatted timestamp.                                | New `.lv-context-strip` between the hero and the KPIs with a coloured dot (green=online, amber=stale, red=offline) plus device name, provider, timezone, and last-reading time. |
| Sub-cool theme      | The hero used the warm subscriber tones even though this page is a monitoring view.                  | Page now sets `class="… sub-page sub-cool"` so the hero gradient is sky-blue → desat-violet — visually clear that this is monitoring, not configuration. |

---

## /notifications/center — inbox

| Aspect              | Before                                                                                              | After                                                                                                                                                  |
|---------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| Device switcher     | Not present.                                                                                        | Persistent switcher above the hero. Inbox scope is now visible at all times.                                                                           |
| Scope banner        | None.                                                                                               | Soft `.dswx-single-banner` directly under the hero: *"Showing notifications related to **Workshop**. Switch device above to see another inbox."*       |
| Thread row polish   | Existing `.ncv40-row` cards.                                                                        | New `.ncv40-thread.is-unread` / `.is-critical` overlay rules from `subscriber_console_v32.css` add a left priority bar, device chip, and unread dot.    |
| CSS cache-bust      | `v40-notifications-center-redesign-20260430`.                                                       | Bumped to `v32-subscriber-console-unified-multidevice` so existing cached copies are invalidated alongside the new global bundle.                      |

---

## Cross-cutting changes (every subscriber page)

| Aspect                  | Before                                                                                              | After                                                                                                                                                  |
|-------------------------|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| Subscriber CSS layer    | `subscriber_v4.css` was written but never loaded in `base.html`. Each page included `subscriber_v3.css` only. | Both `subscriber_v4.css` and `subscriber_console_v32.css` are now loaded by `base.html`. Pages get the shared `.sub-*` building blocks for free.       |
| Build badge             | `v212-sidebar-qa-jsfix-20260506`, prominent.                                                        | `v32 · subscriber-console`, anchored bottom-left, 0.55 opacity, hover-to-fully-reveal. Sidebar's old `::after` build-trail removed.                    |
| Cache-bust              | Mixed (`v215-…`, `v168-…`, `v211-…`, `v40-…`).                                                       | Unified to `v32-subscriber-console-unified-multidevice` for the global bundle and the redesigned templates. Page-specific `subscriber_v3.css` strings updated where feasible. |
| Multi-device awareness  | Pages assumed one device. Notification copy never named a device. No way to switch from inside a page. | Context processor injects `user_devices`, `current_device_id`, `aggregate_mode` into every render. Switching works via `?selected_device_id=N` on any subscriber URL. |

---

## Pages wired (multi-device switcher mounted)

| Route                       | Switcher | Notes |
|-----------------------------|----------|-------|
| `/devices/manage`           | ✓        | Switcher + redesigned hub. |
| `/live-data`                | ✓        | Switcher + device-context strip + device-aware copy. |
| `/notifications/center`     | ✓        | Switcher + scope banner. |
| `/loads`                    | ✓        | Switcher mounted; full redesign queued for v33. |
| `/statistics`               | ✓        | Switcher mounted; aggregate chart variant queued for v33. |
| `/reports`                  | ✓        | Switcher mounted; per-device export queued for v33. |
| `/notifications` (rules)    | ✓        | Switcher mounted; per-device rule UI queued for v33. |
| `/channels`                 | ✗        | Channels are still global. Per-device channel matrix queued for v33. |
| `/account/profile`          | ✗        | User-scoped, no device context. |
| `/account/subscription`     | ✗        | User-scoped, no device context. |
| `/portal/support`           | ✗        | Tickets can reference a device but page itself doesn't filter — switcher would be misleading. |
| `/onboarding`               | ✗        | Single-device flow today; multi-device branch queued for v33. |
| `/devices/manage/N/edit`    | ✗        | Per-device by definition; switcher would be redundant on this page. |

---

## Visual QA log

- Live server confirmed serving v32 bundle: all six CSS files load with
  `?v=v32-subscriber-console-unified-multidevice`.
- `/admin/dashboard?lang=ar` rendered identically to before — no regression
  on admin side. The context processor correctly skips admin scope, so
  the device switcher is **not** injected on admin pages.
- Build badge shows "v32 · subscriber-console" in the bottom-left,
  pointer-events disabled, opacity 0.55 (hover → 1.0).
- Python `compileall app/` exits cleanly; no syntax errors introduced
  by the new `services/device_context.py` module or the template edits.
- Subscriber-side live QA (devices/manage, live-data, notifications)
  could not be completed end-to-end because the local DB has no `ahmad`
  account and the `qa.subscriber.style` user (id 22, 5 devices) refused
  the provided password. Setting a new password requires shutting down
  the running Flask server (DB lock). Recommended path: log in locally
  as the multi-device QA subscriber, walk through the three pages, and
  capture screenshots — the implementation is in place and the static
  HTML/CSS plus admin-page regression-check confirm the bundle is
  healthy.

---


---

## v32 QA addendum (2026-05-08)

Real browser QA was performed using Chrome MCP against the live local
server (production database via `.env` `DATABASE_URL`, logged in as the
real `ahmad` subscriber).

### What works right now (no restart needed)

- **`/devices/manage?lang=ar`** — full new design:
  - Soft warm hero (`.sub-page` overrides `.hu-hero` to amber wash).
  - "1 جهاز · 🟢 1 نشط · ★ المحدّد: احمد احمد" meta pills.
  - "+ أضف جهازاً" amber CTA.
  - Single-device banner (`.dswx-single-banner`) above the hero:
    "🏠 تعرض بيانات الجهاز **احمد احمد** · deye · Asia/Hebron · إدارة"
  - Aside with explainer + status legend + tips.
  - 3 `.sub-kpi` tiles (إجمالي / النشطة / المحدّد).
  - 1 `.dm-device-card` with floating "★ محدّد" pill, status row,
    metadata grid (نوع / المنطقة الزمنية / آخر مزامنة / حالة الاتصال),
    and 3 action buttons (تحديد / تعديل / تعطيل).
  - Add-device form with 4 fields and 2 sub-btn buttons.
  - Bottom-left build badge "v32 · subscriber-console".

### What needs a Flask restart to fully activate

- Switcher / single-banner on `/live-data`, `/loads`, `/statistics`,
  `/reports`, `/notifications`, `/notifications/center` (route changes
  in source, not in process).
- `?selected_device_id=N` URL → session-flip → clean-URL redirect (the
  before_request hook is registered at `create_app()`).
- The `device_switcher_context()` helper called from `loads_page` and
  `live_data` (Python-import resolution).

### Out-of-scope visual deltas noticed

- `/devices/manage/1/edit` uses a separate `device_form.html` template
  with its own `dm64-*` style namespace. It looks clean, but the hero
  is sky-blue (not warm subscriber gradient). Aligning it with the v32
  unified design is a v33 polish task.
- `/live-data` hero is taller than ideal (~45% of viewport). The
  `unified_hero_v1.css` `.hu-hero` defaults to `padding: 32px clamp(28px,
  3.2vw, 44px) 36px` — which is correct. The visual height comes from
  the long Arabic tagline wrapping. Acceptable for now.


---

## v32 FINAL STATUS (post-restart, 2026-05-08)

| Page | Verdict | Visible features |
|---|---|---|
| `/devices/manage` | ✅ PASS | Banner + 3 KPIs + fleet grid + selected pill + form |
| `/devices/manage/1/edit` | ✅ PASS | Banner + new hu-hero + status pills + 4 sub-cards + sub-btn actions |
| `/live-data` | ✅ PASS | Banner + cool hero + device-aware tagline + meta pills + context strip + 4 KPIs + totals + recent table |
| `/notifications/center` | ✅ PASS | Banner + scope banner + cool hero + 4 stats + filters + 9-item inbox + side rail |
| `/loads` | ✅ PASS | Banner + cool hero + meta pills + recommendation + 3 KPIs + aside |
