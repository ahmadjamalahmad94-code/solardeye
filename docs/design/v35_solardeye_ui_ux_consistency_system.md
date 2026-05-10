# SolarDeye — UI / UX Consistency System (v35)

> **Status.** This is the canonical UI/UX reference for SolarDeye. It is descriptive of the system that has actually emerged in the codebase across v32–v33; it is **not** a redesign brief. Future agents (Codex, Claude, human contributors, the planned Android client) must read this before touching admin or subscriber UI.
>
> **Hard locks.** Flow Graph internals are byte-locked. Scheduler, notification dispatch/dedup, message generator, reports/PDF backend, DB schema, and migrations are not in scope for UI work. Anything that requires touching those is a separate, scoped task.

---

## 1. Product design philosophy

### 1.1 What SolarDeye visually is

SolarDeye is an **Arabic-RTL-first SaaS console for solar/energy operators**. The product currently lives in two parallel surfaces:

- **Admin console** (`/admin/...`): operator-side. Handles users, devices, plans, support, finance, system logs, integrations, reviews, backups.
- **Subscriber portal** (`/dashboard`, `/devices/manage`, `/loads`, `/notifications`, `/reports`, `/statistics`, `/live-data`, `/account/profile`, etc.): end-user energy management.

Both surfaces share one design system. The same `prof-*` token system styles `admin_me.html` (admin self-profile) and `account_profile.html` (subscriber profile). The same `_sidebar.html` partial branches on `g.is_admin` rather than rendering two unrelated sidebars. The same `_clock_weather_bar.html` partial sits above admin and subscriber dashboards.

### 1.2 What it visually should feel like

- **Calm SaaS, not playful.** Soft tints, soft borders, soft shadows. Indigo / violet primary (`#4338ca`, `#6366f1`, `#7c3aed`), slate neutrals (`#0f172a` ink, `#475569` muted, `#cbd5e1` line, `#f8fafc` soft bg).
- **Dense-but-clean.** Cards are tight, rows are slim, helper text is one short sentence, padding is small. Empty space is a tool, not a default.
- **Glassy, not flat.** Soft inset highlights (`inset 0 1px 0 rgba(255,255,255,.55)`), faint top-edge gradients, calm `backdrop-filter` where supported. The notifications page tone-tinted cards are the canonical reference.
- **Honest.** Labels never lie about what something does. If settings are global, the page says so. If a value is mock, the page says so. If a feature is a future phase, the page says so. See §10 anti-pattern "fake controls."

### 1.3 What makes it premium vs. messy

**Premium signals (keep):**
- Consistent control height (42 px on standard inputs/selects, 36–40 px on compact rows, 32 × 32 px on icon toggles).
- Single CSS rule changing a section's tone, not twelve different stylesheets.
- One helper sentence per field, contextual.
- Numeric values render with `font-variant-numeric: tabular-nums`.
- LTR values inside RTL flow are wrapped explicitly (`<b dir="ltr">DEYE</b>`).
- Section badges (icon, summary chip, accent strip) inherit the section's tone palette automatically.

**Messy signals (kill on sight):**
- Two helper paragraphs under the same field.
- `data-help-text` popover on a label that also has an inline `<small>`.
- A 600 × 200 hero strip for one button.
- Eight different button gradients across one page.
- A control that looks live but is `disabled` and never persists.
- A "redesign" that lives in a new CSS file alongside three older CSS files saying the same thing with different class names.

---

## 2. Layout system

### 2.1 Spacing rhythm

The base unit is **4 px**. Common values: `2, 4, 6, 8, 10, 12, 14, 16, 18, 22, 24`. Anything outside that scale is suspicious.

| Token (mental) | Value | Used for |
|---|---|---|
| micro | 2–4 px | gap inside a chip, label-to-input |
| tight | 6–8 px | grid gap inside a section, sub-row spacing |
| default | 10–14 px | grid gap between section cards, form-field grid gap |
| comfortable | 14–18 px | hero padding, section padding, sticky preview gap |
| section | 18–24 px | between major sections on a page |

`subscriber_console_v32.css`, `notifications_v33iota.css`, and `admin_user_profile.css` all sit on this scale. Don't introduce 11 px, 13 px, 17 px, 23 px.

### 2.2 Section spacing

- Adjacent `.ns-card` blocks: **14 px** vertical gap (`+ .ns-card { margin-top: 14px }`).
- Hero card → first content card: **18 px**.
- Page bottom padding: **64 px** (`.ns-page { padding-bottom: 64px }`).
- Sidebar to main content gap: handled by `app-shell` grid; do not override per-page.

### 2.3 Card padding

| Card type | Padding | Notes |
|---|---|---|
| Hero card (`.hu-hero`, `.prof-hero`) | `22px 24px` | The largest interior padding in the system. |
| Section card (`.ns-card`, `.up-pane`) | `body: ~18–22px`, `head: ~14–18px` | Header strip is tighter than body. |
| Sub-block (`.ns-tg-block`, `.ns-tm-block`) | `10–12px 12–14px` | Tonal background, no shadow. |
| Tile / chip card (`.ns-tg-card`) | `7–10px 9–12px` | Tightest. Single-line content. |

### 2.4 Grid density

The standard form grid is `.ns-grid` / `.prof-step-body`:

- **Desktop (≥ 1100 px):** `grid-template-columns: repeat(3, minmax(0, 1fr))`, gap `14px`.
- **Tablet (< 1100 px):** `repeat(2, minmax(0, 1fr))`.
- **Mobile (< 720 px):** single column.

The threshold compact-card grid is `.ns-tg-cards`: `repeat(auto-fill, minmax(150px, 1fr))`, gap `10px` → `minmax(140px, 1fr)`, gap `8px` on mobile.

**Never** declare a grid wider than 3 visible columns at typical content widths. The eye can't track 5+ form fields per row.

### 2.5 Preferred widths

- **Sidebar:** ~230 px (collapsed reduces, set in `sidebar_rebuild_v11.css`).
- **Main content:** flexes (no fixed max-width on the app shell). Hero text inside has `max-width: 760px` on its tagline `<p>` to avoid line-length issues in long Arabic.
- **Side card column** (in profile pages, `prof-side`): ~280 px sticky.

