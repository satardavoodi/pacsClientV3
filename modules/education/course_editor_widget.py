"""Course editor widget with slide management."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QListWidget, QListWidgetItem, QMessageBox, QFrame,
    QSplitter, QDialog, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QFont, QIcon

from modules.education.course_database import (
    get_course_by_pk, update_course, get_slides_for_course,
    insert_slide, update_slide, delete_slide, reorder_slides
)
from modules.education.slide_editor_widget import SlideEditorWidget


class SlideListItem(QWidget):
    """Custom widget for slide list item."""
    
    clicked = Signal(int)  # slide_pk
    delete_clicked = Signal(int)
    
    def __init__(self, slide_data, slide_number, parent=None):
        super().__init__(parent)
        self.slide_pk = slide_data['slide_pk']
        self.slide_number = slide_number
        self.setup_ui(slide_data)
    
    def setup_ui(self, slide_data):
        """Setup slide item UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # Slide number
        number_label = QLabel(f"Slide {self.slide_number}")
        number_font = QFont()
        number_font.setBold(True)
        number_label.setFont(number_font)
        number_label.setStyleSheet("color: #3182ce;")
        layout.addWidget(number_label)
        
        # Slide title
        title = slide_data.get('slide_title', 'Untitled Slide')
        title_label = QLabel(title if title else 'Untitled Slide')
        title_label.setStyleSheet("color: #e2e8f0;")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        
        # Delete button
        delete_btn = QPushButton("🗑️")
        delete_btn.setFixedSize(30, 30)
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.slide_pk))
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #e53e3e;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c53030;
            }
        """)
        layout.addWidget(delete_btn, alignment=Qt.AlignRight)
        
        self.setStyleSheet("""
            SlideListItem {
                background-color: #2d3748;
                border-radius: 8px;
                border: 2px solid #4a5568;
            }
            SlideListItem:hover {
                border: 2px solid #3182ce;
            }
        """)
        
        self.setFixedHeight(120)
        self.setCursor(Qt.PointingHandCursor)
    
    def mousePressEvent(self, event):
        """Handle click."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.slide_pk)
        super().mousePressEvent(event)
    
    def set_selected(self, selected):
        """Set selection state."""
        if selected:
            self.setStyleSheet("""
                SlideListItem {
                    background-color: #374151;
                    border-radius: 8px;
                    border: 3px solid #3182ce;
                }
            """)
        else:
            self.setStyleSheet("""
                SlideListItem {
                    background-color: #2d3748;
                    border-radius: 8px;
                    border: 2px solid #4a5568;
                }
                SlideListItem:hover {
                    border: 2px solid #3182ce;
                }
            """)


