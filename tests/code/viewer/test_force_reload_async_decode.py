"""Guard: a force_reload series switch routes its re-decode through the EXISTING
off-thread async path instead of decoding synchronously on the UI thread
(2026-06-24, shared file→render responsiveness — application-wide).

Root cause: a cached series re-loaded with force_reload=True (e.g. a manual drag)
re-decodes from disk inside the SYNC path (_perform_series_switch_optimized's
recovery), on the calling/UI thread. For a large / multi-frame series that froze
the GUI ~1.9 s (observed: multi-frame US, cache_hit=True 1934 ms). The uncached
path already uses _schedule_async_load_and_switch (worker decode + first-slice
preview); this fix sends force_reload there too. Shared import layer → benefits
Poor / Fast / Active-Node equally. Default OFF (AIPACS_FORCE_RELOAD_ASYNC_DECODE=1)
pending live validation.

Source-pin (the switch needs a live viewer + worker thread to exercise).
"""
import re
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_switch.py"
    ).read_text(encoding="utf-8")


def test_flag_present_default_off():
    src = _src()
    assert "AIPACS_FORCE_RELOAD_ASYNC_DECODE" in src
    # Default OFF: the env default literal is "0" and the gate enables only on "1".
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_FORCE_RELOAD_ASYNC_DECODE"\s*,\s*"0"\s*\)[^\n]*==\s*"1"',
        src,
    )
    assert m is not None, "force-reload-async gate must default OFF (enable on '1')"


def test_force_reload_routes_to_async_path_and_returns():
    src = _src()
    idx = src.find("AIPACS_FORCE_RELOAD_ASYNC_DECODE")
    assert idx != -1
    # Inspect the branch body (the async call has many kwargs → wide window).
    block = src[idx: idx + 1400]
    # Gated on force_reload.
    assert "if force_reload and" in src[max(0, idx - 80): idx + 80]
    # Routes to the EXISTING off-thread async loader (reuse, not a new path).
    assert "_schedule_async_load_and_switch(" in block
    # Must return so it does NOT also fall through to the synchronous switch.
    assert "\n                return" in block


def test_sync_path_still_present_for_non_force_reload():
    """The fast cached (non-force_reload) path is unchanged — it still calls the
    synchronous optimizer (which only APPLIES a cached payload, no decode)."""
    src = _src()
    assert "self._perform_series_switch_optimized(vtk_widget, metadata, vtk_image_data" in src
