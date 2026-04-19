from __future__ import annotations

import json
from datetime import datetime

from ..extensions import db
from ..models import ServiceHeartbeat
from .utils import to_json


def heartbeat(service_key: str, service_label: str, status: str = 'ok', message: str = '', source: str = 'system', details=None):
    row = ServiceHeartbeat.query.filter_by(service_key=service_key).first()
    if not row:
        row = ServiceHeartbeat(service_key=service_key, service_label=service_label)
        db.session.add(row)
    row.service_label = service_label
    row.source = source or 'system'
    row.status = status or 'unknown'
    row.message = message or ''
    row.details_json = to_json(details or {})
    row.last_seen_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return row
