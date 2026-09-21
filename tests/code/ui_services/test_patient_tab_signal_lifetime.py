"""External download/priority signals must not own or call retired patient tabs."""
import ast
import gc
from pathlib import Path
import textwrap
import threading
import weakref
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal, QThread
from PySide6.QtWidgets import QApplication, QWidget, QTabWidget
from shiboken6 import isValid

from PacsClient.pacs.workstation_ui.home_ui.home_tab_service import HomeTabService

REPO = Path(__file__).resolve().parents[3]


class Source(QObject):
    priority_download_requested = Signal(str, str)
    download_completed = Signal(str)

    def set_current_study_uid(self, uid):
        self.uid = uid


class Patient(QWidget):
    def __init__(self, source, received):
        super().__init__()
        self.study_uid = "synthetic-study"
        self.thumbnail_manager = source
        self.received = received

    def refresh_after_download(self, uid):
        self.received.append(("complete", uid, QThread.currentThread()))


class Home:
    pass


def bind(home, widget):
    # Execute the actual creation-time wiring, without constructing viewers/DB.
    path = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py"
    source = path.read_text(encoding="utf-8-sig")
    block = source.split("            # Connect signals\n", 1)[1].split("            # Add to tab widget", 1)[0]
    namespace = {"print": lambda *a: None}
    exec("def wire(self, widget, study_uid):\n" + textwrap.indent(textwrap.dedent(block), "    "), namespace)
    namespace["wire"](home, widget, widget.study_uid)


@pytest.fixture
def scene():
    app = QApplication.instance() or QApplication([])
    tabs = QTabWidget()
    source = Source()
    received = []
    home = Home()
    home.tab_service = HomeTabService(tabs)
    home._get_or_create_download_manager_tab = lambda **kw: source
    home._handle_priority_download_from_thumbnail = lambda number, uid, widget: received.append(
        ("priority", number, uid, widget.study_uid, QThread.currentThread()))
    patient = Patient(source, received)
    bind(home, patient)
    yield SimpleNamespace(app=app, home=home, source=source, patient=patient,
                          received=received, tabs=tabs)
    if isValid(patient):
        patient.deleteLater()
    tabs.deleteLater()
    source.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_live_routing_keeps_raw_keys_and_existing_primary_completion_filter(scene):
    scene.source.priority_download_requested.emit("02", "secondary-study")
    scene.source.download_completed.emit("foreign-study")
    scene.source.download_completed.emit("synthetic-study")
    scene.app.processEvents()
    assert [e[:-1] for e in scene.received] == [
        ("priority", "02", "secondary-study", "synthetic-study"),
        ("complete", "synthetic-study"),
    ]


@pytest.mark.parametrize("signal", ["priority", "complete"])
def test_closed_tab_does_not_receive_external_actions(scene, signal):
    scene.patient._pw_close_handled = True
    if signal == "priority":
        scene.source.priority_download_requested.emit("02", "synthetic-study")
    else:
        scene.source.download_completed.emit("synthetic-study")
    scene.app.processEvents()
    assert scene.received == []


def test_deleted_tab_cannot_receive_app_lifetime_completion(scene):
    scene.patient.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    scene.source.download_completed.emit("synthetic-study")
    scene.source.priority_download_requested.emit("02", "synthetic-study")
    scene.app.processEvents()
    assert scene.received == []


def test_external_signals_do_not_retain_deleted_patient_wrapper(scene):
    patient = Patient(scene.source, [])
    bind(scene.home, patient)
    ref = weakref.ref(patient)
    patient.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    del patient
    gc.collect()  # Test-only observability; never introduce this into runtime disposal.
    assert ref() is None


def test_worker_completion_is_consumed_on_gui_thread(scene):
    worker = threading.Thread(target=lambda: scene.source.download_completed.emit("synthetic-study"))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    scene.app.processEvents()
    assert len(scene.received) == 1
    assert scene.received[0][-1] == scene.app.thread()


