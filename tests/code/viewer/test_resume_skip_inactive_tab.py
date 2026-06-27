"""Guard: multi-patient resume-churn fix — skip disk-ready resume on an INACTIVE tab (2026-06-27).

Live evidence (Mehr, 3 patients downloading concurrently): a BACKGROUND patient tab's series
finished downloading, and its disk-ready resume watchdog fired SIX `change_series_on_viewer`
reloads in ~12s (`ViewportLoadResumedFromDisk` every ~2s, `visible` stayed 0), because
`_load_single_series_on_demand` DEFERS an inactive-tab load
(`if not self._tab_active ... return False` -> "Deferred load_series_on_demand until tab
activation"). The resume therefore can never display anything while the tab is inactive — it just
re-arms `_awaiting_series_number` and the watchdog reloads again. That background churn stole
main-thread cycles from the ACTIVE tab the user was watching => the "growth/sidebar not smooth"
jank in the multi-patient scenario.

Fix (flag `AIPACS_RESUME_SKIP_INACTIVE_TAB` default-on; `=0` = byte-identical legacy churn):
`_maybe_resume_awaiting_from_disk` returns early when the tab is inactive AND no interactive load
is in progress. The series loads when its tab is activated; the ACTIVE tab and explicit
interactive loads are unaffected. Defaults (`_tab_active` missing -> True, i.e. "treat as active,
don't skip") keep the legacy behaviour when state is unknown — the guard only skips when it KNOWS
the tab is inactive.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_CANON = (
    Path(__file__).resolve().parents[3]
    / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_progressive.py"
)


def _src() -> str:
    return _CANON.read_text(encoding="utf-8")


def test_flag_defined_after_os_import_default_on():
    s = _src()
    assert s.index("import os as _os") < s.index("_RESUME_SKIP_INACTIVE_TAB ="), (
        "_RESUME_SKIP_INACTIVE_TAB defined before `import os as _os` -> NameError at import."
    )
    assert ('_RESUME_SKIP_INACTIVE_TAB = (_os.getenv("AIPACS_RESUME_SKIP_INACTIVE_TAB", "1") '
            'or "1").strip() != "0"') in s


def test_guard_is_inside_resume_and_returns_early():
    s = _src()
    fn = s[s.index("def _maybe_resume_awaiting_from_disk("):]
    head = fn[:2600]
    assert "_RESUME_SKIP_INACTIVE_TAB" in head, "resume must consult the inactive-tab guard"
    # the guard must run BEFORE the per-episode reset / folder resolution work
    assert head.index("_RESUME_SKIP_INACTIVE_TAB") < head.index("_disk_ready_resume_key"), (
        "the inactive-tab guard must short-circuit BEFORE the resume work"
    )


def test_guard_checks_tab_active_and_interactive_with_safe_defaults():
    s = _src()
    fn = s[s.index("def _maybe_resume_awaiting_from_disk("):]
    head = fn[:2600]
    # active tab / interactive loads are NOT skipped; missing attrs default to "active"
    assert 'getattr(self, "_tab_active", True)' in head
    assert 'getattr(self, "_interactive_load_in_progress", False)' in head
    assert "return False" in head


def test_load_path_still_defers_inactive_tab():
    """The fix relies on the load actually deferring an inactive-tab load — pin that contract
    so a future change there doesn't silently make the skip wrong."""
    load_src = (_CANON.parent / "_vc_load.py").read_text(encoding="utf-8")
    assert "not self._tab_active and not self._interactive_load_in_progress" in load_src
