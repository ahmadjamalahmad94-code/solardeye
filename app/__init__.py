import json
import logging
from flask import Flask
from werkzeug.security import generate_password_hash

from .config import Config
from .extensions import db
from .models import Setting, AppUser, AppDevice


def create_app():
    import pathlib as _pl

    _old_routes = _pl.Path(__file__).parent / 'routes.py'
    if _old_routes.exists():
        import warnings
        warnings.warn(
            "\n\n*** تحذير: ملف routes.py القديم لا يزال موجوداً وسيسبب تعارضاً!\n"
            "احذف الملف: app/routes.py\n",
            stacklevel=2,
        )

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    db.init_app(app)

    # Register blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.api_probe import probe_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(probe_bp)

    with app.app_context():
        db.create_all()
        _migrate_database(db)
        _ensure_default_settings()
        _ensure_foundation_entities(app)
        _backfill_foundation_links(db)

    return app


def _migrate_database(db):
    """
    Safe startup migration: creates missing columns for existing tables without
    requiring Alembic. Supports both SQLite and PostgreSQL.
    IMPORTANT: This foundation migration does not change runtime logic; it only
    prepares schema for future multi-user / multi-device work.
    """
    new_columns = [
        # Existing app tables
        ('reading', 'pv1_power', 'REAL'),
        ('reading', 'pv2_power', 'REAL'),
        ('reading', 'pv3_power', 'REAL'),
        ('reading', 'pv4_power', 'REAL'),
        ('reading', 'inverter_temp', 'REAL'),
        ('reading', 'dc_temp', 'REAL'),
        ('reading', 'grid_voltage', 'REAL'),
        ('reading', 'grid_frequency', 'REAL'),
        ('user_load', 'priority', 'INTEGER DEFAULT 1'),
        ('user_load', 'is_enabled', 'BOOLEAN DEFAULT 1'),
        ('user_load', 'created_at', 'DATETIME'),

        # Smart archive foundation
        ('smart_snapshot', 'user_id', 'INTEGER'),
        ('smart_snapshot', 'device_id', 'INTEGER'),
        ('smart_snapshot', 'reading_id', 'INTEGER'),
        ('smart_snapshot', 'created_at', 'TIMESTAMP'),
        ('smart_snapshot', 'local_hour', 'INTEGER'),
        ('smart_snapshot', 'local_minute_bucket', 'INTEGER'),
        ('smart_snapshot', 'is_day', 'BOOLEAN DEFAULT 1'),
        ('smart_snapshot', 'temperature_c', 'REAL'),
        ('smart_snapshot', 'clouds_percent', 'REAL'),
        ('smart_snapshot', 'weather_code', 'VARCHAR(40)'),
        ('smart_snapshot', 'solar_power', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'home_load', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'battery_soc', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'battery_power', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'grid_power', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'inverter_power', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'raw_surplus_w', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'battery_charge_need_w', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'actual_surplus_w', 'REAL DEFAULT 0'),
        ('smart_snapshot', 'minutes_to_sunset', 'REAL'),
        ('smart_snapshot', 'hours_until_sunrise', 'REAL'),
        ('smart_snapshot', 'quality_score', 'REAL DEFAULT 1.0'),
        ('smart_snapshot', 'source', "VARCHAR(30) DEFAULT 'auto_sync'"),

        ('smart_recommendation_log', 'user_id', 'INTEGER'),
        ('smart_recommendation_log', 'device_id', 'INTEGER'),
        ('smart_recommendation_log', 'created_at', 'TIMESTAMP'),
        ('smart_recommendation_log', 'snapshot_id', 'INTEGER'),
        ('smart_recommendation_log', 'recommendation_type', 'VARCHAR(50)'),
        ('smart_recommendation_log', 'status_label', "VARCHAR(100) DEFAULT ''"),
        ('smart_recommendation_log', 'message_ar', "TEXT DEFAULT ''"),
        ('smart_recommendation_log', 'confidence_score', 'REAL DEFAULT 0'),
        ('smart_recommendation_log', 'matched_count', 'INTEGER DEFAULT 0'),
        ('smart_recommendation_log', 'predicted_next_hour_solar', 'REAL'),
        ('smart_recommendation_log', 'predicted_risk_level', "VARCHAR(30) DEFAULT 'unknown'"),
        ('smart_recommendation_log', 'raw_json', 'TEXT'),

        # Multi-user foundation only (no runtime behavior change yet)
        ('reading', 'user_id', 'INTEGER'),
        ('reading', 'device_id', 'INTEGER'),
        ('sync_log', 'user_id', 'INTEGER'),
        ('sync_log', 'device_id', 'INTEGER'),
        ('notification_log', 'user_id', 'INTEGER'),
        ('notification_log', 'device_id', 'INTEGER'),
        ('user_load', 'user_id', 'INTEGER'),
        ('user_load', 'device_id', 'INTEGER'),
        ('event_log', 'user_id', 'INTEGER'),
        ('event_log', 'device_id', 'INTEGER'),
    ]

    conn = db.engine.raw_connection()
    dialect = getattr(db.engine.dialect, 'name', '').lower()
    logger = logging.getLogger(__name__)
    try:
        cursor = conn.cursor()

        def _existing_columns(table_name: str):
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
                cursor.execute(f"PRAGMA table_info({table_name})")
                return {row[1] for row in cursor.fetchall()}
            except Exception:
                return set()

        existing = {}
        for table, _, _ in new_columns:
            if table not in existing:
                existing[table] = _existing_columns(table)

        added = []
        for table, col, col_def in new_columns:
            if col in existing.get(table, set()):
                continue
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                added.append(f"{table}.{col}")
                existing.setdefault(table, set()).add(col)
            except Exception as exc:
                logger.warning("DB migration skipped for %s.%s: %s", table, col, exc)

        conn.commit()
        if added:
            logger.info("DB migration added columns: %s", added)
    finally:
        conn.close()


