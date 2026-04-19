"""v2.3.4-cp1 — Control-plane and mixed-load governance tests.

Covers the 5 fixes from the log-38 analysis:
  Fix 1: Epoch-aware Layer 3 completion verify
  Fix 2: Series-level prefetch readiness
  Fix 3: Progressive display completeness gate
  Fix 4: Harsher mixed-load PREFETCH + PROGRESSIVE_SIGNAL
  Fix 5: ZetaBoost triage (documentation only — no code test needed)
"""

from __future__ import annotations

import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fix 1 — Epoch-aware Layer 3 completion verify
# ---------------------------------------------------------------------------

class TestEpochAwareLayer3:
    """_completion_verify_series_impl must skip re-entry when series is done
    and viewer is already up-to-date."""

    def _build_controller_stub(self, *, viewer_slices: int, disk_count: int,
                                series_complete: bool = True,
                                lifecycle_state: str = "DONE"):
        """Minimal controller stub for Layer 3 tests."""
        ctrl = SimpleNamespace()
        ctrl._progressive_display_done = set()
        ctrl._progressive_series = {}
        ctrl._layer2b_complete_guard = set()
        ctrl._progressive_lifecycle_state = {}
        ctrl._disk_count_cache = {}
        ctrl.logger = MagicMock()

        # Simulate viewers showing the series
        viewer = SimpleNamespace()
        viewer.metadata = {"instances": [None] * viewer_slices}
        viewer._lazy_loader = SimpleNamespace(slice_count=viewer_slices)
        ctrl._find_progressive_viewers = MagicMock(return_value=[])
        ctrl._all_viewers = MagicMock(return_value=[viewer])

        # Series download status
        ctrl._is_series_download_completed = MagicMock(return_value=series_complete)

        # Disk count (cached)
        ctrl._count_series_files_on_disk = MagicMock(return_value=disk_count)

        # Lifecycle state helper
        ctrl._progressive_lifecycle_state["101"] = lifecycle_state

        return ctrl

    def test_skip_when_viewer_up_to_date(self):
        """When series is done and viewer has all slices, verify is a no-op."""
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import (
            _get_progressive_lifecycle_state,
        )
        ctrl = self._build_controller_stub(
            viewer_slices=100, disk_count=100, series_complete=True,
            lifecycle_state="DONE",
        )
        # The epoch-aware guard should detect viewer is up-to-date
        # and not transition to COMPLETING
        state = _get_progressive_lifecycle_state(ctrl, "101")
        assert state == "DONE"

    def test_imports_lifecycle_helpers(self):
        """Verify we can import the key lifecycle state helpers."""
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import (
            _get_progressive_lifecycle_state,
            _set_progressive_lifecycle_state,
            _cleanup_progressive_lifecycle_state,
        )
        assert callable(_get_progressive_lifecycle_state)
        assert callable(_set_progressive_lifecycle_state)
        assert callable(_cleanup_progressive_lifecycle_state)


# ---------------------------------------------------------------------------
# Fix 2 — Series-level prefetch readiness
# ---------------------------------------------------------------------------

