# 🔄 ملف استكمال العمل — SolarDeye Redesign Project

> **التعليمات للمحادثة الجديدة:** اقرأ هذا الملف بالكامل قبل البدء.
> المشروع: Flask + Jinja2 — منصة طاقة شمسية لإدارة الإنفرترات.

---

## 🎯 السياق العام

تمت إعادة تصميم شاملة للمنصة عبر **5 جلسات متتالية**:
- **الجلسة 1:** تنظيف الكود + إعادة تصميم 12 صفحة إدارية
- **الجلسة 2:** صفحات Plans + Plans-edit مع رؤى ذكية + توحيد التصميم
- **الجلسة 3:** إعادة تصميم 11 صفحة للمشترك + portal/support
- **الجلسة 4:** تطوير صفحة `/admin/finance` بالكامل (محاسبة متقدمة)
- **الجلسة 5 (الحالية):** إعادة تصميم admin/finance بالكامل (v4) + 4 ميزات جديدة

---

## ✅ الصفحات المنجزة (إعادة تصميم من الصفر)

### إدارية (12)
- `/admin/integrations` — مركز التكاملات
- `/admin/devices` — أسطول الأجهزة
- `/admin/plans` — قائمة الباقات
- `/admin/plans/<id>/edit` — تحرير باقة
- `/admin/finance` — **دفتر المالية (مُعاد بناؤه بالكامل في الجلسة 4)**
- `/admin/services-health` — صحة الخدمات
- `/admin/roles` — الأدوار والصلاحيات
- `/admin/activity-log` — سجل العمليات
- `/admin/system-logs` — سجلات النظام
- `/admin/backups` — النسخ الاحتياطية
- `/admin/platform-review` — مراجعة المنصة
- `/api/v1/docs` — وثائق API الموبايل

### مشتركين (11)
- `/devices/manage`, `/account/profile`, `/onboarding`, `/account/subscription`
- `/statistics`, `/reports`, `/live-data`, `/loads`
- `/notifications`, `/channels`, `/portal/support`

---

## 💰 admin/finance — تفاصيل الجلسة 4

### الملفات المعدّلة (كلها في solardeya/ وsolardeya/solardeye/)

| الملف | الحالة | ملاحظات |
|---|---|---|
| `app/blueprints/billing.py` | ✅ مكتمل (~886 سطر) | لا يحتاج ريستارت سيرفر |
| `app/templates/admin_finance.html` | ✅ مكتمل (~754 سطر) | يُحدَّث بدون ريستارت |
| `app/static/css/admin_finance_v3.css` | ✅ مكتمل (~787 سطر) | v442-20260506 |
| `app/config.py` | ✅ `TEMPLATES_AUTO_RELOAD = True` مضاف | |

### هيكل الصفحة (من فوق لتحت)
```
Hero + KPI Pills
Period Filter Bar (الكل/اليوم/الأسبوع/الشهر/السنة/مخصص)
KPI Strip (6 بطاقات): إيداعات / إيراد مكتسب / مصاريف / صافي ر&خ / تدفق نقدي / مشتركين
─────────────────────────────────────
| ملخص الأرباح والخسائر | تصدير PDF (4 تبويبات) |
─────────────────────────────────────
الرسم البياني الشهري (full width)
فورم تسجيل حركة محاسبية (full width)
تحليل الفئات (bars)
دفتر الأستاذ (جدول + pagination 20/page + بحث + فلتر)
محافظ المشتركين (pagination 10/page + بحث)
```

### FINANCE_CATEGORIES (billing.py سطر 409)
```python
# Customer Revenue (account='revenue', type='debit')
'subscription', 'renewal', 'sms', 'extra_service', 'setup_fee', 'other_income'

# Customer Liabilities (account='liability', type='credit')
'customer_deposit', 'wallet_adjustment'

# Refunds (account='refund', type='debit')
'refund'

# Company Expenses (account='expense', type='debit')
'hosting', 'development', 'maintenance', 'salary', 'admin_salary',
'vendor_payment', 'marketing', 'tools', 'taxes', 'other_expense'
```

### منطق حقل المشترك (JS في admin_finance.html)
```javascript
var FIN_NO_TENANT = ['operating_expense','salary','vendor_payment'];
var FIN_OPT_TENANT = ['other_income'];
// customer_deposit, service_charge, refund → tenant REQUIRED + visible
// operating_expense, salary, vendor_payment → tenant HIDDEN
// other_income → tenant optional
```
الباكند: إذا لم يُرسل tenant_id → يُعيّن `_finance_company_tenant()` تلقائياً

