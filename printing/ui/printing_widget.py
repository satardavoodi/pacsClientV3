"""Printing module UI widget."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QSplitter,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QCheckBox,
    QButtonGroup,
    QToolButton,
    QDialog,
)

from printing.constants import DEFAULT_FILM_SIZES, DEFAULT_LAYOUTS
from printing.core import FilmLayout, FilmSize, PrintJob, PrinterConfig, SeriesSelection, ViewportState
from printing.core import load_printing_config, validate_print_job
from printing.data import get_series_for_study
from printing.ui.film_preview_widget import FilmPreviewWidget
from printing.printers.os_printer import OSPrinterHandler
from printing.printers.dicom_printer import (
    DicomImagePayload,
    DicomPrintHandler,
    DicomPrintJob,
    DicomPrinterSettings,
)


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

        self._viewport_state = ViewportState()
        self._printer_configs = self._load_printer_configs()

        self._build_ui()
        self._load_selected_patients()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()

        self._selected_patient_info = {}

        self.layout_group = QButtonGroup(self)
        self.layout_group.setExclusive(True)
        self._current_layout = None
        self.layout_button = QPushButton("Layout")
        self.layout_button.clicked.connect(self._open_layout_dialog)
        self.layout_label = QLabel("Layout: --")
        self._set_current_layout(self._get_available_layouts()[0] if self._get_available_layouts() else None)

        self.film_size_combo = QComboBox()
        self._populate_film_sizes()

        self.printer_combo = QComboBox()
        for printer in self._printer_configs:
            self.printer_combo.addItem(printer.name, printer)


        toolbar.addWidget(self.layout_button)
        toolbar.addWidget(self.layout_label)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Film size"))
        toolbar.addWidget(self.film_size_combo)
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Printer"))
        toolbar.addWidget(self.printer_combo)

        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(420)

        patient_group = QGroupBox("Selected Patients")
        patient_layout = QVBoxLayout(patient_group)
        self.patient_list = QListWidget()
        self.patient_list.setSelectionMode(QListWidget.SingleSelection)
        self.patient_list.itemSelectionChanged.connect(self._on_patient_selected)
        patient_layout.addWidget(self.patient_list)

        series_group = QGroupBox("Series")
        series_layout = QVBoxLayout(series_group)
        self.series_list = QListWidget()
        self.series_list.setSelectionMode(QListWidget.MultiSelection)
        self.series_list.itemSelectionChanged.connect(self._on_series_selection_changed)
        series_layout.addWidget(self.series_list)

        range_group = QGroupBox("Image range")
        range_layout = QHBoxLayout(range_group)
        self.range_start = QSpinBox()
        self.range_start.setRange(1, 100000)
        self.range_start.setValue(1)
        self.range_start.setMaximumWidth(80)
        self.range_end = QSpinBox()
        self.range_end.setRange(1, 100000)
        self.range_end.setValue(20)
        self.range_end.setMaximumWidth(80)
        range_layout.addWidget(QLabel("From"))
        range_layout.addWidget(self.range_start)
        range_layout.addSpacing(8)
        range_layout.addWidget(QLabel("To"))
        range_layout.addWidget(self.range_end)
        range_layout.addStretch(1)

        self.sync_checkbox = QCheckBox("Sync adjustments across images")
        self.sync_checkbox.setChecked(False)
        self.sync_checkbox.toggled.connect(self._on_sync_mode_changed)

        adjustments_group = QGroupBox("Adjustments")
        adjustments_layout = QFormLayout(adjustments_group)
        self.left_drag_mode = QComboBox()
        self.left_drag_mode.addItems([
            "Default",
            "Pan",
            "Window Level / Window Width",
            "Zoom",
        ])
        self.left_drag_mode.setCurrentIndex(1)
        self.left_drag_mode.currentTextChanged.connect(self._on_left_drag_mode_changed)
        adjustments_layout.addRow("Left Mouse Function", self.left_drag_mode)

        self.delete_tiles_btn = QPushButton("Delete Selected Images")
        self.delete_tiles_btn.clicked.connect(self._delete_selected_tiles)

        self.refresh_series_btn = QPushButton("Load Series")
        self.refresh_series_btn.clicked.connect(self._load_series)

        self.preview_btn = QPushButton("Generate Preview")
        self.preview_btn.clicked.connect(self._generate_preview)

        self.print_btn = QPushButton("Print")
        self.print_btn.clicked.connect(self._handle_print)

        left_layout.addWidget(patient_group)
        left_layout.addWidget(series_group)
        left_layout.addWidget(range_group)
        left_layout.addWidget(self.sync_checkbox)
        left_layout.addWidget(adjustments_group)
        left_layout.addWidget(self.refresh_series_btn)
        left_layout.addWidget(self.preview_btn)
        left_layout.addWidget(self.print_btn)
        left_layout.addWidget(self.delete_tiles_btn)
        left_layout.addStretch(1)

        self.preview_widget = FilmPreviewWidget()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_panel.setMaximumWidth(240)
        self.status_label = QLabel("Ready")
        right_layout.addWidget(self.status_label)
        right_layout.addStretch(1)

        splitter.addWidget(left_panel)
        splitter.addWidget(self.preview_widget)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 7)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([360, 900, 180])

        layout.addWidget(splitter)

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
        dialog.resize(360, 320)

        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(12)

        grid_container = QWidget()
        from PySide6.QtWidgets import QGridLayout
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

    def _load_series(self):
        self.series_list.clear()
        self._series_records = []
        if not self._selected_study_uid:
            print("[PRINTING] No study_uid selected")
            return
        print(f"[PRINTING] Loading series for study_uid: {self._selected_study_uid}")
        
        # Use enriched series loader for fault-tolerance
        try:
            from printing.data.dicom_enrichment import get_series_with_enrichment
            series = get_series_with_enrichment(self._selected_study_uid)
        except Exception as e:
            print(f"[PRINTING] ⚠️ Enrichment failed, falling back: {e}")
            series = get_series_for_study(self._selected_study_uid)
        
        print(f"[PRINTING] Found {len(series)} series")
        
        for item in series:
            series_num = item.get('series_number', 'unknown')
            series_desc = item.get('series_description', '')
            img_count = item.get('image_count', 0)
            
            label = f"{series_num} - {series_desc} ({img_count} images)"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.UserRole, item)
            self.series_list.addItem(list_item)
            self._series_records.append(item)
            print(f"[PRINTING]   series_pk={item.get('series_pk')}, series_number={series_num}, images={img_count}")
        
        if self.series_list.count() > 0:
            self.series_list.setCurrentRow(0)
        
        if series:
            self.status_label.setText(f"Loaded {len(series)} series")
        else:
            self.status_label.setText("No series found for selected study")

    def _on_series_selection_changed(self):
        self._selected_series = []
        for item in self.series_list.selectedItems():
            series = item.data(Qt.UserRole)
            if series:
                self._selected_series.append(series)
        self.status_label.setText(f"Selected {len(self._selected_series)} series")

    def _collect_image_paths(self) -> List[str]:
        from printing.data.series_repository import get_dicom_paths_for_series
        paths: List[str] = []
        if not self._selected_series:
            print("[PRINTING] No series selected")
            return []
        print(f"[PRINTING] Collecting paths for {len(self._selected_series)} selected series")
        for series in self._selected_series:
            series_pk = series.get("series_pk")
            
            # Handle series discovered from filesystem (no series_pk)
            if not series_pk:
                print(f"[PRINTING] Series has no pk, using direct path from discovery")
                series_path_str = series.get("series_path")
                if series_path_str:
                    from pathlib import Path
                    try:
                        from natsort import natsorted
                    except Exception:
                        natsorted = sorted
                    series_dir = Path(series_path_str)
                    if series_dir.exists():
                        files = natsorted([str(p) for p in series_dir.glob("*.dcm") if p.is_file()])
                        print(f"[PRINTING]   Got {len(files)} paths from direct scan")
                        paths.extend(files)
                continue
            
            print(f"[PRINTING] Processing series_pk={series_pk}")
            series_paths = get_dicom_paths_for_series(series_pk)
            series_paths = sorted(series_paths)
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

    def _generate_preview(self):
        self.status_label.setText("Generating preview...")
        self._selected_paths = self._collect_image_paths()
        if not self._selected_paths:
            QMessageBox.warning(self, "No images", "Select at least one series with images.")
            self.status_label.setText("No images for preview")
            return

        layout = self._current_layout
        film_size = self.film_size_combo.currentData()
        if not isinstance(layout, FilmLayout) or not isinstance(film_size, FilmSize):
            QMessageBox.warning(self, "Invalid layout", "Select a layout and film size.")
            return

        overlay_info = self._build_overlay_info()
        self.preview_widget.set_tiles(film_size, layout, self._selected_paths, overlay_info=overlay_info)
        self._film_pixmap = self.preview_widget.export_film_pixmap(dpi=150)
        self.status_label.setText(f"Preview generated ({len(self._selected_paths)} images)")

    def _handle_print(self):
        printer = self.printer_combo.currentData()
        if not isinstance(printer, PrinterConfig):
            QMessageBox.warning(self, "Printer", "Select a printer configuration.")
            return

        if self._film_pixmap is None:
            self._generate_preview()
            if self._film_pixmap is None:
                return

        high_res_pixmap = self._render_for_print(dpi=300)
        if high_res_pixmap is None:
            QMessageBox.warning(self, "Print", "Failed to render print image.")
            return

        job = self._build_print_job(printer)
        errors = validate_print_job(job)
        if errors:
            QMessageBox.warning(self, "Print validation", "\n".join(errors))
            return

        if printer.printer_type == "os":
            handler = OSPrinterHandler()
            success = handler.print_film(high_res_pixmap, printer.name)
            if not success:
                QMessageBox.warning(self, "Print", "OS print canceled or failed.")
            return

        if printer.printer_type == "dicom":
            try:
                settings = DicomPrinterSettings(
                    ip_address=printer.settings.get("ip_address", "127.0.0.1"),
                    port=int(printer.settings.get("port", 104)),
                    ae_title=printer.settings.get("ae_title", "PRINTER"),
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
                    from printing.data.series_repository import get_dicom_paths_for_series
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

        return {
            "institution": institution,
            "patient_name": patient_name,
            "patient_id": patient_id,
        }

    def _delete_selected_tiles(self):
        if not self.preview_widget:
            return
        self._selected_paths = self.preview_widget.delete_selected_tiles()

    def _on_left_drag_mode_changed(self, text: str):
        if not self.preview_widget:
            return
        from printing.ui.print_tools import PrintToolManager
        
        if text == "Default":
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