### 2.6 Empty-space handling

The default mistake is to **leave too much**. Empty space must serve a purpose:

- A breathing line between unrelated topics → 24 px is enough.
- A "this section is empty" state → use the empty-state pattern (icon + one short line + optional CTA), do not just leave a 400 px blank rectangle.
- Above a form's first field → 8 px from the step description is enough.

If a page feels "airy" the ratio is wrong. The `.ns-card-body` should be ~80% controls, ~20% breathing.

### 2.7 Desktop vs. mobile philosophy

Desktop is the source of truth for layout shape. Mobile collapses, never restructures. Concretely:

- Multi-column grids drop to two columns at 1100 px and one at 720 px.
- Side panels (preview, side cards) stop being sticky and stack below.
- Hero metas wrap to multiple chip rows, never get hidden.
- Threshold cards stay as cards, never become rows.
- The clock+weather chip variant `.cwx-header-chip` hides below 480 px (the bell + chip would overlap).

---

## 3. Typography system

### 3.1 Type stack

```css
font-family: "Cairo", system-ui, sans-serif;
```

Cairo for Arabic readability. System fallback for early paint. **Helvetica is used only inside the PDF report** for ASCII tokens that would render as boxes in the Arabic font (e.g., `DEYE`, `Asia/Hebron`); do not import it for HTML.

### 3.2 Title hierarchy

| Role | Element / class | Size | Weight | Color |
|---|---|---|---|---|
| Page H1 (hero) | `.hu-hero h1`, `.ns-hero h1` | 1.7 rem | 900 | `#0f172a` |
| Profile inner H2 | `.prof-hero-text h2` | 1.35 rem | 950 | `#0b1220` |
| Section H2 (card head) | `.ns-card-head h2` | 1.15–1.25 rem | 900 | `#0f172a` |
| Sub-block H3 | `.prof-step-side h3`, `.ns-group-title h3` | 0.92 rem | 900 | `#0f172a` |
| Section H4 | `.ns-tg-title`, `.ns-tm-title` | 0.9 rem | 900 | `#0f172a` |

### 3.3 Body / helper hierarchy

| Role | Size | Color | Weight | Notes |
|---|---|---|---|---|
| Hero tagline `<p>` | 0.95–1 rem | `#64748b` | 400–500 | line-height 1.7, max-width 760 px |
| Form input value | 0.88 rem | `#0f172a` | 400 | inside `.prof-input`, `.ns-field input` |
| Field label `<span>` | 0.78 rem | `#334155` | 800 | letter-spacing slightly tightened |
| **Helper `<small>`** | 0.72–0.76 rem | `#64748b` | 600–700 | one sentence, 8–18 words |
| Side-card row label | 0.78 rem | `#475569` | 700 | |
| Eyebrow / breadcrumb | 0.7–0.75 rem | `#4338ca` | 800 | uppercase, letter-spacing .04 em |

### 3.4 Muted text usage

Muted text exists for **secondary information that should not steal attention**: helper sentences, timestamps, "last updated", "saved at", scope notices.

- Acceptable muted tones: `#64748b`, `#475569`. Anything lighter than `#94a3b8` is too faint for body text on white.
- Muted text never carries information a user needs to act on. If it's a CTA, it's not muted.
- Muted text never repeats what the label already says (see §10 "duplicate helper text").

### 3.5 Arabic readability rules

- **Use Cairo at 600+** for all body Arabic. 400 weight Arabic on white at 0.74 rem is borderline; reserve 400 for body paragraphs of length, not for chips.
- **Line-height ≥ 1.55** for any multi-line Arabic helper. 1.7 for paragraphs.
- **Don't break Arabic words across lines.** Avoid forced narrow widths on chip text (`.prof-tag` already uses `white-space: nowrap; max-width: 100%; text-overflow: ellipsis`).
- **Don't mix Hindi-Arabic numerals with Arabic-Eastern numerals** in the same view. We currently use Western digits (`0–9`) everywhere — keep it that way.

### 3.6 RTL punctuation rules

- Comma is the regular Arabic comma `،` for Arabic prose; the ASCII `,` is used inside LTR values (e.g., `08:00,12:00`) and CSV/JSON. Don't mix.
- Em-dash `—` is fine in Arabic ("الاسم — يظهر للدعم"). Avoid `–` (en-dash) in body Arabic.
- Colons `:` are ASCII, kept on the left of values that are themselves LTR (`Asia/Hebron`, `+970`).
- Phone display canonical form: `+970 | 599043337`. The `|` is rendered via CSS `::after { content: "|" }` on `.prof-phone-display-code`, not typed in the Arabic source. This guarantees consistent spacing under any direction.

---

## 4. Form system

### 4.1 Input heights

**One number, everywhere:** `min-height: 42px; height: 42px;` for `.prof-input`, `.ns-field input`, `.ns-field select`, `.ns-window-helper input[type="time"]`, `.ns-window-helper select`, `.ns-hours-field input[type="text"]`. This is the v33-ι contract.

Smaller heights are reserved for:
- Compact log-pager buttons (32 px).
- Icon-only channel chips (32 × 32 px desktop, 30 × 30 px mobile).
- Hero pill action buttons (`.prof-hero-action` ~32–34 px total).

### 4.2 Border, radius, focus

```css
border: 1px solid #d8dee9;
border-radius: 10px;
background: #ffffff;
padding: 8px 12px;
font-size: .88rem;
box-shadow: 0 1px 2px rgba(15, 23, 42, .03);

/* Focus */
border-color: #6366f1;
box-shadow: 0 0 0 3px rgba(99, 102, 241, .14);
```

That focus ring is the system's signature and must not be replaced by browser defaults.

### 4.3 Select behavior

