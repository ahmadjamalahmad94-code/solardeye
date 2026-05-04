# SolarDeye — BUILD GUIDE (Companion to Design System)

> **This is the second half of the design package.** It contains:
>
> 1. A copy-paste prompt template for any AI.
> 2. Embedded full source of the three foundation files an AI needs to wire a new page (`_sidebar.html`, `base.html` skeleton, `sun_context.py`).
> 3. The `setBind` JS helper and the live-poller pattern in their full canonical form.
> 4. A 9-step walk-through for building a new page from scratch.
> 5. A validation checklist (acceptance criteria) so an AI knows when to stop.
>
> Use this file **alongside** `SOLARDEYE_DESIGN_SYSTEM.md`. Together they push the AI's reproduction accuracy from ~85% to ~95%+.

---

## 1. The canonical prompt (copy this verbatim)

```
You are building a new page inside the SolarDeye web app.

Read these reference files in order before writing a single line of code:

  1.  SOLARDEYE_DESIGN_SYSTEM.md    — every visual token + rule
  2.  SOLARDEYE_BUILD_GUIDE.md      — embedded source + walkthrough
  3.  app/templates/dashboard.html  — closest reference template

Your task:
  • Page name:           {{ page name in Arabic }}
  • Page route (Flask):  {{ /your-route }}
  • Page purpose:        {{ what users do on this page }}
  • Class prefix:        {{ pp- }}        (must be unique, 2-3 letters)
  • RTL?                 yes (Arabic-first)
  • Time-aware?          {{ yes if it shows anything that changes with time of day }}

Hard requirements (NO exceptions):
  ☐ Extends `base.html`, body inside `{% block body %}`
  ☐ Includes `{% include '_sidebar.html' %}`
  ☐ Top-level <div class="pp-page" dir="..."> with the canonical CSS variables
  ☐ Hero section uses the sky→amber gradient + eyebrow + h1 + meta + actions
  ☐ White cards on the soft sky-blue gradient page background
  ☐ KPI strip uses 4-6 colored-accent cards with the standard anatomy
  ☐ Tables use #f5f9ff header + #e3eaf6 borders + first-column pill
  ☐ Buttons: primary = amber gradient #ffcf4d→#f59e0b, secondary = white
  ☐ Inter-section gap = 24px (set on .pp-page flex), inter-card gap = 18px
  ☐ Numbers always tabular-nums, weight 950 for hero values
  ☐ font-family: 'Cairo','Inter',system-ui,sans-serif
  ☐ Time-aware widgets MUST consume `sun_ctx` from the route — never compute
    `is_day = solar_power > 50` or any ad-hoc heuristic
  ☐ If the page polls /api/live, read `sun_phase` first, raw `weather` only
    as fallback
  ☐ Final HTML must pass jinja2.parse() without errors
  ☐ Must work in RTL (test by setting dir="rtl")
  ☐ Forbidden: dark navy panels, hardcoded hours, "بحذر" duplication,
    "أعلى من الحالي" during descent phases

Acceptance test before declaring done:
  1. Open the file in a browser. Hero is sky-gradient, full-width.
  2. KPI cards have a 5px colored top strip and lift on hover.
  3. At 7:21 PM the page shows night/sunset icons + advice (if time-aware).
  4. Resizing to 480 px keeps everything readable; nothing overlaps.
  5. Tab order is logical; focus rings are amber 0 0 0 3px rgba(245,158,11,.18).

Deliver one .html file. No external CSS files. Inline <style> at top of
the {% block body %}.
```

---

## 2. Reference source files (embedded)

### 2.1 `app/templates/_sidebar.html` (full file)

