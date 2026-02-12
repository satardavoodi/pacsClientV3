from __future__ import annotations

from pathlib import Path
import random
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDateTime, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except Exception:
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None
    _HAS_MULTIMEDIA = False

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    _HAS_PDF = True
except Exception:
    QPdfDocument = None
    QPdfView = None
    _HAS_PDF = False

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
from PacsClient.pacs.patient_tab.utils import get_study_source_path
from PacsClient.utils import CallerTypes


class EducationalPatientViewerWidget(PatientWidget):
    """Educationally customized copy of the patient viewer with course footer."""

    def __init__(self, course_data: Dict[str, Any], parent: Optional[QWidget] = None):
        self.course_data = course_data or {}
        self.slides: List[Dict[str, Any]] = self._normalize_slides(self.course_data.get("slides") or [])
        self.current_slide_index = 0

        self._session_seconds = 0
        self._session_running = True

        self._current_image_path: Optional[str] = None

        initial = self._find_first_dicom_source()
        initial_study_uid = initial.get("study_uid") if initial else None
        initial_patient_id = initial.get("patient_id") if initial else None
        initial_study_path = None

        if initial_study_uid:
            study_path, _ = get_study_source_path(str(initial_study_uid))
            initial_study_path = str(study_path)

        super().__init__(
            parent=parent,
            import_folder_path=initial_study_path,
            size_init_viewers=(1, 1),
            caller=CallerTypes.SERVER if initial_study_uid else None,
            study_uid=initial_study_uid,
            patient_id=initial_patient_id,
            enable_progressive_mode=False,
        )

        self._update_course_info_panel()
        self._populate_slide_selector()
        self._start_footer_timers()

        if self.slides:
            self._set_current_slide(0)
        else:
            self.items_list.addItem("No slides available")
            self.items_list.setEnabled(False)

    # -----------------------------
    # PatientWidget customization
    # -----------------------------
    def center_layout_ui(self):
        center_widget = QWidget()
        center_widget.setStyleSheet(
            """
            QWidget {
                background-color: #0d0d0d;
                border: none;
                margin: 0px;
                padding: 0px;
            }
            """
        )
        self.center_widget = center_widget

        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(8)

        self.education_content_stack = QStackedWidget()

        dicom_page = QWidget()
        dicom_page_layout = QVBoxLayout(dicom_page)
        dicom_page_layout.setContentsMargins(0, 0, 0, 0)
        dicom_page_layout.setSpacing(0)

        dicom_surface = QWidget()
        self.vtk_layout = QGridLayout(dicom_surface)
        self.vtk_layout.setContentsMargins(8, 8, 8, 8)
        self.vtk_layout.setSpacing(8)
        dicom_page_layout.addWidget(dicom_surface)

        self.education_content_stack.addWidget(dicom_page)

        self.media_page = self._build_media_page()
        self.education_content_stack.addWidget(self.media_page)

        center_layout.addWidget(self.education_content_stack, 1)

        footer = self._build_footer()
        footer.setFixedHeight(190)
        center_layout.addWidget(footer, 0)

        return center_widget

    # -----------------------------
    # Footer UI
    # -----------------------------
    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("EducationalFooter")
        footer.setStyleSheet(
            """
            QFrame#EducationalFooter {
                background-color: #121821;
                border: 1px solid #2a3340;
                border-radius: 8px;
            }
            QLabel {
                color: #d7dfeb;
            }
            QPushButton {
                background-color: #1f4a67;
                color: #f0f4f8;
                border: 1px solid #2f6c90;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #2d5f82;
            }
            QComboBox {
                background-color: #0f141b;
                color: #e2e8f0;
                border: 1px solid #2f3c4d;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QListWidget {
                background-color: #0f141b;
                color: #d7dfeb;
                border: 1px solid #2f3c4d;
                border-radius: 4px;
            }
            """
        )

        root = QHBoxLayout(footer)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Left quarter: current time + session timer
        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 4, 6, 4)
        left_layout.setSpacing(6)

        left_title = QLabel("Time & Timer")
        left_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f0f4f8;")
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.session_label = QLabel("Session: 00:00")
        self.session_label.setStyleSheet("font-size: 13px; color: #9fb4cc;")

        timer_buttons = QHBoxLayout()
        self.timer_toggle_btn = QPushButton("Pause")
        self.timer_toggle_btn.clicked.connect(self._toggle_session_timer)
        timer_reset_btn = QPushButton("Reset")
        timer_reset_btn.clicked.connect(self._reset_session_timer)
        timer_buttons.addWidget(self.timer_toggle_btn)
        timer_buttons.addWidget(timer_reset_btn)

        left_layout.addWidget(left_title)
        left_layout.addWidget(self.clock_label)
        left_layout.addWidget(self.session_label)
        left_layout.addLayout(timer_buttons)
        left_layout.addStretch(1)

        # Middle: slide navigation + items
        middle = QFrame()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(6, 4, 6, 4)
        middle_layout.setSpacing(6)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)

        prev_btn = QPushButton("<")
        prev_btn.setFixedWidth(34)
        prev_btn.clicked.connect(self._previous_slide)

        self.slide_selector = QComboBox()
        self.slide_selector.currentIndexChanged.connect(self._on_slide_selected)

        next_btn = QPushButton(">")
        next_btn.setFixedWidth(34)
        next_btn.clicked.connect(self._next_slide)

        nav_row.addWidget(prev_btn)
        nav_row.addWidget(self.slide_selector, 1)
        nav_row.addWidget(next_btn)

        self.slide_label = QLabel("Slide")
        self.slide_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #f0f4f8;")

        self.items_list = QListWidget()
        self.items_list.setViewMode(QListView.IconMode)
        self.items_list.setFlow(QListView.LeftToRight)
        self.items_list.setWrapping(True)
        self.items_list.setResizeMode(QListView.Adjust)
        self.items_list.setSpacing(8)
        self.items_list.setIconSize(QSize(40, 40))
        self.items_list.setGridSize(QSize(160, 72))
        self.items_list.setWordWrap(True)
        self.items_list.itemClicked.connect(self._on_item_clicked)

        self.slide_notes = QLabel("")
        self.slide_notes.setWordWrap(True)
        self.slide_notes.setStyleSheet("color: #8ea1b7; font-size: 11px;")

        middle_layout.addLayout(nav_row)
        middle_layout.addWidget(self.slide_label)
        middle_layout.addWidget(self.items_list, 1)
        middle_layout.addWidget(self.slide_notes)

        # Right quarter: course information
        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 4, 6, 4)
        right_layout.setSpacing(6)

        right_title = QLabel("Course Info")
        right_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #f0f4f8;")

        self.info_course_name = QLabel("Course: -")
        self.info_author = QLabel("Author: -")
        self.info_slides = QLabel("Slides: 0")
        self.info_items = QLabel("Items: 0")
        self.info_meta = QLabel("")
        self.info_meta.setWordWrap(True)
        self.info_meta.setStyleSheet("color: #8ea1b7;")

        right_layout.addWidget(right_title)
        right_layout.addWidget(self.info_course_name)
        right_layout.addWidget(self.info_author)
        right_layout.addWidget(self.info_slides)
        right_layout.addWidget(self.info_items)
        right_layout.addWidget(self.info_meta)
        right_layout.addStretch(1)

        root.addWidget(left, 1)
        root.addWidget(middle, 2)
        root.addWidget(right, 1)

        return footer

    # -----------------------------
    # Media page
    # -----------------------------
    def _build_media_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.media_title = QLabel("Educational Media")
        self.media_title.setStyleSheet("color: #f0f4f8; font-size: 14px; font-weight: 700;")
        layout.addWidget(self.media_title)

        self.media_stack = QStackedWidget()

        # Message/fallback page
        self.media_message = QLabel("Select a slide item to preview")
        self.media_message.setAlignment(Qt.AlignCenter)
        self.media_message.setStyleSheet("color: #9fb4cc; font-size: 13px;")
        message_page = QWidget()
        message_layout = QVBoxLayout(message_page)
        message_layout.addWidget(self.media_message, 1)
        self.media_stack.addWidget(message_page)

        # Image page
        self.image_label = QLabel("No image")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: #0f141b; border: 1px solid #2f3c4d;")
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.addWidget(self.image_label, 1)
        self.media_stack.addWidget(image_page)

        # Video page
        video_page = QWidget()
        video_layout = QVBoxLayout(video_page)
        video_layout.setContentsMargins(0, 0, 0, 0)
        self.video_widget = QVideoWidget() if _HAS_MULTIMEDIA else QLabel("Video playback is unavailable")
        if not _HAS_MULTIMEDIA:
            self.video_widget.setAlignment(Qt.AlignCenter)
            self.video_widget.setStyleSheet("color: #a0aec0;")
        video_layout.addWidget(self.video_widget, 1)

        video_controls = QHBoxLayout()
        self.media_play_btn = QPushButton("Play")
        self.media_pause_btn = QPushButton("Pause")
        self.media_stop_btn = QPushButton("Stop")
        self.media_play_btn.clicked.connect(self._play_media)
        self.media_pause_btn.clicked.connect(self._pause_media)
        self.media_stop_btn.clicked.connect(self._stop_media_playback)
        video_controls.addWidget(self.media_play_btn)
        video_controls.addWidget(self.media_pause_btn)
        video_controls.addWidget(self.media_stop_btn)
        video_controls.addStretch(1)
        video_layout.addLayout(video_controls)
        self.media_stack.addWidget(video_page)

        # Audio page
        audio_page = QWidget()
        audio_layout = QVBoxLayout(audio_page)
        self.audio_label = QLabel("Audio")
        self.audio_label.setAlignment(Qt.AlignCenter)
        self.audio_label.setStyleSheet("color: #d7dfeb; font-size: 14px;")
        audio_layout.addWidget(self.audio_label, 1)

        audio_controls = QHBoxLayout()
        self.audio_play_btn = QPushButton("Play")
        self.audio_pause_btn = QPushButton("Pause")
        self.audio_stop_btn = QPushButton("Stop")
        self.audio_play_btn.clicked.connect(self._play_media)
        self.audio_pause_btn.clicked.connect(self._pause_media)
        self.audio_stop_btn.clicked.connect(self._stop_media_playback)
        audio_controls.addWidget(self.audio_play_btn)
        audio_controls.addWidget(self.audio_pause_btn)
        audio_controls.addWidget(self.audio_stop_btn)
        audio_controls.addStretch(1)
        audio_layout.addLayout(audio_controls)
        self.media_stack.addWidget(audio_page)

        # PDF page
        self.pdf_page = QWidget()
        pdf_layout = QVBoxLayout(self.pdf_page)
        pdf_layout.setContentsMargins(0, 0, 0, 0)

        self.pdf_open_external_btn = QPushButton("Open PDF in External Viewer")
        self.pdf_open_external_btn.clicked.connect(self._open_current_media_external)

        if _HAS_PDF:
            self.pdf_document = QPdfDocument(self)
            self.pdf_view = QPdfView()
            self.pdf_view.setDocument(self.pdf_document)
            pdf_layout.addWidget(self.pdf_view, 1)
        else:
            self.pdf_document = None
            self.pdf_view = QLabel("PDF preview is unavailable in this build.")
            self.pdf_view.setAlignment(Qt.AlignCenter)
            self.pdf_view.setStyleSheet("color: #a0aec0;")
            pdf_layout.addWidget(self.pdf_view, 1)
            pdf_layout.addWidget(self.pdf_open_external_btn)

        self.media_stack.addWidget(self.pdf_page)

        layout.addWidget(self.media_stack, 1)

        self._current_media_path: Optional[str] = None

        if _HAS_MULTIMEDIA:
            self.media_player = QMediaPlayer(self)
            self.media_audio = QAudioOutput(self)
            self.media_player.setAudioOutput(self.media_audio)
            self.media_player.setVideoOutput(self.video_widget)
        else:
            self.media_player = None
            self.media_audio = None

        return page

    # -----------------------------
    # Slide and item behavior
    # -----------------------------
    @staticmethod
    def _normalize_slides(slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def _slide_sort_key(item: Dict[str, Any]):
            return int(item.get("slide_order") or 0)

        normalized = []
        for slide in slides:
            content = slide.get("content") or []
            content = sorted(content, key=lambda c: int(c.get("content_order") or 0))
            fixed = dict(slide)
            fixed["content"] = content
            normalized.append(fixed)

        return sorted(normalized, key=_slide_sort_key)

    def _find_first_dicom_source(self) -> Optional[Dict[str, Any]]:
        for slide in self.slides:
            for content in slide.get("content") or []:
                ctype = str(content.get("content_type") or "").lower()
                cdata = content.get("content_data") or {}
                if ctype in {"dicom_series", "dicom_study"} and cdata.get("study_uid"):
                    return cdata
        return None

    def _populate_slide_selector(self) -> None:
        self.slide_selector.blockSignals(True)
        self.slide_selector.clear()

        for idx, slide in enumerate(self.slides, start=1):
            title = str(slide.get("slide_title") or f"Slide {idx}").strip()
            self.slide_selector.addItem(f"Slide {idx}: {title}", idx - 1)

        self.slide_selector.blockSignals(False)

    def _set_current_slide(self, slide_index: int) -> None:
        if not self.slides:
            return

        slide_index = max(0, min(slide_index, len(self.slides) - 1))
        self.current_slide_index = slide_index
        self.slide_selector.blockSignals(True)
        self.slide_selector.setCurrentIndex(slide_index)
        self.slide_selector.blockSignals(False)

        slide = self.slides[slide_index]
        slide_title = str(slide.get("slide_title") or f"Slide {slide_index + 1}")
        self.slide_label.setText(f"{slide_title}")
        self.slide_notes.setText(str(slide.get("slide_notes") or ""))

        self.items_list.clear()
        items = slide.get("content") or []
        if not items:
            placeholder = QListWidgetItem("No items in this slide")
            placeholder.setData(Qt.UserRole, None)
            self.items_list.addItem(placeholder)
            self.items_list.setEnabled(False)
            self._show_media_message("No media item selected")
            return

        self.items_list.setEnabled(True)
        for item in items:
            ctype = str(item.get("content_type") or "unknown")
            cdata = item.get("content_data") or {}
            item_name = str(cdata.get("name") or cdata.get("description") or ctype)
            type_label = self._format_content_type_label(ctype)
            list_item = QListWidgetItem(f"{item_name}\n{type_label}")
            list_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            list_item.setToolTip(f"{type_label}: {item_name}")
            list_item.setIcon(self._build_item_icon(ctype))
            list_item.setData(Qt.UserRole, item)
            self.items_list.addItem(list_item)

        self.items_list.setCurrentRow(0)
        first_item = self.items_list.item(0)
        if first_item:
            self._on_item_clicked(first_item)

    def _previous_slide(self) -> None:
        self._set_current_slide(self.current_slide_index - 1)

    def _next_slide(self) -> None:
        self._set_current_slide(self.current_slide_index + 1)

    def _on_slide_selected(self, index: int) -> None:
        if index < 0:
            return
        self._set_current_slide(index)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.UserRole)
        if not payload:
            return

        ctype = str(payload.get("content_type") or "").lower()
        cdata = payload.get("content_data") or {}

        if ctype in {"dicom_series", "dicom_study", "dicom"}:
            self._load_dicom_content(ctype, cdata)
            return

        self._load_media_content(ctype, cdata)

    # -----------------------------
    # DICOM loading
    # -----------------------------
    def _load_dicom_content(self, content_type: str, content_data: Dict[str, Any]) -> None:
        self._stop_media_playback()
        self.education_content_stack.setCurrentIndex(0)

        if content_type == "dicom":
            folder_path = Path(str(content_data.get("path") or "").strip())
            if not folder_path.exists():
                QMessageBox.warning(self, "DICOM Unavailable", "The selected item has no valid folder.")
                return

            study_path, series_number = self._resolve_dicom_folder(folder_path, content_data)
            if not study_path or series_number is None:
                QMessageBox.warning(
                    self,
                    "DICOM Unavailable",
                    f"Unsupported DICOM folder structure:\n{folder_path}",
                )
                return

            self.import_folder_path = study_path
            self._ensure_random_ids_in_series(study_path, series_number)
            loaded = bool(self._load_single_series_on_demand(series_number, study_path=study_path))
            if loaded:
                self.change_series_on_viewer(str(series_number))
                self.switch_right_panel("series", force=True)
                return

            QMessageBox.warning(
                self,
                "DICOM Load Failed",
                f"Could not load DICOM content from folder:\n{folder_path}",
            )
            return

        study_uid = str(content_data.get("study_uid") or self.study_uid or "").strip()
        if not study_uid:
            QMessageBox.warning(self, "DICOM Unavailable", "The selected item has no study UID.")
            return

        study_path, _ = get_study_source_path(study_uid)
        if not study_path.exists():
            QMessageBox.warning(self, "DICOM Unavailable", f"Study folder not found: {study_path}")
            return

        self.study_uid = study_uid
        self.patient_id = content_data.get("patient_id") or self.patient_id
        self.import_folder_path = str(study_path)

        loaded = False

        if content_type == "dicom_series":
            raw_series_number = content_data.get("series_number")
            if raw_series_number is not None:
                try:
                    series_number = int(raw_series_number)
                    loaded = bool(self._load_single_series_on_demand(series_number, study_path=str(study_path)))
                    if loaded:
                        self.change_series_on_viewer(str(series_number))
                except Exception:
                    loaded = False

        if not loaded:
            first_series = self._find_first_series_number(study_path)
            if first_series is not None:
                loaded = bool(self._load_single_series_on_demand(first_series, study_path=str(study_path)))
                if loaded:
                    self.change_series_on_viewer(str(first_series))

        if not loaded:
            QMessageBox.warning(
                self,
                "DICOM Load Failed",
                f"Could not load DICOM content for study {study_uid}.",
            )
            return

        self.switch_right_panel("series", force=True)

    def _ensure_random_ids_in_series(self, study_path: str, series_number: int) -> None:
        """Fill missing IDs in education course DICOM assets with a random 6-digit value."""
        try:
            study_root = Path(study_path)
            if "Education" not in [p.name for p in study_root.parents] and study_root.name != "Education":
                return
            if not any(part.startswith("course_") for part in study_root.parts):
                return

            series_folder = study_root / str(series_number)
            if not series_folder.exists():
                return

            dicom_files = list(series_folder.glob("*.dcm")) + list(series_folder.glob("*.DCM"))
            if not dicom_files:
                return

            if not hasattr(self, "_edu_random_ids_by_study"):
                self._edu_random_ids_by_study = {}

            study_key = str(study_root)
            random_value = self._edu_random_ids_by_study.get(study_key)
            if not random_value:
                random_value = f"{random.randint(100000, 999999)}"
                self._edu_random_ids_by_study[study_key] = random_value

            try:
                from pydicom import dcmread
            except Exception:
                return

            def _needs_fill(value) -> bool:
                if value is None:
                    return True
                text = str(value).strip()
                if not text:
                    return True
                lowered = text.lower()
                return lowered in {"unknown", "unknown property", "unknown property content", "na", "n/a"}

            for path in dicom_files:
                try:
                    ds = dcmread(str(path), force=True)
                    changed = False

                    if _needs_fill(getattr(ds, "PatientID", None)):
                        ds.PatientID = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "StudyID", None)):
                        ds.StudyID = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "AccessionNumber", None)):
                        ds.AccessionNumber = random_value
                        changed = True

                    if _needs_fill(getattr(ds, "PatientName", None)):
                        ds.PatientName = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "StudyDescription", None)):
                        ds.StudyDescription = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "SeriesDescription", None)):
                        ds.SeriesDescription = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "InstitutionName", None)):
                        ds.InstitutionName = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "ReferringPhysicianName", None)):
                        ds.ReferringPhysicianName = random_value
                        changed = True
                    if _needs_fill(getattr(ds, "PerformingPhysicianName", None)):
                        ds.PerformingPhysicianName = random_value
                        changed = True

                    if changed:
                        if not getattr(ds, "file_meta", None):
                            ds.fix_meta_info()
                        ds.save_as(str(path), write_like_original=False)
                except Exception:
                    continue
        except Exception:
            return

    def _resolve_dicom_folder(
        self,
        folder_path: Path,
        content_data: Dict[str, Any],
    ) -> tuple[Optional[str], Optional[int]]:
        desired_series = content_data.get("series_number")
        if desired_series is not None:
            try:
                desired_series = int(desired_series)
            except (TypeError, ValueError):
                desired_series = None

        try:
            if not folder_path.exists() or not folder_path.is_dir():
                return None, None

            series_candidates = []
            for child in folder_path.iterdir():
                if not child.is_dir() or not child.name.isdigit():
                    continue
                if any(child.glob("*.dcm")) or any(child.glob("*.DCM")):
                    series_candidates.append(int(child.name))

            if series_candidates:
                series_candidates.sort()
                series_number = desired_series if desired_series in series_candidates else series_candidates[0]
                return str(folder_path), series_number

            has_dicom = any(folder_path.glob("*.dcm")) or any(folder_path.glob("*.DCM"))
            if has_dicom and folder_path.name.isdigit():
                return str(folder_path.parent), int(folder_path.name)
        except Exception:
            return None, None

        return None, None

    @staticmethod
    def _format_content_type_label(content_type: str) -> str:
        key = str(content_type or "").lower()
        if key in {"dicom", "dicom_series", "dicom_study"}:
            return "DICOM"
        if key == "image":
            return "IMAGE"
        if key == "video":
            return "VIDEO"
        if key == "audio":
            return "AUDIO"
        if key == "pdf":
            return "PDF"
        if key == "text":
            return "TEXT"
        return key.upper() if key else "ITEM"

    def _build_item_icon(self, content_type: str) -> QIcon:
        if not hasattr(self, "_item_icon_cache"):
            self._item_icon_cache = {}
        key = str(content_type or "").lower()
        if key in self._item_icon_cache:
            return self._item_icon_cache[key]

        color_map = {
            "dicom": QColor("#3b82f6"),
            "dicom_series": QColor("#3b82f6"),
            "dicom_study": QColor("#3b82f6"),
            "image": QColor("#22c55e"),
            "video": QColor("#f59e0b"),
            "audio": QColor("#a855f7"),
            "pdf": QColor("#ef4444"),
            "text": QColor("#64748b"),
        }
        icon_color = color_map.get(key, QColor("#64748b"))
        label = self._format_content_type_label(key)[:1]

        pixmap = QPixmap(40, 40)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(icon_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, 40, 40, 6, 6)
        painter.setPen(QColor("#f8fafc"))
        font = QFont("Segoe UI", 14, QFont.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, label)
        painter.end()

        icon = QIcon(pixmap)
        self._item_icon_cache[key] = icon
        return icon

    @staticmethod
    def _find_first_series_number(study_path: Path) -> Optional[int]:
        try:
            series_numbers = []
            for child in study_path.iterdir():
                if not child.is_dir() or not child.name.isdigit():
                    continue
                has_dicom = any(child.glob("*.dcm")) or any(child.glob("*.DCM"))
                if has_dicom:
                    series_numbers.append(int(child.name))
            if not series_numbers:
                return None
            return min(series_numbers)
        except Exception:
            return None

    # -----------------------------
    # Media loading
    # -----------------------------
    def _load_media_content(self, content_type: str, content_data: Dict[str, Any]) -> None:
        media_path = str(content_data.get("path") or "").strip()
        if not media_path or not Path(media_path).exists():
            self._show_media_message(f"File not found: {media_path or 'N/A'}")
            self.education_content_stack.setCurrentIndex(1)
            return

        self.education_content_stack.setCurrentIndex(1)

        content_type = content_type.lower()
        if content_type == "image":
            self._show_image(media_path)
        elif content_type == "video":
            self._show_video(media_path)
        elif content_type == "audio":
            self._show_audio(media_path)
        elif content_type == "pdf":
            self._show_pdf(media_path)
        else:
            self._show_media_message(f"Unsupported content type: {content_type}")

    def _show_media_message(self, message: str) -> None:
        self._stop_media_playback()
        self.media_message.setText(message)
        self.media_stack.setCurrentIndex(0)

    def _show_image(self, file_path: str) -> None:
        self._stop_media_playback()
        self._current_media_path = file_path
        self._current_image_path = file_path

        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            self._show_media_message("Unable to load image")
            return

        target_w = max(600, self.media_stack.width() - 20)
        target_h = max(420, self.media_stack.height() - 20)
        scaled = pixmap.scaled(
            target_w,
            target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.media_stack.setCurrentIndex(1)

    def _show_video(self, file_path: str) -> None:
        if not _HAS_MULTIMEDIA or not self.media_player:
            self._show_media_message("Video playback is unavailable on this system")
            return

        self._current_media_path = file_path
        self.media_player.setSource(QUrl.fromLocalFile(file_path))
        self.media_stack.setCurrentIndex(2)
        self.media_player.play()

    def _show_audio(self, file_path: str) -> None:
        if not _HAS_MULTIMEDIA or not self.media_player:
            self._show_media_message("Audio playback is unavailable on this system")
            return

        self._current_media_path = file_path
        self.audio_label.setText(f"Audio: {Path(file_path).name}")
        self.media_player.setSource(QUrl.fromLocalFile(file_path))
        self.media_stack.setCurrentIndex(3)
        self.media_player.play()

    def _show_pdf(self, file_path: str) -> None:
        self._stop_media_playback()
        self._current_media_path = file_path

        if _HAS_PDF and self.pdf_document is not None:
            error = self.pdf_document.load(file_path)
            if error == QPdfDocument.Error.None_:
                self.media_stack.setCurrentWidget(self.pdf_page)
                return

        self._show_media_message("PDF preview unavailable. Use external viewer.")
        self._open_current_media_external()

    def _play_media(self) -> None:
        if self.media_player:
            self.media_player.play()

    def _pause_media(self) -> None:
        if self.media_player:
            self.media_player.pause()

    def _stop_media_playback(self) -> None:
        if self.media_player:
            self.media_player.stop()

    def _open_current_media_external(self) -> None:
        if not self._current_media_path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_media_path))

    # -----------------------------
    # Course info and timer
    # -----------------------------
    def _update_course_info_panel(self) -> None:
        course_name = str(self.course_data.get("course_name") or "Untitled Course")
        author_name = str(self.course_data.get("author_name") or "Unknown")
        modality = str(self.course_data.get("modality") or "-")
        level = str(self.course_data.get("level") or "-")

        slide_count = len(self.slides)
        item_count = sum(len(slide.get("content") or []) for slide in self.slides)

        self.info_course_name.setText(f"Course: {course_name}")
        self.info_author.setText(f"Author: {author_name}")
        self.info_slides.setText(f"Slides: {slide_count}")
        self.info_items.setText(f"Items: {item_count}")
        self.info_meta.setText(f"Modality: {modality} | Level: {level}")

    def _start_footer_timers(self) -> None:
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self._tick_session)
        self.session_timer.start(1000)

        self._update_clock()
        self._tick_session()

    def _update_clock(self) -> None:
        self.clock_label.setText(QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"))

    def _tick_session(self) -> None:
        if self._session_running:
            self._session_seconds += 1

        minutes = self._session_seconds // 60
        seconds = self._session_seconds % 60
        self.session_label.setText(f"Session: {minutes:02d}:{seconds:02d}")

    def _toggle_session_timer(self) -> None:
        self._session_running = not self._session_running
        self.timer_toggle_btn.setText("Pause" if self._session_running else "Resume")

    def _reset_session_timer(self) -> None:
        self._session_seconds = 0
        self._tick_session()

    def closeEvent(self, event):
        self._stop_media_playback()
        if hasattr(self, "clock_timer"):
            self.clock_timer.stop()
        if hasattr(self, "session_timer"):
            self.session_timer.stop()
        super().closeEvent(event)


class EducationalCourseViewerWidget(EducationalPatientViewerWidget):
    """Semantic alias used by education module tab wiring."""

    pass
