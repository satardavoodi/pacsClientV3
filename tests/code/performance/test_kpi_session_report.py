"""Guard test for the read-only KPI session analyzer (tools/performance/kpi_session_report.py).

Runs in the offscreen verify lane — pure stdlib, builds a tiny synthetic log directory in
tmp_path, and asserts the analyzer's parsing, session-boundary handling, metric computation,
and PASS/FAIL evaluation against the catalog targets. No Qt/VTK/DB imports; never touches the
live logs or dicom.db.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "performance"))

import kpi_session_report as ksr  # noqa: E402
import kpi_targets  # noqa: E402


def _write_logs(d: Path):
    # app.log carries the once-per-process boot sentinels; latest boot = 10:00:01.
    (d / "app.log").write_text(
        "2026-01-01 10:00:00.000000 | INFO | c | component=ui role=main | m | configure_diagnostics ok\n"
        "2026-01-01 10:00:01.000000 | INFO | c | component=ui role=main | m | single_instance_lock.try_acquire ok\n",
        encoding="utf-8",
    )
    header = "| INFO | pid=1 tid=2 | component=viewer role=main | m.fn | action=- stage=- result=- |"
    lines = [
        # PRE-boundary stall — must be excluded by the since filter:
        f"2026-01-01 09:59:00.000000 {header} [MAIN_THREAD_STALL] stall_duration_ms=999.0 "
        "active_viewer_state=switch_complete nearest_table_refresh=none",
        f"2026-01-01 10:00:03.000000 {header} [MAIN_THREAD_STALL] stall_duration_ms=600.0 "
        "active_viewer_state=switch_complete nearest_table_refresh=TABLE_REFRESH#1@50ms",
        f"2026-01-01 10:00:04.000000 {header} [MAIN_THREAD_STALL] stall_duration_ms=120.0 "
        "active_viewer_state=fast_drag_inactive nearest_table_refresh=none",
        f"2026-01-01 10:00:05.000000 {header} [KPI] kind=TTFI series=6 slice=1 ttd_ms=5.0 ttr_ms=20.0 total_ms=25.0",
        f"2026-01-01 10:00:06.000000 {header} [FAST_SET_SLICE_STAGE] idx=1 total_ms=30.0 decode_ms=5.0 wl_ms=2.0 frame_ms=20.0",
        f"2026-01-01 10:00:07.000000 {header} [FAST_DRAG_KPI] event_p95_ms=300.0 ui_lag_max_ms=800.0 handler_p95_ms=10.0",
        # header carries stage=- ; the real stage name lives after the marker:
        f"2026-01-01 10:00:08.000000 {header} [STARTUP_STAGE] stage=add_AIPacs_tab ms=2400.0",
        f"2026-01-01 10:00:09.000000 {header} [FAST_GEOMETRY_ORDER_MISMATCH] series=7 slices=20",
        # oversized single record (> 256 KB) — hygiene failure, must be counted not parsed:
        "2026-01-01 10:00:10.000000 huge " + ("x" * 300000),
    ]
    (d / "viewer_diagnostics.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (d / "db_diagnostics.log").write_text(
        "2026-01-01 10:00:11.000000 | INFO | c | component=db role=main | m.update | "
        "query_type=write | stage-timing duration_ms=8.0\n"
        "2026-01-01 10:00:12.000000 | INFO | c | component=db role=main | m.read | "
        "query_type=read | stage-timing duration_ms=3.0\n"
        "2026-01-01 10:00:13.000000 | INFO | c | component=db role=download-subprocess | m.q | "
        "query_type=write | stage-timing duration_ms=900.0\n",
        encoding="utf-8",
    )
    (d / "download_diagnostics.log").write_text(
        "2026-01-01 10:00:14.000000 | WARNING | c | component=download role=download-subprocess | m | "
        "stage=dicom_file_write_batch result=ok | stage-timing duration_ms=50.0 files=1\n",
        encoding="utf-8",
    )


def test_boundary_and_metrics(tmp_path):
    _write_logs(tmp_path)

    boundary = ksr.detect_session_boundary(tmp_path)
    assert boundary.startswith("2026-01-01 10:00:01"), boundary  # latest boot, not configure line

    res = ksr.analyze(tmp_path, since=boundary)
    m, d = res["metrics"], res["detail"]

    # Pre-boundary 999ms stall excluded → only the two post-boundary stalls remain.
    assert d["stalls"]["count"] == 2
    assert m["stall_over_500_count"] == 1.0            # only the 600ms one
    assert d["stalls"]["nearest"].get("table_refresh") == 1

    # Render / first image
    assert m["ttfi_total_p95_ms"] == 25.0
    assert m["decode_p95_ms"] == 5.0
    assert m["set_slice_total_p95_ms"] == 30.0

    # Drag
    assert m["drag_event_p95_ms"] == 300.0
    assert m["drag_ui_lag_max_ms"] == 800.0

    # DB read/write are gated to role=main (the 900ms subprocess write is excluded)
    assert m["db_read_p95_ms"] == 3.0
    assert m["db_write_p95_ms"] == 8.0

    # Startup stage name parsed from AFTER the marker (not the header stage=-)
    stages = {s["stage"]: s["ms"] for s in d["startup_stages"]}
    assert stages.get("add_AIPacs_tab") == 2400.0

    # Log hygiene
    assert m["oversized_log_records"] == 1.0
    assert d["geometry_order_mismatch"] == 1


def test_target_evaluation_verdicts(tmp_path):
    _write_logs(tmp_path)
    res = ksr.analyze(tmp_path, since=ksr.detect_session_boundary(tmp_path))
    verdicts = {t.key: passed for t, val, passed in kpi_targets.evaluate(res["metrics"])}

    # Failing conditions in the fixture:
    assert verdicts["drag_event_p95_ms"] is False        # 300 > 120
    assert verdicts["drag_ui_lag_max_ms"] is False        # 800 > 200
    assert verdicts["stall_over_500_count"] is False      # 1 > 0
    assert verdicts["oversized_log_records"] is False     # 1 > 0

    # Passing conditions:
    assert verdicts["decode_p95_ms"] is True              # 5 <= 30
    assert verdicts["db_read_p95_ms"] is True             # 3 <= 10
    assert verdicts["db_write_p95_ms"] is True            # 8 <= 50


def test_render_markdown_smoke(tmp_path):
    _write_logs(tmp_path)
    res = ksr.analyze(tmp_path, since=ksr.detect_session_boundary(tmp_path))
    md = ksr.render_markdown(res)
    assert "KPI Session Report" in md
    assert "Main-thread stalls" in md
    assert "add_AIPacs_tab" in md
