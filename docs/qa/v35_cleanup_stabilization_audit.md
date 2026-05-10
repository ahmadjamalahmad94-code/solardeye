# v35 Cleanup / Stabilization Audit

Date: 2026-05-10

Scope: dirty worktree audit after the v34 QA work. This report categorizes modified and untracked files only. No production source files were edited as part of this audit.

## Executive Summary

The dirty worktree contains a mix of broad production UI/backend changes, QA reports, browser/test automation artifacts, generated screenshots/logs, local uploads, and several likely accidental leftovers.

Conservative recommendation:

- Do not commit the dirty tree as-is.
- Keep only deliberately reviewed production changes.
- Delete or move generated screenshots/logs/uploads outside the repo before a production commit.
- Treat broad backend changes, especially notification sending actions and new admin profile routes, as needs-review or dangerous until route-level QA is repeated.
- Keep the v34 QA markdown reports only if the repository intentionally tracks QA evidence.

## Category Legend

- Safe production-ready changes: reviewed and low-risk enough to keep.
- QA/testing/temp artifacts: useful for local QA but not production runtime.
- Generated screenshots/logs: generated output, server logs, browser captures, uploads.
- Likely accidental leftovers: scratch files, temporary render dumps, local notes.
- Needs-review before commit: may be valid work, but must be reviewed/tested before commit.
- Dangerous/unverified changes: could affect app behavior, security, external sends, or broad runtime context.

## High-Risk Notes

- No dirty production file is classified as fully safe without review. The worktree has large UI/backend diffs and many untracked files.
- `app/blueprints/notifications_routes.py` includes notification test/send-related behavior and must be reviewed to ensure no real Telegram/SMS sends are accidentally exposed.
- `app/blueprints/users_routes.py` adds or changes admin profile/avatar behavior and should be checked against actual model field names and authorization expectations before commit.
- `app/__init__.py` and `app/services/clock_weather_context.py` affect global request context and should be reviewed carefully because they can impact every page.
- Local uploads under `app/static/uploads/` should not be committed.

## File Inventory

| File | State | Category | Why | Recommendation |
|---|---:|---|---|---|
| `docs/qa/v35_cleanup_stabilization_audit.md` | new | QA/testing/temp artifacts | Requested audit deliverable created by this task. | keep |
| `AGENTS.md` | modified | Needs-review before commit | Project instruction file changed or line endings changed; not production runtime, but it controls future agent behavior. | review |
| `New Text Document.txt` | modified | Likely accidental leftovers | Generic scratch filename with no clear production purpose. | delete |
| `SOLARDEYE_BUILD_GUIDE.md` | modified | Needs-review before commit | Build guide documentation changed; may be valid but unrelated to runtime QA fixes. | review |
| `_local_server_err.txt` | modified | Generated screenshots/logs | Local server stderr output. | delete + gitignore |
| `_local_server_out.txt` | modified | Generated screenshots/logs | Large local server stdout log with thousands of changed lines. | delete + gitignore |
| `local_server.err` | modified | Generated screenshots/logs | Local server stderr output. | delete + gitignore |
| `local_server.out` | modified | Generated screenshots/logs | Local server stdout output. | delete + gitignore |
| `_qa_server_err.txt` | untracked | Generated screenshots/logs | QA server stderr output. | delete + gitignore |
| `_qa_server_out.txt` | untracked | Generated screenshots/logs | QA server stdout output. | delete + gitignore |
| `current_dirty_state.txt` | untracked | QA/testing/temp artifacts | Snapshot of dirty state, useful locally but not production source. | delete |
| `tmp_register_live.html` | modified | Likely accidental leftovers | Temporary rendered/live HTML capture. | delete |
| `tmp_register_rendered.html` | modified | Likely accidental leftovers | Temporary rendered HTML capture. | delete |
| `tmp_register_script.js` | modified | Likely accidental leftovers | Temporary script for registration testing. | delete |
| `ADMIN_QA_AUDIT_REPORT_2026-05-07.md` | untracked | QA/testing/temp artifacts | Admin QA report artifact outside the `docs/qa` structure. | review or move |
| `docs/qa/v34_subscriber_full_journey_qa.md` | untracked | QA/testing/temp artifacts | Requested v34 QA report. Useful evidence if QA docs are tracked. | keep |
| `docs/qa/v34_subscriber_real_browser_qa_followup.md` | untracked | QA/testing/temp artifacts | Requested v34 browser follow-up report. Useful evidence if QA docs are tracked. | keep |
| `docs/qa/screenshots/v34_subscriber_browser_qa_followup/README.md` | untracked | QA/testing/temp artifacts | Screenshot folder readme/evidence index. | keep or defer |
| `screenshots/INDEX.md` | untracked | Generated screenshots/logs | Screenshot index outside `docs/qa`; likely generated evidence. | review or delete |
| `tools/admin_design_capture.cjs` | untracked | QA/testing/temp artifacts | Browser/design capture tooling, not runtime. | review |
| `tools/subscriber_design_capture.cjs` | untracked | QA/testing/temp artifacts | Browser/design capture tooling, not runtime. | review |
| `tools/subscriber_interaction_qa.py` | untracked | QA/testing/temp artifacts | Subscriber interaction QA script. | review |
| `tools/prepare_subscriber_qa_seed.py` | untracked | QA/testing/temp artifacts | Local QA seed helper. | review |
| `tools/qa_seed_v33b_multi_device.py` | untracked | QA/testing/temp artifacts | Local multi-device QA seed helper. | review |
| `app/static/uploads/avatars/user_1.jpg` | untracked | Generated screenshots/logs | User-uploaded/local avatar media from testing. | delete + gitignore |
| `app/static/uploads/profiles/profile_9097e6efa6.jpg` | untracked | Generated screenshots/logs | User-uploaded/local profile image from testing. | delete + gitignore |

