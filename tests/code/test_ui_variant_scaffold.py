"""Tests for the parallel UI-variant scaffold (AI-PACS design migration).

These prove the safety contract of the opt-in v2 layer:
  * default is "v1" (live UI unchanged),
  * invalid values fall back to "v1",
  * per-module overrides work,
  * the function never raises,
  * the Phase-1 v2 stylesheet MIRRORS v1 exactly (zero visual change).
"""
from __future__ import annotations

import pytest

from PacsClient.utils import ui_variant


def test_default_is_v1_when_no_config(monkeypatch):
    monkeypatch.setattr(ui_variant, "_load", lambda: {})
    assert ui_variant.get_ui_variant() == "v1"
    for module in ui_variant.MODULES:
        assert ui_variant.get_ui_variant(module) == "v1"


def test_invalid_variant_falls_back_to_v1(monkeypatch):
    monkeypatch.setattr(ui_variant, "_load", lambda: {"variant": "bogus"})
    assert ui_variant.get_ui_variant() == "v1"


def test_global_v2(monkeypatch):
    monkeypatch.setattr(ui_variant, "_load", lambda: {"variant": "v2"})
    assert ui_variant.get_ui_variant() == "v2"


def test_per_module_override(monkeypatch):
    monkeypatch.setattr(
        ui_variant, "_load", lambda: {"variant": "v1", "modules": {"home": "v2"}}
    )
    assert ui_variant.get_ui_variant() == "v1"
    assert ui_variant.get_ui_variant("home") == "v2"
    assert ui_variant.get_ui_variant("viewer") == "v1"


def test_env_override(monkeypatch):
    monkeypatch.setenv("AIPACS_UI_VARIANT", "v2")
    assert ui_variant.get_ui_variant() == "v2"
    monkeypatch.setenv("AIPACS_UI_VARIANT", "garbage")
    assert ui_variant.get_ui_variant() == "v1"


def test_never_raises_on_bad_load(monkeypatch):
    def _boom():
        raise RuntimeError("config blew up")

    monkeypatch.setattr(ui_variant, "_load", _boom)
    assert ui_variant.get_ui_variant() == "v1"
    assert ui_variant.get_ui_variant("home") == "v1"


def test_theme_v2_mirrors_v1_in_phase1():
    # The v2 builder must be a no-op mirror of v1 for Phase 1 (zero visual change).
    pytest.importorskip("PySide6")
    from PacsClient.utils.theme_manager import get_theme_manager
    from PacsClient.utils.theme_v2 import build_application_stylesheet_v2

    tm = get_theme_manager()
    theme = tm.current_theme()
    assert build_application_stylesheet_v2(tm, theme) == tm.build_application_stylesheet(theme)
