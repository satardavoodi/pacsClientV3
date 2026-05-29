"""
Regression-guard tests for the 2026-05-27 session fixes:

    1. Download-start slow regression (GetStudyInfo probe must use
       single send_request + _GETSTUDYINFO_PROBE_LOCK; never the
       2-attempt client.get_study_info helper).
    2. Eagle Eye drag-drop crash (MG mirror must be deferred via
       QTimer.singleShot, never a synchronous loop after the primary
       super().change_series_on_viewer).
    3. Multi-patient Download queue slowness (per-study metadata
       prefetch must run in parallel via ThreadPoolExecutor; UI must
       call QApplication.processEvents during the wait).

These tests are intentionally lightweight: they validate the *structure*
of the fixes (so a future refactor that "tidies them up" fails CI), plus
one functional test that exercises the parallel-prefetch wait loop with
a stub fetcher to prove the pattern actually parallelises.

Run from the project root:

    python -m pytest tests/system/test_2026_05_27_regression_guards.py -v
"""

from __future__ import annotations

import ast
import concurrent.futures
import re
import time
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ─────────────────────────────────────────────────────────────────────
# 1. Download-start slow regression — _hp_study_save.py
# ─────────────────────────────────────────────────────────────────────

HP_STUDY_SAVE = (
    PROJECT_ROOT
    / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_study_save.py"
)


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    return re.sub(r"^\s*#.*$", "", src, flags=re.MULTILINE)


def test_hp_study_save_compiles():
    src = _load(HP_STUDY_SAVE)
    ast.parse(src)


def test_probe_lock_is_module_level():
    """`_GETSTUDYINFO_PROBE_LOCK` must be a module-level threading.Lock()."""
    src = _load(HP_STUDY_SAVE)
    assert "_GETSTUDYINFO_PROBE_LOCK = threading.Lock()" in src, (
        "Module-level _GETSTUDYINFO_PROBE_LOCK threading.Lock() is missing — "
        "concurrent patient opens will all stall on the dead GetStudyInfo "
        "probe in parallel without it."
    )


def test_probe_lock_is_used_in_get_series_info_from_server():
    """The probe block must be wrapped in `with _GETSTUDYINFO_PROBE_LOCK:`."""
    src = _load(HP_STUDY_SAVE)
    assert "with _GETSTUDYINFO_PROBE_LOCK:" in src, (
        "Probe lock is declared but never used; serialization is broken."
    )


def test_probe_uses_raw_send_request_not_helper():
    """The probe must call raw send_request("GetStudyInfo"…) — never the
    higher-level client.get_study_info(...) helper, which does a 2-attempt
    retry and re-introduces the ~6 s download-start stall.
    """
    src = _load(HP_STUDY_SAVE)
    src_no_comments = _strip_comments(src)
    assert (
        'client.send_request(\n                                    "GetStudyInfo"'
        in src
        or 'client.send_request("GetStudyInfo"' in src
    ), "Raw send_request('GetStudyInfo', …) is missing from the probe path."
    assert "client.get_study_info(" not in src_no_comments, (
        "BUG / REGRESSION: client.get_study_info(...) reappeared in the "
        "probe path. That helper retries twice with a sleep and turns the "
        "3 s probe into ~6.2 s. Use raw send_request instead. "
        "See ZETA §14 and the inline REGRESSION GUARD comment."
    )


def test_probe_skip_cache_is_populated_on_failure():
    """Failure / slow probe must add (host, port) to _GETSTUDYINFO_UNSUPPORTED."""
    src = _load(HP_STUDY_SAVE)
    assert "_GETSTUDYINFO_UNSUPPORTED.add((host, port))" in src, (
        "Skip-cache is never populated; every subsequent open will pay "
        "the 3 s probe again."
    )


# ─────────────────────────────────────────────────────────────────────
# 2. Eagle Eye drag-drop crash — modules/.../ai_imaging/.../patient_widget.py
# ─────────────────────────────────────────────────────────────────────

