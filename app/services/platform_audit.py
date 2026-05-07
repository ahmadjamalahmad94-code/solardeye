from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SENSITIVE_TEMPLATE_PATTERNS = [
    (re.compile(r'\{\{\s*settings\.deye_(plant_id|device_sn|logger_sn|battery_sn|email|password|password_hash|app_secret)'), 'Deye setting may be visible'),
    (re.compile(r'\{\{\s*row\.device\.(device_uid|station_id|external_device_id)'), 'Device identifier may be visible'),
    (re.compile(r'\{\{\s*settings\.(telegram_bot_token|telegram_chat_id|sms_api_key|sms_recipients)'), 'Notification/SMS secret may be visible'),
]

POST_FORM_RE    = re.compile(r'<form\b(?=[^>]*method=["\']post["\'])', re.I)
CSRF_RE         = re.compile(r'name=["\']csrf_token["\']', re.I)
INLINE_STYLE_RE = re.compile(r'\sstyle=["\']', re.I)
ARABIC_RE       = re.compile(r'[؀-ۿ]')
ROUTE_RE        = re.compile(r'@([a-zA-Z_][\w]*)\.route\(')
URL_FOR_RE      = re.compile(r"url_for\(['\"]([^'\"]+)['\"]")
ROUTE_URL_RE    = re.compile(r"@\w+\.route\(['\"]([^'\"]+)['\"]")

TEMPLATE_PAGE_MAP = {
    'dashboard.html':                 '/',
    'landing.html':                   '/',
    'login.html':                     '/login',
    'register.html':                  '/register',
    'onboarding.html':                '/onboarding',
    'admin_dashboard.html':           '/admin',
    'admin_devices_center.html':      '/admin/devices',
    'admin_integrations.html':        '/admin/integrations',
    'admin_services_health.html':     '/admin/services-health',
    'admin_platform_review.html':     '/admin/platform-review',
    'admin_plans.html':               '/admin/plans',
    'admin_finance.html':             '/admin/finance',
    'admin_roles.html':               '/admin/roles',
    'admin_activity_log.html':        '/admin/activity-log',
    'admin_system_logs.html':         '/admin/system-logs',
    'admin_backups.html':             '/admin/backups',
    'admin_subscribers_phase1a.html': '/admin/subscribers',
    'admin_staff_profile.html':       '/admin/staff/<id>',
    'channels.html':                  '/channels',
    'notifications.html':             '/notifications',
    'statistics.html':                '/statistics',
    'reports.html':                   '/reports',
    'live_data.html':                 '/live-data',
    'loads.html':                     '/loads',
    'account_profile.html':           '/account/profile',
    'account_subscription.html':      '/account/subscription',
    'devices_manage.html':            '/devices/manage',
    'portal_support.html':            '/portal/support',
    'energy.html':                    '/energy',
    'api_v1_docs.html':               '/api/v1/docs',
    'admin_landing_settings.html':    '/admin/landing-settings',
}

