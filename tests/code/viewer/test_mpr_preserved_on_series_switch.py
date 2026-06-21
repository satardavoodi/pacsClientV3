"""Guard: switching a series into a NON-active viewport must not tear down the
active viewport's MPR.

Confirmed root cause (2026-06-21 logs): a series dropped onto viewport 0 (the
drop target) was switched via `_perform_series_switch_optimized`, which then
called `turn_off_all_tools()`. That call operates on the SELECTED viewport —
viewer 1, which hosted MPR — so `check_and_deactivate_tools` closed viewer 1's
MPR (`[MPR-TEARDOWN] … selected is MPR host viewer=1`) even though the drop only
targeted viewer 0. The earlier `set_viewer_to_main_viewer` guard never engaged
because the drop did not change the active selection.

Fix: every series-switch tool reset now routes through
`ToolbarManager.turn_off_all_tools_after_switch(target_widget)`, which only runs
the global reset when the switch target IS the active/selected viewport. A switch
into a different cell leaves the active viewport (and its MPR) untouched. Gated by
`AIPACS_SERIES_SWITCH_TOOL_RESET_TARGET_ONLY` (default on).

The method is exec'd from source against stubs (no QApplication / VTK needed).
"""
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PUI = _ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
_TB = _PUI / "patient_toolbar" / "toolbar_manager.py"


def _load_after_switch_class():
    src = _TB.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    def turn_off_all_tools_after_switch(self, target_widget=None):")
    end = src.index("\n    def ", start + 10)
    block = textwrap.dedent(src[start:end])
    ns = {}
    exec("class _C:\n" + textwrap.indent(block, "    "), ns)  # noqa: S102
    return ns["_C"]


_Cls = _load_after_switch_class()


class _Harness(_Cls):
    def __init__(self, selected):
        self.calls = 0

        class _PW:
            pass

        self.patient_widget = _PW()
        self.patient_widget.selected_widget = selected

    def turn_off_all_tools(self):   # the legacy global reset (acts on selected)
        self.calls += 1


def test_switch_into_non_active_viewport_preserves(monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_SWITCH_TOOL_RESET_TARGET_ONLY", raising=False)
    mpr_host = object()      # viewer 1 = active MPR host
    drop_target = object()   # viewer 0 = drop target
    h = _Harness(selected=mpr_host)
    h.turn_off_all_tools_after_switch(drop_target)
    # global reset (which would close the active viewport's MPR) must be skipped
    assert h.calls == 0


def test_switch_into_active_viewport_still_resets(monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_SWITCH_TOOL_RESET_TARGET_ONLY", raising=False)
    active = object()
    h = _Harness(selected=active)
    h.turn_off_all_tools_after_switch(active)   # target IS the active viewport
    assert h.calls == 1


def test_unknown_target_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_SWITCH_TOOL_RESET_TARGET_ONLY", raising=False)
    h = _Harness(selected=object())
    h.turn_off_all_tools_after_switch(None)     # no target known → legacy reset
    assert h.calls == 1


def test_no_active_selection_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv("AIPACS_SERIES_SWITCH_TOOL_RESET_TARGET_ONLY", raising=False)
    h = _Harness(selected=None)                 # nothing active to protect
    h.turn_off_all_tools_after_switch(object())
    assert h.calls == 1


def test_flag_off_restores_legacy_always_reset(monkeypatch):
    monkeypatch.setenv("AIPACS_SERIES_SWITCH_TOOL_RESET_TARGET_ONLY", "0")
    h = _Harness(selected=object())
    h.turn_off_all_tools_after_switch(object())  # different target, but flag off
    assert h.calls == 1


# ── source pins: every series-switch reset routes through the scoped helper ───
def test_all_series_switch_sites_use_scoped_helper():
    assert "def turn_off_all_tools_after_switch" in _TB.read_text(encoding="utf-8", errors="ignore")
    for rel in (
        "_vc_switch.py",
        "_vc_warmup.py",
        Path("patient_widget_core") / "_pw_series.py",
    ):
        src = (_PUI / rel).read_text(encoding="utf-8", errors="ignore")
        assert "turn_off_all_tools_after_switch(" in src, rel
