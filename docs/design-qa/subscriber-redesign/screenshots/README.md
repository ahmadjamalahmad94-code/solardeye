# v32 QA screenshots

Chrome MCP captures the screenshots client-side and does not save them
into this folder; they live in the Chrome browser cache during the QA
session. The screenshots from the v32 QA pass are referenced in
`subscriber-before-after.md` and `subscriber-redesign-summary.md` as
inline observations.

To re-run QA and capture fresh screenshots:

1. Restart the Flask server (`python app.py`) so the new
   `services/device_context.py` and `register_device_context(app)` in
   `app/__init__.py` take effect.
2. Log in as the multi-device QA subscriber (`ahmad / 791994`).
3. Visit each subscriber page at desktop / tablet / mobile widths via
   browser DevTools device emulation.
4. Save full-page screenshots into this folder using the page name +
   viewport (e.g. `devices-manage_desktop.png`,
   `live-data_mobile.png`).

Pages to capture:
- `/devices/manage?lang=ar`
- `/devices/manage/<id>/edit?lang=ar`
- `/live-data?lang=ar`
- `/notifications/center?lang=ar`
- `/loads?lang=ar`
- `/statistics?lang=ar`
- `/reports?lang=ar`
- `/notifications?lang=ar`
- `/channels?lang=ar`
- `/account/profile?lang=ar`
- `/account/subscription?lang=ar`
- `/portal/support?lang=ar`
- `/onboarding?lang=ar`

For admin regression check:
- `/admin/dashboard?lang=ar`
- `/admin/support-command-center?lang=ar`
- `/admin/devices?lang=ar`
- `/admin/design-qa?lang=ar`
