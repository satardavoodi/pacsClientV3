"""aipacs_chat_unavailable_reason(): precise, actionable gate diagnostics.

The generic "module is not installed or not enabled" dialog is banned
(2026-08-22) — each of the three gate conditions must produce its own named
reason with the place to fix it.
"""

from __future__ import annotations

import pytest

from modules.aipacs_chat import feature_flags as ff


@pytest.fixture()
def gate_all_open(monkeypatch):
    monkeypatch.setattr(ff, "_identity_enabled", lambda: True)
    monkeypatch.setattr(ff, "aipacs_chat_enabled", lambda: True)
    monkeypatch.setattr(ff, "_module_registry_enabled", lambda: True)


def test_no_reason_when_available(gate_all_open):
    assert ff.aipacs_chat_available() is True
    assert ff.aipacs_chat_unavailable_reason() == ""


def test_registry_not_installed_names_install_path(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "_module_registry_enabled", lambda: False)

    import aipacs_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "module_availability_detail",
        lambda module_id: {
            "module_id": module_id,
            "title": "AiPacs Chat",
            "installed": False,
            "enabled": False,
            "status": "not_installed",
            "warning": "",
        },
    )

    reason = ff.aipacs_chat_unavailable_reason()
    assert "not installed" in reason
    assert "Installation & Updates" in reason
    # It does NOT talk about the settings toggle when only the registry fails.
    assert "Consultation & Education" not in reason


def test_registry_install_failure_carries_recorded_warning(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "_module_registry_enabled", lambda: False)

    import aipacs_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "module_availability_detail",
        lambda module_id: {
            "module_id": module_id,
            "title": "AiPacs Chat",
            "installed": False,
            "enabled": False,
            "status": "install_failed",
            "warning": "Bundled package was selected during setup but no package files were found.",
        },
    )

    reason = ff.aipacs_chat_unavailable_reason()
    assert "did not install completely" in reason
    assert "no package files were found" in reason


def test_registry_disabled_but_installed_names_enable_path(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "_module_registry_enabled", lambda: False)

    import aipacs_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "module_availability_detail",
        lambda module_id: {
            "module_id": module_id,
            "title": "AiPacs Chat",
            "installed": True,
            "enabled": False,
            "status": "installed",
            "warning": "",
        },
    )

    reason = ff.aipacs_chat_unavailable_reason()
    assert "installed but disabled" in reason
    assert "Installation & Updates" in reason


def test_own_flag_off_names_settings_toggle(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "aipacs_chat_enabled", lambda: False)
    monkeypatch.setattr(ff, "aipacs_chat_env_override", lambda: "")

    reason = ff.aipacs_chat_unavailable_reason()
    assert "switched off" in reason
    assert "Consultation & Education" in reason


def test_own_flag_env_override_named(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "aipacs_chat_enabled", lambda: False)
    monkeypatch.setattr(ff, "aipacs_chat_env_override", lambda: "AIPACS_CHAT")

    reason = ff.aipacs_chat_unavailable_reason()
    assert "AIPACS_CHAT" in reason


def test_identity_off_named(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "_identity_enabled", lambda: False)

    reason = ff.aipacs_chat_unavailable_reason()
    assert "Identity" in reason


def test_multiple_failures_all_reported(gate_all_open, monkeypatch):
    monkeypatch.setattr(ff, "_identity_enabled", lambda: False)
    monkeypatch.setattr(ff, "aipacs_chat_enabled", lambda: False)
    monkeypatch.setattr(ff, "aipacs_chat_env_override", lambda: "")

    reason = ff.aipacs_chat_unavailable_reason()
    assert "Identity" in reason
    assert "Consultation & Education" in reason