def _ensure_default_settings():
    defaults = {
        'deye_plant_id': '', 'deye_device_sn': '', 'deye_plant_name': '', 'deye_region': '',
        'battery_capacity_kwh': '5', 'battery_reserve_percent': '20',
        'telegram_bot_token': '', 'telegram_chat_id': '', 'telegram_api_url': 'https://api.telegram.org',
        'sms_api_url': '', 'sms_api_key': '', 'sms_sender': '', 'sms_recipients': '',
        'notifications_enabled': 'true', 'daytime_solar_min_w': '50', 'notification_rules_json': '',
        'weather_enabled': 'true', 'weather_daily_summary_enabled': 'true',
        'weather_daily_summary_channel': 'telegram', 'weather_change_alerts_enabled': 'true',
        'weather_change_alerts_channel': 'telegram', 'weather_cloud_threshold': '60',
        'periodic_status_enabled': 'true', 'periodic_status_interval_minutes': '30',
        'periodic_status_channel': 'telegram', 'periodic_status_include_weather': 'true',
        'periodic_status_last_sent_at': '', 'night_max_load_w': '500', 'night_max_allowed_w': '500',
    }
    for key, value in defaults.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))
    db.session.commit()


def _ensure_foundation_entities(app):
    logger = logging.getLogger(__name__)
    username = (app.config.get('ADMIN_USERNAME') or 'admin').strip() or 'admin'
    password = app.config.get('ADMIN_PASSWORD') or 'admin123'

    default_user = AppUser.query.filter_by(username=username).first()
    if not default_user:
        default_user = AppUser(
            username=username,
            password_hash=generate_password_hash(password),
            full_name='Default Admin',
            role='admin',
            preferred_device_type='deye',
            is_active=True,
            is_admin=True,
        )
        db.session.add(default_user)
        db.session.commit()
        logger.info('Created default foundation user: %s', username)

    default_device = AppDevice.query.filter_by(owner_user_id=default_user.id).order_by(AppDevice.id.asc()).first()
    if not default_device:
        plant_name = _setting_value('deye_plant_name') or 'My Solar Device'
        station_id = _setting_value('deye_plant_id') or None
        device_uid = _setting_value('deye_device_sn') or None
        creds = {
            'deye_username': _setting_value('deye_username') or '',
            'deye_password': _setting_value('deye_password') or '',
        }
        default_device = AppDevice(
            owner_user_id=default_user.id,
            name=plant_name,
            device_type='deye',
            api_provider='deye',
            api_base_url='https://eu-developer.deyecloud.com',
            device_uid=device_uid,
            station_id=station_id,
            plant_name=plant_name,
            timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron'),
            auth_mode='settings',
            credentials_json=json.dumps(creds, ensure_ascii=False),
            settings_json=json.dumps({'foundation_safe_mode': True}, ensure_ascii=False),
            is_active=True,
        )
        db.session.add(default_device)
        db.session.commit()
        logger.info('Created default foundation device for user %s', username)


def _backfill_foundation_links(db):
    logger = logging.getLogger(__name__)
    default_user = AppUser.query.order_by(AppUser.id.asc()).first()
    default_device = AppDevice.query.order_by(AppDevice.id.asc()).first()
    if not default_user or not default_device:
        return

    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        statements = [
            ("reading", "UPDATE reading SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
            ("sync_log", "UPDATE sync_log SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
            ("notification_log", "UPDATE notification_log SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
            ("user_load", "UPDATE user_load SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
            ("event_log", "UPDATE event_log SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
            ("smart_snapshot", "UPDATE smart_snapshot SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
            ("smart_recommendation_log", "UPDATE smart_recommendation_log SET user_id = %s, device_id = %s WHERE user_id IS NULL OR device_id IS NULL"),
        ]
        for table_name, sql in statements:
            try:
                cursor.execute(sql, (default_user.id, default_device.id))
            except Exception as exc:
                logger.warning('Backfill skipped for %s: %s', table_name, exc)
        conn.commit()
    finally:
        conn.close()


def _setting_value(key: str, default=''):
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value is not None else default
