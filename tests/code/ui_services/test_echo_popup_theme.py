"""Guard: EchoMind popups/dialogs use explicit, theme-independent colours.

Root cause fixed (2026-06-28): the "Select Reception ID" confirmation dialog
(`_ReceptionIdDialog`), the image-source dialog, and every EchoMind
`QMessageBox` set NO explicit colours, so they fell back to the Windows
light/dark *system* palette (or inherited the chat page's broad
``QWidget { background: transparent; }`` rule) — producing unreadable text on
some computers.

These are SOURCE-PIN checks (read the files, assert patterns) so they run with
no PySide6/Qt dependency, plus a self-contained exec of the real flag-parse
body. They fail if anyone reintroduces an unstyled popup or a raw
``QMessageBox.warning/information/question/critical`` static call in the two
chat files.
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
# tests/code/ui_services/ -> repo root
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_VC = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat")
_HELPERS = os.path.join(_VC, "ai_chat_helpers.py")
_PAGES = os.path.join(_VC, "ai_chat_pages.py")
_WIDGETS = os.path.join(_VC, "ai_chat_widgets.py")

_MIRROR_VC = os.path.join(
    _ROOT, "builder", "plugin package", "packages", "echomind",
    "payload", "python", "modules", "EchoMind", "viewer_chat",
)

# Static popup statics that must NOT remain in the two chat files (they inherit
# the system palette). The helper module itself MAY reference them (fallback).
_STATIC_RE = re.compile(
    r"QMessageBox\.(warning|information|question|critical|about)\("
    r"|QInputDialog\.getText\("
)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_helper_defines_explicit_popup_styling():
    src = _read(_HELPERS)
    assert "def popup_stylesheet(" in src
    assert "def style_popup(" in src
    assert "def themed_message_box(" in src
    # Themed replacement for QInputDialog.getText (the "enter reception/patient
    # id" + "rename chat" prompts) so they don't inherit the system palette.
    assert "def themed_input_text(" in src
    # The QSS must set BOTH background and text colour explicitly on the
    # dialog/message box surfaces (never inherit the system palette).
    assert "QDialog, QMessageBox" in src
    assert "background-color:" in src
    assert "color:" in src
    # The primary reception button is styled by objectName.
    assert "ReceptionIdPrimaryButton" in src


def test_kill_switch_present_and_parses():
    src = _read(_HELPERS)
    assert "AIPACS_ECHO_POPUP_THEME" in src
    # Extract and exec the real flag-parse body in isolation (only needs os).
    m = re.search(
        r"def _echo_popup_theme_enabled\(\)[^\n]*:\n(?:.*\n)*?    return [^\n]+\n",
        src,
    )
    assert m, "could not locate _echo_popup_theme_enabled body"
    ns = {"os": os}
    exec(m.group(0), ns)
    fn = ns["_echo_popup_theme_enabled"]
    saved = os.environ.get("AIPACS_ECHO_POPUP_THEME")
    try:
        for v in ("", "1", "true", "on", "yes", "ANYTHING"):
            os.environ["AIPACS_ECHO_POPUP_THEME"] = v
            assert fn() is True, f"expected ON for {v!r}"
        for v in ("0", "false", "no", "off", "FALSE", "Off"):
            os.environ["AIPACS_ECHO_POPUP_THEME"] = v
            assert fn() is False, f"expected OFF for {v!r}"
        os.environ.pop("AIPACS_ECHO_POPUP_THEME", None)
        assert fn() is True, "default must be ON when unset"
    finally:
        if saved is None:
            os.environ.pop("AIPACS_ECHO_POPUP_THEME", None)
        else:
            os.environ["AIPACS_ECHO_POPUP_THEME"] = saved


def test_reception_and_image_dialogs_are_styled():
    src = _read(_PAGES)
    # Both unstyled dialogs now apply the explicit popup stylesheet.
    assert src.count("style_popup(self)") >= 2
    # Imported from the helper module.
    assert "style_popup" in src and "themed_message_box" in src
    # The two QInputDialog prompts now route through the themed helper.
    assert src.count("themed_input_text(") >= 2


def test_no_raw_static_popups_left_in_chat_files():
    for path in (_PAGES, _WIDGETS):
        src = _read(path)
        leftovers = _STATIC_RE.findall(src)
        assert not leftovers, (
            f"{os.path.basename(path)} still has raw QMessageBox statics: "
            f"{leftovers} — route them through themed_message_box()"
        )
        # And the themed replacement is actually used.
        assert "themed_message_box(" in src


def test_plugin_mirror_in_sync():
    """The echomind plugin package payload must match the source (release
    parity). Skips cleanly if the mirror is absent in this checkout."""
    if not os.path.isdir(_MIRROR_VC):
        return
    for name in ("ai_chat_helpers.py", "ai_chat_pages.py", "ai_chat_widgets.py"):
        srcf = os.path.join(_VC, name)
        mirf = os.path.join(_MIRROR_VC, name)
        if not os.path.exists(mirf):
            continue
        assert _read(srcf) == _read(mirf), (
            f"mirror out of sync for {name}; run tools/dev/sync_plugin_mirrors.py"
        )
