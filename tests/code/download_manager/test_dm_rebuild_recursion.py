"""DM table rebuild storm + priority-combo recursion tests (G7 / G8).

These tests document and protect against the silent main-thread blocker
identified on 2026-04-29:

  ``_clear_details_panel`` mutates ``priority_combo`` without
  ``blockSignals(True)``. The subsequent ``currentTextChanged`` signal
  triggers ``_on_priority_changed`` MID-``_refresh_table_order``, which
  (a) calls ``_refresh_table_order`` recursively (rebuild-storm) and
  (b) corrupts the study's priority from CRITICAL → NORMAL via
  ``state_store.update(priority=NORMAL)``.

Test layers
-----------

L1 — Static contract tests
    Inspect ``modules/download_manager/ui/widget/_dm_details.py`` source.
    Pre-fix: line 233 has ``priority_combo.setCurrentText("Normal")``
    with NO ``blockSignals`` wrapper. Post-fix (G8.1): every programmatic
    write to ``priority_combo`` is wrapped in ``blockSignals(True/False)``.

L2 — Live QComboBox signal tests
    Use a real ``QComboBox`` connected to a stub ``_on_priority_changed``.
    Verify Qt's signal dispatch matches the production failure mode and
    the fix's behavior.

L3 — Coordinator/state-store integration
    Wire ``SeriesIntentCoordinator.refresh_table_order`` to a callback
    that simulates the production rebuild (clears details → ghost combo
    signal → ``state_store.update(priority=NORMAL)``). Verify that, with
    the bug, drag-drop's CRITICAL promotion is silently demoted to
    NORMAL by the time the coordinator method returns.

L4 — Re-entrancy guard contract (G8.2 forward-looking)
    Verify ``_refresh_table_order`` never recurses, regardless of
    upstream signal-blocking discipline.

Plan reference: ``docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md``
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest


# ── ensure project root on path ─────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


from modules.download_manager.coordinator.series_intent_coordinator import (
    SeriesIntentCoordinator,
)
from modules.download_manager.core.enums import DownloadPriority, DownloadStatus
from modules.download_manager.core.models import DownloadTask
from modules.download_manager.state.state_store import DownloadStateStore
from modules.download_manager.ui.widget import _dm_details


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────


def _read_dm_details_source() -> str:
    """Return the full canonical source of `_dm_details.py`."""
    return Path(_dm_details.__file__).read_text(encoding="utf-8")


def _clear_details_panel_source() -> str:
    """Return only the `_clear_details_panel` method body."""
    src = _read_dm_details_source()
    m = re.search(
        r"def _clear_details_panel\(self\):.*?(?=\n    def |\nclass )",
        src,
        re.DOTALL,
    )
    assert m is not None, "_clear_details_panel not found in _dm_details.py"
    return m.group(0)


def _refresh_table_order_source() -> str:
    src = _read_dm_details_source()
    m = re.search(
        r"def _refresh_table_order\(self\):.*?(?=\n    def |\nclass )",
        src,
        re.DOTALL,
    )
    assert m is not None, "_refresh_table_order not found in _dm_details.py"
    return m.group(0)


def _make_task(study_uid: str = "study-rebuild") -> DownloadTask:
    return DownloadTask(
        study_uid=study_uid,
        patient_id="p1",
        patient_name="Patient One",
        study_date="2026-04-29",
        study_time="08:30:00",
        modality="CT",
        description="Rebuild Test",
        series_list=[],
        priority=DownloadPriority.HIGH,
        output_dir=Path("."),
    )


# ────────────────────────────────────────────────────────────────────────────
# L1 — Static contract tests
# ────────────────────────────────────────────────────────────────────────────


class TestStaticContract:
    """Inspect the source code to enforce the blockSignals discipline."""

    def test_clear_details_panel_wraps_priority_combo_in_blockSignals(self):
        """G8.1 contract: every programmatic write to priority_combo from
        _clear_details_panel must be guarded by blockSignals(True/False).

        FAILS pre-fix (line 233 is unguarded). PASSES post-fix.
        """
        body = _clear_details_panel_source()

        if "priority_combo.setCurrentText" not in body:
            pytest.skip(
                "_clear_details_panel no longer mutates priority_combo — bug class removed"
            )

        # Find every setCurrentText call inside _clear_details_panel and
        # verify each is bracketed by blockSignals(True) before and
        # blockSignals(False) after.
        lines = body.splitlines()
        guarded = 0
        unguarded = 0
        for i, line in enumerate(lines):
            if "priority_combo.setCurrentText" not in line:
                continue
            window_before = "\n".join(lines[max(0, i - 4): i])
            window_after = "\n".join(lines[i + 1: i + 5])
            has_block = (
                "priority_combo.blockSignals(True)" in window_before
                and "priority_combo.blockSignals(False)" in window_after
            )
            if has_block:
                guarded += 1
            else:
                unguarded += 1
        assert unguarded == 0, (
            f"_clear_details_panel has {unguarded} unguarded priority_combo "
            "write(s) — must wrap in blockSignals(True/False). See "
            "docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md G8.1."
        )
        assert guarded >= 1, "expected at least one guarded write to remain"

    def test_refresh_table_order_has_reentrancy_guard(self):
        """G8.2 contract: _refresh_table_order must short-circuit on
        recursive entry.

        FAILS pre-fix. PASSES post-fix.
        """
        body = _refresh_table_order_source()
        # The guard pattern uses `_refresh_table_order_in_progress` flag
        # (or equivalent name with `in_progress` substring).
        has_guard = (
            "_refresh_table_order_in_progress" in body
            or "_dm_rebuild_depth" in body
        )
        assert has_guard, (
            "_refresh_table_order has no re-entrancy guard. Add a "
            "_refresh_table_order_in_progress flag at the top of the "
            "method (G8.2). See "
            "docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md."
        )


# ────────────────────────────────────────────────────────────────────────────
# L2 — Live QComboBox signal tests (require QApplication)
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qt_app():
    """Module-scoped headless QApplication."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(["pytest", "-platform", "offscreen"])
    return app


