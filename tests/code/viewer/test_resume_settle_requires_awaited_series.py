"""Guard: disk-ready resume must not "settle" the awaited series while the viewport
still shows a DIFFERENT series (48101 Study 3, 2026-06-29).

Symptom: a multi-study patient with a previous exam. Viewport shows Study 1's series
(10 slices). User drags Study 3 (display key 2000001, 5 images on disk). The disk-ready
resume's settle check was `visible >= count` → 10 >= 5 → it cleared Study 3's awaiting
flag WITHOUT loading it, so Study 3 never displayed and Study 1's series stayed on
screen ("loaded a Study-1 series instead of Study 3").

Fix: `_viewport_displayed_series_number(vtk_w)` reads the FAST container's live
`_qt_bridge.metadata['series']['series_number']`; the settle-by-visible path only fires
when that equals the awaited display key. Flag AIPACS_RESUME_SETTLE_REQUIRE_SERIES
(default on). Source-pins + a behavioral test of the helper.
"""
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_progressive.py"
    ).read_text(encoding="utf-8")


def test_settle_gate_source_pins():
    src = _src()
    assert 'os.getenv("AIPACS_RESUME_SETTLE_REQUIRE_SERIES"' in src
    assert "def _viewport_displayed_series_number(self, vtk_w):" in src
    # the settle-by-visible decision now requires the viewport to show the awaited series
    assert "_settled_visible = _vis_settled > 0 and _vis_settled >= count and _shows_awaited" in src
    # and it flips off when a different series is on screen
    assert "if _cur_disp_sn is not None and str(_cur_disp_sn) != str(display_key):" in src
    assert "_shows_awaited = False" in src


def test_displayed_series_number_helper_behavioral():
    pytest.importorskip("PySide6")
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import (
            _ProgressiveDisplayMixin as _MX,
        )
    except Exception:
        # The mixin name may differ; fall back to importing the module and locating it.
        import importlib
        mod = importlib.import_module(
            "PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive")
        _MX = None
        for _n in dir(mod):
            _o = getattr(mod, _n)
            if isinstance(_o, type) and hasattr(_o, "_viewport_displayed_series_number"):
                _MX = _o
                break
        if _MX is None:
            pytest.skip("mixin with _viewport_displayed_series_number not found")

    helper = _MX._viewport_displayed_series_number
    fake_self = types.SimpleNamespace()

    # FAST container showing Study 1's series '4'.
    w_study1 = types.SimpleNamespace(
        _qt_bridge=types.SimpleNamespace(metadata={"series": {"series_number": "4"}}))
    assert helper(fake_self, w_study1) == "4"

    # Awaited display key is '2000001' (Study 3) → differs from '4' → NOT showing awaited.
    assert helper(fake_self, w_study1) != "2000001"

    # Viewport now showing the awaited key.
    w_study3 = types.SimpleNamespace(
        _qt_bridge=types.SimpleNamespace(metadata={"series": {"series_number": "2000001"}}))
    assert helper(fake_self, w_study3) == "2000001"

    # Unknown (no bridge metadata) → None → caller preserves legacy behavior.
    w_unknown = types.SimpleNamespace()
    assert helper(fake_self, w_unknown) is None

    # Progressive-marker fallback when metadata is absent.
    w_prog = types.SimpleNamespace(_progressive_series_number="2000001")
    assert helper(fake_self, w_prog) == "2000001"
