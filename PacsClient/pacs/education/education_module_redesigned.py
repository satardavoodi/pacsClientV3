"""
Redesigned Education Module with Modern UI/UX
Three tabs: Library | My Courses | Build Course
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QTabWidget, QComboBox, QScrollArea,
    QFrame, QGridLayout, QSpacerItem, QSizePolicy, QCheckBox,
    QGroupBox, QTreeWidget, QTreeWidgetItem, QMessageBox, QDialog,
    QProgressBar, QSlider, QListWidget, QListWidgetItem, QFileDialog,
    QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from PacsClient.pacs.education.course_database import (
    get_all_courses, search_and_filter_courses, insert_course,
    delete_course, get_course_with_slides, update_course,
    get_slides_for_course, insert_slide, update_slide, delete_slide,
    reorder_slides, get_content_for_slide, insert_slide_content,
    update_slide_content, delete_slide_content, save_course_asset,
    import_resource_to_my_courses
)
from PacsClient.pacs.education.study_picker_dialog import StudyPickerDialog
from PacsClient.utils.config import EDUCATION_STORAGE_PATH


# ==================== CONSTANTS ====================

MODALITIES = ["CT", "MRI", "US", "X-Ray", "PET", "SPECT", "Mammography", "Fluoroscopy"]
BODY_REGIONS = ["Head/Neck", "Chest", "Abdomen", "Pelvis", "MSK", "Spine", "Vascular", "Cardiac"]
LEVELS = ["Basic", "Intermediate", "Advanced", "Expert"]
COMMON_TAGS = [
    "Anatomy", "Pathology", "Trauma", "Oncology", "Pediatric", 
    "Emergency", "Intervention", "Physics", "Protocol", "Artifacts"
]
MY_COURSE_STATE_PATH = EDUCATION_STORAGE_PATH / "my_courses_state.json"
RESOURCE_FILTER_OPTIONS = [
    ("All Types", None),
    ("Course", "Course"),
    ("Book", "Book"),
    ("Video", "Video"),
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
        
        # Modality filter: 4 columns x 2 rows
        self.add_filter_grid_group(
            layout,
            "Modality",
            MODALITIES,
            "modality",
            columns=4,
            row_major=True,
        )
        
        # Body Region filter: 2 columns x 4 rows
        self.add_filter_grid_group(
            layout,
            "Body Region",
            BODY_REGIONS,
            "body_regions",
            columns=2,
            row_major=True,
        )
        
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
        
        # Tags filter: two explicit columns
        self.add_filter_dual_column_group(
            layout,
            "Tags",
            ["Anatomy", "Pathology", "Trauma"],
            ["Oncology", "Pediatric", "Emergency"],
            "tags",
        )
        
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
    
    def add_filter_grid_group(self, parent_layout, title, items, filter_key, columns=1, row_major=True):
        """Add a checkbox filter group with grid layout."""
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
        
        group_layout = QGridLayout()
        group_layout.setHorizontalSpacing(12)
        group_layout.setVerticalSpacing(2)
        group_layout.setContentsMargins(0, 18, 0, 10)
        
        checkboxes = []
        for index, item in enumerate(items):
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
            if columns <= 1:
                row, col = index, 0
            else:
                if row_major:
                    row = index // columns
                    col = index % columns
                else:
                    rows = (len(items) + columns - 1) // columns
                    row = index % rows
                    col = index // rows
            group_layout.addWidget(cb, row, col)
        
        group.setLayout(group_layout)
        parent_layout.addWidget(group)
        
        # Store checkboxes for clearing
        setattr(self, f'{filter_key}_checkboxes', checkboxes)

    def add_filter_dual_column_group(self, parent_layout, title, left_items, right_items, filter_key):
        """Add a two-column checkbox group with explicit left/right lists."""
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

        group_layout = QGridLayout()
        group_layout.setHorizontalSpacing(16)
        group_layout.setVerticalSpacing(2)
        group_layout.setContentsMargins(0, 18, 0, 10)

        checkboxes = []

        for row, item in enumerate(left_items):
            cb = self._build_filter_checkbox(item, filter_key)
            checkboxes.append(cb)
            group_layout.addWidget(cb, row, 0)

        for row, item in enumerate(right_items):
            cb = self._build_filter_checkbox(item, filter_key)
            checkboxes.append(cb)
            group_layout.addWidget(cb, row, 1)

        group.setLayout(group_layout)
        parent_layout.addWidget(group)
        setattr(self, f'{filter_key}_checkboxes', checkboxes)

    def _build_filter_checkbox(self, item, filter_key):
        cb = QCheckBox(item)
        cb.setMinimumHeight(32)
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
        return cb
    
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
        """Setup professional clinical card UI with image region."""
        self.setObjectName("ModernCourseCard")
        self.setFixedSize(300, 350)
        self.setCursor(Qt.PointingHandCursor)
        
        # Base card style
        self.update_style()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Image area
        image_frame = QFrame()
        image_frame.setFixedHeight(182)
        image_frame.setStyleSheet("""
            QFrame {
                background-color: #101722;
                border-top-left-radius: 2px;
                border-top-right-radius: 2px;
            }
        """)
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(6, 6, 6, 6)
        image_layout.setSpacing(0)

        thumbnail_label = QLabel()
        thumbnail_label.setFixedSize(168, 168)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_label.setStyleSheet("QLabel { background-color: #0a0f18; color: #9db1c5; border: 1px solid #1d2a3a; }")

        thumbnail_path = self.course_data.get('thumbnail_path') or ''
        if thumbnail_path and Path(thumbnail_path).exists():
            pixmap = QPixmap(thumbnail_path)
            thumbnail_label.setPixmap(pixmap.scaled(168, 168, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            thumbnail_label.setText("Course Image")

        image_layout.addWidget(thumbnail_label)
        layout.addWidget(image_frame)

        # Content area
        content = QFrame()
        content.setStyleSheet("QFrame { background-color: #151f2c; border: none; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 10)
        content_layout.setSpacing(5)

        top_meta = QHBoxLayout()
        top_meta.setSpacing(8)
        resource_type = self.course_data.get('resource_type') or "Course"
        modality = self.course_data.get('modality') or resource_type
        level = self.course_data.get('level', 'Intermediate')

        modality_label = QLabel(modality)
        modality_label.setStyleSheet("""
            QLabel {
                color: #eef5fc;
                font-size: 9pt;
                font-weight: 600;
                padding: 2px 8px;
                background-color: #1f3f66;
                border-radius: 2px;
            }
        """)
        top_meta.addWidget(modality_label)
        top_meta.addStretch()

        level_label = QLabel(level)
        level_label.setStyleSheet("""
            QLabel {
                color: #d7e4f2;
                font-size: 8.5pt;
                padding: 2px 8px;
                background-color: #24384e;
                border-radius: 2px;
            }
        """)
        top_meta.addWidget(level_label)
        if self.course_data.get('needs_attention'):
            attention_label = QLabel("Needs Fix")
            attention_label.setStyleSheet("""
                QLabel {
                    color: #f5c97f;
                    font-size: 8.5pt;
                    padding: 2px 8px;
                    background-color: #3b2b16;
                    border-radius: 2px;
                    border: 1px solid #70572a;
                }
            """)
            top_meta.addWidget(attention_label)
        content_layout.addLayout(top_meta)

        title = QLabel(self.course_data['course_name'])
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f0f4f8;")
        title.setWordWrap(True)
        title.setMaximumHeight(44)
        content_layout.addWidget(title)

        desc_text = self.course_data.get('course_description', '') or ""
        if len(desc_text) > 70:
            desc_text = desc_text[:70] + "..."
        description = QLabel(desc_text)
        description.setStyleSheet("color: #95a7bb; font-size: 8.5pt;")
        description.setWordWrap(True)
        description.setMaximumHeight(30)
        content_layout.addWidget(description)

        author_text = self.course_data.get('author_name', 'Unknown')
        if len(author_text) > 22:
            author_text = author_text[:22] + "..."
        author = QLabel(author_text)
        author.setStyleSheet("color: #8892a0; font-size: 9pt;")
        content_layout.addWidget(author)

        if self.show_actions:
            view_btn = QPushButton("Select")
            view_btn.setFixedHeight(26)
            view_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #7c9cbf;
                    border: 1px solid #2d5a7b;
                    border-radius: 2px;
                    font-size: 8.5pt;
                    padding: 2px 10px;
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
                QFrame#ModernCourseCard {
                    background-color: #1a2332;
                    border: 1px solid #3d7a9f;
                    border-radius: 2px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#ModernCourseCard {
                    background-color: #1a2332;
                    border: 1px solid #1e2530;
                    border-radius: 2px;
                }
                QFrame#ModernCourseCard:hover {
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
    
    def __init__(self, parent=None, allow_edit=True, allow_delete=True, allow_import=True):
        super().__init__(parent)
        self.current_course = None
        self.allow_edit = allow_edit
        self.allow_delete = allow_delete
        self.allow_import = allow_import
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
        author = QLabel(f"Author: {course_data.get('author_name', 'Unknown')}")
        author.setStyleSheet("color: #a8b2c0; font-size: 13pt; border: none; padding: 4px 0;")
        layout.addWidget(author)
        
        # Metadata row
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(12)
        resource_type = course_data.get('resource_type') or "Course"
        resource_label = QLabel(f"Type: {resource_type}")
        resource_label.setStyleSheet("color: #cbd5e0; font-size: 12pt; border: none;")
        meta_layout.addWidget(resource_label)

        if course_data.get('modality'):
            modality_label = QLabel(f"Modality: {course_data['modality']}")
            modality_label.setStyleSheet("color: #cbd5e0; font-size: 12pt; border: none;")
            meta_layout.addWidget(modality_label)
        
        if course_data.get('level'):
            level_label = QLabel(f"Level: {course_data['level']}")
            level_label.setStyleSheet("color: #cbd5e0; font-size: 12pt; border: none;")
            meta_layout.addWidget(level_label)
        meta_layout.addStretch()
        layout.addLayout(meta_layout)

        if course_data.get('needs_attention'):
            warning_label = QLabel("Some imported fields need to be imported or corrected.")
            warning_label.setStyleSheet(
                "color: #f5c97f; font-size: 11pt; border: 1px solid #70572a; "
                "background-color: #2a2215; padding: 8px;"
            )
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)

        if course_data.get('content_origin'):
            origin_label = QLabel(f"Origin: {course_data.get('content_origin')}")
            origin_label.setStyleSheet("color: #9bb0c6; font-size: 10pt; border: none;")
            layout.addWidget(origin_label)
        
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
        root.setText(0, f"ًں“ڑ {slides_count} Slides")
        
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

        if self.allow_import and not course_data.get('is_my_course'):
            import_btn = QPushButton("Download to My Courses")
            import_btn.setFixedHeight(38)
            import_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1b3f2f;
                    color: #def7e8;
                    border: 1px solid #2f6c55;
                    border-radius: 2px;
                    font-size: 12pt;
                }
                QPushButton:hover {
                    background-color: #255a43;
                    border-color: #34785b;
                }
            """)
            import_btn.clicked.connect(lambda: self.action_requested.emit('import_to_my_courses', self.current_course))
            actions_layout.addWidget(import_btn)
        
        if self.allow_edit:
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
        
        if self.allow_delete:
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
    GRID_COLUMNS = 3
    CARD_HEIGHT = 350
    GRID_SPACING = 20
    VISIBLE_ROWS = 2
    
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
        self.center_layout = QVBoxLayout(center_widget)
        self.center_layout.setContentsMargins(16, 10, 16, 12)
        self.center_layout.setSpacing(8)
        
        # Search bar
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search courses, books, videos, tags...")
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

        self.library_resource_filter = QComboBox()
        self.library_resource_filter.setFixedWidth(170)
        for label, value in RESOURCE_FILTER_OPTIONS:
            self.library_resource_filter.addItem(label, value)
        self.library_resource_filter.setStyleSheet("""
            QComboBox {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 10px;
                font-size: 11pt;
            }
            QComboBox:hover {
                border-color: #4d8aaf;
            }
        """)
        self.library_resource_filter.currentIndexChanged.connect(self.apply_filters)
        search_layout.addWidget(self.library_resource_filter)
        
        self.center_layout.addWidget(search_container)
        
        # Results count
        self.results_label = QLabel("0 resources")
        self.results_label.setStyleSheet("color: #a8b2c0; font-size: 12pt; padding: 0;")
        self.center_layout.addWidget(self.results_label)
        
        # Scrollable grid
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(20)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        
        self.cards_scroll.setWidget(self.grid_container)
        self.center_layout.addWidget(self.cards_scroll)
        self._update_cards_scroll_height()
        
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
            tags=self.current_filters.get('tags'),
            resource_types=[self.library_resource_filter.currentData()] if self.library_resource_filter.currentData() else None,
        )
        
        self.update_grid()
        total = len(self.filtered_courses)
        self.results_label.setText(f"{total} resource{'s' if total != 1 else ''}")
    
    def update_grid(self):
        """Update course grid."""
        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.selected_card = None
        
        # Add course cards - 3 columns, first 2 rows visible, rest via scroll
        visible_courses = self.filtered_courses
        cols = self.GRID_COLUMNS
        for i, course in enumerate(visible_courses):
            row = i // cols
            col = i % cols
            
            card = ModernCourseCard(course)
            card.clicked.connect(self.on_card_clicked)
            card.action_requested.connect(self.on_card_action)
            self.grid_layout.addWidget(card, row, col)
        self._update_cards_scroll_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_cards_scroll_height()

    def _update_cards_scroll_height(self):
        target_height = (self.CARD_HEIGHT * self.VISIBLE_ROWS) + (self.GRID_SPACING * (self.VISIBLE_ROWS - 1)) + 10
        available = max(260, self.height() - 170)
        self.cards_scroll.setMaximumHeight(min(target_height, available))
    
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
        elif action == 'import_to_my_courses':
            if course_data.get('is_my_course'):
                QMessageBox.information(self, "Already in My Courses", "This resource is already available in My Courses.")
                return
            if not self._is_free_library_resource(course_data):
                QMessageBox.information(
                    self,
                    "Premium Resource",
                    "This resource is not free.\nPlease contact AI-Pacs.com to obtain access:\nhttps://ai-pacs.com"
                )
                return
            try:
                update_course(
                    course_pk=course_data['course_pk'],
                    is_my_course=True,
                    is_downloaded=True,
                    content_origin="downloaded_library",
                )
                self.load_courses()
                QMessageBox.information(
                    self,
                    "Downloaded to My Courses",
                    f"'{course_data.get('course_name', 'Resource')}' is now available under My Courses > Downloaded."
                )
            except Exception as exc:
                QMessageBox.critical(self, "Download Failed", f"Could not add resource to My Courses:\n{exc}")
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

    def _is_free_library_resource(self, course_data):
        """Infer whether a library resource is free for all users."""
        tags = [str(tag).strip().lower() for tag in (course_data.get("tags") or [])]
        blocked_keywords = {"premium", "paid", "subscription", "licensed", "contact sales"}
        if any(keyword in " ".join(tags) for keyword in blocked_keywords):
            return False

        outline_raw = course_data.get("outline")
        if isinstance(outline_raw, str) and outline_raw.strip():
            try:
                outline_payload = json.loads(outline_raw)
                if isinstance(outline_payload, dict):
                    access_value = str(
                        outline_payload.get("access")
                        or outline_payload.get("pricing")
                        or outline_payload.get("tier")
                        or ""
                    ).strip().lower()
                    if access_value in {"premium", "paid", "subscription", "enterprise"}:
                        return False
            except Exception:
                outline_text = outline_raw.lower()
                if any(keyword in outline_text for keyword in blocked_keywords):
                    return False

        if str(course_data.get("validation_status", "")).strip().lower() == "requires_contact":
            return False

        return True


