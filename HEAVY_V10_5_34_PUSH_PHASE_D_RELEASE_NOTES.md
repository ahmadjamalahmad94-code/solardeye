# Heavy v10.5.34 — Push notifications, Phase D

Backend half of Phase D for v101 push notifications. Surfaces a
single "Push notifications" master toggle in the mobile Settings
screen and attaches an `event_type` to every FCM payload so the
mobile app can deep-link the tap into the natural destination.

Push remains opt-in: defaults are unchanged, and the additive
fan-out only fires when the user explicitly flips the new toggle
ON.

## Highlights

- **`push_enabled` master toggle** — new boolean setting key
  surfaced on `GET /api/mobile/notifications/settings` under
  `channels.push`. When ON, every rule that fires on Telegram /
  SMS / both ALSO sends push, without forcing the user to edit
  per-rule `channel_pref` values. When OFF (the default), push
  only fires for rules whose `channel_pref` is explicitly
  `'push'` or `'all'`.
- **Channels payload extended** with a `push` block:
  `{enabled, configured, token_count}`. `configured: true` means
  the mobile app has registered at least one active
  `MobilePushToken` for this user.
- **`supported_channel_values`** in the settings payload now
  includes `'push'` and `'all'`, so the mobile editor can offer
  them in any per-rule channel picker (a UI affordance the mobile
  app may add later).
- **Deep-link payload** — `dispatch_notification` now passes
  `data={'event_type': <classification>}` to `send_push_to_user`.
  The mobile push overlay reads this to route a tap into the
  natural destination (battery_status → Battery Lab,
  weather_alert → Weather, load_alert → Loads, …).
- **Additive push pass** — appended after the existing channel
  loop in `dispatch_notification`. Skips when `'push'` was
  already in the dispatched channels (avoids double-send) and
  when `channel_pref` is `'none'` (hard opt-out is preserved).
  Logs as `channel='push'` with response_text suffixed
  `(additive)` so the audit trail distinguishes the two paths.

## Out of scope

- Per-rule channel picker UI — the mobile Settings screen still
  shows only the global on/off switches per channel. A future
  pass can add a per-rule editor; the backend already accepts
  `'push'` / `'all'` in the rules payload.
- iOS / APNs.
- Topic-based broadcasts.

## New/changed files

- `app/blueprints/notifications.py`
  - `NOTIFICATION_SECTION_FIELDS['general']['checkbox']` adds
    `'push_enabled'` so the mobile PATCH endpoint will accept it.
  - `dispatch_notification` attaches `data={'event_type': ...}`
    to every `'push'` channel send.
  - `dispatch_notification` adds the additive push pass after
    the channel loop, gated on `settings.get('push_enabled')`.
- `app/blueprints/mobile_api.py`
  - `_MOBILE_NOTIFICATION_CHANNEL_VALUES` includes `'push'` and
    `'all'` so per-rule channel PATCH accepts them.
  - `_mobile_channels_status` returns a `push` channel block
    with `enabled` / `configured` / `token_count`.
  - `_mobile_push_token_count_for_request` — new helper that
    counts active tokens for the bearer-authenticated user, with
    defensive try/except so a count failure never tanks the
    settings payload.
  - `_mobile_notification_settings_payload` extends
    `supported_channel_values` with `'push'` and `'all'`.

## Production rollout (Render)

This is a behaviour change but no schema migration: the
`push_enabled` setting is stored in the existing key/value
`Setting` table, and `MobilePushToken` already exists.

1. Push to `main` → Render auto-deploys.
2. Existing users see the new "الإشعارات الفورية (Push)" row in
   Settings → الإشعارات. Default OFF, so no push fires until
   they flip it on.
3. The mobile app must be on at least the v101 Phase D build for
   the toggle to appear (the channels.push block parsing was
   added in the same release window).

## Roll-back

Two layers:

- Soft: set `PUSH_ENABLED=false` in Render env (already shipped
  in v10.5.33). The dispatcher short-circuits to (0, 0) on every
  call; the toggle still appears in Settings but never fires.
- Hard: revert this commit. The `'push_enabled'` setting becomes
  unknown to the mobile editor again (would surface as an
  `unsupported_field` 400 on PATCH); existing rows in `Setting`
  are harmless — no rule processing path reads them anymore.

## Test plan

```bash
pytest tests/test_v101_push_dispatch.py tests/test_v33_beta.py tests/test_v43_mobile_mirror.py
```

Existing 10 dispatcher tests still pass; the additive push
behaviour is exercised indirectly through manual end-to-end on a
real device. A focused unit test for the additive branch can be
added later if regression risk grows.
