"""Asynchronous Reception template preview and explicit local-copy import."""
from __future__ import annotations

import threading
import copy

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QComboBox, QLineEdit, QCheckBox, QListWidget,
                              QListWidgetItem, QTextEdit, QSplitter, QAbstractItemView,
                              QTabWidget, QMessageBox)

from modules.EchoMind import normal_templates as nt
from modules.EchoMind import reception_templates as rt

_WORKERS = set()


class _LibraryEvents(QObject):
    imported = Signal(list)


library_events = _LibraryEvents()


class _Worker(QThread):
    result = Signal(bool, object)
    progress = Signal(int, int, str)

    def __init__(self, fn, with_progress=False):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress

    def run(self):
        try:
            self.result.emit(True, self.fn(self.progress.emit) if self.with_progress else self.fn())
        except rt.TemplateError as exc:
            self.result.emit(False, str(exc))
        except Exception:
            self.result.emit(False, "The template operation failed. Please retry.")


def _retire(worker):
    _WORKERS.discard(worker)
    worker.deleteLater()


class ReceptionTemplateDialog(QDialog):
    libraryUpdated = Signal(list)

    def __init__(self, parent=None, modality=""):
        super().__init__(parent)
        self.setWindowTitle("Reception Normal Templates")
        self.resize(950, 600)
        self._default_modality = nt.canonical_modality(modality)
        self._catalog = {}
        self._connection = None
        self._busy = False
        self._importing = False
        self._closed = False
        self._cancel = threading.Event()
        root = QVBoxLayout(self)
        note = QLabel("Uses the active server's Reception connection and your signed-in account.\n"
                      "Select one or more templates (Ctrl/Shift) to organize and save reviewable drafts. "
                      "Direct import requires confirming the sample is already a normal template.")
        note.setWordWrap(True)
        root.addWidget(note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search templates…")
        self.modality = QComboBox()
        self.modality.addItem("All modalities", "")
        self.personnel = QComboBox()
        self.personnel.addItem("All personnel", "")
        self.mine_first = QCheckBox("My templates first")
        self.mine_first.setChecked(True)
        self.mine_first.setToolTip("Prioritize templates created by your verified Reception account or assigned to your linked personnel ID.")
        for widget in (self.search, self.modality, self.personnel, self.mine_first):
            filters.addWidget(widget)
        root.addLayout(filters)
        split = QSplitter()
        self.items = QListWidget()
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        split.addWidget(self.items)
        split.addWidget(self.preview)
        root.addWidget(split, 1)
        self.confirm_normal = QCheckBox("I reviewed this sample report and want to use it as a normal template")
        root.addWidget(self.confirm_normal)
        self.status = QLabel("Click Refresh to retrieve the Reception template library.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        actions = QHBoxLayout()
        self.refresh = QPushButton("Refresh from Reception")
        self.import_button = QPushButton("Import selected template")
        self.import_button.setEnabled(False)
        self.organize_button = QPushButton("Optimize, Organize && Save")
        self.organize_button.setEnabled(False)
        self.review_button = QPushButton("Saved organized templates…")
        self.cancel_button = QPushButton("Cancel processing")
        self.cancel_button.setEnabled(False)
        close = QPushButton("Close")
        actions.addWidget(self.refresh)
        actions.addStretch(1)
        actions.addWidget(self.import_button)
        actions.addWidget(close)
        root.addLayout(actions)
        organization_actions = QHBoxLayout()
        for button in (self.organize_button, self.cancel_button, self.review_button):
            organization_actions.addWidget(button)
        root.addLayout(organization_actions)
        self.organize_button.clicked.connect(self._organize)
        self.cancel_button.clicked.connect(self._cancel_processing)
        self.review_button.clicked.connect(self._review)
        self.refresh.clicked.connect(self._fetch)
        self.import_button.clicked.connect(self._import)
        close.clicked.connect(self.reject)
        self.search.textChanged.connect(self._filter)
        self.modality.currentIndexChanged.connect(self._filter)
        self.personnel.currentIndexChanged.connect(self._filter)
        self.mine_first.toggled.connect(self._filter)
        self.items.currentItemChanged.connect(self._selection)
        self.items.itemSelectionChanged.connect(self._enable_import)
        self.confirm_normal.toggled.connect(self._enable_import)

    def _start(self, fn, slot, with_progress=False):
        self._busy = True
        self.refresh.setEnabled(False)
        self._enable_import()
        worker = _Worker(fn, with_progress)
        worker.progress.connect(self._progress)
        _WORKERS.add(worker)  # Outlive a closed dialog until bounded work ends.
        worker.result.connect(slot)
        worker.finished.connect(lambda: _retire(worker))
        worker.start()

    @Slot()
    def _fetch(self):
        if self._busy:
            return
        self._catalog = {}
        self._filter()
        self.status.setText("Downloading templates…")
        self._cancel = threading.Event()
        cancel = self._cancel
        def fetch():
            connection = rt.current_connection()
            catalog = rt.ReceptionTemplates(*connection, cancelled=cancel.is_set).fetch()
            if connection != rt.current_connection():
                raise rt.TemplateError("The active server or account changed. Refresh the templates.")
            return connection, catalog
        self._start(fetch, self._received)

    @Slot(bool, object)
    def _received(self, ok, result):
        self._busy = False
        if self._closed:
            return
        self.refresh.setEnabled(True)
        if not ok:
            self.status.setText(result)
            self._enable_import()
            return
        self._connection, self._catalog = result
        self.modality.blockSignals(True)
        self.modality.clear()
        self.modality.addItem("All modalities", "")
        for mod in self._catalog["modalities"]:
            self.modality.addItem(mod, mod)
        idx = self.modality.findData(self._default_modality)
        self.modality.setCurrentIndex(max(0, idx))
        self.modality.blockSignals(False)
        self.personnel.blockSignals(True)
        self.personnel.clear()
        self.personnel.addItem("All personnel", "")
        persons = {r["reception"]["personnel_id"]: r["reception"]["personnel_name"]
                   for r in self._catalog["records"] if r["reception"]["personnel_id"]}
        for pid, name in sorted(persons.items(), key=lambda item: item[1]):
            self.personnel.addItem(name or "Personnel " + pid[-6:], pid)
        self.personnel.blockSignals(False)
        self.status.setText(f"{len(self._catalog['records'])} templates downloaded; "
                            f"{self._catalog['skipped']} unavailable entries skipped. Nothing imported automatically.")
        self._filter()

    @Slot()
    def _filter(self, *_):
        catalog = self._catalog
        records = rt.ordered_records(catalog.get("records", []), catalog.get("user_id", ""),
                                     catalog.get("personnel_id", ""), self.modality.currentData() or "",
                                     self.mine_first.isChecked())
        query = self.search.text().strip().casefold()
        pid = self.personnel.currentData()
        self.items.clear()
        for rec in records:
            if query and query not in nt.display_label(rec).casefold():
                continue
            if pid and rec["reception"]["personnel_id"] != pid:
                continue
            item = QListWidgetItem(nt.display_label(rec))
            item.setData(Qt.UserRole, rec)
            self.items.addItem(item)
        self._selection()

    @Slot()
    def _selection(self, *_):
        item = self.items.currentItem()
        rec = item.data(Qt.UserRole) if item else None
        self.preview.setPlainText(nt.template_body_text(rec) if rec else "")
        self.confirm_normal.setChecked(False)
        self._enable_import()

    @Slot()
    def _enable_import(self, *_):
        self.import_button.setEnabled(not self._busy and self.items.currentItem() is not None
                                      and self.confirm_normal.isChecked())
        self.organize_button.setEnabled(not self._busy and bool(self.items.selectedItems()))
        self.review_button.setEnabled(not self._busy)
        for widget in (self.search, self.modality, self.personnel, self.mine_first, self.items):
            widget.setEnabled(not self._busy)

    @Slot()
    def _organize(self):
        if self._busy or not self.items.selectedItems():
            return
        records = [copy.deepcopy(item.data(Qt.UserRole)) for item in self.items.selectedItems()]
        connection = self._connection
        self._cancel.clear()
        cancel = self._cancel
        self.cancel_button.setEnabled(True)
        self.status.setText(f"Organizing {len(records)} selected templates one at a time…")
        def work(progress):
            return rt.organize_templates(records, cancelled=cancel.is_set, bilingual=True,
                still_current=lambda: connection == rt.current_connection(), progress=progress)
        self._start(work, self._organized, with_progress=True)

    def _cancel_processing(self):
        self._cancel.set()
        self.cancel_button.setEnabled(False)
        self.status.setText("Stopping after the current response. Previously saved templates are preserved.")

    @Slot(int, int, str)
    def _progress(self, done, total, message):
        if not self._closed:
            self.status.setText(f"{done}/{total}: {message}")

    @Slot(bool, object)
    def _organized(self, ok, result):
        self._busy = False
        if self._closed:
            return
        self.refresh.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if ok:
            prefix = "Stopped. " if result["cancelled"] else "Finished. "
            self.status.setText(prefix + f"Saved: {result['saved']}; already saved: {result['cached']}; "
                f"failed: {result['failed']}. Open Saved organized templates to review, edit and use them.")
        else:
            self.status.setText(result)
        self._enable_import()

    def _review(self):
        OrganizedTemplateReviewDialog(self).exec()

    @Slot()
    def _import(self):
        item = self.items.currentItem()
        if not item or not self.confirm_normal.isChecked() or self._busy:
            return
        record, connection = dict(item.data(Qt.UserRole)), self._connection
        def save():
            if connection != rt.current_connection():
                raise rt.TemplateError("The active server or account changed. Refresh before importing.")
            return rt.import_selected(record)
        self._importing = True
        self.status.setText("Saving the selected template…")
        self._start(save, self._imported)

    @Slot(bool, object)
    def _imported(self, ok, result):
        self._busy = self._importing = False
        self.refresh.setEnabled(True)
        if ok:
            records, added = result
            self.libraryUpdated.emit(records)
            library_events.imported.emit(records)
            self.status.setText("Template imported. Select it in the Normal Template library to use it."
                                if added else "This version is already imported. Your local edits were preserved.")
        else:
            self.status.setText(result)
        self._enable_import()

    def reject(self):
        if self._importing:
            return
        self._closed = True
        self._cancel.set()
        super().reject()

    def closeEvent(self, event):
        if self._importing:
            event.ignore()
        else:
            self._closed = True
            self._cancel.set()
            super().closeEvent(event)


class OrganizedTemplateReviewDialog(QDialog):
    """Review source, grouped draft and editable final wording without GUI-thread I/O."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Saved Organized Templates")
        self.resize(1100, 700)
        self._records = []
        self._busy = False
        self._saving = False
        self._closed = False
        self._dirty = False
        self._current = None
        root = QVBoxLayout(self)
        note = QLabel("Review normal text, fillable fields and on-request pathology codes, then Save & Use. "
                      "Keep code names and boundary markers when editing. Codes require explicit dictation. "
                      "Original text and excluded sample content remain available on the left. "
                      "Linked English and Persian versions are saved together. "
                      "After editing, Generate Linked Versions, review both, then Save & Use.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.items = QListWidget()
        root.addWidget(self.items, 1)
        split = QSplitter()
        tabs = QTabWidget()
        self.original = QTextEdit()
        self.original.setReadOnly(True)
        self.organized = QTextEdit()
        self.organized.setReadOnly(True)
        tabs.addTab(self.original, "Original")
        tabs.addTab(self.organized, "Organization / excluded content")
        split.addWidget(tabs)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("Review and edit the final normal template here…")
        language_tabs = QTabWidget()
        language_tabs.addTab(self.editor, 'Editable source')
        self.english_preview = QTextEdit()
        self.persian_preview = QTextEdit()
        for preview in (self.english_preview, self.persian_preview):
            preview.setReadOnly(True)
        language_tabs.addTab(self.english_preview, 'English')
        language_tabs.addTab(self.persian_preview, 'Persian')
        split.addWidget(language_tabs)
        root.addWidget(split, 3)
        self.status = QLabel("Loading saved templates…")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        self.generate_button = QPushButton('Generate Linked Versions')
        self.save_button = QPushButton("Save && Use")
        self.discard_button = QPushButton("Discard unsaved edits")
        close = QPushButton("Close")
        for button in (self.generate_button, self.save_button, self.discard_button, close):
            buttons.addWidget(button)
        root.addLayout(buttons)
        self.save_button.clicked.connect(self._save)
        self.generate_button.clicked.connect(self._generate_languages)
        self.discard_button.clicked.connect(self._select)
        close.clicked.connect(self.reject)
        self.items.currentItemChanged.connect(self._select)
        self.editor.textChanged.connect(self._edited)
        self._run(rt.load_organized_templates, self._loaded)

    def _controls(self):
        self.items.setEnabled(not self._busy and not self._dirty)
        self.editor.setReadOnly(self._busy or self._current is None)
        ready = not self._busy and self._current is not None and bool(self.editor.toPlainText().strip())
        self.generate_button.setEnabled(ready)
        pair = (self._current or {}).get('translations') or {}
        self.save_button.setEnabled(ready and pair.get('source_hash') == nt.text_digest(self.editor.toPlainText()))
        self.discard_button.setEnabled(not self._busy and self._dirty)

    def _run(self, fn, slot):
        self._busy = True
        self._controls()
        worker = _Worker(fn)
        _WORKERS.add(worker)
        worker.result.connect(slot)
        worker.finished.connect(lambda: _retire(worker))
        worker.start()

    @Slot(bool, object)
    def _loaded(self, ok, result):
        self._busy = False
        if self._closed:
            return
        if not ok:
            self.status.setText(result)
            self._controls()
            return
        self._records = result
        self.items.clear()
        for draft in result:
            item = QListWidgetItem(nt.display_label(draft["source"]))
            item.setData(Qt.UserRole, draft["id"])
            self.items.addItem(item)
        if self.items.count():
            self.items.setCurrentRow(0)
        self.status.setText(f"{len(result)} saved organized templates. Save & Use publishes only your final text.")
        self._controls()

    def _select(self, *_):
        item = self.items.currentItem()
        self._current = nt.find_by_id(self._records, item.data(Qt.UserRole)) if item else None
        draft = self._current
        self.editor.blockSignals(True)
        self.editor.setPlainText(draft["edited_text"] if draft else "")
        self.editor.blockSignals(False)
        pair = (draft or {}).get('translations') or {}
        self.english_preview.setPlainText(pair.get('en', 'Use Generate Linked Versions to prepare this text.'))
        self.persian_preview.setPlainText(pair.get('fa', 'Use Generate Linked Versions to prepare this text.'))
        self.original.setPlainText(nt.template_body_text(draft["source"]) if draft else "")
        parts = []
        if draft:
            blocks = {b["id"]: b["text"] for b in draft["blocks"]}
            for group in draft["groups"]:
                parts.append(group["section"] + " [" + group["kind"].replace("_", " ") + "]\n" +
                             "\n".join(blocks[i] for i in group["ids"]))
        self.organized.setPlainText("\n\n".join(parts))
        self._dirty = False
        self._controls()

    def _edited(self):
        self._dirty = bool(self._current and self.editor.toPlainText() != self._current["edited_text"])
        if self._dirty:
            for preview in (self.english_preview, self.persian_preview):
                preview.setPlainText('Source changed. Use Generate Linked Versions, then review before saving.')
        self._controls()

    def _generate_languages(self):
        if self._busy or not self._current:
            return
        tid, expected = self._current['id'], self._current['edited_text']
        text = self.editor.toPlainText()
        self._saving = True
        self.status.setText('Preparing linked versions for review...')
        self._run(lambda: rt.prepare_organized_languages(tid, text, expected=expected), self._languages_ready)

    @Slot(bool, object)
    def _languages_ready(self, ok, result):
        self._busy = self._saving = False
        if self._closed:
            return
        if ok:
            self._current.update(result)
            pair = result['translations']
            self.english_preview.setPlainText(pair['en'])
            self.persian_preview.setPlainText(pair['fa'])
            self._dirty = False
            self.status.setText('Review both versions, then choose Save & Use to publish.')
        else:
            self.status.setText(result)
        self._controls()

    def _save(self):
        if self._busy or not self._current:
            return
        tid, expected = self._current["id"], self._current["edited_text"]
        text = self.editor.toPlainText()
        self._saving = True
        self.status.setText("Saving the reviewed template…")
        self._run(lambda: rt.save_organized_edit(tid, text, expected=expected, bilingual=True), self._saved)

    @Slot(bool, object)
    def _saved(self, ok, result):
        self._busy = self._saving = False
        if self._closed:
            return
        if ok:
            self._current["edited_text"] = self.editor.toPlainText().strip()
            pair = (nt.find_by_id(result, self._current['id']) or {}).get('translations') or {}
            self._current['translations'] = pair
            self.english_preview.setPlainText(pair.get('en', ''))
            self.persian_preview.setPlainText(pair.get('fa', ''))
            self._dirty = False
            library_events.imported.emit(result)
            self.status.setText("Saved. The reviewed template is available in EchoMind > Normal Template.")
        else:
            self.status.setText(result)
        self._controls()

    def reject(self):
        if self._saving:
            return
        if self._dirty and QMessageBox.question(self, "Unsaved template edits",
                "Discard your unsaved changes?", QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel) != QMessageBox.Discard:
            return
        self._closed = True
        super().reject()

    def closeEvent(self, event):
        self.reject()
        event.accept() if self._closed else event.ignore()
