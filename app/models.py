from datetime import datetime
from .extensions import db


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Reading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    plant_id = db.Column(db.String(50), index=True)
    plant_name = db.Column(db.String(200))
    solar_power = db.Column(db.Float, default=0)
    home_load = db.Column(db.Float, default=0)
    battery_soc = db.Column(db.Float, default=0)
    battery_power = db.Column(db.Float, default=0)
    grid_power = db.Column(db.Float, default=0)
    inverter_power = db.Column(db.Float, default=0)
    daily_production = db.Column(db.Float, default=0)
    monthly_production = db.Column(db.Float, default=0)
    total_production = db.Column(db.Float, default=0)
    status_text = db.Column(db.String(200), default='غير معروف')
    # Frequently queried device fields stored directly (avoids JSON parsing for stats)
    pv1_power = db.Column(db.Float, nullable=True)
    pv2_power = db.Column(db.Float, nullable=True)
    pv3_power = db.Column(db.Float, nullable=True)
    pv4_power = db.Column(db.Float, nullable=True)
    inverter_temp = db.Column(db.Float, nullable=True)
    dc_temp = db.Column(db.Float, nullable=True)
    grid_voltage = db.Column(db.Float, nullable=True)
    grid_frequency = db.Column(db.Float, nullable=True)
    raw_json = db.Column(db.Text)


class SyncLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.String(20), default='info')
    message = db.Column(db.Text, nullable=False)
    raw_json = db.Column(db.Text)


class NotificationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    event_key = db.Column(db.String(160), index=True)
    rule_name = db.Column(db.String(160))
    channel = db.Column(db.String(30), default='telegram')
    level = db.Column(db.String(20), default='info')
    title = db.Column(db.String(200), default='')
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='sent')
    response_text = db.Column(db.Text)


class UserLoad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    power_w = db.Column(db.Float, nullable=False, default=0)
    priority = db.Column(db.Integer, nullable=False, default=1)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class TelegramLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_key = db.Column(db.String(190), nullable=False, unique=True, index=True)
    owner_label = db.Column(db.String(190), nullable=True)
    telegram_user_id = db.Column(db.String(64), nullable=True, index=True)
    telegram_chat_id = db.Column(db.String(64), nullable=True, index=True)
    telegram_username = db.Column(db.String(128), nullable=True)
    telegram_first_name = db.Column(db.String(128), nullable=True)
    telegram_last_name = db.Column(db.String(128), nullable=True)
    link_token = db.Column(db.String(128), nullable=True, unique=True, index=True)
    link_token_expires_at = db.Column(db.DateTime, nullable=True)
    link_status = db.Column(db.String(32), nullable=False, default='pending')  # pending/linked/revoked
    linked_at = db.Column(db.DateTime, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    menu_enabled = db.Column(db.Boolean, nullable=False, default=True)
    commands_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