```jinja2
﻿{% set is_en = (ui_lang or 'ar') == 'en' %}
{% set unread_total = (g.mail_notification_count or 0) + (g.ticket_notification_count or 0) %}

{% macro icon(name) -%}
  {% set paths = {
    'grid':'<path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z"/>',
    'users':'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    'user-check':'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="m16 11 2 2 4-4"/>',
    'headset':'<path d="M3 14v-1a9 9 0 0 1 18 0v1"/><path d="M5 14h3v6H5a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2Z"/><path d="M16 14h3a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2h-3v-6Z"/><path d="M13 20h3"/>',
    'tag':'<path d="M20.59 13.41 11 3.83A2.83 2.83 0 0 0 9 3H4a1 1 0 0 0-1 1v5a2.83 2.83 0 0 0 .83 2l9.58 9.59a2 2 0 0 0 2.83 0l4.35-4.35a2 2 0 0 0 0-2.83Z"/><circle cx="7.5" cy="7.5" r=".5"/>',
    'monitor':'<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    'link':'<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    'activity':'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    'shield':'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    'home':'<path d="m3 10 9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/>',
    'phone':'<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M12 18h.01"/>',
    'database':'<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/>',
    'wallet':'<path d="M20 7H5a2 2 0 0 0 0 4h15v8H5a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3h13v4"/><path d="M16 14h.01"/>',
    'clock':'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    'lock':'<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    'panel':'<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h5"/>',
    'zap':'<path d="M13 2 3 14h8l-1 8 11-13h-8l1-7Z"/>',
    'wand':'<path d="m15 4 5 5-9 9-5-5 9-9Z"/><path d="m4 20 3-3"/><path d="M9 5 7 3M19 15l2 2M3 9l2-2"/>',
    'id':'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M15 8h2M15 12h2M7 16h4"/>',
    'user':'<path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/>',
    'chart':'<path d="M3 3v18h18"/><path d="M7 16V9M12 16V5M17 16v-3"/>',
    'file':'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h6"/>',
    'gauge':'<path d="M12 14 16 9"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/><path d="M12 21a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2Z"/>',
    'bell':'<path d="M18 8a6 6 0 1 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    'send':'<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    'message':'<path d="M21 15a4 4 0 0 1-4 4H7l-4 4V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M8 9h8M8 13h5"/>',
    'logout':'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    'menu':'<path d="M4 6h16M4 12h16M4 18h16"/>',
    'inbox':'<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>'
  } %}
  <svg class="hs-icon-v180" viewBox="0 0 24 24" aria-hidden="true">{{ paths.get(name, paths['grid'])|safe }}</svg>
{%- endmacro %}

{% macro nav_item(key, label_ar, label_en, endpoint_names, href, icon_name, badge=0) -%}
  {% set active = request.endpoint in endpoint_names %}
  {% set shown_label = label_en if is_en else label_ar %}
  <a class="sd-nav-item-v11 {% if active %}active{% endif %}" href="{{ href }}" title="{{ shown_label }}" aria-label="{{ shown_label }}" data-label="{{ shown_label }}">
    <span class="sd-nav-icon-v11">{{ icon(icon_name) }}</span>
    <span class="sd-nav-text-v11">{{ shown_label }}</span>
    {% if badge %}<span class="sd-nav-badge-v11">{{ badge }}</span>{% endif %}
  </a>
{%- endmacro %}

<aside class="sd-sidebar-v11 {% if g.is_admin %}sd-admin-v11{% else %}sd-subscriber-v11{% endif %}" id="sidebarV11" data-sidebar-v11>
  <div class="sd-sidebar-head-v11">
    <button class="sd-menu-btn-v11" id="sdSidebarToggleV21" type="button" data-sd-toggle-sidebar-v21 aria-label="{{ 'Menu' if is_en else 'القائمة' }}">
      {{ icon('menu') }}
    </button>

    <div class="sd-user-v11">
      <div class="sd-avatar-v11">MA<span></span></div>
      <div class="sd-user-copy-v11">
        <strong>{{ g.current_user_display or ('Ø§Ù„Ù…Ø´Ø±Ù Ø§Ù„Ø§ÙØªØ±Ø§Ø¶ÙŠ' if g.is_admin else 'المستخدم') }}</strong>
        <small>{{ 'Platform manager' if (g.is_admin and is_en) else ('مدير المنصة' if g.is_admin else ('Current account' if is_en else 'الحساب الحالي')) }}</small>
      </div>
    </div>

    <div class="sd-lang-v11">
      <a class="{% if not is_en %}active{% endif %}" href="{{ lang_url('ar') }}">عربي</a>
      <a class="{% if is_en %}active{% endif %}" href="{{ lang_url('en') }}">English</a>
    </div>
  </div>

  <nav class="sd-nav-v11" aria-label="{{ 'Main navigation' if is_en else 'القائمة الرئيسية' }}">
    {% if g.is_admin %}
      <div class="sd-group-title-v11"><span>{{ 'Administration' if is_en else 'الإدارة' }}</span></div>
      {{ nav_item('admin_dashboard','لوحة الإدارة','Dashboard',['main.admin_dashboard','energy.admin_dashboard'],url_for('main.admin_dashboard', lang=ui_lang),'grid') }}
      {{ nav_item('notification_center','مركز الإشعارات','Notification Center',['notifications_routes.notification_center','main.notification_center'],url_for('main.notification_center', lang=ui_lang),'inbox', unread_total) }}
      {% if has_permission('can_manage_users') or has_permission('can_manage_roles') %}{{ nav_item('team','فريق الإدارة','Admin Team',['users_routes.admin_team','users_routes.admin_users_legacy','main.admin_users_legacy','users_routes.admin_user_profile','main.admin_user_profile'],url_for('users_routes.admin_team', lang=ui_lang),'users') }}{% endif %}
      {% if has_permission('can_manage_users') or has_permission('can_manage_subscriptions') %}{{ nav_item('subscribers','إدارة المستفيدين','Subscribers',['admin_ops.admin_subscribers_v9','billing.admin_subscribers','billing.admin_subscriber_activate','main.admin_subscribers','main.admin_subscriber_activate'],url_for('main.admin_subscribers', lang=ui_lang),'user-check') }}{% endif %}
      {% if has_permission('can_manage_support') %}{{ nav_item('support','مركز الدعم','Support Center',['support.admin_support_command_center','main.admin_support_command_center'],url_for('main.admin_support_command_center', lang=ui_lang),'headset', unread_total) }}{% endif %}
      {% if has_permission('can_manage_subscriptions') or has_permission('can_manage_users') %}{{ nav_item('plans','الخطط والعروض','Plans & Offers',['billing.admin_plans','billing.admin_plan_create','billing.admin_plan_edit','main.admin_plans','main.admin_plan_create','main.admin_plan_edit'],url_for('main.admin_plans', lang=ui_lang),'tag') }}{% endif %}
      {% if has_permission('can_manage_devices') %}{{ nav_item('devices','الأجهزة','Devices',['admin_ops.admin_devices_center_v9'],url_for('admin_ops.admin_devices_center_v9', lang=ui_lang),'monitor') }}{% endif %}
      {% if has_permission('can_manage_integrations') %}{{ nav_item('integrations','أنواع الأجهزة / التكاملات','Device Types / Integrations',['integrations.admin_integrations','integrations.admin_test_device_integration'],url_for('integrations.admin_integrations', lang=ui_lang),'link') }}{% endif %}
      {% if has_permission('can_view_logs') %}{{ nav_item('health','صحة الخدمات','Services Health',['admin_ops.admin_services_health_v9'],url_for('admin_ops.admin_services_health_v9', lang=ui_lang),'activity') }}{% endif %}
      {% if has_permission('can_view_logs') %}{{ nav_item('review','مراجعة المنصة','Platform Review',['platform.admin_platform_review'],url_for('platform.admin_platform_review', lang=ui_lang),'shield') }}{% endif %}
      {% if has_permission('can_manage_system') or has_permission('can_manage_users') %}{{ nav_item('home','الصفحة الرئيسية','Homepage',['platform.admin_landing_settings'],url_for('platform.admin_landing_settings', lang=ui_lang),'home') }}{% endif %}
      {% if has_permission('can_manage_system') or has_permission('can_access_mobile_api') %}{{ nav_item('mobile','توثيق تطبيق الموبايل','Mobile API Docs',['openapi_api.api_docs','openapi_api.openapi_json'],url_for('openapi_api.api_docs', lang=ui_lang),'phone') }}{% endif %}
      {% if has_permission('can_manage_backups') or has_permission('can_view_logs') %}{{ nav_item('backups','النسخ والاستعادة','Backups & Recovery',['platform.admin_backups','platform.admin_backup_download'],url_for('platform.admin_backups', lang=ui_lang),'database') }}{% endif %}
      {% if has_permission('can_manage_finance') %}{{ nav_item('finance','المحفظة والمالية','Wallet & Finance',['billing.admin_finance','main.admin_finance'],url_for('main.admin_finance', lang=ui_lang),'wallet') }}{% endif %}
      {% if has_permission('can_view_logs') %}{{ nav_item('activity','سجل العمليات','Activity Log',['users_routes.admin_activity_log','main.admin_activity_log'],url_for('main.admin_activity_log', lang=ui_lang),'clock') }}{% endif %}
      {% if has_permission('can_manage_roles') or has_permission('can_manage_users') %}{{ nav_item('roles','الأدوار والصلاحيات','Roles & Permissions',['access_control.admin_roles_v10','main.admin_roles'],url_for('access_control.admin_roles_v10', lang=ui_lang),'lock') }}{% endif %}
      {% if has_permission('can_view_logs') %}{{ nav_item('logs','لوح النظام والخدمات','System Logs',['users_routes.admin_system_logs','main.admin_system_logs'],url_for('main.admin_system_logs', lang=ui_lang),'panel') }}{% endif %}
    {% else %}
      <div class="sd-group-title-v11"><span>{{ 'Portal' if is_en else 'البوابة' }}</span></div>
      {% if portal_page_visible('dashboard') %}{{ nav_item('overview','النظرة العامة','Overview',['energy.dashboard','main.dashboard'],url_for('main.dashboard', lang=ui_lang),'grid') }}{% endif %}
      {{ nav_item('notification_center','مركز الإشعارات','Notification Center',['notifications_routes.notification_center','main.notification_center'],url_for('main.notification_center', lang=ui_lang),'inbox', unread_total) }}
      {% if portal_page_visible('devices_manage') %}{{ nav_item('devices','أجهزتي','My Devices',['devices_routes.devices_manage','main.devices_manage','devices_routes.device_edit','main.device_edit'],url_for('main.devices_manage', lang=ui_lang),'monitor') }}{% endif %}
      {% if portal_page_visible('profile') %}{{ nav_item('profile','الملف الشخصي','Profile',['devices_routes.account_profile','main.account_profile'],url_for('main.account_profile', lang=ui_lang),'user') }}{% endif %}
      {% if portal_page_visible('onboarding') %}{{ nav_item('wizard','معالج الإعداد','Setup Wizard',['devices_routes.onboarding_wizard','main.onboarding_wizard'],url_for('main.onboarding_wizard', lang=ui_lang),'wand') }}{% endif %}
      {% if portal_page_visible('subscription') %}{{ nav_item('subscription','اشتراكي','Subscription',['billing.account_subscription','main.account_subscription'],url_for('main.account_subscription', lang=ui_lang),'id') }}{% endif %}
      <div class="sd-group-title-v11"><span>{{ 'Monitoring' if is_en else 'المتابعة' }}</span></div>
      {% if portal_page_visible('statistics') %}{{ nav_item('statistics','الإحصائيات','Statistics',['energy.statistics','main.statistics'],url_for('main.statistics', lang=ui_lang),'chart') }}{% endif %}
      {% if portal_page_visible('reports') %}{{ nav_item('reports','التقارير','Reports',['energy.reports','main.reports'],url_for('main.reports', lang=ui_lang),'file') }}{% endif %}
      {% if portal_page_visible('live_data') %}{{ nav_item('live','البيانات الحية','Live Data',['energy.live_data','main.live_data'],url_for('main.live_data', lang=ui_lang),'activity') }}{% endif %}
      {% if portal_page_visible('loads') %}{{ nav_item('loads','الأحمال','Loads',['energy.loads_page','main.loads_page'],url_for('main.loads_page', lang=ui_lang),'gauge') }}{% endif %}
      {% if portal_page_visible('notifications') %}{{ nav_item('notifications','الإشعارات','Notifications',['notifications_routes.notifications_settings','main.not```

