from __future__ import annotations

import gzip
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy import text

from ..extensions import db
from ..models import Setting
from .service_monitor import heartbeat

BACKUP_SETTING_KEYS = {
    'backup_enabled': 'true',
    'backup_frequency': 'daily',
    'backup_keep_local': '12',
    'backup_drive_enabled': 'false',
    'backup_drive_folder_id': '',
    'backup_last_at': '',
}


def _setting(key: str, default: str = '') -> str:
    row = Setting.query.filter_by(key=key).first()
    return (row.value if row and row.value is not None else default) or ''


def set_setting(key: str, value: str):
    row = Setting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))


def ensure_backup_settings():
    changed = False
    for key, default in BACKUP_SETTING_KEYS.items():
        if Setting.query.filter_by(key=key).first() is None:
            db.session.add(Setting(key=key, value=default))
            changed = True
    if changed:
        db.session.commit()


def backup_settings() -> dict[str, str]:
    ensure_backup_settings()
    cfg = {key: _setting(key, default) for key, default in BACKUP_SETTING_KEYS.items()}
    # Environment variables can enable Drive upload without storing secrets in DB.
    if current_app.config.get('GOOGLE_DRIVE_BACKUP_ENABLED'):
        cfg['backup_drive_enabled'] = 'true'
    if current_app.config.get('GOOGLE_DRIVE_BACKUP_FOLDER_ID') and not cfg.get('backup_drive_folder_id'):
        cfg['backup_drive_folder_id'] = current_app.config.get('GOOGLE_DRIVE_BACKUP_FOLDER_ID') or ''
    return cfg


def backup_dir() -> Path:
    folder = Path(current_app.instance_path) / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _serialize_database() -> dict[str, Any]:
    payload = {
        'created_at': datetime.utcnow().isoformat(),
        'app': 'SolarDeye',
        'version': 'heavy-v7.1',
        'dialect': db.engine.dialect.name,
        'tables': {},
    }
    with db.engine.connect() as conn:
        for table in db.metadata.sorted_tables:
            rows = []
            result = conn.execute(table.select())
            for row in result.mappings():
                rows.append(dict(row))
            payload['tables'][table.name] = rows
    return payload


def create_backup(reason: str = 'manual', upload_drive: bool | None = None) -> dict[str, Any]:
    ensure_backup_settings()
    now = datetime.utcnow()
    filename = f'solardeye_backup_{now.strftime("%Y%m%d_%H%M%S")}_{reason}.json.gz'
    path = backup_dir() / filename
    payload = _serialize_database()
    with gzip.open(path, 'wt', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, default=_json_default)

    raw_copy = None
    if db.engine.dialect.name == 'sqlite':
        db_path = str(db.engine.url.database or '')
        if db_path and Path(db_path).exists():
            raw_copy = backup_dir() / f'sqlite_raw_{now.strftime("%Y%m%d_%H%M%S")}.db'
            shutil.copy2(db_path, raw_copy)

    drive_result = None
    settings = backup_settings()
    should_upload = upload_drive if upload_drive is not None else str(settings.get('backup_drive_enabled')).lower() == 'true'
    if should_upload:
        drive_result = upload_to_google_drive(path, folder_id=settings.get('backup_drive_folder_id') or current_app.config.get('GOOGLE_DRIVE_BACKUP_FOLDER_ID'))

    keep = int(settings.get('backup_keep_local') or current_app.config.get('BACKUP_KEEP_LOCAL', 12) or 12)
    prune_backups(keep=keep)
    set_setting('backup_last_at', now.isoformat())
    db.session.commit()
    heartbeat('database_backup', 'Database Backup', 'ok', f'Backup created: {filename}', source='backup', details={'file': filename, 'drive': drive_result})
    return {'ok': True, 'path': str(path), 'filename': filename, 'size': path.stat().st_size, 'drive': drive_result, 'raw_copy': str(raw_copy) if raw_copy else None}


