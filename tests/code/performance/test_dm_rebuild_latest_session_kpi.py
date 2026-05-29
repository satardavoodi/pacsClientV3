"""Session-scoped KPI parser tests for DM rebuild logs.

These tests enforce the Phase 2 workflow requirement: validate latest-session
KPI behavior from tests instead of relying on mixed historical aggregate logs.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


from tools.performance.clearcanvas_aipacs_kpi_harness import (
    parse_dm_rebuild_sessions_log_text,
)


class TestDmRebuildLatestSessionParser:
    def test_empty_text_has_no_sessions(self):
        result = parse_dm_rebuild_sessions_log_text("")
        assert result["dm_rebuild_session_count"] == 0
        assert result["dm_rebuild_latest_session"] is None
        assert result["dm_rebuild_latest_pid"] is None

    def test_latest_session_selected_by_timestamp(self):
        text = "\n".join(
            [
                "2026-05-06 10:00:00.000 INFO x: pid=111 [DM_REBUILD] event=enter depth=1 caller=A",
                "2026-05-06 10:00:00.200 INFO x: pid=111 [DM_REBUILD] event=exit depth=1 duration_ms=300.0 rows=4 caller=A",
                "2026-05-06 10:05:00.000 INFO x: pid=222 [DM_REBUILD] event=enter depth=1 caller=B",
                "2026-05-06 10:05:00.010 INFO x: pid=222 [DM_REBUILD] event=exit depth=1 duration_ms=50.0 rows=4 caller=B",
            ]
        )
        result = parse_dm_rebuild_sessions_log_text(text)

        assert result["dm_rebuild_session_count"] == 2
        assert result["dm_rebuild_latest_pid"] == "222"
        latest = result["dm_rebuild_latest_session"]
        assert latest is not None
        assert latest["dm_rebuild_duration_max_ms"] == 50.0
        assert latest["dm_rebuild_duration_p95_ms"] == 50.0

    def test_defer_events_counted_and_do_not_inflate_exit_count(self):
        text = "\n".join(
            [
                "2026-05-06 11:00:00.000 INFO x: pid=333 [DM_REBUILD] event=defer_drag depth=1 caller=C",
                "2026-05-06 11:00:00.001 INFO x: pid=333 [DM_REBUILD] event=defer_hidden depth=1 caller=C",
                "2026-05-06 11:00:00.100 INFO x: pid=333 [DM_REBUILD] event=enter depth=1 caller=C",
                "2026-05-06 11:00:00.200 INFO x: pid=333 [DM_REBUILD] event=exit depth=1 duration_ms=42.5 rows=3 caller=C",
            ]
        )
        result = parse_dm_rebuild_sessions_log_text(text)
        latest = result["dm_rebuild_latest_session"]
        assert latest is not None

        assert latest["dm_rebuild_defer_drag_count"] == 1
        assert latest["dm_rebuild_defer_hidden_count"] == 1
        assert latest["dm_rebuild_count"] == 1
        assert latest["dm_rebuild_duration_max_ms"] == 42.5

    def test_lines_without_pid_grouped_as_nopid(self):
        text = "\n".join(
            [
                "2026-05-06 12:00:00.000 INFO x: [DM_REBUILD] event=enter depth=1 caller=X",
                "2026-05-06 12:00:00.100 INFO x: [DM_REBUILD] event=exit depth=1 duration_ms=10.0 rows=1 caller=X",
            ]
        )
        result = parse_dm_rebuild_sessions_log_text(text)
        assert result["dm_rebuild_session_count"] == 1
        assert result["dm_rebuild_latest_pid"] == "nopid"
        latest = result["dm_rebuild_latest_session"]
        assert latest is not None
        assert latest["pid"] == "nopid"
        assert latest["dm_rebuild_duration_p95_ms"] == 10.0
