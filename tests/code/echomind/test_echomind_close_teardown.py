"""Guard: closing EchoMind mid-recording/transcription must not crash the app.

ROOT CAUSE (2026-07-12, native_fault.log 18:17:16):

    Windows fatal exception: access violation
    Current thread 0x0003bdb0 (most recent call first):
      <no Python frame>                      <-- a pure NATIVE thread
    Thread ... threading._shutdown / concurrent.futures.process._python_exit

`AIChatViewer` is a top-level window with ``WA_DeleteOnClose``, so closing it
destroys the whole widget tree IMMEDIATELY. The composer opens

    sd.InputStream(..., callback=self._rec_callback)

which hands PortAudio a BOUND METHOD of that widget. Nothing stopped the stream on
close, so PortAudio's own native audio thread kept invoking the callback on memory
Qt had already freed -> access violation (no Python frame, because the faulting
thread is PortAudio's, not an interpreter thread). Same hazard for QMediaPlayer.

FIX: `UnifiedComposer.cleanup()` stops the record loop, JOINS the worker (leaving
the `with sd.InputStream(...)` block is what closes the stream), force-stops
PortAudio, and releases QMediaPlayer; `AIChatViewer.closeEvent` / mode-switch call
it BEFORE the tree is deleted.

Source-pin only (no Qt/PortAudio needed).
"""
import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_VC = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat")
_WIDGETS = os.path.join(_VC, "ai_chat_widgets.py")
_VIEWER = os.path.join(_VC, "ai_chat_viewer.py")


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def test_composer_has_idempotent_cleanup():
    src = _read(_WIDGETS)
    assert "def cleanup(self)" in src, "UnifiedComposer.cleanup() is missing"
    assert "_cleaned_up" in src, "cleanup() must be idempotent (close path runs it)"


def test_cleanup_joins_recorder_and_stops_portaudio():
    """The stream is closed by LEAVING the `with sd.InputStream(...)` block, so the
    worker must be joined; sd.stop() is the belt-and-braces if the join times out."""
    src = _read(_WIDGETS)
    cleanup = src.split("def cleanup(self)", 1)[1].split("\n    def ", 1)[0]
    assert "_rec_running = False" in cleanup
    assert ".join(" in cleanup, "must WAIT for the recorder thread to close the stream"
    assert "sd.stop()" in cleanup, "must force PortAudio to release the device"
    assert "setSource(QUrl())" in cleanup, "must release QMediaPlayer"


def test_viewer_tears_down_before_delete_on_close():
    src = _read(_VIEWER)
    # the window is WA_DeleteOnClose -> teardown MUST happen in closeEvent
    assert "WA_DeleteOnClose" in src
    assert "def closeEvent" in src, "AIChatViewer must tear down on close"
    assert "_teardown_page" in src
    # and also when switching mode (the old page is deleteLater'd)
    assert re.search(r"_teardown_page\(w\)\s*\n\s*self\.stack\.removeWidget\(w\)", src), \
        "mode switch must tear the old page down before deleteLater()"


def test_teardown_calls_cleanup_on_page_and_composer():
    src = _read(_VIEWER)
    block = src.split("def _teardown_page", 1)[1].split("\n    def ", 1)[0]
    assert "composer" in block
    assert "cleanup" in block
