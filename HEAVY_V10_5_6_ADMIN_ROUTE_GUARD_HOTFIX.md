# Heavy v10.5.6 — Admin Route Guard Hotfix

Small security-only patch on v10.5.5.

## Fixed
- Disabled/inactive subscriber sessions no longer fall back to the default system admin.
- Subscriber sessions can no longer render `/admin/*` pages; they are redirected to their subscription page.
- `get_current_user()` no longer returns a default system user during browser requests without a valid session user.
- Old notification links that point to admin URLs are sanitized to subscriber-safe portal/subscription URLs.

## Scope
- No UI redesign.
- No route restructuring.
- No main.py split.