## Production Code and Template Changes

These files are potentially legitimate v33/v34 implementation work, but they are not safe to commit blindly because the changes are broad and user-facing.

| File | State | Category | Why | Recommendation |
|---|---:|---|---|---|
| `app/__init__.py` | modified | Dangerous/unverified changes | Registers new app-wide clock/weather context and adds notification default settings; affects every request/app startup. | defer |
| `app/services/clock_weather_context.py` | untracked | Dangerous/unverified changes | New global context helper; needs route/session/device review before production. | defer |
| `app/services/location_catalog.py` | modified | Needs-review before commit | Location/country/timezone data changes affect profile selectors and scheduling context. | review |
| `app/blueprints/devices_routes.py` | modified | Needs-review before commit | Subscriber profile context/data-flow changes for country, timezone, phone prefix, and profile counts. | review |
| `app/blueprints/users_routes.py` | modified | Dangerous/unverified changes | Large admin profile/avatar route changes; authorization and model-field compatibility need careful verification. | defer |
| `app/blueprints/notifications_routes.py` | modified | Dangerous/unverified changes | Adds/changes notification testing, both-channel actions, and log fragment behavior; may touch real external sends. | defer |
| `app/blueprints/helpers.py` | modified | Needs-review before commit | Shared helper changes can affect multiple templates/routes. | review |
| `app/blueprints/main.py` | modified | Needs-review before commit | Route/controller changes need route-level verification. | review |
| `app/templates/base.html` | modified | Needs-review before commit | Shared base template affects all pages. | review |
| `app/templates/_sidebar.html` | modified | Needs-review before commit | Shared navigation/sidebar behavior can affect role separation. | review |
| `app/templates/_live_fleet_rail.html` | modified | Needs-review before commit | Dashboard/fleet UI changes; ensure subscriber/admin scope remains correct. | review |
| `app/templates/_location_picker.html` | modified | Needs-review before commit | Shared country/city picker; previously caused JSON serialization failure when city data was undefined. | review |
| `app/templates/_clock_weather_bar.html` | untracked | Dangerous/unverified changes | New global/top-bar partial tied to untracked context service; sampled output needs Arabic encoding/copy verification. | defer |
| `app/templates/_notifications_log_fragment.html` | untracked | Needs-review before commit | New partial for AJAX log pagination; validate pagination, escaping, empty states, and Arabic copy. | review |
| `app/templates/account_profile.html` | modified | Needs-review before commit | Subscriber profile form/avatar/phone/location changes; high visibility and previous regressions. | review |
| `app/templates/admin_me.html` | untracked | Dangerous/unverified changes | New admin personal profile template; needs auth, route, model, upload, and role review. | defer |
| `app/templates/admin_dashboard.html` | modified | Needs-review before commit | Admin dashboard UI/context changes; verify no subscriber leakage. | review |
| `app/templates/admin_staff_profile.html` | modified | Needs-review before commit | Admin/staff profile UI changes. | review |
| `app/templates/channels.html` | modified | Needs-review before commit | Telegram/SMS channel UI changes; verify no unsafe send behavior and field-name compatibility. | review |
| `app/templates/dashboard.html` | modified | Needs-review before commit | Subscriber dashboard UI changes; Flow Graph boundaries must be confirmed untouched. | review |
| `app/templates/devices_manage.html` | modified | Needs-review before commit | Device management UI/helpers; ensure no real provider calls are triggered by local QA UI. | review |
| `app/templates/loads.html` | modified | Needs-review before commit | Loads UI/helper changes; verify CRUD and selected-device behavior. | review |
| `app/templates/notifications.html` | modified | Needs-review before commit | Very large notification settings UI changes; verify independent saves, hidden threshold values, and no scheduler/dispatch regression. | review |
| `app/templates/partials/profile/_pane_profile.html` | modified | Needs-review before commit | Shared profile partial change; can affect multiple profile surfaces. | review |
| `app/templates/reports.html` | modified | Needs-review before commit | Reports UI/helper changes; ensure report/PDF backend untouched. | review |
| `app/templates/statistics.html` | modified | Needs-review before commit | Statistics UI/helper changes; verify filters and units. | review |
| `app/static/css/account_profile.css` | untracked | Needs-review before commit | New subscriber/admin profile stylesheet; likely valid but must be checked for conflicts with older profile CSS. | review |
| `app/static/css/admin_user_form_v2.css` | untracked | Needs-review before commit | New admin form/profile stylesheet; needs visual and selector-conflict review. | review |
| `app/static/css/admin_staff_profile_v2.css` | modified | Needs-review before commit | Admin profile CSS changes. | review |
| `app/static/css/admin_user_profile.css` | modified | Needs-review before commit | Large profile/admin CSS changes; possible overlap with new profile stylesheet. | review |
| `app/static/css/channels_v3.css` | modified | Needs-review before commit | Channels UI style changes. | review |
| `app/static/css/clock_weather_widget_v1.css` | untracked | Needs-review before commit | New global clock/weather widget CSS; depends on untracked context/partial. | defer |
| `app/static/css/dashboard_main.css` | untracked | Needs-review before commit | New dashboard stylesheet; verify no Flow Graph styling conflict. | review |
| `app/static/css/layout.css` | untracked | Needs-review before commit | New layout stylesheet; broad visual impact. | review |
| `app/static/css/login_v50.css` | untracked | Needs-review before commit | New login stylesheet; verify auth pages and RTL. | review |
| `app/static/css/register_v50.css` | untracked | Needs-review before commit | New register stylesheet; verify auth pages and RTL. | review |
| `app/static/css/notifications_settings_v33.css` | untracked | Needs-review before commit | New notification settings stylesheet; large page impact. | review |
| `app/static/css/notifications_v33iota.css` | untracked | Needs-review before commit | Additional notification polish stylesheet; potential overlap with settings stylesheet. | review |
| `app/static/css/portal_support_v3.css` | modified | Needs-review before commit | Support spacing/contrast changes; likely useful but verify browser results. | review |
| `app/static/css/sidebar.css` | untracked | Needs-review before commit | New sidebar stylesheet; must preserve role-specific navigation and fixed sidebar behavior. | review |
| `app/static/css/subscriber_console_v32.css` | modified | Needs-review before commit | Large shared subscriber UI CSS changes; broad visual impact. | review |
| `app/static/css/ui_guidance_v33.css` | untracked | Needs-review before commit | Reusable helper/tooltip CSS; verify no clipping or contrast issues. | review |
| `app/static/js/clock_weather_widget_v1.js` | untracked | Needs-review before commit | New global widget JS; verify no errors and no stale polling assumptions. | defer |
| `app/static/js/notifications_settings_v33.js` | untracked | Needs-review before commit | Notification page JS for previews/chips/pagination; verify hidden input sync and no broken saves. | review |

