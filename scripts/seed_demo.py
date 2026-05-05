"""Seed demo data for SolarDeye — wipe existing tickets/messages then
populate fake subscribers, admins, tickets, messages, and wallet entries.

Run from project root:
    python -m scripts.seed_demo
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta

# Make project root importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import (
    AppUser,
    TenantAccount,
    TenantSubscription,
    SubscriptionPlan,
    InternalMailThread,
    InternalMailMessage,
    SupportTicket,
    SupportTicketMessage,
    SupportCase,
    SupportAttachment,
    SupportAuditLog,
    WalletLedger,
    AdminActivityLog,
)

# ─────────────────────────────────────────────────────────────────────
# Fake data pools
# ─────────────────────────────────────────────────────────────────────
FIRST_NAMES = [
    'أحمد', 'محمد', 'علاء', 'يوسف', 'إبراهيم', 'خالد', 'سامي', 'عمر',
    'كريم', 'حسن', 'مروان', 'ربيع', 'هاني', 'فادي', 'مازن', 'بشار',
    'وليد', 'طارق', 'جمال', 'أنس', 'ليلى', 'فاطمة', 'سارة', 'هدى',
    'نور', 'مريم', 'دانا', 'لينا', 'رنا', 'هبة',
]
LAST_NAMES = [
    'أحمد', 'علي', 'حسين', 'الخطيب', 'النجار', 'العلي', 'سعيد', 'الزعبي',
    'البرغوثي', 'القيسي', 'الحرباوي', 'الحوراني', 'العمري', 'الشامي',
    'الصالح', 'البلوي', 'الخليل', 'العزيز', 'العباسي', 'الراوي',
]
CITIES = ['رام الله', 'الخليل', 'نابلس', 'بيت لحم', 'جنين', 'طولكرم', 'قلقيلية', 'أريحا', 'غزة', 'بيت ساحور']
COUNTRIES = ['PS', 'JO', 'SA', 'AE', 'EG', 'LB']
COUNTRY_DIALS = {'PS': '+970', 'JO': '+962', 'SA': '+966', 'AE': '+971', 'EG': '+20', 'LB': '+961'}

TICKET_SUBJECTS_BY_CATEGORY = {
    'technical': [
        'الجهاز لا يستجيب لأوامر المزامنة',
        'البيانات غير محدّثة من الأمس',
        'مشكلة في عدّاد الإنتاج اليومي',
        'الإشعارات لا تصل على Telegram',
        'لا يمكنني تسجيل الدخول من تطبيق الموبايل',
        'القراءات تظهر صفر بشكل مفاجئ',
    ],
    'billing': [
        'استفسار عن فاتورة الاشتراك',
        'لم أستلم فاتورة الشهر الماضي',
        'طلب تعديل طريقة الدفع',
        'استرداد دفعة مكررة',
    ],
    'feature_request': [
        'اقتراح إضافة تقرير شهري بصيغة PDF',
        'طلب دعم لغة تركية في التطبيق',
        'إضافة تنبيه عند انخفاض الإنتاج',
    ],
    'general': [
        'استفسار عن خطط الاشتراك',
        'سؤال عن قيود حساب SMS',
        'كيفية إضافة جهاز جديد',
        'تحديث بيانات الحساب',
    ],
}

MAIL_SUBJECTS = [
    'متابعة طلب الترقية',
    'تأكيد استلام الدفعة',
    'تحديث تفاصيل الاشتراك',
    'تذكير بانتهاء الفترة التجريبية',
    'استفسار عن تقرير الإنتاج',
    'طلب إضافة جهاز جديد للحساب',
    'مشكلة في الإشعارات اليومية',
    'تأكيد تفعيل خدمة Telegram',
]

PRIORITIES = ['low', 'normal', 'high', 'urgent']
PRIORITY_WEIGHTS = [2, 5, 2, 1]   # most are normal, few urgent
STATUSES = ['open', 'assigned', 'in_progress', 'waiting_user', 'resolved', 'closed']
STATUS_WEIGHTS = [4, 3, 3, 2, 2, 1]
CATEGORIES = list(TICKET_SUBJECTS_BY_CATEGORY.keys())

USER_OPENING_LINES = [
    'السلام عليكم، أرجو المساعدة في الموضوع التالي:',
    'مرحباً، عندي استفسار حول حسابي.',
    'هاي، فيه مشكلة بسيطة محتاجة حل.',
    'أهلاً، شو رأيكم بهذي الفكرة؟',
    'مساء الخير، يا ريت تتابعوا معي:',
]
USER_BODIES = [
    'الجهاز اشتغل اليوم الصبح بشكل عادي بس بعدين توقف فجأة عن إرسال البيانات. حاولت أعمل restart وما زبط. ممكن تتأكدوا من جهتكم؟',
    'الفاتورة تظهر مبلغ زيادة ٢٠ شيكل عن الشهر السابق بدون تغيير على خطتي. أرجو المراجعة وتزويدي بتفاصيل البنود.',
    'حابب أعرف هل ممكن أضيف جهاز ثاني على نفس الحساب أم محتاج اشتراك جديد؟ وشو التكلفة؟',
    'الإشعارات على Telegram توقفت من أمس. كنت أستلمها بانتظام قبل ذلك. ما الذي تغيّر؟',
    'كيف أنزّل تقرير الشهر الماضي بصيغة PDF؟ ما لقيت الزر في لوحة التحكم.',
    'فيه عدّاد جديد ركّبتُه على المنزل، كيف أربطه بالحساب؟ هل يلزم تواصل فني معكم؟',
]
ADMIN_REPLIES = [
    'تم استلام طلبك ونحن ننظر فيه الآن. سنرد خلال ٢٤ ساعة بحد أقصى.',
    'شكراً لتواصلك. تم التحقق من المشكلة وقمنا بإعادة ضبط الجهاز عن بُعد. حاول مرة ثانية رجاءً.',
    'أهلاً بك. تم تحويل طلبك للقسم الفني المختص للمتابعة معك مباشرة.',
    'جزاك الله خيراً على ملاحظتك. تم تسجيلها كاقتراح وستراجع من فريق التطوير.',
    'تم تنفيذ المطلوب على حسابك. يمكنك التحقق من لوحة التحكم الآن.',
    'نعتذر عن الإزعاج. المشكلة من جهتنا وسيتم حلها خلال ساعات قليلة.',
]

ADMIN_ROLES = [
    ('general_manager',   'مدير عام'),
    ('assistant_manager', 'مساعد مدير'),
    ('technical_support', 'دعم فني'),
    ('finance_manager',   'مدير مالي'),
    ('marketing_manager', 'مدير تسويق'),
]


def w_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


def random_past_dt(min_days=1, max_days=60):
    return datetime.utcnow() - timedelta(
        days=random.randint(min_days, max_days),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


# ─────────────────────────────────────────────────────────────────────
# Wipe existing support data
# ─────────────────────────────────────────────────────────────────────
def wipe_support_and_finance():
    print('[wipe] Deleting existing tickets, threads, cases, attachments, audit logs, wallet entries...')
    SupportAuditLog.query.delete(synchronize_session=False)
    SupportAttachment.query.delete(synchronize_session=False)
    SupportCase.query.delete(synchronize_session=False)
    SupportTicketMessage.query.delete(synchronize_session=False)
    SupportTicket.query.delete(synchronize_session=False)
    InternalMailMessage.query.delete(synchronize_session=False)
    InternalMailThread.query.delete(synchronize_session=False)
    WalletLedger.query.delete(synchronize_session=False)
    db.session.commit()
    print('[wipe] Done.\n')


# ─────────────────────────────────────────────────────────────────────
# Create admin staff (one per role preset) with realistic usernames
# ─────────────────────────────────────────────────────────────────────
ADMIN_PROFILES = [
    # role_code, full_name, username
    ('general_manager',   'سامي عبد العزيز',  'sami.aziz'),
    ('assistant_manager', 'مروان الحسيني',    'marwan.husseini'),
    ('technical_support', 'بلال الشامي',      'bilal.shami'),
    ('finance_manager',   'هدى النجار',       'hoda.najjar'),
    ('marketing_manager', 'دانا البرغوثي',    'dana.barghouti'),
]

def ensure_admin_staff():
    print('[admins] Ensuring one admin per role with realistic profile...')
    created, kept = 0, 0
    out = []
    for role_code, full_name, username in ADMIN_PROFILES:
        existing = AppUser.query.filter_by(username=username).first()
        if existing:
            out.append(existing)
            kept += 1
            continue
        u = AppUser(
            username=username,
            password_hash=generate_password_hash('Demo@2026'),
            full_name=full_name,
            email=f'{username}@solardeye.com',
            phone_country_code='+970',
            phone_number=f'059{random.randint(1000000, 9999999)}',
            country='PS',
            city=random.choice(CITIES),
            timezone='Asia/Hebron',
            preferred_language='ar',
            role=role_code,
            is_admin=True,
            is_active=True,
            created_at=random_past_dt(60, 200),
        )
        db.session.add(u)
        db.session.flush()
        out.append(u)
        created += 1
    db.session.commit()
    print(f'[admins] Created {created} new, kept {kept} existing.\n')
    return out


# ─────────────────────────────────────────────────────────────────────
# Create 20 subscribers
# ─────────────────────────────────────────────────────────────────────
def _slugify_username(first_en, last_en, taken):
    """Produce a unique latin-letter username like ahmad.alkhatib"""
    base = f'{first_en}.{last_en}'.lower()
    candidate = base
    counter = 2
    while candidate in taken or AppUser.query.filter_by(username=candidate).first():
        candidate = f'{base}{counter}'
        counter += 1
    taken.add(candidate)
    return candidate


# Latin transliteration of names so usernames look natural
FIRST_TRANSLIT = {
    'أحمد': 'ahmad', 'محمد': 'mohammed', 'علاء': 'alaa', 'يوسف': 'yousef',
    'إبراهيم': 'ibrahim', 'خالد': 'khaled', 'سامي': 'sami', 'عمر': 'omar',
    'كريم': 'karim', 'حسن': 'hasan', 'مروان': 'marwan', 'ربيع': 'rabie',
    'هاني': 'hani', 'فادي': 'fadi', 'مازن': 'mazen', 'بشار': 'bashar',
    'وليد': 'walid', 'طارق': 'tariq', 'جمال': 'jamal', 'أنس': 'anas',
    'ليلى': 'layla', 'فاطمة': 'fatima', 'سارة': 'sara', 'هدى': 'huda',
    'نور': 'nour', 'مريم': 'maryam', 'دانا': 'dana', 'لينا': 'lina',
    'رنا': 'rana', 'هبة': 'heba',
}
LAST_TRANSLIT = {
    'أحمد': 'ahmad', 'علي': 'ali', 'حسين': 'hussein', 'الخطيب': 'alkhatib',
    'النجار': 'alnajjar', 'العلي': 'alali', 'سعيد': 'saeed', 'الزعبي': 'alzubi',
    'البرغوثي': 'barghouti', 'القيسي': 'alqaisi', 'الحرباوي': 'alhirbawi',
    'الحوراني': 'alhourani', 'العمري': 'alomari', 'الشامي': 'alshami',
    'الصالح': 'alsaleh', 'البلوي': 'albalawi', 'الخليل': 'alkhalil',
    'العزيز': 'alaziz', 'العباسي': 'alabbasi', 'الراوي': 'alrawi',
}

def create_subscribers(count=20):
    print(f'[subs] Creating {count} subscribers with realistic profiles...')
    plans = SubscriptionPlan.query.order_by(SubscriptionPlan.id.asc()).all()
    if not plans:
        print('[subs] WARNING: no SubscriptionPlan rows; skipping plan link.')
    subs = []
    used_usernames = set()
    for i in range(count):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        full = f'{first} {last}'
        country = random.choice(COUNTRIES)
        first_en = FIRST_TRANSLIT.get(first, 'user')
        last_en = LAST_TRANSLIT.get(last, str(i+1))
        username = _slugify_username(first_en, last_en, used_usernames)
        existing = AppUser.query.filter_by(username=username).first()
        if existing:
            subs.append(existing)
            continue
        u = AppUser(
            username=username,
            password_hash=generate_password_hash('Demo@2026'),
            full_name=full,
            email=f'{username}@solardeye.com',
            phone_country_code=COUNTRY_DIALS[country],
            phone_number=f'05{random.randint(10000000, 99999999)}',
            country=country,
            city=random.choice(CITIES),
            timezone='Asia/Hebron',
            preferred_language='ar',
            role='user',
            is_admin=False,
            is_active=random.random() > 0.1,  # 90% active
            created_at=random_past_dt(5, 180),
        )
        db.session.add(u)
        db.session.flush()  # get id

        # Tenant
        t = TenantAccount(
            owner_user_id=u.id,
            display_name=full,
            status='active',
            plan_id=plans[i % len(plans)].id if plans else None,
            created_at=u.created_at,
        )
        db.session.add(t)
        db.session.flush()

        # Subscription
        sub = TenantSubscription(
            tenant_id=t.id,
            plan_id=plans[i % len(plans)].id if plans else None,
            status=random.choice(['trial', 'active', 'active', 'active']),
            activation_mode='manual',
            starts_at=u.created_at,
            ends_at=u.created_at + timedelta(days=random.choice([30, 90, 180, 365])),
            trial_ends_at=u.created_at + timedelta(days=14) if random.random() < 0.3 else None,
        )
        db.session.add(sub)
        subs.append(u)

    db.session.commit()
    print(f'[subs] Done. Total subscribers in DB: {len(subs)}\n')
    return subs


# ─────────────────────────────────────────────────────────────────────
# Per subscriber: 5 tickets + 5 messages
# ─────────────────────────────────────────────────────────────────────
def create_support_data(subscribers, admins):
    print('[support] Creating tickets, threads, messages, cases for each subscriber...')
    tickets_made = threads_made = msgs_made = cases_made = 0

    for sub in subscribers:
        tenant = TenantAccount.query.filter_by(owner_user_id=sub.id).first()
        if not tenant:
            continue

        # ── 5 tickets ──
        for j in range(5):
            cat = random.choice(CATEGORIES)
            subject = random.choice(TICKET_SUBJECTS_BY_CATEGORY[cat])
            priority = w_choice(PRIORITIES, PRIORITY_WEIGHTS)
            status = w_choice(STATUSES, STATUS_WEIGHTS)
            assigned = random.choice(admins) if random.random() > 0.25 else None
            created = random_past_dt(1, 45)
            ticket = SupportTicket(
                tenant_id=tenant.id,
                opened_by_user_id=sub.id,
                assigned_admin_user_id=assigned.id if assigned else None,
                subject=subject,
                category=cat,
                priority=priority,
                status=status,
                created_at=created,
                updated_at=created,
            )
            db.session.add(ticket)
            db.session.flush()

            # First message (from user)
            m1 = SupportTicketMessage(
                ticket_id=ticket.id,
                sender_user_id=sub.id,
                sender_scope='user',
                body=random.choice(USER_OPENING_LINES) + '\n\n' + random.choice(USER_BODIES),
                created_at=created,
            )
            db.session.add(m1)
            msgs_made += 1
            last_reply = created

            # 1–3 admin replies
            n_replies = random.randint(1, 3)
            for r in range(n_replies):
                if not assigned:
                    break
                reply_at = last_reply + timedelta(hours=random.randint(1, 36))
                if reply_at > datetime.utcnow():
                    break
                m = SupportTicketMessage(
                    ticket_id=ticket.id,
                    sender_user_id=assigned.id,
                    sender_scope='admin',
                    body=random.choice(ADMIN_REPLIES),
                    created_at=reply_at,
                )
                db.session.add(m)
                msgs_made += 1
                last_reply = reply_at

            ticket.last_reply_at = last_reply
            ticket.updated_at = last_reply

            # SupportCase mirror
            db.session.add(SupportCase(
                case_type='ticket',
                source_id=ticket.id,
                tenant_id=tenant.id,
                user_id=sub.id,
                assigned_admin_user_id=ticket.assigned_admin_user_id,
                subject=ticket.subject,
                priority=ticket.priority,
                status=ticket.status,
                last_reply_at=last_reply,
                last_reply_by='admin' if n_replies and assigned else 'user',
                created_at=created,
                updated_at=last_reply,
            ))
            tickets_made += 1
            cases_made += 1

        # ── 5 mail threads ──
        for j in range(5):
            subject = random.choice(MAIL_SUBJECTS)
            priority = w_choice(PRIORITIES, PRIORITY_WEIGHTS)
            status = w_choice(STATUSES, STATUS_WEIGHTS)
            assigned = random.choice(admins) if random.random() > 0.3 else None
            created = random_past_dt(1, 60)
            thread = InternalMailThread(
                tenant_id=tenant.id,
                created_by_user_id=sub.id,
                assigned_admin_user_id=assigned.id if assigned else None,
                subject=subject,
                category='general',
                priority=priority,
                status=status,
                created_at=created,
                updated_at=created,
            )
            db.session.add(thread)
            db.session.flush()

            # First message from subscriber
            m1 = InternalMailMessage(
                thread_id=thread.id,
                sender_user_id=sub.id,
                sender_scope='user',
                body=random.choice(USER_OPENING_LINES) + '\n\n' + random.choice(USER_BODIES),
                created_at=created,
            )
            db.session.add(m1)
            msgs_made += 1
            last_reply = created

            # 1–2 admin replies
            n_replies = random.randint(0, 2)
            for r in range(n_replies):
                if not assigned:
                    break
                reply_at = last_reply + timedelta(hours=random.randint(2, 48))
                if reply_at > datetime.utcnow():
                    break
                m = InternalMailMessage(
                    thread_id=thread.id,
                    sender_user_id=assigned.id,
                    sender_scope='admin',
                    body=random.choice(ADMIN_REPLIES),
                    created_at=reply_at,
                )
                db.session.add(m)
                msgs_made += 1
                last_reply = reply_at

            thread.last_reply_at = last_reply
            thread.updated_at = last_reply

            db.session.add(SupportCase(
                case_type='message',
                source_id=thread.id,
                tenant_id=tenant.id,
                user_id=sub.id,
                assigned_admin_user_id=thread.assigned_admin_user_id,
                subject=thread.subject,
                priority=thread.priority,
                status=thread.status,
                last_reply_at=last_reply,
                last_reply_by='admin' if n_replies and assigned else 'user',
                created_at=created,
                updated_at=last_reply,
            ))
            threads_made += 1
            cases_made += 1

    db.session.commit()
    print(f'[support] Tickets: {tickets_made} · Threads: {threads_made} · Messages: {msgs_made} · Cases: {cases_made}\n')


# ─────────────────────────────────────────────────────────────────────
# Wallet ledger entries (deposits + withdrawals + refunds)
# ─────────────────────────────────────────────────────────────────────
def create_wallet_entries(subscribers, admins):
    print('[finance] Creating wallet ledger entries per subscriber...')
    finance_actor = next((a for a in admins if a.role == 'finance_manager'), admins[0] if admins else None)
    total = 0

    for sub in subscribers:
        tenant = TenantAccount.query.filter_by(owner_user_id=sub.id).first()
        if not tenant:
            continue
        n = random.randint(6, 10)
        for _ in range(n):
            kind = random.choices(['credit', 'debit', 'debit'], weights=[3, 2, 1])[0]  # more credits than debits
            amount = round(random.uniform(5, 250), 2)
            note = ''
            reference = ''
            if kind == 'credit':
                note = random.choice([
                    'إيداع شهري للاشتراك',
                    'إيداع رصيد إضافي',
                    'دفعة عبر USDT',
                    'تحويل بنكي مستلم',
                    'دفعة كاش',
                ])
                reference = random.choice(['[usdt]', '[bank]', '[paypal]', '[card]', '[cash]'])
            else:
                # 30% of debits are refunds
                if random.random() < 0.3:
                    note = 'استرداد رصيد بناءً على طلب المشترك'
                    reference = '[refund]'
                else:
                    note = random.choice([
                        'تجديد الاشتراك الشهري',
                        'إضافة كوتا SMS',
                        'رسوم خدمة Telegram',
                        'ترقية للخطة الأعلى',
                        'سحب رصيد',
                    ])
                    reference = random.choice(['[renew]', '[quota]', '[service]', '[plan_change]', '[cashout]'])

            entry = WalletLedger(
                tenant_id=tenant.id,
                actor_user_id=finance_actor.id if finance_actor else None,
                entry_type=kind,
                amount=amount,
                currency='USD',
                note=note,
                reference=reference,
                created_at=random_past_dt(1, 90),
            )
            db.session.add(entry)
            total += 1
    db.session.commit()
    print(f'[finance] Total ledger entries created: {total}\n')


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main():
    random.seed()
    app = create_app()
    with app.app_context():
        wipe_support_and_finance()
        admins = ensure_admin_staff()
        if not admins:
            print('ERROR: no admins available; aborting.')
            return
        subs = create_subscribers(20)
        create_support_data(subs, admins)
        create_wallet_entries(subs, admins)
        print('✅ Data seeded into the live database successfully.')
        print('\nLogin credentials (password for all = "Demo@2026"):')
        print('\n  Admin team:')
        for a in admins:
            print(f'    @{a.username:<26} {a.full_name:<25} ({a.role})')
        print(f'\n  Subscribers ({len(subs)}):')
        for s in subs:
            print(f'    @{s.username:<26} {s.full_name}')


if __name__ == '__main__':
    main()