### تصدير PDF (billing.py سطر 783)
```python
mode = request.args.get('mode')  # month | quarter | range | year
# Params: month/year, quarter/year, from_date/to_date, year
# Content flags: inc_summary, inc_ledger, inc_category, inc_monthly
# Filename: solardeya_accounting_{tag}.pdf
```

### متغيرات render_template (billing.py ~سطر 740-780)
```python
rows, deposits_total, earned_revenue, refunds_total, operating_expenses,
net_profit, cash_in, cash_out, cash_net, customer_liability,
period, period_start, period_end, from_date, to_date,
monthly_data, max_monthly,   # monthly_data items: {label, credit, debit, net, deposits, refunds}
category_breakdown,          # items: {category, label_ar, label_en, icon, color, credit, debit, total}
FINANCE_CATEGORIES,
plan_breakdown, total_mrr, max_plan_rev,
active_sub_count, trial_sub_count, tenant_count,
recurring_entries, recurring_monthly, recurring_count,
top_tenants, tenants,        # tenants للـ dropdown، top_tenants للمحافظ
daily_stats, weekly_stats, monthly_stats, yearly_stats,
format_local, cur_year, now_month, now_year,
mrr, net_balance, total_revenue
```

### CSS Classes الجديدة (admin_finance_v3.css)
```
fin3-entry-form/grid/field/label/input/actions  → فورم التسجيل
fin3-pl-table/section-hdr/subtotal/net/num      → جدول ر&خ
fin3-table-header/controls/search-input         → header الجدول
fin3-filter-btns/filter-btn                     → أزرار الفلتر
fin3-badge-type/type-credit/type-debit          → badges النوع
fin3-cat-pill/cat-grid/cat-row/cat-icon         → فئات الجدول
fin3-wallet-row/wallet-avatar/wallet-info        → محافظ المشتركين
fin3-export-tabs/tab/form/quick/qbtn            → لوحة PDF Export
fin3-pagination/page-info/page-btns/page-btn    → pagination
fin3-submit-btn                                  → زر الترحيل (أخضر)
```

### Paginator JS (نهاية admin_finance.html)
```javascript
// finPager  — ledger table, 20/page
// wPager    — wallet list, 10/page
// finFilter(acc, btn) — all/revenue/liability/expense/refund
// finDoSearch(val)    — بحث في الجدول
// walletDoSearch(val) — بحث في المحافظ
// switchExport(mode, btn) — PDF tabs
// setMonth/setQuarter/setRangeQuick — PDF quick buttons
```

---

## 📁 الملفات المهمة

### CSS:
- `app/static/css/style.css` — نظام التلميحات + pagination + قواعد عامة
- `app/static/css/unified_hero_v1.css` — Hero موحّد (`.hu-hero`)
- `app/static/css/subscriber_v3.css` — مشترك بين صفحات المشتركين
- `app/static/css/admin_finance_v3.css` — صفحة المالية (v442)
- `app/static/css/admin_devices_center_v2.css`, `admin_plans_v2.css` — صفحات أخرى

### JavaScript:
- `app/static/js/help_tooltip_v1.js` — مولّد علامات `?` التلقائي
- `app/static/js/table_paginate_v1.js` — pagination تلقائي للجداول
- `app/static/js/sidebar_rebuild_v11.js` — الـ sidebar

### Python:
- `app/blueprints/billing.py` — كل منطق المالية + subscription
- `app/models.py` — WalletLedger: tenant_id, entry_type, amount, currency, note, reference, category, is_recurring, recurring_period
- `app/__init__.py` — migration يضيف columns الجديدة عند أول تشغيل
- `app/config.py` — TEMPLATES_AUTO_RELOAD=True

---

## ⚠️ مشكلات معروفة ومحلولة

### 1. اللينتر يُقطّع الملفات
**الحل الموثوق:** استخدم Python script للكتابة:
```python
path = '/sessions/.../mnt/solardeya/app/templates/file.html'
content = open(path).read()
content = content.replace(old, new)
open(path, 'w').write(content)
```
ثم تحقق: `python3 -c "from jinja2 import Environment, FileSystemLoader; env=Environment(loader=FileSystemLoader('app/templates')); env.parse(open('app/templates/file.html').read()); print('OK')"`

