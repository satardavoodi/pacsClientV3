"""Guards: Secretary orb teardown, and no Qt work on the audio/worker threads.

THE DEFECTS (Phase-1 audit, 2026-07-31):

1. `SecretaryButtonWidget` had NO teardown at all — no `closeEvent`, no
   `cleanup()`, no `deleteLater()` — while creating one
   `ApiWorker(parent=self)` QThread per voice command. Closing the app during an
   STT upload (the budget is 360 s, so this is ordinary) let Qt destroy a
   RUNNING QThread: `QThread: Destroyed while thread is still running` ->
   qFatal -> abort(), no traceback, app.log stops mid-line. The EchoMind chat
   fixed exactly this in 2026-07-12 with the detach-don't-wait contract; it was
   never carried across.

2. The recorder's `except` handler ran on the AUDIO thread and called
   `_set_active_silent`, which does blockSignals/setChecked and starts/stops
   QTimers — widget mutation from a non-GUI thread. Reached whenever the mic is
   busy, unplugged, or the device index went stale after a dock change.

3. `_persian_bubble`'s worker closure called `self.history.add_bubble(...)`
   INSIDE the function `ApiWorker.run` executes on the QThread, constructing a
   MessageBubble and splicing it into the live layout off the GUI thread.

4. The Settings `_ProbeWorker` was parented to the Settings widget, so closing
   Settings during a blackholed probe destroyed a running QThread.

These are structural guards on purpose: reproducing an access violation or a
qFatal in-process would abort the test runner, which is precisely the failure
mode being guarded against.
"""
from __future__ import annotations

