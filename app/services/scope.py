from __future__ import annotations

from flask import current_app, g, session

from ..models import AppDevice, AppUser


def get_current_user():
    user = getattr(g, 'current_user', None)
    if user is not None:
        return user
    user_id = session.get('user_id')
    if user_id:
        return AppUser.query.filter_by(id=user_id, is_active=True).first()
    return AppUser.query.order_by(AppUser.id.asc()).first()


def get_current_device():
    device = getattr(g, 'current_device', None)
    if device is not None:
        return device
    device_id = session.get('current_device_id')
    if device_id:
        found = AppDevice.query.filter_by(id=device_id, is_active=True).first()
        if found:
            return found
    user = get_current_user()
    if user:
        found = AppDevice.query.filter_by(owner_user_id=user.id, is_active=True).order_by(AppDevice.id.asc()).first()
        if found:
            return found
    return AppDevice.query.filter_by(is_active=True).order_by(AppDevice.id.asc()).first()


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
