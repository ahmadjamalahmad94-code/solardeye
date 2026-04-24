# Heavy v6.3 — Subscriber Support Mailbox UX

This patch extends the Heavy v6.2 mailbox experience to the subscriber-facing support page.

## Main changes

- Rebuilt `/portal/support` and `/support` as a compact mailbox instead of large support cards.
- Added a subscriber inbox list with compact rows for messages and tickets.
- Added a conversation preview panel with chat-style message history.
- Added a right-side request inspector showing type, status, priority, category, responsible team/admin, and last update.
- Moved the “new request” composer into the side panel so the page behaves more like an email/support client.
- Added client-side filters for all/open/archive without page reload.
- Added search across the subscriber’s support history.
- Added list/card view toggle for the subscriber support page.
- Translated raw status and priority values into friendly Arabic/English labels.
- Kept closed/resolved support items frozen and clearly marked as archive.
- Updated support anchors to `#case-mail-ID` / `#case-ticket-ID` for the new mailbox selection behavior.
- Added assignee data to subscriber support rows so the portal can show the assigned support owner when available.
- Updated static cache busting from v6.2 to v6.3.

## Suggested QA

1. Login as a subscriber and open `/portal/support?lang=ar&type=all`.
2. Create a new message from the side panel.
3. Create a new ticket and attach a device if available.
4. Reply to an open message and ticket.
5. Confirm the selected conversation remains active after submit.
6. Confirm open/archive filters work without reload.
7. Confirm search hides unrelated rows and selects the first visible row when needed.
8. Confirm closed/resolved items do not show a reply composer.
9. Confirm admin replies link back to the correct subscriber conversation from notifications.
