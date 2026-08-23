"""Guards for the three GUI-thread disk paths fixed on 2026-08-22.

All three were measured in ``user_data/logs/viewer_diagnostics.log`` on that day
(514 sampled ``[MAIN_THREAD_STALL_TRACE]`` stacks):

  A. Download badges — ``_refresh_statuses_chunked -> update_study_download_status
     -> _check_study_download_status -> check_study_complete``. Already chunked
     2-studies-per-tick, but the disk walk still ran on the GUI thread: a single
     chunk blocked for **13.1 s** and the refresh produced a 3.5-minute stall
     storm (14:14:30-14:18:00). The app was closed four seconds after it ended.
  B. Server search — ``add_data2patient_list_table -> get_study_download_status
     -> count_subfolders_with_dicom``, whose ``rglob('*')`` cost a MEASURED
     **682.5 ms per study** cold. Per row. 12-14 s stalls at 15:36.
  C. Storage cleanup — ``_execute_patient_cleanup -> cleanup_patients_folder``
     running ``shutil.rmtree`` + the DB delete inline: **183 seconds** frozen at
     10:04, 181 of that session's stall samples.

The guards below pin the corrections AND the properties that must not change:
the DICOM scan's verdict, the refresh's cache-write-on-GUI-thread discipline,
and the cleanup's reporting.
"""
import ast
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TABLE = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
          / "patient_table_widget.py")
_PANEL = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "settings_ui"
          / "storage_cleanup_panel.py")
_UTILS = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils" / "utils.py")


# ══════════════════════════════════════════════════════════════════════════
#  B. count_subfolders_with_dicom — the 682.5 ms-per-study scan
# ══════════════════════════════════════════════════════════════════════════

utils = pytest.importorskip("PacsClient.pacs.patient_tab.utils.utils")


def _tree(base: Path, spec: dict) -> Path:
    """{'series0': ['a.dcm'], 'series1': {'nested': ['b.dcm']}, 'empty': []}"""
    base.mkdir(parents=True, exist_ok=True)
    for name, content in spec.items():
        child = base / name
        if isinstance(content, dict):
            _tree(child, content)
        else:
            child.mkdir(parents=True, exist_ok=True)
            for fname in content:
                (child / fname).write_bytes(b"x")
    return base


