"""
Reception Data Tab Module

This module provides a beautiful UI tab for displaying patient reception data.
It fetches data from the API and displays it in an organized, user-friendly format.

Refactored to use modular widgets and centralized styles.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QGroupBox, QGridLayout, QScrollArea, QFrame,
    QMessageBox, QDialog, QFileDialog, QProgressDialog, QGraphicsView, 
    QGraphicsScene, QGraphicsPixmapItem, QTextEdit, QSplitter, QTabWidget
)
from PySide6.QtCore import Qt, QUrl, QByteArray, QBuffer, QIODevice, Signal, QFile, QRectF
from PySide6.QtGui import QFont, QDesktopServices, QCursor, QPixmap, QMouseEvent, QWheelEvent, QPainter
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from .reception_data_service import ReceptionDataService
from .reception_data_styles import (
    COLORS, FONTS, FONT_SIZES, BORDER_RADIUS, SPACING,
    get_main_background_style, get_group_box_style, get_button_style,
    get_label_style, get_progress_dialog_style, get_image_viewer_style,
    get_gradient_button_style, is_rtl_content
)
from .widgets.report_editor_dialog import ReportEditorDialog
from .widgets.patient_info_card import PatientInfoCard, ReceptionInfoCard
from .widgets.attachment_viewer import AttachmentGrid, AttachmentThumbnail
from PacsClient.utils.socket_token_manager import get_socket_token_manager
import qtawesome as qta
import os
import json


class ZoomableImageView(QGraphicsView):
    """Image viewer with zoom and pan capabilities."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        
        self._zoom = 1.0
        self._min_zoom = 0.1
        self._max_zoom = 10.0
        
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        self.pixmap_item = None
    
    def set_image(self, pixmap: QPixmap):
        """Set the image to display."""
        self.scene.clear()
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle zoom with mouse wheel."""
        if event.angleDelta().y() > 0:
            factor = 1.25
            self._zoom *= factor
        else:
            factor = 0.8
            self._zoom *= factor
        
        # Limit zoom
        if self._zoom < self._min_zoom:
            factor = self._min_zoom / (self._zoom / factor)
            self._zoom = self._min_zoom
        elif self._zoom > self._max_zoom:
            factor = self._max_zoom / (self._zoom / factor)
            self._zoom = self._max_zoom
        
        self.scale(factor, factor)
    
    def reset_zoom(self):
        """Reset zoom to fit view."""
        self.resetTransform()
        if self.pixmap_item:
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0


class ClickableAttachmentWidget(QWidget):
    """Clickable widget for attachments."""
    clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"""
            ClickableAttachmentWidget {{
                background-color: {COLORS['bg_lighter']};
                border: 2px solid {COLORS['border_medium']};
                border-radius: {BORDER_RADIUS['sm']}px;
            }}
            ClickableAttachmentWidget:hover {{
                background-color: {COLORS['bg_card']};
                border-color: {COLORS['info']};
            }}
        """)
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ReceptionDataTab(QWidget):
    """
    Reception Data Tab for displaying patient reception information.
    
    Features:
    - Search by Reception ID
    - Display patient information
    - Display modality information
    - Display physician information
    - Display appointment information
    - Beautiful and organized UI layout
    """
    
    def __init__(self, patient_id=None):
        """Initialize the Reception Data Tab."""
        print("=" * 80)

        print("=" * 80)
        super().__init__()

        # Initialize service

        self.service = ReceptionDataService()

        self.service.data_received.connect(self._on_data_received)
        self.service.error_occurred.connect(self._on_error)

        # Current data
        self.current_data = None
        self.patient_id = patient_id
        self.data_fetched = False  # Track if data has been fetched
        
        # Setup UI

        self._setup_ui()

        print("=" * 80)
    
    def _setup_ui(self):
        """Set up the user interface."""

        # Create main vertical layout
        self.vertical_layout = QVBoxLayout(self)
        self.vertical_layout.setContentsMargins(0, 0, 0, 0)
        self.vertical_layout.setSpacing(0)

        # Create main container widget

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Add search section

        search_section = self._create_search_section()

        main_layout.addWidget(search_section)

        # Create scroll area for data display

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        # Create content widget for scroll area

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Add placeholder

        self._show_placeholder()

        scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(scroll_area)

        # Add container to vertical layout
        self.vertical_layout.addWidget(main_container)

        # Set main background style
        self.setStyleSheet(get_main_background_style())


    def _create_search_section(self) -> QWidget:
        """
        Create the search section.
        
        Returns:
            QWidget containing search UI
        """
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title label
        title_label = QLabel("Patient Reception Information")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: white;")
        
        # Add widgets to layout
        search_layout.addWidget(title_label)
        search_layout.addStretch()
        
        return search_widget
    
    def _show_placeholder(self):
        """Show placeholder message when no data is loaded."""

        # Clear existing content
        self._clear_content()
        
        placeholder = QLabel("Click on Reception Data to load patient information")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 12px;
                padding: 20px;
            }
        """)
        self.content_layout.addWidget(placeholder)

    def _show_loading(self):
        """Show loading indicator."""

        self._clear_content()
        
        loading = QLabel("Loading patient data...")
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 16px;
                padding: 40px;
            }
        """)
        self.content_layout.addWidget(loading)

    def _clear_content(self):
        """Clear all content from the content layout."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def fetch_patient_data(self, patient_id=None):
        """Fetch patient data by ID."""
        # Use provided patient_id or stored one
        pid = patient_id or self.patient_id

        if not pid:

            return
        
        # Only fetch once
        if self.data_fetched:

            return

        # Show loading
        self._show_loading()
        
        # Mark as being fetched
        self.data_fetched = True
        
        # Fetch data

        self.service.fetch_patient_data(pid)
    
    def on_tab_activated(self):
        """Called when this tab becomes active."""

        # Fetch data if not already fetched
        if not self.data_fetched and self.patient_id:

            self.fetch_patient_data()
    
    def _on_data_received(self, data: dict):
        """
        Handle received data from API.
        
        Args:
            data: The received data dictionary
        """

        # Check if request was successful
        if not data.get("success"):
            error_msg = data.get("message", "Unknown error occurred")

            self._on_error(error_msg)
            return
        
        # Check if data exists - can be array or object
        patient_data = data.get("data")

        if not patient_data:
            self._on_error("No patient data found for this Patient ID")
            return
        
        # Handle both array and object response formats
        if isinstance(patient_data, list):
            if not patient_data:
                self._on_error("No patient data found for this Patient ID")
                return
            self.current_data = patient_data[0]
        else:
            # Direct object response
            self.current_data = patient_data

        # Display data

        self._display_data()
    
    def _on_error(self, error_message: str):
        """
        Handle error occurrence.
        
        Args:
            error_message: The error message
        """

        # Clear content and show error
        self._clear_content()
        
        error_label = QLabel(f"Error: {error_message}")
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setStyleSheet("""
            QLabel {
                color: #f44336;
                font-size: 14px;
                padding: 40px;
            }
        """)
        self.content_layout.addWidget(error_label)

        # Also show message box
        QMessageBox.critical(self, "Error", error_message)
    
    def _display_data(self):
        """Display the patient data in organized sections."""

        if not self.current_data:

            return

        # Clear existing content
        self._clear_content()
        
        # Create sections in priority order

        self._create_services_section()

        self._create_report_section()

        self._create_attachments_section()

        self._create_patient_info_section()

        self._create_appointment_info_section()

        self._create_physician_info_section()

        self._create_reception_info_section()

        self._create_modality_info_section()
        
        # Add stretch at the end
        self.content_layout.addStretch()

    def _create_info_group(self, title: str, data: dict, color_key: str = "info") -> QGroupBox:
        """
        Create a styled group box with information.
        
        Args:
            title: Title of the group box
            data: Dictionary of label-value pairs
            color_key: Color key for styling ('info', 'success', 'warning', etc.)
            
        Returns:
            QGroupBox with formatted information
        """
        group = QGroupBox(title)
        group.setStyleSheet(get_group_box_style(color_key))
        
        layout = QGridLayout(group)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(SPACING['md'])
        layout.setColumnStretch(1, 1)
        
        row = 0
        for label, value in data.items():
            # Label
            label_widget = QLabel(f"{label}:")
            label_widget.setStyleSheet(get_label_style("secondary", "lg"))
            
            # Value
            value_widget = QLabel(str(value))
            value_widget.setWordWrap(True)
            value_widget.setStyleSheet(get_label_style("primary", "lg", bold=True))
            
            layout.addWidget(label_widget, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(value_widget, row, 1)
            row += 1
        
        return group
    
    def _create_services_section(self):
        """Create services section showing all services."""
        services = self.current_data.get("services", [])
        
        if not services:
            return
        
        # Create group box
        group = QGroupBox(f"Services ({len(services)})")
        group.setStyleSheet(get_group_box_style("success"))
        
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(SPACING['sm'])
        
        for idx, service in enumerate(services, 1):
            service_name = service.get("Service", "N/A")
            qty = service.get("Qty", 1)
            service_group = service.get("ServiceGroup", "")
            
            # Service container
            service_widget = QWidget()
            service_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {COLORS['bg_lighter']};
                    border-radius: {BORDER_RADIUS['sm']}px;
                    padding: 5px;
                }}
            """)
            service_layout = QVBoxLayout(service_widget)
            service_layout.setContentsMargins(SPACING['sm'], SPACING['sm'], SPACING['sm'], SPACING['sm'])
            service_layout.setSpacing(3)
            
            # Service number and group
            header = QLabel(f"#{idx} - {service_group}")
            header.setStyleSheet(get_label_style("success", "md", bold=True))
            service_layout.addWidget(header)
            
            # Service name
            name_label = QLabel(service_name)
            name_label.setWordWrap(True)
            name_label.setStyleSheet(get_label_style("primary", "md"))
            service_layout.addWidget(name_label)
            
            # Quantity
            if qty > 1:
                qty_label = QLabel(f"Quantity: {qty}")
                qty_label.setStyleSheet(get_label_style("secondary", "sm"))
                service_layout.addWidget(qty_label)
            
            layout.addWidget(service_widget)
        
        self.content_layout.addWidget(group)
    
    def _create_report_section(self):
        """Create report status section."""
        # Get report - try both direct and imagingWorkflow paths
        report = self.current_data.get("report", {})
        if not report:
            # Fallback to imagingWorkflow.report
            imaging_workflow = self.current_data.get("imagingWorkflow", {})
            report = imaging_workflow.get("report", {})
        
        if not report:
            return
        
        status = report.get("status", "pending")
        approval_flags = report.get("approvalFlags", {})
        
        # Determine status color
        if status == "completed":
            status_color = "#4caf50"
            bg_color = "#1e3a1e"
        elif status == "in_progress":
            status_color = "#ff9800"
            bg_color = "#3a2e1e"
        else:
            status_color = "#f44336"
            bg_color = "#3a1e1e"
        
        # Create group box
        group = QGroupBox("Report Status")
        group.setStyleSheet(f"""
            QGroupBox {{
                background-color: {bg_color};
                border: 2px solid {status_color};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                font-family: 'Tahoma', 'Segoe UI', sans-serif;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 3px 8px;
                color: {status_color};
            }}
        """)
        
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(6)
        
        # Status
        status_text = {
            "pending": "Pending",
            "in_progress": "In Progress",
            "completed": "Completed"
        }.get(status, status.title())
        
        status_label = QLabel(f"Status: {status_text}")
        status_label.setStyleSheet(f"color: {status_color}; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 13px; font-weight: bold;")
        layout.addWidget(status_label)
        
        # Approvals
        physician_approved = approval_flags.get("physicianApproved", False)
        secretary_approved = approval_flags.get("secretaryApproved", False)
        
        approval_widget = QWidget()
        approval_layout = QGridLayout(approval_widget)
        approval_layout.setContentsMargins(0, 0, 0, 0)
        approval_layout.setSpacing(4)
        
        # Physician approval
        phy_label = QLabel("Physician:")
        phy_label.setStyleSheet("color: #aaa; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 12px;")
        phy_status = QLabel("✓ Approved" if physician_approved else "✗ Pending")
        phy_status.setStyleSheet(f"color: {'#4caf50' if physician_approved else '#f44336'}; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 12px;")
        
        approval_layout.addWidget(phy_label, 0, 0)
        approval_layout.addWidget(phy_status, 0, 1)
        
        # Secretary approval
        sec_label = QLabel("Secretary:")
        sec_label.setStyleSheet("color: #aaa; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 12px;")
        sec_status = QLabel("✓ Approved" if secretary_approved else "✗ Pending")
        sec_status.setStyleSheet(f"color: {'#4caf50' if secretary_approved else '#f44336'}; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 12px;")
        
        approval_layout.addWidget(sec_label, 1, 0)
        approval_layout.addWidget(sec_status, 1, 1)
        
        layout.addWidget(approval_widget)
        
        # Report date if available
        report_date = report.get("reportDate")
        if report_date:
            date_label = QLabel(f"Date: {report_date}")
            date_label.setStyleSheet("color: #aaa; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 12px;")
            layout.addWidget(date_label)
        
        # Radiologist info if available
        radiologist = report.get("radiologist")
        if radiologist:
            radiologist_name = radiologist.get("FullName", "N/A")
            radiologist_label = QLabel(f"Radiologist: {radiologist_name}")
            radiologist_label.setStyleSheet("color: #2196f3; font-family: 'Tahoma', 'Segoe UI', sans-serif; font-size: 12px; font-weight: bold;")
            layout.addWidget(radiologist_label)
        
        # Check if report content exists
        report_content = report.get("content", "") or report.get("findings", "")
        if report_content:
            # Add View/Edit Report button
            view_btn = QPushButton(" View / Edit Report")
            view_btn.setIcon(qta.icon('fa5s.file-medical', color='white'))
            view_btn.setStyleSheet("""
                QPushButton {
                    background-color: #9c27b0;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    font-weight: bold;
                    margin-top: 8px;
                }
                QPushButton:hover {
                    background-color: #7b1fa2;
                }
                QPushButton:pressed {
                    background-color: #6a1b9a;
                }
            """)
            view_btn.clicked.connect(lambda: self._show_report_editor(report))
            layout.addWidget(view_btn)
        
        self.content_layout.addWidget(group)
    
    def _create_attachments_section(self):
        """Create attachments section using the modern AttachmentGrid widget."""
        attachments = self.current_data.get("attachments", [])
        attachments_count = self.current_data.get("attachmentsCount", 0)
        
        if not attachments or attachments_count == 0:
            return
        
        # Get base URL for thumbnail loading
        base_url = self.service.base_url if hasattr(self.service, 'base_url') else "http://81.16.117.196:8080"
        
        # Create the new AttachmentGrid widget
        attachment_grid = AttachmentGrid(attachments, base_url, self)
        attachment_grid.attachment_clicked.connect(self._on_attachment_clicked)
        attachment_grid.setMinimumHeight(250)
        attachment_grid.setMaximumHeight(400)
        
        self.content_layout.addWidget(attachment_grid)
    
    def _on_attachment_clicked(self, attachment: dict):
        """Handle attachment click from the grid widget."""
        file_url = attachment.get("fileUrl", "")
        file_type = attachment.get("fileType", "")
        self._open_attachment(file_url, file_type)
    
    def _open_attachment(self, file_url: str, file_type: str):
        """
        Open attachment file in internal viewer or download it.
        
        Args:
            file_url: The file URL/path
            file_type: The MIME type of the file
        """

        if not file_url:
            QMessageBox.warning(self, "No Path", "File path is not available.")
            return
        
        # Build full URL
        if file_url.startswith("/"):
            base_url = self.service.base_url if hasattr(self.service, 'base_url') else "http://81.16.117.196:8080"
            full_url = f"{base_url}{file_url}"

        elif file_url.startswith("http://") or file_url.startswith("https://"):
            full_url = file_url
        else:
            # Local file
            if os.path.isfile(file_url):
                full_url = file_url
            else:
                QMessageBox.warning(self, "File Not Found", f"File not found:\n{file_url}")
                return
        
        # Open in internal viewer for images, download for others
        if "image" in file_type.lower():
            self._show_image_viewer(full_url, file_url)
        else:
            # For PDF and other types, download the file
            self._download_file(full_url, file_url, file_type)
    
    def _download_file(self, url: str, original_path: str, file_type: str):
        """Download file to user's computer."""

        # Get filename from path
        filename = os.path.basename(original_path) if original_path else "download"
        if not filename or filename == "/":
            # Extract from URL
            filename = os.path.basename(url.split('?')[0])
        
        # Ask user where to save
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save File",
            filename,
            "All Files (*.*)"
        )
        
        if not save_path:

            return

        # Create progress dialog
        progress = QProgressDialog("Downloading file...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Download")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setStyleSheet("""
            QProgressDialog {
                background-color: #2b2b2b;
                color: white;
                font-family: 'Tahoma';
            }
            QProgressBar {
                border: 2px solid #444;
                border-radius: 5px;
                text-align: center;
                background-color: #1e1e1e;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #2196f3;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 15px;
                font-family: 'Tahoma';
            }
        """)
        
        # Download file
        network_manager = QNetworkAccessManager(self)
        
        def on_download_progress(bytes_received, bytes_total):
            if bytes_total > 0:
                progress.setValue(int(bytes_received * 100 / bytes_total))
        
        def on_finished(reply: QNetworkReply):
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    data = reply.readAll()
                    
                    # Save file
                    try:
                        with open(save_path, 'wb') as f:
                            f.write(data.data())

                        progress.close()
                        QMessageBox.information(
                            self,
                            "Download Complete",
                            f"File downloaded successfully!\n\n{save_path}"
                        )
                    except Exception as e:

                        progress.close()
                        QMessageBox.critical(
                            self,
                            "Error",
                            f"Failed to save file:\n{str(e)}"
                        )
                else:
                    progress.close()
                    QMessageBox.critical(
                        self,
                        "Download Error",
                        f"Failed to download file:\n{reply.errorString()}"
                    )
            except Exception as e:
                pass  # Failed to download
                progress.close()
                QMessageBox.critical(self, "Error", f"Error:\n{str(e)}")
            finally:
                reply.deleteLater()
        
        def on_cancelled():

            if hasattr(on_cancelled, 'reply') and on_cancelled.reply:
                on_cancelled.reply.abort()
        
        progress.canceled.connect(on_cancelled)
        
        request = QNetworkRequest(QUrl(url))
        reply = network_manager.get(request)
        on_cancelled.reply = reply
        reply.downloadProgress.connect(on_download_progress)
        network_manager.finished.connect(on_finished)
    
    def _show_image_viewer(self, url: str, original_path: str):
        """Show image in internal viewer with zoom."""

        # Create viewer dialog
        viewer = QDialog(self)
        viewer.setWindowTitle("Image Viewer - Use mouse wheel to zoom")
        viewer.resize(900, 700)
        viewer.setStyleSheet("background-color: #2b2b2b;")
        
        layout = QVBoxLayout(viewer)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Top toolbar
        toolbar_layout = QHBoxLayout()
        
        # Zoom info label
        zoom_label = QLabel("🔍 Zoom: Mouse Wheel | Pan: Click & Drag")
        zoom_label.setStyleSheet("color: #aaa; font-family: 'Tahoma'; font-size: 11px;")
        toolbar_layout.addWidget(zoom_label)
        
        toolbar_layout.addStretch()
        
        # Status label
        status_label = QLabel("Loading...")
        status_label.setStyleSheet("color: white; font-family: 'Tahoma'; font-size: 12px;")
        toolbar_layout.addWidget(status_label)
        
        layout.addLayout(toolbar_layout)
        
        # Image viewer with zoom
        image_view = ZoomableImageView()
        image_view.setStyleSheet("""
            QGraphicsView {
                border: 2px solid #444;
                border-radius: 4px;
                background-color: #1e1e1e;
            }
        """)
        layout.addWidget(image_view)
        
        # Bottom buttons
        btn_layout = QHBoxLayout()
        
        # Zoom buttons
        zoom_in_btn = QPushButton("➕ Zoom In")
        zoom_in_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-family: 'Tahoma';
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        zoom_in_btn.clicked.connect(lambda: image_view.scale(1.25, 1.25))
        btn_layout.addWidget(zoom_in_btn)
        
        zoom_out_btn = QPushButton("➖ Zoom Out")
        zoom_out_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-family: 'Tahoma';
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        zoom_out_btn.clicked.connect(lambda: image_view.scale(0.8, 0.8))
        btn_layout.addWidget(zoom_out_btn)
        
        reset_btn = QPushButton("🔄 Reset")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-family: 'Tahoma';
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        reset_btn.clicked.connect(image_view.reset_zoom)
        btn_layout.addWidget(reset_btn)
        
        btn_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-family: 'Tahoma';
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        close_btn.clicked.connect(viewer.close)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
        # Download image asynchronously
        if url.startswith("http://") or url.startswith("https://"):
            self._download_and_display_image_in_view(url, image_view, status_label)
        else:
            # Local file
            pixmap = QPixmap(url)
            if not pixmap.isNull():
                image_view.set_image(pixmap)
                status_label.setText(f"✅ {pixmap.width()}×{pixmap.height()}")
            else:
                status_label.setText("❌ Failed to load image")
        
        viewer.exec()
    
    def _download_and_display_image_in_view(self, url: str, image_view: ZoomableImageView, status_label: QLabel):
        """Download image from URL and display in zoomable view."""
        network_manager = QNetworkAccessManager(self)
        
        def on_finished(reply: QNetworkReply):
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll()
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    image_view.set_image(pixmap)
                    status_label.setText(f"✅ {pixmap.width()}×{pixmap.height()} pixels")
                else:
                    status_label.setText("❌ Failed to load image")
            else:
                status_label.setText(f"❌ Download error: {reply.errorString()}")
            reply.deleteLater()
        
        network_manager.finished.connect(on_finished)
        request = QNetworkRequest(QUrl(url))
        network_manager.get(request)
    
    def _show_pdf_viewer(self, url: str, original_path: str):
        """Show PDF in internal viewer."""

        try:
            # Create viewer dialog
            viewer = QDialog(self)
            viewer.setWindowTitle("PDF Viewer")
            viewer.resize(900, 700)
            viewer.setStyleSheet("background-color: #1e1e1e;")
            
            layout = QVBoxLayout(viewer)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(10)
            
            # Info label
            self.pdf_info_label = QLabel("PDF Document")
            self.pdf_info_label.setStyleSheet("""
                QLabel {
                    color: white;
                    font-family: 'Tahoma';
                    font-size: 14px;
                    font-weight: bold;
                    padding: 5px;
                }
            """)
            layout.addWidget(self.pdf_info_label)
            
            # Scroll area for PDF pages
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll.setStyleSheet("""
                QScrollArea {
                    border: 2px solid #444;
                    border-radius: 4px;
                    background-color: #2b2b2b;
                }
            """)
            
            # Content widget for pages
            content_widget = QWidget()
            content_layout = QVBoxLayout(content_widget)
            content_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)
            content_layout.setSpacing(10)
            
            # Loading label
            loading_label = QLabel("Loading PDF...")
            loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            loading_label.setStyleSheet("color: white; font-family: 'Tahoma'; font-size: 13px; padding: 20px;")
            content_layout.addWidget(loading_label)
            
            scroll.setWidget(content_widget)
            layout.addWidget(scroll)
            
            # Buttons
            btn_layout = QHBoxLayout()
            
            # Open in browser button
            browser_btn = QPushButton("Open in Browser")
            browser_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-family: 'Tahoma';
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #1976d2;
                }
            """)
            browser_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            btn_layout.addWidget(browser_btn)
            
            btn_layout.addStretch()
            
            # Close button
            close_btn = QPushButton("Close")
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-family: 'Tahoma';
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
            """)
            close_btn.clicked.connect(viewer.close)
            btn_layout.addWidget(close_btn)
            
            layout.addLayout(btn_layout)
            
            # Try to render PDF using available methods
            try:
                self._render_pdf(url, content_layout, loading_label)
            except Exception as e:

                loading_label.setText(f"Error: {str(e)}\nClick 'Open in Browser' to view.")
            
            viewer.exec()
        except Exception as e:

            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to open PDF viewer:\n{str(e)}")
    
    def _render_pdf(self, url: str, content_layout: QVBoxLayout, loading_label: QLabel):
        """Try to render PDF using available libraries."""

        # Try PyMuPDF (fitz)
        try:
            import fitz  # PyMuPDF

            # Download PDF if it's a URL
            if url.startswith("http://") or url.startswith("https://"):

                self._download_and_render_pdf(url, content_layout, loading_label)
            else:
                # Local file
                try:
                    doc = fitz.open(url)
                    loading_label.setText(f"PDF Pages: {len(doc)}")
                    
                    for page_num in range(min(len(doc), 10)):  # Show first 10 pages
                        page = doc.load_page(page_num)
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom
                        img_data = pix.tobytes("ppm")
                        
                        pixmap = QPixmap()
                        pixmap.loadFromData(img_data)
                        
                        page_label = QLabel()
                        page_label.setPixmap(pixmap)
                        page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        content_layout.addWidget(page_label)
                    
                    if len(doc) > 10:
                        more_label = QLabel(f"... and {len(doc) - 10} more pages")
                        more_label.setStyleSheet("color: #aaa; font-family: 'Tahoma'; font-size: 12px; padding: 10px;")
                        more_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        content_layout.addWidget(more_label)
                    
                    doc.close()

                except Exception as e:

                    import traceback
                    traceback.print_exc()
                    loading_label.setText(f"Error loading PDF:\n{str(e)}\n\nClick 'Open in Browser' to view")
        except ImportError as e:
            # PyMuPDF not available - show message

            loading_label.setText("PDF preview not available.\nClick 'Open in Browser' to view the PDF.")
            help_label = QLabel("💡 Install PyMuPDF for PDF preview:\npip install PyMuPDF")
            help_label.setStyleSheet("color: #ff9800; font-family: 'Tahoma'; font-size: 11px; padding: 10px;")
            help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content_layout.addWidget(help_label)
        except Exception as e:

            import traceback
            traceback.print_exc()
            loading_label.setText(f"Unexpected error:\n{str(e)}\n\nClick 'Open in Browser' to view")
    
    def _download_and_render_pdf(self, url: str, content_layout: QVBoxLayout, loading_label: QLabel):
        """Download PDF and render it."""

        try:
            import fitz
            import tempfile
            
            network_manager = QNetworkAccessManager(self)
            
            def on_finished(reply: QNetworkReply):

                try:
                    if reply.error() == QNetworkReply.NetworkError.NoError:
                        data = reply.readAll()

                        # Save to temp file
                        try:
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                                tmp_file.write(data.data())
                                tmp_path = tmp_file.name

                        except Exception as e:

                            loading_label.setText(f"Error saving PDF:\n{str(e)}")
                            reply.deleteLater()
                            return
                        
                        try:

                            doc = fitz.open(tmp_path)

                            loading_label.setText(f"PDF Pages: {len(doc)}")
                            
                            for page_num in range(min(len(doc), 5)):  # Show first 5 pages only

                                page = doc.load_page(page_num)
                                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))  # Reduced zoom
                                img_data = pix.tobytes("ppm")
                                
                                pixmap = QPixmap()
                                if pixmap.loadFromData(img_data):
                                    page_label = QLabel()
                                    page_label.setPixmap(pixmap)
                                    page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                                    content_layout.addWidget(page_label)
                                else:
                                    pass  # Failed to load image data
                            
                            if len(doc) > 5:
                                more_label = QLabel(f"... and {len(doc) - 5} more pages")
                                more_label.setStyleSheet("color: #aaa; font-family: 'Tahoma'; font-size: 12px; padding: 10px;")
                                more_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                                content_layout.addWidget(more_label)
                            
                            doc.close()

                        except Exception as e:

                            import traceback
                            traceback.print_exc()
                            loading_label.setText(f"Error rendering PDF:\n{str(e)}\n\nClick 'Open in Browser' to view")
                        
                        # Clean up temp file
                        try:
                            os.unlink(tmp_path)
                        except Exception as e:
                            pass  # Failed to delete temp file
                    else:
                        error_msg = reply.errorString()
                        loading_label.setText(f"Download error:\n{error_msg}\n\nClick 'Open in Browser' to view")
                except Exception as e:
                    pass  # Failed to handle PDF
                    import traceback
                    traceback.print_exc()
                    loading_label.setText(f"Error:\n{str(e)}\n\nClick 'Open in Browser' to view")
                finally:
                    reply.deleteLater()
            
            network_manager.finished.connect(on_finished)
            request = QNetworkRequest(QUrl(url))

            network_manager.get(request)
        except Exception as e:

            import traceback
            traceback.print_exc()
            loading_label.setText(f"Error:\n{str(e)}\n\nClick 'Open in Browser' to view")
    
    def _show_report_editor(self, report: dict):
        """
        Show professional dialog for viewing and editing report HTML content.
        
        Uses the new ReportEditorDialog widget with full RTL support and editing tools.
        Also checks for AI-generated reports and loads them if available.
        
        Args:
            report: The report dictionary containing content/findings
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("[AI_REPORT_LOAD] Starting report editor initialization")
        logger.info(f"[AI_REPORT_LOAD] Current report: {report.get('_id', 'N/A')}")
        
        # Check for AI-generated report from database
        ai_report_content = self._load_ai_report_if_exists()
        
        if ai_report_content:
            logger.info("[AI_REPORT_LOAD] ✅ AI report found and loaded successfully")
            logger.info(f"[AI_REPORT_LOAD] AI report length: {len(ai_report_content)} characters")
            
            # Merge AI report with existing report
            existing_content = report.get("content", "") or report.get("findings", "")
            
            if existing_content:
                logger.info("[AI_REPORT_LOAD] Merging AI report with existing report")
                # Add AI report before existing content
                merged_content = f"{ai_report_content}<hr><h3>Previous Report:</h3>{existing_content}"
                report["content"] = merged_content
                logger.info(f"[AI_REPORT_LOAD] Merged report length: {len(merged_content)} characters")
            else:
                logger.info("[AI_REPORT_LOAD] No existing report, using AI report only")
                report["content"] = ai_report_content
        else:
            logger.info("[AI_REPORT_LOAD] ❌ No AI report found for this patient")
        
        # Create the new ReportEditorDialog
        logger.info("[AI_REPORT_LOAD] Creating ReportEditorDialog")
        dialog = ReportEditorDialog(report, self.current_data, self)
        
        # Connect the save signal (now with content and status)
        dialog.report_saved.connect(lambda content, status: self._on_report_saved(content, status, dialog))
        
        # Show the dialog
        logger.info("[AI_REPORT_LOAD] Showing dialog")
        dialog.exec()
        logger.info("[AI_REPORT_LOAD] Dialog closed")
    
    def _load_ai_report_if_exists(self) -> str | None:
        """
        Load AI-generated report from database if exists for current patient.
        
        Returns:
            HTML content of AI report if found, None otherwise
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            from PacsClient import utils as U
            
            # Debug: Log the full structure
            logger.info(f"[AI_REPORT_LOAD] ====== DEBUG: Current Data Structure ======")
            logger.info(f"[AI_REPORT_LOAD] Current data keys: {list(self.current_data.keys()) if self.current_data else 'None'}")
            
            # Get patient ID from current data - try multiple sources
            patient = self.current_data.get("patient", {})
            logger.info(f"[AI_REPORT_LOAD] Patient object keys: {list(patient.keys()) if patient else 'None'}")
            
            # Try different patient ID fields in order of preference
            # Note: Field names are CASE-SENSITIVE and some are lowercase in current_data
            patient_id = (
                # Check lowercase nationalCode at top level (this is common in reception data)
                self.current_data.get("nationalCode") or
                # Check patient object fields
                patient.get("NationalID") or  # Note: It's NationalID, not NationalCode!
                patient.get("_id") or  # MongoDB patient ID
                # Check other top-level fields
                self.current_data.get("receptionId") or
                self.current_data.get("_id") or
                # Study UID fields (if present)
                self.current_data.get("studyUID") or
                self.current_data.get("study_uid") or
                # Fallback fields
                self.current_data.get("patientId") or
                self.current_data.get("patient_id")
            )
            
            logger.info(f"[AI_REPORT_LOAD] Patient ID resolution:")
            logger.info(f"  - current_data.nationalCode: {self.current_data.get('nationalCode', 'N/A')}")
            logger.info(f"  - patient.NationalID: {patient.get('NationalID', 'N/A')}")
            logger.info(f"  - patient._id: {patient.get('_id', 'N/A')}")
            logger.info(f"  - current_data.receptionId: {self.current_data.get('receptionId', 'N/A')}")
            logger.info(f"  - current_data._id: {self.current_data.get('_id', 'N/A')}")
            logger.info(f"  ➜ Selected patient_id: {patient_id}")
            
            # IMPORTANT: Build a list of ALL possible patient IDs to search with
            # This is because AI Chat might use Study UID, but Medical Report Editor has different IDs
            possible_patient_ids = []
            
            # Collect all non-None identifiers
            for field_value in [
                self.current_data.get("nationalCode"),
                patient.get("NationalID"),
                patient.get("_id"),
                self.current_data.get("receptionId"),
                self.current_data.get("_id"),
                self.current_data.get("studyUID"),
                self.current_data.get("study_uid"),
            ]:
                if field_value and str(field_value) not in possible_patient_ids:
                    possible_patient_ids.append(str(field_value))
            
            if not possible_patient_ids:
                logger.warning("[AI_REPORT_LOAD] No patient identifiers found in current data")
                logger.debug(f"[AI_REPORT_LOAD] Full current_data: {self.current_data}")
                return None
            
            logger.info(f"[AI_REPORT_LOAD] Searching for AI reports with {len(possible_patient_ids)} possible patient IDs:")
            for idx, pid in enumerate(possible_patient_ids, 1):
                logger.info(f"  {idx}. {pid}")
            
            # Try searching with each patient ID until we find a report
            all_reports = []
            for search_id in possible_patient_ids:
                logger.info(f"[AI_REPORT_LOAD] → Searching with patient_id: {search_id}")
                
                reports = U.ai_get_reception_reports(
                    patient_id=str(search_id),
                    status=None,  # Get all statuses
                    limit=10  # Get up to 10 most recent
                )
                
                if reports:
                    logger.info(f"[AI_REPORT_LOAD]   ✓ Found {len(reports)} report(s) with this ID")
                    all_reports.extend(reports)
                else:
                    logger.info(f"[AI_REPORT_LOAD]   ✗ No reports found with this ID")
            
            # Remove duplicates (same report ID)
            seen_ids = set()
            unique_reports = []
            for report in all_reports:
                report_id = report.get('id')
                if report_id not in seen_ids:
                    seen_ids.add(report_id)
                    unique_reports.append(report)
            
            # Remove duplicates (same report ID)
            seen_ids = set()
            unique_reports = []
            for report in all_reports:
                report_id = report.get('id')
                if report_id not in seen_ids:
                    seen_ids.add(report_id)
                    unique_reports.append(report)
            
            if not unique_reports:
                logger.info(f"[AI_REPORT_LOAD] ❌ No AI reports found for any of the patient IDs")
                return None
            
            # Sort by created_at descending to get most recent first
            unique_reports = sorted(unique_reports, key=lambda r: r.get('created_at', 0), reverse=True)
            
            logger.info(f"[AI_REPORT_LOAD] ✅ Found {len(unique_reports)} unique AI report(s) across all patient IDs")
            
            # Get the most recent report
            report = unique_reports[0]
            logger.info(f"[AI_REPORT_LOAD] Using most recent AI report:")
            logger.info(f"  • Report ID: {report.get('id', 'N/A')}")
            logger.info(f"  • Report status: {report.get('status', 'N/A')}")
            logger.info(f"  • Created at: {report.get('created_at', 'N/A')}")
            logger.info(f"  • Modality: {report.get('sender_info', 'N/A')}")
            
            html_content = report.get('html_content', '')
            
            if not html_content:
                logger.warning("[AI_REPORT_LOAD] AI report found but content is empty")
                return None
            
            logger.info(f"[AI_REPORT_LOAD] Successfully loaded AI report content ({len(html_content)} chars)")
            
            # Mark report as read (only if it's pending)
            if report.get('status') == 'pending':
                try:
                    U.ai_mark_reception_report_read(report['id'])
                    logger.info(f"[AI_REPORT_LOAD] Marked report #{report['id']} as read")
                except Exception as e:
                    logger.warning(f"[AI_REPORT_LOAD] Failed to mark report as read: {e}")
            
            return html_content
            
        except ImportError as e:
            logger.error(f"[AI_REPORT_LOAD] Import error: {e}")
            return None
        except Exception as e:
            logger.error(f"[AI_REPORT_LOAD] Error loading AI report: {e}")
            import traceback
            logger.error(f"[AI_REPORT_LOAD] Traceback: {traceback.format_exc()}")
            return None
    
    def _on_report_saved(self, new_content: str, new_status: str, dialog: ReportEditorDialog):
        """
        Handle report save from the editor dialog.
        
        Args:
            new_content: The new HTML content
            new_status: The new report status
            dialog: The editor dialog
        """
        # Get reception ID - API uses receptionId not patient _id
        reception_id = self.current_data.get("receptionId") or self.current_data.get("ReceptionID")
        
        if not reception_id:
            # Fallback to _id
            reception_id = self.current_data.get("_id") or self.current_data.get("id")
        
        if not reception_id:
            QMessageBox.warning(dialog, "Error", "Reception number not found.")
            return
        
        self._save_report_to_api(reception_id, new_content, new_status, dialog)
    
    def _save_report_to_api(self, reception_id, new_content: str, new_status: str, dialog):
        """
        Save report content to API using the update-report endpoint.
        
        Args:
            reception_id: The reception ID (receptionId)
            new_content: The new HTML content
            new_status: The new report status
            dialog: The parent dialog for showing messages
        """
        import requests
        
        # Get authentication token
        token_manager = get_socket_token_manager()
        token = token_manager.get_token()
        
        if not token:
            QMessageBox.critical(dialog, "Authentication Error", "Authentication token not found. Please log in again.")
            return
        
        # Prepare update data for the new API
        update_data = {
            "receptionId": int(reception_id) if isinstance(reception_id, str) and reception_id.isdigit() else reception_id,
            "content": new_content,
            "findings": new_content,
            "status": new_status
        }
        
        # Make API call
        try:
            url = f"{self.service.base_url}/api/pacs/update-report"
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
            
            response = requests.post(
                url,
                json=update_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get("success"):
                    # Update local data
                    if "report" in self.current_data and self.current_data["report"]:
                        self.current_data["report"]["content"] = new_content
                        self.current_data["report"]["findings"] = new_content
                        self.current_data["report"]["status"] = new_status
                    elif "imagingWorkflow" in self.current_data:
                        if "report" in self.current_data["imagingWorkflow"]:
                            self.current_data["imagingWorkflow"]["report"]["content"] = new_content
                            self.current_data["imagingWorkflow"]["report"]["findings"] = new_content
                            self.current_data["imagingWorkflow"]["report"]["status"] = new_status
                    
                    success_msg = response_data.get("message", "Report saved successfully.")
                    QMessageBox.information(dialog, "Success", success_msg)
                else:
                    error_msg = response_data.get("message", "Error saving report")
                    QMessageBox.critical(dialog, "Error", error_msg)
            elif response.status_code == 401:
                QMessageBox.critical(dialog, "Authentication Error", "Invalid or expired token. Please log in again.")
            elif response.status_code == 403:
                QMessageBox.critical(dialog, "Access Error", "You don't have permission for this operation.")
            elif response.status_code == 404:
                QMessageBox.critical(dialog, "Error", "Requested reception not found.")
            else:
                error_msg = f"Error saving report: {response.status_code}"
                try:
                    error_data = response.json()
                    if "message" in error_data:
                        error_msg = error_data["message"]
                except:
                    pass
                QMessageBox.critical(dialog, "Error", error_msg)

        except requests.exceptions.Timeout:
            QMessageBox.critical(dialog, "Error", "Request timed out. Please try again.")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(dialog, "Connection Error", "Error connecting to server. Please check your internet connection.")
        except Exception as e:
            QMessageBox.critical(dialog, "Error", f"Unexpected error: {str(e)}")

    def _create_reception_info_section(self):
        """Create reception information section using the modern ReceptionInfoCard widget."""
        # Use the new ReceptionInfoCard widget for modern design
        reception_card = ReceptionInfoCard(self.current_data, self)
        self.content_layout.addWidget(reception_card)
    
    def _create_patient_info_section(self):
        """Create patient information section using the modern PatientInfoCard widget."""
        # Use the new PatientInfoCard widget for modern design
        patient_card = PatientInfoCard(self.current_data, self)
        self.content_layout.addWidget(patient_card)
    
    def _create_modality_info_section(self):
        """Create modality information section."""
        modality = self.current_data.get("modality", {})
        
        data = {
            "Type": modality.get("Modality", "N/A"),
            "Name": modality.get("FullName", "N/A"),
        }
        
        section = self._create_info_group("Modality", data)
        self.content_layout.addWidget(section)
    
    def _create_physician_info_section(self):
        """Create referring physician information section."""
        physician = self.current_data.get("referrerPhysician", {})
        
        if physician:
            data = {
                "Name": physician.get("FullName", "N/A"),
                "Expertise": physician.get("Expertise", "N/A"),
                "ID": physician.get("MSID", "N/A"),
            }
            
            section = self._create_info_group("Physician", data)
            self.content_layout.addWidget(section)
    
    def _create_appointment_info_section(self):
        """Create appointment information section."""
        appointment = self.current_data.get("appointment")
        
        if appointment:
            room = appointment.get("room", {})
            
            data = {
                "Date": appointment.get("persianDate", "N/A"),
                "Time": appointment.get("timeSlot", "N/A"),
                "Duration": f"{appointment.get('duration', 'N/A')} min",
                "Room": f"{room.get('roomNumber', 'N/A')} - {room.get('name', 'N/A')}",
                "Shift": appointment.get("shiftName", "N/A"),
            }
            
            section = self._create_info_group("Appointment", data)
            self.content_layout.addWidget(section)

