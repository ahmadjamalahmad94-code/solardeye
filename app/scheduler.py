from __future__ import annotations

import atexit
import importlib
import json
import logging
import os
import time
try:
    from datetime import UTC, datetime, timedelta            # Python 3.11+
except ImportError:                                          # Python 3.10 fallback
    from datetime import datetime, timedelta, timezone as _tz
    UTC = _tz.utc
from hashlib import sha256
from typing import Any, Callable, Iterable

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.services.service_monitor import heartbeat, service_display_name
from app.services.scope import (
    get_default_system_device,
    get_default_system_user,
    reset_system_scope,
    set_system_scope,
    current_scope_ids,
)

_scheduler: BackgroundScheduler | None = None
_scheduler_pid: int | None = None


# ════════════════════════════════════════════════════════════════════════
# v33-α — fan-out helpers
# ────────────────────────────────────────────────────────────────────────
# Per-provider rate-limit defaults. Conservative — rather wait an extra
# half-second than trip a provider 429. Override at runtime via the
# environment variable PROVIDER_THROTTLE_OVERRIDES which accepts a JSON
# object like {"deye": 1.0, "solarman": 2.0}.
# ════════════════════════════════════════════════════════════════════════

_PROVIDER_THROTTLE_DEFAULTS: dict[str, float] = {
    'deye':     0.5,   # Deye allows ~60 req/min/account → 1 req/sec; we cap at 2 req/sec
    'solarman': 1.0,   # SolarMan public docs are quieter; assume 1 req/sec safe
    'tuya':     0.3,   # Tuya is more permissive
    'huawei':   0.5,
    'goodwe':   0.5,
}

_GLOBAL_JOB_IDS: frozenset[str] = frozenset({
    'database_backup_maintenance',  # DB-wide, not per-device
})

# Job-id → fn_path mapping mode.  PER_DEVICE jobs fan out across
# AppDevice.query.filter_by(is_active=True).
_PER_DEVICE_JOB_IDS: frozenset[str] = frozenset({
    'deye_auto_sync',
    'advanced_notifications_check',
    'weather_change_check',
    'weather_daily_summary',
    'daily_morning_report',
})


def _log(msg: str, *args):
    text = msg % args if args else msg
    print(text, flush=True)
    logging.getLogger(__name__).info(text)


def _provider_account_signature(device) -> str:
    """Group key for devices that share one cloud account.

    For Deye, the account is identified by (deye_app_id, deye_email).
    Devices with identical (provider, account) reuse one auth token
    and are throttled within the same provider-cooldown window.
    Falls back to ``provider:device-{id}`` when credentials are absent
    so each unidentifiable device becomes its own group.
    """
    provider = (getattr(device, 'api_provider', None)
                or getattr(device, 'device_type', None)
                or '').strip().lower()
    raw = getattr(device, 'credentials_json', '') or ''
    try:
        creds = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        creds = {}
    # Compose an identity key per provider family
    if provider in ('deye', 'sunsynk', 'sol-ark'):
        ident = f"{creds.get('deye_app_id') or ''}|{creds.get('deye_email') or creds.get('email') or ''}"
    elif provider == 'solarman':
        ident = f"{creds.get('solarman_token') or creds.get('token') or ''}"
    elif provider == 'tuya':
        ident = f"{creds.get('tuya_access_id') or ''}|{creds.get('tuya_uid') or ''}"
    else:
        ident = json.dumps(creds, sort_keys=True) if creds else f'device-{getattr(device, "id", "?")}'
    digest = sha256(ident.encode('utf-8')).hexdigest()[:16]
    return f'{provider}:{digest}'


def _throttle_for_provider(provider_code: str) -> float:
    """Return the conservative inter-call sleep (seconds) for ``provider_code``.

    Overridable via ``PROVIDER_THROTTLE_OVERRIDES`` env var (JSON dict).
    Unknown providers default to 0.0 (no sleep).
    """
    code = (provider_code or '').strip().lower()
    if not code:
        return 0.0
    overrides_raw = os.environ.get('PROVIDER_THROTTLE_OVERRIDES', '').strip()
    if overrides_raw:
        try:
            overrides = json.loads(overrides_raw)
            if isinstance(overrides, dict) and code in overrides:
                v = overrides[code]
                return max(float(v), 0.0)
        except Exception:
            _log('Scheduler: invalid PROVIDER_THROTTLE_OVERRIDES — ignored')
    return _PROVIDER_THROTTLE_DEFAULTS.get(code, 0.0)


