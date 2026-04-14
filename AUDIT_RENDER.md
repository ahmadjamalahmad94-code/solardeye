# Render compatibility audit

## Fixed / verified
1. **Entrypoint conflict fixed**
   - Project contains both `app.py` and `app/` package.
   - Correct startup target is `wsgi:app`, not `app:app`.

2. **Python version risk handled**
   - Render currently defaults new Python services to Python 3.14.3.
   - This project uses `psycopg2-binary==2.9.9`, which caused runtime/import issues under Python 3.14 in your logs.
   - `.python-version` was added to pin Python `3.11.9`.

3. **Requirements look complete for the current imports**
   - Flask
   - Flask-SQLAlchemy
   - requests
   - APScheduler
   - reportlab
   - arabic-reshaper
   - python-bidi
   - gunicorn
   - psycopg2-binary
   - python-dotenv

## Things that are not fatal but important
1. **Weak admin password warning**
   - If `ADMIN_PASSWORD` is missing or weak, the app still starts, but logs a warning.

2. **Scheduler jobs**
   - Auto-sync and notifications start in-process.
   - With one Gunicorn worker this is acceptable.
   - If you increase worker count later, background jobs could duplicate.

3. **Telegram setup**
   - Telegram is configured through app settings/database, not necessarily Render env vars.

## Recommended Render values
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT wsgi:app`
- Python: `3.11.9`
