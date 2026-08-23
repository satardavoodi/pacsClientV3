"""
Text tool — the user must be asked WHAT to write (FAST viewer).

REPORTED FROM THE FLOOR: "in the tools at patient viewer page there is a text
function to write the text on the image / its not working".

It was wired end to end — toolbar button -> toggle_text() -> set_tool_mode
(TOOL_TEXT) -> ToolController._text_press -> ToolStore ->
QPainterToolRenderer._render_text — and the renderer drew `model.text`
faithfully.  The one missing step was the input: `_text_press` hard-coded
``text="Text"``, so every click stamped the literal word "Text" on the image
and there was no way to type your own.  The Advanced (VTK) backend had asked
via ``QInputDialog`` since forever (see
modules/viewer/interactor_styles/text_interactorstyle.py) — only FAST, the
default backend, never asked.

The prompt is INJECTED into the controller rather than opened by it:
``modules/viewer/tools/controller.py`` is deliberately Qt-free (it imports
only ``os``, ``typing`` and its own package) and is imported by headless
tests.  ``qt_viewer_bridge._init_tool_controller`` wires ``_text_prompt_fn``,
exactly as it already wires ``_pixel_data_fn`` / ``_pixel_spacing_fn``.

The load-bearing guards in here are:

  * ``test_the_bridge_wires_the_prompt`` — the controller change is inert
    without the Qt-side wiring, and the wiring is a single line that is easy
    to drop in a merge.  AST-based, so a comment mentioning ``_text_prompt_fn``
    cannot satisfy it.
  * ``test_without_a_prompt_the_legacy_placeholder_is_kept`` — a bare
    ToolController (every existing tool test, the EchoMind write adapter)
    must behave EXACTLY as before.  This is the no-regression pin.
  * ``test_a_cancel_leaves_the_tool_armed`` — cancelling must place nothing
    AND not consume the click, or "I mistyped, let me try again" turns into
    "the tool switched itself off".
"""
from __future__ import annotations

import ast
import inspect
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.enums import ToolType
from modules.viewer.tools.models import RulerModel, TextModel
from modules.viewer.tools.store import ToolStore


# ── Minimal fakes — no Qt ────────────────────────────────────────────────────

class _NoOpRenderer:
    def render_tool(self, *a, **kw):
        return None

    def render_preview(self, *a, **kw):
        return None


class _Prompt:
    """Records how many times it was asked and answers from a script."""

    def __init__(self, *answers, raises: bool = False):
        self.answers = list(answers)
        self.raises = raises
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.raises:
            raise RuntimeError("dialog exploded")
        if not self.answers:
            return None
        return self.answers.pop(0)


def _make(prompt=None):
    store = ToolStore()
    ctrl = ToolController(store, _NoOpRenderer())
    if prompt is not None:
        ctrl._text_prompt_fn = prompt
    ctrl.activate(ToolType.TEXT)
    return ctrl, store


def _texts(store):
    return [m.text for m in store.get_for_slice(0) if isinstance(m, TextModel)]


# ══════════════════════════════════════════════════════════════════════════
# The fix: what the user types is what lands on the image
# ══════════════════════════════════════════════════════════════════════════

def test_the_typed_text_is_what_lands_on_the_image():
    prompt = _Prompt("L4-L5 disc")
    ctrl, store = _make(prompt)

    ctrl.on_mouse_press(100.0, 200.0, 0)

    assert prompt.calls == 1, "the user was never asked what to write"
    items = store.get_for_slice(0)
    assert len(items) == 1
    assert isinstance(items[0], TextModel)
    assert items[0].text == "L4-L5 disc", (
        "the annotation must carry the typed string, not the placeholder"
    )
    assert items[0].points_image == [(100.0, 200.0)]
    assert items[0].is_complete is True


def test_the_placeholder_is_gone_when_a_prompt_is_wired():
    ctrl, store = _make(_Prompt("Nodule"))
    ctrl.on_mouse_press(10.0, 10.0, 0)
    assert _texts(store) == ["Nodule"]
    assert "Text" not in _texts(store), (
        "the hard-coded 'Text' placeholder must not survive a real answer"
    )


def test_each_click_asks_again():
    prompt = _Prompt("first", "second")
    ctrl, store = _make(prompt)

    ctrl.on_mouse_press(10.0, 10.0, 0)
    ctrl.on_mouse_press(20.0, 20.0, 0)

    assert prompt.calls == 2
    assert _texts(store) == ["first", "second"]


def test_non_ascii_text_is_carried_through_unchanged():
    """Reports here are frequently Persian; the prompt must not mangle them."""
    ctrl, store = _make(_Prompt("دیسک"))
    ctrl.on_mouse_press(10.0, 10.0, 0)
    assert _texts(store) == ["دیسک"]


