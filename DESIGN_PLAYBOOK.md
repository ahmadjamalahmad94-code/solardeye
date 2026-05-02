# SolarDeye Design Playbook

مرجع التصميم والتنفيذ الأمامي الرسمي للمشروع.  
أي تطوير أو تحسين في الواجهة يجب أن يُقاس على هذا الملف قبل التنفيذ.

## 1. الصفحات المرجعية الأساسية

هذه الصفحات هي المرجع الأعلى للأسلوب الحالي:

- `app/templates/dashboard.html`
- `app/static/css/dashboard_v40.css`
- `app/templates/live_data.html`
- `app/templates/reports.html`
- `app/templates/statistics.html`
- `app/templates/notifications_center.html`
- `app/static/css/notifications_center_v40.css`
- `app/static/js/notifications_center_v40.js`

## 2. فلسفة التصميم

المنتج يتبع أسلوب:

- SaaS clean UI
- نظيف ومريح بصريًا
- غني بصريًا لكن غير مزدحم
- واضح التراتب
- عربي أولًا مع دعم إنجليزي كامل
- الكروت لا تتمدد عشوائيًا
- القوائم الطويلة تبقى داخل `scroll` داخلي

القاعدة الأساسية:

- لا نعيد بناء الصفحة من الصفر إلا عند الحاجة
- نُحسن ضمن نفس اللغة البصرية
- التغيير يجب أن يشعر المستخدم أنه “تطوير طبيعي” لا “صفحة من مشروع آخر”

## 3. الهوية اللونية

### ألوان النص والخلفيات

- Text primary: `#0b1220`
- Text secondary: `#5e6f8c`
- Text soft: `#1f2a44`
- Border: `#e3eaf6`
- Border stronger: `#cfd9ec`
- Card background: `#ffffff`
- Card soft background: `#f9fbff`
- Page background layers:
  - `#f5f8ff`
  - `#eef3fb`
  - `#e8eef9`

### ألوان الدلالة

- Blue: `#2563eb`
- Blue soft: `#60a5fa`
- Violet: `#6d3aff` / `#7c3aed`
- Amber: `#f59e0b`
- Amber soft: `#fbbf24`
- Green: `#10b981`
- Green soft: `#34d399`
- Rose: `#f43f5e`
- Rose soft: `#fb7185`
- Orange: `#f97316`

## 4. الخلفيات والتدرجات

### الخلفية العامة للصفحات

الخلفية المرجعية لمعظم الصفحات:

```css
background:
  radial-gradient(1100px 480px at 12% -10%, rgba(109, 58, 255, .10), transparent 55%),
  radial-gradient(900px 420px at 92% -4%, rgba(245, 158, 11, .10), transparent 55%),
  linear-gradient(180deg, #f5f8ff 0%, #eef3fb 60%, #e8eef9 100%);
```

### Hero gradient المرجعي

```css
linear-gradient(135deg, #0e3b86 0%, #3aa7ff 50%, #ffd66e 100%)
```

### Hero الإشعارات

```css
linear-gradient(135deg, #1e293b 0%, #1e3a8a 50%, #4338ca 100%)
```

### Hero الداشبورد

Hero ديناميكي بحسب `day_phase`، لكن يلتزم نفس الروح:

- سماء
- توهج
- انتقال ناعم
- طبقات زخرفية غير مزعجة

## 5. الخطوط والتراتبية الطباعية

### الخط الرسمي

```css
font-family: 'Cairo', 'Inter', system-ui, sans-serif;
```

### الأوزان

- Hero / large headings: `950`
- Section titles: `900 - 950`
- Labels and chips: `800 - 900`
- Supporting text: `600 - 700`

### المقاسات المرجعية

- Hero title: `clamp(1.55rem, 2.6vw, 2.05rem)`
- Dashboard hero can go bigger: up to `2.8rem`
- Hero description: `0.95rem - 1rem`
- Section title: `1.02rem - 1.15rem`
- Card label: `0.7rem - 0.8rem`
- Secondary/meta text: `0.76rem - 0.85rem`
- Main values:
  - `1.15rem`
  - `1.55rem`
  - `2rem`
  - `2.05rem`

### قاعدة مهمة

- العنوان قوي وواضح
- النص الثانوي أخف وأهدأ
- الأرقام المهمة يجب أن تبرز مباشرة

## 6. المسافات والإيقاع

### على مستوى الصفحة

- Padding الصفحة:
  - `18px clamp(14px, 2.4vw, 32px) 80px`
- Gap بين الأقسام الرئيسية:
  - `22px` أو `30px`

### على مستوى الكروت

- Padding داخلي متكرر:
  - `18px 20px`
  - `20px 22px`
- Gap داخلي بين عناصر الكرت:
  - `8px`
  - `10px`
  - `12px`
  - `16px`

### القاعدة الإلزامية

- لا تترك الأقسام ملزقة ببعض
- الصفحة يجب أن تتنفس
- إذا كان أول Section مريحًا، يجب أن تكون نفس المسافة مطبقة على الباقي

