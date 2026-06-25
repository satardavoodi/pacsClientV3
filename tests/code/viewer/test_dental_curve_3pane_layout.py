"""Source-pin guard for the Dental Curve MPR 3-viewport startup layout (2026-06-22).

Pure source-string checks (no PySide6/VTK). Pins that Dental Curve MPR opens with a
dominant axial + smaller coronal/sagittal and NO VRT pane at startup, using
StandardMPRViewer's existing subset mechanism (layout_views) — i.e. layout-only, no
change to StandardMPRViewer, geometry, volume, or reconstruction.

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md.
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


def test_3pane_flag_default_on():
    src = _read(_TOOLBAR)
    assert "AIPACS_CURVED_MPR_3PANE_LAYOUT" in src
    # default ON: env.get(..., "1") != "0"
    assert '"AIPACS_CURVED_MPR_3PANE_LAYOUT", "1"' in src


def test_host_built_without_vrt_via_subset_mode():
    src = _read(_TOOLBAR)
    # the dental host is built with the 3 2D panes only (no 3D/VRT) via layout_views
    assert "layout_views=(['axial', 'coronal', 'sagittal'] if three_pane else None)" in src


def test_dominant_axial_layout_present():
    src = _read(_TOOLBAR)
    assert "def _apply_dental_curve_layout(self, host):" in src
    # axial spans both rows at (0,0); coronal/sagittal stacked on the right
    assert "grid.addWidget(axial, 0, 0, 2, 1)" in src
    assert "grid.addWidget(coronal, 0, 1, 1, 1)" in src
    assert "grid.addWidget(sagittal, 1, 1, 1, 1)" in src
    # axial column gets most of the width
    assert "grid.setColumnStretch(0, 3)" in src
    assert "grid.setColumnStretch(1, 1)" in src


def test_layout_is_invoked_on_the_host():
    src = _read(_TOOLBAR)
    assert "self._apply_dental_curve_layout(host)" in src
