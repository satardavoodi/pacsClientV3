"""Slide editor widget for editing individual slide content."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QFileDialog, QMessageBox, QScrollArea, QFrame, QListWidget,
    QListWidgetItem, QDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from pathlib import Path
import json

from modules.education.course_database import (
    get_content_for_slide, insert_slide_content, update_slide_content,
    delete_slide_content, save_course_asset
)
from modules.education.study_picker_dialog import StudyPickerDialog


class ContentItemWidget(QWidget):
    """Widget representing a single content item in the slide."""
    
    delete_requested = Signal(int)  # content_pk
    move_up_requested = Signal(int)
    move_down_requested = Signal(int)
    
    def __init__(self, content_data, parent=None):
        super().__init__(parent)
        self.content_pk = content_data['content_pk']
        self.content_type = content_data['content_type']
        self.content_data = content_data['content_data']
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the content item UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Content type icon and info
        info_layout = QVBoxLayout()
        
        type_label = QLabel(self.get_type_icon() + " " + self.content_type.replace('_', ' ').title())
        type_font = QFont()
        type_font.setBold(True)
        type_label.setFont(type_font)
        type_label.setStyleSheet("color: #e2e8f0;")
        info_layout.addWidget(type_label)
        
        preview_label = QLabel(self.get_content_preview())
        preview_label.setStyleSheet("color: #a0aec0;")
        preview_label.setWordWrap(True)
        info_layout.addWidget(preview_label)
        
        layout.addLayout(info_layout, stretch=1)
        
        # Action buttons
        buttons_layout = QVBoxLayout()
        
        up_btn = QPushButton("↑")
        up_btn.setFixedSize(30, 30)
        up_btn.clicked.connect(lambda: self.move_up_requested.emit(self.content_pk))
        up_btn.setStyleSheet("""
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
        buttons_layout.addWidget(up_btn)
        
        down_btn = QPushButton("↓")
        down_btn.setFixedSize(30, 30)
        down_btn.clicked.connect(lambda: self.move_down_requested.emit(self.content_pk))
        down_btn.setStyleSheet(up_btn.styleSheet())
        buttons_layout.addWidget(down_btn)
        
        delete_btn = QPushButton("✖")
        delete_btn.setFixedSize(30, 30)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.content_pk))
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #e53e3e;
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c53030;
            }
        """)
        buttons_layout.addWidget(delete_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setStyleSheet("""
            ContentItemWidget {
                background-color: #2d3748;
                border-radius: 5px;
                border: 1px solid #4a5568;
            }
        """)
    
    def get_type_icon(self):
        """Get emoji icon for content type."""
        icons = {
            'text': '📝',
            'image': '🖼️',
            'video': '🎥',
            'dicom_study': '🏥',
            'dicom_series': '📊'
        }
        return icons.get(self.content_type, '📄')
    
    def get_content_preview(self):
        """Get preview text for content."""
        if self.content_type == 'text':
            text = self.content_data.get('text', '')
            return text[:100] + '...' if len(text) > 100 else text
        elif self.content_type == 'image':
            return f"Image: {Path(self.content_data.get('path', '')).name}"
        elif self.content_type == 'video':
            return f"Video: {Path(self.content_data.get('path', '')).name}"
        elif self.content_type == 'dicom_study':
            return f"DICOM Study: {self.content_data.get('study_uid', 'Unknown')}"
        elif self.content_type == 'dicom_series':
            return f"DICOM Series {self.content_data.get('series_number', '?')}: {self.content_data.get('study_uid', 'Unknown')}"
        return "Unknown content"


class AddContentDialog(QDialog):
    """Dialog for adding text content."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Text Content")
        self.setMinimumSize(600, 400)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        label = QLabel("Enter text content:")
        label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        layout.addWidget(label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 10px;
                font-size: 11pt;
            }
        """)
        layout.addWidget(self.text_edit)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6b7280;
            }
        """)
        buttons_layout.addWidget(cancel_btn)
        
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self.accept)
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
        """)
        buttons_layout.addWidget(add_btn)
        
        layout.addLayout(buttons_layout)
    
    def get_text(self):
        """Get entered text."""
        return self.text_edit.toPlainText()


class SlideEditorWidget(QWidget):
    """Widget for editing a single slide's content."""
    
    content_changed = Signal()
    
    def __init__(self, slide_pk, course_pk, parent=None):
        super().__init__(parent)
        self.slide_pk = slide_pk
        self.course_pk = course_pk
        self.content_items = []
        self.setup_ui()
        self.load_content()
    
    def setup_ui(self):
        """Setup the slide editor UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Toolbar with add buttons
        toolbar = QWidget()
        toolbar.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
                border-radius: 8px;
            }
        """)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 10, 10, 10)
        toolbar_layout.setSpacing(10)
        
        toolbar_label = QLabel("Add Content:")
        toolbar_label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        toolbar_layout.addWidget(toolbar_label)
        
        # Add content buttons
        self.add_text_btn = QPushButton("📝 Text")
        self.add_text_btn.clicked.connect(self.add_text_content)
        self.add_text_btn.setStyleSheet(self._get_toolbar_button_style())
        toolbar_layout.addWidget(self.add_text_btn)
        
        self.add_image_btn = QPushButton("🖼️ Image")
        self.add_image_btn.clicked.connect(self.add_image_content)
        self.add_image_btn.setStyleSheet(self._get_toolbar_button_style())
        toolbar_layout.addWidget(self.add_image_btn)
        
        self.add_video_btn = QPushButton("🎥 Video")
        self.add_video_btn.clicked.connect(self.add_video_content)
        self.add_video_btn.setStyleSheet(self._get_toolbar_button_style())
        toolbar_layout.addWidget(self.add_video_btn)
        
        self.add_dicom_btn = QPushButton("🏥 DICOM")
        self.add_dicom_btn.clicked.connect(self.add_dicom_content)
        self.add_dicom_btn.setStyleSheet(self._get_toolbar_button_style())
        toolbar_layout.addWidget(self.add_dicom_btn)
        
        toolbar_layout.addStretch()
        
        layout.addWidget(toolbar)
        
        # Content list scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        self.content_list_widget = QWidget()
        self.content_list_layout = QVBoxLayout(self.content_list_widget)
        self.content_list_layout.setSpacing(10)
        self.content_list_layout.setContentsMargins(0, 0, 0, 0)
        self.content_list_layout.addStretch()
        
        scroll.setWidget(self.content_list_widget)
        layout.addWidget(scroll)
        
        # Empty state
        self.empty_label = QLabel("No content yet. Use the buttons above to add content to this slide.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #a0aec0; padding: 50px;")
        layout.addWidget(self.empty_label)
    
    def _get_toolbar_button_style(self):
        """Get toolbar button stylesheet."""
        return """
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
        """
    
    def load_content(self):
        """Load content for this slide from database."""
        # Clear existing
        while self.content_list_layout.count() > 1:
            item = self.content_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Load from database
        content_list = get_content_for_slide(self.slide_pk)
        
        if not content_list:
            self.empty_label.show()
            self.content_list_widget.hide()
        else:
            self.empty_label.hide()
            self.content_list_widget.show()
            
            for content in content_list:
                item_widget = ContentItemWidget(content)
                item_widget.delete_requested.connect(self.delete_content)
                item_widget.move_up_requested.connect(self.move_content_up)
                item_widget.move_down_requested.connect(self.move_content_down)
                self.content_list_layout.insertWidget(
                    self.content_list_layout.count() - 1, 
                    item_widget
                )
    
    def add_text_content(self):
        """Add text content to slide."""
        dialog = AddContentDialog(self)
        if dialog.exec() == QDialog.Accepted:
            text = dialog.get_text()
            if text.strip():
                try:
                    content_order = self.content_list_layout.count() - 1
                    content_data = {'text': text}
                    
                    insert_slide_content(
                        self.slide_pk,
                        'text',
                        content_order,
                        content_data
                    )
                    
                    self.load_content()
                    self.content_changed.emit()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to add text: {str(e)}")
    
    def add_image_content(self):
        """Add image content to slide."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        
        if file_path:
            try:
                # Copy to course assets
                saved_path = save_course_asset(file_path, self.course_pk)
                
                content_order = self.content_list_layout.count() - 1
                content_data = {
                    'path': saved_path,
                    'caption': Path(file_path).stem
                }
                
                insert_slide_content(
                    self.slide_pk,
                    'image',
                    content_order,
                    content_data
                )
                
                self.load_content()
                self.content_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add image: {str(e)}")
    
    def add_video_content(self):
        """Add video content to slide."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video",
            "",
            "Videos (*.mp4 *.avi *.mov *.mkv *.wmv)"
        )
        
        if file_path:
            try:
                # Copy to course assets
                saved_path = save_course_asset(file_path, self.course_pk)
                
                content_order = self.content_list_layout.count() - 1
                content_data = {
                    'path': saved_path,
                    'autoplay': False
                }
                
                insert_slide_content(
                    self.slide_pk,
                    'video',
                    content_order,
                    content_data
                )
                
                self.load_content()
                self.content_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add video: {str(e)}")
    
    def add_dicom_content(self):
        """Add DICOM study/series content to slide."""
        dialog = StudyPickerDialog(self)
        if dialog.exec() == QDialog.Accepted:
            selected = dialog.get_selected_study()
            
            try:
                content_order = self.content_list_layout.count() - 1
                
                if selected['mode'] == 'series':
                    content_type = 'dicom_series'
                    content_data = {
                        'study_uid': selected['study_uid'],
                        'patient_id': selected['patient_id'],
                        'series_number': selected['series_number']
                    }
                else:
                    content_type = 'dicom_study'
                    content_data = {
                        'study_uid': selected['study_uid'],
                        'patient_id': selected['patient_id']
                    }
                
                insert_slide_content(
                    self.slide_pk,
                    content_type,
                    content_order,
                    content_data
                )
                
                self.load_content()
                self.content_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add DICOM: {str(e)}")
    
    def delete_content(self, content_pk):
        """Delete a content item."""
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Delete this content item?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                delete_slide_content(content_pk)
                self.load_content()
                self.content_changed.emit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete: {str(e)}")
    
    def move_content_up(self, content_pk):
        """Move content item up in order."""
        self._reorder_content(content_pk, direction=-1)

    def move_content_down(self, content_pk):
        """Move content item down in order."""
        self._reorder_content(content_pk, direction=1)

    def _reorder_content(self, content_pk, direction: int):
        """Swap a content item with its neighbor and persist the new order.

        Used by both Move Up (direction=-1) and Move Down (direction=1).
        """
        try:
            items = list(get_content_for_slide(self.slide_pk))
            current_index = next(
                (i for i, item in enumerate(items) if item.get('content_pk') == content_pk),
                -1,
            )
            if current_index < 0:
                return
            target_index = current_index + direction
            if target_index < 0 or target_index >= len(items):
                return

            items[current_index], items[target_index] = items[target_index], items[current_index]
            for order, item in enumerate(items, start=1):
                update_slide_content(content_pk=item['content_pk'], content_order=order)

            self.load_content()
            self.content_changed.emit()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to reorder content: {exc}")
