"""Educational courses main widget with anatomy-based course organization."""

import random
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from PacsClient.pacs.education.course_database import (
    delete_course,
    get_all_courses,
    get_course_with_slides,
    insert_course,
    update_course,
)


ANATOMY_CATEGORY_ORDER = [
    "Head & Neck",
    "Brain",
    "Spine",
    "Shoulder",
    "Upper Limb",
    "Chest",
    "Cardiac",
    "Abdomen",
    "Pelvis",
    "Hip",
    "Knee",
    "Ankle & Foot",
    "Breast",
    "Vascular",
    "General",
]

ANATOMY_KEYWORDS = {
    "Head & Neck": ["head", "neck", "sinus", "orbit", "face", "thyroid"],
    "Brain": ["brain", "neuro", "stroke", "pituitary", "cranial", "cns"],
    "Spine": ["spine", "spinal", "cervical", "thoracic", "lumbar", "disc"],
    "Shoulder": ["shoulder", "rotator cuff", "ac joint", "glenoid", "labrum"],
    "Upper Limb": ["elbow", "wrist", "hand", "forearm", "humerus", "radius", "ulna"],
    "Chest": ["chest", "lung", "thorax", "pulmonary", "mediastinum", "pleura"],
    "Cardiac": ["cardiac", "heart", "coronary", "myocard", "echo"],
    "Abdomen": ["abdomen", "abdominal", "liver", "pancreas", "bowel", "kidney", "renal"],
    "Pelvis": ["pelvis", "pelvic", "uterus", "ovary", "prostate", "bladder"],
    "Hip": ["hip", "acetabul", "femoral head"],
    "Knee": ["knee", "acl", "pcl", "meniscus", "patella"],
    "Ankle & Foot": ["ankle", "foot", "achilles", "calcaneus", "metatarsal"],
    "Breast": ["breast", "mammography", "mammo"],
    "Vascular": ["vascular", "vessel", "artery", "vein", "angiography", "aorta"],
}

BODY_REGION_ALIASES = {
    "head": "Head & Neck",
    "neck": "Head & Neck",
    "brain": "Brain",
    "spine": "Spine",
    "shoulder": "Shoulder",
    "upper limb": "Upper Limb",
    "arm": "Upper Limb",
    "elbow": "Upper Limb",
    "wrist": "Upper Limb",
    "hand": "Upper Limb",
    "chest": "Chest",
    "thorax": "Chest",
    "cardiac": "Cardiac",
    "heart": "Cardiac",
    "abdomen": "Abdomen",
    "pelvis": "Pelvis",
    "hip": "Hip",
    "knee": "Knee",
    "ankle": "Ankle & Foot",
    "foot": "Ankle & Foot",
    "breast": "Breast",
    "vascular": "Vascular",
}

MODALITY_ORDER = ["CT", "MRI", "US", "X-ray", "PET", "SPECT", "Mammography", "Fluoroscopy"]
BODY_REGION_FILTER_FIXED = ["Head & Neck", "Chest", "Abdomen", "Pelvis", "Spine", "Shoulder", "Vascular", "Breast"]
TAG_FILTER_LEFT = ["Anatomy", "Pathology", "Trauma"]
TAG_FILTER_RIGHT = ["Oncology", "Pediatric", "Emergency"]
TAG_FILTER_FIXED = TAG_FILTER_LEFT + TAG_FILTER_RIGHT
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_THUMBNAIL_DIR = PROJECT_ROOT / "education_assets" / "sample_thumbnails"

SAMPLE_COURSE_CATALOG = [
    {
        "name": "MRI Shoulder Instability Workup",
        "description": "Evaluation of labral tears, Hill-Sachs defects, and capsular injuries using dedicated shoulder MRI protocol.",
        "author": "Dr. Leila Moradi, MD",
        "modality": "MRI",
        "body_regions": ["Shoulder", "MSK"],
        "level": "Advanced",
        "tags": ["Anatomy", "Pathology"],
    },
    {
        "name": "CT Pancreatitis Severity Evaluation",
        "description": "Contrast-enhanced CT approach for acute pancreatitis severity scoring and necrosis/collection detection.",
        "author": "Dr. Amir Nouri, MD",
        "modality": "CT",
        "body_regions": ["Abdomen"],
        "level": "Intermediate",
        "tags": ["Pathology", "Emergency"],
    },
    {
        "name": "MRI Knee: ACL and Meniscal Injury",
        "description": "High-yield protocol for ACL rupture, ramp lesions, and meniscal root tears with surgical relevance.",
        "author": "Dr. Hannah Porter, MD",
        "modality": "MRI",
        "body_regions": ["Knee", "MSK"],
        "level": "Intermediate",
        "tags": ["Trauma", "Pathology"],
    },
    {
        "name": "CT Head Trauma Hemorrhage Patterns",
        "description": "Fast emergency interpretation of epidural, subdural, and subarachnoid hemorrhage in trauma CT.",
        "author": "Dr. Navid Rahimi, MD",
        "modality": "CT",
        "body_regions": ["Brain", "Head"],
        "level": "Basic",
        "tags": ["Trauma", "Emergency"],
    },
    {
        "name": "Ultrasound Thyroid Nodule Risk Stratification",
        "description": "TI-RADS-based thyroid ultrasound workflow including suspicious features and biopsy thresholds.",
        "author": "Dr. Sophia Reed, MD",
        "modality": "US",
        "body_regions": ["Head & Neck", "Neck"],
        "level": "Intermediate",
        "tags": ["Anatomy", "Oncology"],
    },
    {
        "name": "Chest X-Ray Tuberculosis and Mimics",
        "description": "Pattern-based CXR interpretation for active TB, post-primary disease, and common differential diagnoses.",
        "author": "Dr. Elias Grant, MD",
        "modality": "X-Ray",
        "body_regions": ["Chest"],
        "level": "Basic",
        "tags": ["Pathology", "Emergency"],
    },
    {
        "name": "MRI Lumbar Disc Herniation Mapping",
        "description": "Systematic lumbar MRI reporting for disc extrusion, foraminal stenosis, and nerve root compression.",
        "author": "Dr. Roya Kiani, MD",
        "modality": "MRI",
        "body_regions": ["Spine"],
        "level": "Intermediate",
        "tags": ["Anatomy", "Pathology"],
    },
    {
        "name": "CT Pulmonary Embolism Angiography",
        "description": "CTPA protocol optimization with central/peripheral embolus detection and right-heart strain signs.",
        "author": "Dr. Jonah Kim, MD",
        "modality": "CT",
        "body_regions": ["Chest", "Vascular"],
        "level": "Advanced",
        "tags": ["Emergency", "Pathology"],
    },
    {
        "name": "Mammography BI-RADS Microcalcification Cases",
        "description": "Cluster morphology, distribution patterns, and BI-RADS scoring for microcalcification assessment.",
        "author": "Dr. Marisa Quinn, MD",
        "modality": "Mammography",
        "body_regions": ["Breast"],
        "level": "Intermediate",
        "tags": ["Oncology", "Pathology"],
    },
    {
        "name": "MRI Hip Labral Tear and FAI",
        "description": "MR arthrography and routine MRI signs of femoroacetabular impingement and labral pathology.",
        "author": "Dr. Arman Vaziri, MD",
        "modality": "MRI",
        "body_regions": ["Hip", "MSK"],
        "level": "Advanced",
        "tags": ["Trauma", "Anatomy"],
    },
]


