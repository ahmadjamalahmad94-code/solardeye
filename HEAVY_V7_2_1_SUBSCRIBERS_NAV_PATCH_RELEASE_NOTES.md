# Heavy v7.2.1 — Subscribers Navigation Alignment Patch

## Purpose
This patch resolves the mismatch where the new Subscribers CRM page existed but the admin sidebar still opened the older Users Hub page.

## Changes
- The admin sidebar now opens **Subscribers CRM** at `/admin/subscribers` as the primary subscriber management screen.
- `/admin/users` now redirects to `/admin/subscribers` for normal GET navigation.
- The old users page remains available as `/admin/users/legacy` and is labeled **System users / مستخدمو النظام**.
- The Subscribers CRM quick actions include a **System users** button for maintenance/admin-level user work.
- Back/cancel links from user forms and subscriber profile pages now return to Subscribers CRM.
- Toggle/delete actions return safely to the page they came from.
- Cache bust updated to `v=7.2.1`.

## Recommended usage
- Use `/admin/subscribers` for daily subscriber operations.
- Use `/admin/users/legacy` only for legacy/system user maintenance.
