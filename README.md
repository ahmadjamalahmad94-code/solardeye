# منصة الطاقة الشمسية — Solar Platform

## البنية الجديدة (v16)

```
app/
├── blueprints/
│   ├── auth.py          # تسجيل الدخول والخروج وحماية الـ routes
│   ├── main.py          # Dashboard، Statistics، Reports، Devices...
│   ├── helpers.py       # دوال مشتركة (Battery، Stats، Formatting)
│   └── notifications.py # Telegram، SMS، قواعد الإشعارات
├── services/
│   ├── deye_client.py   # الاتصال بـ Deye Cloud API
│   ├── weather_service.py
│   └── utils.py
├── templates/
├── static/
├── config.py
├── models.py
└── extensions.py
```

## التشغيل

```bash
cp .env.example .env
# عدّل .env وأدخل بياناتك الحقيقية

pip install -r requirements.txt
python app.py
```

## التغييرات الرئيسية في v16

- **أمان**: SECRET_KEY عشوائية تلقائياً، SESSION_LIFETIME 12 ساعة
- **أداء**: الاستعلامات محدودة بالتاريخ — لا full table scans
- **هيكلة**: routes.py المضخم قُسِّم لـ 3 ملفات blueprints
- **صيانة**: تنظيف تلقائي لـ SyncLog (30 يوم) وNotificationLog (90 يوم)
- **أخطاء**: صفحات 404/500 مخصصة بالعربي
- **بيانات**: data_gaps مُتتبَّعة في إحصائيات الطاقة

## تحذير مهم عند الترقية من نسخة قديمة

لو كنت تشغّل نسخة قديمة وتريد الترقية، **لا تنسخ الملفات فوق المشروع القديم مباشرة**.
بدلاً من ذلك:

```bash
# 1. احتفظ بملف قاعدة البيانات فقط
cp solar_platform_old/*.db .

# 2. احذف المجلد القديم كاملاً
# 3. فك ضغط هذا الـ zip في مكان جديد
# 4. انسخ ملف .env وقاعدة البيانات للمجلد الجديد
cp ../solar_platform_old/.env .env
cp ../solar_platform_old/*.db .
```

**السبب:** النسخة القديمة تحتوي على `app/routes.py` يسبب تعارضاً مع الـ blueprints الجديدة.


## Multi-user foundation (safe mode)

This build adds foundation-only tables for future multi-user and multi-device support without changing the current runtime scheduling or day/night logic.