def upload_to_google_drive(path: Path, folder_id: str | None = None) -> dict[str, Any]:
    try:
      from google.oauth2 import service_account
      from googleapiclient.discovery import build
      from googleapiclient.http import MediaFileUpload
    except Exception as exc:
      heartbeat('database_backup_drive', 'Google Drive Backup Upload', 'warning', f'Google Drive libraries are not installed: {exc}', source='backup')
      return {'ok': False, 'message': 'Google Drive libraries are not installed.'}

    scopes = ['https://www.googleapis.com/auth/drive.file']
    service_account_json = current_app.config.get('GOOGLE_SERVICE_ACCOUNT_JSON') or os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    service_account_file = current_app.config.get('GOOGLE_SERVICE_ACCOUNT_FILE') or os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', '')
    try:
        if service_account_json:
            info = json.loads(service_account_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        elif service_account_file:
            creds = service_account.Credentials.from_service_account_file(service_account_file, scopes=scopes)
        else:
            heartbeat('database_backup_drive', 'Google Drive Backup Upload', 'warning', 'Google service account is not configured.', source='backup')
            return {'ok': False, 'message': 'Google service account is not configured.'}
        drive = build('drive', 'v3', credentials=creds, cache_discovery=False)
        metadata = {'name': path.name}
        if folder_id:
            metadata['parents'] = [folder_id]
        media = MediaFileUpload(str(path), mimetype='application/gzip', resumable=False)
        created = drive.files().create(body=metadata, media_body=media, fields='id,name,webViewLink').execute()
        heartbeat('database_backup_drive', 'Google Drive Backup Upload', 'ok', f'Uploaded backup to Drive: {path.name}', source='backup', details=created)
        return {'ok': True, **created}
    except Exception as exc:
        heartbeat('database_backup_drive', 'Google Drive Backup Upload', 'failed', f'Drive upload failed: {exc}', source='backup')
        return {'ok': False, 'message': str(exc)}


def list_backups() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(backup_dir().glob('solardeye_backup_*.json.gz'), reverse=True):
        rows.append({'name': path.name, 'path': str(path), 'size': path.stat().st_size, 'created_at': datetime.utcfromtimestamp(path.stat().st_mtime)})
    return rows


def prune_backups(keep: int = 12):
    files = sorted(backup_dir().glob('solardeye_backup_*.json.gz'), reverse=True)
    for path in files[max(keep, 1):]:
        try:
            path.unlink()
        except Exception:
            pass


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def backup_due(settings: dict[str, str] | None = None) -> bool:
    settings = settings or backup_settings()
    if str(settings.get('backup_enabled', 'true')).lower() != 'true':
        return False
    frequency = (settings.get('backup_frequency') or 'daily').lower()
    last = _parse_dt(settings.get('backup_last_at') or '')
    if not last:
        return True
    delta = datetime.utcnow() - last
    if frequency == 'monthly':
        return delta >= timedelta(days=28)
    if frequency == 'weekly':
        return delta >= timedelta(days=7)
    return delta >= timedelta(hours=23)


def scheduled_backup_job():
    settings = backup_settings()
    if not backup_due(settings):
        heartbeat('database_backup', 'Database Backup', 'ok', 'Backup is not due yet.', source='backup')
        return None
    return create_backup(reason='scheduled')


def restore_backup(filename: str) -> dict[str, Any]:
    # Safety: only restore files from the controlled backup directory.
    path = backup_dir() / Path(filename).name
    if not path.exists():
        raise FileNotFoundError(filename)
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        payload = json.load(fh)
    tables = payload.get('tables') or {}
    with db.engine.begin() as conn:
        for table in reversed(db.metadata.sorted_tables):
            conn.execute(table.delete())
        for table in db.metadata.sorted_tables:
            rows = tables.get(table.name) or []
            if rows:
                conn.execute(table.insert(), rows)
    heartbeat('database_restore', 'Database Restore', 'ok', f'Restored backup: {filename}', source='backup')
    return {'ok': True, 'filename': filename, 'tables': len(tables)}
