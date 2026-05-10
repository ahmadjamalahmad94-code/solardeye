# v34 Subscriber Real Browser QA

## 1. Test Environment

- Date: 2026-05-09
- App: SolarDeye local Flask app
- Server command used/verified: `$env:DATABASE_URL="sqlite:///solar_local.db"; python -m flask --app app run`
- Browser method used: Codex Browser plugin / in-app browser using Playwright API against `http://127.0.0.1:5000`.
- Screenshot folder: `docs/qa/screenshots/v34_subscriber_browser_qa/`
- Raw browser result file: `docs/qa/screenshots/v34_subscriber_browser_qa/_raw_results.json`
- Test account: `qa.subscriber.v34 / qa.subscriber.v34@example.test / Test12345!`
- Test account role: subscriber/user, not admin.

## 2. Browser Availability Note

Real browser automation was available and used for authentication, sidebar navigation, dashboard, profile, devices, and loads. During the loads delete/confirm step the in-app browser tab became blocked by the browser confirmation flow. The recovery attempt closed the tab, after which the Browser plugin reported `No active Codex browser pane available`. No remaining item is marked PASS unless it was actually clicked/typed/selected/submitted/reloaded before that point.

## 3. Summary Counts

- Browser result rows captured: 37
- Screenshots captured in result log: 48
- PNG files present in screenshot folder: 56
- PASS: 25
- FIXED: 1
- FAIL: 8
- NEEDS_VISUAL_REVIEW: 3
- SKIPPED_SAFE_EXTERNAL: 1
- BROWSER_AUTOMATION_UNAVAILABLE: 7

Note: several FAIL rows are preserved as before-fix evidence. The root cause for profile save was fixed and verified with a later `FIXED` row.

## 4. Pages Tested Through Browser

- `/login?lang=ar`: opened, invalid login submitted, valid login submitted.
- `/dashboard`: reached after valid login and re-login; safe dashboard shortcuts clicked.
- Sidebar-visible pages clicked: `/dashboard`, `/notifications/center`, `/devices/manage`, `/account/profile`, `/account/subscription`, `/statistics`, `/reports`, `/live-data`, `/loads`, `/notifications`, `/channels`, `/portal/support`.
- `/account/profile?lang=ar`: fields selected/typed, save tested before and after the fix, reload persistence verified after the fix.
- `/devices/manage?lang=ar`: page opened, add-device anchor clicked; create/edit/delete skipped safely because provider/API behavior was not confirmed local-only.
- `/loads?lang=ar`: page opened, number-input and action-button behavior tested; flow was interrupted by browser confirmation/recovery before completion.

## 5. Bugs Found

1. Guidance tooltip JS blocked action buttons. Elements like profile save and load action buttons had `data-help-text`; the guidance script attached a click handler that called `preventDefault()` and `stopPropagation()`, so real clicks showed/hid help instead of submitting forms.
2. Profile save appeared broken before the JS fix. Full name/contact changes did not persist until the guidance click handling was fixed.
3. Sidebar notification-center click did not navigate during the first browser pass; it remained on dashboard. Retest was blocked by browser loss.
4. Browser automation could not use direct `fill/type` on `input[type=email]` and `input[type=number]` in this environment; email editing and number fill attempts are documented as automation limitations, not confirmed app bugs.
5. Console logs showed Chart.js canvas reuse errors on repeated dashboard navigation: `Canvas is already in use... powerChart`. This was not fixed because dashboard/graph internals are protected in this phase.
6. Browser automation pane became unavailable after the loads delete confirmation flow; remaining page-specific interactions are explicitly not marked PASS.

## 6. Bugs Fixed

- Fixed `app/static/js/ui_guidance_v33.js` so guidance attached to action elements no longer prevents the action click. Action buttons still show help on focus/hover, while dedicated `.ui-help` icons keep click-to-toggle behavior.
- Re-tested profile save after the fix: full name, country, city, timezone, phone prefix, and phone number persisted after reload.

## 7. Deferred / Not Fixed

- Full notification settings interaction pass: deferred because browser automation became unavailable.
- Channels Telegram/SMS send/test buttons: skipped; could trigger real Telegram/SMS/external behavior.
- Device create/edit/delete: skipped; provider integration semantics were not clearly local-only.
- Support ticket create/reply: not completed because browser automation became unavailable after the loads flow.
- Mobile screenshots at 390px and 768px: not completed because browser automation became unavailable.
- Chart.js repeated canvas error: report-only; may touch dashboard chart lifecycle and is outside the safe scope without a focused follow-up.

