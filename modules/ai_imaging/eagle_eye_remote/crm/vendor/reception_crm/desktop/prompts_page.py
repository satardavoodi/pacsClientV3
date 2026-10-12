"""Prompt Management — what the agent is told, before it is told the question.

Every request the assistant answers is assembled the same way:

    mode prompt  +  user request  +  reception data  ->  LLM

This screen is where the first of those three is edited. Each agent mode has its
own prompt, so "خلاصهٔ گزارش این بیمار" in Reporting mode and the same words in
Analysis mode do not produce the same tool call.

Three properties make this safe to expose:

* **Restore is always available.** The packaged text is never modified; an edit
  is an override file, and restoring deletes it. There is no way to lose the
  shipped prompt.
* **Nothing is saved by accident.** The editor tracks dirty state, warns before
  switching away, and saving text identical to the default clears the override
  rather than badging the prompt as customised.
* **The list comes from the mode registry.** A mode added to ``core/modes.py``
  appears here on its own, with no change to this file.

It is deliberately not part of the setup flow. A clinic that never opens this
screen has a working assistant; this is for the person tuning one.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..llm import prompt_store
from . import icons, theme
from .help import Help
from .help_widgets import Callout, HelpButton, StatusChip

PAGE_HELP = Help(
    title="دستورهای هوش مصنوعی",
    what="متنی که پیش از هر پرسش به هوش مصنوعی داده می‌شود و رفتار آن را در هر حالت تعیین می‌کند.",
    why=(
        "دستیار در هر حالت (گزارش، تحلیل، اقدام) باید متفاوت رفتار کند. این دستورها همان چیزی هستند "
        "که این تفاوت را می‌سازند — بدون آن‌ها یک جملهٔ یکسان در دو حالت، یک نتیجه می‌دهد."
    ),
    value="اگر دستیار را تنظیم نمی‌کنید، لازم نیست چیزی را در این صفحه تغییر دهید.",
    warning="تغییر نادرست این متن‌ها می‌تواند پاسخ‌های دستیار را نادرست کند. هر دستور دکمهٔ «بازگردانی به پیش‌فرض» دارد.",
    steps=[
        "از فهرست سمت راست، حالت موردنظر را انتخاب کنید.",
        "متن را ویرایش کنید.",
        "«ذخیره» را بزنید — از فرمان بعدی به بعد اعمال می‌شود.",
        "اگر نتیجه بدتر شد، «بازگردانی به پیش‌فرض» را بزنید.",
    ],
)

EDITOR_FONT = QFont("Consolas", 11)


class PromptsPage(QWidget):
    """A list of prompts on one side, the editor on the other."""

    error_context = "هنگام کار با دستورهای هوش مصنوعی،"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.current: prompt_store.PromptInfo | None = None
        self.dirty = False
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(7)
        title = QLabel(PAGE_HELP.title)
        title.setObjectName("PageTitle")
        header_row.addWidget(title)
        header_row.addWidget(HelpButton(PAGE_HELP))
        header_row.addStretch(1)
        root.addWidget(header)

        hint = QLabel(PAGE_HELP.what)
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(
            Callout(
                "این بخش برای تنظیم دقیق دستیار است و برای کار روزمره لازم نیست. "
                "هر تغییری قابل بازگرداندن است — متن اصلی هیچ‌وقت پاک نمی‌شود.",
                "info",
            )
        )

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.build_editor())
        splitter.addWidget(self.build_list())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([720, 300])
        root.addWidget(splitter, 1)

        root.addWidget(self.build_actions())

        self.status = Callout("", "info")
        self.status.hide()
        root.addWidget(self.status)

        self.reload_list()

    # -- left: the prompt list ------------------------------------------------ #
    def build_list(self) -> QWidget:
        host = QFrame()
        host.setObjectName("Card")
        column = QVBoxLayout(host)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(8)

        label = QLabel("حالت‌های دستیار")
        label.setObjectName("SectionTitle")
        column.addWidget(label)

        self.list = QListWidget()
        self.list.setObjectName("PromptList")
        self.list.setIconSize(QSize(18, 18))
        self.list.currentRowChanged.connect(self.on_selected)
        column.addWidget(self.list, 1)

        self.description = QLabel("")
        self.description.setObjectName("FieldNote")
        self.description.setWordWrap(True)
        column.addWidget(self.description)
        return host

    # -- right: the editor ----------------------------------------------------- #
    def build_editor(self) -> QWidget:
        host = QFrame()
        host.setObjectName("Card")
        column = QVBoxLayout(host)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(8)

        top = QWidget()
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.editor_title = QLabel("")
        self.editor_title.setObjectName("SectionTitle")
        row.addWidget(self.editor_title)
        self.badge = StatusChip("idle", "پیش‌فرض")
        self.badge.setToolTip("این دستور همان متن اصلی برنامه است.")
        row.addWidget(self.badge)
        row.addStretch(1)
        column.addWidget(top)

        self.editor = QPlainTextEdit()
        self.editor.setFont(EDITOR_FONT)
        # Prompts are written in English/Markdown; forcing RTL would reorder the
        # punctuation the model relies on.
        self.editor.setLayoutDirection(Qt.LeftToRight)
        self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.editor.textChanged.connect(self.on_edited)
        column.addWidget(self.editor, 1)
        return host

    # -- actions ---------------------------------------------------------------- #
    def build_actions(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.save_btn = QPushButton("ذخیره")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setToolTip("این دستور را ذخیره می‌کند. از فرمان بعدی اعمال می‌شود.")
        self.save_btn.clicked.connect(self.save_current)

        self.restore_btn = QPushButton("بازگردانی به پیش‌فرض")
        self.restore_btn.setToolTip("متن اصلی برنامه را برمی‌گرداند.")
        self.restore_btn.clicked.connect(self.restore_current)

        self.export_btn = QPushButton("خروجی همهٔ دستورها")
        self.export_btn.setToolTip("همهٔ دستورها را در یک پرونده ذخیره می‌کند تا در مرکز دیگری استفاده شود.")
        self.export_btn.clicked.connect(self.export_all)

        self.import_btn = QPushButton("بارگذاری از پرونده")
        self.import_btn.setToolTip("دستورها را از پروندهٔ خروجی یک مرکز دیگر می‌خواند.")
        self.import_btn.clicked.connect(self.import_all)

        for button in (self.save_btn, self.restore_btn):
            row.addWidget(button)
        row.addStretch(1)
        for button in (self.export_btn, self.import_btn):
            row.addWidget(button)
        return host

    # -- list handling ---------------------------------------------------------- #
    def reload_list(self, keep_key: str | None = None) -> None:
        keep_key = keep_key or (self.current.key if self.current else None)
        self.items = prompt_store.catalog()

        self._loading = True
        self.list.clear()
        palette = theme.active()
        for item in self.items:
            entry = QListWidgetItem(item.title_fa)
            customised = prompt_store.differs_from_default(item.filename)
            # A pencil for an edited prompt, a plain document for a stock one —
            # visible at a glance without reading every row.
            entry.setIcon(icons.icon("wand" if customised else "templates",
                                     palette.warn if customised else palette.muted, 18))
            if customised:
                entry.setToolTip("این دستور تغییر داده شده است.")
            else:
                entry.setToolTip(item.description_fa)
            self.list.addItem(entry)
        self._loading = False

        target = 0
        if keep_key:
            target = next((i for i, item in enumerate(self.items) if item.key == keep_key), 0)
        if self.items:
            self.list.setCurrentRow(target)

    def on_selected(self, row: int) -> None:
        if self._loading or not (0 <= row < len(self.items)):
            return
        if self.dirty and not self.confirm_discard():
            # Put the selection back without re-entering this handler.
            self._loading = True
            self.list.setCurrentRow(self.items.index(self.current))
            self._loading = False
            return
        self.load(self.items[row])

    def load(self, item: prompt_store.PromptInfo) -> None:
        self.current = item
        self.editor_title.setText(item.title_fa)
        self.description.setText(item.description_fa)
        try:
            text = prompt_store.read(item.filename)
        except OSError as exc:
            text = ""
            self.say(
                "متن این دستور در این نسخه پیدا نشد.",
                "bad",
                f"این یک ایراد بسته‌بندی نسخه است، نه تنظیمات شما. ({exc})",
            )
        self._loading = True
        self.editor.setPlainText(text)
        self._loading = False
        self.set_dirty(False)
        self.refresh_badge()

    def refresh_badge(self) -> None:
        if self.current is None:
            return
        if prompt_store.differs_from_default(self.current.filename):
            self.badge.set_state("warn", "تغییر داده شده")
            self.badge.setToolTip("این دستور با متن اصلی برنامه فرق دارد.")
        else:
            self.badge.set_state("idle", "پیش‌فرض")
            self.badge.setToolTip("این دستور همان متن اصلی برنامه است.")
        self.restore_btn.setEnabled(prompt_store.is_overridden(self.current.filename))

    # -- dirty state -------------------------------------------------------------- #
    def on_edited(self) -> None:
        if not self._loading:
            self.set_dirty(True)

    def set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.save_btn.setEnabled(dirty)
        if dirty:
            self.badge.set_state("busy", "ذخیره نشده")

    def confirm_discard(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("تغییرات ذخیره نشده")
        box.setText("تغییرات این دستور ذخیره نشده است.")
        box.setInformativeText("اگر ادامه دهید، تغییرات از بین می‌رود.")
        discard = box.addButton("رها کن", QMessageBox.DestructiveRole)
        box.addButton("برگرد", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is discard

    # -- operations ----------------------------------------------------------------- #
    def say(self, headline: str, tone: str = "info", advice: str = "") -> None:
        self.status.set_text(f"{headline}  {advice}".strip())
        self.status.setObjectName(Callout.OBJECT_NAMES.get(tone, "CalloutInfo"))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.show()

    def save_current(self) -> None:
        if self.current is None:
            return
        text = self.editor.toPlainText()
        if not text.strip():
            self.say(
                "متن دستور نمی‌تواند خالی باشد.",
                "warn",
                advice="اگر می‌خواهید به حالت اولیه برگردید، «بازگردانی به پیش‌فرض» را بزنید.",
            )
            return
        try:
            prompt_store.write(self.current.filename, text)
        except prompt_store.PromptError as exc:
            self.say("ذخیره نشد.", "bad", advice=str(exc))
            return

        self.set_dirty(False)
        if prompt_store.differs_from_default(self.current.filename):
            self.say(
                f"دستور «{self.current.title_fa}» ذخیره شد.",
                "ok",
                advice="از فرمان بعدی به بعد اعمال می‌شود.",
            )
        else:
            self.say(
                f"دستور «{self.current.title_fa}» با متن پیش‌فرض یکسان بود.",
                "ok",
                advice="بنابراین به حالت پیش‌فرض برگشت.",
            )
        self.reload_list()

    def restore_current(self) -> None:
        if self.current is None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("بازگردانی به پیش‌فرض")
        box.setText(f"دستور «{self.current.title_fa}» به متن اصلی برنامه برگردد؟")
        box.setInformativeText("تغییرات شما در این دستور حذف می‌شود.")
        confirm = box.addButton("بله، برگردان", QMessageBox.DestructiveRole)
        box.addButton("انصراف", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        try:
            prompt_store.restore(self.current.filename)
        except prompt_store.PromptError as exc:
            self.say("بازگردانی نشد.", "bad", advice=str(exc))
            return
        self.load(self.current)
        self.say(f"دستور «{self.current.title_fa}» به حالت پیش‌فرض برگشت.", "ok")
        self.reload_list()

    def export_all(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "ذخیرهٔ دستورها", str(Path.home() / "reception-crm-prompts.json"), "پروندهٔ دستورها (*.json)"
        )
        if not path:
            return
        try:
            target = prompt_store.export_all(path)
        except prompt_store.PromptError as exc:
            self.say("خروجی گرفته نشد.", "bad", advice=str(exc))
            return
        self.say(
            "همهٔ دستورها ذخیره شدند.",
            "ok",
            advice=f"می‌توانید همین پرونده را در مرکز دیگری بارگذاری کنید. ({target.name})",
        )

    def import_all(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "بارگذاری دستورها", str(Path.home()), "پروندهٔ دستورها (*.json)"
        )
        if not path:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("بارگذاری دستورها")
        box.setText("دستورهای این پرونده جایگزین دستورهای فعلی شوند؟")
        box.setInformativeText("هر دستور بعداً به‌صورت جداگانه قابل بازگردانی به پیش‌فرض است.")
        confirm = box.addButton("بله، بارگذاری کن", QMessageBox.AcceptRole)
        box.addButton("انصراف", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        try:
            applied = prompt_store.import_all(path)
        except prompt_store.PromptError as exc:
            self.say("پرونده بارگذاری نشد.", "bad", advice=str(exc))
            return

        if not applied:
            self.say("چیزی تغییر نکرد.", "info", advice="دستورهای این پرونده با دستورهای فعلی یکسان بودند.")
        else:
            self.say(
                f"{len(applied)} دستور بارگذاری شد.",
                "ok",
                advice="، ".join(applied),
            )
        self.reload_list()
        if self.current:
            self.load(self.current)

    # -- theme ------------------------------------------------------------------------ #
    def restyle(self) -> None:
        return

    def has_unsaved(self) -> bool:
        return self.dirty
