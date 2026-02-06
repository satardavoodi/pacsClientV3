"""
Redesigned Education Module with Modern UI/UX
Three tabs: Library | My Courses | Build Course
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QTabWidget, QComboBox, QScrollArea,
    QFrame, QGridLayout, QSpacerItem, QSizePolicy, QCheckBox,
    QGroupBox, QTreeWidget, QTreeWidgetItem, QMessageBox, QDialog,
    QProgressBar
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QIcon

import json
from pathlib import Path
from typing import List, Dict, Any

from PacsClient.pacs.education.course_database import (
    get_all_courses, search_and_filter_courses, insert_course,
    delete_course, get_course_with_slides, update_course
)


# ==================== CONSTANTS ====================

MODALITIES = ["CT", "MRI", "US", "X-Ray", "PET", "SPECT", "Mammography", "Fluoroscopy"]
BODY_REGIONS = ["Head/Neck", "Chest", "Abdomen", "Pelvis", "MSK", "Spine", "Vascular", "Cardiac"]
LEVELS = ["Basic", "Intermediate", "Advanced", "Expert"]
COMMON_TAGS = [
    "Anatomy", "Pathology", "Trauma", "Oncology", "Pediatric", 
    "Emergency", "Intervention", "Physics", "Protocol", "Artifacts"
]


# ==================== FILTER PANEL ====================

class FilterPanel(QFrame):
    """Left sidebar filter panel for Library."""
    
    filters_changed = Signal(dict)  # Emits filter dict when changed
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.active_filters = {
            'modality': [],
            'body_regions': [],
            'level': None,
            'tags': []
        }
    
    def setup_ui(self):
        """Setup filter panel UI - Professional clinical style."""
        self.setFixedWidth(380)  # Wide enough to prevent any text overlap
        self.setStyleSheet("""
            QFrame {
                background-color: #0f1419;
                border-right: 1px solid #1e2530;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 24, 18, 24)  # More horizontal padding
        layout.setSpacing(28)  # Reduced slightly for better fit
        
        # Title - Desktop readable
        title = QLabel("Filters")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f7fafc; border: none; margin-bottom: 16px; padding: 0;")
        layout.addWidget(title)
        
        layout.addSpacing(8)  # More space after title
        
        # Modality filter
        self.add_filter_group(layout, "Modality", MODALITIES, 'modality')
        
        # Body Region filter
        self.add_filter_group(layout, "Body Region", BODY_REGIONS, 'body_regions')
        
        # Level filter (single select)
        level_group = QGroupBox("Difficulty Level")
        level_group.setStyleSheet("""
            QGroupBox {
                color: #f0f4f8;
                border: none;
                font-size: 13pt;
                font-weight: 600;
                padding-top: 12px;
                margin-bottom: 12px;
            }
            QGroupBox::title {
                padding: 0 0 12px 0;
                subcontrol-position: top left;
                subcontrol-origin: margin;
            }
        """)
        level_layout = QVBoxLayout()
        level_layout.setSpacing(12)  # More space between label and combo
        level_layout.setContentsMargins(0, 16, 0, 8)  # More space after group title
        
        self.level_combo = QComboBox()
        self.level_combo.addItem("All Levels", None)
        for level in LEVELS:
            self.level_combo.addItem(level, level)
        self.level_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 9px 12px;
                font-size: 13pt;
                min-height: 40px;
            }
            QComboBox:hover {
                border-color: #4d7aa0;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                width: 14px;
                height: 14px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a202c;
                color: #f0f4f8;
                font-size: 13pt;
                selection-background-color: #3d7a9f;
                border: 1px solid #4d7aa0;
                outline: none;
                padding: 6px;
            }
        """)
        self.level_combo.currentIndexChanged.connect(self.on_level_changed)
        level_layout.addWidget(self.level_combo)
        level_group.setLayout(level_layout)
        layout.addWidget(level_group)
        
        # Tags filter
        self.add_filter_group(layout, "Tags", COMMON_TAGS[:6], 'tags')  # Show first 6 tags
        
        layout.addStretch()
        
        # Clear filters button - professional outline style
        clear_btn = QPushButton("Clear Filters")
        clear_btn.setFixedHeight(44)
        clear_btn.setMinimumWidth(200)  # Ensure button is wide enough
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 11px 18px;
                font-size: 12pt;
            }
            QPushButton:hover {
                border-color: #4d7aa0;
                color: #e2e8f0;
                background-color: rgba(61, 122, 159, 0.08);
            }
        """)
        clear_btn.clicked.connect(self.clear_filters)
        layout.addWidget(clear_btn)
    
    def add_filter_group(self, parent_layout, title, items, filter_key):
        """Add a checkbox filter group."""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                color: #f0f4f8;
                border: none;
                font-size: 13pt;
                font-weight: 600;
                padding: 16px 0 20px 0;
                margin: 0;
            }
            QGroupBox::title {
                padding: 0 0 14px 0;
                subcontrol-position: top left;
                subcontrol-origin: margin;
            }
        """)
        
        group_layout = QVBoxLayout()
        group_layout.setSpacing(4)  # Tight spacing since checkboxes have their own margin
        group_layout.setContentsMargins(0, 18, 0, 10)  # More space after group title and bottom padding
        
        checkboxes = []
        for item in items:
            cb = QCheckBox(item)
            cb.setMinimumHeight(32)  # Ensure enough vertical space
            cb.setStyleSheet("""
                QCheckBox {
                    color: #e2e8f0;
                    spacing: 12px;
                    font-size: 12pt;
                    padding: 5px 0;
                    min-height: 28px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 1px solid #4d6a8f;
                    border-radius: 2px;
                    background-color: #0d1117;
                }
                QCheckBox::indicator:hover {
                    border-color: #5d9abf;
                }
                QCheckBox::indicator:checked {
                    background-color: #3d7a9f;
                    border-color: #4d8aaf;
                    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTAgM0w0LjUgOC41TDIgNiIgc3Ryb2tlPSIjZjBmNGY4IiBzdHJva2Utd2lkdGg9IjIuNSIgZmlsbD0ibm9uZSIvPjwvc3ZnPg==);
                }
            """)
            cb.stateChanged.connect(lambda state, key=filter_key, val=item: self.on_filter_changed(key, val, state))
            checkboxes.append(cb)
            group_layout.addWidget(cb)
        
        group.setLayout(group_layout)
        parent_layout.addWidget(group)
        
        # Store checkboxes for clearing
        setattr(self, f'{filter_key}_checkboxes', checkboxes)
    
    def on_filter_changed(self, filter_key, value, state):
        """Handle filter checkbox change."""
        if state == Qt.Checked:
            if value not in self.active_filters[filter_key]:
                self.active_filters[filter_key].append(value)
        else:
            if value in self.active_filters[filter_key]:
                self.active_filters[filter_key].remove(value)
        
        self.filters_changed.emit(self.active_filters)
    
    def on_level_changed(self, index):
        """Handle level combo change."""
        self.active_filters['level'] = self.level_combo.currentData()
        self.filters_changed.emit(self.active_filters)
    
    def clear_filters(self):
        """Clear all filters."""
        # Clear checkboxes
        for filter_key in ['modality', 'body_regions', 'tags']:
            checkboxes = getattr(self, f'{filter_key}_checkboxes', [])
            for cb in checkboxes:
                cb.setChecked(False)
            self.active_filters[filter_key] = []
        
        # Clear level
        self.level_combo.setCurrentIndex(0)
        self.active_filters['level'] = None
        
        self.filters_changed.emit(self.active_filters)


# ==================== COURSE CARD ====================

class ModernCourseCard(QFrame):
    """Compact modern course card for grid layout."""
    
    clicked = Signal(dict)  # course_data
    action_requested = Signal(str, dict)  # (action, course_data)
    
    def __init__(self, course_data, show_actions=True, parent=None):
        super().__init__(parent)
        self.course_data = course_data
        self.show_actions = show_actions
        self.is_selected = False
        self.setup_ui()
    
    def setup_ui(self):
        """Setup professional clinical card UI."""
        self.setFixedSize(280, 140)
        self.setCursor(Qt.PointingHandCursor)
        
        # Base card style
        self.update_style()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header - clean, minimal
        header = QFrame()
        header.setFixedHeight(48)
        modality_color = self.get_modality_color(self.course_data.get('modality', ''))
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {modality_color};
                border: none;
            }}
        """)
        
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # Modality badge
        modality = self.course_data.get('modality', 'N/A')
        level = self.course_data.get('level', 'Intermediate')
        
        modality_label = QLabel(modality)
        modality_label.setStyleSheet("""
            QLabel {
                color: #f0f4f8;
                font-size: 13pt;
                font-weight: 600;
                padding: 5px 10px;
                background-color: rgba(0, 0, 0, 0.2);
                border-radius: 2px;
            }
        """)
        header_layout.addWidget(modality_label)
        
        header_layout.addStretch()
        
        # Level badge
        level_label = QLabel(level)
        level_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 11pt;
                padding: 3px 8px;
                background-color: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }
        """)
        header_layout.addWidget(level_label)
        
        layout.addWidget(header)
        
        # Content area - professional clinical styling
        content = QFrame()
        content.setStyleSheet("QFrame { background-color: transparent; border: none; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 10, 12, 10)
        content_layout.setSpacing(6)  # Better vertical spacing
        
        # Title - main focus
        title = QLabel(self.course_data['course_name'])
        title_font = QFont()
        title_font.setPointSize(12)  # Increased for better readability
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f0f4f8;")  # Higher contrast
        title.setWordWrap(True)
        title.setMaximumHeight(42)
        content_layout.addWidget(title)
        
        # Metadata row - author + tags
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)
        
        author_text = self.course_data.get('author_name', 'Unknown')
        if len(author_text) > 18:
            author_text = author_text[:18] + "..."
        
        author = QLabel(author_text)
        author.setStyleSheet("color: #8892a0; font-size: 11pt;")  # Improved contrast and size
        meta_layout.addWidget(author)
        
        # Tags (up to 3, inline, minimal)
        tags = self.course_data.get('tags', [])
        if tags:
            for tag in tags[:3]:
                tag_label = QLabel(tag)
                tag_label.setStyleSheet("""
                    QLabel {
                        color: #a8b2c0;
                        font-size: 10pt;
                        padding: 2px 6px;
                        background-color: rgba(255, 255, 255, 0.06);
                        border-radius: 2px;
                    }
                """)
                meta_layout.addWidget(tag_label)
        
        meta_layout.addStretch()
        content_layout.addLayout(meta_layout)
        
        content_layout.addStretch()
        
        # Action button - professional, minimal
        if self.show_actions:
            view_btn = QPushButton("Select")
            view_btn.setFixedHeight(28)
            view_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #7c9cbf;
                    border: 1px solid #2d5a7b;
                    border-radius: 2px;
                    font-size: 9pt;
                    padding: 4px 12px;
                }
                QPushButton:hover {
                    background-color: #1e3a5f;
                    border-color: #3d7a9f;
                    color: #9fc5e8;
                }
            """)
            view_btn.clicked.connect(lambda: self.action_requested.emit('view', self.course_data))
            content_layout.addWidget(view_btn)
        
        layout.addWidget(content)
    
    def get_modality_color(self, modality):
        """Get subtle, professional color based on modality."""
        colors = {
            'CT': '#1e3a5f',
            'MRI': '#1e3a5f',
            'US': '#1e4a3f',
            'X-Ray': '#3a2e1e',
            'PET': '#3a1e2e',
            'Mammography': '#2e1e3a',
            'SPECT': '#1e3a3a',
            'Fluoroscopy': '#3a3a1e',
        }
        return colors.get(modality, '#1e2530')
    
    def update_style(self):
        """Update professional card style based on selection."""
        if self.is_selected:
            self.setStyleSheet("""
                QFrame {
                    background-color: #1a2332;
                    border: 1px solid #3d7a9f;
                    border-radius: 2px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #1a2332;
                    border: 1px solid #1e2530;
                    border-radius: 2px;
                }
                QFrame:hover {
                    border-color: #2d5a7b;
                    background-color: #1e2837;
                }
            """)
    
    def set_selected(self, selected):
        """Set selection state."""
        self.is_selected = selected
        self.update_style()
    
    def mousePressEvent(self, event):
        """Handle click."""
        self.clicked.emit(self.course_data)
        super().mousePressEvent(event)