### 2. debug=False → لا يعيد تحميل Python تلقائياً
- HTML/CSS يتحدث تلقائياً (`TEMPLATES_AUTO_RELOAD=True`)
- Python (billing.py, models.py) يحتاج **ريستارت السيرفر**

### 3. Dual sync مطلوب
كل تعديل يجب sync إلى مسارين:
```bash
cp solardeya/app/X solardeya/solardeye/app/X
```

### 4. `format_local` lambda مطلوب
الراوتس التي فيها `format_local(...)` في القالب:
```python
format_local=lambda dt: format_local_datetime(dt, current_app.config['LOCAL_TIMEZONE'])
```

### 5. category_breakdown items structure
```python
{'category': key, 'label_ar': ..., 'label_en': ..., 'icon': ..., 'color': ...,
 'credit': float, 'debit': float, 'total': float}
```

---

## 🔜 ما يمكن تحسينه لاحقاً

- **صفحة admin/finance:** إضافة رسم بياني مقارنة سنوية (year-over-year)
- **صفحة admin/finance:** ربط الحركات التلقائية من الاشتراكات مباشرة بالـ revenue account
- **الـ chart الشهري:** إضافة tooltip عند hover على الأعمدة
- **PDF Export:** إضافة logo الشركة في رأس التقرير
- **i18n موحّد:** نقل النصوص لملف ترجمة مركزي بدلاً من inline
- **اختبار ضغط:** pagination مع > 500 حركة
- **مراجعة نصوص العربية** من قِبل الإدارة

---

## 🎯 كيف تكمل في المحادثة الجديدة

```
أنا أعمل على مشروع SolarDeye.
اقرأ C:\Users\Ahmad J Ahmad\Desktop\solardeya\CONTINUATION.md
لمعرفة كل ما تم. ثم نكمل من:
[اذكر هنا الميزة أو الصفحة الجديدة]
```

---

## 📊 إحصاءات

- **23 صفحة** أُعيد تصميمها
- **4 جلسات** عمل
- **8+ ملفات CSS** جديدة
- **3 ملفات JS** جديدة
- **نظام محاسبة كامل** مع 20+ فئة، PDF export متعدد الأوضاع، pagination، فلتر، بحث

---

> آخر تحديث: 2026-05-06 — الجلسة الخامسة v5.1 (Pro Entry Section: payment methods + file upload + smart help panel + keyboard shortcuts)

---

## 🚀 الجلسة الخامسة — تفاصيل

### الملفات المعدّلة/المُنشأة

| الملف | الحالة | ملاحظات |
|---|---|---|
| `app/static/css/admin_finance_v4.css` | ✅ جديد (~28KB، 770 سطر) | prefix: `.fin4-*` |
| `app/templates/admin_finance.html` | ✅ معاد بناؤها (~52KB، 888 سطر) | يستخدم Chart.js 4.4 من CDN |
| `app/blueprints/billing.py` | ✅ مُحدَّث (~898 سطر) | YoY data + logo header + ledger hook |
| `app/services/subscriptions.py` | ✅ مُحدَّث (~155 سطر) | `_create_subscription_ledger_entry` |

### الميزات الأربع المُنفَّذة

**1. Tooltip تفاعلي للرسم الشهري** (Chart.js external tooltip):
- يعرض: الإيرادات + المصاريف + الإيداعات + الاستردادات + الصافي
- تصميم glassmorphism (rgba blur)، arrow pointer
- بيانات من `window.FIN4.monthly` (مُمرَّرة من Jinja)

**2. رسم Year-over-Year** (line chart بـ tension 0.35):
- خط متصل للسنة الحالية (filled gradient) + خط متقطع للسابقة
- 12 نقطة (يناير → ديسمبر)
- tooltip يحسب الفرق + النسبة المئوية بسهم ▲/▼
- toggle button في `.fin4-chart-toolbar` يبدّل بين monthly و yoy
- البيانات: `yoy_labels`, `yoy_current`, `yoy_previous` من billing.py

**3. Logo الشركة في PDF**:
- Logo برمجي بـ reportlab Drawing primitives (شمس + 8 أشعة + 'SD' monogram)
- 3-column header table: logo / company info / report meta
- Document number: `SD-{filename_tag}`
- Background `#f8fafc` + bottom border `#0f172a` (2px)

