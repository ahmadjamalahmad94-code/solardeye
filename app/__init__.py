import os
import logging
from flask import Flask, request, session
from datetime import datetime, timedelta, UTC
from .config import Config
from .extensions import db
from .models import Setting, Reading
from .scheduler import start_scheduler


def create_app():
    import os as _os, pathlib as _pl
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


    return app


def _migrate_database(db):
    """
    Safe startup migration: creates missing columns for existing tables without
    requiring Alembic. Supports both SQLite and PostgreSQL.
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
    ]

    conn = db.engine.raw_connection()
    dialect = getattr(db.engine.dialect, 'name', '').lower()
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
                logging.getLogger(__name__).warning(
                    "DB migration skipped for %s.%s: %s", table, col, exc
                )

        conn.commit()
        if added:
            logging.getLogger(__name__).info("DB migration added columns: %s", added)
    finally:
        conn.close()


def _start_scheduler(app):
    return start_scheduler(app)


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
