"""Exit confirmation dialog on main window close.

The dialog itself is the easy part. What this file really guards is that the
prompt can NEVER intercept a programmatic close: ``_confirm_application_exit``
opens a nested modal event loop inside ``closeEvent``, and a shutdown that is
blocked there risks the 8 s ``os._exit(0)`` failsafe in
``single_instance_lock._initiate_shutdown`` — which skips ``main.py``'s
``finally`` (download-subprocess termination, DB WAL checkpoint, lock release).
"""
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MW = REPO / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"
SRC = MW.read_text(encoding="utf-8")


class _FakeEvent:
    """Minimal stand-in for QCloseEvent's spontaneous() contract."""

    def __init__(self, spontaneous: bool):
        self._spontaneous = spontaneous

    def spontaneous(self) -> bool:
        return self._spontaneous


class _Host:
    """Binds the real, unmodified `_should_confirm_exit` onto a bare object."""

    def __init__(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("_mw_probe", MW)
        # Importing mainwindow_ui pulls in the whole viewer stack; instead we
        # exec ONLY the decision method's source against this module's globals.
        self._spec = spec


def _load_decision_fn():
    """Extract and compile `_should_confirm_exit` without importing the module."""
    import ast
    import logging
    import textwrap

    tree = ast.parse(SRC)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_should_confirm_exit":
            fn = node
            break
    assert fn is not None, "_should_confirm_exit not found in mainwindow_ui.py"
    src = textwrap.dedent("\n".join(SRC.splitlines()[fn.lineno - 1 : fn.end_lineno]))
    ns = {"os": os, "logger": logging.getLogger("_mw_probe")}
    exec(compile(src, str(MW), "exec"), ns)
    return ns["_should_confirm_exit"]


class _Obj:
    pass


# ── the dialog exists and is wired ──────────────────────────────────────────

def test_close_event_requires_confirmation():
    assert "def _confirm_application_exit(self)" in SRC
    assert "Are you sure you want to close the application?" in SRC
    assert "_exit_confirmed" in SRC
    assert "event.ignore()" in SRC


def test_close_event_routes_through_the_decision_helper():
    assert "def _should_confirm_exit(self, event)" in SRC
    assert "if self._should_confirm_exit(event):" in SRC


def test_the_message_box_is_not_leaked():
    """A QMessageBox parented to the main window outlives the Python local."""
    assert "box.setAttribute(Qt.WA_DeleteOnClose, True)" in SRC


# ── the guards that make it safe ────────────────────────────────────────────

@pytest.fixture()
def decide():
    return _load_decision_fn()


def test_programmatic_close_is_never_interrupted(decide, monkeypatch):
    monkeypatch.setenv("AIPACS_CONFIRM_EXIT", "1")
    host = _Obj()
    assert decide(host, _FakeEvent(spontaneous=False)) is False


def test_user_initiated_close_asks_when_enabled(decide, monkeypatch):
    monkeypatch.setenv("AIPACS_CONFIRM_EXIT", "1")
    host = _Obj()
    assert decide(host, _FakeEvent(spontaneous=True)) is True


def test_default_is_off(decide, monkeypatch):
    """Default OFF until live-verified: the prompt runs a nested modal loop in
    closeEvent, so it stays dark until a real workstation smoke test passes."""
    monkeypatch.delenv("AIPACS_CONFIRM_EXIT", raising=False)
    host = _Obj()
    assert decide(host, _FakeEvent(spontaneous=True)) is False


def test_already_confirmed_is_not_asked_twice(decide, monkeypatch):
    monkeypatch.setenv("AIPACS_CONFIRM_EXIT", "1")
    host = _Obj()
    host._exit_confirmed = True
    assert decide(host, _FakeEvent(spontaneous=True)) is False


def test_an_event_without_spontaneous_falls_back_to_not_asking(decide, monkeypatch):
    monkeypatch.setenv("AIPACS_CONFIRM_EXIT", "1")
    host = _Obj()

    class _Broken:
        def spontaneous(self):
            raise RuntimeError("no native event")

    assert decide(host, _Broken()) is False


def test_exit_confirmed_is_set_even_when_the_prompt_is_skipped():
    """Otherwise a second closeEvent on the same shutdown could re-prompt."""
    body = SRC.split("def closeEvent(self, event):", 1)[1]
    head = body.split("lifecycle_manager", 1)[0]
    assert "self._exit_confirmed = True" in head


# ── unrelated wiring pin kept from the branch ───────────────────────────────

def test_user_account_menu_wiring():
    assert "attach_user_account_menu" in SRC
    menu_src = (
        REPO / "PacsClient" / "pacs" / "workstation_ui" / "user_account_menu.py"
    ).read_text(encoding="utf-8")
    assert "ACCOUNT" in menu_src
    assert "Settings" in menu_src
    assert "Internal Assignments" in menu_src
