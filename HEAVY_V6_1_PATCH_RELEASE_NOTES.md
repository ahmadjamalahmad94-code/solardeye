# Heavy v6.1 Patch — Support Command Center + Site Polish

## Critical fixes
- Fixed the 500 error in `/admin/users/<id>?tab=support` caused by malformed `AdminActivityLog` construction.
- Fixed broken admin activity queries that accidentally mixed several model classes into a single query.
- Hardened admin activity logging so a logging failure no longer breaks the primary action.
- Corrected the Users Hub permission guard back to `can_manage_users`.
- Added permission aliases for support, finance, subscriptions, and integrations so future non-super-admin roles behave more predictably.

## Support Command Center upgrades
- Rebuilt `/admin/support-command-center` as a real operational dashboard instead of a plain table.
- Added KPI cards for active, overdue, unassigned, and closed cases.
- Added compact filter chips with counters.
- Added client-side search across subject, owner, and status.
- Added case cards with type, status, priority, owner, assignee, age, and SLA state.
- Added quick actions from the Command Center: assign to me, waiting user, close/freeze, and reopen.
- Added improved canned replies panel with one-click copy.
- Added audit timeline panel inside the command center.

## Notification improvements
- Added a Mark all read button in the notification bell dropdown.
- Improved notification dropdown actions and visual states.
- Added a client-side toast when new support notifications arrive.
- Added stable styling for `message` notification events.

## Site-wide visual polish
- Added Heavy v6.1 premium background treatment.
- Improved admin headers, cards, tables, forms, buttons, sidebar hover/active states, and responsive layout.
- Added global flash toasts for admin pages that previously did not show feedback messages.
- Updated sidebar labels to v6.1.
- Added Support Command Center shortcut to the admin dashboard quick links.

## Validation performed
- Python syntax compiled successfully with `compileall`.
- JavaScript syntax checked with `node --check`.
- Jinja templates parsed successfully.

Note: Runtime route testing could not be completed inside this sandbox because some production Python dependencies are not installed here and internet installation is unavailable. The patch is syntax-validated and focused on the exact 500 cause found in the code.