# ==================== COURSE DETAILS PANEL ====================

class CourseDetailsPanel(QFrame):
    """Right sidebar showing course details and syllabus."""
    
    action_requested = Signal(str, dict)  # (action, course_data)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_course = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup professional details panel UI."""
        self.setFixedWidth(340)
        self.setStyleSheet("""
            QFrame {
                background-color: #161b22;
                border-left: 1px solid #1e2530;
            }
        """)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)
        
        # Empty state
        self.show_empty_state()
    
    def show_empty_state(self):
        """Show empty state when no course selected."""
        self.clear_layout()
        
        empty_label = QLabel("Select a course to view details")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setStyleSheet("""
            QLabel {
                color: #8892a0;
                font-size: 14pt;
                border: none;
                padding: 20px;
            }
        """)
        empty_label.setWordWrap(True)
        
        self.main_layout.addStretch()
        self.main_layout.addWidget(empty_label)
        self.main_layout.addStretch()
    
    def show_course(self, course_data):
        """Show course details."""
        self.current_course = course_data
        self.clear_layout()
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(20)  # Increased section spacing: 18-22px
        
        # Title
        title = QLabel(course_data['course_name'])
        title_font = QFont()
        title_font.setPointSize(16)  # Larger for readability
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f7fafc; border: none; padding-bottom: 4px;")
        title.setWordWrap(True)
        layout.addWidget(title)
        
        # Author
        author = QLabel(f"👤 {course_data.get('author_name', 'Unknown')}")
        author.setStyleSheet("color: #a8b2c0; font-size: 13pt; border: none; padding: 4px 0;")
        layout.addWidget(author)
        
        # Metadata row
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(12)
        if course_data.get('modality'):
            modality_label = QLabel(f"📡 {course_data['modality']}")
            modality_label.setStyleSheet("color: #cbd5e0; font-size: 12pt; border: none;")
            meta_layout.addWidget(modality_label)
        
        if course_data.get('level'):
            level_label = QLabel(f"📊 {course_data['level']}")
            level_label.setStyleSheet("color: #cbd5e0; font-size: 12pt; border: none;")
            meta_layout.addWidget(level_label)
        meta_layout.addStretch()
        layout.addLayout(meta_layout)
        
        # Description
        if course_data.get('course_description'):
            layout.addSpacing(8)  # Section spacing
            desc_label = QLabel("Description")
            desc_label.setStyleSheet("color: #f0f4f8; font-weight: 600; font-size: 14pt; border: none; padding-bottom: 6px;")
            layout.addWidget(desc_label)
            
            desc = QLabel(course_data['course_description'])
            desc.setStyleSheet("color: #cbd5e0; font-size: 13pt; border: none; line-height: 1.5;")
            desc.setWordWrap(True)
            layout.addWidget(desc)
        
        # Tags
        tags = course_data.get('tags', [])
        if tags:
            layout.addSpacing(8)  # Section spacing
            tags_label = QLabel("Tags")
            tags_label.setStyleSheet("color: #f0f4f8; font-weight: 600; font-size: 14pt; border: none; padding-bottom: 6px;")
            layout.addWidget(tags_label)
            
            tags_container = QWidget()
            tags_layout = QHBoxLayout(tags_container)
            tags_layout.setContentsMargins(0, 0, 0, 0)
            tags_layout.setSpacing(8)
            
            for tag in tags[:4]:  # Show up to 4 tags
                tag_label = QLabel(tag)
                tag_label.setStyleSheet("""
                    QLabel {
                        background-color: #3d5a80;
                        color: #e2e8f0;
                        border-radius: 2px;
                        padding: 6px 10px;
                        font-size: 12pt;
                    }
                """)
                tags_layout.addWidget(tag_label)
            
            tags_layout.addStretch()
            layout.addWidget(tags_container)
        
        # Syllabus/Content structure
        layout.addWidget(QLabel("Course Content"))
        
        # Get slides count
        course_with_slides = get_course_with_slides(course_data['course_pk'])
        slides_count = len(course_with_slides.get('slides', []))
        
        content_tree = QTreeWidget()
        content_tree.setHeaderHidden(True)
        content_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 6px;
            }
            QTreeWidget::item {
                padding: 6px;
            }
            QTreeWidget::item:selected {
                background-color: #3182ce;
            }
        """)
        
        # Add content structure
        root = QTreeWidgetItem(content_tree)
        root.setText(0, f"📚 {slides_count} Slides")
        
        layout.addWidget(content_tree)
        
        layout.addStretch()
        
        # Action buttons
        actions_container = QWidget()
        actions_layout = QVBoxLayout(actions_container)
        actions_layout.setSpacing(10)
        
        # Primary action - professional style
        open_btn = QPushButton("Open Course")
        open_btn.setFixedHeight(44)
        open_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 14pt;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #3d7a9f;
                border-color: #4d8aaf;
            }
        """)
        open_btn.clicked.connect(lambda: self.action_requested.emit('open', self.current_course))
        actions_layout.addWidget(open_btn)
        
        # Secondary actions - outline style
        edit_btn = QPushButton("Edit Course")
        edit_btn.setFixedHeight(38)
        edit_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                font-size: 13pt;
            }
            QPushButton:hover {
                border-color: #4d7aa0;
                color: #cbd5e0;
            }
        """)
        edit_btn.clicked.connect(lambda: self.action_requested.emit('edit', self.current_course))
        actions_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("Delete Course")
        delete_btn.setFixedHeight(38)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                font-size: 13pt;
            }
            QPushButton:hover {
                border-color: #8a4d4d;
                color: #e0b0b0;
                background-color: rgba(120, 50, 50, 0.12);
            }
        """)
        delete_btn.clicked.connect(lambda: self.action_requested.emit('delete', self.current_course))
        actions_layout.addWidget(delete_btn)
        
        layout.addWidget(actions_container)
        
        scroll.setWidget(content)
        self.main_layout.addWidget(scroll)
    
    def clear_layout(self):
        """Clear all widgets from layout."""
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


