"""Guard: the metadata card must not clip, overlap, or overflow the conversation.

Text assertions cannot catch a layout bug. This one shipped and had to be reported from
a screenshot: "04 Chest Abd Pelvis" was cut off after "Abd", and the Persian service
text was truncated, because a word-wrapped QLabel in a QGridLayout inside a scroll area
does not get its `heightForWidth` honoured — the row is sized from a hint computed
before the real column width is known.

A NOTE ON THE NUMBERS. The offscreen Qt platform on this workstation loads **zero font
families**, so every glyph is a wide fallback box: "Study description" measures 204 px
here against roughly 95 px in real Segoe UI. Absolute pixel assertions would therefore
be meaningless. Everything below is RELATIVE and stays true under any font:

  * needed height vs given height        (clipping)
  * label rectangle vs label rectangle   (overlap)
  * card minimum width vs viewport       (horizontal scrollbar over the chat)

If anything, the missing font makes this test HARSHER than reality — it is measuring a
card whose text is twice as wide as the physician will ever see.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication          # noqa: E402

from modules.EchoMind import session_metadata as sm  # noqa: E402

SID = "__geom_guard__"

#: The real study 53516, including the two-service Persian booking and the
#: Chest/Abdomen/Pelvis protocol — the exact content that clipped.
SERVICES = [
    {"Service": "سی تی اسکن قفسه سینه با و بدون کنتراست", "Qty": 1},
    {"Service": "سی تی اسکن شکم و لگن با و بدون تزریق(کلیه ومجاری ادراری)", "Qty": 1},
]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def built(app):
    """A card pinned in a real ChatHistory, as OneChatPage builds it. No adjustSize():
    that papers over exactly the bad size hint this test exists to catch."""
    from modules.EchoMind.viewer_chat.ai_chat_widgets import ChatHistory
    from modules.EchoMind.viewer_chat.metadata_panel import CaseMetadataCard

    sm.save_auto(SID, sm.build_auto_from_context(
        patient={"patient_id": "53516", "sex": "M", "age": "019Y"},
        study={"study_uid": "1.2.3", "body_part": "CHEST", "study_date": "20260806"},
        dicom_facts={"protocol_name": "04 Chest Abd Pelvis",
                     "body_parts": ["CHEST", "ABDOMEN"]},
        reception_services=SERVICES))

    made = []

    def build(width):
        hist = ChatHistory()
        card = CaseMetadataCard(hist.container)
        hist.set_lead_widget(card)
        card.bind(SID)
        hist.resize(width, 620)
        hist.show()
        for _ in range(4):
            app.processEvents()
        made.append(hist)
        return hist, card

    yield build
    for h in made:
        h.close()
    sm.delete(SID)


WIDTHS = [1100, 820, 640, 520, 430]


def _labels(card):
    out = []
    for name, lbl in list(card._vals.items()) + list(card._keys.items()):
        tl = lbl.mapTo(card, lbl.rect().topLeft())
        out.append((name, lbl, tl.x(), tl.y(), lbl.width(), lbl.height()))
    return out


@pytest.mark.parametrize("width", WIDTHS)
def test_no_label_is_clipped(built, width):
    """The reported bug. A label given less height than its wrapped text needs shows
    part of a line and the physician cannot tell that anything is missing."""
    _hist, card = built(width)
    bad = []
    for name, lbl, _x, _y, w, h in _labels(card):
        if w <= 1:
            continue
        need = lbl.heightForWidth(w)
        if need > h:
            bad.append(f"{name}: needs {need}px, has {h}px (width {w})")
    assert not bad, "clipped at window %dpx:\n  %s" % (width, "\n  ".join(bad))


@pytest.mark.parametrize("width", WIDTHS)
def test_no_two_labels_overlap(built, width):
    """Compared as RECTANGLES: two fields sharing a row have the same y range on
    purpose, so a y-only check would call every paired row a collision."""
    _hist, card = built(width)
    items = _labels(card)
    bad = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            n1, _l1, x1, y1, w1, h1 = items[i]
            n2, _l2, x2, y2, w2, h2 = items[j]
            if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                bad.append(f"{n1} overlaps {n2}")
    assert not bad, "overlap at window %dpx: %s" % (width, bad)


@pytest.mark.parametrize("width", WIDTHS)
def test_the_card_never_forces_a_horizontal_scrollbar(built, width):
    """A card wider than the pane puts a horizontal scrollbar under the WHOLE
    conversation, not just the card. Wrapping is always the better answer."""
    hist, card = built(width)
    viewport = hist.scroll.viewport().width()
    need = card.minimumSizeHint().width()
    assert need <= viewport, (
        f"at a {width}px window the card demands {need}px but the conversation has "
        f"{viewport}px — and the offscreen font makes text ~2x wider than real, so "
        f"this is the harsh case, not the typical one"
    )


def test_the_long_values_get_more_room_than_the_paired_ones(built):
    """The fix, stated as a measurement rather than as a layout table: a full-width row
    must actually be wider than a half-width one."""
    _hist, card = built(820)
    paired = card._vals["Patient ID"].width()
    full = card._vals["Service"].width()
    assert full > paired * 1.5, (
        f"Service got {full}px against a paired field's {paired}px — it is still "
        "sharing a line, which is what clipped the Persian booking"
    )


def test_the_card_still_fits_a_narrow_pane_without_losing_content(built):
    """Everything must remain readable at 430px, not merely un-clipped: a value column
    squeezed to nothing is 'not clipped' and still useless."""
    _hist, card = built(430)
    for name in ("Service", "Study description", "Region(s)"):
        assert card._vals[name].width() >= 40, f"{name} collapsed"
        assert card._vals[name].height() > 0