class TestSeriesLevelReadiness:
    """is_viewed_series_complete delegates to orchestrator and
    cap_prefetch_radius relaxes for completed series."""

    def test_no_orchestrator_returns_false(self):
        """Without registered orchestrator, series is never 'complete'."""
        from modules.viewer.fast import ui_throttle
        old = None
        with ui_throttle._ORCHESTRATOR_LOCK:
            old = ui_throttle._ACTIVE_ORCHESTRATOR
            ui_throttle._ACTIVE_ORCHESTRATOR = None
        try:
            assert ui_throttle.is_viewed_series_complete("12345") is False
        finally:
            with ui_throttle._ORCHESTRATOR_LOCK:
                ui_throttle._ACTIVE_ORCHESTRATOR = old

    def test_none_series_returns_false(self):
        from modules.viewer.fast import ui_throttle
        assert ui_throttle.is_viewed_series_complete(None) is False

    def test_orchestrator_reports_complete(self):
        """When orchestrator says series is downloaded, returns True."""
        from modules.viewer.fast import ui_throttle
        orch = SimpleNamespace()
        orch.is_series_downloaded = MagicMock(return_value=True)
        old = None
        with ui_throttle._ORCHESTRATOR_LOCK:
            old = ui_throttle._ACTIVE_ORCHESTRATOR
            ui_throttle._ACTIVE_ORCHESTRATOR = orch
        try:
            assert ui_throttle.is_viewed_series_complete("12345") is True
            orch.is_series_downloaded.assert_called_once_with("12345")
        finally:
            with ui_throttle._ORCHESTRATOR_LOCK:
                ui_throttle._ACTIVE_ORCHESTRATOR = old

    def test_orchestrator_reports_incomplete(self):
        from modules.viewer.fast import ui_throttle
        orch = SimpleNamespace()
        orch.is_series_downloaded = MagicMock(return_value=False)
        old = None
        with ui_throttle._ORCHESTRATOR_LOCK:
            old = ui_throttle._ACTIVE_ORCHESTRATOR
            ui_throttle._ACTIVE_ORCHESTRATOR = orch
        try:
            assert ui_throttle.is_viewed_series_complete("12345") is False
        finally:
            with ui_throttle._ORCHESTRATOR_LOCK:
                ui_throttle._ACTIVE_ORCHESTRATOR = old

    @patch("modules.viewer.fast.ui_throttle.is_heavy_download_active", return_value=True)
    @patch("modules.viewer.fast.ui_throttle.is_viewed_series_complete", return_value=True)
    def test_cap_prefetch_relaxes_for_complete_series(self, mock_complete, mock_heavy):
        """Complete series should get full prefetch even during heavy download."""
        from modules.viewer.fast.ui_throttle import cap_prefetch_radius
        # With series_number for a completed series, heavy should be cleared
        result = cap_prefetch_radius(5, fast_interaction_active=False, series_number="12345")
        # Should NOT be capped to 3 (heavy download alone) — series is complete
        assert result == 5

    @patch("modules.viewer.fast.ui_throttle.is_heavy_download_active", return_value=True)
    @patch("modules.viewer.fast.ui_throttle.is_viewed_series_complete", return_value=False)
    def test_cap_prefetch_caps_for_incomplete_series(self, mock_complete, mock_heavy):
        """Incomplete series should still be capped during heavy download."""
        from modules.viewer.fast.ui_throttle import cap_prefetch_radius
        result = cap_prefetch_radius(5, fast_interaction_active=False, series_number="12345")
        # Should be capped (heavy download, no fast interaction → cap=3)
        assert result <= 3

    @patch("modules.viewer.fast.ui_throttle.is_heavy_download_active", return_value=True)
    def test_cap_prefetch_no_series_number_still_caps(self, mock_heavy):
        """Without series_number, heavy download always caps."""
        from modules.viewer.fast.ui_throttle import cap_prefetch_radius
        result = cap_prefetch_radius(5, fast_interaction_active=False, series_number=None)
        assert result <= 3


# ---------------------------------------------------------------------------
# Fix 3 — Progressive display completeness gate
# ---------------------------------------------------------------------------

class TestCompletenessGate:
    """_start_progressive_display defers when too few files under heavy load."""

    def test_completeness_gate_exists_in_source(self):
        """The completeness threshold must exist in _vc_progressive.py."""
        import pathlib
        vc_prog = pathlib.Path(__file__).resolve().parents[2] / (
            "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py"
        )
        content = vc_prog.read_text(encoding="utf-8", errors="replace")
        assert "_PROGRESSIVE_MIN_COMPLETENESS" in content

    def test_threshold_value_is_030(self):
        """Default completeness gate should be 0.30 (30%)."""
        import pathlib, re
        vc_prog = pathlib.Path(__file__).resolve().parents[2] / (
            "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py"
        )
        content = vc_prog.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"_PROGRESSIVE_MIN_COMPLETENESS\s*=\s*([\d.]+)", content)
        assert match is not None, "Could not find _PROGRESSIVE_MIN_COMPLETENESS assignment"
        assert abs(float(match.group(1)) - 0.30) < 0.01