def _invoke(fn_path: str) -> None:
    """Import-and-call helper. Mirrors the original v32 _build_job behaviour."""
    module_path, fn_name = fn_path.rsplit('.', 1)
    mod = importlib.import_module(module_path)
    if fn_path == 'app.blueprints.main.sync_now_internal':
        getattr(mod, fn_name)(trigger='auto')
    else:
        getattr(mod, fn_name)()


def _active_device_query():
    """Return a query for active AppDevice rows. Swappable in tests."""
    from app.models import AppDevice
    return AppDevice.query.filter_by(is_active=True).order_by(AppDevice.id.asc())


def _should_persist_logs() -> bool:
    """In tests we monkeypatch this to False to skip DB writes."""
    return True


def _persist_sync_log(level: str, message: str, user_id: int | None, device_id: int | None) -> None:
    """Write a SyncLog row, swallowing any DB exception (best-effort logging)."""
    if not _should_persist_logs():
        return
    try:
        from app.extensions import db
        from app.models import SyncLog
        db.session.add(SyncLog(level=level, message=message,
                               user_id=user_id, device_id=device_id))
        db.session.commit()
    except Exception as exc:
        _log('Scheduler: SyncLog persist failed: %s', exc)
        try:
            from app.extensions import db
            db.session.rollback()
        except Exception:
            pass


def _run_per_device_no_app(fn_path: str) -> dict[str, Any]:
    """Core fan-out loop, app-context-free for unit tests.

    Returns a summary dict: ``{'ok': [device_ids], 'failed': [device_ids],
    'groups': N, 'devices': N, 'fn_path': fn_path}``.
    """
    devices = list(_active_device_query().all())
    summary: dict[str, Any] = {
        'fn_path': fn_path, 'groups': 0, 'devices': len(devices),
        'ok': [], 'failed': [], 'throttled': [],
    }
    if not devices:
        _log('[v33-α] %s: no active devices, skipping', fn_path)
        return summary

    # Group devices by provider account signature
    groups: dict[str, list] = {}
    for d in devices:
        groups.setdefault(_provider_account_signature(d), []).append(d)
    summary['groups'] = len(groups)

    cycle_started_at = time.monotonic()

    for sig, group in groups.items():
        provider_code = (getattr(group[0], 'api_provider', None) or '').lower()
        sleep_s = _throttle_for_provider(provider_code)

        for d in group:
            d_id = getattr(d, 'id', None)
            owner = getattr(d, 'owner_user_id', None)
            tokens = set_system_scope(owner, d_id)
            t0 = time.monotonic()
            try:
                _invoke(fn_path)
                elapsed = time.monotonic() - t0
                _log('[v33-α] %s device_id=%s ok elapsed=%.2fs', fn_path, d_id, elapsed)
                _persist_sync_log('info',
                                  f'{fn_path} ok ({elapsed:.2f}s)',
                                  owner, d_id)
                summary['ok'].append(d_id)
                _safe_heartbeat(f'{fn_path}::device-{d_id}', 'ok',
                                f'{fn_path} ok ({elapsed:.2f}s) device={getattr(d, "name", "")}',
                                {'device_id': d_id, 'owner': owner, 'elapsed_s': round(elapsed, 3)})
            except Exception as exc:
                msg = str(exc)[:200]
                low = msg.lower()
                if '429' in low or 'rate' in low or 'too many' in low:
                    summary['throttled'].append(d_id)
                    _log('[v33-α] %s device_id=%s RATE_LIMITED: %s', fn_path, d_id, msg)
                    _persist_sync_log('warning',
                                      f'{fn_path} rate_limited: {msg}',
                                      owner, d_id)
                    _safe_heartbeat(f'{fn_path}::device-{d_id}', 'throttled', msg,
                                    {'device_id': d_id, 'owner': owner})
                else:
                    summary['failed'].append(d_id)
                    _log('[v33-α] %s device_id=%s FAILED: %s', fn_path, d_id, msg)
                    _persist_sync_log('error',
                                      f'{fn_path} failed: {msg}',
                                      owner, d_id)
                    _safe_heartbeat(f'{fn_path}::device-{d_id}', 'failed', msg,
                                    {'device_id': d_id, 'owner': owner})
            finally:
                reset_system_scope(tokens)
                if sleep_s > 0:
                    time.sleep(sleep_s)

    elapsed = time.monotonic() - cycle_started_at
    _log('[v33-α] fan_out fn=%s groups=%d devices=%d ok=%d fail=%d throttled=%d elapsed=%.2fs',
         fn_path, summary['groups'], summary['devices'],
         len(summary['ok']), len(summary['failed']), len(summary['throttled']),
         elapsed)
    return summary


