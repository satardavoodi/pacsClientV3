"""
Guard tests — EagleEye MG viewport fixes (2026-07-14).

Covers the two PURE helpers introduced to address the reported viewport bugs:

  • enforce_single_image_metadata (bug #1 corrective, opt-in) — trims an MG series'
    metadata to its single intended image ONLY when genuinely different images were
    stacked (distinct SOP UIDs), never a multi-frame series.

  • resolve_thumb_lat_view (bug #2) — resolves laterality/view from series metadata
    then DICOM tags, never from series order.

Both live in Qt-importing packages, so — like test_cursor3d_two_stage — we register
the package chain WITHOUT executing the GUI __init__ files, then load only the
functions under test by pulling the module source and exec-ing the pure helpers.

Pure: no Qt/VTK. Runs headless:
    python3 -m pytest tests/code/ai_imaging/test_eagleeye_viewport_fixes.py -q -p no:debugging
"""

from __future__ import annotations

import os
import pathlib
import re
import types

import pytest


_ROOT = pathlib.Path(__file__).resolve().parents[3]


# ─── Load the two pure helpers without importing their Qt-heavy modules ───────
#
# vtk_widget.py and patient_widget.py both import PySide6/VTK at module load. We
# only need two self-contained functions from them, so we extract each function's
# source and exec it in a clean namespace. If a helper ever grows a Qt/VTK
# dependency in its BODY, these tests fail loudly — which is the regression we want
# to catch (the helpers are meant to stay pure and unit-testable).

def _function_source(module_path: pathlib.Path, func_name: str) -> str:
    """Return the exact source of a top-level `def func_name(...)` block.

    Simple, regex-free line scan: from the `def` line to just before the next
    line that begins a new top-level `def `/`class ` (or EOF).
    """
    lines = module_path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(f"def {func_name}("):
            start = i
            break
    assert start is not None, f"{func_name} not found in {module_path.name}"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("def ") or lines[j].startswith("class "):
            end = j
            break
    return "".join(lines[start:end])


def _load_function(module_path: pathlib.Path, func_name: str, helpers: str = "") -> callable:
    ns: dict = {
        "os": os,
        "logging": __import__("logging"),
        "Path": pathlib.Path,
        "logger": __import__("logging").getLogger("test"),
    }
    if helpers:
        exec(helpers, ns)
    exec(_function_source(module_path, func_name), ns)
    return ns[func_name]


_VTK_WIDGET = _ROOT / "modules" / "ai_imaging" / "ai_module_ui" / "overrides" / "vtk_widget.py"
_PATIENT_WIDGET = _ROOT / "modules" / "ai_imaging" / "ai_module_ui" / "overrides" / "patient_widget.py"


# enforce_single_image_metadata reads a module-level flag; provide it.
enforce_single_image_metadata = _load_function(
    _VTK_WIDGET, "enforce_single_image_metadata",
    helpers="_MG_ENFORCE_SINGLE_IMAGE = True\n",
)
resolve_thumb_lat_view = _load_function(_PATIENT_WIDGET, "resolve_thumb_lat_view")


def _meta(instances, modality="MG"):
    return {"series": {"modality": modality}, "instances": instances}


def _inst(sop, path="x.dcm"):
    return {"sop_uid": sop, "instance_path": path}


# ─── bug #1 corrective: enforce_single_image_metadata ────────────────────────

def test_two_stacked_distinct_images_are_trimmed_to_one():
    """The append-bug signature: >1 instance with DIFFERENT SOP UIDs -> keep first."""
    md = _meta([_inst("SOP.A", "A.dcm"), _inst("SOP.B", "B.dcm")])
    out = enforce_single_image_metadata(md, series_index=4, logger=None)
    assert len(out["instances"]) == 1
    assert out["instances"][0]["sop_uid"] == "SOP.A"


def test_single_image_series_is_untouched():
    md = _meta([_inst("SOP.A")])
    out = enforce_single_image_metadata(md, series_index=4, logger=None)
    assert out["instances"] == md["instances"]


