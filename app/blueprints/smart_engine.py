"""Smart Engine v1: instant rule-based advice for energy notifications."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from flask import current_app

from ..services.utils import safe_float, utc_to_local


@dataclass
class EnergySignals:
    context: str
    is_day: bool
    near_sunset: bool
    battery_percent: float
    solar_power: float
    load_power: float
    battery_power: float
    safe_surplus_w: float
    reserve_battery_percent: float
    night_max_load_w: float
    eta_hours: float | None = None
    time_to_sunset_hours: float | None = None


def _parse_eta_hours(value):
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except Exception:
        pass
    text = str(value).strip()
    if not text or text in {'غير متاح', '--', '...'}:
        return None
    total_hours = 0.0
    matched = False
    for token in text.replace('،', ' ').split():
        t = token.strip()
        if not t:
            continue
        if t.endswith('ساعة'):
            try:
                total_hours += float(t[:-4] or 0)
                matched = True
            except Exception:
                pass
        elif t.endswith('ساعات'):
            try:
                total_hours += float(t[:-5] or 0)
                matched = True
            except Exception:
                pass
        elif t.endswith('دقيقة'):
            try:
                total_hours += float(t[:-5] or 0) / 60.0
                matched = True
            except Exception:
                pass
        elif t.endswith('دقائق'):
            try:
                total_hours += float(t[:-5] or 0) / 60.0
                matched = True
            except Exception:
                pass
    return total_hours if matched else None


def _time_to_sunset_hours(weather):
    if not weather or not getattr(weather, 'sunset_time', None):
        return None
    try:
        now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
        hhmm = str(weather.sunset_time).strip()
        parts = hhmm.split(':')
        if len(parts) < 2:
            return None
        sunset_local = now_local.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
        if sunset_local.tzinfo is None and now_local.tzinfo is not None:
            sunset_local = sunset_local.replace(tzinfo=now_local.tzinfo)
        return max((sunset_local - now_local).total_seconds() / 3600.0, 0.0)
    except Exception:
        return None


def extract_energy_signals(latest, weather=None, settings=None, context='periodic_day'):
    settings = settings or {}
    solar = max(float(getattr(latest, 'solar_power', 0) or 0), 0.0)
    load = max(float(getattr(latest, 'home_load', 0) or 0), 0.0)
    battery_percent = max(float(getattr(latest, 'battery_soc', 0) or 0), 0.0)
    battery_power = float(getattr(latest, 'battery_power', 0) or 0)
    min_solar_threshold = safe_float(settings.get('daytime_solar_min_w', '150'), 150)
    reserve_battery_percent = safe_float(settings.get('battery_reserve_percent', '20'), 20)
    night_max_load_w = safe_float(settings.get('night_max_load_w') or settings.get('night_max_allowed_w') or '300', 300)
    safety_margin_w = safe_float(settings.get('smart_safety_margin_w', '100'), 100)
    now_local = utc_to_local(datetime.now(UTC), current_app.config['LOCAL_TIMEZONE']) or datetime.now(UTC)
    sunset_hours = _time_to_sunset_hours(weather)
    near_sunset = sunset_hours is not None and sunset_hours <= 2.5
    context = (context or 'periodic_day').strip().lower()
    if context in {'periodic_night', 'night', 'night_discharge'}:
        is_day = False
    elif context in {'pre_sunset', 'sunset'}:
        is_day = True
        near_sunset = True
    else:
        is_day = solar >= min_solar_threshold and not (near_sunset and sunset_hours is not None and sunset_hours < 0.25)
    if is_day:
        safe_surplus_w = max((solar - load) - safety_margin_w, -99999.0)
    else:
        safe_surplus_w = max((night_max_load_w - load) - safety_margin_w, -99999.0)
    eta_source = None
    if battery_power > 0:
        eta_source = getattr(latest, 'eta_charge_hours', None)
    elif battery_power < 0:
        eta_source = getattr(latest, 'eta_discharge_hours', None)
    eta_hours = _parse_eta_hours(eta_source)
    return EnergySignals(context=context, is_day=is_day, near_sunset=bool(near_sunset), battery_percent=battery_percent, solar_power=solar, load_power=load, battery_power=battery_power, safe_surplus_w=safe_surplus_w, reserve_battery_percent=reserve_battery_percent, night_max_load_w=night_max_load_w, eta_hours=eta_hours, time_to_sunset_hours=sunset_hours)


def evaluate_energy_state(signals: EnergySignals):
    score = 100
    bp = signals.battery_percent
    if bp < 30:
        score -= 60
    elif bp < 45:
        score -= 40
    elif bp < 60:
        score -= 25
    elif bp < 75:
        score -= 10
    if signals.safe_surplus_w < 0:
        score -= 15
    if signals.is_day and signals.battery_power <= -100:
        score -= 20
    if signals.eta_hours is not None:
        if signals.eta_hours < 2:
            score -= 35
        elif signals.eta_hours < 4:
            score -= 20
    if signals.near_sunset and signals.time_to_sunset_hours is not None and signals.time_to_sunset_hours < 1:
        score -= 15
    if (not signals.is_day) and signals.load_power >= signals.night_max_load_w:
        score -= 15
    if bp <= signals.reserve_battery_percent:
        score = min(score, 20)
    score = max(min(int(round(score)), 100), 0)
    if score >= 85:
        status_level = 'safe'
    elif score >= 65:
        status_level = 'caution'
    elif score >= 40:
        status_level = 'warning'
    else:
        status_level = 'danger'
    return {'score': score, 'status_level': status_level}


def render_smart_advice(signals: EnergySignals, evaluation: dict, context='periodic_day'):
    level = evaluation['status_level']
    bp = signals.battery_percent
    ssw = signals.safe_surplus_w
    eta = signals.eta_hours
    is_day = signals.is_day
    if level == 'safe':
        status_label = '🟢 الوضع جيد'
    elif level == 'caution':
        status_label = '🟡 تشغيل محدود بحذر'
    elif level == 'warning':
        status_label = '🟠 الوضع حساس'
    else:
        status_label = '🔴 خطر'
    smart_warning = ''
    smart_recommendation = ''
    decision_now = ''
    if context in {'pre_sunset', 'sunset'} or signals.near_sunset:
        if signals.time_to_sunset_hours is not None and signals.time_to_sunset_hours <= 0.5:
            smart_warning = 'الوقت المتبقي قبل الغروب قصير جدًا.'
            smart_recommendation = 'تجنب بدء أحمال طويلة الآن.'
            decision_now = 'لا تبدأ أي حمل جديد إلا للضرورة.'
        elif bp < 40 or ssw <= 0:
            smart_warning = 'الوضع قبل الغروب لا يمنح هامشًا مريحًا لليل.'
            smart_recommendation = 'خفف الاستهلاك الآن وحافظ على البطارية.'
            decision_now = 'يفضل عدم تشغيل أي حمل جديد الآن.'
        elif signals.time_to_sunset_hours is not None and signals.time_to_sunset_hours > 1 and ssw >= 250 and bp >= 55:
            smart_recommendation = 'ما زالت هناك فرصة لاستغلال الشمس بحمل قصير.'
            decision_now = 'يمكن تشغيل حمل قصير الآن.'
        else:
            smart_recommendation = 'شغل فقط ما هو ضروري وتجنب الأحمال الطويلة.'
            decision_now = 'تشغيل صغير فقط إن لزم.'
    elif is_day:
        if signals.battery_power <= -100 and signals.solar_power > 0 and signals.load_power > signals.solar_power:
            smart_warning = 'الاستهلاك أعلى من الإنتاج الحالي ويتم السحب من البطارية.'
            smart_recommendation = 'خفف الأحمال الحالية وانتظر تحسن الفائض.'
            decision_now = 'لا تضف أحمالًا جديدة الآن.'
        elif ssw >= 400 and bp >= 50:
            smart_recommendation = 'استفد من الفائض الحالي في تشغيل حمل صغير أو متوسط.'
            decision_now = 'يمكن تشغيل حمل صغير أو متوسط الآن.'
        elif 150 <= ssw < 400 and bp >= 40:
            smart_recommendation = 'الفائض مناسب لحمل صغير، والمتوسط يحتاج حذرًا.'
            decision_now = 'يمكن تشغيل حمل صغير فقط.'
        elif 0 <= ssw < 150:
            smart_warning = 'الفائض الحالي محدود وقد لا يستمر.'
            smart_recommendation = 'أجّل الأحمال غير الضرورية إلى وقت أفضل.'
            decision_now = 'تشغيل محدود جدًا فقط.'
        else:
            smart_warning = 'لا يوجد فائض آمن حاليًا.'
            smart_recommendation = 'راقب القراءة القادمة قبل تشغيل أي حمل إضافي.'
            decision_now = 'يفضل عدم تشغيل أحمال إضافية الآن.'
    else:
        if bp < 30 or (eta is not None and eta < 2):
            smart_warning = 'البطارية منخفضة أو وقت النفاد قريب.'
            smart_recommendation = 'أبقِ فقط على الأحمال الأساسية.'
            decision_now = 'لا تشغّل أي جهاز إضافي الآن.'
        elif bp < 45 or (eta is not None and eta < 3):
            smart_warning = 'الوضع الليلي حساس ويحتاج تقليل الاستهلاك.'
            smart_recommendation = 'خفف الأحمال غير الضرورية فورًا.'
            decision_now = 'لا تضف أي حمل جديد الآن.'
        elif bp < 60 or (eta is not None and eta < 5):
            smart_recommendation = 'استخدم الطاقة بحذر وركز على الأجهزة الأساسية.'
            decision_now = 'يفضل عدم تشغيل أحمال إضافية إلا للضرورة.'
        elif bp >= 75 and ((eta is None) or eta >= 8):
            smart_recommendation = 'الوضع الليلي مريح نسبيًا لكن الأفضل الاكتفاء بالأحمال الصغيرة.'
            decision_now = 'يمكن تشغيل حمل صغير فقط.'
        else:
            smart_recommendation = 'الأفضل تشغيل الأحمال الصغيرة فقط ومراقبة البطارية.'
            decision_now = 'تشغيل صغير فقط وبحذر.'
    if (not is_day) and signals.load_power >= signals.night_max_load_w and level != 'danger':
        smart_warning = 'الاستهلاك الحالي تجاوز الحد الليلي الموصى به.'
    return {'status_label': status_label, 'smart_warning': smart_warning, 'smart_recommendation': smart_recommendation, 'decision_now': decision_now, 'score': evaluation.get('score', 0), 'status_level': evaluation.get('status_level', 'warning')}


def build_smart_energy_advice(latest, weather=None, settings=None, context='periodic_day'):
    signals = extract_energy_signals(latest, weather=weather, settings=settings, context=context)
    evaluation = evaluate_energy_state(signals)
    payload = render_smart_advice(signals, evaluation, context=context)
    payload['signals'] = signals
    return payload
