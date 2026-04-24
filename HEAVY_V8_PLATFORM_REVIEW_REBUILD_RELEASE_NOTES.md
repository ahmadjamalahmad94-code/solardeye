# Heavy v8.0 — Platform Review, Privacy, Recovery & UI Hardening

## هدف الإصدار
هذا الإصدار يخرج SolarDeye من مرحلة تعديلات صفحات منفصلة إلى مرحلة مراجعة منصة كاملة: فحص صفحة بصفحة، حماية بيانات خاصة، تحسينات استعادة، وتوحيد أقوى للواجهة.

## التعديلات الرئيسية

### 1. مركز مراجعة المنصة
- إضافة صفحة جديدة: `/admin/platform-review`.
- تعرض فحصًا ثابتًا للقوالب، نماذج POST، CSRF، inline styles، احتمالات ظهور بيانات خاصة، وحجم ملفات CSS/JS.
- تمت إضافتها إلى السايدبار تحت قسم الإدارة.

### 2. إخفاء بيانات خاصة
- إخفاء Plant ID و Device SN في صفحة معلومات المحطة.
- إخفاء رقم الانفيرتر في صفحة الأجهزة.
- إخفاء Device UID / External ID في مركز أجهزة الإدارة.
- إخفاء Station ID داخل قائمة أجهزة المشترك.
- إخفاء Telegram Chat ID و SMS recipients داخل صفحة القنوات.
- توسيع sanitize_response_payload لإخفاء مفاتيح مثل email, phone, chat_id, plant_id, station_id, device_sn, logger_sn, serial.

### 3. حماية CSRF أقوى
- إضافة hidden csrf_token مباشرة إلى كل نماذج POST في القوالب، وليس فقط عبر JavaScript.
- الإبقاء على CSRF التلقائي في JavaScript كطبقة إضافية.

### 4. النسخ الاحتياطي والاستعادة
- إضافة رفع ملف backup محلي بصيغة `solardeye_backup_*.json.gz` من صفحة `/admin/backups`.
- فحص الملف المرفوع قبل إدراجه في نقاط الاستعادة.
- تحديث نسخة backup payload إلى `heavy-v8.0`.

### 5. صحة الخدمات والجدولة
- تحسين قراءة حالة Scheduler: إذا لم يظهر داخل نفس worker لكن آخر heartbeat حديث وسليم، لا يتم اعتباره فاشلًا.
- الرسالة توضّح الفرق بين Scheduler visible داخل worker و Scheduler صحي حسب آخر heartbeat.

### 6. UI hardening
- تحديث النسخة في base و sidebar إلى v8.0.
- منع خروج الكروت والجداول عن حدود الصفحة بشكل أعمق.
- توحيد إضافي للأزرار والحالات والـ focus states.
- تحسين responsive للصفحات الإدارية والجداول.
- إضافة `prefers-reduced-motion` لتقليل الحركة لمن يطلب ذلك.

### 7. مركز الأجهزة
- إعادة تصميم `/admin/devices` كـ Device Fleet Center.
- إضافة KPIs للأجهزة، المتصل، المعطل، الأنواع.
- إظهار المعرّفات الحساسة بشكل مخفي.
- تحسين الفلاتر وعرض الحالة والمالك والمشترك.

## الفحص المنفذ
- Python compile: ناجح.
- Jinja parse لكل القوالب: ناجح.
- JavaScript syntax عبر Node: ناجح.
- i18n audit: لا توجد قوالب legacy عربية غير مترجمة حسب أداة الفحص.
- فحص مباشر للنماذج: كل POST forms تحتوي csrf_token ظاهر.
- فحص أسرار داخل الحزمة: لا توجد `.env` أو قواعد بيانات أو ملفات client_secret في ZIP النهائي.

## ملاحظات تشغيل بعد النشر
- افتح `/admin/platform-review` لمراجعة الصفحات بعد النشر.
- افتح `/admin/backups` وجرب Backup Now ثم Upload Backup على ملف تجريبي.
- افتح `/admin/services-health` وتأكد أن Scheduler لا يظهر كفاشل إذا كانت آخر نبضة حديثة.
- افتح `/admin/devices` وتأكد من إخفاء المعرفات.
- اعمل hard refresh بعد النشر بسبب تحديث CSS/JS إلى `v=8.0`.
