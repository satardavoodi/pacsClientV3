"""Per-chat case metadata, as the FIRST CARD INSIDE the conversation.

STEP 1 OF REGION GATING. The gate must not guess. Before anything selects a
region-specific prompt, the physician has to be able to SEE what EchoMind believes
about this study and correct it. A gate driven by invisible metadata is a gate nobody
can debug — and a wrong region silently deletes the reporting rules for the anatomy
that was actually imaged.

WHY A CARD AND NOT A SIDEBAR (revised 2026-08-08, the same day the sidebar shipped).
Case metadata is conversation CONTEXT, so it belongs in the conversation. The first
build made it a permanent third column, and that was wrong twice over: it took
horizontal space away from the report for the whole session, and it framed the case
facts as chrome standing outside the dialogue rather than as its opening statement.
As a card it scrolls with the conversation, borrows the bubble's own visual language,
and costs nothing once scrolled past.

WHY IT SURVIVES A RE-RENDER. Seven call sites clear the chat history. Rather than
teach all seven about metadata, `ChatHistory` pins the card as a LEAD WIDGET at index
0 and preserves it across `clear()` — exactly as it already preserves the tail spacer.
One place to get right instead of seven, and a new render path inherits the behaviour
for free.

WHAT IT SHOWS. The EFFECTIVE record: detection with the physician's edits applied.
Every value carries its provenance inline — `auto` or `you` — because "the scanner
said so" and "I typed it" carry very different weight when a report comes out wrong.

EDITING IS ONE SHEET, ONE SAVE. The panel committed each field on focus-out, which
meant a half-finished correction could reach storage and a typo'd field was saved
before the physician had looked at the rest. The dialog collects everything and
writes once.

WHAT IT DELIBERATELY DOES NOT DO. It does not reach a prompt. Wiring metadata into
report generation is the next, separately-guarded step, gated on measuring detection
accuracy against real studies first — the first real chats produced ZERO detected
regions, so that measurement is not optional.
"""

from __future__ import annotations

import html
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .ai_chat_config import CLR_ACCENT, CLR_BG_PANEL, CLR_BORDER, CLR_TEXT  # noqa: F401

logger = logging.getLogger(__name__)

#: The card is a bubble, so it obeys the same width discipline as one: wide enough to
#: put two fields on a line, never so wide it becomes a banner.
CARD_MAX_WIDTH = 720

REGION_LABEL = "Region(s)"

#: (label, path in the AUTO layer, path in the USER layer, editable)
#:
#: The two paths differ for study-level fields on purpose. `auto` keeps them inside
#: `studies[0]`, but `set_user_field` builds dicts and `deep_merge` does not merge
#: LISTS — writing "studies.0.body_part" would produce {"studies": {"0": ...}} and
#: quietly corrupt the layer. So a physician's correction lands in `case.*`, and the
#: effective value is "user if set, else auto".
FIELDS = [
    ("Patient ID",        "patient.patient_id",           None,                      False),
    ("Sex",               "patient.sex",                  "patient.sex",             True),
    ("Age",               "patient.age",                  None,                      False),
    ("Service",           "reception.service",            "reception.service",       True),
    ("Modality",          ("case.modality_selected",
                           "studies.0.modality"),        "case.modality_selected",  True),
    ("Body part",         "studies.0.body_part",          "case.body_part",          True),
    ("Study description", "studies.0.study_description",  "case.study_description",  True),
    ("Study date",        "studies.0.study_date",         None,                      False),
]

#: How the card lays out. A two-name row puts both fields on one line; a ONE-name row
#: gives that field the full width.
#:
#: MEASURED, not guessed: in the paired layout a value column is ~108 px. "04 Chest Abd
#: Pelvis" and a two-service Persian booking do not fit in 108 px, so they wrapped and
#: were clipped. The short scalars still pair up — that is what keeps the card compact —
#: and only the three genuinely long fields take a whole row.
#:
#: A test asserts every FIELDS label plus the region label appears here exactly once, so
#: adding a field cannot silently hide it.
LAYOUT_ROWS = [
    ("Patient ID", "Modality"),
    ("Sex",        "Body part"),
    ("Age",        "Study date"),
    ("Study description",),
    ("Service",),
    (REGION_LABEL,),
]

AUTO_FOR_USER = {u: a for (_l, a, u, _e) in FIELDS if u}

_BTN_CSS = """
    QToolButton {
        color: #dcdcdc; padding: 2px 8px; border: 1px solid #3a3a3a;
        border-radius: 6px; background: rgba(255,255,255,0.03);
    }
    QToolButton:hover { background: rgba(255,255,255,0.08); }
    QToolButton:pressed { background: rgba(255,255,255,0.12); }
"""

