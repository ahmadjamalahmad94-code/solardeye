"""Smart Engine v1.5: instant rule-based advice with configurable profile."""
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
    night_comfort_battery: float
    medium_load_threshold_w: float
    sunset_mode: str
    tone_mode: str
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


def _status_label(level: str, tone: str):
    labels = {
        'friendly': {
            'safe': '🟢 الوضع مريح ومطمئن',
            'caution': '🟡 الوضع جيد لكن بهامش محدود',
            'warning': '🟠 الوضع يحتاج انتباهًا',
            'danger': '🔴 الوضع حساس الآن',
        },
        'balanced': {
            'safe': '🟢 الوضع جيد',
            'caution': '🟡 تشغيل محدود بحذر',
            'warning': '🟠 الوضع حساس',
            'danger': '🔴 خطر',
        },
        'strict': {
            'safe': '🟢 آمن',
            'caution': '🟡 حذر',
            'warning': '🟠 تحذير',
            'danger': '🔴 خطر مرتفع',
        },
    }
    return labels.get(tone, labels['balanced']).get(level, '🟡 يحتاج مراجعة')


def _effective_tone(level: str, tone_mode: str):
    tone_mode = (tone_mode or 'adaptive').strip().lower()
    if tone_mode in {'friendly', 'balanced', 'strict'}:
        return tone_mode
    if level == 'safe':
        return 'friendly'
    if level == 'caution':
        return 'balanced'
    return 'strict'


def _sunset_config(mode: str):
    mode = (mode or 'balanced').strip().lower()
    if mode == 'strict':
        return {'allow_window_hours': 1.5, 'min_surplus_w': 350, 'min_battery_percent': 60, 'critical_minutes': 75}
    if mode == 'relaxed':
        return {'allow_window_hours': 0.75, 'min_surplus_w': 200, 'min_battery_percent': 50, 'critical_minutes': 30}
    return {'allow_window_hours': 1.0, 'min_surplus_w': 250, 'min_battery_percent': 55, 'critical_minutes': 45}


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
    night_comfort_battery = safe_float(settings.get('smart_night_comfort_battery', '60'), 60)
    medium_load_threshold_w = safe_float(settings.get('smart_medium_load_threshold_w', '500'), 500)
    sunset_mode = (settings.get('smart_sunset_mode', 'balanced') or 'balanced').strip().lower()
    tone_mode = (settings.get('smart_tone_mode', 'adaptive') or 'adaptive').strip().lower()
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
    return EnergySignals(context=context, is_day=is_day, near_sunset=bool(near_sunset), battery_percent=battery_percent, solar_power=solar, load_power=load, battery_power=battery_power, safe_surplus_w=safe_surplus_w, reserve_battery_percent=reserve_battery_percent, night_max_load_w=night_max_load_w, night_comfort_battery=night_comfort_battery, medium_load_threshold_w=medium_load_threshold_w, sunset_mode=sunset_mode, tone_mode=tone_mode, eta_hours=eta_hours, time_to_sunset_hours=sunset_hours)


