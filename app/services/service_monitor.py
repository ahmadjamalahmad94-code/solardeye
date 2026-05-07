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
    'database_backup_drive': {'ar': '\u0631\u0641\u0639 \u0627\u0644\u0646\u0633\u062e \u0625\u0644\u0649 \u062f\u0631\u0627\u064a\u0641', 'en': 'Drive Upload'},
    'database_backup_maintenance': {'ar': 'صيانة النسخ الاحتياطي', 'en': 'Backup Maintenance'},
    'app.services.backup_service.scheduled_backup_job': {'ar': 'صيانة النسخ الاحتياطي', 'en': 'Backup Maintenance'},
}

# Prefix translation table — works in both ar<->en directions
SOURCE_LABELS = {
    'scheduler': {'ar': '\u0627\u0644\u0645\u062c\u062f\u0648\u0644', 'en': 'Scheduler'},
    'backup': {'ar': '\u0627\u0644\u0646\u0633\u062e \u0627\u0644\u0627\u062d\u062a\u064a\u0627\u0637\u064a', 'en': 'Backup'},
    'system': {'ar': '\u0627\u0644\u0646\u0638\u0627\u0645', 'en': 'System'},
    'manual': {'ar': '\u064a\u062f\u0648\u064a', 'en': 'Manual'},
}

MESSAGE_PREFIXES = [
    ('بدأت المهمة',         'بدأت المهمة',         'Job started'),
    ('اكتملت المهمة بنجاح', 'اكتملت المهمة بنجاح', 'Job completed successfully'),
    ('فشلت المهمة:',        'فشلت المهمة:',        'Job failed:'),
    ('Job started',                'Job started',                'بدأت المهمة'),
    ('Job completed successfully', 'Job completed successfully', 'اكتملت المهمة بنجاح'),
    ('Job failed:',                'Job failed:',                'فشلت المهمة:'),
    ('Scheduler started and jobs are registered.',
     'Scheduler started and jobs are registered.',
     'تم تشغيل الجدولة وتسجيل المهام بنجاح.'),
    ('Backup created:',  'Backup created:',  'تم إنشاء نسخة احتياطية:'),
    ('Backup uploaded to Drive:', 'Backup uploaded to Drive:', 'تم رفع النسخة إلى Drive:'),
    ('Backup deleted:',  'Backup deleted:',  'تم حذف نسخة قديمة:'),
    ('Waiting for first heartbeat.', 'Waiting for first heartbeat.', 'بانتظار أول نبضة من الخدمة.'),
    ('Waiting for heartbeat...', 'Waiting for heartbeat...', 'بانتظار النبضة...'),
]

MESSAGE_TRANSLATIONS = [
    ('Job started', '\u0628\u062f\u0623\u062a \u0627\u0644\u0645\u0647\u0645\u0629'),
    ('Job completed successfully', '\u0627\u0643\u062a\u0645\u0644\u062a \u0627\u0644\u0645\u0647\u0645\u0629 \u0628\u0646\u062c\u0627\u062d'),
    ('Job failed:', '\u0641\u0634\u0644\u062a \u0627\u0644\u0645\u0647\u0645\u0629:'),
    ('Scheduler started and jobs are registered.', '\u062a\u0645 \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0645\u062c\u062f\u0648\u0644 \u0648\u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u0645\u0647\u0627\u0645 \u0628\u0646\u062c\u0627\u062d.'),
    ('Backup created:', '\u062a\u0645 \u0625\u0646\u0634\u0627\u0621 \u0646\u0633\u062e\u0629 \u0627\u062d\u062a\u064a\u0627\u0637\u064a\u0629:'),
    ('Backup uploaded to Drive:', '\u062a\u0645 \u0631\u0641\u0639 \u0627\u0644\u0646\u0633\u062e\u0629 \u0625\u0644\u0649 \u062f\u0631\u0627\u064a\u0641:'),
    ('Backup deleted:', '\u062a\u0645 \u062d\u0630\u0641 \u0646\u0633\u062e\u0629 \u0642\u062f\u064a\u0645\u0629:'),
    ('Waiting for first heartbeat.', '\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0623\u0648\u0644 \u0646\u0628\u0636\u0629 \u0645\u0646 \u0627\u0644\u062e\u062f\u0645\u0629.'),
    ('Waiting for heartbeat...', '\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0627\u0644\u0646\u0628\u0636\u0629...'),
]


