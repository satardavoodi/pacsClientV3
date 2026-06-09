"""Guards for the multi-patient tab lifecycle fix (2026-06-09).

Scenario that regressed: open Patient A + Patient B, report/sync A, then close
A via the native tab 'X'. B shifts to a lower QTabWidget index, but
CustomTabManager.patient_tabs / study_uid_to_tab stayed keyed by the OLD
indices, so on_tab_changed(new_index) resolved the stale dict — it re-activated
A's dead entry (or nothing) and never called B.on_tab_activated(). B's viewer
therefore stayed in the on_tab_deactivated() torn-down state
(zeta_boost.deactivate(clear_cache=True), image-slice booster cleared, prefetch
stopped) → drag-drop, stacking and series-import into B all broke.

Fix:
  1. CustomTabManager.on_tab_changed resolves the active tab by the LIVE widget
     at ``index`` (identity), not by the stale ``patient_tabs[index]`` key, and
     activates a surviving patient widget even when its map entry is stale.
  2. MainWindow.close_tab (the native tab-'X' handler) calls the tab manager's
     update_tab_indices() after removeTab(), so the index maps are rebuilt
     instead of left stale.
"""
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_CTM = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "custom_tab_manager.py")
_MAINWIN = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py")


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _load_on_tab_changed():
    """Exec just CustomTabManager.on_tab_changed against a stub holder."""
    src = _CTM.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def on_tab_changed")
    end = src.index("def show_patient_list", start)
    fn_src = "    " + src[start:end].rstrip() + "\n"
    ns = {"logger": logging.getLogger("test")}
    exec("class _Holder:\n" + fn_src, ns)  # noqa: S102 — test-local exec of repo source
    return ns["_Holder"].on_tab_changed


class _Widget:
    def __init__(self, name):
        self.name = name
        self.activated = 0
        self.deactivated = 0

    def on_tab_activated(self):
        self.activated += 1

    def on_tab_deactivated(self):
        self.deactivated += 1


class _CustomTab:
    def __init__(self):
        self.active = None

    def set_active(self, value):
        self.active = value


class _TabWidget:
    def __init__(self, widgets):
        self._widgets = list(widgets)  # index -> widget (0 == home placeholder)

    def widget(self, i):
        return self._widgets[i] if 0 <= i < len(self._widgets) else None

    def count(self):
        return len(self._widgets)


class _Stub:
    def __init__(self, tab_widget, patient_tabs):
        self.tab_widget = tab_widget
        self.patient_tabs = patient_tabs
        self.logo_calls = []

    def set_logo_active(self, value):
        self.logo_calls.append(value)


def test_surviving_tab_activated_by_identity_when_index_map_is_stale():
    """The crux: after A closed, the live widget at index 1 is B, but the
    (stale) patient_tabs still maps index 1 -> A and index 2 -> B. The handler
    must activate B (the real current widget), NOT A."""
    on_tab_changed = _load_on_tab_changed()

    home = object()
    A = _Widget("A")
    B = _Widget("B")
    # Live tabs after closing A: [home, B]; B is current at index 1.
    tab_widget = _TabWidget([home, B])
    # STALE map (not rebuilt): still keyed as before A closed.
    patient_tabs = {
        1: {"widget": A, "custom_tab": _CustomTab(), "study_uid": "A"},
        2: {"widget": B, "custom_tab": _CustomTab(), "study_uid": "B"},
    }
    stub = _Stub(tab_widget, patient_tabs)

    on_tab_changed(stub, 1)

    # B (the live widget at index 1) must be activated, by identity.
    assert B.activated == 1, "surviving tab B must receive on_tab_activated()"
    assert B.deactivated == 0, "the current tab B must not be deactivated"
    # A is no longer the current widget -> must be deactivated, never activated.
    assert A.activated == 0, "the closed/old entry A must not be activated"


def test_switching_between_two_live_tabs_activates_only_the_target():
    on_tab_changed = _load_on_tab_changed()
    home = object()
    A = _Widget("A")
    B = _Widget("B")
    tab_widget = _TabWidget([home, A, B])  # both open; switch to B (index 2)
    patient_tabs = {
        1: {"widget": A, "custom_tab": _CustomTab(), "study_uid": "A"},
        2: {"widget": B, "custom_tab": _CustomTab(), "study_uid": "B"},
    }
    stub = _Stub(tab_widget, patient_tabs)

    on_tab_changed(stub, 2)

    assert B.activated == 1 and B.deactivated == 0
    assert A.deactivated == 1 and A.activated == 0


def test_patient_list_tab_sets_logo_active():
    on_tab_changed = _load_on_tab_changed()
    home = object()
    A = _Widget("A")
    tab_widget = _TabWidget([home, A])
    patient_tabs = {1: {"widget": A, "custom_tab": _CustomTab(), "study_uid": "A"}}
    stub = _Stub(tab_widget, patient_tabs)

    on_tab_changed(stub, 0)  # the patient-list/home tab

    assert stub.logo_calls and stub.logo_calls[-1] is True
    assert A.deactivated == 1  # the patient tab was deactivated


def test_on_tab_changed_resolves_by_widget_not_index_key():
    """Source guard: activation must read the live widget, not patient_tabs[index]."""
    code = _strip_comments(_CTM.read_text(encoding="utf-8", errors="ignore"))
    start = code.index("def on_tab_changed")
    end = code.index("def show_patient_list", start)
    body = code[start:end]
    assert "self.tab_widget.widget(index)" in body, (
        "on_tab_changed must resolve the active tab by live widget identity"
    )
    # the old stale-index activation form must be gone
    assert "if index in self.patient_tabs:" not in body, (
        "activation must not key off the (stale) patient_tabs[index]"
    )


def test_close_tab_reconciles_tab_manager_indices():
    """Source guard: the native tab-'X' close path must rebuild the tab
    manager's index maps so the surviving patient is not mis-resolved."""
    code = _strip_comments(_MAINWIN.read_text(encoding="utf-8", errors="ignore"))
    start = code.index("def close_tab")
    end = code.index("def ", start + 1)
    body = code[start:end]
    assert "update_tab_indices" in body, (
        "close_tab must call the tab manager's update_tab_indices() after removeTab()"
    )
    assert 'getattr(widget, "tab_manager"' in body or "getattr(widget, 'tab_manager'" in body
