# Heavy v10.2 — Targeted UI Fixes

## Included in this patch

- Fixed the blank space appearing above the header in admin and subscriber/user-facing pages.
- Removed unused top body offset that was reserved for a utility bar not currently rendered.
- Added an explicit body class `no-global-utility-bar` so the top offset stays disabled safely.
- Refined fixed-sidebar nav item sizing so long labels no longer crush vertically or overlap badges.
- Improved sidebar label wrapping and badge spacing.
- Updated visible product version labels to `v10.2`.
- Updated static asset cache-busting tags from `10.1` to `10.2`.

## Files changed

- `app/templates/base.html`
- `app/templates/_sidebar.html`
- `app/static/css/style.css`

## Expected result

- Admin pages start directly from the header/card area without a large blank area above.
- Subscriber pages start correctly as well.
- Sidebar navigation looks more stable with long Arabic labels.