## 8. Arabic / RTL Findings

- Login page, profile fields, sidebar labels, and helper text rendered RTL in browser screenshots.
- Profile country/timezone/prefix data was visible and populated: country list includes Arabic country names, timezone includes the Palestine `Asia/Hebron` option, and the prefix selector includes `PS +970`.
- The QA profile initially showed the city in an English/fallback form; after selecting the Arabic Gaza option and saving after the JS fix, the Arabic city persisted for the QA account.
- Some browser/dev tooling outputs display mojibake in terminal logs, but the actual browser screenshots should be used as the visual source of truth.

## 9. Visual Contrast / Spacing Findings

- Desktop screenshots were captured for auth, dashboard, profile, devices, loads, notifications, channels, support, reports/statistics/live-data via sidebar navigation.
- No additional CSS visual polish was applied in this pass beyond fixing the action-blocking guidance behavior.
- Mobile and deep contrast pass is still required because the browser pane was unavailable before viewport testing.

## 10. Detailed Browser Control Log

| Page | Control | Action performed | Before screenshot | After screenshot | Result | Status | Notes |
|---|---|---|---|---|---|---|---|
| Authentication | Login page | Opened /login?lang=ar | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_login_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_login_before.png` | Login page rendered in Arabic RTL. | PASS | Real browser navigation and screenshot captured. |
| Authentication | Invalid login | Typed qa.subscriber.v34 + wrong password and submitted | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_login_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_invalid_after.png` | Stayed on login page with invalid credential feedback area visible. | PASS | No account state changed. |
| Authentication | Valid login | Typed qa.subscriber.v34 + Test12345! and submitted | `auth_invalid_after` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_dashboard_after_login.png` | Redirected to dashboard. | PASS | Real subscriber session established. |
| Authentication | Logout | Looked for logout control after login | `auth_dashboard_after_login` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_logout_not_available.png` | logout control not found: a[href*="/logout"] \| button[name="logout"] | NEEDS_VISUAL_REVIEW | Logout control was not uniquely found/clickable through browser automation. |
| Authentication | Logout | Clicked sidebar POST logout button | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_dashboard_before_logout_retry.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_after_logout.png` | POST logout completed and returned to a public/auth page. | PASS | Initial lookup missed form-based logout; direct form selector worked. |
| Authentication | Re-login after logout | Logged in again after POST logout | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_after_logout.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_dashboard_after_relogin.png` | Dashboard restored after re-login. | PASS |  |
| Sidebar/navigation | لوحة التحكم | Clicked sidebar link /dashboard?lang=ar | `http://127.0.0.1:5000/dashboard` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_dashboard.png` | Navigated to http://127.0.0.1:5000/dashboard | PASS | Multiple matching anchors (2); used first after count check. |
| Sidebar/navigation | مركز الإشعارات | Clicked sidebar link /notifications/center?lang=ar | `http://127.0.0.1:5000/dashboard` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_notifications_center.png` | Unexpected URL http://127.0.0.1:5000/dashboard | FAIL | Multiple matching anchors (3); used first after count check. |
| Sidebar/navigation | الأجهزة | Clicked sidebar link /devices/manage?lang=ar | `http://127.0.0.1:5000/dashboard` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_devices_manage.png` | Navigated to http://127.0.0.1:5000/devices/manage?lang=ar | PASS | Multiple matching anchors (3); used first after count check. |
| Sidebar/navigation | الملف الشخصي | Clicked sidebar link /account/profile?lang=ar | `http://127.0.0.1:5000/devices/manage?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_account_profile.png` | Navigated to http://127.0.0.1:5000/account/profile?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | الاشتراك | Clicked sidebar link /account/subscription?lang=ar | `http://127.0.0.1:5000/account/profile?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_account_subscription.png` | Navigated to http://127.0.0.1:5000/account/subscription?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | الإحصائيات | Clicked sidebar link /statistics?lang=ar | `http://127.0.0.1:5000/account/subscription?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_statistics.png` | Navigated to http://127.0.0.1:5000/statistics?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | التقارير | Clicked sidebar link /reports?lang=ar | `http://127.0.0.1:5000/statistics?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_reports.png` | Navigated to http://127.0.0.1:5000/reports?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | البيانات الحية | Clicked sidebar link /live-data?lang=ar | `http://127.0.0.1:5000/reports?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_live_data.png` | Navigated to http://127.0.0.1:5000/live-data?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | الأحمال | Clicked sidebar link /loads?lang=ar | `http://127.0.0.1:5000/live-data?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_loads.png` | Navigated to http://127.0.0.1:5000/loads?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | الإشعارات | Clicked sidebar link /notifications?lang=ar | `http://127.0.0.1:5000/loads?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_notifications.png` | Navigated to http://127.0.0.1:5000/notifications?lang=ar | PASS | No admin-only URL exposed. |
| Sidebar/navigation | القنوات | Clicked sidebar link /channels?lang=ar | `http://127.0.0.1:5000/notifications?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_channels.png` | Navigated to http://127.0.0.1:5000/channels?lang=ar | PASS | Multiple matching anchors (3); used first after count check. |
| Sidebar/navigation | الدعم | Clicked sidebar link /portal/support?lang=ar | `http://127.0.0.1:5000/channels?lang=ar` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_portal_support.png` | Navigated to http://127.0.0.1:5000/portal/support?lang=ar | PASS | No admin-only URL exposed. |
| Dashboard | Dashboard render | Opened /dashboard?lang=ar | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_before_controls.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_before_controls.png` | Dashboard rendered for subscriber session. | PASS | Flow Graph area was inspected visually only, not modified. |
| Dashboard | Device management shortcut | Clicked safe dashboard shortcut a[href*="/devices/manage"] | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_before_controls.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_after_device_shortcut.png` | Navigated to http://127.0.0.1:5000/devices/manage?lang=ar | PASS | Multiple matches (3); used first after count check. |
| Dashboard | Loads shortcut | Clicked safe dashboard shortcut a[href*="/loads"] | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_before_controls.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_after_loads_shortcut.png` | Navigated to http://127.0.0.1:5000/loads?lang=ar | PASS | Multiple matches (2); used first after count check. |
| Profile/account | Profile render | Opened /account/profile?lang=ar | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_before_interaction.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_before_interaction.png` | Profile page rendered; timezone and phone prefix options visible in real browser. | PASS | Country/city options are populated from the shared location catalog. |
| Profile/account | Profile form | Attempted safe profile edit/save/reload flow | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_before_interaction.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_error_state.png` | Browser Use encountered an error interacting with this webpage's clipboard: Failed to execute 'setRangeText' on 'HTMLInputElement': The input element's type ('email') does not support selection.<br>locator.fill failed for selector input[name="email"] | FAIL |  |
| Profile/account | Profile retry | Retried safe profile edit/save/reload flow | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_retry_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_retry_error_state.png` | Browser Use encountered an error interacting with this webpage's clipboard: Failed to execute 'setRangeText' on 'HTMLInputElement': The input element's type ('email') does not support selection.<br>locator.type failed for selector input[name="email"] | FAIL |  |
| Profile/account | Profile safe fields excluding email | Changed full name, language, country, city, timezone, phone prefix, phone number | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_edited_before_save.png` | All non-email safe profile fields accepted browser interactions. | PASS | Email was skipped after two browser automation input failures on input[type=email]. |
| Profile/account | Profile save without email edit | Clicked profile save button after non-email changes | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_edited_before_save.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_after_save.png` | Profile form submitted without browser error. | PASS |  |
| Profile/account | Profile persistence without email edit | Reloaded after save and verified visible values | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_after_save.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_after_reload.png` | Some saved values were not visible after reload. | FAIL |  |
| Profile/account | Email field | Attempted editing email twice with browser fill/type, then skipped to avoid blocking rest of QA | `profile_before_interaction` | `profile_retry_error_state` | Browser automation cannot set input[type=email] in this environment; field remained visible and existing value was preserved. | NEEDS_VISUAL_REVIEW | This is an automation limitation, not confirmed app bug. |
| Devices | Devices page render | Opened /devices/manage?lang=ar | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_before.png` | Devices management page rendered for subscriber. | PASS | External provider sync/API calls were not triggered. |
| Devices | Add device anchor | Clicked add-device anchor to reveal/reach form | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_add_form_visible.png` | Add-device form/area reached without external API call. | PASS | Multiple add links (2); used first after count check. |
| Devices | Device form inputs | Inspected visible device inputs/selects in browser | `devices_add_form_visible` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_inputs_review.png` | 9 input/select/textarea controls visible on page. | NEEDS_VISUAL_REVIEW | Creating/editing/deleting a device was skipped: provider credentials/API semantics were not clearly local-only and could create persistent non-cleanup state. |
| Loads | Loads page render | Opened /loads?lang=ar | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_before.png` | Loads page rendered with saved loads and add form. | PASS | Real browser screenshot captured. |
| Loads | Loads interactions | Add/toggle/delete QA load flow | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_error_state.png` | Browser Use encountered an error interacting with this webpage's clipboard: Failed to execute 'setRangeText' on 'HTMLInputElement': The input element's type ('number') does not support selection.<br>locator.fill failed for selector form.lds-form input[name="power_w"] | FAIL |  |
| Profile/account | Focused save button test | Filled full name and clicked save by exact role name | `profile_focused_save_before` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_focused_save_after_reload.png` | Full name did not persist; current value is مشترك QA v34 | FAIL | save button role count 0 |
| Profile/account | Direct CSS save click | Filled full name and clicked button.prof-btn-save directly | `profile_direct_save_before` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_direct_save_after_reload.png` | Full name did not persist; current value is مشترك QA v34 | FAIL |  |
| Profile/account | Profile save after guidance fix | Reloaded patched guidance JS, edited full name/city/phone, clicked save, reloaded | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_after_guidance_fix_edited.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_after_guidance_fix_reloaded.png` | Profile values persisted after the tooltip click-prevention fix. | FIXED | Root cause was guidance click handler preventing action-button default behavior. |
| Loads | Loads retest after guidance fix | Retested add/toggle/delete QA load after JS fix | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_after_guidance_fix_before.png` | `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_after_guidance_fix_error.png` | Browser Use encountered an error interacting with this webpage's clipboard: Failed to execute 'setRangeText' on 'HTMLInputElement': The input element's type ('number') does not support selection. | FAIL |  |
| Notifications | Category toggles and threshold channel chips | Not performed after browser pane loss |  |  | Browser pane became unavailable before this page-specific interaction pass. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |
| Notifications | Save/reload all notification sections | Not performed after browser pane loss |  |  | Not performed after browser pane loss; no PASS claimed. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |
| Channels | Telegram/SMS fields and save buttons | Not performed after browser pane loss |  |  | Page screenshot captured through sidebar navigation, but field interactions were not completed before browser loss. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |
| Channels | Telegram/SMS test buttons | Not performed after browser pane loss |  |  | Skipped/not triggered; could send real external messages. | SKIPPED_SAFE_EXTERNAL | No PASS claimed. |
| Support/messages | Create ticket and reply | Not performed after browser pane loss |  |  | Support page screenshot captured through sidebar navigation, but submit flow was not reached before browser loss. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |
| Notification center | Rows/read-unread/filter clicks | Not performed after browser pane loss |  |  | Initial sidebar click did not navigate; retest blocked by browser loss. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |
| Reports/statistics/live-data | Filters/date/export controls | Not performed after browser pane loss |  |  | Route/page screenshots captured; control clicks not completed before browser loss. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |
| Mobile visual QA | 390px and 768px viewport screenshots | Not performed after browser pane loss |  |  | Viewport tool was available, but browser pane was lost before mobile pass. | BROWSER_AUTOMATION_UNAVAILABLE | No PASS claimed. |

## 11. Screenshots Captured

The folder also contains additional `loads_final_retry_*` PNGs from the timed-out loads retry; they are preserved as visual evidence but are not counted as PASS rows because result logging did not complete after the browser pane became unavailable.

- `auth_login_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_login_before.png`
- `auth_invalid_after`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_invalid_after.png`
- `auth_dashboard_after_login`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_dashboard_after_login.png`
- `auth_logout_not_available`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_logout_not_available.png`
- `auth_dashboard_before_logout_retry`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_dashboard_before_logout_retry.png`
- `auth_after_logout`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_after_logout.png`
- `auth_dashboard_after_relogin`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/auth_dashboard_after_relogin.png`
- `nav_dashboard`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_dashboard.png`
- `nav_notifications_center`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_notifications_center.png`
- `nav_devices_manage`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_devices_manage.png`
- `nav_account_profile`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_account_profile.png`
- `nav_account_subscription`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_account_subscription.png`
- `nav_statistics`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_statistics.png`
- `nav_reports`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_reports.png`
- `nav_live_data`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_live_data.png`
- `nav_loads`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_loads.png`
- `nav_notifications`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_notifications.png`
- `nav_channels`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_channels.png`
- `nav_portal_support`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/nav_portal_support.png`
- `dashboard_before_controls`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_before_controls.png`
- `dashboard_after_device_shortcut`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_after_device_shortcut.png`
- `dashboard_after_loads_shortcut`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_after_loads_shortcut.png`
- `dashboard_after_controls_return`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/dashboard_after_controls_return.png`
- `profile_before_interaction`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_before_interaction.png`
- `profile_error_state`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_error_state.png`
- `profile_retry_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_retry_before.png`
- `profile_retry_error_state`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_retry_error_state.png`
- `profile_no_email_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_before.png`
- `profile_no_email_edited_before_save`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_edited_before_save.png`
- `profile_no_email_after_save`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_after_save.png`
- `profile_no_email_after_reload`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_no_email_after_reload.png`
- `devices_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_before.png`
- `devices_add_form_visible`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_add_form_visible.png`
- `devices_inputs_review`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/devices_inputs_review.png`
- `loads_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_before.png`
- `loads_error_state`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_error_state.png`
- `profile_focused_save_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_focused_save_before.png`
- `profile_focused_save_after_click`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_focused_save_after_click.png`
- `profile_focused_save_after_reload`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_focused_save_after_reload.png`
- `profile_direct_save_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_direct_save_before.png`
- `profile_direct_save_after_click`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_direct_save_after_click.png`
- `profile_direct_save_after_reload`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_direct_save_after_reload.png`
- `profile_after_guidance_fix_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_after_guidance_fix_before.png`
- `profile_after_guidance_fix_edited`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_after_guidance_fix_edited.png`
- `profile_after_guidance_fix_saved`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_after_guidance_fix_saved.png`
- `profile_after_guidance_fix_reloaded`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/profile_after_guidance_fix_reloaded.png`
- `loads_after_guidance_fix_before`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_after_guidance_fix_before.png`
- `loads_after_guidance_fix_error`: `C:/Users/Ahmad J Ahmad/Desktop/solardeya/docs/qa/screenshots/v34_subscriber_browser_qa/loads_after_guidance_fix_error.png`

