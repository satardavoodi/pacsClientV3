"""AiPacs Chat — the manager console for the ai-pacs.com consultation chat.

A SECOND CLIENT, NOT A SECOND CHAT SYSTEM. The conversations, the business
rules and the state all live in the Laravel PatientChat module and are reached
over ``/api/v1/chat/*``. Nothing here decides anything the server already
decides: ``editable``, ``status_tone``, the summary lines, the delivered/seen
distinction and the relative timestamps all arrive on the wire, because a copy
of any of them is a copy that eventually disagrees with the web console.

LAYERS, AND THE RULE BETWEEN THEM:

    services/   no Qt imports at all. Dataclasses, the REST client, and the
                sync engine — all of it unit-testable without a QApplication,
                which is why the protocol rules live here and not in a widget.
    qt/         the only bridge. A repository object that owns the workers and
                emits signals; the UI never sees HTTP and never sees a thread.
    ui/         PySide6 only, no HTTP. Widgets talk to the repository and to
                nothing else.

This package is import-cheap on purpose: importing it must not pull PySide6,
requests, or the Identity module. Everything heavy is imported inside the
function that needs it, so a workstation with the module disabled pays nothing
for its presence.
"""

from __future__ import annotations

__all__ = ["aipacs_chat_available", "aipacs_chat_enabled"]


def __getattr__(name: str):
    """PEP 562 lazy re-export.

    ``from modules.aipacs_chat import aipacs_chat_available`` must not drag in
    anything but the flag module. The web_browser module does the same thing
    for the same reason — there it keeps QtWebEngine out of startup, here it
    keeps the whole console out of a workstation that has it turned off.
    """
    if name in __all__:
        from . import feature_flags

        return getattr(feature_flags, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
