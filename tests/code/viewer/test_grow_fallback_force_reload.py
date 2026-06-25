"""Guard: when a same-series switch detects the series GREW on disk but the
in-place grow cannot run (no lazy loader on a preview / offline-cloud volume),
the fallback invalidates the stale series caches and FORCES the reload so the
container's same-series no-op is bypassed and the viewport rebuilds to the full
slice count (2026-06-24, left-viewport stuck-at-preview freeze — patient 47793
series 203, layout switch, Razi).

Root cause: after a layout switch the viewport held an 8-slice PREVIEW volume of
series 203 while disk had 129 files.  ``_perform_series_switch_optimized`` saw
``series_grew`` (disk 129 > displayed 8) but the in-place grow needed a lazy
loader and the preview volume had none (``_lazy_loader=None``), so it fell
through to a reload that called ``qt_fast_container.switch_series`` WITHOUT
force_reload — and the same-series no-op ("already showing series=203, skip")
rejected it.  The viewport stayed frozen at 8 of 129 (the disk-ready watchdog
retried 90 times, all rejected).

Fix: in the grow branch, when the in-place grow did not succeed, call
``_invalidate_series_caches(series_number)`` (clears the hot / flat / zeta layers
so the rebuild reads the full on-disk metadata, not the cached 8 instances) and
set ``force_reload = True`` so the downstream switch_series bypasses the no-op.
Default ON; kill switch ``AIPACS_GROW_FALLBACK_FORCE_RELOAD=0`` restores legacy.

Source-pin (the real reload needs a live viewer + worker thread to exercise).
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


def test_flag_present_default_on():
    src = _src()
    assert "AIPACS_GROW_FALLBACK_FORCE_RELOAD" in src
    # Default ON: env default literal "1", disables only on "0".
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_GROW_FALLBACK_FORCE_RELOAD"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "grow-fallback force-reload must default ON (disable on '0')"


def test_fallback_runs_after_failed_in_place_grow():
    """The fallback must sit in the series_grew branch, AFTER the `if _grew_ok:
    return` early-out — i.e. only when the in-place grow did NOT succeed."""
    src = _src()
    grew_ok = src.find("if _grew_ok:")
    flag = src.find("AIPACS_GROW_FALLBACK_FORCE_RELOAD")
    assert grew_ok != -1 and flag != -1
    # Fallback comes after the _grew_ok early-return ...
    assert grew_ok < flag
    # ... and before the generic backend-reload log that follows the grow block.
    backend_reload = src.find('"change-series: backend-reload', flag)
    assert backend_reload != -1, "fallback must precede the backend-reload path"


def test_fallback_syncs_canonical_metadata_and_forces_reload():
    src = _src()
    idx = src.find("AIPACS_GROW_FALLBACK_FORCE_RELOAD")
    assert idx != -1
    block = src[idx: idx + 1600]
    # Busts the 1 s disk-count cache so the refresh sees the true file count.
    assert "_invalidate_disk_count_cache(series_number)" in block
    # COMPLETE FIX: brings the canonical lst_thumbnails_data metadata up to the
    # true on-disk file count BEFORE the rebuild, so _get_series_by_number_fast
    # serves the full instance list instead of the stale 1-8 instance stub.
    assert "_refresh_and_sync_metadata(series_number, _fresh_disk)" in block
    # ALWAYS re-sync when disk has files — the refresh's own internal guard reads
    # the REAL canonical count and no-ops cheaply; gating on displayed_count (the
    # viewer's metadata) skipped the re-sync when a separate writer clobbered the
    # canonical back to a stub (47855 series 203).
    assert re.search(r"if\s+_fresh_disk\s*>\s*0\s*:", block)
    # Flips force_reload so the container same-series no-op is bypassed.
    assert re.search(r"\bforce_reload\s*=\s*True\b", block)
