# SolarDeye — Admin Design System Audit

**Build:** v32-subscriber-console-unified-multidevice
**Date:** 2026-05-08
**Purpose:** Distil the design DNA used across admin pages so the subscriber console can match it visually and structurally.

This document is the **source of truth** for the v32 subscriber redesign. Every choice in `subscriber_console_v32.css`, the device switcher integration, and the redesigned subscriber pages traces back to one of the rules below.

---

## 1. Color tokens (extracted from `unified_theme_v1.css` and admin pages)

```
--ink            #0b1220   page text (titles, KPIs)
--ink-soft       #1f2a44   secondary body text
--muted          #5e6f8c   metadata, eyebrows, helper text
--line           #e3eaf6   default borders
--line-strong    #cfd9ec   stronger borders / hover
--card           #ffffff   default card background
--amber          #f59e0b   primary brand accent (CTA, focus, selected)
--amber-soft     #fbbf24
--emerald        #10b981   success / online
--sky            #2563eb   informational (used by admin hero)
--violet         #6d3aff   admin-only accent (NOT used on subscriber side)
--rose           #f43f5e   destructive / error
```

Page background gradient (admin + subscriber):
```css
radial-gradient(1100px 480px at 12% -10%, rgba(109,58,255,.08), transparent 55%),
radial-gradient(900px 420px at 92% -4%, rgba(245,158,11,.08), transparent 55%),
linear-gradient(180deg, #f5f8ff 0%, #eef3fb 60%, #e8eef9 100%);
```

**Subscriber tonal twist:** subscriber pages already lighten the violet-blue washes and lean amber/emerald (`subscriber_v4.css` `.sub-page`). Keep that — it's a deliberate choice that makes the subscriber side feel friendlier than the admin command-center.

Status pills use a fixed palette:
- success → bg `#ecfff4` / text `#0f7a3b` / border `#bbe3c8`
- warning → bg `#fff8dd` / text `#8b6a00` / border `#f1de8a`
- danger  → bg `#fff0f1` / text `#be3a4d` / border `#f4bfca`
- info    → bg `#dbeafe` / text `#1d4ed8` / border `#bfdbfe`

---

## 2. Typography

- Font: `'Cairo','Inter',system-ui,sans-serif` — **single family, no exceptions**.
- Page title (`h1`): `clamp(1.5rem, 2.4vw, 2rem)`, weight 950, letter-spacing -0.2px.
- Section title (`h2`/`h3`): `1.05–1.25rem`, weight 900.
- Card title: `0.95–1.05rem`, weight 900.
- Body: `0.88–0.92rem`, weight 600 (text), 700 (emphasised body).
- Metadata / eyebrow: `0.7–0.78rem`, weight 800–900, **uppercase**, letter-spacing 0.4px.
- Numbers / KPI values: `tabular-nums`, weight 950.
- Arabic readability: line-height 1.5–1.6, no condensed widths.

---

## 3. Layout shell

```
.app-shell.has-layout-sidebar.sidebar-collapsed
  ├── _sidebar.html                          (sidebar v11 rebuild — do NOT swap)
  └── main.app-main.content-area
        ├── header.hu-hero (or admin-page-head)
        ├── (optional) .hu-hero-meta pills row
        ├── KPI strip
        ├── 1- or 2-column shell  ({prefix}-shell + {prefix}-aside + {prefix}-main)
        └── Page-specific sections
```