# ==================== LIBRARY PAGE ====================

class LibraryPage(QWidget):
    """Library tab with filters, course grid, and details panel."""
    
    course_opened = Signal(dict)
    course_edited = Signal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_courses = []
        self.filtered_courses = []
        self.current_search = ""
        self.current_filters = {}
        self.selected_card = None
        self.setup_ui()
        self.load_courses()
    
    def setup_ui(self):
        """Setup three-column layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Left: Filters
        self.filter_panel = FilterPanel()
        self.filter_panel.filters_changed.connect(self.on_filters_changed)
        layout.addWidget(self.filter_panel)
        
        # Center: Course grid
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(20, 20, 20, 20)
        center_layout.setSpacing(15)
        
        # Search bar
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search courses, tags, modality...")
        self.search_input.setFixedHeight(48)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 16px;
                font-size: 15pt;
            }
            QLineEdit::placeholder {
                color: #6b7280;
                font-size: 13pt;
            }
            QLineEdit:focus {
                border: 1px solid #4d8aaf;
                background-color: #161b22;
            }
        """)
        self.search_input.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_input)
        
        center_layout.addWidget(search_container)
        
        # Results count
        self.results_label = QLabel("0 courses")
        self.results_label.setStyleSheet("color: #a8b2c0; font-size: 13pt; padding: 4px 0;")
        center_layout.addWidget(self.results_label)
        
        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(20)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll.setWidget(self.grid_container)
        center_layout.addWidget(scroll)
        
        layout.addWidget(center_widget, stretch=1)
        
        # Right: Details panel
        self.details_panel = CourseDetailsPanel()
        self.details_panel.action_requested.connect(self.on_detail_action)
        layout.addWidget(self.details_panel)
    
    def load_courses(self):
        """Load all courses (library shows all courses)."""
        self.all_courses = get_all_courses()
        self.apply_filters()
    
    def on_search_changed(self, text):
        """Handle search text change."""
        self.current_search = text
        # Debounce search
        if hasattr(self, 'search_timer'):
            self.search_timer.stop()
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.apply_filters)
        self.search_timer.start(300)  # 300ms debounce
    
    def on_filters_changed(self, filters):
        """Handle filter change."""
        self.current_filters = filters
        self.apply_filters()
    
    def apply_filters(self):
        """Apply search and filters to course list."""
        self.filtered_courses = search_and_filter_courses(
            query=self.current_search,
            modality=self.current_filters.get('modality'),
            body_regions=self.current_filters.get('body_regions'),
            level=self.current_filters.get('level'),
            tags=self.current_filters.get('tags')
        )
        
        self.update_grid()
        self.results_label.setText(f"{len(self.filtered_courses)} course{'s' if len(self.filtered_courses) != 1 else ''}")
    
    def update_grid(self):
        """Update course grid."""
        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.selected_card = None
        
        # Add course cards - professional grid
        cols = 4  # 4 cards per row (now more compact)
        for i, course in enumerate(self.filtered_courses):
            row = i // cols
            col = i % cols
            
            card = ModernCourseCard(course)
            card.clicked.connect(self.on_card_clicked)
            card.action_requested.connect(self.on_card_action)
            self.grid_layout.addWidget(card, row, col)
    
    def on_card_clicked(self, course_data):
        """Handle card click."""
        # Deselect previous
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, ModernCourseCard):
                widget.set_selected(False)
        
        # Select clicked card
        sender = self.sender()
        if isinstance(sender, ModernCourseCard):
            sender.set_selected(True)
            self.selected_card = sender
        
        # Update details panel
        self.details_panel.show_course(course_data)
    
    def on_card_action(self, action, course_data):
        """Handle card action button."""
        if action == 'view':
            self.details_panel.show_course(course_data)
            self.on_card_clicked(course_data)
    
    def on_detail_action(self, action, course_data):
        """Handle details panel action."""
        if action == 'open':
            self.course_opened.emit(course_data)
        elif action == 'edit':
            self.course_edited.emit(course_data)
        elif action == 'delete':
            reply = QMessageBox.question(
                self, "Delete Course",
                f"Are you sure you want to delete '{course_data['course_name']}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                delete_course(course_data['course_pk'])
                self.load_courses()
                self.details_panel.show_empty_state()


# ==================== MY COURSES PAGE ====================

class MyCoursesPage(QWidget):
    """My Courses tab with Created/Downloaded sections."""
    
    course_opened = Signal(dict)
    course_edited = Signal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_view = 'created'  # 'created' or 'downloaded'
        self.setup_ui()
        self.load_courses()
    
    def setup_ui(self):
        """Setup My Courses UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Header with toggle
        header_layout = QHBoxLayout()
        
        title = QLabel("My Courses")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #f7fafc;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # View toggle buttons
        self.created_btn = QPushButton("Created by Me")
        self.downloaded_btn = QPushButton("Downloaded")
        
        for btn in [self.created_btn, self.downloaded_btn]:
            btn.setFixedHeight(36)
            btn.setMinimumWidth(140)
            btn.setCursor(Qt.PointingHandCursor)
        
        self.created_btn.clicked.connect(lambda: self.switch_view('created'))
        self.downloaded_btn.clicked.connect(lambda: self.switch_view('downloaded'))
        
        header_layout.addWidget(self.created_btn)
        header_layout.addWidget(self.downloaded_btn)
        
        layout.addLayout(header_layout)
        
        # Course grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(20)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        scroll.setWidget(self.grid_container)
        layout.addWidget(scroll)
        
        # Set initial view
        self.switch_view('created')
    
    def switch_view(self, view):
        """Switch between created/downloaded views."""
        self.current_view = view
        
        # Update button styles
        active_style = """
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }
        """
        inactive_style = """
            QPushButton {
                background-color: transparent;
                color: #cbd5e0;
                border: 1px solid #4a5568;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2d3748;
            }
        """
        
        self.created_btn.setStyleSheet(active_style if view == 'created' else inactive_style)
        self.downloaded_btn.setStyleSheet(active_style if view == 'downloaded' else inactive_style)
        
        self.load_courses()
    
    def load_courses(self):
        """Load courses based on current view."""
        if self.current_view == 'created':
            courses = search_and_filter_courses(is_my_course=True)
        else:
            # For downloaded, we could add another filter
            courses = []  # Placeholder
        
        self.update_grid(courses)
    
    def update_grid(self, courses):
        """Update course grid."""
        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Show empty state if no courses
        if not courses:
            empty_label = QLabel("No courses yet" if self.current_view == 'created' else "No downloaded courses")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("color: #718096; font-size: 12pt;")
            self.grid_layout.addWidget(empty_label, 0, 0, 1, 4)
            return
        
        # Add course cards
        cols = 4  # 4 cards per row
        for i, course in enumerate(courses):
            row = i // cols
            col = i % cols
            
            card = ModernCourseCard(course)
            card.clicked.connect(lambda c=course: self.course_opened.emit(c))
            card.action_requested.connect(self.on_card_action)
            self.grid_layout.addWidget(card, row, col)
    
    def on_card_action(self, action, course_data):
        """Handle card actions."""
        if action == 'view':
            self.course_opened.emit(course_data)


# ==================== BUILD COURSE PAGE ====================

class BuildCoursePage(QWidget):
    """Build Course tab with form for creating new courses."""
    
    course_created = Signal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup build course form."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(20)
        
        # Title - Page title size: 22-24px
        title = QLabel("Create New Course")
        title_font = QFont()
        title_font.setPointSize(23)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f7fafc; padding-bottom: 12px;")
        layout.addWidget(title)
        
        # Form container (centered, max width)
        form_container = QWidget()
        form_container.setMaximumWidth(700)
        form_layout = QVBoxLayout(form_container)
        form_layout.setSpacing(20)
        
        # Professional form field styling
        field_style = """
            QLineEdit, QTextEdit, QComboBox {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #1e2530;
                border-radius: 2px;
                padding: 10px 12px;
                font-size: 10pt;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 1px solid #3d7a9f;
                background-color: #161b22;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #6b7280;
            }
            QComboBox QAbstractItemView {
                background-color: #1a202c;
                color: #cbd5e0;
                selection-background-color: #2d5a7b;
                border: 1px solid #2d3748;
            }
        """
        
        label_style = "color: #e2e8f0; font-weight: bold; font-size: 11pt;"
        
        # Course Title *
        title_label = QLabel("Course Title *")
        title_label.setStyleSheet(label_style)
        form_layout.addWidget(title_label)
        
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("e.g., Advanced Shoulder MRI")
        self.title_input.setStyleSheet(field_style)
        self.title_input.setMinimumHeight(48)
        form_layout.addWidget(self.title_input)
        
        # Author Name *
        author_label = QLabel("Instructor Name *")
        author_label.setStyleSheet(label_style)
        form_layout.addWidget(author_label)
        
        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("e.g., Dr. Smith")
        self.author_input.setStyleSheet(field_style)
        self.author_input.setMinimumHeight(48)
        form_layout.addWidget(self.author_input)
        
        # Description
        desc_label = QLabel("Description")
        desc_label.setStyleSheet(label_style)
        form_layout.addWidget(desc_label)
        
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("Brief overview of course content...")
        self.desc_input.setFixedHeight(120)
        self.desc_input.setStyleSheet(field_style)
        form_layout.addWidget(self.desc_input)
        
        # Row: Modality + Level
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(24)
        
        # Modality
        modality_container = QWidget()
        modality_layout = QVBoxLayout(modality_container)
        modality_layout.setContentsMargins(0, 0, 0, 0)
        modality_layout.setSpacing(8)  # Label to input: 6-8px
        modality_label = QLabel("Modality")
        modality_label.setStyleSheet(label_style)
        modality_layout.addWidget(modality_label)
        
        self.modality_combo = QComboBox()
        self.modality_combo.addItems(MODALITIES)
        self.modality_combo.setStyleSheet(field_style)
        self.modality_combo.setMinimumHeight(56)
        modality_layout.addWidget(self.modality_combo)
        
        row1_layout.addWidget(modality_container)
        
        # Level
        level_container = QWidget()
        level_layout = QVBoxLayout(level_container)
        level_layout.setContentsMargins(0, 0, 0, 0)
        level_layout.setSpacing(8)  # Label to input: 6-8px
        level_label = QLabel("Difficulty Level")
        level_label.setStyleSheet(label_style)
        level_layout.addWidget(level_label)
        
        self.level_combo = QComboBox()
        self.level_combo.addItems(LEVELS)
        self.level_combo.setCurrentText("Intermediate")
        self.level_combo.setStyleSheet(field_style)
        self.level_combo.setMinimumHeight(56)
        level_layout.addWidget(self.level_combo)
        
        row1_layout.addWidget(level_container)
        
        form_layout.addLayout(row1_layout)
        
        form_layout.addSpacing(10)  # Extra spacing between fields
        
        # Tags
        tags_label = QLabel("Tags (comma-separated)")
        tags_label.setStyleSheet(label_style)
        form_layout.addWidget(tags_label)
        
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("e.g., Anatomy, MSK, Advanced")
        self.tags_input.setStyleSheet(field_style)
        self.tags_input.setMinimumHeight(48)
        form_layout.addWidget(self.tags_input)
        
        # Body Regions
        regions_label = QLabel("Body Regions (comma-separated)")
        regions_label.setStyleSheet(label_style)
        form_layout.addWidget(regions_label)
        
        self.regions_input = QLineEdit()
        self.regions_input.setPlaceholderText("e.g., MSK, Shoulder")
        self.regions_input.setStyleSheet(field_style)
        self.regions_input.setMinimumHeight(48)
        form_layout.addWidget(self.regions_input)
        
        form_layout.addSpacing(20)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(18)
        
        # Professional button styling
        clear_btn = QPushButton("Clear Form")
        clear_btn.setFixedHeight(48)
        clear_btn.setMinimumWidth(140)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                font-size: 14pt;
            }
            QPushButton:hover {
                border-color: #4d7aa0;
                color: #cbd5e0;
            }
        """)
        clear_btn.clicked.connect(self.clear_form)
        buttons_layout.addWidget(clear_btn)
        
        create_btn = QPushButton("Create Course")
        create_btn.setFixedHeight(48)
        create_btn.setMinimumWidth(160)
        create_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 14pt;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #3d7a9f;
                border-color: #4d8aaf;
            }
        """)
        create_btn.clicked.connect(self.create_course)
        buttons_layout.addWidget(create_btn)
        
        form_layout.addLayout(buttons_layout)
        
        # Add form container to main layout (centered)
        center_layout = QHBoxLayout()
        center_layout.addStretch()
        center_layout.addWidget(form_container)
        center_layout.addStretch()
        layout.addLayout(center_layout)
        
        layout.addStretch()
    
    def create_course(self):
        """Create new course."""
        title = self.title_input.text().strip()
        author = self.author_input.text().strip()
        
        if not title:
            QMessageBox.warning(self, "Validation Error", "Course title is required.")
            return
        
        if not author:
            QMessageBox.warning(self, "Validation Error", "Instructor name is required.")
            return
        
        description = self.desc_input.toPlainText().strip()
        modality = self.modality_combo.currentText()
        level = self.level_combo.currentText()
        
        # Parse tags and regions
        tags = [t.strip() for t in self.tags_input.text().split(',') if t.strip()]
        regions = [r.strip() for r in self.regions_input.text().split(',') if r.strip()]
        
        # Insert course
        try:
            course_pk = insert_course(
                name=title,
                description=description,
                author=author,
                modality=modality,
                level=level,
                tags=tags,
                body_regions=regions,
                is_my_course=True
            )
            
            QMessageBox.information(self, "Success", f"Course '{title}' created successfully!")
            
            # Clear form
            self.clear_form()
            
            # Emit signal
            course_data = {
                'course_pk': course_pk,
                'course_name': title,
                'author_name': author,
                'course_description': description,
                'modality': modality,
                'level': level,
                'tags': tags,
                'body_regions': regions
            }
            self.course_created.emit(course_data)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create course: {str(e)}")
    
    def clear_form(self):
        """Clear all form fields."""
        self.title_input.clear()
        self.author_input.clear()
        self.desc_input.clear()
        self.modality_combo.setCurrentIndex(0)
        self.level_combo.setCurrentText("Intermediate")
        self.tags_input.clear()
        self.regions_input.clear()


# ==================== MAIN EDUCATION MODULE ====================

class EducationModuleRedesigned(QWidget):
    """Main education module widget with three tabs."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup main UI with tabs."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header bar - professional clinical style
        header = QWidget()
        header.setFixedHeight(68)  # Taller for better proportions
        header.setStyleSheet("""
            QWidget {
                background-color: #0d1117;
                border-bottom: 1px solid #1e2530;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 0, 28, 0)
        
        # Title - professional, calm, larger
        title = QLabel("Education")
        title_font = QFont()
        title_font.setPointSize(18)  # Increased for better visibility
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f0f4f8; background: transparent; letter-spacing: 0.5px;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Status - minimal indicator with better sizing
        status = QLabel("Offline")
        status.setStyleSheet("""
            QLabel {
                background-color: transparent;
                color: #8892a0;
                padding: 8px 16px;
                font-size: 12pt;
                border: 1px solid #3d5a80;
                border-radius: 2px;
            }
        """)
        header_layout.addWidget(status)
        
        layout.addWidget(header)
        
        # Tab widget - professional clinical style with better readability
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #161b22;
                border-top: 1px solid #1e2530;
            }
            QTabBar::tab {
                background-color: transparent;
                color: #8892a0;
                padding: 14px 26px;
                margin-right: 0px;
                border: none;
                border-bottom: 2px solid transparent;
                font-size: 14pt;
                font-weight: normal;
            }
            QTabBar::tab:selected {
                background-color: transparent;
                color: #f0f4f8;
                border-bottom: 2px solid #4d8aaf;
            }
            QTabBar::tab:hover:!selected {
                background-color: rgba(255, 255, 255, 0.04);
                color: #a8b2c0;
            }
        """)
        
        # Create tabs
        self.library_page = LibraryPage()
        self.mycourses_page = MyCoursesPage()
        self.build_page = BuildCoursePage()
        
        self.tab_widget.addTab(self.library_page, "Library")
        self.tab_widget.addTab(self.mycourses_page, "My Courses")
        self.tab_widget.addTab(self.build_page, "Build Course")
        
        layout.addWidget(self.tab_widget)
        
        # Connect signals
        self.library_page.course_opened.connect(self.on_course_opened)
        self.library_page.course_edited.connect(self.on_course_edited)
        self.mycourses_page.course_opened.connect(self.on_course_opened)
        self.mycourses_page.course_edited.connect(self.on_course_edited)
        self.build_page.course_created.connect(self.on_course_created)
    
    def on_course_opened(self, course_data):
        """Handle course open request."""
        print(f"Opening course: {course_data['course_name']}")
        
        # Import and open course editor
        try:
            from PacsClient.pacs.education.course_editor_widget import CourseEditorWidget
            
            # Check if we're in a tab manager context
            parent = self.parent()
            while parent:
                if hasattr(parent, 'tab_widget') and hasattr(parent, 'custom_tab_manager'):
                    # Found the home widget with tab manager
                    editor = CourseEditorWidget(course_data['course_pk'], parent=parent)
                    
                    if parent.custom_tab_manager:
                        # Add as custom tab
                        tab_index = parent.tab_widget.addTab(editor, f"📚 {course_data['course_name']}")
                        parent.tab_widget.setCurrentIndex(tab_index)
                    else:
                        # Fallback
                        tab_index = parent.tab_widget.addTab(editor, f"📚 {course_data['course_name']}")
                        parent.tab_widget.setCurrentIndex(tab_index)
                    break
                parent = parent.parent()
            
        except Exception as e:
            print(f"Error opening course: {e}")
            import traceback
            traceback.print_exc()
    
    def on_course_edited(self, course_data):
        """Handle course edit request."""
        self.on_course_opened(course_data)
    
    def on_course_created(self, course_data):
        """Handle new course created."""
        print(f"Course created: {course_data['course_name']}")
        
        # Refresh My Courses and switch to it
        self.mycourses_page.load_courses()
        self.tab_widget.setCurrentWidget(self.mycourses_page)
        
        # Show success message
        QMessageBox.information(
            self,
            "Course Created",
            f"Course '{course_data['course_name']}' has been created!\n\nYou can now add slides and content in the editor."
        )


# ==================== DEMO ENTRY POINT ====================

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    
    # Set dark theme
    app.setStyle("Fusion")
    
    widget = EducationModuleRedesigned()
    widget.setWindowTitle("Education Module - Redesigned")
    widget.resize(1600, 900)
    widget.show()
    
    sys.exit(app.exec())
