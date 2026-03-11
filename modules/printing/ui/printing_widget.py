"""Printing module UI widget."""

from __future__ import annotations

from pathlib import Path
from typing import List
from datetime import datetime

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QSpinBox,
    QSplitter,
    QGroupBox,
    QFormLayout,
    QDialogButtonBox,
    QLineEdit,
    QMessageBox,
    QCheckBox,
    QButtonGroup,
    QToolButton,
    QDialog,
    QFrame,
    QSlider,
    QSizePolicy,
    QScrollArea,
    QAbstractSpinBox,
)

from modules.printing.constants import DEFAULT_FILM_SIZES, DEFAULT_LAYOUTS
from modules.printing.core import FilmLayout, FilmSize, PrintJob, PrinterConfig, SeriesSelection, ViewportState
from modules.printing.core import load_printing_config, validate_print_job
from modules.printing.data import get_series_for_study
from modules.printing.data.filming_manager import FilmingDataManager
from modules.printing.ui.film_preview_widget import FilmPreviewWidget
from modules.printing.printers.os_printer import OSPrinterHandler
from modules.printing.printers.dicom_printer import (
    DicomImagePayload,
    DicomPrintHandler,
    DicomPrintJob,
    DicomPrinterSettings,
)
from modules.printing.render.dicom_renderer import load_dicom_as_pixmap, load_series_pixmaps
from PacsClient.utils.config import BASE_PATH
from PacsClient.utils import db_manager


