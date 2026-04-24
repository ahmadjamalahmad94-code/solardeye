# Heavy v5.6 — Notification Center Root Fix + Frozen Closed Support

## Main fixes
- Fixed `/notifications/center` and `/notification-center` with a direct login guard instead of the missing `_login_guard()` helper.
- Notification Center now opens safely even if support items cannot be loaded.
- Closed mail threads and closed support tickets are now frozen:
  - no new admin replies
  - no new subscriber replies
  - visible as archived closed items under the open support board
- Admin user profile support tab now splits:
  - open messages/tickets
  - closed/frozen messages/tickets
- Subscriber support page now splits:
  - open support conversations
  - closed/frozen archive
- Closing an item appends a final visible closing message.

## Render compatibility
Kept unchanged:
- `wsgi:app`
- Python `3.11.9`
- `psycopg2-binary==2.9.9`
