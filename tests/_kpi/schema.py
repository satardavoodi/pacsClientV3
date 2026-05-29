"""KPI key registry — the single source of truth for every metric.

Every KPI emitted by a test MUST be a key registered here. Typos in
test code fail loudly (``UnknownKpiError``) so the dashboard never has
two metrics for the same thing.

Thresholds are aspirational targets for a healthy app. ``hard`` is
PR-blocking; ``warn`` surfaces in the report without failing CI.
Lower-is-better is the default; set ``higher_better=True`` to invert.

See ``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §4.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class UnknownKpiError(KeyError):
    """Raised when test code emits a KPI key that isn't in the registry."""


@dataclass(frozen=True)
class KpiSpec:
    key: str
    unit: str
    workflow: str
    hard: Optional[float] = None
    warn: Optional[float] = None
    higher_better: bool = False
    description: str = ""


# ---------------------------------------------------------------------------
# Registry — every KPI emitted by any test lives here
# ---------------------------------------------------------------------------

_SPECS: list[KpiSpec] = [
    # ── Patient open ─────────────────────────────────────────────────────
    KpiSpec("patient_open.elapsed_ms", "ms", "patient_open",
            hard=400, warn=250,
            description="End-to-end: click row → right panel populated"),
    KpiSpec("patient_open.right_panel_socket_ms", "ms", "patient_open",
            hard=400, warn=250,
            description="right_panel_socket_start → right_panel_socket_done"),

    # ── Bulk download ────────────────────────────────────────────────────
    KpiSpec("bulk_download.queue_build_ms", "ms", "bulk_download",
            hard=3000, warn=1500,
            description="Click Download → DM queue table populated"),
    KpiSpec("bulk_download.first_chunk_ms", "ms", "bulk_download",
            hard=5000, warn=2500,
            description="Click Download → first downloaded byte hits disk"),

    # ── Thumbnails ───────────────────────────────────────────────────────
    KpiSpec("thumbnail.load_ms", "ms", "thumbnail",
            hard=200, warn=100,
            description="Per-thumbnail load time"),
    KpiSpec("thumbnail.cross_patient_leak", "count", "thumbnail",
            hard=0, warn=0,
            description="Thumbnails of patient A visible in patient B viewer"),

    # ── Viewer ───────────────────────────────────────────────────────────
    KpiSpec("viewer.first_render_ms", "ms", "viewer",
            hard=800, warn=500,
            description="Series loaded → first frame painted"),
    KpiSpec("viewer.scroll_fps", "fps", "viewer",
            hard=30, warn=45, higher_better=True,
            description="Stack scroll frames per second"),
    KpiSpec("viewer.stack_rebuild_ms", "ms", "viewer",
            hard=500, warn=300,
            description="Layout change → all viewports rebuilt"),

    # ── MPR ──────────────────────────────────────────────────────────────
    KpiSpec("mpr.build_ms", "ms", "mpr",
            hard=4000, warn=2000,
            description="Open MPR → all three orthogonal views ready"),

    # ── Search ───────────────────────────────────────────────────────────
    KpiSpec("search.server_round_trip_ms", "ms", "search",
            hard=1500, warn=800,
            description="Click Search → server GetPatientList response"),
    KpiSpec("search.first_row_render_ms", "ms", "search",
            hard=200, warn=100,
            description="Server response → first table row painted"),

    # ── Database ─────────────────────────────────────────────────────────
    KpiSpec("db.query_ms.find_patient_pk", "ms", "database",
            hard=50, warn=20),
    KpiSpec("db.query_ms.insert_series", "ms", "database",
            hard=100, warn=50),
    KpiSpec("db.query_ms.get_study_info_with_series", "ms", "database",
            hard=200, warn=100),

    # ── Socket ───────────────────────────────────────────────────────────
    KpiSpec("socket.send_request_ms.GetPatientList", "ms", "socket",
            hard=1500, warn=800),
    KpiSpec("socket.send_request_ms.GetStudyThumbnails", "ms", "socket",
            hard=500, warn=250),
    KpiSpec("socket.send_request_ms.QuerySeriesThumbnails", "ms", "socket",
            hard=500, warn=250),
    KpiSpec("socket.send_request_ms.GetSeriesImages", "ms", "socket",
            hard=3000, warn=1500),

    # ── Process resource ────────────────────────────────────────────────
    KpiSpec("proc.idle_cpu_pct", "%", "process",
            hard=5.0, warn=2.0),
    KpiSpec("proc.rss_mb_steady", "MB", "process",
            hard=1500, warn=1000),
    KpiSpec("proc.rss_mb_growth_per_hour", "MB/h", "process",
            hard=50, warn=20,
            description="Drift in RSS during a long session — leak signal"),
    KpiSpec("proc.zombie_after_close", "count", "process",
            hard=0, warn=0,
            description="Processes named python.exe/aipacs.exe still alive"),

    # ── UI responsiveness ────────────────────────────────────────────────
    KpiSpec("ui.freeze_ms_per_session", "ms", "ui",
            hard=1000, warn=200,
            description="Total ms event loop was blocked >50ms during session"),

    # ── Crash / recovery ────────────────────────────────────────────────
    KpiSpec("crash.native_fault_count", "count", "crash",
            hard=0, warn=0),
    KpiSpec("recovery.restart_to_ready_ms", "ms", "recovery",
            hard=15000, warn=8000),

    # ── Long session ────────────────────────────────────────────────────
    KpiSpec("session.no_leak_after_8h", "bool", "session",
            hard=1, warn=1, higher_better=True),

    # ── SystemAdapter / DownloadAdapter elapsed_ms (auto-recorded by bus hook) ──
    KpiSpec("snapshot_resources.elapsed_ms", "ms", "process",
            hard=200, warn=80),
    KpiSpec("count_aipacs_processes.elapsed_ms", "ms", "process",
            hard=1000, warn=400),
    KpiSpec("count_native_faults_since.elapsed_ms", "ms", "crash",
            hard=200, warn=80),
    KpiSpec("probe_idle_cpu.elapsed_ms", "ms", "process",
            hard=20000, warn=10000,
            description="Includes the sampling window (default 5 s)"),
    KpiSpec("check_download_status.elapsed_ms", "ms", "bulk_download",
            hard=50, warn=20),
    KpiSpec("list_downloads.elapsed_ms", "ms", "bulk_download",
            hard=200, warn=80),
    KpiSpec("download_statistics.elapsed_ms", "ms", "bulk_download",
            hard=200, warn=80),
    KpiSpec("cancel_download.elapsed_ms", "ms", "bulk_download",
            hard=200, warn=100),
    KpiSpec("pause_download.elapsed_ms", "ms", "bulk_download",
            hard=200, warn=100),
    KpiSpec("resume_download.elapsed_ms", "ms", "bulk_download",
            hard=200, warn=100),

    # ── ViewerAdapter elapsed_ms (auto-recorded by bus hook) ────────────────
    KpiSpec("get_active_tab.elapsed_ms", "ms", "viewer",
            hard=80, warn=40,
            description="Read active patient-tab snapshot"),
    KpiSpec("list_open_tabs.elapsed_ms", "ms", "viewer",
            hard=80, warn=40),
    KpiSpec("get_thumbnails_data.elapsed_ms", "ms", "viewer",
            hard=150, warn=80,
            description="Read all series metadata for the active patient"),
    KpiSpec("get_active_series.elapsed_ms", "ms", "viewer",
            hard=80, warn=40),
    KpiSpec("get_multistudy_info.elapsed_ms", "ms", "viewer",
            hard=120, warn=60,
            description="Enumerate the studies grouped under the active tab"),
]


KPI_REGISTRY: dict[str, KpiSpec] = {s.key: s for s in _SPECS}


def get_spec(key: str) -> KpiSpec:
    if key not in KPI_REGISTRY:
        raise UnknownKpiError(
            f"KPI key {key!r} is not registered. Add it to "
            f"tests/_kpi/schema.py before emitting it from tests."
        )
    return KPI_REGISTRY[key]


__all__ = ["KpiSpec", "KPI_REGISTRY", "get_spec", "UnknownKpiError"]