def _safe_heartbeat(key: str, status: str, message: str, details: dict | None = None) -> None:
    try:
        heartbeat(key, service_display_name(key, 'en'), status, message,
                  source='scheduler', details=details)
    except Exception:
        pass


def _run_per_device(app, fn_path: str) -> None:
    """App-context wrapper around the per-device fan-out loop."""
    with app.app_context():
        _safe_heartbeat(fn_path, 'running', f'{fn_path} fan-out cycle started', None)
        try:
            summary = _run_per_device_no_app(fn_path)
        except Exception as exc:
            _safe_heartbeat(fn_path, 'failed', f'fan_out crashed: {exc}', None)
            logging.getLogger(__name__).exception('fan_out crashed: %s', fn_path)
            raise
        # Aggregate cycle status: ok / partial / failed
        if summary['devices'] == 0:
            status = 'idle'
            msg = 'no active devices'
        elif summary['failed'] and not summary['ok']:
            status = 'failed'
            msg = f"all {summary['devices']} devices failed"
        elif summary['failed']:
            status = 'partial'
            msg = (f"{len(summary['ok'])}/{summary['devices']} ok, "
                   f"{len(summary['failed'])} failed, "
                   f"{len(summary['throttled'])} throttled")
        else:
            status = 'ok'
            msg = f"{summary['devices']} devices ok"
        _safe_heartbeat(fn_path, status, msg, summary)


def _run_once_global(app, fn_path: str) -> None:
    """Global (non-fan-out) job runner — preserves the v32 behaviour
    for jobs that must NOT iterate over devices."""
    with app.app_context():
        _safe_heartbeat(fn_path, 'running', 'بدأت المهمة', None)
        try:
            _invoke(fn_path)
            _safe_heartbeat(fn_path, 'ok', 'اكتملت المهمة بنجاح', None)
            _log('Scheduler global job finished: %s', fn_path)
        except Exception as exc:
            _safe_heartbeat(fn_path, 'failed', f'فشلت المهمة: {exc}', None)
            logging.getLogger(__name__).exception('Scheduled job failed: %s', fn_path)
            raise


def _build_job(app, fn_path: str, job_id: str | None = None) -> Callable[[], None]:
    """Return the APScheduler-callable wrapper for ``fn_path``.

    v33-α: routes per-device jobs through the fan-out helper, leaves
    global jobs running once per cycle as before.
    """
    if job_id and job_id in _GLOBAL_JOB_IDS:
        def _global_wrapper():
            _run_once_global(app, fn_path)
        return _global_wrapper
    if job_id and job_id in _PER_DEVICE_JOB_IDS:
        def _per_device_wrapper():
            _run_per_device(app, fn_path)
        return _per_device_wrapper

    # Fallback (no job_id supplied) — preserve v32 single-scope behaviour
    def _legacy_inner():
        with app.app_context():
            logger = app.logger
            logger.info('Scheduler job started: %s', fn_path)
            print(f'Scheduler job started: {fn_path}', flush=True)
            system_user = get_default_system_user()
            system_device = get_default_system_device(system_user)
            scope_tokens = set_system_scope(getattr(system_user, 'id', None),
                                            getattr(system_device, 'id', None))
            try:
                _safe_heartbeat(fn_path, 'running', 'بدأت المهمة', None)
                _invoke(fn_path)
                _safe_heartbeat(fn_path, 'ok', 'اكتملت المهمة بنجاح', None)
                logger.info('Scheduler job finished: %s', fn_path)
                print(f'Scheduler job finished: {fn_path}', flush=True)
            except Exception as exc:
                _safe_heartbeat(fn_path, 'failed', f'فشلت المهمة: {exc}', None)
                logger.exception('Scheduled job failed: %s', fn_path)
                print(f'Scheduled job failed: {fn_path}', flush=True)
                raise
            finally:
                reset_system_scope(scope_tokens)
    return _legacy_inner


