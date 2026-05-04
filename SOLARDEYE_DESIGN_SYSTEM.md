# SolarDeye — Design & Intelligence System Reference
> **A complete blueprint for reproducing the dashboard/statistics/reports/live-data/devices look-and-feel and the underlying smart pipeline.** Hand this single file to any LLM with the prompt _"build me a new page that matches this design system 1:1"_ and the result will fit the rest of the product.

Last build covered: `dashboard.html`, `statistics.html`, `reports.html`, `live_data.html`, `devices_manage.html` + the supporting Python services (`sun_context.py`, `smart_engine.py`, `helpers.py`, `energy.py`).

---

## 0. Philosophy

Five principles drive every decision in this system. Treat them as non‑negotiable.

| # | Principle | Meaning |
|---|---|---|
| 1 | **Single Source of Truth** | Every "what time of day is it?", "is the sun producing?", "what icon should I show?" decision is computed *once* by `compute_sun_context()` and consumed everywhere. No widget recomputes from `solar_power > 50` or any other ad-hoc heuristic. |
| 2 | **Phase before reading** | Time-of-day phase (`night/dawn/sunrise/morning/noon/afternoon/pre_sunset/sunset/dusk`) decides the *frame* of the message before the live reading fills in the *number*. A 250 W reading means different things in morning vs sunset. |
| 3 | **Progressive trust** | When archive matches < 3 we say "بانتظار بناء الأرشيف"; 3–5 matches → "ثقة متوسطة • بحذر"; > 5 → "ثقة عالية • يعتمد". The UI never feigns certainty it doesn't have. |
| 4 | **Light, airy, tabular‑numeric** | White cards on soft sky-blue gradient. Generous spacing (24–30 px between sections, 18–22 px inside cards). Numbers always in `font-variant-numeric: tabular-nums` so columns align. |
| 5 | **Server-rendered first, JS poll second** | Every page is fully usable without JS. AJAX only swaps `#xx-content` for navigation, and the live poller updates *bound* fields via `data-bind` selectors. Polling never invents new structure. |

---

## 1. Color tokens

Every page declares its own scoped variables (using a 2-letter prefix matching the page) but the *values* are identical. Copy the block verbatim into any new page, just rename the prefix.

```css
.xx-page{
  /* INK */
  --xx-ink:        #0b1220;   /* primary heading */
  --xx-ink-soft:   #1f2a44;   /* body text, table cells */
  --xx-muted:      #4a5b78;   /* labels, sub-text — WCAG AA on white (~6.3:1) */

  /* LINES */
  --xx-line:        #e3eaf6;  /* card borders, dividers, faint */
  --xx-line-strong: #bcc8df;  /* visible dividers, input borders, hover */

  /* SURFACES */
  --xx-card:    #ffffff;       /* default card body */
  --xx-card-2:  #f9fbff;       /* gradient bottom of inset cards */
  --xx-bg:      #eef3fb;       /* page tint */

  /* BRAND / STATE COLORS (each has _soft + bg variants) */
  --xx-amber:        #f59e0b;  --xx-amber-soft:   #fbbf24;
  --xx-rose:         #f43f5e;  --xx-rose-soft:    #fb7185;
  --xx-emerald:      #10b981;  --xx-emerald-soft: #34d399;
  --xx-sky:          #2563eb;  --xx-sky-soft:     #60a5fa;
  --xx-violet:       #6d3aff;
  --xx-orange:       #f97316;

  /* SHADOWS */
  --xx-shadow-sm: 0 6px 18px rgba(15,23,42,.06);   /* hover, KPI cards */
  --xx-shadow:    0 22px 60px rgba(15,23,42,.09);  /* big cards, panels */
  /* hero shadow is hardcoded:  0 38px 90px rgba(15,23,42,.14)  */

  /* RADIUS */
  --xx-radius:     22px;   /* small cards, nav bars */
  --xx-radius-lg:  30px;   /* main cards, large panels */
  --xx-radius-xl:  38px;   /* hero only */
}
```

**Semantic meaning of accent colors:**

| Color | Used for |
|---|---|
| amber `#f59e0b` | Solar / generation / primary CTA / "current" highlight |
| rose `#f43f5e` | Home consumption / load |
| emerald `#10b981` | Battery / live status / success / "active" |
| sky `#2563eb` | SOC % / "info" / period column / chart trend |
| violet `#6d3aff` | Grid / integrations / categorical 4th |
| orange `#f97316` | Surplus / "today" highlight |

**Dark text per accent (use these for values inside that family of card):**
```
solar  → #b45309   home   → #be123c
batt   → #047857   sky    → #1d4ed8
violet → #5b21b6   orange → #c2410c
```

**Translucent background tints for icon boxes:**
```
amber-bg:   #fef3c7    rose-bg:    #ffe4e6
emerald-bg: #d1fae5    sky-bg:     #dbeafe
violet-bg:  #ede9fe    orange-bg:  #ffedd5
```

---

## 2. Page background

Every page uses the same gradient + halos so the navigation between them feels continuous:

```css
.xx-page{
  background:
    radial-gradient(1100px 480px at 12% -10%, rgba(109,58,255,.10), transparent 55%),
    radial-gradient( 900px 420px at 92%  -4%, rgba(245,158,11,.10), transparent 55%),
    linear-gradient(180deg,#f5f8ff 0%,#eef3fb 60%,#e8eef9 100%);
  min-height:100vh;
  padding:18px clamp(14px,2.4vw,32px) 80px;
  font-family:'Cairo','Inter',system-ui,sans-serif;
  color:var(--xx-ink);
  display:flex;flex-direction:column;gap:24px;
}
.xx-page *,.xx-page *::before,.xx-page *::after{box-sizing:border-box}
```

### MANDATORY: explicit margins for top-level sections (not flex `gap`)

The page wrapper uses `display:flex; flex-direction:column;` for predictable rendering, **but inter-section spacing is enforced with explicit `margin-block-start` on each direct child**, not flex `gap`.

Why: global selectors targeting `.app-main > *`, `.content-area > *`, etc. in `style.css` regularly override flex gap and break vertical rhythm on inner pages. Explicit `!important` margins survive every override.

Canonical pattern (every page must include this block right after the `.xx-page` declaration):

```css
.xx-page > .xx-hero    { margin: 0 !important }
.xx-page > .xx-stats   { margin: 26px 0 0 0 !important }
.xx-page > .xx-toolbar { margin: 26px 0 0 0 !important }
.xx-page > .xx-grid    { margin: 26px 0 0 0 !important }
.xx-page > section,
.xx-page > header      { margin-block-start: 26px !important }
.xx-page > :first-child{ margin-block-start: 0 !important }
```

- Standard inter-section margin: **26 px**
- The `:first-child` reset prevents an empty gap above the hero
- The `!important` is non-negotiable — without it you will lose to the global cascade
- Never set `margin-bottom` on individual sections; spacing is owned by the *next* section's `margin-block-start`

---

## 3. Hero (sky → amber gradient banner)

The hero is the same on every authenticated page. It has a left text column and a right action column.

