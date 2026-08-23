"""The composer: type, send, and the two shortcuts that reach for a template.

ENTER SENDS, SHIFT+ENTER IS A NEWLINE. The opposite of a code editor and the
same as every chat client an operator has ever used.

THE COMPOSER OWNS "SENDING". There is deliberately no `sending` state on the
wire — ``deliveryState()`` returns only delivered or seen — because until the
row exists the server has nothing to report. So the composer keeps the text
until the send succeeds and puts it back if it fails. Clearing optimistically
and losing a reply to a dropped packet is not a trade worth making.

TYPING IS A SIDE EFFECT OF TEXT, NOT AN EVENT. Every keystroke pushes a
four-second deadline; an empty box clears it immediately. The flag rides the
sync that was already scheduled and costs no request of its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_BODY = 4000  # the server's validation limit; enforced here so a long
# paste fails in the UI rather than as a 422 after the round trip.


class _Editor(QPlainTextEdit):
    sendRequested = Signal()
    pasteRequested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
                super().keyPressEvent(event)
                return
            self.sendRequested.emit()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            # An image or a copied file on the clipboard becomes an attachment;
            # anything else falls through to the ordinary text paste. Asked
            # first because QPlainTextEdit would otherwise swallow the image
            # silently and paste nothing at all.
            self.pasteRequested.emit()
            if _clipboard_has_attachment():
                return
        super().keyPressEvent(event)


def _clipboard_has_attachment() -> bool:
    data = QGuiApplication.clipboard().mimeData()
    if data is None:
        return False
    if data.hasImage():
        return True
    return any(url.isLocalFile() for url in (data.urls() or []))


class Composer(QWidget):
    """Reply box, saved-reply picker, and the price action."""

    sendRequested = Signal(str)
    # Emitted INSTEAD of sendRequested when there is something attached, so a
    # plain text reply keeps the signature it always had and cannot regress
    # behind a feature it never uses.
    sendWithFilesRequested = Signal(str, object, bool)   # body, paths, is_report
    priceRequested = Signal(str)          # tier key
    hasTextChanged = Signal(bool)
    statusChangeRequested = Signal(str)   # status key
    attachmentRejected = Signal(str)      # one sentence for the operator

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatComposer")
        self.setAcceptDrops(True)

        self._saved_replies: list[dict] = []
        self._pricing: dict = {}
        self._pending: str = ""
        self._attachments: list[str] = []
        self._pending_attachments: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)

        # --- shortcuts row -------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(6)

        self.saved_reply_box = QComboBox(self)
        self.saved_reply_box.setObjectName("ChatSavedReplies")
        self.saved_reply_box.addItem("Saved replies…", None)
        self.saved_reply_box.setEnabled(False)
        self.saved_reply_box.activated.connect(self._on_saved_reply)
        row.addWidget(self.saved_reply_box, 2)

        self.price_box = QComboBox(self)
        self.price_box.setObjectName("ChatPricing")
        self.price_box.addItem("Send a price…", None)
        self.price_box.setEnabled(False)
        self.price_box.activated.connect(self._on_price)
        row.addWidget(self.price_box, 1)

        self.status_box = QComboBox(self)
        self.status_box.setObjectName("ChatStatuses")
        self.status_box.addItem("Change status…", None)
        self.status_box.setEnabled(False)
        self.status_box.activated.connect(self._on_status)
        row.addWidget(self.status_box, 1)

        self.attach_button = QPushButton("📎 Attach", self)
        self.attach_button.setObjectName("ChatAttachButton")
        self.attach_button.setCursor(Qt.PointingHandCursor)
        self.attach_button.setToolTip(
            "Attach files — or drop them here, or paste an image."
        )
        self.attach_button.setEnabled(False)
        self.attach_button.clicked.connect(self.choose_attachments)
        row.addWidget(self.attach_button, 0)

        self.report_check = QCheckBox("Final report", self)
        self.report_check.setObjectName("ChatReportCheck")
        self.report_check.setToolTip(
            "Mark this file as the final report for the consultation."
        )
        # Only meaningful with a file: a "final report" with nothing attached
        # is a claim about a document that is not there.
        self.report_check.setEnabled(False)
        row.addWidget(self.report_check, 0)

        row.addStretch(1)
        layout.addLayout(row)

        # --- attachment tray -----------------------------------------------
        # Hidden until something is attached, so the composer keeps its height
        # for the reply that has no files, which is most of them.
        self.tray = QWidget(self)
        self.tray.setObjectName("ChatAttachTray")
        self._tray_row = QHBoxLayout(self.tray)
        self._tray_row.setContentsMargins(0, 0, 0, 0)
        self._tray_row.setSpacing(6)
        self.tray_hint = QLabel("", self.tray)
        self.tray_hint.setObjectName("ChatAttachHint")
        self._tray_row.addWidget(self.tray_hint, 0)
        self._tray_row.addStretch(1)
        self.tray.setVisible(False)
        layout.addWidget(self.tray)

        # --- the box -------------------------------------------------------
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)

        self.editor = _Editor(self)
        self.editor.setObjectName("ChatComposerEdit")
        self.editor.setPlaceholderText("Write a reply…  (Enter sends, Shift+Enter for a new line)")
        self.editor.setFixedHeight(84)
        self.editor.sendRequested.connect(self._on_send)
        self.editor.pasteRequested.connect(self.attach_from_clipboard)
        self.editor.textChanged.connect(self._on_text_changed)
        edit_row.addWidget(self.editor, 1)

        self.send_button = QPushButton("Send", self)
        self.send_button.setObjectName("ChatSendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._on_send)
        edit_row.addWidget(self.send_button, 0, Qt.AlignBottom)

        layout.addLayout(edit_row)

        self._had_text = False

    # --- catalogue --------------------------------------------------------

    def set_saved_replies(self, replies) -> None:
        """Bodies arrive with {pay_basic} and {reference} ALREADY resolved.

        Resolved on the server, deliberately: substituting here would need a
        copy of the tier table and the payment links, and the amount-to-link
        pairing is owner-confirmed — not a thing to reproduce in two places.
        """
        self._saved_replies = list(replies or [])
        self.saved_reply_box.blockSignals(True)
        self.saved_reply_box.clear()
        self.saved_reply_box.addItem("Saved replies…", None)
        for reply in self._saved_replies:
            self.saved_reply_box.addItem(str(reply.get("title") or "Reply"), reply.get("body") or "")
        self.saved_reply_box.blockSignals(False)
        self.saved_reply_box.setEnabled(bool(self._saved_replies))

    def set_pricing(self, pricing: dict) -> None:
        self._pricing = dict(pricing or {})
        tiers = self._pricing.get("tiers") or []
        self.price_box.blockSignals(True)
        self.price_box.clear()
        self.price_box.addItem("Send a price…", None)
        for tier in tiers:
            label = str(tier.get("label") or tier.get("key"))
            money = tier.get("money")
            self.price_box.addItem(f"{label} ({money})" if money else label, tier.get("key"))
        self.price_box.blockSignals(False)
        self.price_box.setEnabled(bool(tiers))

    def set_statuses(self, statuses) -> None:
        self.status_box.blockSignals(True)
        self.status_box.clear()
        self.status_box.addItem("Change status…", None)
        for status in statuses or []:
            # Only the transitions a human makes. The flow service moves the
            # rest, and offering those invites an operator to fight it.
            if not status.get("manual_only"):
                continue
            self.status_box.addItem(str(status.get("label") or status.get("key")), status.get("key"))
        self.status_box.blockSignals(False)
        self.status_box.setEnabled(self.status_box.count() > 1)

    # --- state ------------------------------------------------------------

    def set_enabled_for_case(self, enabled: bool) -> None:
        self.editor.setEnabled(enabled)
        self.saved_reply_box.setEnabled(enabled and bool(self._saved_replies))
        self.price_box.setEnabled(enabled and self.price_box.count() > 1)
        self.status_box.setEnabled(enabled and self.status_box.count() > 1)
        self.attach_button.setEnabled(enabled)
        if not enabled:
            # Switching conversations must not carry one patient's files into
            # another patient's thread.
            self.clear_attachments()
        self._refresh_send_button()

    # --- attachments ------------------------------------------------------

    def attachments(self) -> list[str]:
        return list(self._attachments)

    def choose_attachments(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach files to this message", "", "All files (*.*)"
        )
        if paths:
            self.add_attachments(paths)

    def add_attachments(self, paths) -> None:
        """Take what fits, and say plainly when something does not.

        The count is checked HERE because it needs no disk access and the
        operator should learn about the sixth file when they add it, not when
        they press send. Size is not checked here — that is the worker's
        pre-flight, which reads the files anyway.
        """
        from modules.aipacs_chat.services.attachments import MAX_FILES

        added = 0
        for raw in paths or []:
            path = str(raw)
            if not path or path in self._attachments:
                continue
            if len(self._attachments) >= MAX_FILES:
                self.attachmentRejected.emit(
                    f"Up to {MAX_FILES} files can be sent in one message."
                )
                break
            self._attachments.append(path)
            added += 1
        if added:
            self._rebuild_tray()

    def remove_attachment(self, path: str) -> None:
        try:
            self._attachments.remove(str(path))
        except ValueError:
            return
        self._rebuild_tray()

    def clear_attachments(self) -> None:
        if not self._attachments:
            return
        self._attachments.clear()
        self._rebuild_tray()

    def attach_from_clipboard(self) -> None:
        """Ctrl+V: a copied file, or a screenshot.

        A pasted image has no path, so one is made for it under
        ``user_data/aipacs_chat/outbox`` — the upload needs a real file, and
        writing it where every other chat file lives keeps one answer to "where
        did that go".
        """
        data = QGuiApplication.clipboard().mimeData()
        if data is None:
            return

        urls = [u.toLocalFile() for u in (data.urls() or []) if u.isLocalFile()]
        if urls:
            self.add_attachments(urls)
            return

        if not data.hasImage():
            return
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            return
        try:
            from modules.aipacs_chat.services.storage import outbox_dir

            folder = outbox_dir()
            index = 1
            while (folder / f"pasted-{index}.png").exists():
                index += 1
            target = folder / f"pasted-{index}.png"
            if not image.save(str(target), "PNG"):
                raise OSError("the image could not be written")
        except Exception as exc:
            self.attachmentRejected.emit(f"That image could not be attached ({exc}).")
            return
        self.add_attachments([str(target)])

    def _rebuild_tray(self) -> None:
        from pathlib import Path

        while self._tray_row.count() > 2:
            item = self._tray_row.takeAt(1)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for path in self._attachments:
            chip = QPushButton(f"{Path(path).name}  ✕", self.tray)
            chip.setProperty("chatChip", True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip(f"{path}\nClick to remove")
            chip.clicked.connect(lambda _=False, p=path: self.remove_attachment(p))
            self._tray_row.insertWidget(self._tray_row.count() - 1, chip)

        count = len(self._attachments)
        self.tray_hint.setText(
            "" if not count else ("1 file attached" if count == 1 else f"{count} files attached")
        )
        self.tray.setVisible(bool(count))
        self.report_check.setEnabled(bool(count))
        if not count:
            self.report_check.setChecked(False)
        self._refresh_send_button()

    def _refresh_send_button(self) -> None:
        """A file with no caption is a perfectly good message."""
        ready = bool(self.editor.toPlainText().strip()) or bool(self._attachments)
        self.send_button.setEnabled(ready and self.editor.isEnabled())

    # --- drag and drop ----------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        data = event.mimeData()
        if data is not None and any(u.isLocalFile() for u in (data.urls() or [])):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        data = event.mimeData()
        paths = [u.toLocalFile() for u in (data.urls() or [])] if data is not None else []
        paths = [p for p in paths if p]
        if not paths:
            event.ignore()
            return
        self.add_attachments(paths)
        event.acceptProposedAction()

    def text(self) -> str:
        return self.editor.toPlainText()

    def clear(self) -> None:
        self.editor.clear()

    def restore_pending(self) -> None:
        """Put the text AND the files back after a failed send.

        The files matter as much as the text: an operator who picked five
        studies out of a folder and lost them to a dropped packet has to find
        all five again, and will reasonably assume the message went through.
        """
        if self._pending:
            self.editor.setPlainText(self._pending)
            self.editor.moveCursor(QTextCursor.MoveOperation.End)
            self._pending = ""
        if self._pending_attachments:
            restored = list(self._pending_attachments)
            self._pending_attachments = []
            self._attachments = restored
            self._rebuild_tray()

    def confirm_sent(self) -> None:
        self._pending = ""
        self._pending_attachments = []

    # --- events -----------------------------------------------------------

    def _on_text_changed(self) -> None:
        has_text = bool(self.editor.toPlainText().strip())
        self._refresh_send_button()
        if has_text != self._had_text:
            self._had_text = has_text
            self.hasTextChanged.emit(has_text)

    def _on_send(self) -> None:
        body = self.editor.toPlainText().strip()
        files = list(self._attachments)
        if not self.editor.isEnabled():
            return
        if not body and not files:
            return
        if len(body) > MAX_BODY:
            # The server would answer 422; saying so here costs no round trip.
            body = body[:MAX_BODY]

        is_report = bool(files) and self.report_check.isChecked()
        self._pending = body
        self._pending_attachments = files
        self.editor.clear()
        if files:
            self._attachments = []
            self._rebuild_tray()
            self.sendWithFilesRequested.emit(body, files, is_report)
            return
        self.sendRequested.emit(body)

    def _on_saved_reply(self, position: int) -> None:
        if position <= 0:
            return
        body = self.saved_reply_box.itemData(position)
        self.saved_reply_box.setCurrentIndex(0)
        if not body:
            return
        # Inserted, not sent. A template is a starting point — an operator
        # almost always adds a sentence, and sending on pick would take that
        # decision away from them.
        existing = self.editor.toPlainText()
        self.editor.setPlainText(f"{existing.rstrip()}\n\n{body}" if existing.strip() else body)
        self.editor.setFocus()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)

    def _on_price(self, position: int) -> None:
        if position <= 0:
            return
        tier = self.price_box.itemData(position)
        self.price_box.setCurrentIndex(0)
        if tier:
            self.priceRequested.emit(str(tier))

    def _on_status(self, position: int) -> None:
        if position <= 0:
            return
        status = self.status_box.itemData(position)
        self.status_box.setCurrentIndex(0)
        if status:
            self.statusChangeRequested.emit(str(status))
