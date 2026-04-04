"""
Tab lifecycle service for the Home panel.

Manages creation, lookup, activation, and cleanup of patient/viewer tabs
in the main QTabWidget.  Extracted from HomePanelWidget to keep UI code
focused on presentation, following the **Service Layer** pattern.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QTabWidget


class HomeTabService:
    """Manages the patient-tab and utility-tab lifecycle.

    Parameters
    ----------
    tab_widget : QTabWidget
        The main application tab widget.
    custom_tab_manager : object | None
        Optional ``CustomTabManager`` used for title bar integration.
    """

    def __init__(self, tab_widget: QTabWidget, custom_tab_manager=None):
        self.tab_widget = tab_widget
        self.custom_tab_manager = custom_tab_manager
        # study_uid → widget fast-lookup cache
        self._tab_cache: dict[str, object] = {}
        # study UIDs currently being opened (re-entrancy guard)
        self.opening_studies: set[str] = set()

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def find_widget_by_study_uid(self, study_uid: str) -> Optional[object]:
        """Return the widget for *study_uid* if it is still alive, else None."""
        # 1. Cache hit
        cached = self._tab_cache.get(study_uid)
        if cached is not None:
            if self._is_alive(cached):
                return cached
            else:
                self._tab_cache.pop(study_uid, None)

        # 2. Linear scan (fallback)
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if getattr(w, "study_uid", None) == study_uid and self._is_alive(w):
                self._tab_cache[study_uid] = w
                return w
        return None

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate_tab(self, widget_or_uid) -> bool:
        """Bring an existing tab to the front. Returns True on success."""
        widget = widget_or_uid
        if isinstance(widget_or_uid, str):
            widget = self.find_widget_by_study_uid(widget_or_uid)
        if widget is None:
            return False

        idx = self.tab_widget.indexOf(widget)
        if idx == -1:
            return False

        if self.custom_tab_manager:
            try:
                self.custom_tab_manager.set_tab_active(idx)
            except Exception:
                self.tab_widget.setCurrentIndex(idx)
        else:
            self.tab_widget.setCurrentIndex(idx)
        return True

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, study_uid: str, widget) -> None:
        """Add a newly created widget to the cache."""
        self._tab_cache[study_uid] = widget

    def unregister(self, study_uid: str) -> None:
        """Remove a widget from the cache (e.g. on tab close)."""
        self._tab_cache.pop(study_uid, None)

    # ------------------------------------------------------------------
    # Tab close / cleanup
    # ------------------------------------------------------------------

    def close_tab(self, index: int) -> None:
        """Safely close a tab at *index* and clean up references."""
        widget = self.tab_widget.widget(index)
        if widget is None:
            return

        study_uid = getattr(widget, "study_uid", None)
        if study_uid:
            self._tab_cache.pop(study_uid, None)
            self.opening_studies.discard(study_uid)

        self.tab_widget.removeTab(index)
        widget.deleteLater()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_alive(widget) -> bool:
        """Return True if the Qt C++ object behind *widget* still exists."""
        try:
            import sip
            return not sip.isdeleted(widget)
        except ImportError:
            pass
        try:
            _ = widget.isVisible()
            return True
        except RuntimeError:
            return False
