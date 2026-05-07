from __future__ import annotations
from flask import Blueprint, jsonify, render_template, url_for, request

openapi_api_bp = Blueprint('openapi_api', __name__, url_prefix='/api/v1')

# ── Arabic translations for summaries & tags ─────────────────────────
_AR = {
    # Tags
    'Auth':          'المصادقة',
    'Mobile':        'الجوّال',
    'Devices':       'الأجهزة',
    'Support':       'الدعم',
    'Notifications': 'الإشعارات',
    # Summaries
    'Mobile login — obtain access + refresh tokens':
        'تسجيل الدخول عبر الجوّال — الحصول على رمز الوصول ورمز التجديد',
    'Refresh access token using refresh_token (30-day TTL)':
        'تجديد رمز الوصول باستخدام رمز التجديد refresh_token (صالح لمدة 30 يوماً)',
    'Revoke refresh token (immediate invalidation)':
        'إلغاء رمز التجديد فوراً',
    'Current authenticated user profile':
        'بيانات المستخدم الحالي المسجّل دخوله',
    'App bootstrap: navigation, permissions, provider catalog':
        'بيانات التهيئة الأولية للتطبيق: التنقّل، والصلاحيات، وقائمة المزوّدين',
    'Dashboard summary — latest reading for current device':
        'ملخّص لوحة التحكم — آخر قراءة للجهاز الحالي',
    'Recent notifications for current user (last 30)':
        'آخر 30 إشعاراً للمستخدم الحالي',
    'API health check — no auth required':
        'فحص صحة واجهة برمجة التطبيقات — لا يحتاج إلى مصادقة',
    'List devices visible to current user':
        'قائمة الأجهزة المتاحة للمستخدم الحالي',
    'Device details':
        'تفاصيل الجهاز',
    'Latest reading for device':
        'آخر قراءة للجهاز',
    'Paginated reading history':
        'سجل القراءات (مع ترقيم الصفحات)',
    'Derived alerts for device':
        'التنبيهات المستنتجة للجهاز',
    'List support cases for current user':
        'قائمة تذاكر الدعم للمستخدم الحالي',
    'Create new support case':
        'إنشاء تذكرة دعم جديدة',
    'Support case detail with messages':
        'تفاصيل تذكرة الدعم مع الرسائل',
    'Reply to a support case':
        'الرد على تذكرة دعم',
    'Reopen a closed support case':
        'إعادة فتح تذكرة دعم مغلقة',
    'List canned reply templates':
        'قائمة قوالب الردود الجاهزة',
    'List notifications (paginated)':
        'قائمة الإشعارات (مع ترقيم الصفحات)',
    'Mark notifications as read':
        'تمييز الإشعارات كمقروءة',
    'Register device push token':
        'تسجيل رمز إشعارات الدفع للجهاز',
    'Unregister device push token':
        'إلغاء تسجيل رمز إشعارات الدفع للجهاز',
    'Unregister push token (POST alias)':
        'إلغاء تسجيل رمز إشعارات الدفع (مسار بديل عبر POST)',
}

def _tr(text: str, is_ar: bool) -> str:
    """Return Arabic translation if available and lang=ar."""
    return _AR.get(text, text) if is_ar else text


