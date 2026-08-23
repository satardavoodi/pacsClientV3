"""Captured-image picker for the Medical Report Editor (2026-08-18).

A modal gallery of the images the physician captured in the Patient tab for
THIS study. Double-click (or select + Insert) returns the chosen file to the
report editor, which embeds it at the cursor.

Scope is the current study on purpose: captures are stored per
StudyInstanceUID (``ATTACHMENT_PATH/<study_uid>/``) and the report being
written belongs to that study, so "this study's captures" is both the only
lookup that exists today and the only set that is unambiguously relevant.

Thumbnails are decoded a few per event-loop tick rather than all at once. A
study can hold 30+ full-resolution PNG captures; decoding them in the
constructor would block the GUI thread for seconds on exactly the machine this
runs on (two real-time AV engines, cold first-touch costs measured at 7-100x).
The dialog therefore opens immediately and fills in.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QWidget,
)

from .report_capture_images import list_captured_images_for_studies

logger = logging.getLogger(__name__)

_THUMB = 148
_GRID = QSize(168, 190)
_BATCH = 4            # thumbnails decoded per tick
_TICK_MS = 10


class CapturedImagePickerDialog(QDialog):
    """Pick one captured image from the current study.

    After ``exec()`` returns ``QDialog.Accepted``, ``selected_path`` holds the
    chosen file. On reject it is ``None``.
    """

    def __init__(self, study_uids, parent=None, *, is_rtl: bool = True):
        super().__init__(parent)
        # Accepts one UID or several: a report opened from the Reception Data
        # tab often names no study at all, and the UIDs have to be resolved
        # from the patient — which can legitimately return more than one.
        if isinstance(study_uids, str):
            study_uids = [study_uids]
        self.study_uids: List[str] = [
            str(u).strip() for u in (study_uids or []) if str(u or "").strip()
        ]
        self.selected_path: Optional[str] = None
        self._entries: List[tuple] = []      # [(study_uid, Path), ...]
        self._pending: List[int] = []

        self.setWindowTitle("Insert Captured Image")
        self.setModal(True)
        self.resize(820, 560)
        if is_rtl:
            self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self._build_ui()
        self._reload()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        self._header = QLabel()
        self._header.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: 600; background: transparent; }"
        )
        root.addWidget(self._header)

        self._hint = QLabel("Double-click an image to insert it at the cursor.")
        self._hint.setStyleSheet(
            "QLabel { color: #9ca3af; font-size: 12px; background: transparent; }"
        )
        root.addWidget(self._hint)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(_THUMB, _THUMB))
        self._list.setGridSize(_GRID)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setWordWrap(True)
        self._list.setSpacing(6)
        self._list.setUniformItemSizes(True)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        root.addWidget(self._list, 1)

        self._empty = QLabel(
            "No captured images for this study yet.\n\n"
            "Use the Capture tool in the Patient tab viewer to save a key "
            "image, then reopen this dialog."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(
            "QLabel { color: #9ca3af; font-size: 13px; background: transparent; "
            "padding: 40px; }"
        )
        self._empty.hide()
        root.addWidget(self._empty, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setToolTip(
            "Re-scan the study folder - use this after capturing a new image "
            "without closing the editor"
        )
        self._btn_refresh.clicked.connect(self._reload)
        buttons.addWidget(self._btn_refresh)

        buttons.addStretch(1)

        self._btn_insert = QPushButton("Insert")
        self._btn_insert.setDefault(True)
        self._btn_insert.setEnabled(False)
        self._btn_insert.clicked.connect(self._accept_selection)
        buttons.addWidget(self._btn_insert)

        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self._btn_cancel)

        root.addLayout(buttons)

    # ── Data ──────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        """Re-scan the study folder(s) and rebuild the grid."""
        self._list.clear()
        self._pending.clear()
        self._entries = list_captured_images_for_studies(self.study_uids)

        count = len(self._entries)
        n_studies = len(self.study_uids)
        scope = "this study" if n_studies <= 1 else f"{n_studies} studies"
        self._header.setText(
            f"Captured images for {scope} — {count} found"
            if count else f"Captured images for {scope}"
        )
        has_any = count > 0
        self._list.setVisible(has_any)
        self._hint.setVisible(has_any)
        self._empty.setVisible(not has_any)
        self._sync_buttons()
        if not has_any:
            return

        multi = n_studies > 1
        for index, (uid, path) in enumerate(self._entries):
            item = QListWidgetItem(self._caption(path, uid if multi else ""))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(f"{path}\n\nStudy: {uid}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._list.addItem(item)
            self._pending.append(index)

        self._list.setCurrentRow(0)
        QTimer.singleShot(0, self._decode_next_batch)

    @staticmethod
    def _caption(path: Path, study_uid: str = "") -> str:
        """Short, human-readable label: capture time beats a uuid filename.
        When several studies are in scope, the study's tail disambiguates."""
        try:
            stamp = datetime.fromtimestamp(path.stat().st_mtime)
            when = stamp.strftime("%Y-%m-%d %H:%M")
        except OSError:
            when = ""
        name = path.name
        if len(name) > 22:
            name = name[:19] + "..."
        label = f"{when}\n{name}" if when else name
        if study_uid:
            label = f"{label}\n…{study_uid[-12:]}"
        return label

    def _decode_next_batch(self) -> None:
        """Decode a few thumbnails, then yield the GUI thread back."""
        done = 0
        while self._pending and done < _BATCH:
            index = self._pending.pop(0)
            item = self._list.item(index)
            if item is None:
                continue
            pixmap = self._thumbnail(self._entries[index][1])
            if pixmap is not None:
                item.setIcon(QIcon(pixmap))
            done += 1
        if self._pending:
            QTimer.singleShot(_TICK_MS, self._decode_next_batch)

    @staticmethod
    def _thumbnail(path: Path) -> Optional[QPixmap]:
        """Decode at thumbnail size where the format allows it.

        ``QImageReader.setScaledSize`` lets the plugin skip work instead of
        materialising a full 5 MP image just to shrink it - the difference
        between a snappy grid and a visible hitch.
        """
        try:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                scaled = size.scaled(
                    QSize(_THUMB, _THUMB), Qt.AspectRatioMode.KeepAspectRatio
                )
                reader.setScaledSize(scaled)
            image = reader.read()
            if image.isNull():
                return None
            return QPixmap.fromImage(image)
        except Exception:
            logger.debug("[REPORT_IMG] thumbnail failed for %s", path, exc_info=True)
            return None

    # ── Selection ─────────────────────────────────────────────────────────

    def _sync_buttons(self) -> None:
        self._btn_insert.setEnabled(self._current_path() is not None)

    def _current_path(self) -> Optional[str]:
        item = self._list.currentItem()
        if item is None or not self._list.isVisible():
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _on_double_click(self, item: QListWidgetItem) -> None:
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if value:
            self.selected_path = str(value)
            self.accept()

    def _accept_selection(self) -> None:
        path = self._current_path()
        if not path:
            return
        self.selected_path = path
        self.accept()


def pick_captured_image(study_uids, parent=None, *, is_rtl: bool = True) -> Optional[str]:
    """Open the picker; return the chosen file path, or None if cancelled.

    ``study_uids`` may be a single UID or a list of them.

    Never raises - the report editor calls this from a toolbar click, and a
    traceback out of a click handler helps nobody.
    """
    try:
        dialog = CapturedImagePickerDialog(study_uids, parent, is_rtl=is_rtl)
    except Exception:
        logger.warning("[REPORT_IMG] could not open the capture picker", exc_info=True)
        return None
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_path
    except Exception:
        logger.warning("[REPORT_IMG] capture picker failed", exc_info=True)
    return None
