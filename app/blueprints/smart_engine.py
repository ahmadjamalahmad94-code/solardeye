from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..extensions import db
from ..models import SmartRecommendationLog, SmartSnapshot
from ..services.utils import to_json, utc_to_local
from .helpers import (
    build_battery_insights,
    build_pre_sunset_prediction,
    compute_actual_solar_surplus,
    get_runtime_battery_settings,
    load_settings,
)


def _safe_float(value, default=0.0):
    try:
        if value is None or value == '':
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _minute_bucket(dt: datetime) -> int:
    minute = int(getattr(dt, 'minute', 0) or 0)
    return (minute // 15) * 15


def _quality_score(latest, weather=None) -> float:
    score = 1.0
    if latest is None:
        return 0.0
    if getattr(latest, 'solar_power', None) is None:
        score -= 0.15
    if getattr(latest, 'home_load', None) is None:
        score -= 0.15
    if getattr(latest, 'battery_soc', None) is None:
        score -= 0.2
    if weather is None:
        score -= 0.1
    else:
        if getattr(weather, 'temperature_c', None) is None:
            score -= 0.05
        if getattr(weather, 'clouds', None) is None:
            score -= 0.05
    return max(round(score, 2), 0.0)


def _significant_snapshot_change(previous: SmartSnapshot | None, current_payload: dict) -> bool:
    if previous is None:
        return True
    checks = [
        ('solar_power', 200.0),
        ('home_load', 150.0),
        ('battery_soc', 2.0),
        ('actual_surplus_w', 200.0),
        ('clouds_percent', 15.0),
        ('temperature_c', 3.0),
    ]
    for key, threshold in checks:
        old_val = _safe_float(getattr(previous, key, None), 0.0)
        new_val = _safe_float(current_payload.get(key), 0.0)
        if abs(new_val - old_val) >= threshold:
            return True
    if bool(getattr(previous, 'is_day', True)) != bool(current_payload.get('is_day', True)):
        return True
    return False


def save_smart_snapshot_from_reading(latest, weather=None, settings=None, source='auto_sync'):
    if not latest:
        return None

    settings = settings or load_settings()
    timezone_name = settings.get('local_timezone') or 'Asia/Hebron'
    local_dt = utc_to_local(getattr(latest, 'created_at', None), timezone_name) or utc_to_local(datetime.now(UTC), timezone_name) or datetime.now(UTC)

    prediction = build_pre_sunset_prediction(latest, weather=weather, settings=settings) if weather else {}
    surplus_data = compute_actual_solar_surplus(latest, weather=weather, settings=settings)
    minutes_to_sunset = prediction.get('minutes_to_sunset')
    is_day = bool(prediction.get('is_day')) if prediction else (_safe_float(getattr(latest, 'solar_power', 0), 0) > 50)

    payload = {
        'reading_id': getattr(latest, 'id', None),
        'created_at': getattr(latest, 'created_at', None) or datetime.utcnow(),
        'local_hour': int(local_dt.hour),
        'local_minute_bucket': _minute_bucket(local_dt),
        'is_day': is_day,
        'temperature_c': getattr(weather, 'temperature_c', None) if weather else None,
        'clouds_percent': getattr(weather, 'clouds', None) if weather else None,
        'weather_code': getattr(weather, 'condition_code', None) if weather else None,
        'solar_power': _safe_float(getattr(latest, 'solar_power', 0), 0),
        'home_load': _safe_float(getattr(latest, 'home_load', 0), 0),
        'battery_soc': _safe_float(getattr(latest, 'battery_soc', 0), 0),
        'battery_power': _safe_float(getattr(latest, 'battery_power', 0), 0),
        'grid_power': _safe_float(getattr(latest, 'grid_power', 0), 0),
        'inverter_power': _safe_float(getattr(latest, 'inverter_power', 0), 0),
        'raw_surplus_w': _safe_float(surplus_data.get('raw_surplus_w', 0), 0),
        'battery_charge_need_w': _safe_float(surplus_data.get('battery_charge_need_w', 0), 0),
        'actual_surplus_w': _safe_float(surplus_data.get('actual_surplus_w', 0), 0),
        'minutes_to_sunset': None if minutes_to_sunset is None else _safe_float(minutes_to_sunset, 0),
        'quality_score': _quality_score(latest, weather=weather),
        'source': source,
    }

    previous = SmartSnapshot.query.order_by(SmartSnapshot.created_at.desc()).first()
    if previous and getattr(previous, 'created_at', None):
        elapsed = abs((payload['created_at'] - previous.created_at).total_seconds())
        if elapsed < 15 * 60 and not _significant_snapshot_change(previous, payload):
            return previous

    row = SmartSnapshot(**payload)
    db.session.add(row)
    db.session.commit()
    return row


def find_similar_snapshots(current_snapshot: SmartSnapshot | None, lookback_days: int = 45, limit: int = 60):
    if not current_snapshot:
        return []
    since = (current_snapshot.created_at or datetime.utcnow()) - timedelta(days=max(int(lookback_days or 45), 1))
    query = (
        SmartSnapshot.query
        .filter(SmartSnapshot.created_at >= since)
        .filter(SmartSnapshot.id != current_snapshot.id)
        .filter(SmartSnapshot.is_day == current_snapshot.is_day)
        .filter(SmartSnapshot.local_hour.between(max(current_snapshot.local_hour - 1, 0), min(current_snapshot.local_hour + 1, 23)))
    )

    if current_snapshot.temperature_c is not None:
        query = query.filter(SmartSnapshot.temperature_c.between(current_snapshot.temperature_c - 4, current_snapshot.temperature_c + 4))
    if current_snapshot.clouds_percent is not None:
        query = query.filter(SmartSnapshot.clouds_percent.between(current_snapshot.clouds_percent - 20, current_snapshot.clouds_percent + 20))
    if current_snapshot.battery_soc is not None:
        query = query.filter(SmartSnapshot.battery_soc.between(current_snapshot.battery_soc - 10, current_snapshot.battery_soc + 10))

    return query.order_by(SmartSnapshot.created_at.desc()).limit(max(int(limit or 60), 1)).all()


def analyze_historical_pattern(current_snapshot: SmartSnapshot | None, lookback_days: int = 45) -> dict:
    similar = find_similar_snapshots(current_snapshot, lookback_days=lookback_days)
    if not current_snapshot:
        return {
            'matched_count': 0,
            'confidence_score': 0.0,
            'confidence_label_ar': 'لا توجد بيانات',
            'historical_hint_ar': '',
            'predicted_next_hour_solar': None,
            'predicted_next_hour_surplus': None,
            'predicted_risk_level': 'unknown',
        }
    if not similar:
        return {
            'matched_count': 0,
            'confidence_score': 0.12,
            'confidence_label_ar': 'ثقة منخفضة',
            'historical_hint_ar': 'لا توجد بعد حالات مشابهة كفاية في الأرشيف.',
            'predicted_next_hour_solar': None,
            'predicted_next_hour_surplus': None,
            'predicted_risk_level': 'unknown',
        }

    matched_count = len(similar)
    avg_solar = round(sum(_safe_float(x.solar_power, 0) for x in similar) / matched_count, 1)
    avg_surplus = round(sum(_safe_float(x.actual_surplus_w, 0) for x in similar) / matched_count, 1)
    drop_cases = sum(1 for x in similar if _safe_float(x.actual_surplus_w, 0) <= max(_safe_float(current_snapshot.actual_surplus_w, 0) - 150, 0))
    drop_ratio = drop_cases / matched_count if matched_count else 0.0

    if matched_count >= 7:
        confidence = 0.82
        confidence_label_ar = 'ثقة جيدة'
    elif matched_count >= 3:
        confidence = 0.58
        confidence_label_ar = 'ثقة متوسطة'
    else:
        confidence = 0.28
        confidence_label_ar = 'ثقة منخفضة'

    if drop_ratio >= 0.6:
        risk = 'high'
        hint = f'بناءً على {matched_count} حالات مشابهة، هناك احتمال مرتفع لانخفاض الفائض خلال الفترة القادمة.'
    elif drop_ratio >= 0.35:
        risk = 'medium'
        hint = f'بناءً على {matched_count} حالات مشابهة، الإنتاج قد يتراجع خلال الساعة القادمة.'
    else:
        risk = 'low'
        hint = f'بناءً على {matched_count} حالات مشابهة، الوضع يميل إلى الاستقرار القريب.'

    return {
        'matched_count': matched_count,
        'confidence_score': round(confidence, 2),
        'confidence_label_ar': confidence_label_ar,
        'historical_hint_ar': hint,
        'predicted_next_hour_solar': avg_solar,
        'predicted_next_hour_surplus': avg_surplus,
        'predicted_risk_level': risk,
    }


def log_historical_recommendation(snapshot: SmartSnapshot | None, advice: dict, analysis: dict):
    if not snapshot:
        return None
    row = SmartRecommendationLog(
        snapshot_id=snapshot.id,
        recommendation_type='historical_advice',
        status_label=str(advice.get('status_label', ''))[:100],
        message_ar=advice.get('historical_hint', '') or advice.get('smart_recommendation', ''),
        confidence_score=_safe_float(analysis.get('confidence_score', 0), 0),
        matched_count=int(analysis.get('matched_count', 0) or 0),
        predicted_next_hour_solar=analysis.get('predicted_next_hour_solar'),
        predicted_risk_level=str(analysis.get('predicted_risk_level', 'unknown'))[:30],
        raw_json=to_json({'analysis': analysis, 'advice': advice}),
    )
    db.session.add(row)
    db.session.commit()
    return row


def build_smart_energy_advice(latest, weather=None, settings=None, context='periodic_day'):
    if not latest:
        return {
            'status_label': '⚪ لا توجد بيانات',
            'smart_warning': 'لا توجد قراءة حديثة كافية للتحليل.',
            'smart_recommendation': 'انتظر أول مزامنة.',
            'decision_now': 'لا توجد توصية حالياً.',
            'historical_hint': '',
            'confidence_label': 'لا توجد بيانات',
            'matched_count': 0,
        }

    settings = settings or {}
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    soc = float(latest.battery_soc or 0)
    home = float(latest.home_load or 0)

    prediction = build_pre_sunset_prediction(latest, weather=weather, settings=settings) if weather else {}
    minutes_to_sunset = prediction.get('minutes_to_sunset')

    if str(context).lower() == 'periodic_night':
        if soc <= max(float(battery_reserve_percent), 20):
            advice = {
                'status_label': '🔴 حرج',
                'smart_warning': 'نسبة البطارية منخفضة مقارنة بهامش الأمان الليلي.',
                'smart_recommendation': 'قلّل الأحمال غير الضرورية قدر الإمكان.',
                'decision_now': 'يفضل تأجيل أي حمل إضافي الآن.',
            }
        elif home > 0 and battery.get('discharge_eta_hours') is not None and battery.get('discharge_eta_hours', 0) < 6:
            advice = {
                'status_label': '🟡 تشغيل محدود بحذر',
                'smart_warning': 'الطاقة المتبقية قد لا تكون مريحة لبقية الليل.',
                'smart_recommendation': 'حافظ على البطارية حتى الصباح.',
                'decision_now': 'تشغيل بسيط فقط عند الضرورة.',
            }
        else:
            advice = {
                'status_label': '🟢 مطمئن',
                'smart_warning': '',
                'smart_recommendation': 'يمكن تشغيل الأحمال الخفيفة باعتدال.',
                'decision_now': 'الوضع الليلي مستقر حالياً.',
            }
    elif minutes_to_sunset is not None and minutes_to_sunset <= 90:
        advice = {
            'status_label': '🟡 تشغيل محدود بحذر',
            'smart_warning': 'الوقت المتبقي قبل الغروب قصير.',
            'smart_recommendation': 'يفضل تجنب تشغيل حمل طويل الآن.',
            'decision_now': 'تشغيل صغير فقط إذا كان ضروريًا.',
        }
    elif soc <= max(float(battery_reserve_percent), 20):
        advice = {
            'status_label': '🟠 حافظ على الشحن',
            'smart_warning': 'البطارية ما زالت بحاجة إلى دعم أكبر قبل المساء.',
            'smart_recommendation': 'أعطِ أولوية لشحن البطارية.',
            'decision_now': 'يفضل تخفيف الأحمال حاليًا.',
        }
    else:
        advice = {
            'status_label': '🟢 مناسب بحذر',
            'smart_warning': '',
            'smart_recommendation': 'الوضع جيد حاليًا مع الاستمرار بالمراقبة.',
            'decision_now': 'يمكن تشغيل أحمال خفيفة إلى متوسطة حسب الفائض.',
        }

    snapshot = save_smart_snapshot_from_reading(latest, weather=weather, settings=settings, source='smart_advice')
    analysis = analyze_historical_pattern(snapshot)
    advice['historical_hint'] = analysis.get('historical_hint_ar', '')
    advice['confidence_label'] = analysis.get('confidence_label_ar', 'لا توجد بيانات')
    advice['matched_count'] = int(analysis.get('matched_count', 0) or 0)
    advice['predicted_next_hour_solar'] = analysis.get('predicted_next_hour_solar')
    advice['predicted_next_hour_surplus'] = analysis.get('predicted_next_hour_surplus')
    advice['predicted_risk_level'] = analysis.get('predicted_risk_level', 'unknown')

    try:
        log_historical_recommendation(snapshot, advice, analysis)
    except Exception:
        db.session.rollback()

    return advice
