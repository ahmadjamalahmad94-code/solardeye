
from __future__ import annotations
import secrets
from datetime import UTC, datetime, timedelta

from ..extensions import db
from ..models import TelegramLink


def _utc_now_naive():
    return datetime.now(UTC).replace(tzinfo=None)


def get_owner_key(username: str | None) -> str:
    username = (username or 'admin').strip() or 'admin'
    return f'admin:{username}'


def get_or_create_link(owner_key: str, owner_label: str | None = None) -> TelegramLink:
    link = TelegramLink.query.filter_by(owner_key=owner_key).first()
    if not link:
        link = TelegramLink(owner_key=owner_key, owner_label=owner_label or owner_key, link_status='revoked')
        db.session.add(link)
        db.session.flush()
    elif owner_label:
        link.owner_label = owner_label
    return link


def create_link_token(owner_key: str, owner_label: str | None = None, expiry_minutes: int = 10) -> TelegramLink:
    link = get_or_create_link(owner_key, owner_label)
    token = 'link_' + secrets.token_urlsafe(18)
    link.link_token = token
    link.link_token_expires_at = _utc_now_naive() + timedelta(minutes=max(int(expiry_minutes or 10), 1))
    link.link_status = 'pending'
    link.is_active = True
    db.session.commit()
    return link


def consume_link_token(token: str, telegram_data: dict) -> tuple[bool, str, TelegramLink | None]:
    token = (token or '').strip()
    if not token:
        return False, 'رمز الربط غير موجود.', None

    link = TelegramLink.query.filter_by(link_token=token).first()
    if not link:
        return False, 'رمز الربط غير صالح أو لم يعد متاحًا.', None

    now = _utc_now_naive()
    if link.link_token_expires_at and link.link_token_expires_at < now:
        return False, 'انتهت صلاحية رمز الربط. أنشئ رمزًا جديدًا من داخل المنصة.', None

    incoming_user_id = str(telegram_data.get('telegram_user_id') or '').strip()
    existing = None
    if incoming_user_id:
        existing = TelegramLink.query.filter(
            TelegramLink.telegram_user_id == incoming_user_id,
            TelegramLink.owner_key != link.owner_key,
            TelegramLink.link_status == 'linked',
            TelegramLink.is_active.is_(True),
        ).first()
    if existing:
        return False, 'هذا الحساب في Telegram مربوط بحساب آخر بالفعل.', None

    link.telegram_user_id = incoming_user_id or None
    link.telegram_chat_id = str(telegram_data.get('telegram_chat_id') or '').strip() or None
    link.telegram_username = telegram_data.get('telegram_username') or None
    link.telegram_first_name = telegram_data.get('telegram_first_name') or None
    link.telegram_last_name = telegram_data.get('telegram_last_name') or None
    link.link_status = 'linked'
    link.linked_at = now
    link.last_seen_at = now
    link.link_token = None
    link.link_token_expires_at = None
    link.is_active = True
    db.session.commit()
    return True, 'تم ربط Telegram بنجاح ✅', link


def revoke_link(owner_key: str) -> tuple[bool, str]:
    link = TelegramLink.query.filter_by(owner_key=owner_key).first()
    if not link:
        return False, 'لا يوجد ربط لإلغائه.'
    link.link_status = 'revoked'
    link.is_active = False
    link.telegram_chat_id = None
    link.telegram_user_id = None
    link.telegram_username = None
    link.telegram_first_name = None
    link.telegram_last_name = None
    link.link_token = None
    link.link_token_expires_at = None
    db.session.commit()
    return True, 'تم إلغاء ربط Telegram بنجاح.'


def touch_link_by_chat_id(chat_id: str | None) -> TelegramLink | None:
    chat_id = str(chat_id or '').strip()
    if not chat_id:
        return None
    link = TelegramLink.query.filter_by(telegram_chat_id=chat_id, link_status='linked', is_active=True).first()
    if link:
        link.last_seen_at = _utc_now_naive()
        db.session.commit()
    return link


def get_link_by_owner(owner_key: str) -> TelegramLink | None:
    return TelegramLink.query.filter_by(owner_key=owner_key).first()
