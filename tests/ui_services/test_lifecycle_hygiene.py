"""
Lifecycle hygiene tests for Home UI services.

Validates deterministic cleanup of signal wiring, timers, and callbacks
across tab open/close/reopen cycles.

Run:
    python -m pytest tests/ui_services/test_lifecycle_hygiene.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── Fakes ────────────────────────────────────────────────────────

class FakeSignal:
    """Minimal signal emitter with connect/disconnect/emit tracking."""

    def __init__(self, name=""):
        self.name = name
        self._slots = []
        self.connect_count = 0
        self.disconnect_count = 0
        self.emit_count = 0
        self.emissions = []

    def connect(self, slot):
        self._slots.append(slot)
        self.connect_count += 1

    def disconnect(self, slot=None):
        if slot is not None:
            try:
                self._slots.remove(slot)
            except ValueError:
                raise RuntimeError(f"No such slot connected to {self.name}")
        else:
            self._slots.clear()
        self.disconnect_count += 1

    def emit(self, *args):
        self.emit_count += 1
        self.emissions.append(args)
        for slot in list(self._slots):
            slot(*args)

    @property
    def slot_count(self):
        return len(self._slots)


class FakeDM:
    """Minimal DownloadManagerWidget stand-in."""

    def __init__(self):
        self.studyProgressUpdated = FakeSignal("studyProgress")
        self.seriesDownloadStarted = FakeSignal("seriesStarted")
        self.seriesProgressUpdated = FakeSignal("seriesProgress")
        self.seriesDownloadCompleted = FakeSignal("seriesCompleted")
        self._tasks = {}
        self._active_workers = {}


class FakeWidget:
    """Minimal PatientWidget stand-in."""

    def __init__(self, study_uid="study-1"):
        self.study_uid = study_uid
        self._visible = True
        self._deleted = False
        self.series_images_progress = FakeSignal("series_images_progress")
        self.series_downloaded = FakeSignal("series_downloaded")
        self._series_uid_to_number = {}
        self.thumbnail_manager = SimpleNamespace(
            series_widgets={},
            _series_uid_to_number={},
            start_series_download=MagicMock(),
            update_series_progress=MagicMock(),
            complete_series_download=MagicMock(),
        )
        self.on_study_images_progress = MagicMock()

    def isVisible(self):
        if self._deleted:
            raise RuntimeError("C++ object deleted")
        return self._visible


class FakeTabWidget:
    """Minimal QTabWidget stand-in."""

    def __init__(self):
        self._tabs = []

    def count(self):
        return len(self._tabs)

    def widget(self, i):
        if 0 <= i < len(self._tabs):
            return self._tabs[i]
        return None

    def addTab(self, w, label):
        self._tabs.append(w)

    def setCurrentWidget(self, w):
        pass

    def setCurrentIndex(self, i):
        pass

    def indexOf(self, w):
        try:
            return self._tabs.index(w)
        except ValueError:
            return -1

    def removeTab(self, i):
        if 0 <= i < len(self._tabs):
            self._tabs.pop(i)


class FakeTimer:
    """Minimal single-shot timer with manual firing for deterministic tests."""

    def __init__(self):
        self._single_shot = False
        self._interval = 0
        self._active = False
        self.timeout = FakeSignal("timeout")

    def setSingleShot(self, value):
        self._single_shot = bool(value)

    def setInterval(self, value):
        self._interval = int(value)

    def interval(self):
        return self._interval

    def isActive(self):
        return self._active

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def fire(self):
        if not self._active:
            return
        if self._single_shot:
            self._active = False
        self.timeout.emit()


# ─── Helper to build service ─────────────────────────────────────

def _import_home_download_service():
    """Import HomeDownloadService, stubbing heavy deps that aren't needed."""
    import importlib
    import types

    stubs_needed = [
        "modules.download_manager.ui.main_widget",
        "modules.download_manager.ui",
        "modules.download_manager.ui.widget",
        "modules.download_manager.ui.widget.widget",
    ]
    saved = {}
    for name in stubs_needed:
        if name not in sys.modules:
            stub = types.ModuleType(name)
            # Provide a fake DownloadManagerWidget class
            stub.DownloadManagerWidget = type("DownloadManagerWidget", (), {})
            sys.modules[name] = stub
            saved[name] = None
        else:
            saved[name] = sys.modules[name]

    try:
        mod = importlib.import_module(
            "PacsClient.pacs.workstation_ui.home_ui.home_download_service"
        )
        return mod.HomeDownloadService
    finally:
        # Restore originals
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)