### 2.2 `app/templates/base.html` (skeleton — edit nothing in here)

```jinja2
﻿<!doctype html>
<html lang="{{ ui_lang or 'ar' }}" dir="{{ 'ltr' if (ui_lang or 'ar') == 'en' else 'rtl' }}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  {% if session.get('logged_in') or request.endpoint in ['auth.login','auth.register'] %}<meta name="csrf-token" content="{{ csrf_token() }}">{% endif %}
  <title>{% block title %}{{ t(title or 'SolarDeye Platform') }}{% endblock %}</title>
  <script id="solar-scroll-guard-v104">if(!location.hash&&'scrollRestoration'in history){history.scrollRestoration='manual';window.scrollTo(0,0);}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
  {% if (ui_lang or 'ar') == 'en' %}
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  {% else %}
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.rtl.min.css" rel="stylesheet">
  {% endif %}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css', v='v77-account-profile-20260502') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/sidebar_rebuild_v11.css', v='v77-account-profile-20260502') }}">
  {% block extra_head %}{% endblock %}
</head>
<body class="theme-saas saas-only heavy-v70 heavy-v71 heavy-v72 heavy-v721 heavy-v80 heavy-v90 heavy-v100 no-global-utility-bar {% if account_preview_restricted %}account-preview-v107{% endif %}" data-lang="{{ ui_lang or 'ar' }}" data-account-restricted="{{ '1' if account_preview_restricted else '0' }}" data-restricted-message="{{ account_preview_message|e }}" data-csrf-token="{{ csrf_token() if session.get('logged_in') or request.endpoint in ['auth.login','auth.register'] else '' }}">
  {% include '_header_notifications.html' %}
  {% if account_preview_restricted %}
    <div class="account-preview-banner-v107" role="status" aria-live="polite">
      <strong>{{ 'Preview mode' if (ui_lang or 'ar') == 'en' else 'وضع مشاهدة فقط' }}</strong>
      <span>{{ account_preview_message }}</span>
      <a href="{{ url_for('main.account_subscription', lang=ui_lang) }}">{{ 'Activate account' if (ui_lang or 'ar') == 'en' else 'تفعيل الحساب' }}</a>
    </div>
  {% endif %}
  {% set flash_excluded = ['auth.login','auth.register','main.dashboard','main.devices_manage','devices_routes.account_profile','main.account_profile','main.notifications_settings','main.loads_page','main.channels','main.onboarding_wizard'] %}
  {% if request.endpoint not in flash_excluded %}
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="flash-stack-v61" role="status" aria-live="polite">
          {% for category, message in messages %}
            <div class="flash-toast-v61 {{ category }}"><span>{{ '✅' if category == 'success' else ('⚠️' if category == 'warning' else ('❌' if category == 'danger' else 'ℹ️')) }}</span><p>{{ t(message) }}</p></div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
  {% endif %}
  <div class="dev-build-badge-v11">Build: v77-account-profile-20260502</div>

  {% block body %}{% endblock %}
  {% block content %}{% endblock %}
  <script>window.SOLARDEYE_I18N = {{ i18n_client_catalog_json|safe }};</script>
  <script defer src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
  <script defer src="{{ url_for('static', filename='js/app.js', v='v77-account-profile-20260502') }}"></script>
  <script src="{{ url_for('static', filename='js/sidebar_rebuild_v11.js', v='v77-account-profile-20260```


### 2.3 `app/services/sun_context.py` (FULL — copy verbatim if absent)

This is the spine of all time-aware intelligence. Any new page that talks
about "now", "the sun", "production", or "the night" *must* import and
consume this. Never reimplement the phase logic.

```python
"""SunContext — the *single source of truth* for "what time of day is it, and
what does that mean for solar production".

Every dashboard widget that needs to answer questions like
  "is the sun up?", "is it producing?", "is it night?", "what icon should
  I show?", "what's a contextually-correct piece of advice?" — must consume
  this object instead of computing its own boolean from `solar_power > 50`.

Design
──────
This module is a *thin wrapper* over the existing `classify_day_phase` in
`app/services/utils.py` (which already returns 9 phases: night, dawn,
sunrise, morning, noon, afternoon, pre_sunset, sunset, dusk).  We add
production-aware metadata on top:

  * `is_day_for_production`  — was it sunny enough that the inverter could
    realistically produce non-trivial power?  This is *not* the same as
    "the sun is geometrically above the horizon" — it accounts for the
    pre-dawn / dusk twilight where production is essentially zero.
  * `weather_icon_for(condition)` — picks the right emoji given current
    phase × current weather condition.  Chooses 🌙 over ☀️ at night even
    if the API returned "Clear".
  * `decision_matrix(confidence, risk, surplus_kwh)` — central decision
    logic for the smart-prediction card so every layer uses the same one.
  * `phase_message_for_smart_card()` — non-conflicting copy used by the
    smart-prediction widget.  No more "the sun is shining" + "expect
    surplus drop in 30 minutes" in the same paragraph.

Public entry point: `compute_sun_context(latest, weather, settings)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .utils import classify_day_phase, utc_to_local


# All possible phases (ordered by time of day).
_PHASE_ORDER = [
    'night', 'dawn', 'sunrise', 'morning', 'noon',
    'afternoon', 'pre_sunset', 'sunset', 'dusk',
]

# Phases where the inverter can produce *meaningful* DC power.
_PRODUCTIVE_PHASES = {'sunrise', 'morning', 'noon', 'afternoon', 'pre_sunset'}

