# -*- coding: utf-8 -*-
"""Guard: Dental Imaging UI + active-series load + drag-drop (2026-06-23).

Pins:
 * the Advanced-Analysis Dental Imaging button uses the shared BLUE module style
   (not a separate purple) and the long Advanced MPR label wraps to 2 lines;
 * clicking resolves the series active-viewer → selected-thumbnail → empty-state,
   reusing the shared volume infra (active reuse, else PyDicomLazyVolume.from_series);
 * the workspace is a drop target for the app's series payload and reloads the exact
   dropped series via the injected resolver, with a static (no-render-window) preview.

Source-pin (Qt/large files, flaky mount).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "modules" / "dental_imaging"
WORKSPACE = PKG / "workspace.py"
LAUNCHER = PKG / "launcher.py"
INIT = PKG / "__init__.py"
PW_ADVANCED = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_widget_core" / "_pw_advanced.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace")


def _read_complete(p: Path, anchor: str) -> str:
    s = _read(p)
    if anchor not in s:
        pytest.skip(f"{p.name} mirror truncated (anchor missing); run on Windows")
    return s


# --- workspace: drop target + preview + empty-state ------------------------
def test_workspace_is_series_drop_target():
    s = _read(WORKSPACE)
    assert "setAcceptDrops(True)" in s
    assert "def dragEnterEvent(self, event)" in s
    assert "def dropEvent(self, event)" in s
    assert "def set_series_resolver" in s and "_series_resolver" in s
    assert "_SERIES_DROP_MIME" in s  # the app's series payload, not a position hack


def test_workspace_drop_reloads_exact_series_via_resolver():
    s = _read(WORKSPACE)
    assert "self._series_resolver(int(series_number))" in s
    assert "self.load_series(context, volume)" in s  # replaces the current series


def test_workspace_static_preview_and_empty_state():
    s = _read(WORKSPACE)
    assert "def _render_ortho_previews" in s   # axial/coronal/sagittal previews
    assert "Format_Grayscale8" in s            # static QImage preview
    assert "QVTKRenderWindowInteractor" not in s and "vtkImageViewer2" not in s
    assert "No active series" in s             # clear empty-state
    # correct series-drag MIME fallback (the bug: was missing the -number suffix)
    assert "application/x-aipacs-series-number" in s


def test_launcher_and_init_thread_resolver():
    lsrc = _read_complete(LAUNCHER, "ws.activateWindow()")  # tail anchor → full read
    assert "resolver" in lsrc and "set_series_resolver" in lsrc
    isrc = _read_complete(INIT, "def open_dental_imaging_workspace")
    assert "resolver" in isrc


# --- button: blue, shared style, wrapped long label ------------------------
def test_dental_button_uses_shared_blue_style():
    s = _read_complete(PW_ADVANCED, "def _on_advanced_mpr_clicked")
    assert "def _module_button(" in s
    assert 'self.btn_dental_imaging = _module_button("Dental Imaging")' in s
    assert "stop:0 #2563eb, stop:1 #1e40af" in s          # shared blue gradient
    assert "Advanced MPR and\\nAI segmentation" in s       # long label wraps to 2 lines


# --- _pw_advanced: resolver + fallback + drop wiring -----------------------
def test_pw_advanced_resolver_fallback_and_shared_infra():
    s = _read_complete(PW_ADVANCED, "def _bind_dental_volume_for")
    assert "def _resolve_dental_series_by_number(self, series_number)" in s
    assert "def _bind_dental_volume_for(self, context)" in s
    assert "_selected_advanced_series" in s                       # thumbnail fallback
    assert "resolver=self._resolve_dental_series_by_number" in s  # drop resolver passed
    # reuse the shared volume infra (active reuse + from_series), never a fork
    assert "bind_active_viewer_volume" in s
    assert "PyDicomLazyVolume.from_series" in s
