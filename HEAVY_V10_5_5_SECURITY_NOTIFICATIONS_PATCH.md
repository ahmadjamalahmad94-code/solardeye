# Heavy v10.5.5 — Security Notifications Patch

Scope: security-only hotfix on top of v10.5.3.

- Subscribers are blocked from rendering any `/admin/*` page even if an old notification contains an admin URL.
- Notification URLs are sanitized according to the target user role.
- Subscriber notification links resolve to portal support/dashboard pages.
- Admin/staff notification links may still resolve to admin pages.
- Empty/unknown roles no longer become admin-like automatically.
- No UI pages were redesigned in this patch.
