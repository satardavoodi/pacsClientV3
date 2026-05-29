import os
from types import SimpleNamespace

from modules.network import grpc_client as grpc_client_mod


def test_get_thumbnails_strict_guard_returns_none_on_qt_main_thread(monkeypatch):
    from PySide6.QtCore import QCoreApplication, QThread

    sentinel_thread = object()
    monkeypatch.setattr(QCoreApplication, "instance", staticmethod(lambda: SimpleNamespace(thread=lambda: sentinel_thread)))
    monkeypatch.setattr(QThread, "currentThread", staticmethod(lambda: sentinel_thread))

    emitted = []
    monkeypatch.setattr(grpc_client_mod, "emit_ui_event", lambda *args, **kwargs: emitted.append((args, kwargs)))
    monkeypatch.setenv("AIPACS_THUMBNAIL_MAIN_THREAD_GUARD_STRICT", "1")

    client = grpc_client_mod.DicomGrpcClient.__new__(grpc_client_mod.DicomGrpcClient)
    client.timeout = 30.0
    client.stub = SimpleNamespace()
    client._ensure_stub = lambda: True

    assert client.get_thumbnails("p1", "study-1") is None
    assert emitted, "guard must emit THUMBNAIL_FETCH_MAIN_THREAD_BLOCK_PREVENTED"

    # cleanup env mutation for test process safety
    os.environ.pop("AIPACS_THUMBNAIL_MAIN_THREAD_GUARD_STRICT", None)
