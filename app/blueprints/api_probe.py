"""
API Probe — يجرب كل endpoint ممكن في Deye API ويعرض النتائج
"""
from __future__ import annotations
import time
from datetime import datetime

import requests
from flask import Blueprint, render_template, request, current_app

from .helpers import load_settings
from ..services.utils import sha256_hex
from ..services.scope import is_system_admin
from ..services.security import sanitize_response_payload

probe_bp = Blueprint('probe', __name__)

_EU   = 'https://eu1-developer.deyecloud.com/v1.0'
_DEV  = 'https://www.deyecloud.com/device-s'
_GLOB = 'https://developer.deyecloud.com/v1.0'


def _debug_tools_guard():
    if not is_system_admin():
        return False, ("Debug tools require an administrator account.", 403)
    if not current_app.config.get('DEBUG_TOOLS_ENABLED'):
        return False, ("Debug tools are disabled in this environment. Set DEBUG_TOOLS_ENABLED=true to enable them temporarily.", 403)
    return True, None


def _call(session, method, url, token=None, body=None, params=None, timeout=12):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    t0 = time.time()
    try:
        if method == 'GET':
            r = session.get(url, headers=headers, params=params or {}, timeout=timeout)
        else:
            r = session.post(url, headers=headers, json=body or {}, params=params or {}, timeout=timeout)
        ms = int((time.time() - t0) * 1000)
        try:
            data = r.json()
        except Exception:
            data = {'_raw': r.text[:600]}
        return {'ok': r.ok, 'status': r.status_code, 'ms': ms, 'data': data, 'error': None}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {'ok': False, 'status': 0, 'ms': ms, 'data': {}, 'error': str(e)}


def _has_data(result: dict) -> bool:
    """True if response looks like real useful data (not an error or empty)."""
    if not result['ok']:
        return False
    d = result['data']
    if not isinstance(d, dict):
        return False
    code = str(d.get('code', ''))
    success = d.get('success', True)
    if code and code not in ('1000000', '0', ''):
        return False
    if success is False:
        return False
    # Must have more than just status fields
    meaningful_keys = [k for k in d if k not in ('code', 'msg', 'success', 'requestId')]
    return len(meaningful_keys) >= 1


