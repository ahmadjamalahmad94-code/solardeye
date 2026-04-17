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


def _confidence_profile(matched_count: int) -> dict:
    matched_count = int(matched_count or 0)
    if matched_count <= 2:
        return {
            'confidence_score': 0.18 if matched_count else 0.08,
            'confidence_band': 'low',
            'confidence_label_ar': 'ثقة ضعيفة',
            'confidence_message_ar': 'لا يعتمد',
            'use_historical_for_decision': False,
        }
    if matched_count <= 5:
        return {
            'confidence_score': 0.56,
            'confidence_band': 'medium',
            'confidence_label_ar': 'ثقة متوسطة',
            'confidence_message_ar': 'بحذر',
            'use_historical_for_decision': True,
        }
    return {
        'confidence_score': 0.82,
        'confidence_band': 'high',
        'confidence_label_ar': 'ثقة عالية',
        'confidence_message_ar': 'يعتمد',
        'use_historical_for_decision': True,
    }


def _scenario_from_history(current_snapshot: SmartSnapshot, avg_solar: float, avg_surplus: float, risk_code: str, matched_count: int) -> dict:
    current_solar = _safe_float(getattr(current_snapshot, 'solar_power', 0), 0)
    current_surplus = _safe_float(getattr(current_snapshot, 'actual_surplus_w', 0), 0)
    solar_delta = round(avg_solar - current_solar, 1)
    surplus_delta = round(avg_surplus - current_surplus, 1)

    if matched_count <= 2:
        return {
            'scenario_title_ar': 'السيناريو القادم',
            'scenario_summary_ar': 'الأرشيف ما زال قليلًا، لذلك نعرض القراءة الحالية فقط دون اعتماد تاريخي.',
            'scenario_detail_ar': 'يلزم مزيد من الحالات المشابهة قبل اعتبار التوقع التاريخي مرجعًا.',
        }

    if risk_code == 'high':
        title = 'سيناريو هبوط قريب'
        summary = 'خلال 30–60 دقيقة قد ينخفض الفائض عن الوضع الحالي.'
    elif risk_code == 'medium':
        title = 'سيناريو مراقبة'
        summary = 'خلال الساعة القادمة قد يظهر تراجع جزئي ويستحسن عدم التوسع بالأحمال.'
    else:
        title = 'سيناريو مستقر'
        summary = 'خلال الساعة القادمة يبدو السلوك قريبًا من الاستقرار مقارنة بالأرشيف.'

    solar_phrase = 'أقل' if solar_delta < -80 else ('أعلى' if solar_delta > 80 else 'قريب من الحالي')
    if solar_phrase == 'قريب من الحالي':
        detail = f'الإنتاج المتوقع يقارب {avg_solar:.1f} واط، والفائض المتوقع يقارب {avg_surplus:.1f} واط.'
    else:
        detail = f'الإنتاج المتوقع {avg_solar:.1f} واط، وهو {solar_phrase} من القراءة الحالية، والفائض المتوقع {avg_surplus:.1f} واط.'

    if surplus_delta < -150:
        detail += ' يفضل عدم تشغيل حمل إضافي طويل الآن.'
    elif surplus_delta > 200:
        detail += ' قد تكون هناك مساحة محدودة لأحمال خفيفة إذا استمرت الظروف.'

    return {
        'scenario_title_ar': title,
        'scenario_summary_ar': summary,
        'scenario_detail_ar': detail,
    }


