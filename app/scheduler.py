from __future__ import annotations

import atexit
import importlib
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Callable

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.services.service_monitor import heartbeat
from app.services.scope import get_default_system_device, get_default_system_user, reset_system_scope, set_system_scope

_scheduler: BackgroundScheduler | None = None
_scheduler_pid: int | None = None


def _log(msg: str, *args):
    text = msg % args if args else msg
    print(text, flush=True)
    logging.getLogger(__name__).info(text)


def _build_job(app, fn_path: str) -> Callable[[], None]:
    def _inner():
        with app.app_context():
            logger = app.logger
            logger.info('Scheduler job started: %s', fn_path)
            print(f'Scheduler job started: {fn_path}', flush=True)
            module_path, fn_name = fn_path.rsplit('.', 1)
            mod = importlib.import_module(module_path)
            system_user = get_default_system_user()
            system_device = get_default_system_device(system_user)
            scope_tokens = set_system_scope(getattr(system_user, 'id', None), getattr(system_device, 'id', None))
            try:
                heartbeat(fn_path, fn_path, 'running', 'بدأت المهمة', source='scheduler')
                getattr(mod, fn_name)()
                heartbeat(fn_path, fn_path, 'ok', 'اكتملت المهمة بنجاح', source='scheduler')
                logger.info('Scheduler job finished: %s', fn_path)
                print(f'Scheduler job finished: {fn_path}', flush=True)
            except Exception as exc:
                heartbeat(fn_path, fn_path, 'failed', f'فشلت المهمة: {exc}', source='scheduler')
                logger.exception('Scheduled job failed: %s', fn_path)
                print(f'Scheduled job failed: {fn_path}', flush=True)
                raise
            finally:
                reset_system_scope(scope_tokens)
    return _inner


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
            'func': _build_job(app, 'app.blueprints.notifications.run_advanced_notification_scheduler'),
            'trigger': IntervalTrigger(seconds=30, timezone=timezone_name),
            'next_run_time': now_utc + timedelta(seconds=15),
        },
        {
            'id': 'weather_change_check',
            'func': _build_job(app, 'app.blueprints.notifications.run_weather_checks'),
            'trigger': IntervalTrigger(minutes=10, timezone=timezone_name),
            'next_run_time': now_utc + timedelta(seconds=20),
        },
        {
            'id': 'weather_daily_summary',
            'func': _build_job(app, 'app.blueprints.notifications.send_daily_weather_summary'),
            'trigger': CronTrigger(hour=7, minute=0, timezone=timezone_name),
        },
        {
            'id': 'daily_morning_report',
            'func': _build_job(app, 'app.blueprints.notifications.send_daily_morning_report'),
            'trigger': CronTrigger(hour=9, minute=5, timezone=timezone_name),
        },
        {
            'id': 'database_backup_maintenance',
            'func': _build_job(app, 'app.services.backup_service.scheduled_backup_job'),
            'trigger': CronTrigger(hour=2, minute=15, timezone=timezone_name),
        },
    ]

    if app.config.get('AUTO_SYNC_ENABLED', True):
        sync_minutes = max(int(app.config.get('AUTO_SYNC_MINUTES', 5)), 1)
        job_specs.insert(0, {
            'id': 'deye_auto_sync',
            'func': _build_job(app, 'app.blueprints.main.sync_now_internal'),
            'trigger': IntervalTrigger(minutes=sync_minutes, timezone=timezone_name),
            'next_run_time': now_utc + timedelta(seconds=10),
        })
    else:
        _log('Scheduler: AUTO_SYNC disabled, sync job not added')

    for spec in job_specs:
        scheduler.add_job(
            spec['func'],
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

    _log('Scheduler started in pid=%s with jobs=%s', current_pid, [j.id for j in scheduler.get_jobs()])
    try:
        heartbeat('scheduler', 'Internal Scheduler', 'ok', 'Scheduler started and jobs are registered.', source='scheduler', details={'pid': current_pid, 'jobs': [j.id for j in scheduler.get_jobs()]})
    except Exception:
        pass

    try:
        atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
    except Exception:
        pass

    return scheduler
