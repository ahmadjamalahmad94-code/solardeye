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



class EventLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
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