class PrintingWidget(QWidget):
    """Top-level printing UI widget."""

    def __init__(self, parent=None, host_tab_widget=None, host_custom_tab_manager=None, selected_patients=None):
        super().__init__(parent)
        self.host_tab_widget = host_tab_widget
        self.host_custom_tab_manager = host_custom_tab_manager
        self._selected_patients = selected_patients or []
        self._active_patient = None

        self._selected_study_uid: str | None = None
        self._series_records: List[dict] = []
        self._selected_series: List[dict] = []
        self._selected_paths: List[str] = []
        self._film_pixmap = None
        self._current_page = 0
        self._total_pages = 1
        self._saved_filming_pages: List[dict] = []
        self._header_settings = {
            "center_name": "",
            "phone": "",
            "website": "",
            "extra": "",
            "font_patient_name": 24,
            "font_patient_id": 18,
            "font_center_name": 42,
            "font_right_block": 18,
        }

        self._viewport_state = ViewportState()
        self._printer_configs = self._load_printer_configs()
        self._dicom_print_settings = {
            "ip_address": "127.0.0.1",
            "port": 104,
            "ae_title": "PRINTER",
            "local_ae_title": "AIPACS",
            "film_orientation": "PORTRAIT",
            "medium_type": "PAPER",
            "film_destination": "PROCESSOR",
            "print_priority": "MED",
        }

        self._build_ui()
        self._load_selected_patients()

    def eventFilter(self, watched, event):
        """Debug event filter to log mouse events on series list."""
        if watched == self.series_list.viewport():
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.MouseButtonPress:
                mouse_event = event
                modifiers = mouse_event.modifiers()
                ctrl_held = bool(modifiers & Qt.ControlModifier)
                shift_held = bool(modifiers & Qt.ShiftModifier)
                print(f"[MOUSE_DEBUG] MouseButtonPress: Ctrl={ctrl_held}, Shift={shift_held}, button={mouse_event.button()}")
            elif event.type() == QEvent.MouseButtonRelease:
                mouse_event = event
                modifiers = mouse_event.modifiers()
                ctrl_held = bool(modifiers & Qt.ControlModifier)
                shift_held = bool(modifiers & Qt.ShiftModifier)
                print(f"[MOUSE_DEBUG] MouseButtonRelease: Ctrl={ctrl_held}, Shift={shift_held}, button={mouse_event.button()}")
        return super().eventFilter(watched, event)

    def _scaled(self, px: int) -> int:
        screen = self.screen()
        if not screen:
            return px
        try:
            dpi = float(screen.logicalDotsPerInch())
        except Exception:
            dpi = 96.0
        scale = max(1.0, min(2.0, dpi / 96.0))
        return int(round(px * scale))

    def _truncate_label(self, text: str, max_chars: int = 30) -> str:
        """Truncate text with ellipsis if it exceeds max length."""
        text = str(text or "").strip()
        if len(text) > max_chars:
            return text[:max_chars - 1] + "…"
        return text

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._selected_patient_info = {}

        self.layout_group = QButtonGroup(self)
        self.layout_group.setExclusive(True)
        self._current_layout = None
        self.layout_button = QPushButton("Layout")
        self.layout_button.setMinimumHeight(self._scaled(32))
        self.layout_button.clicked.connect(self._open_layout_dialog)
        self.header_button = QPushButton("Header Settings")
        self.header_button.setMinimumHeight(self._scaled(32))
        self.header_button.clicked.connect(self._open_header_settings_dialog)
        self.layout_label = QLabel("Layout: --")
        self.layout_label.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 12px;")
        self.layout_label.setMinimumWidth(self._scaled(100))
        self._set_current_layout(self._get_available_layouts()[0] if self._get_available_layouts() else None)

        self.film_size_combo = QComboBox()
        self.film_size_combo.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        self.film_size_combo.setMinimumHeight(self._scaled(32))
        self._populate_film_sizes()
        self.film_size_combo.currentIndexChanged.connect(self._on_film_size_changed)

        toolbar.addWidget(self.layout_button)
        toolbar.addWidget(self.header_button)
        toolbar.addWidget(self.layout_label)
        toolbar.addSpacing(8)

        # Film size label
        film_size_label = QLabel("Film")
        film_size_label.setStyleSheet("color: #cbd5e1; font-weight: 500; font-size: 11px;")
        # Page navigation
        self.prev_page_btn = QPushButton("◄")
        self.prev_page_btn.setMinimumWidth(self._scaled(36))
        self.prev_page_btn.setMinimumHeight(self._scaled(32))
        self.prev_page_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.page_label = QLabel("Page 1/1")
        self.page_label.setMinimumWidth(self._scaled(80))
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 12px;")
        self.next_page_btn = QPushButton("►")
        self.next_page_btn.setMinimumWidth(self._scaled(36))
        self.next_page_btn.setMinimumHeight(self._scaled(32))
        self.next_page_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.next_page_btn.clicked.connect(self._next_page)
        
        toolbar.addWidget(self.prev_page_btn)
        toolbar.addWidget(self.page_label)
        toolbar.addWidget(self.next_page_btn)
        toolbar.addSpacing(4)
        toolbar.addWidget(film_size_label)
        toolbar.addWidget(self.film_size_combo)
        toolbar.addStretch(1)

        toolbar.setContentsMargins(2, 2, 2, 2)
        toolbar.setSpacing(6)

        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(8)
        left_panel.setMaximumWidth(420)

        patient_group = QGroupBox("Selected Patients")
        patient_layout = QVBoxLayout(patient_group)
        self.patient_list = QListWidget()
        self.patient_list.setSelectionMode(QListWidget.SingleSelection)
        self.patient_list.setMaximumHeight(self._scaled(120))
        self.patient_list.itemSelectionChanged.connect(self._on_patient_selected)
        patient_layout.addWidget(self.patient_list)

        series_group = QGroupBox("Series")
        series_layout = QVBoxLayout(series_group)
        series_layout.setContentsMargins(8, 8, 8, 8)
        self.series_list = QListWidget()
        self.series_list.setMinimumHeight(self._scaled(480))
        self.series_list.setMaximumHeight(self._scaled(700))
        self.series_list.setSpacing(6)
        # Use ExtendedSelection: standard Qt pattern for Ctrl/Shift multi-select
        # - Click: select single item
        # - Ctrl+Click: add/remove item to selection
        # - Shift+Click: select range from anchor to clicked item
        self.series_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.series_list.setUniformItemSizes(False)
        self.series_list.setStyleSheet(
            """
            QListWidget {
                background: #1f2937;
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                border: none;
                margin: 2px;
                padding: 2px;
            }
            QListWidget::item:selected {
                background: #0f172a;
                border: 1px solid #22d3ee;
                border-radius: 6px;
            }
            """
        )
        # Connect to itemSelectionChanged to track selection internally
        # Use Qt.QueuedConnection to debounce rapid mouse events and prevent toggle-on/toggle-off
        # This ensures all pending selection events are batched before the slot is called
        self.series_list.itemSelectionChanged.connect(
            self._on_series_selection_changed, type=Qt.ConnectionType.QueuedConnection
        )
        # Install event filter to log mouse events for debugging
        self.series_list.viewport().installEventFilter(self)
        series_layout.addWidget(self.series_list)

        self.sync_checkbox = QCheckBox("Sync adjustments across images")
        self.sync_checkbox.setChecked(False)
        self.sync_checkbox.toggled.connect(self._on_sync_mode_changed)

        left_layout.addWidget(patient_group)
        left_layout.addWidget(self.sync_checkbox)
        left_layout.addWidget(series_group)
        left_layout.addStretch(1)

        self.preview_widget = FilmPreviewWidget()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(10)
        right_panel.setMinimumWidth(320)
        right_panel.setMaximumWidth(340)

        range_group = QGroupBox("Image range")
        range_layout = QHBoxLayout(range_group)
        range_layout.setContentsMargins(6, 8, 6, 8)
        range_layout.setSpacing(6)
        self.range_start = QSpinBox()
        self.range_start.setRange(1, 100000)
        self.range_start.setValue(1)
        self.range_start.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        self.range_start.setMinimumWidth(self._scaled(96))
        self.range_start.setMinimumHeight(self._scaled(36))
        self.range_start.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        self.range_end = QSpinBox()
        self.range_end.setRange(1, 100000)
        self.range_end.setValue(20)
        self.range_end.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        self.range_end.setMinimumWidth(self._scaled(96))
        self.range_end.setMinimumHeight(self._scaled(36))
        self.range_end.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        from_lbl = QLabel("From")
        from_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        range_layout.addWidget(from_lbl)
        range_layout.addWidget(self.range_start)
        range_layout.addSpacing(4)
        to_lbl = QLabel("To")
        to_lbl.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        range_layout.addWidget(to_lbl)
        range_layout.addWidget(self.range_end)
        range_layout.addStretch(1)

        adjustments_group = QGroupBox("Adjustments")
        adjustments_layout = QFormLayout(adjustments_group)
        adjustments_layout.setContentsMargins(6, 8, 6, 8)
        adjustments_layout.setVerticalSpacing(8)
        adjustments_layout.setHorizontalSpacing(6)
        adjustments_lbl = QLabel("Left Mouse")
        adjustments_lbl.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 12px;")
        adjustments_lbl.setMaximumWidth(self._scaled(140))
        self.left_drag_mode = QComboBox()
        self.left_drag_mode.addItems([
            "Default Mouse Function",
            "Pan",
            "Window Level / Window Width",
            "Zoom",
        ])
        self.left_drag_mode.currentTextChanged.connect(self._on_left_drag_mode_changed)
        self.left_drag_mode.blockSignals(True)
        self.left_drag_mode.setCurrentIndex(0)
        self.left_drag_mode.blockSignals(False)
        self.left_drag_mode.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        adjustments_layout.addRow(adjustments_lbl, self.left_drag_mode)

        printer_group = QGroupBox("Printer")
        printer_layout = QVBoxLayout(printer_group)
        printer_layout.setContentsMargins(6, 8, 6, 8)
        printer_layout.setSpacing(8)
        self.printer_type_combo = QComboBox()
        self.printer_type_combo.addItems(["Local Printer", "DICOM Printer"])
        self.printer_type_combo.currentTextChanged.connect(self._on_printer_type_changed)
        self.printer_type_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.local_printer_combo = QComboBox()
        self._populate_local_printers()
        self.local_printer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.dicom_settings_btn = QPushButton("DICOM Settings")
        self.dicom_settings_btn.setMinimumHeight(self._scaled(32))
        self.dicom_settings_btn.clicked.connect(self._open_dicom_printer_settings)

        self.printer_status = QLabel("Ready")
        self.printer_status.setStyleSheet("color: #93c5fd; font-size: 11px;")
        self.printer_status.setWordWrap(True)
        self.printer_status.setMaximumHeight(self._scaled(40))

        type_col = QVBoxLayout()
        type_col.setSpacing(4)
        type_col.setContentsMargins(0, 0, 0, 0)
        type_lbl = QLabel("Type")
        type_lbl.setStyleSheet("font-weight: 600; color: #cbd5e1; font-size: 12px;")
        type_col.addWidget(type_lbl)
        type_col.addWidget(self.printer_type_combo)
        printer_layout.addLayout(type_col)

        local_col = QVBoxLayout()
        local_col.setSpacing(4)
        local_col.setContentsMargins(0, 0, 0, 0)
        local_lbl = QLabel("Local Printer")
        local_lbl.setStyleSheet("font-weight: 600; color: #cbd5e1; font-size: 12px;")
        local_lbl.setMaximumWidth(self._scaled(180))
        local_col.addWidget(local_lbl)
        local_col.addWidget(self.local_printer_combo)
        printer_layout.addLayout(local_col)

        dicom_row = QHBoxLayout()
        dicom_row.setSpacing(6)
        dicom_row.setContentsMargins(0, 0, 0, 0)
        dicom_row.addWidget(self.dicom_settings_btn)
        dicom_row.addStretch(1)
        printer_layout.addLayout(dicom_row)
        printer_layout.addWidget(self.printer_status)
        self._on_printer_type_changed(self.printer_type_combo.currentText())

        self.delete_tiles_btn = QPushButton("Delete Selected Images")
        self.delete_tiles_btn.clicked.connect(self._delete_selected_tiles)

        self.refresh_series_btn = QPushButton("Load Series")
        self.refresh_series_btn.clicked.connect(self._load_series)

        self.preview_btn = QPushButton("Generate Report")
        self.preview_btn.setToolTip("Generate preview/report pages from selected series")
        self.preview_btn.clicked.connect(self._generate_preview)
        
        self.save_preview_btn = QPushButton("Save Preview")
        self.save_preview_btn.clicked.connect(self._save_preview)

        self.print_btn = QPushButton("Print")
        self.print_btn.clicked.connect(self._handle_print)

        action_buttons = [
            self.refresh_series_btn,
            self.preview_btn,
            self.save_preview_btn,
            self.print_btn,
            self.delete_tiles_btn,
            self.layout_button,
            self.header_button,
            self.dicom_settings_btn,
        ]
        for btn in action_buttons:
            btn.setMinimumHeight(self._scaled(38))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        right_layout.addWidget(range_group)
        right_layout.addWidget(adjustments_group)
        right_layout.addWidget(printer_group)
        
        # Saved filming pages section
        filming_group = QGroupBox("Saved Filming Pages")
        filming_layout = QVBoxLayout(filming_group)
        filming_layout.setContentsMargins(6, 6, 6, 6)
        self.filming_scroll = QScrollArea()
        self.filming_scroll.setWidgetResizable(True)
        self.filming_scroll.setMinimumHeight(180)
        self.filming_scroll.setMaximumHeight(280)
        self.filming_scroll.setStyleSheet(
            """
            QScrollArea {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
            }
            """
        )
        self.filming_container = QWidget()
        self.filming_container_layout = QVBoxLayout(self.filming_container)
        self.filming_container_layout.setSpacing(6)
        self.filming_container_layout.setAlignment(Qt.AlignTop)
        self.filming_scroll.setWidget(self.filming_container)
        filming_layout.addWidget(self.filming_scroll)
        right_layout.addWidget(filming_group)
        
        self.status_label = QLabel("Ready")
        right_layout.addWidget(self.status_label)
        right_layout.addStretch(1)

        splitter.addWidget(left_panel)
        splitter.addWidget(self.preview_widget)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 7)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([360, 900, 280])

        layout.addWidget(splitter)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        buttons_row.setContentsMargins(2, 4, 2, 4)
        buttons_row.addWidget(self.refresh_series_btn)
        buttons_row.addWidget(self.preview_btn)
        buttons_row.addWidget(self.save_preview_btn)
        buttons_row.addWidget(self.print_btn)
        buttons_row.addWidget(self.delete_tiles_btn)
        layout.addLayout(buttons_row)

        self._apply_modern_styles()

    def _load_selected_patients(self):
        self.patient_list.clear()
        if not self._selected_patients:
            self.status_label.setText("No selected patients")
            return
        for patient in self._selected_patients:
            label = f"{patient.get('patient_name', 'Unknown')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, patient)
            self.patient_list.addItem(item)
        if self.patient_list.count() > 0:
            self.patient_list.setCurrentRow(0)
        if self._current_layout:
            self.layout_label.setText(f"Layout: {self._current_layout.rows} x {self._current_layout.cols}")

    def _open_layout_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Layout")
        dialog.setModal(True)
        dialog.resize(420, 420)

        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(12)

        # Preset quick picks (common PACS print layouts)
        presets_row = QHBoxLayout()
        for r, c in [(3, 2), (4, 4), (4, 5)]:
            btn = QPushButton(f"{r}×{c}")
            btn.clicked.connect(lambda _, rr=r, cc=c: self._set_current_layout(FilmLayout(rows=rr, cols=cc)))
            presets_row.addWidget(btn)
        main_layout.addLayout(presets_row)

        # Numeric entry
        numeric_row = QHBoxLayout()
        rows_spin = QSpinBox()
        rows_spin.setRange(1, 10)
        rows_spin.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        cols_spin = QSpinBox()
        cols_spin.setRange(1, 10)
        cols_spin.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        if hasattr(self, "_spinbox_style"):
            rows_spin.setStyleSheet(self._spinbox_style)
            cols_spin.setStyleSheet(self._spinbox_style)
        if self._current_layout:
            rows_spin.setValue(self._current_layout.rows)
            cols_spin.setValue(self._current_layout.cols)
        else:
            rows_spin.setValue(3)
            cols_spin.setValue(2)
        apply_custom = QPushButton("Apply")
        apply_custom.clicked.connect(lambda: self._set_current_layout(FilmLayout(rows=rows_spin.value(), cols=cols_spin.value())))
        numeric_row.addWidget(QLabel("Rows"))
        numeric_row.addWidget(rows_spin)
        numeric_row.addWidget(QLabel("Cols"))
        numeric_row.addWidget(cols_spin)
        numeric_row.addWidget(apply_custom)
        main_layout.addLayout(numeric_row)

        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(10)

        button_group = QButtonGroup(dialog)
        button_group.setExclusive(True)

        layouts = self._get_available_layouts()
        for idx, layout_item in enumerate(layouts):
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setToolTip(f"{layout_item.rows} x {layout_item.cols}")
            btn.setIcon(self._layout_icon(layout_item.rows, layout_item.cols))
            btn.setIconSize(QSize(48, 48))
            btn.clicked.connect(lambda checked, l=layout_item: self._set_current_layout(l))
            button_group.addButton(btn)
            row = idx // 3
            col = idx % 3
            grid_layout.addWidget(btn, row, col)
            if self._current_layout and layout_item.rows == self._current_layout.rows and layout_item.cols == self._current_layout.cols:
                btn.setChecked(True)

        main_layout.addWidget(grid_container)

        selected_label = QLabel()
        selected_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(selected_label)

        def update_label():
            if self._current_layout:
                selected_label.setText(f"Selected layout: {self._current_layout.rows} x {self._current_layout.cols}")
                self.layout_label.setText(f"Layout: {self._current_layout.rows} x {self._current_layout.cols}")
            else:
                selected_label.setText("Selected layout: --")
                self.layout_label.setText("Layout: --")

        update_label()
        button_group.buttonClicked.connect(lambda _: update_label())

        close_btn = QPushButton("Done")
        close_btn.clicked.connect(dialog.accept)
        main_layout.addWidget(close_btn)

        dialog.exec()

    def _layout_icon(self, rows: int, cols: int):
        from PySide6.QtGui import QPainter, QPixmap, QColor, QPen

        pixmap = QPixmap(34, 34)
        pixmap.fill(QColor(30, 41, 59))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(148, 163, 184))
        pen.setWidth(1)
        painter.setPen(pen)

        cell_w = 28 / cols
        cell_h = 28 / rows
        start_x = 3
        start_y = 3
        for r in range(rows):
            for c in range(cols):
                x = start_x + c * cell_w
                y = start_y + r * cell_h
                painter.drawRect(int(x), int(y), int(cell_w), int(cell_h))
        painter.end()
        return pixmap

    def _set_current_layout(self, layout: FilmLayout):
        if layout is None:
            return
        self._current_layout = layout
        if hasattr(self, "layout_label"):
            self.layout_label.setText(f"Layout: {layout.rows} x {layout.cols}")

    def _get_available_layouts(self) -> List[FilmLayout]:
        config = load_printing_config()
        layouts = []
        for item in config.get("default_layouts", []):
            try:
                layouts.append(FilmLayout(rows=int(item["rows"]), cols=int(item["cols"])))
            except Exception:
                continue
        if not layouts:
            layouts = DEFAULT_LAYOUTS
        return layouts

    def _populate_film_sizes(self):
        config = load_printing_config()
        sizes = []
        for item in config.get("default_film_sizes", []):
            try:
                sizes.append(FilmSize(name=item["name"], width_in=float(item["width_in"]), height_in=float(item["height_in"])))
            except Exception:
                continue
        if not sizes:
            sizes = DEFAULT_FILM_SIZES
        for size_item in sizes:
            self.film_size_combo.addItem(size_item.name, size_item)

    def _on_patient_selected(self):
        selected_items = self.patient_list.selectedItems()
        if not selected_items:
            return
        patient = selected_items[0].data(Qt.UserRole)
        if not patient:
            return
        self._active_patient = patient
        self._selected_patient_info = patient
        self._selected_study_uid = patient.get("study_uid")
        self._load_series()
        self._load_filming_pages()

    def _load_series(self):
        self.series_list.clear()
        self._series_records = []
        if not self._selected_study_uid:
            print("[PRINTING] No study_uid selected")
            return
        print(f"[PRINTING] Loading series for study_uid: {self._selected_study_uid}")
        
        # Use enriched series loader for fault-tolerance
        try:
            from modules.printing.data.dicom_enrichment import get_series_with_enrichment
            series = get_series_with_enrichment(self._selected_study_uid)
        except Exception as e:
            print(f"[PRINTING] ⚠️ Enrichment failed, falling back: {e}")
            series = get_series_for_study(self._selected_study_uid)
        
        print(f"[PRINTING] Found {len(series)} series")
        
        for item in series:
            series_num = item.get('series_number', 'unknown')
            series_desc = item.get('series_description', '')
            modality = item.get('modality', '')
            img_count = item.get('image_count', 0)

            list_item = QListWidgetItem()
            list_item.setSizeHint(QSize(0, self._scaled(96)))
            list_item.setData(Qt.UserRole, item)
            self.series_list.addItem(list_item)
            thumb_pm = self._build_series_thumbnail_pixmap(item)
            widget = self._build_series_thumbnail_widget(
                series=item,
                series_number=self._truncate_label(str(series_num), 20),
                description=self._truncate_label(str(series_desc), 60),
                modality=self._truncate_label(str(modality), 15),
                image_count=int(img_count or 0),
                thumbnail=thumb_pm,
            )
            self.series_list.setItemWidget(list_item, widget)
            self._series_records.append(item)
            print(f"[PRINTING]   series_pk={item.get('series_pk')}, series_number={series_num}, images={img_count}")
        
        if self.series_list.count() > 0:
            first_item = self.series_list.item(0)
            if first_item is not None:
                self.series_list.setCurrentItem(first_item)
                first_item.setSelected(True)
                self._on_series_selection_changed()
        
        if series:
            self.status_label.setText(f"Loaded {len(series)} series")
        else:
            self.status_label.setText("No series found for selected study")

    def _on_series_selection_changed(self):
        """
        Sync internal series list with current QListWidget selection.
        Called automatically by itemSelectionChanged signal from ExtendedSelection mode.
        ExtendedSelection handles Ctrl/Shift modifier keys automatically:
        - Click: select single item (clears previous selection)
        - Ctrl+Click: add/remove item to existing selection
        - Shift+Click: select range from anchor point to clicked item
        """
        print(f"[SELECTION_DEBUG] ========== _on_series_selection_changed CALLED ==========")
        print(f"[SELECTION_DEBUG] Total items in list: {self.series_list.count()}")
        
        # Log which items are currently selected in the widget
        selected_items = self.series_list.selectedItems()
        print(f"[SELECTION_DEBUG] selectedItems() returned: {len(selected_items)} items")
        
        for idx, item in enumerate(selected_items):
            series = item.data(Qt.UserRole)
            series_desc = series.get('SeriesDescription', 'N/A') if series else 'NO_DATA'
            print(f"[SELECTION_DEBUG]   [{idx}] Selected: {series_desc}")
        
        # Update internal state
        self._selected_series = []
        for item in self.series_list.selectedItems():
            series = item.data(Qt.UserRole)
            if series:
                self._selected_series.append(series)
        
        print(f"[SELECTION_DEBUG] Internal _selected_series updated: {len(self._selected_series)} items")
        print(f"[SELECTION_DEBUG] ========== END ==========\n")
        
        self.status_label.setText(f"Selected {len(self._selected_series)} series")

    def _build_series_thumbnail_widget(
        self,
        series: dict,
        series_number: str,
        description: str,
        modality: str,
        image_count: int,
        thumbnail: QPixmap | None = None,
    ) -> QWidget:
        container = QFrame()
        container.setObjectName("seriesThumb")
        container.setStyleSheet(
            """
            QFrame#seriesThumb {
                background: #111827;
                border: 1px solid #374151;
                border-radius: 8px;
            }
            QFrame#seriesThumb:hover {
                border-color: #60a5fa;
                background: #1a202c;
            }
            """
        )
        
        # Store series data on container for click selection
        container._series_data = series
        
        # Make container respond to mouse clicks to select series
        def make_mouse_release_handler(series_ref):
            def on_mouse_release(event):
                # Select this series when clicked anywhere on the card
                print(f"[PRINTING] Series thumbnail clicked: series_number={series_ref.get('series_number')}")
                self._select_series_for_action(series_ref, clear_existing=True)
            return on_mouse_release
        
        container.mouseReleaseEvent = make_mouse_release_handler(series)

        row = QHBoxLayout(container)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        thumb = QLabel()
        thumb.setFixedSize(72, 54)
        thumb.setStyleSheet("background:#1f2937; border:1px solid #4b5563; border-radius:6px;")

        pm = thumbnail if thumbnail is not None and not thumbnail.isNull() else self._create_series_placeholder_pixmap()
        thumb.setPixmap(pm)

        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(f"Series {series_number}")
        title.setStyleSheet("font-weight:600; color:#e5e7eb;")
        desc = QLabel(description or "-")
        desc.setStyleSheet("color:#cbd5e1;")
        desc.setWordWrap(True)
        meta = QLabel(f"{modality} • {image_count} images")
        meta.setStyleSheet("color:#93c5fd;")

        info.addWidget(title)
        info.addWidget(desc)
        info.addWidget(meta)

        actions = QVBoxLayout()
        actions.setSpacing(4)
        view_btn = QPushButton("View")
        view_btn.setMinimumWidth(self._scaled(86))
        view_btn.setMinimumHeight(self._scaled(36))
        view_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        view_btn.clicked.connect(lambda: self._open_series_viewer(series, ensure_selection=True))
        view_btn_style = """
            QPushButton {
                background: #1e3a8a;
                color: #ffffff;
                border: 1px solid #2563eb;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #2563eb;
                border-color: #3b82f6;
            }
            QPushButton:pressed {
                background: #1e40af;
            }
        """
        view_btn.setStyleSheet(view_btn_style)
        actions.addWidget(view_btn)
        actions.addStretch(1)

        row.addWidget(thumb)
        row.addLayout(info, 1)
        row.addLayout(actions)
        return container

    def _series_matches(self, left: dict, right: dict) -> bool:
        if not left or not right:
            return False

        if left.get("series_pk") and right.get("series_pk"):
            return str(left.get("series_pk")) == str(right.get("series_pk"))

        if left.get("series_uid") and right.get("series_uid"):
            return str(left.get("series_uid")) == str(right.get("series_uid"))

        left_path = str(left.get("series_path") or "").strip().lower()
        right_path = str(right.get("series_path") or "").strip().lower()
        if left_path and right_path and left_path == right_path:
            return True

        return (
            str(left.get("series_number") or "") == str(right.get("series_number") or "")
            and str(left.get("series_description") or "") == str(right.get("series_description") or "")
        )

    def _select_series_for_action(self, series: dict, clear_existing: bool = False) -> bool:
        matched = False
        if clear_existing:
            self.series_list.clearSelection()

        for row in range(self.series_list.count()):
            item = self.series_list.item(row)
            if item is None:
                continue
            item_series = item.data(Qt.UserRole)
            if self._series_matches(item_series or {}, series or {}):
                item.setSelected(True)
                self.series_list.setCurrentItem(item)
                matched = True
                break

        if matched:
            self._on_series_selection_changed()
        return matched

    def _ensure_series_selection(self) -> List[dict]:
        # Prefer explicit current selection
        if self._selected_series:
            return self._selected_series

        # Synchronize from QListWidget selection if internal list got stale
        selected_items = self.series_list.selectedItems()
        if selected_items:
            self._on_series_selection_changed()
            if self._selected_series:
                return self._selected_series

        # Fallback: use current row item
        current_item = self.series_list.currentItem()
        if current_item is not None:
            current_item.setSelected(True)
            self._on_series_selection_changed()
            if self._selected_series:
                return self._selected_series

        # Final fallback: auto-select first available series
        if self.series_list.count() > 0:
            first_item = self.series_list.item(0)
            if first_item is not None:
                self.series_list.setCurrentItem(first_item)
                first_item.setSelected(True)
                self._on_series_selection_changed()

        return self._selected_series

    def _create_series_placeholder_pixmap(self) -> QPixmap:
        pm = QPixmap(72, 54)
        pm.fill(QColor("#1f2937"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#9ca3af"))
        p.setPen(pen)
        p.drawRect(8, 8, 56, 38)
        p.drawLine(8, 8, 64, 46)
        p.drawLine(8, 46, 64, 8)
        p.end()
        return pm

    def _build_series_thumbnail_pixmap(self, series: dict) -> QPixmap:
        # 1) Prefer pre-generated thumbnail path from DB (same PACS thumbnail flow)
        thumb_path = series.get("thumbnail_path")
        if thumb_path:
            p = Path(str(thumb_path))
            if p.exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    return pix.scaled(72, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # 1.5) Local thumbnail fallback: thumbnails/{study_uid}/{series_number}.png
        try:
            study_uid = self._selected_study_uid
            series_number = str(series.get("series_number", "")).strip()
            if study_uid and series_number:
                local_thumb = Path(BASE_PATH) / "thumbnails" / str(study_uid) / f"{series_number}.png"
                if local_thumb.exists():
                    pix = QPixmap(str(local_thumb))
                    if not pix.isNull():
                        return pix.scaled(72, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            pass

        # 2) Fallback: render first DICOM like viewer flow (WL aware)
        try:
            from modules.printing.data.series_repository import get_dicom_paths_for_series
            paths: List[str] = []
            series_pk = series.get("series_pk")
            if series_pk:
                paths = get_dicom_paths_for_series(series_pk)
            elif series.get("series_path"):
                series_dir = Path(str(series.get("series_path")))
                if series_dir.exists():
                    paths = [str(x) for x in series_dir.glob("*.dcm") if x.is_file()]

            if paths:
                rendered = load_dicom_as_pixmap(paths[0], None)
                if rendered and not rendered.pixmap.isNull():
                    return rendered.pixmap.scaled(72, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            pass

        # 3) Placeholder
        return self._create_series_placeholder_pixmap()

    def _open_series_viewer(self, series: dict, ensure_selection: bool = False) -> None:
        from modules.printing.data.series_repository import get_dicom_paths_for_series

        if ensure_selection:
            self._select_series_for_action(series, clear_existing=True)

        series_pk = series.get("series_pk")
        paths: List[str] = []
        if series_pk:
            paths = get_dicom_paths_for_series(series_pk)
        elif series.get("series_path"):
            series_dir = Path(str(series.get("series_path")))
            if series_dir.exists():
                paths = [str(x) for x in series_dir.glob("*.dcm") if x.is_file()]

        if not paths:
            QMessageBox.information(self, "Series Viewer", "No images found for this series.")
            return

        dialog = QDialog(self)
        series_number = series.get("series_number", "-")
        dialog.setWindowTitle(f"Series {series_number} Viewer")
        dialog.resize(900, 700)

        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(10)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumSize(640, 480)
        image_label.setStyleSheet("background:#0b1220; border:1px solid #334155; border-radius:8px;")
        main_layout.addWidget(image_label, 1)

        controls = QHBoxLayout()
        prev_btn = QPushButton("Prev")
        next_btn = QPushButton("Next")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, max(0, len(paths) - 1))
        index_label = QLabel()
        index_label.setStyleSheet("color:#cbd5e1;")
        set_scout_btn = QPushButton("Set as Scout")
        clear_scout_btn = QPushButton("Clear Scout")

        if hasattr(self, "_button_style"):
            prev_btn.setStyleSheet(self._button_style)
            next_btn.setStyleSheet(self._button_style)
            set_scout_btn.setStyleSheet(self._button_style)
            clear_scout_btn.setStyleSheet(self._button_style)

        controls.addWidget(prev_btn)
        controls.addWidget(next_btn)
        controls.addWidget(slider, 1)
        controls.addWidget(index_label)
        controls.addWidget(set_scout_btn)
        controls.addWidget(clear_scout_btn)
        main_layout.addLayout(controls)

        def update_image(idx: int) -> None:
            idx = max(0, min(idx, len(paths) - 1))
            rendered = load_dicom_as_pixmap(paths[idx], None)
            if rendered and not rendered.pixmap.isNull():
                pm = rendered.pixmap.scaled(image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                image_label.setPixmap(pm)
            index_label.setText(f"{idx + 1} / {len(paths)}")

        def step(delta: int) -> None:
            slider.setValue(max(0, min(slider.value() + delta, len(paths) - 1)))

        slider.valueChanged.connect(update_image)
        prev_btn.clicked.connect(lambda: step(-1))
        next_btn.clicked.connect(lambda: step(1))

        def set_scout() -> None:
            self.preview_widget.set_scout_path(paths[slider.value()])
            self.status_label.setText("Scout image selected")

        def clear_scout() -> None:
            self.preview_widget.set_scout_path(None)
            self.status_label.setText("Scout image cleared")

        set_scout_btn.clicked.connect(set_scout)
        clear_scout_btn.clicked.connect(clear_scout)

        update_image(0)
        dialog.exec()

    def _apply_modern_styles(self) -> None:
        arrow_path = (BASE_PATH / "Qss" / "icons" / "fefefe" / "feather" / "chevron-down.png").as_posix()
        combo_style = f"""
            QComboBox {{
                background: #0f172a;
                color: #e5e7eb;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 28px 6px 10px;
                min-height: 30px;
            }}
            QComboBox:hover {{
                border-color: #60a5fa;
            }}
            QComboBox:focus {{
                border: 1px solid #38bdf8;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #334155;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
                background: #111827;
            }}
            QComboBox::down-arrow {{
                image: url({arrow_path});
                width: 12px;
                height: 12px;
            }}
            QComboBox QAbstractItemView {{
                background: #0f172a;
                color: #e5e7eb;
                border: 1px solid #334155;
                selection-background-color: #1d4ed8;
                selection-color: #ffffff;
            }}
        """

        button_style = """
            QPushButton {
                background: #1e293b;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #334155;
                border-color: #60a5fa;
            }
            QPushButton:pressed {
                background: #0f172a;
            }
        """

        spinbox_style = """
            QSpinBox {
                background: #0f172a;
                color: #e5e7eb;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px 36px 8px 10px;
                min-height: 38px;
                font-size: 14px;
                font-weight: 500;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                background: #1e293b;
                border-left: 1px solid #334155;
                width: 36px;
            }
            QSpinBox::up-button {
                subcontrol-position: top right;
                border-top-right-radius: 8px;
                height: 19px;
            }
            QSpinBox::down-button {
                subcontrol-position: bottom right;
                border-bottom-right-radius: 8px;
                height: 19px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #334155;
            }
            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
                background: #0f172a;
            }
            QSpinBox:hover {
                border-color: #60a5fa;
            }
            QSpinBox:focus {
                border: 1px solid #38bdf8;
            }
        """

        self._combo_style = combo_style
        self._button_style = button_style
        self._spinbox_style = spinbox_style

        for cb in [self.film_size_combo, self.left_drag_mode, self.printer_type_combo, self.local_printer_combo]:
            cb.setStyleSheet(combo_style)

        for btn in [self.layout_button, self.header_button, self.refresh_series_btn, self.preview_btn, self.save_preview_btn, self.print_btn, self.delete_tiles_btn, self.dicom_settings_btn]:
            btn.setStyleSheet(button_style)
        
        for page_btn in [self.prev_page_btn, self.next_page_btn]:
            page_btn.setStyleSheet(button_style)

        for spin in [self.range_start, self.range_end]:
            spin.setStyleSheet(spinbox_style)

    def _collect_image_paths(self) -> List[str]:
        from pathlib import Path
        from modules.printing.data.series_repository import get_dicom_paths_for_series
        try:
            from natsort import natsorted
        except Exception:
            natsorted = sorted
        
        paths: List[str] = []
        selected_series = self._ensure_series_selection()
        if not selected_series:
            print("[PRINTING] No series selected")
            return []
        print(f"[PRINTING] Collecting paths for {len(selected_series)} selected series")
        for series in selected_series:
            series_pk = series.get("series_pk")
            
            # Handle series discovered from filesystem (no series_pk)
            if not series_pk:
                print(f"[PRINTING] Series has no pk, using direct path from discovery")
                series_path_str = series.get("series_path")
                if series_path_str:
                    series_dir = Path(series_path_str)
                    if series_dir.exists():
                        files = [
                            *series_dir.glob("*.dcm"),
                            *series_dir.glob("*.DCM"),
                        ]
                        files = [str(p) for p in natsorted(files) if p.is_file()]
                        print(f"[PRINTING]   Got {len(files)} paths from direct scan")
                        paths.extend(files)
                continue
            
            print(f"[PRINTING] Processing series_pk={series_pk}")
            series_paths = get_dicom_paths_for_series(series_pk)
            series_paths = [p for p in sorted(series_paths) if p and Path(p).exists()]
            print(f"[PRINTING]   Got {len(series_paths)} paths")
            paths.extend(series_paths)

        print(f"[PRINTING] Total paths before range filter: {len(paths)}")
        start = max(self.range_start.value(), 1) - 1
        end = max(self.range_end.value(), start + 1)
        end = min(end, len(paths))
        print(f"[PRINTING] Range filter: {start} to {end}")
        return paths[start:end]

    def _build_viewport(self) -> ViewportState:
        return ViewportState()

    def _on_film_size_changed(self, index: int) -> None:
        """Re-render the preview when the film size combo changes."""
        if not self._selected_paths:
            return  # No preview yet — nothing to refresh
        self._update_page_display()

    def _generate_preview(self):
        print("[PRINTING] === Generate Preview Started ===")
        self.status_label.setText("Generating preview...")
        self._selected_paths = self._collect_image_paths()
        print(f"[PRINTING] Collected {len(self._selected_paths)} image paths")
        
        scout_path = self.preview_widget.get_scout_path() if self.preview_widget else None
        print(f"[PRINTING] Scout path: {scout_path}")
        if scout_path:
            self._selected_paths = [p for p in self._selected_paths if p != scout_path]
            print(f"[PRINTING] After removing scout: {len(self._selected_paths)} paths")
        
        if not self._selected_paths:
            study_uid = self._selected_study_uid or "Unknown"
            print(f"[PRINTING] ERROR: No image paths found for study {study_uid}")
            QMessageBox.warning(
                self,
                "No images",
                (
                    "No local DICOM files were found for the selected series.\n\n"
                    f"Study UID: {study_uid}\n"
                    "Please re-download this study/series from PACS, then try Generate Report again."
                ),
            )
            self.status_label.setText("No images for preview")
            return

        layout = self._current_layout
        film_size = self.film_size_combo.currentData()
        print(f"[PRINTING] Layout: {layout.rows}x{layout.cols}, Film size: {film_size.name if film_size else 'None'}")
        
        if not isinstance(layout, FilmLayout) or not isinstance(film_size, FilmSize):
            print("[PRINTING] ERROR: Invalid layout or film size")
            QMessageBox.warning(self, "Invalid layout", "Select a layout and film size.")
            return

        # Calculate pagination accounting for scout reservation logic
        total_cells = layout.rows * layout.cols
        scout_reserved = bool(scout_path) or total_cells > 1
        available_cells_for_images = total_cells - (1 if scout_reserved else 0)
        images_per_page = max(1, available_cells_for_images)
        
        print(f"[PRINTING] Total cells: {total_cells}, Scout reserved: {scout_reserved}, Available for images: {available_cells_for_images}, Per page: {images_per_page}")
        
        self._total_pages = max(1, (len(self._selected_paths) + images_per_page - 1) // images_per_page)
        self._current_page = 0
        print(f"[PRINTING] Total pages: {self._total_pages}")
        
        self._update_page_display()

    def _update_page_display(self):
        layout = self._current_layout
        film_size = self.film_size_combo.currentData()
        if not isinstance(layout, FilmLayout) or not isinstance(film_size, FilmSize):
            print("[PRINTING-DISPLAY] Invalid layout/film_size")
            return

        # Match the pagination logic from _generate_preview
        total_cells = layout.rows * layout.cols
        scout_path = self.preview_widget.get_scout_path() if self.preview_widget else None
        scout_reserved = bool(scout_path) or total_cells > 1
        available_cells_for_images = total_cells - (1 if scout_reserved else 0)
        images_per_page = max(1, available_cells_for_images)
        
        start_idx = self._current_page * images_per_page
        end_idx = min(start_idx + images_per_page, len(self._selected_paths))
        page_paths = self._selected_paths[start_idx:end_idx]
        
        print(f"[PRINTING-DISPLAY] Page {self._current_page + 1}: start={start_idx}, end={end_idx}, paths={len(page_paths)}/{len(self._selected_paths)}")

        overlay_info = self._build_overlay_info()
        overlay_info["sequence_start"] = start_idx + 1
        print(f"[PRINTING-DISPLAY] Calling set_tiles with {len(page_paths)} paths, layout {layout.rows}x{layout.cols}")
        self.preview_widget.set_tiles(film_size, layout, page_paths, overlay_info=overlay_info)
        self._film_pixmap = self.preview_widget.export_film_pixmap(dpi=150)
        print(f"[PRINTING-DISPLAY] export_film_pixmap returned: {self._film_pixmap is not None}")
        
        self.page_label.setText(f"Page {self._current_page + 1}/{self._total_pages}")
        self.prev_page_btn.setEnabled(self._current_page > 0)
        self.next_page_btn.setEnabled(self._current_page < self._total_pages - 1)
        self.status_label.setText(f"Page {self._current_page + 1}/{self._total_pages} ({len(page_paths)} images)")

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._update_page_display()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._update_page_display()

    def _handle_print(self):
        if self._film_pixmap is None:
            self._generate_preview()
            if self._film_pixmap is None:
                return

        high_res_pixmap = self._render_for_print(dpi=300)
        if high_res_pixmap is None:
            QMessageBox.warning(self, "Print", "Failed to render print image.")
            return

        printer = PrinterConfig(name="Selected", printer_type="os")
        job = self._build_print_job(printer)
        errors = validate_print_job(job)
        if errors:
            QMessageBox.warning(self, "Print validation", "\n".join(errors))
            return

        if self.printer_type_combo.currentText() == "Local Printer":
            handler = OSPrinterHandler()
            selected_printer = self.local_printer_combo.currentText().strip() or None
            success = handler.print_film(high_res_pixmap, selected_printer)
            if not success:
                QMessageBox.warning(self, "Print", "OS print canceled or failed.")
            return

        if self.printer_type_combo.currentText() == "DICOM Printer":
            try:
                settings = DicomPrinterSettings(
                    ip_address=self._dicom_print_settings.get("ip_address", "127.0.0.1"),
                    port=int(self._dicom_print_settings.get("port", 104)),
                    ae_title=self._dicom_print_settings.get("ae_title", "PRINTER"),
                )
                handler = DicomPrintHandler(settings)
                job = self._build_dicom_job()
                success = handler.send_print_job(job)
                if not success:
                    QMessageBox.warning(self, "DICOM Print", "DICOM print failed.")
            except Exception as exc:
                QMessageBox.warning(self, "DICOM Print", str(exc))
            return

        QMessageBox.warning(self, "Print", "Unsupported printer type.")

    def _build_print_job(self, printer: PrinterConfig) -> PrintJob:
        layout = self._current_layout
        film_size = self.film_size_combo.currentData()
        if not isinstance(layout, FilmLayout):
            layout = FilmLayout(rows=1, cols=1)
        if not isinstance(film_size, FilmSize):
            film_size = FilmSize(name="14x17", width_in=14.0, height_in=17.0)

        series_selection = SeriesSelection(
            study_uid=self._selected_study_uid or "",
            series_uids=[s.get("series_uid", "") for s in self._selected_series],
            image_selections=[],
        )

        patient_name = self._selected_patient_info.get("patient_name", "")
        patient_id = self._selected_patient_info.get("patient_id", "")

        return PrintJob(
            patient_id=patient_id,
            patient_name=patient_name,
            study_uid=self._selected_study_uid or "",
            film_size=film_size,
            layout=layout,
            series_selection=series_selection,
            printer=printer,
            metadata={"range": f"{self.range_start.value()}-{self.range_end.value()}"},
        )

    def _build_dicom_job(self) -> DicomPrintJob:
        layout = self._current_layout
        film_size = self.film_size_combo.currentData()
        layout = layout if isinstance(layout, FilmLayout) else FilmLayout(1, 1)
        film_size = film_size if isinstance(film_size, FilmSize) else FilmSize("14x17", 14, 17)

        viewport = self._build_viewport() if self.sync_checkbox.isChecked() else None
        rendered = load_series_pixmaps(self._selected_paths, viewport)
        rendered = rendered[: layout.rows * layout.cols]
        images: List[DicomImagePayload] = []

        for render in rendered:
            qimage = render.pixmap.toImage()
            qimage = qimage.convertToFormat(qimage.Format_Grayscale8)
            width = qimage.width()
            height = qimage.height()
            ptr = qimage.bits()
            ptr.setsize(qimage.sizeInBytes())
            pixel_data = bytes(ptr)
            images.append(DicomImagePayload(rows=height, columns=width, pixel_data=pixel_data))

        image_display_format = f"STANDARD\\{layout.rows},{layout.cols}"
        film_size_key = film_size.name.upper().replace(" ", "")
        film_size_map = {
            "14X17": "14INX17IN",
            "11X14": "11INX14IN",
            "8X10": "8INX10IN",
            "A3": "A3",
            "A4": "A4",
        }
        film_size_id = film_size_map.get(
            film_size_key,
            f"{film_size.width_in:.0f}INX{film_size.height_in:.0f}IN",
        )

        return DicomPrintJob(
            images=images,
            image_display_format=image_display_format,
            film_size_id=film_size_id,
            print_priority=self._dicom_print_settings.get("print_priority", "MED"),
            medium_type=self._dicom_print_settings.get("medium_type", "PAPER"),
            film_destination=self._dicom_print_settings.get("film_destination", "PROCESSOR"),
            film_orientation=self._dicom_print_settings.get("film_orientation", "PORTRAIT"),
        )

    def _render_for_print(self, dpi: int = 300):
        return self.preview_widget.export_film_pixmap(dpi=dpi)

    def _build_overlay_info(self) -> dict:
        institution = ""
        if self._selected_series:
            institution = self._selected_series[0].get("institution_name", "")

        patient_name = self._selected_patient_info.get("patient_name", "")
        patient_id = self._selected_patient_info.get("patient_id", "")

        needs_dicom = not patient_name or not patient_id or not institution
        if needs_dicom:
            sample_path = None
            if self._selected_paths:
                sample_path = self._selected_paths[0]
            elif self._selected_series:
                try:
                    from modules.printing.data.series_repository import get_dicom_paths_for_series
                    series_pk = self._selected_series[0].get("series_pk")
                    if series_pk:
                        paths = get_dicom_paths_for_series(series_pk)
                        if paths:
                            sample_path = paths[0]
                except Exception:
                    sample_path = None

            if sample_path:
                try:
                    import pydicom

                    dcm = pydicom.dcmread(sample_path, stop_before_pixels=True, force=True)
                    if not patient_name:
                        patient_name = str(getattr(dcm, "PatientName", ""))
                    if not patient_id:
                        patient_id = str(getattr(dcm, "PatientID", ""))
                    if not institution:
                        institution = str(getattr(dcm, "InstitutionName", ""))
                except Exception:
                    pass

        center_name = self._header_settings.get("center_name") or institution
        phone = self._header_settings.get("phone") or ""
        website = self._header_settings.get("website") or ""
        extra = self._header_settings.get("extra") or ""
        right_line_1 = " | ".join([v for v in [extra, phone] if v])
        right_line_2 = website

        return {
            "institution": institution,
            "patient_name": patient_name,
            "patient_id": patient_id,
            "center_name": center_name,
            "header_right_line_1": right_line_1,
            "header_right_line_2": right_line_2,
            "font_patient_name": self._header_settings.get("font_patient_name", 24),
            "font_patient_id": self._header_settings.get("font_patient_id", 18),
            "font_center_name": self._header_settings.get("font_center_name", 42),
            "font_right_block": self._header_settings.get("font_right_block", 18),
        }

    def _delete_selected_tiles(self):
        if not self.preview_widget:
            return
        self._selected_paths = self.preview_widget.delete_selected_tiles()

    def _on_left_drag_mode_changed(self, text: str):
        if not self.preview_widget:
            return
        from modules.printing.ui.print_tools import PrintToolManager
        
        if text == "Default Mouse Function":
            tool_mode = PrintToolManager.DEFAULT
        elif text == "Pan":
            tool_mode = PrintToolManager.PAN
        elif text == "Window Level / Window Width":
            tool_mode = PrintToolManager.WINDOW_LEVEL
        elif text == "Zoom":
            tool_mode = PrintToolManager.ZOOM
        else:
            tool_mode = PrintToolManager.DEFAULT
        
        self.preview_widget.set_tool_mode(tool_mode)

    def _populate_local_printers(self):
        self.local_printer_combo.clear()
        printers = []
        try:
            printers = [p.printerName() for p in QPrinterInfo.availablePrinters()]
        except Exception:
            pass
        if not printers:
            printers = OSPrinterHandler().list_printers()
        if not printers:
            printers = ["Default System Printer"]
        self.local_printer_combo.addItems(printers)

    def _on_printer_type_changed(self, text: str):
        is_local = text == "Local Printer"
        self.local_printer_combo.setEnabled(is_local)
        self.dicom_settings_btn.setEnabled(not is_local)
        self.printer_status.setText("Ready" if is_local else "DICOM settings required")

    def _open_dicom_printer_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("DICOM Printer Settings")
        dialog.setModal(True)
        form = QFormLayout(dialog)

        ip_edit = QLineEdit(str(self._dicom_print_settings.get("ip_address", "127.0.0.1")))
        port_spin = QSpinBox()
        port_spin.setRange(1, 65535)
        port_spin.setValue(int(self._dicom_print_settings.get("port", 104)))
        port_spin.setButtonSymbols(QAbstractSpinBox.PlusMinus)
        if hasattr(self, "_spinbox_style"):
            port_spin.setStyleSheet(self._spinbox_style)
        ae_edit = QLineEdit(str(self._dicom_print_settings.get("ae_title", "PRINTER")))
        local_ae_edit = QLineEdit(str(self._dicom_print_settings.get("local_ae_title", "AIPACS")))

        orientation_combo = QComboBox()
        orientation_combo.addItems(["PORTRAIT", "LANDSCAPE"])
        orientation_combo.setCurrentText(str(self._dicom_print_settings.get("film_orientation", "PORTRAIT")))

        medium_combo = QComboBox()
        medium_combo.addItems(["PAPER", "BLUE FILM", "CLEAR FILM"])
        medium_combo.setCurrentText(str(self._dicom_print_settings.get("medium_type", "PAPER")))

        destination_combo = QComboBox()
        destination_combo.addItems(["PROCESSOR", "MAGAZINE", "BIN_i"])
        destination_combo.setCurrentText(str(self._dicom_print_settings.get("film_destination", "PROCESSOR")))

        priority_combo = QComboBox()
        priority_combo.addItems(["LOW", "MED", "HIGH"])
        priority_combo.setCurrentText(str(self._dicom_print_settings.get("print_priority", "MED")))

        form.addRow("Printer IP", ip_edit)
        form.addRow("Port", port_spin)
        form.addRow("Called AE Title", ae_edit)
        form.addRow("Calling AE Title", local_ae_edit)
        form.addRow("Film Orientation", orientation_combo)
        form.addRow("Medium Type", medium_combo)
        form.addRow("Film Destination", destination_combo)
        form.addRow("Print Priority", priority_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() == QDialog.Accepted:
            self._dicom_print_settings.update(
                {
                    "ip_address": ip_edit.text().strip() or "127.0.0.1",
                    "port": int(port_spin.value()),
                    "ae_title": ae_edit.text().strip() or "PRINTER",
                    "local_ae_title": local_ae_edit.text().strip() or "AIPACS",
                    "film_orientation": orientation_combo.currentText(),
                    "medium_type": medium_combo.currentText(),
                    "film_destination": destination_combo.currentText(),
                    "print_priority": priority_combo.currentText(),
                }
            )
            self.printer_status.setText(
                f"DICOM: {self._dicom_print_settings['ip_address']}:{self._dicom_print_settings['port']} ({self._dicom_print_settings['ae_title']})"
            )

    def _open_header_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Header Settings")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        form = QFormLayout(dialog)

        # --- Helper to create a row with a text field + font-size spinbox ---
        def _make_row(label: str, text_key: str, font_key: str):
            from PySide6.QtWidgets import QHBoxLayout, QSpinBox, QLabel as QL
            text_edit = QLineEdit(str(self._header_settings.get(text_key, "")))
            text_edit.setMinimumWidth(280)
            spin = QSpinBox()
            spin.setRange(6, 120)
            spin.setValue(int(self._header_settings.get(font_key, 18)))
            spin.setSuffix(" pt")
            spin.setToolTip(f"Font size for {label}")
            row = QHBoxLayout()
            row.addWidget(text_edit, 1)
            row.addSpacing(8)
            row.addWidget(QL("Size:"))
            row.addWidget(spin)
            form.addRow(label, row)
            return text_edit, spin

        center_edit, center_spin = _make_row("Center / Institute", "center_name", "font_center_name")
        phone_edit, phone_spin = _make_row("Phone", "phone", "font_right_block")
        website_edit, website_spin = _make_row("Website", "website", "font_right_block")
        extra_edit, extra_spin = _make_row("Address / Extra", "extra", "font_right_block")

        # --- Patient fields (read-only text; font size adjustable) ---
        form.addRow("", QLineEdit())  # spacer
        form.itemAt(form.rowCount() - 1, QFormLayout.FieldRole).widget().setVisible(False)

        from PySide6.QtWidgets import QHBoxLayout as HL, QSpinBox as SB, QLabel as QL2
        pname_spin = QSpinBox()
        pname_spin.setRange(6, 120)
        pname_spin.setValue(int(self._header_settings.get("font_patient_name", 24)))
        pname_spin.setSuffix(" pt")
        pname_row = QHBoxLayout()
        pname_row.addWidget(QL2("Patient Name font size:"))
        pname_row.addWidget(pname_spin)
        pname_row.addStretch()
        form.addRow("", pname_row)

        pid_spin = QSpinBox()
        pid_spin.setRange(6, 120)
        pid_spin.setValue(int(self._header_settings.get("font_patient_id", 18)))
        pid_spin.setSuffix(" pt")
        pid_row = QHBoxLayout()
        pid_row.addWidget(QL2("Patient ID font size:"))
        pid_row.addWidget(pid_spin)
        pid_row.addStretch()
        form.addRow("", pid_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() == QDialog.Accepted:
            self._header_settings.update(
                {
                    "center_name": center_edit.text().strip(),
                    "phone": phone_edit.text().strip(),
                    "website": website_edit.text().strip(),
                    "extra": extra_edit.text().strip(),
                    "font_patient_name": pname_spin.value(),
                    "font_patient_id": pid_spin.value(),
                    "font_center_name": center_spin.value(),
                    "font_right_block": phone_spin.value(),
                }
            )
            if self._selected_paths:
                self._update_page_display()

    def _save_preview(self):
        """Save current preview page to filming folder."""
        if self._film_pixmap is None:
            QMessageBox.warning(self, "Save Preview", "Generate a preview first.")
            return
        
        if not self._active_patient:
            QMessageBox.warning(self, "Save Preview", "No patient selected.")
            return
        
        # Get patient folder from study_uid
        study_uid = self._active_patient.get("study_uid")
        if not study_uid:
            QMessageBox.warning(self, "Save Preview", "Patient study UID not found.")
            return
        
        # Construct patient folder path (assuming attachment/StudyInstanceUID structure)
        patient_folder = Path(BASE_PATH) / "attachment" / study_uid
        if not patient_folder.exists():
            patient_folder.mkdir(parents=True, exist_ok=True)
        
        # Prepare metadata
        layout = self._current_layout
        film_size = self.film_size_combo.currentData()
        metadata = {
            "patient_name": self._active_patient.get("patient_name", "Unknown"),
            "patient_id": self._active_patient.get("patient_id", "Unknown"),
            "study_uid": study_uid,
            "page_number": self._current_page + 1,
            "total_pages": self._total_pages,
            "layout": f"{layout.rows}x{layout.cols}" if layout else "unknown",
            "film_size": film_size.name if film_size else "unknown",
            "timestamp": datetime.now().isoformat(),
        }
        
        # Save the page
        thumb_path = FilmingDataManager.save_filming_page(
            patient_folder,
            self._current_page + 1,
            self._film_pixmap,
            metadata
        )
        
        if thumb_path:
            filming_folder_path = str((patient_folder / "Filming").resolve())
            db_manager.set_filming_folder_for_study(study_uid, filming_folder_path)
            self.status_label.setText(f"Preview saved to Filming folder")
            self._load_filming_pages()
        else:
            QMessageBox.warning(self, "Save Preview", "Failed to save preview.")
    
    def _load_filming_pages(self):
        """Load saved filming pages for current patient."""
        # Clear existing thumbnails
        while self.filming_container_layout.count():
            item = self.filming_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self._active_patient:
            return
        
        study_uid = self._active_patient.get("study_uid")
        if not study_uid:
            return
        
        folder_from_db = db_manager.get_filming_folder_for_study(study_uid)
        if folder_from_db:
            filming_folder = Path(folder_from_db)
            patient_folder = filming_folder.parent
        else:
            patient_folder = Path(BASE_PATH) / "attachment" / study_uid

        pages = FilmingDataManager.load_filming_pages(patient_folder)
        self._saved_filming_pages = pages
        
        if not pages:
            no_pages_lbl = QLabel("No saved filming pages")
            no_pages_lbl.setStyleSheet("color: #6b7280; padding: 10px;")
            no_pages_lbl.setAlignment(Qt.AlignCenter)
            self.filming_container_layout.addWidget(no_pages_lbl)
            return
        
        for idx, page_data in enumerate(pages):
            thumb_widget = self._create_filming_thumbnail(page_data, idx)
            self.filming_container_layout.addWidget(thumb_widget)
    
    def _create_filming_thumbnail(self, page_data: dict, index: int) -> QWidget:
        """Create a thumbnail widget for a saved filming page."""
        container = QFrame()
        container.setObjectName("filmingThumb")
        container.setStyleSheet(
            """
            QFrame#filmingThumb {
                background: #111827;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px;
            }
            QFrame#filmingThumb:hover {
                border-color: #60a5fa;
            }
            """
        )
        
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        
        # Thumbnail image
        thumb_label = QLabel()
        thumb_label.setFixedSize(96, 72)
        thumb_label.setStyleSheet("background:#0f172a; border:1px solid #4b5563; border-radius:4px;")
        
        thumb_path = page_data.get("thumbnail_path")
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(96, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb_label.setPixmap(scaled)
        
        # Info section
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        metadata = page_data.get("metadata", {})
        page_num = metadata.get("page_number", index + 1)
        layout_str = metadata.get("layout", "unknown")
        film_size_str = metadata.get("film_size", "unknown")
        
        title_lbl = QLabel(f"Page {page_num}")
        title_lbl.setStyleSheet("font-weight:600; color:#e5e7eb; font-size:13px;")
        
        details_lbl = QLabel(f"{layout_str} • {film_size_str}")
        details_lbl.setStyleSheet("color:#94a3b8; font-size:11px;")
        
        timestamp_str = metadata.get("timestamp", "")
        if timestamp_str:
            try:
                dt = datetime.fromisoformat(timestamp_str)
                time_lbl = QLabel(dt.strftime("%Y-%m-%d %H:%M"))
                time_lbl.setStyleSheet("color:#6b7280; font-size:10px;")
            except:
                time_lbl = QLabel("")
        else:
            time_lbl = QLabel("")
        
        info_layout.addWidget(title_lbl)
        info_layout.addWidget(details_lbl)
        info_layout.addWidget(time_lbl)
        info_layout.addStretch(1)
        
        # Actions
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(4)
        
        load_btn = QPushButton("Load")
        load_btn.setFixedSize(60, 24)
        load_btn.setStyleSheet(
            """
            QPushButton {
                background: #1e40af;
                color: #fff;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #2563eb;
            }
            """
        )
        load_btn.clicked.connect(lambda: self._load_saved_filming_page(page_data))
        
        delete_btn = QPushButton("Delete")
        delete_btn.setFixedSize(60, 24)
        delete_btn.setStyleSheet(
            """
            QPushButton {
                background: #991b1b;
                color: #fff;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #dc2626;
            }
            """
        )
        delete_btn.clicked.connect(lambda: self._delete_filming_page(page_data))
        
        actions_layout.addWidget(load_btn)
        actions_layout.addWidget(delete_btn)
        actions_layout.addStretch(1)
        
        layout.addWidget(thumb_label)
        layout.addLayout(info_layout, 1)
        layout.addLayout(actions_layout)
        
        return container
    
    def _load_saved_filming_page(self, page_data: dict):
        """Load a saved filming page image and set it as the current printable preview."""
        thumb_path = page_data.get("thumbnail_path")
        if not thumb_path or not Path(thumb_path).exists():
            QMessageBox.warning(self, "Load Filming Page", "Saved filming image was not found on disk.")
            return

        pixmap = QPixmap(str(thumb_path))
        if pixmap.isNull():
            QMessageBox.warning(self, "Load Filming Page", "Failed to open saved filming image.")
            return

        self._film_pixmap = pixmap

        dialog = QDialog(self)
        dialog.setWindowTitle("Saved Filming Page")
        dialog.resize(920, 720)
        layout = QVBoxLayout(dialog)

        preview = QLabel()
        preview.setAlignment(Qt.AlignCenter)
        preview.setStyleSheet("background:#0b1220; border:1px solid #334155; border-radius:8px;")
        scaled = pixmap.scaled(860, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        preview.setPixmap(scaled)
        layout.addWidget(preview, 1)

        close_btn = QPushButton("Close")
        if hasattr(self, "_button_style"):
            close_btn.setStyleSheet(self._button_style)
        close_btn.clicked.connect(dialog.accept)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self.status_label.setText("Loaded saved filming page as current preview")
        dialog.exec()
    
    def _delete_filming_page(self, page_data: dict):
        """Delete a saved filming page."""
        reply = QMessageBox.question(
            self,
            "Delete Filming Page",
            "Are you sure you want to delete this saved page?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            thumb_path = page_data.get("thumbnail_path")
            if thumb_path and FilmingDataManager.delete_filming_page(thumb_path):
                self.status_label.setText("Filming page deleted")
                self._load_filming_pages()
            else:
                QMessageBox.warning(self, "Delete", "Failed to delete filming page.")

    def _on_sync_mode_changed(self, checked: bool):
        if not self.preview_widget:
            return
        self.preview_widget.set_sync_mode(checked)

    def _load_printer_configs(self) -> List[PrinterConfig]:
        config = load_printing_config()
        printers = []
        for item in config.get("printers", []):
            try:
                printers.append(
                    PrinterConfig(
                        name=item.get("name", "Printer"),
                        printer_type=item.get("printer_type", "os"),
                        settings=item.get("settings", {}),
                    )
                )
            except Exception:
                continue
        if not printers:
            printers.append(PrinterConfig(name="Local Printer", printer_type="os"))
        return printers
