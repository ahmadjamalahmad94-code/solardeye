from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


RENDER_TEMPLATE_RE = re.compile(r"render_template\(\s*['\"]([^'\"]+)['\"]")

EXCLUDED_BLUEPRINT_FILES = {
    'mobile_api.py',
    'mobile_auth_api.py',
    'mobile_devices_api.py',
    'mobile_notifications_api.py',
    'mobile_support_api.py',
    'openapi_api.py',
    'fleet_api.py',
}

WEB_PAGE_REGISTRY = [
    {'system': 'الصفحة الرئيسية', 'section': 'Public web', 'route': '/', 'template': 'landing.html'},
    {'system': 'تسجيل الدخول', 'section': 'Auth web', 'route': '/login', 'template': 'login.html'},
    {'system': 'إنشاء حساب', 'section': 'Auth web', 'route': '/register', 'template': 'register.html'},
    {'system': 'معالج الإعداد', 'section': 'Subscriber web', 'route': '/onboarding', 'template': 'onboarding_wizard.html'},
    {'system': 'لوحة المشترك', 'section': 'Subscriber web', 'route': '/dashboard', 'template': 'dashboard.html'},
    {'system': 'الملف الشخصي', 'section': 'Subscriber web', 'route': '/account/profile', 'template': 'account_profile.html'},
    {'system': 'الاشتراك', 'section': 'Subscriber web', 'route': '/account/subscription', 'template': 'account_subscription_phase1a.html'},
    {'system': 'إدارة الأجهزة', 'section': 'Subscriber web', 'route': '/devices/manage', 'template': 'devices_manage.html'},
    {'system': 'الأحمال', 'section': 'Subscriber web', 'route': '/loads', 'template': 'loads.html'},
    {'system': 'الإشعارات', 'section': 'Subscriber web', 'route': '/notifications', 'template': 'notifications.html'},
    {'system': 'قنوات الإرسال', 'section': 'Subscriber web', 'route': '/channels', 'template': 'channels.html'},
    {'system': 'مركز الإشعارات', 'section': 'Subscriber web', 'route': '/notifications/center', 'template': 'notifications_center.html'},
    {'system': 'الدعم', 'section': 'Subscriber web', 'route': '/portal/support', 'template': 'portal_support.html'},
    {'system': 'التقارير', 'section': 'Subscriber web', 'route': '/reports', 'template': 'reports.html'},
    {'system': 'الإحصائيات', 'section': 'Subscriber web', 'route': '/statistics', 'template': 'statistics.html'},
    {'system': 'البيانات الحية', 'section': 'Subscriber web', 'route': '/live-data', 'template': 'live_data.html'},
    {'system': 'لوحة الإدارة', 'section': 'Admin web', 'route': '/admin/dashboard', 'template': 'admin_dashboard.html'},
    {'system': 'مختبر جودة التصميم', 'section': 'Admin web', 'route': '/admin/design-qa', 'template': 'admin_design_qa.html'},
    {'system': 'مراجعة المنصة', 'section': 'Admin web', 'route': '/admin/platform-review', 'template': 'admin_platform_review.html'},
    {'system': 'مركز الأجهزة', 'section': 'Admin web', 'route': '/admin/devices', 'template': 'admin_devices_center.html'},
    {'system': 'التكاملات', 'section': 'Admin web', 'route': '/admin/integrations', 'template': 'admin_integrations.html'},
    {'system': 'صحة الخدمات', 'section': 'Admin web', 'route': '/admin/services-health', 'template': 'admin_services_health.html'},
    {'system': 'الباقات', 'section': 'Admin web', 'route': '/admin/plans', 'template': 'admin_plans_phase1a.html'},
    {'system': 'المالية', 'section': 'Admin web', 'route': '/admin/finance', 'template': 'admin_finance.html'},
    {'system': 'الأدوار', 'section': 'Admin web', 'route': '/admin/roles', 'template': 'admin_roles.html'},
    {'system': 'سجل العمليات', 'section': 'Admin web', 'route': '/admin/activity-log', 'template': 'admin_activity_log.html'},
    {'system': 'سجلات النظام', 'section': 'Admin web', 'route': '/admin/system-logs', 'template': 'admin_system_logs.html'},
    {'system': 'النسخ الاحتياطي', 'section': 'Admin web', 'route': '/admin/backups', 'template': 'admin_backups.html'},
    {'system': 'المشتركون', 'section': 'Admin web', 'route': '/admin/subscribers', 'template': 'admin_subscribers_phase1a.html'},
    {'system': 'الاشتراكات', 'section': 'Admin web', 'route': '/admin/subscriptions', 'template': 'admin_subscriptions.html'},
    {'system': 'مركز الدعم الإداري', 'section': 'Admin web', 'route': '/admin/support-command-center', 'template': 'admin_support_command_center.html'},
    {'system': 'البريد الداخلي', 'section': 'Admin web', 'route': '/admin/mail', 'template': 'admin_internal_mail.html'},
    {'system': 'فريق الإدارة', 'section': 'Admin web', 'route': '/admin/team', 'template': 'admin_users.html'},
    {'system': 'ملف مستخدم إداري', 'section': 'Admin web', 'route': '/admin/users/<int:user_id>', 'template': 'admin_user_profile.html'},
    {'system': 'إعدادات الصفحة الرئيسية', 'section': 'Admin web', 'route': '/admin/landing-settings', 'template': 'admin_landing_settings.html'},
    {'system': 'سجل التنبيهات', 'section': 'Admin web', 'route': '/alerts', 'template': 'alerts.html'},
]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return ''


