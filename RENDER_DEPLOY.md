# Render deploy

## Build Command
`pip install -r requirements.txt`

## Start Command
`gunicorn --bind 0.0.0.0:$PORT app:app`

## Required Environment Variables
- `DATABASE_URL` = Internal Database URL from Render Postgres
- `SECRET_KEY` = long random secret
- `LOCAL_TIMEZONE` = `Asia/Hebron`
- `TELEGRAM_BOT_TOKEN` = your Telegram bot token
- `TELEGRAM_CHAT_ID` = your Telegram chat id
- `ADMIN_USERNAME` = admin
- `ADMIN_PASSWORD` = choose a strong password

## Optional
- `AUTO_SYNC_ENABLED=true`
- `AUTO_SYNC_MINUTES=5`

## Telegram webhook
After deploy, open:
`https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://<YOUR-RENDER-DOMAIN>/telegram/webhook`
