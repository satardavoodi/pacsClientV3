"""Desktop conversation history and its server-local analysis files."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core.conversations import ConversationError, ConversationStore
from ..core.types import Principal
from ..jalali import gregorian_to_jalali
from ..runtime import data_root as configured_data_root
from .help import PAGE_HELP
from .help_widgets import HelpButton


PREVIEW_BYTES = 256 * 1024


class ConversationHistoryPage(QWidget):
    """A read-only view of chats, answers, complete JSON and generated CSVs."""

    def __init__(self, window: Any) -> None:
        super().__init__()
        self.window_ref = window
        self._loaded = False
        self._conversations: list[dict[str, Any]] = []
        self._artifact_ids: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(self._title())

        tools = QFrame()
        tools.setObjectName("Card")
        tool_row = QHBoxLayout(tools)
        tool_row.setContentsMargins(14, 12, 14, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در عنوان گفت‌وگوها…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.archived = QCheckBox("نمایش بایگانی‌شده‌ها")
        self.archived.toggled.connect(self.refresh)
        refresh = QPushButton("تازه‌سازی")
        refresh.setProperty("kind", "secondary")
        refresh.clicked.connect(self.refresh)
        tool_row.addWidget(self.search, 1)
        tool_row.addWidget(self.archived)
        tool_row.addWidget(refresh)
        root.addWidget(tools)

        splitter = QSplitter(Qt.Horizontal)
        self.conversations = QListWidget()
        self.conversations.setMinimumWidth(280)
        self.conversations.setAlternatingRowColors(True)
        self.conversations.currentItemChanged.connect(self._select_conversation)
        splitter.addWidget(self.conversations)

        self.tabs = QTabWidget()
        self.timeline = QTextBrowser()
        self.timeline.setOpenExternalLinks(False)
        self.timeline.setPlaceholderText("یک گفت‌وگو را از فهرست انتخاب کنید.")
        self.tabs.addTab(self.timeline, "گفت‌وگو")

        data_tab = QWidget()
        data_layout = QVBoxLayout(data_tab)
        data_layout.setContentsMargins(0, 8, 0, 0)
        self.files = QTableWidget(0, 5)
        self.files.setHorizontalHeaderLabels(
            ["زمان پاسخ", "نام داده", "نوع", "ردیف‌ها", "حجم"]
        )
        self.files.setSelectionBehavior(QTableWidget.SelectRows)
        self.files.setSelectionMode(QTableWidget.SingleSelection)
        self.files.setEditTriggers(QTableWidget.NoEditTriggers)
        self.files.verticalHeader().setVisible(False)
        self.files.setColumnWidth(0, 245)
        self.files.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.files.itemSelectionChanged.connect(self._preview_selected)
        data_layout.addWidget(self.files, 1)

        actions = QHBoxLayout()
        self.open_file = QPushButton("باز کردن فایل")
        self.open_file.setEnabled(False)
        self.open_file.clicked.connect(self._open_selected)
        self.file_note = QLabel("فایل‌های کامل روی همین سرور نگهداری می‌شوند")
        self.file_note.setObjectName("FieldNote")
        actions.addWidget(self.open_file)
        actions.addWidget(self.file_note, 1)
        data_layout.addLayout(actions)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("برای پیش‌نمایش یک فایل را انتخاب کنید")
        self.preview.setMinimumHeight(180)
        data_layout.addWidget(self.preview)
        self.tabs.addTab(data_tab, "داده‌ها و فایل‌ها")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        self.status = QLabel("هنوز بارگذاری نشده است.")
        self.status.setObjectName("FieldNote")
        root.addWidget(self.status)

    def _title(self) -> QWidget:
        topic = PAGE_HELP["conversations"]
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        label = QLabel(topic.title)
        label.setObjectName("PageTitle")
        top.addWidget(label)
        top.addWidget(HelpButton(topic))
        top.addStretch(1)
        layout.addLayout(top)
        hint = QLabel(topic.what)
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    def showEvent(self, event) -> None:  # noqa: N802 - Qt signature
        super().showEvent(event)
        if not self._loaded:
            self.refresh()

    def _principal(self) -> Principal:
        return Principal(
            user=str(self.window_ref.user or ""),
            center=str(self.window_ref.center or ""),
            roles=["agent_readonly"],
            auth_method="desktop_local",
        )

    def _store(self) -> ConversationStore:
        root = str(self.window_ref.data_root or "").strip()
        return ConversationStore(Path(root) if root else configured_data_root())

    def refresh(self) -> None:
        selected = self._selected_conversation_id()
        self.status.setText("در حال خواندن گفت‌وگوها…")
        try:
            self._conversations = self._store().list(
                self._principal(),
                include_archived=self.archived.isChecked(),
                limit=200,
            )
        except (ConversationError, OSError) as exc:
            self._conversations = []
            self.conversations.clear()
            self.status.setText("خواندن تاریخچه ممکن نشد.")
            self.timeline.setPlainText(str(exc))
            return
        self._loaded = True
        self._apply_filter()
        if selected:
            for row in range(self.conversations.count()):
                item = self.conversations.item(row)
                if item.data(Qt.UserRole) == selected:
                    self.conversations.setCurrentItem(item)
                    break
        if not self._conversations:
            self.status.setText("هنوز گفت‌وگویی برای این کاربر در این مرکز ذخیره نشده است.")

    def _apply_filter(self) -> None:
        query = self.search.text().strip().casefold()
        current = self._selected_conversation_id()
        self.conversations.clear()
        for conversation in self._conversations:
            title = str(conversation.get("title") or "گفت‌وگوی بدون عنوان")
            if query and query not in title.casefold():
                continue
            item = QListWidgetItem(
                f"{title}\n{_date(conversation.get('updatedAt'))}  "
                f"{_digits(conversation.get('turnCount') or 0)} پیام"
            )
            item.setData(Qt.UserRole, conversation["id"])
            item.setToolTip(title)
            self.conversations.addItem(item)
            if conversation["id"] == current:
                self.conversations.setCurrentItem(item)
        if self.conversations.currentItem() is None and self.conversations.count():
            self.conversations.setCurrentRow(0)
        elif not self.conversations.count():
            self.timeline.clear()
            self._fill_files([])
        self.status.setText(
            f"{_digits(self.conversations.count())} گفت‌وگو نمایش داده می‌شود."
        )

    def _selected_conversation_id(self) -> str:
        item = self.conversations.currentItem()
        return str(item.data(Qt.UserRole) or "") if item else ""

    def _select_conversation(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        conversation_id = str(current.data(Qt.UserRole) or "")
        try:
            store = self._store()
            turns: list[dict[str, Any]] = []
            after_seq = 0
            while True:
                page = store.turns(
                    self._principal(), conversation_id, after_seq=after_seq, limit=200
                )
                turns.extend(page)
                if len(page) < 200:
                    break
                after_seq = int(page[-1]["seq"])
            analyses = store.analyses(self._principal(), conversation_id, limit=200)
        except (ConversationError, OSError) as exc:
            self.timeline.setPlainText(f"خواندن این گفت‌وگو ممکن نشد: {exc}")
            self._fill_files([])
            return
        self.timeline.setHtml(_timeline_html(turns))
        self._fill_files(analyses)
        self.status.setText(
            f"{_digits(len(turns))} پیام و "
            f"{_digits(sum(len(a.get('artifacts') or []) for a in analyses))} فایل"
        )

    def _fill_files(self, analyses: list[dict[str, Any]]) -> None:
        records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for analysis in analyses:
            for artifact in analysis.get("artifacts") or []:
                records.append((analysis, artifact))
        self.files.setRowCount(len(records))
        self._artifact_ids = []
        for row, (analysis, artifact) in enumerate(records):
            self._artifact_ids.append(str(artifact.get("id") or ""))
            values = (
                _date(analysis.get("createdAt")),
                artifact.get("name") or "داده",
                _artifact_type(artifact),
                "ندارد" if artifact.get("rowCount") is None else _digits(artifact.get("rowCount")),
                _size(artifact.get("sizeBytes")),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, artifact.get("id"))
                self.files.setItem(row, column, cell)
        self.preview.clear()
        self.open_file.setEnabled(False)
        self.tabs.setTabText(1, f"داده‌ها و فایل‌ها  {_digits(len(records))} فایل")

    def _selected_artifact_id(self) -> str:
        row = self.files.currentRow()
        if row < 0 or row >= len(self._artifact_ids):
            return ""
        return self._artifact_ids[row]

    def _artifact_path(self) -> Path | None:
        artifact_id = self._selected_artifact_id()
        if not artifact_id:
            return None
        try:
            return self._store().artifact_path(self._principal(), artifact_id)
        except (ConversationError, OSError) as exc:
            self.preview.setPlainText(f"این فایل در دسترس نیست: {exc}")
            return None

    def _preview_selected(self) -> None:
        path = self._artifact_path()
        self.open_file.setEnabled(path is not None)
        if path is None:
            return
        try:
            size = path.stat().st_size
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
                self.preview.setPlainText(
                    "این فایل تصویری/PDF همان مدرکی است که از موبایل ارسال شده است.\n\n"
                    "برای دیدن نسخهٔ کامل، «باز کردن فایل» را بزنید."
                )
                self.file_note.setText(
                    f"{_format_label(path.suffix.lstrip('.'))} — {_size(size)} — فایل اصلی کامل"
                )
                return
            with path.open("rb") as handle:
                raw = handle.read(PREVIEW_BYTES + 1)
            text = raw[:PREVIEW_BYTES].decode("utf-8-sig", errors="replace")
            if len(raw) > PREVIEW_BYTES:
                text += "\n\n… پیش‌نمایش کوتاه شده است؛ فایل کامل را باز کنید."
            self.preview.setPlainText(text)
            self.file_note.setText(
                f"{_format_label(path.suffix.lstrip('.'))} — {_size(size)} — کامل"
            )
        except OSError as exc:
            self.preview.setPlainText(f"پیش‌نمایش فایل ممکن نشد: {exc}")

    def _open_selected(self) -> None:
        path = self._artifact_path()
        if path is None:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "باز کردن فایل", "ویندوز نتوانست برنامهٔ مناسب را باز کند.")

    def restyle(self) -> None:
        # QTextBrowser keeps previously-rendered HTML across a theme switch.
        current = self.conversations.currentItem()
        if current is not None:
            self._select_conversation(current)


def _timeline_html(turns: list[dict[str, Any]]) -> str:
    blocks = []
    for turn in turns:
        assistant = turn.get("role") == "assistant"
        label = "دستیار" if assistant else "کاربر"
        colour = "#0d6e6e" if assistant else "#596777"
        text = html.escape(str(turn.get("text") or "")).replace("\n", "<br>")
        blocks.append(
            f'<div style="margin:8px 2px 14px;padding:12px 14px;border-right:4px solid {colour};">'
            f'<div style="font-weight:700;color:{colour}">{label}  {_date(turn.get("createdAt"))}</div>'
            f'<div style="margin-top:6px;line-height:1.75">{text}</div></div>'
        )
    return '<div dir="rtl">' + "".join(blocks) + "</div>"


def _date(value: Any) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = parsed.astimezone()
        year, month, day = gregorian_to_jalali(local.date()).split("/")
        return _digits(
            f"ساعت {local.hour:02d} و {local.minute:02d}  تاریخ {year} {month} {day}"
        )
    except (TypeError, ValueError):
        return str(value)


def _size(value: Any) -> str:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        return "—"
    if size < 1024:
        return f"{_digits(size)} بایت"
    if size < 1024 * 1024:
        return f"{_digits(f'{size / 1024:.1f}')} کیلوبایت"
    return f"{_digits(f'{size / (1024 * 1024):.1f}')} مگابایت"


def _format_label(value: Any) -> str:
    return {
        "json": "دادهٔ کامل",
        "jsonl": "دادهٔ خام",
        "csv": "جدول",
        "jpg": "تصویر JPEG",
        "jpeg": "تصویر JPEG",
        "png": "تصویر PNG",
        "webp": "تصویر WebP",
        "pdf": "سند PDF",
    }.get(str(value or "").lower(), str(value or "فایل"))


def _artifact_type(artifact: dict[str, Any]) -> str:
    return {
        "response": "پاسخ کامل",
        "evidence": "همهٔ منابع",
        "table": "جدول",
        "evidence_table": "جدول منبع",
        "source": "دادهٔ خام",
        "input": "فایل ارسالی کاربر",
    }.get(str(artifact.get("kind") or ""), _format_label(artifact.get("format")))


def _digits(value: Any) -> str:
    return str(value).translate(str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫"))
