"""VS-2 — heavy viewer imports warmed off the GUI thread (2026-08-16).

Live stall traces of a first series open showed one contiguous ~9.1 s frozen
UI. After moving the disk-pixel-cache index scan off-thread, the remaining
GUI-thread cost was dominated by ONE-TIME MODULE IMPORTS, caught mid-import by
the sampler:

    cv2/__init__.py:181 <module> -> :153 bootstrap -> :88 import_module   (~2 s)
    dicom_windowing.auto_window_level_from_array -> np.percentile
        -> np.unique -> numpy/__init__.py:737 __getattr__                (~1 s)

The second one is the giveaway that this is import cost, not arithmetic:
`numpy/__init__.py:__getattr__` is numpy resolving a LAZY submodule. Measured
on this machine with the PacsClient package already loaded (as in the running
app): cv2 82 ms + numpy percentile/unique 103 ms + filter pipeline 2 ms =
~187 ms WARM, versus the ~3 s seen cold in the live trace.

The fix warms them on a daemon thread from the existing first-search warm hook
(the same hook that already warms the download manager and the viewer
linecache). These pins cover the wiring and — the part that actually matters —
that doing this work off the GUI thread is safe and effective.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SRC = (REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
       / "home_panel" / "_hp_search.py").read_text(encoding="utf-8")


def _warm_block() -> str:
    start = SRC.find("def _warm_viewer_imports():")
    assert start != -1, "the viewer import warmer is missing"
    return SRC[start:start + 3000]


# ---------------------------------------------------------------------------
# Wiring.
# ---------------------------------------------------------------------------
def test_warmer_runs_on_a_daemon_thread_not_the_gui_thread():
    block = SRC[SRC.find("def _warm_viewer_imports():"):]
    tail = block[:block.find("try:\n            from PySide6.QtCore import QTimer")]
    assert 'name="viewer-import-warm"' in tail
    assert "daemon=True" in tail
    assert "Thread(" in tail


def test_warmer_is_kill_switchable_and_default_on():
    block = SRC[SRC.find("def _warm_viewer_imports():"):]
    assert 'getenv("AIPACS_VIEWER_IMPORT_WARM", "1")' in block
    assert '!= "0"' in block


def test_warmer_targets_the_measured_offenders():
    block = _warm_block()
    assert "import cv2" in block, "cv2 is the ~2 s offender in the live trace"
    assert "percentile" in block, "the numpy lazy-import path must be forced"
    assert "unique" in block
    assert "opencv_filter_pipeline" in block


def test_every_warm_step_is_individually_guarded():
    """One missing optional dep must not skip the rest of the warm."""
    block = _warm_block()
    assert block.count("except Exception:") >= 3, (
        "each import step needs its own try/except so one failure cannot "
        "abort the others")


def test_warmer_creates_no_qt_objects():
    """Off-thread is only safe because this touches no Qt/GUI object."""
    block = _warm_block()
    for forbidden in ("QWidget", "QPixmap", "QImage", "QWindow", "QPainter",
                      "setStyleSheet", ".show()"):
        assert forbidden not in block, (
            f"{forbidden} in a background thread is not safe — the warm must "
            f"stay pure imports")


# ---------------------------------------------------------------------------
# The behaviour that makes it worth doing.
# ---------------------------------------------------------------------------
def test_the_warm_sequence_is_safe_off_thread_and_actually_resolves_imports():
    """Run the exact warm sequence on a worker thread; it must not raise."""
    errors = []

    def _warm():
        try:
            import cv2  # noqa: F401
            import numpy as np
            tiny = np.array([0, 1, 2], dtype=np.int16)
            np.percentile(tiny, 1.0)
            np.percentile(tiny, 99.0)
            np.unique(tiny)
            from PacsClient.pacs.patient_tab.utils import (  # noqa: F401
                opencv_filter_pipeline,
            )
        except Exception as exc:                      # pragma: no cover
            errors.append(exc)

    t = threading.Thread(target=_warm, daemon=True)
    t.start()
    t.join(120)
    assert not t.is_alive(), "the warm sequence hung on a background thread"
    if errors and isinstance(errors[0], ImportError):
        pytest.skip(f"optional dependency unavailable: {errors[0]}")
    assert errors == [], f"warm sequence raised off-thread: {errors}"

    # ...and the modules the viewer needs are now resolved in this process.
    assert "cv2" in sys.modules
    assert "numpy" in sys.modules


def test_windowing_path_uses_the_warmed_numpy_calls():
    """Pin the link between the warm and the real hot path it protects."""
    dw = (REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils"
          / "dicom_windowing.py").read_text(encoding="utf-8")
    fn = dw[dw.find("def auto_window_level_from_array"):]
    fn = fn[:fn.find("\ndef ")]
    assert "np.percentile" in fn, (
        "if the windowing path stops using np.percentile, the numpy warm "
        "above is warming the wrong thing")


def test_filter_pipeline_imports_cv2_lazily_at_module_level():
    """cv2 is imported when opencv_filter_pipeline loads — hence the warm."""
    ofp = (REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils"
           / "opencv_filter_pipeline.py").read_text(encoding="utf-8")
    head = ofp[:ofp.find("logger = logging.getLogger")]
    assert "import cv2" in head
