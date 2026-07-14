# -*- coding: utf-8 -*-
"""Guard: every Eagle Eye run must appear as its own entry in the AI Results dropdown.

Regression (2026-07-12): re-running Eagle Eye on the SAME patient from the SAME
workstation did not add the new CSV to the left-panel "AI Results" dropdown, while
running it from a *different* computer showed every run.

Root cause was UI-only — the data layer was always correct:
  * `_save_mg_manifest` APPENDS each run to `mg_ai_manifest.json::available` and points
    `active` at the newest (verified on disk: 3 runs → 3 entries).
  * but the dropdown was filled exactly ONCE: `_finalize_loading` (tab construction) and
    `left_sidebar_layout_ui` behind the `mg_runs_loaded` run-once latch.
  * a re-run REUSES the already-open `AiMainWindow` tab
    (`_hp_modules.add_new_tab_widget` → `setCurrentWidget(existing_tab)` → `return`),
    so nothing re-read the manifest. A second computer built the tab fresh → all runs.

Pins: the manifest still accumulates runs, the new public refresh clears the latch and
reloads, `AiMainWindow.refresh_ai_results` delegates, and the tab-reuse branch calls it.
"""

import inspect
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PacsClient.utils.utils import load_mg_ai_runs  # noqa: E402
from modules.ai_imaging.ai_module_ui.ai_mainwindow import AiMainWindow  # noqa: E402
from modules.ai_imaging.ai_module_ui.service_tab.imaging_tab import ImagingToolsTab  # noqa: E402
from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_modules  # noqa: E402


# ---------------------------------------------------------------------------
# stubs (no Qt widget construction — we exercise the real methods with a fake self)
# ---------------------------------------------------------------------------

class _FakeImagingTab:
    """Minimal stand-in exposing exactly what refresh_mg_ai_results touches."""

    def __init__(self, modality="MG", has_combo=True):
        self._modality = modality
        self.mg_runs_combo = object() if has_combo else None
        self.mg_runs_loaded = True          # the run-once latch, already tripped
        self.load_calls = 0

    def detect_modality(self):
        return self._modality

    def _load_mg_runs_into_dropdown(self):
        self.load_calls += 1
        self.mg_runs_loaded = True

    # bind the REAL implementations under test
    _ai_result_refresh_enabled = staticmethod(ImagingToolsTab._ai_result_refresh_enabled)
    refresh_mg_ai_results = ImagingToolsTab.refresh_mg_ai_results


class _FakeAiWindow:
    def __init__(self, imaging_tab):
        self.imaging_tab = imaging_tab

    refresh_ai_results = AiMainWindow.refresh_ai_results


# ---------------------------------------------------------------------------
# 1. The data layer keeps every run (this half was never broken — pin it)
# ---------------------------------------------------------------------------

def test_manifest_accumulates_every_run(tmp_path):
    study = "1.2.3.4"
    d = tmp_path / study
    d.mkdir(parents=True)
    manifest = {
        "available": [
            {"detection": "updated_csv_with_boxes_0.45.csv",
             "classification": "classification_0.45.csv", "threshold": 0.45},
            {"detection": "updated_csv_with_boxes_0.45_2.csv",
             "classification": "classification_0.45_2.csv", "threshold": 0.45},
            {"detection": "updated_csv_with_boxes_0.30_3.csv",
             "classification": "classification_0.30_3.csv", "threshold": 0.30},
        ],
        "active": {"detection": "updated_csv_with_boxes_0.30_3.csv",
                   "classification": "classification_0.30_3.csv"},
    }
    (d / "mg_ai_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    data = load_mg_ai_runs(study, tmp_path)
    assert data is not None
    assert len(data["available"]) == 3, "every run must be listed, incl. repeats at the same threshold"
    # each entry carries a distinct CSV pair -> a distinct dropdown item
    pairs = {(r["detection"], r["classification"]) for r in data["available"]}
    assert len(pairs) == 3
    # each entry gets a UI label, and the newest run is active
    assert all(r.get("threshold_label") for r in data["available"])
    assert data["active"]["detection"] == "updated_csv_with_boxes_0.30_3.csv"


# ---------------------------------------------------------------------------
# 2. The refresh clears the run-once latch and reloads (the fix)
# ---------------------------------------------------------------------------

def test_refresh_reloads_dropdown_despite_run_once_latch(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_EYE_RESULT_REFRESH", raising=False)
    tab = _FakeImagingTab()
    assert tab.mg_runs_loaded is True   # the latch that used to block a reload

    assert tab.refresh_mg_ai_results() is True
    assert tab.load_calls == 1, "manifest must be re-read after a new Eagle Eye run"

    # repeated runs keep refreshing
    assert tab.refresh_mg_ai_results() is True
    assert tab.load_calls == 2


def test_refresh_is_noop_for_non_mg(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_EYE_RESULT_REFRESH", raising=False)
    tab = _FakeImagingTab(modality="DX")
    assert tab.refresh_mg_ai_results() is False
    assert tab.load_calls == 0


def test_refresh_is_noop_without_combo(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_EYE_RESULT_REFRESH", raising=False)
    tab = _FakeImagingTab(has_combo=False)
    assert tab.refresh_mg_ai_results() is False
    assert tab.load_calls == 0


def test_kill_switch_restores_legacy_no_refresh(monkeypatch):
    monkeypatch.setenv("AIPACS_EAGLE_EYE_RESULT_REFRESH", "0")
    tab = _FakeImagingTab()
    assert tab.refresh_mg_ai_results() is False
    assert tab.load_calls == 0, "flag=0 must be byte-identical legacy (no reload)"


def test_refresh_never_raises_on_deleted_widget(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_EYE_RESULT_REFRESH", raising=False)

    class _Deleted(_FakeImagingTab):
        def _load_mg_runs_into_dropdown(self):
            raise RuntimeError("Internal C++ object (QComboBox) already deleted.")

    assert _Deleted().refresh_mg_ai_results() is False  # swallowed, no crash


# ---------------------------------------------------------------------------
# 3. Wiring: window delegates, and the tab-REUSE branch triggers the refresh
# ---------------------------------------------------------------------------

def test_ai_main_window_delegates_to_imaging_tab(monkeypatch):
    monkeypatch.delenv("AIPACS_EAGLE_EYE_RESULT_REFRESH", raising=False)
    tab = _FakeImagingTab()
    assert _FakeAiWindow(tab).refresh_ai_results() is True
    assert tab.load_calls == 1

    # missing imaging tab must not raise
    assert _FakeAiWindow(None).refresh_ai_results() is False


def test_add_new_tab_widget_refreshes_reused_eagle_eye_tab():
    src = inspect.getsource(_hp_modules._HPModulesMixin.add_new_tab_widget)
    reuse = src.split("setCurrentWidget(existing_tab)", 1)
    assert len(reuse) == 2, "the Eagle Eye tab-reuse branch disappeared"
    after_reuse = reuse[1].split("return existing_tab", 1)[0]
    assert "refresh_ai_results" in after_reuse, (
        "a REUSED Eagle Eye tab must refresh its AI Results dropdown — otherwise a "
        "re-run on the same workstation never shows the new CSV"
    )
