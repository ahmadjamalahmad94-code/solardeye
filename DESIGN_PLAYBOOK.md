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
- Text secondary (muted): `#4a5b78` — مُحدَّث لاجتياز WCAG AA على الأبيض (~6.3:1)
- Text soft: `#1f2a44`
- Border: `#e3eaf6` — فواصل خفيفة
- Border stronger: `#bcc8df` — حدود الإدخالات والفواصل المرئية والـ hover
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
  - `22px clamp(14px, 2.4vw, 28px) 56px`
- المسافة بين الأقسام الرئيسية: **`26px`** (موحَّدة وإلزامية)

### على مستوى الكروت

- Padding داخلي متكرر:
  - `18px 20px`
  - `20px 22px`
- Gap داخلي بين عناصر الكرت:
  - `8px` / `10px` / `12px` / `16px`

### ⚠️ القاعدة الإلزامية للمسافات بين الأقسام

> لا تعتمد على `flex gap` بين الأقسام الرئيسية للصفحة. القواعد العامة في `style.css` (مثل `.app-main > *` و `.content-area > *`) تكسر الـ flex gap بشكل متكرر، فتلتصق الأقسام ببعض. الحل **إجباري ومُوحَّد**: استخدام `margin-block-start` صريح بـ `!important` على كل قسم direct child من حاوية الصفحة.

```css
.xx-page > .xx-hero    { margin: 0 !important }
.xx-page > .xx-stats   { margin: 26px 0 0 0 !important }
.xx-page > .xx-toolbar { margin: 26px 0 0 0 !important }
.xx-page > .xx-grid    { margin: 26px 0 0 0 !important }
.xx-page > section,
.xx-page > header      { margin-block-start: 26px !important }
.xx-page > :first-child{ margin-block-start: 0 !important }
```

- المسافة الموحَّدة بين الأقسام: **`26px`**
- `!important` غير قابلة للتفاوض — بدونها الـ cascade العام يكسر التصميم
- `:first-child` يُصفِّر margin-top للهيرو لئلا تظهر فجوة فارغة فوقه
- ممنوع استخدام `margin-bottom` على الأقسام — المسافة يملكها القسم التالي عبر `margin-block-start`
- لا تعتمد على `flex-gap` للأقسام top-level (للداخل-الكرت OK)

#### مبدأ بسيط:
- لا تترك الأقسام ملزقة ببعض
- الصفحة يجب أن تتنفس
- نفس مسافة `26px` تطبَّق على كل صفحة في النظام

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

## 25. صفحات المصادقة (تسجيل الدخول والتسجيل)

صفحات المصادقة تتبع نمط **stage مقسوم**: بطاقة بيضاء طويلة تحوي عمودين — `showcase` بتدرّج لوني على جانب، و `form` على الجانب الآخر. يجب أن تشعر الصفحتان (login و register) متطابقتين بصرياً تماماً.

### 25.1 إيقاع الـ hero — مسافات ثابتة لا توزيع ديناميكي

هذه القاعدة الأهم وغير البديهية:

> صفحة login تستخدم `justify-content:space-between` لأن الفورم فيها يسع 620 px. أما register فالفورم فيها ~1200 px، فلو استخدمنا `space-between` نفسها يتم توزيع الفراغ الفائض على الـ panel الجانبي وتتفكك الأقسام. الحل: نستغني عن `space-between` ونعتمد على **margin-bottom ثابت** بين الأقسام الكبرى — لتبقى الإيقاعية موحَّدة بصرف النظر عن طول الفورم.

```css
.xx-showcase{ justify-content:flex-start; gap:20px }
.xx-showcase > .xx-brand        { margin-bottom:80px }  /* فجوة قبل المحتوى */
.xx-showcase > .xx-showcase-body{ margin-bottom:60px }  /* فجوة قبل بطاقة الإحصاء */
```

النتيجة: 100 px بين اللوغو والمحتوى، 80 px بين المحتوى وبطاقة الإحصاء — مطابق لتوزيع login داخل 620 px. التدرج اللوني يملأ ما تبقى من الـ panel تلقائياً.

### 25.2 ترتيب أبناء الـ showcase

| البلوك | الكلاس | المحتوى |
|---|---|---|
| Brand | `.xx-brand` | أيقونة + اسم المنصة + سطر فرعي |
| Body  | `.xx-showcase-body` | eyebrow chip + h1 + tagline + شبكة 2×2 من المزايا |
| Stats | `.xx-stats` | بطاقة من 3 أعمدة بخلفية بيضاء شبه شفافة |

### 25.3 toggle اللغة الواحد

في صفحات المصادقة: استخدم **فقط** الـ pill العام `.xx-lang-toggle` (مثبَّت في زاوية الصفحة). لا تضع toggle ثاني داخل header الفورم — ذلك يضاعف نقاط القرار ويسرق الانتباه.

### 25.4 حقول الإدخال

```css
.xx-field-input{
  position:relative; display:flex; align-items:center;
  background:#fff; border:1px solid var(--xx-line-strong); border-radius:11px;
  padding-inline-start:38px; padding-inline-end:6px;
}
.xx-field-input:focus-within{
  border-color:var(--xx-amber);
  box-shadow:0 0 0 3px rgba(245,158,11,.18);
}
.xx-field-icon{
  position:absolute; inset-inline-start:12px; top:50%; transform:translateY(-50%);
  color:var(--xx-muted);
}
```

أيقونة الحقل تُموضع بـ `inset-inline-start` فتظهر على **اليمين** في RTL وعلى **اليسار** في LTR تلقائياً.

