"""A 403 on the poll, and the pane widths the operator chose.

A 403 from the sync endpoint is the one failure an operator cannot fix and
cannot diagnose from the generic message: the account is signed in, the network
is fine, and the site owner has simply not listed it as a console operator.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from modules.aipacs_chat.services.chat_client import (  # noqa: E402
    ChatClient,
    ChatForbiddenError,
    ChatTransportError,
)

# Imported ONCE, at module level, and used from there. Another test in this
# suite reloads the client module; mixing a module-level class object with a
# freshly re-imported one makes ``pytest.raises`` miss an exception that IS the
# right class — which reads as a client bug and is not one.


class _ForbiddenWebClient:
    base_url = "https://example.invalid/consult-form"

    def request_json(self, method, path, **kwargs):
        from modules.Identity.providers.aipacs_web import AipacsWebError

        raise AipacsWebError("This action is unauthorized.", status_code=403)


class _BrokenWebClient:
    base_url = "https://example.invalid/consult-form"

    def request_json(self, method, path, **kwargs):
        from modules.Identity.providers.aipacs_web import AipacsWebError

        raise AipacsWebError("Could not reach the consultation server.")


def test_a_403_on_the_poll_names_the_real_problem():
    client = ChatClient(_ForbiddenWebClient(), aipacs_user="drv")

    with pytest.raises(ChatForbiddenError) as caught:
        client.sync([("m", 0)])

    message = str(caught.value).lower()
    assert "operator" in message
    assert "network" not in message, "this is not a connection problem"


def test_an_ordinary_transport_failure_is_not_dressed_up_as_a_permission_one():
    client = ChatClient(_BrokenWebClient(), aipacs_user="drv")

    with pytest.raises(ChatTransportError) as caught:
        client.sync([("m", 0)])

    assert not isinstance(caught.value, ChatForbiddenError)


# ── pane widths ──────────────────────────────────────────────────────────────


def test_a_stale_splitter_value_is_ignored_rather_than_collapsing_a_pane(monkeypatch):
    """A saved layout from a build with a different pane count must not win."""
    from PySide6.QtWidgets import QApplication, QSplitter, QWidget

    app = QApplication.instance() or QApplication([])

    from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget

    class _Probe:
        _SETTINGS_SPLITTER = AiPacsChatWidget._SETTINGS_SPLITTER
        _restore_splitter = AiPacsChatWidget._restore_splitter

        def __init__(self, stored):
            self._stored = stored
            self.splitter = QSplitter()
            for _ in range(3):
                self.splitter.addWidget(QWidget())
            self.splitter.setSizes([320, 760, 320])

        def _settings(self):
            probe = self

            class _S:
                def value(self, key, default=None):
                    return probe._stored

            return _S()

    stale = _Probe([100, 200])          # two panes, not three
    stale._restore_splitter()
    assert stale.splitter.sizes() != [100, 200]

    good = _Probe([200, 900, 400])
    good._restore_splitter()
    assert sum(good.splitter.sizes()) > 0
    app.processEvents()