def evaluate_energy_state(signals: EnergySignals):
    score = 100
    bp = signals.battery_percent
    if not signals.is_day and bp < signals.night_comfort_battery:
        score -= 12
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
    tone = _effective_tone(level, signals.tone_mode)
    status_label = _status_label(level, tone)
    smart_warning = ''
    smart_recommendation = ''
    decision_now = ''
    if context in {'pre_sunset', 'sunset'} or signals.near_sunset:
        sunset_cfg = _sunset_config(signals.sunset_mode)
        critical_hours = sunset_cfg['critical_minutes'] / 60.0
        if signals.time_to_sunset_hours is not None and signals.time_to_sunset_hours <= critical_hours:
            smart_warning = 'الوقت المتبقي قبل الغروب قصير، فالأفضل عدم بدء حمل طويل الآن.'
            smart_recommendation = 'حافظ على الهامش المتبقي لمرحلة الليل.'
            decision_now = 'تشغيل صغير جدًا فقط إن كان ضروريًا.'
        elif bp < 40 or ssw <= 0:
            smart_warning = 'الوضع قبل الغروب لا يمنح هامشًا مريحًا للفترة الليلية.'
            smart_recommendation = 'خفف الأحمال الآن ودع الشحن يكمل قدر الإمكان.'
            decision_now = 'يفضل عدم تشغيل أي حمل جديد الآن.'
        elif signals.time_to_sunset_hours is not None and signals.time_to_sunset_hours > sunset_cfg['allow_window_hours'] and ssw >= sunset_cfg['min_surplus_w'] and bp >= sunset_cfg['min_battery_percent']:
            smart_recommendation = 'ما زالت هناك فرصة جيدة لاستغلال الشمس بحمل قصير ومدروس.'
            decision_now = 'يمكن تشغيل حمل قصير الآن.'
        else:
            smart_recommendation = 'الوضع متوازن، لكن الأفضل تجنب أي حمل طويل قبل الغروب.'
            decision_now = 'تشغيل صغير فقط إن لزم.'
    elif is_day:
        if signals.battery_power <= -100 and signals.solar_power > 0 and signals.load_power > signals.solar_power:
            smart_warning = 'الاستهلاك أعلى من الإنتاج الحالي، والجهاز يسحب من البطارية.'
            smart_recommendation = 'خفف الأحمال الحالية وانتظر تحسن الفائض قبل إضافة أي جهاز.'
            decision_now = 'لا تضف أحمالًا جديدة الآن.'
        elif ssw >= signals.medium_load_threshold_w and bp >= 50:
            smart_recommendation = 'الوضع مناسب للاستفادة من الفائض الحالي بشكل مريح.'
            decision_now = 'يمكن تشغيل حمل صغير أو متوسط الآن.'
        elif 250 <= ssw < signals.medium_load_threshold_w and bp >= 40:
            smart_recommendation = 'الفائض الحالي جيد لكن الأفضل الاكتفاء بالأحمال الخفيفة.'
            decision_now = 'يمكن تشغيل حمل صغير فقط.'
        elif 0 <= ssw < 250:
            smart_warning = 'الفائض الحالي محدود وقد يتغير بسرعة.'
            smart_recommendation = 'أجّل الأحمال غير الضرورية وانتظر قراءة أفضل.'
            decision_now = 'تشغيل محدود جدًا فقط.'
        else:
            smart_warning = 'لا يوجد فائض آمن كافٍ الآن.'
            smart_recommendation = 'راقب القراءة القادمة قبل تشغيل أي حمل إضافي.'
            decision_now = 'يفضل عدم تشغيل أحمال إضافية الآن.'
    else:
        if bp < 30 or (eta is not None and eta < 2):
            smart_warning = 'البطارية منخفضة أو وقت النفاد قريب، لذلك يلزم التشدد.'
            smart_recommendation = 'أبقِ فقط على الأحمال الأساسية في هذه المرحلة.'
            decision_now = 'لا تشغّل أي جهاز إضافي الآن.'
        elif bp < 45 or (eta is not None and eta < 3):
            smart_warning = 'الوضع الليلي حساس وقد تتسارع وتيرة النزول مع أي حمل إضافي.'
            smart_recommendation = 'خفف الأحمال غير الضرورية فورًا وحافظ على الحد الأدنى.'
            decision_now = 'لا تضف أي حمل جديد الآن.'
        elif bp < signals.night_comfort_battery or (eta is not None and eta < 5):
            smart_recommendation = 'الوضع ما زال مقبولًا لكن ليس مريحًا بالكامل لليل.'
            decision_now = 'يفضل عدم تشغيل أحمال إضافية إلا للضرورة.'
        elif bp >= signals.night_comfort_battery and ((eta is None) or eta >= 6):
            smart_recommendation = 'الوضع الليلي مريح نسبيًا وفق الحد الذي اخترته، لكن الأفضل البقاء على الأحمال الصغيرة.'
            decision_now = 'يمكن تشغيل حمل صغير فقط.'
        else:
            smart_recommendation = 'الأفضل تشغيل الأحمال الصغيرة فقط مع متابعة البطارية.'
            decision_now = 'تشغيل صغير فقط وبحذر.'
    if (not is_day) and signals.load_power >= signals.night_max_load_w and level != 'danger':
        smart_warning = 'الاستهلاك الحالي تجاوز الحد الليلي الذي حددته، فالأفضل التخفيف الآن.'
    return {'status_label': status_label, 'smart_warning': smart_warning, 'smart_recommendation': smart_recommendation, 'decision_now': decision_now, 'score': evaluation.get('score', 0), 'status_level': evaluation.get('status_level', 'warning'), 'tone_used': tone}


def build_smart_energy_advice(latest, weather=None, settings=None, context='periodic_day'):
    signals = extract_energy_signals(latest, weather=weather, settings=settings, context=context)
    evaluation = evaluate_energy_state(signals)
    payload = render_smart_advice(signals, evaluation, context=context)
    payload['signals'] = signals
    return payload