TEMPLATE_PAGE_NAMES = {
    'dashboard.html':                    {'ar': 'لوحة التحكم',         'en': 'Dashboard'},
    'user_dashboard.html':               {'ar': 'لوحة المستخدم',       'en': 'User Dashboard'},
    'landing.html':                      {'ar': 'الصفحة الرئيسية',     'en': 'Home'},
    'login.html':                        {'ar': 'تسجيل الدخول',        'en': 'Login'},
    'register.html':                     {'ar': 'التسجيل',              'en': 'Register'},
    'onboarding_wizard.html':            {'ar': 'الإعداد الأولي',      'en': 'Onboarding'},
    'admin.html':                        {'ar': 'لوحة الإدارة',        'en': 'Admin'},
    'admin_dashboard.html':              {'ar': 'لوحة الإدارة',        'en': 'Admin Dashboard'},
    'admin_devices_center.html':         {'ar': 'مركز الأجهزة',        'en': 'Devices Center'},
    'admin_integrations.html':           {'ar': 'التكاملات',            'en': 'Integrations'},
    'admin_services_health.html':        {'ar': 'صحة الخدمات',         'en': 'Services Health'},
    'admin_platform_review.html':        {'ar': 'مراجعة المنصة',       'en': 'Platform Review'},
    'admin_plans_phase1a.html':          {'ar': 'الخطط',               'en': 'Plans'},
    'admin_plan_form_phase1a.html':      {'ar': 'نموذج الخطة',         'en': 'Plan Form'},
    'admin_finance.html':                {'ar': 'المالية',              'en': 'Finance'},
    'admin_roles.html':                  {'ar': 'الأدوار',              'en': 'Roles'},
    'admin_activity_log.html':           {'ar': 'سجل النشاط',          'en': 'Activity Log'},
    'admin_system_logs.html':            {'ar': 'سجلات النظام',        'en': 'System Logs'},
    'admin_backups.html':                {'ar': 'النسخ الاحتياطية',    'en': 'Backups'},
    'admin_subscribers_phase1a.html':    {'ar': 'المشتركون',            'en': 'Subscribers'},
    'admin_subscriptions.html':          {'ar': 'الاشتراكات',           'en': 'Subscriptions'},
    'admin_subscriber_activate_phase1a.html': {'ar': 'تفعيل المشترك',  'en': 'Activate Subscriber'},
    'admin_staff_profile.html':          {'ar': 'ملف الموظف',           'en': 'Staff Profile'},
    'admin_user_form.html':              {'ar': 'نموذج المستخدم',       'en': 'User Form'},
    'admin_user_profile.html':           {'ar': 'ملف المستخدم',         'en': 'User Profile'},
    'admin_users.html':                  {'ar': 'المستخدمون',           'en': 'Users'},
    'admin_quotas.html':                 {'ar': 'الحصص',               'en': 'Quotas'},
    'admin_tickets.html':                {'ar': 'التذاكر',              'en': 'Tickets'},
    'admin_internal_mail.html':          {'ar': 'البريد الداخلي',       'en': 'Internal Mail'},
    'admin_support_command_center.html': {'ar': 'مركز الدعم',           'en': 'Support Center'},
    'admin_landing_settings.html':       {'ar': 'إعدادات الصفحة الرئيسية', 'en': 'Landing Settings'},
    'admin_design_qa.html':              {'ar': 'مراجعة التصميم',       'en': 'Design QA'},
    'channels.html':                     {'ar': 'القنوات',              'en': 'Channels'},
    'notifications.html':                {'ar': 'الإشعارات',            'en': 'Notifications'},
    'notification_center.html':          {'ar': 'مركز الإشعارات',       'en': 'Notification Center'},
    'notifications_center.html':         {'ar': 'مركز الإشعارات',       'en': 'Notification Center'},
    'statistics.html':                   {'ar': 'الإحصاءات',            'en': 'Statistics'},
    'reports.html':                      {'ar': 'التقارير',             'en': 'Reports'},
    'live_data.html':                    {'ar': 'البيانات الحية',        'en': 'Live Data'},
    'loads.html':                        {'ar': 'الأحمال',              'en': 'Loads'},
    'account_profile.html':              {'ar': 'الملف الشخصي',         'en': 'My Profile'},
    'account_subscription_phase1a.html': {'ar': 'اشتراكي',              'en': 'My Subscription'},
    'devices.html':                      {'ar': 'الأجهزة',              'en': 'Devices'},
    'device_form.html':                  {'ar': 'نموذج الجهاز',         'en': 'Device Form'},
    'devices_manage.html':               {'ar': 'إدارة الأجهزة',        'en': 'Manage Devices'},
    'deye_settings.html':                {'ar': 'إعدادات المحول',       'en': 'Inverter Settings'},
    'diagnostics.html':                  {'ar': 'التشخيص',              'en': 'Diagnostics'},
    'battery_lab.html':                  {'ar': 'مختبر البطارية',       'en': 'Battery Lab'},
    'plant_info.html':                   {'ar': 'معلومات المحطة',       'en': 'Plant Info'},
    'portal_support.html':               {'ar': 'الدعم الفني',          'en': 'Support'},
    'portal_messages.html':              {'ar': 'الرسائل',              'en': 'Messages'},
    'portal_tickets.html':               {'ar': 'التذاكر',              'en': 'Tickets'},
    'alerts.html':                       {'ar': 'التنبيهات',            'en': 'Alerts'},
    'api_docs.html':                     {'ar': 'توثيق API',            'en': 'API Docs'},
    'api_probe.html':                    {'ar': 'فاحص API',             'en': 'API Probe'},
    'user.html':                         {'ar': 'المستخدم',             'en': 'User'},
    'error.html':                        {'ar': 'خطأ',                  'en': 'Error'},
}