def _listener(event):
    if event.exception:
        _log('Scheduler listener: job %s failed', event.job_id)
    elif event.code == EVENT_JOB_MISSED:
        _log('Scheduler listener: job %s missed', event.job_id)
    else:
        _log('Scheduler listener: job %s executed', event.job_id)


def start_scheduler(app) -> BackgroundScheduler:
    global _scheduler, _scheduler_pid

    if os.environ.get('DISABLE_INTERNAL_SCHEDULER', '').lower() == 'true':
        _log('Scheduler disabled by DISABLE_INTERNAL_SCHEDULER=true')
        return _scheduler

    current_pid = os.getpid()
    if _scheduler is not None and _scheduler.running and _scheduler_pid == current_pid:
        _log('Scheduler already running in pid=%s', current_pid)
        return _scheduler

    if _scheduler is not None and _scheduler.running and _scheduler_pid != current_pid:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None

    timezone_name = app.config.get('LOCAL_TIMEZONE', 'Asia/Hebron')
    scheduler = BackgroundScheduler(
        timezone=timezone_name,
        daemon=True,
        job_defaults={
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 180,
        },
    )

    now_utc = datetime.now(UTC)
    job_specs = [
        {
            'id': 'advanced_notifications_check',
            'fn_path': 'app.blueprints.notifications.run_advanced_notification_scheduler',
            'trigger': IntervalTrigger(seconds=30, timezone=timezone_name),
            'next_run_time': now_utc + timedelta(seconds=15),
        },
        {
            'id': 'weather_change_check',
            'fn_path': 'app.blueprints.notifications.run_weather_checks',
            'trigger': IntervalTrigger(minutes=10, timezone=timezone_name),
            'next_run_time': now_utc + timedelta(seconds=20),
        },
        {
            'id': 'weather_daily_summary',
            'fn_path': 'app.blueprints.notifications.send_daily_weather_summary',
            'trigger': CronTrigger(hour=7, minute=0, timezone=timezone_name),
        },
        {
            'id': 'daily_morning_report',
            'fn_path': 'app.blueprints.notifications.send_daily_morning_report',
            'trigger': CronTrigger(hour=9, minute=5, timezone=timezone_name),
        },
        {
            'id': 'database_backup_maintenance',
            'fn_path': 'app.services.backup_service.scheduled_backup_job',
            'trigger': CronTrigger(hour=2, minute=15, timezone=timezone_name),
        },
    ]

    if app.config.get('AUTO_SYNC_ENABLED', True):
        sync_minutes = max(int(app.config.get('AUTO_SYNC_MINUTES', 5)), 1)
        job_specs.insert(0, {
            'id': 'deye_auto_sync',
            'fn_path': 'app.blueprints.main.sync_now_internal',
            'trigger': IntervalTrigger(minutes=sync_minutes, timezone=timezone_name),
            'next_run_time': now_utc + timedelta(seconds=10),
        })
    else:
        _log('Scheduler: AUTO_SYNC disabled, sync job not added')

    for spec in job_specs:
        scheduler.add_job(
            _build_job(app, spec['fn_path'], job_id=spec['id']),
            trigger=spec['trigger'],
            id=spec['id'],
            replace_existing=True,
            next_run_time=spec.get('next_run_time'),
        )

    scheduler.add_listener(_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    scheduler.start()

    _scheduler = scheduler
    _scheduler_pid = current_pid
    app.scheduler = scheduler
    app._scheduler_started = True

    _log('Scheduler started in pid=%s with jobs=%s [v33-α fan-out enabled]',
         current_pid, [j.id for j in scheduler.get_jobs()])
    try:
        heartbeat('scheduler', 'Internal Scheduler', 'ok',
                  'Scheduler started and jobs are registered (v33-α fan-out).',
                  source='scheduler',
                  details={'pid': current_pid,
                           'jobs': [j.id for j in scheduler.get_jobs()],
                           'per_device_jobs': sorted(_PER_DEVICE_JOB_IDS),
                           'global_jobs': sorted(_GLOBAL_JOB_IDS)})
    except Exception:
        pass

    try:
        atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
    except Exception:
        pass

    return scheduler
