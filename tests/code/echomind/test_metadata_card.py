"""Guard: case metadata is the FIRST CARD INSIDE the conversation (2026-08-08).

Replaces test_metadata_panel.py, which pinned the third-column architecture that was
rejected the same day it shipped. Case metadata is conversation CONTEXT: it belongs in
the scroll area with the other cards, not in a sidebar that costs the report horizontal
space for the whole session.

Four properties are load-bearing and each has a test here:

  1. NOTHING adds metadata to a layout outside the scroll area — not the page's
     horizontal root (the rejected sidebar), and not the vertical history/composer
     stack either, because that stack feeds the composer height maths and growing it
     is what pushed the action row off-window before.
  2. The card survives a re-render. SEVEN call sites clear the history; the card
     survives because ChatHistory preserves it like the tail spacer, not because each
     site remembers to put it back. A render path added tomorrow inherits that.
  3. Editing is one sheet, one Save, keyed by the path it writes. The panel indexed
     its editors by LABEL and committed by PATH — every edit raised KeyError inside a
     Qt slot and vanished. And a focus-out commit puts half-finished corrections into
     storage.
  4. A physician's correction survives re-detection, and clearing corrections restores
     detection rather than blanking the field. That is the entire reason the store has
     two layers.
"""

import ast
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_CARD = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "metadata_panel.py")
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
_WIDGETS = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_widgets.py")
_META = os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py")


def _read(p):
    with open(p, encoding="utf-8-sig") as fh:
        return fh.read()


def _class_src(src, name):
    """Source of one class. `root = QHBoxLayout(self)` appears in more than one page
    class, so every layout assertion has to be scoped or it tests the wrong widget."""
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.ClassDef) and n.name == name)
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def _method_src(src, cls_name, fn_name):
    """Source of one METHOD. `clear` is defined on several widgets in this module;
    a name-keyed walk would silently test whichever came last."""
    lines = src.split("\n")
    cls = next(n for n in ast.parse(src).body
               if isinstance(n, ast.ClassDef) and n.name == cls_name)
    fn = next(n for n in cls.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == fn_name)
    return "\n".join(lines[fn.lineno - 1:fn.end_lineno])