class TestLiveCombo:
    """Drive a real QComboBox to verify signal propagation matches our model."""

    def _make_combo(self, qt_app):
        from PySide6.QtWidgets import QComboBox

        combo = QComboBox()
        combo.addItems(["Critical", "High", "Normal", "Low"])
        combo.setCurrentText("Critical")
        return combo

    def test_setCurrentText_without_blockSignals_fires_slot(self, qt_app):
        """Reproduce the bug: an unguarded setCurrentText fires the slot."""
        combo = self._make_combo(qt_app)
        emissions = []

        def on_changed(text: str):
            emissions.append(text)

        combo.currentTextChanged.connect(on_changed)

        # Production bug at _dm_details.py:233 — no blockSignals wrapper.
        combo.setCurrentText("Normal")

        assert emissions == ["Normal"], (
            "QComboBox.setCurrentText fires currentTextChanged when not "
            "blocked. This is the mechanism that drives the rebuild storm."
        )

    def test_setCurrentText_with_blockSignals_does_not_fire_slot(self, qt_app):
        """Verify the fix: blockSignals(True/False) suppresses the slot."""
        combo = self._make_combo(qt_app)
        emissions = []

        combo.currentTextChanged.connect(lambda t: emissions.append(t))

        # G8.1 fix pattern.
        combo.blockSignals(True)
        try:
            combo.setCurrentText("Normal")
        finally:
            combo.blockSignals(False)

        assert emissions == [], (
            "Once blockSignals(True/False) is applied, no programmatic "
            "write should fire the slot."
        )


# ────────────────────────────────────────────────────────────────────────────
# L3 — Coordinator / state-store integration test
# ────────────────────────────────────────────────────────────────────────────


class _RuleEngineStub:
    def evaluate_preemption(self, _task):
        return None


class _PoolFreeStub:
    max_workers = 3
    active_workers: dict = {}

    def can_add_worker(self):
        return True