TERM_GLOSSARY = [
    {'concept_en': 'Heartbeat',            'standard_ar': 'نبضة',              'standard_en': 'Heartbeat',           'variants': ['نبض ', 'heartbeat'],                       'note_ar': 'استخدم "نبضة / نبضات" لوصف إشارة الحياة للخدمات',           'note_en': 'Use "نبضة / نبضات" consistently'},
    {'concept_en': 'Sync',                 'standard_ar': 'مزامنة',            'standard_en': 'Sync',                'variants': ['تزامن', 'Sync', 'sync'],                   'note_ar': 'استخدم "مزامنة" وليس "تزامن"',                             'note_en': 'Use "مزامنة" not "تزامن"'},
    {'concept_en': 'Notification / Alert', 'standard_ar': 'إشعار / تنبيه',     'standard_en': 'Notification',        'variants': ['اشعار', 'Notification', 'notification'],   'note_ar': '"إشعار" للرسائل المرسلة، "تنبيه" للقواعد',                 'note_en': '"إشعار" for sent messages, "تنبيه" for rules'},
    {'concept_en': 'Scheduler',            'standard_ar': 'المجدول',           'standard_en': 'Scheduler',           'variants': ['الجدول ', 'scheduler', 'Scheduler'],       'note_ar': '"المجدول" للنظام، "الجدولة" للعملية',                      'note_en': '"المجدول" for the system, "الجدولة" for the process'},
    {'concept_en': 'Backup',               'standard_ar': 'نسخة احتياطية',     'standard_en': 'Backup',              'variants': ['نسخ احتياطي', 'backup', 'Backup'],         'note_ar': '"نسخة احتياطية" مفرد، "نسخ احتياطية" جمع',                'note_en': '"نسخة احتياطية" singular, "نسخ احتياطية" plural'},
    {'concept_en': 'User / Subscriber',    'standard_ar': 'مشترك / مستخدم',    'standard_en': 'User / Subscriber',   'variants': ['يوزر', 'User', 'user'],                    'note_ar': '"مشترك" للمستخدم النهائي، "مستخدم" للحساب التقني',         'note_en': '"مشترك" for end users, "مستخدم" for system accounts'},
    {'concept_en': 'Device',               'standard_ar': 'جهاز',              'standard_en': 'Device',              'variants': ['device', 'Device', 'انفرتر'],               'note_ar': 'استخدم "جهاز" بشكل موحد',                                  'note_en': 'Use "جهاز" consistently'},
    {'concept_en': 'Dashboard',            'standard_ar': 'لوحة التحكم',       'standard_en': 'Dashboard',           'variants': ['داشبورد', 'Dashboard', 'dashboard'],       'note_ar': 'استخدم "لوحة التحكم" وليس "داشبورد"',                      'note_en': 'Use "لوحة التحكم" not "داشبورد"'},
    {'concept_en': 'Settings',             'standard_ar': 'الإعدادات',         'standard_en': 'Settings',            'variants': ['Settings', 'settings', 'التهيئة', 'Config'],'note_ar': 'استخدم "الإعدادات" باستمرار',                              'note_en': 'Use "الإعدادات" consistently'},
    {'concept_en': 'Report',               'standard_ar': 'تقرير',             'standard_en': 'Report',              'variants': ['Report', 'report', 'ريبورت'],               'note_ar': 'تجنب "ريبورت" المعرّبة',                                   'note_en': 'Avoid transliteration "ريبورت"'},
]

