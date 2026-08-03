"""Normal Template Library — the physician's personal template manager.

Opened from the ⚙ Manage button on the Normal Template tab's toolbar. The
toolbar itself stays a 44 px strip (the composer height maths in
``UnifiedComposer._sync_composer_heights_for_tab`` depends on that number, and
growing it is what pushed the action row out of the window last time), so
everything that needs room — search, filters, preview, metadata editing —
lives here instead.

All storage, parsing, search and validation live in the pure-stdlib
``modules.EchoMind.normal_templates``. This file is only Qt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from modules.EchoMind import normal_templates as nt

from .ai_chat_config import CLR_ACCENT, CLR_BG_PANEL, CLR_BORDER, CLR_TEXT
from .ai_chat_helpers import themed_message_box

_ANY_MODALITY = "All modalities"
_ANY_REGION = "All regions"


def read_template_file(path: str) -> str:
    """Read an uploaded template file, tolerating the encodings that turn up.

    A BOM-prefixed UTF-8 file and a cp1256 file authored on a Persian Windows
    both have to import; the old loader already did this and dropping it would
    be a regression for existing users.
    """
    for enc in ("utf-8-sig", "utf-8", "cp1256"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            break
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def import_report(added: int, problems: List[str], notes: List[str]) -> str:
    """The message shown after an import. PURE — unit-tested without Qt.

    The old loader reported nothing unless the file was a total loss, so a file
    of 40 templates could import 12 and look like a success.
    """
    lines: List[str] = []
    if added:
        lines.append(f"Imported {added} template{'s' if added != 1 else ''}.")
    else:
        lines.append("No new templates were imported.")
    if notes:
        lines.append("")
        lines.extend(notes)
    if problems:
        lines.append("")
        lines.append(f"{len(problems)} entr{'ies' if len(problems) != 1 else 'y'} could not be used:")
        for p in problems[:12]:
            lines.append(f"  • {p}")
        if len(problems) > 12:
            lines.append(f"  • … and {len(problems) - 12} more.")
    return "\n".join(lines)


class NormalTemplateLibraryDialog(QDialog):
    """Search / preview / import / rename / delete the physician's templates."""

    templateChosen = Signal(dict)
    libraryChanged = Signal()

    def __init__(self, parent=None, records: Optional[List[Dict[str, Any]]] = None,
                 active_id: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Normal Template Library")
        self.setModal(True)
        self.resize(920, 560)

        self._records: List[Dict[str, Any]] = list(records if records is not None else nt.load_library())
        self._active_id = str(active_id or "")
        self._dirty_id = ""

        self.setStyleSheet(f"""
            QDialog {{ background:{CLR_BG_PANEL}; color:{CLR_TEXT}; }}
            QLabel {{ color:{CLR_TEXT}; }}
            QLineEdit, QComboBox, QTextEdit, QListWidget {{
                background:#2f2f2f; color:{CLR_TEXT};
                border:1px solid {CLR_BORDER}; border-radius:8px; padding:5px 8px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border-color:{CLR_ACCENT}; }}
            QListWidget::item {{ padding:6px 4px; border-radius:6px; }}
            QListWidget::item:selected {{ background:{CLR_ACCENT}; color:#1a1a1a; }}
            QPushButton {{
                background:#3a3a3a; color:{CLR_TEXT}; border:1px solid {CLR_BORDER};
                border-radius:10px; padding:6px 14px; min-height:26px; font-weight:600;
            }}
            QPushButton:hover {{ border-color:{CLR_ACCENT}; background:#4a4a4a; }}
            QPushButton:disabled {{ color:#888; border-color:#444; }}
            QPushButton#primary {{ background:{CLR_ACCENT}; color:#1a1a1a; border:none; }}
            QPushButton#danger:hover {{ border-color:#d9534f; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        # ── search + filters ────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.ed_search = QLineEdit(self)
        self.ed_search.setPlaceholderText("Search by name, number, modality or region…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._refresh_list)
        self.cmb_modality = QComboBox(self)
        self.cmb_modality.setMinimumWidth(150)
        self.cmb_modality.currentIndexChanged.connect(self._refresh_list)
        self.cmb_region = QComboBox(self)
        self.cmb_region.setMinimumWidth(150)
        self.cmb_region.currentIndexChanged.connect(self._refresh_list)
        bar.addWidget(self.ed_search, 1)
        bar.addWidget(self.cmb_modality, 0)
        bar.addWidget(self.cmb_region, 0)
        root.addLayout(bar)

        # ── list | preview + metadata ───────────────────────────────────────
        split = QSplitter(Qt.Horizontal, self)
        self.lst = QListWidget(split)
        self.lst.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lst.currentItemChanged.connect(lambda *_: self._on_selection_changed())
        self.lst.itemDoubleClicked.connect(lambda *_: self._use_selected())

        right = QWidget(split)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 0, 0, 0)
        rl.setSpacing(8)

        self.lbl_title = QLabel("Select a template", right)
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        self.lbl_title.setFont(f)
        rl.addWidget(self.lbl_title)

        self.txt_preview = QTextEdit(right)
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setPlaceholderText("Preview of the template as the model will receive it.")
        rl.addWidget(self.txt_preview, 1)

        meta_box = QFrame(right)
        form = QFormLayout(meta_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.ed_name = QLineEdit(meta_box)
        self.ed_number = QLineEdit(meta_box)
        self.cmb_edit_modality = QComboBox(meta_box)
        self.cmb_edit_modality.addItem("")
        self.cmb_edit_modality.addItems(list(nt.CANONICAL_MODALITIES))
        self.cmb_edit_modality.setEditable(True)
        self.ed_region = QLineEdit(meta_box)
        self.ed_exam = QLineEdit(meta_box)
        for w in (self.ed_name, self.ed_number, self.ed_region, self.ed_exam):
            w.textChanged.connect(self._mark_dirty)
        self.cmb_edit_modality.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Name", self.ed_name)
        form.addRow("Number", self.ed_number)
        form.addRow("Modality", self.cmb_edit_modality)
        form.addRow("Body region", self.ed_region)
        form.addRow("Exam type", self.ed_exam)
        rl.addWidget(meta_box)

        self.btn_save_meta = QPushButton("Save changes", right)
        self.btn_save_meta.setEnabled(False)
        self.btn_save_meta.clicked.connect(self._save_metadata)
        rl.addWidget(self.btn_save_meta, 0, Qt.AlignRight)

        split.addWidget(self.lst)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        # ── actions ─────────────────────────────────────────────────────────
        act = QHBoxLayout()
        act.setSpacing(8)
        self.btn_import = QPushButton("📁 Import JSON…", self)
        self.btn_import.clicked.connect(self._import)
        self.btn_delete = QPushButton("Delete", self)
        self.btn_delete.setObjectName("danger")
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete)
        self.lbl_count = QLabel("", self)
        self.btn_use = QPushButton("Use selected template", self)
        self.btn_use.setObjectName("primary")
        self.btn_use.setEnabled(False)
        self.btn_use.clicked.connect(self._use_selected)
        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.reject)
        act.addWidget(self.btn_import)
        act.addWidget(self.btn_delete)
        act.addWidget(self.lbl_count, 1)
        act.addWidget(self.btn_use)
        act.addWidget(self.btn_close)
        root.addLayout(act)

        self._refresh_filters()
        self._refresh_list()

    # ── data helpers ────────────────────────────────────────────────────────
    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def _selected_record(self) -> Optional[Dict[str, Any]]:
        item = self.lst.currentItem()
        if item is None:
            return None
        return nt.find_by_id(self._records, item.data(Qt.UserRole))

    def _refresh_filters(self):
        for combo, any_label, values in (
            (self.cmb_modality, _ANY_MODALITY, nt.available_modalities(self._records)),
            (self.cmb_region, _ANY_REGION, nt.available_body_regions(self._records)),
        ):
            keep = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(any_label)
            combo.addItems(values)
            idx = combo.findText(keep)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _refresh_list(self):
        mod = self.cmb_modality.currentText()
        reg = self.cmb_region.currentText()
        hits = nt.search_templates(
            self._records,
            self.ed_search.text(),
            modality="" if mod == _ANY_MODALITY else mod,
            body_region="" if reg == _ANY_REGION else reg,
        )
        keep_id = ""
        cur = self.lst.currentItem()
        if cur is not None:
            keep_id = str(cur.data(Qt.UserRole))

        self.lst.blockSignals(True)
        self.lst.clear()
        for rec in hits:
            item = QListWidgetItem(nt.display_label(rec))
            item.setData(Qt.UserRole, rec.get("id"))
            if str(rec.get("id")) == self._active_id:
                fnt = item.font()
                fnt.setBold(True)
                item.setFont(fnt)
                item.setText(f"● {item.text()}")
                item.setToolTip("Currently in use")
            self.lst.addItem(item)
        self.lst.blockSignals(False)

        total = len(self._records)
        shown = len(hits)
        self.lbl_count.setText(
            f"{shown} of {total} template{'s' if total != 1 else ''}"
            if shown != total else f"{total} template{'s' if total != 1 else ''}"
        )
        if keep_id:
            for i in range(self.lst.count()):
                if str(self.lst.item(i).data(Qt.UserRole)) == keep_id:
                    self.lst.setCurrentRow(i)
                    break
        if self.lst.currentItem() is None and self.lst.count():
            self.lst.setCurrentRow(0)
        self._on_selection_changed()

    def _on_selection_changed(self):
        rec = self._selected_record()
        has = rec is not None
        self.btn_use.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self._dirty_id = ""
        self.btn_save_meta.setEnabled(False)
        if not has:
            self.lbl_title.setText("Select a template")
            self.txt_preview.setPlainText("")
            for w in (self.ed_name, self.ed_number, self.ed_region, self.ed_exam):
                w.blockSignals(True)
                w.setText("")
                w.blockSignals(False)
            return

        self.lbl_title.setText(nt.display_label(rec))
        self.txt_preview.setPlainText(nt.template_body_text(rec))
        pairs = (
            (self.ed_name, rec.get("name")),
            (self.ed_number, rec.get("number")),
            (self.ed_region, rec.get("body_region")),
            (self.ed_exam, rec.get("exam_type")),
        )
        for w, v in pairs:
            w.blockSignals(True)
            w.setText(str(v or ""))
            w.blockSignals(False)
        self.cmb_edit_modality.blockSignals(True)
        self.cmb_edit_modality.setCurrentText(str(rec.get("modality") or ""))
        self.cmb_edit_modality.blockSignals(False)

        hints = []
        if rec.get("modality_inferred"):
            hints.append("modality guessed from the name")
        if rec.get("body_region_inferred"):
            hints.append("region guessed from the name")
        if rec.get("source_file"):
            hints.append(f"from {rec['source_file']}")
        self.txt_preview.setToolTip(" · ".join(hints))

    def _mark_dirty(self, *_):
        rec = self._selected_record()
        if rec is None:
            return
        self._dirty_id = str(rec.get("id") or "")
        self.btn_save_meta.setEnabled(bool(self._dirty_id and self.ed_name.text().strip()))

    # ── actions ─────────────────────────────────────────────────────────────
    def _save_metadata(self):
        if not self._dirty_id:
            return
        self._records = nt.update_record(
            self._records, self._dirty_id,
            name=self.ed_name.text(),
            number=self.ed_number.text(),
            modality=self.cmb_edit_modality.currentText(),
            body_region=self.ed_region.text(),
            exam_type=self.ed_exam.text(),
        )
        self._persist()
        self._refresh_filters()
        self._refresh_list()

    def _delete(self):
        rec = self._selected_record()
        if rec is None:
            return
        ok = themed_message_box(
            self, QMessageBox.Icon.Question, "Delete template",
            f"Delete \"{rec.get('name')}\" from your library?\n"
            f"This does not affect any report you have already generated.",
            buttons=QMessageBox.Yes | QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        self._records = nt.delete_record(self._records, rec.get("id"))
        self._persist()
        self._refresh_filters()
        self._refresh_list()

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Normal Template JSON", "",
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not path:
            return
        try:
            text = read_template_file(path)
        except Exception as exc:
            themed_message_box(self, QMessageBox.Icon.Warning, "Import failed",
                               f"Could not read the file:\n{exc}")
            return

        records, problems = nt.parse_templates(text, source_file=path)
        merged, notes, added = nt.merge_into_library(self._records, records)
        if added:
            self._records = merged
            self._persist()
            self._refresh_filters()
            self._refresh_list()
        icon = QMessageBox.Icon.Information if added else QMessageBox.Icon.Warning
        themed_message_box(self, icon, "Import result", import_report(added, problems, notes))

    def _use_selected(self):
        rec = self._selected_record()
        if rec is None:
            return
        self._active_id = str(rec.get("id") or "")
        self.templateChosen.emit(dict(rec))
        self.accept()

    def _persist(self):
        if not nt.save_library(self._records):
            themed_message_box(
                self, QMessageBox.Icon.Warning, "Could not save",
                "Your template library could not be written to disk. The change "
                "applies to this session only.",
            )
        self.libraryChanged.emit()
