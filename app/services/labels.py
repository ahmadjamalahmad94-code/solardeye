from __future__ import annotations

from typing import Any

LABELS = {
    'status': {
        'ar': {
            'new': 'جديد', 'open': 'مفتوح', 'assigned': 'مخصص', 'pending': 'قيد الانتظار',
            'in_progress': 'قيد المتابعة', 'waiting_user': 'بانتظار المستخدم', 'resolved': 'تم الحل',
            'closed': 'مغلق', 'read': 'مقروء', 'unread': 'غير مقروء', 'active': 'نشط',
            'inactive': 'غير نشط', 'disabled': 'معطل', 'enabled': 'مفعل', 'trial': 'تجريبي',
            'suspended': 'معلق', 'expired': 'منتهي', 'cancelled': 'ملغي', 'ok': 'سليم',
            'warning': 'تنبيه', 'danger': 'خطر', 'failed': 'فشل', 'unknown': 'غير معروف',
            'manual': 'يدوي', 'monthly': 'شهري', 'weekly': 'أسبوعي', 'daily': 'يومي', 'paused': 'متوقف مؤقتًا', 'exhausted': 'مستنفد', 'success': 'ناجح', 'info': 'معلومة',
        },
        'en': {
            'new': 'New', 'open': 'Open', 'assigned': 'Assigned', 'pending': 'Pending',
            'in_progress': 'In progress', 'waiting_user': 'Waiting user', 'resolved': 'Resolved',
            'closed': 'Closed', 'read': 'Read', 'unread': 'Unread', 'active': 'Active',
            'inactive': 'Inactive', 'disabled': 'Disabled', 'enabled': 'Enabled', 'trial': 'Trial',
            'suspended': 'Suspended', 'expired': 'Expired', 'cancelled': 'Cancelled', 'ok': 'Healthy',
            'warning': 'Warning', 'danger': 'Danger', 'failed': 'Failed', 'unknown': 'Unknown',
            'manual': 'Manual', 'monthly': 'Monthly', 'weekly': 'Weekly', 'daily': 'Daily', 'paused': 'Paused', 'exhausted': 'Exhausted', 'success': 'Success', 'info': 'Info',
        },
    },
    'priority': {
        'ar': {'low': 'منخفض', 'normal': 'عادي', 'medium': 'متوسط', 'high': 'مهم', 'urgent': 'عاجل'},
        'en': {'low': 'Low', 'normal': 'Normal', 'medium': 'Medium', 'high': 'High', 'urgent': 'Urgent'},
    },
    'type': {
        'ar': {'message': 'رسالة', 'mail': 'رسالة', 'ticket': 'تذكرة', 'support': 'دعم', 'device': 'جهاز', 'finance': 'مالي'},
        'en': {'message': 'Message', 'mail': 'Message', 'ticket': 'Ticket', 'support': 'Support', 'device': 'Device', 'finance': 'Finance'},
    },
    'role': {
        'ar': {'admin': 'مدير', 'manager': 'مشرف', 'user': 'مستخدم'},
        'en': {'admin': 'Administrator', 'manager': 'Manager', 'user': 'User'},
    },
    'finance': {
        'ar': {'credit': 'إضافة رصيد', 'debit': 'خصم', 'refund': 'استرداد', 'adjustment': 'تسوية'},
        'en': {'credit': 'Credit', 'debit': 'Debit', 'refund': 'Refund', 'adjustment': 'Adjustment'},
    },
    'boolean': {
        'ar': {'true': 'نعم', 'false': 'لا', True: 'نعم', False: 'لا'},
        'en': {'true': 'Yes', 'false': 'No', True: 'Yes', False: 'No'},
    },
}

BADGE_CLASSES = {
    'closed': 'is-muted', 'resolved': 'is-success', 'open': 'is-info', 'new': 'is-info',
    'assigned': 'is-primary', 'in_progress': 'is-primary', 'waiting_user': 'is-warning',
    'pending': 'is-warning', 'urgent': 'is-danger', 'high': 'is-danger', 'normal': 'is-muted',
    'low': 'is-muted', 'active': 'is-success', 'trial': 'is-warning', 'expired': 'is-danger',
    'suspended': 'is-danger', 'paused': 'is-warning', 'exhausted': 'is-danger', 'ok': 'is-success', 'success': 'is-success', 'warning': 'is-warning',
    'danger': 'is-danger', 'failed': 'is-danger', 'credit': 'is-success', 'debit': 'is-danger',
}


def normalize_lang(lang: str | None) -> str:
    return 'en' if str(lang or '').lower().startswith('en') else 'ar'


def label(value: Any, category: str = 'status', lang: str = 'ar') -> str:
    if value is None:
        return '—'
    lang = normalize_lang(lang)
    raw = value if isinstance(value, bool) else str(value).strip()
    if raw == '':
        return '—'
    mapping = LABELS.get(category, {})
    lang_map = mapping.get(lang, {})
    return lang_map.get(raw, lang_map.get(str(raw).lower(), str(value)))


def badge_class(value: Any) -> str:
    return BADGE_CLASSES.get(str(value or '').strip().lower(), 'is-muted')


def register_template_helpers(app):
    @app.template_filter('ui_label')
    def _ui_label(value, category='status', lang='ar'):
        return label(value, category, lang)

    @app.template_filter('badge_class')
    def _badge_class(value):
        return badge_class(value)

    @app.context_processor
    def _label_context():
        return {'ui_label': label, 'badge_class': badge_class}