```css
.xx-hero{
  position:relative;border-radius:var(--xx-radius-xl);
  padding:clamp(22px,3vw,34px) clamp(20px,3vw,38px);
  overflow:hidden;color:#fff;
  box-shadow:0 38px 90px rgba(15,23,42,.14);isolation:isolate;
  background:linear-gradient(135deg,#0e3b86 0%,#3aa7ff 50%,#ffd66e 100%);
}
.xx-hero::before{    /* halo accents */
  content:"";position:absolute;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(420px 240px at 12% 18%, rgba(255,255,255,.18), transparent 60%),
    radial-gradient(380px 220px at 88% 80%, rgba( 11, 23, 67,.25), transparent 60%);
}
.xx-hero-grid{
  position:relative;z-index:1;display:grid;gap:18px;
  grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);
  align-items:center;
}
@media (max-width:980px){.xx-hero-grid{grid-template-columns:1fr}}
```

### Hero anatomy (mandatory order):

```
xx-hero
└── xx-hero-grid
    ├── xx-hero-text (1.2fr)
    │   ├── xx-eyebrow              ← pill chip with pulsing dot
    │   ├── h1                      ← page title (clamp 1.55–2.05rem, weight 950)
    │   ├── p                       ← page subtitle/description
    │   └── xx-hero-meta            ← row of meta chips (📅 / 🌅 / 🟢 LIVE / etc)
    │       ├── xx-hero-meta-item   ← white pill, 12 px radius
    │       └── xx-live-chip        ← emerald gradient with pulsing dot (when live)
    └── xx-hero-actions (1fr)       ← right side, justify:flex-end
        ├── xx-export-btn.csv       ← white pill, secondary action
        ├── xx-export-btn.pdf       ← amber gradient, primary CTA
        └── xx-refresh-btn          ← white with sky accent text, animated icon
```

### Eyebrow chip (pulse animation)

```css
.xx-eyebrow{
  display:inline-flex;align-items:center;gap:6px;align-self:flex-start;
  font-size:.72rem;font-weight:900;letter-spacing:.6px;text-transform:uppercase;
  color:#0b1531;background:rgba(255,255,255,.92);
  padding:.35rem .75rem;border-radius:999px;
  box-shadow:0 6px 16px rgba(11,21,49,.18);
}
.xx-eyebrow .xx-pulse{
  width:8px;height:8px;border-radius:50%;
  background:var(--xx-amber);
  box-shadow:0 0 0 0 rgba(245,158,11,.7);
  animation:xxPulse 1.8s infinite;
}
@keyframes xxPulse{
  0%  {box-shadow:0 0 0 0  rgba(245,158,11,.7)}
  70% {box-shadow:0 0 0 10px rgba(245,158,11,0)}
  100%{box-shadow:0 0 0 0  rgba(245,158,11,0)}
}
```

### Hero title

```css
.xx-hero h1{
  font-size:clamp(1.55rem,2.6vw,2.05rem);font-weight:950;
  margin:0;line-height:1.18;color:#fff;
  text-shadow:0 4px 18px rgba(11,21,49,.22);
}
.xx-hero p{
  margin:0;font-size:.95rem;color:rgba(255,255,255,.92);
  max-width:64ch;line-height:1.55;font-weight:600;
}
```

### Live chip (emerald gradient, used when content auto-refreshes)

```css
.xx-live-chip{
  display:inline-flex;align-items:center;gap:.4rem;
  padding:.36rem .75rem;border-radius:12px;
  background:linear-gradient(135deg,#10b981,#34d399);
  color:#04221b;font-size:.78rem;font-weight:900;
  box-shadow:0 6px 16px rgba(16,185,129,.32);
}
.xx-live-chip .xx-live-dot{
  width:7px;height:7px;border-radius:50%;background:#04221b;
  animation:xxPulseG 1.6s infinite;
}
@keyframes xxPulseG{
  0%  {box-shadow:0 0 0 0 rgba(4,34,27,.55)}
  70% {box-shadow:0 0 0 8px rgba(4,34,27,0)}
  100%{box-shadow:0 0 0 0 rgba(4,34,27,0)}
}
```

### Action buttons (primary, secondary, refresh)

```css
.xx-export-btn{
  display:inline-flex;align-items:center;gap:.45rem;
  padding:.6rem 1.05rem;border-radius:14px;
  font-size:.83rem;font-weight:900;
  text-decoration:none;border:1px solid transparent;cursor:pointer;
  transition:transform .15s,box-shadow .15s;font-family:inherit;
}
.xx-export-btn.csv{background:#fff;color:var(--xx-ink-soft);border-color:var(--xx-line)}
.xx-export-btn.csv:hover{transform:translateY(-1px);box-shadow:var(--xx-shadow-sm)}
.xx-export-btn.pdf{
  background:linear-gradient(135deg,#ffcf4d,#f59e0b);
  color:#0b1531;
  box-shadow:0 14px 30px rgba(245,158,11,.28);
}
.xx-export-btn.pdf:hover{transform:translateY(-1px);box-shadow:0 18px 36px rgba(245,158,11,.38)}
```

The amber gradient `#ffcf4d → #f59e0b` is **the** primary-action signature. Use it for any primary CTA: "Apply", "Add device", "Refresh now", "Export PDF", segmented control active state.

---

## 4. Sticky/glass nav bar (period selector pattern)

Used on `/statistics` and `/reports`. White-translucent with backdrop blur — sits between hero and content.

```css
.xx-nav-bar{
  position:relative;z-index:5;
  background:rgba(255,255,255,.92);
  backdrop-filter:saturate(160%) blur(14px);
  border:1px solid var(--xx-line);
  border-radius:var(--xx-radius);
  padding:12px 16px;
  display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:12px;
  box-shadow:var(--xx-shadow);
}
```

Components inside it:
- `.xx-seg` — segmented control: `display:flex` on a `#f1f5fc` background with 4 px padding and 14 px border-radius. Active button gets the amber gradient + 6 px y-offset shadow.
- `.xx-date-arrow` — 38×38 px square, 12 px radius, white background, subtle border, hover lifts 1 px.
- `.xx-date-input` — `<input type=date>` with 12 px radius and amber `:focus` ring (`0 0 0 3px rgba(245,158,11,.18)`).
- `.xx-apply-btn` — primary amber gradient pill.
- `.xx-title-hint` — `#f5f9ff` pill that displays the human-readable selected period.

---

## 5. KPI / Stat cards (the "shelf row")

Every page has 4–6 stat cards in a row right after the hero. Each card has a colored top accent bar.

