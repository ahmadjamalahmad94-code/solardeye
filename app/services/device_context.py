"""Device-context Flask glue.

Powers the subscriber-side multi-device UX (v32):

  * Provides every template with ``user_devices`` (the list this user owns),
    ``current_device_id`` (the device whose data is being viewed), and
    ``aggregate_mode`` (True when the user has explicitly selected the
    "all devices" aggregate view).

  * Honours the ``?selected_device_id=...`` query param on any GET so the
    persistent device switcher just works: clicking an item in the dropdown
    flips the session and redirects back to the same page without the param
    (clean URLs, no infinite query-string growth).

The data layer is already device-aware:

  * ``AppUser.preferred_device_id`` — durable preference, used as fallback.
  * ``session['current_device_id']`` — fast per-request access.
  * ``services.scope.scoped_query`` — auto-filters models by device_id when
    a current device is set.

This service does NOT add new database columns. It is purely the wiring
between the URL/session, the Jinja context, and the existing scope helpers.

Backwards compatibility:
  * If the user has 0 devices, ``user_devices`` is ``[]`` and the device
    switcher partial renders nothing.
  * If the user has 1 device, the switcher partial still renders (so
    "Manage" + "Add device" remain reachable), but the dropdown collapses
    to one entry.
  * Admin scope (``/admin/*``) is skipped — the switcher never appears
    there, and routes never resolve to a device for admin users.
"""
from __future__ import annotations

from typing import Any

from flask import g, redirect, request, session, url_for, has_request_context

from ..models import AppDevice
from .scope import get_current_user, is_admin_scope


_AGGREGATE_TOKEN = '__all__'


def _user_devices_for(user) -> list[AppDevice]:
    if user is None:
        return []
    return (
        AppDevice.query
        .filter_by(owner_user_id=user.id)
        .order_by(AppDevice.is_active.desc(), AppDevice.id.asc())
        .all()
    )


def _resolve_device_for_user(user, raw_id):
    """Return (device_id_or_None, aggregate_mode)."""
    if raw_id == _AGGREGATE_TOKEN:
        return None, True
    if not raw_id:
        return None, False
    try:
        rid = int(raw_id)
    except (ValueError, TypeError):
        return None, False
    if user is None:
        return None, False
    found = AppDevice.query.filter_by(id=rid, owner_user_id=user.id).first()
    if found is None:
        return None, False
    return found.id, False


def _is_subscriber_endpoint() -> bool:
    """Heuristic: is the current request a subscriber-side page that should
    honour ?selected_device_id=...?

    We intentionally accept the parameter on *any* non-admin GET request.
    Admin pages are skipped, JSON/API endpoints are skipped (they don't
    redirect), and POSTs are passed through unchanged so form submits
    still hit their handler.
    """
    if not has_request_context():
        return False
    if request.method != 'GET':
        return False
    path = (request.path or '').lower()
    if path.startswith('/admin') or path.startswith('/api/'):
        return False
    if is_admin_scope():
        return False
    return True


def _maybe_apply_selected_device_query():
    """If ?selected_device_id=... is present on a subscriber GET, set the
    session and redirect to the same URL without that param.
    Returns a Response on redirect, or None to continue normally.
    """
    if not _is_subscriber_endpoint():
        return None

    raw = request.args.get('selected_device_id')
    if raw is None:
        return None

    user = get_current_user()
    if user is None:
        return None

    if raw == _AGGREGATE_TOKEN:
        session['current_device_id'] = _AGGREGATE_TOKEN
        session.pop('aggregate_legacy', None)
    else:
        device_id, _ = _resolve_device_for_user(user, raw)
        if device_id is None:
            # Bad id — drop it but still strip the param.
            session.pop('current_device_id', None)
        else:
            session['current_device_id'] = device_id
            # Persist as the durable preferred device too, so /devices/manage
            # and the dashboard agree across sessions.
            try:
                if user.preferred_device_id != device_id:
                    user.preferred_device_id = device_id
                    from ..extensions import db
                    db.session.commit()
            except Exception:
                # Best effort — never break the page over a preference write.
                from ..extensions import db
                db.session.rollback()

    # Strip ?selected_device_id and redirect (preserve other query args).
    new_args = {k: v for k, v in request.args.items() if k != 'selected_device_id'}
    target = url_for(request.endpoint, **(request.view_args or {}), **new_args) if request.endpoint else request.path
    return redirect(target)


def _device_context_payload() -> dict[str, Any]:
    """Return the context-processor dict."""
    if not has_request_context() or is_admin_scope():
        return {
            'user_devices': [],
            'current_device_id': None,
            'aggregate_mode': False,
        }

    user = get_current_user()
    devices = _user_devices_for(user)

    raw = session.get('current_device_id')
    if raw == _AGGREGATE_TOKEN:
        return {
            'user_devices': devices,
            'current_device_id': None,
            'aggregate_mode': True,
        }

    device_id, _ = _resolve_device_for_user(user, raw)
    if device_id is None and user is not None:
        # Fall back to durable preference, then first device.
        device_id = (
            user.preferred_device_id
            if user.preferred_device_id and any(d.id == user.preferred_device_id for d in devices)
            else (devices[0].id if devices else None)
        )

    return {
        'user_devices': devices,
        'current_device_id': device_id,
        'aggregate_mode': False,
    }


def device_switcher_context() -> dict[str, Any]:
    """Public helper for routes that want to pass the device-switcher payload
    explicitly (useful when the registered context_processor isn't loaded yet,
    e.g. immediately after deploying v32 without restarting the Flask process).

    Returns a ``{'user_devices', 'current_device_id', 'aggregate_mode'}`` dict
    that templates can splat into their context. Safe to call from any
    request handler — admin scope returns the empty fallback.
    """
    try:
        return _device_context_payload()
    except Exception:
        return {'user_devices': [], 'current_device_id': None, 'aggregate_mode': False}


def register_device_context(app) -> None:
    """Register the before_request and context_processor hooks on *app*."""

    @app.before_request
    def _device_switcher_query_param():
        # Skip if security/quota guards already redirected.
        return _maybe_apply_selected_device_query()

    @app.context_processor
    def _inject_device_context():
        try:
            return _device_context_payload()
        except Exception:
            # Never break a render over the switcher.
            return {
                'user_devices': [],
                'current_device_id': None,
                'aggregate_mode': False,
            }
