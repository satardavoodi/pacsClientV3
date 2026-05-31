"""Tests for the UI-variant flag system (AI-PACS design migration).

Default flipped V1 → V2 on 2026-05-31. These tests prove:
  * default is "v2" (V2 is the shipping design),
  * invalid values still fall back to the default ("v2"),
  * per-module overrides still work in both directions,
  * env var still overrides,
  * the function never raises,
  * a user CAN still pin themselves back to V1 via env / config (legacy
    backup path remains reachable).
"""
from __future__ import annotations

import pytest

from PacsClient.utils import ui_variant


def test_default_is_v2_when_no_config(monkeypatch):
    monkeypatch.setattr(ui_variant, "_load", lambda: {})
    assert ui_variant.get_ui_variant() == "v2"
    for module in ui_variant.MODULES:
        assert ui_variant.get_ui_variant(module) == "v2"


def test_invalid_variant_falls_back_to_default_v2(monkeypatch):
    monkeypatch.setattr(ui_variant, "_load", lambda: {"variant": "bogus"})
    assert ui_variant.get_ui_variant() == "v2"


def test_explicit_v1_still_works(monkeypatch):
    # V1 must remain reachable as the legacy/backup variant.
    monkeypatch.setattr(ui_variant, "_load", lambda: {"variant": "v1"})
    assert ui_variant.get_ui_variant() == "v1"
    for module in ui_variant.MODULES:
        assert ui_variant.get_ui_variant(module) == "v1"


def test_explicit_v2(monkeypatch):
    monkeypatch.setattr(ui_variant, "_load", lambda: {"variant": "v2"})
    assert ui_variant.get_ui_variant() == "v2"


def test_per_module_override_v1_within_v2(monkeypatch):
    # A user can stay on V2 globally but pin one module back to V1.
    monkeypatch.setattr(
        ui_variant, "_load", lambda: {"variant": "v2", "modules": {"home": "v1"}}
    )
    assert ui_variant.get_ui_variant() == "v2"
    assert ui_variant.get_ui_variant("home") == "v1"
    assert ui_variant.get_ui_variant("viewer") == "v2"


def test_per_module_override_v2_within_v1(monkeypatch):
    # And the inverse: pin to V1 globally but opt one module into V2.
    monkeypatch.setattr(
        ui_variant, "_load", lambda: {"variant": "v1", "modules": {"home": "v2"}}
    )
    assert ui_variant.get_ui_variant() == "v1"
    assert ui_variant.get_ui_variant("home") == "v2"
    assert ui_variant.get_ui_variant("viewer") == "v1"


def test_env_override(monkeypatch):
    monkeypatch.setenv("AIPACS_UI_VARIANT", "v1")
    assert ui_variant.get_ui_variant() == "v1"
    monkeypatch.setenv("AIPACS_UI_VARIANT", "garbage")
    # garbage falls back to the build default (now V2).
    assert ui_variant.get_ui_variant() == "v2"


def test_never_raises_on_bad_load(monkeypatch):
    def _boom():
        raise RuntimeError("config blew up")

    monkeypatch.setattr(ui_variant, "_load", _boom)
    # Exception path falls back to the build default (V2 now), so a
    # corrupt config file can never strand the user on the legacy UI.
    assert ui_variant.get_ui_variant() == "v2"
    assert ui_variant.get_ui_variant("home") == "v2"


def test_theme_v2_mirrors_v1_in_phase1():
    # The v2 builder must be a no-op mirror of v1 for Phase 1 (zero visual change).
    pytest.importorskip("PySide6")
    from PacsClient.utils.theme_manager import get_theme_manager
    from PacsClient.utils.theme_v2 import build_application_stylesheet_v2

    tm = get_theme_manager()
    theme = tm.current_theme()
    assert build_application_stylesheet_v2(tm, theme) == tm.build_application_stylesheet(theme)
