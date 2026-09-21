"""Real Qt lifecycle guards; synthetic transport/data, no database or network."""

import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from modules.cloud_consultation.notifications import poller as mod


def spin(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "Qt lifecycle condition did not complete"


@pytest.fixture
def rig(monkeypatch):
    app = QApplication.instance() or QApplication([])
    owners, releases, writes = [], [], []
    from database import consultation_db

    for name in ("upsert_consultation", "update_consultation_fields", "add_event"):
        monkeypatch.setattr(consultation_db, name, lambda *a, **k: writes.append("db"))
    monkeypatch.setattr(mod.inbox, "notify", lambda *a, **k: writes.append("notify") or 1)
    monkeypatch.setattr(mod.ConsultationPoller, "_outgoing_awaiting_response", lambda self: [])

    poller_class = mod.ConsultationPoller
    def make(provider=lambda: None):
        owner = poller_class(provider, "synthetic@example.invalid", interval_ms=999999)
        owners.append(owner)
        return owner

    yield app, make, releases, writes
    for release in releases:
        release.set()
    for owner in owners:
        if isValid(owner):
            owner.stop()
            for worker in owner.findChildren(QThread):
                assert worker.wait(3000), "synthetic worker failed to finish"
    app.processEvents()
    for owner in owners:
        if isValid(owner):
            owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_stop_cancels_deferred_start(rig):
    app, make, _, _ = rig
    calls = []
    owner = make(lambda: calls.append(1))
    owner.start()
    owner.stop()
    # Use the real five-second startup boundary, not an implementation-shaped timer mock.
    done = []
    QTimer.singleShot(5750, lambda: done.append(True))
    spin(app, lambda: done, timeout=7)
    assert not calls


def test_stop_rejects_manual_or_already_queued_poll(rig):
    _, make, _, _ = rig
    owner = make()
    owner.stop()
    owner.poll_once()
    assert owner._scan is None


def test_completion_requires_stop_and_queued_finished_delivery(rig):
    app, make, releases, _ = rig
    entered, release = threading.Event(), threading.Event()
    releases.append(release)

    def provider():
        entered.set()
        assert release.wait(3)

    owner = make(provider)
    assert not owner.shutdown_complete
    owner.poll_once()
    spin(app, entered.is_set)
    owner.stop()
    assert not owner.shutdown_complete
    worker = owner._scan
    release.set()
    assert worker.wait(3000)  # Test only: queued GUI finish is still undelivered.
    assert not owner.shutdown_complete
    spin(app, lambda: owner.shutdown_complete)


def test_completion_probe_includes_retired_app_owned_pollers(rig):
    from modules.cloud_consultation.notifications import autostart
    app, make, releases, _ = rig
    entered, release = threading.Event(), threading.Event()
    releases.append(release)

    def provider():
        entered.set()
        assert release.wait(3)

    retired = make(provider)
    retired.setParent(app)
    current = make()
    current.setParent(app)
    retired.poll_once()
    spin(app, entered.is_set)
    retired.dispose()
    current.stop()
    assert current.shutdown_complete
    assert not autostart.consultation_shutdown_complete()
    release.set()
    spin(app, autostart.consultation_shutdown_complete)


@pytest.mark.parametrize("handler,items", [
    ("_on_found", [{"envelope": {"consultation_id": "synthetic-incoming"}}]),
    ("_on_found_responses", [{"consultation_id": "synthetic-outgoing"}]),
    ("_on_scan_error", "synthetic offline"),
])
def test_stop_rejects_late_delivery(rig, handler, items):
    _, make, _, writes = rig
    owner = make()
    owner.stop()
    interval = owner._timer.interval()
    getattr(owner, handler)(items)
    assert writes == []
    assert not owner._known and not owner._known_answered
    assert owner._timer.interval() == interval


def test_stop_is_nonblocking_and_skips_next_network_stage(rig):
    app, make, releases, _ = rig
    entered, release = threading.Event(), threading.Event()
    releases.append(release)
    stages = []

    class Transport:
        def ensure_app_folder(self):
            stages.append("folder")
            return "synthetic"

    def provider():
        entered.set()
        assert release.wait(3)
        return Transport()

    owner = make(provider)
    owner.poll_once()
    assert entered.wait(1)
    before = time.monotonic()
    owner.stop()
    assert time.monotonic() - before < 0.1
    worker = owner._scan
    assert worker.isRunning()  # stop did not wait or forcibly terminate it
    release.set()
    assert worker.wait(1000)
    app.processEvents()
    assert stages == []


def test_finished_workers_are_released_on_owner_thread(rig):
    app, make, _, _ = rig
    owner = make()
    for _ in range(3):
        owner.poll_once()
        spin(app, lambda: owner._scan is None)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert owner.findChildren(QThread) == []


def test_restart_does_not_accept_previous_scan(rig, monkeypatch):
    app, make, releases, writes = rig
    entered, release = threading.Event(), threading.Event()
    releases.append(release)

    def assigned(*args):
        entered.set()
        assert release.wait(3)
        return [{"envelope": {"consultation_id": "retired-result"}}]

    monkeypatch.setattr(mod, "find_assigned_consultations", assigned)
    class Transport:
        def ensure_app_folder(self):
            return "synthetic"

    owner = make(Transport())
    owner.poll_once()
    assert entered.wait(1)
    owner.stop()
    owner.start()
    release.set()
    spin(app, lambda: owner._scan is None)
    assert writes == []


def test_dispose_retains_running_worker_until_finished(rig):
    app, make, releases, _ = rig
    entered, release = threading.Event(), threading.Event()
    releases.append(release)
    def provider():
        entered.set()
        assert release.wait(3)

    owner = make(provider)
    owner.poll_once()
    assert entered.wait(1)
    owner.dispose()
    owner.start()  # disposal is terminal
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert isValid(owner) and owner._scan.isRunning()
    assert not owner._timer.isActive()
    release.set()
    spin(app, lambda: owner._scan is None)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(owner)


def test_queued_result_from_finished_old_generation_is_rejected(rig, monkeypatch):
    app, make, _, writes = rig
    class Transport:
        def ensure_app_folder(self):
            return "synthetic"
    monkeypatch.setattr(mod, "find_assigned_consultations", lambda *a: [
        {"envelope": {"consultation_id": "queued-old-result"}}])
    owner = make(Transport())
    owner.poll_once()
    assert owner._scan.wait(1000)  # result is queued, no GUI event delivered yet
    owner.stop()
    owner.start()
    spin(app, lambda: owner._scan is None)
    assert not writes  # QThread interruption alone cannot reject this result


def test_normal_delivery_still_notifies_on_gui_thread(rig, monkeypatch):
    app, make, _, writes = rig
    threads = []
    class Transport:
        def ensure_app_folder(self):
            return "synthetic"
    monkeypatch.setattr(mod, "find_assigned_consultations", lambda *a: [
        {"envelope": {"consultation_id": "current-result"}}])
    owner = make(Transport())
    owner.notified.connect(lambda _: threads.append(QThread.currentThread()))
    owner.poll_once()
    spin(app, lambda: owner._scan is None)
    assert writes == ["db", "notify"]
    assert threads == [app.thread()]


def test_stop_from_notification_cancels_remaining_batch(rig, monkeypatch):
    app, make, _, writes = rig
    class Transport:
        def ensure_app_folder(self):
            return "synthetic"
    monkeypatch.setattr(mod, "find_assigned_consultations", lambda *a: [
        {"envelope": {"consultation_id": "first-result"}},
        {"envelope": {"consultation_id": "after-stop-result"}},
    ])
    owner = make(Transport())
    owner.notified.connect(owner.stop)
    owner.poll_once()
    spin(app, lambda: owner._scan is None)
    assert writes == ["db", "notify"]


@pytest.fixture
def autostart_rig(rig, monkeypatch):
    from modules.cloud_consultation.notifications import autostart
    from modules.cloud_consultation import feature_flags
    from modules.Identity.identity_service import IdentityService

    app, make, _, _ = rig
    monkeypatch.setattr(app, autostart._POLLER_ATTR, None, raising=False)
    monkeypatch.setattr(app, "_aipacs_consultation_shutdown", False, raising=False)
    monkeypatch.setattr(feature_flags, "cloud_consultation_enabled", lambda: True)
    monkeypatch.setattr(feature_flags, "consultation_address", lambda **kw: kw["default"])
    monkeypatch.setattr(IdentityService, "resolve_aipacs_user", lambda _: "synthetic")
    identity = SimpleNamespace(handle="first@example.invalid", subject_id="synthetic")
    monkeypatch.setattr(autostart, "_google_identity", lambda _: identity)
    monkeypatch.setattr(autostart, "_make_transport_provider", lambda *a: lambda: None)
    original = mod.ConsultationPoller
    # Track real owners for guaranteed teardown, while retaining their app parent.
    def factory(provider, address, parent):
        owner = make(provider)
        owner._my_email = address
        owner.setParent(parent)
        return owner
    monkeypatch.setattr(mod, "ConsultationPoller", factory)
    yield app, autostart, identity
    if getattr(app, "_aipacs_consultation_shutdown_hook", False):
        app.aboutToQuit.disconnect(autostart.stop_consultation_poller)
        delattr(app, "_aipacs_consultation_shutdown_hook")
    monkeypatch.setattr(mod, "ConsultationPoller", original)


def test_autostart_shutdown_gate_prevents_recreation(autostart_rig):
    app, auto, _ = autostart_rig
    assert auto.ensure_consultation_poller({})
    owner = getattr(app, auto._POLLER_ATTR)
    auto.stop_consultation_poller()
    assert not owner._timer.isActive()
    assert not auto.ensure_consultation_poller({})


def test_identity_replacement_retires_old_owner(autostart_rig):
    app, auto, ident = autostart_rig
    assert auto.ensure_consultation_poller({})
    old = getattr(app, auto._POLLER_ATTR)
    assert auto.ensure_consultation_poller({})
    assert getattr(app, auto._POLLER_ATTR) is old
    ident.handle = "second@example.invalid"
    assert auto.ensure_consultation_poller({})
    assert getattr(app, auto._POLLER_ATTR) is not old
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old)


def test_main_lifecycle_stops_poller_before_database(autostart_rig, monkeypatch):
    # Execute only the production registration method, not a clinical MainWindow.
    from PacsClient.components import lifecycle_manager as lm
    app, auto, _ = autostart_rig
    assert auto.ensure_consultation_poller({})
    manager = lm.LifecycleManager()
    monkeypatch.setattr(lm, "lifecycle_manager", manager)
    path = Path(__file__).resolve().parents[3] / "PacsClient/pacs/workstation_ui/mainwindow_ui.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_register_lifecycle_resources")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    namespace[method.name](SimpleNamespace())
    resources = manager._resources
    assert resources[-1][0] == "consultation_poller.request_stop"
    assert resources[0][0] == "database.connection_pools"
    resources[-1][1]()
    assert not getattr(app, auto._POLLER_ATTR)._timer.isActive()
    assert not auto.ensure_consultation_poller({})
    monkeypatch.setattr(auto, "consultation_shutdown_complete", lambda: False)
    assert manager._completion_probes["consultation_poller.request_stop"]() is False
