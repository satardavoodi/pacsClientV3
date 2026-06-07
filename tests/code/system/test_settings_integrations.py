"""Guards: Settings ↔ viewer reconnects (2026-06-06).

1. Tools Settings actually reach the viewers:
   - apply_to_fast_viewer_styles() pushes saved values into the FAST
     renderer's style constants (read at render time → next repaint).
   - Called at startup (preload) and on Settings "Save Changes".
   - Advanced/VTK interactor styles (ruler/angle/arrow/ROI) read the saved
     style at tool creation; reference line reads it on BOTH backends.

2. Viewer Configuration modality grid drives:
   - the Home Page modality filter checkboxes (add/remove on Save), and
   - per-modality default layouts — all defaults are 1 × 2 for now.
"""
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def stub_qta(monkeypatch):
    from PySide6.QtGui import QIcon
    import qtawesome
    monkeypatch.setattr(qtawesome, "icon", lambda *a, **k: QIcon())
    yield


# ───────────────────────────── 1. tools settings → viewers ──────────────

def test_apply_to_fast_viewer_styles_mutates_constants(monkeypatch):
    from PacsClient.pacs.patient_tab.utils import tools_settings as ts
    from modules.viewer.tools import styles

    saved = {
        name: getattr(styles, name)
        for name in (
            "RULER_COLOR", "RULER_LINE_WIDTH", "LABEL_FONT_SIZE",
            "ANGLE_COLOR", "ANGLE_LINE_WIDTH", "ARROW_COLOR",
            "ARROW_LINE_WIDTH", "ROI_COLOR", "ROI_LINE_WIDTH",
            "CIRCLE_ROI_COLOR", "CIRCLE_ROI_LINE_WIDTH",
        )
    }
    try:
        custom = ts.ToolsSettings(
            ruler=ts.ToolStyle(line_width=4.0, color=(1.0, 0.0, 0.0), font_size=30),
            angle=ts.ToolStyle(line_width=2.0, color=(0.0, 0.0, 1.0)),
            arrow=ts.ToolStyle(line_width=5.0, color=(1.0, 1.0, 0.0)),
            rectangle=ts.ToolStyle(line_width=3.0, color=(0.0, 1.0, 1.0)),
        )

        class _StubManager:
            def get_settings(self):
                return custom

        monkeypatch.setattr(ts, "get_tools_settings", lambda: _StubManager())

        assert ts.apply_to_fast_viewer_styles() is True
        assert styles.RULER_COLOR == (255, 0, 0)
        assert styles.RULER_LINE_WIDTH == 4
        assert styles.LABEL_FONT_SIZE == 30
        assert styles.ANGLE_COLOR == (0, 0, 255)
        assert styles.ARROW_COLOR == (255, 255, 0)
        assert styles.ARROW_LINE_WIDTH == 5
        assert styles.ROI_COLOR == (0, 255, 255)
        assert styles.CIRCLE_ROI_COLOR == (0, 255, 255)
    finally:
        for name, value in saved.items():
            setattr(styles, name, value)


def test_bridge_called_at_startup_and_on_save():
    from PacsClient.pacs.patient_tab.utils import preload_settings
    src = inspect.getsource(preload_settings.preload_tools_settings)
    assert "apply_to_fast_viewer_styles" in src

    save_src = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "settings_ui"
                / "tools_settings_ui.py").read_text(encoding="utf-8", errors="ignore")
    assert "apply_to_fast_viewer_styles" in save_src


def test_vtk_styles_read_saved_settings():
    base = _ROOT / "modules" / "viewer" / "interactor_styles"
    expectations = {
        "ruler_interactorstyle.py": "get_ruler_style",
        "angle_interactorstyle.py": "get_angle_style",
        "arrow_interactorstyle.py": "get_arrow_style",
        "roi_interactorstyle.py": "get_rectangle_style",
    }
    for fname, getter in expectations.items():
        src = (base / fname).read_text(encoding="utf-8", errors="ignore")
        assert getter in src, f"{fname} must honor saved Tools Settings ({getter})"