class CourseCardWidget(QFrame):
    """Medium-sized course card with image, title and short description."""

    clicked = Signal(int)
    edit_clicked = Signal(int)
    present_clicked = Signal(int)
    delete_clicked = Signal(int)

    def __init__(self, course_data, parent=None):
        super().__init__(parent)
        self.course_data = course_data
        self.course_pk = course_data["course_pk"]
        self.setup_ui()
        self.setMouseTracking(True)

    def setup_ui(self):
        self.setFixedSize(320, 330)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            """
            CourseCardWidget {
                background-color: #253140;
                border: 1px solid #3b4b5d;
                border-radius: 12px;
            }
            CourseCardWidget:hover {
                border: 1px solid #4f8cc9;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        image_frame = QFrame()
        image_frame.setFixedHeight(162)
        image_frame.setStyleSheet(
            """
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #334155, stop:1 #1f2937
                );
                border-radius: 12px 12px 0 0;
            }
            """
        )
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(12, 10, 12, 10)
        image_layout.setAlignment(Qt.AlignCenter)

        thumbnail_path = self.course_data.get("thumbnail_path")
        if thumbnail_path and Path(thumbnail_path).exists():
            pixmap = QPixmap(thumbnail_path)
            image_label = QLabel()
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setPixmap(
                pixmap.scaled(
                    294,
                    140,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
            )
            image_layout.addWidget(image_label)
        else:
            placeholder = QLabel("Course Image")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                """
                QLabel {
                    color: #dbe4ee;
                    font-size: 11pt;
                    font-weight: 600;
                    border: 1px dashed rgba(219, 228, 238, 0.45);
                    border-radius: 8px;
                    padding: 10px 14px;
                }
                """
            )
            image_layout.addWidget(placeholder)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)

        modality_value = str(self.course_data.get("modality") or "").strip()
        if modality_value.lower() in {"xray", "x-ray", "radiography", "x-ray"}:
            modality_value = "X-ray"
        modality_badge = QLabel(modality_value)
        modality_badge.setStyleSheet(
            """
            QLabel {
                color: #f8fbff;
                background-color: rgba(37, 99, 235, 0.78);
                border: 1px solid rgba(59, 130, 246, 0.9);
                border-radius: 10px;
                padding: 3px 10px;
                font-size: 8.6pt;
                font-weight: 700;
            }
            """
        )
        badge_row.addWidget(modality_badge, 0, Qt.AlignLeft)

        level_text = str(self.course_data.get("level") or "").strip()
        if level_text:
            level_badge = QLabel(level_text)
            level_badge.setStyleSheet(
                """
                QLabel {
                    color: #eef6ff;
                    background-color: rgba(15, 118, 110, 0.70);
                    border: 1px solid rgba(20, 184, 166, 0.85);
                    border-radius: 10px;
                    padding: 3px 10px;
                    font-size: 8.3pt;
                    font-weight: 600;
                }
                """
            )
            badge_row.addWidget(level_badge, 0, Qt.AlignLeft)

        badge_row.addStretch()
        image_layout.addLayout(badge_row)

        root.addWidget(image_frame)

        content = QFrame()
        content.setStyleSheet(
            """
            QFrame {
                background-color: #253140;
                border-radius: 0 0 12px 12px;
            }
            """
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 12, 14, 12)
        content_layout.setSpacing(8)

        title = QLabel(self._truncate_text(self.course_data.get("course_name", "Untitled course"), 65))
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setWordWrap(True)
        title.setMaximumHeight(42)
        title.setStyleSheet("color: #f1f5f9;")
        content_layout.addWidget(title)

        description = self.course_data.get("course_description") or "No description provided."
        description_label = QLabel(self._truncate_text(description, 110))
        description_label.setWordWrap(True)
        description_label.setMaximumHeight(54)
        description_label.setStyleSheet("color: #c2d0df; font-size: 9pt;")
        content_layout.addWidget(description_label)

        author = self.course_data.get("author_name") or "Unknown instructor"
        author_label = QLabel(f"Instructor: {self._truncate_text(author, 32)}")
        author_label.setStyleSheet("color: #9fb0c2; font-size: 8.5pt;")
        content_layout.addWidget(author_label)

        region_tokens = self._course_region_summary(self.course_data)
        if region_tokens:
            region_label = QLabel(region_tokens)
            region_label.setStyleSheet("color: #90a4b7; font-size: 8.3pt;")
            content_layout.addWidget(region_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        present_btn = QPushButton("Present")
        present_btn.setFixedHeight(32)
        present_btn.clicked.connect(lambda: self.present_clicked.emit(self.course_pk))
        present_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 9pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2f6fce;
            }
            """
        )
        actions.addWidget(present_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedHeight(32)
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.course_pk))
        edit_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #445569;
                color: #f8fafc;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #556b84;
            }
            """
        )
        actions.addWidget(edit_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setFixedHeight(32)
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.course_pk))
        delete_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #445569;
                color: #f8fafc;
                border: none;
                border-radius: 6px;
                padding: 0 12px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #b63f49;
            }
            """
        )
        actions.addWidget(delete_btn)

        content_layout.addLayout(actions)
        root.addWidget(content)

    @staticmethod
    def _course_region_summary(course_data):
        raw_regions = course_data.get("body_regions") or []
        if isinstance(raw_regions, str):
            raw_regions = [raw_regions]
        normalized = []
        for region in raw_regions:
            region_text = str(region).strip()
            if not region_text:
                continue
            if region_text not in normalized:
                normalized.append(region_text)
        if not normalized:
            return ""
        if len(normalized) <= 2:
            return f"Region: {', '.join(normalized)}"
        return f"Region: {', '.join(normalized[:2])} +{len(normalized) - 2}"

    @staticmethod
    def _truncate_text(text, max_chars):
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            clicked_child = self.childAt(event.pos())
            if not clicked_child or not isinstance(clicked_child, QPushButton):
                self.edit_clicked.emit(self.course_pk)
        super().mousePressEvent(event)


