"""AiPacs Chat feature flag: default OFF; env + config overrides; the 3-part gate.

Guards the invariant every module flag in this repo shares — a disabled module
has NO startup side effects, not even a created directory — plus the one that
is specific to this module: the gate is three conditions and checking one of
them is not checking the gate.
"""

import pathlib

from modules.aipacs_chat import feature_flags


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("AIPACS_CHAT", raising=False)
    monkeypatch.setattr(
        feature_flags, "_flag_file_path", lambda: pathlib.Path("/nonexistent/aipacs_chat.json")
    )
    assert feature_flags.aipacs_chat_enabled() is False


def test_flag_env_on(monkeypatch):
    monkeypatch.setenv("AIPACS_CHAT", "1")
    assert feature_flags.aipacs_chat_enabled() is True


def test_flag_env_off_beats_config(monkeypatch, tmp_path):
    flag = tmp_path / "aipacs_chat.json"
    flag.write_text('{"enabled": true}', encoding="utf-8")
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    monkeypatch.setenv("AIPACS_CHAT", "off")
    assert feature_flags.aipacs_chat_enabled() is False


def test_flag_config_file(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_CHAT", raising=False)
    flag = tmp_path / "aipacs_chat.json"
    flag.write_text('{"enabled": true}', encoding="utf-8")
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    assert feature_flags.aipacs_chat_enabled() is True


def test_reading_the_flag_creates_nothing(monkeypatch, tmp_path):
    """A disabled module must not leave a folder behind on every startup."""
    monkeypatch.delenv("AIPACS_CHAT", raising=False)
    monkeypatch.setattr(feature_flags, "_config_root", lambda: tmp_path)

    feature_flags.aipacs_chat_enabled()

    assert list(tmp_path.iterdir()) == []


def test_a_corrupt_flag_file_reads_as_off_rather_than_raising(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_CHAT", raising=False)
    flag = tmp_path / "aipacs_chat.json"
    flag.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    assert feature_flags.aipacs_chat_enabled() is False


# --- the combined gate ------------------------------------------------------


def test_the_gate_needs_all_three(monkeypatch):
    """Identity OFF must close the gate even with this module's flag ON.

    This module has no authentication of its own: the Sanctum token belongs to
    modules/Identity. Opening the console without it means a window that can
    only ever show a sign-in error.
    """
    monkeypatch.setattr(feature_flags, "aipacs_chat_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "_module_registry_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "_identity_enabled", lambda: False)

    assert feature_flags.aipacs_chat_available() is False


def test_the_gate_is_closed_by_the_module_registry_too(monkeypatch):
    monkeypatch.setattr(feature_flags, "aipacs_chat_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "_identity_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "_module_registry_enabled", lambda: False)

    assert feature_flags.aipacs_chat_available() is False


def test_the_gate_opens_when_all_three_agree(monkeypatch):
    monkeypatch.setattr(feature_flags, "aipacs_chat_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "_identity_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "_module_registry_enabled", lambda: True)

    assert feature_flags.aipacs_chat_available() is True


def test_the_module_registry_fails_open(monkeypatch):
    """A registry that cannot be consulted must not hide a licensed module.

    Mirrors modules/education/online_consultation: a source checkout has no
    installation profile, and refusing there would mean the module silently
    never opens with no way to tell why.
    """
    def _boom():
        raise RuntimeError("no runtime")

    monkeypatch.setattr(
        feature_flags, "_module_registry_enabled", feature_flags._module_registry_enabled
    )
    monkeypatch.setitem(
        __import__("sys").modules, "aipacs_runtime", type("M", (), {"is_module_enabled": _boom})()
    )

    assert feature_flags._module_registry_enabled() is True


def test_importing_the_package_does_not_pull_pyside(monkeypatch):
    """The package is import-cheap by contract.

    ``from modules.aipacs_chat import aipacs_chat_available`` runs on every
    startup that draws the left menu. If it dragged in PySide6, requests and
    the Identity module, a workstation with the module turned OFF would pay
    for it anyway.
    """
    import importlib
    import sys

    for name in [n for n in sys.modules if n.startswith("modules.aipacs_chat")]:
        del sys.modules[name]

    package = importlib.import_module("modules.aipacs_chat")

    assert callable(package.aipacs_chat_available)
    assert "modules.aipacs_chat.services" not in sys.modules
    assert "modules.aipacs_chat.ui" not in sys.modules
