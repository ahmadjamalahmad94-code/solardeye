from __future__ import annotations

from contextvars import ContextVar

from flask import g, has_request_context, session

from ..models import AppDevice, AppUser

_system_user_id: ContextVar[int | None] = ContextVar('_system_user_id', default=None)
_system_device_id: ContextVar[int | None] = ContextVar('_system_device_id', default=None)


def set_system_scope(user_id: int | None, device_id: int | None):
    token_user = _system_user_id.set(user_id)
    token_device = _system_device_id.set(device_id)
    return token_user, token_device


def reset_system_scope(tokens):
    if not tokens:
        return
    token_user, token_device = tokens
    try:
        _system_user_id.reset(token_user)
    except Exception:
        pass
    try:
        _system_device_id.reset(token_device)
    except Exception:
        pass


def get_default_system_user():
    user = AppUser.query.filter_by(is_active=True, is_admin=True).order_by(AppUser.id.asc()).first()
    if user:
        return user
    return AppUser.query.filter_by(is_active=True).order_by(AppUser.id.asc()).first()


def get_default_system_device(user: AppUser | None = None):
    if user is not None:
        device = AppDevice.query.filter_by(owner_user_id=user.id, is_active=True).order_by(AppDevice.id.asc()).first()
        if device:
            return device
    return AppDevice.query.filter_by(is_active=True).order_by(AppDevice.id.asc()).first()


def get_current_user():
    if has_request_context():
        user = getattr(g, 'current_user', None)
        if user is not None:
            return user
        user_id = session.get('user_id')
        if user_id:
            found = AppUser.query.filter_by(id=user_id, is_active=True).first()
            if found:
                return found

    system_user_id = _system_user_id.get()
    if system_user_id:
        found = AppUser.query.filter_by(id=system_user_id, is_active=True).first()
        if found:
            return found

    return get_default_system_user()


def get_current_device():
    if has_request_context():
        device = getattr(g, 'current_device', None)
        if device is not None:
            return device
        device_id = session.get('current_device_id')
        if device_id:
            found = AppDevice.query.filter_by(id=device_id, is_active=True).first()
            if found:
                return found

    system_device_id = _system_device_id.get()
    if system_device_id:
        found = AppDevice.query.filter_by(id=system_device_id, is_active=True).first()
        if found:
            return found

    user = get_current_user()
    return get_default_system_device(user)


def current_scope_ids():
    user = get_current_user()
    device = get_current_device()
    return (getattr(user, 'id', None), getattr(device, 'id', None))


def is_system_admin() -> bool:
    user = get_current_user()
    if not user:
        return False
    return bool(getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'admin')


def scoped_query(model, query=None):
    query = query or model.query
    user_id, device_id = current_scope_ids()
    if device_id is not None and hasattr(model, 'device_id'):
        query = query.filter(getattr(model, 'device_id') == device_id)
    elif user_id is not None and hasattr(model, 'user_id'):
        query = query.filter(getattr(model, 'user_id') == user_id)
    return query