class NewCourseDialog(QDialog):
    """Dialog for creating a new course."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Course")
        self.setMinimumSize(700, 520)
        self.setMaximumSize(700, 520)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        header_label = QLabel("Create New Educational Course")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setStyleSheet("color: #f7fafc; margin-bottom: 10px;")
        layout.addWidget(header_label)

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

        name_label = QLabel("Course Title *")
        name_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11pt;")
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., Advanced MRI Shoulder Pathology")
        self.name_input.setStyleSheet(form_style)
        layout.addWidget(self.name_input)

        author_label = QLabel("Instructor Name *")
        author_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11pt;")
        layout.addWidget(author_label)

        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("e.g., Dr. Sarah Johnson, MD")
        self.author_input.setStyleSheet(form_style)
        layout.addWidget(self.author_input)

        desc_label = QLabel("Course Description")
        desc_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11pt;")
        layout.addWidget(desc_label)

        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("Brief overview of the course content and learning objectives...")
        self.desc_input.setFixedHeight(80)
        self.desc_input.setStyleSheet(form_style)
        layout.addWidget(self.desc_input)

        layout.addStretch()

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(42)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(
            """
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
            """
        )
        buttons_layout.addWidget(cancel_btn)

        create_btn = QPushButton("Create Course")
        create_btn.setFixedHeight(42)
        create_btn.clicked.connect(self.accept)
        create_btn.setStyleSheet(
            """
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
            """
        )
        buttons_layout.addWidget(create_btn)

        layout.addLayout(buttons_layout)
        self.setStyleSheet("QDialog { background-color: #1a202c; }")

    def get_course_data(self):
        return {
            "name": self.name_input.text().strip(),
            "author": self.author_input.text().strip(),
            "description": self.desc_input.toPlainText().strip(),
            "outline": "",
        }


class EducationMainWidget(QWidget):
    """Main education interface with anatomy-based grouping and limited card volume."""

    INITIAL_VISIBLE_CARDS = 9
    CARD_LOAD_STEP = 5
    MAX_VISIBLE_CARDS = 9
    CARDS_PER_ROW = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.all_courses = []
        self.courses_by_category = {"All": []}
        self.available_categories = ["All"]
        self.selected_category = "All"
        self.visible_cards = self.INITIAL_VISIBLE_CARDS
        self.selected_modalities = set()
        self.selected_body_regions = set()
        self.selected_tags = set()
        self.filtered_courses = []
        self.available_modalities = []
        self.available_body_regions = []
        self.available_tags = []

        self.setup_ui()
        self.load_courses()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title_group = QVBoxLayout()
        title_group.setSpacing(4)

        title_label = QLabel("Educational Courses")
        title_font = QFont()
        title_font.setPointSize(21)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #f7fafc;")
        title_group.addWidget(title_label)

        subtitle_label = QLabel("Organized by anatomy to keep course browsing focused.")
        subtitle_label.setStyleSheet("color: #9fb0c2; font-size: 10pt;")
        title_group.addWidget(subtitle_label)

        header_layout.addLayout(title_group)
        header_layout.addStretch()

        self.new_course_btn = QPushButton("+ New Course")
        self.new_course_btn.setFixedHeight(42)
        self.new_course_btn.clicked.connect(self.create_new_course)
        self.new_course_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 9px;
                padding: 0 20px;
                font-size: 10pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        header_layout.addWidget(self.new_course_btn)
        layout.addLayout(header_layout)

        self.category_panel = QFrame()
        self.category_panel.setStyleSheet(
            """
            QFrame {
                background-color: #1f2a37;
                border: 1px solid #2f3d4e;
                border-radius: 10px;
            }
            """
        )
        category_panel_layout = QVBoxLayout(self.category_panel)
        category_panel_layout.setContentsMargins(12, 10, 12, 10)
        category_panel_layout.setSpacing(10)

        categories_title = QLabel("Anatomy Subcategories")
        categories_title.setStyleSheet("color: #d7e3ef; font-size: 10pt; font-weight: 600;")
        category_panel_layout.addWidget(categories_title)

        categories_scroll = QScrollArea()
        categories_scroll.setFixedHeight(52)
        categories_scroll.setWidgetResizable(True)
        categories_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        categories_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        categories_scroll.setFrameShape(QFrame.NoFrame)
        categories_scroll.setStyleSheet(
            """
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:horizontal {
                height: 8px;
                background: #1f2a37;
            }
            QScrollBar::handle:horizontal {
                background: #45576b;
                border-radius: 4px;
            }
            """
        )

        self.category_buttons_widget = QWidget()
        self.category_buttons_layout = QHBoxLayout(self.category_buttons_widget)
        self.category_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.category_buttons_layout.setSpacing(8)
        categories_scroll.setWidget(self.category_buttons_widget)
        category_panel_layout.addWidget(categories_scroll)

        filters_title = QLabel("Filters")
        filters_title.setStyleSheet("color: #d7e3ef; font-size: 10pt; font-weight: 600;")
        category_panel_layout.addWidget(filters_title)

        modality_title = QLabel("Modality")
        modality_title.setStyleSheet("color: #9fb0c2; font-size: 9pt; font-weight: 600;")
        category_panel_layout.addWidget(modality_title)

        self.modality_buttons_widget = QWidget()
        self.modality_buttons_layout = QGridLayout(self.modality_buttons_widget)
        self.modality_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.modality_buttons_layout.setHorizontalSpacing(8)
        self.modality_buttons_layout.setVerticalSpacing(8)
        category_panel_layout.addWidget(self.modality_buttons_widget)

        body_region_title = QLabel("Body Regions")
        body_region_title.setStyleSheet("color: #9fb0c2; font-size: 9pt; font-weight: 600;")
        category_panel_layout.addWidget(body_region_title)

        self.body_region_widget = QWidget()
        self.body_region_layout = QGridLayout(self.body_region_widget)
        self.body_region_layout.setContentsMargins(0, 0, 0, 0)
        self.body_region_layout.setHorizontalSpacing(8)
        self.body_region_layout.setVerticalSpacing(8)
        category_panel_layout.addWidget(self.body_region_widget)

        tags_title = QLabel("Tags")
        tags_title.setStyleSheet("color: #9fb0c2; font-size: 9pt; font-weight: 600;")
        category_panel_layout.addWidget(tags_title)

        self.tags_widget = QWidget()
        self.tags_layout = QGridLayout(self.tags_widget)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setHorizontalSpacing(8)
        self.tags_layout.setVerticalSpacing(8)
        category_panel_layout.addWidget(self.tags_widget)

        self.category_info_label = QLabel("")
        self.category_info_label.setStyleSheet("color: #9fb0c2; font-size: 9pt;")
        category_panel_layout.addWidget(self.category_info_label)

        layout.addWidget(self.category_panel)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.NoFrame)
        self.cards_scroll.setStyleSheet(
            """
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2d3748;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #4a5568;
                border-radius: 5px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #5f7187;
            }
            """
        )

        self.scroll_content = QWidget()
        self.grid_layout = QGridLayout(self.scroll_content)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cards_scroll.setWidget(self.scroll_content)
        layout.addWidget(self.cards_scroll)

        show_more_row = QHBoxLayout()
        show_more_row.addStretch()
        self.show_more_btn = QPushButton("Show more")
        self.show_more_btn.setFixedHeight(38)
        self.show_more_btn.setVisible(False)
        self.show_more_btn.clicked.connect(self.show_more_courses)
        self.show_more_btn.setStyleSheet(
            """
            QPushButton {
                background-color: transparent;
                color: #d9e4ef;
                border: 1px solid #4f6278;
                border-radius: 8px;
                padding: 0 18px;
                font-size: 9.5pt;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(79, 98, 120, 0.22);
            }
            """
        )
        show_more_row.addWidget(self.show_more_btn)
        show_more_row.addStretch()
        layout.addLayout(show_more_row)

        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)

        empty_title = QLabel("No courses yet")
        empty_title_font = QFont()
        empty_title_font.setPointSize(17)
        empty_title_font.setBold(True)
        empty_title.setFont(empty_title_font)
        empty_title.setStyleSheet("color: #6b7280;")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)

        empty_subtitle = QLabel("Create your first educational course to get started.")
        empty_subtitle.setStyleSheet("color: #4a5568; font-size: 11pt;")
        empty_subtitle.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_subtitle)

        self.empty_state.hide()
        layout.addWidget(self.empty_state)

        self.setStyleSheet("QWidget { background-color: #1a202c; }")

    def load_courses(self):
        self.all_courses = get_all_courses()
        self._ensure_sample_courses_and_thumbnails()
        self.all_courses = get_all_courses()
        self._clear_grid()

        if not self.all_courses:
            self.cards_scroll.hide()
            self.category_panel.hide()
            self.show_more_btn.hide()
            self.empty_state.show()
            return

        self.empty_state.hide()
        self.cards_scroll.show()
        self.category_panel.show()

        self._refresh_filter_options()
        self.filtered_courses = self._apply_active_filters(self.all_courses)
        self._build_category_index()
        if self.selected_category not in self.courses_by_category:
            self.selected_category = "All"
        self.visible_cards = self.INITIAL_VISIBLE_CARDS
        self._refresh_modality_buttons()
        self._refresh_body_region_buttons()
        self._refresh_category_buttons()
        self._render_selected_category()

    def _refresh_filter_options(self):
        self.available_modalities = list(MODALITY_ORDER)
        self.available_body_regions = list(BODY_REGION_FILTER_FIXED)
        self.available_tags = list(TAG_FILTER_FIXED)

        self.selected_modalities = {m for m in self.selected_modalities if m in self.available_modalities}
        self.selected_body_regions = {r for r in self.selected_body_regions if r in self.available_body_regions}
        self.selected_tags = {t for t in self.selected_tags if t in self.available_tags}

    @staticmethod
    def _normalize_modality(modality_value):
        normalized = str(modality_value or "").strip().lower()
        if not normalized:
            return ""
        if normalized in {"ct", "cat"}:
            return "CT"
        if normalized in {"mri", "mr"}:
            return "MRI"
        if normalized in {"us", "ultrasound"}:
            return "US"
        if normalized in {"xray", "x-ray", "radiography"}:
            return "X-ray"
        if normalized in {"mammo", "mammography"}:
            return "Mammography"
        if normalized == "pet":
            return "PET"
        if normalized == "spect":
            return "SPECT"
        if normalized in {"fluoro", "fluoroscopy"}:
            return "Fluoroscopy"
        return str(modality_value).strip()

    def _apply_active_filters(self, courses):
        filtered_courses = []
        for course in courses:
            course_modality = self._normalize_modality(course.get("modality"))
            if self.selected_modalities and course_modality not in self.selected_modalities:
                continue

            if self.selected_body_regions:
                if not (self._course_regions_for_filter(course) & self.selected_body_regions):
                    continue

            if self.selected_tags:
                course_tags = course.get("tags") or []
                if isinstance(course_tags, str):
                    course_tags = [course_tags]
                normalized_tags = {str(tag).strip() for tag in course_tags if str(tag).strip()}
                if not (normalized_tags & self.selected_tags):
                    continue

            filtered_courses.append(course)

        return filtered_courses

    def _course_regions_for_filter(self, course):
        regions = set()
        resolved = self._resolve_anatomy_category(course)
        if resolved and resolved != "General":
            regions.add(resolved)

        raw_regions = course.get("body_regions") or []
        if isinstance(raw_regions, str):
            raw_regions = [raw_regions]
        for region in raw_regions:
            region_text = str(region).strip()
            if not region_text:
                continue
            lowered = region_text.lower()
            if lowered in {"msk", "musculoskeletal"}:
                regions.add("Shoulder")
                regions.add("Spine")
            mapped = BODY_REGION_ALIASES.get(lowered)
            if mapped:
                regions.add(mapped)
            regions.add(region_text)

        # Normalize a few common variations to match the fixed filter names.
        normalized = set()
        for region in regions:
            if region.lower() in {"head/neck", "head", "neck"}:
                normalized.add("Head & Neck")
            else:
                normalized.add(region)

        # Keep only the displayed filter labels.
        return {r for r in normalized if r in BODY_REGION_FILTER_FIXED}

    def _refresh_modality_buttons(self):
        while self.modality_buttons_layout.count():
            item = self.modality_buttons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for index, modality in enumerate(self.available_modalities[:8]):
            row = index // 4
            col = index % 4
            btn = QPushButton(modality)
            btn.setCheckable(True)
            btn.setChecked(modality in self.selected_modalities)
            btn.setFixedHeight(32)
            btn.clicked.connect(
                lambda checked=False, modality_name=modality: self._toggle_modality_filter(modality_name)
            )
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #2e3a4a;
                    color: #d8e3ee;
                    border: 1px solid #445569;
                    border-radius: 6px;
                    padding: 0 12px;
                    font-size: 8.8pt;
                    font-weight: 600;
                }
                QPushButton:hover {
                    border-color: #5c748f;
                }
                QPushButton:checked {
                    background-color: #1e40af;
                    border-color: #3b82f6;
                    color: #f8fbff;
                }
                """
            )
            self.modality_buttons_layout.addWidget(btn, row, col)

    def _refresh_body_region_buttons(self):
        while self.body_region_layout.count():
            item = self.body_region_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for index, region in enumerate(self.available_body_regions[:8]):
            col = index // 4
            row = index % 4
            btn = QPushButton(region)
            btn.setCheckable(True)
            btn.setChecked(region in self.selected_body_regions)
            btn.setFixedHeight(30)
            btn.clicked.connect(
                lambda checked=False, region_name=region: self._toggle_body_region_filter(region_name)
            )
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #2e3a4a;
                    color: #d8e3ee;
                    border: 1px solid #445569;
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 8.7pt;
                }
                QPushButton:hover {
                    border-color: #5c748f;
                }
                QPushButton:checked {
                    background-color: #0f766e;
                    border-color: #14b8a6;
                    color: #f8fbff;
                    font-weight: 600;
                }
                """
            )
            self.body_region_layout.addWidget(btn, row, col)

        self._refresh_tag_buttons()

    def _refresh_tag_buttons(self):
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row_index, tag in enumerate(TAG_FILTER_LEFT):
            btn = self._make_tag_button(tag)
            self.tags_layout.addWidget(btn, row_index, 0)

        for row_index, tag in enumerate(TAG_FILTER_RIGHT):
            btn = self._make_tag_button(tag)
            self.tags_layout.addWidget(btn, row_index, 1)

    def _make_tag_button(self, tag_name):
        btn = QPushButton(tag_name)
        btn.setCheckable(True)
        btn.setChecked(tag_name in self.selected_tags)
        btn.setFixedHeight(30)
        btn.clicked.connect(lambda checked=False, tag_value=tag_name: self._toggle_tag_filter(tag_value))
        btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2e3a4a;
                color: #d8e3ee;
                border: 1px solid #445569;
                border-radius: 6px;
                padding: 0 10px;
                font-size: 8.7pt;
            }
            QPushButton:hover {
                border-color: #5c748f;
            }
            QPushButton:checked {
                background-color: #7c2d12;
                border-color: #fb923c;
                color: #fff7ed;
                font-weight: 600;
            }
            """
        )
        return btn

    def _toggle_modality_filter(self, modality_name):
        if modality_name in self.selected_modalities:
            self.selected_modalities.remove(modality_name)
        else:
            self.selected_modalities.add(modality_name)
        self._apply_filters_and_refresh_categories()

    def _toggle_body_region_filter(self, region_name):
        if region_name in self.selected_body_regions:
            self.selected_body_regions.remove(region_name)
        else:
            self.selected_body_regions.add(region_name)
        self._apply_filters_and_refresh_categories()

    def _toggle_tag_filter(self, tag_name):
        if tag_name in self.selected_tags:
            self.selected_tags.remove(tag_name)
        else:
            self.selected_tags.add(tag_name)
        self._apply_filters_and_refresh_categories()

    def _apply_filters_and_refresh_categories(self):
        self.filtered_courses = self._apply_active_filters(self.all_courses)
        self._build_category_index()
        if self.selected_category not in self.courses_by_category:
            self.selected_category = "All"
        self.visible_cards = self.INITIAL_VISIBLE_CARDS
        self._refresh_modality_buttons()
        self._refresh_body_region_buttons()
        self._refresh_category_buttons()
        self._render_selected_category()

    def _build_category_index(self):
        self.courses_by_category = {"All": list(self.filtered_courses)}
        for course in self.filtered_courses:
            category = self._resolve_anatomy_category(course)
            self.courses_by_category.setdefault(category, []).append(course)

        ordered = ["All"]
        ordered.extend(
            category
            for category in ANATOMY_CATEGORY_ORDER
            if category in self.courses_by_category and category != "All"
        )
        extras = sorted(
            category
            for category in self.courses_by_category.keys()
            if category not in ordered
        )
        self.available_categories = ordered + extras

    def _resolve_anatomy_category(self, course):
        body_regions = course.get("body_regions") or []
        if isinstance(body_regions, str):
            body_regions = [body_regions]

        for region in body_regions:
            normalized_region = str(region).strip().lower()
            for alias, mapped_category in BODY_REGION_ALIASES.items():
                if alias in normalized_region:
                    return mapped_category

        search_text = " ".join(
            [
                str(course.get("course_name") or ""),
                str(course.get("course_description") or ""),
                str(course.get("outline") or ""),
            ]
        ).lower()
        for category, keywords in ANATOMY_KEYWORDS.items():
            if any(keyword in search_text for keyword in keywords):
                return category

        return "General"

    def _refresh_category_buttons(self):
        while self.category_buttons_layout.count():
            item = self.category_buttons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for category in self.available_categories:
            count = len(self.courses_by_category.get(category, []))
            button = QPushButton(f"{category} ({count})")
            button.setCheckable(True)
            button.setChecked(category == self.selected_category)
            button.setFixedHeight(34)
            button.clicked.connect(
                lambda checked=False, category_name=category: self.select_category(category_name)
            )
            button.setStyleSheet(
                """
                QPushButton {
                    background-color: #2e3a4a;
                    color: #d8e3ee;
                    border: 1px solid #445569;
                    border-radius: 17px;
                    padding: 0 14px;
                    font-size: 9pt;
                    font-weight: 600;
                }
                QPushButton:hover {
                    border-color: #5c748f;
                }
                QPushButton:checked {
                    background-color: #2563eb;
                    border-color: #3b82f6;
                    color: #f8fbff;
                }
                """
            )
            self.category_buttons_layout.addWidget(button)

        self.category_buttons_layout.addStretch()

    def select_category(self, category_name):
        if category_name == self.selected_category:
            return
        self.selected_category = category_name
        self.visible_cards = self.INITIAL_VISIBLE_CARDS
        self._refresh_category_buttons()
        self._render_selected_category()

    def _render_selected_category(self):
        self._clear_grid()
        category_courses = self.courses_by_category.get(self.selected_category, [])
        total = len(category_courses)
        filter_parts = []
        if self.selected_modalities:
            filter_parts.append(f"modality={', '.join(sorted(self.selected_modalities))}")
        if self.selected_body_regions:
            filter_parts.append(f"regions={', '.join(sorted(self.selected_body_regions))}")
        if self.selected_tags:
            filter_parts.append(f"tags={', '.join(sorted(self.selected_tags))}")
        filter_text = f" | filters: {'; '.join(filter_parts)}" if filter_parts else ""

        if total == 0:
            empty_label = QLabel(f"No courses in '{self.selected_category}' yet.")
            empty_label.setStyleSheet("color: #9fb0c2; font-size: 10pt; padding: 16px;")
            self.grid_layout.addWidget(empty_label, 0, 0, 1, self.CARDS_PER_ROW)
            self.category_info_label.setText(f"{self.selected_category}: 0 courses{filter_text}")
            self.show_more_btn.hide()
            return

        shown_count = min(self.visible_cards, self.MAX_VISIBLE_CARDS, total)
        courses_to_show = category_courses[:shown_count]

        for index, course in enumerate(courses_to_show):
            row = index // self.CARDS_PER_ROW
            col = index % self.CARDS_PER_ROW
            card = CourseCardWidget(course)
            card.edit_clicked.connect(self.edit_course)
            card.present_clicked.connect(self.present_course)
            card.delete_clicked.connect(self.delete_course)
            self.grid_layout.addWidget(card, row, col)

        self.category_info_label.setText(
            f"{self.selected_category}: showing {shown_count} of {total} courses (max {self.MAX_VISIBLE_CARDS}){filter_text}."
        )

        can_show_more = shown_count < total and shown_count < self.MAX_VISIBLE_CARDS
        self.show_more_btn.setVisible(can_show_more)
        if can_show_more:
            remaining = min(self.MAX_VISIBLE_CARDS, total) - shown_count
            self.show_more_btn.setText(f"Show more ({remaining} remaining)")

    def show_more_courses(self):
        self.visible_cards = min(
            self.visible_cards + self.CARD_LOAD_STEP,
            self.MAX_VISIBLE_CARDS,
        )
        self._render_selected_category()

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _ensure_sample_courses_and_thumbnails(self):
        SAMPLE_THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

        # If the DB already has plenty of courses, still ensure visible ones have thumbnails.
        if len(self.all_courses) >= self.MAX_VISIBLE_CARDS:
            self._ensure_thumbnails_for_existing_courses()
            return

        existing_names = {
            str(course.get("course_name") or "").strip().lower()
            for course in self.all_courses
        }

        inserted = False

        for sample in SAMPLE_COURSE_CATALOG:
            if sample["name"].strip().lower() in existing_names:
                continue

            thumbnail_path = self._build_sample_thumbnail_path(sample)
            if not thumbnail_path.exists():
                self._generate_sample_thumbnail(
                    thumbnail_path=thumbnail_path,
                    modality=sample["modality"],
                    course_title=sample["name"],
                )

            insert_course(
                name=sample["name"],
                description=sample["description"],
                author=sample["author"],
                modality=sample["modality"],
                body_regions=sample["body_regions"],
                level=sample["level"],
                thumbnail_path=str(thumbnail_path),
                tags=sample.get("tags") or ["Anatomy"],
                is_my_course=False,
                is_downloaded=True,
            )
            existing_names.add(sample["name"].strip().lower())
            inserted = True

            if len(existing_names) >= self.MAX_VISIBLE_CARDS:
                break

        if inserted:
            self.all_courses = get_all_courses()

        self._ensure_thumbnails_for_existing_courses()

    def _ensure_thumbnails_for_existing_courses(self):
        updated_any = False
        for course in self.all_courses[: max(self.MAX_VISIBLE_CARDS, 12)]:
            course_pk = course.get("course_pk")
            if not course_pk:
                continue
            thumbnail_path = str(course.get("thumbnail_path") or "").strip()
            if thumbnail_path and Path(thumbnail_path).exists():
                continue

            desired_path = SAMPLE_THUMBNAIL_DIR / f"course_{course_pk}.png"
            if not desired_path.exists():
                self._generate_sample_thumbnail(
                    thumbnail_path=desired_path,
                    modality=course.get("modality") or "CT",
                    course_title=course.get("course_name") or f"Course {course_pk}",
                )
            try:
                update_course(course_pk=int(course_pk), thumbnail_path=str(desired_path))
                updated_any = True
            except Exception:
                continue

        if updated_any:
            self.all_courses = get_all_courses()

    @staticmethod
    def _build_sample_thumbnail_path(sample_course):
        safe_name = "".join(
            character.lower() if character.isalnum() else "_"
            for character in sample_course["name"]
        )
        safe_name = "_".join(part for part in safe_name.split("_") if part)
        return SAMPLE_THUMBNAIL_DIR / f"{safe_name}.png"

    def _generate_sample_thumbnail(self, thumbnail_path, modality, course_title):
        width, height = 960, 540
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor("#0b1020"))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        gradient = QLinearGradient(0, 0, width, height)
        modality_name = self._normalize_modality(modality)
        if modality_name == "MRI":
            gradient.setColorAt(0.0, QColor(24, 36, 59))
            gradient.setColorAt(1.0, QColor(8, 12, 24))
        elif modality_name == "CT":
            gradient.setColorAt(0.0, QColor(46, 55, 69))
            gradient.setColorAt(1.0, QColor(18, 20, 28))
        elif modality_name == "US":
            gradient.setColorAt(0.0, QColor(15, 28, 36))
            gradient.setColorAt(1.0, QColor(8, 14, 19))
        elif modality_name == "X-Ray":
            gradient.setColorAt(0.0, QColor(14, 18, 27))
            gradient.setColorAt(1.0, QColor(3, 6, 11))
        elif modality_name == "Mammography":
            gradient.setColorAt(0.0, QColor(45, 32, 40))
            gradient.setColorAt(1.0, QColor(21, 14, 19))
        else:
            gradient.setColorAt(0.0, QColor(25, 34, 46))
            gradient.setColorAt(1.0, QColor(9, 14, 20))
        painter.fillRect(0, 0, width, height, QBrush(gradient))

        self._draw_imaging_pattern(painter, width, height, modality_name, course_title)
        self._draw_thumbnail_overlay(painter, width, height, modality_name, course_title)

        painter.end()
        image.save(str(thumbnail_path), "PNG")

    def _draw_imaging_pattern(self, painter, width, height, modality_name, course_title):
        rng = random.Random(sum(ord(ch) for ch in f"{course_title}:{modality_name}"))
        center_x = int(width * 0.52)
        center_y = int(height * 0.46)

        if modality_name == "MRI":
            painter.setBrush(QColor(30, 35, 48))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center_x - 190, center_y - 145, 380, 290)
            painter.setBrush(QColor(86, 100, 118, 170))
            painter.drawEllipse(center_x - 145, center_y - 112, 290, 224)
            painter.setBrush(QColor(134, 148, 166, 145))
            painter.drawEllipse(center_x - 97, center_y - 78, 194, 156)
            painter.setBrush(QColor(202, 208, 218, 120))
            painter.drawEllipse(center_x - 44, center_y - 34, 88, 68)
        elif modality_name == "CT":
            painter.setBrush(QColor(55, 60, 68))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center_x - 200, center_y - 150, 400, 300)
            painter.setBrush(QColor(148, 156, 164, 160))
            painter.drawEllipse(center_x - 156, center_y - 116, 312, 232)
            painter.setBrush(QColor(46, 48, 51))
            painter.drawEllipse(center_x - 124, center_y - 92, 248, 184)
            painter.setBrush(QColor(168, 174, 180, 190))
            painter.drawEllipse(center_x - 16, center_y - 18, 32, 36)
        elif modality_name == "US":
            path = QPainterPath()
            path.moveTo(center_x - 230, center_y - 160)
            path.lineTo(center_x + 230, center_y - 160)
            path.lineTo(center_x + 120, center_y + 190)
            path.lineTo(center_x - 120, center_y + 190)
            path.closeSubpath()
            painter.fillPath(path, QColor(44, 56, 63))
            painter.setBrush(QColor(212, 219, 227, 135))
            painter.setPen(Qt.NoPen)
            for _ in range(16):
                x = center_x + rng.randint(-150, 150)
                y = center_y + rng.randint(-100, 160)
                size = rng.randint(12, 26)
                painter.drawEllipse(x, y, size, size)
        elif modality_name == "X-Ray":
            painter.setPen(QPen(QColor(208, 218, 236, 200), 7))
            painter.drawLine(center_x - 130, center_y - 150, center_x - 55, center_y + 180)
            painter.drawLine(center_x + 130, center_y - 150, center_x + 55, center_y + 180)
            painter.setPen(QPen(QColor(230, 236, 245, 178), 6))
            for step in range(8):
                y = center_y - 74 + step * 31
                painter.drawLine(center_x - 100, y, center_x + 100, y)
        elif modality_name == "Mammography":
            painter.setBrush(QColor(70, 74, 92, 190))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(center_x - 190, center_y - 136, 380, 270, 22, 22)
            painter.setBrush(QColor(190, 195, 205, 120))
            painter.drawEllipse(center_x - 120, center_y - 80, 240, 170)
            painter.setBrush(QColor(235, 239, 245, 150))
            for _ in range(18):
                x = center_x + rng.randint(-112, 114)
                y = center_y + rng.randint(-84, 80)
                painter.drawEllipse(x, y, rng.randint(4, 8), rng.randint(4, 8))
        else:
            painter.setBrush(QColor(80, 90, 106, 170))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(center_x - 175, center_y - 128, 350, 256)

        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        for _ in range(3400):
            x = rng.randint(0, width - 1)
            y = rng.randint(0, height - 1)
            painter.drawPoint(x, y)

    @staticmethod
    def _draw_thumbnail_overlay(painter, width, height, modality_name, course_title):
        painter.setPen(QColor(237, 243, 249, 230))
        title_font = QFont("Segoe UI", 18, QFont.Bold)
        painter.setFont(title_font)
        painter.drawText(30, height - 68, modality_name)

        painter.setPen(QColor(214, 224, 236, 220))
        subtitle_font = QFont("Segoe UI", 11)
        painter.setFont(subtitle_font)
        trimmed_title = course_title if len(course_title) <= 62 else f"{course_title[:59]}..."
        painter.drawText(30, height - 34, trimmed_title)

    def create_new_course(self):
        dialog = NewCourseDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        data = dialog.get_course_data()
        if not data["name"]:
            QMessageBox.warning(self, "Required Field", "Please enter a course title.")
            return
        if not data["author"]:
            QMessageBox.warning(self, "Required Field", "Please enter an instructor name.")
            return

        try:
            course_pk = insert_course(
                name=data["name"],
                description=data["description"],
                author=data["author"],
                outline=data["outline"],
            )
            self.load_courses()
            self.edit_course(course_pk)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to create course: {exc}")

    def edit_course(self, course_pk):
        try:
            from PacsClient.pacs.education.course_editor_widget import CourseEditorWidget

            editor = CourseEditorWidget(course_pk, parent=self)
            editor.course_saved.connect(self.load_courses)
            editor.setWindowTitle("Course Editor")
            editor.showMaximized()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open editor: {exc}")

    def present_course(self, course_pk):
        try:
            from PacsClient.pacs.education.educational_patient_viewer_widget import EducationalCourseViewerWidget

            course = get_course_with_slides(course_pk)
            if not course:
                QMessageBox.warning(self, "Course Not Found", "The selected course could not be loaded.")
                return

            # Find parent context with tab widget/custom tab manager
            parent = self.parent()
            while parent and not hasattr(parent, "tab_widget"):
                parent = parent.parent()

            viewer = EducationalCourseViewerWidget(course, parent=parent if parent else self)
            course_name = str(course.get("course_name") or "Course")

            if parent and hasattr(parent, "custom_tab_manager") and parent.custom_tab_manager:
                if hasattr(parent.custom_tab_manager, "add_educational_course_tab"):
                    parent.custom_tab_manager.add_educational_course_tab(
                        course_name=course_name,
                        course_pk=course.get("course_pk"),
                        widget=viewer,
                        activate=True,
                    )
                else:
                    tab_index = parent.tab_widget.addTab(viewer, f"Educational Course - {course_name}")
                    parent.tab_widget.setCurrentIndex(tab_index)
            elif parent and hasattr(parent, "tab_widget"):
                tab_index = parent.tab_widget.addTab(viewer, f"Educational Course - {course_name}")
                parent.tab_widget.setCurrentIndex(tab_index)
            else:
                viewer.setWindowTitle(f"Educational Course - {course_name}")
                viewer.showMaximized()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to start presentation: {exc}")

    def delete_course(self, course_pk):
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this course?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            delete_course(course_pk)
            self.load_courses()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to delete course: {exc}")
