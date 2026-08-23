"""One identity key for every module (live bug 2026-08-22).

The AI-PACS account is stored per workstation user, keyed by
``IdentityService.resolve_aipacs_user(auth_user)``. The Settings page found the
login dict by scanning top-level widgets; ``open_aipacs_chat`` read
``getattr(self, 'auth_user', None)`` off HomePanelWidget, which never sets that
attribute. So the chat console resolved identity ``"local"``, found no account
and rendered "Not signed in to AI-PACS" — while Settings, reading the real key,
showed the same operator signed in with chat access granted.

These tests pin the fix: one shared resolver, and no call site that bypasses it.
"""

import inspect
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


AUTH = {"username": "vahid", "full_name": "vahid", "role": "admin"}


def test_resolver_finds_the_login_on_the_window(qapp):
    from PySide6.QtWidgets import QWidget

    from modules.Identity.ui.host_user import resolve_host_auth_user

    window = QWidget()
    window.auth_user = dict(AUTH)
    child = QWidget(window)
    try:
        assert resolve_host_auth_user(child) == AUTH
    finally:
        window.deleteLater()


def test_resolver_follows_the_mainwindow_host_window_chain(qapp):
    from PySide6.QtWidgets import QWidget

    from modules.Identity.ui.host_user import resolve_host_auth_user

    class _Host:
        auth_user = dict(AUTH)

    class _Main:
        host_window = _Host()

    widget = QWidget()          # its own window(), with no auth_user on it
    widget.mainwindow = _Main()
    try:
        assert resolve_host_auth_user(widget) == AUTH
    finally:
        widget.deleteLater()


def test_resolver_scans_top_level_windows_with_no_widget(qapp):
    """The Settings page has no useful parent chain — it must still find it."""
    from PySide6.QtWidgets import QWidget

    from modules.Identity.ui.host_user import resolve_host_auth_user

    window = QWidget()
    window.auth_user = dict(AUTH)
    window.show()
    try:
        assert resolve_host_auth_user() == AUTH
    finally:
        window.hide()
        window.deleteLater()


def test_resolver_never_raises_and_yields_local(qapp):
    from modules.Identity.ui.host_user import (
        resolve_host_aipacs_user,
        resolve_host_auth_user,
    )

    class _Hostile:
        @property
        def auth_user(self):
            raise RuntimeError("boom")

        def window(self):
            raise RuntimeError("boom")

    assert resolve_host_auth_user(_Hostile()) is None or isinstance(
        resolve_host_auth_user(_Hostile()), dict)
    assert isinstance(resolve_host_aipacs_user(_Hostile()), str)


def test_settings_and_chat_resolve_the_SAME_key(qapp):
    """The heart of the bug: two consoles, one operator, one key."""
    from PySide6.QtWidgets import QWidget

    from modules.Identity.ui.host_user import resolve_host_aipacs_user
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    window = QWidget()
    window.auth_user = dict(AUTH)
    window.show()
    try:
        assert ces._aipacs_user() == "vahid"
        assert resolve_host_aipacs_user(None) == "vahid"
        assert ces._aipacs_user() == resolve_host_aipacs_user(None)
    finally:
        window.hide()
        window.deleteLater()


def test_chat_open_path_does_not_read_a_nonexistent_attribute():
    """`open_aipacs_chat` must use the shared resolver.

    `getattr(self, 'auth_user', None)` on HomePanelWidget silently returns
    None — the attribute does not exist — and None means identity "local".
    """
    root = Path(__file__).resolve().parents[3]
    src = (root / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
           / "home_panel" / "_hp_modules.py").read_text(encoding="utf-8")
    start = src.index("def open_aipacs_chat")
    end = src.index("def open_education_module")
    body = src[start:end]
    assert "resolve_host_auth_user" in body
    # Compare CODE, not prose: the comment above the fix names the old call on
    # purpose, and a guard that reads comments would fire on its own docs.
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "getattr(self, 'auth_user'" not in code
    assert 'getattr(self, "auth_user"' not in code


def test_chat_widget_falls_back_when_handed_no_login():
    """Defence in depth: any entry point that cannot supply the dict must still
    land on the right identity rather than silently becoming "local"."""
    from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget

    src = inspect.getsource(AiPacsChatWidget._build_repository)
    assert "resolve_host_auth_user" in src
    assert "resolve_aipacs_user" in src


def test_settings_delegates_to_the_shared_resolver():
    from PacsClient.pacs.workstation_ui.settings_ui import (
        consultation_education_settings as ces,
    )

    src = inspect.getsource(ces._resolve_auth_user)
    assert "resolve_host_auth_user" in src
    # It must NOT keep its own private widget scan, or the two drift again.
    assert "topLevelWidgets" not in src