## 7. الزوايا والظلال

### Border radius

- Small: `12px`
- Standard: `18px - 22px`
- Large: `24px - 30px`
- Hero XL: `28px - 38px`
- Pills / badges: `999px`

### Shadows

- Card shadow:

```css
0 6px 18px rgba(15, 23, 42, .06)
```

- Hover shadow:

```css
0 22px 60px rgba(15, 23, 42, .09)
```

- Hero shadow:

```css
0 38px 90px rgba(15, 23, 42, .14)
```

### ممنوع

- ظلال قاسية
- حدود سميكة
- كروت حادة أو مزعجة

## 8. بنية الصفحة القياسية

الهيكل المرجعي لمعظم الصفحات:

1. Hero واضح
2. شريط تحكم / فلترة / تنقل
3. Summary cards
4. Main sections داخل cards
5. قوائم / جداول / رسوم
6. القوائم الطويلة داخل scroll

## 9. الـ Hero

### خصائصه

- واضح من أول نظرة
- Title كبير ومباشر
- Description قصيرة
- Eyebrow pill صغيرة أعلى العنوان
- Meta pills أو actions على الطرف الثاني
- Responsive بدون انهيار

### مكوناته المتكررة

- badge صغيرة مع pulse
- عنوان
- نص تعريفي قصير
- action buttons
- meta chips

## 10. الكروت

### خصائص عامة

- White card
- Border خفيف
- Shadow خفيف
- Radius متوسط إلى كبير
- داخله hierarchy واضح

### أسلوب الإبراز

- top accent bar
- icon tile صغيرة
- value prominent
- meta text هادئ

### ممنوع

- كرت يتمدد لأن النص طال
- كرت بلا hierarchy
- ضغط عناصر كثيرة في مساحة صغيرة

## 11. الـ Chips / Pills / Badges

عنصر أساسي في النظام.

الاستخدامات:

- status
- priority
- counters
- active tabs
- filters
- meta labels

خصائصها:

- `border-radius: 999px`
- padding صغير
- font-weight عالٍ
- لون خلفية خفيف
- لون نص أوضح

## 12. الأيقونات والرموز

الأسلوب الحالي يمزج بين:

- emoji / glyphs في الصفحات التشغيلية
- icons مخصصة في الصفحات الأكثر modular مثل الإشعارات

### قاعدة العمل

- إذا كانت الصفحة سريعة/تشغيلية: يجوز استخدام رموز بسيطة متوازنة
- إذا كانت الصفحة كبيرة أو طويلة العمر: يفضل icons منظمة عبر component/macro

### ممنوع

- أيقونات كبيرة ومشتتة
- عدم التوازن بين الأيقونة والنص

## 13. الجداول والقوائم الطويلة

هذه نقطة إلزامية:

- لا نترك القوائم الطويلة تمدد الصفحة
- يجب وضعها داخل wrapper داخلي

### النمط المرجعي

```css
overflow: auto;
max-height: min(62vh, 520px);
```

### الاستخدامات

- الجداول الكبيرة
- قوائم الأجهزة
- integration lists
- notification rows
- activity logs

### الهدف

- الحفاظ على توازن الصفحة
- إبقاء كل section بطول منطقي
- تقليل الفوضى البصرية

## 14. الـ Layout والتوزيع

### الصفحات التحليلية

`statistics / reports / live-data`

- صفحات stack رأسية
- gap واضح بين sections
- grids داخلية مرنة
- cards متعددة بنفس اللغة

### الداشبورد

يعتمد Grid من 12 عمودًا.

الأسبان المرجعية:

- `span-full`
- `span-8`
- `span-7`
- `span-6`
- `span-5`
- `span-4`
- `span-3`

وعند الحاجة لتثبيت قسمين جنب بعض:

- نعمل row wrapper خاص
- مثل `d40-log-row`

### الإشعارات

تخطيط عمود رئيسي + عمود جانبي:

```css
grid-template-columns: minmax(0, 1fr) 340px;
```

## 15. الـ Responsive

### القاعدة

- لا نكسر الموبايل
- لا نترك النصوص تتداخل
- لا نجعل الشاشات المتوسطة تنهار بسرعة

### السلوك المتوقع

- على desktop: side-by-side rows عندما يكون ذلك منطقيًا
- على tablet: collapse محسوب
- على mobile: عمود واحد عند الحاجة فقط

### قاعدة مهمة

إذا كان المستخدم طلب عنصرين “جنب بعض”، لا يكفي `span-6`;  
أحيانًا يجب عمل wrapper row مخصص حتى نضمن ثباتهما.

## 16. أسلوب البرمجة والتنظيم

### المبدأ الصحيح

- class للشكل
- `data-*` للسلوك
- عدم ربط JavaScript فقط بأسماء الكلاسات الشكلية

### الأفضلية الحالية

الأكثر نضجًا تنظيميًا:

- `notifications center`
- `dashboard`

لأنها تستخدم:

- CSS منفصل
- JS منفصل
- partials/components
- data hooks

