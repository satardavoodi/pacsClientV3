"""Source-pin guard for Dental Curve MPR cross-section slice navigation (2026-06-22):
slider + counter under the cross-section panel, synced to the reference line.

Pure source-string checks (no PySide6/VTK). Runtime validated on the source build.

See docs/plans/architecture/UNIFIED_MPR_3D_PIPELINE_DIRECTION_2026-06-22.md.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PANORAMIC = (
    _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_xsection_nav_flag_default_on():
    src = _read(_PANORAMIC)
    assert "AIPACS_CURVED_MPR_XSECTION_NAV" in src
    assert '"AIPACS_CURVED_MPR_XSECTION_NAV", "1"' in src  # default ON


def test_crosssection_panel_has_slider_and_counter():
    src = _read(_PANORAMIC)
    assert "self._xsection_slider = QSlider(Qt.Horizontal)" in src
    assert "self._xsection_count_label" in src
    assert "self._xsection_slider.valueChanged.connect(self._on_xsection_slider_changed)" in src


def test_slider_drives_slice_and_reference_line():
    src = _read(_PANORAMIC)
    assert "def _on_xsection_slider_changed(self, value):" in src
    assert "self.crosssection_viewer.SetSlice(value)" in src
    assert "self._update_reference_line(value)" in src


def test_slider_initialised_and_kept_in_sync():
    src = _read(_PANORAMIC)
    assert "def _init_xsection_slider(self):" in src
    assert "self._init_xsection_slider()" in src  # called from _setup_viewers
    assert "def _sync_xsection_slider(self, value):" in src
    # _check_slice_change keeps the slider in sync with VTK-driven slice changes
    assert "self._sync_xsection_slider(current_slice)" in src
