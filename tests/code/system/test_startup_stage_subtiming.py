"""Guard test for the finer startup instrumentation (P1.4 measurement step).

`add_AIPacs_tab` (~2.6 s of the ~2.9 s startup freeze) was a black box beyond the existing
`home_widget` / `settings_widget` stages. This adds telemetry-only sub-stage markers inside
ControlPanelWindow.setupUi (`setupUi_pre_home`, `setupUi_post_home`, `setupUi_apply_theme`) so the
remaining ~1.3 s can be attributed on the source build before any (risky) startup change.

Pure logging — no behaviour change. Source-pin guard (no PySide6/QApplication needed).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AIPACS_UI = REPO / "PacsClient" / "pacs" / "workstation_ui" / "AIPacs_ui.py"


def _src() -> str:
    return AIPACS_UI.read_text(encoding="utf-8", errors="ignore")


def test_new_substage_markers_present():
    s = _src()
    for stage in ("setupUi_pre_home", "setupUi_post_home", "setupUi_apply_theme"):
        assert f"stage={stage} ms=" in s, f"missing STARTUP_STAGE {stage}"


def test_substage_timers_defined_before_use():
    s = _src()
    # each timer is assigned before it is referenced in its log line
    for var in ("_t_setupui_pre", "_t_setupui_post", "_t_setupui_theme"):
        assert f"{var} = time.perf_counter()" in s
        assert s.index(f"{var} = time.perf_counter()") < s.index(f"(time.perf_counter() - {var})")


def test_pre_existing_stages_still_present():
    s = _src()
    # the fix must not remove the existing attribution
    assert "stage=home_widget ms=" in s
    assert "stage=settings_widget ms=" in s


def test_apply_theme_call_preserved():
    s = _src()
    # the theme apply is only *bracketed* by timing, not removed/reordered away
    assert "self.apply_theme(self._active_theme)" in s
