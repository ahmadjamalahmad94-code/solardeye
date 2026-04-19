from datetime import datetime
from .extensions import db


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppUser(db.Model):
    __tablename__ = 'app_user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False, default='')
    full_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(50), nullable=False, default='admin')
    preferred_device_type = db.Column(db.String(50), nullable=False, default='deye')
    preferred_device_id = db.Column(db.Integer, nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppDevice(db.Model):
    __tablename__ = 'app_device'

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False, default='My Solar Device')
    device_type = db.Column(db.String(50), nullable=False, default='deye', index=True)
    api_provider = db.Column(db.String(50), nullable=False, default='deye')
    api_base_url = db.Column(db.String(255), nullable=True)
    external_device_id = db.Column(db.String(120), nullable=True, index=True)
    device_uid = db.Column(db.String(120), nullable=True, unique=True)
    station_id = db.Column(db.String(120), nullable=True)
    plant_name = db.Column(db.String(120), nullable=True)
    timezone = db.Column(db.String(64), default='Asia/Hebron')
    auth_mode = db.Column(db.String(50), default='config')
    credentials_json = db.Column(db.Text, nullable=True)
    settings_json = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Reading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
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
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.String(20), default='info')
    message = db.Column(db.Text, nullable=False)
    raw_json = db.Column(db.Text)


class NotificationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
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
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    power_w = db.Column(db.Float, nullable=False, default=0)
    priority = db.Column(db.Integer, nullable=False, default=1)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class EventLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    event_key = db.Column(db.String(160), index=True)
    event_type = db.Column(db.String(60), index=True, default='system')
    severity = db.Column(db.String(20), default='info')
    title = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text, default='')
    value_before = db.Column(db.String(120), default='')
    value_after = db.Column(db.String(120), default='')
    raw_json = db.Column(db.Text)


class SmartSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
    reading_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    local_hour = db.Column(db.Integer, index=True)
    local_minute_bucket = db.Column(db.Integer, index=True)
    is_day = db.Column(db.Boolean, default=True, index=True)
    temperature_c = db.Column(db.Float, nullable=True)
    clouds_percent = db.Column(db.Float, nullable=True)
    weather_code = db.Column(db.String(40), nullable=True)
    solar_power = db.Column(db.Float, default=0)
    home_load = db.Column(db.Float, default=0)
    battery_soc = db.Column(db.Float, default=0)
    battery_power = db.Column(db.Float, default=0)
    grid_power = db.Column(db.Float, default=0)
    inverter_power = db.Column(db.Float, default=0)
    raw_surplus_w = db.Column(db.Float, default=0)
    battery_charge_need_w = db.Column(db.Float, default=0)
    actual_surplus_w = db.Column(db.Float, default=0)
    minutes_to_sunset = db.Column(db.Float, nullable=True)
    hours_until_sunrise = db.Column(db.Float, nullable=True)
    quality_score = db.Column(db.Float, default=1.0)
    source = db.Column(db.String(30), default='auto_sync')


class SmartRecommendationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    device_id = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    snapshot_id = db.Column(db.Integer, nullable=True, index=True)
    recommendation_type = db.Column(db.String(50), index=True)
    status_label = db.Column(db.String(100), default='')
    message_ar = db.Column(db.Text, default='')
    confidence_score = db.Column(db.Float, default=0)
    matched_count = db.Column(db.Integer, default=0)
    predicted_next_hour_solar = db.Column(db.Float, nullable=True)
    predicted_risk_level = db.Column(db.String(30), default='unknown')
    raw_json = db.Column(db.Text, nullable=True)


class ServiceHeartbeat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    service_label = db.Column(db.String(160), nullable=False, default='')
    source = db.Column(db.String(40), nullable=False, default='system')
    status = db.Column(db.String(30), nullable=False, default='unknown')
    message = db.Column(db.Text, default='')
    details_json = db.Column(db.Text, nullable=True)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