class NewSlideDialog(QDialog):
    """Dialog for creating a new slide."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Slide")
        self.setMinimumSize(500, 300)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title input
        title_label = QLabel("Slide Title:")
        title_label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        layout.addWidget(title_label)
        
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Enter slide title...")
        self.title_input.setStyleSheet("""
            QLineEdit {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 8px;
                font-size: 11pt;
            }
        """)
        layout.addWidget(self.title_input)
        
        # Notes input
        notes_label = QLabel("Speaker Notes (optional):")
        notes_label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        layout.addWidget(notes_label)
        
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Enter speaker notes...")
        self.notes_input.setMaximumHeight(100)
        self.notes_input.setStyleSheet("""
            QTextEdit {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 8px;
                font-size: 11pt;
            }
        """)
        layout.addWidget(self.notes_input)
        
        layout.addStretch()
        
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
        
        create_btn = QPushButton("Create Slide")
        create_btn.setFixedSize(120, 35)
        create_btn.clicked.connect(self.accept)
        create_btn.setStyleSheet("""
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
        """)
        buttons_layout.addWidget(create_btn)
        
        layout.addLayout(buttons_layout)
    
    def get_slide_data(self):
        """Get entered slide data."""
        return {
            'title': self.title_input.text().strip(),
            'notes': self.notes_input.toPlainText().strip()
        }


class CourseEditorWidget(QWidget):
    """Main course editor with slide list and content editor."""
    
    course_saved = Signal()
    
    def __init__(self, course_pk, parent=None):
        super().__init__(parent)
        self.course_pk = course_pk
        self.current_slide_pk = None
        self.slide_widgets = {}  # Cache slide editors
        self.load_course()
        self.setup_ui()
        self.load_slides()
    
    def load_course(self):
        """Load course data from database."""
        self.course_data = get_course_by_pk(self.course_pk)
        if not self.course_data:
            QMessageBox.critical(self, "Error", "Course not found!")
            self.close()
    
    def setup_ui(self):
        """Setup the course editor UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Top bar with course info and save button
        top_bar = QWidget()
        top_bar.setFixedHeight(70)
        top_bar.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
                border-bottom: 2px solid #4a5568;
            }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 10, 20, 10)
        
        # Course title
        course_title = QLabel(f"Editing: {self.course_data['course_name']}")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        course_title.setFont(title_font)
        course_title.setStyleSheet("color: #e2e8f0;")
        top_layout.addWidget(course_title)
        
        top_layout.addStretch()
        
        # Save button
        save_btn = QPushButton("💾 Save Course")
        save_btn.setFixedHeight(45)
        save_btn.clicked.connect(self.save_course)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #38a169;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #2f855a;
            }
        """)
        top_layout.addWidget(save_btn)
        
        # Close button
        close_btn = QPushButton("✖ Close")
        close_btn.setFixedHeight(45)
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #e53e3e;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #c53030;
            }
        """)
        top_layout.addWidget(close_btn)
        
        layout.addWidget(top_bar)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #4a5568;
                width: 2px;
            }
        """)
        
        # Left panel: Slide list
        left_panel = QWidget()
        left_panel.setMinimumWidth(250)
        left_panel.setMaximumWidth(400)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(10)
        
        # Slide list header
        slides_header = QHBoxLayout()
        slides_label = QLabel("Slides")
        slides_font = QFont()
        slides_font.setPointSize(14)
        slides_font.setBold(True)
        slides_label.setFont(slides_font)
        slides_label.setStyleSheet("color: #e2e8f0;")
        slides_header.addWidget(slides_label)
        
        slides_header.addStretch()
        
        add_slide_btn = QPushButton("+ Add Slide")
        add_slide_btn.clicked.connect(self.add_new_slide)
        add_slide_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
        """)
        slides_header.addWidget(add_slide_btn)
        
        left_layout.addLayout(slides_header)
        
        # Slide list
        self.slide_list_widget = QWidget()
        self.slide_list_layout = QVBoxLayout(self.slide_list_widget)
        self.slide_list_layout.setSpacing(10)
        self.slide_list_layout.setContentsMargins(0, 0, 0, 0)
        self.slide_list_layout.addStretch()
        
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.slide_list_widget)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        left_layout.addWidget(scroll)
        
        splitter.addWidget(left_panel)
        
        # Right panel: Slide editor
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        # Slide title editor
        title_container = QWidget()
        title_container.setStyleSheet("""
            QWidget {
                background-color: #2d3748;
                border-radius: 8px;
            }
        """)
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(15, 15, 15, 15)
        
        title_label = QLabel("Slide Title:")
        title_label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        title_layout.addWidget(title_label)
        
        self.slide_title_input = QLineEdit()
        self.slide_title_input.setPlaceholderText("Enter slide title...")
        self.slide_title_input.textChanged.connect(self.on_title_changed)
        self.slide_title_input.setStyleSheet("""
            QLineEdit {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 10px;
                font-size: 12pt;
            }
        """)
        title_layout.addWidget(self.slide_title_input)
        
        right_layout.addWidget(title_container)
        
        # Slide content editor (stacked widget)
        self.editor_stack = QStackedWidget()
        
        # Empty state
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_label = QLabel("Select a slide from the left to edit its content")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("color: #a0aec0; font-size: 14pt;")
        empty_layout.addWidget(empty_label)
        self.editor_stack.addWidget(empty_widget)
        
        right_layout.addWidget(self.editor_stack, stretch=1)
        
        splitter.addWidget(right_panel)
        
        # Set initial sizes
        splitter.setSizes([300, 900])
        
        layout.addWidget(splitter)
        
        # Set background
        self.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
            }
        """)
    
    def load_slides(self):
        """Load slides from database."""
        # Clear existing
        while self.slide_list_layout.count() > 1:
            item = self.slide_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Load slides
        slides = get_slides_for_course(self.course_pk)
        
        for idx, slide in enumerate(slides):
            slide_item = SlideListItem(slide, idx + 1)
            slide_item.clicked.connect(self.select_slide)
            slide_item.delete_clicked.connect(self.delete_slide_confirm)
            self.slide_list_layout.insertWidget(idx, slide_item)
    
    def add_new_slide(self):
        """Add a new slide."""
        dialog = NewSlideDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_slide_data()
            
            try:
                # Get next slide order
                slides = get_slides_for_course(self.course_pk)
                next_order = len(slides) + 1
                
                slide_pk = insert_slide(
                    course_fk=self.course_pk,
                    slide_order=next_order,
                    title=data['title'],
                    notes=data['notes']
                )
                
                self.load_slides()
                self.select_slide(slide_pk)
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create slide: {str(e)}")
    
    def select_slide(self, slide_pk):
        """Select and display a slide for editing."""
        self.current_slide_pk = slide_pk
        
        # Update selection visuals
        for i in range(self.slide_list_layout.count() - 1):
            item = self.slide_list_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, 'slide_pk'):
                    widget.set_selected(widget.slide_pk == slide_pk)
        
        # Get or create slide editor
        if slide_pk not in self.slide_widgets:
            editor = SlideEditorWidget(slide_pk, self.course_pk)
            editor.content_changed.connect(self.on_content_changed)
            self.editor_stack.addWidget(editor)
            self.slide_widgets[slide_pk] = editor
        
        # Show editor
        self.editor_stack.setCurrentWidget(self.slide_widgets[slide_pk])
        
        # Load slide title
        from modules.education.course_database import get_slide_by_pk
        slide = get_slide_by_pk(slide_pk)
        if slide:
            self.slide_title_input.blockSignals(True)
            self.slide_title_input.setText(slide.get('slide_title', ''))
            self.slide_title_input.blockSignals(False)
    
    def on_title_changed(self, text):
        """Handle slide title change.

        Each keystroke must persist the title, but rebuilding the slide
        sidebar on every keystroke (the old behavior) discarded the visual
        selection of the currently-edited slide and caused flicker. Persist
        immediately, then debounce the sidebar refresh and re-apply the
        selection on rebuild.
        """
        if not self.current_slide_pk:
            return
        try:
            update_slide(self.current_slide_pk, title=text)
        except Exception as e:
            print(f"Error updating title: {e}")
            return

        if not hasattr(self, '_title_refresh_timer') or self._title_refresh_timer is None:
            self._title_refresh_timer = QTimer(self)
            self._title_refresh_timer.setSingleShot(True)
            self._title_refresh_timer.timeout.connect(self._refresh_slide_list_preserve_selection)
        self._title_refresh_timer.stop()
        self._title_refresh_timer.start(400)

    def _refresh_slide_list_preserve_selection(self):
        """Rebuild the slide sidebar but keep the visual selection on the active slide."""
        active_pk = self.current_slide_pk
        self.load_slides()
        if active_pk is None:
            return
        for i in range(self.slide_list_layout.count() - 1):
            item = self.slide_list_layout.itemAt(i)
            widget = item.widget() if item else None
            if widget is not None and hasattr(widget, 'slide_pk') and hasattr(widget, 'set_selected'):
                widget.set_selected(widget.slide_pk == active_pk)
    
    def on_content_changed(self):
        """Handle content changes."""
        # Could implement auto-save or change tracking here
        pass
    
    def delete_slide_confirm(self, slide_pk):
        """Confirm and delete a slide."""
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete this slide?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                delete_slide(slide_pk)
                
                # Remove from cache
                if slide_pk in self.slide_widgets:
                    widget = self.slide_widgets.pop(slide_pk)
                    self.editor_stack.removeWidget(widget)
                    widget.deleteLater()
                
                # Reset if this was selected
                if self.current_slide_pk == slide_pk:
                    self.current_slide_pk = None
                    self.editor_stack.setCurrentIndex(0)
                
                self.load_slides()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete slide: {str(e)}")
    
    def save_course(self):
        """Save course changes."""
        try:
            # Course data is auto-saved as changes are made
            # This is more of a confirmation
            QMessageBox.information(self, "Success", "Course saved successfully!")
            self.course_saved.emit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save course: {str(e)}")