class TestCoordinatorPriorityCorruption:
    """End-to-end: drag-drop must end with priority=CRITICAL, not NORMAL."""

    def _build_coordinator(self, *, refresh_callback):
        store = DownloadStateStore()
        task = _make_task()
        store.create(task)
        # Patient was just opened → HIGH (per the production flow).
        store.update(task.study_uid, priority=DownloadPriority.HIGH)

        tasks = {task.study_uid: task}

        coord = SeriesIntentCoordinator(
            state_store=store,
            rule_engine=_RuleEngineStub(),
            worker_pool=_PoolFreeStub(),
            tasks_ref=tasks,
            pause_downloads_for_preemption=lambda _uids: None,
            start_download_worker=lambda _uid: True,
            start_next_pending=lambda: None,
            refresh_table_order=refresh_callback,
            check_auto_resume=lambda: None,
            defer_call=lambda _ms, _cb: None,
        )
        return coord, store, task

    def test_drag_drop_critical_request_preserves_priority(self):
        """Drag-drop sets CRITICAL and the rebuild callback must NOT
        be allowed to demote it back to NORMAL.

        With the bug, _refresh_table_order indirectly triggers
        state_store.update(priority=NORMAL) via the ghost combo
        signal. This test simulates that simultaneously by having the
        refresh callback do exactly what the production rebuild does
        with the unguarded combo write.

        FAILS pre-fix (priority becomes NORMAL).
        PASSES post-fix (the simulated ghost signal is suppressed —
        callback no longer demotes the study).
        """
        # The simulated rebuild callback represents what production does
        # IF the bug is present: clear details → unguarded combo →
        # ghost on_priority_changed slot → state_store.update(NORMAL).
        # We toggle this via a probe so the test works pre-fix AND
        # post-fix.
        ghost_signal_active = {"on": _ghost_signal_present_in_production()}

        def refresh_table_order():
            if ghost_signal_active["on"]:
                store.update(task.study_uid, priority=DownloadPriority.NORMAL)

        coord, store, task = self._build_coordinator(
            refresh_callback=refresh_table_order
        )

        ok = coord.request_critical_series(task.study_uid, "1")
        assert ok is True

        final = store.get(task.study_uid)
        assert final.priority == DownloadPriority.CRITICAL, (
            f"Drag-drop priority CORRUPTION detected: study ended at "
            f"{final.priority}, expected CRITICAL. Root cause: "
            f"_clear_details_panel writes priority_combo without "
            f"blockSignals — see "
            f"docs/plans/performance/DM_TABLE_REBUILD_STORM_2026-04-29.md."
        )


# ────────────────────────────────────────────────────────────────────────────
# Helper to detect whether the production `_clear_details_panel` still has
# the unguarded write. Drives the test fixture to mirror the live bug.
# ────────────────────────────────────────────────────────────────────────────


def _ghost_signal_present_in_production() -> bool:
    """True iff `_clear_details_panel` still writes priority_combo
    unguarded (i.e. pre-G8.1)."""
    body = _clear_details_panel_source()
    if "priority_combo.setCurrentText" not in body:
        return False
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if "priority_combo.setCurrentText" not in line:
            continue
        window_before = "\n".join(lines[max(0, i - 4): i])
        window_after = "\n".join(lines[i + 1: i + 5])
        if not (
            "priority_combo.blockSignals(True)" in window_before
            and "priority_combo.blockSignals(False)" in window_after
        ):
            return True
    return False


# ────────────────────────────────────────────────────────────────────────────
# L4 — Re-entrancy guard contract (G8.2)
# ────────────────────────────────────────────────────────────────────────────


class TestReentrancyGuardContract:
    """Once `_refresh_table_order_in_progress` flag exists, recursive
    calls must be no-ops."""

    def test_refresh_table_order_recursion_short_circuits(self):
        """Pre-fix: this test is SKIPPED because the guard does not
        exist yet. Post-fix: it asserts the guard short-circuits."""
        body = _refresh_table_order_source()
        if "_refresh_table_order_in_progress" not in body:
            pytest.skip("Re-entrancy guard not yet shipped (G8.2 pending).")

        # When the guard is in place, the body must check the flag
        # BEFORE any expensive work (e.g. setRowCount).
        m = re.search(
            r"_refresh_table_order_in_progress.*?setRowCount",
            body,
            re.DOTALL,
        )
        assert m is not None, (
            "_refresh_table_order_in_progress check must precede the "
            "table-clearing call (setRowCount) — otherwise the guard "
            "does not protect the expensive rebuild path."
        )


