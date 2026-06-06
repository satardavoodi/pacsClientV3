"""Guards for the Data Analysis dashboard freeze fix (2026-06-06).

Contract:
  1. DataAnalysisDashboard.refresh_data() never runs build_snapshot on the
     GUI thread — it returns immediately and applies the snapshot via a
     queued signal from a background thread.
  2. Overlapping refresh requests coalesce into at most one pending re-run,
     keeping the strongest force_storage_refresh flag.
  3. DataAnalysisService caches storage stats / cleanup info with a TTL;
     force_storage_refresh bypasses the cache.
  4. The single-pass USER_DATA_ROOT walk produces byte-identical totals to
     the legacy per-entry walks.
  5. AIPacs_ui re-open path must NOT force a storage re-walk.

These tests stub the service snapshot — they must never touch the live
dicom.db or the real user_data tree.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

import modules.data_analysis.service as service_mod  # noqa: E402
from modules.data_analysis.service import DataAnalysisService  # noqa: E402
from modules.data_analysis.widget import DataAnalysisDashboard  # noqa: E402


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _canned_snapshot(tag: str = "t") -> dict:
    return {
        "account": {"full_name": "Test", "username": "test", "role": "user"},
        "active_filters": {"date_range": "All Time", "server": "All Servers", "user": "All Users"},
        "filter_options": {
            "date_ranges": list(DataAnalysisService.DATE_RANGES),
            "servers": ["All Servers"],
            "users": ["All Users"],
        },
        "totals": {"patients": 1, "studies": 2},
        "modalities": [{"modality": "MR", "count": 2, "percent": 100.0}],
        "module_usage": [],
        "study_trend": [],
        "report_status": [],
        "servers": [],
        "storage": [],
        "storage_cleanup": {"drives": [], "folders": []},
        "recent_studies": [],
        "generated_at": tag,
    }


def _wait_until(qapp, predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── 1+2: async refresh + coalescing ─────────────────────────────────────────
def test_refresh_is_async_and_coalesces(qapp, monkeypatch):
    gate = threading.Event()
    calls = []

    def fake_build(self, auth_user=None, filters=None):
        calls.append(dict(filters or {}))
        assert threading.current_thread() is not threading.main_thread(), (
            "build_snapshot must never run on the GUI thread"
        )
        gate.wait(timeout=5.0)
        return _canned_snapshot(tag=f"run{len(calls)}")

    monkeypatch.setattr(DataAnalysisService, "build_snapshot", fake_build)

    t0 = time.monotonic()
    dash = DataAnalysisDashboard()  # __init__ triggers refresh #1
    construct_time = time.monotonic() - t0
    assert construct_time < 2.0, f"constructor blocked for {construct_time:.1f}s"
    assert dash._refresh_in_flight is True
    assert dash.generated_at_label.text() == "Updating…"
    assert not dash.refresh_btn.isEnabled()

    # Requests while in flight must coalesce into ONE pending re-run,
    # keeping the strongest force flag.
    dash.refresh_data(force_storage_refresh=False)
    dash.refresh_data(force_storage_refresh=True)
    dash.refresh_data(force_storage_refresh=False)
    assert dash._pending_refresh is True
    assert len(calls) == 1

    gate.set()
    assert _wait_until(qapp, lambda: len(calls) == 2 and not dash._refresh_in_flight)
    assert dash._pending_refresh is None
    # Pending re-run carried force flag through.
    assert calls[1].get("force_storage_refresh") is True
    # Snapshot applied on the GUI thread.
    assert dash._snapshot.get("generated_at", "").startswith("run")
    assert dash.refresh_btn.isEnabled()
    assert "Updating" not in dash.generated_at_label.text()
    assert dash._kpi_labels["patients"].text() == "1"


def test_failed_snapshot_keeps_previous_data(qapp, monkeypatch):
    ok = _canned_snapshot(tag="good")
    state = {"fail": False}

    def fake_build(self, auth_user=None, filters=None):
        if state["fail"]:
            raise RuntimeError("boom")
        return ok

    monkeypatch.setattr(DataAnalysisService, "build_snapshot", fake_build)
    dash = DataAnalysisDashboard()
    assert _wait_until(qapp, lambda: not dash._refresh_in_flight)
    assert dash._snapshot.get("generated_at") == "good"

    state["fail"] = True
    dash.refresh_data()
    assert _wait_until(qapp, lambda: not dash._refresh_in_flight)
    # Old snapshot retained; UI re-enabled.
    assert dash._snapshot.get("generated_at") == "good"
    assert dash.refresh_btn.isEnabled()


# ── 3: storage TTL cache ────────────────────────────────────────────────────
def test_storage_stats_cached_with_ttl(monkeypatch):
    svc = DataAnalysisService()
    walk_calls = []
    monkeypatch.setattr(
        DataAnalysisService,
        "_collect_storage_stats",
        lambda self: walk_calls.append(1) or [{"name": "X", "path": "p", "size_bytes": 1, "files": 1}],
    )

    first = svc._collect_storage_stats_cached(force_refresh=False)
    second = svc._collect_storage_stats_cached(force_refresh=False)
    assert len(walk_calls) == 1, "second call within TTL must use the cache"
    assert first == second

    svc._collect_storage_stats_cached(force_refresh=True)
    assert len(walk_calls) == 2, "force_refresh must bypass the cache"

    svc._storage_stats_cache_ts = time.monotonic() - (svc.STORAGE_CACHE_TTL_SEC + 1)
    svc._collect_storage_stats_cached(force_refresh=False)
    assert len(walk_calls) == 3, "expired TTL must re-walk"


def test_storage_cleanup_cached_with_ttl(monkeypatch):
    svc = DataAnalysisService()
    calls = []
    monkeypatch.setattr(
        DataAnalysisService,
        "_collect_storage_cleanup_info",
        lambda self, force_refresh=False: calls.append(1) or {"drives": [], "folders": []},
    )
    svc._collect_storage_cleanup_info_cached(force_refresh=False)
    svc._collect_storage_cleanup_info_cached(force_refresh=False)
    assert len(calls) == 1
    svc._collect_storage_cleanup_info_cached(force_refresh=True)
    assert len(calls) == 2


# ── 4: single-pass walk equivalence ─────────────────────────────────────────
def test_single_pass_walk_matches_legacy_per_entry_walks(tmp_path, monkeypatch):
    root = tmp_path / "user_data"
    layout = {
        "database/dicom.db": 10,
        "patients/dicom/s1/a.dcm": 100,
        "patients/dicom/s1/b.dcm": 50,
        "patients/thumbnails/s1/1.png": 7,
        "patients/attachments/x.bin": 5,
        "echomind/e.txt": 3,
        "reports/r.txt": 2,
        "logs/app.log": 1,  # only counted in User Data Root
    }
    for rel, size in layout.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)

    monkeypatch.setattr(service_mod, "USER_DATA_ROOT", root)
    monkeypatch.setattr(service_mod, "DATABASE_FILE", root / "database" / "dicom.db")
    monkeypatch.setattr(service_mod, "DICOM_IMAGES_DIR", root / "patients" / "dicom")
    monkeypatch.setattr(service_mod, "ATTACHMENTS_DIR", root / "patients" / "attachments")
    monkeypatch.setattr(service_mod, "THUMBNAILS_DIR", root / "patients" / "thumbnails")
    monkeypatch.setattr(service_mod, "ECHOMIND_DIR", root / "echomind")
    monkeypatch.setattr(service_mod, "REPORTS_DIR", root / "reports")

    svc = DataAnalysisService()
    stats = {row["name"]: row for row in svc._collect_storage_stats()}

    expected = {
        "Database": (10, 1),
        "DICOM Storage": (150, 2),
        "Attachments": (5, 1),
        "Thumbnails": (7, 1),
        "EchoMind": (3, 1),
        "Reports": (2, 1),
        "User Data Root": (178, 8),
    }
    for name, (size_b, files) in expected.items():
        assert stats[name]["size_bytes"] == size_b, name
        assert stats[name]["files"] == files, name

    # Equivalence with the legacy per-entry walk implementation.
    for name, row in stats.items():
        legacy_size, legacy_files = svc._path_stats(Path(row["path"]))
        assert (row["size_bytes"], row["files"]) == (legacy_size, legacy_files), name


def test_missing_paths_report_zero(tmp_path, monkeypatch):
    root = tmp_path / "empty_root"
    root.mkdir()
    for const in (
        "DATABASE_FILE",
        "DICOM_IMAGES_DIR",
        "ATTACHMENTS_DIR",
        "THUMBNAILS_DIR",
        "ECHOMIND_DIR",
        "REPORTS_DIR",
    ):
        monkeypatch.setattr(service_mod, const, root / "missing" / const.lower())
    monkeypatch.setattr(service_mod, "USER_DATA_ROOT", root)

    svc = DataAnalysisService()
    for row in svc._collect_storage_stats():
        assert row["size_bytes"] == 0
        assert row["files"] == 0


# ── 5: no background work while the page is hidden ─────────────────────────
def test_auto_refresh_only_runs_while_visible(qapp, monkeypatch):
    monkeypatch.setattr(
        DataAnalysisService, "build_snapshot", lambda self, a=None, f=None: _canned_snapshot()
    )
    dash = DataAnalysisDashboard()
    assert _wait_until(qapp, lambda: not dash._refresh_in_flight)

    refreshes = []
    monkeypatch.setattr(dash, "refresh_data", lambda force_storage_refresh=False: refreshes.append(1))

    # Hidden page (user is elsewhere): the tick must do NOTHING — the module
    # must not consume CPU/disk/DB in the background.
    assert not dash.isVisible()
    dash._on_auto_refresh_tick()
    assert not refreshes

    dash.show()
    qapp.processEvents()
    dash._on_auto_refresh_tick()
    assert len(refreshes) == 1

    # Timer lifecycle: opted-in auto refresh pauses on hide, resumes on show.
    dash.auto_refresh_checkbox.setChecked(True)
    assert dash._auto_refresh_timer.isActive()
    dash.hide()
    qapp.processEvents()
    assert not dash._auto_refresh_timer.isActive(), "hidden page must stop polling"
    dash.show()
    qapp.processEvents()
    assert dash._auto_refresh_timer.isActive(), "opted-in auto refresh resumes on show"
    dash.hide()


# ── 6: AIPacs_ui re-open path must not force a re-walk ─────────────────────
def test_reopen_does_not_force_storage_refresh():
    src = (
        _REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "AIPacs_ui.py"
    ).read_text(encoding="utf-8")
    refresh_fn = src.split("def _refresh_data_analysis_async", 1)[1].split("def ", 1)[0]
    assert "refresh_data(force_storage_refresh=False)" in refresh_fn, (
        "module re-open must use the storage cache; only the dashboard's "
        "Refresh button forces a re-walk"
    )