def test_queued_worker_completion_is_rejected_after_close(scene):
    worker = threading.Thread(target=lambda: scene.source.download_completed.emit("synthetic-study"))
    worker.start()
    worker.join(timeout=2)
    scene.patient._pw_close_handled = True
    scene.app.processEvents()
    assert scene.received == []


def test_explicit_patient_exit_disconnects_before_teardown(scene):
    path = REPO / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_lifecycle.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "exit_patient_widget")
    ns = {"_close_step": lambda label: nullcontext()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), ns)
    scene.patient._exit_patient_widget_impl = lambda: scene.source.download_completed.emit("synthetic-study")
    ns[method.name](scene.patient)
    ns[method.name](scene.patient)
    scene.app.processEvents()
    assert scene.received == []


def test_rebinding_and_disposal_preserve_other_subscribers(scene):
    other = []
    scene.source.download_completed.connect(other.append)
    bind(scene.home, scene.patient)
    scene.source.download_completed.emit("synthetic-study")
    scene.app.processEvents()
    assert len(scene.received) == 1
    relay = scene.patient._home_signal_relay
    relay.dispose()
    relay.dispose()
    scene.source.download_completed.emit("synthetic-study")
    scene.app.processEvents()
    assert len(scene.received) == 1
    assert len(other) == 2


def test_queued_completion_cannot_cross_rebinding(scene):
    worker = threading.Thread(target=lambda: scene.source.download_completed.emit("synthetic-study"))
    worker.start()
    worker.join(timeout=2)
    bind(scene.home, scene.patient)
    scene.app.processEvents()
    assert scene.received == []
    scene.source.download_completed.emit("synthetic-study")
    scene.app.processEvents()
    assert len(scene.received) == 1


def test_one_retired_tab_does_not_disconnect_another(scene):
    other_received = []
    other = Patient(scene.source, other_received)
    bind(scene.home, other)
    try:
        scene.patient._home_signal_relay.dispose()
        scene.source.download_completed.emit("synthetic-study")
        scene.app.processEvents()
        assert scene.received == []
        assert len(other_received) == 1
    finally:
        other.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_publisher_destruction_before_dispose_is_safe(scene):
    publisher = Source()
    scene.home.tab_service.bind_patient_signals(scene.home, scene.patient, "synthetic-study", publisher)
    publisher.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    scene.patient._home_signal_relay.dispose()
    assert scene.patient._home_signal_relay is None


def test_optional_manager_and_study_do_not_create_completion_route(scene):
    scene.patient.thumbnail_manager = None
    scene.home.tab_service.bind_patient_signals(scene.home, scene.patient, None)
    scene.source.download_completed.emit("synthetic-study")
    scene.source.priority_download_requested.emit("02", "synthetic-study")
    scene.app.processEvents()
    assert scene.received == []


def test_binding_does_not_retain_home_owner(scene):
    home = Home()
    home.tab_service = scene.home.tab_service
    home._get_or_create_download_manager_tab = lambda **kw: scene.source
    home._handle_priority_download_from_thumbnail = lambda *a: scene.received.append("unexpected")
    bind(home, scene.patient)
    ref = weakref.ref(home)
    del home
    gc.collect()
    assert ref() is None
    scene.source.priority_download_requested.emit("02", "synthetic-study")
    scene.app.processEvents()
    assert scene.received == []


def test_deleted_qobject_home_is_not_called(scene):
    home = QObject()
    home.tab_service = scene.home.tab_service
    home._get_or_create_download_manager_tab = lambda **kw: scene.source
    home._handle_priority_download_from_thumbnail = lambda *a: scene.received.append("unexpected")
    bind(home, scene.patient)
    home.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    scene.source.priority_download_requested.emit("02", "synthetic-study")
    scene.app.processEvents()
    assert scene.received == []


def test_priority_binding_precedes_existing_lazy_download_manager_lookup(scene):
    seen = []

    def lookup(**kw):
        scene.source.priority_download_requested.emit("02", "secondary-study")
        seen.append(kw)
        return scene.source

    scene.home._get_or_create_download_manager_tab = lookup
    bind(scene.home, scene.patient)
    scene.app.processEvents()
    assert len(scene.received) == 1
    assert seen == [{"activate_tab": False}]
