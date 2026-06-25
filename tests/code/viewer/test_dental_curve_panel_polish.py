"""Source-pin guard for the Dental Curve MPR panel/UI polish (2026-06-22):
professional styling, panoramic-thickness (trough) control wired to generation, and
top-right tool-palette positioning.

Pure source-string checks (no PySide6/VTK). Runtime validated on the source build.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLBAR = (
    _REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_panel_imports_qslider():
    src = _read(_TOOLBAR)
    assert "QListWidget, QSlider" in src


def test_panel_has_professional_header():
    src = _read(_TOOLBAR)
    assert 'header = QLabel("Dental Curve MPR")' in src
    # purple Path Builder header is gone
    assert 'QLabel("Curved MPR Path Builder")' not in src


def test_panoramic_thickness_control_wired_to_generation():
    src = _read(_TOOLBAR)
    assert "self._curved_mpr_thickness_mm = 10.0" in src
    assert "Panoramic thickness" in src
    assert "def _on_thickness_changed(v):" in src
    # the control feeds generate_panoramic_view
    assert "slice_thickness_mm=float(getattr(self, '_curved_mpr_thickness_mm', 10.0))" in src


def test_panel_repositioned_as_tool_palette():
    src = _read(_TOOLBAR)
    assert "pw.mapToGlobal(QPoint(max(0, pw.width() - panel_w - 16), 72))" in src
