"""WU-1 — background series-file warm at patient open (2026-08-08).

Live evidence (patient 53417, 13:57): the switch-time header scan probed a
444-file CT series at 40.5 ms/file COLD (AV on-open + cold I/O; the adaptive
8-thread pool caps at ~2.3x — bench: seq 23.1 / t8 9.8 / t24 9.8 ms/file) →
series 202 took ~8.6 s to the viewport. WARM the same probe is 0.88 ms/file.
WU-1 pays the AV/I-O cost in a budgeted background thread at patient open;
the switch-time scan (and its full per-file verification) is unchanged.

Pins:
  * the sync core reads every series file head under the study dirs;
  * per-file head read honours the chunk size; missing/garbage dirs are safe;
  * file- and time-budgets cap the run (capped=True, never raises);
  * kill switch AIPACS_SERIES_FILE_WARM=0 -> no thread, False returned;
  * duplicate concurrent warm of the same study set is refused;
  * async wrapper actually runs and clears its active-key;
  * source pin: the open pipeline kicks the warmer in _background_setup_thread.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PacsClient.pacs.patient_tab.utils import series_file_warm as sfw


def _make_study(tmp_path: Path, name: str, series: dict[str, int],
                size: int = 4096) -> Path:
    study = tmp_path / name
    for series_name, n in series.items():
        d = study / series_name
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"img_{i:04d}.dcm").write_bytes(b"\x00" * size)
    return study


def test_sync_core_reads_all_series_files(tmp_path):
    study = _make_study(tmp_path, "study-a", {"202": 5, "101": 3})
    stats = sfw._warm_paths([str(study)], chunk_bytes=1024, max_files=100,
                            max_seconds=10.0, workers=4)
    assert stats["files"] == 8
    assert stats["bytes"] == 8 * 1024          # head chunk only, not the 4 KiB
    assert stats["capped"] is False


def test_chunk_larger_than_file_reads_whole_file(tmp_path):
    study = _make_study(tmp_path, "study-b", {"1": 2}, size=100)
    stats = sfw._warm_paths([str(study)], chunk_bytes=64 * 1024, max_files=100,
                            max_seconds=10.0, workers=2)
    assert stats["files"] == 2
    assert stats["bytes"] == 200


def test_legacy_series_primes_shared_pixel_facts_instead_of_raw_read(
        tmp_path, monkeypatch):
    study = _make_study(tmp_path, "study-facts", {"1": 3}, size=100)
    series_path = study / "1"
    primed = []

    def prime(path):
        primed.append(Path(path))
        return True, 1

    monkeypatch.setattr(sfw, "prime_dicom_pixel_fact", prime)
    stats = sfw._warm_paths(
        [str(study)], chunk_bytes=64 * 1024, max_files=100,
        max_seconds=10.0, workers=2,
        pixel_fact_series_paths=[str(series_path)],
    )

    assert sorted(primed) == sorted(series_path.glob("*.dcm"))
    assert stats["files"] == stats["fact_files"] == 3
    assert stats["bytes"] == 0


def test_only_unverified_local_series_select_shared_fact_warm(
        tmp_path, monkeypatch):
    study = _make_study(tmp_path, "study-select", {"ready": 1, "legacy": 1})
    ready = {"series_path": str(study / "ready"), "state": "ready"}
    legacy = {"series_path": str(study / "legacy"), "state": "legacy"}
    monkeypatch.setattr(
        sfw, "indexed_series_pixel_inventory",
        lambda row: object() if row.get("state") == "ready" else None,
    )

    assert sfw._pixel_fact_series_paths([ready, legacy]) == {
        os.path.normcase(os.path.abspath(study / "legacy"))
    }


def test_local_fact_warm_has_independent_rollback_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_LOCAL_PIXEL_FACT_WARM", "0")
    assert sfw._pixel_fact_warm_enabled() is False
    assert sfw._pixel_fact_series_paths([
        {"series_path": "synthetic/legacy"},
    ]) == set()


def test_ordered_local_inventory_delegates_unverified_warm_work(monkeypatch, tmp_path):
    study = _make_study(tmp_path, "study-owner", {"ready": 1, "legacy": 1})
    ready = {"series_path": str(study / "ready"), "state": "ready"}
    legacy = {"series_path": str(study / "legacy"), "state": "legacy"}
    monkeypatch.delenv("AIPACS_LOCAL_ORDERED_INVENTORY", raising=False)
    monkeypatch.setattr(
        sfw, "indexed_series_pixel_inventory",
        lambda row: object() if row.get("state") == "ready" else None,
    )

    raw, facts, delegated = sfw._local_series_warm_plan([ready, legacy])

    assert raw == set()
    assert facts == set()
    assert delegated == {
        os.path.normcase(os.path.abspath(study / "ready")),
        os.path.normcase(os.path.abspath(study / "legacy")),
    }


def test_patient_open_does_not_raw_warm_producer_indexed_local_series(
        monkeypatch, tmp_path):
    """A durable Local index must not trigger a second whole-series disk read."""
    study = _make_study(tmp_path, "study-indexed-local", {"ready": 3})
    ready_path = os.path.normcase(os.path.abspath(study / "ready"))
    ready = {"series_path": str(study / "ready"), "state": "ready"}
    monkeypatch.delenv("AIPACS_LOCAL_INDEXED_FILE_WARM", raising=False)
    monkeypatch.setattr(
        sfw, "indexed_series_pixel_inventory",
        lambda row: object() if row.get("state") == "ready" else None,
    )

    raw, facts, delegated = sfw._local_series_warm_plan([ready])

    assert raw == set()
    assert facts == set()
    assert delegated == {ready_path}


def test_indexed_local_patient_open_does_not_start_a_warm_thread(
        monkeypatch, tmp_path):
    study = _make_study(tmp_path, "study-indexed-no-thread", {"ready": 3})
    monkeypatch.delenv("AIPACS_LOCAL_INDEXED_FILE_WARM", raising=False)
    monkeypatch.setattr(sfw, "indexed_series_pixel_inventory", lambda _row: object())

    started = sfw.warm_study_series_async(
        [str(study)], local_series=[{"series_path": str(study / "ready")}],
    )

    assert started is False


def test_indexed_local_file_warm_has_explicit_rollback(monkeypatch, tmp_path):
    study = _make_study(tmp_path, "study-indexed-rollback", {"ready": 1})
    ready_path = os.path.normcase(os.path.abspath(study / "ready"))
    monkeypatch.setenv("AIPACS_LOCAL_INDEXED_FILE_WARM", "1")
    monkeypatch.setattr(sfw, "indexed_series_pixel_inventory", lambda _row: object())

    raw, facts, delegated = sfw._local_series_warm_plan([
        {"series_path": str(study / "ready")},
    ])

    assert raw == {ready_path}
    assert facts == set()
    assert delegated == set()


def test_ordered_local_inventory_rollback_restores_fact_warm(monkeypatch, tmp_path):
    study = _make_study(tmp_path, "study-rollback", {"ready": 1, "legacy": 1})
    ready = {"series_path": str(study / "ready"), "state": "ready"}
    legacy = {"series_path": str(study / "legacy"), "state": "legacy"}
    monkeypatch.setenv("AIPACS_LOCAL_ORDERED_INVENTORY", "0")
    monkeypatch.setattr(
        sfw, "indexed_series_pixel_inventory",
        lambda row: object() if row.get("state") == "ready" else None,
    )

    raw, facts, delegated = sfw._local_series_warm_plan([ready, legacy])

    assert raw == set()
    assert facts == {os.path.normcase(os.path.abspath(study / "legacy"))}
    assert delegated == {os.path.normcase(os.path.abspath(study / "ready"))}


def test_delegated_local_series_is_not_touched_by_the_parallel_warmer(tmp_path):
    study = _make_study(tmp_path, "study-delegated", {"ready": 1, "legacy": 3}, size=100)

    stats = sfw._warm_paths(
        [str(study)], chunk_bytes=1024, max_files=100,
        max_seconds=10.0, workers=4,
        delegated_series_paths=[str(study / "legacy")],
    )

    assert stats["files"] == 1
    assert stats["bytes"] == 100
    assert stats["fact_files"] == 0
    assert stats["delegated_series"] == 1


def test_missing_and_garbage_paths_are_safe(tmp_path):
    study = _make_study(tmp_path, "study-c", {"1": 1})
    stats = sfw._warm_paths(
        [str(study), str(tmp_path / "does-not-exist"), ""],
        chunk_bytes=1024, max_files=100, max_seconds=10.0, workers=2)
    assert stats["files"] == 1


def test_file_budget_caps_run(tmp_path):
    study = _make_study(tmp_path, "study-d", {"1": 10})
    stats = sfw._warm_paths([str(study)], chunk_bytes=1024, max_files=4,
                            max_seconds=10.0, workers=2)
    assert stats["files"] <= 4
    assert stats["capped"] is True


def test_time_budget_caps_run(tmp_path, monkeypatch):
    study = _make_study(tmp_path, "study-e", {"1": 50})
    real_perf = time.perf_counter
    t0 = real_perf()
    # Pretend 100 s have passed after the first few files.
    calls = {"n": 0}

    def _fake_perf():
        calls["n"] += 1
        return t0 + (100.0 if calls["n"] > 4 else 0.0)

    monkeypatch.setattr(sfw.time, "perf_counter", _fake_perf)
    stats = sfw._warm_paths([str(study)], chunk_bytes=1024, max_files=1000,
                            max_seconds=30.0, workers=2)
    assert stats["capped"] is True
    assert stats["files"] < 50


def test_kill_switch_blocks_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_SERIES_FILE_WARM", "0")
    study = _make_study(tmp_path, "study-f", {"1": 1})
    assert sfw.warm_study_series_async([str(study)]) is False


def test_empty_paths_refused(monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_FILE_WARM", raising=False)
    assert sfw.warm_study_series_async([]) is False
    assert sfw.warm_study_series_async([None, ""]) is False


def test_async_runs_and_clears_active_key(tmp_path, monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_FILE_WARM", raising=False)
    study = _make_study(tmp_path, "study-g", {"1": 3})
    assert sfw.warm_study_series_async([str(study)]) is True
    deadline = time.time() + 10.0
    while time.time() < deadline:
        with sfw._active_lock:
            if not sfw._active_keys:
                break
        time.sleep(0.02)
    with sfw._active_lock:
        assert not sfw._active_keys, "active key must clear when warm finishes"


def test_duplicate_concurrent_warm_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_FILE_WARM", raising=False)
    study = _make_study(tmp_path, "study-h", {"1": 1})
    key = "|".join(sorted([str(study)]))
    with sfw._active_lock:
        sfw._active_keys.add(key)
    try:
        assert sfw.warm_study_series_async([str(study)]) is False
    finally:
        with sfw._active_lock:
            sfw._active_keys.discard(key)


@pytest.mark.parametrize("val,expected", [
    (None, True), ("", True), ("1", True), ("junk", True),
    ("0", False),
])
def test_warm_flag_parsing(monkeypatch, val, expected):
    if val is None:
        monkeypatch.delenv("AIPACS_SERIES_FILE_WARM", raising=False)
    else:
        monkeypatch.setenv("AIPACS_SERIES_FILE_WARM", val)
    assert sfw._enabled() is expected


def test_open_pipeline_kicks_warmer():
    src = (REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
           / "home_panel" / "_hp_patient_open.py").read_text(encoding="utf-8")
    bg = src.split("def _background_setup_thread", 1)[1]
    head = bg.split("Download attachments in background", 1)[0]
    assert "warm_study_series_async" in head, (
        "WU-1: _background_setup_thread must kick the series-file warmer")
    assert "SOURCE_PATH" in head