**اتجاه الحقل (input dir):** لا تثبّت `dir="ltr"`. اجعله ديناميكياً ليتبع لغة الصفحة:
```jinja2
<input ... dir="{{ 'ltr' if is_en else 'rtl' }}">
```
هذا يضع المؤشر في بداية الحقل البصرية بحسب اللغة. خوارزمية bidi تتعامل مع الأحرف اللاتينية المضمَّنة داخل حقل RTL تلقائياً.

### 25.5 رابط "العودة للرئيسية"

لا تضع السهم داخل نفس string النص — bidi قد يموضعه بشكل خاطئ. افصل في `<span>`:

```html
<a class="xx-back-link" href="...">
  <span class="xx-back-arrow" aria-hidden="true">{{ '←' if is_en else '→' }}</span>
  <span>{{ 'Back to home' if is_en else 'العودة للرئيسية' }}</span>
</a>
```

اتجاه السهم:
- LTR: `←` — للخلف باتجاه عكس القراءة
- RTL: `→` — للخلف باتجاه عكس قراءة العربية

أنميشن hover يحرّك السهم باتجاه "الخلف":
```css
.xx-back-link:hover .xx-back-arrow{
  transform: translateX({{ '-3px' if is_en else '3px' }})
}
```

### 25.6 زر التأكيد (Submit)

ثلاثة أبناء بهذا الترتيب: SVG أمن (قفل) → النص → سهم اتجاهي. **بدون إيموجي**.

```html
<button class="xx-submit" type="submit">
  <svg class="xx-submit-icon" .../>
  <span>{{ 'Sign in securely' if is_en else 'دخول آمن' }}</span>
  <span class="xx-submit-arrow" aria-hidden="true">{{ '→' if is_en else '←' }}</span>
</button>
```

السهم بـ `opacity:.85` افتراضياً ويصبح `1` مع `translateX(±4px)` عند hover.

### 25.7 الفاصل "أو تابع باستخدام"

استخدم flexbox، ليس `position:absolute`:
```css
.xx-divider{
  display:flex; align-items:center; gap:.75rem;
  font-size:.74rem; color:var(--xx-muted); font-weight:800;
  text-transform:uppercase; letter-spacing:.4px; margin:.4rem 0;
}
.xx-divider::before, .xx-divider::after{
  content:""; flex:1; height:1px; background:var(--xx-line-strong);
}
```

### 25.8 معالجة BiDi للنصوص المختلطة

عندما تحتوي جملة عربية على token لاتيني متبوع بفاصلة (مثل `SMS، تيليجرام`)، الفاصلة قد تظهر في الجهة الخاطئة. لفّ الـ token بـ `<bdi>`:

```jinja2
{{ ('SMS, Telegram, in-app' if is_en else '<bdi>SMS</bdi>، تيليجرام، داخل التطبيق') | safe }}
```

## 26. الـ Hero الموحَّد (.hu-* shared classes)

**اعتباراً من v95**، كل صفحات الإدارة الداخلية تستخدم نفس الـ hero الفاتح المشترك من `static/css/unified_hero_v1.css` (محمَّل تلقائياً من `base.html`). لا حاجة بعد الآن لتكرار CSS الـ hero في كل صفحة.

### الـ Markup الإلزامي

```html
<header class="hu-hero">
  <div class="hu-hero-grid">
    <div class="hu-hero-text">
      <span class="hu-eyebrow">
        <svg .../>اسم القسم
      </span>
      <h1 class="hu-h1">عنوان الصفحة</h1>
      <p class="hu-tagline">الوصف.</p>
    </div>
    <div class="hu-hero-cta">
      <a class="hu-btn hu-btn-ghost">إجراء ثانوي</a>
      <a class="hu-btn hu-btn-primary">+ إجراء رئيسي</a>
    </div>
  </div>
</header>
```

### الالتزامات البصرية المقفلة

| الخاصية | القيمة |
|---|---|
| `border-radius` | `30px` |
| `padding` | `32px clamp(28px, 3.2vw, 44px) 36px` |
| Gradient | فاتح: `#7fb1e6 → #f8d7b6` |
| لون العنوان | `#1d4ed8` (أزرق مشبع) |
| لون eyebrow | `#1d4ed8` (داخل pill أبيض) |
| لون tagline | `#334155` |
| الزخارف | نقاط أعلى-البداية + موجة SVG في الأسفل |

### أنواع الأزرار

- `.hu-btn-primary` — تدرج أمبر، نص كحلي (الإجراء الرئيسي)
- `.hu-btn-ghost` — أبيض، نص كحلي ناعم (إجراء ثانوي)
- `.hu-btn-success` — تدرج أخضر
- `.hu-btn-danger` — تدرج وردي

كل الأنواع تتغلب على القواعد العامة لـ `<a>` بـ `body main.app-main .hu-btn-* { color: ... !important }`.

### قائمة فحص الترحيل من hero قديم

1. استبدل `<header class="xx-hero">` بـ `<header class="hu-hero xx-hero">` (للحفاظ على أي layout قائم)
2. استبدل `<h1>` بـ `<h1 class="hu-h1">`
3. استبدل tagline `<p>` بـ `<p class="hu-tagline">`
4. استبدل `<span class="xx-eyebrow">` بـ `<span class="hu-eyebrow">` مع أيقونة SVG بداخله
5. استبدل CTA buttons من `xx-btn-*` إلى `hu-btn-*`
6. احذف CSS المحلي للـ hero/eyebrow/tagline/buttons من `<style>` الصفحة — صار تابعاً للملف الموحَّد

### متى لا تستخدم الـ Hero الموحَّد

- صفحات marketing/landing عامة (لها هوية بصرية مختلفة)
- صفحات الـ public site
- الـ admin/internal فقط هي اللي تستخدم النمط الموحَّد
