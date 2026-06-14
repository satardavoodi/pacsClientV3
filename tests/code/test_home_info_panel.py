"""Guards for the redesigned Home Information panel (2026-06-06).

Contract:
  1. The panel shows the RUNNING app version (QApplication.applicationVersion,
     fallback RELEASE_INFO) + status chip + build/release meta.
  2. Release data is complete (changes + modules per the spec).
  3. Flat design: no QFrame boxes / divider lines; the only border is the
     status chip; sections are quiet captions + whitespace.
  4. Extensible: add_section appends new content without redesign.
  5. AIPacs_ui wires HomeInfoPanel into page_4 with a fail-safe fallback.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from PacsClient.pacs.workstation_ui.home_ui.home_info_panel import (  # noqa: E402
    COMPANY_INFO,
    PERSIAN_EDITION,
    RELEASE_INFO,
    HomeInfoPanel,
)

_SRC = (
    _REPO_ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py"
).read_text(encoding="utf-8")
_UI_SRC = (
    _REPO_ROOT / "PacsClient/pacs/workstation_ui/AIPacs_ui.py"
).read_text(encoding="utf-8")


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _labels(panel):
    return [l.text() for l in panel.findChildren(QLabel)]


# ── content ───────────────────────────────────────────────────────────────
def test_version_follows_running_app(qapp, monkeypatch):
    qapp.setApplicationVersion("9.9.9-test")
    panel = HomeInfoPanel()
    assert panel.version_label.text() == "Version 9.9.9-test"
    # fallback when no QApplication is reachable (NOTE: an *empty* version
    # can't be simulated in-process — Qt then substitutes the executable's
    # file-version metadata; production always sets the version in main.py
    # before the UI builds)
    import PacsClient.pacs.workstation_ui.home_ui.home_info_panel as mod
    monkeypatch.setattr(mod.QApplication, "instance", staticmethod(lambda: None))
    assert mod.HomeInfoPanel.running_version() == RELEASE_INFO["version"]


def test_release_data_complete():
    assert RELEASE_INFO["app_name"] == "AI-PACS Viewer"
    assert RELEASE_INFO["status"] in ("Stable", "Beta", "Internal Testing")
    assert len(RELEASE_INFO["changes"]) >= 5
    assert set(RELEASE_INFO["modules"]) >= {
        "Viewer", "Download Manager", "MPR", "EchoMind", "EagleEye"}
    assert RELEASE_INFO["build_date"] and RELEASE_INFO["release_date"]


def test_panel_renders_software_and_company_blocks(qapp):
    panel = HomeInfoPanel()
    texts = " | ".join(_labels(panel))
    assert "AI-PACS Viewer" in texts
    assert "RECENT CHANGES" in texts and "AFFECTED MODULES" in texts
    assert "ABOUT AI-PACS" in texts and "WE DEVELOP" in texts
    assert "SERVICES" in texts and "GLOBAL" in texts
    for c in RELEASE_INFO["changes"]:
        assert c in texts
    for d in COMPANY_INFO["develops"]:
        assert d in texts
    assert COMPANY_INFO["global"] in texts
    assert panel.status_chip.text() == RELEASE_INFO["status"]


# ── flat design ───────────────────────────────────────────────────────────
def test_flat_no_frames_or_dividers():
    assert "QFrame" not in _SRC               # no boxed regions
    assert "HLine" not in _SRC and "Separator" not in _SRC
    # the only bordered element is the status chip
    assert _SRC.count("border: 1px solid") == 1
    assert "NoFrame" in _SRC                  # frameless scroll area


# ── extensibility ─────────────────────────────────────────────────────────
def test_add_section_extends_without_redesign(qapp):
    panel = HomeInfoPanel()
    before = len(panel.findChildren(QLabel))
    panel.add_section("MAINTENANCE", ["Server window: Friday 22:00"])
    texts = " | ".join(_labels(panel))
    assert "MAINTENANCE" in texts and "Server window: Friday 22:00" in texts
    assert len(panel.findChildren(QLabel)) == before + 2


# ── Persian customized edition notice ───────────────────────────────────────
def test_persian_edition_data_complete():
    # English (full) notice carries the partner + version + collaboration line
    en = " ".join(PERSIAN_EDITION["en"])
    assert "AI-PACS Version 3.2.8" in en
    assert "Iran Nobat" in en
    assert "customized" in en.lower() and "localized" in en.lower()
    assert "collaboration with Iran Nobat" in en
    # Farsi rendering of the same notice (partner name + brand present)
    fa = " ".join(PERSIAN_EDITION["fa"])
    assert "ایران نوبت" in fa
    assert "AI-PACS" in fa
    assert len(PERSIAN_EDITION["fa"]) == len(PERSIAN_EDITION["en"])


def test_panel_renders_persian_edition(qapp):
    panel = HomeInfoPanel()
    texts = " | ".join(_labels(panel))
    # caption is uppercased by add_section
    assert "PERSIAN CUSTOMIZED EDITION" in texts
    # both languages reach the UI
    assert "Developed by AI-PACS in collaboration with Iran Nobat." in texts
    assert any("ایران نوبت" in t for t in _labels(panel))


def test_persian_lines_render_right_to_left(qapp):
    from PySide6.QtCore import Qt
    panel = HomeInfoPanel()
    fa_first = PERSIAN_EDITION["fa"][0]
    matches = [l for l in panel.findChildren(QLabel) if l.text() == fa_first]
    assert matches, "Farsi line not found in panel"
    assert matches[0].layoutDirection() == Qt.RightToLeft


def test_persian_edition_adds_no_extra_border():
    # flat-design contract must hold: still exactly one bordered element (chip)
    assert _SRC.count("border: 1px solid") == 1


# ── wiring ────────────────────────────────────────────────────────────────
def test_ui_page4_uses_panel_with_failsafe():
    i = _UI_SRC.index("Page 4 - Information")
    block = _UI_SRC[i:i + 1800]
    assert "HomeInfoPanel" in block
    assert "self.info_panel = HomeInfoPanel(self.page_4)" in block
    assert "except Exception" in block  # legacy text fallback kept