### قاعدة إلزامية

أي صفحة كبيرة أو معقدة يجب أن تكون بهذا الشكل:

- `app/templates/page_name.html`
- `app/static/css/page_name.css`
- `app/static/js/page_name.js`

### ممنوع

- تكديس CSS طويل داخل القالب بدون سبب
- تكديس JS طويل داخل القالب بدون سبب
- ربط السلوك عبر class شكلي فقط

## 17. الصفحة المرجعية المعمارية

### بصريًا

أفضل مرجعين بصريين:

- `dashboard`
- `statistics`

### معماريًا

أفضل مرجع تنظيمي:

- `notifications center`

### القاعدة العملية

إذا كنا نبني صفحة جديدة:

- نستلهم الشكل من `dashboard/statistics`
- ونستلهم البنية البرمجية من `notifications center`

## 18. سلوك الـ Hover والحركة

الحركة في المشروع subtle وليست استعراضية:

- `translateY(-1px)` أو `translateY(-3px)`
- shadow يزيد قليلًا
- pulse dots في badges الحية
- transitions قصيرة وناعمة

### ممنوع

- أنيميشن مزعج
- bounce
- تأثيرات صاخبة

## 19. الترجمة واللغة

المشروع عربي أولًا.

### القواعد

- نقلل الإنجليزي قدر الإمكان في النسخة العربية
- نترجم كل ما يمكن ترجمته بشكل طبيعي
- نبتعد عن المصطلحات الركيكة
- إذا كان المصطلح الإنجليزي ضروريًا، نستخدمه بحذر

### معيار الجودة

- النص العربي يجب أن يبدو وكأنه كُتب أصلًا بالعربية
- لا مجرد ترجمة حرفية

## 20. قواعد إلزامية عند أي تعديل جديد

قبل أي تعديل UI أو frontend:

1. راجع هذا الملف
2. حدّد الصفحة المرجعية الأقرب
3. التزم بـ:
   - نفس spacing rhythm
   - نفس typography hierarchy
   - نفس card language
   - نفس background softness
   - نفس scroll handling للقوائم الطويلة
4. لا تُدخل ثيم جديد غريب
5. لا تكسر RTL
6. لا تجعل الكرت يتمدد حسب النص
7. إذا الصفحة كبيرة: افصل CSS/JS

## 21. الصفحات التي بُني عليها هذا المرجع

تم استخلاص هذا الـ Playbook من:

- `/dashboard`
- `/live-data`
- `/reports`
- `/statistics`
- `/notifications/center`

## 22. الخلاصة التنفيذية

هذا الملف هو المرجع الرسمي لأي:

- redesign
- polish
- layout cleanup
- spacing fix
- card refactor
- list/table scroll handling
- section hierarchy improvement

أي واجهة جديدة أو مطورة يجب أن تبدو وكأنها ابنة طبيعية لهذه الصفحات، لا صفحة دخيلة على المشروع.

## 23. قواعد التوازن البصري المضافة بعد صفحة الأجهزة

هذه القواعد أصبحت إلزامية بعد مراجعة `/devices/manage`:

- لا نسمح للعمود الجانبي أن يفرض ارتفاعًا مبالغًا فيه على القسم الرئيسي
- أي `main grid` فيه عمود رئيسي + عمود جانبي يجب أن يمنع التمدد العمودي غير المنطقي
- الأقسام الثانوية لا يجوز أن تبدو أهم من القسم الرئيسي
- إذا كان المحتوى الرئيسي قليلًا، لا نترك الحاوية الرئيسية ممتدة لمسافة كبيرة فارغة
- الـ placeholder cards مثل “إضافة عنصر جديد” يجب أن تكون compact، لا أن تأخذ وزن بطاقة بيانات حقيقية
- القوائم المساندة الطويلة في العمود الجانبي يجب أن تكون أقصر من المحتوى الرئيسي وأن تعمل داخل `scroll`
- لا نكرر نفس CTA الكبير أكثر من مرة داخل نفس المشهد إلا إذا كان هناك سبب وظيفي قوي جدًا

### مضادات يجب تجنبها نهائيًا

- `sidebar card stack` أطول وأكثر هيمنة من المحتوى الرئيسي
- main card فارغ طويل فقط لأن side column أطول
- تكرار زر الإضافة في الهيرو ثم داخل نفس section ثم داخل placeholder card
- قسم مساعد مثل “التكاملات المتاحة” يسرق الانتباه من القسم الأساسي مثل “أسطول الأجهزة”

## 24. Device Hub Rules

- The devices page should behave as a hub, not a long open form.
- Keep the default layout focused on:
  - hero
  - summary cards
  - support sidebar
  - fleet cards
- Add-device forms should open in a drawer or a clearly isolated surface, not stretch the full page by default.
- Long integration catalogs must stay inside an internal scroll panel.
- Device cards and add-device cards must use the same top accent-line treatment used by the reference stat cards.
- Main sections need explicit visible spacing between them; do not rely only on parent gap when the visual separation is weak.