#: Lifted verbatim from MessageBubble so the card cannot drift away from the bubbles
#: it sits above.
_CARD_CSS = """
    QLabel#who { color: #ffd48a; font-weight: 600; padding-left: 6px; font-size: 12px; }
    QFrame#bubbleBox { background: #2b2b2b; border: 1px solid #3a3a3a; border-radius: 12px; }
    QLabel#metaKey { color: #9a9a9a; font-size: 11px; }
    QLabel#metaVal { color: #e6e6e6; font-size: 12px; }
"""


def _dig_first(rec: dict, paths):
    """First non-empty value along a chain of candidate paths.

    Modality needs this. `case.modality_selected` is the physician's CHOICE and is
    only set once he opens the Modalities picker, but the scanner already said "CT" --
    so a card reading only the choice reports "not detected" for a study whose
    modality was never in doubt.
    """
    if isinstance(paths, str):
        paths = (paths,)
    for p in paths:
        if not p:
            continue
        v = _dig(rec, p)
        if v not in (None, "", [], {}):
            return v
    return None


def _dig(rec: dict, path: str):
    """Read a dotted path, tolerating 'studies.0.x' and any missing level."""
    cur = rec
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
                continue
            except (ValueError, IndexError):
                return None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt(value, edited: bool, accent: bool = False) -> str:
    """A value with its provenance attached, as one line of rich text.

    Inline rather than in its own column: a provenance column costs width on every
    row, and width is the thing the sidebar was taking away from the conversation.
    """
    if value in (None, "", [], "unknown"):
        return '<span style="color:#7a7a7a;">not detected</span>'
    colour = "#ffd48a" if accent else "#e6e6e6"
    word, mark_colour = ("you", "#4CAF50") if edited else ("auto", "#7a7a7a")
    return (f'<span style="color:{colour};">{html.escape(str(value))}</span>'
            f'&nbsp;<span style="color:{mark_colour};font-size:9px;">{word}</span>')


