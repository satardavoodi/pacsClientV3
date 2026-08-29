"""The three questions Eagle Eye asks when it is not confident.

Thin by design: every one of them is a list, a reason line and OK/Cancel. All
the judgement about WHETHER to ask lives in ``resolver``; these only render the
question and return the answer, which is what keeps the state machine testable
without a running GUI.

Shared behaviour, because getting any of it wrong here is a clinical risk:
  * nothing is pre-selected unless there is a real suggestion to pre-select;
  * Cancel always means "do not open anything", never "use the first row";
  * the reason Eagle Eye is asking is always shown, so the reader can tell a
    genuinely ambiguous study from a mislabelled one.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout,
)

from .protocols import Protocol, ProtocolDetection
from .resolver import Prompts
from .series_classifier import SeriesCandidate
from .study_catalog import StudyCandidate

logger = logging.getLogger(__name__)

_STYLE = """
QDialog { background: #1a202c; }
QLabel { color: #f7fafc; font-size: 13px; }
QLabel#eagleHint { color: #9ca3af; font-size: 12px; }
QListWidget {
    background: #0f1419; color: #f7fafc; border: 1px solid #2d3748;
    border-radius: 6px; padding: 4px; font-size: 13px;
}
QListWidget::item { padding: 7px 8px; border-radius: 4px; }
QListWidget::item:selected { background: #3182ce; color: #ffffff; }
QListWidget::item:disabled { color: #6b7280; }
QPushButton {
    background: #1a202c; color: #f7fafc; border: 1px solid #2d3748;
    border-radius: 4px; padding: 6px 16px; font-size: 12px;
}
QPushButton:hover { background: #2d3748; }
"""


class _ChoiceDialog(QDialog):
    """A titled list with a reason line, OK and Cancel."""

    def __init__(self, parent, title: str, question: str, hint: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        prompt = QLabel(question)
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("eagleHint")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _item: self._accept_if_selectable())
        layout.addWidget(self.list)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept_if_selectable)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.list.currentItemChanged.connect(self._sync_ok)
        self._sync_ok()

    def add_row(self, text: str, payload: Any, *, selectable: bool = True,
                preselect: bool = False) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, payload)
        if not selectable:
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
        self.list.addItem(item)
        if preselect and selectable:
            self.list.setCurrentItem(item)
        return item

    def _current_payload(self) -> Any:
        item = self.list.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsSelectable):
            return None
        return item.data(Qt.UserRole)

    def _sync_ok(self, *_args) -> None:
        ok = self.buttons.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(self._current_payload() is not None)

    def _accept_if_selectable(self) -> None:
        if self._current_payload() is not None:
            self.accept()

    def choice(self) -> Any:
        """Run the dialog; the payload of the chosen row, or None on Cancel."""
        if self.exec() != QDialog.Accepted:
            return None
        return self._current_payload()


class QtPrompts(Prompts):
    """The resolver's questions, rendered as dialogs."""

    def __init__(self, parent=None):
        self.parent = parent

    # -- study ------------------------------------------------------------

    def choose_study(self, studies: Sequence[StudyCandidate],
                     reason: str) -> Optional[StudyCandidate]:
        dialog = _ChoiceDialog(
            self.parent,
            "Eagle Eye — Select Study",
            "Which study should Eagle Eye analyze?",
            reason,
        )
        for study in studies:
            detail = study.detail
            text = f"{study.label}\n{detail}" if detail else study.label
            dialog.add_row(text, study, preselect=study.is_current)
        return dialog.choice()

    # -- protocol ---------------------------------------------------------

    def choose_protocol(self, protocols: Sequence[Protocol],
                        detection: ProtocolDetection) -> Optional[Protocol]:
        hint = f"Eagle Eye could not confidently determine the study protocol: {detection.reason}."
        if detection.protocol is not None:
            hint += f" Best guess: {detection.protocol.name} ({detection.confidence} confidence)."

        dialog = _ChoiceDialog(
            self.parent,
            "Eagle Eye — Select Protocol",
            "Which Eagle Eye protocol would you like to use?",
            hint,
        )
        for protocol in protocols:
            if protocol.implemented:
                slots = ", ".join(slot.label for slot in protocol.slots)
                text = f"{protocol.name}\n{slots}"
                dialog.add_row(text, protocol,
                               preselect=(protocol is detection.protocol))
            else:
                # Shown so the list reads as a roadmap, but not selectable: a
                # protocol with no capture pipeline would fail after the user
                # had already committed to it.
                dialog.add_row(f"{protocol.name}  (not available yet)",
                               protocol, selectable=False)
        return dialog.choice()

    # -- series -----------------------------------------------------------

    def choose_series(self, protocol: Protocol, slot_key: str,
                      options: Sequence[SeriesCandidate],
                      suggestion: Optional[SeriesCandidate],
                      reason: str) -> Optional[SeriesCandidate]:
        spec = protocol.slot(slot_key)
        label = spec.label if spec is not None else slot_key
        dialog = _ChoiceDialog(
            self.parent,
            f"Eagle Eye — Select {label}",
            f"Please select the correct series for {label}:",
            f"{reason} Only {spec.plane} series are listed."
            if spec is not None else reason,
        )
        for candidate in options:
            dialog.add_row(_series_row(candidate), candidate,
                           preselect=(candidate is suggestion))
        return dialog.choice()

    # -- messages ---------------------------------------------------------

    def report(self, title: str, message: str) -> None:
        logger.info("eagle_eye: %s - %s", title, message)
        try:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(self.parent)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle(title)
            box.setText(message)
            box.exec()
        except Exception as exc:
            logger.warning("eagle_eye: could not show '%s': %s", title, exc)


def _series_row(candidate: SeriesCandidate) -> str:
    """One series, with the metadata a reader needs to recognise it."""
    name = candidate.series_description or candidate.protocol_name or "(no description)"
    head = f"Series {candidate.series_number} — {name}"

    bits = []
    if candidate.plane:
        bits.append(candidate.plane)
    if candidate.slice_count:
        bits.append(f"{candidate.slice_count} images")
    if candidate.echo_time is not None:
        bits.append(f"TE {candidate.echo_time:g}")
    if candidate.repetition_time is not None:
        bits.append(f"TR {candidate.repetition_time:g}")
    return f"{head}\n{' · '.join(bits)}" if bits else head
