# Heavy v10.5.9 — Subscriber 360 Control & Polish

Focused patch for the Subscriber 360 page only.

## Changes

- Activity tab now shows Arabic-friendly activity labels in Arabic mode.
- Activity list is limited to the latest 10 rows and avoids clipped dates.
- Quota form now uses ready-made quota keys with an optional custom key.
- Quota save now creates or updates by key and shows success/failure messages.
- Subscription date fields are proper date pickers.
- Subscription tab now displays remaining days based on trial/end dates.
- Added per-subscriber portal page visibility controls inside Subscriber 360.
- Hidden per-subscriber portal pages are removed from the subscriber sidebar and guarded from direct access.
- Support mailbox accents are contained inside cards and message spacing was improved.

## Scope

No broad layout or main.py split changes. This patch only touches Subscriber 360 behavior/UI and per-user portal visibility support.
