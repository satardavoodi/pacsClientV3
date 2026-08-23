"""Regression tests for the STABLE machine fingerprint + backward-compatible
license validation (fixes the "license lost after reboot" bug).

Root cause covered: Key 1 used to derive from uuid.getnode() (a MAC address)
which changes across reboots. Key 1 must now be stable and must NOT depend on
network adapters / MAC / COMPUTERNAME.
"""
import importlib
import os
import sys

import pytest

_LG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "modules", "LicenseGenerator",
)
if _LG_DIR not in sys.path:
    sys.path.insert(0, _LG_DIR)

import license_manager as lm  # noqa: E402
from license_manager import LicenseManager  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_appdata(tmp_path, monkeypatch):
    """Redirect all cache/state/log writes to a temp dir so tests don't touch
    the real %APPDATA%."""
    monkeypatch.setattr(lm, "_compute_app_data_dir", lambda: tmp_path)
    # reset the cached logger so it re-binds under tmp
    monkeypatch.setattr(lm, "_license_logger", None, raising=False)
    yield


def _fixed_components(guid="GUID-AAAA", serial="DEADBEEF"):
    return {"machine_guid": guid, "system_volume_serial": serial}


def test_key1_is_deterministic_and_32_chars(monkeypatch):
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    a = m.get_hardware_id()
    b = m.get_hardware_id()
    assert a == b
    assert len(a) == 32


def test_key1_ignores_mac_and_computername(monkeypatch):
    """Changing the MAC / COMPUTERNAME must NOT change Key 1 (the old bug)."""
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    monkeypatch.setattr(lm.uuid, "getnode", lambda: 0x001122334455)
    monkeypatch.setenv("COMPUTERNAME", "PC-ALPHA")
    id_before = m.get_hardware_id()
    # Simulate a reboot that picks a different adapter / random MAC + rename.
    monkeypatch.setattr(lm.uuid, "getnode", lambda: 0xAABBCCDDEEFF)
    monkeypatch.setenv("COMPUTERNAME", "PC-BETA")
    id_after = m.get_hardware_id()
    assert id_before == id_after


def test_generate_validate_roundtrip(monkeypatch):
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    key = m.generate_license_key(m.get_hardware_id(), 365)
    ok, msg = m.validate_license(key)
    assert ok, msg


def test_foreign_machine_rejected(monkeypatch):
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    key = m.generate_license_key("F" * 32, 365)
    ok, _ = m.validate_license(key)
    assert not ok


def test_legacy_license_still_validates(monkeypatch):
    """A license issued under the OLD uuid.getnode() scheme must keep working
    without re-activation."""
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    legacy_id = lm._hash_id(lm._read_legacy_node_raw())
    legacy_key = m.generate_license_key(legacy_id, 365)
    ok, msg = m.validate_license(legacy_key)
    assert ok, msg


def test_expired_rejected(monkeypatch):
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    key = m.generate_license_key(m.get_hardware_id(), -1)
    ok, _ = m.validate_license(key)
    assert not ok


def test_stable_when_volume_serial_missing(monkeypatch):
    """MachineGuid alone still yields a stable, valid fingerprint."""
    monkeypatch.setattr(
        lm, "collect_fingerprint_components",
        lambda: {"machine_guid": "GUID-ONLY", "system_volume_serial": None},
    )
    m = LicenseManager()
    a = m.get_hardware_id()
    b = m.get_hardware_id()
    assert a == b and len(a) == 32


def test_cache_fallback_when_hardware_unreadable(monkeypatch):
    """If stable identifiers become temporarily unreadable, the cached stable ID
    is reused rather than drifting to a new value."""
    monkeypatch.setattr(lm, "collect_fingerprint_components",
                        lambda: _fixed_components())
    m = LicenseManager()
    stable = m.get_hardware_id()  # seeds the cache
    # Now simulate hardware readers all failing.
    monkeypatch.setattr(
        lm, "collect_fingerprint_components",
        lambda: {"machine_guid": None, "system_volume_serial": None},
    )
    assert m.get_hardware_id() == stable