def _make_service():
    HomeDownloadService = _import_home_download_service()
    tab_widget = FakeTabWidget()
    svc = HomeDownloadService(tab_widget)
    return svc


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════

class TestConnectDisconnectIdempotency:
    """Connect and disconnect must be safe to call multiple times."""

    def test_connect_is_idempotent(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        svc.connect_dm_to_widget(dm, w, "study-1")
        svc.connect_dm_to_widget(dm, w, "study-1")  # duplicate

        assert len(svc._dm_widget_connections) == 1
        assert dm.seriesProgressUpdated.connect_count == 1

    def test_disconnect_after_connect(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        svc.connect_dm_to_widget(dm, w, "study-1")

        removed = svc.disconnect_widget(w)

        assert removed == 1
        assert len(svc._dm_widget_connections) == 0
        assert dm.seriesProgressUpdated.disconnect_count == 1

    def test_double_disconnect_is_safe(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        svc.connect_dm_to_widget(dm, w, "study-1")
        svc.disconnect_widget(w)
        removed_again = svc.disconnect_widget(w)

        assert removed_again == 0


class TestCloseUnderActiveDownload:
    """Cleanup must be safe even when signals are being emitted."""

    def test_disconnect_prevents_further_callbacks(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        svc.connect_dm_to_widget(dm, w, "study-1")

        # Simulate disconnect (tab close)
        svc.disconnect_widget(w)

        # Now emit — handler should no longer be in the slot list
        assert dm.seriesProgressUpdated.slot_count == 0

    def test_progress_fanout_is_coalesced_to_latest_state(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        dm._tasks["study-1"] = SimpleNamespace(
            series_list=[SimpleNamespace(series_uid="7", series_number="7", image_count=10)]
        )

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesDownloadStarted.emit("study-1", "7", "series-7")
        assert w.thumbnail_manager.start_series_download.call_count == 1
        assert w.thumbnail_manager.start_series_download.call_args.args == ("7",)
        assert w.thumbnail_manager.start_series_download.call_args.kwargs == {"total_images": 10}

        dm.seriesProgressUpdated.emit("study-1", "7", 1, 10)
        dm.seriesProgressUpdated.emit("study-1", "7", 2, 10)
        dm.seriesProgressUpdated.emit("study-1", "7", 3, 10)

        assert w.series_images_progress.emit_count == 0
        assert w.thumbnail_manager.update_series_progress.call_count == 0

        rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 1
        assert w.series_images_progress.emissions[-1] == ("7", 3, 10)
        assert w.thumbnail_manager.update_series_progress.call_count == 0

        dm.seriesProgressUpdated.emit("study-1", "7", 3, 10)
        rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 1
        assert w.thumbnail_manager.update_series_progress.call_count == 0

    def test_terminal_progress_after_completion_is_dropped(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        dm._tasks["study-1"] = SimpleNamespace(
            series_list=[SimpleNamespace(series_uid="7", series_number="7", image_count=10)]
        )

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesProgressUpdated.emit("study-1", "7", 3, 10)
        rec.progress_timer.fire()
        assert w.series_images_progress.emissions[-1] == ("7", 3, 10)

        dm.seriesDownloadCompleted.emit("study-1", "7")
        assert w.series_downloaded.emit_count == 1
        assert w.thumbnail_manager.complete_series_download.call_count == 1

        # Late terminal progress for the same series/cycle must not recreate
        # downstream thumbnail/progressive churn after completion.
        dm.seriesProgressUpdated.emit("study-1", "7", 10, 10)
        rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 2  # 3/10 + final completion pulse
        assert w.series_images_progress.emissions[-1] == ("7", 10, 10)
        assert w.thumbnail_manager.update_series_progress.call_count == 0

    def test_second_completion_projects_thumbnail_immediately_before_flush(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        dm._tasks["study-1"] = SimpleNamespace(
            series_list=[
                SimpleNamespace(series_uid="7", series_number="7", image_count=10),
                SimpleNamespace(series_uid="8", series_number="8", image_count=12),
            ]
        )

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesDownloadCompleted.emit("study-1", "7")
        assert w.thumbnail_manager.complete_series_download.call_count == 1
        assert w.series_downloaded.emit_count == 1

        dm.seriesDownloadCompleted.emit("study-1", "8")

        # Thumbnail should turn ready immediately; viewer completion fan-out stays batched.
        assert w.thumbnail_manager.complete_series_download.call_count == 2
        assert w.thumbnail_manager.complete_series_download.call_args.args == ("8",)
        assert w.thumbnail_manager.complete_series_download.call_args.kwargs == {"total_images": 12}
        assert w.series_downloaded.emit_count == 1

        rec.flush_timer.fire()

        assert w.series_downloaded.emit_count == 2

    def test_new_partial_cycle_after_completion_is_admitted(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        dm._tasks["study-1"] = SimpleNamespace(
            series_list=[SimpleNamespace(series_uid="7", series_number="7", image_count=10)]
        )

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesDownloadCompleted.emit("study-1", "7")
        assert w.series_downloaded.emit_count == 1

        # A verified new partial cycle for the same series should clear the
        # completed guard and emit progress again.
        dm.seriesProgressUpdated.emit("study-1", "7", 1, 10)
        rec.progress_timer.fire()

        assert w.series_images_progress.emissions[-1] == ("7", 1, 10)
        assert w.thumbnail_manager.start_series_download.call_count == 1
        assert w.thumbnail_manager.start_series_download.call_args.args == ("7",)
        assert w.thumbnail_manager.start_series_download.call_args.kwargs == {"total_images": 10}

    def test_thumbnail_progress_is_suppressed_without_blocking_viewer_progress(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesProgressUpdated.emit("study-1", "7", 11, 100)
        rec.progress_timer.fire()

        dm.seriesProgressUpdated.emit("study-1", "7", 14, 100)
        rec.progress_timer.fire()

        dm.seriesProgressUpdated.emit("study-1", "7", 22, 100)
        rec.progress_timer.fire()

        dm.seriesProgressUpdated.emit("study-1", "7", 24, 100)
        rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 1
        assert w.series_images_progress.emissions[-1] == ("7", 11, 100)
        assert w.thumbnail_manager.update_series_progress.call_count == 0

    def test_thumbnail_progress_is_not_bucketed_because_it_is_not_forwarded(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesProgressUpdated.emit("study-1", "7", 31, 100)
        rec.progress_timer.fire()

        dm.seriesProgressUpdated.emit("study-1", "7", 34, 100)
        rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 1
        assert w.thumbnail_manager.update_series_progress.call_count == 0

    def test_viewer_progress_is_deferred_until_admitted(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        import PacsClient.pacs.workstation_ui.home_ui.home_download_service as _hds_mod

        gate = iter([False, True])
        with patch.object(_hds_mod, "_ui_should_admit", side_effect=lambda *a, **kw: next(gate)):
            dm.seriesProgressUpdated.emit("study-1", "7", 4, 10)
            rec.progress_timer.fire()

            assert w.series_images_progress.emit_count == 0
            assert rec.progress_timer.isActive() is True

            rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 1
        assert w.series_images_progress.emissions[-1] == ("7", 4, 10)

    def test_widget_level_series_uid_map_resolves_progress_before_thumbnails_exist(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        w._series_uid_to_number["uid-201"] = "201"

        with patch("PySide6.QtCore.QTimer", FakeTimer):
            svc.connect_dm_to_widget(dm, w, "study-1")

        rec = next(iter(svc._dm_widget_connections.values()))

        dm.seriesProgressUpdated.emit("study-1", "uid-201", 4, 10)
        rec.progress_timer.fire()

        assert w.series_images_progress.emit_count == 1
        assert w.series_images_progress.emissions[-1] == ("201", 4, 10)


class TestOpenCloseReopenCycle:
    """Repeated open/close/reopen must not accumulate state."""

    def test_reopen_after_close_creates_fresh_connection(self):
        svc = _make_service()
        dm = FakeDM()

        # First session
        w1 = FakeWidget("study-1")
        svc.connect_dm_to_widget(dm, w1, "study-1")
        svc.disconnect_widget(w1)

        # Second session — different widget instance
        w2 = FakeWidget("study-1")
        svc.connect_dm_to_widget(dm, w2, "study-1")

        assert len(svc._dm_widget_connections) == 1
        assert dm.seriesProgressUpdated.connect_count == 2

    def test_multiple_studies_cleanup(self):
        svc = _make_service()
        dm = FakeDM()

        w1 = FakeWidget("study-A")
        w2 = FakeWidget("study-B")
        svc.connect_dm_to_widget(dm, w1, "study-A")
        svc.connect_dm_to_widget(dm, w2, "study-B")
        assert len(svc._dm_widget_connections) == 2

        svc.disconnect_widget(w1)
        assert len(svc._dm_widget_connections) == 1

        svc.disconnect_widget(w2)
        assert len(svc._dm_widget_connections) == 0


class TestGlobalCleanup:
    """Full service cleanup (shutdown path)."""

    def test_cleanup_disconnects_all(self):
        svc = _make_service()
        dm = FakeDM()
        w1 = FakeWidget("s-1")
        w2 = FakeWidget("s-2")
        svc.connect_dm_to_widget(dm, w1, "study-1")
        svc.connect_dm_to_widget(dm, w2, "study-2")

        svc.cleanup()

        assert len(svc._dm_widget_connections) == 0
        assert dm.seriesProgressUpdated.slot_count == 0

    def test_double_cleanup_is_safe(self):
        svc = _make_service()
        svc.cleanup()
        svc.cleanup()  # no error


class TestNoStaleProgressAfterTeardown:
    """After disconnect, no progress should reach the closed widget."""

    def test_no_progress_after_disconnect(self):
        svc = _make_service()
        dm = FakeDM()
        w = FakeWidget()
        svc.connect_dm_to_widget(dm, w, "study-1")

        svc.disconnect_widget(w)

        # Emit progress — should have no effect since slot is disconnected
        # We check by verifying no slots remain
        assert dm.seriesProgressUpdated.slot_count == 0
        assert dm.studyProgressUpdated.slot_count == 0
        assert dm.seriesDownloadStarted.slot_count == 0
        assert dm.seriesDownloadCompleted.slot_count == 0


class TestDbServiceContextManager:
    """HomeDbService must use context-managed DB connections."""

    def test_get_patient_study_uses_context_manager(self):
        """Verify the method uses get_db_connection(), not bare get_connection_database()."""
        import inspect
        from PacsClient.pacs.workstation_ui.home_ui.home_db_service import HomeDbService
        source = inspect.getsource(HomeDbService.get_patient_study)
        assert "get_db_connection" in source
        assert "get_connection_database" not in source

    def test_save_study_details_uses_context_manager(self):
        import inspect
        from PacsClient.pacs.workstation_ui.home_ui.home_db_service import HomeDbService
        source = inspect.getsource(HomeDbService.save_study_details)
        assert "get_db_connection" in source
        assert "get_connection_database" not in source


# ═══════════════════════════════════════════════════════════════════
# Track 2+4: Orchestrator bridge in ui_throttle
# ═══════════════════════════════════════════════════════════════════

class TestOrchestratorBridge:
    """Verify ui_throttle orchestrator registration and query."""

    def test_set_and_clear_orchestrator(self):
        from modules.viewer.fast.ui_throttle import (
            set_active_orchestrator,
            clear_active_orchestrator,
            _ORCHESTRATOR_LOCK,
        )
        import modules.viewer.fast.ui_throttle as _mod

        fake = SimpleNamespace(is_heavy_download_active=lambda: True)
        set_active_orchestrator(fake)
        with _ORCHESTRATOR_LOCK:
            assert _mod._ACTIVE_ORCHESTRATOR is fake
        clear_active_orchestrator(fake)
        with _ORCHESTRATOR_LOCK:
            assert _mod._ACTIVE_ORCHESTRATOR is None

    def test_clear_wrong_instance_is_noop(self):
        from modules.viewer.fast.ui_throttle import (
            set_active_orchestrator,
            clear_active_orchestrator,
            _ORCHESTRATOR_LOCK,
        )
        import modules.viewer.fast.ui_throttle as _mod

        real = SimpleNamespace(is_heavy_download_active=lambda: False)
        other = SimpleNamespace(is_heavy_download_active=lambda: False)
        set_active_orchestrator(real)
        clear_active_orchestrator(other)  # wrong instance — should keep real
        with _ORCHESTRATOR_LOCK:
            assert _mod._ACTIVE_ORCHESTRATOR is real
        clear_active_orchestrator()  # cleanup

    def test_is_heavy_download_active_probes_orchestrator(self):
        from modules.viewer.fast.ui_throttle import (
            set_active_orchestrator,
            clear_active_orchestrator,
            is_heavy_download_active,
        )

        fake = SimpleNamespace(is_heavy_download_active=lambda: True)
        set_active_orchestrator(fake)
        try:
            assert is_heavy_download_active() is True
        finally:
            clear_active_orchestrator()

    def test_no_orchestrator_still_works(self):
        from modules.viewer.fast.ui_throttle import (
            clear_active_orchestrator,
            is_heavy_download_active,
        )
        clear_active_orchestrator()
        # Should not raise, returns based on ZetaBoost globals alone
        result = is_heavy_download_active()
        assert isinstance(result, bool)
