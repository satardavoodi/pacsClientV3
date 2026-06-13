from __future__ import annotations

import html as _html
from pathlib import Path
import random
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDateTime, QEvent, QPointF, QRectF, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
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

import logging
logger = logging.getLogger(__name__)


class _ZoomPanGraphicsView(QGraphicsView):
    """A pixmap viewer with fit-to-view, zoom (buttons + wheel) and drag-pan."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = None
        self._fit = True
        self._in_fit = False  # re-entrancy guard: fitInView() can re-trigger resizeEvent
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setStyleSheet("background:#0f141b;border:1px solid #2f3c4d;")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def set_pixmap(self, pm: QPixmap) -> None:
        self._scene.clear()
        self._item = self._scene.addPixmap(pm)
        self._scene.setSceneRect(QRectF(pm.rect()))
        self.fit()

    def has_image(self) -> bool:
        return self._item is not None

    def fit(self) -> None:
        # Guard against the classic QGraphicsView trap: fitInView() can toggle a
        # scrollbar, which resizes the viewport and synchronously re-enters
        # resizeEvent() -> fit() -> ... (stack overflow / freeze). The guard makes
        # any re-entrant fit() during an in-progress fit a no-op.
        if self._item is None or self._in_fit:
            return
        self._in_fit = True
        try:
            self._fit = True
            self.resetTransform()
            self.fitInView(self._item, Qt.KeepAspectRatio)
        finally:
            self._in_fit = False

    def reset_view(self) -> None:
        self.fit()

    def zoom(self, factor: float) -> None:
        if self._item is None:
            return
        self._fit = False
        self.scale(factor, factor)

    def wheelEvent(self, event) -> None:
        if self._item is None:
            return
        self._fit = False
        self.scale(1.25 if event.angleDelta().y() > 0 else 0.8,
                   1.25 if event.angleDelta().y() > 0 else 0.8)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit:
            self.fit()


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

        # Education opens in the default 1x2 layout once the initial load settles.
        QTimer.singleShot(300, self._apply_default_education_layout)

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
        center_layout.setSpacing(6)

        # Content-type header: tells the user exactly what the viewport is
        # showing (DICOM / Image / PDF / Presentation / Notes + details).
        self.content_type_label = QLabel("")
        self.content_type_label.setStyleSheet(
            "color:#9ecbff; font-size:12px; font-weight:600; padding:1px 4px;")
        center_layout.addWidget(self.content_type_label, 0)

        # Content row: a compact vertical slide-nav beside the viewer/media, which
        # now own the full height (course metadata no longer lives in the dock).
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)

        self.education_content_stack = QStackedWidget()
        # Must be free to shrink so it can't overflow behind the bottom dock;
        # it expands to exactly fill the area above the footer.
        self.education_content_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.education_content_stack.setMinimumSize(0, 0)
        # Accept resources dragged from the Resources browser -> open in viewport.
        self.education_content_stack.setAcceptDrops(True)
        self.education_content_stack.installEventFilter(self)

        dicom_page = QWidget()
        dicom_page_layout = QVBoxLayout(dicom_page)
        dicom_page_layout.setContentsMargins(0, 0, 0, 0)
        dicom_page_layout.setSpacing(0)

        dicom_surface = QWidget()
        dicom_surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        dicom_surface.setMinimumSize(0, 0)
        self.vtk_layout = QGridLayout(dicom_surface)
        self.vtk_layout.setContentsMargins(8, 8, 8, 8)
        self.vtk_layout.setSpacing(8)
        dicom_page_layout.addWidget(dicom_surface, 1)

        self.education_content_stack.addWidget(dicom_page)

        self.media_page = self._build_media_page()
        self.education_content_stack.addWidget(self.media_page)

        content_row.addWidget(self.education_content_stack, 1)
        center_layout.addLayout(content_row, 1)

        # Item-focused dock (resources + item information), shorter than before so
        # the viewer/content gets the largest share of vertical space.
        footer = self._build_footer()
        # Guarantee a roomy resource browser (the teaching workflow's focus):
        # a minimum height so the dock can't collapse, with a sensible ceiling.
        footer.setMinimumHeight(196)
        footer.setMaximumHeight(240)
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

        # Footer = slim collapsible header  +  body (3 columns).  Collapsing the
        # body hands the vertical space back to the viewport.
        footer_v = QVBoxLayout(footer)
        footer_v.setContentsMargins(0, 0, 0, 0)
        footer_v.setSpacing(0)

        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(10, 6, 10, 2)
        header_row.setSpacing(8)
        # Metadata is referenced occasionally -> two on-demand Review popups.
        self.course_review_btn = QPushButton("ⓘ  Course Review")
        self.course_review_btn.setCursor(Qt.PointingHandCursor)
        self.course_review_btn.clicked.connect(self._show_course_overview)
        self.slide_review_btn = QPushButton("⧉  Slide Review")
        self.slide_review_btn.setCursor(Qt.PointingHandCursor)
        self.slide_review_btn.clicked.connect(self._show_slide_review)
        # Quick item stepper + position indicator.
        prev_item_btn = QPushButton("◀")
        prev_item_btn.setFixedWidth(30)
        prev_item_btn.setToolTip("Previous item")
        prev_item_btn.clicked.connect(self._previous_slide)
        self.header_item_label = QLabel("Item – / –")
        self.header_item_label.setStyleSheet("color:#cfe0f2; font-size:12px; font-weight:600;")
        next_item_btn = QPushButton("▶")
        next_item_btn.setFixedWidth(30)
        next_item_btn.setToolTip("Next item")
        next_item_btn.clicked.connect(self._next_slide)
        # Session controls.
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setStyleSheet("font-size: 11px; color:#6f7f93;")
        self.session_label = QLabel("Session: 00:00")
        self.session_label.setStyleSheet("font-size: 12px; color: #9fb4cc;")
        self.timer_toggle_btn = QPushButton("Pause")
        self.timer_toggle_btn.setFixedWidth(62)
        self.timer_toggle_btn.clicked.connect(self._toggle_session_timer)
        timer_reset_btn = QPushButton("Reset")
        timer_reset_btn.setFixedWidth(56)
        timer_reset_btn.clicked.connect(self._reset_session_timer)
        header_row.addWidget(self.course_review_btn, 0)
        header_row.addWidget(self.slide_review_btn, 0)
        header_row.addSpacing(12)
        header_row.addWidget(prev_item_btn, 0)
        header_row.addWidget(self.header_item_label, 0)
        header_row.addWidget(next_item_btn, 0)
        header_row.addStretch(1)
        header_row.addWidget(self.clock_label, 0)
        header_row.addWidget(self.session_label, 0)
        header_row.addWidget(self.timer_toggle_btn, 0)
        header_row.addWidget(timer_reset_btn, 0)
        footer_v.addWidget(header)

        self.dock_body = QWidget()
        root = QHBoxLayout(self.dock_body)
        root.setContentsMargins(10, 2, 10, 8)
        root.setSpacing(12)

        # Item selector (left): the list of items/slides in this course.
        sel_col = QFrame()
        sel_layout = QVBoxLayout(sel_col)
        sel_layout.setContentsMargins(6, 2, 6, 2)
        sel_layout.setSpacing(4)
        sel_label = QLabel("Items")
        sel_label.setStyleSheet("font-size: 11px; color:#8ea1b7; font-weight:600;")
        self.slides_list = QListWidget()
        self.slides_list.setStyleSheet(
            "QListWidget::item{ padding:5px 6px; } "
            "QListWidget::item:selected{ background:#1f4a67; }")
        self.slides_list.currentRowChanged.connect(self._on_slide_selected)
        sel_layout.addWidget(sel_label)
        sel_layout.addWidget(self.slides_list, 1)
        sel_col.setFixedWidth(432)  # ~80% wider so full item titles are readable

        # Resource browser (right): the current item's resources -- the focus of
        # the teaching workflow, so it takes the lion's share of the dock.
        res_col = QFrame()
        res_layout = QVBoxLayout(res_col)
        res_layout.setContentsMargins(6, 2, 6, 2)
        res_layout.setSpacing(4)
        res_label = QLabel("Resources")
        res_label.setStyleSheet("font-size: 11px; color:#8ea1b7; font-weight:600;")
        self.items_list = QListWidget()
        self.items_list.setViewMode(QListView.IconMode)
        self.items_list.setFlow(QListView.LeftToRight)
        self.items_list.setWrapping(True)
        self.items_list.setResizeMode(QListView.Adjust)
        self.items_list.setSpacing(10)
        self.items_list.setIconSize(QSize(44, 44))
        self.items_list.setGridSize(QSize(150, 92))
        self.items_list.setWordWrap(True)
        self.items_list.setDragEnabled(True)  # drag a resource into the viewport
        self.items_list.itemClicked.connect(self._on_item_clicked)
        res_layout.addWidget(res_label)
        res_layout.addWidget(self.items_list, 1)

        root.addWidget(sel_col, 0)
        root.addWidget(res_col, 1)
        footer_v.addWidget(self.dock_body)

        return footer

    def _show_slide_review(self) -> None:
        """Current item's information, on demand (kept out of the persistent UI)."""
        if not self.slides:
            return
        slide = self.slides[self.current_slide_index]
        title = str(slide.get("slide_title") or f"Item {self.current_slide_index + 1}")
        notes = str(slide.get("slide_notes") or "").strip()
        content = slide.get("content") or []
        modality = body = ""
        for it in content:
            cd = it.get("content_data") or {}
            if str(it.get("content_type") or "").lower().startswith("dicom"):
                modality = modality or str(cd.get("modality") or "")
                body = body or str(cd.get("body_part") or "")
        meta = []
        if modality:
            meta.append(f"Modality: {modality.upper()}")
        if body:
            meta.append(f"Body part: {body.title()}")
        level = str(self.course_data.get("level") or "").strip()
        if level:
            meta.append(f"Level: {level}")
        meta.append(f"Resources: {len(content)}")
        parts = [f"<h3 style='margin:0 0 6px'>{_html.escape(title)}</h3>",
                 f"<p style='color:#9ecbff;margin:0 0 8px'>{_html.escape('   ·   '.join(meta))}</p>"]
        if notes:
            parts.append(f"<div>{_html.escape(notes).replace(chr(10), '<br>')}</div>")
        else:
            parts.append("<p style='color:#9fb4cc'>No additional notes for this item.</p>")
        box = QMessageBox(self)
        box.setWindowTitle("Slide Review")
        box.setTextFormat(Qt.RichText)
        box.setText("".join(parts))
        box.setStandardButtons(QMessageBox.Close)
        box.exec()

    def _show_course_overview(self) -> None:
        """Course-level metadata, on demand (it is the least-used information)."""
        c = self.course_data or {}
        slide_count = len(self.slides)
        res_count = sum(len(s.get("content") or []) for s in self.slides)
        tags = c.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        parts = [
            f"<h3 style='margin:0 0 6px'>{_html.escape(str(c.get('course_name') or 'Course'))}</h3>",
            f"<p style='color:#9fb4cc;margin:0 0 8px'>{_html.escape(str(c.get('author_name') or 'Unknown'))}</p>",
            f"<b>Items:</b> {slide_count} &nbsp;&nbsp; <b>Resources:</b> {res_count}<br>",
            f"<b>Modality:</b> {_html.escape(str(c.get('modality') or '-'))} &nbsp;&nbsp; "
            f"<b>Level:</b> {_html.escape(str(c.get('level') or '-'))}",
        ]
        if tags:
            parts.append(f"<br><b>Tags:</b> {_html.escape(', '.join(map(str, tags)))}")
        desc = str(c.get("course_description") or "").strip()
        if desc:
            parts.append(f"<p style='margin-top:8px'>{_html.escape(desc)}</p>")
        box = QMessageBox(self)
        box.setWindowTitle("Course Review")
        box.setTextFormat(Qt.RichText)
        box.setText("".join(parts))
        box.setStandardButtons(QMessageBox.Close)
        box.exec()

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

        # ---- Adaptive media control bar (shows controls relevant to the content) ----
        self.media_controls = QFrame()
        mc = QHBoxLayout(self.media_controls)
        mc.setContentsMargins(0, 0, 0, 0)
        mc.setSpacing(4)

        def _ctl(text: str, tip: str, slot) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QToolButton{color:#cfe0f2;background:#1b2a3a;border:1px solid #2f3c4d;"
                "border-radius:4px;padding:3px 9px;font-size:12px;}"
                "QToolButton:hover{background:#27384b;}")
            b.clicked.connect(slot)
            return b

        self.btn_zoom_out = _ctl("−", "Zoom out", self._media_zoom_out)
        self.btn_zoom_in = _ctl("+", "Zoom in", self._media_zoom_in)
        self.btn_fit = _ctl("Fit", "Fit to viewport", self._media_fit)
        self.btn_reset = _ctl("Reset", "Reset view", self._media_fit)
        self.btn_prev_page = _ctl("◀", "Previous page", self._media_prev_page)
        self.btn_next_page = _ctl("▶", "Next page", self._media_next_page)
        self.btn_font_dec = _ctl("A−", "Smaller text", self._media_font_dec)
        self.btn_font_inc = _ctl("A+", "Larger text", self._media_font_inc)
        self._media_control_buttons = [
            self.btn_zoom_out, self.btn_zoom_in, self.btn_fit, self.btn_reset,
            self.btn_prev_page, self.btn_next_page, self.btn_font_dec, self.btn_font_inc,
        ]
        for b in self._media_control_buttons:
            mc.addWidget(b)
        mc.addStretch(1)
        self.media_controls.setVisible(False)
        layout.addWidget(self.media_controls)

        self._current_media_kind: Optional[str] = None
        self.media_stack = QStackedWidget()

        # Message/fallback page
        self.media_message = QLabel("Select a slide item to preview")
        self.media_message.setAlignment(Qt.AlignCenter)
        self.media_message.setStyleSheet("color: #9fb4cc; font-size: 13px;")
        message_page = QWidget()
        message_layout = QVBoxLayout(message_page)
        message_layout.addWidget(self.media_message, 1)
        self.media_stack.addWidget(message_page)

        # Image page (zoom / pan / fit via a graphics view)
        self.image_view = _ZoomPanGraphicsView()
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.addWidget(self.image_view, 1)
        self.media_stack.addWidget(image_page)

        # Video page -- a BARE HOST. ONE persistent VideoSlideWidget (its own
        # player + QVideoWidget + controls) is created on first use and reused for
        # the session; switching away only PAUSES it (never stop/destroy, which
        # deadlocks the UI thread). See _show_video / _play_in_persistent_player /
        # _pause_active_media.
        self.video_page = QWidget()
        self.video_host_layout = QVBoxLayout(self.video_page)
        self.video_host_layout.setContentsMargins(0, 0, 0, 0)
        self.media_stack.addWidget(self.video_page)

        # Audio page kept for stack-index stability; audio actually reuses the
        # persistent player on the video page.
        self.audio_page = QWidget()
        self.audio_host_layout = QVBoxLayout(self.audio_page)
        self.audio_host_layout.setContentsMargins(0, 0, 0, 0)
        self.media_stack.addWidget(self.audio_page)

        # ONE persistent video/audio player (VideoSlideWidget), created on first
        # use and reused all session. Never torn down mid-session (teardown
        # deadlocks the UI thread); switching away only pauses it.
        self._video_player = None

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

        # Text / notes page (learning objectives, teaching points, notes).
        self.media_text_page = QWidget()
        text_layout = QVBoxLayout(self.media_text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.media_text = QTextEdit()
        self.media_text.setReadOnly(True)
        self.media_text.setFrameShape(QFrame.NoFrame)
        self.media_text.setStyleSheet(
            "QTextEdit { background-color: #0d1117; color: #e8eef6; border: none; "
            "padding: 16px 22px; font-size: 14px; }"
        )
        text_layout.addWidget(self.media_text, 1)
        self.media_stack.addWidget(self.media_text_page)

        # Word document page: .docx is rendered inline (converted to HTML) so the
        # teaching document shows in the layout instead of opening externally.
        self.media_word_page = QWidget()
        word_layout = QVBoxLayout(self.media_word_page)
        word_layout.setContentsMargins(0, 0, 0, 0)
        word_layout.setSpacing(6)
        self.media_word = QTextBrowser()
        self.media_word.setOpenExternalLinks(True)
        self.media_word.setStyleSheet(
            "QTextBrowser { background-color: #ffffff; border: 1px solid #2f3c4d; }"
        )
        word_layout.addWidget(self.media_word, 1)
        self.word_open_external_btn = QPushButton("Open in external editor")
        self.word_open_external_btn.clicked.connect(self._open_current_media_external)
        word_layout.addWidget(self.word_open_external_btn, 0)
        self.media_stack.addWidget(self.media_word_page)

        layout.addWidget(self.media_stack, 1)

        self._current_media_path: Optional[str] = None
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
        if not hasattr(self, "slides_list"):
            return
        self.slides_list.blockSignals(True)
        self.slides_list.clear()
        for idx, slide in enumerate(self.slides, start=1):
            title = str(slide.get("slide_title") or f"Slide {idx}").strip()
            QListWidgetItem(f"{idx}.  {title}", self.slides_list)
        self.slides_list.blockSignals(False)

    def _set_current_slide(self, slide_index: int) -> None:
        if not self.slides:
            return

        slide_index = max(0, min(slide_index, len(self.slides) - 1))
        self.current_slide_index = slide_index
        if hasattr(self, "slides_list"):
            self.slides_list.blockSignals(True)
            self.slides_list.setCurrentRow(slide_index)
            self.slides_list.blockSignals(False)

        slide = self.slides[slide_index]
        if hasattr(self, "header_item_label"):
            self.header_item_label.setText(f"Item {slide_index + 1} / {len(self.slides)}")

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-fit the displayed image to the viewport whenever it changes size.
        try:
            if getattr(self, "media_stack", None) is not None and self.media_stack.currentIndex() == 1:
                self._fit_current_image()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        # Drag a resource tile from the Resources browser onto the viewport to
        # open it there (the viewport then renders it by type).
        try:
            if obj is getattr(self, "education_content_stack", None):
                et = event.type()
                if et == QEvent.DragEnter and event.mimeData() is not None:
                    event.acceptProposedAction()
                    return True
                if et == QEvent.Drop:
                    item = self.items_list.currentItem() if hasattr(self, "items_list") else None
                    if item is not None:
                        event.acceptProposedAction()
                        self._on_item_clicked(item)
                        return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.UserRole)
        if not payload:
            return

        # CRITICAL: release any playing media FIRST, while its page is still
        # visible. _teardown_media() stops it AND detaches the video sink from the
        # QVideoWidget. If a video/audio was active, defer the actual switch to the
        # next event-loop turn so the native (Windows) media backend can finish
        # releasing on its own thread BEFORE we hide the widget / load a DICOM
        # study -- doing both in one call stack freezes / crashes the backend.
        media_was_active = getattr(self, "_current_media_kind", None) in ("video", "audio")
        self._teardown_media()
        if media_was_active:
            QTimer.singleShot(0, lambda p=payload: self._dispatch_item_payload(p))
        else:
            self._dispatch_item_payload(payload)

    def _dispatch_item_payload(self, payload: Dict[str, Any]) -> None:
        try:
            ctype = str(payload.get("content_type") or "").lower()
            cdata = payload.get("content_data") or {}
            if ctype in {"dicom_series", "dicom_study", "dicom"}:
                self._load_dicom_content(ctype, cdata)
            else:
                self._load_media_content(ctype, cdata)
        except Exception as exc:
            logger.info("[EDU] item dispatch failed: %s", exc)

    # -----------------------------
    # DICOM loading
    # -----------------------------
    def _load_dicom_content(self, content_type: str, content_data: Dict[str, Any]) -> None:
        self._stop_media_playback()
        self.education_content_stack.setCurrentIndex(0)
        _dname = str(content_data.get("name") or content_data.get("study_uid") or "Study")
        _ddesc = str(content_data.get("description") or "").strip()
        self._set_content_header("DICOM", f"{_dname}  ·  {_ddesc}" if _ddesc else _dname)

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

            self.study_uid = str(content_data.get("study_uid") or "").strip()
            self.import_folder_path = study_path
            self._ensure_random_ids_in_series(study_path, series_number)
            # Populate the series-thumbnail rail for this study (same mechanism
            # the normal patient pipeline uses) so every series is browsable and
            # clickable -- this also gives a click-to-load fallback if the
            # auto-load of the first series doesn't take.
            rail_count = self._populate_education_series_rail()
            loaded = bool(self._load_single_series_on_demand(series_number, study_path=study_path))
            if loaded:
                self.change_series_on_viewer(str(series_number))
            # Always reveal the series rail so the user can pick a series.
            self.switch_right_panel("series", force=True)
            # Keep the default 1x2 teaching layout, then fit the series to its pane.
            QTimer.singleShot(60, self._apply_default_education_layout)
            QTimer.singleShot(180, self._fit_education_dicom)
            if loaded:
                return

            # Auto-load didn't take: if the rail is populated the user can simply
            # click a series, so don't block them with a modal -- only warn when
            # there is genuinely nothing to show.
            if not rail_count:
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

    def _populate_education_series_rail(self) -> int:
        """Render the left series-thumbnail rail for the current study.

        Mirrors the normal patient pipeline (clear -> reset -> show_exist_thumbnails)
        but for a locally-migrated education study.  Reads the pre-rendered PNGs
        from THUMBNAIL_PATH/<study_uid>/<series>.png (generated by
        tools/migration/generate_education_thumbnails.py).  Returns the number of
        series thumbnails shown.
        """
        # Clear the rail grid directly (PatientWidget has no clear_thumbnails);
        # this is the same teardown the multi-study render path uses.
        try:
            grid = getattr(self, "thumb_grid", None)
            if grid is not None:
                while grid.count():
                    item = grid.takeAt(0)
                    w = item.widget() if item else None
                    if w is not None:
                        w.deleteLater()
        except Exception:
            pass
        try:
            # Education loads one study at a time -- never the multi-study grouped path.
            self._thumbnails_shown = False
            self._is_multistudy_hint = False
            self._studies_series = {}
            if hasattr(self, "show_exist_thumbnails"):
                return int(self.show_exist_thumbnails() or 0)
        except Exception:
            pass
        return 0

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
        """Error boundary: a bad/unsupported attachment must never crash the app."""
        try:
            self._load_media_content_impl(content_type, content_data)
        except Exception as exc:
            logger.exception("[EDU_MEDIA] load failed (type=%s): %s", content_type, exc)
            try:
                self._pause_active_media()
                self._show_media_message(
                    "This item could not be displayed.\n"
                    "The file may be unsupported or damaged (details in the log).")
            except Exception:
                pass

    def _load_media_content_impl(self, content_type: str, content_data: Dict[str, Any]) -> None:
        content_type = (content_type or "").lower()
        name = str(content_data.get("name") or content_data.get("source_name") or "").strip()
        logger.info("[EDU_MEDIA] load type=%s name=%s", content_type,
                    str(content_data.get("path") or name)[:120])

        # Text / notes content has no file path -- render the text itself
        # instead of reporting a missing file.
        if content_type == "text":
            self.education_content_stack.setCurrentIndex(1)
            self._set_content_header("Notes", name)
            self._show_text(content_data)
            return

        media_path = str(content_data.get("path") or "").strip()
        fname = Path(media_path).name if media_path else (name or "—")
        if not media_path or not Path(media_path).exists():
            self._set_content_header("Unavailable", fname)
            self._show_media_message(f"File not found: {media_path or 'N/A'}")
            self.education_content_stack.setCurrentIndex(1)
            return

        self.education_content_stack.setCurrentIndex(1)

        if content_type == "image":
            self._set_content_header("Image", fname)
            self._show_image(media_path)
        elif content_type == "video":
            self._set_content_header("Video", fname)
            self._show_video(media_path)
        elif content_type == "audio":
            self._set_content_header("Audio", fname)
            self._show_audio(media_path)
        elif content_type == "pdf":
            self._set_content_header("PDF", fname)
            self._show_pdf(media_path)
        elif Path(media_path).suffix.lower() == ".docx":
            # Word documents render inline (converted to HTML) -- regardless of the
            # stored content_type (Word arrives as 'attachment'/'document').
            self._set_content_header("Document", fname)
            self._show_word(media_path)
        elif content_type in ("presentation", "document", "attachment", "archive", "other"):
            label = {"presentation": "Presentation", "document": "Document",
                     "attachment": "Attachment", "archive": "Archive",
                     "other": "Resource"}.get(content_type, "Resource")
            self._set_content_header(label, fname)
            self._show_external_resource(label, media_path)
        else:
            self._set_content_header("Resource", fname)
            self._show_media_message(f"Unsupported content type: {content_type}")

    def _set_content_header(self, kind: str, detail: str = "") -> None:
        """Update the viewport's content-type indicator (e.g. 'PDF · file.pdf')."""
        if hasattr(self, "content_type_label"):
            self.content_type_label.setText(f"{kind}  ·  {detail}" if detail else kind)

    def _show_external_resource(self, label: str, file_path: str) -> None:
        """Presentations / office docs / archives can't render in-app -- show a
        clear message and open the file in its native application."""
        self._stop_media_playback()
        self._current_media_path = file_path
        self.media_message.setText(
            f"{label}: {Path(file_path).name}\n\nOpening in its external application…")
        self.media_stack.setCurrentIndex(0)
        self._set_media_controls("none")
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
        except Exception:
            pass

    def _show_word(self, file_path: str) -> None:
        """Render a Word (.docx) document inline by converting it to HTML.

        Falls back to opening externally if the file can't be parsed (e.g. a
        legacy binary .doc saved with a .docx extension)."""
        self._stop_media_playback()
        self._current_media_path = file_path
        try:
            from modules.education.docx_render import docx_to_html
            html_doc = docx_to_html(file_path)
        except Exception as exc:
            logger.info("[EDU] inline Word render failed for %s: %s", file_path, exc)
            self._show_external_resource("Document", file_path)
            return
        self.media_word.setHtml(html_doc)
        self.media_stack.setCurrentWidget(self.media_word_page)
        self._set_media_controls("word")

    def _show_media_message(self, message: str) -> None:
        self._stop_media_playback()
        self.media_message.setText(message)
        self.media_stack.setCurrentIndex(0)
        if hasattr(self, "media_controls"):
            self._set_media_controls("none")

    # -----------------------------
    # Media controls (zoom / pan / page / font / seek)
    # -----------------------------
    def _set_media_controls(self, kind: str) -> None:
        """Show only the controls relevant to the current content type."""
        self._current_media_kind = kind
        zoomable = kind in ("image", "pdf")
        pageable = kind == "pdf"
        fontable = kind in ("text", "word")
        for b in (self.btn_zoom_out, self.btn_zoom_in, self.btn_fit, self.btn_reset):
            b.setVisible(zoomable)
        for b in (self.btn_prev_page, self.btn_next_page):
            b.setVisible(pageable)
        for b in (self.btn_font_dec, self.btn_font_inc):
            b.setVisible(fontable)
        self.media_controls.setVisible(zoomable or pageable or fontable)

    def _media_zoom_in(self) -> None:
        self._media_zoom(1.25)

    def _media_zoom_out(self) -> None:
        self._media_zoom(0.8)

    def _media_zoom(self, factor: float) -> None:
        k = getattr(self, "_current_media_kind", None)
        if k == "image":
            self.image_view.zoom(factor)
        elif k == "pdf":
            self._pdf_zoom(factor)

    def _media_fit(self) -> None:
        k = getattr(self, "_current_media_kind", None)
        if k == "image":
            self.image_view.fit()
        elif k == "pdf" and _HAS_PDF:
            try:
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
            except Exception:
                pass

    def _pdf_zoom(self, factor: float) -> None:
        if not _HAS_PDF:
            return
        try:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(
                max(0.1, min(8.0, float(self.pdf_view.zoomFactor()) * factor)))
        except Exception:
            pass

    def _media_prev_page(self) -> None:
        self._pdf_jump(-1)

    def _media_next_page(self) -> None:
        self._pdf_jump(1)

    def _pdf_jump(self, delta: int) -> None:
        if not _HAS_PDF or self.pdf_document is None:
            return
        try:
            nav = self.pdf_view.pageNavigator()
            target = nav.currentPage() + delta
            if 0 <= target < self.pdf_document.pageCount():
                nav.jump(target, QPointF(), nav.currentZoom())
        except Exception:
            pass

    def _media_font_inc(self) -> None:
        self._font_zoom(1)

    def _media_font_dec(self) -> None:
        self._font_zoom(-1)

    def _font_zoom(self, step: int) -> None:
        target = (self.media_word
                  if getattr(self, "_current_media_kind", None) == "word"
                  else self.media_text)
        try:
            target.zoomIn(1) if step > 0 else target.zoomOut(1)
        except Exception:
            pass

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        s = max(0, int(ms)) // 1000
        return f"{s // 60}:{s % 60:02d}"

    def _show_text(self, content_data: Dict[str, Any]) -> None:
        """Render a text/notes content item (objectives, teaching points)."""
        self._stop_media_playback()
        name = str(content_data.get("name") or "Notes").strip()
        body = str(content_data.get("text") or "").strip()
        parts = [f"<h3 style='color:#9ecbff;margin:0 0 10px 0;'>{_html.escape(name)}</h3>"]
        if body:
            safe = _html.escape(body).replace("\n", "<br>")
            parts.append(f"<div style='line-height:1.55;'>{safe}</div>")
        else:
            parts.append("<div style='color:#9fb4cc;'>No additional notes for this item.</div>")
        self.media_text.setHtml("".join(parts))
        self.media_stack.setCurrentWidget(self.media_text_page)
        self._set_media_controls("text")

    def _show_image(self, file_path: str) -> None:
        self._stop_media_playback()
        self._current_media_path = file_path
        self._current_image_path = file_path

        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            self._current_image_pixmap = None
            self._show_media_message("Unable to load image")
            return

        # The graphics view owns zoom / pan / fit; load the original pixmap and
        # fit it to the viewport (scales down for small panes, up for large).
        self._current_image_pixmap = pixmap
        self.image_view.set_pixmap(pixmap)
        self.media_stack.setCurrentIndex(1)
        self._set_media_controls("image")
        # The pane may not have its final size yet right after a switch / drop;
        # re-fit once the layout has settled.
        QTimer.singleShot(0, self._fit_current_image)
        QTimer.singleShot(60, self._fit_current_image)

    def _fit_current_image(self) -> None:
        """Fit the current image to the viewport (keep aspect)."""
        if self.media_stack.currentIndex() == 1 and hasattr(self, "image_view"):
            self.image_view.fit()

    def _apply_default_education_layout(self) -> None:
        """Open the education viewer in the default 1x2 layout (two side-by-side
        panes) so a teaching case can show two series at once. Uses the same
        public layout call the toolbar's layout picker uses."""
        try:
            vc = getattr(self, "viewer_controller", None)
            if getattr(vc, "_current_layout", None) == (1, 2):
                return  # already in the default layout; avoid a redundant rebuild
            if hasattr(self, "apply_multi_viewer"):
                self.apply_multi_viewer((1, 2), modify_by_user=True)
        except Exception:
            pass

    def _fit_education_dicom(self) -> None:
        """Fit the freshly-loaded DICOM to its (education) viewport by calling the
        FAST viewer's existing fit method on this widget's own panes. Education
        instance only -- does not change the shared viewer's resize behaviour."""
        try:
            surface = self.vtk_layout.parentWidget() if getattr(self, "vtk_layout", None) else None
            if surface is None:
                return
            fitted = 0
            for w in surface.findChildren(QWidget):
                for meth in ("zoom_to_fit", "reset_view", "fit_to_window"):
                    fn = getattr(w, meth, None)
                    if callable(fn):
                        try:
                            fn()
                            fitted += 1
                        except Exception:
                            pass
                        break
                if fitted >= 4:  # safety cap (multi-pane)
                    break
        except Exception:
            pass

    def _show_video(self, file_path: str) -> None:
        if not _HAS_MULTIMEDIA:
            self._show_media_message("Video playback is unavailable on this system")
            return
        self._current_media_path = file_path
        self.media_stack.setCurrentWidget(self.video_page)
        self._set_media_controls("video")
        if not self._play_in_persistent_player(file_path):
            self._show_external_resource("Video", file_path)

    def _show_audio(self, file_path: str) -> None:
        if not _HAS_MULTIMEDIA:
            self._show_media_message("Audio playback is unavailable on this system")
            return
        self._current_media_path = file_path
        # Audio reuses the same persistent player on the video page (it shows a
        # black frame + transport controls for an audio-only file).
        self.media_stack.setCurrentWidget(self.video_page)
        self._set_media_controls("video")
        if not self._play_in_persistent_player(file_path):
            self._show_external_resource("Audio", file_path)

    def _play_in_persistent_player(self, file_path: str) -> bool:
        """Play in ONE persistent VideoSlideWidget that is created once and reused
        for the whole session.

        The player is NEVER stopped / torn down / destroyed while in use, because
        every QMediaPlayer teardown call (stop / setVideoOutput / setSource(empty)
        / delete) deadlocks this app's UI thread (confirmed via py-spy hung-stack
        dumps -- the deadlock only manifests in the full app context). Switching
        away merely PAUSES it (_pause_active_media). Loading a new clip happens
        while the widget is VISIBLE (setSource + play), which does not deadlock."""
        try:
            from modules.education.video_slide_widget import VideoSlideWidget
            if self._video_player is None:
                self._video_player = VideoSlideWidget(file_path, autoplay=True)
                self.video_host_layout.addWidget(self._video_player)
            else:
                self._video_player.set_video(file_path, autoplay=True)
        except Exception as exc:
            logger.info("[EDU_MEDIA] video play failed for %s: %s", file_path, exc)
            return False
        logger.info("[EDU_MEDIA] playing: %s", Path(file_path).name)
        return True

    def _show_pdf(self, file_path: str) -> None:
        self._stop_media_playback()
        self._current_media_path = file_path

        if _HAS_PDF and self.pdf_document is not None:
            error = self.pdf_document.load(file_path)
            if error == QPdfDocument.Error.None_:
                # Fit the page to the viewport so it scales to the pane size.
                try:
                    self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
                except Exception:
                    pass
                self.media_stack.setCurrentWidget(self.pdf_page)
                self._set_media_controls("pdf")
                return

        self._show_media_message("PDF preview unavailable. Use external viewer.")
        self._open_current_media_external()

    def _pause_active_media(self) -> None:
        """PAUSE the persistent player without tearing it down.

        Called on every content switch / before showing other content. We never
        stop/destroy the player mid-session because QMediaPlayer teardown
        deadlocks this app's UI thread; a paused, hidden player is safe and is
        reused for the next clip. pause() is the only media control proven safe
        in-app."""
        vp = getattr(self, "_video_player", None)
        if vp is not None:
            try:
                vp.pause_only()
            except Exception:
                pass

    # Names kept for the many existing call sites -- all now pause-only.
    def _stop_media_playback(self) -> None:
        self._pause_active_media()

    def _teardown_media(self) -> None:
        self._pause_active_media()

    def _open_current_media_external(self) -> None:
        if not self._current_media_path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_media_path))

    # -----------------------------
    # Course info and timer
    # -----------------------------
    def _update_course_info_panel(self) -> None:
        # Course + slide metadata now live behind the Review popups; nothing is
        # shown persistently. Keep the course name on the button tooltip.
        if hasattr(self, "course_review_btn"):
            self.course_review_btn.setToolTip(
                str(self.course_data.get("course_name") or "Course Review"))

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
