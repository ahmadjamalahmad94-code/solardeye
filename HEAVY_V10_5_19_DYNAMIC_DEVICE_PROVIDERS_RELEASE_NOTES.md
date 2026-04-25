# Heavy v10.5.19 — Dynamic Device Providers

## Scope
Limited implementation for the device management step.

## What changed
- Device add/edit forms now start with a provider selector.
- Fields are generated dynamically from the provider catalog.
- Deye remains compatible with the existing live sync engine.
- Other providers store their required connection fields cleanly in `credentials_json` and `settings_json` for staged adapters.
- Existing secret fields are masked/preserved when left blank.
- Device list shows provider/type, masked identifiers, and connection status more clearly.

## Providers
The UI uses the existing energy integration provider catalog, including Deye, SolarEdge, Enphase, Victron, Fronius, SMA, Tesla, Huawei, Shelly, Solarman, Sungrow, GoodWe, Solis, OpenDTU, MQTT, Home Assistant and others already present in the catalog.

## Not changed
- No remote control commands were added.
- Non-Deye live sync is not force-enabled here; adapters can be connected provider by provider.
- Registration/onboarding deep flow remains for the next step.