- Country, city, and timezone selects come from `_location_picker.html` macros (`loc.country_select`, `loc.city_select`, `loc.timezone_select`) backed by `services/location_catalog.py` and `static/js/location_picker.js`. These cascade — country change repopulates city + suggests timezone via `data-loc-*` hooks. **Do not bypass** these macros with hand-rolled `<select>`s. We've broken country/city sync three times by hand-rolling.
- Timezone select is **grouped** via `optgroup`. Don't pass `timezones_for_template()` (flat) to the macro that expects `timezones_grouped_for_template()`.
- Phone-code select uses a separate compact pattern: a narrow flag-prefixed select sitting next to the phone-number input, both LTR. Width pattern: `.prof-phone { display: flex; gap: 8px } .prof-phone-code { flex: 0 0 auto; min-width: 110px } .prof-phone-num { flex: 1 1 auto }`.

### 4.4 Prefix / phone layouts

There are **two** phone surfaces:

1. **Form (editable):** `.prof-phone` flex row inside a `.prof-field-full` label. Country code dropdown + LTR number input.
2. **Display (chip):** `.prof-tag-phone` with `.prof-phone-display-code` + `.prof-phone-display-number` and a CSS `::after` separator (`|`). Goes inside `.prof-hero-meta`.

Never render the display form as an input-shaped box in the hero. Never render the form as a flat string in chips.

### 4.5 Helper text positioning

Helper `<small>` always sits **after** the input, last child of the label:

```html
<label class="ns-field">
  <span>الفاصل الزمني</span>
  <input type="number" name="periodic_day_interval_value" />
  <small>مثلاً: 2 + ساعات = رسالة كل ساعتين داخل نافذة التشغيل.</small>
</label>
```

**Maximum one** `<small>` per field. The previous regression where `[data-field-help]::after { content: attr(...) }` rendered the helper in addition to the JS-injected `<small>` (see §10 anti-pattern) is permanently fixed in `ui_guidance_v33.css` — do not reintroduce.

### 4.6 Validation behavior

We currently rely on:
- HTML5 `required` for required fields.
- Server-side validation in the route, with `flash(category, msg)` messages rendered in the v61 toast stack.
- Inline error messages **only** for credential conflicts (e.g., "اسم المستخدم مستخدم من قبل").

Don't add custom client-side validators that contradict the server. Don't show validation errors as red borders without a message. Don't show success animations for ordinary saves — a flash toast is enough.

### 4.7 Save-button positioning philosophy

- One **primary** Save button per form, always at the bottom in `.prof-form-actions` / `.ns-actions`.
- Style: full-bleed indigo gradient pill, white text, no shadow on hover.
- The button submits the form. Don't intercept with `preventDefault()` unless you also visibly indicate the AJAX state (loading spinner, disabled state, success badge). Saved-but-page-still-shows-old-values is the most painful regression we've shipped.
- Independent section saves use `<input type="hidden" name="settings_section" value="periodic_day">` — the route reads `settings_section` and saves only that section. Don't lose this contract.

### 4.8 Dangerous patterns to avoid

