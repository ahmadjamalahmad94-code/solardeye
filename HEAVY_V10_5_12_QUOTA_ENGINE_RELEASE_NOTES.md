# Heavy v10.5.12 — Quota Engine Wiring

## Scope
Targeted patch based on v10.5.11. It wires existing quota rows to actual operations.

## Added
- `app/services/quota_engine.py`
- Central quota checks and consumption for:
  - `support_cases_limit` when a subscriber opens a new support message/ticket.
  - `sms_limit` after successful SMS sends. Count is based on successful recipients.
  - `telegram_limit` after successful Telegram messages/menu sends.
- Mobile Support API quota enforcement for opening support cases.
- Clear quota exceeded messages instead of silently allowing usage.

## Behavior
- Existing quota rows remain the source of truth.
- If a quota row does not exist for a tenant, the operation remains allowed.
- If limit is exhausted, the operation is blocked before sending/creating.
- Counts increase only after successful external SMS/Telegram send, and during support case creation.

## Notes
- This patch does not redesign UI.
- This patch does not add period reset automation yet. The current UI period remains metadata until reset logic is added in a later focused patch.