# Phases that count as "night" for the weather widget icon.
_NIGHT_PHASES = {'night', 'dusk'}

# Phases that count as "twilight" (no production but not full night).
_TWILIGHT_PHASES = {'dawn', 'sunset'}


@dataclass(frozen=True)
class SunContext:
    """Fully-resolved picture of the current solar moment."""

    # ── time anchors ──────────────────────────────────────────────────
    now_local: datetime
    timezone_name: str
    sunrise_text: str           # "HH:MM" today
    sunset_text: str            # "HH:MM" today (official)
    sunset_effective_text: str  # production cutoff (~1h before official)

    # ── phase ─────────────────────────────────────────────────────────
    phase: str                  # one of _PHASE_ORDER values
    label_ar: str
    label_en: str
    icon: str                   # emoji selected purely from phase
    description_ar: str
    description_en: str
    accent: str                 # hex color associated with the phase
    gradient: str               # css gradient

    # ── production-aware flags ────────────────────────────────────────
    is_day_for_production: bool
    is_night: bool
    is_twilight: bool
    is_producing_meaningfully: bool   # solar_power > 100 W *and* phase ∈ productive

    # ── time deltas ───────────────────────────────────────────────────
    minutes_to_sunset: int
    minutes_to_sunrise: int

    # ── meta about source data ────────────────────────────────────────
    has_weather_times: bool

    # ── derived helpers ───────────────────────────────────────────────
    @property
    def is_pre_sunset_window(self) -> bool:
        """True in the last ~90 minutes before effective sunset — when
        the user should think about finishing battery charge."""
        return self.phase in {'pre_sunset', 'sunset'}

    @property
    def is_morning_window(self) -> bool:
        return self.phase in {'sunrise', 'morning'}

    # ── icon adapted to weather condition ─────────────────────────────
    def weather_icon_for(self, condition_text: Optional[str], cloud_cover: float = 0.0) -> str:
        """Returns the most appropriate icon given current phase + weather.
        Critical: at night, never returns ☀️ even if condition='Clear'."""
        cond = (condition_text or '').strip()
        is_clear = ('مشمس' in cond) or ('Clear' in cond) or cloud_cover < 20
        is_partly_cloudy = ('غائم جزئي' in cond) or ('Partly' in cond) or 20 <= cloud_cover < 60
        is_overcast = ('غائم' in cond and 'جزئي' not in cond) or cloud_cover >= 80
        is_rainy = ('ممطر' in cond) or ('Rain' in cond) or ('rain' in cond)

        if self.phase in _NIGHT_PHASES:
            if is_rainy:        return '🌧️'
            if is_overcast:     return '☁️'
            if is_partly_cloudy:return '☁️🌙'
            return '🌙'                              # clear night → moon
        if self.phase == 'dawn':       return '🌅'
        if self.phase == 'sunset':     return '🌇'
        if self.phase == 'sunrise':    return '🌄'
        # Day-time phases — pick by weather
        if is_rainy:                   return '🌧️'
        if is_overcast:                return '☁️'
        if is_partly_cloudy:           return '⛅'
        if self.phase == 'noon':       return '☀️'
        return '🌤️'

    def weather_label_for(self, condition_text: Optional[str], cloud_cover: float = 0.0,
                          lang: str = 'ar') -> str:
        """Human-readable weather label that respects the phase.
        At night, "Clear" becomes 'ليل صافٍ' instead of 'مشمس'."""
        cond = (condition_text or '').strip()
        is_ar = lang == 'ar'

        if self.phase in _NIGHT_PHASES:
            if 'ممطر' in cond or 'Rain' in cond:
                return 'ليلة ممطرة' if is_ar else 'Rainy night'
            if 'غائم' in cond and 'جزئي' not in cond:
                return 'ليلة غائمة' if is_ar else 'Cloudy night'
            if cloud_cover >= 40:
                return 'ليلة غائمة جزئيًا' if is_ar else 'Partly cloudy night'
            return 'ليل صافٍ' if is_ar else 'Clear night'

        if self.phase == 'dawn':
            return 'فجر' if is_ar else 'Dawn'
        if self.phase == 'sunrise':
            return 'وقت الشروق' if is_ar else 'Sunrise'
        if self.phase == 'sunset':
            return 'وقت الغروب' if is_ar else 'Sunset'

        # Daytime → use the API's condition text directly
        return cond or ('غير متاح' if is_ar else 'Unavailable')

    # ── decision matrix ───────────────────────────────────────────────
    def decision_matrix(self, confidence_band: str, risk_level: str,
                        surplus_kwh: float, lang: str = 'ar') -> tuple[str, str]:
        """Single source of truth for "what should the user do right now?".

        Returns (status_label, decision_now) — both Arabic by default.

        Rules
        ─────
        * Night/dusk overrides everything: production decisions are off.
        * High risk + zero surplus + ≥medium confidence → "أوقف الأحمال"
        * Low confidence → "لا توصية قطعية" (we won't pretend we know)
        * Else → graded recommendation by risk band.
        """
        is_ar = lang == 'ar'

        # Night-time always: focus on battery survival
        if self.phase in _NIGHT_PHASES:
            return (
                ('فترة ليلية' if is_ar else 'Night period'),
                ('اعتمد على البطارية حتى الشروق وتجنّب الأحمال الكبيرة.'
                 if is_ar else 'Run on battery until sunrise; avoid heavy loads.'),
            )

        # Twilight (dawn or sunset): cautious posture
        if self.phase in _TWILIGHT_PHASES:
            return (
                ('وقت انتقالي' if is_ar else 'Transition window'),
                ('انتظر استقرار الإنتاج قبل تشغيل أحمال جديدة.'
                 if is_ar else 'Wait for production to stabilise before adding loads.'),
            )

        # Daytime — combine risk × confidence × surplus
        is_low_conf = confidence_band == 'low'
        is_high_risk = risk_level in {'high', 'مرتفع'}
        is_med_risk = risk_level in {'medium', 'متوسط'}
        has_surplus = surplus_kwh > 0.1

        if is_low_conf:
            return (
                ('بانتظار بناء الأرشيف' if is_ar else 'Awaiting archive'),
                ('بيانات قليلة بعد — اعتمد على القراءات الحالية بدل التوقع.'
                 if is_ar else 'Insufficient data — rely on live readings.'),
            )

        if is_high_risk and not has_surplus:
            return (
                ('أوقف الأحمال الإضافية' if is_ar else 'Stop extra loads'),
                ('الفائض المتوقع 0 والمخاطرة مرتفعة — لا تشغّل أحمالًا جديدة الآن.'
                 if is_ar else 'Expected surplus is zero — do not add new loads.'),
            )

        if is_high_risk and has_surplus:
            return (
                ('تشغيل صغير فقط' if is_ar else 'Small loads only'),
                ('شغّل أحمالًا خفيفة وقصيرة فقط.'
                 if is_ar else 'Run light and short loads only.'),
            )

        if is_med_risk:
            return (
                ('تشغيل محدود' if is_ar else 'Limited operation'),
                ('شغّل الأحمال المتوسطة، وراقب الفائض.'
                 if is_ar else 'Run medium loads and monitor surplus.'),
            )

        # Low/no risk + decent confidence
        return (
            ('وضع جيد للتشغيل' if is_ar else 'Good to operate'),
            ('يمكنك تشغيل الأحمال المعتادة بأمان.'
             if is_ar else 'You can run normal loads safely.'),
        )

    # ── advice for the weather card ───────────────────────────────────
    def weather_advice(self, lang: str = 'ar') -> tuple[str, str]:
        """Returns (advice_text, level) — advice that respects time of day.

        At 7 PM we should NOT say "best time to run appliances is between
        mid-morning and noon" — we should say "wait for tomorrow's sunrise"."""
        is_ar = lang == 'ar'

        if self.phase == 'night':
            return (
                (f'انتظر الشروق ({self.sunrise_text}). البطارية والشبكة تكفيان حتى ذلك الحين.'
                 if is_ar else
                 f'Wait for sunrise ({self.sunrise_text}). Battery + grid carry you till then.'),
                'info',
            )
        if self.phase == 'dusk':
            return (
                ('انتهى يوم الإنتاج. خفّف الأحمال الكبيرة الآن.'
                 if is_ar else 'Production day is over. Trim large loads now.'),
                'warning',
            )
        if self.phase == 'sunset':
            return (
                ('الشمس تغيب الآن. أوقف الأحمال غير الضرورية.'
                 if is_ar else 'Sun is setting now. Stop non-essential loads.'),
                'warning',
            )
        if self.phase == 'pre_sunset':
            return (
                ('تأكد من امتلاء البطارية قبل الغياب.'
                 if is_ar else 'Make sure the battery fills before the sun leaves.'),
                'warning',
            )
        if self.phase == 'dawn':
            return (
                (f'الشروق قريب ({self.sunrise_text}). الإنتاج سيبدأ بهدوء.'
                 if is_ar else f'Sunrise is near ({self.sunrise_text}). Production will start gently.'),
                'info',
            )
        if self.phase == 'sunrise':
            return (
                ('بدأ يوم جديد للإنتاج — وقت تشغيل الأحمال المتوسطة قريبًا.'
                 if is_ar else 'A new production day is starting — medium loads soon.'),
                'success',
            )
        if self.phase == 'morning':
            return (
                ('الإنتاج يتصاعد — مناسب للأحمال المتوسطة.'
                 if is_ar else 'Production is climbing — ideal for medium loads.'),
                'success',
            )
        if self.phase == 'noon':
            return (
                ('ذروة الإنتاج — وقت الذهب للأحمال الثقيلة.'
                 if is_ar else 'Production peak — golden hour for heavy loads.'),
                'success',
            )
        # afternoon
        return (
            ('الإنتاج يهدأ — ركّز على شحن البطارية ثم خفّف الأحمال تدريجيًا.'
             if is_ar else 'Output easing — focus on charging, then taper loads.'),
            'info',
        )

    # ── one-line message for the smart-prediction card ────────────────
    def smart_card_lead(self, lang: str = 'ar') -> str:
        """A single, non-conflicting opening sentence for the smart card.
        Replaces the old f-string that concatenated "sun is shining" with
        archive warnings."""
        is_ar = lang == 'ar'
        if self.phase == 'night':
            return ('🌙 فترة ليلية — البطارية والأرشيف يدعمانك حتى الشروق.'
                    if is_ar else '🌙 Night — battery + archive carry you till sunrise.')
        if self.phase == 'dusk':
            return ('🌃 الغسق — الإنتاج توقّف، الأرشيف يحدّد قرار الليل.'
                    if is_ar else '🌃 Dusk — production has stopped; archive guides the night.')
        if self.phase == 'sunset':
            return ('🌇 الشمس تغيب الآن — أنهِ الأحمال الكبيرة.'
                    if is_ar else '🌇 Sun is setting — wrap up heavy loads.')
        if self.phase == 'pre_sunset':
            return ('🌅 قبل الغروب — تأكد من امتلاء البطارية قبل الغياب.'
                    if is_ar else '🌅 Pre-sunset — finish charging before the sun leaves.')
        if self.phase == 'dawn':
            return ('🌌 الفجر — قريبًا تطلع الشمس وينبض الإنتاج.'
                    if is_ar else '🌌 Dawn — sunrise is near; production will pulse soon.')
        if self.phase == 'sunrise':
            return ('🌄 الشمس تطلع الآن — أول قطرات الإنتاج تظهر.'
                    if is_ar else '🌄 Sun is rising — the first drops of harvest.')
        if self.phase == 'noon':
            return ('☀️ ذروة النهار — الإنتاج في أعلاه.'
                    if is_ar else '☀️ Solar noon — production at its peak.')
        if self.phase == 'morning':
            return ('🌤️ الصباح — الإنتاج يتصاعد بثبات.'
                    if is_ar else '🌤️ Morning — production climbing steadily.')
        # afternoon
        return ('🌞 بعد الظهر — الإنتاج يهدأ تدريجيًا.'
                if is_ar else '🌞 Afternoon — output easing down.')


