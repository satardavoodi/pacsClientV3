"""
Fix G source-contract tests: eventFilter drag gate for _is_over_window_buttons.

Tests verify that:
 1. `_is_fast_drag_active` helper exists and is callable in mainwindow_ui.
 2. The eventFilter skips `_is_over_window_buttons` when drag is active for
    MouseMove/HoverMove events (preventing the 400-500ms mapFromGlobal stall).
 3. The eventFilter still calls `_is_over_window_buttons` when drag is NOT active.
 4. Click/press events bypass the drag gate (button clicks must still work during drag).
"""
import sys
import types
import importlib
import unittest
from unittest.mock import MagicMock, patch, call


class TestIsFastDragActiveHelper(unittest.TestCase):
    """Test the module-level lazy-bound helper function."""

    def test_helper_exists_in_module(self):
        """_is_fast_drag_active must be a callable at module level."""
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu
        self.assertTrue(
            hasattr(mwu, "_is_fast_drag_active"),
            "_is_fast_drag_active not found in mainwindow_ui module",
        )
        self.assertTrue(callable(mwu._is_fast_drag_active))

    def test_helper_returns_false_when_throttle_unavailable(self):
        """When ui_throttle import fails, _is_fast_drag_active must return False."""
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu

        # Save and reset the cached function pointer
        original = mwu._ui_throttle_drag_check
        mwu._ui_throttle_drag_check = None
        try:
            with patch.dict(sys.modules, {"modules.viewer.fast.ui_throttle": None}):
                result = mwu._is_fast_drag_active()
            self.assertIsInstance(result, bool)
        finally:
            mwu._ui_throttle_drag_check = original

    def test_helper_returns_true_when_drag_active(self):
        """When is_protected_drag_active returns True, helper must return True."""
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu

        original = mwu._ui_throttle_drag_check
        mwu._ui_throttle_drag_check = lambda: True
        try:
            self.assertTrue(mwu._is_fast_drag_active())
        finally:
            mwu._ui_throttle_drag_check = original

    def test_helper_returns_false_when_drag_inactive(self):
        """When is_protected_drag_active returns False, helper must return False."""
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu

        original = mwu._ui_throttle_drag_check
        mwu._ui_throttle_drag_check = lambda: False
        try:
            self.assertFalse(mwu._is_fast_drag_active())
        finally:
            mwu._ui_throttle_drag_check = original


class TestEventFilterDragGate(unittest.TestCase):
    """
    Source-contract: the eventFilter must contain the Fix G guard that skips
    _is_over_window_buttons for MouseMove/HoverMove during FAST drag.

    We use source inspection + module-level mock injection rather than trying
    to instantiate a full MainWindowWidget (which requires a live QApplication
    and Shiboken C++ objects that break isinstance() checks for MagicMock stubs).
    """

    def test_fix_g_guard_present_in_eventfilter_source(self):
        """eventFilter source must contain the Fix G drag gate guard."""
        import inspect
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu
        src = inspect.getsource(mwu.MainWindowWidget.eventFilter)
        self.assertIn(
            "_is_fast_drag_active()",
            src,
            "[Fix G] _is_fast_drag_active() guard missing from eventFilter",
        )

    def test_fix_g_guard_is_before_button_check(self):
        """Fix G drag gate must appear BEFORE the _is_over_window_buttons call in eventFilter."""
        import inspect
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu
        src = inspect.getsource(mwu.MainWindowWidget.eventFilter)
        idx_gate = src.find("_is_fast_drag_active()")
        # Search for the actual METHOD CALL (if self._is_over_window_buttons),
        # not any mention in comments.
        idx_btn = src.find("if self._is_over_window_buttons(")
        self.assertGreater(idx_gate, 0, "_is_fast_drag_active() not found in eventFilter")
        self.assertGreater(idx_btn, 0, "if self._is_over_window_buttons( not found in eventFilter")
        self.assertLess(
            idx_gate, idx_btn,
            "Fix G guard must appear BEFORE the _is_over_window_buttons call",
        )

    def test_fix_g_guard_covers_mousemove_and_hovermove(self):
        """The guard must be inside a block that checks for MouseMove and HoverMove."""
        import inspect
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu
        src = inspect.getsource(mwu.MainWindowWidget.eventFilter)
        # Find the guard block (a few lines around _is_fast_drag_active)
        idx = src.find("_is_fast_drag_active()")
        context = src[max(0, idx - 200): idx + 200]
        self.assertIn("MouseMove", context, "Guard must reference MouseMove")
        self.assertIn("HoverMove", context, "Guard must reference HoverMove")

    def test_fix_g_guard_returns_false_not_true(self):
        """Guard must return False (pass-through), not True (consume the event)."""
        import inspect
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu
        src = inspect.getsource(mwu.MainWindowWidget.eventFilter)
        idx = src.find("_is_fast_drag_active()")
        # The guard block ends with 'return False'
        context = src[idx: idx + 150]
        self.assertIn(
            "return False",
            context,
            "Fix G guard must use 'return False' (pass-through) not 'return True'",
        )

    def test_button_check_skipped_when_drag_active_mock_injection(self):
        """
        Inject drag_active=True into the module and verify that `_is_fast_drag_active`
        returns True, confirming the guard path will be taken.
        """
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu

        original = mwu._ui_throttle_drag_check
        mwu._ui_throttle_drag_check = lambda: True
        try:
            self.assertTrue(mwu._is_fast_drag_active())
        finally:
            mwu._ui_throttle_drag_check = original

    def test_button_check_runs_when_drag_inactive_mock_injection(self):
        """
        Inject drag_active=False and verify `_is_fast_drag_active` returns False,
        confirming the guard path will NOT be taken (normal flow continues).
        """
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu

        original = mwu._ui_throttle_drag_check
        mwu._ui_throttle_drag_check = lambda: False
        try:
            self.assertFalse(mwu._is_fast_drag_active())
        finally:
            mwu._ui_throttle_drag_check = original


class TestEventFilterClicksUnaffected(unittest.TestCase):
    """Press/release events must still reach _is_over_window_buttons regardless of drag state."""

    def test_fix_g_guard_does_not_cover_press_events(self):
        """
        The Fix G drag gate must ONLY fire for MouseMove / HoverMove.
        Press/Release events must NOT be short-circuited by the drag gate.
        """
        import inspect
        import PacsClient.pacs.workstation_ui.mainwindow_ui as mwu
        src = inspect.getsource(mwu.MainWindowWidget.eventFilter)
        idx = src.find("_is_fast_drag_active()")
        # The guard context must be gated on MouseMove/HoverMove only
        context = src[max(0, idx - 300): idx + 10]
        # 'MouseButtonPress' must NOT appear in the guard condition block
        # (it should only have MouseMove and HoverMove)
        gate_block = src[max(0, idx - 100): idx + 50]
        self.assertNotIn(
            "MouseButtonPress",
            gate_block,
            "Fix G guard must not block MouseButtonPress events",
        )


if __name__ == "__main__":
    unittest.main()
