"""
Attachment Viewer Widget

Grid-based attachment viewer with thumbnail support and preview capabilities.
"""

from PacsClient.utils.scroll_style import get_scroll_area_style

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QFrame, QScrollArea, QSizePolicy, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QSize, QUrl
from PySide6.QtGui import QCursor, QPixmap, QMouseEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
import qtawesome as qta

from ..reception_data_styles import (
    COLORS, FONTS, FONT_SIZES, BORDER_RADIUS, SPACING,
    get_group_box_style
)


class AttachmentThumbnail(QWidget):
    """
    Clickable thumbnail widget for attachments.
    
    Features:
    - Image preview for images
    - Type-based icons for other files
    - Hover effects
    - File info display
    """
    
    clicked = Signal(dict)  # Emits attachment data when clicked
    
    def __init__(self, attachment: dict, base_url: str = "", parent=None):
        """
        Initialize attachment thumbnail.
        
        Args:
            attachment: Attachment data dictionary
            base_url: Base URL for fetching images
            parent: Parent widget
        """
        super().__init__(parent)
        self.attachment = attachment
        self.base_url = base_url
        self.network_manager = None
        self._setup_ui()
        self._load_thumbnail()
    
    def _setup_ui(self):
        """Set up the thumbnail UI."""
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedSize(160, 180)
        self.setStyleSheet(f"""
            AttachmentThumbnail {{
                background-color: {COLORS['bg_lighter']};
                border: 2px solid {COLORS['border_medium']};
                border-radius: {BORDER_RADIUS['md']}px;
            }}
            AttachmentThumbnail:hover {{
                background-color: {COLORS['bg_card']};
                border-color: {COLORS['info']};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        
        # Thumbnail/icon area
        self.thumb_container = QWidget()
        self.thumb_container.setFixedSize(140, 100)
        self.thumb_container.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_dark']};
                border-radius: {BORDER_RADIUS['sm']}px;
            }}
        """)
        
        thumb_layout = QVBoxLayout(self.thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Thumbnail image or icon
        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background: transparent;")
        
        # Set initial icon based on file type
        file_type = self.attachment.get("fileType", "").lower()
        if "image" in file_type:
            icon_name = 'fa5s.image'
            icon_color = COLORS['success']
        elif "pdf" in file_type:
            icon_name = 'fa5s.file-pdf'
            icon_color = COLORS['error']
        elif "video" in file_type:
            icon_name = 'fa5s.video'
            icon_color = COLORS['warning']
        elif "word" in file_type or "doc" in file_type:
            icon_name = 'fa5s.file-word'
            icon_color = COLORS['info']
        elif "excel" in file_type or "xls" in file_type:
            icon_name = 'fa5s.file-excel'
            icon_color = COLORS['success']
        else:
            icon_name = 'fa5s.file'
            icon_color = COLORS['text_secondary']
        
        self.thumb_label.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(48, 48))
        thumb_layout.addWidget(self.thumb_label)
        
        layout.addWidget(self.thumb_container)
        
        # File name
        file_name = self.attachment.get("fileName", "Unknown")
        # Truncate if too long
        if len(file_name) > 18:
            file_name = file_name[:15] + "..."
        
        name_label = QLabel(file_name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setToolTip(self.attachment.get("fileName", ""))
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['sm']}px;
                background: transparent;
            }}
        """)
        layout.addWidget(name_label)
        
        # File size and type
        file_size = self.attachment.get("fileSize", 0)
        size_str = self._format_size(file_size)
        
        info_label = QLabel(f"{size_str}")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['xs']}px;
                background: transparent;
            }}
        """)
        layout.addWidget(info_label)
    
    def _format_size(self, size: int) -> str:
        """Format file size to human readable string."""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.2f} MB"
    
    def _load_thumbnail(self):
        """Load thumbnail for image files."""
        file_type = self.attachment.get("fileType", "").lower()
        if "image" not in file_type:
            return
        
        file_url = self.attachment.get("fileUrl", "")
        if not file_url:
            return
        
        # Build full URL
        if file_url.startswith("/"):
            full_url = f"{self.base_url}{file_url}"
        elif file_url.startswith("http"):
            full_url = file_url
        else:
            return
        
        # Create network manager and fetch image
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.finished.connect(self._on_thumbnail_loaded)
        
        request = QNetworkRequest(QUrl(full_url))
        self.network_manager.get(request)
    
    def _on_thumbnail_loaded(self, reply: QNetworkReply):
        """Handle loaded thumbnail image."""
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                # Scale to fit thumbnail area
                scaled = pixmap.scaled(
                    130, 90,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.thumb_label.setPixmap(scaled)
        reply.deleteLater()
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle click to emit signal."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.attachment)
        super().mousePressEvent(event)


class AttachmentGrid(QWidget):
    """
    Grid layout widget for displaying multiple attachments.
    
    Features:
    - Responsive grid layout
    - Thumbnail previews
    - Click to open/download
    - Grouping by file type
    """
    
    attachment_clicked = Signal(dict)  # Emits when an attachment is clicked
    
    def __init__(self, attachments: list, base_url: str = "", parent=None):
        """
        Initialize attachment grid.
        
        Args:
            attachments: List of attachment dictionaries
            base_url: Base URL for fetching files
            parent: Parent widget
        """
        super().__init__(parent)
        self.attachments = attachments
        self.base_url = base_url
        self._setup_ui()

    def _setup_ui(self):
        """Set up the grid UI."""
        self.setStyleSheet(f"""
            AttachmentGrid {{
                background-color: {COLORS['info_bg']};
                border: 2px solid {COLORS['info']};
                border-radius: {BORDER_RADIUS['lg']}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = self._create_header()
        layout.addWidget(header)

        # Content with scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(get_scroll_area_style())

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        grid_layout = QGridLayout(content)
        grid_layout.setContentsMargins(15, 15, 15, 15)
        grid_layout.setSpacing(15)

        # Add attachment thumbnails to grid
        columns = 4  # Number of columns
        for idx, attachment in enumerate(self.attachments):
            row = idx // columns
            col = idx % columns

            thumbnail = AttachmentThumbnail(attachment, self.base_url, self)
            thumbnail.clicked.connect(self.attachment_clicked.emit)
            grid_layout.addWidget(thumbnail, row, col)

        # Add stretch to fill remaining space
        grid_layout.setRowStretch(len(self.attachments) // columns + 1, 1)

        scroll.setWidget(content)
        layout.addWidget(scroll)
    
    def _create_header(self) -> QWidget:
        """Create the section header."""
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['info_bg']};
                border-top-left-radius: {BORDER_RADIUS['md']}px;
                border-top-right-radius: {BORDER_RADIUS['md']}px;
                border-bottom: 1px solid {COLORS['info']};
            }}
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Icon
        icon = QLabel()
        icon.setPixmap(qta.icon('fa5s.paperclip', color=COLORS['info']).pixmap(24, 24))
        icon.setStyleSheet("background: transparent;")
        layout.addWidget(icon)
        
        # Title
        title = QLabel(f" Attachments ({len(self.attachments)})")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['info']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['xl']}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        layout.addWidget(title)
        layout.addStretch()
        
        # File type summary
        images = sum(1 for a in self.attachments if 'image' in a.get('fileType', '').lower())
        pdfs = sum(1 for a in self.attachments if 'pdf' in a.get('fileType', '').lower())
        others = len(self.attachments) - images - pdfs
        
        summary_parts = []
        if images:
            summary_parts.append(f"{images} images")
        if pdfs:
            summary_parts.append(f"{pdfs} PDFs")
        if others:
            summary_parts.append(f"{others} other")
        
        if summary_parts:
            summary = QLabel(" | ".join(summary_parts))
            summary.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_secondary']};
                    font-family: {FONTS['primary']};
                    font-size: {FONT_SIZES['sm']}px;
                    background: transparent;
                }}
            """)
            layout.addWidget(summary)
        
        return header
    
    def update_attachments(self, attachments: list):
        """
        Update the grid with new attachments.
        
        Args:
            attachments: New list of attachment dictionaries
        """
        self.attachments = attachments
        # Clear and rebuild
        for i in reversed(range(self.layout().count())):
            widget = self.layout().itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self._setup_ui()


class AttachmentListItem(QWidget):
    """
    List-style attachment item widget (alternative to grid).
    """
    
    clicked = Signal(dict)
    
    def __init__(self, attachment: dict, index: int, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.index = index
        self._setup_ui()
    
    def _setup_ui(self):
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"""
            AttachmentListItem {{
                background-color: {COLORS['bg_lighter']};
                border: 2px solid {COLORS['border_medium']};
                border-radius: {BORDER_RADIUS['sm']}px;
            }}
            AttachmentListItem:hover {{
                background-color: {COLORS['bg_card']};
                border-color: {COLORS['info']};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        
        # Header row with type and size
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        
        # File type with icon
        file_type = self.attachment.get("fileType", "").lower()
        if "image" in file_type:
            type_label = "Image"
            type_color = COLORS['success']
            icon_name = 'fa5s.image'
        elif "pdf" in file_type:
            type_label = "PDF"
            type_color = COLORS['error']
            icon_name = 'fa5s.file-pdf'
        elif "video" in file_type:
            type_label = "Video"
            type_color = COLORS['warning']
            icon_name = 'fa5s.video'
        else:
            type_label = "File"
            type_color = COLORS['text_secondary']
            icon_name = 'fa5s.file'
        
        icon = QLabel()
        icon.setPixmap(qta.icon(icon_name, color=type_color).pixmap(16, 16))
        icon.setStyleSheet("background: transparent;")
        header_layout.addWidget(icon)
        
        type_lbl = QLabel(f"#{self.index} {type_label}")
        type_lbl.setStyleSheet(f"""
            QLabel {{
                color: {type_color};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['md']}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        header_layout.addWidget(type_lbl)
        
        header_layout.addStretch()
        
        # File size
        file_size = self.attachment.get("fileSize", 0)
        size_str = self._format_size(file_size)
        size_lbl = QLabel(size_str)
        size_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['sm']}px;
                background: transparent;
            }}
        """)
        header_layout.addWidget(size_lbl)
        
        layout.addWidget(header)
        
        # File name
        file_name = self.attachment.get("fileName", "Unknown")
        name_lbl = QLabel(file_name)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['md']}px;
                background: transparent;
            }}
        """)
        layout.addWidget(name_lbl)
        
        # Date/time
        upload_date = self.attachment.get("uploadDate", "")
        upload_time = self.attachment.get("uploadTime", "")
        if upload_date or upload_time:
            datetime_lbl = QLabel(f"{upload_date} {upload_time}".strip())
            datetime_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_muted']};
                    font-family: {FONTS['primary']};
                    font-size: {FONT_SIZES['xs']}px;
                    background: transparent;
                }}
            """)
            layout.addWidget(datetime_lbl)
    
    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.2f} MB"
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.attachment)
        super().mousePressEvent(event)
