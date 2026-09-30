"""Dialog for selecting DICOM studies to embed in presentations."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QHeaderView, QMessageBox, QComboBox, QWidget
)
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QFont

from PacsClient.utils.database import get_db_connection
import sqlite3


class _StudyRowsTask(QThread):
    def __init__(self, study_pk=None, parent=None):
        super().__init__(parent)
        self.study_pk = study_pk
        self.rows = []
        self.failed = False

    def run(self):
        try:
            with get_db_connection() as conn:
                conn.row_factory = sqlite3.Row
                if self.study_pk is None:
                    query = """SELECT p.patient_id, p.patient_name, s.study_date,
                        s.study_description, s.modality, s.number_of_series,
                        s.study_uid, s.study_pk FROM studies s
                        JOIN patients p ON s.patient_fk=p.patient_pk
                        ORDER BY s.study_date DESC"""
                    self.rows = [dict(r) for r in conn.execute(query)]
                else:
                    self.rows = [dict(r) for r in conn.execute(
                        "SELECT series_number,series_description,modality,image_count,series_uid FROM series WHERE study_fk=? ORDER BY series_number",
                        (self.study_pk,))]
        except Exception:
            self.failed = True


class StudyPickerDialog(QDialog):
    """Dialog to select a DICOM study for presentation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select DICOM Study")
        self.setMinimumSize(1000, 600)
        self.selected_study_uid = None
        self.selected_patient_id = None
        self.selected_series_number = None
        self.mode = 'study'  # 'study' or 'series'
        self._query_workers = []
        self._query_generation = 0
        self._close_pending = False
        self.setup_ui()
        self.load_studies()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("Select a DICOM Study or Series")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(title)

        # Search and filter
        search_layout = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by patient name, ID, or study description...")
        self.search_input.textChanged.connect(self.filter_studies)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 8px;
                font-size: 11pt;
            }
        """)
        search_layout.addWidget(self.search_input, stretch=1)

        self.search_scope = QComboBox()
        self.search_scope.addItems(["Patient ID (exact)", "All fields"])
        self.search_scope.currentTextChanged.connect(lambda _: self.filter_studies(self.search_input.text()))
        search_layout.addWidget(self.search_scope)

        # Mode selector
        mode_label = QLabel("Select:")
        mode_label.setStyleSheet("color: #e2e8f0;")
        search_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Entire Study", "Specific Series"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 8px;
                min-width: 150px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border: none;
            }
        """)
        search_layout.addWidget(self.mode_combo)

        layout.addLayout(search_layout)

        # Studies table
        self.studies_table = QTableWidget()
        self.studies_table.setColumnCount(7)
        self.studies_table.setHorizontalHeaderLabels([
            "Patient ID", "Patient Name", "Study Date",
            "Study Description", "Modality", "Series Count", "Study UID"
        ])
        self.studies_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.studies_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.studies_table.setSelectionMode(QTableWidget.SingleSelection)
        self.studies_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.studies_table.doubleClicked.connect(self.on_study_double_clicked)
        self.studies_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.studies_table.setStyleSheet("""
            QTableWidget {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                gridline-color: #4a5568;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #3182ce;
            }
            QHeaderView::section {
                background-color: #1a202c;
                color: #e2e8f0;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.studies_table)

        # Series selection (hidden initially)
        self.series_panel = QWidget()
        series_layout = QVBoxLayout(self.series_panel)
        series_layout.setContentsMargins(0, 10, 0, 0)

        series_label = QLabel("Select Series:")
        series_label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        series_layout.addWidget(series_label)

        self.series_table = QTableWidget()
        self.series_table.setColumnCount(5)
        self.series_table.setHorizontalHeaderLabels([
            "Series Number", "Description", "Modality", "Image Count", "Series UID"
        ])
        self.series_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.series_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.series_table.setSelectionMode(QTableWidget.SingleSelection)
        self.series_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.series_table.setMaximumHeight(200)
        self.series_table.setStyleSheet(self.studies_table.styleSheet())
        # Enable the Select button when a series row is chosen (fixes 'Specific Series' mode being unusable).
        self.series_table.itemSelectionChanged.connect(self.on_series_selection_changed)
        self.series_table.doubleClicked.connect(self.on_series_double_clicked)
        series_layout.addWidget(self.series_table)

        self.series_panel.hide()
        layout.addWidget(self.series_panel)

        # Info label
        self.info_label = QLabel("Select a study from the list above")
        self.info_label.setStyleSheet("color: #a0aec0; font-style: italic;")
        layout.addWidget(self.info_label)

        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(100, 35)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6b7280;
            }
        """)
        buttons_layout.addWidget(cancel_btn)

        self.select_btn = QPushButton("Select")
        self.select_btn.setFixedSize(100, 35)
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.on_select)
        self.select_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
            QPushButton:disabled {
                background-color: #4a5568;
                color: #a0aec0;
            }
        """)
        buttons_layout.addWidget(self.select_btn)

        layout.addLayout(buttons_layout)

    def load_studies(self):
        self._start_rows_query()

    def load_series_for_study(self, study_pk):
        self.series_table.setRowCount(0)
        self.select_btn.setEnabled(False)
        self._start_rows_query(study_pk)

    def _start_rows_query(self, study_pk=None):
        self._query_generation += 1
        generation = self._query_generation
        task = _StudyRowsTask(study_pk, self)
        self._query_workers.append(task)
        task.finished.connect(lambda: self._rows_loaded(task, generation))
        task.start()

    def _rows_loaded(self, task, generation):
        self._query_workers.remove(task)
        task.deleteLater()
        if self._close_pending:
            if not self._query_workers:
                super().reject()
            return
        if generation != self._query_generation:
            return
        if task.failed:
            QMessageBox.warning(self, "Local Studies", "Could not read local studies. Please retry.")
            return
        is_study = task.study_pk is None
        table = self.studies_table if is_study else self.series_table
        fields = (["patient_id", "patient_name", "study_date", "study_description", "modality", "number_of_series", "study_uid"]
                  if is_study else ["series_number", "series_description", "modality", "image_count", "series_uid"])
        table.setRowCount(len(task.rows))
        for index, row in enumerate(task.rows):
            for col, field in enumerate(fields):
                value = row.get(field)
                table.setItem(index, col, QTableWidgetItem("" if value is None else str(value)))
            if is_study:
                table.item(index, 0).setData(Qt.UserRole, row["study_pk"])
        if is_study:
            self.filter_studies(self.search_input.text())

    def reject(self):
        if self._query_workers:
            self._close_pending = True
            self.setEnabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self._query_workers:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

    def filter_studies(self, text):
        """Filter studies based on search text."""
        self.studies_table.clearSelection()
        if self.studies_table.rowCount():
            self._query_generation += 1
        self.series_table.clearSelection()
        self.series_table.setRowCount(0)
        self.selected_study_uid = None
        self.selected_patient_id = None
        self.selected_series_number = None
        exact = self.search_scope.currentText() == "Patient ID (exact)"
        for row in range(self.studies_table.rowCount()):
            match = False
            for col in range(self.studies_table.columnCount()):
                item = self.studies_table.item(row, col)
                if item and text.lower() in item.text().lower():
                    match = True
                    break
            if exact and text.strip():
                item = self.studies_table.item(row, 0)
                match = bool(item and item.text().strip().casefold() == text.strip().casefold())
            self.studies_table.setRowHidden(row, not match)

    def on_mode_changed(self, text):
        """Handle mode change between study and series selection."""
        if text == "Specific Series":
            self.mode = 'series'
            self.series_panel.show()
            # Reset any prior series selection so the Select button reflects the new mode.
            self.selected_series_number = None
            self.series_table.clearSelection()
            self.on_selection_changed()  # Refresh series if study is selected
        else:
            self.mode = 'study'
            self.series_panel.hide()
            self.selected_series_number = None
            self.on_selection_changed()

    def on_selection_changed(self):
        """Handle study selection change."""
        selected_rows = self.studies_table.selectedItems()

        if selected_rows:
            row = self.studies_table.currentRow()
            study_uid_item = self.studies_table.item(row, 6)
            patient_id_item = self.studies_table.item(row, 0)

            if study_uid_item and patient_id_item:
                self.selected_study_uid = study_uid_item.text()
                self.selected_patient_id = patient_id_item.text()

                # Load series if in series mode
                if self.mode == 'series':
                    study_pk = self.studies_table.item(row, 0).data(Qt.UserRole)
                    self.load_series_for_study(study_pk)
                    # Reset any prior series selection ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ series_number must be re-chosen for the new study.
                    self.selected_series_number = None
                    self.series_table.clearSelection()
                    self.select_btn.setEnabled(False)
                    self.info_label.setText("Now select a series from the table below")
                else:
                    self.select_btn.setEnabled(True)
                    study_desc = self.studies_table.item(row, 3).text()
                    self.info_label.setText(f"Selected: {study_desc}")
        else:
            self.select_btn.setEnabled(False)
            self.info_label.setText("Select a study from the list above")

    def on_study_double_clicked(self):
        """Handle double-click on study (quick select)."""
        if self.mode == 'study':
            self.on_select()

    def on_series_selection_changed(self):
        """Enable the Select button only after a real series row is chosen (series mode)."""
        if self.mode != 'series':
            return
        selected = self.series_table.selectedItems()
        if selected:
            self.select_btn.setEnabled(True)
            series_row = self.series_table.currentRow()
            series_desc_item = self.series_table.item(series_row, 1)
            series_num_item = self.series_table.item(series_row, 0)
            label = ""
            if series_num_item:
                label = f"Series {series_num_item.text()}"
            if series_desc_item and series_desc_item.text().strip():
                label = f"{label}: {series_desc_item.text()}" if label else series_desc_item.text()
            if label:
                self.info_label.setText(f"Selected: {label}")
        else:
            self.select_btn.setEnabled(False)

    def on_series_double_clicked(self):
        """Quick-select a series on double-click (series mode)."""
        if self.mode == 'series' and self.series_table.selectedItems():
            self.on_select()

    def on_select(self):
        """Handle selection confirmation."""
        if self._query_workers:
            return
        row = self.studies_table.currentRow()
        if not self.studies_table.selectedItems() or row < 0 or self.studies_table.isRowHidden(row):
            return
        if self.mode == 'series':
            # Check if series is selected
            selected_series = self.series_table.selectedItems()
            if not selected_series:
                QMessageBox.warning(self, "No Series Selected", "Please select a series from the list.")
                return

            series_row = self.series_table.currentRow()
            series_number_item = self.series_table.item(series_row, 0)

            if series_number_item:
                try:
                    self.selected_series_number = int(str(series_number_item.text()).strip())
                except (TypeError, ValueError):
                    QMessageBox.warning(
                        self,
                        "Invalid Series",
                        "The selected series number is not a valid integer.",
                    )
                    return

        self.accept()

    def get_selected_study(self):
        """Return the selected study UID and patient ID."""
        return {
            'study_uid': self.selected_study_uid,
            'patient_id': self.selected_patient_id,
            'series_number': self.selected_series_number,
            'mode': self.mode
        }