def compute_sun_context(
    latest=None,
    weather=None,
    settings=None,
    timezone_name: Optional[str] = None,
) -> SunContext:
    """Compute the unified sun context.  Safe to call with any combination
    of None inputs — falls back to sensible defaults (06:00 sunrise / 18:30
    sunset) when sunrise/sunset times are unavailable."""

    tz_name = timezone_name
    if tz_name is None and settings is not None:
        tz_name = settings.get('local_timezone') if isinstance(settings, dict) else None
    if tz_name is None:
        try:
            from flask import current_app
            tz_name = current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')
        except Exception:
            tz_name = 'Asia/Hebron'

    try:
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_local = datetime.now()

    sunrise_text = getattr(weather, 'sunrise_time', None) if weather else None
    sunset_text = getattr(weather, 'sunset_time', None) if weather else None
    has_weather_times = bool(sunrise_text and sunset_text)

    # Use the existing 9-phase classifier as the underlying truth.
    phase_info = classify_day_phase(now_local, sunrise_text, sunset_text)
    phase_key = phase_info['key']

    # Effective sunset (~1h before official) — production cutoff
    sunset_effective_text = sunset_text or '17:30'
    if sunset_text:
        try:
            hh, mm = sunset_text.split(':')
            eff = (int(hh) * 60 + int(mm)) - 60
            if eff < 0: eff += 24 * 60
            sunset_effective_text = f'{eff // 60:02d}:{eff % 60:02d}'
        except Exception:
            sunset_effective_text = sunset_text

    # Production-aware flags
    is_day_for_production = phase_key in _PRODUCTIVE_PHASES
    is_night = phase_key in _NIGHT_PHASES
    is_twilight = phase_key in _TWILIGHT_PHASES

    solar_power_w = 0.0
    try:
        solar_power_w = float(getattr(latest, 'solar_power', 0) or 0)
    except Exception:
        pass
    is_producing_meaningfully = is_day_for_production and solar_power_w > 100

    return SunContext(
        now_local=now_local,
        timezone_name=tz_name,
        sunrise_text=sunrise_text or phase_info.get('sunrise_text', '06:00'),
        sunset_text=sunset_text or phase_info.get('sunset_text', '18:30'),
        sunset_effective_text=sunset_effective_text,
        phase=phase_key,
        label_ar=phase_info['label_ar'],
        label_en=phase_info['label_en'],
        icon=phase_info['icon'],
        description_ar=phase_info['description_ar'],
        description_en=phase_info['description_en'],
        accent=phase_info['accent'],
        gradient=phase_info['gradient'],
        is_day_for_production=is_day_for_production,
        is_night=is_night,
        is_twilight=is_twilight,
        is_producing_meaningfully=is_producing_meaningfully,
        minutes_to_sunset=int(phase_info.get('mins_to_sunset', 0)),
        minutes_to_sunrise=int(phase_info.get('mins_to_sunrise', 0)),
        has_weather_times=has_weather_times,
    )