- Form fields with `name=""` containing dynamic values not present in the save handler. Always check `save_notification_settings_from_form` before adding new keys.
- Select `<option>` lists shorter than the live dataset (we've shipped at least one timezone selector that was missing rows because it walked the wrong helper).
- Tying form submit to JS that depends on a global state object — when the global is null on first load, the button silently does nothing.
- Submit buttons that are styled like primary CTAs but execute test/fire-and-forget actions (e.g., "Test SMS"). Use the `.ns-btn.ghost` style for non-save actions.

---

## 5. Notification system UI

### 5.1 Page architecture

`notifications.html` is the most complex subscriber surface. Its shape (since v33-ι):

```
ns-page
├─ ns-hero               (page title + tagline + Manage-channels link)
├─ ns-summary            (4 KPI chips: Telegram / SMS / Active sections / Critical SMS)
├─ ns-device-note-v33iota (honest scope notice — global settings notice)
├─ ns-nav                (anchor jumps to sections)
├─ ns-layout
│   └─ ns-main
│       ├─ ns-card.tone-general          (01 — global toggle)
│       ├─ ns-card.tone-day              (02 — periodic day)
│       ├─ ns-card.tone-night            (03 — periodic night)
│       ├─ ns-card.tone-sunset           (04 — pre-sunset)
│       ├─ ns-card.tone-weather          (05 — weather)
│       ├─ ns-card.tone-battery          (06 — battery test)
│       ├─ ns-card.tone-load             (07 — loads)
│       ├─ ns-card.tone-report           (08 — daily report)
│       ├─ ns-card.tone-discharge        (09 — night discharge)
│       ├─ ns-card.tone-content          (MC — message content map)
│       ├─ ns-card.tone-critical         (10 — critical SMS)
│       ├─ ns-card.tone-rules            (11 — threshold channels + day-deficit + step %)
│       └─ ns-card #history              (12 — paginated log)
```

Each `.ns-card.tone-*` derives its full visual identity (background gradient, border tint, accent strip, section number badge color, summary chip color) from the `--tone-*` CSS variable system in `notifications_v33iota.css`. **Do not** introduce a new tone by writing a new card stylesheet — add a tone palette to the variable block and one new `tone-*` modifier.

### 5.2 Compact threshold routing — canonical form (v33-threshold-compact-icon-cards-final)

The `قواعد العتبات` section uses a **single legend chip + three subsection card grids of compact icon-only tiles**:

```
[ ✈ = Telegram   ✉ = SMS ]            ← single legend chip, top of section

قنوات الشحن
[ 95% ✈ ✉ ]  [ 90% ✈ ✉ ]  [ 85% ✈ ✉ ]  [ 80% ✈ ✉ ]  [ 75% ✈ ✉ ]  ...

قنوات التفريغ
...

قنوات الحمل الليلي  (note: 300W / 400W / 500W only — fixed by backend)
[ 300W ✈ ✉ ]  [ 400W ✈ ✉ ]  [ 500W ✈ ✉ ]
```

Per-card structure:
- Width: `auto-fill, minmax(150px, 1fr)` (~5–6 per row at content width).
- Padding: `8px 10px`.
- Three columns: level badge | Telegram chip | SMS chip.
- The hidden `<input type="hidden" name="charge_50" value="none|telegram|sms|both">` is the source of truth. The two checkbox-labels (`data-channel-choice="telegram"`, `data-channel-choice="sms"`) toggle and the JS in `notifications_settings_v33.js` syncs the hidden value.

**Do not regress.** The path `cards → grids → matrix table → compact icon cards` happened across multiple turns. The compact icon cards are the final shape. Each step in the ladder broke one of: spatial efficiency, label-repetition, or row-height inflation. Don't restart that journey.

### 5.3 Icon-only routing philosophy

Icon-only is acceptable **when there is a single shared legend** in scope. The `.ns-tg-legend` chip at the top of the threshold section is what makes 30+ icon toggles below it readable. If you ever add icon-only toggles outside a legend, add a legend.

Selected state:
- Telegram chip checked → `background: #4338ca` (indigo), white icon, inset border `#3730a3`.
- SMS chip checked → `background: #16a34a` (green), white icon, inset border `#15803d`.
- Off state → calm gray outline (`#94a3b8` icon on white).

### 5.4 Grouped settings layout

Every notification section card body uses the same internal rhythm:

```
toggle_field (master enable)
group_title("الإعدادات الأساسية", subtitle)
ns-grid (channel / mode / cadence / window-start / window-end / specific-hours)
group_title("محتوى الرسالة", subtitle)
ns-toggle-grid (include flags, alternating row tones)
[optional advanced <details>]
ns-actions (single Save button)
[optional ns-test-row (ghost Test button)]
```

This is the **canonical section template**. New sections (when added with backend support) should follow this exact rhythm.

### 5.5 Avoiding giant settings galleries

A "gallery" is what threshold channels were before v33-threshold-compact-icon-cards-final: a 30-item grid where each item is a 200 px wide, 60 px tall card with its own border and shadow. Symptoms:

- The page scrolls 5x what the actual data needs.
- The eye loses the relationship between cards.
- Mobile becomes a single column of giant cards and is unreadable.

The fix is the matrix or the compact-icon-card pattern (§5.2).

### 5.6 Explanation text style

Each section header has a one-line subtitle (`group_title(title, desc)`). Each field has at most one helper `<small>`. The page top has one global scope notice (`ns-device-note-v33iota`). That's the entire explanation budget. No popovers on field labels (they fight inline `<small>` — see §10).

The single permitted **popover** styling lives on:
- `.ns-card[data-help-text]` — section-level.
- Save / Test buttons — button-level.
- The live-preview aside — composite-level.

Field-level popovers are banned.

---

## 6. Dashboard system

### 6.1 Card density philosophy

The subscriber dashboard (`dashboard.html`) is a **dense single-page command center**:

```
app-shell
├─ _sidebar (collapsed by default)
└─ app-main.dashboard-v40
    ├─ _clock_weather_bar (v33-μ — profile-driven, no GPS/IP)
    ├─ _live_fleet_rail   (multi-device only; hidden for single-device users)
    ├─ Flow Graph         (LOCKED — md5 56124a8799a3bb800231d99d83f6d616)
    └─ stat / chart / next-action cards
```

Density target: a visitor with one device should see system status, current power flow, today's totals, and the next sensible action **without scrolling once on a 1080p screen**. Multi-device users get the fleet rail above the Flow Graph; the Flow Graph reflects the active device.

### 6.2 Live-data rhythm

`/live-data` is the dashboard's sibling — a focused single-device view. It shares:
- The `_device_switcher.html` partial (top-right of the main column on multi-device accounts).
- The fleet rail when 2+ devices.
- Flow Graph (locked).

Polling cadence is configured per-page in `data-live-url`. **Do not poll faster than every 15 s** — the scheduler expects calm. Don't introduce a "real-time" pulse ring that animates every 200 ms; visual noise without semantic gain.

### 6.3 How to avoid visual overload

- **One hero per page.** `.hu-hero` (admin) or `.ns-hero` (subscriber) — pick one, never both.
- **One KPI strip max.** 4 chips, not 8.
- **One graph dominant.** Flow Graph on dashboard. Statistics chart on `/statistics`. Reports on `/reports`. Don't put two large charts on one page.
- **No marquee, no auto-rotating cards, no "tip of the day" rotators.** They eat attention without earning it.

### 6.4 What should remain visually dominant

The Flow Graph is the brand-defining visual on the dashboard. All other cards must **not compete**:
- Cards above and below the Flow Graph use the `.ns-card` muted-glass style, not bright gradients.
- Status chips beside the Flow Graph are pill-sized, never card-sized.
- The fleet rail (`live_fleet_rail_v33b.css`) is a horizontal row of compact device pills, not a 200 px tall section.

### 6.5 Flow Graph protection rules

```
Locked file md5:           56124a8799a3bb800231d99d83f6d616
Locked file size:          7,970 bytes
Touchable templates:       only the wrappers that include it (e.g., dashboard.html)
Allowed wrapper changes:   adding partials *above* (clock+weather, fleet rail, scope hint)
Forbidden:                 modifying the inner SVG, the inner JS animation, the inner CSS,
                           the inner d3/data binding, the data shape it consumes
```

If a task description ever asks for "minor Flow Graph polish" the answer is **no, route it through a separate scoped task**.

### 6.6 Sidebar interaction philosophy

The sidebar (`_sidebar.html` + `sidebar_rebuild_v11.css`) is the spine of navigation:

- Two branches: `{% if g.is_admin %}` (admin items) `{% else %}` (subscriber items). They never share an item — admin's "ملفي الشخصي" links to `/admin/me`, subscriber's links to `/account/profile`.
- `nav_item(...)` macro is the only way to add an item. It expects: `(slug, ar_label, en_label, [active_endpoints], href, icon, [optional_badge])`.
- **Do not** branch a Jinja conditional on `current_app.view_functions` — Flask's `current_app` is not exposed to Jinja. We've shipped that bug; it crashes every page that includes the sidebar. Use `g`, registered template helpers, or have Python pass a context flag.
- Active state is computed by the macro from `request.endpoint in active_endpoints`. Don't hand-toggle `.active` from JS.

---

## 7. Support center system

### 7.1 Ticket / chat layout rhythm

The support center (admin and subscriber) follows a two-pane layout:

```
Inbox column (left in LTR / right in RTL)
├─ status filter chips
├─ search
└─ ticket rows                          → click to open

Conversation column (right / left)
├─ ticket header (subject, status, assignee, last reply at)
├─ message thread (newest at bottom, soft scroll)
└─ reply composer (textarea + attachments + send)
```

Dimensions: inbox column ~340 px on desktop, conversation column flexes. On tablet (< 1100 px), inbox collapses to a top strip (horizontal scroll of recent tickets) and conversation takes the full width below.

### 7.2 Empty-state handling

- **No tickets yet:** centered icon + "ابدأ بإنشاء أول رسالة" + a primary CTA. Not a 600 px blank box.
- **No reply yet on an open ticket:** the conversation pane shows the original message + a calm "ابدأ بكتابة الرد" placeholder inside the composer. Not a giant "no messages" banner.
- **All filters return zero:** the row list shows a one-line "لا توجد رسائل تطابق هذه التصفية." with a "إعادة ضبط" link.

### 7.3 Scroll behavior

- The conversation pane scrolls **inside itself**, not the whole page. The composer stays visible at the bottom. Use `overflow-y: auto` on the message thread, `position: sticky; bottom: 0` on the composer.
- Newest message scrolls into view on open. A new outgoing reply scrolls the user to it.
- The inbox column scrolls independently. Don't sync scroll between panes.

### 7.4 Sidebar / helper column behavior

If the page has a third column (helpful information, ticket metadata, related cases), it sits to the far end of the row and collapses below the conversation on tablet. Width ~280 px. Don't push the conversation narrower than ~520 px to keep this column visible.

### 7.5 Avoiding giant dead space

A recurring issue is the "new ticket" form rendering above a 400 px gap before the existing ticket list. Fix pattern:
- The new-ticket form is a **collapsed details disclosure** by default (`<details>`), expanded only when the user clicks "رسالة جديدة".
- The expanded form's height matches its content; no `min-height` overrides.
- The list immediately follows. No `margin-top: 40px` on the list.

---

## 8. Color / contrast rules

### 8.1 Palette anchors

| Role | Hex | Usage |
|---|---|---|
| Ink (primary text) | `#0f172a` | All H1–H4, all input values |
| Soft ink | `#1e293b` | Secondary headings, emphasis in helper |
| Muted | `#475569` | Field labels, side-card row labels |
| Faint muted | `#64748b` | Helper `<small>`, timestamps |
| Lighter muted (limit) | `#94a3b8` | Disabled control text only |
| Line | `#cbd5e1` / `rgba(15,23,42,.07)` | Default borders |
| Soft bg | `#f8fafc` / `#f1f5f9` | Section glass bg, alternating rows |
| Indigo primary | `#4338ca` / `#6366f1` | Primary CTAs, focus ring, eyebrow |
| Indigo soft | `#eef2ff` / `#c7d2fe` | Secondary action background |
| Violet | `#7c3aed` / `#6d28d9` | Profile hero accents, role pills |
| Slate steel | `#334155` / `#475569` | Secondary action text |
| Success | `#16a34a` / `#15803d` | SMS-on, "Active" pills, success flash |
| Warning amber | `#f59e0b` / `#b45309` | Pre-sunset tone, sms-critical accent |
| Danger | `#dc2626` / `#b91c1c` | Disabled/disabled-account, destructive |
| Cyan/teal | `#06b6d4` / `#14b8a6` | Weather / report tones |

### 8.2 Acceptable muted text strength

- On white: `#475569` is the **darkest** muted, `#64748b` is the standard, `#94a3b8` is the **lightest acceptable** for disabled/inert text only.
- On `#f8fafc`: same scale, with `#94a3b8` reserved for placeholder text only.
- **Banned on body content:** `#cbd5e1` and lighter. Those are line colors, not text colors.

### 8.3 Card / background contrast

Every card sits on the page background with at least one of:
- A 1 px border (`rgba(15,23,42,.07)`+).
- A soft tonal background distinguishable from the page (the `.ns-card.tone-*` system).
- A soft shadow (`0 1px 2px + 0 4px 18px rgba(15,23,42,.04)`).

A card with no border, no tint, and no shadow on a near-white page is invisible; we've shipped that.

### 8.4 Border softness

Always **rounded**: 10 px on inputs and small cards, 12 px on form-step cards and side-cards, 14 px on hero/notice strips, 16 px on top-level glass cards. **Never** sharp corners except inside tables (where the wrapping container provides the radius).

Borders are **always tinted to their context**:
- Default: `rgba(15,23,42,.07)` neutral slate.
- Tonal cards: `rgba(<tone-color>,.20–.25)`.
- Hover: `rgba(99,102,241,.25–.35)` indigo accent.
- Focus: `#6366f1`.

### 8.5 Button contrast

| Button class | Background | Text | Border | Used for |
|---|---|---|---|---|
| `.prof-btn-save`, `.ns-btn.primary` | indigo gradient `#4338ca → #4f46e5` | `#fff` | none | save, submit |
| `.ns-btn.ghost` | white | `#334155` | `#cbd5e1` | test, secondary |
| `.prof-hero-action` | `#eef2ff` | `#3730a3` | `#c7d2fe` | inline mini actions (avatar) |
| `.prof-hero-action.prof-hero-action-clear` | `#f1f5f9` | `#475569` | `#cbd5e1` | destructive-soft (remove) |
| `.ns-channel-chip.telegram` (on) | `#4338ca` | `#fff` | `#3730a3` | Telegram routing on |
| `.ns-channel-chip.sms` (on) | `#16a34a` | `#fff` | `#15803d` | SMS routing on |

Disabled buttons get `opacity: .45; cursor: not-allowed;`. **Never** use a different color hue to indicate disabled.

### 8.6 Danger / warning / success usage

- **Success flash:** green-on-mint, used for save confirmations only.
- **Warning flash:** amber-on-cream, used for "your settings are partially saved", "test mode", "preview only" notices.
- **Danger flash:** red-on-rose, used for failed save, conflict, destructive confirmation. Never used for "almost done" or "be careful" — that's warning.
- **Disabled state on inputs/selects** is always neutral slate, never red.

### 8.7 Currently faint or risky

(Items currently borderline. Do not make them lighter, and prefer to nudge them darker on the next refresh.)

- `.ns-summary-line` summary chip text on tone-day (sky) at 0.78 rem — borderline against the tone.
- `.cwx-weather-text` weather chip text in `.cwx-header-chip` at 0.74 rem on rgba(255,255,255,.92) — borderline on the dashboard with the Flow Graph backdrop.
- `.prof-tz-hint` and similar `<small>` hints at 0.74 rem — they're at the bottom of our acceptable size scale; don't shrink them.

---

## 9. Mobile adaptation philosophy

### 9.1 What collapses

- 3-column form grids → 2 columns at 1100 px → 1 column at 720 px.
- 2-pane support layout → stacked with inbox above conversation.
- Sticky preview pane → static, below settings.
- 4-chip KPI strip → 2 × 2.
- Sidebar → hamburger / off-canvas (handled by `sidebar_rebuild_v11.js`).

### 9.2 What wraps

- `.prof-hero-meta` chip row.
- `.ns-summary` chip strip.
- `.ns-tg-legend` legend chip.
- `.ns-tg-cards` (the `auto-fill, minmax(140px, 1fr)` does the work).

### 9.3 What should never overflow

- Tables. Wrap them in a `.table-responsive` scroll container if they truly need it (rare; most are convertible to card lists).
- The threshold matrix (now compact icon cards — already wrapping-safe).
- The Flow Graph (its viewBox handles its own scaling — don't override).
- Long Arabic words inside chips. `.prof-tag` already uses `text-overflow: ellipsis`.

### 9.4 Preferred mobile density

Mobile is **denser** than desktop, not airier. Smaller chip padding, slightly smaller fonts (`-0.04 rem` scale), 8 px gaps instead of 14 px, single-column flow. Don't introduce large illustrations or marketing-style hero blocks for mobile users.

### 9.5 Future Android compatibility notes

The planned Android client should consume the same routes the web does (or a `/api/v1/...` endpoint set already partially built). Visual alignment notes:

- The compact icon-card pattern translates directly to a RecyclerView with a 3-column grid.
- The `.prof-hero-avatar-block` matches Material's CircularImageView + trailing actions.
- Form helpers map to TextInputLayout `helperText`.
- The notification tone-tinted cards map to MaterialCardView with surfaceTint variants.
- Stick to the same color tokens listed in §8.1; wrap them as Android theme colors.

Anti-pattern for Android: rebuilding the visual language from scratch. Reuse this token set; tweak the corner radii and elevation scales to match Material 3.

---

## 10. Anti-patterns (canonical, all observed in this codebase)

These are the recurring failure modes with the file/line/turn they appeared in. Each is tagged with the canonical fix.

### 10.1 Duplicated helper text (CSS pseudo-element + DOM injection)

**Symptom:** every field with `data-field-help` shows its helper sentence twice, once "darker" (pseudo-element) and once "muted gray" (DOM).
**Source:** `app/static/css/ui_guidance_v33.css` had `[data-field-help]::after { content: attr(data-field-help) }` in addition to `ui_guidance_v33.js::ensureInlineHelp` injecting a `<small class="ui-field-help">`.
**Fix (locked):** the `::after` rule is removed; only the JS-injected `<small>` exists. Do not reintroduce `attr(data-field-help)` rendering anywhere.

### 10.2 Stacked CSS systems

**Symptom:** the page imports `style.css`, `unified_theme_v1.css`, `subscriber_v4.css`, `subscriber_console_v32.css`, plus `notifications_settings_v33.css`, plus `notifications_v33iota.css`, and three of them define `.ns-card` differently.
**Why:** every "redesign turn" added a new stylesheet without removing the previous one.
**Rule:** when the next refresh ships, the old stylesheet must be **deleted** or fully refactored — not coexist. If coexistence is needed, the new layer must scope all its rules under a wrapper class (`.ns-card-v33iota` etc.).

### 10.3 Giant empty space

**Symptom:** a 400 px blank rectangle above the support center's ticket form, or a hero strip that takes 30% of vertical space for one button.
**Rule:** vertical space must be earned. Use the empty-state pattern (icon + line + CTA), not raw padding.

### 10.4 Fake controls

**Symptom:** a `<input type="number" disabled value="1000">` next to "حد ليلي مخصص — قيد التطوير" that doesn't save anywhere.
**Source:** the `.ns-night-custom-concept` block (now removed).
**Rule:** if a control doesn't persist to a real backend field today, it doesn't render today. Replace with a one-line note describing the deferred phase (e.g., "حدود الحمل الليلي الحالية ثابتة حسب النظام، وسيتم دعم الحدود المخصصة لاحقًا.").

### 10.5 Broken save buttons due to `preventDefault`

**Symptom:** form submit attaches a JS handler that calls `event.preventDefault()` to do AJAX, the AJAX path is null/broken, and the submit silently does nothing.
**Rule:** if you intercept the form, you **must**: (a) show a loading state, (b) handle the success and error paths, (c) call `form.submit()` as a fallback if the JS path fails. Better: don't intercept; let the browser submit and use the existing flash-toast pattern.

### 10.6 Huge cards for tiny controls

**Symptom:** a 220 × 80 px card with a 32 px chip inside.
**Rule:** card padding scales with content. A pair of icon chips lives in a tile with `padding: 8px 10px`, not in a card-of-cards.

### 10.7 Dropdown abuse

**Symptom:** a select with three options (`telegram / sms / both / none`) used 30 times in a row to route channels. Same pattern with mode/cadence pairs hidden behind selects.
**Rule:** if there are ≤ 4 options and a clear default, show them as toggle chips. If there's a scale (interval value), show a number input. Selects are for ≥ 5 options or genuinely-flat enumerations.

### 10.8 Inconsistent form heights

**Symptom:** text input is 38 px, select is 42 px, time input is 36 px, the row looks broken.
**Rule:** §4.1 — 42 px everywhere on standard form controls. The override layer in `notifications_v33iota.css` enforces this with `!important` because legacy CSS layers fight us. Don't add new overrides at other heights.

### 10.9 Mixed old/new components

**Symptom:** the page uses `.ns-card` (new) and `.subscriber-card` (legacy) on the same page; they don't share radius/border/shadow; the page looks half-finished.
**Rule:** when migrating a page, migrate it whole. Don't leave one card on the old class.

### 10.10 Unreadable muted text

**Symptom:** `<small style="color:#cbd5e1">` on white. Invisible.
**Rule:** §3.4. `#94a3b8` is the floor. Anything lighter is a border, not a text.

### 10.11 Random margins

**Symptom:** `style="margin-top: 17px;"` inline somewhere.
**Rule:** §2.1. The 4 px scale is `2, 4, 6, 8, 10, 12, 14, 16, 18, 22, 24`. Inline styles for spacing are banned in templates; if you need it, name it in CSS.

### 10.12 Oversized hero sections

**Symptom:** `.hu-hero` at 280 px tall holding a 32 px-tall H1, a single chip, and three lines of marketing prose.
**Rule:** the hero is informational, not promotional. 22–24 px padding, 1.7 rem H1, one tagline ≤ 760 px wide, ≤ 5 meta chips. If you need more info, it's a section card, not a hero.

### 10.13 Uncontrolled global CSS

**Symptom:** a new file declares `.btn { background: ... }` with no scoping; every Bootstrap button on the page changes.
**Rule:** all SolarDeye styles are scoped under a system prefix (`prof-*`, `ns-*`, `cwx-*`, `pcwx-*`, `sd-*`, `up-*`, `hu-*`, `ad-*`, `lhx-*`). New rules adopt one of these or introduce a new prefix; never bare element selectors like `button`, `input`, `select`, `a`.

### 10.14 Fake per-device settings without backend support

**Symptom:** a UI banner claims "هذه الإعدادات تطبق على الجهاز المحدد فقط" while the underlying `Setting` table has no `device_id` column.
**Source:** would have been the v33-ζ task if not caught.
**Rule:** UI never lies about persistence. If the schema is global, the page says global. The deferred phase note is honest; a fake claim is not. The full deferred plan lives as `v33-κ-device-notification-settings` in the report from that turn — don't restart it as a UI-only fix.

### 10.15 Duplicate avatar buttons / leftover controls

**Symptom:** the avatar shows Change/Remove buttons inside the hero (new) **and** at the bottom of the page (old) — both wired to upload, both visible.
**Source:** the v33-ε-3 → v33-profile-hero-avatar-actions-final-polish migration.
**Rule:** when relocating a control, **delete the old block in the same commit**. Don't leave hidden duplicates "for fallback."

### 10.16 Bidi rendering of LTR values inside Arabic font

**Symptom:** "DEYE" and "Asia/Hebron" render as empty squares in PDF.
**Source:** the Arabic font we ship doesn't include ASCII glyphs.
**Rule:** wrap LTR ASCII tokens in a Helvetica run inside the PDF, and `<b dir="ltr">DEYE</b>` in HTML. The PDF report renderer handles this; don't bypass it.

### 10.17 Filename Content-Disposition latin-1 crash

**Symptom:** Arabic filename in the PDF download triggers `UnicodeEncodeError` in Werkzeug.
**Fix (locked):** RFC 5987 `filename*=UTF-8''…` pattern in `download_pdf` headers. Don't revert.

### 10.18 Cross-device leakage in `/loads`

**Symptom:** loads created with NULL `device_id` show up across all devices.
**Fix (locked):** `_loads_current_scope` requires `device_id`, falls back to `devices[0]` if needed; load create/toggle/delete validate ownership. `Setting._save_setting_value` commits unconditionally. Don't reintroduce silent-NULL paths.

### 10.19 Jinja `for` scope leak

**Symptom:** `{% set _curr_dev = d %}` inside `{% for d in devices %}` doesn't propagate after the loop.
**Fix (locked):** use `{% set ns = namespace(curr=None) %}` then `{% set ns.curr = d %}`. The `_device_switcher.html` partial uses this pattern. Don't drop it.

### 10.20 GPS / IP geolocation

**Symptom:** the clock+weather widget asks for browser geolocation and falls back to an IP geolocation API.
**Source:** original `clock_weather_widget_v1.js`.
**Fix (locked):** v33-μ refactor — only the saved profile city / country / timezone are used. No `navigator.geolocation`, no `ipapi.co`, no `/api/me/timezone` POST. The code is in profile-only mode; if location is missing, `_clock_weather_bar.html` shows the empty-state with a profile-link CTA.

### 10.21 `current_app.view_functions` in Jinja

**Symptom:** every page that includes `_sidebar.html` returns 500 with `'current_app' is undefined`.
**Source:** a defensive `{% if 'users_routes.admin_me' in current_app.view_functions %}` guard added during a hotfix.
**Rule:** Flask's `current_app` is not exposed to Jinja by default. Use `g` flags from a context processor, or a registered template helper, or — simpler — just call `url_for(...)` and trust route registration.

---

## 11. Golden rules for future development

These are the rules every PR / commit / agent run must check itself against.

1. **Never ship a "redesign" that adds a stylesheet without removing the old one.** Either delete the old layer, or scope every new rule under a new wrapper class.
2. **One helper sentence per field. 8–18 words. Single `<small>`. Period.** No popovers on form-field labels. Section/card/button popovers are fine.
3. **42 px is the form-control height.** Don't ship 38 px, 40 px, 44 px without adopting it across the entire page.
4. **Numeric digits use `font-variant-numeric: tabular-nums`.** Status, percentages, watts, hours.
5. **Arabic text never hand-flips LTR values.** Wrap with `dir="ltr"` or render via the PDF Helvetica fallback.
6. **The `name=` attribute is sacred.** Never change a form-field name without simultaneously updating the save handler. Most production bugs we shipped were "oh, the field renamed itself in the template."
7. **The Flow Graph is locked.** md5 `56124a8799a3bb800231d99d83f6d616`. If a task asks you to touch it, refuse and route through a separate scoped task.
8. **Setting model is global.** No `device_id`. UI must not claim per-device isolation. Use the v33-κ deferred-phase wording.
9. **Sidebar branches on `g.is_admin` only.** Never use `current_app.*` in Jinja. Subscriber and admin items never share a row.
10. **Every form field must have a working save path.** No fake disabled inputs. No "preview only" controls without an explicit gray banner saying preview-only.
11. **Honest scope language always.** "global", "preview", "deferred phase", "backend-supported" — these labels are not optional polish.
12. **CSS scope under a system prefix** (`prof-*`, `ns-*`, `cwx-*`, `pcwx-*`, `sd-*`, `up-*`, `hu-*`, `ad-*`, `lhx-*`, `ap-*`). No bare element selectors.
13. **Each stylesheet is loaded once.** `subscriber_console_v32.css` loaded twice was a real bug. The `extra_head` block in `base.html` is the registry.
14. **Cache-bust labels mean something.** Each version label is tied to a release moment (`v33-iota2-section-glass-tints`, `v33-mu-profile-clock-weather-bar`, `v33-threshold-compact-icon-cards-final`, `v33-profile-hero-avatar-actions-final`). When you ship a real change, bump it. When you make a one-line fix, don't bump it.
15. **`compileall` and Jinja parse pass before merge.** Even when the bash sandbox is unreliable, the Read-tool view of the file must show balanced `{% endblock %}`, `{% endfor %}`, `</div>`, `</section>`.
16. **`name=` attribute count is preserved across UI refactors.** A grep for `name="..."` counts identically before and after.
17. **No GPS, no IP geolocation, no auto-permission prompts** in the user-portal surfaces. Profile is the source of truth for location.
18. **No real SMS / no real Telegram fires from QA paths** unless the page explicitly says it's the live channel and the user explicitly confirms.
19. **Deletion is destructive.** Every destructive action confirms (modal or click-twice). Empty-trash, mass-delete, and account-disable are admin-gated — subscriber UI doesn't expose them.
20. **Admin self-demotion / self-deactivation are not exposed.** Admin self-profile (`/admin/me`) shows role and account-status as **disabled** display fields. Permissions and status changes happen in the user management page only.
21. **Honest reports about uncertain state.** When the bash sandbox is flaky, when an MCP tool is offline, when a feature is half-implemented — say so in the final report. Don't paper over it. The session has a long list of "sandbox cache drift" notes; that's the right pattern.

---

## Appendix A — Canonical class prefixes (registry)

| Prefix | System | Files |
|---|---|---|
| `prof-*` | Profile pages (admin & subscriber, shared) | `admin_user_profile.css`, `admin_staff_profile_v2.css`, `account_profile.css` (override) |
| `up-*` | Profile-page outer (`up-page`, `up-pane`, `up-stat`) | `admin_user_profile.css` |
| `hu-*` | Hero unified (`hu-hero`, `hu-eyebrow`, `hu-h1`) | `unified_hero_v1.css` |
| `ns-*` | Notifications page system | `notifications_settings_v33.css`, `notifications_v33iota.css` |
| `ns-tg-*` | Threshold compact icon cards | `notifications_v33iota.css` |
| `ns-channel-chip*` | Telegram/SMS routing toggles | `notifications_v33iota.css` (legacy in `notifications_settings_v33.css`) |
| `cwx-*` | Clock+weather chip (compact) | `clock_weather_widget_v1.css` |
| `pcwx-*` | Clock+weather bar (in-page) | `clock_weather_widget_v1.css` |
| `sd-*` | Sidebar v11 | `sidebar_rebuild_v11.css` |
| `ad-*` | Admin dashboard layout | `admin_dashboard.css` (in `unified_theme_v1.css`) |
| `lhx-*` | Public landing page hero | `landing` stylesheets |
| `ap-*` | Account-profile-only IDs | `account_profile.html` |
| `lf-*` / `live-fleet-*` | Multi-device fleet rail | `live_fleet_rail_v33b.css` |

## Appendix B — Canonical partials

| Partial | Purpose |
|---|---|
| `_sidebar.html` | Two-branch sidebar (`g.is_admin` decides). |
| `_header_notifications.html` | Top-right notification bell + dropdown. |
| `_clock_weather_bar.html` | Profile-driven clock + weather strip (v33-μ). |
| `_device_switcher.html` | Multi-device switcher with for-scope-safe `namespace()`. |
| `_live_fleet_rail.html` | Multi-device fleet pill rail above Flow Graph. |
| `_location_picker.html` | Country / city / timezone macros (`loc.country_select`, etc.). |
| `_notifications_log_fragment.html` | AJAX-paginated NotificationLog (10/page). |

## Appendix C — Canonical context processors

| Module | Purpose |
|---|---|
| `services/security.py::register_security` | CSRF, account-preview banner, `csrf_token`/`mask_*` helpers. |
| `services/i18n.py::register_i18n` | `ui_lang`, `t()`, `i18n_client_catalog_json`. |
| `services/labels.py::register_template_helpers` | `role_label`, label dictionaries. |
| `services/rbac.py::register_access_control` | `has_permission()`, `portal_page_visible()`. |
| `services/device_context.py::register_device_context` | Active device, scope, fleet metadata. |
| `services/clock_weather_context.py::register_clock_weather_context` | `cwx_user_country / city / timezone` + `cwx_profile_url` (v33-μ). |

## Appendix D — Hard locks (do not modify)

- `Flow Graph` template + JS + SVG (md5 `56124a8799a3bb800231d99d83f6d616`, 7,970 bytes).
- `app/scheduler/*` — scheduler fan-out + cron logic.
- `app/services/notifications/__init__.py`, `app/services/notifications/utils.py` — dispatch + dedup.
- `app/blueprints/notifications.py::save_notification_settings_from_form` — settings save engine. UI-side changes never touch this; only add new keys after backend support is real.
- `app/services/weather_service.py` — Open-Meteo weather backend. Reachable through profile-driven flows only.
- `app/blueprints/reports.py` (PDF export pipeline) — Helvetica/Arabic font, RFC 5987 disposition, scope block, page-2 analytical table. UI must not regress these.

---

*End of v35 consistency system. Subsequent UI work is judged against this document.*