```css
.xx-stats{
  display:grid;gap:18px;
  grid-template-columns:repeat(4,minmax(0,1fr));
}
@media (max-width:1024px){.xx-stats{grid-template-columns:repeat(2,1fr)}}
@media (max-width:560px) {.xx-stats{grid-template-columns:1fr}}

.xx-stat{
  position:relative;background:var(--xx-card);
  border:1px solid var(--xx-line);border-radius:var(--xx-radius-lg);
  padding:18px 20px 20px;
  box-shadow:var(--xx-shadow-sm);overflow:hidden;
  transition:all .2s;
  display:flex;flex-direction:column;gap:.4rem;
}
.xx-stat:hover{
  transform:translateY(-3px);
  box-shadow:var(--xx-shadow);
  border-color:var(--xx-line-strong);
}
.xx-stat::before{                                 /* the accent bar */
  content:"";position:absolute;inset:0 0 auto 0;height:5px;
  border-radius:var(--xx-radius-lg) var(--xx-radius-lg) 0 0;opacity:.95;
}
.xx-stat.amber  ::before{background:linear-gradient(90deg,#f59e0b,#fbbf24)}
.xx-stat.rose   ::before{background:linear-gradient(90deg,#f43f5e,#fb7185)}
.xx-stat.emerald::before{background:linear-gradient(90deg,#10b981,#34d399)}
.xx-stat.sky    ::before{background:linear-gradient(90deg,#2563eb,#60a5fa)}
.xx-stat.violet ::before{background:linear-gradient(90deg,#6d3aff,#a78bfa)}
.xx-stat.orange ::before{background:linear-gradient(90deg,#f97316,#fb923c)}
```

### Internal anatomy (mandatory):

```
xx-stat.<accent>
├── xx-stat-top              flex justify-between
│   ├── xx-stat-icon         46×46 px, 14 px radius, accent-bg color
│   └── xx-stat-trend        small tag, "current/active/total"
├── xx-stat-label            .78rem muted, weight 800
├── xx-stat-value            2rem weight 950, accent dark color, tabular-nums
└── xx-stat-sub              .78rem muted, 1.55 line-height
```

Sizing:
- Icon box: **46 × 46 px**, **radius 14 px**, font-size **1.4 rem**.
- Trend pill: padding `.3rem .65rem`, radius `999px`, background `#f1f5fc`, border `var(--xx-line)`.
- Value: `font-size: 2rem; font-weight: 950; letter-spacing: -.02em; line-height: 1.1`.

**Rule:** the stat value's color *must* match the dark text variant of its accent (`#b45309` for amber, `#047857` for emerald, etc.). The card is otherwise neutral — color is concentrated in the accent strip + value.

---

## 6. Section header

