# Render deploy

## What was fixed for Render
- Start entrypoint uses `wsgi:app` to avoid the `app.py` vs `app/` naming conflict.
- Python is pinned with `.python-version` to `3.11.9` so Render won't default to Python `3.14.x`.
- PostgreSQL driver is `psycopg2-binary==2.9.9`, which is compatible with Python 3.11 for this app.

## Build Command
`pip install -r requirements.txt`

## Start Command
`gunicorn --bind 0.0.0.0:$PORT wsgi:app`

## Required Environment Variables
- `DATABASE_URL` = Internal Database URL from Render Postgres
- `SECRET_KEY` = long random secret (32+ chars)
- `ADMIN_USERNAME` = admin username for login
- `ADMIN_PASSWORD` = strong password
- `LOCAL_TIMEZONE` = `Asia/Hebron`

## Recommended Environment Variables
- `AUTO_SYNC_ENABLED=true`
- `AUTO_SYNC_MINUTES=5`
- `PYTHON_VERSION=3.11.9` (optional if `.python-version` is committed, but safe to keep)

## Important notes
- Telegram settings are stored inside the app settings page/database (`telegram_bot_token`, `telegram_chat_id`). They are **not required** as Render environment variables unless you changed the code.
- On first deploy, the app will create tables automatically.
- If the service restarts without a `DATABASE_URL`, it will fall back to SQLite locally. On Render, always attach PostgreSQL and set `DATABASE_URL`.

## Telegram webhook
After deploy, open:
`https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://<YOUR-RENDER-DOMAIN>/telegram/webhook`