**4. ربط الاشتراكات بالحركات التلقائية**:
- `_create_subscription_ledger_entry()` في `subscriptions.py`
- يُستدعى من `activate_tenant_subscription` (تفعيل) و`admin_subscriber_extend` (تجديد)
- Reference format: `SUB-{tenant_id}-{sub_id}` (تفعيل) أو `REN-{tenant_id}-{sub_id}` (تجديد)
- Category: `subscription` أو `renewal`، entry_type: `debit`، account: `revenue`
- Badge `⚡ AUTO` يظهر في جدول الـ ledger للحركات المولّدة تلقائياً
- Safe-fail: لا يكسر تفعيل الاشتراك إذا فشل الإنشاء

### CSS Tokens الجديدة (admin_finance_v4.css)

```css
:root {
  --fin4-bg, --fin4-panel, --fin4-border, --fin4-border-soft
  --fin4-ink, --fin4-ink-soft, --fin4-muted
  --fin4-blue/green/red/teal/purple/amber/pink/slate
  --fin4-shadow, --fin4-shadow-md, --fin4-shadow-lg
  --fin4-radius, --fin4-radius-sm, --fin4-radius-lg
}
```

### الكلاسات الرئيسية

```
fin4-hero (gradient dark + glow effects)
fin4-sticky-bar (sticky filter, top:0, blur backdrop)
fin4-kpi-grid + fin4-kpi.{blue|green|red|teal|purple|amber}
fin4-row-2 (responsive 1fr 1fr → 1fr at 980px)
fin4-pl-table + fin4-pl-{section-hdr|subtotal|net|profit|loss|num.green/red}
fin4-export-tabs/tab/form/quick/qbtn/btn (PDF tabs)
fin4-chart-canvas-wrap (h:320px desktop / 260px mobile)
fin4-chart-toolbar/toggle (monthly|yoy)
fin4-cat-grid/row/icon/info/bar/amt
fin4-table/row/badge-type/cat-pill/auto-link
fin4-pagination/page-btn (active state in blue)
fin4-wallet-list/row/avatar/info/bal
fin4-collapsible/-body (collapse panels)
fin4-tooltip/-title/-row/-key/-net (Chart.js external)
```

### JavaScript المضاف (نهاية admin_finance.html)

```javascript
window.FIN4 = { isEn, monthly[], yoy: {labels, current, previous, currentYear, previousYear} }
Paginator class (ledger 20/page, wallets 12/page)
finFilter / finDoSearch / walletDoSearch
finUpdateForm / finSyncCategory (smart tenant field)
switchExport / setMonth / setQuarter / setRangeQuick (PDF tabs)
toggleCollapse (collapsible panels)
externalMonthlyTooltip / externalYoyTooltip (Chart.js)
buildMonthlyConfig / buildYoyConfig
window.switchChart(view, btn)
```

### تنبيهات

- `admin_finance_v3.css` لا يُحمَّل بعد الآن (احتفظ به للتراجع)
- يحتاج ريستارت السيرفر لتطبيق تغييرات `billing.py` و `subscriptions.py`
- HTML/CSS تتحدث تلقائياً بفضل `TEMPLATES_AUTO_RELOAD=True`
- Chart.js 4.4 من CDN (`cdn.jsdelivr.net`) — يحتاج اتصال إنترنت أو local copy

---

## 🚀 الجلسة الخامسة v5.1 — قسم الإدخال الاحترافي

### الهدف
رفع قسم "تسجيل حركة محاسبية" إلى مستوى محاسبي متقدم: 10 طرق دفع/استلام، رفع فواتير، لوحة شروحات ذكية متغيّرة حسب نوع العملية، اختصارات لوحة المفاتيح.

### الملفات المعدّلة

| الملف | تغيير |
|---|---|
| `app/models.py` | `WalletLedger`: + `payment_method`, `attachment_path`, `attachment_name` |
| `app/__init__.py` | migration: 3 columns جديدة في `wallet_ledger` |
| `app/blueprints/billing.py` | + `PAYMENT_METHODS` list (10 methods) + file upload handler |
| `app/templates/admin_finance.html` | إعادة هيكلة قسم الإدخال (2-col: form + help panel) |
| `app/static/css/admin_finance_v4.css` | + 320 سطر: `.fin4-pay-grid`, `.fin4-file-zone`, `.fin4-help-panel`, etc. |
| `app/static/uploads/finance/` | مجلد جديد لتخزين المرفقات |