def _is_web_rule(rule: Any) -> bool:
    endpoint = rule.endpoint or ''
    path = rule.rule or ''
    if endpoint == 'static':
        return False
    if path.startswith('/api'):
        return False
    if 'mobile' in endpoint.lower():
        return False
    return True


def _route_index(app: Any) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for rule in app.url_map.iter_rules():
        if not _is_web_rule(rule):
            continue
        methods = sorted((rule.methods or set()) - {'HEAD', 'OPTIONS'})
        index.setdefault(rule.rule, []).append({
            'endpoint': rule.endpoint,
            'methods': methods,
        })
    return index


def _render_template_sources(base: Path) -> dict[str, list[dict[str, Any]]]:
    sources: dict[str, list[dict[str, Any]]] = {}
    blueprints_dir = base / 'app' / 'blueprints'
    for path in sorted(blueprints_dir.glob('*.py')):
        if path.name in EXCLUDED_BLUEPRINT_FILES:
            continue
        text = _read(path)
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            for lineno, line in enumerate(lines, start=1):
                for template_name in RENDER_TEMPLATE_RE.findall(line):
                    sources.setdefault(template_name, []).append({
                        'file': str(path.relative_to(base)).replace('\\', '/'),
                        'line': lineno,
                        'snippet': line.strip()[:180],
                    })
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', '')
            if func_name != 'render_template' or not node.args:
                continue
            first_arg = node.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue
            lineno = getattr(node, 'lineno', 1)
            template_name = first_arg.value
            sources.setdefault(template_name, []).append({
                'file': str(path.relative_to(base)).replace('\\', '/'),
                'line': lineno,
                'snippet': (lines[lineno - 1].strip() if 0 <= lineno - 1 < len(lines) else 'render_template(...)')[:180],
            })
    return sources


def _detail_payload(system: dict[str, Any], route_matches: list[dict[str, Any]], source_matches: list[dict[str, Any]], template_exists: bool) -> dict[str, Any]:
    return {
        'system': system['system'],
        'section': system['section'],
        'route': system['route'],
        'template': system['template'],
        'route_matches': route_matches,
        'template_exists': template_exists,
        'render_template_sources': source_matches,
    }


def _source_status(route_exists: bool, template_exists: bool, source_matches: list[dict[str, Any]]) -> tuple[str, str, str]:
    if route_exists and template_exists and source_matches:
        return 'strong', 'ok', 'المسار والقالب ومصدر render_template موجودة.'
    if route_exists and template_exists:
        return 'weak', 'medium', 'المسار والقالب موجودان، لكن لم يظهر مصدر render_template مباشر في ملفات الويب المفحوصة.'
    if route_exists:
        return 'missing_template', 'high', 'المسار موجود لكن القالب المتوقع غير موجود.'
    if template_exists:
        return 'missing_route', 'high', 'القالب موجود لكن المسار المتوقع غير موجود.'
    return 'missing_route_template', 'high', 'المسار والقالب المتوقعان غير موجودين.'


