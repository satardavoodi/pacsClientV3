"""Main education widget - Redesigned for professional medical education UI."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QDialog, QLineEdit, QTextEdit, QGridLayout,
    QScrollArea, QFrame, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QPixmap, QFont, QPainter, QColor, QPen

from pathlib import Path
from datetime import datetime

from PacsClient.pacs.education.course_database import (
    get_all_courses, delete_course, get_course_with_slides
)


class CourseCardWidget(QFrame):
    """Modern card widget for course display with hover effects."""
    
    clicked = Signal(int)  # course_pk
    edit_clicked = Signal(int)
    present_clicked = Signal(int)
    delete_clicked = Signal(int)
    
    def __init__(self, course_data, parent=None):
        super().__init__(parent)
        self.course_pk = course_data['course_pk']
        self.course_data = course_data
        self.setup_ui()
        self.setMouseTracking(True)
    
    def setup_ui(self):
        """Setup modern card UI."""
        self.setFixedSize(340, 290)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Thumbnail area (40% of card)
        thumbnail_container = QFrame()
        thumbnail_container.setFixedHeight(116)
        thumbnail_container.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3182ce, stop:0.5 #7c3aed, stop:1 #3182ce);
                border-radius: 12px 12px 0 0;
            }
        """)
        thumb_layout = QVBoxLayout(thumbnail_container)
        thumb_layout.setAlignment(Qt.AlignCenter)
        
        # Icon or thumbnail
        if self.course_data.get('thumbnail_path') and Path(self.course_data['thumbnail_path']).exists():
            pixmap = QPixmap(self.course_data['thumbnail_path'])
            thumb_label = QLabel()
            thumb_label.setPixmap(pixmap.scaled(280, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            thumb_layout.addWidget(thumb_label)
        else:
            icon_label = QLabel("🎓")
            icon_label.setAlignment(Qt.AlignCenter)
            icon_font = QFont()
            icon_font.setPointSize(42)
            icon_label.setFont(icon_font)
            icon_label.setStyleSheet("color: rgba(255, 255, 255, 0.9);")
            thumb_layout.addWidget(icon_label)
        
        layout.addWidget(thumbnail_container)
        
        # Content area
        content_frame = QFrame()
        content_frame.setStyleSheet("""
            QFrame {
                background-color: #2d3748;
                border-radius: 0 0 12px 12px;
            }
        """)
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(18, 16, 18, 16)
        content_layout.setSpacing(12)
        
        # Course title
        title_label = QLabel(self.course_data['course_name'])
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #f7fafc; line-height: 1.3;")
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(50)
        content_layout.addWidget(title_label)
        
        # Author and date
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)
        
        author_name = self.course_data.get('author_name', 'Unknown')
        # Truncate if too long
        if len(author_name) > 15:
            author_name = author_name[:15] + '...'
        
        author_label = QLabel(f"👤 {author_name}")
        author_label.setStyleSheet("color: #a0aec0; font-size: 9pt;")
        meta_layout.addWidget(author_label)
        
        meta_layout.addStretch()
        
        # Date
        date_str = self.course_data.get('created_at', '')[:10] if self.course_data.get('created_at') else ''
        if date_str:
            date_label = QLabel(f"📅 {date_str}")
            date_label.setStyleSheet("color: #a0aec0; font-size: 9pt;")
            meta_layout.addWidget(date_label)
        
        content_layout.addLayout(meta_layout)
        
        content_layout.addSpacing(4)
        
        # Action buttons row
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(8)
        
        # Present button (primary)
        present_btn = QPushButton("▶ Present")
        present_btn.setFixedHeight(36)
        present_btn.clicked.connect(lambda: self.present_clicked.emit(self.course_pk))
        present_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 0 18px;
                font-weight: bold;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
        """)
        actions_layout.addWidget(present_btn)
        
        # Edit button (secondary)
        edit_btn = QPushButton("✏️")
        edit_btn.setFixedSize(36, 36)
        edit_btn.setToolTip("Edit Course")
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.course_pk))
        edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 7px;
                font-size: 13pt;
            }
            QPushButton:hover {
                background-color: #6b7280;
            }
        """)
        actions_layout.addWidget(edit_btn)
        
        # Delete button
        delete_btn = QPushButton("🗑️")
        delete_btn.setFixedSize(36, 36)
        delete_btn.setToolTip("Delete Course")
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.course_pk))
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 7px;
                font-size: 13pt;
            }
            QPushButton:hover {
                background-color: #e53e3e;
            }
        """)
        actions_layout.addWidget(delete_btn)
        
        content_layout.addLayout(actions_layout)
        layout.addWidget(content_frame)
        
        # Card styling with shadow effect
        self.setStyleSheet("""
            CourseCardWidget {
                background-color: #2d3748;
                border-radius: 12px;
                border: 2px solid #374151;
            }
            CourseCardWidget:hover {
                border: 2px solid #3182ce;
            }
        """)
    
    def mousePressEvent(self, event):
        """Handle card click."""
        if event.button() == Qt.LeftButton:
            # Only emit if not clicking buttons
            if not self.childAt(event.pos()) or not isinstance(self.childAt(event.pos()), QPushButton):
                self.edit_clicked.emit(self.course_pk)
        super().mousePressEvent(event)


class NewCourseDialog(QDialog):
    """Streamlined dialog for creating a new course."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Course")
        self.setMinimumSize(700, 520)
        self.setMaximumSize(700, 520)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup modern dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Header
        header_label = QLabel("📚 Create New Educational Course")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setStyleSheet("color: #f7fafc; margin-bottom: 10px;")
        layout.addWidget(header_label)
        
        # Form fields with modern styling
        form_style = """
            QLineEdit, QTextEdit {
                background-color: #374151;
                color: #e2e8f0;
                border: 2px solid #4a5568;
                border-radius: 8px;
                padding: 12px;
                font-size: 11pt;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 2px solid #3182ce;
            }
        """
        
        # Course name
        name_label = QLabel("Course Title *")
        name_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11pt;")
        layout.addWidget(name_label)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Advanced MRI Shoulder Pathology")
        self.name_input.setStyleSheet(form_style)
        layout.addWidget(self.name_input)
        
        # Author name
        author_label = QLabel("Instructor Name *")
        author_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11pt;")
        layout.addWidget(author_label)
        
        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("e.g., Dr. Sarah Johnson, MD")
        self.author_input.setStyleSheet(form_style)
        layout.addWidget(self.author_input)
        
        # Description
        desc_label = QLabel("Course Description")
        desc_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11pt;")
        layout.addWidget(desc_label)
        
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("Brief overview of the course content and learning objectives...")
        self.desc_input.setFixedHeight(80)
        self.desc_input.setStyleSheet(form_style)
        layout.addWidget(self.desc_input)
        
        layout.addStretch()
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(42)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 25px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #6b7280;
            }
        """)
        buttons_layout.addWidget(cancel_btn)
        
        create_btn = QPushButton("✓ Create Course")
        create_btn.setFixedHeight(42)
        create_btn.clicked.connect(self.accept)
        create_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 25px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
        """)
        buttons_layout.addWidget(create_btn)
        
        layout.addLayout(buttons_layout)
        
        # Dialog styling
        self.setStyleSheet("""
            QDialog {
                background-color: #1a202c;
            }
        """)
    
    def get_course_data(self):
        """Return the entered course data."""
        return {
            'name': self.name_input.text().strip(),
            'author': self.author_input.text().strip(),
            'description': self.desc_input.toPlainText().strip(),
            'outline': ''
        }