@pytest.fixture(autouse=True)
def _default_flags(monkeypatch):
    for var in ("AIPACS_DICOM_SCAN_FAST", "AIPACS_STATUS_REFRESH_OFFTHREAD",
                "AIPACS_STORAGE_CLEANUP_OFFTHREAD", "AIPACS_STATUS_REFRESH_DISPATCH"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_direct_dicom_subfolders_are_counted(tmp_path):
    root = _tree(tmp_path / "study", {"0": ["a.dcm"], "1": ["b.DICOM"], "2": ["c.txt"]})
    assert utils.count_subfolders_with_dicom(root) == 2


def test_nested_dicom_still_counts(tmp_path):
    """Semantics preserved: 'at least one .dcm at ANY depth'."""
    root = _tree(tmp_path / "study", {"0": {"deep": {"deeper": ["a.dcm"]}}})
    assert utils.count_subfolders_with_dicom(root) == 1


def test_empty_and_non_dicom_subfolders_are_not_counted(tmp_path):
    root = _tree(tmp_path / "study", {"0": [], "1": ["thumb.png"], "2": {"x": ["y.jpg"]}})
    assert utils.count_subfolders_with_dicom(root) == 0


def test_top_level_files_are_ignored(tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    (root / "loose.dcm").write_bytes(b"x")
    assert utils.count_subfolders_with_dicom(root) == 0


def test_missing_folder_returns_zero(tmp_path):
    assert utils.count_subfolders_with_dicom(tmp_path / "nope") == 0


def test_fast_and_legacy_scans_agree(tmp_path, monkeypatch):
    spec = {
        "0": ["a.dcm", "b.dcm"],
        "1": {"sub": ["c.dicom"]},
        "2": ["thumb.png"],
        "3": [],
        "4": {"a": {"b": {"c": ["d.DCM"]}}},
    }
    root = _tree(tmp_path / "study", spec)
    monkeypatch.setenv("AIPACS_DICOM_SCAN_FAST", "1")
    fast = utils.count_subfolders_with_dicom(root)
    monkeypatch.setenv("AIPACS_DICOM_SCAN_FAST", "0")
    legacy = utils.count_subfolders_with_dicom(root)
    assert fast == legacy == 3


def test_the_fast_scan_does_not_use_rglob(tmp_path, monkeypatch):
    """THE behavioural guard: rglob('*') is what cost 682.5 ms per study, so the
    fast path must not touch it. Pre-fix this test fails — the old code calls it."""
    root = _tree(tmp_path / "study", {"0": ["a.dcm"], "1": ["t.png"]})

    def _boom(self, *a, **k):
        raise AssertionError("count_subfolders_with_dicom must not call rglob()")

    monkeypatch.setattr(Path, "rglob", _boom)
    assert utils.count_subfolders_with_dicom(root) == 1


def test_the_kill_switch_restores_the_rglob_walk(tmp_path, monkeypatch):
    root = _tree(tmp_path / "study", {"0": ["a.dcm"]})
    monkeypatch.setenv("AIPACS_DICOM_SCAN_FAST", "0")
    called = {"n": 0}
    original = Path.rglob

    def _counting(self, *a, **k):
        called["n"] += 1
        return original(self, *a, **k)

    monkeypatch.setattr(Path, "rglob", _counting)
    assert utils.count_subfolders_with_dicom(root) == 1
    assert called["n"] >= 1, "the kill switch must restore the legacy walk"


def test_a_subfolder_that_cannot_be_read_does_not_raise(tmp_path, monkeypatch):
    root = _tree(tmp_path / "study", {"0": ["a.dcm"]})
    real_scandir = os.scandir
    calls = {"n": 0}

    def _flaky(path, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:                      # the first SUBfolder
            raise OSError("permission denied")
        return real_scandir(path, *a, **k)

    monkeypatch.setattr(os, "scandir", _flaky)
    assert utils.count_subfolders_with_dicom(root) == 0   # skipped, not crashed


# ══════════════════════════════════════════════════════════════════════════
#  A. Download-status refresh — exec'd from source against a stub
# ══════════════════════════════════════════════════════════════════════════

_METHODS = (
    "_status_refresh_offthread_enabled",
    "_peek_download_status",
    "_compute_study_download_status",
    "_on_download_status_ready",
    "_refresh_statuses_chunked_impl",
)


def _stub_table():
    """Exec the five status methods from source into a bare class — no Qt, no
    2000-line widget constructor, and the guards still run the REAL code."""
    src = _TABLE.read_text(encoding="utf-8", errors="ignore")
    lines = src.splitlines()
    tree = ast.parse(src)
    wanted = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _METHODS:
            # ast.get_source_segment() drops decorators — and @staticmethod is
            # load-bearing here, so slice from the first decorator instead.
            start = node.lineno
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list)
            wanted[node.name] = "\n".join(lines[start - 1:node.end_lineno])
    missing = set(_METHODS) - set(wanted)
    assert not missing, "methods missing from patient_table_widget: %s" % sorted(missing)

    timers = []

    class _QTimer:
        @staticmethod
        def singleShot(_ms, fn):
            timers.append(fn)

    body = "\n".join(textwrap.dedent(wanted[name]) for name in _METHODS)
    ns = {"os": os, "time": time, "QTimer": _QTimer, "print": lambda *a, **k: None}
    exec("class _T:\n" + textwrap.indent(body, "    "), ns)   # noqa: S102
    cls = ns["_T"]

    obj = cls()
    obj._download_status_cache = {}
    obj._cache_validity_seconds = 5
    obj._status_refresh_token = 7
    obj.updated = []
    obj.dispatched = []
    obj.rebuild = False
    obj.update_study_download_status = lambda uid, status=None, is_downloaded=None: \
        obj.updated.append((uid, status))
    obj._dispatch_download_status_async = lambda uid, token: \
        obj.dispatched.append((uid, token))
    obj.table_rebuild_in_progress = lambda: obj.rebuild
    obj.timers = timers
    return obj


def test_a_cold_row_is_dispatched_not_walked_on_the_gui_thread():
    """The fix: an unresolved row must NOT call update_study_download_status
    (which is what walks the disk) — it must hand the work to the worker."""
    obj = _stub_table()
    uids = ["s%d" % i for i in range(5)]
    obj._refresh_statuses_chunked_impl(uids, 0, 7)
    assert obj.updated == []
    assert [u for u, _t in obj.dispatched] == uids


def test_a_warm_row_is_applied_without_dispatch():
    obj = _stub_table()
    now = time.time()
    obj._download_status_cache["s0"] = {"status": "complete", "timestamp": now}
    obj._refresh_statuses_chunked_impl(["s0"], 0, 7)
    assert obj.updated == [("s0", "complete")]
    assert obj.dispatched == []


def test_a_stale_cache_entry_is_treated_as_cold():
    obj = _stub_table()
    obj._download_status_cache["s0"] = {"status": "complete",
                                        "timestamp": time.time() - 999}
    obj._refresh_statuses_chunked_impl(["s0"], 0, 7)
    assert obj.updated == []
    assert obj.dispatched == [("s0", 7)]


def test_peek_never_computes():
    obj = _stub_table()
    assert obj._peek_download_status("missing") is None
    assert obj._download_status_cache == {}      # a peek must not populate


def test_a_superseded_refresh_stops_immediately():
    obj = _stub_table()
    obj._refresh_statuses_chunked_impl(["s0"], 0, 6)   # token 6 != 7
    assert obj.updated == [] and obj.dispatched == []


def test_a_late_answer_from_a_superseded_refresh_is_dropped():
    obj = _stub_table()
    obj._on_download_status_ready("s0", "complete", 6)
    assert obj.updated == []
    obj._on_download_status_ready("s0", "complete", 7)
    assert obj.updated == [("s0", "complete")]


def test_a_late_answer_is_dropped_while_the_table_is_rebuilding():
    obj = _stub_table()
    obj.rebuild = True
    obj._on_download_status_ready("s0", "complete", 7)
    assert obj.updated == []


def test_the_chain_continues_until_every_row_is_handled():
    obj = _stub_table()
    uids = ["s%d" % i for i in range(100)]
    obj._refresh_statuses_chunked_impl(uids, 0, 7)
    assert len(obj.dispatched) == 40             # AIPACS_STATUS_REFRESH_DISPATCH
    assert obj.timers, "the chain must re-arm for the remaining rows"


def test_offthread_kill_switch_restores_the_blocking_call(monkeypatch):
    monkeypatch.setenv("AIPACS_STATUS_REFRESH_OFFTHREAD", "0")
    obj = _stub_table()
    obj._refresh_statuses_chunked_impl(["s0", "s1"], 0, 7)
    assert obj.updated == [("s0", None), ("s1", None)]
    assert obj.dispatched == []


def test_compute_maps_every_result_shape(monkeypatch):
    obj = _stub_table()
    import PacsClient.pacs.patient_tab.utils.utils as _u
    for result, expected in (({"is_complete": True}, "complete"),
                             ({"is_complete": False, "series_downloaded": 3}, "partial"),
                             ({"is_complete": False, "series_downloaded": 0}, "not_downloaded"),
                             (True, "complete"),
                             (False, "not_downloaded"),
                             (None, "not_downloaded")):
        monkeypatch.setattr(_u, "check_study_complete", lambda _uid, r=result: r)
        assert obj._compute_study_download_status("s") == expected


def test_compute_never_raises(monkeypatch):
    obj = _stub_table()
    import PacsClient.pacs.patient_tab.utils.utils as _u

    def _boom(_uid):
        raise OSError("disk gone")

    monkeypatch.setattr(_u, "check_study_complete", _boom)
    assert obj._compute_study_download_status("s") == "not_downloaded"


# ══════════════════════════════════════════════════════════════════════════
#  C. Storage cleanup — the 183-second freeze
# ══════════════════════════════════════════════════════════════════════════

def _calls_in(path: Path, func_name: str):
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            out = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    fn = sub.func
                    if isinstance(fn, ast.Name):
                        out.add(fn.id)
                    elif isinstance(fn, ast.Attribute):
                        out.add(fn.attr)
            return out
    raise AssertionError("%s not found in %s" % (func_name, path.name))


def test_patient_cleanup_no_longer_runs_on_the_gui_thread():
    calls = _calls_in(_PANEL, "_execute_patient_cleanup")
    assert "cleanup_patients_folder" not in calls, \
        "the cleanup must be handed to the worker, not called inline"
    assert "cleanup_patients_folder_filtered" not in calls
    assert "_run_cleanup_job" in calls


def test_category_cleanup_no_longer_runs_on_the_gui_thread():
    calls = _calls_in(_PANEL, "_handle_cleanup_action")
    for blocking in ("cleanup_patients_folder", "cleanup_education_folder",
                     "cleanup_cache_folder", "cleanup_printing_folder",
                     "cleanup_offline_cloud_folder"):
        assert blocking not in calls, "%s must not be called inline" % blocking
    assert "_run_cleanup_job" in calls


def test_the_worker_moves_to_a_thread_and_reports_back():
    calls = _calls_in(_PANEL, "_run_cleanup_job")
    assert "moveToThread" in calls, "the job must actually leave the GUI thread"
    assert "QThread" in calls
    assert "start" in calls


def test_the_panel_still_reports_the_same_numbers():
    body = _PANEL.read_text(encoding="utf-8", errors="ignore")
    for field in ("folders_touched", "files_deleted", "db_rows_affected"):
        assert field in body, "the completion dialog must keep reporting %s" % field
    assert "storageChanged" in body


def test_cleanup_worker_emits_the_result():
    pytest.importorskip("PySide6.QtCore")
    panel = pytest.importorskip(
        "PacsClient.pacs.workstation_ui.settings_ui.storage_cleanup_panel")
    seen = []
    worker = panel._CleanupWorker(lambda: "the-result")
    worker.finished.connect(seen.append)
    worker.run()
    assert seen == ["the-result"]


def test_cleanup_worker_reports_failure_instead_of_raising():
    pytest.importorskip("PySide6.QtCore")
    panel = pytest.importorskip(
        "PacsClient.pacs.workstation_ui.settings_ui.storage_cleanup_panel")

    def _boom():
        raise RuntimeError("rmtree exploded")

    failures, done = [], []
    worker = panel._CleanupWorker(_boom)
    worker.failed.connect(failures.append)
    worker.finished.connect(done.append)
    worker.run()                                  # must not raise
    assert done == []
    assert failures and "rmtree exploded" in failures[0]


# ── the local-only refresh must not be a synchronous per-row loop any more ──

def test_storage_clear_refresh_goes_through_the_chunked_chain():
    calls = _calls_in(_TABLE, "refresh_download_statuses_local_only")
    assert "_refresh_statuses_chunked" in calls, \
        "the post-storage-clear refresh must not walk every row inline"