Used to introduce a list/grid below it. Always sits in the page flex stream (no extra margin above; the page's `gap:24px` handles spacing).

```css
.xx-section-head{
  display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:.75rem;padding:0 6px;
}
.xx-section-head h2{
  font-size:1.15rem;font-weight:950;color:var(--xx-ink);margin:0;
  display:inline-flex;align-items:center;gap:.5rem;
}
.xx-section-head h2 .xx-section-icon{
  width:32px;height:32px;border-radius:9px;
  background:rgba(37,99,235,.12);
  display:inline-flex;align-items:center;justify-content:center;
  font-size:1rem;color:#1d4ed8;
}
.xx-section-head small{
  display:block;color:var(--xx-muted);font-weight:700;font-size:.82rem;
}
.xx-section-head .xx-pill{                /* right-side pill (count, status) */
  display:inline-flex;align-items:center;gap:.4rem;
  font-size:.78rem;font-weight:800;color:var(--xx-ink-soft);
  background:#fff;padding:.4rem .75rem;border-radius:999px;
  border:1px solid var(--xx-line);box-shadow:var(--xx-shadow-sm);
}
```

---

## 7. Cards & panels

There are exactly three card sizes — always white, always with the same border + shadow.

| Type | Use case | Radius | Padding | Shadow |
|---|---|---|---|---|
| `xx-card` | Charts, tables, panels | `var(--xx-radius-lg)` (30px) | `18-20 px` outer, content gets `1.1 rem 1.4 rem 1.2 rem` | `--xx-shadow-sm` (rises to `--xx-shadow` on hover) |
| `xx-stat`/`xx-metric` | KPI shelf | `var(--xx-radius-lg)` (30px) | `18 20 20 20` | `--xx-shadow-sm` |
| Mini cards inside panels (`xx-mini-stat`, `xx-side-stat`) | Sub-stats inside another card | `13–16 px` | `.75 .85 rem` | none (just background gradient) |

**Card head pattern** (universal):

```html
<div class="xx-card">
  <div class="xx-card-head">
    <div>
      <h3>📈 Title</h3>
      <small>Sub-description</small>
    </div>
    <span class="xx-pill">Right-side hint</span>
  </div>
  <div class="xx-chart-wrap">…content…</div>
</div>
```

```css
.xx-card-head{
  display:flex;align-items:flex-start;justify-content:space-between;
  padding:18px 20px 4px;flex-wrap:wrap;gap:.75rem;
}
.xx-card-head h3{
  font-size:1.02rem;font-weight:950;color:var(--xx-ink);
  margin:0 0 .2rem;line-height:1.3;
}
.xx-card-head small{
  font-size:.78rem;color:var(--xx-muted);font-weight:700;display:block;
}
```

The leading emoji on the `<h3>` is part of the design language — it keeps the page scannable. Reserved emojis:

| Emoji | Section |
|---|---|
| 📈 | Time/profile chart |
| 🧩 | Distribution / Mix / Categories |
| 📋 | Table / Analytical breakdown |
| 💡 | Smart suggestions / Tips |
| 🔋 | Battery |
| ☀️ / 🌤️ | Solar / weather |
| 🏠 | Home |
| ⚡ | Grid / Power |
| 📅 / 🗓️ / 📆 | Day/Week/Month |

---

## 8. Mini stats (inside panels)

```css
.xx-mini-stat{
  background:linear-gradient(180deg,#fff,#f7faff);
  border:1px solid var(--xx-line);border-radius:16px;
  padding:.85rem .95rem;
  display:flex;flex-direction:column;gap:.3rem;
  transition:transform .15s,box-shadow .15s;
}
.xx-mini-stat:hover{transform:translateY(-1px);box-shadow:var(--xx-shadow-sm)}
.xx-mini-label{
  font-size:.7rem;color:var(--xx-muted);font-weight:900;
  text-transform:uppercase;letter-spacing:.5px;
}
.xx-mini-value{
  font-size:1.02rem;font-weight:950;
  font-variant-numeric:tabular-nums;color:var(--xx-ink);
  display:inline-flex;align-items:center;gap:.35rem;
}
```

Notice the `linear-gradient(180deg,#fff,#f7faff)` — this is the **inset card gradient**. Reuse it for any sub-card inside a parent card.

---

## 9. Tables

```css
.xx-table{
  width:100%;border-collapse:collapse;font-size:.88rem;
  font-variant-numeric:tabular-nums;
}
.xx-table thead th{
  padding:.85rem 1rem;text-align:start;
  font-size:.7rem;font-weight:900;
  color:var(--xx-muted);text-transform:uppercase;letter-spacing:.5px;
  background:#f5f9ff;
  border-bottom:1px solid var(--xx-line);white-space:nowrap;
}
.xx-table tbody tr{
  border-bottom:1px solid var(--xx-line);transition:background .15s;
}
.xx-table tbody tr:last-child{border-bottom:none}
.xx-table tbody tr:hover{background:#f8fbff}
.xx-table tbody td{
  padding:.85rem 1rem;color:var(--xx-ink-soft);white-space:nowrap;font-weight:700;
}

/* The first column gets the "period pill" treatment */
.xx-period-pill{
  display:inline-block;padding:.28rem .75rem;border-radius:999px;
  background:#eef3ff;color:#1d4ed8;
  font-size:.78rem;font-weight:900;
  border:1px solid #dbe5fb;
}

/* Per-column accent classes */
.xx-val-solar{color:#b45309 !important}
.xx-val-home {color:#be123c !important}
.xx-val-batt {color:#047857 !important}
.xx-val-grid {color:#1f2937 !important}
```

Use a **pill in the first column** to set the row's identity. Numbers are tabular-nums and use the dark text of the accent associated with that column's data.

---

## 10. Drawers (slide-in panels)

Used for "Add device" and similar flows. **Slim** (≤ 540 px), sky-gradient header.

```css
.xx-drawer{position:fixed;inset:0;z-index:9100;pointer-events:none;opacity:0;transition:opacity .2s}
.xx-drawer.open{pointer-events:all;opacity:1}
.xx-drawer-backdrop{position:absolute;inset:0;background:rgba(15,23,42,.45);backdrop-filter:blur(4px)}
.xx-drawer-panel{
  position:absolute;top:0;bottom:0;width:min(540px,96vw);
  background:#fff;display:flex;flex-direction:column;overflow:hidden;
  box-shadow:-12px 0 40px rgba(15,23,42,.20);
  transition:transform .3s cubic-bezier(.4,0,.2,1);
}
[dir=rtl] .xx-drawer-panel{left:0;transform:translateX(-110%)}
[dir=ltr] .xx-drawer-panel{right:0;transform:translateX(110%)}
.xx-drawer.open .xx-drawer-panel{transform:translateX(0)}

.xx-drawer-head{
  position:relative;padding:20px 22px 16px;
  background:linear-gradient(135deg,#0e3b86 0%,#3aa7ff 80%);
  color:#fff;flex-shrink:0;
}
.xx-drawer-head::after{   /* amber underline, signature touch */
  content:"";position:absolute;inset:auto 0 0 0;height:3px;
  background:linear-gradient(90deg,#fbbf24,#f59e0b);
}
```

The drawer head **always** has the sky-blue gradient + 3 px amber underline. Body is plain white. Footer (action buttons) gets `background:#f8fbff` to visually anchor it.

**Step indicator** inside drawers:

```css
.xx-step-num{
  width:26px;height:26px;border-radius:50%;
  background:var(--xx-line);color:var(--xx-muted);
  display:flex;align-items:center;justify-content:center;
  font-size:.78rem;font-weight:900;transition:all .2s;
}
.xx-step.active .xx-step-num{
  background:linear-gradient(135deg,#ffcf4d,#f59e0b);
  color:#0b1531;
  box-shadow:0 4px 12px rgba(245,158,11,.25);
}
.xx-step.done .xx-step-num{background:var(--xx-emerald);color:#fff}
```

---

## 11. Form fields (inside drawers, modals, settings)

```css
.xx-field input, .xx-field textarea{
  background:#fff;border:1px solid var(--xx-line);border-radius:11px;
  color:var(--xx-ink);padding:.55rem .8rem;
  font-size:.88rem;font-family:inherit;font-weight:600;outline:none;
  transition:border-color .15s,box-shadow .15s;
}
.xx-field input:focus, .xx-field textarea:focus{
  border-color:var(--xx-amber);
  box-shadow:0 0 0 3px rgba(245,158,11,.18);
}
.xx-field input::placeholder{color:var(--xx-muted);font-weight:500}
.xx-field label{
  font-size:.78rem;font-weight:800;color:var(--xx-ink-soft);
  display:flex;align-items:baseline;gap:4px;margin:0;
}
```

**Custom toggle switch** (use this instead of native `<input type=checkbox>` everywhere):

```css
.xx-toggle-row input[type=checkbox]{
  appearance:none;width:38px;height:22px;border-radius:11px;
  background:var(--xx-line);position:relative;cursor:pointer;
  transition:background .2s;flex-shrink:0;
}
.xx-toggle-row input[type=checkbox]::after{
  content:"";position:absolute;top:2px;inset-inline-start:2px;
  width:18px;height:18px;border-radius:50%;background:#fff;
  box-shadow:0 2px 4px rgba(15,23,42,.2);
  transition:inset-inline-start .2s;
}
.xx-toggle-row input[type=checkbox]:checked{
  background:linear-gradient(135deg,#10b981,#34d399);
}
.xx-toggle-row input[type=checkbox]:checked::after{inset-inline-start:18px}
```

---

## 12. Status pills

For showing connection state, alert level, etc. Always have a leading dot + pastel background + dark text.

```css
.xx-status{
  display:inline-flex;align-items:center;gap:.5rem;
  font-size:.78rem;font-weight:800;
  padding:.32rem .65rem;border-radius:999px;align-self:flex-start;
  background:#f1f5fc;color:var(--xx-ink-soft);border:1px solid var(--xx-line);
}
.xx-status .xx-dot{width:7px;height:7px;border-radius:50%;
  background:var(--xx-muted);flex-shrink:0;
}

/* States */
.xx-status.connected{background:#d1fae5;color:#047857;border-color:#a7f3d0}
.xx-status.connected .xx-dot{background:var(--xx-emerald);box-shadow:0 0 6px rgba(16,185,129,.5)}
.xx-status.error    {background:#ffe4e6;color:#be123c;border-color:#fecdd3}
.xx-status.error    .xx-dot{background:var(--xx-rose)}
.xx-status.pending  {background:#fef3c7;color:#b45309;border-color:#fde68a}
.xx-status.pending  .xx-dot{background:var(--xx-amber)}
```

---

## 13. Empty states

Always white card with **dashed border** to signal "nothing here yet but it's ready":

```css
.xx-empty{
  background:var(--xx-card);
  border:2px dashed var(--xx-line-strong);
  border-radius:var(--xx-radius-lg);padding:60px 30px;text-align:center;
  box-shadow:var(--xx-shadow-sm);
}
.xx-empty-icon{
  width:80px;height:80px;margin:0 auto 18px;border-radius:24px;
  background:linear-gradient(135deg,rgba(255,207,77,.18),rgba(245,158,11,.12));
  display:flex;align-items:center;justify-content:center;font-size:2.4rem;
}
.xx-empty h3{font-size:1.3rem;font-weight:950;color:var(--xx-ink);margin:0 0 .4rem}
.xx-empty p{font-size:.92rem;color:var(--xx-muted);font-weight:600;
  max-width:420px;margin:0 auto 22px;line-height:1.55}
```

---

## 14. Charts (Chart.js)

Universal options object — copy verbatim, don't deviate:

```js
const chartBase = {
  responsive: true, maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      position: 'bottom',
      labels: {
        color: '#1f2a44', usePointStyle: true, boxWidth: 10, padding: 14,
        font: { family: 'Cairo', weight: '700' },
      }
    },
    tooltip: {
      backgroundColor: 'rgba(15,23,42,.95)',
      borderColor: 'rgba(255,255,255,.12)', borderWidth: 1,
      titleColor: '#fff', bodyColor: 'rgba(255,255,255,.92)',
      titleFont: { family: 'Cairo', weight: '800' },
      bodyFont:  { family: 'Cairo' },
      padding: 10, cornerRadius: 10, rtl: true,
    }
  },
  scales: {
    x: {
      grid:  { color: 'rgba(15,23,42,.05)' },
      ticks: { color: '#5e6f8c', font: { family: 'Cairo', weight: '600' },
               maxRotation: 0, minRotation: 0 }
    },
    y: {
      beginAtZero: true,
      grid:  { color: 'rgba(15,23,42,.05)' },
      ticks: { color: '#5e6f8c', font: { family: 'Cairo', weight: '600' } }
    }
  }
};
```

Dataset color rules:

| Dataset | Border | Fill |
|---|---|---|
| Solar power | `#f59e0b` | `rgba(245,158,11,.18)` |
| Home load | `#f43f5e` | `rgba(244,63,94,.10)` |
| Battery | `#10b981` | `rgba(16,185,129,.10)` |
| SOC % | `#2563eb` | dashed `[6,4]`, no fill |
| Grid | `#94a3b8` | for bars only |

Always:
- `tension: 0.4` on lines.
- `pointRadius: 3, pointHoverRadius: 6, borderWidth: 3` for line series.
- `borderRadius: 6–8, barPercentage: .7–.8` for bar series.
- Doughnut: `cutout: '64–66%'`, `borderColor: '#fff'`, `borderWidth: 4`, `hoverOffset: 8`.

---

## 15. Backend intelligence — `SunContext` is the spine

All "what time of day?" / "should we be in day mode?" / "what icon?" / "what advice?" logic flows through one service:

`app/services/sun_context.py` exports `compute_sun_context(latest, weather, settings) -> SunContext`.

### Phase set (9 phases — never collapse to a boolean)

```
night → dawn → sunrise → morning → noon → afternoon → pre_sunset → sunset → dusk → night
```

`is_day_for_production` returns `True` only for `{sunrise, morning, noon, afternoon, pre_sunset}`. Don't gate decisions on raw `solar_power > 50` — use the phase.

### Required SunContext fields

```python
@dataclass(frozen=True)
class SunContext:
    now_local: datetime
    timezone_name: str
    sunrise_text: str              # "HH:MM"
    sunset_text: str               # "HH:MM"
    sunset_effective_text: str     # ~1 h before official
    phase: str
    label_ar: str; label_en: str
    icon: str                      # phase icon (☀️/🌅/🌇/🌙/etc)
    description_ar/en: str
    accent: str                    # hex matching the phase
    gradient: str                  # css gradient for that phase
    is_day_for_production: bool
    is_night: bool
    is_twilight: bool
    is_producing_meaningfully: bool   # solar_power > 100W AND productive phase
    minutes_to_sunset: int
    minutes_to_sunrise: int
    has_weather_times: bool
```

### Public methods every consumer calls

| Method | Returns |
|---|---|
| `weather_icon_for(condition, cloud_cover)` | Phase-aware icon (🌙 at night even if API said "Clear") |
| `weather_label_for(condition, cloud_cover, lang)` | "ليل صافٍ" at night instead of "مشمس" |
| `weather_advice(lang)` | Single sentence, time-of-day correct (no "best time to run appliances is morning" at 7 PM) |
| `smart_card_lead(lang)` | One opening sentence for the smart-prediction card — never concatenated |
| `decision_matrix(confidence, risk, surplus_kwh)` | Single source of decision: `(status_label, decision_now)` |

### Decision matrix logic

```
phase ∈ {night, dusk}      → "فترة ليلية"  / "اعتمد على البطارية حتى الشروق"
phase ∈ {dawn, sunset}     → "وقت انتقالي" / "انتظر استقرار الإنتاج"
confidence == 'low'        → "بانتظار بناء الأرشيف" / "اعتمد على القراءات الحالية"
risk == 'high' AND surplus == 0  → "أوقف الأحمال الإضافية" / "لا تشغّل أحمالًا جديدة"
risk == 'high' AND surplus > 0   → "تشغيل صغير فقط" / "أحمال خفيفة وقصيرة"
risk == 'medium'                 → "تشغيل محدود" / "متوسطة، راقب الفائض"
default                          → "وضع جيد للتشغيل" / "أحمال معتادة بأمان"
```

### Wiring rules (mandatory)

1. Any route that renders a page that talks about time/sun *must* compute `sun_ctx` and pass it to the template.
2. `helpers.py:build_pre_sunset_prediction` re-computes a SunContext to grade `verdict.level` — **info** at sunset/dusk, **danger** only when SOC actually low.
3. `smart_engine.py:_sun_phase_guidance` consumes the ctx — never the boolean `is_day` alone.
4. `main.py:_load_suggestion_mode` consults `ctx.phase` to choose `'day'` vs `'night'` mode (no hardcoded 9 AM cutoff).
5. The `/api/live` endpoint includes a `sun_phase` block in its JSON response so the client poller can update the weather widget's icon/label without reverting to raw API data.

---

## 16. Live update pattern

Two layers:

**Server-side render**: route writes `weather_now_icon`, `weather_now_label`, `weather_advice_text` directly into the template (so first paint is correct).

**Client poll**: `/api/live` returns a `sun_phase` object. The page's `setBind('weather.icon', sun_phase.weather_icon || w.icon)` reads from `sun_phase` *first*, falling back to the raw weather only if absent.

```js
var sph = p.sun_phase || {};
var phaseIcon  = sph.weather_icon  || (w && w.icon)         || '';
var phaseLabel = sph.weather_label || (w && w.condition_ar) || '';
setBind('weather.icon', phaseIcon);
setBind('weather.cond', phaseLabel);
```

This is the **single most important rule for live data**: never let the JS poller overwrite SunContext-aware values with raw API values. If you skip this step, the page silently rolls back to wrong-time-of-day icons within seconds of loading.

---

## 17. AJAX navigation pattern (for paginated pages)

Used on `/statistics` and `/reports`. The page wraps content in `<div id="xx-content">…</div>`, intercepts form submits + arrow clicks, fetches with `X-Requested-With: XMLHttpRequest`, parses the response, and swaps `#xx-content`.

```js
function xxNavigate(url) {
  if (busy) return;
  busy = true;
  var oldEl = document.getElementById('xx-content');
  if (oldEl) oldEl.style.opacity = '0.35';
  fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(r => r.text())
    .then(html => {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var newEl = doc.getElementById('xx-content');
      var curEl = document.getElementById('xx-content');
      if (newEl && curEl) {
        destroyCharts();
        curEl.replaceWith(newEl);
        history.pushState({ xxUrl: url }, '', url);
        initCharts();
        setupNav();
      }
    })
    .catch(() => { window.location.href = url; })
    .finally(() => { busy = false; });
}
```

Auto-refresh every 30 s only when:
- The page's `data-date` matches `today` (`new Date().toISOString().slice(0,10)`).
- `document.hidden` is false.

When auto-refreshing, dim the metric values via `.is-updating` class so the user sees a subtle flicker rather than empty content.

---

## 18. Spacing checklist


> ⚠️ **Top-level page section spacing is governed by §2's mandatory rule** — explicit `margin-block-start: 26px !important` on each direct child of `.xx-page`, not by flex `gap`. Don't reintroduce `margin-bottom` here. The list below applies to *internal* spacing inside cards/panels.

| Element | Spacing |
|---|---|
| Inter-section gap (page level) | `24 px` (set on `.xx-page` flex gap) |
| Inter-card gap (within a row) | `18 px` |
| Card padding (top-level cards) | `18 20 20` (top, sides, bottom) |
| Card head padding | `18 20 4` |
| Mini-stat padding | `.85rem .95rem` |
| Drawer head | `20 22 16` |
| Drawer body | `18 22` |
| Hero | `clamp(22,3vw,34) clamp(20,3vw,38)` |
| Form field padding | `.55rem .8rem` |

**Rule of thumb: never put a `margin-top` on a top-level section. Use the page's `gap` for inter-section air. Margins only inside cards.**

---

## 19. Typography scale

| Use | Size | Weight | Notes |
|---|---|---|---|
| Hero h1 | `clamp(1.55rem, 2.6vw, 2.05rem)` | 950 | text-shadow on dark hero |
| Card h3 | `1.02–1.15rem` | 950 | leading emoji |
| Stat value | `1.85–2rem` | 950 | tabular-nums |
| Body text | `.88–.95rem` | 600–700 | line-height 1.5–1.6 |
| Labels | `.7–.78rem` | 800–900 | uppercase + letter-spacing |
| Pills/chips | `.7–.78rem` | 800–900 | |
| Small/caption | `.66–.72rem` | 700 | |

Two principles:
- **Numbers and labels are always heavier than body** (weight 800+).
- **Tabular-nums everywhere a number lives in a column** so things line up.

Font family: `'Cairo','Inter',system-ui,sans-serif` — Cairo first because the product is Arabic-first.

---

## 20. RTL handling

The product is Arabic-first. Every layout must work in `dir="rtl"`.

**Logical properties (mandatory):**
- Use `inset-inline-start/end` instead of `left/right` everywhere.
- Use `margin-inline-start` / `padding-inline-start` instead of physical equivalents.
- For flex layouts the order automatically flips — don't force `flex-direction: row-reverse`.
- For drawers: `[dir=rtl] .xx-drawer-panel { left: 0 }` and `transform: translateX(-110%)`.
- Don't reverse number direction — keep numbers LTR via `direction: ltr` on numeric cells.

**Form input direction (auth pages, settings, anywhere users type):**
Inputs should follow page direction so the cursor starts at the visual start of the field:
```jinja2
<input ... dir="{{ 'ltr' if is_en else 'rtl' }}">
```
Don't hard-code `dir="ltr"` — it forces the cursor to the left even in Arabic. The bidi algorithm handles embedded Latin text inside an RTL field correctly on its own.

**Bidirectional Latin tokens inside Arabic strings:**
When an Arabic sentence contains a Latin token followed by punctuation (e.g. `SMS، تيليجرام`), the comma can render on the wrong side. Wrap the Latin token in `<bdi>`:
```jinja2
{{ ('SMS, Telegram, in-app' if is_en else '<bdi>SMS</bdi>، تيليجرام، داخل التطبيق') | safe }}
```

**Directional arrows (back links, "next" buttons):**
Don't bake the arrow into the same string as the label — bidi will misplace it. Split into spans and pick the arrow per language:
```html
<a class="xx-back-link" href="...">
  <span class="xx-back-arrow" aria-hidden="true">{{ '←' if is_en else '→' }}</span>
  <span>{{ 'Back to home' if is_en else 'العودة للرئيسية' }}</span>
</a>
```
- LTR: `←` (back points left, away from forward reading)
- RTL: `→` (back points right, away from RTL reading flow)

Hover micro-animation matches the direction:
```css
.xx-back-link:hover .xx-back-arrow{
  transform: translateX({{ '-3px' if is_en else '3px' }})
}
```

**Submit / CTA buttons with directional arrows:**
Same pattern — separate `.xx-submit-arrow` span with `{{ '→' if is_en else '←' }}` and a hover translate of `±4px`. Never put both an emoji *and* an arrow on the same button — pick one (or use an SVG icon for security/lock indicators instead of an emoji).

---

## 21. Code-level conventions

1. **Class prefix per page**: `dm-` (devices), `st-` (stats), `rp-` (reports), `lv-` (live), `d40-` (dashboard). All variables use the same prefix.
2. **CSS variable scoping**: declared on `.xx-page` so they don't leak globally.
3. **Inline `<style>` block** lives at the top of the template, right after the Jinja `{% block body %}`. Don't fragment styles into multiple CSS files for new pages — one file per page keeps the design system additive.
4. **Server-side fields**: when you compute a phase-aware value in the route, pass it via 3 specific names — `weather_now_icon`, `weather_now_label`, `weather_advice_text`. The template falls back to raw weather only if these are missing.
5. **Templates extend `base.html`** and put everything inside `{% block body %}`. The sidebar is `{% include '_sidebar.html' %}`.
6. **Jinja `{% set %}` blocks at the top of `.xx-metrics`** for any percent-bar math. Don't inline complex math in attributes.
7. **Defensive coalescing**: every Jinja value goes through `or` defaults, e.g. `{{ stats.solar_generated_kwh or 0 }}`.

---

## 22. Boilerplate template (copy-paste starter)

A new page that follows this system looks like:

```jinja2
{% extends 'base.html' %}
{% block body %}
{% set is_en = (ui_lang or 'ar') == 'en' %}
<style>
.np-page{
  --np-ink:#0b1220; --np-ink-soft:#1f2a44; --np-muted:#4a5b78;
  --np-line:#e3eaf6; --np-line-strong:#bcc8df;
  --np-card:#fff; --np-bg:#eef3fb;
  --np-amber:#f59e0b; --np-emerald:#10b981; --np-sky:#2563eb;
  --np-rose:#f43f5e; --np-violet:#6d3aff;
  --np-shadow-sm:0 6px 18px rgba(15,23,42,.06);
  --np-shadow:0 22px 60px rgba(15,23,42,.09);
  --np-radius:22px; --np-radius-lg:30px; --np-radius-xl:38px;
  background:
    radial-gradient(1100px 480px at 12% -10%,rgba(109,58,255,.10),transparent 55%),
    radial-gradient(900px 420px at 92% -4%,rgba(245,158,11,.10),transparent 55%),
    linear-gradient(180deg,#f5f8ff 0%,#eef3fb 60%,#e8eef9 100%);
  min-height:100vh;padding:22px clamp(14px,2.4vw,28px) 56px;
  font-family:'Cairo','Inter',system-ui,sans-serif;color:var(--np-ink);
  display:flex;flex-direction:column;
}
/* MANDATORY — survives global overrides; see §2 */
.np-page > section,
.np-page > header { margin-block-start:26px !important }
.np-page > :first-child { margin-block-start:0 !important }
.np-hero{ /* … paste hero from §3 … */ }
.np-stats{ /* … paste from §5 … */ }
.np-card{ /* … paste from §7 … */ }
</style>

<div class="app-shell has-layout-sidebar sidebar-collapsed" id="appShell">
  {% include '_sidebar.html' %}
  <main class="app-main content-area">
    <div class="np-page" dir="{{ 'ltr' if is_en else 'rtl' }}">

      <section class="np-hero">
        <div class="np-hero-grid">
          <div class="np-hero-text">
            <span class="np-eyebrow"><span class="np-pulse"></span>EYEBROW</span>
            <h1>Page Title</h1>
            <p>Page description.</p>
            <div class="np-hero-meta">
              <span class="np-hero-meta-item">📅 <b>Today</b></span>
            </div>
          </div>
          <div class="np-hero-actions">
            <button class="np-export-btn pdf">Primary CTA</button>
          </div>
        </div>
      </section>

      <section class="np-stats">
        <article class="np-stat amber">…</article>
        <article class="np-stat emerald">…</article>
        <article class="np-stat sky">…</article>
        <article class="np-stat violet">…</article>
      </section>

      <div class="np-section-head">
        <div><h2><span class="np-section-icon">📋</span>Section title</h2><small>sub</small></div>
      </div>

      <div class="np-card">
        <div class="np-card-head"><div><h3>📈 Card</h3><small>sub</small></div></div>
        <div class="np-chart-wrap">…</div>
      </div>

    </div>
  </main>
</div>
{% endblock %}
```

---

## 23. PDF rendering (when applicable)

Use `reportlab.pdfgen.canvas` directly — not Platypus — for pages that want the same visual identity. Mirror the dashboard color palette exactly. Required:

- Page background: `#f5f8ff` + soft circles (violet `α=.05`, amber `α=.05`, emerald `α=.04`).
- Top accent strip: half sky `#60a5fa` + half amber `#fbbf24`.
- Hero band: solid `#3aa7ff` rounded rect, white text, gold "تحليل الطاقة" pill.
- Cards: white with 0.6 px `#e3eaf6` border, 4 px colored top accent strip.
- Table: header `#f5f9ff`, alternating rows `#fff` / `#f8fbff`, period column in sky-blue.
- Always preserve the Arabic-shaping pipeline: `ar(text) → arabic_reshaper.reshape → bidi.get_display`. Never bypass it.

---

## 24. Anti-patterns (don't do these)

| ❌ Don't | ✅ Do |
|---|---|
| Hardcode `if hour > 9` to detect daytime | Use `ctx.is_day_for_production` |
| Set `is_day = solar_power > 50` | Use SunContext phase set |
| Show `☀️` at 7 PM because the API said `"Clear"` | Use `ctx.weather_icon_for(...)` |
| Concatenate `sun_message + history_warning` | Keep them on separate lines (`summary` vs `detail`) |
| Print "بحذر" in both `status_label` and `confidence_message` | Decouple — confidence message lives on its own badge |
| Use dark navy panels (legacy) | White cards on the soft sky-blue gradient |
| Use `margin-top` between sections | Use `gap` on the parent flex container |
| Use raw Bootstrap `.btn` styles | Use the `xx-export-btn`/`xx-action-btn` family |
| Put units inside the value span | Wrap units in a separate `.xx-unit` span at 0.85 rem, weight 800, muted |
| Style emoji as `font-size: 2rem` floating in text | Wrap in a 46 × 46 px rounded box with the accent-bg color |
| Make tables with grey borders | `#f5f9ff` header background + `#e3eaf6` borders, hover row `#f8fbff` |

---

## 25. Quick-reference cheat sheet

```
RADII:        22 / 30 / 38 px        (small / large / hero)
SHADOWS:      .06α small / .09α big / .14α hero
GAPS:         24 page / 18 cards / 12 nav-bar / .65 inside-card
BUTTONS:      pill 14 px radius, weight 900, padding .6 1.05 rem
HERO BG:      linear-gradient(135deg,#0e3b86 0%,#3aa7ff 50%,#ffd66e 100%)
PRIMARY CTA:  linear-gradient(135deg,#ffcf4d,#f59e0b)  shadow .28α
PRIMARY TXT:  #0b1531 (deep navy on amber CTAs)
LIVE CHIP:    linear-gradient(135deg,#10b981,#34d399)  text #04221b
LINES:        #e3eaf6  HOVER LINES: #bcc8df
MUTED TEXT:   #4a5b78 (~6.3:1 on white, AA pass)
PAGE BG:      sky+amber+violet halos on  #f5f8ff → #eef3fb → #e8eef9
PHASE ICONS:  🌙 night/dusk · 🌅 dawn · 🌄 sunrise · 🌤️ morning · ☀️ noon · 🌞 afternoon · 🌇 sunset
```

---

> **Final note:** every choice in this document was made deliberately. If something feels off when you build a new page against these rules, the answer is almost always *"more breathing room"* — bump a gap from 18 to 24, a padding from 16 to 20, a font from 700 to 800. The system is calibrated to feel airy and legible at the expense of density. Trust it.

---

## 26. Auth pages (login, register) — split-stage hero pattern

Authentication pages use a **split-stage layout**: a tall white card with a gradient `showcase` panel on one side and a `form` panel on the other. Both pages must feel identical — same gradient, same brand block, same eyebrow → title → tagline → feature grid → stats card rhythm.

### 26.1 Stage shell

```css
.xx-stage{
  width:100%; max-width:1180px;
  background:#fff; border:1px solid var(--xx-line);
  border-radius:32px; overflow:hidden;
  box-shadow:0 38px 90px rgba(15,23,42,.14);
  display:grid; grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);
  min-height:620px;
}
@media (max-width:980px){ .xx-stage{grid-template-columns:1fr} }
```

### 26.2 Showcase panel (the gradient side)

```css
.xx-showcase{
  position:relative;
  background:linear-gradient(135deg,#0e3b86 0%,#3aa7ff 50%,#ffd66e 100%);
  color:#fff; padding:clamp(28px,3vw,40px);
  display:flex; flex-direction:column; gap:20px;
  isolation:isolate; overflow:hidden;
}
.xx-showcase::before{
  content:""; position:absolute; inset:0; z-index:0; pointer-events:none;
  background:
    radial-gradient(420px 240px at 12% 18%, rgba(255,255,255,.18), transparent 60%),
    radial-gradient(380px 220px at 88% 80%, rgba( 11, 23, 67,.25), transparent 60%);
}
.xx-showcase>*{ position:relative; z-index:1 }
@media (max-width:980px){ .xx-showcase{display:none} }
```

### 26.3 Hero rhythm — fixed margins, NOT `space-between`

This is the rule that took the longest to get right and is non-obvious:

> **Login uses `justify-content:space-between` because its form fits in 620 px. Register's form is ~1200 px tall, so `space-between` over-distributes and tears the sections apart. The fix: drop `space-between` everywhere and use *fixed* margins between the major sections so the rhythm stays identical regardless of form height.**

```css
.xx-showcase{ justify-content:flex-start }
.xx-showcase > .xx-brand        { margin-bottom:80px }  /* gap before content */
.xx-showcase > .xx-showcase-body{ margin-bottom:60px }  /* gap before stats   */
```

With the existing `gap:20px`, the visual gaps become 100 px (brand → body) and 80 px (body → stats), matching login's natural distribution. Empty gradient below the stats card is intentional — the gradient fills the rest.

### 26.4 Showcase children

| Block | Class | Purpose |
|---|---|---|
| Brand | `.xx-brand` | Logo mark + site name + subtitle |
| Body  | `.xx-showcase-body` | Eyebrow pill + h1 + tagline + 2×2 feature grid |
| Stats | `.xx-stats` | 3-column white-translucent card at the bottom |

```css
.xx-showcase-body{ display:flex; flex-direction:column; gap:1rem }
.xx-feature-grid{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
                  gap:.6rem; margin-top:.4rem }
.xx-stats{
  display:grid; grid-template-columns:repeat(3,1fr); gap:.6rem;
  background:rgba(255,255,255,.92); border-radius:14px; padding:.85rem;
  box-shadow:0 6px 14px rgba(11,21,49,.10);
}
.xx-stat{ display:flex; flex-direction:column; align-items:center; text-align:center }
.xx-stat strong{ font-size:1.05rem; font-weight:950; color:var(--xx-ink);
                 font-variant-numeric:tabular-nums; line-height:1.2 }
.xx-stat small { font-size:.7rem;  color:var(--xx-muted); font-weight:700; margin-top:2px }
```

### 26.5 Form fields (input pattern)

```css
.xx-field-input{
  position:relative; display:flex; align-items:center;
  background:#fff; border:1px solid var(--xx-line-strong); border-radius:11px;
  transition:border-color .15s, box-shadow .15s;
  padding-inline-start:38px; padding-inline-end:6px;
}
.xx-field-input:has(.xx-toggle-pw){ padding-inline-end:4px }
.xx-field-input:focus-within{ border-color:var(--xx-amber);
                              box-shadow:0 0 0 3px rgba(245,158,11,.18) }
.xx-field-input.error      { border-color:var(--xx-rose);
                              box-shadow:0 0 0 3px rgba(244,63,94,.18) }
.xx-field-icon{
  position:absolute; inset-inline-start:12px; top:50%; transform:translateY(-50%);
  color:var(--xx-muted);
}
```

The leading icon uses `inset-inline-start:12px` (logical) so it lands on the **right** in RTL and the **left** in LTR automatically. No `[dir=rtl]` overrides needed.

The trailing eye toggle gets `flex-shrink:0; margin-inline-start:4px` and a `:focus-visible` outline (2 px amber, 2 px offset).

### 26.6 Single language toggle

Auth pages use **only** the global `.xx-lang-toggle` pill (fixed top-right corner). Don't put a second `عربي / English` toggle inside the form header — it duplicates an action that already lives in a known location and steals attention from the form.

### 26.7 Section divider ("or continue with")

Don't position the lines absolutely — flexbox is simpler and adapts:
```css
.xx-divider{
  display:flex; align-items:center; gap:.75rem;
  font-size:.74rem; color:var(--xx-muted); font-weight:800;
  text-transform:uppercase; letter-spacing:.4px; margin:.4rem 0;
}
.xx-divider::before, .xx-divider::after{
  content:""; flex:1; height:1px; background:var(--xx-line-strong);
}
```

### 26.8 Submit button anatomy

Three children, in this order: SVG security icon → label → directional arrow. No emoji.
```html
<button class="xx-submit" type="submit">
  <svg class="xx-submit-icon" .../>     <!-- lock or shield SVG -->
  <span>Sign in securely</span>
  <span class="xx-submit-arrow" aria-hidden="true">→</span>  <!-- ← in RTL -->
</button>
```
The arrow lives at `opacity:.85` baseline and animates to `opacity:1; translateX(±4px)` on hover.


---

## 27. Unified Hero (.hu-* shared classes)

> **As of v95**, every page hero uses the same shared `.hu-*` classes loaded from `static/css/unified_hero_v1.css` (auto-included in `base.html`). No more per-page hero CSS duplication.

### Markup pattern

```html
<header class="hu-hero">
  <div class="hu-hero-grid">
    <div class="hu-hero-text">
      <span class="hu-eyebrow">
        <svg .../>{{ eyebrow_label }}
      </span>
      <h1 class="hu-h1">{{ page_title }}</h1>
      <p class="hu-tagline">{{ page_description }}</p>
      <!-- optional meta pills -->
      <div class="hu-hero-meta">
        <span class="hu-meta-pill ok">🟢 <b>4</b>/4 healthy</span>
        <span class="hu-meta-pill warn">⚠️ <b>2</b> open</span>
      </div>
    </div>
    <div class="hu-hero-cta">
      <a class="hu-btn hu-btn-ghost" href="...">Secondary</a>
      <a class="hu-btn hu-btn-primary" href="...">+ Primary action</a>
    </div>
  </div>
</header>
```

### Locked-in visual contract

| Property | Value |
|---|---|
| `border-radius` | `30px` |
| `padding` | `32px clamp(28px,3.2vw,44px) 36px` |
| Gradient | `linear-gradient(135deg, #7fb1e6, #a9c8ec, #d6dfee, #f1e6d6, #f8d7b6)` |
| Title color | `#1d4ed8` (saturated blue) |
| Eyebrow color | `#1d4ed8` (white pill bg) |
| Tagline color | `#334155` |
| Decorations | dotted top-start + SVG wave bottom |
| Tagline accent bar | vertical `linear-gradient(180deg, #3aa7ff, #ffd66e)` |

### Button variants

- `.hu-btn-primary` — amber gradient, dark navy text (PRIMARY CTA)
- `.hu-btn-ghost` — white bg, ink-soft text (SECONDARY)
- `.hu-btn-success` — emerald gradient
- `.hu-btn-danger` — rose gradient
- All variants resist global `<a>` link styles via `body main.app-main .hu-btn-*` selectors with `!important`.

### Migration checklist when porting an old hero

1. Replace `<header class="xx-hero">` with `<header class="hu-hero xx-hero">` (keep legacy class only if other layout depends on it).
2. Replace `<h1>` with `<h1 class="hu-h1">`.
3. Replace tagline `<p>` with `<p class="hu-tagline">`.
4. Replace `<span class="xx-eyebrow">` with `<span class="hu-eyebrow">` and add an inline SVG icon.
5. Replace CTA `<a class="xx-btn xx-btn-primary">` with `<a class="hu-btn hu-btn-primary">`.
6. Remove the page-scoped CSS for hero/eyebrow/tagline/buttons — they're handled globally now.

### When NOT to migrate

The unified hero applies to **admin & internal command pages**. Public-facing landing/marketing pages may keep custom heroes if they need a different gradient or layout. Notification center's previously-dark hero is now unified per the latest spec.
