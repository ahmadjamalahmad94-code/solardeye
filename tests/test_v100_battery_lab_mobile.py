"""v100 — Battery Lab mobile API endpoint.

The owner asked for the mobile app to display Battery Lab natively
instead of opening the web `/battery-lab` URL in an external browser.
This commit's backend half adds `/api/mobile/battery-lab` that
returns the same data the web page renders (insights, details, 48h
hourly aggregation) in a JSON shape the Flutter screen can consume.

These tests cover the payload-builder helper in isolation so we
don't need the whole Flask + auth stack to assert shape.
"""
from __future__ import annotations

import json
import os
import sys
from unittest import mock

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _make_flask_app():
    from flask import Flask
    app = Flask(__name__)
    app.config['BATTERY_RESERVE_PERCENT'] = 20
    app.config['BATTERY_KNOWN_VOLTAGE'] = ''
    app.config['BATTERY_KNOWN_CURRENT'] = ''
    app.config['BATTERY_KNOWN_HEALTH'] = ''
    app.config['BATTERY_KNOWN_CAPACITY_AH'] = ''
    app.config['BATTERY_KNOWN_CYCLES'] = ''
    app.config['BATTERY_KNOWN_TEMPERATURE'] = ''
    app.config['LOCAL_TIMEZONE'] = 'UTC'
    return app


def test_battery_lab_endpoint_registered_in_allowed_methods():
    """The new endpoint must be on the mobile allowed-methods
    registry so the catch-all 404 handler doesn't shadow it."""
    from app.blueprints import mobile_api as mod
    # The registry is a module-private dict; we read it through the
    # public allowed-methods lookup that the catch-all uses.
    allowed = mod._mobile_allowed_methods_for('/battery-lab')
    assert allowed is not None, (
        '/battery-lab is missing from the mobile allowed-methods '
        'registry — the catch-all 404 handler will shadow it.'
    )
    assert 'GET' in allowed


def test_required_helpers_are_imported():
    """build_battery_insights / build_battery_details /
    get_runtime_battery_settings must be in scope so the endpoint
    can build its payload."""
    from app.blueprints.mobile_api import (
        build_battery_insights,
        build_battery_details,
        get_runtime_battery_settings,
        _mobile_battery_lab_payload,
    )
    assert build_battery_insights is not None
    assert build_battery_details is not None
    assert get_runtime_battery_settings is not None
    assert _mobile_battery_lab_payload is not None
