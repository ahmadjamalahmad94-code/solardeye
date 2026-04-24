from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SENSITIVE_TEMPLATE_PATTERNS = [
    (re.compile(r'\{\{\s*settings\.deye_(plant_id|device_sn|logger_sn|battery_sn|email|password|password_hash|app_secret)'), 'Deye setting may be visible'),
    (re.compile(r'\{\{\s*row\.device\.(device_uid|station_id|external_device_id)'), 'Device identifier may be visible'),
    (re.compile(r'\{\{\s*settings\.(telegram_bot_token|telegram_chat_id|sms_api_key|sms_recipients)'), 'Notification/SMS secret may be visible'),
]

POST_FORM_RE = re.compile(r'<form\b(?=[^>]*method=["\']post["\'])', re.I)
CSRF_RE = re.compile(r'name=["\']csrf_token["\']', re.I)
INLINE_STYLE_RE = re.compile(r'\sstyle=["\']', re.I)
ARABIC_RE = re.compile(r'[\u0600-\u06FF]')


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def _severity(score: int) -> str:
    if score >= 5:
        return 'high'
    if score >= 2:
        return 'medium'
    if score == 1:
        return 'low'
    return 'ok'


def audit_templates(base_dir: str | Path) -> list[dict[str, Any]]:
    base = Path(base_dir)
    templates = sorted((base / 'app' / 'templates').glob('*.html'))
    rows: list[dict[str, Any]] = []
    for path in templates:
        text = _read(path)
        post_forms = len(POST_FORM_RE.findall(text))
        csrf_inputs = len(CSRF_RE.findall(text))
        inline_styles = len(INLINE_STYLE_RE.findall(text))
        sensitive_hits = []
        for pattern, label in SENSITIVE_TEMPLATE_PATTERNS:
            if pattern.search(text):
                sensitive_hits.append(label)
        hardcoded_arabic = 1 if ARABIC_RE.search(text) else 0
        score = 0
        if post_forms and csrf_inputs < post_forms:
            score += 4
        if sensitive_hits:
            score += 5
        if inline_styles > 12:
            score += 2
        elif inline_styles:
            score += 1
        if path.stat().st_size > 32000:
            score += 1
        rows.append({
            'name': path.name,
            'relative_path': str(path.relative_to(base)),
            'size_kb': round(path.stat().st_size / 1024, 1),
            'post_forms': post_forms,
            'csrf_inputs': csrf_inputs,
            'inline_styles': inline_styles,
            'sensitive_hits': sensitive_hits,
            'has_legacy_arabic': bool(hardcoded_arabic),
            'severity': _severity(score),
            'score': score,
        })
    return rows


def audit_project(base_dir: str | Path) -> dict[str, Any]:
    base = Path(base_dir)
    template_rows = audit_templates(base)
    py_files = list(base.glob('app/**/*.py')) + list(base.glob('tools/**/*.py'))
    css_path = base / 'app' / 'static' / 'css' / 'style.css'
    js_path = base / 'app' / 'static' / 'js' / 'app.js'
    main_path = base / 'app' / 'blueprints' / 'main.py'
    main_text = _read(main_path)
    routes = re.findall(r'@main_bp\.route\(', main_text)
    high = sum(1 for row in template_rows if row['severity'] == 'high')
    medium = sum(1 for row in template_rows if row['severity'] == 'medium')
    ok = sum(1 for row in template_rows if row['severity'] in {'ok', 'low'})
    return {
        'summary': {
            'templates': len(template_rows),
            'python_files': len(py_files),
            'routes': len(routes),
            'post_forms': sum(row['post_forms'] for row in template_rows),
            'csrf_inputs': sum(row['csrf_inputs'] for row in template_rows),
            'inline_styles': sum(row['inline_styles'] for row in template_rows),
            'high_risk_templates': high,
            'medium_risk_templates': medium,
            'ok_templates': ok,
            'css_kb': round(css_path.stat().st_size / 1024, 1) if css_path.exists() else 0,
            'js_kb': round(js_path.stat().st_size / 1024, 1) if js_path.exists() else 0,
            'main_py_lines': len(main_text.splitlines()),
        },
        'templates': template_rows,
        'recommendations': [
            {'area': 'Security', 'ar': 'راجع أي قالب عالي الخطورة يحتوي معرفات خاصة ظاهرة أو نماذج POST بلا CSRF ظاهر.', 'en': 'Review high-risk templates that expose private identifiers or POST forms without visible CSRF.'},
            {'area': 'UI', 'ar': 'خفف inline styles تدريجيًا وانقلها إلى style.css أو components.', 'en': 'Gradually move inline styles into style.css/components.'},
            {'area': 'Architecture', 'ar': 'استمر بتقسيم main.py إلى blueprints حسب المجالات.', 'en': 'Continue splitting main.py into domain-specific blueprints.'},
            {'area': 'Performance', 'ar': 'أضف pagination لأي جدول يتجاوز 100 عنصر.', 'en': 'Add pagination to lists that can exceed 100 records.'},
        ],
    }
