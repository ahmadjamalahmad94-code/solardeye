from __future__ import annotations

from typing import Any

from flask import g, session, request

from ..models import AppUser
from .subscriptions import current_subscription_for_user, compute_subscription_status


RESTRICTED_AR = 'حسابك معطل أو اشتراكك غير مفعل. يمكنك التعرف على الخدمات، لكن الإجراءات مجمّدة حتى تفعيل حسابك أو اشتراكك للاستفادة من خدماتنا.'
RESTRICTED_EN = 'Your account is disabled or your subscription is not active. You can explore the platform, but actions are frozen until your account or subscription is activated.'


def _lang() -> str:
    return 'en' if (request.args.get('lang') or session.get('ui_lang') or 'ar') == 'en' else 'ar'


def explicit_admin(user: AppUser | None) -> bool:
    if not user:
        return False
    if not bool(getattr(user, 'is_active', True)):
        return False
    role = (getattr(user, 'role', '') or '').strip().lower()
    return bool(getattr(user, 'is_admin', False) or role == 'admin')


def account_access_state(user: AppUser | None, *, include_subscription: bool = True) -> dict[str, Any]:
    """Return the current subscriber access state.

    Disabled subscribers are allowed to browse the portal in read-only preview
    mode. Mutating actions are blocked by the request guard.
    """
    if not user:
        return {'restricted': False, 'reason': '', 'message_ar': '', 'message_en': ''}
    if explicit_admin(user):
        return {'restricted': False, 'reason': '', 'message_ar': '', 'message_en': ''}

    reasons: list[str] = []
    if not bool(getattr(user, 'is_active', True)):
        reasons.append('account_disabled')

    if include_subscription:
        try:
            sub = current_subscription_for_user(user)
            sub_status = compute_subscription_status(sub)
            if sub_status not in ('trial', 'active'):
                reasons.append('subscription_inactive')
        except Exception:
            # If the subscription state cannot be resolved, do not crash the page;
            # let the portal render in preview mode.
            reasons.append('subscription_unknown')

    restricted = bool(reasons)
    return {
        'restricted': restricted,
        'reason': ','.join(reasons),
        'message_ar': RESTRICTED_AR if restricted else '',
        'message_en': RESTRICTED_EN if restricted else '',
    }


def account_restricted(user: AppUser | None = None) -> bool:
    if user is None:
        user = getattr(g, 'current_user', None)
        if user is None and session.get('user_id'):
            try:
                user = AppUser.query.get(int(session.get('user_id')))
            except Exception:
                user = None
    return bool(account_access_state(user).get('restricted'))


def account_restricted_message(lang: str | None = None, user: AppUser | None = None) -> str:
    state = account_access_state(user or getattr(g, 'current_user', None))
    lang = 'en' if str(lang or _lang()).lower().startswith('en') else 'ar'
    return state.get('message_en' if lang == 'en' else 'message_ar') or ''


def request_user_from_session() -> AppUser | None:
    user = getattr(g, 'current_user', None)
    if user is not None:
        return user
    if session.get('user_id'):
        try:
            return AppUser.query.get(int(session.get('user_id')))
        except Exception:
            return None
    return None
