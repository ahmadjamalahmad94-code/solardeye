# Heavy v10.5.33 — Push notifications backend

This release wires Firebase Cloud Messaging into the existing
notification rules engine so the mobile app can receive push
notifications for the same events that already fire on Telegram and
SMS. Push is **opt-in only** — defaults are unchanged.

## Highlights

- Added `firebase-admin` (6.6.0) as a direct dependency.
- New `app/services/push_dispatch.py` — single entry-point
  `send_push_to_user(user_id, title, body, data=None)` that lazily
  initialises the Firebase Admin SDK on first use, sends one FCM
  message per active token belonging to the user, auto-prunes tokens
  that Google reports as `UnregisteredError`, and returns a
  `(sent, failed)` count to the caller.
- Extended `dispatch_notification` in
  `app/blueprints/notifications.py` with two new channel values:
  - `'push'` — single-channel push send.
  - `'all'` — fans out to Telegram + SMS + push (mirrors the existing
    `'both'` shape).
  All other channel values (`'telegram'`, `'sms'`, `'both'`,
  `'none'`) are unchanged.
- `default_notification_rules()` is **not** modified. Push fires
  only when a user explicitly sets a rule's channel to `'push'` or
  `'all'`.
- New env vars (with safe defaults for dev):
  - `GOOGLE_APPLICATION_CREDENTIALS` — path to the Firebase service
    account JSON. Empty by default; the dispatcher silently no-ops
    when unset so dev / CI without secrets keeps working.
  - `PUSH_ENABLED` — explicit kill switch (`true` by default).
- `.env.example` and `render.yaml` updated to document the env
  vars. `render.yaml` does **not** define the secret file itself —
  on Render it must be added manually as a Secret File mounted at
  `/etc/secrets/firebase-service-account.json`.
- `.gitignore` hardened against accidental commit of any
  `*-firebase-adminsdk-*.json`, `serviceAccountKey.json`, or
  `firebase-service-account*.json`.
- Existing `POST /api/v1/notifications/push-tokens` and `DELETE
  /api/v1/notifications/push-tokens` endpoints already cover token
  registration and revocation — no new endpoints required for this
  release.

## Out of scope (deliberately)

- iOS / APNs (Android-only for now).
- Settings UI for per-rule push toggles (a Phase D follow-up).
- Deep linking from a tapped notification to a specific screen.
- Topic-based broadcast notifications.

## New/changed files

- `requirements.txt` (added `firebase-admin==6.6.0`)
- `app/services/push_dispatch.py` (new)
- `app/blueprints/notifications.py` (extended `dispatch_notification`)
- `.env.example` (documented two new env vars)
- `render.yaml` (added two new env-var entries; secret file added
  manually in dashboard, not committed)
- `.gitignore` (added Firebase service-account patterns)
- `tests/test_v101_push_dispatch.py` (new — 10 unit tests covering
  lazy init, send loop behaviour, error handling, token-leak
  defensiveness, and the `notifications.py` wiring)

## Production rollout (Render)

1. **Render dashboard → Service → Environment → Secret Files →
   Add Secret File.** Filename: `firebase-service-account.json`.
   Paste the entire service-account JSON downloaded from the
   Firebase Console.
2. The two new env vars in `render.yaml` will be picked up
   automatically on the next deploy:
   - `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/firebase-service-account.json`
   - `PUSH_ENABLED=true`
3. Trigger a deploy. The build step will install `firebase-admin`
   from the bumped `requirements.txt`.
4. Verify the dispatcher initialises by checking the Render logs
   for any "GOOGLE_APPLICATION_CREDENTIALS points at a missing
   file" warnings (there should be none).
5. From a Render shell, run:
   ```python
   from app.services.push_dispatch import send_push_to_user
   send_push_to_user(user_id=<your_id>, title='تجربة', body='Render OK')
   ```
   The phone running the latest Zynavolt mobile build should buzz.

## Roll-back

Set `PUSH_ENABLED=false` in the Render dashboard. The dispatcher
short-circuits to `(0, 0)` on every call — Telegram / SMS / inbox
mirroring continue untouched. No code redeploy needed.

## Test plan

```bash
pytest tests/test_v101_push_dispatch.py -v
```

All 10 tests pass with `firebase-admin` installed. They also pass
without it installed because each test stubs `firebase_admin` and
`firebase_admin.messaging` via `sys.modules` — the dispatcher's
lazy-import path makes this possible.
