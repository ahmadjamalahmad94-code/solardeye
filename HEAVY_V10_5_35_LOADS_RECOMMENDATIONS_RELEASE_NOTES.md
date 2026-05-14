# Heavy v10.5.35 — Loads Recommendations (real backend decision)

Replaces the `mobile_recommendations_deferred` stub on
`GET /api/mobile/loads/recommendations` with real per-load
allow/deny decisions derived from the existing `smart_engine`
output (the same function the web dashboard renders). Implemented
per the canonical spec at `docs/LOADS_BACKEND_SPEC.md` in the
mobile repo, with full owner sign-off on the algorithm before
any code was written.

## Highlights

- **Flask backend is the sole decision source.** No mobile-side
  heuristics, no mock data. The endpoint pulls the latest reading,
  weather, and settings the same way `/insights` does, calls
  `build_smart_energy_advice` (verbatim — no re-implementation),
  and feeds the output into a pure decision function.
- **No `UserLoad` model change.** Every input the algorithm needs
  (`name`, `power_w`, `priority`, `is_enabled`) already exists as
  a column. The recommendation is computed at request time, not
  stored.
- **Priority-aware surplus accounting** — loads consume the
  predicted next-hour surplus in priority order (`priority ASC`,
  essentials first). A headroom factor tightens as the system
  level worsens: 1.0× (good), 1.3× (caution), 1.8× (warning).
- **Conservative on critical / unknown** — critical denies every
  load with a unified reason; unknown only allows priority ≤ 1
  essentials (defaults to "أجِّل غير الضروري" otherwise).
- **Essentials override** on non-critical levels: priority ≤ 1
  always runs even when surplus is insufficient, with an honest
  reason string.
- **Honest unavailable envelopes** for the same reasons the
  `/insights` endpoint surfaces (`reading_unavailable` /
  `station_coords_unavailable` / `weather_unreachable`) plus a
  new `no_active_device` code for accounts with zero devices.

## Out of scope (deliberately)

- Per-load schedule recommendations ("turn on at 14:00") — only
  the boolean allow/deny is computed.
- User-defined load classes beyond the existing `UserLoad` rows.
- Load remote control / actuation.
- Loads recommendation history / trends.
- Per-load notifications.

## New/changed files

- `app/services/loads_recommendations.py` — **new**.
  `build_loads_recommendations(...)` is a pure function over
  `(enabled_loads, advice_dict, scope, generated_at)`. No DB or
  Flask context dependencies — every dependency is passed in.
  Tunables (`HEADROOM_BY_LEVEL`, `ESSENTIAL_PRIORITY_THRESHOLD`)
  are module-level constants so the owner can tune after the
  first on-device run.
- `app/blueprints/mobile_api.py` — replaced the stub body of
  `mobile_load_recommendations()` with the real handler. Fetches
  latest reading + weather + settings via the same helpers
  `device_insights` uses; binds `g.current_user` /
  `g.current_device` for the `smart_engine` call; restores them
  in a `finally`.
- `tests/test_v102_loads_recommendations.py` — **new**. 8 cases
  (no loads / critical / unknown / good-surplus / warning-essential
  override / reading-unavailable envelope / None-surplus / endpoint
  registration smoke). All pass under pytest 9 / Python 3.14
  locally; no live DB required.

## NOT touched (per owner constraint)

- `app/models.py` — no `UserLoad` column added or modified.
- `app/blueprints/notifications.py` — no rules / dispatcher change.
- `app/blueprints/smart_engine.py` — consumed read-only.
- `app/templates/**` — no web UI change. Flow Graph untouched.
- `app/static/css/**` — no styling change.
- Phase D / push wiring — entirely unrelated path.

## Production rollout (Render)

Standard auto-deploy on `git push origin main`. No new env vars,
no new Secret File, no new dependencies. The endpoint replaces a
stub — no caller's contract breaks.

Manual smoke after deploy from a Render shell:

```bash
curl -sS -H 'Authorization: Bearer <real-access-token>' \
  https://solardeye.onrender.com/api/mobile/loads/recommendations \
  | python -m json.tool
```

Expect `available: true` + non-empty `items` if the user has at
least one enabled load + a recent reading + weather. Expect
`available: false` with `reading_unavailable` / similar reason
otherwise.

## Roll-back

`git revert` the commit. The endpoint reverts to the stub
(`available: false`, `reason: 'mobile_recommendations_deferred'`).
No data loss. No schema delta.

## Test plan

```bash
pytest tests/test_v102_loads_recommendations.py -v
```

→ 8 passed, 1 warning (pre-existing ADMIN_PASSWORD bootstrap
notice — not raised by this change).

## Response example (success)

```json
{
  "available": true,
  "reason": null,
  "message": null,
  "scope": { "mode": "device", "device_id": 12 },
  "decision": {
    "headline": "🟡 ابقَ منتبهاً",
    "summary": "البطارية منخفضة. حاول تأجيل الأحمال غير الضرورية.",
    "level": "caution",
    "confidence": "medium"
  },
  "items": [
    {
      "load_id": 21,
      "name": "ثلاجة",
      "power_w": 200,
      "priority": 1,
      "allowed": true,
      "reason": "الفائض المتوقع كافٍ (1500 و)"
    },
    {
      "load_id": 24,
      "name": "غسالة",
      "power_w": 1200,
      "priority": 2,
      "allowed": true,
      "reason": "الفائض المتوقع كافٍ (1300 و)"
    },
    {
      "load_id": 27,
      "name": "فرن كهربائي",
      "power_w": 2500,
      "priority": 3,
      "allowed": false,
      "reason": "الفائض المتوقع لا يكفي (2500 و)"
    }
  ],
  "totals": {
    "enabled_load_count": 3,
    "allowed_count": 2,
    "denied_count": 1,
    "allowed_power_w": 1400.0,
    "denied_power_w": 2500.0
  },
  "generated_at": "2026-05-14T15:30:00"
}
```
