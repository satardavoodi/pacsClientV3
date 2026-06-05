# -*- coding: utf-8 -*-
"""Live-adapter API contract tests (fidelity audit 2026-06-04 §4.4).

The command layer dispatches into ``HomeWidgetAdapter`` by name and argument
shape. Four latent bugs (unreachable open_patient, rowless list_patients,
unattached DownloadAdapter, study-level thumbnails) stayed invisible because
test fakes drifted from this live surface. These tests pin the contract: if a
live adapter method is renamed or its signature changes, this fails loudly —
BEFORE an agent run discovers it against the real app.
"""
from __future__ import annotations

import inspect

from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
from modules.EchoMind.secretary.adapters.viewer_write_adapter import (
    TEST_WRITE_ACTIONS,
    ViewerWriteCommandAdapter,
)


def _params(fn):
    return [p.name for p in inspect.signature(fn).parameters.values()]


def test_home_widget_adapter_contract():
    # open_patient(patient_id, patient_name, study_uid, report_status="pending")
    p = _params(HomeWidgetAdapter.open_patient)
    assert p == ["self", "patient_id", "patient_name", "study_uid", "report_status"]
    assert (inspect.signature(HomeWidgetAdapter.open_patient)
            .parameters["report_status"].default == "pending")

    # select_patient(patient_id, patient_name, study_uid)
    p = _params(HomeWidgetAdapter.select_patient)
    assert p == ["self", "patient_id", "patient_name", "study_uid"]

    # search(source, criteria, timeout_s=...)
    p = _params(HomeWidgetAdapter.search)
    assert p[:3] == ["self", "source", "criteria"]

    # read_patient_rows() -> rows with the keys the MCP/stress drivers consume
    assert _params(HomeWidgetAdapter.read_patient_rows) == ["self"]


def test_read_patient_rows_row_shape():
    class _FakeHome:
        _server_patient_meta_by_pid = {
            "1": {"latest_study_uid": "u1", "study_uids": ["u1"],
                  "modalities": ["CT"], "total_studies": 1,
                  "patient_name": "n1", "report_status": "pending"},
        }
        _server_series_count_by_study = {"u1": 7}

    rows = HomeWidgetAdapter(home_widget=_FakeHome()).read_patient_rows()
    assert len(rows) == 1
    row = rows[0]
    for key in ("patient_id", "study_uid", "study_uids", "modalities",
                "total_studies", "series_count", "patient_name", "report_status"):
        assert key in row, f"read_patient_rows row missing '{key}'"
    assert row["series_count"] == 7 and row["patient_name"] == "n1"


def test_viewer_write_actions_registered_and_present():
    for action, method in TEST_WRITE_ACTIONS.items():
        fn = getattr(ViewerWriteCommandAdapter, method, None)
        assert callable(fn), f"write adapter missing method for action '{action}'"
        assert _params(fn) == ["self", "plan", "state"]
    for required in ("change_series", "query_viewport_state", "get_series_info",
                     "close_patient_tab", "switch_tab"):
        assert required in TEST_WRITE_ACTIONS


def test_command_adapter_select_patient_resolves_from_rows():
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan

    calls = {}

    class _FakeLegacy:
        def is_available(self):  # satisfies HomeCommandAdapter._available()
            return True

        def read_patient_rows(self):
            return [{"patient_id": "44866", "patient_name": "manijeh",
                     "study_uid": "uidX"}]

        def select_patient(self, pid, name, uid):
            calls["args"] = (pid, name, uid)

    adapter = HomeCommandAdapter(_FakeLegacy())
    res = adapter.select_patient(
        CommandPlan(action="select_patient", entities={"patient_id": "44866"}), {})
    assert res.ok, res.message
    assert calls["args"] == ("44866", "manijeh", "uidX")