def _norm_lang(lang):
    return 'en' if str(lang or '').lower().startswith('en') else 'ar'


def _humanize_backup_filename(name):
    """solardeye_backup_20260424_200628_manual.json.gz -> 24/04/2026 - 20:06 (\u064a\u062f\u0648\u064a)"""
    m = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', name)
    if not m:
        return name
    yr, mo, dy, hh, mm, _ = m.groups()
    kind = '\u064a\u062f\u0648\u064a' if 'manual' in name else '\u062a\u0644\u0642\u0627\u0626\u064a'
    return f'{dy}/{mo}/{yr} \u2014 {hh}:{mm} ({kind})'


def service_display_name(key_or_label, lang='ar'):
    lang = _norm_lang(lang)
    raw = str(key_or_label or '').strip()
    if not raw:
        return '\u2014'
    if raw in SERVICE_LABELS:
        return SERVICE_LABELS[raw][lang]
    tail = raw.rsplit('.', 1)[-1].replace('_', ' ')
    if lang == 'en':
        return tail.title()
    return raw


def service_source_label(source, lang='ar'):
    lang = _norm_lang(lang)
    raw = str(source or '').strip()
    if not raw:
        return '\u2014'
    key = raw.lower()
    if key in SOURCE_LABELS:
        return SOURCE_LABELS[key][lang]
    if lang == 'en':
        return raw.replace('_', ' ').title()
    return raw


def service_message(message, lang='ar'):
    lang = _norm_lang(lang)
    text = str(message or '').strip()
    if not text:
        return '\u2014'
    for en_text, ar_text in MESSAGE_TRANSLATIONS:
        if lang == 'ar' and text.startswith(en_text):
            remainder = text[len(en_text):].strip()
            if remainder:
                remainder = _humanize_backup_filename(remainder)
            return ar_text + (' ' + remainder if remainder else '')
        if lang == 'en' and text.startswith(ar_text):
            remainder = text[len(ar_text):].strip()
            return en_text + (' ' + remainder if remainder else '')
    if lang == 'ar' and re.search(r'[\u0600-\u06ff]', text):
        return text
    idx = 0 if lang == 'ar' else 1   # column index: 0=ar_src,1=en_src
    out_idx = 0 if lang == 'ar' else 1  # output column: 0=ar,1=en (same cols here)
    # Search prefix table: each row = (ar_prefix, en_prefix, ar_translation, [en_translation])
    # Layout: (ar_prefix, en_prefix, other_lang_translation)
    for row in MESSAGE_PREFIXES:
        ar_pfx, en_pfx, other = row[0], row[1], row[2]
        src_pfx = ar_pfx if lang == 'ar' else en_pfx
        if text.startswith(src_pfx):
            remainder = text[len(src_pfx):].strip()
            translated = (other if lang == 'ar' else en_pfx)
            if lang == 'ar' and remainder:
                remainder = _humanize_backup_filename(remainder)
            return translated + (' ' + remainder if remainder else '')
    # Fallback word replacements
    if lang == 'ar':
        for en, ar in [('Healthy','\u0633\u0644\u064a\u0645'),('Failed','\u0641\u0634\u0644'),
                       ('Warning','\u062a\u062d\u0630\u064a\u0631'),('running','\u064a\u0639\u0645\u0644'),
                       ('ok','\u0633\u0644\u064a\u0645'),('error','\u062e\u0637\u0623')]:
            text = re.sub(r'\b' + re.escape(en) + r'\b', ar, text, flags=re.IGNORECASE)
    else:
        for ar, en in [('\u0633\u0644\u064a\u0645','Healthy'),('\u0641\u0634\u0644','Failed'),
                       ('\u062a\u062d\u0630\u064a\u0631','Warning'),('\u0627\u0643\u062a\u0645\u0644\u062a','Completed'),
                       ('\u0628\u062f\u0623\u062a','Started'),('\u062a\u0645','Done')]:
            text = re.sub(r'(?<![\u0600-\u06ff])' + re.escape(ar) + r'(?![\u0600-\u06ff])', en, text)
    return text


def heartbeat(service_key, service_label, status='ok', message='', source='system', details=None):
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