- Page padding: `18px clamp(14px, 2.4vw, 32px) 80px`.
- Section spacing: `18–24px gap`.
- 2-column shell: `grid-template-columns: minmax(0,1fr) 320px` collapsing to 1 col below 1080px.
- Mobile: hero collapses to single column at 980px; KPI grids collapse to 1 column at 768px; sidebar collapses to a slide-over (handled by sidebar v11 JS — don't fight it).

---

## 4. Hero pattern (used everywhere)

There are **two** valid hero shells:

### A. `header.hu-hero` (preferred for subscriber + most admin pages)

Light gradient, dotted top decoration, wave footer (defined in `unified_hero_v1.css`).

```html
<header class="hu-hero">
  <div class="hu-hero-grid">
    <div class="hu-hero-text">
      <span class="hu-eyebrow"><svg/> Section · Page</span>
      <h1 class="hu-h1">Page title</h1>
      <p class="hu-tagline">Short description.</p>
      <div class="hu-hero-meta">
        <span class="hu-meta-pill"><b>12</b> devices</span>
        <span class="hu-meta-pill ok">✓ <b>3</b> active</span>
      </div>
    </div>
    <div class="hu-hero-cta">
      <a class="hu-btn hu-btn-ghost">Secondary</a>
      <a class="hu-btn hu-btn-primary">＋ Primary</a>
    </div>
  </div>
</header>
```

Subscriber pages override the gradient via `.sub-page .hu-hero` to a warm amber wash; "monitoring" pages use `.sub-page.sub-cool` for a sky-blue wash. **Both already exist** in `subscriber_v4.css` lines 376–411.

### B. `header.admin-page-head` (sky-amber gradient, used by some legacy admin pages)

Stronger sky→amber gradient, white H1, white meta pills. Defined in `unified_theme_v1.css` lines 614–685. **Only use this on admin-shell pages, never subscriber.**

---

## 5. Card / KPI patterns

### Stat / KPI card (universal)
```css
background: #fff;
border: 1px solid var(--line);
border-radius: 22px;
padding: 18px 20px;
box-shadow: 0 6px 18px rgba(15,23,42,.06);
```
- Top accent bar (`::before`) 3px tall — uses brand gradient.
- KPI value: weight 950, `tabular-nums`, 1.4–1.65rem.
- Hover: `translateY(-2px)` + stronger shadow.

### Generic panel card
```css
background: #fff;
border: 1px solid var(--line);
border-radius: 22–24px;
padding: 22px;
```
- Section heading inline (`<h3>` + `<small>` muted) with dashed bottom-border separator.

### Empty-state card
```css
background: #f7faff;
border: 1px dashed var(--line-strong);
border-radius: 18px;
padding: 18px;
text-align: center;
```

---

## 6. Tables

`.admin-table-v2` is the gold standard:
- Separated borders (`border-collapse: separate; border-spacing: 0`).
- Header row gradient `linear-gradient(180deg,#f7faff,#eef3fb)`.
- Header text uppercase 900 weight, letter-spacing 0.4px.
- Body cells `padding: 14px`, `vertical-align: middle`.
- Row hover background `#f7faff`.
- Last row no bottom border.

Subscriber tables (`.dm-table` etc.) follow the same rules but with slightly tighter padding (12–14px).

---

## 7. Buttons

| Variant       | Class                  | Background                          | Text     | Border                |
|---------------|------------------------|-------------------------------------|----------|-----------------------|
| Primary       | `.hu-btn-primary` / `.btn-primary` | linear amber `#ffcf4d → #f59e0b` | `#0b1531` | none |
| Ghost         | `.hu-btn-ghost`        | `#fff`                              | `#1f2a44`| transparent           |
| Outline       | `.btn-outline-primary` | `#fff`                              | ink-soft | `--line`              |
| Success       | `.hu-btn-success`      | `#34d399 → #10b981`                 | `#04221b`| none                  |
| Danger        | `.hu-btn-danger`       | `#fb7185 → #f43f5e`                 | `#fff`   | none                  |

- Border-radius: 12–14px.
- Padding: `.6rem 1.05rem` default, `.45rem .8rem` small.
- Hover: `translateY(-1px)` + larger shadow.
- All buttons: `font-weight: 900`, gap `.4rem`, `display: inline-flex`.

---

## 8. Filters / chips / toolbar

`.sub-filters` (subscriber) and `.ad-quick` (admin) are both:
- Card-style container (white, bordered, radius 14–18px).
- Inline filter inputs/selects with bg `#f8fafc`.
- Chips: pill rounding (999px), weight 800.

---

## 9. Tabs

`.user360-tab` (admin) and `.sub-tab` (subscriber):
- Container: white card with internal padding 4–10px.
- Inactive tab: transparent bg, muted text.
- Active tab: amber gradient bg `#ffcf4d → #f59e0b` (admin) or `#fef3c7 → #fde68a` (subscriber, lighter), bold text.

---

## 10. Empty states (must look beautiful)

```html
<div class="sub-empty">           OR    <div class="dm-empty">
  <span class="sub-empty-icon">📭</span>
  <strong class="sub-empty-title">No devices yet</strong>
  <p class="sub-empty-body">Connect your first inverter or gateway to start monitoring.</p>
  <a class="sub-btn sub-btn-primary">＋ Add device</a>
</div>
```
- Padding 30–48px, centered, soft icon (3rem, .6 opacity).
- Title weight 900, body line-height 1.6, max-width 420px.

---

## 11. Sidebar (sidebar v11 rebuild)

- Defined in `sidebar_rebuild_v11.css` and `sidebar_rebuild_v11.js`.
- Always include `_sidebar.html` from base templates.
- Body classes: `app-shell.has-layout-sidebar.sidebar-collapsed` (default).
- **DO NOT mix in older `_sidebar_*` partials** — there is exactly one sidebar system; respect it.

---

## 12. Coding conventions

- **Page-prefix classes:** every page has its own short prefix (`dm-`, `lv-`, `lds-`, `chn-`, `ncv40-`, `sc-`, `ad-`, `pf-`, `sp-`, …). These hold all page-specific styling and prevent cross-bleed.
- **Shared layer:** `.sub-*` (subscriber) and `.admin-*-v2` (admin) hold the shared building blocks. Reach for them first; fall back to a page prefix only when behaviour is genuinely page-specific.
- **CSS files:** versioned per page (`channels_v3.css`, `notifications_center_v40.css`). Bump version on every meaningful redesign.
- **Cache-bust:** `url_for('static', filename='css/X.css', v='vNNN-tag-YYYYMMDD')`.
- **Templates:** load page-specific CSS through `{% block extra_head %}` in the page template, not in `base.html`.
- **JS hooks:** use `data-*` attributes (`data-dswx`, `data-paginate`, `data-help`) — never query by class.
- **i18n:** Arabic-first; English via `{% if is_en %}…{% else %}…{% endif %}` ternaries with `is_en = (ui_lang or 'ar') == 'en'`.
- **RTL:** logical properties (`inset-inline-start/end`, `padding-inline-end`) — not `left`/`right`.
- **Numbers always `dir="ltr"` islands** when shown inside Arabic text (per design playbook).

---

## 13. Multi-device design rules (NEW for v32)

### When to show the device switcher
- On any page where the data being viewed is scoped to one device: `/live-data`, `/statistics`, `/reports`, `/loads`, `/notifications`, `/notifications/center`, `/devices/manage` (highlighted), and the dashboard.
- **Hide** the switcher when the user has **0 or 1** device — it just adds noise.
- On `/account/profile`, `/account/subscription`, `/channels` (currently global), `/portal/support` — no per-device scope, so no switcher.

### Where the switcher sits
- **Above** the hero, with 14–18px gap below it before the next section.
- Inside the same `<main>` element so it inherits page padding.

### Selection persistence
- Source of truth: `AppUser.preferred_device_id` (already exists on the model).
- Mirror in `session['current_device_id']` for fast access across requests.
- "All devices" mode: store the literal string `'__all__'` in session OR set `aggregate_mode = True` in template context.
- The `?selected_device_id=N` query param on any link triggers a session update + redirect-without-param (clean URLs).

### Device-aware copy
- KPI subtitles, "last update" pills, error messages must mention device name when available: e.g. *"Last update from **Roof Inverter** at 14:32"*.
- Empty states: *"This device hasn't sent data yet"* (singular) vs *"None of your devices have data yet"* (aggregate).

---

## 14. Page density & SaaS feel

The bar to clear:
- **Calm:** never more than 5 visual emphasis points per fold (KPIs + hero + one section title).
- **Clean:** at most 2 levels of card nesting.
- **Spacious but not empty:** `gap` between sections matches `padding` of the largest card (≈ 22px).
- **Single visual system:** no mixing of `admin-page-head` with subscriber pages, no leftover `style.css` legacy classes inside scoped pages.
- **No top banners.** Build badge stays in the footer (`.dev-build-badge-v11`).
- **Forms** never have more than 4 fields per visible row, never less than 1.6 line-height in labels, always have a brief helper text under each field.

---

## 15. What the subscriber redesign must inherit

1. The **page shell** (`.app-shell` + `_sidebar.html` + `main.app-main.content-area`).
2. The **`hu-hero` pattern** — already used by `live_data.html`, `devices_manage.html`, `loads.html`, `channels.html`. Keep it. **Standardise** the eyebrow icon and meta pills across all subscriber pages.
3. The **`.sub-*` shared layer** from `subscriber_v4.css`. Currently this file exists but is not loaded by any subscriber template (they all load `subscriber_v3.css`). Resolution: load **both**, with `subscriber_v4.css` after for shared building blocks, and let `subscriber_v3.css` keep the page-prefix legacy styles until each page is migrated.
4. The **device switcher** (`_device_switcher.html` + `.dswx-*` CSS) — **wire it in** above the hero on the right pages.
5. The **same color tokens, type scale, spacing, and shadow values** documented above.

---

## 16. Anti-patterns to delete

- ❌ Hard-coded inline-style KPI tiles (e.g. `<article style="display:flex;…padding:14px 16px;background:#fff;border:1px solid…">` repeated three times in `devices_manage.html` lines 75–86). Replace with a single `.sub-kpi` or `.dm-kpi` class.
- ❌ "Top update banners" or "what's new" announcements pinned at the top.
- ❌ `<table>` styled with raw inline colors instead of the `.dm-table` / `.admin-table-v2` classes.
- ❌ Mixing emojis as primary status indicators with no fallback — keep them, but always pair with a status pill class.
- ❌ Two devices' data shown in the same view without a clear label.

---

## 17. Open questions / future work

- **Channels are still global** (Setting key/value table). Per-device channel routing is a backend gap, intentionally deferred from this session. UI for per-device channel **assignment** can ship; the backend uses the global config until the new model lands.
- **NotificationRule** has no model yet — it's read from settings. Migrating to a real `notification_rule` table with `device_id` is a follow-up.
- **Onboarding** still assumes a single device. The wizard needs a multi-device-aware "add another device" branch — not in scope for this session, queued for v33.

---