## Generated QA Evidence and Screenshots

These files are generated artifacts. Keep them only if the repo intentionally stores visual QA evidence; otherwise delete or move outside Git and add ignore patterns.

| File | State | Category | Why | Recommendation |
|---|---:|---|---|---|
| `audit_artifacts/admin_design_20260507/admin_design_capture.json` | untracked | Generated screenshots/logs | Generated admin design capture metadata. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__activity-log.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__backups.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__dashboard.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__design-qa.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__devices.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__finance.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__integrations.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__landing-settings.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__mail.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__me.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__plans.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__plans__new.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__platform-review.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__quotas.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__roles.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__services-health.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__subscribers.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__support-command-center.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__system-logs.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__team.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__tickets.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/admin_design_20260507/screenshots/admin__users__legacy.png` | untracked | Generated screenshots/logs | Generated admin screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/SUBSCRIBER_STYLE_AND_QA_REPORT_2026-05-07.md` | untracked | QA/testing/temp artifacts | Subscriber design QA report artifact. | review or move into `docs/qa` |
| `audit_artifacts/subscriber_design_20260507/WORK_SUMMARY_2026-05-07.md` | untracked | QA/testing/temp artifacts | Work summary artifact. | review or move into `docs/qa` |
| `audit_artifacts/subscriber_design_20260507/subscriber_design_capture.json` | untracked | Generated screenshots/logs | Generated subscriber design capture metadata. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/subscriber_interaction_qa.json` | untracked | Generated screenshots/logs | Generated subscriber interaction QA metadata. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/account__profile.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/account__subscription.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/alerts.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/battery-lab.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/channels.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/devices.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/devices__manage.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/deye.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/diagnostics.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/live-data.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/loads.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/notification-center.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/notifications.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/notifications__center.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/onboarding.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/plant-info.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/portal__messages.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/portal__support.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/portal__tickets.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/reports.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/statistics.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |
| `audit_artifacts/subscriber_design_20260507/screenshots/support.png` | untracked | Generated screenshots/logs | Generated subscriber screenshot. | delete or archive outside repo |

## Recommended Cleanup Plan

1. Delete local logs and scratch files: `_local_server_*`, `_qa_server_*`, `local_server.*`, `tmp_register_*`, `current_dirty_state.txt`, and `New Text Document.txt`.
2. Move or delete generated screenshot trees under `audit_artifacts/` unless the team intentionally tracks image QA evidence.
3. Add or verify `.gitignore` rules for local server logs, generated screenshots, test captures, and uploaded media.
4. Review production changes in small commits by area:
   - profile/location/phone/avatar
   - notifications/channels
   - support spacing/contrast
   - dashboard/layout/sidebar
   - QA tooling/docs
5. Defer risky backend/global changes until isolated verification:
   - `app/__init__.py`
   - `app/services/clock_weather_context.py`
   - `app/blueprints/notifications_routes.py`
   - `app/blueprints/users_routes.py`
   - `app/templates/admin_me.html`
6. Before committing any production UI files, rerun route render checks and targeted browser verification for the affected pages.

## Suggested Keep / Delete Summary

Keep after review:

- v34 QA markdown reports in `docs/qa/`
- QA tools in `tools/` if the team wants repeatable browser QA
- Production templates/CSS/JS only after file-by-file review and route verification

Delete or move outside repo:

- local server logs
- temporary rendered registration files
- generated screenshots under `audit_artifacts/`
- local uploaded avatars/profile images
- scratch files with generic names

Defer:

- global app context changes
- notification send/test route changes
- new admin profile route/template stack

