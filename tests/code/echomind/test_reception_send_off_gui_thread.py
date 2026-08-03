"""Guard: "Send to Reception" must never block the Qt main thread (F1).

THE DEFECT: `OneChatPage._send_to_reception` called its nested
`_send_with_patient_id(...)` inline on the GUI thread. That function issues a
`requests.get(timeout=20)`, a `requests.post(timeout=30)` and a database write —
so on a slow or unreachable reception server the whole workstation froze for up
to ~50 s with no spinner, no wait cursor and no cancel.

THE FIX AND ITS ONE INVARIANT: the work moved onto an `ApiWorker`, and therefore
**the worker function must not touch a single Qt object**. Two GUI calls used to
live inside it and both are now returned as data instead:

  * `themed_message_box(...)` — modal dialog;
  * `_propagate_reception_status_to_pacs(...)` — walks `self.parent()` and may
    call `widget._change_report_status(...)`.

Calling either from a worker thread is a Qt violation that can crash natively
with no Python traceback (cf. the 2026-07-12 close-while-transcribing abort).
This test pins that separation structurally, so a future edit that "just adds a
message box" inside the worker fails here instead of in a clinic.

`ai_chat_pages` cannot be imported standalone (it pulls the whole PacsClient +
widget chain), so this is an AST source-pin — the same approach
`test_echomind_close_teardown.py` uses.
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


def _function_source(name: str) -> str:
    src = _src()
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    pytest.fail(f"function {name!r} not found in ai_chat_pages.py")


@pytest.fixture(scope="module")
def worker_src() -> str:
    return _function_source("_send_with_patient_id")


@pytest.fixture(scope="module")
def outer_src() -> str:
    return _function_source("_send_to_reception")


# ── the invariant: no Qt from the worker ─────────────────────────────────────

def test_worker_never_opens_a_message_box(worker_src):
    assert "themed_message_box" not in worker_src, (
        "_send_with_patient_id runs on an ApiWorker thread; showing a modal "
        "dialog from there is a Qt violation. Return the dict and let "
        "_deliver_reception_result show it on the GUI thread."
    )


def test_worker_never_propagates_status_itself(worker_src):
    assert "_propagate_reception_status_to_pacs" not in worker_src, (
        "_propagate_reception_status_to_pacs walks self.parent() and may call "
        "widget._change_report_status(...) — GUI work. The worker must hand back "
        "a 'propagate' request instead."
    )


@pytest.mark.parametrize(
    "forbidden",
    ["QMessageBox(", "QDialog(", ".exec()", "setEnabled(", "QApplication.processEvents"],
)
def test_worker_does_no_other_gui_work(worker_src, forbidden):
    assert forbidden not in worker_src, (
        f"{forbidden!r} in _send_with_patient_id — that function runs off the GUI thread."
    )


# ── the network really is in the worker (not accidentally left behind) ───────

def test_the_blocking_http_calls_live_in_the_worker(worker_src):
    assert "requests.get(" in worker_src
    assert "requests.post(" in worker_src


def test_the_worker_is_dispatched_through_run_async(outer_src):
    assert "_run_async(" in outer_src, (
        "the reception send must be dispatched onto an ApiWorker via _run_async "
        "(which also registers it in self._workers for the close-teardown sweep)"
    )
    assert "_send_with_patient_id(patient_id)" in outer_src


def test_the_old_synchronous_call_shape_is_gone(outer_src):
    assert "if not _send_with_patient_id(patient_id):" not in outer_src, (
        "that is the pre-fix inline GUI-thread call — do not restore it"
    )


# ── GUI work is delivered on the GUI thread, in BOTH modes ──────────────────

def test_a_gui_thread_consumer_exists_and_does_the_qt_work():
    consumer = _function_source("_deliver_reception_result")
    assert "themed_message_box" in consumer
    assert "_propagate_reception_status_to_pacs" in consumer


def test_the_kill_switch_path_is_still_fully_synchronous(outer_src):
    """AIPACS_ECHOMIND_RECEPTION_ASYNC=0 must restore the legacy behaviour."""
    assert "_reception_send_async_enabled()" in outer_src
    assert "_deliver_reception_result(_send_with_patient_id(patient_id))" in outer_src, (
        "the flag-off path must call the worker inline and deliver its result "
        "synchronously — byte-equivalent to the pre-fix behaviour"
    )


def test_kill_switch_defaults_to_on():
    src = _src()
    assert '_ENV_RECEPTION_ASYNC = "AIPACS_ECHOMIND_RECEPTION_ASYNC"' in src
    tree = ast.parse(src)
    names = {
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_reception_send_async_enabled"
    }
    assert names, "_reception_send_async_enabled() must exist as the single gate"


# ── the worker's return contract ─────────────────────────────────────────────

def test_every_worker_exit_returns_the_result_contract(worker_src):
    """No `return False` / `return True` survivors — those would show no dialog."""
    tree = ast.parse("\n".join(l[8:] if l.startswith(" " * 8) else l
                               for l in worker_src.splitlines()))
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert returns, "worker has no return statements — did the parse fail?"
    for node in returns:
        assert isinstance(node.value, ast.Dict), (
            f"line {node.lineno} of _send_with_patient_id returns a non-dict; "
            "every exit must return the {'ok','icon','title','text'} contract so "
            "the GUI thread knows what to show"
        )


def test_result_contract_keys_are_present(worker_src):
    for key in ('"ok"', '"icon"', '"title"', '"text"', '"propagate"'):
        assert key in worker_src, f"missing {key} in the worker result contract"
