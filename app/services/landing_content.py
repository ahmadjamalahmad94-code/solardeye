from __future__ import annotations

import json
from typing import Any

from ..extensions import db
from ..models import Setting, SubscriptionPlan
from .subscriptions import plan_features

LANDING_SETTING_KEYS = [
    'site_name_ar', 'site_name_en', 'hero_badge_ar', 'hero_badge_en',
    'hero_title_ar', 'hero_title_en', 'hero_subtitle_ar', 'hero_subtitle_en',
    'hero_primary_ar', 'hero_primary_en', 'hero_secondary_ar', 'hero_secondary_en',
    'mission_ar', 'mission_en', 'vision_ar', 'vision_en', 'promise_ar', 'promise_en',
    'footer_about_ar', 'footer_about_en',
    'social_facebook', 'social_instagram', 'social_x', 'social_linkedin', 'social_telegram', 'social_whatsapp',
]

DEFAULT_LANDING_SETTINGS = {
    'site_name_ar': 'منصة الطاقة',
    'site_name_en': 'Energy Platform',
    'hero_badge_ar': 'منصة SaaS ذكية للطاقة',
    'hero_badge_en': 'Smart SaaS for energy operations',
    'hero_title_ar': 'منصة ذكية لإدارة الطاقة والأجهزة والتنبيهات',
    'hero_title_en': 'Smart platform for energy, devices, and alerts',
    'hero_subtitle_ar': 'راقب أنظمتك الشمسية، أجهزتك المتصلة، التنبيهات، الطقس، الدعم، والتقارير من واجهة واحدة احترافية.',
    'hero_subtitle_en': 'Monitor solar systems, connected devices, alerts, weather, support, and reports from one professional interface.',
    'hero_primary_ar': 'ابدأ الآن',
    'hero_primary_en': 'Start now',
    'hero_secondary_ar': 'شاهد الباقات',
    'hero_secondary_en': 'View plans',
    'mission_ar': 'نمنح أصحاب أنظمة الطاقة لوحة تشغيل واضحة تجمع الأجهزة، المشتركين، التنبيهات، الدعم، والخطط في مكان واحد.',
    'mission_en': 'We give energy operators one clear command layer for devices, subscribers, alerts, support, and plans.',
    'vision_ar': 'رؤيتنا أن تصبح إدارة الطاقة أسهل من قراءة رسالة: بيانات واضحة، قرارات أسرع، ونظام ينمو معك.',
    'vision_en': 'Our vision is to make energy operations as simple as reading a message: clear data, faster decisions, and a platform that grows with you.',
    'promise_ar': 'واجهة عربية احترافية، صلاحيات مرنة، كوتا قابلة للتخصيص، وتنبيهات مستقرة لا تضيع.',
    'promise_en': 'A professional Arabic-first interface, flexible permissions, customizable quotas, and reliable alerts.',
    'footer_about_ar': 'منصة متكاملة لإدارة الطاقة والأجهزة والتنبيهات باحترافية، مصممة لتبسيط التشغيل اليومي وتحسين قراراتك.',
    'footer_about_en': 'A professional platform for managing energy, devices, and alerts with clarity and confidence.',
    'social_facebook': '',
    'social_instagram': '',
    'social_x': '',
    'social_linkedin': '',
    'social_telegram': '',
    'social_whatsapp': '',
}

SOCIAL_LINKS = [
    ('social_facebook', 'Facebook', 'f'),
    ('social_instagram', 'Instagram', '◎'),
    ('social_x', 'X', '𝕏'),
    ('social_linkedin', 'LinkedIn', 'in'),
    ('social_telegram', 'Telegram', '✈'),
    ('social_whatsapp', 'WhatsApp', '☎'),
]


def get_setting_value(key: str, default: str = '') -> str:
    row = Setting.query.filter_by(key=f'landing.{key}').first()
    if row and row.value not in (None, ''):
        return str(row.value)
    return str(default)


def set_setting_value(key: str, value: str) -> None:
    row = Setting.query.filter_by(key=f'landing.{key}').first()
    if not row:
        row = Setting(key=f'landing.{key}')
        db.session.add(row)
    row.value = value or ''


def get_landing_settings() -> dict[str, str]:
    return {key: get_setting_value(key, DEFAULT_LANDING_SETTINGS.get(key, '')) for key in LANDING_SETTING_KEYS}


def save_landing_settings(form) -> None:
    for key in LANDING_SETTING_KEYS:
        set_setting_value(key, (form.get(key) or '').strip())


def _list_from_lines(raw: str | None) -> list[str]:
    return [line.strip() for line in str(raw or '').splitlines() if line.strip()]


def _features_dict(plan: SubscriptionPlan | None) -> dict[str, Any]:
    if not plan:
        return {}
    return plan_features(plan) or {}


