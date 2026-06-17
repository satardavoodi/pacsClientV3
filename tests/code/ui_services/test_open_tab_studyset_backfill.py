"""Phase-3 (46630 fix) regression: the OPEN viewer tab is back-filled when the
patient's study set is discovered to have grown after the tab was built.

Target: `_HPPatientOpenMixin._backfill_open_viewer_studyset`
(`PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`).

The method is bound to a lightweight stub (the home-panel collaborators are
stubbed), so these run on Windows with PySide6. `is_widget_alive` is module-level
in `_hp_patient_open`, so it is monkeypatched. The method is METADATA-ONLY — it
calls the viewer's merge-aware `set_server_series_info`; it never touches
geometry/VTK/MPR.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytestmark = pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None,
    reason="PySide6 required to import the home-panel mixin",
)

from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_patient_open as hpo  # noqa: E402


def _bind(stub):
    stub._backfill_open_viewer_studyset = (
        hpo._HPPatientOpenMixin._backfill_open_viewer_studyset.__get__(stub)
    )
    stub._enqueue_missing_series_for_open_study = (
        hpo._HPPatientOpenMixin._enqueue_missing_series_for_open_study.__get__(stub)
    )
    if not hasattr(stub, "_get_or_create_download_manager_tab"):
        stub._get_or_create_download_manager_tab = lambda activate_tab=False: None
    return stub


def test_backfill_pushes_late_doc_study(monkeypatch):
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    pushed = {}
    widget = types.SimpleNamespace(
        _server_series_info={"1": {"study_uid": "PRIMARY", "series_number": "1"}},
        _studies_series={"PRIMARY": [{"study_uid": "PRIMARY"}]},
    )
    widget.set_server_series_info = lambda series: pushed.__setitem__("series", series)

    traces = []
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: widget if uid == "PRIMARY" else None
    stub._get_or_fetch_series_info = lambda su, pid, force: (
        {"patient_id": "46630",
         "series": [{"series_uid": "doc-s", "series_number": "100000", "study_uid": "DOC"}]}
        if su == "DOC" else
        {"patient_id": "46630",
         "series": [{"series_uid": "p-s", "series_number": "1", "study_uid": "PRIMARY"}]}
    )
    stub._log_open_trace = lambda uid, phase, **kw: traces.append((phase, kw))
    _bind(stub)

    asyncio.run(stub._backfill_open_viewer_studyset("46630", "name", ["PRIMARY", "DOC"]))

    assert "series" in pushed, "open viewer was not back-filled"
    assert {s["study_uid"] for s in pushed["series"]} == {"DOC"}  # only the MISSING study
    assert getattr(widget, "_is_multistudy_hint", None) is True
    assert any(t[0] == "patient_study_set_viewer_backfill" for t in traces)


def test_backfill_noop_when_no_open_tab(monkeypatch):
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    fetched = []
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: None
    stub._get_or_fetch_series_info = lambda su, pid, force: fetched.append(su)
    stub._log_open_trace = lambda *a, **k: None
    _bind(stub)
    # Must not raise and must not fetch anything (no tab to update).
    asyncio.run(stub._backfill_open_viewer_studyset("46630", "n", ["A", "B"]))
    assert fetched == []


def test_backfill_noop_when_tab_already_complete(monkeypatch):
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    pushed = {}
    widget = types.SimpleNamespace(
        _server_series_info={"1": {"study_uid": "PRIMARY"}, "100000": {"study_uid": "DOC"}},
        _studies_series={"PRIMARY": [], "DOC": []},
    )
    widget.set_server_series_info = lambda series: pushed.__setitem__("series", series)
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: widget
    stub._get_or_fetch_series_info = lambda su, pid, force: {"patient_id": "46630", "series": []}
    stub._log_open_trace = lambda *a, **k: None
    _bind(stub)
    asyncio.run(stub._backfill_open_viewer_studyset("46630", "n", ["PRIMARY", "DOC"]))
    assert "series" not in pushed  # nothing pushed — tab already has both studies


def test_backfill_skips_foreign_study(monkeypatch):
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    pushed = {}
    widget = types.SimpleNamespace(
        _server_series_info={"1": {"study_uid": "PRIMARY"}},
        _studies_series={"PRIMARY": []},
    )
    widget.set_server_series_info = lambda series: pushed.__setitem__("series", series)
    traces = []
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: widget
    stub._get_or_fetch_series_info = lambda su, pid, force: {
        "patient_id": "44533",
        "series": [{"series_uid": "f", "series_number": "9", "study_uid": "FOREIGN"}],
    }
    stub._log_open_trace = lambda uid, phase, **kw: traces.append((phase, kw))
    _bind(stub)
    asyncio.run(stub._backfill_open_viewer_studyset("46630", "n", ["PRIMARY", "FOREIGN"]))
    assert "series" not in pushed  # foreign study must NOT be attached
    assert any(t[0] == "viewer_backfill_cross_patient_skip" for t in traces)


def test_backfill_enqueues_missing_late_study(monkeypatch):
    # The open-intent half: a late DOC study that is missing on disk must also be
    # QUEUED for download (not just shown), because a viewer tab is open.
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    import modules.storage.sync_manifest as _sm
    monkeypatch.setattr(
        _sm, "evaluate_sync",
        lambda study_uid, server_series=None: {"missing_series": ["100000"], "partial_series": []})
    pushed = {}
    widget = types.SimpleNamespace(
        _server_series_info={"1": {"study_uid": "PRIMARY"}}, _studies_series={"PRIMARY": []})
    widget.set_server_series_info = lambda series: pushed.__setitem__("series", series)
    enq = []
    dm = types.SimpleNamespace(
        add_downloads=lambda lst, start_immediately=False: enq.extend(lst),
        state_store=types.SimpleNamespace(get=lambda u: None))
    traces = []
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: widget
    stub._get_or_fetch_series_info = lambda su, pid, force: {
        "patient_id": "46630", "study_description": "Doc", "count_of_series": 1,
        "series": [{"series_uid": "doc-s", "series_number": "100000", "study_uid": "DOC", "image_count": 1}],
    }
    stub._get_or_create_download_manager_tab = lambda activate_tab=False: dm
    stub._log_open_trace = lambda uid, phase, **kw: traces.append((phase, kw))
    _bind(stub)

    asyncio.run(stub._backfill_open_viewer_studyset("46630", "name", ["PRIMARY", "DOC"]))

    assert "series" in pushed  # metadata pushed to the open viewer
    assert any(d.get("study_uid") == "DOC" for d in enq), "late DOC study not enqueued for download"
    assert any(t[0] == "patient_study_set_late_download_enqueued" for t in traces)


def test_backfill_finds_tab_by_secondary_uid(monkeypatch):
    # Patient-level tab lookup (Step 6): the open tab is keyed by a SECONDARY study
    # UID (not uids[0]); back-fill must still find it by trying every study in the set.
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    pushed = {}
    widget = types.SimpleNamespace(
        _server_series_info={"100000": {"study_uid": "DOC"}}, _studies_series={"DOC": []})
    widget.set_server_series_info = lambda series: pushed.__setitem__("series", series)
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: widget if uid == "DOC" else None  # tab keyed by DOC
    stub._get_or_fetch_series_info = lambda su, pid, force: {
        "patient_id": "46630",
        "series": [{"series_uid": "p", "series_number": "1", "study_uid": "PRIMARY"}]}
    stub._log_open_trace = lambda *a, **k: None
    _bind(stub)
    asyncio.run(stub._backfill_open_viewer_studyset("46630", "n", ["PRIMARY", "DOC"]))
    assert "series" in pushed  # tab found via the secondary UID; PRIMARY back-filled
    assert {s["study_uid"] for s in pushed["series"]} == {"PRIMARY"}


def test_backfill_no_download_when_no_open_tab(monkeypatch):
    # The no-download contract: a single-click preview with NO open tab must never
    # enqueue a download (the back-fill returns before any fetch/enqueue).
    monkeypatch.setattr(hpo, "is_widget_alive", lambda w: True)
    enq = []
    dm = types.SimpleNamespace(
        add_downloads=lambda lst, **k: enq.extend(lst),
        state_store=types.SimpleNamespace(get=lambda u: None))
    stub = types.SimpleNamespace()
    stub._find_widget_by_study_uid = lambda uid: None  # no open tab for this patient
    stub._get_or_fetch_series_info = lambda su, pid, force: {"patient_id": "46630", "series": []}
    stub._get_or_create_download_manager_tab = lambda activate_tab=False: dm
    stub._log_open_trace = lambda *a, **k: None
    _bind(stub)

    asyncio.run(stub._backfill_open_viewer_studyset("46630", "n", ["A", "B"]))
    assert enq == []  # no open tab -> no download