AI_PATIENT_WIDGET = (
    PROJECT_ROOT
    / "modules/ai_imaging/ai_module_ui/overrides/patient_widget.py"
)


def test_ai_patient_widget_compiles():
    src = _load(AI_PATIENT_WIDGET)
    ast.parse(src)


def test_mg_mirror_is_deferred_via_qtimer():
    """`_schedule_mg_mirror` must post the mirror super() call via
    `QTimer.singleShot(0, _do_mirror)`. Running it synchronously
    stacks two heavy VTK series loads in one event-loop turn while
    the Windows OLE drop's COM context is still settling and trips
    a fatal `RPC_E_CANTCALLOUT_ININPUTSYNCCALL` (0x8001010d).
    """
    src = _load(AI_PATIENT_WIDGET)
    assert "_schedule_mg_mirror" in src, "Mirror scheduler missing."
    assert "QTimer.singleShot(0, _do_mirror)" in src, (
        "Mirror is not deferred via QTimer.singleShot(0). A synchronous "
        "mirror reintroduces the 0x8001010d crash on Eagle Eye drag-drop."
    )


def test_mg_mirror_has_no_synchronous_loop_after_primary_switch():
    """The override must NOT contain the old `for node in self.lst_node_viewers[:2]: ... super().change_series_on_viewer(...)` synchronous-mirror loop."""
    src = _load(AI_PATIENT_WIDGET)
    sync_mirror_pat = re.compile(
        r"for\s+node\s+in\s+self\.lst_node_viewers\[:2\]:[^_]*?super\(\)\.change_series_on_viewer",
        re.DOTALL,
    )
    assert not sync_mirror_pat.search(src), (
        "BUG: the synchronous mirror loop is back inside "
        "change_series_on_viewer. Move it into _schedule_mg_mirror "
        "and defer via QTimer."
    )


def test_change_series_signature_matches_base():
    """The override signature must mirror the base
    change_series_on_viewer exactly — a wrong-name kwarg (the old
    `target_viewer_id=`) broke drag-drop in earlier releases.
    """
    src = _load(AI_PATIENT_WIDGET)
    assert (
        "def change_series_on_viewer(self, series_index, "
        "flag_change_selected_widget=True,"
    ) in src
    # The bad legacy parameter is tolerated only via kwargs.pop, not in the signature.
    sig_match = re.search(
        r"def change_series_on_viewer\(self,([^)]*)\)\s*:",
        src,
    )
    assert sig_match, "Could not find change_series_on_viewer definition."
    signature = sig_match.group(1)
    assert "target_viewer_id" not in signature, (
        "BUG: target_viewer_id is back in the signature. It must be "
        "tolerated via kwargs.pop only, never declared as a parameter."
    )


# ─────────────────────────────────────────────────────────────────────
# 3. Multi-patient queue slowness — _hp_download.py
# ─────────────────────────────────────────────────────────────────────

HP_DOWNLOAD = (
    PROJECT_ROOT
    / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py"
)


def test_hp_download_compiles():
    src = _load(HP_DOWNLOAD)
    ast.parse(src)


def test_prefetch_uses_threadpool_executor():
    """Multi-patient metadata pre-fetch must run on a thread pool, not
    in a sequential UI-thread loop.
    """
    src = _load(HP_DOWNLOAD)
    assert "import concurrent.futures" in src, (
        "concurrent.futures import missing — parallel prefetch impossible."
    )
    assert "concurrent.futures.ThreadPoolExecutor(" in src, (
        "ThreadPoolExecutor not used; metadata prefetch is still "
        "sequential. Expect 6-30 s UI freeze on 20-30 patient downloads."
    )
    assert "QApplication.processEvents()" in src, (
        "processEvents not pumped during the prefetch wait; UI will "
        "freeze even though fetches are parallel."
    )