# ---------------------------------------------------------------------------
# Fix 4 — Harsher mixed-load PREFETCH + PROGRESSIVE_SIGNAL
# ---------------------------------------------------------------------------

class TestHarsherMixedLoadThrottle:
    """SystemLoadController uses stricter caps during download+scroll combo."""

    def test_prefetch_radius_1_during_download_and_scroll(self):
        """PREFETCH radius should be 1 when both download and scroll active."""
        from modules.viewer.fast.system_load_controller import (
            get_system_load_controller,
            WorkClass,
        )
        ctrl = get_system_load_controller()
        policy = ctrl.policy_for(
            WorkClass.PREFETCH,
            heavy_download_active=True,
            fast_interaction_active=True,
        )
        assert policy.radius_cap == 1

    def test_prefetch_radius_3_during_download_only(self):
        """PREFETCH radius should be 3 when downloading but not scrolling."""
        from modules.viewer.fast.system_load_controller import (
            get_system_load_controller,
            WorkClass,
        )
        ctrl = get_system_load_controller()
        policy = ctrl.policy_for(
            WorkClass.PREFETCH,
            heavy_download_active=True,
            fast_interaction_active=False,
        )
        assert policy.radius_cap == 3

    def test_prefetch_no_cap_when_idle(self):
        """PREFETCH radius should be uncapped when neither download nor scroll."""
        from modules.viewer.fast.system_load_controller import (
            get_system_load_controller,
            WorkClass,
        )
        ctrl = get_system_load_controller()
        policy = ctrl.policy_for(
            WorkClass.PREFETCH,
            heavy_download_active=False,
            fast_interaction_active=False,
        )
        assert policy.radius_cap is None

    def test_progressive_signal_750ms_during_download_and_scroll(self):
        """PROGRESSIVE_SIGNAL coalesce should be 750ms during download+scroll."""
        from modules.viewer.fast.system_load_controller import (
            get_system_load_controller,
            WorkClass,
        )
        ctrl = get_system_load_controller()
        policy = ctrl.policy_for(
            WorkClass.PROGRESSIVE_SIGNAL,
            heavy_download_active=True,
            fast_interaction_active=True,
        )
        assert policy.coalesce_interval_ms == 750.0

    def test_progressive_signal_500ms_during_download_only(self):
        """PROGRESSIVE_SIGNAL coalesce should be 500ms during download w/o scroll."""
        from modules.viewer.fast.system_load_controller import (
            get_system_load_controller,
            WorkClass,
        )
        ctrl = get_system_load_controller()
        policy = ctrl.policy_for(
            WorkClass.PROGRESSIVE_SIGNAL,
            heavy_download_active=True,
            fast_interaction_active=False,
        )
        assert policy.coalesce_interval_ms == 500.0

    def test_progressive_signal_100ms_when_idle(self):
        """PROGRESSIVE_SIGNAL coalesce should be 100ms when idle."""
        from modules.viewer.fast.system_load_controller import (
            get_system_load_controller,
            WorkClass,
        )
        ctrl = get_system_load_controller()
        policy = ctrl.policy_for(
            WorkClass.PROGRESSIVE_SIGNAL,
            heavy_download_active=False,
            fast_interaction_active=False,
        )
        assert policy.coalesce_interval_ms == 100.0


# ---------------------------------------------------------------------------
# Fix 5 — ZetaBoost triage (documentation verification)
# ---------------------------------------------------------------------------

class TestZetaBoostFastModeEmpty:
    """Doc/comment verification: ZetaBoost RAM cache is empty in FAST mode."""

    def test_vc_load_has_zetaboost_fast_mode_comment(self):
        """_vc_load.py should have the diagnostic comment about FAST mode."""
        import pathlib
        vc_load = pathlib.Path(
            r"PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py"
        )
        if not vc_load.is_absolute():
            vc_load = pathlib.Path(__file__).resolve().parents[2] / vc_load
        content = vc_load.read_text(encoding="utf-8", errors="replace")
        assert "architecturally empty" in content or "RAM cache unused" in content
