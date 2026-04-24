# Heavy v7.1 — Language, Subscribers, Backup & Recovery Patch

## الهدف
تصحيح المشاكل التي ظهرت بعد v7.0:

- تثبيت تغيير اللغة في الإدارة والمشترك.
- منع بقاء نصوص عربية ظاهرة عند اختيار English قدر الإمكان عبر طبقة لغة عامة + fallback للواجهات القديمة.
- إعادة هيكلة صفحة إدارة المشتركين مع إجراءات سريعة.
- إضافة حذف نهائي فعلي بجانب التعطيل الآمن.
- تفعيل النسخ الاحتياطي المحلي وجدولته، مع رفع اختياري إلى Google Drive.
- تحسين مركز صحة الخدمات حتى يعرض حالة Scheduler والنسخ الاحتياطي بوضوح.
- مراجعة واجهة المشترك/الدعم وإضافة CSS يمنع خروج الكروت والجداول عن حدود الصفحة.

## الملفات الأهم

- `app/services/i18n.py`
- `app/services/backup_service.py`
- `app/blueprints/main.py`
- `app/scheduler.py`
- `app/templates/admin_subscribers_phase1a.html`
- `app/templates/admin_backups.html`
- `app/templates/admin_services_health.html`
- `app/templates/_sidebar.html`
- `app/templates/base.html`
- `app/static/js/app.js`
- `app/static/css/style.css`
- `requirements.txt`
- `render.yaml`

## إعدادات النسخ الاحتياطي

يمكن ضبطها من صفحة:

`/admin/backups`

أو من متغيرات البيئة:

```env
BACKUP_ENABLED=true
BACKUP_FREQUENCY=daily
BACKUP_KEEP_LOCAL=12
GOOGLE_DRIVE_BACKUP_ENABLED=false
GOOGLE_DRIVE_BACKUP_FOLDER_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=
GOOGLE_SERVICE_ACCOUNT_FILE=
```

للرفع إلى Google Drive يجب استخدام Service Account ومشاركة مجلد Drive معها.

## الفحص

تم فحص:

- Python syntax عبر `compileall`.
- Jinja parsing لكل القوالب.
- JavaScript syntax عبر `node --check`.
- تنظيف `__pycache__` قبل التغليف.

لم يتم تشغيل runtime كامل داخل sandbox لأن Flask غير مثبت في البيئة المحلية هنا.