def analyze_historical_pattern(current_snapshot: SmartSnapshot | None, lookback_days: int = 45) -> dict:
    empty_result = {
        'matched_count': 0,
        'confidence_score': 0.0,
        'confidence_band': 'low',
        'confidence_label_ar': 'ثقة ضعيفة',
        'confidence_message_ar': 'لا يعتمد',
        'use_historical_for_decision': False,
        'historical_hint_ar': '',
        'predicted_next_hour_solar': None,
        'predicted_next_hour_surplus': None,
        'predicted_risk_level': 'unknown',
        'predicted_risk_label_ar': 'غير معروف',
        'scenario_title_ar': 'السيناريو القادم',
        'scenario_summary_ar': 'لا توجد بيانات كافية بعد.',
        'scenario_detail_ar': 'انتظر تكوّن الأرشيف الذكي عبر مزامَنات أكثر.',
    }
    if not current_snapshot:
        return empty_result

    similar = find_similar_snapshots(current_snapshot, lookback_days=lookback_days)
    matched_count = len(similar)
    confidence = _confidence_profile(matched_count)

    if not similar:
        result = dict(empty_result)
        result.update(confidence)
        result.update({
            'historical_hint_ar': '⚠️ البيانات غير كافية: لا توجد بعد حالات مشابهة في الأرشيف.',
            'predicted_risk_level': 'insufficient',
            'predicted_risk_label_ar': 'بيانات غير كافية',
        })
        return result

    avg_solar = round(sum(_safe_float(x.solar_power, 0) for x in similar) / matched_count, 1)
    avg_surplus = round(sum(_safe_float(x.actual_surplus_w, 0) for x in similar) / matched_count, 1)
    current_surplus = _safe_float(getattr(current_snapshot, 'actual_surplus_w', 0), 0)

    drop_cases = sum(1 for x in similar if _safe_float(x.actual_surplus_w, 0) <= max(current_surplus - 150, 0))
    drop_ratio = drop_cases / matched_count if matched_count else 0.0

    if matched_count <= 2:
        risk_code = 'insufficient'
        risk_label = 'بيانات غير كافية'
        if matched_count == 1:
            hint = '⚠️ البيانات غير كافية (حالة واحدة فقط)، لذلك لا نعتمد هذا التوقع التاريخي بعد.'
        else:
            hint = '⚠️ البيانات غير كافية (حالَتان فقط)، لذلك يبقى القرار الحالي هو المرجع الأساسي.'
    else:
        if drop_ratio >= 0.6:
            risk_code = 'high'
            risk_label = 'مرتفعة'
            hint = f'بناءً على {matched_count} حالات مشابهة، يوجد نمط متكرر يشير إلى احتمال مرتفع لانخفاض الفائض قريبًا.'
        elif drop_ratio >= 0.35:
            risk_code = 'medium'
            risk_label = 'متوسطة'
            hint = f'بناءً على {matched_count} حالات مشابهة، يوجد احتمال متوسط لتراجع الفائض خلال الساعة القادمة.'
        else:
            risk_code = 'low'
            risk_label = 'منخفضة'
            hint = f'بناءً على {matched_count} حالات مشابهة، السلوك التاريخي يميل إلى الاستقرار خلال الساعة القادمة.'

    scenario = _scenario_from_history(current_snapshot, avg_solar, avg_surplus, risk_code, matched_count)

    return {
        'matched_count': matched_count,
        'confidence_score': round(confidence['confidence_score'], 2),
        'confidence_band': confidence['confidence_band'],
        'confidence_label_ar': confidence['confidence_label_ar'],
        'confidence_message_ar': confidence['confidence_message_ar'],
        'use_historical_for_decision': confidence['use_historical_for_decision'],
        'historical_hint_ar': hint,
        'predicted_next_hour_solar': avg_solar,
        'predicted_next_hour_surplus': avg_surplus,
        'predicted_risk_level': risk_code,
        'predicted_risk_label_ar': risk_label,
        'scenario_title_ar': scenario['scenario_title_ar'],
        'scenario_summary_ar': scenario['scenario_summary_ar'],
        'scenario_detail_ar': scenario['scenario_detail_ar'],
    }



