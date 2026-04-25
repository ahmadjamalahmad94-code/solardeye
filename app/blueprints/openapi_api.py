from __future__ import annotations

from flask import Blueprint, jsonify, render_template_string, url_for

openapi_api_bp = Blueprint('openapi_api', __name__, url_prefix='/api/v1')


def _spec():
    return {
        'openapi': '3.0.3',
        'info': {'title': 'SolarDeye Mobile API', 'version': '10.1.0', 'description': 'Mobile-first API for authentication, devices, support, notifications and app bootstrap.'},
        'servers': [{'url': '/'}],
        'components': {
            'securitySchemes': {'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'signed-token'}},
            'schemas': {
                'ApiOk': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}, 'data': {'type': 'object'}, 'meta': {'type': 'object'}, 'errors': {'type': 'array'}}},
                'ApiError': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}, 'message': {'type': 'string'}, 'code': {'type': 'string'}, 'errors': {'type': 'array'}}},
            },
        },
        'paths': {
            '/api/v1/auth/login': {'post': {'summary': 'Mobile login', 'tags': ['Auth']}},
            '/api/v1/auth/refresh': {'post': {'summary': 'Refresh access token', 'tags': ['Auth']}},
            '/api/v1/auth/logout': {'post': {'summary': 'Revoke refresh token', 'tags': ['Auth']}},
            '/api/v1/auth/me': {'get': {'summary': 'Current user', 'tags': ['Auth'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/mobile/bootstrap': {'get': {'summary': 'App bootstrap and navigation', 'tags': ['Mobile'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/mobile/summary': {'get': {'summary': 'Dashboard summary', 'tags': ['Mobile'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/devices': {'get': {'summary': 'List devices', 'tags': ['Devices'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/devices/{device_id}': {'get': {'summary': 'Device details', 'tags': ['Devices'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/devices/{device_id}/latest': {'get': {'summary': 'Latest device reading', 'tags': ['Devices'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/devices/{device_id}/history': {'get': {'summary': 'Paginated device history', 'tags': ['Devices'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/devices/{device_id}/alerts': {'get': {'summary': 'Derived device alerts', 'tags': ['Devices'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/support/cases': {'get': {'summary': 'List support cases', 'tags': ['Support'], 'security': [{'bearerAuth': []}]}, 'post': {'summary': 'Create support case', 'tags': ['Support'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/support/cases/{kind}/{case_id}': {'get': {'summary': 'Support case detail', 'tags': ['Support'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/support/cases/{kind}/{case_id}/reply': {'post': {'summary': 'Reply to support case', 'tags': ['Support'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/support/cases/{kind}/{case_id}/reopen': {'post': {'summary': 'Reopen support case', 'tags': ['Support'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/notifications': {'get': {'summary': 'List notifications', 'tags': ['Notifications'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/notifications/mark-read': {'post': {'summary': 'Mark notifications read', 'tags': ['Notifications'], 'security': [{'bearerAuth': []}]}},
            '/api/v1/notifications/push-tokens': {'post': {'summary': 'Register push token', 'tags': ['Notifications'], 'security': [{'bearerAuth': []}]}, 'delete': {'summary': 'Unregister push token', 'tags': ['Notifications'], 'security': [{'bearerAuth': []}]}},
        },
    }


@openapi_api_bp.get('/openapi.json')
def openapi_json():
    return jsonify(_spec())


@openapi_api_bp.get('/docs')
def api_docs():
    spec_url = url_for('openapi_api.openapi_json')
    return render_template_string('''
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SolarDeye API Docs</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f8fbff;color:#0f172a}.wrap{max-width:1120px;margin:0 auto;padding:32px}.card{background:#fff;border:1px solid #dbe4f0;border-radius:24px;padding:24px;box-shadow:0 18px 60px rgba(15,23,42,.08)}code{background:#eef3ff;border-radius:8px;padding:3px 7px}.grid{display:grid;gap:12px;margin-top:20px}.row{display:flex;justify-content:space-between;gap:16px;border:1px solid #e2e8f0;border-radius:16px;padding:14px 16px;background:#fff}.tag{font-weight:800;color:#2563eb}</style></head>
<body><main class="wrap"><section class="card"><h1>SolarDeye Mobile API</h1><p>OpenAPI JSON: <a href="{{ spec_url }}"><code>{{ spec_url }}</code></a></p><p>Use <code>POST /api/v1/auth/login</code>, then pass <code>Authorization: Bearer ACCESS_TOKEN</code>.</p><div class="grid">{% for path, ops in spec.paths.items() %}<div class="row"><strong>{{ path }}</strong><span class="tag">{{ ops.keys()|list|join(', ')|upper }}</span></div>{% endfor %}</div></section></main></body></html>
''', spec=_spec(), spec_url=spec_url)
