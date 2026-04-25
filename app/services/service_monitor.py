from __future__ import annotations

import re
from datetime import datetime

from ..extensions import db
from ..models import ServiceHeartbeat
from .utils import to_json

SERVICE_LABELS = {
    'scheduler': {'ar': 'الجدولة الداخلية', 'en': 'Internal Scheduler'},
    'deye_auto_sync': {'ar': 'المزامنة التلقائية', 'en': 'Auto Sync'},
    'app.blueprints.main.sync_now_internal': {'ar': 'المزامنة التلقائية', 'en': 'Auto Sync'},
    'advanced_notifications_check': {'ar': 'الإشعارات المتقدمة', 'en': 'Advanced Notifications'},
    'app.blueprints.notifications.run_advanced_notification_scheduler': {'ar': 'الإشعارات المتقدمة', 'en': 'Advanced Notifications'},
    'weather_change_check': {'ar': 'فحص الطقس', 'en': 'Weather Checks'},
    'app.blueprints.notifications.run_weather_checks': {'ar': 'فحص الطقس', 'en': 'Weather Checks'},
    'weather_daily_summary': {'ar': 'ملخص الطقس اليومي', 'en': 'Daily Weather Summary'},
    'app.blueprints.notifications.send_daily_weather_summary': {'ar': 'ملخص الطقس اليومي', 'en': 'Daily Weather Summary'},
    'daily_morning_report': {'ar': 'التقرير الصباحي', 'en': 'Morning Report'},
    'app.blueprints.notifications.send_daily_morning_report': {'ar': 'التقرير الصباحي', 'en': 'Morning Report'},
    'database_backup': {'ar': 'النسخ الاحتياطي', 'en': 'Database Backup'},
    'database_backup_drive': {'ar': 'رفع النسخ إلى Drive', 'en': 'Drive Upload'},
    'database_backup_maintenance': {'ar': 'صيانة النسخ الاحتياطي', 'en': 'Backup Maintenance'},
    'app.services.backup_service.scheduled_backup_job': {'ar': 'صيانة النسخ الاحتياطي', 'en': 'Backup Maintenance'},
}

MESSAGE_PREFIXES = {
    'بدأت المهمة': {'ar': 'بدأت المهمة', 'en': 'Job started'},
    'اكتملت المهمة بنجاح': {'ar': 'اكتملت المهمة بنجاح', 'en': 'Job completed successfully'},
    'فشلت المهمة:': {'ar': 'فشلت المهمة:', 'en': 'Job failed:'},
    'Scheduler started and jobs are registered.': {'ar': 'تم تشغيل الجدولة وتسجيل المهام.', 'en': 'Scheduler started and jobs are registered.'},
}


def _norm_lang(lang: str | None) -> str:
    return 'en' if str(lang or '').lower().startswith('en') else 'ar'


def service_display_name(key_or_label: str | None, lang: str = 'ar') -> str:
    lang = _norm_lang(lang)
    raw = str(key_or_label or '').strip()
    if not raw:
        return '—'
    if raw in SERVICE_LABELS:
        return SERVICE_LABELS[raw][lang]
    # Known function paths can be reduced to a readable name.
    tail = raw.rsplit('.', 1)[-1].replace('_', ' ')
    if lang == 'en':
        return tail.title()
    return raw


def service_message(message: str | None, lang: str = 'ar') -> str:
    lang = _norm_lang(lang)
    text = str(message or '').strip()
    if not text:
        return '—'
    if lang == 'ar':
        return text
    for source, mapping in MESSAGE_PREFIXES.items():
        if text.startswith(source):
            return mapping['en'] + text[len(source):]
    # Avoid leaking common Arabic health words in English mode.
    replacements = {
        'سليم': 'Healthy',
        'فشل': 'Failed',
        'فشلت': 'Failed',
        'تحذير': 'Warning',
        'اكتملت': 'Completed',
        'بدأت': 'Started',
        'تم': 'Done',
    }
    for ar, en in replacements.items():
        text = re.sub(r'(?<![\u0600-\u06FF])' + re.escape(ar) + r'(?![\u0600-\u06FF])', en, text)
    return text


def heartbeat(service_key: str, service_label: str, status: str = 'ok', message: str = '', source: str = 'system', details=None):
    row = ServiceHeartbeat.query.filter_by(service_key=service_key).first()
    if not row:
        row = ServiceHeartbeat(service_key=service_key, service_label=service_label)
        db.session.add(row)
    row.service_label = service_label or service_display_name(service_key, 'en')
    row.source = source or 'system'
    row.status = status or 'unknown'
    row.message = message or ''
    row.details_json = to_json(details or {})
    row.last_seen_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return row
