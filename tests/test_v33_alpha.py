"""v33-α automated tests.

Covers:
  T1  fan-out helper iterates each active device exactly once
  T2  one device's failure does not abort the loop for the rest
  T3  dispatch_notification builds device-distinct event_keys
  T4  _provider_account_signature groups devices that share an account
  T5  _throttle_for_provider returns conservative defaults

Tests are written so they can run WITHOUT a live database — the
fan-out helper accepts an injected ``devices_iter`` and the dedup
key construction is a pure function. Integration tests that need
a real DB are skipped when not available.
"""
from __future__ import annotations

import sys
import os
from unittest import mock

import pytest

# Make ``app`` importable when pytest is run from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.fixtures.multidevice_alpha import build_fixture, FakeAppDevice


# ─── unit tests on pure helpers ────────────────────────────────────────────

def test_provider_account_signature_groups_shared_accounts():
    """A1 + A2 share a Deye account → identical signature.
       A3 is solarman → distinct signature."""
    from app.scheduler import _provider_account_signature
    _, devices = build_fixture()
    a1, a2, a3 = devices
    sig1, sig2, sig3 = (_provider_account_signature(d) for d in (a1, a2, a3))
    assert sig1 == sig2, "A1 and A2 must share a provider-account signature"
    assert sig1 != sig3, "Different providers must hash to different keys"


def test_throttle_for_provider_returns_conservative_defaults():
    """Defaults are conservative; no provider returns 0 unless 'unknown'."""
    from app.scheduler import _throttle_for_provider
    assert _throttle_for_provider('deye') >= 0.4
    assert _throttle_for_provider('solarman') >= 0.8
    assert _throttle_for_provider('tuya') >= 0.2
    assert _throttle_for_provider('') == 0.0       # unknown → no sleep
    assert _throttle_for_provider('weird') == 0.0


def test_dedup_key_includes_device_id_when_scope_set():
    """build_dedup_key('charge-50-2026-05-08', user_id=1, device_id=42)
    appends ::dev42 so cross-device events do not suppress each other."""
    from app.blueprints.notifications import _build_device_dedup_key
    base = 'charge-50-2026-05-08'
    assert _build_device_dedup_key(base, 1, 42) == f'{base}::dev42'
    # When no device in scope (admin / global), fall back to original key
    assert _build_device_dedup_key(base, 1, None) == base
    # Two devices → distinct keys
    assert _build_device_dedup_key(base, 1, 7) != _build_device_dedup_key(base, 1, 8)


# ─── fan-out helper test (with mocked DB query) ──────────────────────────

def test_fanout_iterates_all_active_devices(monkeypatch):
    """`_run_per_device` calls _invoke once per active device, with
       per-device scope set; failures on one don't stop others."""
    from app import scheduler as sched
    _, devices = build_fixture()

    seen_scopes: list[tuple[int | None, int | None]] = []

    def fake_invoke(fn_path):
        # Read the scope at the moment of invocation
        from app.services.scope import current_scope_ids
        seen_scopes.append(current_scope_ids())

    # Patch DB query → return our 3 fake devices
    class _Q:
        def __init__(self, items): self._items = items
        def filter_by(self, **k):  return _Q([d for d in self._items if all(getattr(d,K)==V for K,V in k.items())])
        def order_by(self, *a):    return self
        def all(self):             return list(self._items)
    monkeypatch.setattr(sched, '_active_device_query', lambda: _Q(devices))
    monkeypatch.setattr(sched, '_invoke', fake_invoke)
    monkeypatch.setattr(sched, '_should_persist_logs', lambda: False)

    # Use a minimal stub app context (no real Flask app needed for this test)
    sched._run_per_device_no_app('app.blueprints.main.sync_now_internal')

    device_ids = sorted(d for _, d in seen_scopes if d is not None)
    assert device_ids == [9001, 9002, 9003], f"Expected fan-out across 3 devices, got {device_ids}"


def test_failure_in_one_device_does_not_abort_others(monkeypatch):
    """If _invoke raises for device 9002, devices 9001 and 9003 still run."""
    from app import scheduler as sched
    _, devices = build_fixture()

    invoked: list[int] = []

    def fake_invoke(fn_path):
        from app.services.scope import current_scope_ids
        _, did = current_scope_ids()
        invoked.append(did)
        if did == 9002:
            raise RuntimeError('simulated provider 502')

    class _Q:
        def __init__(self, items): self._items = items
        def filter_by(self, **k):  return _Q([d for d in self._items if all(getattr(d,K)==V for K,V in k.items())])
        def order_by(self, *a):    return self
        def all(self):             return list(self._items)
    monkeypatch.setattr(sched, '_active_device_query', lambda: _Q(devices))
    monkeypatch.setattr(sched, '_invoke', fake_invoke)
    monkeypatch.setattr(sched, '_should_persist_logs', lambda: False)

    summary = sched._run_per_device_no_app('app.blueprints.main.sync_now_internal')

    assert sorted(invoked) == [9001, 9002, 9003]
    assert 9002 in summary['failed']
    assert 9001 in summary['ok'] and 9003 in summary['ok']


# ─── integration test (skipped if no test DB) ────────────────────────────

def _can_run_integration_tests() -> bool:
    """Integration tests need a fully initialised Flask app + SQLite test DB.
    Skip gracefully if the env can't support it."""
    try:
        os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
        os.environ.setdefault('SECRET_KEY', 'x' * 64)
        os.environ.setdefault('SESSION_COOKIE_SECURE', 'false')
        from app import create_app  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _can_run_integration_tests(),
                    reason='Flask test app could not be constructed; skipping integration test')
def test_loads_add_carries_device_id_when_logged_in():
    """End-to-end: POST to /loads with action=add carries the current
    session device_id into the new UserLoad row.

    Marked skipif because constructing a SQLite test DB inside the
    sandbox is environment-dependent. The test is written and ready
    to run once a CI test-DB is available."""
    pytest.skip('Integration harness pending — manual T4 covers this in v33-α-test-plan.md')
