"""UI setup: header, toolbar, download queue, details panel"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel, QSplitter, QFrame, QHeaderView, QAbstractItemView, QGroupBox, QScrollArea, QProgressBar, QComboBox, QTextEdit
import qtawesome as qta

logger = logging.getLogger(__name__)

class _DMUISetupMixin:
    """UI setup: header, toolbar, download queue, details panel"""

    def _setup_ui(self) -> None:
        """Setup user interface matching v1.0.6 layout"""
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            
            # Header section (minimal, just title and status)
            self._setup_header(main_layout)
            
            # Main content area - horizontal layout with toolbar on left
            content_widget = QWidget()
            content_layout = QHBoxLayout(content_widget)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            
            # Left toolbar
            self._setup_toolbar(content_layout)
            
            # Splitter for download queue and details panel
            splitter = QSplitter(Qt.Horizontal)
            content_layout.addWidget(splitter)
            
            # Download queue
            self._setup_download_queue(splitter)
            
            # Right panel - Details and controls
            self._setup_details_panel(splitter)
            
            # Set splitter proportions (slightly wider details panel for controls)
            splitter.setSizes([560, 340])
            
            main_layout.addWidget(content_widget)
            
            # Apply v1.0.6 styling
            self._apply_v106_styling()
            
        except Exception as e:
            logger.error(f"Error in _setup_ui: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def _setup_header(self, layout):
        """Setup minimal header section matching v1.0.6"""
        header_widget = QWidget()
        header_widget.setFixedHeight(45)
        header_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e293b,
                    stop:1 #0f172a
                );
                border-bottom: 2px solid rgba(6, 182, 212, 0.2);
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(12)
        
        # Title with icon
        title_icon = QLabel()
        title_icon.setPixmap(qta.icon('fa5s.download', color='#06b6d4').pixmap(20, 20))
        
        title_text = QLabel("Download Manager")
        title_text.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 700;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                color: #ffffff;
            }
        """)
        
        # Status summary
        self.status_summary = QLabel("Ready")
        self.status_summary.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: 500;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                color: #94a3b8;
                padding: 6px 12px;
                background: rgba(6, 182, 212, 0.1);
                border: 1px solid rgba(6, 182, 212, 0.2);
                border-radius: 6px;
            }
        """)
        
        header_layout.addWidget(title_icon)
        header_layout.addWidget(title_text)
        header_layout.addStretch()
        header_layout.addWidget(self.status_summary)
        
        layout.addWidget(header_widget)

    def _setup_toolbar(self, layout):
        """Setup modern left-side vertical toolbar matching v1.0.6"""
        try:
            toolbar_widget = QWidget()
            toolbar_widget.setFixedWidth(70)
            toolbar_widget.setStyleSheet("""
                QWidget {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 #1e293b,
                        stop:1 #0f172a
                    );
                    border-right: 2px solid rgba(6, 182, 212, 0.2);
                }
            """)
            
            toolbar_layout = QVBoxLayout(toolbar_widget)
            toolbar_layout.setContentsMargins(8, 12, 8, 12)
            toolbar_layout.setSpacing(10)
            
            # Modern button style template
            button_style = """
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 0.2),
                    stop:1 rgba({r}, {g}, {b}, 0.1)
                );
                border: 2px solid rgba({r}, {g}, {b}, 0.3);
                border-radius: 8px;
                padding: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 0.3),
                    stop:1 rgba({r}, {g}, {b}, 0.15)
                );
                border: 2px solid rgba({r}, {g}, {b}, 0.5);
            }}
            QPushButton:pressed {{
                background: rgba({r}, {g}, {b}, 0.25);
            }}
            """
            
            # Start all button (Cyan)
            self.start_all_btn = QPushButton()
            self.start_all_btn.setIcon(qta.icon('fa5s.play', color='#06b6d4'))
            self.start_all_btn.setToolTip("Start All Downloads")
            self.start_all_btn.clicked.connect(self._on_play)
            self.start_all_btn.setFixedSize(54, 54)
            self.start_all_btn.setStyleSheet(button_style.format(r=6, g=182, b=212))
            toolbar_layout.addWidget(self.start_all_btn)
            
            # Pause all button (Orange)
            self.pause_all_btn = QPushButton()
            self.pause_all_btn.setIcon(qta.icon('fa5s.pause', color='#f97316'))
            self.pause_all_btn.setToolTip("Pause All Downloads")
            self.pause_all_btn.clicked.connect(self._on_pause)
            self.pause_all_btn.setFixedSize(54, 54)
            self.pause_all_btn.setStyleSheet(button_style.format(r=249, g=115, b=22))
            toolbar_layout.addWidget(self.pause_all_btn)
            
            # Separator
            toolbar_layout.addWidget(self._create_toolbar_separator())
            
            # Clear button (Rose)
            self.clear_all_btn = QPushButton()
            self.clear_all_btn.setIcon(qta.icon('fa5s.trash', color='#f43f5e'))
            self.clear_all_btn.setToolTip("Clear Completed Downloads")
            self.clear_all_btn.clicked.connect(self._on_clear)
            self.clear_all_btn.setFixedSize(54, 54)
            self.clear_all_btn.setStyleSheet(button_style.format(r=244, g=63, b=94))
            toolbar_layout.addWidget(self.clear_all_btn)
            
            # Refresh button (Emerald)
            self.refresh_btn = QPushButton()
            self.refresh_btn.setIcon(qta.icon('fa5s.sync', color='#10b981'))
            self.refresh_btn.setToolTip("Refresh Download Status")
            self.refresh_btn.clicked.connect(self._on_refresh)
            self.refresh_btn.setFixedSize(54, 54)
            self.refresh_btn.setStyleSheet(button_style.format(r=16, g=185, b=129))
            toolbar_layout.addWidget(self.refresh_btn)
            
            toolbar_layout.addStretch()
            layout.addWidget(toolbar_widget)
            
        except Exception as e:
            logger.error(f"Error in _setup_toolbar: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def _create_toolbar_separator(self):
        """Create a visual separator for toolbar"""
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFixedHeight(2)
        separator.setStyleSheet("""
            QFrame {
                background: rgba(6, 182, 212, 0.15);
                border: none;
                margin: 4px 8px;
            }
        """)
        return separator

    def _setup_download_queue(self, splitter):
        """Setup the download queue table"""
        queue_widget = QWidget()
        queue_layout = QVBoxLayout(queue_widget)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        
        # Queue header
        queue_header = QLabel("Download Queue")
        queue_header.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: bold;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 4px 0px;
            }
        """)
        queue_layout.addWidget(queue_header)
        
        # Download table
        self.download_table = QTableWidget()
        self.download_table.setColumnCount(7)
        self.download_table.setHorizontalHeaderLabels([
            "Status",
            "Patient",
            "Modality",
            "Progress",
            "Speed",
            "Priority",
            "Actions"
        ])
        
        # Table settings
        self.download_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.download_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.setAlternatingRowColors(False)  # We'll handle coloring via priority groups
        
        # Column sizing
        header = self.download_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Status
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Patient
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Modality
        header.setSectionResizeMode(3, QHeaderView.Fixed)  # Progress
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Speed
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Priority
        header.setSectionResizeMode(6, QHeaderView.Fixed)  # Actions
        
        self.download_table.setColumnWidth(0, 140)  # Status column
        self.download_table.setColumnWidth(3, 240)  # Progress column
        self.download_table.setColumnWidth(6, 180)  # Actions column
        
        # Connect selection changed
        self.download_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.download_table.cellClicked.connect(self._on_table_cell_clicked)
        self.download_table.itemClicked.connect(self._on_table_item_clicked)
        
        queue_layout.addWidget(self.download_table)
        splitter.addWidget(queue_widget)

    def _setup_details_panel(self, splitter):
        """Setup the details and controls panel matching v1.0.6"""
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        
        # Details header
        details_header = QLabel("Download Details")
        details_header.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: bold;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 4px 0px;
            }
        """)
        details_layout.addWidget(details_header)
        
        # Scroll area for details
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 12px;
                margin: 12px 0px 12px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 40px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 12px;
                width: 12px;
                background: transparent;
                border: none;
                subcontrol-origin: margin;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
            }
        """)
        
        details_content = QWidget()
        details_content_layout = QVBoxLayout(details_content)
        details_content_layout.setSpacing(12)
        
        # === Patient & Study Information Group ===
        patient_info_group = QGroupBox("Patient & Study Information")
        patient_info_layout = QVBoxLayout(patient_info_group)
        
        # Patient Name
        self.patient_name_label = QLabel("Name: -")
        self.patient_name_label.setWordWrap(True)
        self.patient_name_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 0px;
            }
        """)
        
        # Patient ID
        self.patient_id_label = QLabel("ID: -")
        self.patient_id_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Patient Identifier (Reception)
        self.patient_identifier_label = QLabel("Identifier: -")
        self.patient_identifier_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Separator
        separator1 = QLabel("")
        separator1.setStyleSheet("border-bottom: 1px solid #374151; margin: 4px 0;")
        
        # Study UID
        self.url_label = QLabel("Study UID: -")
        self.url_label.setWordWrap(True)
        self.url_label.setStyleSheet("""
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                padding: 2px 0px;
            }
        """)
        
        # Study Date
        self.study_date_label = QLabel("Study Date: -")
        self.study_date_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Modality
        self.modality_label = QLabel("Modality: -")
        self.modality_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Description
        self.study_desc_label = QLabel("Description: -")
        self.study_desc_label.setWordWrap(True)
        self.study_desc_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Requesting Physician
        self.requesting_physician_label = QLabel("Requesting Physician: -")
        self.requesting_physician_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Reception Status
        self.reception_status_label = QLabel("Reception Status: -")
        self.reception_status_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Additional patient information fields
        self.age_label = QLabel("Age: -")
        self.age_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        self.gender_label = QLabel("Gender: -")
        self.gender_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        self.birth_date_label = QLabel("Birth Date: -")
        self.birth_date_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        self.tel_label = QLabel("Time: -")  # Changed from Phone to Time
        self.tel_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Body part label
        self.body_part_label = QLabel("Body Part: -")
        self.body_part_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Series/Images count
        separator2 = QLabel("")
        separator2.setStyleSheet("border-bottom: 1px solid #374151; margin: 4px 0;")
        
        self.size_label = QLabel("Series: - | Images: -")
        self.size_label.setStyleSheet("""
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                font-style: italic;
                padding: 2px 0px;
            }
        """)
        
        patient_info_layout.addWidget(self.patient_name_label)
        patient_info_layout.addWidget(self.patient_id_label)
        patient_info_layout.addWidget(self.patient_identifier_label)
        patient_info_layout.addWidget(separator1)
        patient_info_layout.addWidget(self.url_label)
        patient_info_layout.addWidget(self.study_date_label)
        patient_info_layout.addWidget(self.modality_label)
        patient_info_layout.addWidget(self.study_desc_label)
        patient_info_layout.addWidget(self.requesting_physician_label)
        patient_info_layout.addWidget(self.reception_status_label)
        
        # Add additional patient information fields
        patient_info_layout.addWidget(self.age_label)
        patient_info_layout.addWidget(self.gender_label)
        patient_info_layout.addWidget(self.birth_date_label)
        patient_info_layout.addWidget(self.tel_label)
        patient_info_layout.addWidget(self.body_part_label)
        
        patient_info_layout.addWidget(separator2)
        patient_info_layout.addWidget(self.size_label)
        
        # === Download Progress Group ===
        progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(8)
        
        # Overall Progress header
        overall_header = QLabel("📊 Overall Progress")
        overall_header.setStyleSheet("""
            QLabel {
                color: #06b6d4;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 0px;
            }
        """)
        progress_layout.addWidget(overall_header)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setFormat("0.0% (0/0 images)")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                background: #1a202c;
                height: 24px;
                text-align: center;
                font-size: 12px;
                font-weight: 600;
                padding: 0px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #06b6d4, stop:1 #0891b2);
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        # Progress details
        progress_details_layout = QHBoxLayout()
        progress_details_layout.setSpacing(16)
        
        self.progress_label = QLabel("0% (0/0 images)")
        self.progress_label.setStyleSheet("""
            QLabel {
                color: #06b6d4;
                font-weight: bold;
                font-size: 13px;
            }
        """)
        
        self.speed_label = QLabel("Speed: 0 KB/s")
        self.speed_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
            }
        """)
        
        self.eta_label = QLabel("ETA: Unknown")
        self.eta_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
            }
        """)
        
        progress_details_layout.addWidget(self.progress_label)
        progress_details_layout.addStretch()
        progress_details_layout.addWidget(self.speed_label)
        progress_details_layout.addWidget(self.eta_label)
        
        progress_layout.addLayout(progress_details_layout)
        
        # Separator
        separator = QLabel("")
        separator.setStyleSheet("border-bottom: 1px solid #374151; margin: 8px 0;")
        progress_layout.addWidget(separator)
        
        # Series Breakdown header
        series_header = QLabel("📁 Series Breakdown")
        series_header.setStyleSheet("""
            QLabel {
                color: #10b981;
                font-weight: bold;
                font-size: 12px;
                padding: 4px 0px;
            }
        """)
        progress_layout.addWidget(series_header)
        
        # Series list container
        self.series_scroll = QScrollArea()
        self.series_scroll.setWidgetResizable(True)
        self.series_scroll.setMinimumHeight(300)
        self.series_scroll.setMaximumHeight(500)
        self.series_scroll.setStyleSheet("""
            QScrollArea {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
            }
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 12px;
                margin: 12px 0px 12px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 40px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 12px;
                width: 12px;
                background: transparent;
                border: none;
                subcontrol-origin: margin;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
            }
        """)
        
        self.series_container = QWidget()
        self.series_layout = QVBoxLayout(self.series_container)
        self.series_layout.setSpacing(8)
        self.series_layout.setContentsMargins(8, 8, 8, 8)
        
        series_empty_label = QLabel("No series information available")
        series_empty_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 8px;")
        self.series_layout.addWidget(series_empty_label)
        self.series_layout.addStretch()
        
        self.series_scroll.setWidget(self.series_container)
        progress_layout.addWidget(self.series_scroll)
        
        # === Controls Group ===
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(qta.icon('fa5s.play', color='white'))
        self.start_btn.clicked.connect(self._on_start_selected)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(qta.icon('fa5s.pause', color='white'))
        self.pause_btn.clicked.connect(self._on_pause_selected)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(qta.icon('fa5s.stop', color='white'))
        self.cancel_btn.clicked.connect(self._on_cancel_selected)
        
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setIcon(qta.icon('fa5s.redo', color='white'))
        self.retry_btn.clicked.connect(self._on_retry_selected)
        
        self.reset_btn = QPushButton("Reset All")
        self.reset_btn.setIcon(qta.icon('fa5s.sync', color='white'))
        self.reset_btn.clicked.connect(self._on_reset_all)
        
        for btn in [self.start_btn, self.pause_btn, self.cancel_btn, self.retry_btn, self.reset_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background: #374151;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 12px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #4b5563;
                }
                QPushButton:pressed {
                    background: #1f2937;
                }
                QPushButton:disabled {
                    background: #1f2937;
                    color: #64748b;
                }
            """)
            action_layout.addWidget(btn)
        
        controls_layout.addLayout(action_layout)
        
        # Priority selector
        priority_layout = QHBoxLayout()
        priority_label = QLabel("Priority:")
        priority_label.setStyleSheet("color: #e2e8f0; font-size: 12px;")
        priority_layout.addWidget(priority_label)
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Low", "Normal", "High", "Critical"])
        self.priority_combo.setCurrentText("Normal")
        self.priority_combo.currentTextChanged.connect(self._on_priority_changed)
        self.priority_combo.setMinimumWidth(140)
        self.priority_combo.setStyleSheet("""
            QComboBox {
                background: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 6px 10px;
                color: #e2e8f0;
                font-size: 12px;
                min-height: 28px;
            }
        """)
        
        priority_layout.addWidget(self.priority_combo)
        priority_layout.addStretch()
        
        controls_layout.addLayout(priority_layout)
        
        # === Attachments Group ===
        attachments_group = QGroupBox("Attachments")
        attachments_layout = QVBoxLayout(attachments_group)

        self.attachments_list = QTextEdit()
        self.attachments_list.setMaximumHeight(100)
        self.attachments_list.setReadOnly(True)
        self.attachments_list.setPlaceholderText("No attachments available")
        self.attachments_list.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                padding: 8px;
            }
        """)

        attachments_layout.addWidget(self.attachments_list)

        # === Log Group ===
        log_group = QGroupBox("Download Logs")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Download logs will appear here...")
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #e2e8f0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10px;
                padding: 8px;
            }
        """)

        log_layout.addWidget(self.log_text)

        # Add all groups to details layout (reordered)
        details_content_layout.addWidget(patient_info_group)
        details_content_layout.addWidget(controls_group)
        details_content_layout.addWidget(progress_group)
        details_content_layout.addWidget(attachments_group)
        details_content_layout.addWidget(log_group)
        details_content_layout.addStretch()
        
        scroll_area.setWidget(details_content)
        details_layout.addWidget(scroll_area)
        
        splitter.addWidget(details_widget)