def test_surrounding_whitespace_is_trimmed():
    ctrl, store = _make(_Prompt("   Nodule   "))
    ctrl.on_mouse_press(10.0, 10.0, 0)
    assert _texts(store) == ["Nodule"]


# ══════════════════════════════════════════════════════════════════════════
# Cancel / bad input must place NOTHING
# ══════════════════════════════════════════════════════════════════════════

def test_cancel_places_nothing():
    ctrl, store = _make(_Prompt(None))
    ctrl.on_mouse_press(10.0, 10.0, 0)
    assert store.count() == 0, "cancelling the dialog must not stamp a label"


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", "  \t \n "])
def test_blank_input_is_a_cancel_not_a_blank_label(blank):
    ctrl, store = _make(_Prompt(blank))
    ctrl.on_mouse_press(10.0, 10.0, 0)
    assert store.count() == 0, (
        f"{blank!r} must be treated as a cancel — an empty label is invisible "
        "on the image but still selectable/erasable, which reads as a ghost"
    )


def test_a_broken_prompt_does_not_stamp_a_stray_label():
    prompt = _Prompt(raises=True)
    ctrl, store = _make(prompt)

    ctrl.on_mouse_press(10.0, 10.0, 0)   # must not raise out of a mouse press

    assert prompt.calls == 1
    assert store.count() == 0


def test_a_cancel_leaves_the_tool_armed():
    """Cancel must not consume the tool — the next click still works."""
    prompt = _Prompt(None, "second try")
    ctrl, store = _make(prompt)

    ctrl.on_mouse_press(10.0, 10.0, 0)
    assert store.count() == 0
    assert ctrl.active_tool == ToolType.TEXT, (
        "cancelling must leave TEXT active so the user can try again"
    )

    ctrl.on_mouse_press(20.0, 20.0, 0)
    assert _texts(store) == ["second try"]


# ══════════════════════════════════════════════════════════════════════════
# No regression: everything that does NOT wire a prompt is untouched
# ══════════════════════════════════════════════════════════════════════════

def test_without_a_prompt_the_legacy_placeholder_is_kept():
    """A bare ToolController must behave EXACTLY as it did before the fix."""
    ctrl, store = _make()          # no prompt injected
    ctrl.on_mouse_press(100.0, 200.0, 0)
    items = store.get_for_slice(0)
    assert len(items) == 1
    assert items[0].text == "Text"


def test_a_fresh_controller_has_no_prompt_wired():
    ctrl = ToolController(ToolStore(), _NoOpRenderer())
    assert ctrl._text_prompt_fn is None


def test_the_prompt_is_only_asked_for_the_text_tool():
    prompt = _Prompt("should not be used")
    store = ToolStore()
    ctrl = ToolController(store, _NoOpRenderer())
    ctrl._text_prompt_fn = prompt

    ctrl.activate(ToolType.RULER)
    ctrl.on_mouse_press(10.0, 10.0, 0)
    ctrl.on_mouse_press(50.0, 50.0, 0)

    assert prompt.calls == 0, "only the TEXT tool may pop a dialog"
    assert any(isinstance(m, RulerModel) for m in store.get_for_slice(0))


def test_the_controller_module_stays_qt_free():
    """The prompt is injected precisely so this stays true."""
    src = Path(inspect.getsourcefile(ToolController)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    offenders = [m for m in imported if "PySide" in m or "QtWidgets" in m or "vtk" in m.lower()]
    assert not offenders, (
        f"controller.py must stay Qt/VTK-free (found {offenders}); the text "
        "prompt belongs in qt_viewer_bridge, not here"
    )


# ══════════════════════════════════════════════════════════════════════════
# The Qt side: the wiring, and the dialog wrapper
# ══════════════════════════════════════════════════════════════════════════

def _bridge_ast():
    from modules.viewer.fast import qt_viewer_bridge
    src = Path(qt_viewer_bridge.__file__).read_text(encoding="utf-8")
    return ast.parse(src)


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _vtk_text_style_source() -> str:
    """Source of the Advanced backend's text tool (modules/viewer/...)."""
    viewer_pkg = Path(inspect.getsourcefile(ToolController)).parents[1]
    path = viewer_pkg / "interactor_styles" / "text_interactorstyle.py"
    assert path.is_file(), f"text_interactorstyle.py not found at {path}"
    return path.read_text(encoding="utf-8")


def test_the_bridge_wires_the_prompt():
    """The controller fix is inert unless the Qt layer injects the dialog.

    AST-based on purpose: a comment naming ``_text_prompt_fn`` must not be
    able to satisfy this guard.
    """
    fn = _func(_bridge_ast(), "_init_tool_controller")
    assert fn is not None, "_init_tool_controller vanished from qt_viewer_bridge"

    wired = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_text_prompt_fn"
            for t in node.targets
        )
    ]
    assert wired, (
        "_init_tool_controller must assign ctrl._text_prompt_fn — without it "
        "the FAST Text tool silently goes back to stamping the word 'Text'"
    )


