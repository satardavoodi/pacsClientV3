"""Guard: non-terminal progressive-grow interaction STARVATION fix (2026-06-26).

Live evidence — patient 45743, previous study 30256, series 8 (multi-study offset/display
key ``2000008``): the FAST progressive-grow loop logged, across 11 consecutive ticks,
``[PROGRESSIVE_GROW_DEFERRED_INTERACTION] series=2000008 applied_count=0 pending_count=162
interaction_active=True terminal=False reason=nonterminal_hot`` — the series stayed stuck at
~50 of 162 slices because the user kept scrolling (interaction stayed "hot").

Root cause: in ``_flush_progressive_grow_impl`` the *terminal* grow path (F10) has a
force-after-N starvation guard (``_FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES``), but the
*non-terminal* interaction-hot path just deferred and ``continue``-d every tick with NO
equivalent — so sustained interaction starved it indefinitely.

Fix (flag ``AIPACS_PROGRESSIVE_HOT_FORCE`` default-on; ``=0`` → byte-identical legacy starve):
after ``_PROGRESSIVE_HOT_FORCE_AFTER`` (default 3) consecutive interaction-hot deferrals, force
ONE ``admit_batch``-capped grow that bypasses the cadence + ``_should_defer`` gates for that tick,
then reset the coalesced counter so it stays periodic (small + every K ticks → no drag stall).
The pure decision lives in ``_should_force_nonterminal_grow`` so it is unit-testable.

Plan / history: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md,
docs/reports/FIRST_IMAGE_TO_FULL_STACK_GROW_INVESTIGATION_2026-06-26.md.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_CANON = (
    Path(__file__).resolve().parents[3]
    / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_progressive.py"
)


def _src() -> str:
    return _CANON.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Functional — the pure decision helper
# --------------------------------------------------------------------------- #

@pytest.fixture()
def _mod():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as mod
    except Exception as exc:  # pragma: no cover - heavy import unavailable
        pytest.skip(f"_vc_progressive import unavailable: {exc}")
    return mod


def test_below_threshold_does_not_force(_mod, monkeypatch):
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_AFTER", 3)
    assert _mod._should_force_nonterminal_grow(0) is False
    assert _mod._should_force_nonterminal_grow(1) is False
    assert _mod._should_force_nonterminal_grow(2) is False


def test_at_or_above_threshold_forces(_mod, monkeypatch):
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_AFTER", 3)
    assert _mod._should_force_nonterminal_grow(3) is True   # the starving series finally grows
    assert _mod._should_force_nonterminal_grow(11) is True  # the live 45743/2000008 count


def test_kill_switch_disables_force(_mod, monkeypatch):
    """AIPACS_PROGRESSIVE_HOT_FORCE=0 → never forces → byte-identical legacy starve behaviour."""
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_ENABLED", False)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_AFTER", 3)
    assert _mod._should_force_nonterminal_grow(3) is False
    assert _mod._should_force_nonterminal_grow(9999) is False


def test_bad_input_is_safe(_mod, monkeypatch):
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_HOT_FORCE_AFTER", 3)
    assert _mod._should_force_nonterminal_grow(None) is False
    assert _mod._should_force_nonterminal_grow("nan") is False


def test_default_threshold_is_small_and_positive(_mod):
    """Default K must be a small positive int (periodic forward progress, tiny per-tick cost)."""
    assert isinstance(_mod._PROGRESSIVE_HOT_FORCE_AFTER, int)
    assert 1 <= _mod._PROGRESSIVE_HOT_FORCE_AFTER <= 10
    assert _mod._PROGRESSIVE_HOT_FORCE_ENABLED is True   # default-on


# --------------------------------------------------------------------------- #
# Source-pins — the hot-path wiring (no heavy import needed)
# --------------------------------------------------------------------------- #

def test_flag_and_helper_defined():
    s = _src()
    assert 'AIPACS_PROGRESSIVE_HOT_FORCE' in s
    assert 'AIPACS_PROGRESSIVE_HOT_FORCE_AFTER' in s
    assert "def _should_force_nonterminal_grow(" in s


def test_flag_defined_after_os_import():
    """The flag uses _os.getenv, so it MUST be defined after `import os as _os` or the
    module raises NameError at load time (py_compile would not catch it)."""
    s = _src()
    assert s.index("import os as _os") < s.index("_PROGRESSIVE_HOT_FORCE_ENABLED ="), (
        "_PROGRESSIVE_HOT_FORCE_ENABLED is defined before `import os as _os` → "
        "NameError at module import."
    )


def _hot_region(s: str) -> str:
    """The non-terminal interaction-hot defer+force region: from the hot-block guard up to
    the cadence gate (which is the first ``not _forced_progress`` line)."""
    start = s.index("if not is_terminal and interaction_hot:")
    end = s.index("if not is_terminal and not _forced_progress:", start)
    return s[start:end]


def test_nonterminal_block_routes_through_helper():
    region = _hot_region(_src())
    assert "_should_force_nonterminal_grow(_coalesced_now)" in region, (
        "non-terminal interaction-hot block must consult the starvation-guard helper"
    )


def test_force_path_caps_resets_and_marks_forced():
    """The forced grow must be SMALL (admit_batch-capped), periodic (counter reset), and
    flagged (_forced_progress) so the downstream gates are bypassed for exactly one tick."""
    region = _hot_region(_src())
    assert "_forced_progress = True" in region
    assert "coalesced_map[sn] = 0" in region                              # periodic, not every tick
    assert "min(int(pending), int(last_grow) + int(admit_batch))" in region  # capped batch
    assert "[PROGRESSIVE_GROW_FORCE_PROGRESS]" in region                  # observable in logs


def test_downstream_gates_bypassed_when_forced():
    """Both the cadence gate and the generic _should_defer gate must yield to a forced tick,
    else the force is silently undone and the series still starves."""
    s = _src()
    assert "if not is_terminal and not _forced_progress:" in s, (
        "cadence gate must be bypassed on a forced tick"
    )
    assert "if (not _forced_progress) and _should_defer_progressive_grow(terminal=is_terminal):" in s, (
        "_should_defer gate must be bypassed on a forced tick"
    )


def test_terminal_f10_guard_untouched():
    """The fix must NOT alter the pre-existing terminal (F10) force-after-budget guard."""
    s = _src()
    assert "_FAST_PROGRESSIVE_FINALIZE_DEFER_MAX_RETRIES" in s
    assert "if is_terminal and interaction_hot:" in s
