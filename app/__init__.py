import os
import logging
from flask import Flask, request, session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta, UTC
from .config import Config
from .extensions import db
from .models import Setting, Reading


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

    if app.config.get('AUTO_SYNC_ENABLED', True):
        _start_scheduler(app)

    return app


def _migrate_database(db):
    """
    Safe migration: adds new columns to existing tables without losing data.
    Uses raw SQL ALTER TABLE so it works with SQLite without needing Alembic.
    """
    new_columns = [
        # (table, column_name, column_definition)
        ('reading', 'pv1_power',       'REAL'),
        ('reading', 'pv2_power',       'REAL'),
        ('reading', 'pv3_power',       'REAL'),
        ('reading', 'pv4_power',       'REAL'),
        ('reading', 'inverter_temp',   'REAL'),
        ('reading', 'dc_temp',         'REAL'),
        ('reading', 'grid_voltage',    'REAL'),
        ('reading', 'grid_frequency',  'REAL'),
        ('user_load', 'priority', 'INTEGER DEFAULT 1'),
        ('user_load', 'is_enabled', 'BOOLEAN DEFAULT 1'),
        ('user_load', 'created_at', 'DATETIME'),
    ]
    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        # Get existing columns for each table
        existing = {}
        for table, col, _ in new_columns:
            if table not in existing:
                try:
                    cursor.execute(f"PRAGMA table_info({table})")
                    existing[table] = {row[1] for row in cursor.fetchall()}
                except Exception:
                    existing[table] = set()

        added = []
        for table, col, col_def in new_columns:
            if col not in existing.get(table, set()):
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                    added.append(f"{table}.{col}")
                except Exception:
                    pass  # Column may already exist in some edge cases

        conn.commit()
        if added:
            import logging
            logging.getLogger(__name__).info(f"DB migration: added columns {added}")
    finally:
        conn.close()


def _start_scheduler(app):
    if getattr(app, '_scheduler_started', False):
        return
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    scheduler = BackgroundScheduler(
        timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron'),
        job_defaults={
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 120,
        },
    )

    def _job(fn_path):
        def _inner():
            with app.app_context():
                module_path, fn_name = fn_path.rsplit('.', 1)
                import importlib
                logger = logging.getLogger(__name__)
                logger.info('Scheduler job started: %s', fn_path)
                mod = importlib.import_module(module_path)
                try:
                    getattr(mod, fn_name)()
                    logger.info('Scheduler job finished: %s', fn_path)
                except Exception:
                    logger.exception('Scheduled job failed: %s', fn_path)
        return _inner

    now_utc = datetime.now(UTC)
    sync_minutes = max(int(app.config.get('AUTO_SYNC_MINUTES', 5)), 1)
    job_specs = [
        {
            'id': 'deye_auto_sync',
            'func': _job('app.blueprints.main.sync_now_internal'),
            'trigger': IntervalTrigger(minutes=sync_minutes, timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')),
            'next_run_time': now_utc + timedelta(seconds=10),
        },
        {
            'id': 'weather_change_check',
            'func': _job('app.blueprints.notifications.run_weather_checks'),
            'trigger': IntervalTrigger(minutes=10, timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')),
            'next_run_time': now_utc + timedelta(seconds=20),
        },
        {
            'id': 'advanced_notifications_check',
            'func': _job('app.blueprints.notifications.run_advanced_notification_scheduler'),
            'trigger': IntervalTrigger(seconds=30, timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')),
            'next_run_time': now_utc + timedelta(seconds=15),
        },
        {
            'id': 'weather_daily_summary',
            'func': _job('app.blueprints.notifications.send_daily_weather_summary'),
            'trigger': CronTrigger(hour=7, minute=0, timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')),
        },
        {
            'id': 'daily_morning_report',
            'func': _job('app.blueprints.notifications.send_daily_morning_report'),
            'trigger': CronTrigger(hour=9, minute=5, timezone=app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')),
        },
    ]

    for spec in job_specs:
        scheduler.add_job(
            spec['func'],
            trigger=spec['trigger'],
            id=spec['id'],
            replace_existing=True,
            next_run_time=spec.get('next_run_time'),
        )

    scheduler.start()
    logging.getLogger(__name__).info('Scheduler started with jobs: %s', [job.id for job in scheduler.get_jobs()])
    app._scheduler_started = True
    app.scheduler = scheduler


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
