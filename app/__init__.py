import json
import logging
import secrets
from datetime import datetime

from flask import Flask
from werkzeug.security import generate_password_hash

from .config import Config
from .extensions import db
from .models import AppDevice, AppUser, Setting, DeviceType, AppRole, PortalPageSetting, MobileRefreshToken, MobilePushToken
from .services.subscriptions import seed_default_plans
from .services.support_ops import seed_canned_replies, sync_existing_cases
from .services.security import register_security
from .services.labels import register_template_helpers
from .services.i18n import register_i18n
from .services.backup_service import ensure_backup_settings
from .services.energy_integrations import provider_catalog
from .services.rbac import register_access_control, seed_access_control
from .scheduler import start_scheduler

logger = logging.getLogger(__name__)


def _default_admin_password(app):
    password = (app.config.get('ADMIN_PASSWORD') or '').strip()
    if password:
        return password
    logger.warning('ADMIN_PASSWORD is not configured. Generated a random bootstrap admin password. Set ADMIN_PASSWORD and reset the admin password immediately.')
    return secrets.token_urlsafe(24)


def create_app():
    _warn_legacy_routes_file()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    db.init_app(app)
    register_i18n(app)
    register_security(app)
    register_template_helpers(app)
    register_access_control(app)

    from .blueprints.auth import auth_bp
    from .blueprints.integrations import integrations_bp
    from .blueprints.platform import platform_bp
    from .blueprints.admin_ops import admin_ops_bp
    from .blueprints.access_control import access_control_bp
    from .blueprints.mobile_api import mobile_api_bp
    from .blueprints.mobile_auth_api import mobile_auth_api_bp
    from .blueprints.mobile_devices_api import mobile_devices_api_bp
    from .blueprints.mobile_support_api import mobile_support_api_bp
    from .blueprints.mobile_notifications_api import mobile_notifications_api_bp
    from .blueprints.openapi_api import openapi_api_bp
    from .blueprints.energy import energy_bp
    from .blueprints.devices_routes import devices_bp
    from .blueprints.support import support_bp
    from .blueprints.billing import billing_bp
    from .blueprints.notifications_routes import notifications_routes_bp
    from .blueprints.users_routes import users_bp
    from .blueprints.main import main_bp
    from .blueprints.api_probe import probe_bp

    app.register_blueprint(auth_bp)
    # v9 modular admin operations are registered before the legacy main blueprint
    # so shared URLs are handled by split modules first.
    app.register_blueprint(admin_ops_bp)
    app.register_blueprint(access_control_bp)
    app.register_blueprint(mobile_api_bp)
    app.register_blueprint(mobile_auth_api_bp)
    app.register_blueprint(mobile_devices_api_bp)
    app.register_blueprint(mobile_support_api_bp)
    app.register_blueprint(mobile_notifications_api_bp)
    app.register_blueprint(openapi_api_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(platform_bp)
    app.register_blueprint(energy_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(notifications_routes_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(probe_bp)

    with app.app_context():
        db.create_all()
        _migrate_database()
        _ensure_database_indexes()
        _ensure_default_settings()
        ensure_backup_settings()
        seed_access_control()
        seed_default_plans()
        seed_canned_replies()
        try:
            sync_existing_cases(commit=True)
        except Exception as exc:
            logger.warning('Support case startup sync skipped: %s', exc)
        default_user = _ensure_default_app_user(app)
        default_device = _ensure_default_app_device(app, default_user)
        if default_user.preferred_device_id != default_device.id:
            default_user.preferred_device_id = default_device.id
            db.session.commit()
        _backfill_foundation_ids(default_user.id, default_device.id)
        _seed_device_types()

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
            'preferred_device_id': 'INTEGER',
            'is_active': 'BOOLEAN DEFAULT TRUE',
            'is_admin': 'BOOLEAN DEFAULT FALSE',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
            'onboarding_completed': 'BOOLEAN DEFAULT FALSE',
            'onboarding_step': 'VARCHAR(50)',
            'oauth_provider': 'VARCHAR(30)',
            'oauth_subject': 'VARCHAR(255)',
            'last_login_at': 'TIMESTAMP',
            'permissions_json': 'TEXT',
            'tenant_id': 'INTEGER',
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
            'notes': 'TEXT',
            'connection_status': "VARCHAR(30) DEFAULT 'new'",
            'last_connected_at': 'TIMESTAMP',
            'is_active': 'BOOLEAN DEFAULT TRUE',
            'created_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP',
            'tenant_id': 'INTEGER',
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
        'notification_event': {'event_type': "VARCHAR(40) DEFAULT 'support'", 'target_user_id': 'INTEGER', 'tenant_id': 'INTEGER', 'source_type': 'VARCHAR(40)', 'source_id': 'INTEGER', 'title': "VARCHAR(220) DEFAULT ''", 'message': 'TEXT', 'direct_url': 'VARCHAR(500)', 'status': "VARCHAR(30) DEFAULT 'new'", 'result': 'TEXT', 'is_read': 'BOOLEAN DEFAULT FALSE', 'appeared_in_bell': 'BOOLEAN DEFAULT FALSE', 'delivered_to_user': 'BOOLEAN DEFAULT FALSE', 'created_at': 'TIMESTAMP', 'read_at': 'TIMESTAMP'},
        'support_case': {'case_type': 'VARCHAR(30)', 'source_id': 'INTEGER', 'tenant_id': 'INTEGER', 'user_id': 'INTEGER', 'assigned_admin_user_id': 'INTEGER', 'subject': "VARCHAR(220) DEFAULT ''", 'priority': "VARCHAR(30) DEFAULT 'normal'", 'status': "VARCHAR(30) DEFAULT 'open'", 'is_frozen': 'BOOLEAN DEFAULT FALSE', 'sla_due_at': 'TIMESTAMP', 'last_reply_at': 'TIMESTAMP', 'last_reply_by': 'VARCHAR(20)', 'created_at': 'TIMESTAMP', 'updated_at': 'TIMESTAMP'},
        'support_audit_log': {'case_type': 'VARCHAR(30)', 'source_id': 'INTEGER', 'actor_user_id': 'INTEGER', 'action': 'VARCHAR(80)', 'summary': "VARCHAR(255) DEFAULT ''", 'details_json': 'TEXT', 'created_at': 'TIMESTAMP'},
        'canned_reply': {'title': 'VARCHAR(120)', 'body': 'TEXT', 'category': "VARCHAR(50) DEFAULT 'support'", 'is_active': 'BOOLEAN DEFAULT TRUE', 'created_at': 'TIMESTAMP', 'updated_at': 'TIMESTAMP'},
        'tenant_quota': {'source': "VARCHAR(30) DEFAULT 'manual'", 'source_plan_id': 'INTEGER', 'is_unlimited': 'BOOLEAN DEFAULT FALSE'},
        'app_role': {'code': 'VARCHAR(60)', 'name_ar': "VARCHAR(120) DEFAULT ''", 'name_en': "VARCHAR(120) DEFAULT ''", 'summary_ar': 'VARCHAR(255)', 'summary_en': 'VARCHAR(255)', 'permissions_json': 'TEXT', 'is_system': 'BOOLEAN DEFAULT FALSE', 'is_active': 'BOOLEAN DEFAULT TRUE', 'sort_order': 'INTEGER DEFAULT 100', 'created_at': 'TIMESTAMP', 'updated_at': 'TIMESTAMP'},
        'portal_page_setting': {'page_key': 'VARCHAR(80)', 'endpoint': "VARCHAR(120) DEFAULT ''", 'label_ar': "VARCHAR(120) DEFAULT ''", 'label_en': "VARCHAR(120) DEFAULT ''", 'icon': "VARCHAR(20) DEFAULT '•'", 'group_key': "VARCHAR(40) DEFAULT 'portal'", 'is_visible': 'BOOLEAN DEFAULT TRUE', 'is_locked': 'BOOLEAN DEFAULT FALSE', 'sort_order': 'INTEGER DEFAULT 100', 'created_at': 'TIMESTAMP', 'updated_at': 'TIMESTAMP'},
        'mobile_refresh_token': {'user_id': 'INTEGER', 'token_hash': 'VARCHAR(128)', 'device_label': 'VARCHAR(160)', 'ip_address': 'VARCHAR(80)', 'user_agent': 'VARCHAR(255)', 'created_at': 'TIMESTAMP', 'last_used_at': 'TIMESTAMP', 'expires_at': 'TIMESTAMP', 'revoked_at': 'TIMESTAMP'},
        'mobile_push_token': {'user_id': 'INTEGER', 'platform': "VARCHAR(30) DEFAULT 'android'", 'token': 'TEXT', 'token_hash': 'VARCHAR(128)', 'device_label': 'VARCHAR(160)', 'app_version': 'VARCHAR(60)', 'is_active': 'BOOLEAN DEFAULT TRUE', 'created_at': 'TIMESTAMP', 'last_seen_at': 'TIMESTAMP', 'revoked_at': 'TIMESTAMP'},
    }


    # create phase 1.A tables if missing
    ddl_statements = [
        """CREATE TABLE IF NOT EXISTS subscription_plan (id INTEGER PRIMARY KEY, code VARCHAR(50) UNIQUE, name_ar VARCHAR(120) NOT NULL, name_en VARCHAR(120) NOT NULL, price FLOAT DEFAULT 0.0, currency VARCHAR(10) DEFAULT 'USD', duration_days_default INTEGER DEFAULT 30, max_devices INTEGER DEFAULT 1, is_active BOOLEAN DEFAULT TRUE, sort_order INTEGER DEFAULT 0, features_json TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tenant_account (id INTEGER PRIMARY KEY, owner_user_id INTEGER, display_name VARCHAR(150) NOT NULL, status VARCHAR(30) DEFAULT 'trial', plan_id INTEGER, max_devices_override INTEGER, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tenant_subscription (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, plan_id INTEGER NOT NULL, status VARCHAR(30) DEFAULT 'trial', activation_mode VARCHAR(30) DEFAULT 'manual', starts_at TIMESTAMP, ends_at TIMESTAMP, trial_ends_at TIMESTAMP, activated_by_user_id INTEGER, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS device_type (id INTEGER PRIMARY KEY, code VARCHAR(50) UNIQUE, name VARCHAR(120) NOT NULL, provider VARCHAR(120) DEFAULT 'custom', auth_mode VARCHAR(50) DEFAULT 'api_key', base_url VARCHAR(255), healthcheck_endpoint VARCHAR(255), sync_endpoint VARCHAR(255), required_fields_json TEXT, mapping_schema_json TEXT, is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS internal_mail_thread (id INTEGER PRIMARY KEY, tenant_id INTEGER, created_by_user_id INTEGER, assigned_admin_user_id INTEGER, subject VARCHAR(200) NOT NULL, category VARCHAR(50) DEFAULT 'general', priority VARCHAR(30) DEFAULT 'normal', status VARCHAR(30) DEFAULT 'open', last_reply_at TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS internal_mail_message (id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL, sender_user_id INTEGER, sender_scope VARCHAR(20) DEFAULT 'user', is_internal_note BOOLEAN DEFAULT FALSE, body TEXT NOT NULL, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_ticket (id INTEGER PRIMARY KEY, tenant_id INTEGER, opened_by_user_id INTEGER, assigned_admin_user_id INTEGER, subject VARCHAR(200) NOT NULL, category VARCHAR(50) DEFAULT 'support', priority VARCHAR(30) DEFAULT 'normal', status VARCHAR(30) DEFAULT 'open', related_device_id INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP, last_reply_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_ticket_message (id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, sender_user_id INTEGER, sender_scope VARCHAR(20) DEFAULT 'user', is_internal_note BOOLEAN DEFAULT FALSE, body TEXT NOT NULL, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tenant_quota (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, quota_key VARCHAR(80), quota_label VARCHAR(120), limit_value FLOAT DEFAULT 0.0, used_value FLOAT DEFAULT 0.0, reset_period VARCHAR(30) DEFAULT 'manual', status VARCHAR(30) DEFAULT 'active', source VARCHAR(30) DEFAULT 'manual', source_plan_id INTEGER, is_unlimited BOOLEAN DEFAULT FALSE, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS wallet_ledger (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, actor_user_id INTEGER, entry_type VARCHAR(30) DEFAULT 'credit', amount FLOAT DEFAULT 0.0, currency VARCHAR(10) DEFAULT 'USD', note TEXT, reference VARCHAR(120), created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS admin_activity_log (id INTEGER PRIMARY KEY, actor_user_id INTEGER, action VARCHAR(120) NOT NULL, target_type VARCHAR(80), target_id INTEGER, summary VARCHAR(255) NOT NULL, details_json TEXT, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS notification_event (id INTEGER PRIMARY KEY, event_type VARCHAR(40) DEFAULT 'support', target_user_id INTEGER, tenant_id INTEGER, source_type VARCHAR(40), source_id INTEGER, title VARCHAR(220) DEFAULT '', message TEXT DEFAULT '', direct_url VARCHAR(500), status VARCHAR(30) DEFAULT 'new', result TEXT, is_read BOOLEAN DEFAULT FALSE, appeared_in_bell BOOLEAN DEFAULT FALSE, delivered_to_user BOOLEAN DEFAULT FALSE, created_at TIMESTAMP, read_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_case (id INTEGER PRIMARY KEY, case_type VARCHAR(30) NOT NULL, source_id INTEGER NOT NULL, tenant_id INTEGER, user_id INTEGER, assigned_admin_user_id INTEGER, subject VARCHAR(220) DEFAULT '', priority VARCHAR(30) DEFAULT 'normal', status VARCHAR(30) DEFAULT 'open', is_frozen BOOLEAN DEFAULT FALSE, sla_due_at TIMESTAMP, last_reply_at TIMESTAMP, last_reply_by VARCHAR(20), created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_audit_log (id INTEGER PRIMARY KEY, case_type VARCHAR(30) NOT NULL, source_id INTEGER NOT NULL, actor_user_id INTEGER, action VARCHAR(80) NOT NULL, summary VARCHAR(255) DEFAULT '', details_json TEXT, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS canned_reply (id INTEGER PRIMARY KEY, title VARCHAR(120) NOT NULL, body TEXT NOT NULL, category VARCHAR(50) DEFAULT 'support', is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS app_role (id INTEGER PRIMARY KEY, code VARCHAR(60) UNIQUE NOT NULL, name_ar VARCHAR(120) DEFAULT '', name_en VARCHAR(120) DEFAULT '', summary_ar VARCHAR(255), summary_en VARCHAR(255), permissions_json TEXT, is_system BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE, sort_order INTEGER DEFAULT 100, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS portal_page_setting (id INTEGER PRIMARY KEY, page_key VARCHAR(80) UNIQUE NOT NULL, endpoint VARCHAR(120) DEFAULT '', label_ar VARCHAR(120) DEFAULT '', label_en VARCHAR(120) DEFAULT '', icon VARCHAR(20) DEFAULT '•', group_key VARCHAR(40) DEFAULT 'portal', is_visible BOOLEAN DEFAULT TRUE, is_locked BOOLEAN DEFAULT FALSE, sort_order INTEGER DEFAULT 100, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS mobile_refresh_token (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, token_hash VARCHAR(128) UNIQUE NOT NULL, device_label VARCHAR(160), ip_address VARCHAR(80), user_agent VARCHAR(255), created_at TIMESTAMP, last_used_at TIMESTAMP, expires_at TIMESTAMP, revoked_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS mobile_push_token (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, platform VARCHAR(30) DEFAULT 'android', token TEXT NOT NULL, token_hash VARCHAR(128) UNIQUE NOT NULL, device_label VARCHAR(160), app_version VARCHAR(60), is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP, last_seen_at TIMESTAMP, revoked_at TIMESTAMP)""",
    ]

    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        for ddl in ddl_statements:
            try:
                cursor.execute(ddl)
            except Exception as exc:
                logger.warning('DDL skipped: %s', exc)
        conn.commit()
    finally:
        conn.close()

    conn = db.engine.raw_connection()
    dialect = getattr(db.engine.dialect, 'name', '').lower()
    try:
        cursor = conn.cursor()

        for ddl in ddl_statements:
            try:
                cursor.execute(ddl)
            except Exception as exc:
                logger.warning('Startup DDL skipped: %s', exc)

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



def _ensure_database_indexes():
    """Create low-risk indexes and de-duplicate support cases.

    This keeps startup migrations backward-compatible while avoiding repeated
    support_case rows and speeding up the new mailbox/notification flows.
    """
    conn = db.engine.raw_connection()
    dialect = getattr(db.engine.dialect, 'name', '').lower()
    placeholder = '%s' if dialect == 'postgresql' else '?'
    try:
        cursor = conn.cursor()
        # Remove duplicate support_case rows before creating the unique index.
        try:
            cursor.execute("""
                SELECT case_type, source_id, MIN(id) AS keep_id, COUNT(*) AS row_count
                FROM support_case
                GROUP BY case_type, source_id
                HAVING COUNT(*) > 1
            """)
            duplicates = cursor.fetchall()
            for case_type, source_id, keep_id, _count in duplicates:
                cursor.execute(
                    f"DELETE FROM support_case WHERE case_type = {placeholder} AND source_id = {placeholder} AND id <> {placeholder}",
                    (case_type, source_id, keep_id),
                )
        except Exception as exc:
            logger.warning('Support case de-duplication skipped: %s', exc)

        index_statements = [
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_support_case_case_type_source_id ON support_case (case_type, source_id)",
            "CREATE INDEX IF NOT EXISTS ix_notification_event_target_read_created ON notification_event (target_user_id, is_read, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_notification_event_source ON notification_event (source_type, source_id)",
            "CREATE INDEX IF NOT EXISTS ix_support_case_status_assignee_updated ON support_case (status, assigned_admin_user_id, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_support_case_tenant_user ON support_case (tenant_id, user_id)",
            "CREATE INDEX IF NOT EXISTS ix_support_case_sla_due_at ON support_case (sla_due_at)",
            "CREATE INDEX IF NOT EXISTS ix_support_ticket_tenant_status_updated ON support_ticket (tenant_id, status, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_internal_mail_thread_tenant_status_updated ON internal_mail_thread (tenant_id, status, updated_at)",
            "CREATE INDEX IF NOT EXISTS ix_support_ticket_message_ticket_created ON support_ticket_message (ticket_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_internal_mail_message_thread_created ON internal_mail_message (thread_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_reading_device_created ON reading (device_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_reading_user_created ON reading (user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_app_role_code_created ON app_role (code, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_portal_page_setting_visible_order ON portal_page_setting (is_visible, sort_order)",
            "CREATE INDEX IF NOT EXISTS ix_mobile_refresh_user_expires ON mobile_refresh_token (user_id, expires_at, revoked_at)",
            "CREATE INDEX IF NOT EXISTS ix_mobile_push_user_active ON mobile_push_token (user_id, is_active, last_seen_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_quota_tenant_key_period ON tenant_quota (tenant_id, quota_key, reset_period, status)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_quota_plan_source ON tenant_quota (source_plan_id, source)",
        ]
        for ddl in index_statements:
            try:
                cursor.execute(ddl)
            except Exception as exc:
                logger.warning('Index DDL skipped: %s', exc)
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




def _default_permissions_for_role(role: str) -> dict:
    role = (role or 'user').strip().lower()
    if role == 'admin':
        return {
            'can_manage_users': True,
            'can_manage_devices': True,
            'can_manage_support': True,
            'can_manage_finance': True,
            'can_manage_subscriptions': True,
            'can_view_logs': True,
            'can_configure_integrations': True,
            'can_manage_integrations': True,
        }
    if role == 'manager':
        return {
            'can_manage_users': False,
            'can_manage_devices': True,
            'can_view_logs': True,
            'can_configure_integrations': False,
            'can_manage_integrations': False,
        }
    return {
        'can_manage_users': False,
        'can_manage_devices': True,
        'can_view_logs': False,
        'can_configure_integrations': False,
            'can_manage_integrations': False,
    }

def _settings_map():
    return {row.key: row.value for row in Setting.query.all()}


def _ensure_default_app_user(app):
    username = (app.config.get('ADMIN_USERNAME') or 'admin').strip() or 'admin'
    user = AppUser.query.filter_by(username=username).first()
    if user:
        changed = False
        if not user.password_hash:
            user.password_hash = generate_password_hash(_default_admin_password(app))
            changed = True
        if not user.role:
            user.role = 'admin'
            changed = True
        if not user.preferred_device_type:
            user.preferred_device_type = 'deye'
            changed = True
        if not user.permissions_json:
            user.permissions_json = json.dumps(_default_permissions_for_role(user.role or 'admin'), ensure_ascii=False)
            changed = True
        if changed:
            user.updated_at = datetime.utcnow()
            db.session.commit()
        return user

    user = AppUser(
        username=username,
        password_hash=generate_password_hash(_default_admin_password(app)),
        full_name='مدير النظام',
        email='',
        role='admin',
        preferred_device_type='deye',
        is_active=True,
        is_admin=True,
        permissions_json=json.dumps(_default_permissions_for_role('admin'), ensure_ascii=False),
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

    # create phase 1.A tables if missing
    ddl_statements = [
        """CREATE TABLE IF NOT EXISTS subscription_plan (id INTEGER PRIMARY KEY, code VARCHAR(50) UNIQUE, name_ar VARCHAR(120) NOT NULL, name_en VARCHAR(120) NOT NULL, price FLOAT DEFAULT 0.0, currency VARCHAR(10) DEFAULT 'USD', duration_days_default INTEGER DEFAULT 30, max_devices INTEGER DEFAULT 1, is_active BOOLEAN DEFAULT TRUE, sort_order INTEGER DEFAULT 0, features_json TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tenant_account (id INTEGER PRIMARY KEY, owner_user_id INTEGER, display_name VARCHAR(150) NOT NULL, status VARCHAR(30) DEFAULT 'trial', plan_id INTEGER, max_devices_override INTEGER, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tenant_subscription (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, plan_id INTEGER NOT NULL, status VARCHAR(30) DEFAULT 'trial', activation_mode VARCHAR(30) DEFAULT 'manual', starts_at TIMESTAMP, ends_at TIMESTAMP, trial_ends_at TIMESTAMP, activated_by_user_id INTEGER, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS device_type (id INTEGER PRIMARY KEY, code VARCHAR(50) UNIQUE, name VARCHAR(120) NOT NULL, provider VARCHAR(120) DEFAULT 'custom', auth_mode VARCHAR(50) DEFAULT 'api_key', base_url VARCHAR(255), healthcheck_endpoint VARCHAR(255), sync_endpoint VARCHAR(255), required_fields_json TEXT, mapping_schema_json TEXT, is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS internal_mail_thread (id INTEGER PRIMARY KEY, tenant_id INTEGER, created_by_user_id INTEGER, assigned_admin_user_id INTEGER, subject VARCHAR(200) NOT NULL, category VARCHAR(50) DEFAULT 'general', priority VARCHAR(30) DEFAULT 'normal', status VARCHAR(30) DEFAULT 'open', last_reply_at TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS internal_mail_message (id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL, sender_user_id INTEGER, sender_scope VARCHAR(20) DEFAULT 'user', is_internal_note BOOLEAN DEFAULT FALSE, body TEXT NOT NULL, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_ticket (id INTEGER PRIMARY KEY, tenant_id INTEGER, opened_by_user_id INTEGER, assigned_admin_user_id INTEGER, subject VARCHAR(200) NOT NULL, category VARCHAR(50) DEFAULT 'support', priority VARCHAR(30) DEFAULT 'normal', status VARCHAR(30) DEFAULT 'open', related_device_id INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP, last_reply_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_ticket_message (id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, sender_user_id INTEGER, sender_scope VARCHAR(20) DEFAULT 'user', is_internal_note BOOLEAN DEFAULT FALSE, body TEXT NOT NULL, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tenant_quota (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, quota_key VARCHAR(80), quota_label VARCHAR(120), limit_value FLOAT DEFAULT 0.0, used_value FLOAT DEFAULT 0.0, reset_period VARCHAR(30) DEFAULT 'manual', status VARCHAR(30) DEFAULT 'active', source VARCHAR(30) DEFAULT 'manual', source_plan_id INTEGER, is_unlimited BOOLEAN DEFAULT FALSE, notes TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS wallet_ledger (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, actor_user_id INTEGER, entry_type VARCHAR(30) DEFAULT 'credit', amount FLOAT DEFAULT 0.0, currency VARCHAR(10) DEFAULT 'USD', note TEXT, reference VARCHAR(120), created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS admin_activity_log (id INTEGER PRIMARY KEY, actor_user_id INTEGER, action VARCHAR(120) NOT NULL, target_type VARCHAR(80), target_id INTEGER, summary VARCHAR(255) NOT NULL, details_json TEXT, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS notification_event (id INTEGER PRIMARY KEY, event_type VARCHAR(40) DEFAULT 'support', target_user_id INTEGER, tenant_id INTEGER, source_type VARCHAR(40), source_id INTEGER, title VARCHAR(220) DEFAULT '', message TEXT DEFAULT '', direct_url VARCHAR(500), status VARCHAR(30) DEFAULT 'new', result TEXT, is_read BOOLEAN DEFAULT FALSE, appeared_in_bell BOOLEAN DEFAULT FALSE, delivered_to_user BOOLEAN DEFAULT FALSE, created_at TIMESTAMP, read_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_case (id INTEGER PRIMARY KEY, case_type VARCHAR(30) NOT NULL, source_id INTEGER NOT NULL, tenant_id INTEGER, user_id INTEGER, assigned_admin_user_id INTEGER, subject VARCHAR(220) DEFAULT '', priority VARCHAR(30) DEFAULT 'normal', status VARCHAR(30) DEFAULT 'open', is_frozen BOOLEAN DEFAULT FALSE, sla_due_at TIMESTAMP, last_reply_at TIMESTAMP, last_reply_by VARCHAR(20), created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS support_audit_log (id INTEGER PRIMARY KEY, case_type VARCHAR(30) NOT NULL, source_id INTEGER NOT NULL, actor_user_id INTEGER, action VARCHAR(80) NOT NULL, summary VARCHAR(255) DEFAULT '', details_json TEXT, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS canned_reply (id INTEGER PRIMARY KEY, title VARCHAR(120) NOT NULL, body TEXT NOT NULL, category VARCHAR(50) DEFAULT 'support', is_active BOOLEAN DEFAULT TRUE, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS app_role (id INTEGER PRIMARY KEY, code VARCHAR(60) UNIQUE NOT NULL, name_ar VARCHAR(120) DEFAULT '', name_en VARCHAR(120) DEFAULT '', summary_ar VARCHAR(255), summary_en VARCHAR(255), permissions_json TEXT, is_system BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE, sort_order INTEGER DEFAULT 100, created_at TIMESTAMP, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS portal_page_setting (id INTEGER PRIMARY KEY, page_key VARCHAR(80) UNIQUE NOT NULL, endpoint VARCHAR(120) DEFAULT '', label_ar VARCHAR(120) DEFAULT '', label_en VARCHAR(120) DEFAULT '', icon VARCHAR(20) DEFAULT '•', group_key VARCHAR(40) DEFAULT 'portal', is_visible BOOLEAN DEFAULT TRUE, is_locked BOOLEAN DEFAULT FALSE, sort_order INTEGER DEFAULT 100, created_at TIMESTAMP, updated_at TIMESTAMP)""",
    ]

    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        for ddl in ddl_statements:
            try:
                cursor.execute(ddl)
            except Exception as exc:
                logger.warning('DDL skipped: %s', exc)
        conn.commit()
    finally:
        conn.close()

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


def _seed_device_types():
    # v9: device provider catalog is centralized in app.services.energy_integrations.
    for spec in provider_catalog():
        payload = spec.as_device_type_payload()
        row = DeviceType.query.filter_by(code=payload['code']).first()
        if not row:
            db.session.add(DeviceType(**payload))
            continue
        changed = False
        for key, value in payload.items():
            if getattr(row, key, None) in (None, '') and value not in (None, ''):
                setattr(row, key, value)
                changed = True
        if changed:
            db.session.add(row)
    db.session.commit()

def _start_scheduler(app):
    return start_scheduler(app)
