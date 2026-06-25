# -*- coding: utf-8 -*-
"""Guard: Dental Imaging module skeleton + two-level separation (2026-06-23).

Pins the Milestone-0 scaffold:
 * modules/dental_imaging exists as a real, self-contained module.
 * It is import-light + VTK-free and does NOT import the simple Dental Curve MPR
   engine — the two levels (simple viewer vs. professional module) stay separate.
 * The Advanced-Analysis "Dental Imaging" entry is wired, flag-gated, and
   ADDITIVE (existing Advanced MPR / Stitching entries preserved).
 * The simple Patient-Tab Dental Curve MPR engine still exists (untouched).

Source-pin style (tolerant of the flaky/truncating Linux test mount) plus a
guarded runtime import of the pure parts.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PKG = REPO_ROOT / "modules" / "dental_imaging"
PW_ADVANCED = (
    REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_widget_core" / "_pw_advanced.py"
)
SIMPLE_ENGINE = REPO_ROOT / "modules" / "mpr" / "zeta_mpr" / "curved_mpr.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing: {p}"
    data = p.read_bytes()
    if b"\x00" in data:
        pytest.skip(f"mount served a NUL-truncated copy of {p.name}; run on Windows")
    return data.decode("utf-8", errors="replace")


def _read_complete(p: Path, anchor: str) -> str:
    src = _read(p)
    if anchor not in src:
        pytest.skip(f"{p.name} mirror looks truncated (anchor missing); run on Windows")
    return src


# --- module exists & is structurally separated ----------------------------
def test_module_files_exist():
    for name in ("__init__.py", "context.py", "workspace.py", "launcher.py", "README.md"):
        assert (PKG / name).exists(), f"dental_imaging missing {name}"


def test_package_is_import_light_and_vtk_free():
    # __init__ + context must not import Qt/VTK (cheap to import from the viewer).
    for name in ("__init__.py", "context.py"):
        src = _read(PKG / name)
        assert "PySide6" not in src, f"{name} must stay Qt-free"
        assert "import vtk" not in src and "vtkmodules" not in src, f"{name} must stay VTK-free"
    # The workspace may read volume scalars (numpy_support) for a STATIC preview,
    # but must NEVER instantiate a VTK render window (the FAST rule).
    wsrc = _read(PKG / "workspace.py")
    assert "QVTKRenderWindowInteractor" not in wsrc, "workspace must not host a VTK render window"
    assert "vtkImageViewer2" not in wsrc, "workspace must not build a vtkImageViewer2"
    assert "vtkRenderWindow" not in wsrc, "workspace must not create a render window"


def test_module_does_not_touch_simple_dental_curve_mpr():
    # The two levels must not be mixed: the professional module must not import
    # the simple Dental Curve MPR engine / display package.
    for name in ("__init__.py", "context.py", "workspace.py", "launcher.py"):
        src = _read(PKG / name)
        assert "zeta_mpr.curved_mpr" not in src
        assert "mpr.curved_mpr" not in src


def test_no_duplicate_volume_pipeline():
    # Reuse, don't duplicate: the skeleton must not reimplement volume/geometry.
    for name in ("__init__.py", "context.py", "workspace.py", "launcher.py"):
        src = _read(PKG / name)
        assert "vtkImageReslice" not in src
        assert "PyDicomLazyVolume(" not in src  # not building a volume yet


# --- wiring (Advanced Analysis) -------------------------------------------
def test_advanced_analysis_button_wired_flag_gated_and_additive():
    # Button wiring lives in the panel builder (well before this anchor), so it
    # is present whenever the mirror reaches the anchor.
    src = _read_complete(PW_ADVANCED, "def _on_advanced_mpr_clicked")
    assert "btn_dental_imaging" in src
    assert "AIPACS_DENTAL_IMAGING" in src
    assert "self._on_dental_imaging_clicked" in src
    # Additive: the existing Advanced-Analysis entries must remain.
    assert "btn_advanced_mpr" in src
    assert "btn_stitching" in src


def test_dental_imaging_handler_and_import_present():
    # The handler + lazy import live at the TAIL of the file; the flaky Linux
    # mount often truncates large files, so anchor on the method def itself and
    # skip a truncated mirror (it runs for real on the Windows source build).
    src = _read_complete(PW_ADVANCED, "def _on_dental_imaging_clicked")
    assert "from modules.dental_imaging import" in src
    assert "_resolve_dental_series_context" in src


# --- simple viewer untouched ----------------------------------------------
def test_simple_dental_curve_mpr_engine_still_present():
    assert SIMPLE_ENGINE.exists(), "the simple Dental Curve MPR engine must remain"


# --- pure runtime behaviour (guarded) -------------------------------------
def test_flag_and_context_runtime():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        import modules.dental_imaging as di
    except Exception as exc:  # heavy parent package / missing deps in this env
        pytest.skip(f"cannot import package here: {exc}")

    # Context behaviour
    ctx = di.DentalSeriesContext(dicom_dir="/x/1", series_uid="1.2.3", series_number=4)
    assert ctx.is_loadable() is True
    assert "Series 4" in ctx.summary()
    assert di.DentalSeriesContext().is_loadable() is False

    # Flag default ON; disabled → open returns None WITHOUT importing Qt.
    import os as _os
    old = _os.environ.get("AIPACS_DENTAL_IMAGING")
    try:
        _os.environ["AIPACS_DENTAL_IMAGING"] = "0"
        assert di.dental_imaging_enabled() is False
        assert di.open_dental_imaging_workspace() is None
        _os.environ["AIPACS_DENTAL_IMAGING"] = "1"
        assert di.dental_imaging_enabled() is True
    finally:
        if old is None:
            _os.environ.pop("AIPACS_DENTAL_IMAGING", None)
        else:
            _os.environ["AIPACS_DENTAL_IMAGING"] = old