class EducationMainWidget(QWidget):
    """Main education interface with modern card-grid layout."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setup_ui()
        self.load_courses()
    
    def setup_ui(self):
        """Setup optimized modern UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(20)
        
        # Header section
        header_layout = QHBoxLayout()
        header_layout.setSpacing(15)
        
        # Title and subtitle
        title_container = QVBoxLayout()
        title_container.setSpacing(5)
        
        title_label = QLabel("📚 Educational Courses")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #f7fafc;")
        title_container.addWidget(title_label)
        
        subtitle_label = QLabel("Create and manage radiology teaching presentations")
        subtitle_label.setStyleSheet("color: #a0aec0; font-size: 11pt;")
        title_container.addWidget(subtitle_label)
        
        header_layout.addLayout(title_container)
        header_layout.addStretch()
        
        # New course button
        self.new_course_btn = QPushButton("+ New Course")
        self.new_course_btn.setFixedHeight(45)
        self.new_course_btn.clicked.connect(self.create_new_course)
        self.new_course_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 0 30px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
        """)
        header_layout.addWidget(self.new_course_btn)
        
        layout.addLayout(header_layout)
        
        # Course cards scroll area with grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2d3748;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #4a5568;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6b7280;
            }
        """)
        
        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setSpacing(20)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll)
        
        # Empty state
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        
        empty_icon = QLabel("📚")
        empty_icon_font = QFont()
        empty_icon_font.setPointSize(72)
        empty_icon.setFont(empty_icon_font)
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setStyleSheet("color: #4a5568;")
        empty_layout.addWidget(empty_icon)
        
        empty_text = QLabel("No courses yet")
        empty_text_font = QFont()
        empty_text_font.setPointSize(18)
        empty_text_font.setBold(True)
        empty_text.setFont(empty_text_font)
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setStyleSheet("color: #6b7280; margin-top: 20px;")
        empty_layout.addWidget(empty_text)
        
        empty_subtext = QLabel("Create your first educational course to get started")
        empty_subtext.setAlignment(Qt.AlignCenter)
        empty_subtext.setStyleSheet("color: #4a5568; font-size: 12pt; margin-top: 10px;")
        empty_layout.addWidget(empty_subtext)
        
        self.empty_state.hide()
        layout.addWidget(self.empty_state)
        
        # Widget styling
        self.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
            }
        """)
    
    def load_courses(self):
        """Load and display courses in grid layout - OPTIMIZED."""
        # Clear existing cards
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Load courses from database
        courses = get_all_courses()
        
        if not courses:
            self.empty_state.show()
            self.scroll_content.hide()
        else:
            self.empty_state.hide()
            self.scroll_content.show()
            
            # Add cards to grid (3 columns)
            row, col = 0, 0
            for course in courses:
                card = CourseCardWidget(course)
                card.edit_clicked.connect(self.edit_course)
                card.present_clicked.connect(self.present_course)
                card.delete_clicked.connect(self.delete_course)
                
                self.grid_layout.addWidget(card, row, col)
                
                col += 1
                if col >= 3:  # 3 cards per row
                    col = 0
                    row += 1
    
    def create_new_course(self):
        """Open dialog to create a new course."""
        dialog = NewCourseDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_course_data()
            
            if not data['name']:
                QMessageBox.warning(self, "Required Field", "Please enter a course title.")
                return
            
            if not data['author']:
                QMessageBox.warning(self, "Required Field", "Please enter an instructor name.")
                return
            
            # Create course in database
            from PacsClient.pacs.education.course_database import insert_course
            
            try:
                course_pk = insert_course(
                    name=data['name'],
                    description=data['description'],
                    author=data['author'],
                    outline=data['outline']
                )
                
                self.load_courses()
                self.edit_course(course_pk)
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create course: {str(e)}")
    
    def edit_course(self, course_pk):
        """Open course editor."""
        try:
            from PacsClient.pacs.education.course_editor_widget import CourseEditorWidget
            
            editor = CourseEditorWidget(course_pk, parent=self)
            editor.course_saved.connect(self.load_courses)
            editor.setWindowTitle("Course Editor")
            editor.showMaximized()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open editor: {str(e)}")
    
    def present_course(self, course_pk):
        """Start presentation mode for a course."""
        try:
            from PacsClient.pacs.education.presentation_viewer_widget import PresentationViewerWidget
            
            course = get_course_with_slides(course_pk)
            
            if not course or not course.get('slides'):
                QMessageBox.warning(self, "No Slides", "This course has no slides to present.")
                return
            
            viewer = PresentationViewerWidget(course)
            viewer.showFullScreen()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start presentation: {str(e)}")
    
    def delete_course(self, course_pk):
        """Delete a course after confirmation."""
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this course?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                delete_course(course_pk)
                self.load_courses()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete course: {str(e)}")