def test_reference_line_uses_saved_style_on_both_backends():
    src = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
           / "patient_widget_core" / "_pw_sync.py").read_text(encoding="utf-8", errors="ignore")
    assert "get_reference_line_style" in src
    # the hardcoded literals must remain only as fallback defaults
    assert "_rl_color" in src and "_rl_width" in src


# ─────────────────────── 2. modality grid → home filters / layouts ──────

def test_home_filter_modalities_come_from_grid_config(qapp, stub_qta, tmp_path, monkeypatch):
    import PacsClient.utils.config as cfg_mod

    cfg = {
        "default": {"rows": 1, "cols": 2},
        "modality_layouts": {
            "CT": {"rows": 1, "cols": 2},
            "PX": {"rows": 1, "cols": 2},   # the Panorex example
        },
    }
    (tmp_path / "modality_grid.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "SOCKET_CONFIG_PATH", tmp_path)

    from PacsClient.pacs.workstation_ui.home_ui.patient_search_widget import PatientSearchWidget
    w = PatientSearchWidget()
    assert set(w.modality_checks.keys()) == {"CT", "PX"}

    # user ticks PX; settings then REMOVE PX and ADD US → reload reflects it,
    # surviving check-states preserved
    w.modality_checks["CT"].setChecked(True)
    cfg["modality_layouts"] = {"CT": {"rows": 1, "cols": 2}, "US": {"rows": 1, "cols": 2}}
    (tmp_path / "modality_grid.json").write_text(json.dumps(cfg), encoding="utf-8")
    w.reload_modalities()
    assert set(w.modality_checks.keys()) == {"CT", "US"}
    assert w.modality_checks["CT"].isChecked()
    assert not w.modality_checks["US"].isChecked()


def test_home_filter_falls_back_when_config_missing(qapp, stub_qta, tmp_path, monkeypatch):
    import PacsClient.utils.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "SOCKET_CONFIG_PATH", tmp_path / "nope")

    from PacsClient.pacs.workstation_ui.home_ui.patient_search_widget import PatientSearchWidget
    w = PatientSearchWidget()
    assert set(w.modality_checks.keys()) == set(w._DEFAULT_FILTER_MODALITIES)


def test_all_default_modality_layouts_are_1x2():
    from PacsClient.pacs.workstation_ui.settings_ui.viewerconfigsetting import (
        ModalityGridConfigWidget,
    )
    assert ModalityGridConfigWidget.DEFAULT_LAYOUTS, "defaults must exist"
    for modality, layout in ModalityGridConfigWidget.DEFAULT_LAYOUTS.items():
        assert tuple(layout) == (1, 2), f"{modality} default must be 1x2"


def test_first_display_applies_modality_layout():
    """The open pipeline creates viewers with the GLOBAL default (modality
    unknown); the first-display choke points must re-apply the configured
    per-modality layout (MG → 2×2 etc.) before placing the series."""
    src = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
           / "_vc_warmup.py").read_text(encoding="utf-8", errors="ignore")
    assert "_apply_modality_layout_for_first_display" in src
    # both first-display paths (all-viewers + progressive primary) call it
    assert src.count("self._apply_modality_layout_for_first_display(metadata)") >= 2
    # the helper applies via the controller without flagging user-modified
    assert "apply_multi_viewer(tuple(optimal), modify_by_user=False)" in src


def test_modality_layout_lookup_is_case_insensitive():
    src = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
           / "_vc_load.py").read_text(encoding="utf-8", errors="ignore")
    assert "strip().upper()" in src.split("def _get_default_layout_from_config", 1)[1].split("def ", 1)[0], (
        "modality lookup must normalize case ('mg'/'Mg'/'MG ' all match)"
    )


def test_settings_save_refreshes_home_filters():
    src = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "AIPacs_ui.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    assert "reload_modalities" in src, (
        "modality-grid Save must refresh the Home Page modality filter list"
    )
