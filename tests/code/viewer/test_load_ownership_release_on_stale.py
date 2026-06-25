"""Guard: a series load that is superseded at the serialized-load gate RELEASES
its interactive-load ownership before returning, instead of leaking it
(2026-06-25, confirmed root cause of 47855 series 203 "1 image" + a general
concurrency reliability hole).

Root cause: `_load_single_series_on_demand` takes ownership (`_loading_series_numbers.add`
+ `_series_load_events[...]`) and, after acquiring `_interactive_full_load_semaphore`,
re-checks `_is_request_current`. If the viewport switched series/patient while waiting
on the gate, it returned False — but the surrounding `finally` only released the
SEMAPHORE, not the ownership. The leaked `series_key` then made every future load see
"already loading" (line ~640) and bail, so the series could NEVER full-load again
(stuck on its 1-slice preview; `UX_SERIES_LOAD_START` never fires). This happens
constantly under rapid series/patient switching. Fix: release ownership + wake waiters
on the stale path. Default on; `AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE=0` = legacy leak.

Also pins the disposal hardening: `_dl_watchdog_timer` is stopped on tab teardown.

Source-pin (the leak needs a live serialized load + a mid-load switch to exercise).
"""
import re
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _load_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_load.py"
    ).read_text(encoding="utf-8")


def _lifecycle_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_widget_core" / "_pw_lifecycle.py"
    ).read_text(encoding="utf-8")


def test_flag_present_default_on():
    src = _load_src()
    assert "AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE" in src
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_LOAD_OWNERSHIP_RELEASE_ON_STALE"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "ownership-release-on-stale must default ON (disable on '0')"


def test_stale_path_releases_ownership_before_return():
    src = _load_src()
    # Locate the stale-request check at the load gate.
    idx = src.find("not self._is_request_current(target_vtk_widget, expected_token)")
    assert idx != -1
    block = src[idx: idx + 2200]
    # It must discard the series from _loading_series_numbers, pop the event, and
    # wake waiters — all BEFORE the `return False`.
    assert "_loading_series_numbers.discard(series_key)" in block
    assert "_series_load_events.pop(series_key" in block
    assert re.search(r"_evt_stale\.set\(\)", block)
    # The release sits under the lock, before the return.
    assert re.search(r"with self\._series_load_lock:[\s\S]{0,200}?_loading_series_numbers\.discard\(series_key\)[\s\S]{0,700}?return False", block)


def test_other_exit_paths_still_release_ownership():
    """Regression-pin the pre-existing releases so the function stays leak-free on
    every path (None result, success, exception)."""
    src = _load_src()
    # at least three other discard sites remain (None / success / outer except)
    assert src.count("_loading_series_numbers.discard(series_key)") >= 3
    assert "_loading_series_numbers.discard(str(series_number))" in src  # outer except


def test_watchdog_timer_stopped_on_teardown():
    src = _lifecycle_src()
    # The teardown timer-stop loop must include the disk-ready watchdog timer.
    assert "_dl_watchdog_timer" in src
    assert re.search(r"for _tname in \([\s\S]{0,160}?_dl_watchdog_timer", src)
