"""SunContext — the *single source of truth* for "what time of day is it, and
what does that mean for solar production".

Every dashboard widget that needs to answer questions like
  "is the sun up?", "is it producing?", "is it night?", "what icon should
  I show?", "what's a contextually-correct piece of advice?" — must consume
  this object instead of computing its own boolean from `solar_power > 50`.

Design
──────
This module is a *thin wrapper* over the existing `classify_day_phase` in
`app/services/utils.py` (which already returns 9 phases: night, dawn,
sunrise, morning, noon, afternoon, pre_sunset, sunset, dusk).  We add
production-aware metadata on top:

  * `is_day_for_production`  — was it sunny enough that the inverter could
    realistically produce non-trivial power?  This is *not* the same as
    "the sun is geometrically above the horizon" — it accounts for the
    pre-dawn / dusk twilight where production is essentially zero.
  * `weather_icon_for(condition)` — picks the right emoji given current
    phase × current weather condition.  Chooses 🌙 over ☀️ at night even
    if the API returned "Clear".
  * `decision_matrix(confidence, risk, surplus_kwh)` — central decision
    logic for the smart-prediction card so every layer uses the same one.
  * `phase_message_for_smart_card()` — non-conflicting copy used by the
    smart-prediction widget.  No more "the sun is shining" + "expect
    surplus drop in 30 minutes" in the same paragraph.

Public entry point: `compute_sun_context(latest, weather, settings)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .utils import classify_day_phase, utc_to_local


# All possible phases (ordered by time of day).
_PHASE_ORDER = [
    'night', 'dawn', 'sunrise', 'morning', 'noon',
    'afternoon', 'pre_sunset', 'sunset', 'dusk',
]

# Phases where the inverter can produce *meaningful* DC power.
_PRODUCTIVE_PHASES = {'sunrise', 'morning', 'noon', 'afternoon', 'pre_sunset'}

# Phases that count as "night" for the weather widget icon.
_NIGHT_PHASES = {'night', 'dusk'}

# Phases that count as "twilight" (no production but not full night).
_TWILIGHT_PHASES = {'dawn', 'sunset'}


@dataclass(frozen=True)
class SunContext:
    """Fully-resolved picture of the current solar moment."""

    # ── time anchors ──────────────────────────────────────────────────
    now_local: datetime
    timezone_name: str
    sunrise_text: str           # "HH:MM" today
    sunset_text: str            # "HH:MM" today (official)
    sunset_effective_text: str  # production cutoff (~1h before official)

    # ── phase ─────────────────────────────────────────────────────────
    phase: str                  # one of _PHASE_ORDER values
    label_ar: str
    label_en: str
    icon: str                   # emoji selected purely from phase
    description_ar: str
    description_en: str
    accent: str                 # hex color associated with the phase
    gradient: str               # css gradient

    # ── production-aware flags ────────────────────────────────────────
    is_day_for_production: bool
    is_night: bool
    is_twilight: bool
    is_producing_meaningfully: bool   # solar_power > 100 W *and* phase ∈ productive

    # ── time deltas ───────────────────────────────────────────────────
    minutes_to_sunset: int
    minutes_to_sunrise: int

    # ── meta about source data ────────────────────────────────────────
    has_weather_times: bool

    # ── derived helpers ───────────────────────────────────────────────
    @property
    def is_pre_sunset_window(self) -> bool:
        """True in the last ~90 minutes before effective sunset — when
        the user should think about finishing battery charge."""
        return self.phase in {'pre_sunset', 'sunset'}

    @property
    def is_morning_window(self) -> bool:
        return self.phase in {'sunrise', 'morning'}

    # ── icon adapted to weather condition ─────────────────────────────
    def weather_icon_for(self, condition_text: Optional[str], cloud_cover: float = 0.0) -> str:
        """Returns the most appropriate icon given current phase + weather.
        Critical: at night, never returns ☀️ even if condition='Clear'."""
        cond = (condition_text or '').strip()
        is_clear = ('مشمس' in cond) or ('Clear' in cond) or cloud_cover < 20
        is_partly_cloudy = ('غائم جزئي' in cond) or ('Partly' in cond) or 20 <= cloud_cover < 60
        is_overcast = ('غائم' in cond and 'جزئي' not in cond) or cloud_cover >= 80
        is_rainy = ('ممطر' in cond) or ('Rain' in cond) or ('rain' in cond)

        if self.phase in _NIGHT_PHASES:
            if is_rainy:        return '🌧️'
            if is_overcast:     return '☁️'
            if is_partly_cloudy:return '☁️🌙'
            return '🌙'                              # clear night → moon
        if self.phase == 'dawn':       return '🌅'
        if self.phase == 'sunset':     return '🌇'
        if self.phase == 'sunrise':    return '🌄'
        # Day-time phases — pick by weather
        if is_rainy:                   return '🌧️'
        if is_overcast:                return '☁️'
        if is_partly_cloudy:           return '⛅'
        if self.phase == 'noon':       return '☀️'
        return '🌤️'

    def weather_label_for(self, condition_text: Optional[str], cloud_cover: float = 0.0,
                          lang: str = 'ar') -> str:
        """Human-readable weather label that respects the phase.
        At night, "Clear" becomes 'ليل صافٍ' instead of 'مشمس'."""
        cond = (condition_text or '').strip()
        is_ar = lang == 'ar'

        if self.phase in _NIGHT_PHASES:
            if 'ممطر' in cond or 'Rain' in cond:
                return 'ليلة ممطرة' if is_ar else 'Rainy night'
            if 'غائم' in cond and 'جزئي' not in cond:
                return 'ليلة غائمة' if is_ar else 'Cloudy night'
            if cloud_cover >= 40:
                return 'ليلة غائمة جزئيًا' if is_ar else 'Partly cloudy night'
            return 'ليل صافٍ' if is_ar else 'Clear night'

        if self.phase == 'dawn':
            return 'فجر' if is_ar else 'Dawn'
        if self.phase == 'sunrise':
            return 'وقت الشروق' if is_ar else 'Sunrise'
        if self.phase == 'sunset':
            return 'وقت الغروب' if is_ar else 'Sunset'

        # Daytime → use the API's condition text directly
        return cond or ('غير متاح' if is_ar else 'Unavailable')

    # ── decision matrix ───────────────────────────────────────────────
    def decision_matrix(self, confidence_band: str, risk_level: str,
                        surplus_kwh: float, lang: str = 'ar') -> tuple[str, str]:
        """Single source of truth for "what should the user do right now?".

        Returns (status_label, decision_now) — both Arabic by default.

        Rules
        ─────
        * Night/dusk overrides everything: production decisions are off.
        * High risk + zero surplus + ≥medium confidence → "أوقف الأحمال"
        * Low confidence → "لا توصية قطعية" (we won't pretend we know)
        * Else → graded recommendation by risk band.
        """
        is_ar = lang == 'ar'

        # Night-time always: focus on battery survival
        if self.phase in _NIGHT_PHASES:
            return (
                ('فترة ليلية' if is_ar else 'Night period'),
                ('اعتمد على البطارية حتى الشروق وتجنّب الأحمال الكبيرة.'
                 if is_ar else 'Run on battery until sunrise; avoid heavy loads.'),
            )

        # Twilight (dawn or sunset): cautious posture
        if self.phase in _TWILIGHT_PHASES:
            return (
                ('وقت انتقالي' if is_ar else 'Transition window'),
                ('انتظر استقرار الإنتاج قبل تشغيل أحمال جديدة.'
                 if is_ar else 'Wait for production to stabilise before adding loads.'),
            )

        # Daytime — combine risk × confidence × surplus
        is_low_conf = confidence_band == 'low'
        is_high_risk = risk_level in {'high', 'مرتفع'}
        is_med_risk = risk_level in {'medium', 'متوسط'}
        has_surplus = surplus_kwh > 0.1

        if is_low_conf:
            return (
                ('بانتظار بناء الأرشيف' if is_ar else 'Awaiting archive'),
                ('بيانات قليلة بعد — اعتمد على القراءات الحالية بدل التوقع.'
                 if is_ar else 'Insufficient data — rely on live readings.'),
            )

        if is_high_risk and not has_surplus:
            return (
                ('أوقف الأحمال الإضافية' if is_ar else 'Stop extra loads'),
                ('الفائض المتوقع 0 والمخاطرة مرتفعة — لا تشغّل أحمالًا جديدة الآن.'
                 if is_ar else 'Expected surplus is zero — do not add new loads.'),
            )

        if is_high_risk and has_surplus:
            return (
                ('تشغيل صغير فقط' if is_ar else 'Small loads only'),
                ('شغّل أحمالًا خفيفة وقصيرة فقط.'
                 if is_ar else 'Run light and short loads only.'),
            )

        if is_med_risk:
            return (
                ('تشغيل محدود' if is_ar else 'Limited operation'),
                ('شغّل الأحمال المتوسطة، وراقب الفائض.'
                 if is_ar else 'Run medium loads and monitor surplus.'),
            )

        # Low/no risk + decent confidence
        return (
            ('وضع جيد للتشغيل' if is_ar else 'Good to operate'),
            ('يمكنك تشغيل الأحمال المعتادة بأمان.'
             if is_ar else 'You can run normal loads safely.'),
        )

    # ── advice for the weather card ───────────────────────────────────
    def weather_advice(self, lang: str = 'ar') -> tuple[str, str]:
        """Returns (advice_text, level) — advice that respects time of day.

        At 7 PM we should NOT say "best time to run appliances is between
        mid-morning and noon" — we should say "wait for tomorrow's sunrise"."""
        is_ar = lang == 'ar'

        if self.phase == 'night':
            return (
                (f'انتظر الشروق ({self.sunrise_text}). البطارية والشبكة تكفيان حتى ذلك الحين.'
                 if is_ar else
                 f'Wait for sunrise ({self.sunrise_text}). Battery + grid carry you till then.'),
                'info',
            )
        if self.phase == 'dusk':
            return (
                ('انتهى يوم الإنتاج. خفّف الأحمال الكبيرة الآن.'
                 if is_ar else 'Production day is over. Trim large loads now.'),
                'warning',
            )
        if self.phase == 'sunset':
            return (
                ('الشمس تغيب الآن. أوقف الأحمال غير الضرورية.'
                 if is_ar else 'Sun is setting now. Stop non-essential loads.'),
                'warning',
            )
        if self.phase == 'pre_sunset':
            return (
                ('تأكد من امتلاء البطارية قبل الغياب.'
                 if is_ar else 'Make sure the battery fills before the sun leaves.'),
                'warning',
            )
        if self.phase == 'dawn':
            return (
                (f'الشروق قريب ({self.sunrise_text}). الإنتاج سيبدأ بهدوء.'
                 if is_ar else f'Sunrise is near ({self.sunrise_text}). Production will start gently.'),
                'info',
            )
        if self.phase == 'sunrise':
            return (
                ('بدأ يوم جديد للإنتاج — وقت تشغيل الأحمال المتوسطة قريبًا.'
                 if is_ar else 'A new production day is starting — medium loads soon.'),
                'success',
            )
        if self.phase == 'morning':
            return (
                ('الإنتاج يتصاعد — مناسب للأحمال المتوسطة.'
                 if is_ar else 'Production is climbing — ideal for medium loads.'),
                'success',
            )
        if self.phase == 'noon':
            return (
                ('ذروة الإنتاج — وقت الذهب للأحمال الثقيلة.'
                 if is_ar else 'Production peak — golden hour for heavy loads.'),
                'success',
            )
        # afternoon
        return (
            ('الإنتاج يهدأ — ركّز على شحن البطارية ثم خفّف الأحمال تدريجيًا.'
             if is_ar else 'Output easing — focus on charging, then taper loads.'),
            'info',
        )

    # ── one-line message for the smart-prediction card ────────────────
    def smart_card_lead(self, lang: str = 'ar') -> str:
        """A single, non-conflicting opening sentence for the smart card.
        Replaces the old f-string that concatenated "sun is shining" with
        archive warnings."""
        is_ar = lang == 'ar'
        if self.phase == 'night':
            return ('🌙 فترة ليلية — البطارية والأرشيف يدعمانك حتى الشروق.'
                    if is_ar else '🌙 Night — battery + archive carry you till sunrise.')
        if self.phase == 'dusk':
            return ('🌃 الغسق — الإنتاج توقّف، الأرشيف يحدّد قرار الليل.'
                    if is_ar else '🌃 Dusk — production has stopped; archive guides the night.')
        if self.phase == 'sunset':
            return ('🌇 الشمس تغيب الآن — أنهِ الأحمال الكبيرة.'
                    if is_ar else '🌇 Sun is setting — wrap up heavy loads.')
        if self.phase == 'pre_sunset':
            return ('🌅 قبل الغروب — تأكد من امتلاء البطارية قبل الغياب.'
                    if is_ar else '🌅 Pre-sunset — finish charging before the sun leaves.')
        if self.phase == 'dawn':
            return ('🌌 الفجر — قريبًا تطلع الشمس وينبض الإنتاج.'
                    if is_ar else '🌌 Dawn — sunrise is near; production will pulse soon.')
        if self.phase == 'sunrise':
            return ('🌄 الشمس تطلع الآن — أول قطرات الإنتاج تظهر.'
                    if is_ar else '🌄 Sun is rising — the first drops of harvest.')
        if self.phase == 'noon':
            return ('☀️ ذروة النهار — الإنتاج في أعلاه.'
                    if is_ar else '☀️ Solar noon — production at its peak.')
        if self.phase == 'morning':
            return ('🌤️ الصباح — الإنتاج يتصاعد بثبات.'
                    if is_ar else '🌤️ Morning — production climbing steadily.')
        # afternoon
        return ('🌞 بعد الظهر — الإنتاج يهدأ تدريجيًا.'
                if is_ar else '🌞 Afternoon — output easing down.')


def compute_sun_context(
    latest=None,
    weather=None,
    settings=None,
    timezone_name: Optional[str] = None,
) -> SunContext:
    """Compute the unified sun context.  Safe to call with any combination
    of None inputs — falls back to sensible defaults (06:00 sunrise / 18:30
    sunset) when sunrise/sunset times are unavailable."""

    tz_name = timezone_name
    if tz_name is None and settings is not None:
        tz_name = settings.get('local_timezone') if isinstance(settings, dict) else None
    if tz_name is None:
        try:
            from flask import current_app
            tz_name = current_app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')
        except Exception:
            tz_name = 'Asia/Hebron'

    try:
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_local = datetime.now()

    sunrise_text = getattr(weather, 'sunrise_time', None) if weather else None
    sunset_text = getattr(weather, 'sunset_time', None) if weather else None
    has_weather_times = bool(sunrise_text and sunset_text)

    # Use the existing 9-phase classifier as the underlying truth.
    phase_info = classify_day_phase(now_local, sunrise_text, sunset_text)
    phase_key = phase_info['key']

    # Effective sunset (~1h before official) — production cutoff
    sunset_effective_text = sunset_text or '17:30'
    if sunset_text:
        try:
            hh, mm = sunset_text.split(':')
            eff = (int(hh) * 60 + int(mm)) - 60
            if eff < 0: eff += 24 * 60
            sunset_effective_text = f'{eff // 60:02d}:{eff % 60:02d}'
        except Exception:
            sunset_effective_text = sunset_text

    # Production-aware flags
    is_day_for_production = phase_key in _PRODUCTIVE_PHASES
    is_night = phase_key in _NIGHT_PHASES
    is_twilight = phase_key in _TWILIGHT_PHASES

    solar_power_w = 0.0
    try:
        solar_power_w = float(getattr(latest, 'solar_power', 0) or 0)
    except Exception:
        pass
    is_producing_meaningfully = is_day_for_production and solar_power_w > 100

    return SunContext(
        now_local=now_local,
        timezone_name=tz_name,
        sunrise_text=sunrise_text or phase_info.get('sunrise_text', '06:00'),
        sunset_text=sunset_text or phase_info.get('sunset_text', '18:30'),
        sunset_effective_text=sunset_effective_text,
        phase=phase_key,
        label_ar=phase_info['label_ar'],
        label_en=phase_info['label_en'],
        icon=phase_info['icon'],
        description_ar=phase_info['description_ar'],
        description_en=phase_info['description_en'],
        accent=phase_info['accent'],
        gradient=phase_info['gradient'],
        is_day_for_production=is_day_for_production,
        is_night=is_night,
        is_twilight=is_twilight,
        is_producing_meaningfully=is_producing_meaningfully,
        minutes_to_sunset=int(phase_info.get('mins_to_sunset', 0)),
        minutes_to_sunrise=int(phase_info.get('mins_to_sunrise', 0)),
        has_weather_times=has_weather_times,
    )


__all__ = ['SunContext', 'compute_sun_context']
