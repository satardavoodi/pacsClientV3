"""
Tab lifecycle service for the Home panel.

Manages creation, lookup, activation, and cleanup of patient/viewer tabs
in the main QTabWidget.  Extracted from HomePanelWidget to keep UI code
focused on presentation, following the **Service Layer** pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import asyncio
import logging
import weakref

from PySide6.QtCore import QObject, QTimer, Qt, Slot
from PySide6.QtWidgets import QTabWidget

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatientTabAdmission:
    """Result of the single tab-capacity admission authority."""

    status: str
    study_uid: str
    active_tabs: int = 0
    max_tabs: int = 0

    @property
    def admitted(self) -> bool:
        return self.status == "admitted"


class _PatientTabSignalRelay(QObject):
    """GUI-owned lifetime boundary for Home priority and download completion.

    External publishers do not capture the patient/Home owners. QObject parent
    destruction disconnects slots even when a tab is deleted without closeEvent.
    Explicit exit retires queued deliveries before viewer teardown begins.
    """

    def __init__(self, home, widget, study_uid, download_manager):
        super().__init__(widget)
        self._home_ref = weakref.ref(home)
        self._widget_ref = weakref.ref(widget)
        self._study_uid = study_uid
        self._disposed = False
        self._connections = []
        manager = getattr(widget, 'thumbnail_manager', None)
        if manager is not None:
            manager.set_current_study_uid(study_uid)
            self._connections.append(manager.priority_download_requested.connect(self.on_priority))
        self.connect_download_manager(download_manager)

    def connect_download_manager(self, download_manager):
        """Attach once during creation, after the existing lazy DM lookup."""
        if not self._disposed and self._study_uid and download_manager is not None:
            self._connections.append(download_manager.download_completed.connect(self.on_complete))

    def _live_widget(self):
        from shiboken6 import isValid

        widget = self._widget_ref()
        if (self._disposed or widget is None or not isValid(widget)
                or getattr(widget, '_pw_close_handled', False)):
            return None
        return widget

    @Slot(str, str)
    def on_priority(self, series_number, study_uid):
        from shiboken6 import isValid

        widget = self._live_widget()
        home = self._home_ref()
        if (widget is not None and home is not None
                and (not isinstance(home, QObject) or isValid(home))):
            # Preserve existing routing and owner-local keys; this is not the
            # later SeriesIntentCoordinator priority migration.
            home._handle_priority_download_from_thumbnail(series_number, study_uid, widget)

    @Slot(str)
    def on_complete(self, study_uid):
        widget = self._live_widget()
        if widget is not None and study_uid == self._study_uid:
            widget.refresh_after_download(study_uid)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        for connection in self._connections:
            QObject.disconnect(connection)
        self._connections.clear()
        widget = self._widget_ref()
        if widget is not None and getattr(widget, '_home_signal_relay', None) is self:
            widget._home_signal_relay = None
        self.deleteLater()


class _PendingHomeSeriesAction(QObject):
    """One GUI-owned, event-driven placement intent, bounded to one live tab.

    Metadata can arrive from a worker: queued QObject slots marshal consumption
    to the GUI thread. No polling, file scan, decoder or downloader lives here.
    """

    def __init__(self, service, widget, action):
        super().__init__(widget)
        self.service, self.widget, self.action = service, widget, action
        self.done = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        widget.series_metadata_ready.connect(self.attempt, Qt.QueuedConnection)
        widget.loading_complete.connect(self.attempt, Qt.QueuedConnection)
        service.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.timer.start(30000)

    @Slot()
    def attempt(self):
        if self.done:
            return
        tabs = self.service.tab_widget
        if tabs.indexOf(self.widget) < 0 or tabs.currentWidget() is not self.widget:
            self.cancel()
            return
        controller = getattr(self.widget, 'viewer_controller', None)
        if controller is not None and not getattr(controller, 'lst_nodes_viewer', None):
            return  # Initial layout readiness is signalled by loading_complete.
        key = self.action.resolve_display_key(
            dict(getattr(self.widget, '_server_series_info', {}) or {}),
            primary_study_uid=getattr(self.widget, 'study_uid', ''))
        if key is None:
            return
        self.cancel()
        self.widget.change_series_on_viewer(key)
        _logger.info('[HOME-SERIES-ACTION] result=placement_requested')

    @Slot(int)
    def on_tab_changed(self, index):
        if self.service.tab_widget.widget(index) is not self.widget:
            self.cancel()

    @Slot()
    def expire(self):
        _logger.warning('[HOME-SERIES-ACTION] result=metadata_timeout')
        self.cancel()

    def cancel(self):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        for signal, slot in (
            (self.widget.series_metadata_ready, self.attempt),
            (self.widget.loading_complete, self.attempt),
            (self.service.tab_widget.currentChanged, self.on_tab_changed),
        ):
            signal.disconnect(slot)
        if getattr(self.widget, '_home_series_action_pending', None) is self:
            self.widget._home_series_action_pending = None
        self.deleteLater()


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
        # Capacity reservations exist only until CustomTabManager registers the
        # widget. They prevent two nested/concurrent opens from both consuming
        # the final slot without double-counting an already-registered tab.
        self._patient_tab_reservations: set[str] = set()
        self._series_open_tasks = {}
        self._series_open_intents = {}

    @property
    def patient_tab_reservations(self) -> frozenset[str]:
        return frozenset(self._patient_tab_reservations)

    def begin_patient_open(self, study_uid: str) -> bool:
        """Claim the one in-flight OPEN identity; reject empty/duplicate opens."""
        uid = str(study_uid or "").strip()
        if not uid or uid in self.opening_studies:
            return False
        self.opening_studies.add(uid)
        return True

    def end_patient_open(self, study_uid: str) -> None:
        self.opening_studies.discard(str(study_uid or "").strip())

    def _active_patient_tab_count(self) -> int:
        counter = getattr(self.custom_tab_manager, "patient_tab_count", None)
        if callable(counter):
            return max(0, int(counter()))
        return sum(
            1 for index in range(self.tab_widget.count())
            if str(getattr(self.tab_widget.widget(index), "study_uid", "") or "").strip()
        )

    def reserve_patient_tab(self, study_uid: str) -> PatientTabAdmission:
        """Reserve capacity before any PatientWidget constructor can run."""
        from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import (
            MAX_PATIENT_TABS,
        )

        uid = str(study_uid or "").strip()
        active = self._active_patient_tab_count()
        if not uid:
            return PatientTabAdmission("invalid_identity", uid, active, MAX_PATIENT_TABS)
        existing = getattr(self.custom_tab_manager, "study_uid_to_tab", {}) or {}
        if uid in existing or self.find_widget_by_study_uid(uid) is not None:
            return PatientTabAdmission("existing", uid, active, MAX_PATIENT_TABS)
        if uid in self._patient_tab_reservations:
            return PatientTabAdmission("duplicate", uid, active, MAX_PATIENT_TABS)
        if active + len(self._patient_tab_reservations) >= MAX_PATIENT_TABS:
            return PatientTabAdmission("capacity", uid, active, MAX_PATIENT_TABS)
        self._patient_tab_reservations.add(uid)
        return PatientTabAdmission("admitted", uid, active, MAX_PATIENT_TABS)

    def commit_patient_tab(self, study_uid: str, widget) -> None:
        uid = str(study_uid or "").strip()
        self._patient_tab_reservations.discard(uid)
        if uid:
            self.register(uid, widget)

    def abort_patient_tab(self, study_uid: str) -> None:
        self._patient_tab_reservations.discard(str(study_uid or "").strip())

    def bind_patient_signals(self, home, widget, study_uid, download_manager=None):
        """Install one replaceable, patient-owned relay without changing routing."""
        previous = getattr(widget, '_home_signal_relay', None)
        if previous is not None:
            previous.dispose()
        relay = _PatientTabSignalRelay(home, widget, study_uid, download_manager)
        widget._home_signal_relay = relay
        return relay

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

    async def open_series_action(self, action, open_patient, *, open_key: str) -> bool:
        """Reuse a matching tab or await the standard patient-open workflow.

        Repeated clicks during opening share one task; the last intent wins.
        The opener is supplied by Home with a captured, validated row context.
        """
        from PacsClient.utils.series_identity import SeriesActionIdentity

        if not isinstance(action, SeriesActionIdentity) or not open_key:
            return False
        if self.show_series_action(action):
            self._series_open_intents.pop(open_key, None)
            return True
        token = object()
        self._series_open_intents[open_key] = token
        initial_widget = self.find_widget_by_study_uid(open_key)
        initial_selection = getattr(initial_widget, '_home_series_selection_serial', 0)
        task = self._series_open_tasks.get(open_key)
        if task is None:
            task = asyncio.create_task(open_patient())
            self._series_open_tasks[open_key] = task

            def finished(completed):
                # A cancelled waiter must not retain the independently finishing
                # open task or leave its exception unobserved.
                if self._series_open_tasks.get(open_key) is completed:
                    self._series_open_tasks.pop(open_key, None)
                if not completed.cancelled():
                    completed.exception()

            task.add_done_callback(finished)
        try:
            widget = await asyncio.shield(task)
            if self._series_open_intents.get(open_key) is not token:
                return False
            if widget is None or not self._is_alive(widget):
                return False
            if getattr(widget, '_home_series_selection_serial', 0) != initial_selection:
                return False  # A manual placement during opening superseded this intent.
            if (self.tab_widget.indexOf(widget) < 0
                    or self.tab_widget.currentWidget() is not widget):
                return False
            pending = getattr(widget, '_home_series_action_pending', None)
            if pending is not None:
                pending.cancel()
            pending = _PendingHomeSeriesAction(self, widget, action)
            widget._home_series_action_pending = pending
            pending.attempt()
            return True
        finally:
            if task.done() and self._series_open_tasks.get(open_key) is task:
                self._series_open_tasks.pop(open_key, None)
            if self._series_open_intents.get(open_key) is token:
                self._series_open_intents.pop(open_key, None)

    def show_series_action(self, action) -> bool:
        """Route a Home click only to an existing, uniquely matching patient tab.

        Selection/priority/load remain owned by the normal patient-viewer entry
        point. This adapter does no disk/DB/network lookup and creates no tabs or
        downloaders. Revalidate after activation, which can process nested Qt events.
        """
        from PacsClient.utils.series_identity import SeriesActionIdentity

        if not isinstance(action, SeriesActionIdentity):
            return False

        def resolve(widget):
            if not self._is_alive(widget):
                return None
            entries = getattr(widget, "_server_series_info", None)
            if not isinstance(entries, dict):
                return None
            return action.resolve_display_key(
                entries, primary_study_uid=getattr(widget, "study_uid", ""))

        matches = []
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            if callable(getattr(widget, "change_series_on_viewer", None)) and resolve(widget) is not None:
                matches.append(widget)
        if len(matches) != 1:
            return False
        widget = matches[0]
        controller = getattr(widget, 'viewer_controller', None)
        if controller is not None and not getattr(controller, 'lst_nodes_viewer', None):
            return False
        if not self.activate_tab(widget):
            return False
        if self.tab_widget.indexOf(widget) < 0:
            return False
        key = resolve(widget)
        if key is None:
            return False
        pending = getattr(widget, '_home_series_action_pending', None)
        if pending is not None:
            pending.cancel()
        widget.change_series_on_viewer(key)
        return True

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