## 12. Supplemental Route Render Checks

These are supplemental server-side checks, not a substitute for browser PASS marks. With a subscriber session injected in Flask test client, these routes returned 200:

- `/`, `/login?lang=ar`, `/register?lang=ar`, `/dashboard?lang=ar`, `/account/profile?lang=ar`, `/devices/manage?lang=ar`, `/loads?lang=ar`, `/notifications?lang=ar`, `/channels?lang=ar`, `/portal/support?lang=ar`, `/notifications/center?lang=ar`, `/reports?lang=ar`, `/statistics?lang=ar`, `/live-data?lang=ar`.

## 13. Verification Commands

- `node --check app/static/js/ui_guidance_v33.js`: PASS
- `python -m compileall app tests`: PASS
- `git diff --check`: PASS, with existing LF/CRLF warnings in the dirty worktree.
- Jinja parse check: PASS for `account_profile.html`, `dashboard.html`, `devices_manage.html`, `loads.html`, `notifications.html`, `channels.html`, `portal_support.html`, `notifications_center.html`, `reports.html`, `statistics.html`.

## 14. Files Changed

- `app/static/js/ui_guidance_v33.js`
- `docs/qa/v34_subscriber_real_browser_qa.md`
- `docs/qa/screenshots/v34_subscriber_browser_qa/*`

