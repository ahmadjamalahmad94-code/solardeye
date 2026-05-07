from __future__ import annotations

from math import ceil
from typing import Any

from flask import jsonify, make_response, request

# ---------------------------------------------------------------------------
# Rate-limit budget constants (enforced application-side as advisory headers).
# A real token-bucket / sliding-window limiter (e.g. Flask-Limiter) should
# wrap these values; for now we emit the headers so clients can adapt.
# ---------------------------------------------------------------------------
_RL_LIMIT_DEFAULT = 300        # requests per window
_RL_WINDOW_SECONDS = 300       # 5-minute rolling window


def _rl_headers() -> dict[str, str]:
    """Return advisory rate-limit headers for every API response."""
    return {
        'X-RateLimit-Limit': str(_RL_LIMIT_DEFAULT),
        'X-RateLimit-Window': str(_RL_WINDOW_SECONDS),
        'X-Content-Type-Options': 'nosniff',
    }


def api_ok(data: Any = None, *, meta: dict | None = None, message: str | None = None, status: int = 200, **extra):
    payload = {'ok': True, 'data': data if data is not None else {}, 'meta': meta or {}, 'errors': []}
    if message:
        payload['message'] = message
    payload.update(extra)
    resp = make_response(jsonify(payload), status)
    for k, v in _rl_headers().items():
        resp.headers[k] = v
    return resp


def api_error(message: str, *, code: str = 'error', status: int = 400, errors: list | None = None, **extra):
    payload = {'ok': False, 'message': message, 'code': code, 'errors': errors or []}
    payload.update(extra)
    resp = make_response(jsonify(payload), status)
    for k, v in _rl_headers().items():
        resp.headers[k] = v
    return resp


def pagination_args(default_size: int = 30, max_size: int = 100) -> tuple[int, int]:
    try:
        page = int(request.args.get('page') or 1)
    except Exception:
        page = 1
    try:
        page_size = int(request.args.get('page_size') or request.args.get('limit') or default_size)
    except Exception:
        page_size = default_size
    page = max(page, 1)
    page_size = min(max(page_size, 1), max_size)
    return page, page_size


def page_meta(page: int, page_size: int, total: int) -> dict:
    from math import ceil
    pages = ceil(total / page_size) if page_size else 0
    return {'page': page, 'page_size': page_size, 'total': total, 'pages': pages, 'has_next': page < pages, 'has_prev': page > 1}