def test_multiframe_series_one_sop_is_never_trimmed():
    """
    A multi-frame MG series is ONE file / ONE SOP that the loader may expand into
    several instance entries sharing that SOP. It must NOT be collapsed — doing so
    would drop real frames. Distinct-SOP count == 1 → leave it alone.
    """
    md = _meta([_inst("SOP.SAME", "f.dcm"), _inst("SOP.SAME", "f.dcm")])
    out = enforce_single_image_metadata(md, series_index=4, logger=None)
    assert len(out["instances"]) == 2, "multi-frame (single SOP) must be preserved"


def test_non_mg_series_is_untouched():
    md = _meta([_inst("SOP.A"), _inst("SOP.B")], modality="CT")
    out = enforce_single_image_metadata(md, series_index=1, logger=None)
    assert len(out["instances"]) == 2


def test_original_metadata_is_not_mutated_in_place():
    """Trimming must return a NEW dict — the caller's original (and any cache entry)
    must be preserved. A subtle in-place mutation would corrupt shared metadata."""
    original = _meta([_inst("SOP.A", "A.dcm"), _inst("SOP.B", "B.dcm")])
    out = enforce_single_image_metadata(original, series_index=4, logger=None)
    assert len(original["instances"]) == 2, "original must be untouched"
    assert out is not original


def test_flag_off_is_a_no_op(monkeypatch):
    """With the flag off (the default), even the bug signature is left untouched —
    the corrective is opt-in until the live diagnostic confirms the mechanism."""
    off = _load_function(
        _VTK_WIDGET, "enforce_single_image_metadata",
        helpers="_MG_ENFORCE_SINGLE_IMAGE = False\n",
    )
    md = _meta([_inst("SOP.A"), _inst("SOP.B")])
    out = off(md, series_index=4, logger=None)
    assert len(out["instances"]) == 2


# ─── bug #2: resolve_thumb_lat_view ──────────────────────────────────────────

def test_laterality_view_from_metadata_when_present():
    thumb = {"metadata": {"series": {"laterality": "L", "view_position": "MLO"}}}
    assert resolve_thumb_lat_view(thumb) == ("L", "MLO")


def test_laterality_is_truncated_to_single_letter():
    thumb = {"metadata": {"series": {"laterality": "LEFT", "view_position": "CC"}}}
    lat, vp = resolve_thumb_lat_view(thumb)
    assert lat == "L" and vp == "CC"


def test_blank_metadata_and_no_file_returns_empty_not_a_guess():
    """When neither metadata nor DICOM can determine it, return ('','') — never a
    guess from series order. The caller then declines to auto-pair rather than
    pairing the wrong views."""
    thumb = {"metadata": {"series": {}, "instances": [{"instance_path": "/no/such.dcm"}]}}
    assert resolve_thumb_lat_view(thumb) == ("", "")


def test_metadata_takes_priority_over_dicom():
    """Metadata is the already-parsed authority; a present metadata value must not
    trigger a (slow) DICOM read."""
    thumb = {
        "metadata": {
            "series": {"laterality": "R", "view_position": "CC"},
            "instances": [{"instance_path": "/should/not/be/read.dcm"}],
        }
    }
    assert resolve_thumb_lat_view(thumb) == ("R", "CC")


def test_helpers_stay_pure_no_qt_or_vtk():
    """The corrective and resolver must not import Qt/VTK in their bodies — the
    offscreen test lane depends on it."""
    qt = re.compile(r"^\s*(?:from|import)\s+PySide6\b", re.MULTILINE)
    vtk = re.compile(r"^\s*(?:from|import)\s+vtk\b", re.MULTILINE)
    for path, fn in ((_VTK_WIDGET, "enforce_single_image_metadata"),
                     (_PATIENT_WIDGET, "resolve_thumb_lat_view")):
        body = _function_source(path, fn)
        assert not vtk.search(body), f"{fn} must not import VTK"
        assert not qt.search(body), f"{fn} must not import Qt"
