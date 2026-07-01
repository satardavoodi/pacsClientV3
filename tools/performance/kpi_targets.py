"""AI-PACS KPI targets — single source of truth for the session analyzer.

Thresholds are transcribed from the repo's own performance standards:
  - docs/performance/FAST_VIEWER_KPI_CATALOG.md
  - docs/plans/performance/CURRENT_KPIS_v2.3.6.md

Keep this file stdlib-only so it can be imported by both the offline analyzer
(`kpi_session_report.py`) and the offscreen guard test without pulling in Qt/VTK.

When the catalog changes, update the `source` note and the limit here — do NOT
hard-code thresholds anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    key: str          # must match a metric key produced by kpi_session_report
    label: str
    limit: float
    direction: str    # "max" => value must be <= limit to PASS
    unit: str
    source: str


# Ordered for display. direction is always "max" (value must be <= limit).
TARGETS = (
    Target("ttfi_total_p95_ms", "First image visible (TTFI) p95", 80.0, "max", "ms",
           "FAST_VIEWER_KPI_CATALOG fast_first_image_visible / CURRENT_KPIS (<80ms OK)"),
    Target("decode_p95_ms", "DICOM decode p95", 30.0, "max", "ms",
           "derived soft target — decode should stay well under a frame budget"),
    Target("set_slice_total_p95_ms", "Cached slice display p95", 15.0, "max", "ms",
           "FAST_VIEWER_KPI_CATALOG fast_cached_display_p95_ms (<15ms)"),
    Target("drag_event_p95_ms", "Drag event interval p95", 120.0, "max", "ms",
           "FAST_VIEWER_KPI_CATALOG fast_drag_event_p95_ms (<120ms)"),
    Target("drag_ui_lag_max_ms", "Drag UI lag max", 200.0, "max", "ms",
           "FAST_VIEWER_KPI_CATALOG fast_drag_ui_lag / CURRENT_KPIS ui_lag_max (<200ms)"),
    Target("stall_p95_ms", "Main-thread stall p95", 100.0, "max", "ms",
           "main_thread_blocking_io_ms=0 during interaction; stall threshold 100ms"),
    Target("stall_over_500_count", "Main-thread stalls >= 500ms", 0.0, "max", "count",
           "interaction must not freeze > 0.5s"),
    Target("db_read_p95_ms", "DB read stage p95", 10.0, "max", "ms",
           "FAST_VIEWER_KPI_CATALOG db_read_transaction_p95_ms (<10ms)"),
    Target("db_write_p95_ms", "DB write stage p95", 50.0, "max", "ms",
           "FAST_VIEWER_KPI_CATALOG db_write_transaction_p95_ms (<50ms)"),
    Target("oversized_log_records", "Oversized log records (> 256 KB)", 0.0, "max", "count",
           "log hygiene — no MB-scale single records on the main thread"),
    Target("max_warning_ratio_pct", "Highest per-file WARNING ratio", 90.0, "max", "pct",
           "log hygiene — telemetry must not saturate the WARNING channel"),
)


def evaluate(metrics: dict) -> list:
    """Return [(Target, value_or_None, passed_or_None)] for every target.

    A metric that is absent (value None) is reported as passed=None (not applicable /
    not exercised this session) rather than a failure.
    """
    rows = []
    for t in TARGETS:
        val = metrics.get(t.key)
        if val is None:
            rows.append((t, None, None))
            continue
        passed = (val <= t.limit) if t.direction == "max" else (val >= t.limit)
        rows.append((t, float(val), bool(passed)))
    return rows
