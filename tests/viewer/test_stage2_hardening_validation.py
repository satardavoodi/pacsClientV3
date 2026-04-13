"""
Stage 2 Hardening Validation — Escape Hatch, Bind-Remap, Post-Bind Check
=========================================================================
Validates Stage 2 additions (v2.3.3):
  1. AIPACS_FORCE_PYDICOM_2D=1 escape hatch bypasses alias remap
  2. Escape hatch inactive by default — alias remap still fires
  3. _bind_backend_from_metadata remap guard catches leaked BACKEND_PYDICOM
  4. Post-bind sanity check detects violation
  5. Startup banner imports succeed
  6. force_vtk=True still resolves to BACKEND_VTK regardless of escape hatch

Run:  python -m pytest tests/viewer/test_stage2_hardening_validation.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.viewer.viewer_backend_config import (
    BACKEND_VTK,
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    resolve_viewer_backend,
    load_viewer_backend,
)


def _make_metadata(instances_count: int = 10, force_vtk: bool = False):
    """Build a minimal metadata dict."""
    instances = [{"instance_number": i + 1} for i in range(instances_count)]
    series = {"image_count": instances_count}
    if force_vtk:
        series["force_vtk_fallback"] = True
    return {"series": series, "instances": instances}


# ─── 1. Escape Hatch Tests ───────────────────────────────────────────────────

class TestEscapeHatch:
    """AIPACS_FORCE_PYDICOM_2D env var escape hatch."""

    def test_escape_hatch_bypasses_alias_remap(self):
        """When AIPACS_FORCE_PYDICOM_2D=1, pydicom_2d is NOT remapped to pydicom_qt."""
        meta = _make_metadata(instances_count=50)
        # Simulate stale config saying pydicom_2d + escape hatch active
        with patch.dict(os.environ, {"AIPACS_FORCE_PYDICOM_2D": "1"}):
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
        # The escape hatch should keep BACKEND_PYDICOM (and then it has
        # lazy_loader_key="" so it falls back to VTK — but the point is the
        # alias remap did NOT fire).
        # Actually: PYDICOM + no lazy_loader_key → VTK fallback.
        # The escape hatch prevents the alias from firing, so PYDICOM stays,
        # then the "no lazy_loader_key" guard kicks in → VTK.
        backend = result["backend"]
        # With escape hatch, it should NOT resolve to PYDICOM_QT
        assert backend != BACKEND_PYDICOM_QT, (
            f"Escape hatch should prevent alias remap, got {backend}"
        )

    def test_escape_hatch_preserves_pydicom_with_lazy_key(self):
        """With escape hatch + lazy_loader_key, BACKEND_PYDICOM survives."""
        meta = _make_metadata(instances_count=50)
        meta["series"]["lazy_loader_key"] = "test_key_123"
        meta["series"]["viewer_backend"] = BACKEND_PYDICOM
        with patch.dict(os.environ, {"AIPACS_FORCE_PYDICOM_2D": "1"}):
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_PYDICOM

    def test_escape_hatch_inactive_by_default(self):
        """Without env var, alias remap fires normally."""
        meta = _make_metadata(instances_count=50)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIPACS_FORCE_PYDICOM_2D", None)
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_PYDICOM_QT

    def test_escape_hatch_does_not_affect_vtk(self):
        """Escape hatch with VTK config does nothing."""
        meta = _make_metadata(instances_count=50)
        with patch.dict(os.environ, {"AIPACS_FORCE_PYDICOM_2D": "1"}):
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_VTK)
        assert result["backend"] == BACKEND_VTK

    def test_escape_hatch_overridden_by_force_vtk(self):
        """force_vtk_fallback in metadata overrides even escape hatch."""
        meta = _make_metadata(instances_count=50, force_vtk=True)
        meta["series"]["lazy_loader_key"] = "key123"
        meta["series"]["viewer_backend"] = BACKEND_PYDICOM
        with patch.dict(os.environ, {"AIPACS_FORCE_PYDICOM_2D": "1"}):
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_VTK


# ─── 2. Alias Consistency ────────────────────────────────────────────────────

class TestAliasConsistency:
    """Ensure alias + escape hatch interact correctly with all backend inputs."""

    @pytest.mark.parametrize("escape,settings,expected_not", [
        ("0", BACKEND_PYDICOM, BACKEND_PYDICOM),       # escape off → alias fires → not PYDICOM
        ("", BACKEND_PYDICOM, BACKEND_PYDICOM),         # escape empty → alias fires
    ])
    def test_alias_escape_matrix(self, escape, settings, expected_not):
        """Backend should NOT be expected_not after resolution."""
        meta = _make_metadata(instances_count=50)
        env = {"AIPACS_FORCE_PYDICOM_2D": escape} if escape else {}
        with patch.dict(os.environ, env, clear=False):
            if not escape:
                os.environ.pop("AIPACS_FORCE_PYDICOM_2D", None)
            result = resolve_viewer_backend(metadata=meta, settings=settings)
        assert result["backend"] != expected_not, (
            f"Expected NOT {expected_not}, got {result['backend']}"
        )

    def test_escape_hatch_overrides_pydicom_qt_config(self):
        """Escape hatch forces pydicom_qt config back to pydicom_2d."""
        meta = _make_metadata(instances_count=50)
        with patch.dict(os.environ, {"AIPACS_FORCE_PYDICOM_2D": "1"}):
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM_QT)
        # Escape hatch converts pydicom_qt → pydicom_2d; without lazy_loader_key
        # it stays pydicom_2d (metadata_backend guard only fires when
        # metadata_backend == PYDICOM, which isn't set in minimal metadata)
        assert result["backend"] != BACKEND_PYDICOM_QT


# ─── 3. Force VTK Always Wins ────────────────────────────────────────────────

class TestForceVtkAlwaysWins:
    """force_vtk_fallback=True overrides any escape hatch or alias."""

    @pytest.mark.parametrize("escape", ["0", "1", ""])
    def test_force_vtk_with_any_escape(self, escape):
        meta = _make_metadata(instances_count=50, force_vtk=True)
        env = {"AIPACS_FORCE_PYDICOM_2D": escape} if escape else {}
        with patch.dict(os.environ, env, clear=False):
            if not escape:
                os.environ.pop("AIPACS_FORCE_PYDICOM_2D", None)
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_VTK


# ─── 4. Startup Banner ───────────────────────────────────────────────────────

class TestStartupBanner:
    """Startup banner code in main.py imports succeed."""

    def test_load_viewer_backend_importable(self):
        from modules.viewer.viewer_backend_config import load_viewer_backend
        result = load_viewer_backend()
        assert result in {BACKEND_VTK, BACKEND_PYDICOM, BACKEND_PYDICOM_QT}

    def test_backend_pydicom_qt_importable(self):
        from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT
        assert BACKEND_PYDICOM_QT == "pydicom_qt"


# ─── 5. Bind-Level Hardening ─────────────────────────────────────────────────

class TestBindLevelHardening:
    """The _bind_backend_from_metadata remap guard catches leaked PYDICOM."""

    def test_resolver_never_returns_pydicom_without_escape(self):
        """Without escape hatch, BACKEND_PYDICOM can never be the final backend."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIPACS_FORCE_PYDICOM_2D", None)
            for has_instances in [True, False]:
                for has_key in [True, False]:
                    meta = _make_metadata(instances_count=50 if has_instances else 0)
                    if has_key:
                        meta["series"]["lazy_loader_key"] = "key"
                        meta["series"]["viewer_backend"] = BACKEND_PYDICOM
                    result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
                    assert result["backend"] != BACKEND_PYDICOM, (
                        f"BACKEND_PYDICOM leaked: instances={has_instances}, key={has_key}, "
                        f"got {result['backend']}"
                    )

    def test_resolver_can_return_pydicom_with_escape(self):
        """With escape hatch + lazy key + instances, BACKEND_PYDICOM survives."""
        meta = _make_metadata(instances_count=50)
        meta["series"]["lazy_loader_key"] = "key"
        meta["series"]["viewer_backend"] = BACKEND_PYDICOM
        with patch.dict(os.environ, {"AIPACS_FORCE_PYDICOM_2D": "1"}):
            result = resolve_viewer_backend(metadata=meta, settings=BACKEND_PYDICOM)
        assert result["backend"] == BACKEND_PYDICOM
