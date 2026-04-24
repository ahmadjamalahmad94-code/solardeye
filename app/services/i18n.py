from __future__ import annotations

from urllib.parse import urlencode

from flask import g, request, session, url_for

SUPPORTED_LANGS = {'ar', 'en'}

# Server-side phrases used mostly for flashes and old templates that pre-date the
# full i18n pass. Client-side fallback handles small legacy labels too.
PHRASES = {
    'اختر مستخدمًا واحدًا على الأقل لتنفيذ العملية.': 'Select at least one user before applying an action.',
    'إجراء جماعي غير معروف.': 'Unknown bulk action.',
    'تم تنفيذ العملية على {changed} مستخدم. تم تخطي {skipped}.': 'Action applied to {changed} users. Skipped {skipped}.',
    'تم تحديث حالة المستخدم.': 'User status updated.',
    'لا يمكن تعطيل مدير النظام الأساسي.': 'The primary system administrator cannot be disabled.',
    'تم حذف المستخدم نهائيًا.': 'User permanently deleted.',
    'لا يمكن حذف مدير النظام الأساسي.': 'The primary system administrator cannot be deleted.',
    'لا يمكن حذف حسابك الحالي.': 'You cannot delete your own current account.',
    'تعذر حذف المستخدم بسبب بيانات مرتبطة. تم تعطيله بدلًا من ذلك حفاظًا على السجلات.': 'The user could not be deleted because linked data exists. The account was disabled instead to preserve records.',
    'تم إنشاء نسخة احتياطية بنجاح.': 'Backup created successfully.',
    'تم تحديث إعدادات النسخ الاحتياطي.': 'Backup settings updated.',
    'تعذر إنشاء النسخة الاحتياطية.': 'Backup creation failed.',
    'تم استعادة قاعدة البيانات من النسخة الاحتياطية.': 'Database restored from the selected backup.',
    'تعذر استعادة النسخة الاحتياطية.': 'Backup restore failed.',
    'تم حفظ نوع التكامل بنجاح': 'Integration type saved successfully.',
    'تم تحديث الخطة': 'Plan updated.',
    'تم تفعيل اشتراك المشترك': 'Subscriber subscription activated.',
    'تم حفظ الإعدادات بنجاح': 'Settings saved successfully.',
    'تم حفظ إعدادات Telegram': 'Telegram settings saved.',
    'تم حفظ إعدادات SMS': 'SMS settings saved.',
    'تم اختيار الجهاز': 'Device selected',
    'الجهاز المطلوب غير متاح ضمن حسابك.': 'The requested device is not available in your account.',
    'تم إرسال الرد وتحديث المحادثة.': 'Reply sent and conversation updated.',
    'تم إرسال الرد وتحديث التذكرة.': 'Reply sent and ticket updated.',
    'تم فتح التذكرة بنجاح': 'Ticket opened successfully.',
    'تم إرسال الرسالة بنجاح': 'Message sent successfully.',
}


def normalize_lang(value: str | None) -> str:
    value = str(value or '').strip().lower()
    return 'en' if value.startswith('en') else 'ar'


def active_lang() -> str:
    return normalize_lang(getattr(g, 'ui_lang', None) or session.get('ui_lang') or 'ar')


def choose(ar: str, en: str) -> str:
    return en if active_lang() == 'en' else ar


def translate(value: str, lang: str | None = None, **kwargs) -> str:
    target = normalize_lang(lang or active_lang())
    text = '' if value is None else str(value)
    if target != 'en':
        return text.format(**kwargs) if kwargs else text
    template = PHRASES.get(text, text)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def lang_url(lang: str, endpoint: str | None = None, **values) -> str:
    """Build a URL preserving the current route/query while changing language."""
    lang = normalize_lang(lang)
    endpoint = endpoint or request.endpoint
    if not endpoint:
        return f'?lang={lang}'
    args = request.view_args.copy() if request.view_args else {}
    args.update(values)
    # Preserve useful query args such as tab/filter/type, but override lang.
    query = request.args.to_dict(flat=True)
    query.update(args)
    query['lang'] = lang
    try:
        return url_for(endpoint, **query)
    except Exception:
        query = request.args.to_dict(flat=True)
        query['lang'] = lang
        return request.path + '?' + urlencode(query)


def register_i18n(app):
    @app.before_request
    def _capture_language():
        raw = request.args.get('lang') or request.form.get('lang')
        if raw:
            session['ui_lang'] = normalize_lang(raw)
        elif 'ui_lang' not in session:
            session['ui_lang'] = 'ar'
        g.ui_lang = normalize_lang(session.get('ui_lang'))
        return None

    @app.context_processor
    def _i18n_context():
        lang = active_lang()
        return {
            'ui_lang': lang,
            'is_en': lang == 'en',
            't': translate,
            'lang_url': lang_url,
        }