ISSUE_FIX_ADVICE = {
    'csrf_missing': {
        'cause_ar': 'نماذج POST بدون حقل csrf_token — أي طلب جانبي يستطيع إرسال البيانات باسم المستخدم',
        'cause_en': 'POST forms without csrf_token field — cross-site requests can submit data on behalf of the user',
        'fix_ar':   'أضف {{ form.hidden_tag() }} أو <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"> داخل كل <form method="post">',
        'fix_en':   'Add {{ form.hidden_tag() }} or <input name="csrf_token" value="{{ csrf_token() }}"> inside every <form method="post">',
        'scope_ar': 'يؤثر على كل مستخدم يملك صلاحية الوصول لهذه الصفحة',
        'scope_en': 'Affects every user with access to this page',
    },
    'sensitive_data': {
        'cause_ar': 'متغيرات حساسة (tokens, IDs) تُعرض مباشرة في HTML — مرئية عبر مصدر الصفحة',
        'cause_en': 'Sensitive variables rendered directly in HTML — visible via page source',
        'fix_ar':   'أظهر آخر 4 أحرف فقط: {{ value[-4:] }} أو انقل المنطق للـ backend',
        'fix_en':   'Show last 4 chars only: {{ value[-4:] }} or move logic to backend',
        'scope_ar': 'ثغرة خطيرة — يمكن استغلالها من أي مستخدم يرى الصفحة',
        'scope_en': 'Critical — exploitable by anyone who can view the page',
    },
    'inline_styles': {
        'cause_ar': 'أنماط CSS مضمّنة في HTML — تُصعّب الصيانة ولا يُخزّنها المتصفح مؤقتاً',
        'cause_en': 'CSS embedded in HTML — hard to maintain and not cached by browser',
        'fix_ar':   'انقل الأنماط المتكررة إلى ملف CSS، واحتفظ بـ style= للقيم الديناميكية فقط',
        'fix_en':   'Move repeated styles to CSS file; keep style= only for dynamic values',
        'scope_ar': 'يؤثر على أداء تحميل الصفحة لكل الزوار',
        'scope_en': 'Impacts page load performance for all visitors',
    },
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def _severity(score: int) -> str:
    if score >= 5: return 'high'
    if score >= 2: return 'medium'
    if score == 1: return 'low'
    return 'ok'


def audit_templates(base_dir) -> list:
    base = Path(base_dir)
    rows = []
    for path in sorted((base / 'app' / 'templates').glob('*.html')):
        text          = _read(path)
        post_forms    = len(POST_FORM_RE.findall(text))
        csrf_inputs   = len(CSRF_RE.findall(text))
        inline_styles = len(INLINE_STYLE_RE.findall(text))
        url_for_refs  = URL_FOR_RE.findall(text)
        sensitive_hits = [lbl for pat, lbl in SENSITIVE_TEMPLATE_PATTERNS if pat.search(text)]
        score, issues = 0, []
        if post_forms and csrf_inputs < post_forms:
            score += 4; issues.append('csrf_missing')
        if sensitive_hits:
            score += 5; issues.append('sensitive_data')
        if inline_styles > 12:
            score += 2; issues.append('inline_styles')
        elif inline_styles:
            score += 1
        if path.stat().st_size > 36000: score += 1
        if 'overflow:auto' not in text and path.stat().st_size > 24000: score += 1
        rows.append({
            'name': path.name,
            'relative_path': str(path.relative_to(base)),
            'size_kb': round(path.stat().st_size / 1024, 1),
            'post_forms': post_forms,
            'csrf_inputs': csrf_inputs,
            'inline_styles': inline_styles,
            'url_for_refs': len(url_for_refs),
            'sensitive_hits': sensitive_hits,
            'has_legacy_arabic': bool(ARABIC_RE.search(text)),
            'severity': _severity(score),
            'score': score,
            'issues': issues,
            'fix_advice': [ISSUE_FIX_ADVICE[i] for i in issues if i in ISSUE_FIX_ADVICE],
            'page_url':  TEMPLATE_PAGE_MAP.get(path.name, '—'),
            'page_name': TEMPLATE_PAGE_NAMES.get(path.name, {'ar': '—', 'en': '—'}),
        })
    return rows


def audit_python(base_dir) -> dict:
    base = Path(base_dir)
    py_files = sorted(list((base / 'app').glob('**/*.py')) + list((base / 'tools').glob('**/*.py')))
    files, route_count, oversized = [], 0, []
    HINTS = {
        'main.py':          'استخرج: Devices, Reports, Notifications → blueprints منفصلة',
        'helpers.py':       'قسّم إلى: sync_helpers.py, notification_helpers.py',
        'notifications.py': 'استخرج: rules.py، channels.py',
        'energy.py':        'استخرج: energy_calc.py، statistics.py',
        'admin_ops.py':     'استخرج: Users, Devices, Finance → admin blueprints',
    }
    for path in py_files:
        text   = _read(path)
        routes = len(ROUTE_RE.findall(text))
        route_count += routes
        lines  = len(text.splitlines())
        route_urls = ROUTE_URL_RE.findall(text)[:8]
        row = {'name': str(path.relative_to(base)), 'lines': lines, 'routes': routes,
               'hint': HINTS.get(path.name, ''), 'route_urls': route_urls}
        files.append(row)
        if lines > 1200: oversized.append(row)
    return {'files': files, 'routes': route_count, 'oversized': oversized}


def audit_terminology(base_dir) -> list:
    base = Path(base_dir)
    all_text = '\n'.join(_read(p) for p in (base / 'app' / 'templates').glob('*.html'))
    results = []
    for term in TERM_GLOSSARY:
        found_variants = [{'variant': v, 'count': len(re.findall(re.escape(v), all_text))}
                          for v in term['variants'] if len(re.findall(re.escape(v), all_text)) > 0]
        standard_count = len(re.findall(re.escape(term['standard_ar']), all_text))
        status = 'warning' if found_variants else ('ok' if standard_count > 0 else 'info')
        results.append({**term, 'standard_count': standard_count,
                         'found_variants': found_variants, 'status': status})
    return results


def audit_project(base_dir) -> dict:
    base          = Path(base_dir)
    template_rows = audit_templates(base)
    py_audit      = audit_python(base)
    terminology   = audit_terminology(base)
    css_path  = base / 'app' / 'static' / 'css' / 'style.css'
    main_path = base / 'app' / 'blueprints' / 'main.py'
    main_text = _read(main_path)
    high   = sum(1 for r in template_rows if r['severity'] == 'high')
    medium = sum(1 for r in template_rows if r['severity'] == 'medium')
    ok     = sum(1 for r in template_rows if r['severity'] in {'ok', 'low'})
    return {
        'summary': {
            'templates': len(template_rows),
            'python_files': len(py_audit['files']),
            'blueprints': len(sorted((base / 'app' / 'blueprints').glob('*.py'))),
            'routes': py_audit['routes'],
            'post_forms': sum(r['post_forms'] for r in template_rows),
            'csrf_inputs': sum(r['csrf_inputs'] for r in template_rows),
            'inline_styles': sum(r['inline_styles'] for r in template_rows),
            'high_risk_templates': high,
            'medium_risk_templates': medium,
            'ok_templates': ok,
            'css_kb': round(css_path.stat().st_size / 1024, 1) if css_path.exists() else 0,
            'main_py_lines': len(main_text.splitlines()),
            'architecture_split_score': max(0, 100 - max(0, len(main_text.splitlines()) - 1800) // 25),
            'terminology_warnings': sum(1 for t in terminology if t['status'] == 'warning'),
        },
        'templates':    template_rows,
        'python':       py_audit,
        'terminology':  terminology,
        'recommendations': [
            {'area': 'Security',     'ar': 'راجع أي قالب عالي الخطورة قد يعرض معرفات خاصة أو نماذج بلا CSRF.', 'en': 'Review high-risk templates for exposed secrets or POST forms without CSRF.'},
            {'area': 'Architecture', 'ar': 'استمر بتقسيم main.py إلى blueprints أصغر حسب الوظيفة.', 'en': 'Continue splitting main.py into smaller feature-based blueprints.'},
            {'area': 'Terminology',  'ar': 'وحّد المصطلحات العربية عبر كل القوالب باستخدام القاموس الموحد.', 'en': 'Unify Arabic terminology across all templates using the standard glossary.'},
            {'area': 'UI',           'ar': 'استخدم pagination لأي جدول يتجاوز 50 صفاً.', 'en': 'Add pagination to any table that may exceed 50 rows.'},
            {'area': 'Performance',  'ar': 'انقل الأنماط المتكررة من style= إلى ملفات CSS منفصلة.', 'en': 'Move repeated inline styles to dedicated CSS files.'},
        ],
    }