def test_the_bridge_exposes_the_prompt_method():
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
    assert callable(getattr(QtViewerBridge, "_prompt_annotation_text", None))


def test_the_prompt_method_is_re_entrancy_guarded():
    """A modal dialog pumps events; a second press must not stack a dialog."""
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    fake = SimpleNamespace(qt_viewer=None, _text_prompt_open=True)
    bound = types.MethodType(QtViewerBridge._prompt_annotation_text, fake)
    assert bound() is None, "a re-entrant prompt must report a cancel, not open"


class _StubDialog:
    """Stands in for QInputDialog — no QApplication, no window."""

    result = ("", False)
    calls = []

    @staticmethod
    def getText(parent, title, label, *a, **kw):
        _StubDialog.calls.append((parent, title, label))
        return _StubDialog.result


@pytest.fixture
def stub_input_dialog(monkeypatch):
    qtw = pytest.importorskip("PySide6.QtWidgets")
    _StubDialog.calls = []
    monkeypatch.setattr(qtw, "QInputDialog", _StubDialog, raising=True)
    return _StubDialog


def test_the_prompt_method_returns_the_typed_text(stub_input_dialog):
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    stub_input_dialog.result = ("Nodule", True)
    fake = SimpleNamespace(qt_viewer=None)
    bound = types.MethodType(QtViewerBridge._prompt_annotation_text, fake)

    assert bound() == "Nodule"
    assert len(stub_input_dialog.calls) == 1
    assert fake._text_prompt_open is False, "the re-entrancy flag must be released"


def test_the_prompt_method_reports_cancel_as_none(stub_input_dialog):
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    stub_input_dialog.result = ("typed then cancelled", False)
    fake = SimpleNamespace(qt_viewer=None)
    bound = types.MethodType(QtViewerBridge._prompt_annotation_text, fake)

    assert bound() is None, "Cancel must discard whatever was in the box"


def test_the_prompt_method_releases_the_flag_when_the_dialog_raises(
    stub_input_dialog, monkeypatch
):
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    def _boom(*a, **kw):
        raise RuntimeError("no display")

    # via monkeypatch so the stub is restored for the other tests
    monkeypatch.setattr(stub_input_dialog, "getText", staticmethod(_boom))
    fake = SimpleNamespace(qt_viewer=None)
    bound = types.MethodType(QtViewerBridge._prompt_annotation_text, fake)

    assert bound() is None
    assert fake._text_prompt_open is False, (
        "a raising dialog must not leave the tool permanently muted"
    )


# ══════════════════════════════════════════════════════════════════════════
# The Advanced (VTK) backend: it always asked, but ignored Cancel
# ══════════════════════════════════════════════════════════════════════════

def test_the_vtk_text_tool_honours_cancel():
    """`ok` was collected and then ignored, so Cancel added an empty actor."""
    src = _vtk_text_style_source()
    tree = ast.parse(src)
    fn = _func(tree, "on_left_button_press")
    assert fn is not None

    guarded_returns = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.If)
        and any(
            isinstance(n, ast.Name) and n.id == "ok"
            for n in ast.walk(node.test)
        )
        and any(isinstance(b, ast.Return) for b in node.body)
    ]
    assert guarded_returns, (
        "TextInteractorStyle.on_left_button_press must bail out when the "
        "dialog was cancelled, instead of adding an empty text actor"
    )

    # ...and the bail-out has to come BEFORE the actor is built.
    guard_line = min(n.lineno for n in guarded_returns)
    actor_lines = [
        node.lineno for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_text_actor"
    ]
    assert actor_lines, "create_text_actor call disappeared"
    assert guard_line < min(actor_lines), (
        "the cancel guard must precede create_text_actor, or the empty actor "
        "is built anyway"
    )


def test_both_backends_ask_the_same_question():
    """Same dialog title/label in FAST and Advanced — one muscle memory."""
    from modules.viewer.fast import qt_viewer_bridge

    fast_src = Path(qt_viewer_bridge.__file__).read_text(encoding="utf-8")
    vtk_src = _vtk_text_style_source()

    def _titles(src, fname):
        tree = ast.parse(src)
        fn = _func(tree, fname)
        out = []
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getText"
            ):
                out = [
                    a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ]
        return out

    fast_titles = _titles(fast_src, "_prompt_annotation_text")
    vtk_titles = _titles(vtk_src, "on_left_button_press")
    assert fast_titles and vtk_titles
    assert fast_titles[:2] == vtk_titles[:2], (
        f"FAST asks {fast_titles[:2]} but Advanced asks {vtk_titles[:2]} — "
        "the two backends must word the prompt identically"
    )


if __name__ == "__main__":   # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
