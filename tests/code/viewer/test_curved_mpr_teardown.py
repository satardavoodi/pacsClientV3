"""Source-pin guard for the Dental Curve MPR cleanup (2026-06-22).

Pure source-string checks — imports NO PySide6 / VTK, so it runs anywhere
(offscreen sandbox or Windows) without a display or the heavy deps. It guards
the docs-+-safe-cleanup pass on the Dental Curve MPR feature:

  * the leaked-timer / use-after-free fix on CurvedMPRPanoramicView
    (parented reference-line timer + closeEvent + _teardown_curved_mpr_vtk),
    gated by AIPACS_CURVED_MPR_TEARDOWN (default on);
  * the print()->logging shadow in the three Dental-path modules;
  * the docstrings that disambiguate the duplicate CurvedMPRGenerator name.

See docs/pipelines/dental-curve-mpr.md.
"""

from pathlib import Path

import pytest

# tests/code/viewer/<this> -> repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]

_PANORAMIC = _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"
_ENGINE = _REPO_ROOT / "modules" / "mpr" / "zeta_mpr" / "curved_mpr.py"
_LEGACY = _REPO_ROOT / "modules" / "mpr" / "curved_mpr" / "curved_mpr_module.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected source file missing: {path}"
    return path.read_text(encoding="utf-8")


# --- Teardown / use-after-free fix -----------------------------------------

def test_teardown_flag_declared_default_on():
    src = _read(_PANORAMIC)
    assert 'os.environ.get("AIPACS_CURVED_MPR_TEARDOWN"' in src, (
        "teardown kill-switch flag missing"
    )
    # default must be ON: '... "1") != "0"'
    assert '"AIPACS_CURVED_MPR_TEARDOWN", "1"' in src, "flag must default ON"


def test_teardown_methods_present():
    src = _read(_PANORAMIC)
    assert "def _teardown_curved_mpr_vtk(self):" in src
    assert "def closeEvent(self, event):" in src
    # closeEvent must actually invoke the teardown
    assert "self._teardown_curved_mpr_vtk()" in src


def test_reference_line_timer_is_parented_under_flag():
    src = _read(_PANORAMIC)
    # The timer must be parented to the widget when teardown is enabled so it
    # cannot outlive / fire against a finalized render window.
    assert "QTimer(self if _CURVED_MPR_TEARDOWN else None)" in src, (
        "reference-line timer must be parented to the widget when teardown is on"
    )


def test_teardown_finalizes_both_render_windows():
    src = _read(_PANORAMIC)
    assert "panoramic_vtk_widget" in src and "crosssection_vtk_widget" in src
    assert "render_window.Finalize()" in src, "teardown must finalize render windows"


def test_teardown_is_idempotent_guarded():
    src = _read(_PANORAMIC)
    assert '_curved_mpr_torn_down' in src, "teardown must be idempotent-guarded"


# --- print() -> logging shadow ---------------------------------------------

@pytest.mark.parametrize("path", [_PANORAMIC, _ENGINE, _LEGACY])
def test_print_shadow_routes_to_logger(path):
    src = _read(path)
    assert "logging.getLogger(__name__)" in src, f"module logger missing in {path.name}"
    assert "def print(" in src, f"print() shadow missing in {path.name}"
    assert "logger.debug(" in src, f"shadow must route to logger.debug in {path.name}"


# --- Duplicate-name disambiguation docstrings ------------------------------

def test_engine_docstring_marks_dental_owner():
    src = _read(_ENGINE)
    assert "Dental Curve MPR" in src
    assert "curved_mpr_module.py" in src, (
        "engine docstring must cross-reference the legacy namesake"
    )


def test_legacy_docstring_marks_itself_legacy():
    src = _read(_LEGACY)
    assert "LEGACY" in src
    assert "zeta_mpr/curved_mpr.py" in src, (
        "legacy docstring must point at the real Dental engine"
    )