# ==================== MY COURSES PAGE ====================

class MyCoursesPage(QWidget):
    """My Courses tab with Downloaded, Created, and Imported sections."""
     
    course_opened = Signal(dict)
    course_edited = Signal(dict)
    case_of_day_opened = Signal(dict)
    GRID_COLUMNS = 2
    CARD_HEIGHT = 350
    GRID_SPACING = 20
    VISIBLE_ROWS = 2
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_view = 'created'  # 'downloaded' | 'created' | 'imported'
        self.current_search = ""
        self.current_resource_filter = None
        self.downloaded_filters = {"modality": [], "body_regions": [], "level": None, "tags": []}
        self.selected_card = None
        self.selected_course = None
        self.state_data = {"courses": {}}
        self.setup_ui()
        self._load_personal_state()
        self._ensure_my_courses_samples()
        self.load_courses()
    
    def setup_ui(self):
        """Setup personalized My Courses UI."""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left personalized panel
        self.personal_panel = QFrame()
        self.personal_panel.setFixedWidth(370)
        self.personal_panel.setStyleSheet("""
            QFrame {
                background-color: #111a26;
                border-right: 1px solid #1e2d3d;
            }
        """)
        personal_layout = QVBoxLayout(self.personal_panel)
        personal_layout.setContentsMargins(16, 16, 16, 16)
        personal_layout.setSpacing(12)

        panel_title = QLabel("My Course Notes")
        panel_title_font = QFont()
        panel_title_font.setPointSize(15)
        panel_title_font.setWeight(QFont.DemiBold)
        panel_title.setFont(panel_title_font)
        panel_title.setStyleSheet("color: #f1f5f9;")
        personal_layout.addWidget(panel_title)

        self.personal_course_title = QLabel("Select a course")
        self.personal_course_title.setStyleSheet("color: #c7d3df; font-size: 11pt; font-weight: 600;")
        self.personal_course_title.setWordWrap(True)
        personal_layout.addWidget(self.personal_course_title)

        self.personal_exam_structure = QLabel("Exam structure: Not set")
        self.personal_exam_structure.setStyleSheet("color: #93a4b6; font-size: 9.5pt;")
        personal_layout.addWidget(self.personal_exam_structure)

        progress_header = QLabel("Completion Progress")
        progress_header.setStyleSheet("color: #d8e3ee; font-size: 10pt; font-weight: 600;")
        personal_layout.addWidget(progress_header)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.personal_progress_slider = QSlider(Qt.Horizontal)
        self.personal_progress_slider.setRange(0, 100)
        self.personal_progress_slider.setValue(0)
        self.personal_progress_slider.valueChanged.connect(self._on_progress_changed)
        self.personal_progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #2f455a;
                height: 8px;
                background: #152436;
            }
            QSlider::handle:horizontal {
                background: #3d7a9f;
                border: 1px solid #4d8aaf;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
        """)
        progress_row.addWidget(self.personal_progress_slider)

        self.personal_progress_label = QLabel("0%")
        self.personal_progress_label.setStyleSheet("color: #9fc5e8; font-size: 10pt; font-weight: 600;")
        progress_row.addWidget(self.personal_progress_label)
        personal_layout.addLayout(progress_row)

        self.personal_progress_bar = QProgressBar()
        self.personal_progress_bar.setRange(0, 100)
        self.personal_progress_bar.setValue(0)
        self.personal_progress_bar.setTextVisible(False)
        self.personal_progress_bar.setFixedHeight(10)
        self.personal_progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #152436;
                border: 1px solid #2f455a;
            }
            QProgressBar::chunk {
                background-color: #3d7a9f;
            }
        """)
        personal_layout.addWidget(self.personal_progress_bar)

        exam_row = QHBoxLayout()
        exam_row.setSpacing(8)
        self.personal_exam_type = QComboBox()
        self.personal_exam_type.addItems(["No Exam", "Quiz", "Case Assessment", "Final Exam"])
        self.personal_exam_type.currentTextChanged.connect(self._on_exam_field_changed)
        self.personal_exam_type.setStyleSheet("""
            QComboBox {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #2e4156;
                padding: 6px 10px;
                font-size: 9pt;
            }
        """)
        exam_row.addWidget(self.personal_exam_type)

        self.personal_exam_status = QComboBox()
        self.personal_exam_status.addItems(["Not Started", "Preparing", "Passed", "Needs Review"])
        self.personal_exam_status.currentTextChanged.connect(self._on_exam_field_changed)
        self.personal_exam_status.setStyleSheet(self.personal_exam_type.styleSheet())
        exam_row.addWidget(self.personal_exam_status)
        personal_layout.addLayout(exam_row)

        notes_label = QLabel("Personal Notes")
        notes_label.setStyleSheet("color: #d8e3ee; font-size: 10pt; font-weight: 600;")
        personal_layout.addWidget(notes_label)

        self.personal_notes_input = QTextEdit()
        self.personal_notes_input.setPlaceholderText("Write your review notes, reminders, weak points, and follow-up plan...")
        self.personal_notes_input.setFixedHeight(180)
        self.personal_notes_input.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #2e4156;
                padding: 8px;
                font-size: 9.5pt;
            }
        """)
        personal_layout.addWidget(self.personal_notes_input)

        self.personal_last_reviewed = QLabel("Last reviewed: -")
        self.personal_last_reviewed.setStyleSheet("color: #8497ab; font-size: 9pt;")
        personal_layout.addWidget(self.personal_last_reviewed)

        save_btn = QPushButton("Save Note")
        save_btn.setFixedHeight(34)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #1f3f66;
                color: #e9f2fb;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2b527f;
            }
        """)
        save_btn.clicked.connect(self._save_current_course_state)
        personal_layout.addWidget(save_btn)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.personal_open_btn = QPushButton("Open")
        self.personal_open_btn.setFixedHeight(34)
        self.personal_open_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 9.5pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        self.personal_open_btn.clicked.connect(self._open_selected_course)
        action_row.addWidget(self.personal_open_btn)

        self.personal_edit_btn = QPushButton("Edit in Build Course")
        self.personal_edit_btn.setFixedHeight(34)
        self.personal_edit_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #d8e2ee;
                border: 1px solid #4d7aa0;
                border-radius: 2px;
                font-size: 9.5pt;
            }
            QPushButton:hover {
                border-color: #5d8ab0;
                background-color: rgba(93, 138, 176, 0.12);
            }
        """)
        self.personal_edit_btn.clicked.connect(self._edit_selected_course)
        action_row.addWidget(self.personal_edit_btn)
        personal_layout.addLayout(action_row)
        personal_layout.addStretch()

        # Center section
        center_widget = QWidget()
        self.center_layout = QVBoxLayout(center_widget)
        self.center_layout.setContentsMargins(16, 10, 16, 12)
        self.center_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        title = QLabel("My Courses")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #f7fafc;")
        header_layout.addWidget(title)
        header_layout.addStretch()
 
        self.created_btn = QPushButton("Created by Me")
        self.downloaded_btn = QPushButton("Downloaded (from Library)")
        self.imported_btn = QPushButton("Imported")
        self.case_of_day_btn = QPushButton("Case of the Day")
        for btn in [self.downloaded_btn, self.created_btn, self.imported_btn, self.case_of_day_btn]:
            btn.setFixedHeight(36)
            btn.setMinimumWidth(150)
            btn.setCursor(Qt.PointingHandCursor)
        self.downloaded_btn.clicked.connect(lambda: self.switch_view('downloaded'))
        self.created_btn.clicked.connect(lambda: self.switch_view('created'))
        self.imported_btn.clicked.connect(lambda: self.switch_view('imported'))
        self.case_of_day_btn.clicked.connect(lambda: self.switch_view('case_of_day'))
        header_layout.addWidget(self.downloaded_btn)
        header_layout.addWidget(self.created_btn)
        header_layout.addWidget(self.imported_btn)
        header_layout.addWidget(self.case_of_day_btn)
        self.center_layout.addLayout(header_layout)

        import_row = QHBoxLayout()
        import_row.setSpacing(8)
        self.import_type_combo = QComboBox()
        self.import_type_combo.addItem("Auto Type", None)
        self.import_type_combo.addItem("Course", "Course")
        self.import_type_combo.addItem("Book", "Book")
        self.import_type_combo.addItem("Video", "Video")
        self.import_type_combo.setFixedHeight(40)
        self.import_type_combo.setFixedWidth(160)
        self.import_type_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 10px;
                font-size: 10.5pt;
            }
        """)
        import_row.addWidget(self.import_type_combo)
        import_btn = QPushButton("Import Course")
        import_btn.setFixedHeight(40)
        import_btn.setMinimumWidth(170)
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1f4a67;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10.5pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #2d5f82; }
        """)
        import_btn.clicked.connect(self._on_import_course_clicked)
        import_row.addWidget(import_btn)
        import_row.addStretch()
        self.center_layout.addLayout(import_row)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search in my courses...")
        self.search_input.setFixedHeight(42)
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 14px;
                font-size: 12pt;
            }
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_input)

        self.resource_filter_combo = QComboBox()
        for label, value in RESOURCE_FILTER_OPTIONS:
            self.resource_filter_combo.addItem(label, value)
        self.resource_filter_combo.setFixedHeight(42)
        self.resource_filter_combo.setFixedWidth(170)
        self.resource_filter_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 10px;
                font-size: 10.5pt;
            }
        """)
        self.resource_filter_combo.currentIndexChanged.connect(self._on_resource_filter_changed)
        search_row.addWidget(self.resource_filter_combo)
        self.center_layout.addLayout(search_row)

        self.results_label = QLabel("0 resources")
        self.results_label.setStyleSheet("color: #a8b2c0; font-size: 12pt; padding: 0;")
        self.center_layout.addWidget(self.results_label)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(self.GRID_SPACING)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.cards_scroll.setWidget(self.grid_container)
        self.center_layout.addWidget(self.cards_scroll)
        self._update_cards_scroll_height()

        self.downloaded_filter_panel = FilterPanel()
        self.downloaded_filter_panel.filters_changed.connect(self._on_downloaded_filters_changed)

        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self.personal_panel)  # index 0
        self.left_stack.addWidget(self.downloaded_filter_panel)  # index 1
        self.left_stack.setFixedWidth(380)
        root.addWidget(self.left_stack)
 
        self.standard_center_widget = center_widget
        root.addWidget(self.standard_center_widget, stretch=1)

        self.downloaded_details_panel = CourseDetailsPanel(
            parent=self,
            allow_edit=False,
            allow_delete=False,
            allow_import=False,
        )
        self.downloaded_details_panel.action_requested.connect(self._on_downloaded_detail_action)
        self.downloaded_details_panel.hide()
        root.addWidget(self.downloaded_details_panel)
 
        from PacsClient.pacs.education.case_of_day_widget import CaseOfDayPage
        self.case_of_day_page = CaseOfDayPage(self)
        self.case_of_day_page.case_opened.connect(self._on_case_of_day_opened)
        self.case_of_day_page.hide()
        root.addWidget(self.case_of_day_page, stretch=1)
 
        self._reset_personal_panel()
        self.switch_view('created')
    
    def switch_view(self, view):
        """Switch between downloaded/created/imported/case-of-day views."""
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
        
        self.downloaded_btn.setStyleSheet(active_style if view == 'downloaded' else inactive_style)
        self.created_btn.setStyleSheet(active_style if view == 'created' else inactive_style)
        self.imported_btn.setStyleSheet(active_style if view == 'imported' else inactive_style)
        self.case_of_day_btn.setStyleSheet(active_style if view == 'case_of_day' else inactive_style)

        if view == 'case_of_day':
            self.left_stack.hide()
            self.standard_center_widget.hide()
            self.downloaded_details_panel.hide()
            self.case_of_day_page.show()
            self.case_of_day_page.refresh()
            return
        else:
            self.case_of_day_page.hide()
            self.left_stack.show()
            self.standard_center_widget.show()

        if view == 'downloaded':
            self.left_stack.setCurrentIndex(1)
            self.downloaded_details_panel.show()
            self.personal_open_btn.setEnabled(False)
            self.personal_edit_btn.setEnabled(False)
        else:
            self.left_stack.setCurrentIndex(0)
            self.downloaded_details_panel.hide()
            if self.selected_course:
                self.personal_open_btn.setEnabled(True)
                self.personal_edit_btn.setEnabled(view in {'created', 'imported'})
            else:
                self.personal_open_btn.setEnabled(False)
                self.personal_edit_btn.setEnabled(False)
        
        self.load_courses()

    def _on_case_of_day_opened(self, payload: Dict[str, Any]):
        self.case_of_day_opened.emit(payload)
    
    def _on_search_changed(self, text):
        self.current_search = text
        if hasattr(self, 'search_timer'):
            self.search_timer.stop()
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.load_courses)
        self.search_timer.start(250)

    def _on_resource_filter_changed(self, _index):
        self.current_resource_filter = self.resource_filter_combo.currentData()
        self.load_courses()

    def _on_downloaded_filters_changed(self, filters):
        self.downloaded_filters = dict(filters or {})
        if self.current_view == 'downloaded':
            self.load_courses()

    def _on_downloaded_detail_action(self, action, course_data):
        if action == "open":
            self.course_opened.emit(course_data)

    def _open_selected_course(self):
        if not self.selected_course:
            QMessageBox.information(self, "No Selection", "Select a course first.")
            return
        self.course_opened.emit(self.selected_course)

    def _edit_selected_course(self):
        if not self.selected_course:
            QMessageBox.information(self, "No Selection", "Select a course first.")
            return
        if self.current_view == 'downloaded':
            QMessageBox.information(
                self,
                "Read-Only Downloaded Resource",
                "Downloaded Library resources are fixed and cannot be edited."
            )
            return
        self.course_edited.emit(self.selected_course)

    def _on_import_course_clicked(self):
        file_filter = (
            "Supported Imports (*.json *.pdf *.epub *.mobi *.txt *.doc *.docx "
            "*.mp4 *.avi *.mov *.mkv *.wmv *.webm *.m4v *.png *.jpg *.jpeg *.bmp *.tif *.tiff "
            "*.wav *.mp3 *.ogg *.aac *.m4a);;All Files (*)"
        )
        selected_file, _ = QFileDialog.getOpenFileName(self, "Import Course / Book / Video", "", file_filter)
        if not selected_file:
            return

        try:
            result = import_resource_to_my_courses(
                file_path=selected_file,
                desired_resource_type=self.import_type_combo.currentData(),
            )
            self.current_view = 'imported'
            self.switch_view('imported')
            warning_lines = result.get("warnings") or []
            if warning_lines:
                preview = "\n".join(f"- {line}" for line in warning_lines[:6])
                more = "\n- ..." if len(warning_lines) > 6 else ""
                QMessageBox.warning(
                    self,
                    "Imported with Attention Required",
                    f"Imported '{result.get('course_name', 'resource')}' into My Courses.\n\n"
                    f"Some fields need correction:\n{preview}{more}"
                )
            else:
                QMessageBox.information(
                    self,
                    "Import Completed",
                    f"Imported '{result.get('course_name', 'resource')}' into My Courses."
                )
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Could not import selected file:\n{exc}")

    def load_courses(self):
        """Load courses based on current view."""
        self._ensure_my_courses_samples()
        all_courses = get_all_courses()

        if self.current_view == 'downloaded':
            courses = search_and_filter_courses(
                query=self.current_search,
                modality=self.downloaded_filters.get('modality'),
                body_regions=self.downloaded_filters.get('body_regions'),
                level=self.downloaded_filters.get('level'),
                tags=self.downloaded_filters.get('tags'),
                resource_types=[self.current_resource_filter] if self.current_resource_filter else None,
            )
            courses = [course for course in courses if bool(course.get('is_downloaded'))]
        else:
            query = self.current_search.strip().lower()
            if self.current_view == 'imported':
                courses = [
                    c for c in all_courses
                    if bool(c.get('is_my_course'))
                    and str(c.get('content_origin') or '').strip().lower() == 'imported'
                ]
            else:
                courses = [
                    c for c in all_courses
                    if bool(c.get('is_my_course'))
                    and not bool(c.get('is_downloaded'))
                    and str(c.get('content_origin') or 'local').strip().lower() != 'imported'
                ]

            if self.current_resource_filter:
                courses = [c for c in courses if c.get('resource_type') == self.current_resource_filter]

            if query:
                courses = [
                    c for c in courses
                    if query in (c.get('course_name') or '').lower()
                    or query in (c.get('course_description') or '').lower()
                    or query in (c.get('author_name') or '').lower()
                    or query in (c.get('resource_type') or '').lower()
                    or query in (c.get('content_origin') or '').lower()
                ]
        
        self.update_grid(courses)
        self.results_label.setText(f"{len(courses)} resource{'s' if len(courses) != 1 else ''}")
    
    def update_grid(self, courses):
        """Update course grid."""
        # Clear existing
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Show empty state if no courses
        if not courses:
            if self.current_view == 'downloaded':
                empty_text = "No downloaded resources"
            elif self.current_view == 'imported':
                empty_text = "No imported resources"
            else:
                empty_text = "No created resources"
            empty_label = QLabel(empty_text)
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("color: #718096; font-size: 12pt;")
            self.grid_layout.addWidget(empty_label, 0, 0, 1, self.GRID_COLUMNS)
            self._reset_personal_panel()
            self.downloaded_details_panel.show_empty_state()
            self._update_cards_scroll_height()
            return
        
        # Add course cards (2 columns, 2 rows visible then scroll)
        cols = self.GRID_COLUMNS
        for i, course in enumerate(courses):
            row = i // cols
            col = i % cols
            
            card = ModernCourseCard(course)
            card.clicked.connect(self._on_card_clicked)
            card.action_requested.connect(self.on_card_action)
            self.grid_layout.addWidget(card, row, col)
        
        self._update_cards_scroll_height()
    
    def on_card_action(self, action, course_data):
        """Handle card actions."""
        if action == 'view':
            self._select_course(course_data, self.sender() if isinstance(self.sender(), ModernCourseCard) else None)
            if self.current_view == 'downloaded':
                self.downloaded_details_panel.show_course(course_data)
            else:
                self.course_opened.emit(course_data)

    def _on_card_clicked(self, course_data):
        sender = self.sender() if isinstance(self.sender(), ModernCourseCard) else None
        self._select_course(course_data, sender)

    def _select_course(self, course_data, selected_widget=None):
        for i in range(self.grid_layout.count()):
            widget = self.grid_layout.itemAt(i).widget()
            if isinstance(widget, ModernCourseCard):
                widget.set_selected(False)

        if selected_widget is not None:
            selected_widget.set_selected(True)
            self.selected_card = selected_widget
        self.selected_course = course_data
        if self.current_view == 'downloaded':
            self.downloaded_details_panel.show_course(course_data)
        else:
            self._populate_personal_panel(course_data)

    def _populate_personal_panel(self, course_data):
        course_pk = str(course_data.get('course_pk'))
        state = self.state_data.get("courses", {}).get(course_pk, {})
        self.personal_open_btn.setEnabled(True)
        self.personal_edit_btn.setEnabled(self.current_view in {'created', 'imported'})

        self.personal_course_title.setText(course_data.get('course_name') or "Selected course")
        self.personal_exam_structure.setText(
            f"Exam structure: {self._infer_exam_structure(course_data)}"
        )

        progress = int(state.get("progress", 0))
        self.personal_progress_slider.blockSignals(True)
        self.personal_progress_slider.setValue(progress)
        self.personal_progress_slider.blockSignals(False)
        self.personal_progress_bar.setValue(progress)
        self.personal_progress_label.setText(f"{progress}%")

        exam_type = state.get("exam_type", "No Exam")
        exam_status = state.get("exam_status", "Not Started")
        self.personal_exam_type.blockSignals(True)
        self.personal_exam_type.setCurrentText(exam_type if exam_type in [self.personal_exam_type.itemText(i) for i in range(self.personal_exam_type.count())] else "No Exam")
        self.personal_exam_type.blockSignals(False)
        self.personal_exam_status.blockSignals(True)
        self.personal_exam_status.setCurrentText(exam_status if exam_status in [self.personal_exam_status.itemText(i) for i in range(self.personal_exam_status.count())] else "Not Started")
        self.personal_exam_status.blockSignals(False)

        self.personal_notes_input.setPlainText(state.get("note", ""))
        self.personal_last_reviewed.setText(f"Last reviewed: {state.get('last_reviewed', '-')}")

    def _reset_personal_panel(self):
        self.selected_card = None
        self.selected_course = None
        self.personal_open_btn.setEnabled(False)
        self.personal_edit_btn.setEnabled(False)
        self.personal_course_title.setText("Select a course")
        self.personal_exam_structure.setText("Exam structure: Not set")
        self.personal_progress_slider.blockSignals(True)
        self.personal_progress_slider.setValue(0)
        self.personal_progress_slider.blockSignals(False)
        self.personal_progress_bar.setValue(0)
        self.personal_progress_label.setText("0%")
        self.personal_exam_type.blockSignals(True)
        self.personal_exam_type.setCurrentText("No Exam")
        self.personal_exam_type.blockSignals(False)
        self.personal_exam_status.blockSignals(True)
        self.personal_exam_status.setCurrentText("Not Started")
        self.personal_exam_status.blockSignals(False)
        self.personal_notes_input.clear()
        self.personal_last_reviewed.setText("Last reviewed: -")

    def _infer_exam_structure(self, course_data):
        text = " ".join([
            str(course_data.get('course_name') or ''),
            str(course_data.get('course_description') or ''),
            str(course_data.get('outline') or ''),
            " ".join(course_data.get('tags') or []),
        ]).lower()
        if any(token in text for token in ["exam", "quiz", "assessment", "test", "osce"]):
            return "Exam/Assessment Available"
        return "No Exam Declared"

    def _on_progress_changed(self, value):
        self.personal_progress_bar.setValue(value)
        self.personal_progress_label.setText(f"{value}%")
        self._save_current_course_state(auto=True)

    def _on_exam_field_changed(self, _):
        self._save_current_course_state(auto=True)

    def _save_current_course_state(self, auto=False):
        if not self.selected_course:
            if not auto:
                QMessageBox.information(self, "No Course Selected", "Select a course before saving notes.")
            return

        course_pk = str(self.selected_course.get('course_pk'))
        if "courses" not in self.state_data:
            self.state_data["courses"] = {}
        self.state_data["courses"][course_pk] = {
            "note": self.personal_notes_input.toPlainText().strip(),
            "progress": int(self.personal_progress_slider.value()),
            "exam_type": self.personal_exam_type.currentText(),
            "exam_status": self.personal_exam_status.currentText(),
            "last_reviewed": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.personal_last_reviewed.setText(f"Last reviewed: {self.state_data['courses'][course_pk]['last_reviewed']}")
        self._persist_personal_state()

    def _load_personal_state(self):
        try:
            if MY_COURSE_STATE_PATH.exists():
                with open(MY_COURSE_STATE_PATH, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                    if isinstance(loaded, dict):
                        self.state_data = loaded
        except Exception:
            self.state_data = {"courses": {}}
        if "courses" not in self.state_data:
            self.state_data["courses"] = {}

    def _persist_personal_state(self):
        try:
            MY_COURSE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(MY_COURSE_STATE_PATH, "w", encoding="utf-8") as file:
                json.dump(self.state_data, file, ensure_ascii=True, indent=2)
        except Exception:
            pass

    def _ensure_my_courses_samples(self):
        existing_courses = get_all_courses()
        existing_names = {(c.get('course_name') or '').strip().lower() for c in existing_courses}

        sample_courses = [
            {
                "name": "My MRI Shoulder Follow-Up Pack",
                "description": "Personal review pack with instability, cuff tears, and post-op findings.",
                "author": "Dr. Personal Track",
                "modality": "MRI",
                "body_regions": ["MSK", "Shoulder"],
                "level": "Intermediate",
                "tags": ["Anatomy", "Pathology", "Quiz"],
                "is_my_course": True,
                "is_downloaded": False,
            },
            {
                "name": "My CT Acute Abdomen Crash Notes",
                "description": "Focused checklist for emergency CT abdomen interpretation.",
                "author": "Dr. Personal Track",
                "modality": "CT",
                "body_regions": ["Abdomen"],
                "level": "Basic",
                "tags": ["Emergency", "Trauma"],
                "is_my_course": True,
                "is_downloaded": False,
            },
            {
                "name": "My Spine MRI Daily Checklist",
                "description": "Routine checklist for degenerative spine MRI reporting and follow-up findings.",
                "author": "Dr. Personal Track",
                "modality": "MRI",
                "body_regions": ["Spine"],
                "level": "Intermediate",
                "tags": ["Anatomy", "Pathology"],
                "is_my_course": True,
                "is_downloaded": False,
            },
            {
                "name": "My Emergency Brain CT Summary",
                "description": "Quick personal revision for emergency intracranial bleed patterns and red flags.",
                "author": "Dr. Personal Track",
                "modality": "CT",
                "body_regions": ["Head/Neck"],
                "level": "Intermediate",
                "tags": ["Emergency", "Assessment"],
                "is_my_course": True,
                "is_downloaded": False,
            },
            {
                "name": "Downloaded Neuro MRI Exam Cases",
                "description": "Downloaded case library for neuro board exam preparation.",
                "author": "Online Academy",
                "modality": "MRI",
                "body_regions": ["Head/Neck"],
                "level": "Advanced",
                "tags": ["Exam", "Pathology"],
                "is_my_course": False,
                "is_downloaded": True,
            },
            {
                "name": "Downloaded Chest CT Reporting Drills",
                "description": "Practice drills for structured chest CT reporting.",
                "author": "Online Academy",
                "modality": "CT",
                "body_regions": ["Chest"],
                "level": "Intermediate",
                "tags": ["Assessment", "Emergency"],
                "is_my_course": False,
                "is_downloaded": True,
            },
            {
                "name": "Downloaded Abdomen CT Board Bank",
                "description": "Downloaded board-oriented CT abdomen cases with structured answer templates.",
                "author": "Online Academy",
                "modality": "CT",
                "body_regions": ["Abdomen"],
                "level": "Advanced",
                "tags": ["Exam", "Pathology"],
                "is_my_course": False,
                "is_downloaded": True,
            },
            {
                "name": "Downloaded MSK MRI Spotter Review",
                "description": "Downloaded rapid spotter cases for MSK MRI course completion review.",
                "author": "Online Academy",
                "modality": "MRI",
                "body_regions": ["MSK", "Shoulder"],
                "level": "Intermediate",
                "tags": ["Quiz", "Trauma"],
                "is_my_course": False,
                "is_downloaded": True,
            },
        ]

        for sample in sample_courses:
            name_key = sample["name"].strip().lower()
            if name_key in existing_names:
                continue
            try:
                insert_course(
                    name=sample["name"],
                    description=sample["description"],
                    author=sample["author"],
                    modality=sample["modality"],
                    body_regions=sample["body_regions"],
                    level=sample["level"],
                    tags=sample["tags"],
                    is_my_course=sample["is_my_course"],
                    is_downloaded=sample["is_downloaded"],
                )
                existing_names.add(name_key)
            except Exception:
                continue

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_cards_scroll_height()

    def _update_cards_scroll_height(self):
        target_height = (self.CARD_HEIGHT * self.VISIBLE_ROWS) + (self.GRID_SPACING * (self.VISIBLE_ROWS - 1)) + 10
        available = max(240, self.height() - 180)
        self.cards_scroll.setMaximumHeight(min(target_height, available))


# ==================== BUILD COURSE PAGE ====================

class ItemMetaDialog(QDialog):
    """Dialog for creating or editing a slide item."""

    def __init__(self, course_pk: int, existing_item: Dict[str, Any] = None, parent=None):
        super().__init__(parent)
        self.course_pk = course_pk
        self.existing_item = existing_item or {}
        self.content_type = None
        self.content_data = {}
        self.setWindowTitle("Slide Item")
        self.setMinimumWidth(620)
        self.setup_ui()
        self._load_existing()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        label_style = "color: #e2e8f0; font-size: 11pt; font-weight: 600;"
        field_style = """
            QLineEdit, QTextEdit, QComboBox {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #2a3442;
                border-radius: 2px;
                padding: 8px 10px;
                font-size: 10pt;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #4d8aaf; }
        """

        name_label = QLabel("Item Name *")
        name_label.setStyleSheet(label_style)
        layout.addWidget(name_label)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Pulmonary Embolism CT Axial Review")
        self.name_input.setStyleSheet(field_style)
        layout.addWidget(self.name_input)

        desc_label = QLabel("Item Description")
        desc_label.setStyleSheet(label_style)
        layout.addWidget(desc_label)
        self.desc_input = QTextEdit()
        self.desc_input.setFixedHeight(82)
        self.desc_input.setStyleSheet(field_style)
        self.desc_input.setPlaceholderText("Brief educational note for this item...")
        layout.addWidget(self.desc_input)

        type_label = QLabel("Content Type *")
        type_label.setStyleSheet(label_style)
        layout.addWidget(type_label)
        self.type_combo = QComboBox()
        self.type_combo.addItem("DICOM Image Set", "dicom")
        self.type_combo.addItem("Image", "image")
        self.type_combo.addItem("Audio (Voice)", "audio")
        self.type_combo.addItem("Video", "video")
        self.type_combo.addItem("PDF", "pdf")
        self.type_combo.setStyleSheet(field_style)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.type_combo)

        source_label = QLabel("Content Source *")
        source_label.setStyleSheet(label_style)
        layout.addWidget(source_label)
        source_row = QHBoxLayout()
        source_row.setSpacing(10)
        self.source_input = QLineEdit()
        self.source_input.setReadOnly(True)
        self.source_input.setPlaceholderText("No source selected")
        self.source_input.setStyleSheet(field_style)
        source_row.addWidget(self.source_input, stretch=1)
        self.source_btn = QPushButton("Select")
        self.source_btn.setFixedWidth(140)
        self.source_btn.clicked.connect(self._pick_source)
        self.source_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                padding: 8px 12px;
                font-size: 10pt;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        source_row.addWidget(self.source_btn)
        layout.addLayout(source_row)

        layout.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setFixedWidth(120)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                font-size: 10pt;
            }
            QPushButton:hover { color: #d8e2ee; border-color: #4d7aa0; }
        """)
        actions.addWidget(cancel_btn)
        save_btn = QPushButton("Save Item")
        save_btn.setFixedHeight(40)
        save_btn.setFixedWidth(140)
        save_btn.clicked.connect(self._save)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        actions.addWidget(save_btn)
        layout.addLayout(actions)
        self._on_type_changed()

    def _on_type_changed(self):
        if self.type_combo.currentData() == "dicom":
            self.source_btn.setText("Pick DICOM")
        else:
            self.source_btn.setText("Select File")

    def _load_existing(self):
        if not self.existing_item:
            return
        existing_type = self.existing_item.get("content_type", "")
        existing_data = self.existing_item.get("content_data", {})
        if not isinstance(existing_data, dict):
            existing_data = {}
        self.content_data = dict(existing_data)
        self.content_type = existing_type
        self.name_input.setText(existing_data.get("name", ""))
        self.desc_input.setPlainText(existing_data.get("description", ""))

        if existing_type in {"dicom_study", "dicom_series"}:
            self.type_combo.setCurrentIndex(0)
            if existing_data.get("series_number"):
                self.source_input.setText(
                    f"Study {existing_data.get('study_uid', '')} | Series {existing_data.get('series_number')}"
                )
            else:
                self.source_input.setText(f"Study {existing_data.get('study_uid', '')}")
            return

        idx = self.type_combo.findData(existing_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        if existing_data.get("path"):
            self.source_input.setText(existing_data.get("path"))

    def _pick_source(self):
        type_key = self.type_combo.currentData()
        if type_key == "dicom":
            picker = StudyPickerDialog(self)
            if picker.exec() != QDialog.Accepted:
                return
            selected = picker.get_selected_study()
            if not selected.get("study_uid") or not selected.get("patient_id"):
                QMessageBox.warning(self, "Selection Required", "Please select a valid DICOM study.")
                return
            self.content_data.update({
                "study_uid": selected.get("study_uid"),
                "patient_id": selected.get("patient_id"),
                "mode": selected.get("mode"),
            })
            if selected.get("mode") == "series" and selected.get("series_number") is not None:
                self.content_data["series_number"] = selected.get("series_number")
                self.content_type = "dicom_series"
                self.source_input.setText(
                    f"Study {selected.get('study_uid')} | Series {selected.get('series_number')}"
                )
            else:
                self.content_data.pop("series_number", None)
                self.content_type = "dicom_study"
                self.source_input.setText(f"Study {selected.get('study_uid')}")
            return

        filters = {
            "image": "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
            "audio": "Audio (*.wav *.mp3 *.ogg *.m4a *.aac)",
            "video": "Videos (*.mp4 *.avi *.mov *.mkv *.wmv)",
            "pdf": "PDF (*.pdf)",
        }
        selected_file, _ = QFileDialog.getOpenFileName(
            self, "Select Content File", "", filters.get(type_key, "All Files (*)")
        )
        if not selected_file:
            return
        try:
            saved_path = save_course_asset(selected_file, self.course_pk)
        except Exception as exc:
            QMessageBox.critical(self, "Import Failed", f"Could not import file:\n{exc}")
            return
        self.content_data["path"] = saved_path
        self.content_type = type_key
        self.source_input.setText(saved_path)

    def _save(self):
        item_name = self.name_input.text().strip()
        if not item_name:
            QMessageBox.warning(self, "Validation Error", "Item name is required.")
            return
        type_key = self.type_combo.currentData()
        if type_key == "dicom":
            if not self.content_data.get("study_uid") or not self.content_data.get("patient_id"):
                QMessageBox.warning(self, "Validation Error", "Please select a DICOM study or series.")
                return
            if not self.content_type:
                self.content_type = "dicom_study"
        else:
            if not self.content_data.get("path"):
                QMessageBox.warning(self, "Validation Error", "Please select a content file.")
                return
            self.content_type = type_key
        self.content_data["name"] = item_name
        self.content_data["description"] = self.desc_input.toPlainText().strip()
        self.accept()

    def get_payload(self) -> Dict[str, Any]:
        return {"content_type": self.content_type, "content_data": self.content_data}

class BuildCoursePage(QWidget):
    """Build Course tab with two-step workflow for card + slides."""

    FILTER_TAGS = ["Anatomy", "Pathology", "Trauma", "Oncology", "Pediatric", "Emergency"]
    course_created = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.course_pk = None
        self.course_data = None
        self.cover_image_source = ""
        self.slides_cache: List[Dict[str, Any]] = []
        self.items_cache: List[Dict[str, Any]] = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(12)

        title = QLabel("Build Course")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f7fafc;")
        layout.addWidget(title)

        subtitle = QLabel("Step 1: define course card data. Step 2: create and order slides/items.")
        subtitle.setStyleSheet("color: #9fb1c5; font-size: 11pt;")
        layout.addWidget(subtitle)

        step_row = QHBoxLayout()
        step_row.setSpacing(10)
        self.step_one_badge = QLabel("1  Course Card")
        self.step_two_badge = QLabel("2  Slides and Content")
        for badge in (self.step_one_badge, self.step_two_badge):
            badge.setStyleSheet(
                "QLabel { background-color: #111722; color: #95a8bd; border: 1px solid #2a3442; "
                "padding: 7px 12px; border-radius: 2px; font-size: 10pt; }"
            )
            step_row.addWidget(badge)
        step_row.addStretch()
        layout.addLayout(step_row)

        self.step_stack = QStackedWidget()
        self.step_stack.addWidget(self._build_step_one())
        self.step_stack.addWidget(self._build_step_two())
        layout.addWidget(self.step_stack, stretch=1)

        self._set_step(1)

    def _set_step(self, step_number: int):
        self.step_stack.setCurrentIndex(0 if step_number == 1 else 1)
        active_style = (
            "QLabel { background-color: #1f4a67; color: #e8f0f8; border: 1px solid #2f6c90; "
            "padding: 7px 12px; border-radius: 2px; font-size: 10pt; font-weight: 600; }"
        )
        inactive_style = (
            "QLabel { background-color: #111722; color: #95a8bd; border: 1px solid #2a3442; "
            "padding: 7px 12px; border-radius: 2px; font-size: 10pt; }"
        )
        self.step_one_badge.setStyleSheet(active_style if step_number == 1 else inactive_style)
        self.step_two_badge.setStyleSheet(active_style if step_number == 2 else inactive_style)

    def _build_step_one(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(0)

        form_container = QWidget()
        form_container.setMaximumWidth(1150)
        form = QVBoxLayout(form_container)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(16)

        field_style = """
            QLineEdit, QTextEdit, QComboBox {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #1f2a37;
                border-radius: 2px;
                padding: 9px 11px;
                font-size: 10pt;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 1px solid #4d8aaf;
                background-color: #131b25;
            }
        """
        label_style = "color: #d9e3ef; font-size: 11pt; font-weight: 600;"

        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        left_block = QVBoxLayout()
        left_block.setSpacing(10)
        name_label = QLabel("Course Name *")
        name_label.setStyleSheet(label_style)
        left_block.addWidget(name_label)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("e.g., MRI Shoulder Instability")
        self.title_input.setStyleSheet(field_style)
        self.title_input.setMinimumHeight(42)
        left_block.addWidget(self.title_input)

        instructor_label = QLabel("Instructor *")
        instructor_label.setStyleSheet(label_style)
        left_block.addWidget(instructor_label)
        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("e.g., Dr. Leila N")
        self.author_input.setStyleSheet(field_style)
        self.author_input.setMinimumHeight(42)
        left_block.addWidget(self.author_input)
        top_row.addLayout(left_block, stretch=2)

        cover_block = QVBoxLayout()
        cover_block.setSpacing(10)
        cover_label = QLabel("Course Cover Image")
        cover_label.setStyleSheet(label_style)
        cover_block.addWidget(cover_label)
        self.cover_preview = QLabel("No image selected")
        self.cover_preview.setFixedSize(240, 150)
        self.cover_preview.setAlignment(Qt.AlignCenter)
        self.cover_preview.setStyleSheet(
            "QLabel { background-color: #0d1117; color: #7f8fa3; border: 1px solid #2a3442; border-radius: 2px; }"
        )
        cover_block.addWidget(self.cover_preview)
        cover_btn = QPushButton("Choose Image")
        cover_btn.setFixedHeight(38)
        cover_btn.setStyleSheet("""
            QPushButton {
                background-color: #1f4a67;
                color: #e6eef8;
                border: 1px solid #2f6c90;
                border-radius: 2px;
                font-size: 10pt;
            }
            QPushButton:hover { background-color: #2d5f82; }
        """)
        cover_btn.clicked.connect(self._pick_cover_image)
        cover_block.addWidget(cover_btn)
        cover_block.addStretch()
        top_row.addLayout(cover_block, stretch=1)
        form.addLayout(top_row)

        desc_label = QLabel("Course Description")
        desc_label.setStyleSheet(label_style)
        form.addWidget(desc_label)
        self.desc_input = QTextEdit()
        self.desc_input.setFixedHeight(94)
        self.desc_input.setStyleSheet(field_style)
        self.desc_input.setPlaceholderText("Brief educational summary of this course...")
        form.addWidget(self.desc_input)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(16)

        modality_col = QVBoxLayout()
        modality_col.setSpacing(8)
        modality_label = QLabel("Modality")
        modality_label.setStyleSheet(label_style)
        modality_col.addWidget(modality_label)
        self.modality_combo = QComboBox()
        self.modality_combo.addItems(MODALITIES)
        self.modality_combo.setStyleSheet(field_style)
        self.modality_combo.setMinimumHeight(42)
        modality_col.addWidget(self.modality_combo)
        meta_row.addLayout(modality_col, stretch=1)

        level_col = QVBoxLayout()
        level_col.setSpacing(8)
        level_label = QLabel("Difficulty")
        level_label.setStyleSheet(label_style)
        level_col.addWidget(level_label)
        self.level_combo = QComboBox()
        self.level_combo.addItems(LEVELS)
        self.level_combo.setCurrentText("Intermediate")
        self.level_combo.setStyleSheet(field_style)
        self.level_combo.setMinimumHeight(42)
        level_col.addWidget(self.level_combo)
        meta_row.addLayout(level_col, stretch=1)

        visibility_col = QVBoxLayout()
        visibility_col.setSpacing(8)
        visibility_label = QLabel("Visibility Tag")
        visibility_label.setStyleSheet(label_style)
        visibility_col.addWidget(visibility_label)
        self.visibility_combo = QComboBox()
        self.visibility_combo.addItems(["Public", "Private"])
        self.visibility_combo.setStyleSheet(field_style)
        self.visibility_combo.setMinimumHeight(42)
        visibility_col.addWidget(self.visibility_combo)
        meta_row.addLayout(visibility_col, stretch=1)
        form.addLayout(meta_row)

        checklist_box_style = """
            QFrame {
                background-color: #111722;
                border: 1px solid #1f2a37;
                border-radius: 2px;
            }
            QCheckBox {
                color: #e2e8f0;
                font-size: 10.5pt;
                spacing: 8px;
                padding: 3px 0;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border: 1px solid #4d6a8f;
                background-color: #0d1117;
            }
            QCheckBox::indicator:checked {
                background-color: #3d7a9f;
                border-color: #4d8aaf;
            }
        """

        selector_row = QHBoxLayout()
        selector_row.setSpacing(16)

        regions_box = QFrame()
        regions_box.setStyleSheet(checklist_box_style)
        regions_layout = QVBoxLayout(regions_box)
        regions_layout.setContentsMargins(12, 10, 12, 12)
        regions_layout.setSpacing(8)
        regions_title = QLabel("Body Regions (Library Filters)")
        regions_title.setStyleSheet(label_style)
        regions_layout.addWidget(regions_title)
        regions_grid = QGridLayout()
        regions_grid.setHorizontalSpacing(12)
        regions_grid.setVerticalSpacing(4)
        self.region_checks = []
        for index, name in enumerate(BODY_REGIONS):
            cb = QCheckBox(name)
            self.region_checks.append(cb)
            regions_grid.addWidget(cb, index // 2, index % 2)
        regions_layout.addLayout(regions_grid)
        selector_row.addWidget(regions_box, stretch=1)

        tags_box = QFrame()
        tags_box.setStyleSheet(checklist_box_style)
        tags_layout = QVBoxLayout(tags_box)
        tags_layout.setContentsMargins(12, 10, 12, 12)
        tags_layout.setSpacing(8)
        tags_title = QLabel("Tags (Library Filters)")
        tags_title.setStyleSheet(label_style)
        tags_layout.addWidget(tags_title)
        tags_grid = QGridLayout()
        tags_grid.setHorizontalSpacing(12)
        tags_grid.setVerticalSpacing(4)
        self.tag_checks = []
        for index, tag in enumerate(self.FILTER_TAGS):
            cb = QCheckBox(tag)
            self.tag_checks.append(cb)
            tags_grid.addWidget(cb, index // 2, index % 2)
        tags_layout.addLayout(tags_grid)
        selector_row.addWidget(tags_box, stretch=1)

        form.addLayout(selector_row)

        actions = QHBoxLayout()
        actions.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(42)
        clear_btn.setFixedWidth(130)
        clear_btn.clicked.connect(self._clear_step_one)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                font-size: 10pt;
            }
            QPushButton:hover { color: #d8e2ee; border-color: #4d7aa0; }
        """)
        actions.addWidget(clear_btn)

        create_btn = QPushButton("Create Card and Continue")
        create_btn.setFixedHeight(42)
        create_btn.setMinimumWidth(230)
        create_btn.clicked.connect(self._create_course_card)
        create_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        actions.addWidget(create_btn)
        form.addLayout(actions)

        root.addStretch()
        root.addWidget(form_container)
        root.addStretch()
        return page

    def _build_step_two(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.step_two_title = QLabel("No course selected")
        self.step_two_title.setStyleSheet("color: #e2e8f0; font-size: 13pt; font-weight: 600;")
        header.addWidget(self.step_two_title)
        header.addStretch()

        back_btn = QPushButton("Back to Card Data")
        back_btn.setFixedHeight(38)
        back_btn.clicked.connect(lambda: self._set_step(1))
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 12px;
                font-size: 10pt;
            }
            QPushButton:hover { color: #d8e2ee; border-color: #4d7aa0; }
        """)
        header.addWidget(back_btn)

        finish_btn = QPushButton("Finish Course Setup")
        finish_btn.setFixedHeight(38)
        finish_btn.setMinimumWidth(190)
        finish_btn.clicked.connect(self._finish_course_setup)
        finish_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        header.addWidget(finish_btn)
        root.addLayout(header)

        main = QHBoxLayout()
        main.setSpacing(12)

        left = QFrame()
        left.setFixedWidth(370)
        left.setStyleSheet("QFrame { background-color: #111722; border: 1px solid #1f2a37; border-radius: 2px; }")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)

        slides_label = QLabel("Slides")
        slides_label.setStyleSheet("color: #e2e8f0; font-size: 12pt; font-weight: 600;")
        left_layout.addWidget(slides_label)

        self.slides_list = QListWidget()
        self.slides_list.setMinimumHeight(380)
        self.slides_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1117;
                color: #dbe5ef;
                border: 1px solid #273140;
                font-size: 10.5pt;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #1d2734;
            }
            QListWidget::item:selected {
                background-color: #1f4a67;
                color: #f4f8fd;
            }
        """)
        self.slides_list.currentRowChanged.connect(self._on_slide_selected)
        left_layout.addWidget(self.slides_list, stretch=1)

        slide_buttons = QGridLayout()
        slide_buttons.setHorizontalSpacing(8)
        slide_buttons.setVerticalSpacing(8)

        add_slide_btn = QPushButton("Add Slide")
        add_slide_btn.clicked.connect(self._add_slide)
        del_slide_btn = QPushButton("Delete Slide")
        del_slide_btn.clicked.connect(self._delete_slide)
        up_slide_btn = QPushButton("Move Up")
        up_slide_btn.clicked.connect(lambda: self._move_slide(-1))
        down_slide_btn = QPushButton("Move Down")
        down_slide_btn.clicked.connect(lambda: self._move_slide(1))
        for btn in (add_slide_btn, del_slide_btn, up_slide_btn, down_slide_btn):
            btn.setFixedHeight(34)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1f4a67;
                    color: #e8f0f8;
                    border: 1px solid #2f6c90;
                    border-radius: 2px;
                    font-size: 9.5pt;
                }
                QPushButton:hover { background-color: #2d5f82; }
            """)
        slide_buttons.addWidget(add_slide_btn, 0, 0)
        slide_buttons.addWidget(del_slide_btn, 0, 1)
        slide_buttons.addWidget(up_slide_btn, 1, 0)
        slide_buttons.addWidget(down_slide_btn, 1, 1)
        left_layout.addLayout(slide_buttons)
        main.addWidget(left)

        right = QFrame()
        right.setStyleSheet("QFrame { background-color: #111722; border: 1px solid #1f2a37; border-radius: 2px; }")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(10)

        slide_name_label = QLabel("Slide Name")
        slide_name_label.setStyleSheet("color: #e2e8f0; font-size: 11pt; font-weight: 600;")
        right_layout.addWidget(slide_name_label)
        self.slide_name_input = QLineEdit()
        self.slide_name_input.setPlaceholderText("e.g., Initial MRI Findings")
        self.slide_name_input.setStyleSheet("""
            QLineEdit {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #273140;
                border-radius: 2px;
                padding: 8px 10px;
                font-size: 10.5pt;
            }
        """)
        right_layout.addWidget(self.slide_name_input)

        slide_desc_label = QLabel("Slide Description")
        slide_desc_label.setStyleSheet("color: #e2e8f0; font-size: 11pt; font-weight: 600;")
        right_layout.addWidget(slide_desc_label)
        self.slide_desc_input = QTextEdit()
        self.slide_desc_input.setFixedHeight(96)
        self.slide_desc_input.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #273140;
                border-radius: 2px;
                padding: 8px 10px;
                font-size: 10.5pt;
            }
        """)
        right_layout.addWidget(self.slide_desc_input)

        save_slide_btn = QPushButton("Save Slide Metadata")
        save_slide_btn.setFixedHeight(36)
        save_slide_btn.clicked.connect(self._save_slide)
        save_slide_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        right_layout.addWidget(save_slide_btn)

        items_header = QHBoxLayout()
        items_title = QLabel("Slide Items (max 5)")
        items_title.setStyleSheet("color: #e2e8f0; font-size: 11pt; font-weight: 600;")
        items_header.addWidget(items_title)
        items_header.addStretch()
        helper = QLabel("Types: DICOM, Image, Audio, Video, PDF")
        helper.setStyleSheet("color: #8fa2b7; font-size: 9.5pt;")
        items_header.addWidget(helper)
        right_layout.addLayout(items_header)

        self.items_list = QListWidget()
        self.items_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1117;
                color: #dbe5ef;
                border: 1px solid #273140;
                font-size: 10.2pt;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #1d2734;
            }
            QListWidget::item:selected {
                background-color: #1f4a67;
                color: #f4f8fd;
            }
        """)
        right_layout.addWidget(self.items_list, stretch=1)

        item_buttons = QGridLayout()
        item_buttons.setHorizontalSpacing(8)
        item_buttons.setVerticalSpacing(8)
        add_item_btn = QPushButton("Add Item")
        add_item_btn.clicked.connect(self._add_item)
        edit_item_btn = QPushButton("Edit Item")
        edit_item_btn.clicked.connect(self._edit_item)
        delete_item_btn = QPushButton("Remove Item")
        delete_item_btn.clicked.connect(self._delete_item)
        up_item_btn = QPushButton("Item Up")
        up_item_btn.clicked.connect(lambda: self._move_item(-1))
        down_item_btn = QPushButton("Item Down")
        down_item_btn.clicked.connect(lambda: self._move_item(1))
        self.item_action_buttons = [add_item_btn, edit_item_btn, delete_item_btn, up_item_btn, down_item_btn]
        for btn in self.item_action_buttons:
            btn.setFixedHeight(34)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1f4a67;
                    color: #e8f0f8;
                    border: 1px solid #2f6c90;
                    border-radius: 2px;
                    font-size: 9.5pt;
                }
                QPushButton:hover { background-color: #2d5f82; }
            """)
        item_buttons.addWidget(add_item_btn, 0, 0)
        item_buttons.addWidget(edit_item_btn, 0, 1)
        item_buttons.addWidget(delete_item_btn, 0, 2)
        item_buttons.addWidget(up_item_btn, 1, 0)
        item_buttons.addWidget(down_item_btn, 1, 1)
        right_layout.addLayout(item_buttons)

        main.addWidget(right, stretch=1)
        root.addLayout(main, stretch=1)
        self._set_slide_edit_enabled(False)
        return page

    def _pick_cover_image(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self, "Select Course Cover", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if not selected_file:
            return
        self.cover_image_source = selected_file
        pixmap = QPixmap(selected_file)
        if pixmap.isNull():
            self.cover_preview.setText(Path(selected_file).name)
            self.cover_preview.setPixmap(QPixmap())
            return
        self.cover_preview.setPixmap(
            pixmap.scaled(self.cover_preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        )

    def _clear_step_one(self):
        self.title_input.clear()
        self.author_input.clear()
        self.desc_input.clear()
        self.modality_combo.setCurrentIndex(0)
        self.level_combo.setCurrentText("Intermediate")
        self.visibility_combo.setCurrentText("Public")
        self.cover_image_source = ""
        self.cover_preview.setPixmap(QPixmap())
        self.cover_preview.setText("No image selected")
        for cb in self.region_checks + self.tag_checks:
            cb.setChecked(False)

    def _selected_checks(self, checks: List[QCheckBox]) -> List[str]:
        return [check.text() for check in checks if check.isChecked()]

    def _set_slide_edit_enabled(self, enabled: bool):
        self.slide_name_input.setEnabled(enabled)
        self.slide_desc_input.setEnabled(enabled)
        self.items_list.setEnabled(enabled)
        for btn in self.item_action_buttons:
            btn.setEnabled(enabled)

    def load_course_for_edit(self, course_pk: int):
        """Load an existing course into Build Course for continued editing."""
        course_full = get_course_with_slides(course_pk)
        if not course_full:
            QMessageBox.warning(self, "Course Not Found", "Could not load selected course for editing.")
            return

        self.course_pk = course_pk

        tags_value = course_full.get("tags", [])
        if isinstance(tags_value, str):
            try:
                tags_value = json.loads(tags_value)
            except Exception:
                tags_value = []
        if not isinstance(tags_value, list):
            tags_value = []

        regions_value = course_full.get("body_regions", [])
        if isinstance(regions_value, str):
            try:
                regions_value = json.loads(regions_value)
            except Exception:
                regions_value = []
        if not isinstance(regions_value, list):
            regions_value = []

        visibility = "Public"
        outline_raw = course_full.get("outline")
        if isinstance(outline_raw, str) and outline_raw.strip():
            try:
                outline_payload = json.loads(outline_raw)
                if isinstance(outline_payload, dict):
                    visibility = str(outline_payload.get("visibility") or "Public")
            except Exception:
                visibility = "Public"

        self.title_input.setText(str(course_full.get("course_name") or ""))
        self.author_input.setText(str(course_full.get("author_name") or ""))
        self.desc_input.setPlainText(str(course_full.get("course_description") or ""))

        modality = str(course_full.get("modality") or "")
        modality_index = self.modality_combo.findText(modality)
        self.modality_combo.setCurrentIndex(modality_index if modality_index >= 0 else 0)

        level = str(course_full.get("level") or "Intermediate")
        level_index = self.level_combo.findText(level)
        self.level_combo.setCurrentIndex(level_index if level_index >= 0 else self.level_combo.findText("Intermediate"))

        visibility_index = self.visibility_combo.findText(visibility)
        self.visibility_combo.setCurrentIndex(visibility_index if visibility_index >= 0 else 0)

        selected_regions = {str(value) for value in regions_value}
        for checkbox in self.region_checks:
            checkbox.setChecked(checkbox.text() in selected_regions)

        selected_tags = {str(value) for value in tags_value}
        for checkbox in self.tag_checks:
            checkbox.setChecked(checkbox.text() in selected_tags)

        thumbnail_path = str(course_full.get("thumbnail_path") or "")
        self.cover_image_source = thumbnail_path
        if thumbnail_path and Path(thumbnail_path).exists():
            pixmap = QPixmap(thumbnail_path)
            self.cover_preview.setPixmap(
                pixmap.scaled(self.cover_preview.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            )
        else:
            self.cover_preview.setPixmap(QPixmap())
            self.cover_preview.setText("No image selected")

        self.course_data = {
            "course_pk": course_pk,
            "course_name": str(course_full.get("course_name") or ""),
            "author_name": str(course_full.get("author_name") or ""),
            "course_description": str(course_full.get("course_description") or ""),
            "modality": modality,
            "level": level,
            "tags": tags_value,
            "body_regions": regions_value,
            "thumbnail_path": thumbnail_path,
            "visibility": visibility,
        }

        self.step_two_title.setText(
            f"Course: {self.course_data['course_name']} | Visibility: {visibility} | Modality: {modality or 'N/A'}"
        )
        self._set_step(2)
        self._load_slides()

    def _create_course_card(self):
        course_name = self.title_input.text().strip()
        instructor = self.author_input.text().strip()
        if not course_name:
            QMessageBox.warning(self, "Validation Error", "Course name is required.")
            return
        if not instructor:
            QMessageBox.warning(self, "Validation Error", "Instructor name is required.")
            return

        description = self.desc_input.toPlainText().strip()
        modality = self.modality_combo.currentText()
        level = self.level_combo.currentText()
        visibility = self.visibility_combo.currentText()
        body_regions = self._selected_checks(self.region_checks)
        tags = self._selected_checks(self.tag_checks)
        card_metadata = {"visibility": visibility}

        try:
            course_pk = insert_course(
                name=course_name,
                description=description,
                author=instructor,
                outline=json.dumps(card_metadata, ensure_ascii=True),
                modality=modality,
                body_regions=body_regions,
                level=level,
                tags=tags,
                is_my_course=True,
                is_downloaded=False,
            )

            thumbnail_path = None
            if self.cover_image_source:
                thumbnail_path = save_course_asset(self.cover_image_source, course_pk)
                update_course(course_pk, thumbnail_path=thumbnail_path)

            self.course_pk = course_pk
            self.course_data = {
                "course_pk": course_pk,
                "course_name": course_name,
                "author_name": instructor,
                "course_description": description,
                "modality": modality,
                "level": level,
                "tags": tags,
                "body_regions": body_regions,
                "thumbnail_path": thumbnail_path,
                "visibility": visibility,
            }
            self.step_two_title.setText(
                f"Course: {course_name} | Visibility: {visibility} | Modality: {modality}"
            )
            self._set_step(2)
            self._load_slides()
            QMessageBox.information(
                self, "Step 1 Completed", "Course card data created. Continue by adding slides and slide items."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to create course card:\n{exc}")

    def _finish_course_setup(self):
        if not self.course_data:
            QMessageBox.warning(self, "No Course", "Please complete course card data first.")
            return
        self.course_created.emit(self.course_data)
        self._reset_builder()

    def _reset_builder(self):
        self.course_pk = None
        self.course_data = None
        self.slides_cache = []
        self.items_cache = []
        self.slides_list.clear()
        self.items_list.clear()
        self.slide_name_input.clear()
        self.slide_desc_input.clear()
        self.step_two_title.setText("No course selected")
        self._set_slide_edit_enabled(False)
        self._clear_step_one()
        self._set_step(1)

    def _load_slides(self, select_slide_pk: int = None):
        self.slides_list.clear()
        self.slide_name_input.clear()
        self.slide_desc_input.clear()
        self.items_list.clear()
        self.items_cache = []

        if not self.course_pk:
            self.slides_cache = []
            self._set_slide_edit_enabled(False)
            return

        self.slides_cache = get_slides_for_course(self.course_pk)
        for slide in self.slides_cache:
            title = slide.get("slide_title", "") or "Untitled Slide"
            display = f"{slide.get('slide_order', 0)}. {title}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, slide)
            self.slides_list.addItem(item)

        if not self.slides_cache:
            self._set_slide_edit_enabled(False)
            return

        target_row = 0
        if select_slide_pk is not None:
            for idx, slide in enumerate(self.slides_cache):
                if slide.get("slide_pk") == select_slide_pk:
                    target_row = idx
                    break
        self.slides_list.setCurrentRow(target_row)

    def _on_slide_selected(self, row: int):
        if row < 0 or row >= len(self.slides_cache):
            self._set_slide_edit_enabled(False)
            self.slide_name_input.clear()
            self.slide_desc_input.clear()
            self.items_list.clear()
            self.items_cache = []
            return

        self._set_slide_edit_enabled(True)
        slide = self.slides_cache[row]
        self.slide_name_input.setText(slide.get("slide_title", "") or "")
        self.slide_desc_input.setPlainText(slide.get("slide_notes", "") or "")
        self._load_items()

    def _add_slide(self):
        if not self.course_pk:
            QMessageBox.warning(self, "No Course", "Complete Step 1 before adding slides.")
            return
        try:
            slide_order = len(self.slides_cache) + 1
            slide_pk = insert_slide(
                course_fk=self.course_pk,
                slide_order=slide_order,
                title=f"Slide {slide_order}",
                notes="",
            )
            self._load_slides(select_slide_pk=slide_pk)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to add slide:\n{exc}")

    def _save_slide(self):
        current_row = self.slides_list.currentRow()
        if current_row < 0 or current_row >= len(self.slides_cache):
            QMessageBox.warning(self, "No Slide", "Select a slide first.")
            return
        slide = self.slides_cache[current_row]
        new_title = self.slide_name_input.text().strip() or f"Slide {slide.get('slide_order', current_row + 1)}"
        new_notes = self.slide_desc_input.toPlainText().strip()
        try:
            update_slide(slide_pk=slide["slide_pk"], title=new_title, notes=new_notes)
            self._load_slides(select_slide_pk=slide["slide_pk"])
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save slide:\n{exc}")

    def _delete_slide(self):
        current_row = self.slides_list.currentRow()
        if current_row < 0 or current_row >= len(self.slides_cache):
            return
        slide = self.slides_cache[current_row]
        confirm = QMessageBox.question(
            self,
            "Delete Slide",
            f"Delete '{slide.get('slide_title') or 'Untitled Slide'}' and all its items?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            delete_slide(slide["slide_pk"])
            self._load_slides()
            self._normalize_slide_order()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to delete slide:\n{exc}")

    def _move_slide(self, direction: int):
        current_row = self.slides_list.currentRow()
        target_row = current_row + direction
        if current_row < 0 or target_row < 0 or target_row >= len(self.slides_cache):
            return
        order_list = [slide["slide_pk"] for slide in self.slides_cache]
        order_list[current_row], order_list[target_row] = order_list[target_row], order_list[current_row]
        try:
            reorder_slides(self.course_pk, order_list)
            moved_pk = order_list[target_row]
            self._load_slides(select_slide_pk=moved_pk)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to reorder slides:\n{exc}")

    def _normalize_slide_order(self):
        if not self.course_pk:
            return
        slides = get_slides_for_course(self.course_pk)
        if not slides:
            return
        reorder_slides(self.course_pk, [slide["slide_pk"] for slide in slides])
        self._load_slides()

    def _load_items(self, select_content_pk: int = None):
        self.items_list.clear()
        self.items_cache = []
        current_row = self.slides_list.currentRow()
        if current_row < 0 or current_row >= len(self.slides_cache):
            return

        slide_pk = self.slides_cache[current_row]["slide_pk"]
        self.items_cache = get_content_for_slide(slide_pk)
        for item in self.items_cache:
            content_type = item.get("content_type", "unknown")
            content_data = item.get("content_data", {})
            if not isinstance(content_data, dict):
                content_data = {}
            display_name = (
                content_data.get("name")
                or content_data.get("title")
                or Path(content_data.get("path", "")).name
                or "Untitled item"
            )
            line = f"{item.get('content_order', 0)}. {content_type.upper()} | {display_name}"
            list_item = QListWidgetItem(line)
            list_item.setData(Qt.UserRole, item)
            self.items_list.addItem(list_item)

        if not self.items_cache:
            return
        target_row = 0
        if select_content_pk is not None:
            for idx, item in enumerate(self.items_cache):
                if item.get("content_pk") == select_content_pk:
                    target_row = idx
                    break
        self.items_list.setCurrentRow(target_row)

    def _add_item(self):
        current_row = self.slides_list.currentRow()
        if current_row < 0 or current_row >= len(self.slides_cache):
            QMessageBox.warning(self, "No Slide", "Select a slide first.")
            return
        if len(self.items_cache) >= 5:
            QMessageBox.warning(self, "Limit Reached", "Each slide can contain up to 5 items.")
            return
        dialog = ItemMetaDialog(course_pk=self.course_pk, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.get_payload()
        try:
            slide_pk = self.slides_cache[current_row]["slide_pk"]
            insert_slide_content(
                slide_fk=slide_pk,
                content_type=payload["content_type"],
                content_order=len(self.items_cache) + 1,
                content_data=payload["content_data"],
            )
            self._load_items()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to add item:\n{exc}")

    def _edit_item(self):
        selected_item = self.items_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Item", "Select an item to edit.")
            return
        item_data = selected_item.data(Qt.UserRole)
        dialog = ItemMetaDialog(course_pk=self.course_pk, existing_item=item_data, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.get_payload()
        try:
            update_slide_content(
                content_pk=item_data["content_pk"],
                content_type=payload["content_type"],
                content_data=payload["content_data"],
            )
            self._load_items(select_content_pk=item_data["content_pk"])
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to update item:\n{exc}")

    def _delete_item(self):
        selected_item = self.items_list.currentItem()
        if not selected_item:
            return
        item_data = selected_item.data(Qt.UserRole)
        confirm = QMessageBox.question(
            self,
            "Remove Item",
            "Remove selected item from this slide?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            delete_slide_content(item_data["content_pk"])
            self._load_items()
            self._normalize_item_order()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to remove item:\n{exc}")

    def _move_item(self, direction: int):
        current_row = self.items_list.currentRow()
        target_row = current_row + direction
        if current_row < 0 or target_row < 0 or target_row >= len(self.items_cache):
            return
        ordered_items = list(self.items_cache)
        ordered_items[current_row], ordered_items[target_row] = ordered_items[target_row], ordered_items[current_row]
        try:
            for order, item in enumerate(ordered_items, start=1):
                update_slide_content(content_pk=item["content_pk"], content_order=order)
            moved_pk = ordered_items[target_row]["content_pk"]
            self._load_items(select_content_pk=moved_pk)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to reorder items:\n{exc}")

    def _normalize_item_order(self):
        current_row = self.slides_list.currentRow()
        if current_row < 0 or current_row >= len(self.slides_cache):
            return
        slide_pk = self.slides_cache[current_row]["slide_pk"]
        current_items = get_content_for_slide(slide_pk)
        for order, item in enumerate(current_items, start=1):
            update_slide_content(content_pk=item["content_pk"], content_order=order)
        self._load_items()


# ==================== MAIN EDUCATION MODULE ====================

class EducationModuleRedesigned(QWidget):
    """Main education module widget with three tabs."""
    
    def __init__(self, parent=None, host_tab_widget=None, host_custom_tab_manager=None, host_parent=None):
        super().__init__(parent)
        self.host_tab_widget = host_tab_widget
        self.host_custom_tab_manager = host_custom_tab_manager
        self.host_parent = host_parent
        self.setup_ui()

    def set_tab_host(self, tab_widget=None, custom_tab_manager=None, host_parent=None):
        """Allow caller to inject the outer top-tab host explicitly."""
        self.host_tab_widget = tab_widget
        self.host_custom_tab_manager = custom_tab_manager
        self.host_parent = host_parent

    def _resolve_tab_host(self):
        """
        Resolve the outer top-level tab host where Educational Course tabs should open.
        Returns: (tab_widget, custom_tab_manager, owner_object)
        """
        # 1) Explicit host from constructor/setter (most reliable path)
        if self.host_tab_widget is not None:
            return self.host_tab_widget, self.host_custom_tab_manager, self.host_parent

        # 2) Walk QObject parent chain
        parent = self.parent()
        while parent:
            if hasattr(parent, 'tab_widget'):
                return (
                    getattr(parent, 'tab_widget', None),
                    getattr(parent, 'custom_tab_manager', None),
                    parent,
                )
            parent = parent.parent() if hasattr(parent, 'parent') else None

        # 3) Fallback: check window container
        win = self.window()
        if win and hasattr(win, 'tab_widget'):
            return (
                getattr(win, 'tab_widget', None),
                getattr(win, 'custom_tab_manager', None),
                win,
            )

        return None, None, None
    
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
        self.mycourses_page.case_of_day_opened.connect(self.on_case_of_day_opened)
        self.build_page.course_created.connect(self.on_course_created)
    
    def on_course_opened(self, course_data):
        """Handle course open request."""
        print(f"Opening educational course viewer: {course_data['course_name']}")

        try:
            from PacsClient.pacs.education.educational_patient_viewer_widget import EducationalCourseViewerWidget

            course_pk = course_data.get('course_pk')
            course_full = get_course_with_slides(course_pk) if course_pk else None
            if not course_full:
                course_full = dict(course_data)
                course_full.setdefault('slides', [])

            host_tab_widget, host_custom_tab_manager, host_owner = self._resolve_tab_host()
            viewer = EducationalCourseViewerWidget(course_full, parent=host_owner if host_owner else self)
            course_name = str(course_full.get('course_name') or 'Course')

            if host_custom_tab_manager:
                if hasattr(host_custom_tab_manager, 'add_educational_course_tab'):
                    host_custom_tab_manager.add_educational_course_tab(
                        course_name=course_name,
                        course_pk=course_full.get('course_pk'),
                        widget=viewer,
                        activate=True,
                    )
                else:
                    tab_index = host_tab_widget.addTab(viewer, f"Educational Course - {course_name}")
                    host_tab_widget.setCurrentIndex(tab_index)
            elif host_tab_widget is not None:
                tab_index = host_tab_widget.addTab(viewer, f"Educational Course - {course_name}")
                host_tab_widget.setCurrentIndex(tab_index)
            else:
                viewer.setWindowTitle(f"Educational Course - {course_name}")
                viewer.showMaximized()

        except Exception as e:
            print(f"Error opening course: {e}")
            import traceback
            traceback.print_exc()

    def on_course_edited(self, course_data):
        """Handle course edit request."""
        try:
            from PacsClient.pacs.education.course_editor_widget import CourseEditorWidget

            host_tab_widget, _, host_owner = self._resolve_tab_host()
            editor = CourseEditorWidget(course_data['course_pk'], parent=host_owner if host_owner else self)

            if host_tab_widget is not None:
                tab_index = host_tab_widget.addTab(editor, f"Edit: {course_data['course_name']}")
                host_tab_widget.setCurrentIndex(tab_index)
            else:
                editor.setWindowTitle(f"Edit Course - {course_data['course_name']}")
                editor.showMaximized()

        except Exception as e:
            print(f"Error opening course editor: {e}")
            import traceback
            traceback.print_exc()
    
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

    def on_case_of_day_opened(self, payload: Dict[str, Any]):
        try:
            from PacsClient.pacs.education.case_of_day_database import get_case
            from PacsClient.pacs.education.case_of_day_viewer_widget import CaseOfDayViewerWidget

            case_pk = int(payload.get("case_pk"))
            entry = get_case(case_pk)
            if not entry:
                QMessageBox.warning(self, "Case Not Found", "Could not find selected Case of the Day entry.")
                return

            case_data = {
                "case_pk": entry.case_pk,
                "saved_by": entry.saved_by,
                "modality": entry.modality,
                "body_part": entry.body_part,
                "diagnosis": entry.diagnosis,
                "anatomical_classification": entry.anatomical_classification,
                "protocol_details": entry.protocol_details,
                "description": entry.description,
                "differential_diagnosis": entry.differential_diagnosis,
                "dicom_folder_path": entry.dicom_folder_path,
                "patient_id": entry.patient_id,
                "study_uid": entry.study_uid,
            }

            host_tab_widget, _, host_owner = self._resolve_tab_host()
            viewer = CaseOfDayViewerWidget(case_data, parent=host_owner if host_owner else self)
            tab_title = f"Case - {entry.diagnosis or entry.body_part or entry.modality}"

            if host_tab_widget is not None:
                tab_index = host_tab_widget.addTab(viewer, tab_title)
                host_tab_widget.setCurrentIndex(tab_index)
            else:
                viewer.setWindowTitle(tab_title)
                viewer.showMaximized()
        except Exception as exc:
            print(f"Error opening Case of the Day: {exc}")
            import traceback
            traceback.print_exc()


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
