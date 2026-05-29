"""ViewerCommandAdapter unit tests (read-only — by design cannot mutate state)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pydantic  # noqa: F401
except ImportError:
    import pytest
    pytest.skip("pydantic not installed", allow_module_level=True)

from modules.EchoMind.secretary import (  # noqa: E402
    AdapterRegistry, CommandBus, CommandPlan,
)
from modules.EchoMind.secretary.adapters import ViewerCommandAdapter  # noqa: E402


# ── fake patient widget mimicking the live API ─────────────────────────

class _FakeImageViewer:
    def __init__(self, series_uid, series_number, modality, study_uid,
                 orig_series_number=""):
        self.metadata = {"series": {
            "series_uid": series_uid,
            "series_number": series_number,
            "modality": modality,
            "study_uid": study_uid,
            "_orig_series_number": orig_series_number,
        }}


class _FakeVtkWidget:
    def __init__(self, iv): self.image_viewer = iv


class _FakeNode:
    def __init__(self, vtk_widget): self.vtk_widget = vtk_widget


class _FakePatientTab:
    """Single-study tab by default."""
    def __init__(self, *, is_multistudy=False):
        self.study_uid = "UID-PRIMARY"
        self.patient_id = "43743"
        nodes = [_FakeNode(_FakeVtkWidget(_FakeImageViewer(
            series_uid="SERIES-1", series_number="1",
            modality="MR", study_uid="UID-PRIMARY",
        )))]
        self.lst_nodes_viewer = nodes
        self.selected_widget = nodes[0].vtk_widget
        self.lst_thumbnails_data = [
            {"series_number": "1", "modality": "MR", "image_count": 12,
             "metadata": {"series": {"series_uid": "SERIES-1",
                                      "study_uid": "UID-PRIMARY"}}},
            {"series_number": "2", "modality": "MR", "image_count": 8,
             "metadata": {"series": {"series_uid": "SERIES-2",
                                      "study_uid": "UID-PRIMARY"}}},
        ]
        if is_multistudy:
            self._studies_series = {
                "UID-PRIMARY": [{"series_number": "1"}, {"series_number": "2"}],
                "UID-PRIOR":   [{"series_number": "1"}, {"series_number": "2"},
                                 {"series_number": "3"}],
            }
            self.lst_thumbnails_data.append({
                "series_number": "1000001",
                "modality": "MR", "image_count": 5,
                "metadata": {"series": {
                    "series_uid": "PRIOR-SERIES-1",
                    "study_uid": "UID-PRIOR",
                    "_orig_series_number": "1",
                }},
            })


class _FakeTabWidget:
    def __init__(self, tabs):
        self._tabs = tabs
        self._current = 0
    def count(self): return len(self._tabs)
    def tabText(self, i): return self._tabs[i][1]
    def currentIndex(self): return self._current
    def currentWidget(self): return self._tabs[self._current][0]


def _bus_with_viewer(tab=None, main_tabs=None):
    adapter = ViewerCommandAdapter(
        get_active_patient_tab=lambda: tab,
        get_main_tab_widget=lambda: main_tabs,
    )
    reg = AdapterRegistry()
    reg.register("viewer", adapter, actions={
        "get_active_tab":      "get_active_tab",
        "list_open_tabs":      "list_open_tabs",
        "get_thumbnails_data": "get_thumbnails_data",
        "get_active_series":   "get_active_series",
        "get_multistudy_info": "get_multistudy_info",
    })
    return CommandBus(registry=reg, orchestrator=None)


# ── tests ──────────────────────────────────────────────────────────────

def test_no_active_tab_returns_clean_error():
    bus = _bus_with_viewer(tab=None)
    for action in ("get_active_tab", "get_thumbnails_data",
                   "get_active_series", "get_multistudy_info"):
        r = bus.execute(CommandPlan(action=action))
        assert r.ok is False
        assert r.error_code == "NO_ACTIVE_TAB"


def test_get_active_tab_single_study():
    tab = _FakePatientTab(is_multistudy=False)
    bus = _bus_with_viewer(tab=tab)
    r = bus.execute(CommandPlan(action="get_active_tab"))
    assert r.ok
    assert r.data["study_uid"] == "UID-PRIMARY"
    assert r.data["patient_id"] == "43743"
    assert r.data["is_multistudy"] is False
    assert r.data["viewport_count"] == 1


def test_get_active_tab_multistudy_flag_propagates():
    tab = _FakePatientTab(is_multistudy=True)
    bus = _bus_with_viewer(tab=tab)
    r = bus.execute(CommandPlan(action="get_active_tab"))
    assert r.ok
    assert r.data["is_multistudy"] is True


def test_list_open_tabs():
    tab = _FakePatientTab()
    main = _FakeTabWidget([(tab, "Patient 43743"),
                           (object(), "Download Manager")])
    bus = _bus_with_viewer(tab=tab, main_tabs=main)
    r = bus.execute(CommandPlan(action="list_open_tabs"))
    assert r.ok
    assert r.data["count"] == 2
    titles = [t["title"] for t in r.data["tabs"]]
    assert titles == ["Patient 43743", "Download Manager"]


def test_list_open_tabs_no_tab_widget_error():
    bus = _bus_with_viewer(tab=_FakePatientTab(), main_tabs=None)
    r = bus.execute(CommandPlan(action="list_open_tabs"))
    assert r.ok is False
    assert r.error_code == "NO_TAB_WIDGET"


def test_get_thumbnails_data_returns_rows_with_orig_series_number():
    tab = _FakePatientTab(is_multistudy=True)
    bus = _bus_with_viewer(tab=tab)
    r = bus.execute(CommandPlan(action="get_thumbnails_data"))
    assert r.ok
    rows = r.data["rows"]
    assert r.data["count"] == 3
    assert r.data["is_multistudy"] is True
    # The multi-study row should carry the orig_series_number, not the
    # opaque offset key as the "real" series number.
    multi_row = next(r for r in rows if r["study_uid"] == "UID-PRIOR")
    assert multi_row["orig_series_number"] == "1"
    assert multi_row["series_number"] == "1000001"  # opaque offset key


def test_get_active_series_focused_viewport():
    tab = _FakePatientTab()
    bus = _bus_with_viewer(tab=tab)
    r = bus.execute(CommandPlan(action="get_active_series"))
    assert r.ok
    assert r.data["series_uid"] == "SERIES-1"
    assert r.data["series_number"] == "1"
    assert r.data["modality"] == "MR"


def test_get_active_series_returns_empty_when_no_viewport():
    class _EmptyTab(_FakePatientTab):
        def __init__(self):
            super().__init__()
            self.lst_nodes_viewer = []
            self.selected_widget = None
    bus = _bus_with_viewer(tab=_EmptyTab())
    r = bus.execute(CommandPlan(action="get_active_series"))
    assert r.ok is False
    assert r.error_code == "NO_VIEWPORT"


def test_get_multistudy_info_single_study_returns_one_primary_row():
    bus = _bus_with_viewer(tab=_FakePatientTab(is_multistudy=False))
    r = bus.execute(CommandPlan(action="get_multistudy_info"))
    assert r.ok
    assert len(r.data["studies"]) == 1
    only = r.data["studies"][0]
    assert only["study_uid"] == "UID-PRIMARY"
    assert only["is_primary"] is True
    assert r.data["is_multistudy"] is False


def test_get_multistudy_info_multistudy_flags_primary():
    bus = _bus_with_viewer(tab=_FakePatientTab(is_multistudy=True))
    r = bus.execute(CommandPlan(action="get_multistudy_info"))
    assert r.ok
    studies = r.data["studies"]
    assert len(studies) == 2
    primary_rows = [s for s in studies if s["is_primary"]]
    prior_rows   = [s for s in studies if not s["is_primary"]]
    assert len(primary_rows) == 1
    assert len(prior_rows) == 1
    assert primary_rows[0]["study_uid"] == "UID-PRIMARY"
    assert primary_rows[0]["series_count"] == 2
    assert prior_rows[0]["series_count"] == 3


def test_adapter_is_purely_read_only():
    """ViewerCommandAdapter exposes ONLY query methods.

    Catches accidental addition of mutating actions. The contract is
    asymmetric on purpose — see MULTI_STUDY_SINGLE_TAB_PLAN.md.
    """
    write_verbs = ("set", "change", "scroll", "rotate", "flip",
                   "toggle", "apply", "clear")
    for action in ViewerCommandAdapter.SUPPORTED_ACTIONS:
        for verb in write_verbs:
            assert not action.startswith(verb), (
                f"ViewerCommandAdapter action {action!r} starts with "
                f"a write verb. Read-only adapter must not expose mutators."
            )