def run_probe(settings: dict) -> dict:
    app_id        = (settings.get('deye_app_id') or '').strip()
    app_secret    = (settings.get('deye_app_secret') or '').strip()
    email         = (settings.get('deye_email') or '').strip()
    password      = (settings.get('deye_password') or '').strip()
    pw_hash       = (settings.get('deye_password_hash') or sha256_hex(password)).strip()
    plant_id      = (settings.get('deye_plant_id') or '').strip()
    device_sn     = (settings.get('deye_device_sn') or '').strip()
    logger_sn     = (settings.get('deye_logger_sn') or '').strip()
    bat_main      = (settings.get('deye_battery_sn_main') or '').strip()
    bat_module    = (settings.get('deye_battery_sn_module') or '').strip()

    results = []
    session = requests.Session()

    def rec(name, category, result, note=''):
        results.append({
            'name': name, 'category': category,
            'ok': result['ok'], 'has_data': _has_data(result),
            'status': result['status'], 'ms': result['ms'],
            'note': note, 'data': result['data'], 'error': result.get('error'),
        })

    # ── 1. Token ──────────────────────────────────────────────────────────────
    token_res = _call(session, 'POST', f'{_EU}/account/token',
                      params={'appId': app_id},
                      body={'appSecret': app_secret, 'email': email, 'password': pw_hash})
    rec('POST /account/token', 'auth', token_res, 'الخطوة الأولى — الحصول على Access Token')

    # Extract token
    token = None
    d = token_res['data']
    for path in ['accessToken', 'token']:
        if d.get(path): token = d[path]; break
    if not token and isinstance(d.get('data'), dict):
        for path in ['accessToken', 'token']:
            if d['data'].get(path): token = d['data'][path]; break

    if not token:
        rec('⛔ فشل الـ Token — باقي الاختبارات ملغاة', 'error',
            {'ok': False, 'status': 0, 'ms': 0, 'data': {}, 'error': None},
            'تأكد من APP_ID / APP_SECRET / EMAIL / PASSWORD')
        session.close()
        return {'results': results, 'token': None, 'summary': _summary(results)}

    tok_display = token[:20] + '...'

    # ── 2. Account ────────────────────────────────────────────────────────────
    rec('POST /account/info', 'account',
        _call(session, 'POST', f'{_EU}/account/info', token=token),
        'معلومات الحساب والصلاحيات')

    # ── 3. Stations ───────────────────────────────────────────────────────────
    rec('POST /station/list', 'station',
        _call(session, 'POST', f'{_EU}/station/list', token=token, body={'page': 1, 'size': 20}),
        'قائمة المحطات المرتبطة بالحساب')

    if plant_id:
        pid = int(plant_id)

        rec('POST /station/latest', 'station',
            _call(session, 'POST', f'{_EU}/station/latest', token=token, body={'stationId': pid}),
            'البيانات اللحظية (القدرة، SOC، إلخ)')

        rec('POST /station/history', 'station',
            _call(session, 'POST', f'{_EU}/station/history', token=token, body={'stationId': pid}),
            'بيانات تاريخية (قد ترجع فارغة للحسابات الشخصية)')

        rec('POST /station/device/list', 'station',
            _call(session, 'POST', f'{_EU}/station/device/list', token=token,
                  body={'stationId': pid, 'page': 1, 'size': 20}),
            'قائمة الأجهزة — تُعيد deviceId اللازم لـ device/originalData')

        # ── 4. Energy endpoints ───────────────────────────────────────────────
        today = datetime.now().strftime('%Y-%m-%d')
        month = today[:7]
        year  = today[:4]

        for ep, body, note in [
            ('energy/day',   {'stationId': pid, 'date': today},  f'إنتاج اليوم {today}'),
            ('energy/month', {'stationId': pid, 'date': month},  f'إنتاج الشهر {month}'),
            ('energy/year',  {'stationId': pid, 'date': year},   f'إنتاج السنة {year}'),
            ('energy/total', {'stationId': pid},                  'الإجمالي الكلي منذ البداية'),
            ('energy/flow',  {'stationId': pid},                  'تدفق الطاقة'),
        ]:
            rec(f'POST /station/{ep}', 'energy',
                _call(session, 'POST', f'{_EU}/station/{ep}', token=token, body=body), note)

        # Extra station endpoints
        for ep, note in [
            ('realtime',  'بيانات realtime مفصلة'),
            ('battery',   'بيانات البطارية المفصلة'),
            ('overview',  'ملخص المحطة'),
            ('alarm',     'قائمة التنبيهات والأعطال'),
        ]:
            rec(f'POST /station/{ep}', 'station_extra',
                _call(session, 'POST', f'{_EU}/station/{ep}', token=token, body={'stationId': pid}), note)

    # ── 5. device/originalData — try every SN ─────────────────────────────────
    sns = []
    if logger_sn:   sns.append(('Logger SN',      logger_sn))
    if device_sn:   sns.append(('Inverter SN',     device_sn))
    if bat_main:    sns.append(('Battery Main',    bat_main))
    if bat_module:  sns.append(('Battery Module',  bat_module))
    if plant_id:    sns.append(('Plant ID',        plant_id))

    for label, sn in sns:
        rec(f'GET  /device/originalData [{label}: {sn}]', 'device',
            _call(session, 'GET', f'{_DEV}/device/originalData', token=token, params={'deviceId': sn}),
            'بيانات خام السجلات (PV، جهد، حرارة، BMS)')

        rec(f'POST /device/originalData [{label}: {sn}]', 'device',
            _call(session, 'POST', f'{_DEV}/device/originalData', token=token, body={'deviceId': sn}),
            'نفس الـ endpoint بـ POST')

    # ── 6. Device endpoints (deviceSn based) ─────────────────────────────────
    # These may work for personal accounts using deviceSn directly
    dev_sns = []
    if device_sn:   dev_sns.append(('Inverter SN', device_sn))
    if logger_sn:   dev_sns.append(('Logger SN',   logger_sn))

    for label, sn in dev_sns:
        rec(f'POST /device/latest [{label}: {sn}]', 'device_sn',
            _call(session, 'POST', f'{_EU}/device/latest', token=token, body={'deviceList': [sn]}),
            'أحدث بيانات الجهاز — يتضمن SOC، إنتاج يومي/شهري/كلي، جهد، تيار')

        rec(f'POST /device/measurePoints [{label}: {sn}]', 'device_sn',
            _call(session, 'POST', f'{_EU}/device/measurePoints', token=token, body={'deviceSn': sn}),
            'قائمة المقاييس المتاحة للجهاز (SOC, PV1_V, INV_T...)')

        today = datetime.now().strftime('%Y-%m-%d')
        rec(f'POST /device/history (day) [{label}: {sn}]', 'device_sn',
            _call(session, 'POST', f'{_EU}/device/history', token=token, body={
                'deviceSn': sn, 'granularity': 1, 'startAt': today, 'endAt': today,
                'measurePoints': ['SOC', 'generationPower', 'batteryPower']
            }), 'تاريخ اليوم (granularity=1)')

        rec(f'POST /device/list', 'device_sn',
            _call(session, 'POST', f'{_EU}/device/list', token=token, body={'page': 1, 'size': 20}),
            'قائمة كل الأجهزة في الحساب')

    # ── 7. station/device endpoint (different from station/device/list) ────────
    if plant_id:
        rec('POST /station/device', 'device_sn',
            _call(session, 'POST', f'{_EU}/station/device', token=token,
                  body={'page': 1, 'size': 10, 'stationIds': [int(plant_id)]}),
            'أجهزة المحطة — نسخة مختلفة من device/list')

        rec('POST /station/listWithDevice', 'device_sn',
            _call(session, 'POST', f'{_EU}/station/listWithDevice', token=token,
                  body={'page': 1, 'size': 10, 'deviceType': 'INVERTER'}),
            'قائمة المحطات مع أجهزتها — تعطي deviceSn')

    # ── 8. Alternate base URLs ─────────────────────────────────────────────────
    if plant_id:
        rec('POST /station/latest (Global URL)', 'alt_url',
            _call(session, 'POST', f'{_GLOB}/station/latest', token=token, body={'stationId': int(plant_id)}),
            'تجربة الـ Global URL بدل EU')

    session.close()
    return {'results': results, 'token': tok_display, 'summary': _summary(results)}