## 15. Forbidden-Path Confirmation

- Flow Graph files changed: no.
- Scheduler files changed: no.
- Notification dispatch/dedup logic changed: no.
- Schema/migration files changed: no.
- Report/PDF backend changed: no.
- Unsafe external Telegram/SMS/provider sends: no.

## 16. Risks

- `ui_guidance_v33.js` is currently an untracked file in this working tree. It is included because the app already loads this guidance layer and the real browser QA found a blocking behavior inside it.
- The worktree was dirty before this QA task. The report only claims the JS guidance fix and generated QA artifacts as changes from this pass.
- Full mobile and deep notification/support interactions still need a fresh browser session.

## 17. Recommended Next Phase

Run a focused follow-up browser pass after reopening the in-app browser pane: notifications controls, channels fields without external sends, support ticket/reply, notification center read/unread, reports/statistics filters, and mobile screenshots. Keep the guidance action-button fix as the first commit candidate because it unblocks real form actions across subscriber pages.

## 18. Explicit Git Add Commands

```powershell
git add app/static/js/ui_guidance_v33.js
git add docs/qa/v34_subscriber_real_browser_qa.md
git add docs/qa/screenshots/v34_subscriber_browser_qa
```

Suggested commit message: `v34: real subscriber browser QA with screenshots`