__all__ = ['SunContext', 'compute_sun_context']
```

### 2.4 `setBind` JavaScript helper (canonical implementation)

The live-update poller uses a `data-bind="key.subkey"` selector contract.
Every server-rendered value that the poller will refresh has a matching
`data-bind` attribute on its node.

```javascript
// --- Live poller (canonical pattern) -------------------------------------
var main    = document.querySelector('.your-page-class');
var liveUrl = main && main.dataset.liveUrl;
if (!liveUrl) return;

function setBind(key, value) {
  var nodes = document.querySelectorAll('[data-bind="' + key + '"]');
  nodes.forEach(function (node) {
    if (value === null || value === undefined) return;
    var current = node.textContent.trim();
    var fresh   = String(value);
    if (current !== fresh) {
      node.textContent = fresh;
      // brief glow to signal a change (optional — define `.your-flash` in CSS)
      node.classList.add('your-flash');
      setTimeout(function () { node.classList.remove('your-flash'); }, 700);
    }
  });
}

function fmtPower(w) {
  var v = Number(w || 0);
  if (Math.abs(v) >= 1000) return (v / 1000).toFixed(2) + ' kW';
  return v.toFixed(1) + ' W';
}

function applyPayload(p) {
  if (!p) return;

  /* ── Always read SunContext FIRST, raw weather as fallback ── */
  var w   = p.weather;
  var sph = p.sun_phase || {};
  if (w || sph) {
    var phaseIcon  = sph.weather_icon  || (w && w.icon)         || '';
    var phaseLabel = sph.weather_label || (w && w.condition_ar) || '';
    setBind('weather.icon', phaseIcon);
    setBind('weather.temp', (w && w.temperature !== null && w.temperature !== undefined ? w.temperature : '--') + '°');
    setBind('weather.cond', phaseLabel);
  }

  /* ── Other live fields (per-page) ── */
  var lt = p.latest;
  if (lt) {
    setBind('latest.solar_power', fmtPower(lt.solar_power));
    setBind('latest.home_load',   fmtPower(lt.home_load));
    setBind('latest.grid_power',  fmtPower(lt.grid_power));
    setBind('battery.soc_pct',   Math.round(lt.battery_soc || 0) + '%');
  }
}

function poll() {
  fetch(liveUrl, {
    credentials: 'same-origin',
    headers: { 'Accept': 'application/json' }
  })
  .then(function (r) { return r.json(); })
  .then(applyPayload)
  .catch(function () { /* silent — try again next tick */ });
}

poll();
setInterval(poll, 30000);              // every 30 s
document.addEventListener('visibilitychange', function () {
  if (!document.hidden) poll();        // refresh immediately on tab focus
});
```

The complementary CSS animation:

```css
.your-flash {
  animation: yourFlash .7s ease;
}
@keyframes yourFlash {
  0%   { background-color: rgba(245,158,11,.18); }
  100% { background-color: transparent; }
}
```

### 2.5 `/api/live` server contract (the JSON the poller expects)

The route must return at minimum:

```json
{
  "ok": true,
  "day_phase": { "key": "morning", "label_ar": "...", "icon": "🌤️", ... },
  "sun_phase": {
    "phase":          "morning",
    "icon":           "🌤️",
    "label_ar":       "صباحًا",
    "label_en":       "Morning",
    "is_day_for_production": true,
    "is_night":       false,
    "weather_icon":   "🌤️",
    "weather_label":  "مشمس",
    "weather_advice": "الإنتاج يتصاعد — مناسب للأحمال المتوسطة.",
    "weather_advice_level": "success"
  },
  "latest":  { "solar_power": ..., "home_load": ..., "battery_soc": ... },
  "weather": { "icon": ..., "condition_ar": ..., "temperature": ..., ... },
  "battery": { ... },
  "system_status": { "title": "...", "tone": "ok|warning|danger" }
}
```

The Flask route that produces this response is the canonical pattern below
(simplified from `app/blueprints/energy.py:api_live`):

```python
@bp.route('/api/live')
def api_live():
    latest   = _latest_reading()
    weather  = get_weather_for_latest(latest)
    settings = load_settings()

    if not latest:
        return {'ok': False, 'empty': True}

    from ..services.sun_context import compute_sun_context
    ctx = compute_sun_context(latest=latest, weather=weather, settings=settings)
    cond  = getattr(weather, 'condition_ar', None) if weather else None
    cloud = float(getattr(weather, 'cloud_cover', 0) or 0) if weather else 0
    lang  = _lang()

    wx_icon         = ctx.weather_icon_for(cond, cloud)
    wx_label        = ctx.weather_label_for(cond, cloud, lang=lang)
    wx_adv, wx_lvl  = ctx.weather_advice(lang=lang)

    return {
        'ok': True,
        'sun_phase': {
            'phase':                 ctx.phase,
            'icon':                  ctx.icon,
            'label_ar':              ctx.label_ar,
            'label_en':              ctx.label_en,
            'is_day_for_production': ctx.is_day_for_production,
            'is_night':              ctx.is_night,
            'weather_icon':          wx_icon,
            'weather_label':         wx_label,
            'weather_advice':        wx_adv,
            'weather_advice_level':  wx_lvl,
        },
        'latest':  { ... },        # whichever fields the page needs
        'weather': { ... },        # raw weather payload
    }