### PAYMENT_METHODS (billing.py)
```python
PAYMENT_METHODS = [
    {'key': 'cash',          'icon': '💵', 'color': '#10b981'},  # نقد
    {'key': 'bank_transfer', 'icon': '🏦', 'color': '#2563eb'},  # تحويل بنكي
    {'key': 'visa',          'icon': '💳', 'color': '#1a1f71'},  # Visa
    {'key': 'mastercard',    'icon': '💳', 'color': '#eb001b'},  # Mastercard
    {'key': 'paypal',        'icon': '🅿', 'color': '#003087'},   # PayPal
    {'key': 'bank_card',     'icon': '💳', 'color': '#0ea5e9'},  # بطاقة بنكية
    {'key': 'check',         'icon': '📃', 'color': '#7c3aed'},  # شيك
    {'key': 'crypto',        'icon': '₿',  'color': '#f7931a'},   # Crypto
    {'key': 'wallet',        'icon': '📱', 'color': '#14b8a6'},  # E-Wallet
    {'key': 'other',         'icon': '⚙', 'color': '#64748b'},   # أخرى
]
```

### رفع الفواتير (file upload)
- POST handler يستقبل `request.files.get('attachment')` (form بـ `enctype="multipart/form-data"`)
- whitelist: `.png .jpg .jpeg .gif .webp .pdf .heic .bmp`
- Max size: 10 MB (تحقق client-side)
- اسم الملف: `{YYYYMMDD_HHMMSS}_{uuid8}{ext}` لتجنب التضارب
- يُحفظ في: `app/static/uploads/finance/`
- يُسجَّل في `WalletLedger.attachment_path` (relative) + `attachment_name` (original)
- يظهر في الـ ledger بـ link `📎 عرض` يفتح الملف في tab جديد

### Smart Help Panel
- Sticky على اليمين (top: 88px)، scrollable داخلياً
- 7 blocks (`data-help`): customer_deposit, service_charge, refund, operating_expense, salary, vendor_payment, other_income + default
- كل block: title + numbered steps + best-practice tip
- تتغير تلقائياً عند تبديل `operation_type` (في `finUpdateForm()`)
- قسم Keyboard Shortcuts في الأسفل

### الاختصارات
```
Ctrl+Enter  → ترحيل الحركة (submit)
Ctrl+M      → focus حقل المبلغ + select
Ctrl+U      → فتح اختيار الملف
Esc         → reset النموذج (مع تأكيد)
```

### CSS Classes الجديدة
```
.fin4-entry-pro                   → grid 1.6fr 1fr (>980px)
.fin4-entry-main                  → form column
.fin4-section-head + -icon        → numbered section dividers
.fin4-pay-grid + .fin4-pay-card   → radio cards for payment method
.fin4-pay-card.selected           → blue glow + checkmark
.fin4-file-zone + .has-file       → drop zone (dashed → solid green)
.fin4-file-icon/-text/-sub/-preview
.fin4-help-panel                  → sticky aside with linear gradient bg
.fin4-help-head + -icon (yellow)
.fin4-help-block (.active)        → switchable instruction blocks
.fin4-help-title + -steps + -tip
.fin4-shortcuts + .fin4-shortcut + .fin4-kbd
.fin4-pay-pill                    → small badge in ledger row
.fin4-attachment-link             → 📎 view link in ledger
.fin4-entry-actions-pro           → submit row with shortcut hint
.fin4-shortcut-hint               → "Ctrl+Enter to post"
```

### JS الجديد (admin_finance.html)
```javascript
finSelectPay(card)     // toggle radio cards visually
finFileChange(input)   // update file zone UI + size validation
// finUpdateForm extended → switch help panel block
// keyboard shortcut listener (Ctrl+Enter, Ctrl+M, Ctrl+U, Esc)
```

### تنبيه ريستارت
- **تغييرات Python (models, billing, init):** تحتاج ريستارت السيرفر
- **migration:** يُطبَّق تلقائياً عند أول تشغيل (يضيف 3 أعمدة لـ `wallet_ledger`)
- **CSS/HTML:** تتحدث تلقائياً

