import os
import secrets
import warnings
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class Config:
    _db_url = os.getenv('DATABASE_URL', '').strip()
    if _db_url.startswith('postgres://'):
        _db_url = 'postgresql://' + _db_url[len('postgres://'):]

    # ── Security ──────────────────────────────────────────────────────────────
    _raw_secret = os.getenv('SECRET_KEY', '')
    SECRET_KEY = _raw_secret if len(_raw_secret) >= 32 else secrets.token_hex(32)

    _admin_pass = os.getenv('ADMIN_PASSWORD', '')
    if not _admin_pass or _admin_pass in ('admin123', 'admin', 'password', 'change-this'):
        warnings.warn("ADMIN_PASSWORD is weak or not set in .env", stacklevel=2)
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = _admin_pass or 'admin123'

    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = _db_url or 'sqlite:///solar_v8.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    # ── App ───────────────────────────────────────────────────────────────────
    LOCAL_TIMEZONE = os.getenv('LOCAL_TIMEZONE') or os.getenv('TIMEZONE', 'Asia/Hebron')
    BATTERY_CAPACITY_KWH = float(os.getenv('BATTERY_CAPACITY_KWH', '5') or '5')
    BATTERY_RESERVE_PERCENT = float(os.getenv('BATTERY_RESERVE_PERCENT', '20') or '20')

    AUTO_SYNC_ENABLED = os.getenv('AUTO_SYNC_ENABLED', 'true').lower() == 'true'
    AUTO_SYNC_MINUTES = max(int(os.getenv('AUTO_SYNC_MINUTES', '5') or '5'), 1)

    # Limits & retention
    MAX_READINGS_QUERY = int(os.getenv('MAX_READINGS_QUERY', '2000') or '2000')
    SYNCLOG_RETENTION_DAYS = int(os.getenv('SYNCLOG_RETENTION_DAYS', '30') or '30')
    NOTIFICATIONLOG_RETENTION_DAYS = int(os.getenv('NOTIFICATIONLOG_RETENTION_DAYS', '90') or '90')

    # ── Battery known fallback values ─────────────────────────────────────────
    BATTERY_KNOWN_VOLTAGE = os.getenv('BATTERY_KNOWN_VOLTAGE', '')
    BATTERY_KNOWN_CURRENT = os.getenv('BATTERY_KNOWN_CURRENT', '')
    BATTERY_KNOWN_HEALTH = os.getenv('BATTERY_KNOWN_HEALTH', '')
    BATTERY_KNOWN_CAPACITY_AH = os.getenv('BATTERY_KNOWN_CAPACITY_AH', '')
    BATTERY_KNOWN_CYCLES = os.getenv('BATTERY_KNOWN_CYCLES', '')
    BATTERY_KNOWN_TEMPERATURE = os.getenv('BATTERY_KNOWN_TEMPERATURE', '')

    # ── Deye API ──────────────────────────────────────────────────────────────
    DEYE_BASE_URL = os.getenv('DEYE_BASE_URL', 'https://eu1-developer.deyecloud.com/v1.0').rstrip('/')
    DEYE_APP_ID = os.getenv('DEYE_APP_ID', '')
    DEYE_APP_SECRET = os.getenv('DEYE_APP_SECRET', '')
    DEYE_EMAIL = os.getenv('DEYE_EMAIL', '')
    DEYE_PASSWORD = os.getenv('DEYE_PASSWORD', '')
    DEYE_PASSWORD_HASH = os.getenv('DEYE_PASSWORD_HASH', '')
    DEYE_REGION = os.getenv('DEYE_REGION', 'EMEA')
    DEYE_PLANT_ID = os.getenv('DEYE_PLANT_ID', '')
    DEYE_DEVICE_SN = os.getenv('DEYE_DEVICE_SN', '')
    DEYE_LOGGER_SN = os.getenv('DEYE_LOGGER_SN', '')  # Logger SN (e.g. 3434586752) — needed for device/originalData
    DEYE_PLANT_NAME = os.getenv('DEYE_PLANT_NAME', '')
    DEYE_BATTERY_SN_MAIN = os.getenv('DEYE_BATTERY_SN_MAIN', '')
    DEYE_BATTERY_SN_MODULE = os.getenv('DEYE_BATTERY_SN_MODULE', '')

    DEYE_TOKEN_ENDPOINT = os.getenv('DEYE_TOKEN_ENDPOINT', '/account/token')
    DEYE_ACCOUNT_INFO_ENDPOINT = os.getenv('DEYE_ACCOUNT_INFO_ENDPOINT', '/account/info')
    DEYE_STATION_LIST_ENDPOINT = os.getenv('DEYE_STATION_LIST_ENDPOINT', '/station/list')
    DEYE_STATION_LATEST_ENDPOINT = os.getenv('DEYE_STATION_LATEST_ENDPOINT', '/station/latest')
    DEYE_STATION_HISTORY_ENDPOINT = os.getenv('DEYE_STATION_HISTORY_ENDPOINT', '/station/history')


# ── OAuth / Social Login ─────────────────────────────────────────────────────
_google_client_file = os.getenv('GOOGLE_CLIENT_SECRET_FILE', '').strip()
if not _google_client_file:
    for _candidate in BASE_DIR.glob('client_secret_*.json'):
        _google_client_file = str(_candidate)
        break

_google_json = {}
if _google_client_file:
    try:
        import json as _json
        _google_json = _json.loads(Path(_google_client_file).read_text(encoding='utf-8')).get('web', {})
    except Exception:
        _google_json = {}

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID') or _google_json.get('client_id', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET') or _google_json.get('client_secret', '')
GOOGLE_AUTH_URI = os.getenv('GOOGLE_AUTH_URI') or _google_json.get('auth_uri', 'https://accounts.google.com/o/oauth2/auth')
GOOGLE_TOKEN_URI = os.getenv('GOOGLE_TOKEN_URI') or _google_json.get('token_uri', 'https://oauth2.googleapis.com/token')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI') or ((_google_json.get('redirect_uris') or [''])[1] if len(_google_json.get('redirect_uris') or []) > 1 else (_google_json.get('redirect_uris') or [''])[0])
GOOGLE_USERINFO_URI = os.getenv('GOOGLE_USERINFO_URI', 'https://openidconnect.googleapis.com/v1/userinfo')

FACEBOOK_APP_ID = os.getenv('FACEBOOK_APP_ID', '')
FACEBOOK_APP_SECRET = os.getenv('FACEBOOK_APP_SECRET', '')
FACEBOOK_REDIRECT_URI = os.getenv('FACEBOOK_REDIRECT_URI', '')