import ast
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_ORB = ("PacsClient", "pacs", "workstation_ui", "home_ui", "secretary_button_widget.py")
_POPUP = ("PacsClient", "pacs", "workstation_ui", "home_ui", "secretary_popup.py")
_SETTINGS = ("PacsClient", "pacs", "workstation_ui", "settings_ui", "echomind_settings.py")
_PAGES = ("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _read(*parts: str) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _class(src: str, name: str) -> ast.ClassDef:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError("class %s not found" % name)


def _method(src: str, cls: str, name: str) -> str:
    node = _class(src, cls)
    for n in node.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError("%s.%s not found" % (cls, name))


def _code_only(text: str) -> str:
    """Strip comment lines so a guard never matches its own explanation."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


# ── 1. the orb has a teardown at all ─────────────────────────────────────────

@pytest.mark.parametrize("method", ["cleanup", "closeEvent"])
def test_secretary_widget_has_a_teardown(method):
    names = {n.name for n in _class(_read(*_ORB), "SecretaryButtonWidget").body
             if isinstance(n, ast.FunctionDef)}
    assert method in names, (
        "SecretaryButtonWidget.%s is gone — closing the app during an STT "
        "upload will destroy a running QThread and abort the process" % method
    )


def test_close_event_calls_cleanup():
    assert "cleanup()" in _method(_read(*_ORB), "SecretaryButtonWidget", "closeEvent")


def test_cleanup_never_waits_on_a_worker():
    """`wait()` re-creates the freeze the worker exists to avoid — up to the
    full read timeout with the GUI thread blocked."""
    body = _code_only(_method(_read(*_ORB), "SecretaryButtonWidget", "cleanup"))
    assert ".wait(" not in body, (
        "cleanup() calls wait() — this blocks the GUI thread for the remaining "
        "read timeout. The contract is detach, don't wait."
    )


def test_cleanup_parks_running_workers_instead_of_dropping_them():
    """Letting Python GC a running QThread aborts the process, so a detached
    worker must be held somewhere until it finishes."""
    src = _read(*_ORB)
    body = _code_only(_method(src, "SecretaryButtonWidget", "cleanup"))
    assert "_ORPHANED_SECRETARY_WORKERS" in body, "detached workers are not parked"
    assert "setParent(None)" in body, "workers are not unparented before detaching"
    assert "_ORPHANED_SECRETARY_WORKERS: list = []" in src, "the park list is gone"
    assert "def _release_orphan_secretary_worker" in src, "nothing ever frees a parked worker"


def test_cleanup_stops_the_audio_stream():
    body = _code_only(_method(_read(*_ORB), "SecretaryButtonWidget", "cleanup"))
    assert "_abort_audio_stream" in body, (
        "PortAudio is not stopped deterministically — a live stream holds a "
        "bound method into a widget Qt is about to free"
    )


def test_the_recorder_keeps_a_handle_on_its_stream():
    """It used to live only inside a `with`, so nothing could stop it."""
    body = _code_only(_method(_read(*_ORB), "SecretaryButtonWidget", "_start_recording"))
    assert "self._rec_stream = stream" in body, "the stream handle is not retained"


def test_cancel_recording_aborts_the_stream_too():
    body = _code_only(_method(_read(*_ORB), "SecretaryButtonWidget", "cancel_recording"))
    assert "_abort_audio_stream" in body, (
        "the 1.5 s join has no fallback: if PortAudio does not return the "
        "stream is still live"
    )


# ── 2. nothing touches a widget from the audio thread ────────────────────────

def test_recorder_error_path_marshals_to_the_gui_thread():
    body = _code_only(_method(_read(*_ORB), "SecretaryButtonWidget", "_start_recording"))
    assert "_call_on_gui" in body, "the recorder error path is not marshalled"
    # the direct, off-thread call must be gone
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("self._set_active_silent("):
            raise AssertionError(
                "`_set_active_silent` is called directly from the recorder "
                "thread again: %r" % line
            )


def test_cross_thread_marshal_passes_a_context_object():
    """Two-arg `QTimer.singleShot(0, fn)` creates the timer on the CALLING
    thread. From a plain threading.Thread with no Qt event loop it never fires,
    so the callback is silently dropped. The three-arg form delivers into the
    context object's thread."""
    body = _code_only(_method(_read(*_ORB), "SecretaryButtonWidget", "_call_on_gui"))
    assert "QTimer.singleShot(0, self," in body, (
        "_call_on_gui does not pass a context QObject — from the audio thread "
        "the callback will never run"
    )


# ── 3. no widgets built on an ApiWorker thread ───────────────────────────────

def test_persian_bubble_worker_does_not_build_widgets():
    """`ApiWorker.run` executes `work()` on the QThread. It must return data."""
    src = _read(*_PAGES)
    node = None
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == "_persian_bubble":
            node = n
            break
    assert node is not None, "_persian_bubble not found"
    for inner in ast.walk(node):
        if isinstance(inner, ast.FunctionDef) and inner.name == "work":
            body = _code_only(ast.get_source_segment(src, inner) or "")
            assert "self.history.add_bubble" not in body, (
                "a MessageBubble is being constructed on the worker thread "
                "again — return data and let the GUI thread render it"
            )
            return
    raise AssertionError("_persian_bubble has no inner work()")


# ── 4. popup and probe lifetimes ─────────────────────────────────────────────

def test_popup_tears_the_widget_down_not_just_the_mic():
    body = _code_only(_method(_read(*_POPUP), "SecretaryPopup", "_cancel_active_work"))
    assert "cleanup" in body, (
        "closing the popup cancels the recording but leaves an in-flight STT "
        "QThread parented to a widget that may be destroyed"
    )


def test_settings_probe_is_not_parented_to_the_settings_widget():
    src = _code_only(_read(*_SETTINGS))
    assert "_ProbeWorker(work, parent=self)" not in src, (
        "the probe is parented again — closing Settings during a blackholed "
        "probe destroys a running QThread"
    )
    assert "_LIVE_PROBES" in src, "the probe is not held anywhere; Python may GC a running QThread"
    assert "def _release_probe" in src, "nothing ever frees a finished probe"
