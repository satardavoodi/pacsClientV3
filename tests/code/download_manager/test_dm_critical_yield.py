"""Guard tests for the same-study batch-boundary critical yield (2026-06-05).

Contract (drag-drop priority):
  * A drag-dropped CRITICAL series of the study that is ALREADY downloading is
    signalled to the running worker via ``{SOURCE_PATH}/{study_uid}/
    .critical_intent.json`` — the worker is NOT torn down mid-batch.
  * The running SeriesDownloader polls the file between instance batches via
    ``SocketDicomClient.yield_check``; the in-flight batch always finishes;
    the current series stops with the distinct ``YIELDED_TO_CRITICAL`` marker
    (NOT a failure) and is re-queued right after the critical series.
  * Stale intents (>TTL) are ignored; a serviced intent is consumed (deleted).
"""
from __future__ import annotations

import json
import time
import types
from pathlib import Path

from modules.download_manager.download.series_downloader import SeriesDownloader
from modules.download_manager.network.socket_client import YIELDED_TO_CRITICAL


def _make_downloader(tmp_path: Path) -> SeriesDownloader:
    sd = SeriesDownloader.__new__(SeriesDownloader)
    sd.base_output_dir = tmp_path
    sd._intent_mtime = 0.0
    sd._intent_value = None
    return sd


def _write_intent(tmp_path: Path, study_uid: str, series_number, ts=None):
    d = tmp_path / study_uid
    d.mkdir(parents=True, exist_ok=True)
    (d / ".critical_intent.json").write_text(
        json.dumps({"series_number": str(series_number),
                    "ts": time.time() if ts is None else ts}),
        encoding="utf-8")


def test_marker_is_distinct_from_preemption():
    assert "preemption" not in YIELDED_TO_CRITICAL.lower()
    assert "critical" in YIELDED_TO_CRITICAL.lower()


def test_read_intent_roundtrip(tmp_path):
    sd = _make_downloader(tmp_path)
    assert sd._read_critical_intent("study-1") is None
    _write_intent(tmp_path, "study-1", 401)
    assert sd._read_critical_intent("study-1") == "401"


def test_stale_intent_ignored(tmp_path):
    sd = _make_downloader(tmp_path)
    _write_intent(tmp_path, "study-1", 401, ts=time.time() - 16 * 60)
    assert sd._read_critical_intent("study-1") is None


def test_consume_only_when_target_matches(tmp_path):
    sd = _make_downloader(tmp_path)
    _write_intent(tmp_path, "study-1", 401)
    sd._consume_critical_intent("study-1", 999)   # different series → keep
    assert (tmp_path / "study-1" / ".critical_intent.json").exists()
    sd._consume_critical_intent("study-1", 401)   # serviced → delete
    assert not (tmp_path / "study-1" / ".critical_intent.json").exists()
    assert sd._read_critical_intent("study-1") is None


def test_intent_update_detected_via_mtime(tmp_path):
    sd = _make_downloader(tmp_path)
    _write_intent(tmp_path, "study-1", 401)
    assert sd._read_critical_intent("study-1") == "401"
    time.sleep(0.05)
    _write_intent(tmp_path, "study-1", 502)
    assert sd._read_critical_intent("study-1") == "502"


def test_gui_intent_writer_atomic(tmp_path, monkeypatch):
    """_dm_retry._write_critical_intent_file writes the file the downloader reads."""
    import PacsClient.utils.config as cfg
    monkeypatch.setattr(cfg, "SOURCE_PATH", str(tmp_path), raising=False)

    from modules.download_manager.ui.widget._dm_retry import _DMRetryMixin

    stub = types.SimpleNamespace()
    ok = _DMRetryMixin._write_critical_intent_file(stub, "study-9", 707)
    assert ok is True
    sd = _make_downloader(tmp_path)
    assert sd._read_critical_intent("study-9") == "707"


def test_yield_branch_source_contract():
    """Source contracts that keep the behaviour from regressing:

    1. socket_client consults yield_check BETWEEN batches (after the R25
       cancel check) and returns YIELDED_TO_CRITICAL — never mid-batch.
    2. series_downloader handles the marker as a non-failure and re-queues
       the current series AFTER the critical one.
    3. _dm_retry prefers the intent file over worker teardown for the
       same-study case (intent write appears before the legacy preempt log).
    """
    root = Path(__file__).resolve().parents[3]
    sock = (root / "modules/download_manager/network/socket_client.py").read_text(encoding="utf-8")
    assert "yield_check" in sock and "YIELDED_TO_CRITICAL" in sock
    # the in-loop yield hook sits AFTER the R25 cancel check (between batches)
    assert sock.index("R25: Check for preemption between batches") < sock.index(
        "Same-study critical yield (2026-06-05, drag-drop priority)")

    sd_src = (root / "modules/download_manager/download/series_downloader.py").read_text(encoding="utf-8")
    assert "YIELDED_TO_CRITICAL" in sd_src
    # non-failure handling exists and precedes the generic failed branch
    assert sd_src.index('== YIELDED_TO_CRITICAL') < sd_src.index(
        'logger.error(f"    ❌ FAILED: {series_result.error_message}")')

    retry = (root / "modules/download_manager/ui/widget/_dm_retry.py").read_text(encoding="utf-8")
    assert "_write_critical_intent_file" in retry
    assert retry.index("_write_critical_intent_file(study_uid, target_num)") < retry.index(
        "Preempting current study worker for immediate reprioritization")