def plan_landing_meta(plan: SubscriptionPlan, lang: str = 'ar') -> dict[str, Any]:
    features = _features_dict(plan)
    is_en = str(lang or 'ar').lower().startswith('en')
    subtitle = features.get('landing_subtitle_en' if is_en else 'landing_subtitle_ar') or (
        'For growing teams' if is_en else 'للمشاريع التي تريد مراقبة أوضح'
    )
    bullets_raw = features.get('landing_bullets_en' if is_en else 'landing_bullets_ar') or []
    if isinstance(bullets_raw, str):
        bullets = _list_from_lines(bullets_raw)
    elif isinstance(bullets_raw, list):
        bullets = [str(x).strip() for x in bullets_raw if str(x).strip()]
    else:
        bullets = []
    if not bullets:
        if is_en:
            bullets = [
                f'Up to {plan.max_devices} devices',
                'Smart alerts and support',
                f'{plan.duration_days_default} days package duration',
            ]
        else:
            bullets = [
                f'حتى {plan.max_devices} أجهزة',
                'تنبيهات ذكية ودعم مباشر',
                f'مدة الباقة {plan.duration_days_default} يوم',
            ]
        quota_rules = features.get('quota_rules') or {}
        sms_rule = quota_rules.get('sms_limit') or {}
        sms_monthly = ((sms_rule.get('limits') or {}).get('monthly') or '') if isinstance(sms_rule, dict) else ''
        if sms_monthly:
            bullets.insert(1, (f'{sms_monthly} SMS monthly' if is_en else f'{sms_monthly} رسالة SMS شهريًا'))
    featured = bool(features.get('landing_featured')) or (plan.code or '').lower() in {'pro', 'professional'}
    badge = features.get('landing_badge_en' if is_en else 'landing_badge_ar') or ('Most popular' if is_en else 'الأكثر شيوعًا')
    return {'subtitle': subtitle, 'bullets': bullets[:6], 'featured': featured, 'badge': badge}


def build_landing_plan_cards(lang: str = 'ar') -> list[dict[str, Any]]:
    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()
    cards = []
    for plan in plans[:3]:
        meta = plan_landing_meta(plan, lang)
        cards.append({
            'id': plan.id,
            'code': plan.code,
            'name': plan.name_en if str(lang).startswith('en') else plan.name_ar,
            'name_ar': plan.name_ar,
            'name_en': plan.name_en,
            'price': plan.price,
            'currency': plan.currency,
            'duration_days': plan.duration_days_default,
            'max_devices': plan.max_devices,
            **meta,
        })
    if cards:
        return cards
    # Safe fallback when DB has no plans yet.
    return [
        {'id': 0, 'code': 'basic', 'name': 'الأساسية', 'name_ar': 'الأساسية', 'name_en': 'Basic', 'price': 9, 'currency': 'USD', 'duration_days': 30, 'max_devices': 10, 'subtitle': 'مثالية للمشاريع الصغيرة', 'bullets': ['حتى 10 أجهزة', '50 تنبيه شهريًا', 'دعم عبر التذاكر'], 'featured': False, 'badge': ''},
        {'id': 0, 'code': 'pro', 'name': 'الاحترافية', 'name_ar': 'الاحترافية', 'name_en': 'Pro', 'price': 29, 'currency': 'USD', 'duration_days': 30, 'max_devices': 50, 'subtitle': 'للشركات والمشاريع المتوسطة', 'bullets': ['حتى 50 جهاز', '200 تنبيه شهريًا', 'تقارير متقدمة'], 'featured': True, 'badge': 'الأكثر شيوعًا'},
        {'id': 0, 'code': 'platinum', 'name': 'البلاتينية', 'name_ar': 'البلاتينية', 'name_en': 'Platinum', 'price': 79, 'currency': 'USD', 'duration_days': 30, 'max_devices': 999, 'subtitle': 'للمشاريع الكبيرة والمؤسسات', 'bullets': ['أجهزة غير محدودة', 'تنبيهات متقدمة', 'واجهة API'], 'featured': False, 'badge': ''},
    ]


def update_plan_landing_meta(plan: SubscriptionPlan, form, prefix: str) -> None:
    features = _features_dict(plan)
    features['landing_subtitle_ar'] = (form.get(f'{prefix}_subtitle_ar') or '').strip()
    features['landing_subtitle_en'] = (form.get(f'{prefix}_subtitle_en') or '').strip()
    features['landing_bullets_ar'] = _list_from_lines(form.get(f'{prefix}_bullets_ar'))
    features['landing_bullets_en'] = _list_from_lines(form.get(f'{prefix}_bullets_en'))
    features['landing_badge_ar'] = (form.get(f'{prefix}_badge_ar') or '').strip()
    features['landing_badge_en'] = (form.get(f'{prefix}_badge_en') or '').strip()
    features['landing_featured'] = form.get(f'{prefix}_featured') == 'on'
    plan.features_json = json.dumps(features, ensure_ascii=False)