```

---

## 3. The 9-step walkthrough — build a new page from scratch

> Follow these steps in order. Don't skip ahead.

### Step 1 — Pick a unique 2-3 letter prefix

Look at existing prefixes (so you don't collide):

| Prefix | Page |
|---|---|
| `d40-` | dashboard |
| `st-`  | statistics |
| `rp-`  | reports |
| `lv-`  | live-data |
| `dm-`  | devices manage |

Choose something like `nt-`, `pf-`, `ad-`. The prefix appears on every class
and CSS variable in your file.

### Step 2 — Create `app/templates/<your_page>.html` with the page shell

```jinja2
{% extends 'base.html' %}
{% block body %}
{% set is_en = (ui_lang or 'ar') == 'en' %}
<style>
.pp-page{
  --pp-ink:#0b1220; --pp-ink-soft:#1f2a44; --pp-muted:#5e6f8c;
  --pp-line:#e3eaf6; --pp-line-strong:#cfd9ec;
  --pp-card:#fff; --pp-bg:#eef3fb;
  --pp-amber:#f59e0b; --pp-emerald:#10b981; --pp-sky:#2563eb;
  --pp-rose:#f43f5e; --pp-violet:#6d3aff; --pp-orange:#f97316;
  --pp-shadow-sm:0 6px 18px rgba(15,23,42,.06);
  --pp-shadow:   0 22px 60px rgba(15,23,42,.09);
  --pp-radius:22px; --pp-radius-lg:30px; --pp-radius-xl:38px;
  background:
    radial-gradient(1100px 480px at 12% -10%,rgba(109,58,255,.10),transparent 55%),
    radial-gradient( 900px 420px at 92%  -4%,rgba(245,158,11,.10),transparent 55%),
    linear-gradient(180deg,#f5f8ff 0%,#eef3fb 60%,#e8eef9 100%);
  min-height:100vh;padding:18px clamp(14px,2.4vw,32px) 80px;
  font-family:'Cairo','Inter',system-ui,sans-serif;color:var(--pp-ink);
  display:flex;flex-direction:column;gap:24px;
}
.pp-page *,.pp-page *::before,.pp-page *::after{box-sizing:border-box}
</style>

<div class="app-shell has-layout-sidebar sidebar-collapsed" id="appShell">
  {% include '_sidebar.html' %}
  <main class="app-main content-area">
    <div class="pp-page" dir="{{ 'ltr' if is_en else 'rtl' }}">
      <!-- (1) hero  -->
      <!-- (2) KPI strip -->
      <!-- (3) section header -->
      <!-- (4) main content cards -->
    </div>
  </main>
</div>
{% endblock %}
```

### Step 3 — Add the hero section (copy from §3 of the design system)

Always: eyebrow → h1 → p → meta → actions. Don't reorder.

### Step 4 — Add the KPI strip (4 cards)

Pick one accent color per card. Don't use the same color twice in a row.

### Step 5 — Add section content (cards, tables, lists)

Use `pp-card` + `pp-card-head` + body. Always one `<h3>` with leading emoji.

### Step 6 — Wire the Flask route

```python
@bp.route('/your-route')
def your_view():
    latest   = _latest_reading()
    weather  = get_weather_for_latest(latest)
    settings = load_settings()

    # MANDATORY if the page is time-aware:
    from ..services.sun_context import compute_sun_context
    sun_ctx = compute_sun_context(latest=latest, weather=weather, settings=settings)
    weather_now_icon  = sun_ctx.weather_icon_for(...)
    weather_now_label = sun_ctx.weather_label_for(..., lang=_lang())
    weather_advice_text, weather_advice_level = sun_ctx.weather_advice(lang=_lang())

    return render_template(
        'your_page.html',
        ui_lang=_lang(),
        sun_ctx=sun_ctx,
        weather_now_icon=weather_now_icon,
        weather_now_label=weather_now_label,
        weather_advice_text=weather_advice_text,
        # ... your page-specific data
    )
```

### Step 7 — Wire the live poller (only if data changes in real time)

Add this attribute to your `<main>`:
```html
<main class="app-main content-area pp-live" data-live-url="{{ url_for('bp.api_live', lang=ui_lang) }}">
```

Add the JS block from §2.4 above, replacing `your-page-class` with `pp-live`.

### Step 8 — Add the live-update payload to `/api/live`

Make sure the route already used by your page's poller returns `sun_phase`
plus whichever extra `latest` / `weather` / page-specific fields you need.

### Step 9 — Validate with Jinja parser

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('app/templates'))
src = open('app/templates/your_page.html', encoding='utf-8').read()
env.parse(src)
print('OK')
"
```

If it fails, fix before moving on. Don't push a broken template.

---

## 4. Validation checklist (definition of done)

A new page is "done" when **every** box below is ticked:

### Visual / Layout
- [ ] Hero is sky-blue → amber gradient at the top, full width
- [ ] Eyebrow chip has the pulsing amber dot animation
- [ ] Hero h1 uses `font-weight: 950` and the white text-shadow
- [ ] At least one primary action button uses the amber gradient
- [ ] KPI strip has 4-6 cards, each with a 5 px colored top strip
- [ ] Cards lift `-3 px` on hover, shadow gets darker
- [ ] Page background shows the violet + amber halos (not flat white)
- [ ] Inter-section gap is exactly 24 px
- [ ] No dark navy panels anywhere

### Typography & Numbers
- [ ] All number values use `font-variant-numeric: tabular-nums`
- [ ] Stat values: 1.85-2 rem, weight 950
- [ ] Labels: 0.7-0.78 rem, weight 800-900, uppercase + letter-spacing
- [ ] Body text: 0.88-0.95 rem, weight 600-700
- [ ] Font family is Cairo + Inter + system-ui

### Color Discipline
- [ ] Solar = amber `#f59e0b` family
- [ ] Home = rose `#f43f5e` family
- [ ] Battery = emerald `#10b981` family
- [ ] SOC / period = sky `#2563eb` family
- [ ] Stat values use the dark text variant (#b45309, #047857, etc.)
- [ ] No accent color used twice in the same row

### Intelligence (if page is time-aware)
- [ ] Route imports and computes `compute_sun_context(...)`
- [ ] Template uses `weather_now_icon`/`weather_now_label`/`weather_advice_text`
- [ ] Never gates on `solar_power > 50` to detect day vs night
- [ ] At sunset / dusk / night, icons are 🌇 / 🌃 / 🌙 — never ☀️
- [ ] Weather advice is appropriate to the time of day
- [ ] No "best time to run appliances is morning" message at 7 PM

### Live Updates (if applicable)
- [ ] `<main>` has a `data-live-url` attribute
- [ ] JS poller reads `p.sun_phase` first, falls back to raw `weather`
- [ ] Poller polls every 30 s and re-polls on `visibilitychange`
- [ ] Server-side first-paint is correct (page is usable without JS)

### RTL & Forms
- [ ] Page works in `dir="rtl"` (default for Arabic)
- [ ] Uses `inset-inline-start/end` not `left/right`
- [ ] Forms use `border-radius: 11 px`, amber focus ring
- [ ] Custom toggle switches replace native checkboxes for is_active flags
- [ ] Drawers slide from the correct side per direction

### Code Hygiene
- [ ] Unique class prefix on every class and CSS variable
- [ ] CSS variables scoped to `.pp-page`, not global
- [ ] `<style>` block lives at the top of `{% block body %}`
- [ ] All Jinja `url_for` calls use the right blueprint name
- [ ] All `csrf_token()` calls are inside `<form>` tags
- [ ] Template parses cleanly with Jinja2 (no `endblock` errors)

### Defense
- [ ] No `margin-top` between top-level sections (use page flex gap)
- [ ] Numbers wrap units in a separate `<span class="pp-unit">` (small + muted)
- [ ] Empty state uses dashed border + icon box pattern
- [ ] Status pills have a leading dot + pastel background

---

## 5. Things AIs commonly get wrong (and how to detect them)

| Symptom | Likely cause | Fix |
|---|---|---|
| Page feels cramped | Used `margin` instead of `gap` | Set `gap: 24px` on `.pp-page` |
| Buttons look bootstrap-ish | Inherited Bootstrap `.btn` | Add `pp-export-btn` class with our padding/radius |
| Cards look flat | Missing `border` or `box-shadow` | `border: 1px solid var(--pp-line)` + `var(--pp-shadow-sm)` |
| KPI values are small | Forgot `font-weight: 950` | Bump to 950 + 1.85 rem |
| At night still shows ☀️ | Reading raw `weather.icon` instead of `sun_phase.weather_icon` | Wire the SunContext payload as in §2.4 |
| "بحذر" appears twice | Status label includes confidence message | Strip it before render (see `smart_engine.py` reference) |
| Text overlaps in chart | Bar labels too dense | Use the adaptive `step = ceil(n / max_labels)` from `statistics.html` |
| Drawer feels huge | Width > 540 px | Cap with `width: min(540px, 96vw)` |
| Weather chip stuck on "مشمس" at night | Live poller overwriting server-rendered value | Read `p.sun_phase` first in `applyPayload` |

---

## 6. The "smell test" — five-second visual inspection

When the AI delivers, eyeball the result for these signals:

1. **First 5 seconds** — Does it feel airy or cramped? If cramped, the AI used wrong gaps/paddings.
2. **First 10 seconds** — Are the numbers big and readable? If small, weight/size are wrong.
3. **First 15 seconds** — Is there color discipline? If every card is a different rainbow, the AI ignored §1's accent rules.
4. **First 30 seconds** — Try resizing to mobile (< 600 px). If layouts collapse weirdly, the AI didn't add the breakpoints.
5. **First minute** — At sunset, do the icons say "night"? If they still say ☀️, the AI didn't wire SunContext.

If any of those fail, regenerate with the failing point highlighted.

---

## 7. Final pep-talk for the AI

- **Trust the system.** Don't get clever. Use the exact spacings, exact colors, exact radii. The system was calibrated by a human who tested every value at every screen size.
- **Phase before reading.** Decide what time it is *first*, then fill in the numbers. A 250 W reading is a fact; whether it's good or bad depends on the phase.
- **One source of truth.** If you compute the same fact (icon, label, advice) in two places, you've already failed. Compute once in `sun_context`, consume everywhere.
- **Server-first, JS second.** The page must be usable without JavaScript. JS only refreshes existing bindings; it never creates new structure.
- **Numbers are sacred.** Every numeric value is `tabular-nums`, weight ≥ 700, and aligned to a column in tables.
- **Air over density.** When in doubt, add more space, not less. Bump `gap: 18` → `24`, padding `16` → `20`.

If you do all this, the page will feel like the rest of SolarDeye. If you cut corners, it will feel foreign. There's no middle ground.


---

## 8. The unified-theme override file (v82, May 2026)

After Wave 1 (auth pages) and Wave 2 (subscriber pages) shipped with their own scoped CSS files, we still had ~24 admin templates running on legacy classes from `style.css`. Touching every admin template by hand was scope-explosion territory. So we built one global override file.

### Architecture

```
base.html  →  loads in this exact order:
   1. style.css                (legacy, v78-account-profile-playbook-20260502)
   2. sidebar_rebuild_v11.css  (sidebar-only, v78-...)
   3. unified_theme_v1.css     (LAST, wins via cascade — v82-admin-wave3b-20260503)
   4. {% block extra_head %}   (per-page scoped CSS files)
```

`unified_theme_v1.css` repaints every legacy admin class — `.admin-card-v2`, `.admin-kpi-card`, `.admin-table-v2`, `.user360-*`, `.status-pill`, `.quick-links-v2`, `.activity-list-v2`, etc. — with the unified light theme using `!important` so heavy-v* body modifiers can't override it.

Pages with their own scoped sheet (`landing_settings_v110.css`, `platform_review.css`, `services_health.css`, `notifications_center.css`) load AFTER the override, so their custom hero designs win locally without leaking into the rest of admin.

### Why one file beats per-template overrides

| Per-template override | Single override file |
|---|---|
| 24 templates to edit | 1 CSS file to edit |
| Risk of typos × 24 | Risk × 1 |
| Cache busting per file | Cache busting once |
| Hard to enforce consistency | Tokenized, tested, documented |
| Harder to A/B alternate themes | Just swap or feature-flag the file |

### What lives in `unified_theme_v1.css`

```
:root            → CSS tokens (--u-ink, --u-amber, --u-shadow-sm, etc.)
body.theme-saas  → page background gradient
.app-main        → content padding/color
.topbar / header.admin-page-head
                 → sky→amber gradient hero with eyebrow + h1
.stat-card / .panel-card / .live-hero-card
                 → subscriber legacy classes (loads, channels, etc.)
.admin-shell-v2  → admin shell padding/gap
.admin-page-head → admin hero with action pills
.admin-kpi-card  → 220px-min auto-fit grid + amber top stripe
.admin-card-v2   → white card, 24px radius, dashed inline heading divider
.admin-table-v2  → gradient thead, hover rows, sub-text style
.user360-hero    → user-profile KPI grid (5 cards, 180px min)
.user360-tab     → pill tabs, amber gradient when .active
.status-pill     → success/warning/danger pills, brand-aligned
.quick-links-v2  → linked-list cards with hover lift
.activity-list-v2/.activity-item-v2
                 → vertical activity feed
.empty-box-v2    → dashed border empty state
prefers-reduced-motion @media block
:focus-visible   → amber rings on all interactives
@media print     → simplified greyscale print stylesheet
body[data-theme="dark"] → dormant; ready for dark-mode toggle
```

### How to add a new admin page (3 steps, 5 minutes)

1. **Use the standard skeleton** — copy from any current admin template:
   ```html
   {% extends 'base.html' %}
   {% block body %}
   {% set is_en = (ui_lang or 'ar') == 'en' %}
   <div class="app-shell has-layout-sidebar sidebar-collapsed">
     {% include '_sidebar.html' %}
     <main class="app-main content-area admin-shell-v2">
       <header class="admin-page-head">
         <div>
           <span class="eyebrow">{{ '...' }}</span>
           <h1>{{ '...' }}</h1>
           <p>{{ '...' }}</p>
         </div>
         <div class="admin-head-actions">...</div>
       </header>
       <!-- content -->
     </main>
   </div>
   {% endblock %}
   ```
2. **Use existing classes only** — `.admin-kpi-grid-v2 + .admin-kpi-card`, `.admin-layout-v2 + .admin-card-v2`, `.admin-table-v2`, `.status-pill`, `.user360-hero/-kpi/-tab` etc.
3. **No need to write any CSS.** If your page truly needs a custom hero (like `landing_settings`), add a scoped CSS file in `{% block extra_head %}` — it'll naturally win over the override.

### Verification: the Design QA page

A regression-detection canvas lives at `/admin/design-qa`. It renders every reusable component side-by-side. After ANY change to `unified_theme_v1.css`, open this page and visually scan — anything that looks wrong is a regression. Save it to your bookmarks bar.

### Cache busting protocol

Every change to `unified_theme_v1.css` MUST bump the `v=...` parameter in `base.html` — otherwise users (and you) see stale cached CSS. Format: `v<N>-<short-description>-<YYYYMMDD>`. Latest: `v82-admin-wave3b-20260503`.

### Anti-patterns to avoid

❌ Don't write `<style>` blocks inside admin templates. Add to `unified_theme_v1.css` instead so all admin pages get it.
❌ Don't use inline `style="..."` for color, background, or border on .admin-* elements. The override won't be able to win.
❌ Don't use absolute pixel values that contradict tokens (use `var(--u-ink)`, `var(--u-amber)`, etc.).
❌ Don't import `style.css` admin classes directly in new code — they're flagged for removal as we expand the override.
