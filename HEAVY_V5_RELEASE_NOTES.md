# SolarDeye Heavy v5

هذه نسخة Heavy v5 مبنية فوق Heavy v4 مع إضافة طبقة إشعارات فعلية:

- أيقونة إشعارات عائمة في الواجهة.
- عداد رسائل وتذاكر مفتوحة.
- قائمة آخر 5 إشعارات.
- مركز إشعارات كامل `/notification-center`.
- روابط مباشرة إلى صفحة المشترك / تبويب الدعم أو بوابة المستخدم.
- الحفاظ على إعدادات Render: `gunicorn --bind 0.0.0.0:$PORT wsgi:app`, Python 3.11.9, psycopg2-binary 2.9.9.

ملاحظة: هذه النسخة مبنية على آخر نسخة متوفرة في بيئة الملفات: `solardeye_admin_heavy_v4_user360_restructure.zip`.
