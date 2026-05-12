"""v49 — mobile provider-setup endpoint helper tests.

Focuses on the pure logic of ``_mobile_apply_provider_setup`` and
``_is_secret_setup_field``. The endpoint itself is a thin wrapper
around them (auth + device lookup + JSON commit), so locking the
helper's contract is enough to keep the credential storage shape
identical to what the web flow produces.
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ─── _is_secret_setup_field — secret classification ──────────────────


def test_is_secret_setup_field_recognises_substring_patterns():
    from app.blueprints.mobile_api import _is_secret_setup_field
    assert _is_secret_setup_field('deye_app_secret') is True
    assert _is_secret_setup_field('api_key') is True
    assert _is_secret_setup_field('access_token') is True
    assert _is_secret_setup_field('user_password') is True
    assert _is_secret_setup_field('DEYE_PASSWORD') is True  # case-insensitive


def test_is_secret_setup_field_special_names():
    from app.blueprints.mobile_api import _is_secret_setup_field
    # Exact-name set from devices_routes.py:155
    assert _is_secret_setup_field('deye_email') is True
    assert _is_secret_setup_field('username') is True
    assert _is_secret_setup_field('account') is True


def test_is_secret_setup_field_non_secret_keys():
    from app.blueprints.mobile_api import _is_secret_setup_field
    assert _is_secret_setup_field('site_id') is False
    assert _is_secret_setup_field('deye_app_id') is False
    assert _is_secret_setup_field('deye_plant_id') is False
    assert _is_secret_setup_field('') is False
    assert _is_secret_setup_field(None) is False  # type: ignore[arg-type]


# ─── _mobile_apply_provider_setup — Deye whitelisting + classification ─


def _fresh_device():
    """Return a SimpleNamespace standing in for ``AppDevice``. Only
    the attributes the helper reads/writes are present, so the test
    doesn't need a live SQLAlchemy session."""
    return SimpleNamespace(
        credentials_json=None,
        settings_json=None,
        station_id=None,
        device_uid=None,
        external_device_id=None,
        api_provider='deye',
        api_base_url='https://eu1-developer.deyecloud.com',
        auth_mode='config',
        timezone='Asia/Hebron',
        updated_at=None,
    )


def _deye_spec():
    from app.services.energy_integrations import PROVIDER_MAP
    return PROVIDER_MAP['deye']


def test_apply_setup_writes_secret_keys_to_credentials_json():
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    device = _fresh_device()
    _mobile_apply_provider_setup(device, _deye_spec(), {
        'deye_app_id': 'app-123',
        'deye_app_secret': 'super-secret',
        'deye_email': 'user@example.com',
        'deye_password_or_hash': 'pw-or-hash',
        'deye_plant_id': 'plant-9001',
    })
    creds = json.loads(device.credentials_json)
    settings = json.loads(device.settings_json)

    # secret keys → credentials_json
    assert creds['deye_app_secret'] == 'super-secret'
    assert creds['deye_email'] == 'user@example.com'
    assert creds['deye_password_or_hash'] == 'pw-or-hash'
    # non-secret keys → settings_json
    assert settings['deye_app_id'] == 'app-123'
    assert settings['deye_plant_id'] == 'plant-9001'
    # secret keys must NOT bleed into settings_json
    assert 'deye_app_secret' not in settings
    assert 'deye_email' not in settings
    # non-secret keys must NOT bleed into credentials_json
    assert 'deye_app_id' not in creds
    assert 'deye_plant_id' not in creds


def test_apply_setup_deye_compat_mappings():
    """The Deye sync client reads ``device.station_id`` /
    ``device.device_uid`` directly. The helper must mirror the web
    flow's `deye_plant_id` → `station_id` and `deye_device_sn` →
    `device_uid` mappings, AND duplicate `deye_password_or_hash` into
    `deye_password` if neither hash nor password are already set."""
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    device = _fresh_device()
    _mobile_apply_provider_setup(device, _deye_spec(), {
        'deye_plant_id': 'plant-42',
        'deye_device_sn': 'sn-9999',
        'deye_password_or_hash': 'raw-pw',
    })
    creds = json.loads(device.credentials_json)
    assert device.station_id == 'plant-42'
    assert device.device_uid == 'sn-9999'
    assert creds['deye_password_or_hash'] == 'raw-pw'
    assert creds['deye_password'] == 'raw-pw'  # auto-filled compat key