def _summary(results):
    working = [r for r in results if r['has_data']]
    return {
        'total':   len(results),
        'working': len(working),
        'failed':  len([r for r in results if not r['ok']]),
        'working_names': [r['name'] for r in working],
    }


@probe_bp.route('/api-probe')
def api_probe_page():
    ok, guard = _debug_tools_guard()
    if not ok:
        message, status = guard
        return render_template('error.html', code=status, message=message), status
    settings = load_settings()
    probe_data = None
    if request.args.get('run') == '1':
        probe_data = sanitize_response_payload(run_probe(settings))
    return render_template('api_probe.html', settings=settings, probe=probe_data)


@probe_bp.route('/api/device-inspect')
def device_inspect():
    """Full data dump from all working device endpoints — use this to find field names."""
    ok, guard = _debug_tools_guard()
    if not ok:
        message, status = guard
        return {'ok': False, 'error': message}, status
    settings = load_settings()
    device_sn = (settings.get('deye_device_sn') or '').strip()
    logger_sn  = (settings.get('deye_logger_sn') or '').strip()
    plant_id   = (settings.get('deye_plant_id') or '').strip()

    import requests as _req
    session = _req.Session()
    result = {}

    try:
        # Get token
        pw = settings.get('deye_password_hash') or sha256_hex(settings.get('deye_password',''))
        r = session.post(f'{_EU}/account/token',
            params={'appId': settings.get('deye_app_id','')},
            headers={'Content-Type': 'application/json'},
            json={'appSecret': settings.get('deye_app_secret',''),
                  'email': settings.get('deye_email',''), 'password': pw},
            timeout=15)
        td = r.json()
        token = (td.get('accessToken') or td.get('token') or
                 (td.get('data') or {}).get('accessToken') or
                 (td.get('data') or {}).get('token'))

        if not token:
            return sanitize_response_payload({'error': 'Token failed', 'response': td})

        headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}

        # device/latest for inverter SN
        if device_sn:
            r = session.post(f'{_EU}/device/latest', headers=headers,
                             json={'deviceList': [device_sn]}, timeout=15)
            result['device_latest_inverter'] = r.json()

        # device/latest for logger SN
        if logger_sn:
            r = session.post(f'{_EU}/device/latest', headers=headers,
                             json={'deviceList': [logger_sn]}, timeout=15)
            result['device_latest_logger'] = r.json()

        # device/measurePoints
        if device_sn:
            r = session.post(f'{_EU}/device/measurePoints', headers=headers,
                             json={'deviceSn': device_sn}, timeout=15)
            result['measure_points_inverter'] = r.json()

        if logger_sn:
            r = session.post(f'{_EU}/device/measurePoints', headers=headers,
                             json={'deviceSn': logger_sn}, timeout=15)
            result['measure_points_logger'] = r.json()

        from datetime import datetime as _dt
        today = _dt.now().strftime('%Y-%m-%d')
        this_month = _dt.now().strftime('%Y-%m')
        this_year  = _dt.now().strftime('%Y')
        last_month_start = (_dt.now().replace(day=1) - __import__('datetime').timedelta(days=1)).strftime('%Y-%m')

        if device_sn:
            # granularity=2: daily history for this month
            r = session.post(f'{_EU}/device/history', headers=headers,
                             json={'deviceSn': device_sn, 'granularity': 2,
                                   'startAt': _dt.now().replace(day=1).strftime('%Y-%m-%d'),
                                   'endAt': today,
                                   'measurePoints': ['dailyProductionActive',
                                       'dailyConsumption', 'dailyChargingEnergy',
                                       'dailyDischargingEnergy']},
                             timeout=15)
            result['device_history_daily_this_month'] = r.json()

            # granularity=3: monthly history for this year
            r = session.post(f'{_EU}/device/history', headers=headers,
                             json={'deviceSn': device_sn, 'granularity': 3,
                                   'startAt': this_year + '-01',
                                   'endAt': this_month,
                                   'measurePoints': ['dailyProductionActive',
                                       'dailyConsumption', 'totalChargingEnergy']},
                             timeout=15)
            result['device_history_monthly_this_year'] = r.json()

            # granularity=1: today's BMS data (few points to avoid 'list too long')
            r = session.post(f'{_EU}/device/history', headers=headers,
                             json={'deviceSn': device_sn, 'granularity': 1,
                                   'startAt': today, 'endAt': today,
                                   'measurePoints': ['soc', 'batteryVoltage',
                                       'bmsTemperature', 'batteryPower',
                                       'dcPowerPv1', 'dcPowerPv2',
                                       'totalConsumptionPower']},
                             timeout=15)
            result['device_history_today_bms'] = r.json()

        # station/listWithDevice
        if plant_id:
            r = session.post(f'{_EU}/station/listWithDevice', headers=headers,
                             json={'page': 1, 'size': 10, 'deviceType': 'INVERTER'}, timeout=15)
            result['station_list_with_device'] = r.json()

        # station/device
        if plant_id:
            r = session.post(f'{_EU}/station/device', headers=headers,
                             json={'page': 1, 'size': 10, 'stationIds': [int(plant_id)]}, timeout=15)
            result['station_device'] = r.json()

    except Exception as e:
        result['error'] = str(e)
    finally:
        session.close()

    return sanitize_response_payload(result)