def build_web_design_qa(app: Any, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Build a web-only Design QA snapshot.

    This intentionally scans web routes and templates only. It does not inspect
    or grade machine-client endpoints, provider integrations, schedulers, or
    background dispatch logic.
    """
    base = Path(base_dir or Path(app.root_path).parent)
    templates_dir = base / 'app' / 'templates'
    routes = _route_index(app)
    render_sources = _render_template_sources(base)

    source_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for system in WEB_PAGE_REGISTRY:
        template_path = templates_dir / system['template']
        template_exists = template_path.exists()
        route_matches = routes.get(system['route'], [])
        route_exists = bool(route_matches)
        source_matches = render_sources.get(system['template'], [])
        source_status, severity, evidence = _source_status(route_exists, template_exists, source_matches)
        detail_payload = _detail_payload(system, route_matches, source_matches, template_exists)

        source_rows.append({
            'system': system['system'],
            'section': system['section'],
            'template': system['template'],
            'route': system['route'],
            'issue_type': 'source_verification',
            'severity': severity,
            'status': source_status,
            'evidence': evidence,
            'recommendation': 'اربط الصف بمصدر route/render_template حقيقي أو صحح اسم القالب/المسار.' if severity != 'ok' else 'لا يلزم إجراء.',
            'detail_payload': detail_payload,
            'detail_url': system['route'],
        })

        route_rows.append({
            'system': system['system'],
            'section': system['section'],
            'template': system['template'],
            'route': system['route'],
            'issue_type': 'route_template_mapping',
            'severity': 'ok' if route_exists and template_exists else 'high',
            'status': 'ok' if route_exists and template_exists else 'broken',
            'evidence': 'المسار والقالب موجودان.' if route_exists and template_exists else 'يوجد نقص في المسار أو القالب.',
            'recommendation': 'لا يلزم إجراء.' if route_exists and template_exists else 'صحح سجل Design QA أو أصلح المسار/القالب الويب المفقود.',
            'route_matches': route_matches,
            'detail_payload': detail_payload,
            'detail_url': system['route'] if route_exists else '',
        })

        if severity != 'ok':
            issue_type = 'missing_source_evidence' if source_status == 'weak' else source_status
            issues.append({
                'system': system['system'],
                'section': system['section'],
                'template': system['template'],
                'route': system['route'],
                'issue_type': issue_type,
                'severity': severity,
                'evidence': evidence,
                'recommendation': 'راجع اسم القالب والمسار ومصدر render_template. لا تعتبر الصف ناجحًا حتى توجد أدلة مصدر واضحة.',
                'detail_payload': detail_payload,
                'detail_url': system['route'] if route_exists else '',
            })

    duplicate_web_routes = [
        {
            'route': route,
            'endpoints': [entry['endpoint'] for entry in entries],
            'methods': sorted({method for entry in entries for method in entry['methods']}),
        }
        for route, entries in sorted(routes.items())
        if len(entries) > 1 and route in {item['route'] for item in WEB_PAGE_REGISTRY}
    ]

    deferred = [
        {
            'system': 'المسارات ذات المعاملات',
            'reason': 'يفحص هذا المركز وجود mapping فقط، ولا يفتح صفحات تحتاج معرفات حقيقية مثل ملف مستخدم محدد.',
        },
        {
            'system': 'نماذج POST و CSRF',
            'reason': 'الفحص الحالي يثبت وجود صفحات الويب ومصادرها. فحص CSRF العميق مؤجل لتذكرة أمان منفصلة حتى لا يخلط Design QA مع منطق الحماية.',
        },
    ]

    summary = {
        'systems': len(WEB_PAGE_REGISTRY),
        'routes_checked': len(route_rows),
        'source_rows': len(source_rows),
        'issues': len(issues),
        'high': sum(1 for row in issues if row['severity'] == 'high'),
        'medium': sum(1 for row in issues if row['severity'] == 'medium'),
        'ok_sources': sum(1 for row in source_rows if row['severity'] == 'ok'),
        'duplicate_web_routes': len(duplicate_web_routes),
    }

    return {
        'summary': summary,
        'issues': issues,
        'source_rows': source_rows,
        'route_rows': route_rows,
        'duplicate_web_routes': duplicate_web_routes,
        'deferred': deferred,
    }