def test_apply_setup_drops_keys_not_in_provider_whitelist():
    """An attacker could try to inject ``admin_token`` or any other
    key into credentials_json. The helper must drop unknown keys
    silently, regardless of whether they look like secrets."""
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    device = _fresh_device()
    _mobile_apply_provider_setup(device, _deye_spec(), {
        'deye_app_id': 'legit',
        'admin_token': 'NOT-A-WHITELISTED-FIELD',
        'rogue_password': 'should-not-land',
    })
    creds = json.loads(device.credentials_json)
    settings = json.loads(device.settings_json)
    assert settings.get('deye_app_id') == 'legit'
    assert 'admin_token' not in creds
    assert 'admin_token' not in settings
    assert 'rogue_password' not in creds
    assert 'rogue_password' not in settings


def test_apply_setup_blank_input_preserves_existing_values():
    """The mobile UI may re-submit the form with empty secret fields
    when only one non-secret field changed. Blank values must NOT null
    out the existing stored credentials — mirrors the web's
    `preserve_secret_form_value(... fallback)` behaviour."""
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    device = _fresh_device()
    device.credentials_json = json.dumps({
        'deye_app_secret': 'KEEP-ME',
        'deye_password': 'KEEP-PASSWORD',
    })
    device.settings_json = json.dumps({
        'deye_app_id': 'KEEP-APP-ID',
    })
    _mobile_apply_provider_setup(device, _deye_spec(), {
        'deye_app_id': '',          # blank → keep existing
        'deye_app_secret': '',      # blank → keep existing
        'deye_plant_id': 'new-plant',  # new value
    })
    creds = json.loads(device.credentials_json)
    settings = json.loads(device.settings_json)
    assert creds['deye_app_secret'] == 'KEEP-ME'
    assert creds['deye_password'] == 'KEEP-PASSWORD'
    assert settings['deye_app_id'] == 'KEEP-APP-ID'
    assert settings['deye_plant_id'] == 'new-plant'


def test_apply_setup_does_not_touch_connection_status():
    """Setup must NEVER promote the device to 'connected'. Only a real
    sync (in main.py:685, 728) is allowed to set connection_status='ok'.
    The helper does not even read it — confirmed by the absence of
    the attribute on the test stub."""
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    device = _fresh_device()
    # Intentionally NOT setting connection_status on the stub. If the
    # helper tried to touch it the AttributeError would surface here.
    _mobile_apply_provider_setup(device, _deye_spec(), {
        'deye_app_id': 'x', 'deye_app_secret': 'y',
    })
    assert not hasattr(device, 'connection_status')  # untouched


def test_apply_setup_mirrors_provider_metadata_into_settings():
    """The web flow mirrors provider_code / provider_name / api_provider
    / api_base_url / auth_mode / timezone into ``settings_json`` so
    audit trails + future re-renders can read them. Confirm the same
    keys appear here."""
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    device = _fresh_device()
    _mobile_apply_provider_setup(device, _deye_spec(), {
        'deye_app_id': 'x', 'deye_app_secret': 'y',
    })
    settings = json.loads(device.settings_json)
    assert settings['provider_code'] == 'deye'
    assert settings['provider_name'] == 'Deye Cloud'
    assert settings['api_provider'] == 'deye'
    assert settings['auth_mode'] == 'config'
    assert settings['timezone'] == 'Asia/Hebron'


def test_apply_setup_non_deye_provider_uses_generic_compat_map():
    """For non-Deye providers the helper falls through to the generic
    station_id / device_uid alias map (site_id, system_id, etc.).
    Test with the SolarEdge spec which uses `site_id`."""
    from app.blueprints.mobile_api import _mobile_apply_provider_setup
    from app.services.energy_integrations import PROVIDER_MAP
    spec = PROVIDER_MAP['solaredge_cloud']
    device = _fresh_device()
    device.api_provider = 'solaredge'
    _mobile_apply_provider_setup(device, spec, {
        'site_id': 'site-7',
        'api_key': 'secret-key',
    })
    creds = json.loads(device.credentials_json)
    settings = json.loads(device.settings_json)
    assert device.station_id == 'site-7'
    assert settings['site_id'] == 'site-7'
    assert creds['api_key'] == 'secret-key'
    assert 'api_key' not in settings
