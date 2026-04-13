"""
Stage 1 Migration Validation — Runtime Proof
=============================================
Validates that the FAST backend switch (v2.3.3) is correctly wired:
  1. FAST config resolves to BACKEND_PYDICOM_QT at every decision point
  2. Stale BACKEND_PYDICOM config is aliased to BACKEND_PYDICOM_QT
  3. Advanced mode (force_vtk) still resolves to BACKEND_VTK
  4. VTK-path code is unreachable in FAST mode
  5. Progressive display, tools, scroll paths are Qt-gated
  6. No regression in Advanced mode resolution

Run:  python -m pytest tests/viewer/test_stage1_migration_validation.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.viewer.viewer_backend_config import (
    BACKEND_VTK,
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    resolve_viewer_backend,
    load_viewer_backend,
    _config_path,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_metadata(instances_count: int = 10, viewer_backend: str = "", force_vtk: bool = False):
    """Build a minimal metadata dict mimicking a real series."""
    instances = [{"instance_number": i + 1} for i in range(instances_count)]
    series = {"image_count": instances_count}
    if viewer_backend:
        series["viewer_backend"] = viewer_backend
    if force_vtk:
        series["force_vtk_fallback"] = True
    return {"series": series, "instances": instances}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FAST backend resolution
# ═══════════════════════════════════════════════════════════════════════════════

class TestFastBackendResolution:
    """Prove FAST mode resolves to BACKEND_PYDICOM_QT."""

    def test_config_file_reads_pydicom_qt(self):
        """The on-disk config now says pydicom_qt."""
        cfg = _config_path()
        with open(cfg, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["viewer_2d_backend"] == "pydicom_qt", (
            f"Config file should say pydicom_qt, got {data['viewer_2d_backend']}"
        )

    def test_load_viewer_backend_returns_pydicom_qt(self):
        """load_viewer_backend() reads the updated config."""
        result = load_viewer_backend()
        assert result == BACKEND_PYDICOM_QT, (
            f"load_viewer_backend() should return {BACKEND_PYDICOM_QT}, got {result}"
        )

    def test_resolve_fast_with_metadata_returns_pydicom_qt(self):
        """FAST series with instances resolves to BACKEND_PYDICOM_QT."""
        metadata = _make_metadata(instances_count=50)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM_QT)
        assert result["backend"] == BACKEND_PYDICOM_QT
        assert result["requested_backend"] == BACKEND_PYDICOM_QT
        assert result["metadata_complete"] is True

    def test_resolve_fast_init_no_metadata_falls_back_to_vtk(self):
        """Init-time call (metadata=None) correctly falls back to VTK.
        This is expected — per-series rebinding later overrides it."""
        result = resolve_viewer_backend(metadata=None, settings=BACKEND_PYDICOM_QT)
        assert result["backend"] == BACKEND_VTK, (
            "Init-time resolution with metadata=None must fall back to VTK"
        )
        assert result["metadata_complete"] is False

    def test_resolve_fast_rebind_overrides_init(self):
        """Simulates the full lifecycle: init → rebind with metadata."""
        # Init (metadata=None) → VTK fallback
        init_result = resolve_viewer_backend(metadata=None, settings=BACKEND_PYDICOM_QT)
        assert init_result["backend"] == BACKEND_VTK

        # Rebind (metadata with instances) → PYDICOM_QT
        metadata = _make_metadata(instances_count=120)
        rebind_result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM_QT)
        assert rebind_result["backend"] == BACKEND_PYDICOM_QT
        assert rebind_result["metadata_complete"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PYDICOM → PYDICOM_QT alias (safety net)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPydicomAlias:
    """Prove the v2.3.3 alias remaps stale BACKEND_PYDICOM config."""

    def test_stale_pydicom_config_remapped_to_qt(self):
        """If someone manually sets config back to pydicom_2d, alias catches it."""
        metadata = _make_metadata(instances_count=50)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_PYDICOM_QT, (
            f"Stale BACKEND_PYDICOM should alias to BACKEND_PYDICOM_QT, got {result['backend']}"
        )
        assert result["requested_backend"] == BACKEND_PYDICOM_QT

    def test_stale_pydicom_config_no_metadata_still_falls_back(self):
        """Alias remaps to PYDICOM_QT, but no instances → VTK fallback."""
        result = resolve_viewer_backend(metadata=None, settings=BACKEND_PYDICOM)
        # requested_backend is now PYDICOM_QT (aliased), but no instances → VTK
        assert result["requested_backend"] == BACKEND_PYDICOM_QT
        assert result["backend"] == BACKEND_VTK

    def test_alias_does_not_affect_vtk_backend(self):
        """BACKEND_VTK is never aliased."""
        metadata = _make_metadata(instances_count=50)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_VTK)
        assert result["backend"] == BACKEND_VTK
        assert result["requested_backend"] == BACKEND_VTK


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Advanced mode remains on VTK
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdvancedModeUnchanged:
    """Prove Advanced mode (force_vtk) always resolves to BACKEND_VTK."""

    def test_force_vtk_fallback_in_metadata(self):
        """Series with force_vtk_fallback=True resolves to VTK."""
        metadata = _make_metadata(instances_count=50, force_vtk=True)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM_QT)
        assert result["backend"] == BACKEND_VTK

    def test_explicit_vtk_settings(self):
        """Passing BACKEND_VTK directly always returns VTK."""
        metadata = _make_metadata(instances_count=50)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_VTK)
        assert result["backend"] == BACKEND_VTK

    def test_force_vtk_overrides_alias(self):
        """Even with PYDICOM alias active, force_vtk_fallback wins."""
        metadata = _make_metadata(instances_count=50, force_vtk=True)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_VTK


# ═══════════════════════════════════════════════════════════════════════════════
# 4. VTK path unreachability in FAST mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestVtkPathUnreachable:
    """Prove that VTK-only code paths are not reachable in FAST mode."""

    def test_pydicom_lazy_volume_guard(self):
        """PyDicomLazyVolume is only constructed when _active_backend == BACKEND_PYDICOM.
        After alias, BACKEND_PYDICOM never appears as resolved backend."""
        # With the alias, even requesting PYDICOM gives PYDICOM_QT
        metadata = _make_metadata(instances_count=50)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM)
        assert result["backend"] != BACKEND_PYDICOM, (
            "BACKEND_PYDICOM should never be the resolved backend after alias"
        )

    def test_no_lazy_loader_key_for_pydicom_qt(self):
        """BACKEND_PYDICOM_QT resolution never produces a lazy_loader_key."""
        metadata = _make_metadata(instances_count=50)
        result = resolve_viewer_backend(metadata=metadata, settings=BACKEND_PYDICOM_QT)
        assert not result["lazy_loader_key"], (
            "PYDICOM_QT should not produce a lazy_loader_key"
        )

    def test_backend_pydicom_cannot_survive_resolution(self):
        """Exhaustive: no combination of valid inputs produces BACKEND_PYDICOM as final backend."""
        for settings in [BACKEND_PYDICOM, BACKEND_PYDICOM_QT, BACKEND_VTK]:
            for has_instances in [True, False]:
                for force_vtk in [True, False]:
                    metadata = _make_metadata(
                        instances_count=50 if has_instances else 0,
                        force_vtk=force_vtk,
                    )
                    result = resolve_viewer_backend(metadata=metadata, settings=settings)
                    assert result["backend"] != BACKEND_PYDICOM, (
                        f"BACKEND_PYDICOM leaked through with settings={settings}, "
                        f"instances={has_instances}, force_vtk={force_vtk}: "
                        f"got backend={result['backend']}"
                    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _is_fast_viewer_mode() covers both backends
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsFastViewerMode:
    """Prove _is_fast_viewer_mode() returns True for PYDICOM_QT."""

    def test_fast_mode_with_pydicom_qt_config(self):
        """Current config (pydicom_qt) → _is_fast_viewer_mode() returns True."""
        from modules.viewer.viewer_backend_config import BACKEND_PYDICOM, BACKEND_PYDICOM_QT
        # Simulate what _is_fast_viewer_mode does
        backend = load_viewer_backend()
        assert backend in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT), (
            f"load_viewer_backend() returned {backend}, not in FAST set"
        )

    def test_fast_mode_uses_constant_not_string(self):
        """Verify the viewer controller imports BACKEND_PYDICOM_QT by name."""
        controller_path = (
            ROOT
            / "PacsClient"
            / "pacs"
            / "patient_tab"
            / "ui"
            / "patient_ui"
            / "patient_widget_viewer_controller.py"
        )
        content = controller_path.read_text(encoding="utf-8")
        assert "BACKEND_PYDICOM_QT" in content, (
            "BACKEND_PYDICOM_QT constant is not referenced in viewer controller"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Qt-bridge guard coverage in scroll/render paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestQtBridgeGuards:
    """Prove that scroll, render, and tool paths are guarded by _qt_bridge_active."""

    def test_scroll_path_has_qt_bridge_guard(self):
        """_vw_scroll.py set_slice() has _qt_bridge_active early-return."""
        scroll_path = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget" / "_vw_scroll.py"
        content = scroll_path.read_text(encoding="utf-8")
        assert "_qt_bridge_active" in content, "set_slice() must guard on _qt_bridge_active"
        # Verify it appears in the set_slice context
        lines = content.split("\n")
        in_set_slice = False
        found_guard = False
        for line in lines:
            if "def set_slice" in line:
                in_set_slice = True
            if in_set_slice and "_qt_bridge_active" in line:
                found_guard = True
                break
            if in_set_slice and line.strip().startswith("def ") and "set_slice" not in line:
                break
        assert found_guard, "set_slice() must check _qt_bridge_active for Qt early-return"

    def test_render_path_has_qt_bridge_guard(self):
        """_vw_render.py has _qt_bridge_active guard."""
        render_path = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget" / "_vw_render.py"
        content = render_path.read_text(encoding="utf-8")
        assert "_qt_bridge_active" in content, "_vw_render.py must guard on _qt_bridge_active"

    def test_wheel_event_has_qt_bridge_guard(self):
        """wheelEvent in _vw_scroll.py has _qt_bridge_active early-return."""
        scroll_path = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget" / "_vw_scroll.py"
        content = scroll_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        in_wheel = False
        found_guard = False
        for line in lines:
            if "def wheelEvent" in line:
                in_wheel = True
            if in_wheel and "_qt_bridge_active" in line:
                found_guard = True
                break
            if in_wheel and line.strip().startswith("def ") and "wheelEvent" not in line:
                break
        assert found_guard, "wheelEvent() must check _qt_bridge_active"

    def test_interactor_style_has_qt_bridge_guard(self):
        """set_new_interactorstyle routes to _QtBridgeStyle when _qt_bridge_active."""
        interactor_path = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget" / "_vw_interactor.py"
        content = interactor_path.read_text(encoding="utf-8")
        assert "_qt_bridge_active" in content, "Interactor must check _qt_bridge_active"
        assert "_QtBridgeStyle" in content, "Interactor must reference _QtBridgeStyle"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Progressive display path works for FAST Qt backend
# ═══════════════════════════════════════════════════════════════════════════════

class TestProgressiveDisplayPath:
    """Prove progressive display path is compatible with PYDICOM_QT."""

    def test_grow_progressive_has_qt_bridge_path(self):
        """_grow_progressive_fast or equivalent checks _qt_bridge_active → bridge.grow()."""
        vc_path = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        # Check in viewer controller mixins
        found_grow_qt = False
        for py_file in vc_path.rglob("_vc_progressive*.py"):
            content = py_file.read_text(encoding="utf-8")
            if "bridge" in content.lower() and "grow" in content.lower():
                found_grow_qt = True
                break
        if not found_grow_qt:
            # Also check main viewer controller
            vc_main = vc_path / "patient_widget_viewer_controller.py"
            if vc_main.exists():
                content = vc_main.read_text(encoding="utf-8")
                if "_qt_bridge_active" in content and "grow" in content:
                    found_grow_qt = True
        assert found_grow_qt, "Progressive display must have Qt bridge grow path"

    def test_is_fast_viewer_mode_gates_progressive(self):
        """on_series_images_progress checks _is_fast_viewer_mode()."""
        vc_path = ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        found = False
        for py_file in vc_path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if "_is_fast_viewer_mode" in content and "series_images_progress" in content:
                found = True
                break
        assert found, "Progressive display must check _is_fast_viewer_mode()"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Exhaustive resolution matrix
# ═══════════════════════════════════════════════════════════════════════════════

class TestExhaustiveResolutionMatrix:
    """Exhaustive truth table for resolve_viewer_backend outcomes."""

    @pytest.mark.parametrize("settings,has_instances,force_vtk,expected_backend", [
        # FAST paths — all resolve to PYDICOM_QT (never PYDICOM)
        (BACKEND_PYDICOM_QT, True, False, BACKEND_PYDICOM_QT),
        (BACKEND_PYDICOM_QT, False, False, BACKEND_VTK),        # no instances → VTK fallback
        (BACKEND_PYDICOM_QT, True, True, BACKEND_VTK),          # force_vtk wins
        # Aliased PYDICOM paths — remap to PYDICOM_QT then same rules
        (BACKEND_PYDICOM, True, False, BACKEND_PYDICOM_QT),     # alias active
        (BACKEND_PYDICOM, False, False, BACKEND_VTK),            # alias + no instances
        (BACKEND_PYDICOM, True, True, BACKEND_VTK),              # alias + force_vtk
        # Advanced paths — always VTK
        (BACKEND_VTK, True, False, BACKEND_VTK),
        (BACKEND_VTK, False, False, BACKEND_VTK),
        (BACKEND_VTK, True, True, BACKEND_VTK),
    ])
    def test_resolution_truth_table(self, settings, has_instances, force_vtk, expected_backend):
        metadata = _make_metadata(
            instances_count=50 if has_instances else 0,
            force_vtk=force_vtk,
        )
        result = resolve_viewer_backend(metadata=metadata, settings=settings)
        assert result["backend"] == expected_backend, (
            f"settings={settings}, instances={has_instances}, force_vtk={force_vtk}: "
            f"expected {expected_backend}, got {result['backend']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 9. BACKEND_PYDICOM never survives as resolved backend
# ═══════════════════════════════════════════════════════════════════════════════

class TestPydicomNeverResolved:
    """The old FAST backend (pydicom_2d) must NEVER be the resolved backend."""

    def test_pydicom_cannot_be_final_backend_with_instances(self):
        metadata = _make_metadata(instances_count=100)
        for settings in [BACKEND_PYDICOM, BACKEND_PYDICOM_QT, BACKEND_VTK]:
            result = resolve_viewer_backend(metadata=metadata, settings=settings)
            assert result["backend"] != BACKEND_PYDICOM

    def test_pydicom_cannot_be_final_backend_without_instances(self):
        metadata = _make_metadata(instances_count=0)
        for settings in [BACKEND_PYDICOM, BACKEND_PYDICOM_QT, BACKEND_VTK]:
            result = resolve_viewer_backend(metadata=metadata, settings=settings)
            assert result["backend"] != BACKEND_PYDICOM

    def test_pydicom_cannot_be_final_backend_none_metadata(self):
        for settings in [BACKEND_PYDICOM, BACKEND_PYDICOM_QT, BACKEND_VTK]:
            result = resolve_viewer_backend(metadata=None, settings=settings)
            assert result["backend"] != BACKEND_PYDICOM
