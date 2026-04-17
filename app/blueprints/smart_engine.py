from __future__ import annotations

from datetime import UTC, datetime

from .helpers import build_battery_insights, build_pre_sunset_prediction, get_runtime_battery_settings
from ..services.utils import utc_to_local


def build_smart_energy_advice(latest, weather=None, settings=None, context='periodic_day'):
    if not latest:
        return {
            'status_label': '⚪ لا توجد بيانات',
            'smart_warning': 'لا توجد قراءة حديثة كافية للتحليل.',
            'smart_recommendation': 'انتظر أول مزامنة.',
            'decision_now': 'لا توجد توصية حالياً.',
        }

    settings = settings or {}
    battery_capacity_kwh, battery_reserve_percent = get_runtime_battery_settings(settings)
    battery = build_battery_insights(latest, battery_capacity_kwh, battery_reserve_percent)
    now_local = utc_to_local(datetime.now(UTC), 'Asia/Hebron') or datetime.now(UTC)
    soc = float(latest.battery_soc or 0)
    home = float(latest.home_load or 0)

    prediction = build_pre_sunset_prediction(latest, weather=weather, settings=settings) if weather else {}
    minutes_to_sunset = prediction.get('minutes_to_sunset')

    if str(context).lower() == 'periodic_night':
        if soc <= max(float(battery_reserve_percent), 20):
            return {
                'status_label': '🔴 حرج',
                'smart_warning': 'نسبة البطارية منخفضة مقارنة بهامش الأمان الليلي.',
                'smart_recommendation': 'قلّل الأحمال غير الضرورية قدر الإمكان.',
                'decision_now': 'يفضل تأجيل أي حمل إضافي الآن.',
            }
        if home > 0 and battery.get('discharge_eta_hours') is not None and battery.get('discharge_eta_hours', 0) < 6:
            return {
                'status_label': '🟡 تشغيل محدود بحذر',
                'smart_warning': 'الطاقة المتبقية قد لا تكون مريحة لبقية الليل.',
                'smart_recommendation': 'حافظ على البطارية حتى الصباح.',
                'decision_now': 'تشغيل بسيط فقط عند الضرورة.',
            }
        return {
            'status_label': '🟢 مطمئن',
            'smart_warning': '',
            'smart_recommendation': 'يمكن تشغيل الأحمال الخفيفة باعتدال.',
            'decision_now': 'الوضع الليلي مستقر حالياً.',
        }

    if minutes_to_sunset is not None and minutes_to_sunset <= 90:
        return {
            'status_label': '🟡 تشغيل محدود بحذر',
            'smart_warning': 'الوقت المتبقي قبل الغروب قصير.',
            'smart_recommendation': 'يفضل تجنب تشغيل حمل طويل الآن.',
            'decision_now': 'تشغيل صغير فقط إذا كان ضروريًا.',
        }
    if soc <= max(float(battery_reserve_percent), 20):
        return {
            'status_label': '🟠 حافظ على الشحن',
            'smart_warning': 'البطارية ما زالت بحاجة إلى دعم أكبر قبل المساء.',
            'smart_recommendation': 'أعطِ أولوية لشحن البطارية.',
            'decision_now': 'يفضل تخفيف الأحمال حاليًا.',
        }
    return {
        'status_label': '🟢 مناسب بحذر',
        'smart_warning': '',
        'smart_recommendation': 'الوضع جيد حاليًا مع الاستمرار بالمراقبة.',
        'decision_now': 'يمكن تشغيل أحمال خفيفة إلى متوسطة حسب الفائض.',
    }
