"""Regression guard: Dental Curve MPR must NOT write the read-only
PatientWidget.selected_widget property (2026-06-22).

PatientWidget.selected_widget is a read-only property delegating to
viewer_controller.selected_widget. Assigning `patient_widget.selected_widget = X`
raises AttributeError ("property ... has no setter"), which previously tripped the
Dental Curve MPR result display into its simple-dialog fallback and crashed the
cross-section viewport click handler. Writes must go through viewer_controller.

Pure source-string checks (no PySide6/VTK).
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLBAR = (
    _REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)
_PANORAMIC = (
    _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_toolbar_sets_selected_widget_via_controller():
    src = _read(_TOOLBAR)
    # the curved-MPR result/placement assignments must go through viewer_controller
    assert "self.patient_widget.viewer_controller.selected_widget = viewer_widget.active_viewport" in src
    # and must NOT write the read-only property directly
    assert "self.patient_widget.selected_widget = viewer_widget.active_viewport" not in src


def test_panoramic_click_handler_uses_controller():
    src = _read(_PANORAMIC)
    assert "controller.selected_widget = viewport" in src
    # the old direct write must be gone
    assert "parent.selected_widget = viewport" not in src
