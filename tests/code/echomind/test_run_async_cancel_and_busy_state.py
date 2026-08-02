"""Guard: `_run_async` needs a cancel, and must not fight the transcriber (F5).

TWO DEFECTS, one function.

1. NO CANCEL. `_run_async` disabled the whole composer and re-enabled it only on
   `done`/`failed`. The four chat modes used a 300 s timeout, so a hung server
   locked the composer for FIVE MINUTES with no way out except closing the
   window. `_transcribe_now` already had a cancel button; `_run_async` did not.

2. BUSY-STATE CROSS-TALK. `_transcribe_now` locks btn_plus/btn_mic/btn_send
   individually, while `_run_async`'s cleanup calls `composer.set_enabled(True)`
   — which re-enables all three. Finishing a bubble-triggered translate or
   correction therefore unlocked the mic MID-TRANSCRIPTION and let the user fire
   a second request into a busy pipeline.

The cancel uses the proven "detach, don't wait" contract from the 2026-07-12
close-while-transcribing fix: an in-flight `requests` call cannot be interrupted,
so we disconnect its signals and park the QThread in `_ORPHANED_WORKERS` rather
than `wait()` (which would freeze the GUI) or let Python GC it (which aborts the
process with "QThread: Destroyed while thread is still running").
"""
from __future__ import annotations

import ast
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _src() -> str:
    with open(_PAGES, encoding="utf-8") as fh:
        return fh.read()


def _function_source(name: str, within: str | None = None) -> str:
    """Source of function `name`, optionally the one nested inside `within`.

    `within` matters: there are TWO `cleanup_ui` closures in this file — one in
    `_transcribe_now` and one in the queued multi-file voice upload (which uses
    `composer.set_enabled` and so has no cross-talk to fix). Matching the first
    by name alone silently tests the wrong one.
    """
    src = _src()
    lines = src.splitlines()
    tree = ast.parse(src)
    scope = tree
    if within is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == within:
                scope = node
                break
        else:
            pytest.fail(f"enclosing function {within!r} not found")
    for node in ast.walk(scope):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    pytest.fail(f"function {name!r} not found in ai_chat_pages.py")


@pytest.fixture(scope="module")
def run_async() -> str:
    return _function_source("_run_async")


# ── 1. cancel exists and is safe ────────────────────────────────────────────

def test_run_async_offers_a_cancel(run_async):
    assert "cancelClicked.connect(_on_cancel)" in run_async
    assert "show_cancel(True)" in run_async


def test_cancel_detaches_the_thread_instead_of_waiting(run_async):
    """wait() would freeze the GUI; letting Python GC it aborts the process."""
    cancel = _function_source("_on_cancel")
    assert "_ORPHANED_WORKERS.append(worker)" in cancel, (
        "a cancelled but still-running QThread must keep a strong reference"
    )
    assert "_release_orphan_worker" in cancel
    assert "worker.wait(" not in cancel, "wait() on the GUI thread re-creates the freeze"
    assert "terminate()" not in cancel, (
        "QThread.terminate() bypasses run()'s cleanup and can orphan the socket"
    )


def test_cancel_disconnects_so_a_late_result_cannot_reach_the_ui(run_async):
    cancel = _function_source("_on_cancel")
    assert "worker.done.disconnect" in cancel
    assert "worker.failed.disconnect" in cancel


def test_a_late_callback_after_cancel_is_ignored(run_async):
    """Belt and braces: even if a signal slips through, _ok/_er bail out."""
    assert run_async.count('if cancelled["flag"]:') >= 3


def test_cancel_is_idempotent(run_async):
    cancel = _function_source("_on_cancel")
    assert 'if cancelled["flag"]:' in cancel
    assert 'cancelled["flag"] = True' in cancel


# ── 2. only one owner of the shared cancel button ───────────────────────────

def test_run_async_does_not_steal_the_cancel_button_from_a_transcription(run_async):
    assert 'owns_cancel = {"flag": not getattr(self, "_tr_in_flight", False)}' in run_async
    assert 'if owns_cancel["flag"]:' in run_async


def test_cancel_wiring_is_only_torn_down_by_its_owner(run_async):
    teardown = _function_source("_stop_cancel_wiring")
    assert 'if not owns_cancel["flag"]:' in teardown
    assert "return" in teardown


# ── 3. busy-state cross-talk ────────────────────────────────────────────────

def test_composer_is_not_re_enabled_during_a_transcription(run_async):
    assert 'if self._busy_count == 0 and not getattr(self, "_tr_in_flight", False):' in run_async, (
        "composer.set_enabled(True) unlocks btn_mic/btn_send/btn_plus — it must "
        "not run while _transcribe_now still holds them"
    )


def test_the_bare_busy_count_check_is_gone(run_async):
    assert "if self._busy_count == 0:\n" not in run_async, (
        "that is the pre-fix condition that ignored an in-flight transcription"
    )


def test_transcribe_sets_and_clears_the_in_flight_flag():
    body = _function_source("_transcribe_now")
    assert "self._tr_in_flight = True" in body
    cleanup = _function_source("cleanup_ui", within="_transcribe_now")
    assert "self._tr_in_flight = False" in cleanup, (
        "the flag must be cleared on EVERY transcription exit, including cancel "
        "and failure — cleanup_ui is the single choke point"
    )


def test_flag_read_is_defensive():
    """`_tr_in_flight` may not exist yet on a freshly built page."""
    body = _function_source("_run_async")
    assert 'getattr(self, "_tr_in_flight", False)' in body


# ── 4. the chat modes no longer carry their own 300 s scalar ───────────────

def test_chat_modes_no_longer_pin_a_300_second_scalar_timeout():
    src = _src()
    assert "timeout=300" not in src, (
        "the 300 s scalar is what made the composer lock for five minutes; the "
        "timeout now comes from echomind_http (connect 10 s / read 180 s)"
    )
