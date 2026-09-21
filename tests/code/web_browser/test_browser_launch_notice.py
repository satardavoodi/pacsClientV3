"""Cold browser launch UX: real Qt shell, synthetic browser, no network or DB."""

import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressBar, QPushButton, QTabWidget, QWidget
from shiboken6 import isValid

from PacsClient.pacs.workstation_ui.home_ui.home_module_tabs import activate_or_create_module_tab


class PaintProbe(QObject):
    def __init__(self):
        super().__init__()
        self.paints = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint and obj.objectName() == "browserLaunchNotice":
            self.paints += 1
        return False


@pytest.fixture
def shell(monkeypatch):
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    root.resize(800, 600)
    tabs = QTabWidget(root)
    tabs.setGeometry(0, 120, 800, 480)
    home = QWidget(tabs)
    tabs.addTab(home, "Synthetic Home")
    manager = SimpleNamespace(patient_tabs={})
    def add_browser(*, widget):
        index = tabs.addTab(widget, "Web Browser")
        manager.patient_tabs[index] = {"is_web_browser_tab": True, "widget": widget}
        tabs.setCurrentIndex(index)
    manager.add_web_browser_tab = add_browser
    home.tab_widget, home.custom_tab_manager = tabs, manager
    source = Path(__file__).resolve().parents[3] / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "open_web_browser")
    namespace = dict(is_module_enabled=lambda _: True, QMessageBox=QMessageBox,
                     activate_or_create_module_tab=activate_or_create_module_tab,
                     logger=logging.getLogger("synthetic-browser-test"))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    home.open_web_browser = lambda **kw: namespace[method.name](home, **kw)
    import modules.web_browser as package
    from modules.web_browser import prewarm
    monkeypatch.setattr(prewarm, "mark_browser_used", lambda: None)
    probe = PaintProbe()
    app.installEventFilter(probe)
    root.show()
    app.processEvents()
    yield SimpleNamespace(app=app, root=root, home=home, tabs=tabs, manager=manager,
                          probe=probe, package=package, namespace=namespace)
    app.removeEventFilter(probe)
    if isValid(root):
        root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def settle(shell):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        shell.app.processEvents()
        if not shell.root.findChildren(QWidget, "browserLaunchNotice"):
            return
        time.sleep(.01)
    assert not shell.root.findChildren(QWidget, "browserLaunchNotice")


def test_notice_paints_before_even_the_lazy_engine_import(shell, monkeypatch):
    observations = []
    def lazy(name):
        if name != "WebBrowserWidget":
            raise AttributeError(name)
        observations.append((shell.probe.paints, [x.text() for x in shell.root.findChildren(QLabel)]))
        return QWidget
    monkeypatch.delitem(shell.package.__dict__, "WebBrowserWidget", raising=False)
    monkeypatch.setattr(shell.package, "__getattr__", lazy)
    widget = shell.home.open_web_browser()
    assert widget is not None
    assert observations and observations[0][0] > 0, "engine import preceded visible status paint"
    assert any("Please wait" in text for text in observations[0][1])
    settle(shell)


def test_reentrant_launch_does_not_create_a_second_browser(shell, monkeypatch):
    calls = []
    def browser():
        calls.append(1)
        if len(calls) == 1:
            shell.home.open_web_browser()
        return QWidget()
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", browser)
    assert shell.home.open_web_browser() is not None
    assert calls == [1]
    assert shell.tabs.count() == 2
    settle(shell)


def test_input_is_blocked_during_construction_then_restored(shell, monkeypatch):
    button = QPushButton("Synthetic action", shell.root)
    button.show()
    received = []
    class InputProbe(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.KeyPress:
                received.append(1)
            return False
    probe = InputProbe()
    button.installEventFilter(probe)
    def key():
        QCoreApplication.sendEvent(button, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
    def browser():
        key()
        return QWidget()
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", browser)
    shell.home.open_web_browser()
    assert received == [], "input reached another control during engine construction"
    settle(shell)
    key()
    assert received == [1]


def test_exception_restores_input_and_allows_retry(shell, monkeypatch):
    def broken():
        raise RuntimeError("synthetic browser init failure")
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", broken)
    assert shell.home.open_web_browser(show_unavailable_dialog=False) is None
    settle(shell)
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", QWidget)
    assert shell.home.open_web_browser() is not None
    assert shell.tabs.count() == 2
    settle(shell)


def test_existing_tab_reuses_widget_without_wait_notice(shell, monkeypatch):
    widget = QWidget()
    shell.manager.add_web_browser_tab(widget=widget)
    def forbidden():
        raise AssertionError("existing tab must not construct another browser")
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", forbidden)
    assert shell.home.open_web_browser() is widget
    assert shell.probe.paints == 0


def test_module_off_does_not_show_notice_or_load_engine(shell, monkeypatch):
    shell.namespace["is_module_enabled"] = lambda _: False
    def forbidden():
        raise AssertionError("disabled module imported browser")
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", forbidden)
    assert shell.home.open_web_browser(show_unavailable_dialog=False) is None
    assert shell.probe.paints == 0


def test_no_nested_events_are_processed_to_show_status(shell, monkeypatch):
    pending = []
    QTimer.singleShot(0, lambda: pending.append(True))
    def browser():
        assert not pending, "showing status dispatched unrelated queued work"
        assert shell.probe.paints > 0
        return QWidget()
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", browser)
    assert shell.home.open_web_browser() is not None
    settle(shell)


def test_queued_input_is_discarded_before_gate_is_released(shell, monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    field = QLineEdit(shell.root)
    field.show()
    def browser():
        QCoreApplication.postEvent(field, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a"))
        return QWidget()
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", browser)
    shell.home.open_web_browser()
    settle(shell)
    assert field.text() == ""
    QCoreApplication.sendEvent(field, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b"))
    assert field.text() == "b"


def test_no_fake_percentage_or_cancellable_native_startup(shell, monkeypatch):
    observed = []
    def browser():
        bars = shell.root.findChildren(QProgressBar)
        observed.append([(bar.minimum(), bar.maximum(), bar.isTextVisible()) for bar in bars])
        assert not shell.root.close()  # Cannot tear down an in-construction engine's owner.
        return QWidget()
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", browser)
    assert shell.home.open_web_browser() is not None
    assert observed == [[(0, 0, False)]]
    settle(shell)
    assert shell.root.close()


def test_return_contract_survives_input_drain_grace(shell, monkeypatch):
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", QWidget)
    widget = shell.home.open_web_browser(show_unavailable_dialog=False)
    assert widget is not None  # OAuth/CommandBus require a widget immediately.
    assert shell.home.open_web_browser(show_unavailable_dialog=False) is widget
    assert shell.tabs.count() == 2
    settle(shell)


def test_deleted_owner_retires_input_filter_and_timer(shell, monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    from shiboken6 import delete
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", QWidget)
    shell.home.open_web_browser()
    notice = shell.root.findChild(QWidget, "browserLaunchNotice")
    assert notice is not None
    delete(shell.root)
    assert not isValid(notice)
    field = QLineEdit()
    try:
        QCoreApplication.sendEvent(field, QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a"))
        assert field.text() == "a"
        shell.app.processEvents()
    finally:
        delete(field)


def test_preexisting_disabled_control_stays_disabled(shell, monkeypatch):
    button = QPushButton("Disabled by existing policy", shell.root)
    button.setEnabled(False)
    monkeypatch.setitem(shell.package.__dict__, "WebBrowserWidget", QWidget)
    shell.home.open_web_browser()
    settle(shell)
    assert not button.isEnabled()
