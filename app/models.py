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
    onboarding_completed = db.Column(db.Boolean, default=False, nullable=False)
    onboarding_step = db.Column(db.String(50), nullable=True)
    oauth_provider = db.Column(db.String(30), nullable=True)
    oauth_subject = db.Column(db.String(255), nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    permissions_json = db.Column(db.Text, nullable=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=True, index=True)


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
    connection_status = db.Column(db.String(30), nullable=True, default='new')
    last_connected_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=True, index=True)


class SubscriptionPlan(db.Model):
    __tablename__ = 'subscription_plan'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120), nullable=False)
    price = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='USD')
    duration_days_default = db.Column(db.Integer, default=30)
    max_devices = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    features_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantAccount(db.Model):
    __tablename__ = 'tenant_account'

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    display_name = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(30), default='trial', index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plan.id'), nullable=True, index=True)
    max_devices_override = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantSubscription(db.Model):
    __tablename__ = 'tenant_subscription'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plan.id'), nullable=False, index=True)
    status = db.Column(db.String(30), default='trial', index=True)
    activation_mode = db.Column(db.String(30), default='manual')
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, nullable=True)
    activated_by_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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


class DeviceType(db.Model):
    __tablename__ = 'device_type'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    provider = db.Column(db.String(120), nullable=False, default='custom')
    auth_mode = db.Column(db.String(50), nullable=False, default='api_key')
    base_url = db.Column(db.String(255), nullable=True)
    healthcheck_endpoint = db.Column(db.String(255), nullable=True)
    sync_endpoint = db.Column(db.String(255), nullable=True)
    required_fields_json = db.Column(db.Text, nullable=True)
    mapping_schema_json = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InternalMailThread(db.Model):
    __tablename__ = 'internal_mail_thread'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=True, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    assigned_admin_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    subject = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='general')
    priority = db.Column(db.String(30), nullable=False, default='normal')
    status = db.Column(db.String(30), nullable=False, default='open', index=True)
    last_reply_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InternalMailMessage(db.Model):
    __tablename__ = 'internal_mail_message'

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey('internal_mail_thread.id'), nullable=False, index=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    sender_scope = db.Column(db.String(20), nullable=False, default='user')
    is_internal_note = db.Column(db.Boolean, default=False, nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SupportTicket(db.Model):
    __tablename__ = 'support_ticket'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=True, index=True)
    opened_by_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    assigned_admin_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    subject = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='support')
    priority = db.Column(db.String(30), nullable=False, default='normal')
    status = db.Column(db.String(30), nullable=False, default='open', index=True)
    related_device_id = db.Column(db.Integer, db.ForeignKey('app_device.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_reply_at = db.Column(db.DateTime, nullable=True)


class SupportTicketMessage(db.Model):
    __tablename__ = 'support_ticket_message'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('support_ticket.id'), nullable=False, index=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    sender_scope = db.Column(db.String(20), nullable=False, default='user')
    is_internal_note = db.Column(db.Boolean, default=False, nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class TenantQuota(db.Model):
    __tablename__ = 'tenant_quota'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=False, index=True)
    quota_key = db.Column(db.String(80), nullable=False, index=True)
    quota_label = db.Column(db.String(120), nullable=True)
    limit_value = db.Column(db.Float, nullable=False, default=0.0)
    used_value = db.Column(db.Float, nullable=False, default=0.0)
    reset_period = db.Column(db.String(30), nullable=False, default='manual')
    status = db.Column(db.String(30), nullable=False, default='active')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WalletLedger(db.Model):
    __tablename__ = 'wallet_ledger'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenant_account.id'), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    entry_type = db.Column(db.String(30), nullable=False, default='credit')
    amount = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(10), nullable=False, default='USD')
    note = db.Column(db.Text, nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AdminActivityLog(db.Model):
    __tablename__ = 'admin_activity_log'

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('app_user.id'), nullable=True, index=True)
    action = db.Column(db.String(120), nullable=False, index=True)
    target_type = db.Column(db.String(80), nullable=True)
    target_id = db.Column(db.Integer, nullable=True, index=True)
    summary = db.Column(db.String(255), nullable=False)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