def test_prefetch_has_no_sequential_loop():
    """The old `for study in selected_studies: if 'series' not in study: ... _get_or_fetch_series_info(...)` pattern must be gone."""
    src = _load(HP_DOWNLOAD)
    # Match the exact failure-mode pattern.
    old_pat = re.compile(
        r"for\s+study\s+in\s+selected_studies:\s*\n"
        r"\s+if\s+'series'\s+not\s+in\s+study\s+or\s+not\s+study\.get\('series'\):"
    )
    assert not old_pat.search(src), (
        "BUG / REGRESSION: the sequential per-study fetch loop is back "
        "in _on_download_requested. Multi-patient Download will freeze "
        "the UI for 6-30 s on 20-30 patient selections."
    )


def test_prefetch_preserves_downstream_contract():
    """`zeta_manager.add_downloads(selected_studies, start_immediately=True)`
    must still be called with the same enriched list.
    """
    src = _load(HP_DOWNLOAD)
    assert (
        "zeta_manager.add_downloads(selected_studies, start_immediately=True)"
        in src
    ), "Downstream add_downloads call shape changed; queue insertion broken."


# ─────────────────────────────────────────────────────────────────────
# Functional: prove the parallel-prefetch pattern actually parallelises.
# This is a pure, dependency-free reproduction of the wait-loop logic
# from _hp_download.py — it catches subtle bugs in the pattern itself
# (e.g. a stray time.sleep, an accidental as_completed iteration error).
# ─────────────────────────────────────────────────────────────────────


def _simulate_parallel_prefetch(n_studies, per_fetch_seconds, max_workers):
    """Reproduces the wait-loop pattern from _hp_download.py."""
    studies = [{"study_uid": f"uid-{i}", "patient_id": f"p-{i}", "series": []}
               for i in range(n_studies)]

    def _fake_fetch_one(study_ref):
        time.sleep(per_fetch_seconds)
        return (study_ref, {"series": [{"series_uid": "s1", "image_count": 1}],
                            "count_of_series": 1}, None)

    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fake_fetch_one, s) for s in studies]
        pending = set(futures)
        processed = 0
        ticks = 0
        while pending:
            done, pending = concurrent.futures.wait(
                pending,
                timeout=0.05,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                study_ref, info, err = fut.result()
                if info:
                    study_ref["series"] = info["series"]
                    study_ref["series_count"] = info["count_of_series"]
                processed += 1
            ticks += 1
    elapsed = time.monotonic() - start
    return elapsed, processed, ticks, studies


def test_parallel_prefetch_is_faster_than_sequential():
    """With 8 parallel workers and 100 ms per fetch, 16 studies should
    finish in well under 16 × 100 ms = 1.6 s sequential. Aim for < 600 ms.
    """
    elapsed, processed, ticks, studies = _simulate_parallel_prefetch(
        n_studies=16,
        per_fetch_seconds=0.10,
        max_workers=8,
    )
    assert processed == 16
    # Sequential lower bound is 1.6 s. Parallel should be ~2 × per-fetch
    # plus loop overhead (~0.05 s).
    assert elapsed < 0.6, (
        f"Parallel prefetch took {elapsed:.3f}s for 16 studies @ 100ms each "
        f"with 8 workers. Expected < 0.6s; got {elapsed:.3f}s — pattern "
        f"is not actually parallelising."
    )
    # The wait loop should tick more than once (we want UI-pump opportunities).
    assert ticks > 1, "Wait loop ran in one shot; no UI-pump opportunity."


def test_parallel_prefetch_populates_every_study():
    """The wait-loop mutation pattern must reliably populate `series` on
    every input dict (in-place), preserving the dict identity.
    """
    elapsed, processed, ticks, studies = _simulate_parallel_prefetch(
        n_studies=8,
        per_fetch_seconds=0.02,
        max_workers=4,
    )
    assert all(s.get("series") for s in studies), (
        "Some studies were not populated after parallel prefetch — the "
        "mutation contract is broken; add_downloads will reject them."
    )
    assert all(s.get("series_count") == 1 for s in studies)