def _functions(src):
    lines = src.split("\n")
    return {n.name: "\n".join(lines[n.lineno - 1:n.end_lineno])
            for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _consts():
    """The declarative tables, executed for real. They are pure literals plus one
    comprehension, so no Qt import is needed to check them."""
    src = _read(_CARD)
    seg = src[src.index("REGION_LABEL ="):src.index("_BTN_CSS =")]
    ns = {}
    exec(compile(seg, _CARD, "exec"), ns)
    return ns


# ── 1. it must not take space outside the conversation ───────────────────────

def test_the_metadata_sidebar_is_gone():
    """The rejected build. A permanent third column takes horizontal space from the
    report for the whole session and frames the case facts as chrome standing outside
    the dialogue."""
    src = _read(_PAGES)
    assert "ChatMetadataPanel" not in src
    assert "meta_panel" not in src
    page = _class_src(src, "OneChatPage")
    i = page.index("root = QHBoxLayout(self)")
    assert "meta" not in page[i:i + 300], (
        "something is still being added to the page's horizontal root layout"
    )


def test_the_card_does_not_join_the_vertical_stack_either():
    """That stack drives the composer height calculation; growing it is what pushed
    the action row out of the window before."""
    page = _class_src(_read(_PAGES), "OneChatPage")
    j = page.index("right = QVBoxLayout()")
    assert "meta" not in page[j:j + 300]


def test_the_card_is_pinned_as_the_first_card_of_the_conversation():
    page = _class_src(_read(_PAGES), "OneChatPage")
    assert "self.history.set_lead_widget(self.meta_card)" in page, (
        "the card is not inside the chat scroll area"
    )
    assert "CaseMetadataCard(self.history.container)" in page, (
        "the card is not parented to the conversation's container"
    )


def test_a_card_failure_cannot_break_the_chat_page():
    page = _class_src(_read(_PAGES), "OneChatPage")
    i = page.index("from .metadata_panel import CaseMetadataCard")
    seg = page[max(0, i - 200):i + 500]
    assert "try:" in seg and "except Exception" in seg
    assert "self.meta_card = None" in seg, "no fallback when the card cannot be built"


# ── 2. it survives every re-render, without any of them knowing ──────────────

def test_the_history_pins_the_lead_widget_at_the_top():
    body = _method_src(_read(_WIDGETS), "ChatHistory", "set_lead_widget")
    assert "insertWidget(0" in body, "the pinned widget is not placed first"
    assert "removeWidget" in body, "re-pinning would leave the previous card behind"


def test_clear_preserves_the_pinned_card():
    """`clear()` deletes every widget it finds. Without an exemption the card is
    destroyed on the first chat switch and every later refresh writes to a deleted
    C++ object."""
    body = _method_src(_read(_WIDGETS), "ChatHistory", "clear")
    assert "_lead_widget" in body, "clear() does not know about the pinned card"
    assert "continue" in body, "the pinned card is deleted along with the messages"
    assert "insertWidget(0" in body, (
        "the card is not returned to the top once the messages above it are gone"
    )


def test_no_render_path_has_to_re_add_the_card():
    """THE reason this lives in ChatHistory. Seven call sites clear the history; if
    each had to remember to re-add the card, the eighth would forget."""
    src = _read(_PAGES)
    assert src.count("self.history.clear()") >= 5, (
        "the render paths moved — re-check that the card still survives all of them"
    )
    fns = _functions(src)
    for name in ("_load_from_db_and_render", "_open_session", "_new_chat"):
        assert "set_lead_widget" not in fns.get(name, ""), (
            f"{name} re-pins the card by hand; ChatHistory already guarantees it"
        )


def test_the_card_is_bound_when_the_physician_switches_chat():
    fns = _functions(_read(_PAGES))
    assert "_sync_metadata_card" in fns["_open_session"], (
        "switching chat leaves the card showing the previous patient — which is worse "
        "than showing nothing"
    )


def test_the_card_is_bound_when_reporting_mints_a_chat():
    fns = _functions(_read(_PAGES))
    assert "_sync_metadata_card" in fns["_ensure_local_session"]


def test_binding_is_fully_swallowed():
    body = _functions(_read(_PAGES))["_sync_metadata_card"]
    assert "try:" in body and "except Exception" in body
    assert 'getattr(self, "meta_card", None)' in body, "assumes the attribute exists"


def test_an_unbound_card_shows_nothing_and_costs_nothing():
    """A hidden widget takes no room in a QVBoxLayout, so a chat with no case behind
    it is not charged for an empty card."""
    body = _method_src(_read(_CARD), "CaseMetadataCard", "_refresh")
    assert "setVisible(False)" in body and "setVisible(True)" in body


# ── 3. editing: one sheet, one save, keyed by the path it writes ─────────────

def test_the_card_has_an_edit_action():
    src = _read(_CARD)
    assert 'setText("Edit")' in src, "the physician cannot correct anything"
    assert "class CaseMetadataDialog" in src


def test_edits_are_committed_once_not_per_field():
    """A focus-out commit writes a half-finished correction to storage, and saves a
    typo'd field before the physician has looked at the rest of the sheet."""
    assert "editingFinished" not in _read(_CARD)


def test_the_editor_is_keyed_by_the_path_it_writes():
    """The panel's real bug: `_editors` was keyed by LABEL and `_commit` looked up by
    PATH, so every edit raised KeyError inside a Qt slot and was silently lost."""
    src = _read(_CARD)
    assert "self._edits[user_path] = ed" in src
    assert "self._edits.items()" in _method_src(src, "CaseMetadataDialog", "_save")


def test_confirming_detection_is_not_recorded_as_an_edit():
    """Typing exactly what was detected must leave the field marked `auto`. Otherwise
    the provenance readout — the whole point of the two layers — starts lying."""
    body = _method_src(_read(_CARD), "CaseMetadataDialog", "_save")
    assert "clear_user_field" in body and "set_user_field" in body
    assert "same" in body, "no comparison against the detected value"


def test_every_editable_field_can_find_its_detected_value():
    ns = _consts()
    for label, auto_path, user_path, editable in ns["FIELDS"]:
        if editable:
            assert ns["AUTO_FOR_USER"].get(user_path) == auto_path, (
                f"{label}: _save cannot tell whether the typed value equals detection"
            )


def test_no_user_path_indexes_a_list():
    """THE corruption guard. `auto` keeps study fields in studies[0], but the user
    layer is dict-only — a numeric path segment would create {"studies": {"0": ...}}."""
    for label, auto_path, user_path, editable in _consts()["FIELDS"]:
        if not user_path:
            assert not editable, f"{label} is editable but has nowhere to save"
            continue
        for part in user_path.split("."):
            assert not part.isdigit(), (
                f"{label} writes to {user_path!r}, which indexes a list — "
                "set_user_field would corrupt the user layer"
            )


def test_every_editable_field_has_a_user_path():
    fields = _consts()["FIELDS"]
    editable = [f for f in fields if f[3]]
    assert editable, "nothing is editable — the card would be read-only"
    assert all(f[2] for f in editable)


def test_the_fields_cover_what_was_asked_for():
    ns = _consts()
    labels = {f[0] for f in ns["FIELDS"]}
    for want in ("Patient ID", "Sex", "Service", "Modality", "Body part",
                 "Study description"):
        assert want in labels, f"the card does not show {want!r}"
    assert ns["REGION_LABEL"]


def test_every_field_is_actually_placed_on_the_card():
    """The card lays out from an explicit row table. Adding a field to FIELDS without
    placing it would store the value and never show it."""
    ns = _consts()
    placed = [x for row in ns["LAYOUT_ROWS"] for x in row]
    expected = {f[0] for f in ns["FIELDS"]} | {ns["REGION_LABEL"]}
    assert set(placed) == expected, (
        f"unplaced or unknown: {sorted(set(placed) ^ expected)}"
    )
    assert len(placed) == len(set(placed)), "a field is placed twice"


def test_the_long_fields_get_a_whole_row():
    """MEASURED: a paired value column is ~108 px. "04 Chest Abd Pelvis" and a
    two-service Persian booking do not fit in 108 px — they wrapped and were clipped."""
    ns = _consts()
    full_width = {row[0] for row in ns["LAYOUT_ROWS"] if len(row) == 1}
    for label in ("Service", "Study description", ns["REGION_LABEL"]):
        assert label in full_width, f"{label!r} is still sharing a line"


def test_short_fields_still_pair_up():
    """Giving everything its own row would double the card's height for no gain."""
    ns = _consts()
    assert sum(1 for row in ns["LAYOUT_ROWS"] if len(row) == 2) >= 3


def test_a_wrapped_value_reserves_the_height_it_needs():
    """A word-wrapped QLabel in a grid inside a scroll area is sized from a hint
    computed before its real width is known, so the second line gets clipped."""
    src = _read(_CARD)
    i = src.index("class _FitLabel")
    seg = src[i:src.index("\nclass ", i + 10)]
    assert "heightForWidth" in seg, "nothing re-measures the wrapped text"
    assert "setMinimumHeight" in seg, "the measured height is never reserved"
    assert "resizeEvent" in seg, "it is never re-measured when the column changes width"
    assert "setWordWrap(True)" in seg, "heightForWidth returns -1 without word wrap"
    assert "!= self.minimumHeight()" in seg, (
        "no equality guard — setMinimumHeight relayouts, which would recurse"
    )


def test_keys_and_values_share_one_label_implementation():
    """Both clip for the same reason. Two implementations means fixing it twice, and
    the second one gets forgotten."""
    src = _read(_CARD)
    assert 'key = _FitLabel("metaKey")' in src
    assert '_FitLabel("metaVal", rich=True)' in src
    assert "class _ValueLabel" not in src, "the old single-purpose class is still here"


def test_nothing_may_force_a_horizontal_scrollbar_over_the_chat():
    """A word-wrapped QLabel reports its LONGEST WORD as its minimum width. Left
    alone, the study description and a two-service Persian booking drag the card wider
    than the conversation."""
    src = _read(_CARD)
    i = src.index("class _FitLabel")
    seg = src[i:src.index("\nclass ", i + 10)]
    assert "setMinimumWidth(40)" in seg, "no floor, or a floor big enough to overflow"
    assert "setColumnMinimumWidth(1," not in src, (
        "a minimum width on a value column only bites when the pane is narrow, which "
        "is exactly when wrapping is the right answer"
    )


def test_the_card_may_grow_but_not_be_squeezed():
    src = _read(_CARD)
    assert "QSizePolicy.Preferred, QSizePolicy.Minimum" in src, (
        "a Maximum vertical policy lets the layout squeeze the card below its hint, "
        "which clips the last row"
    )


def test_regions_are_picked_from_the_canonical_list_not_typed():
    """A typo'd region is worse than none: it selects nothing and looks set."""
    src = _read(_CARD)
    i = src.index("class RegionPickerDialog")
    seg = src[i:src.index("\nclass ", i + 10)]
    assert "REGION_KEYS" in seg, "the picker does not use the canonical vocabulary"
    assert "QCheckBox" in seg, "regions are free text somewhere"


# ── 4. the two-layer contract, through real storage ─────────────────────────

def test_clearing_edits_keeps_detection():
    """'Clear my edits' must restore what was detected, never blank the record."""
    from modules.EchoMind import session_metadata as sm
    sid = "__card_guard__"
    try:
        sm.save_auto(sid, sm.build_auto_from_context(
            study={"study_uid": "1.2.3", "body_part": "CHEST"}, modality_selected="CT"))
        sm.set_user_field(sid, "case.body_part", "SHOULDER")
        assert sm.load(sid)["case"]["body_part"] == "SHOULDER"
        sm.clear_user_layer(sid)
        rec = sm.load(sid)
        assert "body_part" not in (rec.get("case") or {}), "the edit survived a clear"
        assert rec["studies"][0]["body_part"] == "CHEST", "detection was destroyed too"
    finally:
        sm.delete(sid)


def test_clear_user_layer_exists_and_touches_only_the_user_layer():
    body = _functions(_read(_META))["clear_user_layer"]
    assert "user={}" in body
    assert "auto" not in body, "clearing edits must not write the auto layer"


# ── 5. the step-1 boundary still holds ───────────────────────────────────────

def test_the_card_does_not_reach_a_prompt():
    """Showing metadata is step 1. Feeding it to the model is a later, separately
    guarded step — gated on measuring detection accuracy, which on the first real
    chats produced zero regions."""
    for rel in ("modules/EchoMind/viewer_chat/openai_reporter.py",
                "modules/EchoMind/viewer_chat/openai_parallel_backend.py"):
        assert "metadata_panel" not in _read(os.path.join(_ROOT, rel))
        assert "session_metadata" not in _read(os.path.join(_ROOT, rel))
