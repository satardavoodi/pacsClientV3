"""
Advanced analysis panel (MPR, stitching, Eagle Eye).

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import os
import time
import traceback
from pathlib import Path
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget
from PacsClient.pacs.patient_tab.utils import ThumbnailManager, check_and_get_thumbnails, get_quickly_series_info
from PacsClient.utils.scroll_style import get_scroll_area_style


class _PWAdvancedMixin:
    """Advanced analysis panel (MPR, stitching, Eagle Eye)."""

    def launch_advanced_analysis_for_active_series(self) -> bool:
        """
        Launch Advanced MPR (3D Slicer) with the currently active series.

        Returns:
            bool: True if launch initiated, False otherwise.
        """
        try:
            selected_widget = self.selected_widget
            if selected_widget is None or not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                QMessageBox.warning(
                    self,
                    "No Image Available",
                    "No active DICOM series available.\n\nPlease load an image first."
                )
                return False

            # Prefer metadata directly from the active viewer
            metadata = getattr(selected_widget.image_viewer, 'metadata', None)

            # Fallback: resolve metadata from thumbnails using last_series_show
            if not metadata:
                series_data = None
                last_series_show = getattr(selected_widget, 'last_series_show', None)
                if last_series_show is not None:
                    if isinstance(last_series_show, int) and 0 <= last_series_show < len(self.lst_thumbnails_data):
                        series_data = self.lst_thumbnails_data[last_series_show]
                    else:
                        try:
                            last_series_int = int(last_series_show)
                        except (TypeError, ValueError):
                            last_series_int = None
                        if last_series_int is not None:
                            for data in self.lst_thumbnails_data:
                                series_num = data.get('metadata', {}).get('series', {}).get('series_number')
                                try:
                                    if series_num is not None and int(series_num) == last_series_int:
                                        series_data = data
                                        break
                                except (TypeError, ValueError):
                                    continue

                if series_data:
                    metadata = series_data.get('metadata', {})

            if not metadata:
                QMessageBox.warning(
                    self,
                    "No Series Available",
                    "No active DICOM series available.\n\nPlease select a series first."
                )
                return False

            series_metadata = metadata.get('series', {})
            dicom_directory = series_metadata.get('series_path')
            series_uid = series_metadata.get('series_uid')
            window_width = None
            window_level = None

            instances = metadata.get('instances', [])
            if instances:
                first_instance = instances[0]
                if not dicom_directory:
                    first_instance_path = first_instance.get('instance_path')
                    if first_instance_path:
                        dicom_directory = os.path.dirname(first_instance_path)

                window_width = first_instance.get('window_width')
                window_level = first_instance.get('window_center')

            if not dicom_directory:
                QMessageBox.warning(
                    self,
                    "Invalid Series",
                    "Could not find DICOM directory for the active series."
                )
                return False

            if not os.path.exists(dicom_directory):
                QMessageBox.warning(
                    self,
                    "Directory Not Found",
                    f"DICOM directory not found:\n{dicom_directory}"
                )
                return False

            return self._launch_advanced_analysis_with_params(
                dicom_dir=dicom_directory,
                series_uid=series_uid,
                window_width=window_width,
                window_level=window_level
            )

        except Exception as e:
            print(f"[PatientWidget] Error launching Advanced Analysis: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Error",
                f"Error launching Advanced Analysis:\n{str(e)}"
            )
            return False

    def _build_advanced_analysis_panel(self) -> QWidget:
        """
        Build Advanced Analysis panel with:
        - Top 50%: Thumbnails panel (identical to Series thumbnails)
        - Bottom 50%: Advanced Models buttons section
        """
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Create vertical splitter for 50-50 split
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # =====================================================================
        # TOP HALF: Thumbnails Panel – identical to Series thumbnails
        # =====================================================================
        top_widget = QWidget()
        top_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(20, 6, 6, 6)
        top_layout.setSpacing(6)

        # Header (same as Series Thumbnails header)
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        thumb_title_label = QLabel("Thumbnails")
        thumb_title_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)
        self.advanced_thumb_count_label = QLabel("0 series")
        self.advanced_thumb_count_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
        """)
        header_layout.addWidget(thumb_title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.advanced_thumb_count_label)
        top_layout.addWidget(header_widget)

        # Scroll area (same style as Series scroll area)
        thumb_scroll = QScrollArea()
        self.advanced_thumb_scroll = thumb_scroll
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        thumb_scroll.setStyleSheet(get_scroll_area_style())

        # Grid container (same as Series grid)
        thumb_container = QWidget()
        thumb_container.setStyleSheet("QWidget { background-color: transparent; }")
        thumb_container_layout = QGridLayout(thumb_container)
        thumb_container_layout.setContentsMargins(8, 6, 14, 6)
        thumb_container_layout.setHorizontalSpacing(6)
        thumb_container_layout.setVerticalSpacing(6)
        thumb_container_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        # Store for future reference
        self.advanced_analysis_thumb_grid = thumb_container_layout
        self.advanced_analysis_thumb_container = thumb_container

        thumb_scroll.setWidget(thumb_container)
        top_layout.addWidget(thumb_scroll)

        # =====================================================================
        # BOTTOM HALF: Advanced Models Buttons Section
        # =====================================================================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        # Advanced Models title
        models_title_label = QLabel("Advanced Models")
        models_title_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)
        bottom_layout.addWidget(models_title_label)

        # Models container (scrollable)
        models_scroll = QScrollArea()
        models_scroll.setWidgetResizable(True)
        models_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        models_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        models_scroll.setStyleSheet(get_scroll_area_style())

        # Models container
        models_container = QWidget()
        models_container.setStyleSheet("QWidget { background: transparent; }")
        models_container_layout = QVBoxLayout(models_container)
        models_container_layout.setContentsMargins(8, 6, 8, 6)
        models_container_layout.setSpacing(8)
        models_container_layout.setAlignment(Qt.AlignTop)

        # Advanced MPR Button
        self.btn_advanced_mpr = QPushButton("Advanced MPR and AI segmentation")
        self.btn_advanced_mpr.setCursor(Qt.PointingHandCursor)
        self.btn_advanced_mpr.setMinimumHeight(48)
        self.btn_advanced_mpr.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 10px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2563eb, stop:1 #1e40af);
                border: 1px solid #1e40af;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e3a8a);
                border: 1px solid #1e3a8a;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e40af, stop:1 #1e3a8a);
            }
        """)
        self.btn_advanced_mpr.clicked.connect(self._on_advanced_mpr_clicked)
        models_container_layout.addWidget(self.btn_advanced_mpr)

        # Stitching Module Button
        self.btn_stitching = QPushButton("Stitching")
        self.btn_stitching.setCursor(Qt.PointingHandCursor)
        self.btn_stitching.setMinimumHeight(48)
        self.btn_stitching.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 10px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2563eb, stop:1 #1e40af);
                border: 1px solid #1e40af;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e3a8a);
                border: 1px solid #1e3a8a;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e40af, stop:1 #1e3a8a);
            }
        """)
        self.btn_stitching.clicked.connect(self._on_stitching_clicked)
        models_container_layout.addWidget(self.btn_stitching)

        # Add stretch to push buttons to the top
        models_container_layout.addStretch()

        models_scroll.setWidget(models_container)
        bottom_layout.addWidget(models_scroll)

        # Add widgets to splitter
        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # Store the series list widget for backward compatibility
        self.advanced_analysis_series_list = None

        return panel

    def _refresh_advanced_analysis_series_list(self) -> None:
        """
        Populate thumbnails in the Advanced Analysis panel top section.
        Uses the same ThumbnailManager.create_thumbnail_widget() as the
        Series panel so thumbnails look identical.
        """
        if not hasattr(self, 'advanced_analysis_thumb_grid') or self.advanced_analysis_thumb_grid is None:
            return

        # Clear existing thumbnails
        while self.advanced_analysis_thumb_grid.count():
            item = self.advanced_analysis_thumb_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Get real thumbnail image files (same source as Series panel) ──
        thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid) if self.import_folder_path else None
        if thumbnails:
            thumbnails = sorted(thumbnails, key=lambda p: (int(p.stem) if p.stem.isdigit() else float('inf'), p.stem))

        # Collect series entries for metadata
        series_entries = self._collect_advanced_analysis_series_entries()

        if not series_entries and not thumbnails:
            empty_label = QLabel("No series available")
            empty_label.setStyleSheet("QLabel { color: #a0aec0; font-size: 12px; padding: 20px; }")
            empty_label.setAlignment(Qt.AlignCenter)
            self.advanced_analysis_thumb_grid.addWidget(empty_label, 0, 0)
            return

        # Build a quick lookup: series_number → entry
        entry_map = {str(e.get('series_number')): e for e in series_entries}

        # Build a separate ThumbnailManager for this panel so we don't
        # interfere with the main Series panel's ThumbnailManager.
        if not hasattr(self, '_adv_thumbnail_manager') or self._adv_thumbnail_manager is None:
            self._adv_thumbnail_manager = ThumbnailManager(method_change_series=self._on_advanced_thumb_series_clicked)

        adv_mgr = self._adv_thumbnail_manager
        # Reset so we can repopulate
        adv_mgr.buttons.clear()
        adv_mgr.lst_buttons_name.clear()
        adv_mgr.series_widgets.clear()

        thumb_index = 0

        # Prefer real thumbnail images; fall back to entries list
        if thumbnails:
            for thumbnail_file in thumbnails:
                series_number = thumbnail_file.stem
                entry = entry_map.get(str(series_number))

                # Build series_info dict matching what ThumbnailManager expects
                series_info = None
                if entry:
                    series_info = {
                        'series_number': entry.get('series_number'),
                        'series_description': entry.get('series_description', ''),
                        'series_uid': entry.get('series_uid'),
                        'series_path': entry.get('series_path'),
                    }
                else:
                    # Minimal info from folder
                    series_info = {'series_number': series_number}
                    if self.import_folder_path:
                        candidate = Path(self.import_folder_path) / str(series_number)
                        if candidate.exists():
                            from PacsClient.pacs.patient_tab.utils import get_quickly_series_info
                            series_info = get_quickly_series_info(candidate)

                pixmap = QPixmap(str(thumbnail_file))
                thumb_widget = adv_mgr.create_thumbnail_widget(
                    pixmap=pixmap,
                    label_text=str(series_number),
                    sop_instance_uid='adv_thumb',
                    thumbnail_index=series_number,
                    series_info=series_info,
                )

                # Add in the same 1×2-column span used by the Series panel
                self.advanced_analysis_thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 2)
                thumb_index += 1
        else:
            # No thumbnail images available – create placeholder cards per entry
            for entry in series_entries:
                series_number = entry.get('series_number', 'N/A')
                series_info = {
                    'series_number': series_number,
                    'series_description': entry.get('series_description', ''),
                    'series_uid': entry.get('series_uid'),
                    'series_path': entry.get('series_path'),
                }
                pixmap = QPixmap()  # empty / placeholder
                thumb_widget = adv_mgr.create_thumbnail_widget(
                    pixmap=pixmap,
                    label_text=str(series_number),
                    sop_instance_uid='adv_thumb',
                    thumbnail_index=series_number,
                    series_info=series_info,
                )
                self.advanced_analysis_thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 2)
                thumb_index += 1

        # Update count label
        if hasattr(self, 'advanced_thumb_count_label'):
            self.advanced_thumb_count_label.setText(f"{thumb_index} series")

        # Default selected series to the first entry
        if series_entries:
            self._selected_advanced_series = series_entries[0]

    def _on_advanced_thumb_series_clicked(self, series_number_or_index) -> None:
        """Callback used by the Advanced Analysis ThumbnailManager when a
        thumbnail is clicked.  We just store the selection – we do NOT
        switch the viewer like the main Series panel does."""
        series_key = str(series_number_or_index)
        # Find matching entry
        entries = self._collect_advanced_analysis_series_entries()
        for entry in entries:
            if str(entry.get('series_number')) == series_key:
                self._selected_advanced_series = entry
                print(f"[AdvancedAnalysis] Selected series {series_key}")
                return
        # Fallback – store minimal info
        self._selected_advanced_series = {'series_number': series_key}

    def _collect_advanced_analysis_series_entries(self) -> list:
        """Collect ALL patient series from every available source.

        Sources (merged in order — later sources fill gaps but never
        overwrite a non-None value):
            1. ``lst_thumbnails_data``   – series already loaded into VTK viewers
            2. ``_server_series_info``   – full list received from server
            3. **Disk scan**             – subdirectories of ``import_folder_path``
               whose names are numeric and contain at least one ``.dcm`` file
        """
        entries: dict = {}
        base_path = self.import_folder_path  # e.g. source/<study_uid>

        # -- helper: set a key only if missing or currently None ----------
        def _set(entry: dict, key: str, value):
            if value is not None and entry.get(key) is None:
                entry[key] = value

        # ── Source 1: lst_thumbnails_data ────────────────────────────────
        for data in getattr(self, 'lst_thumbnails_data', []) or []:
            metadata = data.get('metadata', {})
            series_meta = metadata.get('series', {})
            series_number = series_meta.get('series_number')
            if series_number is None:
                continue
            key = str(series_number)

            entry = entries.setdefault(key, {'series_number': key})
            _set(entry, 'series_description',
                 series_meta.get('series_description') or series_meta.get('series_name'))
            _set(entry, 'series_uid', series_meta.get('series_uid'))

            # Resolve series_path with multiple fallbacks
            sp = series_meta.get('series_path')
            if not sp:
                instances = metadata.get('instances', [])
                if instances:
                    inst_path = instances[0].get('instance_path')
                    if inst_path:
                        sp = os.path.dirname(inst_path)
            if not sp and base_path:
                candidate = os.path.join(str(base_path), str(series_number))
                if os.path.isdir(candidate):
                    sp = candidate
            _set(entry, 'series_path', sp)

            instances = metadata.get('instances', [])
            if instances:
                first_instance = instances[0]
                _set(entry, 'window_width', first_instance.get('window_width'))
                _set(entry, 'window_level', first_instance.get('window_center'))

        # ── Source 2: _server_series_info ────────────────────────────────
        for series_number, info in getattr(self, '_server_series_info', {}).items():
            key = str(series_number)
            entry = entries.setdefault(key, {'series_number': key})
            _set(entry, 'series_description',
                 info.get('series_description') or info.get('series_name'))
            _set(entry, 'series_uid', info.get('series_uid'))
            sp = info.get('series_path')
            if not sp and base_path:
                candidate = os.path.join(str(base_path), str(series_number))
                if os.path.isdir(candidate):
                    sp = candidate
            _set(entry, 'series_path', sp)

        # ── Source 3: disk scan of import_folder_path ───────────────────
        if base_path and os.path.isdir(str(base_path)):
            try:
                for child in os.listdir(str(base_path)):
                    child_path = os.path.join(str(base_path), child)
                    if not os.path.isdir(child_path):
                        continue
                    # Only consider directories whose name is numeric
                    # (series_number convention)
                    try:
                        int(child)
                    except ValueError:
                        continue
                    key = str(child)
                    if key in entries and entries[key].get('series_path'):
                        continue  # already have full info
                    # Verify the directory has at least one .dcm file
                    has_dcm = any(
                        f.lower().endswith('.dcm')
                        for f in os.listdir(child_path)
                        if os.path.isfile(os.path.join(child_path, f))
                    )
                    if not has_dcm:
                        continue
                    entry = entries.setdefault(key, {'series_number': key})
                    _set(entry, 'series_path', child_path)
                    _set(entry, 'series_description', f"Series {key}")
            except OSError:
                pass

        # ── Sort by series_number and return ────────────────────────────
        def _sort_key(item):
            try:
                return int(item.get('series_number', 0))
            except (TypeError, ValueError):
                return 0

        result = sorted(entries.values(), key=_sort_key)
        print(f"[PatientWidget] _collect_advanced_analysis_series_entries → {len(result)} series "
              f"(thumbnails={len(getattr(self, 'lst_thumbnails_data', []) or [])}, "
              f"server={len(getattr(self, '_server_series_info', {}))}, "
              f"disk_scan={'yes' if base_path and os.path.isdir(str(base_path)) else 'no'})")
        return result

    def _on_advanced_mpr_clicked(self) -> None:
        """
        Handle Advanced MPR button click.
        Shows loading overlay immediately, then defers the actual launch so
        the Qt event-loop has time to render the overlay before any blocking
        work (socket timeout inside send_remote_command, etc.) happens.
        """
        print("[PatientWidget] Advanced MPR button clicked")
        
        # ========== BUTTON SAFEGUARD: Prevent concurrent operations ==========
        if not self.button_safeguard.start_operation("Advanced MPR Launch"):
            QMessageBox.warning(
                self, "Operation In Progress",
                "Another operation is currently running. Please wait for it to complete."
            )
            return
        # ======================================================================

        # ── Resolve selected series ──────────────────────────────────────
        # Priority: use the *currently active viewer* (blue-bordered tab)
        # so the user always gets the series they are actually viewing,
        # not the first series in the list.
        selected_series = None
        try:
            sw = self.selected_widget
            if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                md = getattr(sw.image_viewer, 'metadata', None)
                if md:
                    sm = md.get('series', {})
                    selected_series = {
                        'series_number': sm.get('series_number'),
                        'series_uid':    sm.get('series_uid'),
                        'series_path':   sm.get('series_path'),
                        'window_width':  md.get('instances', [{}])[0].get('window_width'),
                        'window_level':  md.get('instances', [{}])[0].get('window_center'),
                    }
                    print(f"[PatientWidget] Active viewer series: {sm.get('series_number')}")
        except Exception as e:
            print(f"[PatientWidget] Error getting active viewer series: {e}")

        # Fallback: thumbnail panel selection (if no active viewer)
        if not selected_series:
            selected_series = getattr(self, '_selected_advanced_series', None)
            if selected_series:
                print(f"[PatientWidget] Fallback to thumbnail selection: series {selected_series.get('series_number')}")

        # Resolve dicom_directory with fallbacks (same logic as
        # launch_advanced_analysis_for_active_series)
        dicom_directory = (selected_series or {}).get('series_path')

        if not dicom_directory and selected_series:
            # Fallback: construct from import_folder_path + series_number
            sn = selected_series.get('series_number')
            if sn and self.import_folder_path:
                candidate = os.path.join(str(self.import_folder_path), str(sn))
                if os.path.isdir(candidate):
                    dicom_directory = candidate
                    selected_series['series_path'] = candidate

        if not dicom_directory:
            # Last resort: active viewer's metadata → instance_path
            try:
                sw = self.selected_widget
                if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                    md = getattr(sw.image_viewer, 'metadata', None)
                    if md:
                        instances = md.get('instances', [])
                        if instances:
                            inst_path = instances[0].get('instance_path')
                            if inst_path:
                                dicom_directory = os.path.dirname(inst_path)
            except Exception:
                pass

        if not dicom_directory:
            QMessageBox.warning(
                self, "No Series Selected",
                "Please select a series from the thumbnails panel.\n\n"
                "No active series available."
            )
            # End safeguard operation on early return
            self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")
            return
        if not os.path.exists(dicom_directory):
            QMessageBox.warning(
                self, "Directory Not Found",
                f"DICOM directory not found:\n{dicom_directory}"
            )
            # End safeguard operation on early return
            self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")
            return

        # ── Show the overlay NOW and force it to paint ───────────────────
        self._show_advanced_mpr_loading_ui()

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()          # flush paint queue once
        QApplication.processEvents()          # second pass for deferred paints

        # ── Defer the real launch 500 ms so the overlay is fully visible ─
        QTimer.singleShot(500, lambda: self._launch_advanced_mpr_async(
            dicom_dir=dicom_directory,
            series_uid=selected_series.get('series_uid'),
            window_width=selected_series.get('window_width'),
            window_level=selected_series.get('window_level'),
        ))

    def _show_advanced_mpr_loading_ui(self) -> None:
        """Show the loading overlay *over the DICOM viewer area* only."""
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        self._hide_advanced_mpr_loading_ui()  # remove stale overlay
        # Parent to the center viewer widget so the overlay covers only
        # the DICOM images area, not the thumbnails column.
        viewer_area = getattr(self, 'center_widget', None) or self
        self._advanced_mpr_loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=viewer_area,
            title="AI Pacs Image Analysis",
            status="AI Pacs is loading 3D Slicer",
            subtitle="Preparing Advanced MPR and AI segmentation engine",
        )

    def _hide_advanced_mpr_loading_ui(self, *, delay_ms: int = 0) -> None:
        """Remove the full-screen loading overlay with optional fade."""
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        overlay = getattr(self, '_advanced_mpr_loading_overlay', None)
        if overlay is not None:
            AiPacsLoadingOverlay.hide_overlay(
                overlay, fade_ms=500, delay_ms=delay_ms,
            )
            self._advanced_mpr_loading_overlay = None

    def _show_eagle_eye_loading_ui(self) -> None:
        """Show modal loading overlay for Eagle Eye that blocks all user interaction."""
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        self._hide_eagle_eye_loading_ui()  # Remove any existing overlay
        
        # Parent to the main window to create a full-screen modal overlay
        # This will block ALL interaction across the entire application
        main_window = self.window()
        
        self._eagle_eye_loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=main_window,
            title="EAGLE EYE AI Analysis",
            status="Loading AI Analysis Module",
            subtitle="Please wait while the AI module initializes"
        )
        
        # Make it application modal to block ALL user interaction
        self._eagle_eye_loading_overlay.setWindowModality(Qt.ApplicationModal)
        
        # Force immediate paint so loading appears before heavy operations
        QApplication.processEvents()
        QApplication.processEvents()  # Double process to ensure full render

    def _hide_eagle_eye_loading_ui(self, *, delay_ms: int = 0) -> None:
        """Remove the Eagle Eye loading overlay immediately."""
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        overlay = getattr(self, '_eagle_eye_loading_overlay', None)
        if overlay is not None:
            # No fade animation - hide immediately
            AiPacsLoadingOverlay.hide_overlay(
                overlay, fade_ms=0, delay_ms=0,
            )
            self._eagle_eye_loading_overlay = None

    def _force_hide_eagle_eye_loading(self) -> None:
        """Force remove Eagle Eye loading after timeout (safety mechanism)."""
        overlay = getattr(self, '_eagle_eye_loading_overlay', None)
        if overlay is not None:
            print("⚠️ [PatientWidget] Force removing Eagle Eye loading after 10s timeout")
            from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
            try:
                AiPacsLoadingOverlay.hide_overlay(overlay, fade_ms=0, delay_ms=0)
            except Exception as e:
                print(f"⚠️ Error force hiding overlay: {e}")
                # Force delete the overlay widget
                try:
                    overlay.close()
                    overlay.deleteLater()
                except Exception:
                    pass
            self._eagle_eye_loading_overlay = None

    def _open_eagle_eye_tab_with_loading(self) -> None:
        """Open Eagle Eye tab and hide loading overlay when visible."""
        try:
            # Open the Eagle Eye tab
            if self.method_add_new_tab:
                ai_widget = self.method_add_new_tab(open_ai_client_tab=True, study_uid=self.study_uid)
                
                # Tab is now visible - hide loading after a short delay for UI to render
                # Process events to ensure tab is painted
                QApplication.processEvents()
                QApplication.processEvents()
                
                # Hide loading overlay after short delay to ensure tab is visible
                QTimer.singleShot(500, lambda: self._hide_eagle_eye_loading_ui())
                print("[PatientWidget] Eagle Eye tab opened, scheduling loading removal")
        except Exception as e:
            print(f"⚠️ Error opening Eagle Eye tab: {e}")
            # Hide loading on error
            self._hide_eagle_eye_loading_ui()
            import traceback
            traceback.print_exc()

    def _launch_advanced_mpr_async(
        self,
        dicom_dir: str,
        series_uid: str | None = None,
        window_width: float | None = None,
        window_level: float | None = None,
    ) -> None:
        """Start the 3-D Slicer worker thread.  Called from a QTimer so the
        loading overlay is guaranteed to be painted first."""
        try:
            from modules.mpr.advanced_3d_slicer.slicer_launcher import get_slicer_launcher

            launcher = get_slicer_launcher(parent_widget=self)

            # Avoid stacking duplicate connections on the singleton.
            # PySide6's disconnect() can raise RuntimeError *or* set an
            # internal exception flag, so catch broadly with Exception.
            for sig, slot in (
                (launcher.slicer_started,  self._on_advanced_mpr_started),
                (launcher.slicer_finished, self._on_advanced_mpr_finished),
                (launcher.slicer_error,    self._on_advanced_mpr_error),
            ):
                try:
                    sig.disconnect(slot)
                except Exception:
                    pass
                sig.connect(slot)

            launcher.launch_with_dicom(
                dicom_dir=dicom_dir,
                layout='mpr',
                patient_id=getattr(self, 'patient_id', None),
                study_id=getattr(self, 'study_uid', None),
                window_width=window_width,
                window_level=window_level,
                series_uid=series_uid,
                viewport_x=self.mapToGlobal(QPoint(0, 0)).x(),
                viewport_y=self.mapToGlobal(QPoint(0, 0)).y(),
                viewport_width=self.width(),
                viewport_height=self.height(),
            )
        except Exception as e:
            print(f"[PatientWidget] Error launching Advanced MPR: {e}")
            import traceback
            traceback.print_exc()
            self._hide_advanced_mpr_loading_ui()
            
            # ========== BUTTON SAFEGUARD: End operation on exception ==========
            self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")
            # ==================================================================
            
            QMessageBox.critical(
                self, "Error",
                f"Failed to launch Advanced MPR:\n{str(e)}"
            )

    def _on_advanced_mpr_started(self) -> None:
        """3D Slicer process has started — hide the loader after a brief delay
        so the viewer has time to become visible before the overlay fades out."""
        print("[PatientWidget] Advanced MPR started – scheduling loader fade-out")
        # Update status text to indicate success, then fade after 1.5 s
        overlay = getattr(self, '_advanced_mpr_loading_overlay', None)
        if overlay is not None:
            overlay.set_status("3D Slicer launched successfully")
        self._hide_advanced_mpr_loading_ui(delay_ms=1500)
        
        # ========== BUTTON SAFEGUARD: End operation on success ==========
        self.button_safeguard.end_operation(success=True, operation_name="Advanced MPR Launch")

    def _on_advanced_mpr_finished(self, exit_code: int) -> None:
        """Handle Advanced MPR process completion (Slicer closed)."""
        print(f"[PatientWidget] Advanced MPR finished with exit code: {exit_code}")
        self._hide_advanced_mpr_loading_ui()

    def _on_advanced_mpr_error(self, error_msg: str) -> None:
        """Handle Advanced MPR launch error."""
        print(f"[PatientWidget] Advanced MPR error: {error_msg}")
        self._hide_advanced_mpr_loading_ui()
        
        # ========== BUTTON SAFEGUARD: End operation on error ==========
        self.button_safeguard.end_operation(success=False, operation_name="Advanced MPR Launch")

    def _on_stitching_clicked(self) -> None:
        """Handle Stitching button click — mirrors _on_advanced_mpr_clicked."""
        print("[PatientWidget] Stitching button clicked")
        
        # ========== BUTTON SAFEGUARD: Prevent concurrent operations ==========
        if not self.button_safeguard.start_operation("Stitching Launch"):
            QMessageBox.warning(
                self, "Operation In Progress",
                "Another operation is currently running. Please wait for it to complete."
            )
            return
        # ======================================================================

        # ── Resolve selected series (same logic as Advanced MPR) ─────
        selected_series = None
        try:
            sw = self.selected_widget
            if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                md = getattr(sw.image_viewer, 'metadata', None)
                if md:
                    sm = md.get('series', {})
                    selected_series = {
                        'series_number': sm.get('series_number'),
                        'series_uid':    sm.get('series_uid'),
                        'series_path':   sm.get('series_path'),
                        'window_width':  md.get('instances', [{}])[0].get('window_width'),
                        'window_level':  md.get('instances', [{}])[0].get('window_center'),
                    }
        except Exception as e:
            print(f"[PatientWidget] Error getting active viewer series: {e}")

        if not selected_series:
            selected_series = getattr(self, '_selected_advanced_series', None)

        dicom_directory = (selected_series or {}).get('series_path')

        if not dicom_directory and selected_series:
            sn = selected_series.get('series_number')
            if sn and self.import_folder_path:
                candidate = os.path.join(str(self.import_folder_path), str(sn))
                if os.path.isdir(candidate):
                    dicom_directory = candidate
                    selected_series['series_path'] = candidate

        if not dicom_directory:
            try:
                sw = self.selected_widget
                if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                    md = getattr(sw.image_viewer, 'metadata', None)
                    if md:
                        instances = md.get('instances', [])
                        if instances:
                            inst_path = instances[0].get('instance_path')
                            if inst_path:
                                dicom_directory = os.path.dirname(inst_path)
            except Exception:
                pass

        if not dicom_directory:
            QMessageBox.warning(
                self, "No Series Selected",
                "Please select a series from the thumbnails panel.\n\n"
                "No active series available."
            )
            # End safeguard operation on early return
            self.button_safeguard.end_operation(success=False, operation_name="Stitching Launch")
            return
        if not os.path.exists(dicom_directory):
            QMessageBox.warning(
                self, "Directory Not Found",
                f"DICOM directory not found:\n{dicom_directory}"
            )
            # End safeguard operation on early return
            self.button_safeguard.end_operation(success=False, operation_name="Stitching Launch")
            return

        # ── Show overlay & defer launch ──────────────────────────────
        self._show_stitching_loading_ui()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        QApplication.processEvents()

        QTimer.singleShot(500, lambda: self._launch_stitching_async(
            dicom_dir=dicom_directory,
            series_uid=(selected_series or {}).get('series_uid'),
            window_width=(selected_series or {}).get('window_width'),
            window_level=(selected_series or {}).get('window_level'),
        ))

    def _show_stitching_loading_ui(self) -> None:
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        self._hide_stitching_loading_ui()
        viewer_area = getattr(self, 'center_widget', None) or self
        self._stitching_loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=viewer_area,
            title="AI Pacs Image Analysis",
            status="Loading Stitching Module",
            subtitle="Preparing 2D radiograph stitching engine",
        )

    def _hide_stitching_loading_ui(self, *, delay_ms: int = 0) -> None:
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        overlay = getattr(self, '_stitching_loading_overlay', None)
        if overlay is not None:
            AiPacsLoadingOverlay.hide_overlay(
                overlay, fade_ms=500, delay_ms=delay_ms,
            )
            self._stitching_loading_overlay = None

    def _launch_stitching_async(
        self,
        dicom_dir: str,
        series_uid: str | None = None,
        window_width: float | None = None,
        window_level: float | None = None,
    ) -> None:
        """Open the Stitching window.  Called from QTimer so the
        loading overlay is guaranteed to be painted first."""
        try:
            from modules.stitching.stitching_widget import get_stitching_widget

            widget = get_stitching_widget(parent_widget=self)

            # Safe signal reconnect (avoid stacking on singleton)
            for sig, slot in (
                (widget.stitching_started,  self._on_stitching_started),
                (widget.stitching_finished, self._on_stitching_finished),
                (widget.stitching_error,    self._on_stitching_error),
            ):
                try:
                    sig.disconnect(slot)
                except Exception:
                    pass
                sig.connect(slot)

            # Collect all available series entries so the stitching widget
            # can show a multi-series selection list.
            available_series = self._collect_advanced_analysis_series_entries()

            widget.launch_with_series(
                available_series=available_series,
                dicom_dir=dicom_dir,
                series_uid=series_uid,
                window_width=window_width,
                window_level=window_level,
            )
        except Exception as e:
            print(f"[PatientWidget] Error launching Stitching: {e}")
            import traceback
            traceback.print_exc()
            self._hide_stitching_loading_ui()
            
            # ========== BUTTON SAFEGUARD: End operation on exception ==========
            self.button_safeguard.end_operation(success=False, operation_name="Stitching Launch")
            # ==================================================================
            
            QMessageBox.critical(
                self, "Error",
                f"Failed to launch Stitching module:\n{str(e)}"
            )

    def _on_stitching_started(self) -> None:
        print("[PatientWidget] Stitching module started")
        overlay = getattr(self, '_stitching_loading_overlay', None)
        if overlay is not None:
            overlay.set_status("Stitching module launched successfully")
        self._hide_stitching_loading_ui(delay_ms=1500)
        
        # ========== BUTTON SAFEGUARD: End operation on success ==========
        self.button_safeguard.end_operation(success=True, operation_name="Stitching Launch")

    def _on_stitching_finished(self, exit_code: int) -> None:
        print(f"[PatientWidget] Stitching finished with exit code: {exit_code}")
        self._hide_stitching_loading_ui()

    def _on_stitching_error(self, error_msg: str) -> None:
        print(f"[PatientWidget] Stitching error: {error_msg}")
        self._hide_stitching_loading_ui()
        
        # ========== BUTTON SAFEGUARD: End operation on error ==========
        self.button_safeguard.end_operation(success=False, operation_name="Stitching Launch")

    def _launch_advanced_analysis_with_params(
        self,
        dicom_dir: str,
        series_uid: str | None = None,
        window_width: float | None = None,
        window_level: float | None = None
    ) -> bool:
        from modules.mpr.advanced_3d_slicer.slicer_launcher import get_slicer_launcher

        launcher = get_slicer_launcher(parent_widget=self)
        return bool(launcher.launch_with_dicom(
            dicom_dir=dicom_dir,
            layout='mpr',
            patient_id=getattr(self, 'patient_id', None),
            study_id=getattr(self, 'study_uid', None),
            window_width=window_width,
            window_level=window_level,
            series_uid=series_uid
        ))