def _spec():
    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'SolarDeye Mobile API',
            'version': '10.1.0',
            'description': (
                'Mobile-first REST API for authentication, devices, support, notifications and app bootstrap. '
                'All authenticated endpoints require a signed Bearer token obtained via POST /api/v1/auth/login. '
                'Tokens are HMAC-signed (not standard JWT); expiry is 15 min by default. '
                'Use POST /api/v1/auth/refresh with a valid refresh_token (30-day TTL) to renew. '
                'Every response includes X-RateLimit-Limit and X-RateLimit-Window advisory headers.'
            ),
        },
        'servers': [{'url': '/'}],
        'components': {
            'securitySchemes': {
                'bearerAuth': {
                    'type': 'http',
                    'scheme': 'bearer',
                    'bearerFormat': 'signed-token',
                    'description': (
                        'HMAC-signed access token. '
                        'Obtain via POST /api/v1/auth/login. '
                        'Expires in 15 min. '
                        'Renew via POST /api/v1/auth/refresh.'
                    ),
                },
            },
            'schemas': {
                'ApiOk': {
                    'type': 'object',
                    'required': ['ok', 'data', 'meta', 'errors'],
                    'properties': {
                        'ok':      {'type': 'boolean', 'example': True},
                        'data':    {'type': 'object',  'description': 'Response payload'},
                        'meta':    {'type': 'object',  'description': 'Pagination or context metadata'},
                        'errors':  {'type': 'array',   'items': {'type': 'string'}},
                        'message': {'type': 'string',  'description': 'Optional human-readable message'},
                    },
                },
                'ApiError': {
                    'type': 'object',
                    'required': ['ok', 'message', 'code', 'errors'],
                    'properties': {
                        'ok':      {'type': 'boolean', 'example': False},
                        'message': {'type': 'string'},
                        'code':    {'type': 'string',  'description': 'Machine-readable error code'},
                        'errors':  {'type': 'array',   'items': {'type': 'string'}},
                    },
                },
            },
        },
        'paths': {
            # ── Auth ────────────────────────────────────────────────────────
            '/api/v1/auth/login': {'post': {
                'summary': 'Mobile login — obtain access + refresh tokens',
                'tags': ['Auth'],
                'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                    'type': 'object',
                    'properties': {
                        'username':     {'type': 'string', 'example': 'user@example.com'},
                        'password':     {'type': 'string'},
                        'device_label': {'type': 'string', 'example': 'iPhone 15 Pro'},
                    },
                }}}},
                'responses': {
                    '200': {'description': 'access_token + refresh_token issued'},
                    '401': {'description': 'Invalid credentials'},
                },
            }},
            '/api/v1/auth/refresh': {'post': {
                'summary': 'Refresh access token using refresh_token (30-day TTL)',
                'tags': ['Auth'],
                'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                    'type': 'object',
                    'properties': {'refresh_token': {'type': 'string'}},
                }}}},
                'responses': {
                    '200': {'description': 'New access_token issued'},
                    '401': {'description': 'Refresh token invalid or expired'},
                },
            }},
            '/api/v1/auth/logout': {'post': {
                'summary': 'Revoke refresh token (immediate invalidation)',
                'tags': ['Auth'],
                'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                    'type': 'object',
                    'properties': {'refresh_token': {'type': 'string'}},
                }}}},
                'responses': {'200': {'description': 'Token revoked'}},
            }},
            '/api/v1/auth/me': {'get': {
                'summary': 'Current authenticated user profile',
                'tags': ['Auth'],
                'security': [{'bearerAuth': []}],
                'responses': {
                    '200': {'description': 'User profile object'},
                    '401': {'description': 'Auth required'},
                },
            }},
            # ── Mobile ──────────────────────────────────────────────────────
            '/api/v1/mobile/bootstrap': {'get': {
                'summary': 'App bootstrap: navigation, permissions, provider catalog',
                'tags': ['Mobile'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Bootstrap payload'}},
            }},
            '/api/v1/mobile/summary': {'get': {
                'summary': 'Dashboard summary — latest reading for current device',
                'tags': ['Mobile'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Summary payload'}},
            }},
            '/api/v1/mobile/notifications': {'get': {
                'summary': 'Recent notifications for current user (last 30)',
                'tags': ['Mobile'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Notification list'}},
            }},
            '/api/v1/mobile/health': {'get': {
                'summary': 'API health check — no auth required',
                'tags': ['Mobile'],
                'responses': {'200': {'description': 'API is healthy'}},
            }},
            # ── Devices ─────────────────────────────────────────────────────
            '/api/v1/devices': {'get': {
                'summary': 'List devices visible to current user',
                'tags': ['Devices'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Device list'}},
            }},
            '/api/v1/devices/{device_id}': {'get': {
                'summary': 'Device details',
                'tags': ['Devices'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Device object'}},
            }},
            '/api/v1/devices/{device_id}/latest': {'get': {
                'summary': 'Latest reading for device',
                'tags': ['Devices'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Latest reading'}},
            }},
            '/api/v1/devices/{device_id}/history': {'get': {
                'summary': 'Paginated reading history',
                'tags': ['Devices'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Reading history (paginated)'}},
            }},
            '/api/v1/devices/{device_id}/alerts': {'get': {
                'summary': 'Derived alerts for device',
                'tags': ['Devices'],
                'security': [{'bearerAuth': []}],
                'responses': {'200': {'description': 'Alert list'}},
            }},
            # ── Support ─────────────────────────────────────────────────────
            '/api/v1/support/cases': {
                'get':  {'summary': 'List support cases for current user',  'tags': ['Support'], 'security': [{'bearerAuth': []}]},
                'post': {'summary': 'Create new support case',              'tags': ['Support'], 'security': [{'bearerAuth': []}]},
            },
            '/api/v1/support/cases/{kind}/{case_id}': {'get': {
                'summary': 'Support case detail with messages',
                'tags': ['Support'],
                'security': [{'bearerAuth': []}],
            }},
            '/api/v1/support/cases/{kind}/{case_id}/reply': {'post': {
                'summary': 'Reply to a support case',
                'tags': ['Support'],
                'security': [{'bearerAuth': []}],
            }},
            '/api/v1/support/cases/{kind}/{case_id}/reopen': {'post': {
                'summary': 'Reopen a closed support case',
                'tags': ['Support'],
                'security': [{'bearerAuth': []}],
            }},
            '/api/v1/support/canned-replies': {'get': {
                'summary': 'List canned reply templates',
                'tags': ['Support'],
                'security': [{'bearerAuth': []}],
            }},
            # ── Notifications ────────────────────────────────────────────────
            '/api/v1/notifications': {'get': {
                'summary': 'List notifications (paginated)',
                'tags': ['Notifications'],
                'security': [{'bearerAuth': []}],
            }},
            '/api/v1/notifications/mark-read': {'post': {
                'summary': 'Mark notifications as read',
                'tags': ['Notifications'],
                'security': [{'bearerAuth': []}],
            }},
            '/api/v1/notifications/push-tokens': {
                'post':   {'summary': 'Register device push token',   'tags': ['Notifications'], 'security': [{'bearerAuth': []}]},
                'delete': {'summary': 'Unregister device push token', 'tags': ['Notifications'], 'security': [{'bearerAuth': []}]},
            },
            '/api/v1/notifications/push-tokens/unregister': {'post': {
                'summary': 'Unregister push token (POST alias)',
                'tags': ['Notifications'],
                'security': [{'bearerAuth': []}],
            }},
        },
    }


@openapi_api_bp.get('/openapi.json')
def openapi_json():
    return jsonify(_spec())


@openapi_api_bp.get('/docs')
def api_docs():
    spec  = _spec()
    lang  = (request.args.get('lang') or 'ar').strip().lower()
    is_ar = lang == 'ar'

    by_tag: dict = {}
    for path, ops in spec.get('paths', {}).items():
        for method, op in (ops or {}).items():
            tag = (op.get('tags') or ['General'])[0]
            by_tag.setdefault(tag, []).append({
                'method':       method.upper(),
                'path':         path,
                'summary':      _tr(op.get('summary', ''), is_ar),
                'auth_required': bool(op.get('security')),
            })

    # Translate tag labels for the UI
    tag_labels = {tag: (_AR.get(tag, tag) if is_ar else tag) for tag in by_tag}

    return render_template(
        'api_docs.html',
        spec=spec,
        spec_url=url_for('openapi_api.openapi_json'),
        ui_lang=lang,
        by_tag=by_tag,
        tag_labels=tag_labels,
    )
