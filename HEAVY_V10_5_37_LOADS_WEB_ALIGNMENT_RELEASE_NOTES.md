# Heavy v10.5.37 — Loads Recommendations: single source of truth

Replaces the v10.5.35/.36 parallel algorithm
(priority + headroom + essentials override +
`predicted_next_hour_surplus`) with a direct call into the web's
authoritative helper
`_smart_load_suggestions(latest, settings)` in
`app/blueprints/main.py`. The mobile endpoint is now a thin
client over the same function the web dashboard template at
`app/templates/dashboard.html` renders.

## Why

Owner-reported divergence: at the same moment (~sunset, 0 W
actual surplus), the web showed "يفضل تأجيلها" / "لا يوجد حمل
مناسب الآن" while the mobile showed "كل الأحمال مسموحة الآن"
with 9.1 kW total. The two surfaces disagreed because the
mobile algorithm was using:

* `predicted_next_hour_surplus` (ML forecast in kW) instead of
  the web's measured `actual_surplus_w` (raw surplus minus
  battery charge need),
* a priority + headroom + essentials-override decision tree
  instead of the web's simple `power_w ≤ safe_available + ε`
  rule.

Both differences are now eliminated by removing the parallel
algorithm entirely.

## Highlights

* `app/services/loads_recommendations.py` is now a TRANSFORMER —
  given the web's result dict, it shapes the mobile JSON
  envelope. No decision logic, no algorithm, no thresholds.
* `mobile_load_recommendations()` in `mobile_api.py` calls
  `_smart_load_suggestions(latest, settings)` from the web
  blueprint after binding `g.current_user` / `g.current_device`
  so the helper's scoped queries pick up the bearer-auth user.
* Mobile envelope gains a new `surplus` block carrying the
  web's headline metrics (safe / raw / battery_need / actual +
  phase + night_max). The mobile UI can render the same numbers
  the dashboard shows without re-querying.
* Decision level mapping (good / caution / warning / unknown)
  is derived from the web's output, not invented locally:
  * `can_run` non-empty → good
  * `can_run` empty + `safe_available > 0` → caution
  * `can_run` empty + `safe_available == 0` + day → warning
  * night phase with hold-only → caution (not warning — lack of
    solar at night is expected, not an alert state)
  * no enabled loads → unknown

## Out of scope (deliberately)

* Per-load schedule recommendations.
* Load remote control.
* Loads recommendation history.
* Re-implementing the web's algorithm anywhere on mobile.

## New/changed files

* `app/services/loads_recommendations.py` — full rewrite.
  `build_loads_recommendations` removed. New
  `transform_loads_suggestions(web_result, ...)` produces the
  mobile envelope.
* `app/blueprints/mobile_api.py` —
  `mobile_load_recommendations()` rewritten to call the web
  helper directly. Removed:
  * `build_smart_energy_advice` invocation,
  * weather fetch (`_smart_load_suggestions` does its own),
  * `station_coords_unavailable` / `weather_unreachable`
    branches (the helper degrades gracefully).
* `tests/test_v102_loads_recommendations.py` — full rewrite,
  8 new cases covering the transformer's behaviour against
  synthetic web-result dicts (day/night, mixed/hold-only,
  reading_unavailable envelope, surplus block completeness,
  totals correctness, endpoint registration).

## NOT touched

* `app/blueprints/main.py:_smart_load_suggestions` — consumed
  read-only as the source of truth.
* `app/blueprints/helpers.py:compute_actual_solar_surplus` —
  consumed transitively, never re-implemented.
* `app/models.py` — no schema delta.
* `app/templates/**` — no web UI change. Flow Graph untouched.
* Phase D / push wiring — entirely unrelated path.

## Production rollout (Render)

Auto-deploy on `git push origin main`. No new env vars, no new
Secret File, no new dependencies. Same endpoint contract;
response shape gains the `surplus` block (additive — old
clients ignore it gracefully).

Smoke after deploy:

```bash
curl -sS -H 'Authorization: Bearer <token>' \
  https://solardeye.onrender.com/api/mobile/loads/recommendations \
  | python -m json.tool
```

The decision returned must MATCH the web dashboard's
"التوصيات الذكية للأحمال" widget at the same moment.

## Roll-back

`git revert`. The endpoint returns to v10.5.36 internal
algorithm. No data loss, no schema delta.

## Test plan

```bash
pytest tests/test_v102_loads_recommendations.py -v
```

→ 8 passed (T1–T8). All cases run as pure-function tests against
synthetic web results — no DB, no Flask context.

For the cross-surface integration check, the owner verifies on
their account that:
1. Mobile `available_w` / `actual_w` / `safe_available_w` match
   the web dashboard's surplus card.
2. The mobile's `items[].allowed` set is identical to the web's
   `can_run` list (by load id).
3. The mobile's `items[].denied` set is identical to the web's
   `hold` list (by load id).