class _FitLabel(QLabel):
    """A wrapped label that reserves the height it actually needs — used for BOTH the
    keys and the values, because both failure modes have the same cause.

    CLIPPING. A word-wrapped QLabel inside a QGridLayout inside a scroll area does not
    get its `heightForWidth` honoured: the row is sized from a hint computed before the
    real column width is known, so a label that turns out to need two lines is given one
    line of row and the rest is cut off. That is what truncated "04 Chest Abd Pelvis"
    after "Abd" and clipped the Persian service text.

    Re-measuring on every resize and pinning the answer as a MINIMUM HEIGHT is the
    standard fix. Only the height is pinned, so the relayout it triggers cannot change
    the width that produced it, and the equality guard stops it recursing.

    HORIZONTAL OVERFLOW. A word-wrapped QLabel reports its LONGEST WORD as its minimum
    width. Left alone, "Study description" and a two-service Persian booking drag the
    card wider than the conversation and raise a horizontal scrollbar over the whole
    chat. Wrapping — even mid-phrase, even on a key — is strictly better than that, so
    the floor here is small and deliberate: enough that a column cannot vanish, not
    enough to push the card past the pane.
    """

    def __init__(self, object_name: str, *, rich: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        if rich:
            self.setTextFormat(Qt.RichText)
            self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setWordWrap(True)            # required: heightForWidth returns -1 without it
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setMinimumWidth(40)

    def setText(self, text):              # noqa: D102 - Qt override
        super().setText(text)
        self._fit()

    def resizeEvent(self, event):         # noqa: D102 - Qt override
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        w = self.width()
        if w <= 1:
            return                        # not laid out yet; resizeEvent will call back
        h = self.heightForWidth(w)
        if h > 0 and h != self.minimumHeight():
            self.setMinimumHeight(h)


class RegionPickerDialog(QDialog):
    """Checkboxes over the canonical vocabulary — never a free-text region.

    A typo'd region is worse than no region: it selects nothing and looks set. A study
    may legitimately cover several (shoulder AND knee), so this is multi-select.
    """

    def __init__(self, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Regions for this study")
        self.resize(340, 460)
        from modules.EchoMind.session_metadata import REGION_KEYS

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Tick every region this study covers:"))
        inner = QWidget()
        grid = QVBoxLayout(inner)
        grid.setSpacing(2)
        self._boxes = {}
        for key in REGION_KEYS:
            cb = QCheckBox(key.replace("_", " "))
            cb.setChecked(key in (selected or []))
            self._boxes[key] = cb
            grid.addWidget(cb)
        grid.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def chosen(self):
        return [k for k, cb in self._boxes.items() if cb.isChecked()]


class CaseMetadataDialog(QDialog):
    """The Edit action. One sheet, one Save.

    Every box shows what the physician typed; the greyed placeholder shows what was
    detected. Emptying a box therefore means "go back to what you found", which is the
    same rule for every field including regions — there is deliberately no way to
    assert "this study covers no region at all", because in three months of real cases
    that has never been the intent and a silent empty override would be unreadable.
    """

    def __init__(self, sid: str, parent=None):
        super().__init__(parent)
        from modules.EchoMind import session_metadata as sm

        self._sid = sid
        self._sm = sm
        self.setWindowTitle("Case metadata")
        self.setMinimumWidth(440)

        self._auto, self._user = sm.load_layers(sid)
        eff = sm.merge_layers(self._auto, self._user)
        self._regions = list((eff.get("case") or {}).get("regions") or [])
        self._edits: dict = {}          # user_path -> QLineEdit
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        hint = QLabel("What you type here overrides what was detected. "
                      "Empty a box to fall back to detection.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9a9a9a;")
        outer.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        row = 0
        for label, auto_path, user_path, editable in FIELDS:
            grid.addWidget(QLabel(label), row, 0, Qt.AlignRight | Qt.AlignVCenter)
            detected = _dig_first(self._auto, auto_path)
            if editable:
                ed = QLineEdit()
                uval = _dig(self._user, user_path)
                if uval not in (None, ""):
                    ed.setText(str(uval))
                ed.setPlaceholderText(
                    "not detected" if detected in (None, "") else f"detected: {detected}")
                self._edits[user_path] = ed
                grid.addWidget(ed, row, 1)
            else:
                ro = QLabel("—" if detected in (None, "") else str(detected))
                ro.setStyleSheet("color:#9a9a9a;")
                grid.addWidget(ro, row, 1)
            row += 1

        grid.addWidget(QLabel(REGION_LABEL), row, 0, Qt.AlignRight | Qt.AlignTop)
        rr = QHBoxLayout()
        self.lbl_regions = QLabel(self._region_text())
        self.lbl_regions.setWordWrap(True)
        rr.addWidget(self.lbl_regions, 1)
        btn_pick = QPushButton("Choose…")
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.clicked.connect(self._pick_regions)
        rr.addWidget(btn_pick, 0)
        grid.addLayout(rr, row, 1)

        outer.addLayout(grid)

        bar = QHBoxLayout()
        btn_clear = QPushButton("Clear my edits")
        btn_clear.setToolTip(
            "Remove every value you set here and fall back to what was detected")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(self._clear_all)
        bar.addWidget(btn_clear, 0)
        bar.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        bar.addWidget(bb, 0)
        outer.addLayout(bar)

    def _region_text(self) -> str:
        return (", ".join(r.replace("_", " ") for r in self._regions)
                if self._regions else "none")

    def _pick_regions(self):
        dlg = RegionPickerDialog(self._regions, self)
        if dlg.exec() == QDialog.Accepted:
            self._regions = dlg.chosen()
            self.lbl_regions.setText(self._region_text())

    def _save(self):
        """Write the whole sheet. A value equal to detection is stored as NO edit —
        otherwise confirming what the scanner said would mark the field `you` and make
        the provenance readout lie."""
        sm = self._sm
        try:
            for user_path, ed in self._edits.items():
                text = ed.text().strip()
                detected = _dig_first(self._auto, AUTO_FOR_USER.get(user_path, ""))
                same = detected is not None and text == str(detected).strip()
                if not text or same:
                    sm.clear_user_field(self._sid, user_path)
                else:
                    sm.set_user_field(self._sid, user_path, text)

            auto_regions = list((self._auto.get("case") or {}).get("regions") or [])
            if self._regions and self._regions != auto_regions:
                sm.set_user_field(self._sid, "case.regions", self._regions)
            else:
                sm.clear_user_field(self._sid, "case.regions")
        except Exception as exc:
            logger.warning("[EchoMind-meta] could not save case metadata: %s", exc)
        self.accept()

    def _clear_all(self):
        """Drop the whole user layer. Detection is untouched — that is the point of
        keeping the two layers apart."""
        try:
            self._sm.clear_user_layer(self._sid)
        except Exception as exc:
            logger.warning("[EchoMind-meta] could not clear edits: %s", exc)
            return
        self.accept()


class CaseMetadataCard(QWidget):
    """The opening card of every EchoMind chat. Owns no state — it renders whatever
    `session_metadata` holds for the bound chat."""

    metadataChanged = Signal(str)          # sid

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sid: Optional[str] = None
        self._vals: dict = {}              # label -> value QLabel
        self._keys: dict = {}              # label -> key QLabel
        # Minimum, not Maximum: the card may GROW past its hint (a two-line service
        # name) but must never be squeezed below it, which is what clips a row.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._build()
        # Nothing to say until a chat is bound. Hidden widgets take no room in a
        # QVBoxLayout, so an unbound card costs the conversation zero pixels.
        self.setVisible(False)

    # ── construction ─────────────────────────────────────────────────────────
    def _build(self):
        outer = QVBoxLayout(self)
        # The same 8 px top gap add_bubble gives every wrap, so the card sits in the
        # conversation's rhythm rather than crowding the first message.
        outer.setContentsMargins(6, 8, 6, 0)
        outer.setSpacing(4)

        who = QLabel("Case")
        who.setObjectName("who")
        outer.addWidget(who, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.box = QFrame(self)
        self.box.setObjectName("bubbleBox")
        self.box.setMaximumWidth(CARD_MAX_WIDTH)
        box_lay = QVBoxLayout(self.box)
        box_lay.setContentsMargins(12, 10, 12, 8)
        box_lay.setSpacing(8)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        grid.setColumnMinimumWidth(2, 18)
        # Deliberately NO minimum width on the value columns. The stretch above already
        # hands them every spare pixel, so a floor only bites when the pane is narrow —
        # and there the right answer is to WRAP (which _ValueLabel now sizes correctly),
        # not to push the card wider than the conversation and raise a horizontal
        # scrollbar over the whole chat.

        for row, spec in enumerate(LAYOUT_ROWS):
            if len(spec) == 2:
                self._add_cell(grid, row, 0, spec[0])
                self._add_cell(grid, row, 3, spec[1])
            else:
                self._add_cell(grid, row, 0, spec[0], col_span=4)
        box_lay.addLayout(grid)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        footer.addStretch(1)
        self.btnEdit = QToolButton(self.box)
        self.btnEdit.setText("Edit")
        self.btnEdit.setToolTip("Correct the case metadata for this chat")
        self.btnEdit.setCursor(Qt.PointingHandCursor)
        self.btnEdit.setAutoRaise(True)
        self.btnEdit.setStyleSheet(_BTN_CSS)
        self.btnEdit.clicked.connect(self._open_editor)
        footer.addWidget(self.btnEdit, 0, Qt.AlignRight)
        box_lay.addLayout(footer)

        # No AlignLeft: with it the frame shrinks to its hint and the value columns
        # collapse. It fills the conversation width instead, capped at CARD_MAX_WIDTH.
        outer.addWidget(self.box, 0)
        self.setStyleSheet(_CARD_CSS)

    def _add_cell(self, grid: QGridLayout, row: int, col: int, label: str,
                  col_span: int = 1):
        key = _FitLabel("metaKey")
        key.setAlignment(Qt.AlignRight | Qt.AlignTop)
        key.setText(label)
        grid.addWidget(key, row, col, Qt.AlignRight | Qt.AlignTop)
        val = _FitLabel("metaVal", rich=True)
        grid.addWidget(val, row, col + 1, 1, col_span)
        self._keys[label] = key
        self._vals[label] = val

    # ── binding ──────────────────────────────────────────────────────────────
    def bind(self, sid: Optional[str]):
        """Point the card at a chat. Safe with None or an unknown sid."""
        self._sid = (sid or "").strip() or None
        self.refresh()

    def refresh(self):
        """Re-read from storage. Fully swallowed: metadata must never break the chat."""
        try:
            self._refresh()
        except Exception as exc:                       # pragma: no cover - defensive
            logger.warning("[EchoMind-meta] card refresh failed: %s", exc)
            self.setVisible(False)

    def _refresh(self):
        if not self._sid:
            self.setVisible(False)
            return

        from modules.EchoMind import session_metadata as sm

        auto, user = sm.load_layers(self._sid)
        eff = sm.merge_layers(auto, user)

        for label, auto_path, user_path, _editable in FIELDS:
            uval = _dig(user, user_path) if user_path else None
            val = uval if uval not in (None, "") else _dig_first(auto, auto_path)
            self._vals[label].setText(_fmt(val, uval not in (None, "")))

        regions = _dig(eff, "case.regions") or []
        self._vals[REGION_LABEL].setText(
            _fmt(", ".join(r.replace("_", " ") for r in regions) or None,
                 bool(_dig(user, "case.regions")), accent=True))

        self.setVisible(True)

    # ── the Edit action ──────────────────────────────────────────────────────
    def _open_editor(self):
        if not self._sid:
            return
        try:
            dlg = CaseMetadataDialog(self._sid, self)
        except Exception as exc:
            logger.warning("[EchoMind-meta] could not open the editor: %s", exc)
            return
        if dlg.exec() == QDialog.Accepted:
            self.refresh()
            self.metadataChanged.emit(self._sid)