def get_latest_historical_overview(lookback_days: int = 45) -> dict:
    """
    Compatibility helper expected by main.py.
    Returns a lightweight overview built from the latest stored SmartSnapshot.
    Safe fallback: if there is no snapshot yet, return a non-breaking empty overview.
    """
    latest_snapshot = SmartSnapshot.query.order_by(SmartSnapshot.created_at.desc()).first()
    if latest_snapshot is None:
        return {
            'archive_ready': False,
            'matched_count': 0,
            'confidence_score': 0.0,
            'confidence_label': 'ثقة ضعيفة',
            'confidence_band': 'low',
            'confidence_message': '⚠️ لا توجد بيانات أرشيفية كافية بعد.',
            'historical_hint': 'الأرشيف ما زال في مرحلة التأسيس.',
            'predicted_next_hour_solar': None,
            'predicted_next_hour_surplus': None,
            'predicted_risk_code': 'insufficient',
            'predicted_risk_level': 'بيانات غير كافية',
            'scenario_title': 'السيناريو القادم',
            'scenario_summary': 'لا توجد حالات تاريخية كافية حتى الآن.',
            'scenario_detail': 'سيبدأ التحليل التاريخي بعد تراكم عدد مناسب من اللقطات.',
            'historical_is_actionable': False,
        }

    analysis = analyze_historical_pattern(latest_snapshot, lookback_days=lookback_days)

    return {
        'archive_ready': True,
        'snapshot_id': getattr(latest_snapshot, 'id', None),
        'matched_count': int(analysis.get('matched_count', 0) or 0),
        'confidence_score': float(analysis.get('confidence_score', 0.0) or 0.0),
        'confidence_label': analysis.get('confidence_label', 'ثقة ضعيفة'),
        'confidence_band': analysis.get('confidence_band', 'low'),
        'confidence_message': analysis.get('confidence_message', '⚠️ البيانات غير كافية بعد.'),
        'historical_hint': analysis.get('historical_hint', ''),
        'predicted_next_hour_solar': analysis.get('predicted_next_hour_solar'),
        'predicted_next_hour_surplus': analysis.get('predicted_next_hour_surplus'),
        'predicted_risk_code': analysis.get('predicted_risk_code', 'insufficient'),
        'predicted_risk_level': analysis.get('predicted_risk_level', 'بيانات غير كافية'),
        'scenario_title': analysis.get('scenario_title', 'السيناريو القادم'),
        'scenario_summary': analysis.get('scenario_summary', ''),
        'scenario_detail': analysis.get('scenario_detail', ''),
        'historical_is_actionable': bool(analysis.get('historical_is_actionable', False)),
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
            'confidence_label': 'ثقة ضعيفة',
            'confidence_message': 'لا يعتمد',
            'confidence_band': 'low',
            'matched_count': 0,
            'predicted_risk_level': 'غير معروف',
            'predicted_risk_code': 'unknown',
            'scenario_title': 'السيناريو القادم',
            'scenario_summary': 'لا توجد بيانات كافية بعد.',
            'scenario_detail': 'انتظر تكوّن الأرشيف الذكي عبر مزامَنات أكثر.',
            'historical_is_actionable': False,
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
    advice['confidence_label'] = analysis.get('confidence_label_ar', 'ثقة ضعيفة')
    advice['confidence_message'] = analysis.get('confidence_message_ar', 'لا يعتمد')
    advice['confidence_band'] = analysis.get('confidence_band', 'low')
    advice['matched_count'] = int(analysis.get('matched_count', 0) or 0)
    advice['predicted_next_hour_solar'] = analysis.get('predicted_next_hour_solar')
    advice['predicted_next_hour_surplus'] = analysis.get('predicted_next_hour_surplus')
    advice['predicted_risk_code'] = analysis.get('predicted_risk_level', 'unknown')
    advice['predicted_risk_level'] = analysis.get('predicted_risk_label_ar', 'غير معروف')
    advice['scenario_title'] = analysis.get('scenario_title_ar', 'السيناريو القادم')
    advice['scenario_summary'] = analysis.get('scenario_summary_ar', '')
    advice['scenario_detail'] = analysis.get('scenario_detail_ar', '')
    advice['historical_is_actionable'] = bool(analysis.get('use_historical_for_decision'))

    if not advice['historical_is_actionable']:
        advice['decision_now'] = f"{advice['decision_now']} (المرجع الحالي هو القراءة اللحظية فقط)"

    try:
        log_historical_recommendation(snapshot, advice, analysis)
    except Exception:
        db.session.rollback()

    return advice
