import json
import logging
from datetime import datetime

from flask import Flask
from werkzeug.security import generate_password_hash

from .config import Config
from .extensions import db
from .models import AppDevice, AppUser, Setting
from .scheduler import start_scheduler

logger = logging.getLogger(__name__)


def create_app():
    _warn_legacy_routes_file()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    db.init_app(app)

    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.api_probe import probe_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(probe_bp)

    with app.app_context():
        db.create_all()
        _migrate_database()
        _ensure_default_settings()
        default_user = _ensure_default_app_user(app)
        default_device = _ensure_default_app_device(app, default_user)
        _backfill_foundation_ids(default_user.id, default_device.id)

    return app


def _warn_legacy_routes_file():
    import pathlib
    import warnings

    old_routes = pathlib.Path(__file__).parent / 'routes.py'
    if old_routes.exists():
        warnings.warn(
            (
                "\n\n*** تحذير: ملف routes.py القديم لا يزال موجودًا وقد يسبب تعارضًا!\n"
                "احذف الملف: app/routes.py\n"
            ),
            stacklevel=2,
        )


def _migrate_database():
    column_defs = {
        'app_user': {
            'username': 'VARCHAR(80)',
            'password_hash': "VARCHAR(255) DEFAULT ''",
            'full_name': 'VARCHAR(120)',
            'email': 'VARCHAR(120)',
            'role': "VARCHAR(50) DEFAULT 'admin'",
            'preferred_device_type': "VARCHAR(50) DEFAULT 'deye'",
            'is_active': 'BOOLEAN DEFAULT TRUE',
            'is_admin': 'BOOLEAN DEFAULT FALSE',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
        },
        'app_device': {
            'owner_user_id': 'INTEGER',
            'name': "VARCHAR(120) DEFAULT 'My Solar Device'",
            'device_type': "VARCHAR(50) DEFAULT 'deye'",
            'api_provider': "VARCHAR(50) DEFAULT 'deye'",
            'api_base_url': 'VARCHAR(255)',
            'external_device_id': 'VARCHAR(120)',
            'device_uid': 'VARCHAR(120)',
            'station_id': 'VARCHAR(120)',
            'plant_name': 'VARCHAR(120)',
            'timezone': "VARCHAR(64) DEFAULT 'Asia/Hebron'",
            'auth_mode': "VARCHAR(50) DEFAULT 'config'",
            'credentials_json': 'TEXT',
            'settings_json': 'TEXT',
            'is_active': 'BOOLEAN DEFAULT TRUE',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
        },
        'reading': {
            'user_id': 'INTEGER',
            'device_id': 'INTEGER',
            'pv1_power': 'REAL',
            'pv2_power': 'REAL',
            'pv3_power': 'REAL',
            'pv4_power': 'REAL',
            'inverter_temp': 'REAL',
            'dc_temp': 'REAL',
            'grid_voltage': 'REAL',
            'grid_frequency': 'REAL',
        },
        'sync_log': {'user_id': 'INTEGER', 'device_id': 'INTEGER'},
        'notification_log': {'user_id': 'INTEGER', 'device_id': 'INTEGER'},
        'user_load': {
            'user_id': 'INTEGER',
            'device_id': 'INTEGER',
            'priority': 'INTEGER DEFAULT 1',
            'is_enabled': 'BOOLEAN DEFAULT TRUE',
            'created_at': 'TIMESTAMP',
        },
        'event_log': {'user_id': 'INTEGER', 'device_id': 'INTEGER'},
        'smart_snapshot': {
            'user_id': 'INTEGER',
            'device_id': 'INTEGER',
            'reading_id': 'INTEGER',
            'created_at': 'TIMESTAMP',
            'local_hour': 'INTEGER',
            'local_minute_bucket': 'INTEGER',
            'is_day': 'BOOLEAN DEFAULT TRUE',
            'temperature_c': 'REAL',
            'clouds_percent': 'REAL',
            'weather_code': 'VARCHAR(40)',
            'solar_power': 'REAL DEFAULT 0',
            'home_load': 'REAL DEFAULT 0',
            'battery_soc': 'REAL DEFAULT 0',
            'battery_power': 'REAL DEFAULT 0',
            'grid_power': 'REAL DEFAULT 0',
            'inverter_power': 'REAL DEFAULT 0',
            'raw_surplus_w': 'REAL DEFAULT 0',
            'battery_charge_need_w': 'REAL DEFAULT 0',
            'actual_surplus_w': 'REAL DEFAULT 0',
            'minutes_to_sunset': 'REAL',
            'hours_until_sunrise': 'REAL',
            'quality_score': 'REAL DEFAULT 1.0',
            'source': "VARCHAR(30) DEFAULT 'auto_sync'",
        },
        'service_heartbeat': {
            'service_key': 'VARCHAR(120)',
            'service_label': 'VARCHAR(160)',
            'source': "VARCHAR(40) DEFAULT 'system'",
            'status': "VARCHAR(30) DEFAULT 'unknown'",
            'message': 'TEXT',
            'details_json': 'TEXT',
            'last_seen_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
        },
        'smart_recommendation_log': {
            'user_id': 'INTEGER',
            'device_id': 'INTEGER',
            'created_at': 'TIMESTAMP',
            'snapshot_id': 'INTEGER',
            'recommendation_type': 'VARCHAR(50)',
            'status_label': "VARCHAR(100) DEFAULT ''",
            'message_ar': "TEXT DEFAULT ''",
            'confidence_score': 'REAL DEFAULT 0',
            'matched_count': 'INTEGER DEFAULT 0',
            'predicted_next_hour_solar': 'REAL',
            'predicted_risk_level': "VARCHAR(30) DEFAULT 'unknown'",
            'raw_json': 'TEXT',
        },
    }

    conn = db.engine.raw_connection()
    dialect = getattr(db.engine.dialect, 'name', '').lower()
    try:
        cursor = conn.cursor()

        def existing_columns(table_name: str):
            try:
                if dialect == 'postgresql':
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                        """,
                        (table_name,),
                    )
                    return {row[0] for row in cursor.fetchall()}
                cursor.execute(f'PRAGMA table_info({table_name})')
                return {row[1] for row in cursor.fetchall()}
            except Exception:
                return set()

        for table_name, cols in column_defs.items():
            present = existing_columns(table_name)
            for column_name, definition in cols.items():
                if column_name in present:
                    continue
                try:
                    cursor.execute(
                        f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}'
                    )
                    logger.info('Added startup migration column %s.%s', table_name, column_name)
                except Exception as exc:
                    logger.warning(
                        'Startup migration skipped for %s.%s: %s',
                        table_name,
                        column_name,
                        exc,
                    )
        conn.commit()
    finally:
        conn.close()


def _ensure_default_settings():
    defaults = {
        'deye_plant_id': '',
        'deye_device_sn': '',
        'deye_plant_name': '',
        'deye_region': '',
        'battery_capacity_kwh': '5',
        'battery_reserve_percent': '20',
        'telegram_bot_token': '',
        'telegram_chat_id': '',
        'telegram_api_url': 'https://api.telegram.org',
        'sms_api_url': '',
        'sms_api_key': '',
        'sms_sender': '',
        'sms_recipients': '',
        'notifications_enabled': 'true',
        'daytime_solar_min_w': '50',
        'notification_rules_json': '',
        'weather_enabled': 'true',
        'weather_daily_summary_enabled': 'true',
        'weather_daily_summary_channel': 'telegram',
        'weather_change_alerts_enabled': 'true',
        'weather_change_alerts_channel': 'telegram',
        'weather_cloud_threshold': '60',
        'periodic_status_enabled': 'true',
        'periodic_status_interval_minutes': '30',
        'periodic_status_channel': 'telegram',
        'periodic_status_include_weather': 'true',
        'periodic_status_last_sent_at': '',
        'night_max_load_w': '500',
        'night_max_allowed_w': '500',
    }
    for key, value in defaults.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))
    db.session.commit()


def _settings_map():
    return {row.key: row.value for row in Setting.query.all()}


def _ensure_default_app_user(app):
    username = (app.config.get('ADMIN_USERNAME') or 'admin').strip() or 'admin'
    user = AppUser.query.filter_by(username=username).first()
    if user:
        changed = False
        if not user.password_hash:
            user.password_hash = generate_password_hash(app.config.get('ADMIN_PASSWORD') or 'admin123')
            changed = True
        if not user.role:
            user.role = 'admin'
            changed = True
        if not user.preferred_device_type:
            user.preferred_device_type = 'deye'
            changed = True
        if changed:
            user.updated_at = datetime.utcnow()
            db.session.commit()
        return user

    user = AppUser(
        username=username,
        password_hash=generate_password_hash(app.config.get('ADMIN_PASSWORD') or 'admin123'),
        full_name='مدير النظام',
        email='',
        role='admin',
        preferred_device_type='deye',
        is_active=True,
        is_admin=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _ensure_default_app_device(app, user):
    settings = _settings_map()
    station_id = (settings.get('deye_plant_id') or app.config.get('DEYE_PLANT_ID') or '').strip()
    device_uid = (settings.get('deye_device_sn') or app.config.get('DEYE_DEVICE_SN') or '').strip()
    name = (settings.get('deye_plant_name') or app.config.get('DEYE_PLANT_NAME') or '').strip() or 'My Solar Device'

    device = None
    if station_id:
        device = AppDevice.query.filter_by(station_id=station_id).first()
    if device is None and device_uid:
        device = AppDevice.query.filter_by(device_uid=device_uid).first()
    if device is None:
        device = AppDevice.query.order_by(AppDevice.id.asc()).first()

    credentials = {
        'deye_email': app.config.get('DEYE_EMAIL', ''),
        'deye_region': settings.get('deye_region') or app.config.get('DEYE_REGION', ''),
    }
    settings_json = {
        'plant_id': station_id,
        'device_sn': device_uid,
        'plant_name': name,
    }

    if device is None:
        device = AppDevice(
            owner_user_id=user.id,
            name=name,
            device_type='deye',
            api_provider='deye',
            api_base_url=app.config.get('DEYE_BASE_URL', ''),
            external_device_id=device_uid or None,
            device_uid=device_uid or None,
            station_id=station_id or None,
            plant_name=name,
            timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron'),
            auth_mode='config',
            credentials_json=json.dumps(credentials, ensure_ascii=False),
            settings_json=json.dumps(settings_json, ensure_ascii=False),
            is_active=True,
        )
        db.session.add(device)
        db.session.commit()
        return device

    changed = False
    if not device.owner_user_id:
        device.owner_user_id = user.id
        changed = True
    if not device.name:
        device.name = name
        changed = True
    if not device.device_type:
        device.device_type = 'deye'
        changed = True
    if not device.api_provider:
        device.api_provider = 'deye'
        changed = True
    if not device.api_base_url:
        device.api_base_url = app.config.get('DEYE_BASE_URL', '')
        changed = True
    if station_id and device.station_id != station_id:
        device.station_id = station_id
        changed = True
    if device_uid and device.device_uid != device_uid:
        device.device_uid = device_uid
        changed = True

    device.credentials_json = json.dumps(credentials, ensure_ascii=False)
    device.settings_json = json.dumps(settings_json, ensure_ascii=False)
    if changed:
        device.updated_at = datetime.utcnow()
    db.session.commit()
    return device


def _backfill_foundation_ids(user_id, device_id):
    updates = [
        ('reading', ['user_id', 'device_id']),
        ('sync_log', ['user_id', 'device_id']),
        ('notification_log', ['user_id', 'device_id']),
        ('user_load', ['user_id', 'device_id']),
        ('event_log', ['user_id', 'device_id']),
        ('smart_snapshot', ['user_id', 'device_id']),
        ('smart_recommendation_log', ['user_id', 'device_id']),
    ]
    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        dialect = getattr(db.engine.dialect, 'name', '').lower()
        placeholder = '%s' if dialect == 'postgresql' else '?'
        for table_name, columns in updates:
            for col in columns:
                value = user_id if col == 'user_id' else device_id
                try:
                    cursor.execute(
                        f'UPDATE {table_name} SET {col} = {placeholder} WHERE {col} IS NULL',
                        (value,),
                    )
                except Exception as exc:
                    logger.warning('Backfill skipped for %s.%s: %s', table_name, col, exc)
        conn.commit()
    finally:
        conn.close()


def _start_scheduler(app):
    return start_scheduler(app)