# ────────────────────────────────────────────────────────────────────────────
# L5 — Deleted-QComboBox resilience (regression 2026-04-30)
#
# The G8.1 fix added `priority_combo.blockSignals(True)` before
# `setCurrentText("Normal")`. In production we then observed a storm of
# `RuntimeError: Internal C++ object (PySide6.QtWidgets.QComboBox)
# already deleted` originating from line 238. Root cause: the Python
# wrapper outlives the C++ widget (e.g. when the details panel is
# being rebuilt mid-`_refresh_table_order`); a truthy
# `if self.priority_combo` check does NOT detect this. Each crash
# aborted `_select_study_row`, leaving the table in an inconsistent
# state and amplifying the rebuild storm.
# ────────────────────────────────────────────────────────────────────────────


class TestDeletedComboResilience:
    """`_clear_details_panel` must tolerate a sip-deleted priority_combo."""

    def test_clear_details_panel_source_handles_runtime_error(self):
        """Static contract: the priority_combo block must be wrapped in
        a `try/except RuntimeError` so a deleted C++ object cannot
        propagate up and abort `_select_study_row`."""
        body = _clear_details_panel_source()
        if "priority_combo.setCurrentText" not in body:
            pytest.skip("priority_combo write removed — bug class gone")

        # Find the line with setCurrentText and verify a RuntimeError
        # handler appears within ~12 lines after the blockSignals(False).
        lines = body.splitlines()
        protected = False
        for i, line in enumerate(lines):
            if "priority_combo.setCurrentText" not in line:
                continue
            window = "\n".join(lines[max(0, i - 6): i + 12])
            if (
                "blockSignals(True)" in window
                and "blockSignals(False)" in window
                and re.search(r"except\s+RuntimeError", window)
            ):
                protected = True
                break
        assert protected, (
            "priority_combo write in _clear_details_panel must be "
            "wrapped in `try: ... except RuntimeError: ...` to "
            "tolerate deleted C++ widgets. Live regression observed "
            "2026-04-30 — see download_diagnostics.log near 00:53:50."
        )

    def test_live_deleted_combo_does_not_raise(self, qt_app):
        """L2-style live test: simulate the production failure mode.

        Build a minimal stub mirroring the relevant subset of
        `_DmDetailsMixin` state, point `priority_combo` at a real
        QComboBox, delete the underlying C++ object, then invoke the
        real `_clear_details_panel`. With the fix, this must NOT raise.
        """
        from PySide6.QtWidgets import QComboBox
        import shiboken6

        from modules.download_manager.ui.widget._dm_details import _DMDetailsMixin

        class _Stub:
            # All optional widgets are None to skip those branches.
            patient_label = None
            patient_name_label = None
            patient_id_label = None
            url_label = None
            study_desc_label = None
            study_date_label = None
            modality_label = None
            size_label = None
            progress_bar = None
            progress_label = None
            speed_label = None
            eta_label = None
            study_uid_label = None
            series_count_label = None
            study_size_label = None

            def _reset_reception_fields(self, status_text: str = "-") -> None:
                pass

        stub = _Stub()
        stub.priority_combo = QComboBox()
        stub.priority_combo.addItems(["Low", "Normal", "High", "Critical"])

        # Force-delete the C++ object — the Python wrapper survives.
        shiboken6.delete(stub.priority_combo)
        assert not shiboken6.isValid(stub.priority_combo)

        # Pre-fix this raises RuntimeError; post-fix it must swallow it.
        try:
            _DMDetailsMixin._clear_details_panel(stub)
        except RuntimeError as exc:
            pytest.fail(
                f"_clear_details_panel raised RuntimeError on deleted "
                f"priority_combo: {exc}. Wrap the priority_combo block "
                f"in try/except RuntimeError."
            )
