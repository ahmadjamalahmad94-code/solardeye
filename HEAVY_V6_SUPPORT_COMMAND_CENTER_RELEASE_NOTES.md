# Heavy v6 — Support & Operations Command Center

## Implemented

- Added persistent `notification_event` table for stable notification state, read/unread, direct links, bell visibility and delivery/result fields.
- Added unified `support_case` table that overlays messages and tickets with one operational model: type, status, assignee, priority, SLA, tenant/user ownership, frozen/closed state and latest reply metadata.
- Added `support_audit_log` for support actions: create, reply, assignment/update, close/reopen.
- Added `canned_reply` table and seeded default Arabic canned replies.
- Added admin page: `/admin/support-command-center`.
  - Unified Inbox / Support Queue.
  - Filters: all, assigned to me, unassigned, urgent, waiting user, unanswered, closed.
  - SLA color indicators and overdue highlight.
  - Direct open links to the related subscriber support area.
  - Reopen action for closed/resolved cases.
  - Canned replies panel.
  - Support audit log panel.
- Reworked notification feed to prefer `notification_event` and fallback safely to old Heavy v5 notification calculation.
- Header bell still refreshes every 10 seconds, now reading from persistent notification events.
- Added `/notifications/mark-read` endpoint for read/unread workflows.
- Integrated case/audit/notification writes into subscriber support create/reply and admin reply/update flows.
- Added startup DDL/migration support for the new Heavy v6 tables.
- Added sidebar entry for the Support Command Center.

## Notes

- Existing message/ticket data is backfilled into `support_case` lazily when opening the command center.
- The old pages remain available; Heavy v6 is an operational layer on top, not a destructive replacement.
- Closed items remain frozen. The new command center exposes a clear `إعادة فتح` action.
