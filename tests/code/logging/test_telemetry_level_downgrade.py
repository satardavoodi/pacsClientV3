"""Guard test for OPT-09 — download telemetry level downgrade.

The download component threshold is WARNING, so the download pipeline emits its
high-volume progress telemetry (batch traces, per-series/pipeline summaries, stage
timings, TTFC KPIs) at WARNING purely to pass that gate — burying the ~300 real
download WARNING/ERROR records among ~36 k telemetry lines (125:1). The
`TelemetryLevelDowngradeFilter`, attached to the download handler AFTER the threshold
filter, relabels those known-telemetry records to INFO so real problems are grep-able.

These tests exercise the real filter class directly (no QApplication / no file I/O).
"""

from __future__ import annotations

import logging

from PacsClient.utils.diagnostic_logging import TelemetryLevelDowngradeFilter


def _rec(msg: str, level=logging.WARNING) -> logging.LogRecord:
    return logging.LogRecord(
        name="modules.download_manager.network.socket_client",
        level=level, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=None,
    )


def test_batch_trace_warning_downgraded_to_info():
    f = TelemetryLevelDowngradeFilter()
    f._enabled = True
    r = _rec("[BATCH_TRACE] series=5 batch_index=0 size=1 received=1 has_more=True")
    assert f.filter(r) is True          # record is kept…
    assert r.levelno == logging.INFO    # …but relabelled INFO
    assert r.levelname == "INFO"


def test_various_telemetry_prefixes_downgraded():
    f = TelemetryLevelDowngradeFilter()
    f._enabled = True
    for msg in (
        "download-summary key=GetSeriesImages:1.2.3:0 progress=50%",
        "series-summary series=5 downloaded=10 skipped=0 total=10",
        "download-pipeline-summary series=5 elapsed_s=2",
        "stage-timing duration_ms=12 files=3 query_type=disk_write",
        "[NET_TIMING] endpoint=GetStudyThumbnails payload_bytes=100",
        "[reporter-hydration] phase=status_resolved pid=1 study=x",
        "[KPI] kind=TTFC scope=download study=x series=5",
        "[SERIES_COMPLETE] series=5 on_disk=10 expected=10 study=x",
    ):
        r = _rec(msg)
        f.filter(r)
        assert r.levelno == logging.INFO, msg


def test_real_warning_is_not_downgraded():
    f = TelemetryLevelDowngradeFilter()
    f._enabled = True
    r = _rec("socket recv failed: connection reset by peer (retry 2/3)")
    assert f.filter(r) is True
    assert r.levelno == logging.WARNING   # genuine warning untouched
    assert r.levelname == "WARNING"


def test_real_error_is_not_touched():
    f = TelemetryLevelDowngradeFilter()
    f._enabled = True
    r = _rec("[BATCH_TRACE] series=5 ...", level=logging.ERROR)  # even telemetry-shaped
    assert f.filter(r) is True
    assert r.levelno == logging.ERROR     # only WARNING is remapped; ERROR stays ERROR


def test_kill_switch_keeps_warning():
    f = TelemetryLevelDowngradeFilter()
    f._enabled = False                    # AIPACS_LOG_TELEMETRY_DOWNGRADE=0
    r = _rec("[BATCH_TRACE] series=5 ...")
    assert f.filter(r) is True
    assert r.levelno == logging.WARNING   # byte-identical legacy


def test_prefix_must_be_near_start_not_mid_message():
    f = TelemetryLevelDowngradeFilter()
    f._enabled = True
    # a real warning that merely mentions a token later in a long message is not telemetry
    r = _rec("connection dropped while writing; pending " + "x" * 80 + " [BATCH_TRACE]")
    f.filter(r)
    assert r.levelno == logging.WARNING


def test_filter_wired_onto_download_handler_source():
    # source-pin: the filter is actually attached to the download handler after threshold
    from pathlib import Path
    src = Path(__file__).resolve().parents[3] / "PacsClient" / "utils" / "diagnostic_logging.py"
    s = src.read_text(encoding="utf-8", errors="ignore")
    assert "download_handler.addFilter(TelemetryLevelDowngradeFilter())" in s
    i = s.index("download_handler.addFilter(threshold_filter)")
    j = s.index("download_handler.addFilter(TelemetryLevelDowngradeFilter())")
    assert i < j, "downgrade filter must run AFTER the threshold gate"
