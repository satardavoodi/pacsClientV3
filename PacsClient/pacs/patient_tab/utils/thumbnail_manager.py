from PySide6.QtCore import QSize, Signal, QPropertyAnimation, QEasingCurve, QTimer, QRect
from PySide6.QtGui import QPixmap, Qt, QFont, QPainter, QPen, QBrush, QLinearGradient, QColor, QPainterPath, QImage
from PySide6.QtWidgets import QPushButton, QWidget, QLabel, QVBoxLayout, QApplication, QGridLayout, QProgressBar, QHBoxLayout, QFrame, QGraphicsDropShadowEffect
import logging
import weakref 
from PySide6.QtCore import QObject, Signal, QTimer, QThread

from PySide6.QtCore import QMimeData, QByteArray, Qt, Property, QRectF
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QDrag, QMouseEvent, QPixmap, QConicalGradient, QIcon
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QWidget, QLabel, QProgressBar
from PySide6.QtCore import Qt
import math
import time
from PacsClient.utils.theme_manager import get_theme_manager
from modules.viewer.fast.ui_throttle import (
    is_fast_interaction_active,
    is_heavy_download_active,
    should_admit as _ui_should_admit,
    thumbnail_log_interval_ms,
    thumbnail_progress_interval_ms,
)
from modules.viewer.fast.slot_timing import time_slot as _g6_time_slot
from modules.viewer.fast.slot_timing import slot_timing as _g6_slot_timing

_tm_logger = logging.getLogger(__name__)


class CircularProgressborder(QFrame):
    """
    Circular progress border widget that shows download progress as a colored border around thumbnail
    ویجت بوردر دایره‌ای که پیشرفت دانلود را به صورت یک بوردر رنگی دور تامب‌نیل نمایش می‌دهد
    """
    
    def __init__(self, parent=None, theme=None):
        super().__init__(parent)
        self._progress = 0  # 0-100
        self._border_width = 2  # border thickness
        self._downloading = False
        self._is_ready = False
        self._is_selected = False
        # Session "viewed" mark: True once this series has been loaded into a
        # viewport. A viewed series shows a green border when it is not the
        # active series (purple while active). In-memory only; the
        # authoritative set lives on ThumbnailManager.viewed_series.
        self._viewed = False
        self._theme = theme if theme else get_theme_manager().current_theme()
        self.theme_manager = get_theme_manager()
        
        # Animation for smooth progress updates
        self._animation = QPropertyAnimation(self, b"progress")
        self._animation.setDuration(400)  # 400ms smooth animation
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        
        # Make background transparent
        self.setStyleSheet("background: transparent; border: none;")
        
        # Shadow effect for better visibility
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(12)
        self._shadow.setColor(QColor(59, 130, 246, 100))  # Blue glow
        
        # Progress percentage label (overlay on entire widget)
        self._progress_label = QLabel(self)
        self._progress_label.setAlignment(Qt.AlignCenter)
        self._progress_label.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(59, 130, 246, 240),
                    stop:1 rgba(37, 99, 235, 240));
                color: #ffffff;
                font-size: 24px;
                font-weight: bold;
                border: 3px solid rgba(255, 255, 255, 150);
                border-radius: 25px;
                padding: 10px 20px;
            }
        """)
        self._progress_label.setVisible(False)
        
        # Position label in center
        self._progress_label.setGeometry(0, 0, 90, 45)
        
        # Raise label to top to ensure it's visible over everything
        self._progress_label.raise_()

    def force_green_border(self):
        """Force the border to show green immediately"""
        self._is_ready = True
        self._downloading = False
        self._progress = 100
        self._border_color = QColor(16, 185, 129)  # Green
        self._border_width = 2
        
        # Force immediate repaint
        self.update()
        self.repaint()
        
        # Also update via style sheet as backup
        self.setStyleSheet("""
            CircularProgressborder {
                border: 2px solid #10b981;
                border-radius: 8px;
                background: transparent;
            }
        """)     

    def get_progress(self):
        return self._progress
    
    def set_progress(self, value):
        self._progress = max(0, min(100, value))
        
        # Update progress label text and visibility
        if self._downloading and self._progress > 0 and self._progress < 100:
            self._progress_label.setText(f"{int(self._progress)}%")
            
            # Reset to blue style for downloading
            self._progress_label.setStyleSheet("""
                QLabel {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(59, 130, 246, 240),
                        stop:1 rgba(37, 99, 235, 240));
                    color: #ffffff;
                    font-size: 24px;
                    font-weight: bold;
                    border: 3px solid rgba(255, 255, 255, 150);
                    border-radius: 25px;
                    padding: 10px 20px;
                }
            """)
            self._progress_label.setVisible(True)
            
            # Center the label
            self._center_progress_label()
        else:
            self._progress_label.setVisible(False)
        
        self.update()  # Trigger repaint
    
    def _center_progress_label(self):
        """Center the progress label in the frame"""
        label_width = 90
        label_height = 45
        x = (self.width() - label_width) // 2
        # Position slightly above center for better visibility
        y = (self.height() - label_height) // 2 - 10
        self._progress_label.setGeometry(x, y, label_width, label_height)
    
    def resizeEvent(self, event):
        """Handle resize to keep label centered"""
        super().resizeEvent(event)
        self._center_progress_label()
    
    # Define as Qt Property for animation
    progress = Property(float, get_progress, set_progress)
    
    def setProgressAnimated(self, value):
        """Set progress with smooth animation"""
        if self._animation.state() == QPropertyAnimation.Running:
            self._animation.stop()
        
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(value)
        self._animation.start()
        
        # If reaching 100%, trigger ready state after animation
        if value >= 100:
            QTimer.singleShot(450, lambda: self.setReady(True))  # 450ms = animation time + buffer
    
    def setDownloading(self, downloading: bool):
        """Set downloading state"""
        self._downloading = downloading
        if downloading:
            self._is_ready = False
            # Show progress label if downloading
            if self._progress > 0 and self._progress < 100:
                self._progress_label.setVisible(True)
        else:
            # Hide progress label when not downloading
            self._progress_label.setVisible(False)
        self.update()
        

    def setReady(self, ready: bool):
        """Set ready state - FIXED VERSION"""
        self._is_ready = ready
        if ready:
            self._downloading = False
            self._progress = 100  # Ensure progress is 100%
            
            # Show "Ready" message briefly, then hide
            if hasattr(self, '_progress_label'):
                self._progress_label.setText("✅ Ready")
                self._progress_label.setStyleSheet("""
                    QLabel {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(16, 185, 129, 240),
                            stop:1 rgba(5, 150, 105, 240));
                        color: #ffffff;
                        font-size: 20px;
                        font-weight: bold;
                        border: 3px solid rgba(255, 255, 255, 150);
                        border-radius: 25px;
                        padding: 10px 20px;
                    }
                """)
                self._progress_label.setVisible(True)
                
                # Force update immediately
                self._progress_label.update()
                
                # Hide after 2.5 seconds (تغییر از 2000 به 2500)
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2500, lambda: self._hide_ready_label())
        
        # Force immediate repaint
        self.update()


    def _hide_ready_label(self):
        """Hide the ready/progress label with safety checks"""
        try:
            # ✅ FIX: Use _progress_label (the actual attribute) instead of _ready_label
            if not hasattr(self, '_progress_label') or self._progress_label is None:
                return
                
            # Check if the underlying C++ object still exists
            try:
                self._progress_label.hide()
                self._progress_label.update()
            except RuntimeError:
                # Object already deleted, ignore
                pass
                
        except Exception as e:
            _tm_logger.debug("error hiding ready label: %s", e)

    # Also fix the timer callback in create_thumbnail_widget or similar:
    def on_thumbnail_ready(self):
        """Handle thumbnail ready state"""
        try:
            # Check if widget still exists
            if not self or not hasattr(self, 'progress_border'):
                return
                
            # Safely update
            try:
                self.progress_border.update()
            except RuntimeError:
                pass  # Object deleted
                
        except Exception as e:
            _tm_logger.debug("error in on_thumbnail_ready: %s", e)

    def cleanup(self):
        """Clean up resources and timers"""
        try:
            # Disconnect from the app-lifetime ThemeManager so the closed tab's
            # thumbnail manager does not stay pinned as a live signal receiver.
            try:
                if getattr(self, 'theme_manager', None) is not None:
                    self.theme_manager.themeChanged.disconnect(self._on_theme_changed)
            except (TypeError, RuntimeError):
                pass
            if hasattr(self, 'dot_timer') and self.dot_timer:
                self.dot_timer.stop()
                self.dot_timer.deleteLater()

            if hasattr(self, '_animation') and self._animation:
                self._animation.stop()
                self._animation.deleteLater()
                
            # Clean up progress label if it exists
            if hasattr(self, '_progress_label') and self._progress_label:
                try:
                    self._progress_label.setParent(None)  # Remove from parent
                    self._progress_label.deleteLater()   # Schedule for deletion
                except RuntimeError:
                    pass  # Label already deleted
        except Exception:
            pass
                
    def setSelected(self, selected: bool):
        """Set selected state"""
        self._is_selected = selected
        
        # Update shadow effect for selected state
        try:
            # Check if shadow effect is still valid (C++ object not deleted)
            if self._shadow is None:
                self._shadow = QGraphicsDropShadowEffect(self)
                self._shadow.setOffset(0, 0)
            
            # Try to access shadow - will fail if C++ object is deleted
            try:
                _ = self._shadow.blurRadius()
            except RuntimeError:
                # C++ object was deleted, recreate it
                self._shadow = QGraphicsDropShadowEffect(self)
                self._shadow.setOffset(0, 0)
            
            if selected:
                self._shadow.setBlurRadius(18)
                self._shadow.setColor(QColor(34, 211, 238, 150))  # Cyan glow
                self.setGraphicsEffect(self._shadow)
            else:
                self._shadow.setBlurRadius(12)
                self._shadow.setColor(QColor(59, 130, 246, 100))  # Blue glow
                if not self._downloading:
                    self.setGraphicsEffect(None)
        except RuntimeError:
            # C++ object already deleted, ignore
            pass
        
        self.update()
    
    def paintEvent(self, event):
        """Custom paint for circular progress border"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        rect = self.rect()
        
        # Create rounded rect path for the border
        border_rect = QRectF(
            rect.x() + self._border_width / 2,
            rect.y() + self._border_width / 2,
            rect.width() - self._border_width,
            rect.height() - self._border_width
        )
        
        radius = 8  # border radius
        
        # Determine border color and style based on state.
        # Thumbnail border meaning (fixed colors, theme-independent so the
        # blue / purple / green semantics hold under every app theme):
        #   Purple - the series is currently active / being viewed.
        #   Green  - the series has been viewed at least once and is no
        #            longer the active series.
        #   Blue   - the series is downloaded but not viewed yet.
        # A download in progress keeps its blue progress arc; a series that
        # is neither downloaded nor viewed stays gray (pending).
        # All five states now derive their colour from the active workstation
        # theme:
        #   selected   → accent        (was hard-coded purple #8b5cf6)
        #   viewed     → success       (was hard-coded green   #10b981)
        #   ready      → info          (was hard-coded blue    #3b82f6)
        #   downloading→ info
        #   pending    → border (neutral grey)
        # This keeps the SEMANTIC palette (accent=current, success=done,
        # info=available) but lets it shift with the workstation theme so
        # the thumbnail badges stop fighting non-Blue palettes.
        if self._is_selected:
            border_color = QColor(self._theme.get('accent', '#8b5cf6'))
            bg_color = QColor(self._theme.get('accent', '#8b5cf6'))
            bg_color.setAlpha(30)
        elif self._viewed and not self._downloading:
            # `success` token — universally "completed" across themes.
            border_color = QColor(self._theme.get('success', '#10b981'))
            bg_color = QColor(self._theme.get('success', '#10b981'))
            bg_color.setAlpha(22)
        elif self._is_ready:
            # `info` token — "available, not yet viewed".
            border_color = QColor(self._theme.get('info', '#3b82f6'))
            bg_color = QColor(self._theme.get('info', '#3b82f6'))
            bg_color.setAlpha(20)
        elif self._downloading and self._progress > 0:
            # Downloading - Use theme info color (blue)
            border_color = QColor(self._theme.get('info', '#3b82f6'))
            bg_color = QColor(self._theme.get('info', '#3b82f6'))
            bg_color.setAlpha(20)
        else:
            # Pending - Use theme border color (gray)
            border_color = QColor(self._theme.get('border', '#718096'))
            bg_color = QColor(self._theme.get('border', '#718096'))
            bg_color.setAlpha(10)
        
        # Draw background
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(border_rect, radius, radius)
        
        # Draw border
        if self._downloading and self._progress > 0 and self._progress < 100:
            # Progress border - draw arc based on progress
            pen = QPen(border_color, self._border_width, Qt.SolidLine)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            
            # Draw background circle (gray)
            painter.setPen(QPen(QColor(45, 55, 72), self._border_width, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(border_rect, radius, radius)
            
            # Draw progress arc
            # Calculate arc based on progress (0-360 degrees)
            # Start from top (270 degrees in Qt) and go clockwise
            start_angle = 90 * 16  # Qt uses 1/16th degree units, start from top
            span_angle = -int((self._progress / 100.0) * 360 * 16)  # Negative for clockwise
            
            # Create gradient for progress
            gradient = QConicalGradient(border_rect.center(), 90)
            gradient.setColorAt(0, QColor(59, 130, 246, 255))  # Blue
            gradient.setColorAt(self._progress / 100.0, QColor(139, 92, 246, 255))  # Purple
            gradient.setColorAt(1, QColor(59, 130, 246, 100))  # Faded blue
            
            pen.setBrush(QBrush(gradient))
            pen.setColor(border_color)
            painter.setPen(pen)
            painter.drawArc(border_rect.toRect(), start_angle, span_angle)
            
        elif not self._downloading or self._is_ready:
            # Solid border for pending/ready/selected/viewed
            if self._is_ready or self._is_selected or self._viewed:
                # Solid border
                pen = QPen(border_color, self._border_width, Qt.SolidLine)
            else:
                # Dashed border for pending
                pen = QPen(border_color, 2, Qt.DashLine)
            
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(border_rect, radius, radius)
        
        painter.end()


class ModernProgressBar(QProgressBar):
    """Modern animated progress bar with smooth transitions"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(12)
        self.setRange(0, 100)
        self.setValue(0)
        self.setVisible(False)
        
        # Animation for smooth progress updates
        self.animation = QPropertyAnimation(self, b"value")
        self.animation.setDuration(300)  # 300ms smooth animation
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Theme-aware progress bar: chunk colour follows accent, track
        # follows the deep panel token. Falls back to the original blue
        # baseline if the theme manager is unavailable (e.g. during early
        # construction).
        try:
            from PacsClient.utils.theme_manager import get_theme_manager
            _pb_theme = get_theme_manager().current_theme()
            _pb_track = _pb_theme.get('panel_deep_bg', '#1a202c')
            _pb_accent = _pb_theme.get('accent', '#3182ce')
            _pb_text = _pb_theme.get('text_primary', '#ffffff')
        except Exception:
            _pb_track = '#1a202c'
            _pb_accent = '#3182ce'
            _pb_text = '#ffffff'
        self.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                border-radius: 8px;
                background: {_pb_track};
                text-align: center;
                font-size: 9px;
                font-weight: bold;
                color: {_pb_text};
                padding: 2px;
            }}
            QProgressBar::chunk {{
                background: {_pb_accent};
                border-radius: 6px;
            }}
        """)
    
    def setValueAnimated(self, value):
        """Set value with smooth animation"""
        if self.animation.state() == QPropertyAnimation.Running:
            self.animation.stop()
        
        self.animation.setStartValue(self.value())
        self.animation.setEndValue(value)
        self.animation.start()
    
    def setProgress(self, progress_percent, status_text=""):
        """Update progress with animation and status text"""
        self.setVisible(True)
        self.setValueAnimated(int(progress_percent))
        
        if progress_percent >= 100:
            self.setFormat("✅ Complete")
            # Change color to green when complete
            self.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 8px;
                    background: #1a202c;
                    text-align: center;
                    font-size: 9px;
                    font-weight: bold;
                    color: #ffffff;
                    padding: 2px;
                }
                QProgressBar::chunk {
                    background: #10b981;
                    border-radius: 6px;
                }
            """)
        else:
            self.setFormat(f"{int(progress_percent)}%")


class StatusLabel(QLabel):
    """Modern status label with smooth color transitions"""
    
    def __init__(self, text="Pending...", parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(16)
        self.setAlignment(Qt.AlignCenter)
        
        # Animation for color transitions
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity")
        self.fade_animation.setDuration(200)
        
        self.setPendingStyle()
    
    def _themed_status_style(self, color_hex: str) -> str:
        """Status-pill stylesheet keyed off a theme color (warning / info /
        success). Keeps the SEMANTIC palette but lets each state's hue
        track the active workstation theme."""
        return (
            f"QLabel {{ font-size: 10px; font-weight: bold; "
            f"color: {color_hex}; background: transparent; "
            f"border: 1px solid {color_hex}; border-radius: 4px; "
            f"padding: 2px 4px; }}"
        )

    def _theme_color(self, key: str, fallback: str) -> str:
        try:
            from PacsClient.utils.theme_manager import get_theme_manager
            return get_theme_manager().current_theme().get(key, fallback)
        except Exception:
            return fallback

    def setPendingStyle(self):
        """Set pending status style — uses theme warning."""
        self.setText("Pending...")
        self.setStyleSheet(self._themed_status_style(self._theme_color('warning', '#fbbf24')))

    def setDownloadingStyle(self, text=""):
        """Set downloading status style — uses theme info."""
        self.setText(text)
        self.setStyleSheet(self._themed_status_style(self._theme_color('info', '#3182ce')))

    def setCompleteStyle(self):
        """Set complete status style — uses theme success."""
        self.setText("Ready")
        self.setStyleSheet(self._themed_status_style(self._theme_color('success', '#10b981')))


class DraggableButton(QPushButton):
    dragStarted = Signal(object)

    def __init__(self, pixmap, parent=None, thumbnail_index=0, series_number=None):
        super().__init__(parent)
        self.setIcon(QIcon(pixmap))
        self.setIconSize(pixmap.size())
        self.setCheckable(True)
        self.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 6px;
                background: transparent;
            }
        """)
        self._drag_start_pos = None
        self.thumbnail_index = thumbnail_index
        # ✅ CRITICAL FIX: Store series_number for drag-and-drop to avoid index confusion
        self.series_number = series_number if series_number is not None else thumbnail_index

    def mousePressEvent(self, event: QMouseEvent):  # create signal 'click'
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):  # drag
        if event.buttons() & Qt.LeftButton:
            if self._drag_start_pos is not None:
                distance = (event.pos() - self._drag_start_pos).manhattanLength()
                if distance >= QApplication.startDragDistance():
                    # set check this button
                    if not self.isChecked():
                        self.setChecked(True)
                        self.dragStarted.emit(self)  # publish signal with self button

                    drag = QDrag(self)
                    mime_data = QMimeData()
                    # ✅ CRITICAL FIX: Send series_number instead of index to avoid confusion
                    series_number_text = str(self.series_number)
                    mime_data.setText(series_number_text)  # legacy fallback
                    mime_data.setData("application/x-aipacs-series-number", series_number_text.encode("utf-8"))
                    drag.setMimeData(mime_data)
                    drag_pixmap = self.grab()
                    if drag_pixmap.isNull():
                        drag_pixmap = self.icon().pixmap(self.iconSize())
                    if not drag_pixmap.isNull():
                        drag.setPixmap(drag_pixmap)
                        hot_spot = self._drag_start_pos if self._drag_start_pos is not None else drag_pixmap.rect().center()
                        max_x = max(0, drag_pixmap.width() - 1)
                        max_y = max(0, drag_pixmap.height() - 1)
                        hot_spot = QPoint(
                            max(0, min(int(hot_spot.x()), max_x)),
                            max(0, min(int(hot_spot.y()), max_y)),
                        )
                        drag.setHotSpot(hot_spot)
                    drag.exec(Qt.CopyAction)
                    self._drag_start_pos = None
        super().mouseMoveEvent(event)


# هایلایت انتخاب‌شده (پررنگ‌تر و قابل‌تشخیص)
SELECTED_FRAME_CSS = """
QFrame#availabilityFrame {
    border: 3px solid #22d3ee;  /* فیروزه‌ای پررنگ */
    border-radius: 6px;
    background: transparent;
    margin: 0px;
    padding: 2px;
}
"""

# اگر بخواهی «آماده + انتخاب‌شده» کمی پررنگ‌تر از سبز معمولی شود:
READY_SELECTED_FRAME_CSS = """
QFrame#availabilityFrame {
    border: 3px solid #34d399;  /* سبز پررنگ‌تر */
    border-radius: 6px;
    background: transparent;
    margin: 0px;
    padding: 2px;
}
"""


PENDING_FRAME_CSS = """
QFrame#availabilityFrame {
    border: 2px dashed #718096;
    border-radius: 6px;
    background: transparent;
    margin: 0px;
    padding: 2px;
}
"""
READY_FRAME_CSS = """
QFrame#availabilityFrame {
    border: 2px solid #10b981;
    border-radius: 6px;
    background: transparent;
    margin: 0px;
    padding: 2px;
}
"""
DEFAULT_CONTAINER_CSS = """
QWidget {
    background: #2d3748;
    border: none;
    border-radius: 8px;
    margin: 2px;
}
QWidget:hover {
    background: #374151;
}
"""



class ThumbnailManager(QObject):
    # تعریف سیگنال‌ها
    priority_download_requested = Signal(str, str)  # series_number, study_uid
    retry_download_requested = Signal(str, str, str)  # series_number, study_uid, series_uid
    thumbnail_image_ready = Signal(str, QImage)  # series_number, QImage

    def __init__(self, method_change_series, theme=None):
        super().__init__()  # فراخوانی سازنده QObject
        self.buttons = []
        self.lst_buttons_name = []
        self.method_change_series = method_change_series
        self.selected_series = None
        self.series_widgets = {}
        self.ready_series = set()
        # Series loaded into a viewport this session ("viewed"). Session-scoped,
        # in-memory; reset only by reset_all_states() (new patient). This set is
        # the source of truth — apply_border_states_new() re-applies it to every
        # widget, so a sidebar re-render keeps the mark.
        self.viewed_series = set()
        self.current_study_uid = None  # برای ذخیره study_uid فعلی
        self._placeholder_cache = None
        self.theme_manager = get_theme_manager()
        self._theme = theme if theme else self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        self._series_uid_to_number = {}
        # Coalesce frequent border refresh requests to avoid UI repaint storms.
        self._border_state_update_pending = False
        self._last_border_apply_ts = 0.0
        self._scroll_active = False
        self._progress_update_last_ts = {}
        self._progress_update_pending = {}
        self._progress_update_timer_active = False
        self._thumb_state_log_last_ts = {}
        self._set_ready_reentrant_guard = False
        self._series_projection_state = {}
        self._series_total_images = {}
        self.thumbnail_image_ready.connect(self._apply_thumbnail_image)

    @staticmethod
    def _normalize_total_images(total_images):
        try:
            if total_images is None:
                return None
            value = int(total_images)
            return value if value > 0 else None
        except Exception:
            return None

    def _remember_series_total_images(self, series_key: str, total_images=None):
        """Persist the first known positive total for a series lifecycle."""
        key = str(series_key)
        normalized = self._normalize_total_images(total_images)
        known = self._series_total_images.get(key)
        if known is not None:
            return known
        if normalized is not None:
            self._series_total_images[key] = normalized
            return normalized
        return None

    def _get_series_projection_state(self, series_key: str) -> str:
        return str(self._series_projection_state.get(str(series_key), "pending"))

    def _set_series_projection_state(self, series_key: str, state: str) -> None:
        self._series_projection_state[str(series_key)] = str(state)

    def set_scroll_active(self, active: bool):
        """Defer heavy thumbnail border repaints while the viewer is scrolling."""
        self._scroll_active = bool(active)
        if not self._scroll_active and self._border_state_update_pending:
            QTimer.singleShot(0, lambda: self.apply_border_states_new(immediate=True))

    def _progress_update_interval_ms(self) -> float:
        """Thumbnail progress cadence: normal 10 Hz, protected 2 Hz."""
        if self._scroll_active:
            return 500.0
        return float(thumbnail_progress_interval_ms())

    def _schedule_progress_flush(self, delay_ms: float) -> None:
        if self._progress_update_timer_active:
            return
        self._progress_update_timer_active = True
        QTimer.singleShot(max(0, int(delay_ms)), self._flush_pending_progress_updates)

    def _flush_pending_progress_updates(self) -> None:
        self._progress_update_timer_active = False
        pending = dict(self._progress_update_pending)
        self._progress_update_pending.clear()
        for series_number, progress_percent, status_text in pending.values():
            self.update_series_progress(series_number, progress_percent, status_text, _force=True)

    def _should_log_thumb_state(self, series_key: str, progress_percent: float, *, force: bool = False) -> bool:
        if force or progress_percent >= 100:
            self._thumb_state_log_last_ts[series_key] = time.monotonic() * 1000.0
            return True
        now_ms = time.monotonic() * 1000.0
        last_ms = self._thumb_state_log_last_ts.get(series_key, 0.0)
        interval_ms = 500.0 if self._scroll_active else float(thumbnail_log_interval_ms())
        if now_ms - last_ms >= interval_ms:
            self._thumb_state_log_last_ts[series_key] = now_ms
            return True
        return False

    def _is_focus_series(self, series_key: str) -> bool:
        """True when a thumbnail belongs to the actively viewed / selected series."""
        try:
            key = str(series_key)
            if str(getattr(self, 'selected_series', '') or '') == key:
                return True

            parent_widget = getattr(self, 'parent_widget', None)
            if parent_widget is None:
                return False

            for node in getattr(parent_widget, 'lst_nodes_viewer', []) or []:
                vtk_w = getattr(node, 'vtk_widget', None)
                if vtk_w is None:
                    continue
                try:
                    viewer_sn = str(
                        getattr(vtk_w.image_viewer, 'metadata', {})
                        .get('series', {}).get('series_number', '')
                    )
                except Exception:
                    viewer_sn = ''
                if viewer_sn == key:
                    return True
                if str(getattr(vtk_w, '_awaiting_series_number', '') or '') == key:
                    return True
                if str(getattr(vtk_w, '_progressive_series_number', '') or '') == key:
                    return True
            return False
        except Exception:
            return False

    def _should_use_compact_progress_ui(self, series_key: str, progress_percent: float) -> bool:
        """Use a cheaper thumbnail update path for background series under overlap."""
        try:
            if progress_percent >= 100:
                return False
            if self._is_focus_series(series_key):
                return False
            return bool(is_fast_interaction_active() or is_heavy_download_active())
        except Exception:
            return False

    def _apply_compact_progress_state(self, widget, series_key: str, progress_percent: float, status_text: str = "") -> bool:
        """Cheap thumbnail update path: no glass overlay churn for background series.

        Returns True only when something changed and a repaint is warranted.
        """
        try:
            if widget is None:
                return False
            changed = False

            if hasattr(widget, 'progress_overlay'):
                try:
                    changed = self._set_widget_visible_if_needed(widget.progress_overlay, False) or changed
                except RuntimeError:
                    return False

            if hasattr(widget, 'glass_overlay'):
                try:
                    changed = self._set_widget_visible_if_needed(widget.glass_overlay, False) or changed
                except RuntimeError:
                    return False

            if status_text:
                try:
                    count_label = getattr(widget, 'count_label', None)
                    desired_text = str(status_text)
                    if count_label is None or count_label.text() != desired_text:
                        self._set_series_count_label_text(series_key, desired_text)
                        changed = True
                except Exception:
                    pass

            if hasattr(widget, 'progress_border'):
                try:
                    progress_border = widget.progress_border
                    if progress_percent >= 100:
                        changed = self._set_progress_border_downloading_if_needed(progress_border, False) or changed
                        changed = self._set_progress_border_ready_if_needed(progress_border, True) or changed
                    elif progress_percent > 0:
                        changed = self._set_progress_border_downloading_if_needed(progress_border, True) or changed
                except RuntimeError:
                    return False

            if changed:
                try:
                    widget.update()
                except RuntimeError:
                    return False
            return changed
        except Exception:
            return False

    @staticmethod
    def _set_widget_visible_if_needed(widget, visible: bool) -> bool:
        """Set QWidget visibility only when the value actually changes."""
        if widget is None:
            return False
        new_visible = bool(visible)
        current_visible = bool(widget.isVisible())
        if current_visible == new_visible:
            return False
        widget.setVisible(new_visible)
        return True

    @staticmethod
    def _set_label_text_if_needed(label, text: str) -> bool:
        """Set QLabel text only when the rendered text changes."""
        if label is None:
            return False
        new_text = str(text)
        if label.text() == new_text:
            return False
        label.setText(new_text)
        return True

    @staticmethod
    def _set_progress_border_downloading_if_needed(progress_border, downloading: bool) -> bool:
        """Update border download state only on actual transition."""
        if progress_border is None:
            return False
        new_state = bool(downloading)
        if bool(getattr(progress_border, '_downloading', False)) == new_state:
            return False
        progress_border.setDownloading(new_state)
        return True

    @staticmethod
    def _set_progress_border_ready_if_needed(progress_border, ready: bool) -> bool:
        """Update border ready state only on actual transition."""
        if progress_border is None:
            return False
        new_state = bool(ready)
        if bool(getattr(progress_border, '_is_ready', False)) == new_state:
            return False
        progress_border.setReady(new_state)
        return True

    def _on_theme_changed(self, theme):
        """Handle theme changes - update all created thumbnails"""
        self._theme = theme
        # Update border colors for all existing thumbnails
        for widget in self.series_widgets.values():
            try:
                if widget and hasattr(widget, 'progress_border'):
                    widget.progress_border._theme = theme
                    widget.progress_border.update()
            except RuntimeError:
                continue

    def create_placeholder_pixmap(self, size: QSize = None, text: str = "Loading...") -> QPixmap:
        """Create and cache a lightweight placeholder pixmap (GUI thread only)."""
        if size is None:
            size = QSize(160, 120)
        if self._placeholder_cache and self._placeholder_cache.size() == size:
            return self._placeholder_cache

        pixmap = QPixmap(size)
        pixmap.fill(QColor("#1f2937"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
        painter.end()

        self._placeholder_cache = pixmap
        return pixmap

    def update_thumbnail_image(self, series_number: str, image: QImage):
        """Thread-safe image update (emit to GUI thread)."""
        try:
            if image is None or image.isNull():
                return
            _tm_logger.info(
                "FAST:first_thumbnail_visible series=%s t_abs=%.6f",
                series_number, time.perf_counter(),
            )
            self.thumbnail_image_ready.emit(str(series_number), image)
        except Exception:
            return

    def update_series_image_count(self, series_number: str, image_count: int):
        """Update the image count label for a series thumbnail (GUI thread only)."""
        try:
            series_key = str(series_number)
            widget = self.series_widgets.get(series_key)
            if widget is None:
                return

            try:
                _ = widget.isVisible()
            except RuntimeError:
                return

            if image_count is None:
                return
            try:
                image_count = int(image_count)
            except Exception:
                return
            if image_count <= 0:
                return
            self._set_series_count_label_text(series_key, f"{image_count} images")
        except Exception:
            return

    def _set_series_count_label_text(self, series_key: str, text: str) -> None:
        """Set or create the thumbnail count label text for one series."""
        widget = self.series_widgets.get(str(series_key))
        if widget is None:
            return

        try:
            _ = widget.isVisible()
        except RuntimeError:
            return

        count_label = getattr(widget, "count_label", None)
        if count_label is None:
            content_layout = getattr(widget, "content_layout", None)
            if content_layout is None:
                return
            count_label = QLabel(text)
            count_label.setFixedHeight(20)
            count_label.setAlignment(Qt.AlignCenter)
            # Theme-aware accent for the "{N} images" count text — was
            # hard-coded #3b82f6 (Material blue), which clashed with every
            # non-Blue theme. Mirrors the themed path in
            # `_create_thumbnail_widget` so both code paths surface the
            # same color regardless of which branch produced the label.
            count_color = (
                self._theme.get('accent', '#3b82f6') if hasattr(self, '_theme') and self._theme else '#3b82f6'
            )
            count_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    font-weight: bold;
                    color: {count_color};
                    background: transparent;
                    border: none;
                    padding: 2px;
                }}
            """)
            content_layout.addWidget(count_label)
            widget.count_label = count_label
        else:
            if count_label.text() == text:
                return
            count_label.setText(text)
        count_label.update()
        widget.update()

    def _apply_thumbnail_image(self, series_number: str, image: QImage):
        """Apply image to existing thumbnail widget on GUI thread."""
        try:
            series_key = str(series_number)
            widget = self.series_widgets.get(series_key)
            if widget is None:
                return
            try:
                _ = widget.isVisible()
            except RuntimeError:
                return

            image_button = getattr(widget, "image_button", None)
            if image_button is None:
                return

            pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                return

            scaled = pixmap.scaled(160, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_button.setIcon(scaled)
            image_button.setIconSize(scaled.size())
            image_button.update()
            _tm_logger.info(
                "FAST:thumbnail_cache series=%s source=generated source_detail=applied_to_widget",
                series_number,
            )
        except Exception:
            return

    def set_current_study_uid(self, study_uid):
        """Set the current study UID - fixes the AttributeError"""
        self.current_study_uid = study_uid
        _tm_logger.debug("ThumbnailManager: set current study UID: %s", study_uid)

    def reset_all_states(self):
        """Reset all thumbnail states for a new patient"""
        _tm_logger.debug("ThumbnailManager: resetting all states for new patient")

        # Clear all ready series
        self.ready_series.clear()
        # Clear the session "viewed" marks for the new patient
        self.viewed_series.clear()
        self._series_uid_to_number.clear()
        self._series_projection_state.clear()
        self._series_total_images.clear()

        # Clear selected series
        self.selected_series = None

        # Reset all widget states
        # Create a copy of the keys to iterate over since we might delete items
        for key in list(self.series_widgets.keys()):
            widget = self.series_widgets[key]
            try:
                if widget and hasattr(widget, 'progress_border'):
                    # Check if the progress_border still exists before accessing it
                    try:
                        if widget.progress_border:
                            # Reset to pending state
                            widget.progress_border._is_ready = False
                            widget.progress_border._is_selected = False
                            widget.progress_border._downloading = False
                            widget.progress_border._viewed = False
                            widget.progress_border._progress = 0
                            widget.progress_border.update()
                    except (RuntimeError, AttributeError):
                        # Widget or progress_border has been deleted, remove from tracking
                        if key in self.series_widgets:
                            del self.series_widgets[key]
            except RuntimeError:
                # Widget has been deleted, remove from tracking
                if key in self.series_widgets:
                    del self.series_widgets[key]

        # Clear all buttons
        self.buttons.clear()
        self.lst_buttons_name.clear()

        # Clear all widgets
        self.series_widgets.clear()

        _tm_logger.debug("ThumbnailManager: all states reset")
    def apply_border_states(self):
        """
        همه‌ی ویجت‌ها را مرور می‌کند و بر اساس سه حالت زیر استایل می‌دهد:
          - انتخاب‌شده (selected)
          - آماده (ready)
          - هیچ‌کدام
        """
        try:
            # Use list of keys to avoid modification during iteration
            for key in list(self.series_widgets.keys()):
                w = self.series_widgets[key]
                try:
                    # Check if widget still exists
                    if not w:
                        continue
                        
                    # Check if C++ object is still valid
                    try:
                        if not w.isVisible() and not w.isEnabled():
                            continue
                    except RuntimeError:
                        # Widget has been deleted, remove from tracking
                        if key in self.series_widgets:
                            del self.series_widgets[key]
                        continue

                    if not hasattr(w, "status_frame"):
                        continue

                    is_ready = key in self.ready_series
                    is_selected = (self.selected_series == key)

                    # 1) انتخاب‌شده + آماده
                    if is_ready and is_selected:
                        w.status_frame.setStyleSheet(READY_SELECTED_FRAME_CSS)
                    # 2) فقط انتخاب‌شده
                    elif is_selected:
                        w.status_frame.setStyleSheet(SELECTED_FRAME_CSS)
                    # 3) فقط آماده
                    elif is_ready:
                        w.status_frame.setStyleSheet(READY_FRAME_CSS)
                    # 4) هیچ‌کدام → Pending/پیش‌فرض
                    else:
                        w.status_frame.setStyleSheet(PENDING_FRAME_CSS)

                    # یک سایه نرم برای انتخاب‌شده‌ها (دید بهتر)
                    eff = getattr(w.status_frame, "_shadow_eff", None)
                    if is_selected:
                        if eff is None:
                            eff = QGraphicsDropShadowEffect(w.status_frame)
                            eff.setOffset(0, 0)
                            eff.setBlurRadius(18)
                            eff.setColor(QColor(34, 211, 238, 120))  # هم‌رنگ select
                            w.status_frame._shadow_eff = eff
                            w.status_frame.setGraphicsEffect(eff)
                    else:
                        if eff is not None:
                            w.status_frame.setGraphicsEffect(None)
                            w.status_frame._shadow_eff = None

                    w.status_frame.update()
                    w.update()
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if key in self.series_widgets:
                        del self.series_widgets[key]
                    continue
        except Exception as e:
            _tm_logger.debug("apply_border_states error: %s", e)
    
    @_g6_slot_timing("thumbnail.apply_border_states_new")
    def apply_border_states_new(self, immediate: bool = False):
        """
        Apply border states using new CircularProgressborder - OPTIMIZED VERSION
        """
        try:
            if self._scroll_active:
                self._border_state_update_pending = True
                return

            # Coalesce frequent update calls into one apply per frame.
            if not immediate:
                if self._border_state_update_pending:
                    return

                now = time.perf_counter()
                elapsed_ms = (now - self._last_border_apply_ts) * 1000.0
                frame_budget_ms = 150.0  # Coalesce updates during bulk downloads
                delay_ms = 0 if elapsed_ms >= frame_budget_ms else int(frame_budget_ms - elapsed_ms)

                self._border_state_update_pending = True
                QTimer.singleShot(delay_ms, lambda: self.apply_border_states_new(immediate=True))
                return

            # We are executing the coalesced update now.
            self._border_state_update_pending = False
            self._last_border_apply_ts = time.perf_counter()

            # Skip if no widgets
            if not self.series_widgets:
                return
            
            # Disable updates during batch processing
            for w in self.series_widgets.values():
                try:
                    if w and hasattr(w, 'setUpdatesEnabled'):
                        w.setUpdatesEnabled(False)
                except RuntimeError:
                    continue
            
            try:
                widgets_copy = list(self.series_widgets.items())
                
                for key, w in widgets_copy:
                    try:
                        # Quick validation
                        if w is None:
                            continue
                        
                        # Check if C++ object is still valid
                        try:
                            if not w.isVisible():
                                continue
                        except RuntimeError:
                            continue
                        
                        if not hasattr(w, "progress_border"):
                            continue
                        
                        progress_border = w.progress_border
                        
                        # Quick validation for progress_border
                        try:
                            if not progress_border.isVisible():
                                continue
                        except RuntimeError:
                            continue
                        
                        # Get states
                        is_ready = key in self.ready_series
                        is_selected = (self.selected_series == key)
                        is_viewed = key in self.viewed_series

                        # Update progress border properties WITHOUT painting yet
                        progress_border._is_ready = is_ready
                        progress_border._is_selected = is_selected
                        progress_border._viewed = is_viewed
                        
                        if is_ready:
                            progress_border._downloading = False
                            progress_border._progress = 100
                    
                    except Exception as e:
                        if "deleted" not in str(e).lower():
                            _tm_logger.debug("error processing widget %s: %s", key, e)
                        continue
                
                # Now do a single update for all widgets
                for key, w in list(self.series_widgets.items()):  # Use list to avoid modification during iteration
                    try:
                        if w and hasattr(w, 'progress_border'):
                            # Check if the progress_border still exists before updating
                            try:
                                if w.progress_border:
                                    # Schedule update instead of immediate repaint
                                    w.progress_border.update()
                            except (RuntimeError, AttributeError):
                                # Widget or progress_border has been deleted, remove from tracking
                                if key in self.series_widgets:
                                    del self.series_widgets[key]
                    except RuntimeError:
                        continue
                    
            finally:
                # Re-enable updates
                for w in self.series_widgets.values():
                    try:
                        if w and hasattr(w, 'setUpdatesEnabled'):
                            w.setUpdatesEnabled(True)
                            # Single update per widget
                            w.update()
                    except RuntimeError:
                        continue
            
            _tm_logger.debug("ThumbnailManager: border states applied to %d widgets", len(self.series_widgets))
            
        except Exception as e:
            if immediate:
                self._border_state_update_pending = False
            if "deleted" not in str(e).lower():
                _tm_logger.debug("apply_border_states_new error: %s", e)
                

    @staticmethod
    def create_standard_metadata(series_number, modality='Unknown', series_description='', 
                                image_count=1, protocol_name='', body_part_examined='', 
                                is_downloading=False, main_thumbnail=True):
        """Backward-compatible delegate to the shared thumbnail projection helper."""
        from PacsClient.pacs.patient_tab.utils.thumbnail_projection_service import ThumbnailProjectionService

        return ThumbnailProjectionService.create_standard_metadata(
            series_number=series_number,
            modality=modality,
            series_description=series_description,
            image_count=image_count,
            protocol_name=protocol_name,
            body_part_examined=body_part_examined,
            is_downloading=is_downloading,
            main_thumbnail=main_thumbnail,
        )

    def register_button(self, button: QPushButton, button_name):
        self.buttons.append(button)
        self.lst_buttons_name.append(button_name)

    def uncheck_others(self, selected_button: QPushButton):
        for btn in self.buttons:
            btn.setChecked(btn is selected_button)


    def create_thumbnail_widget(self, pixmap: QPixmap, label_text: str, sop_instance_uid='test uid', thumbnail_index=0, series_info=None, show_progress=False):
        """Create unified and consistent thumbnail widget for all scenarios"""
        try:
            # Canonical series key priority:
            # 1) thumbnail_index (caller passes key_thumbnail/series number)
            # 2) series_info
            # 3) label_text
            series_number = None
            if thumbnail_index not in (None, ""):
                series_number = str(thumbnail_index)

            if (series_number is None or series_number == "") and series_info and isinstance(series_info, dict):
                if 'series' in series_info and isinstance(series_info['series'], dict):
                    series_number = series_info['series'].get('series_number')
                elif 'series_number' in series_info:
                    series_number = series_info['series_number']

            if series_number is None or series_number == "":
                series_number = label_text
            
            # Use series_number as the key (NOT thumbnail_index)
            series_key = str(series_number)

            # Multi-study patients carry a patient-unique offset key as the
            # series_number; show the original study-local number to the user.
            display_series = series_number
            try:
                if isinstance(series_info, dict):
                    _orig = (
                        series_info.get('_orig_series_number')
                        or (series_info.get('series') or {}).get('_orig_series_number')
                    )
                    if _orig:
                        display_series = _orig
            except Exception:
                display_series = series_number

            # Main container widget - SQUARE dimensions
            widget = QWidget()
            widget.setFixedSize(190, 215)  # 2026-05-29: was 190 - made taller so both server description label
            # and image-count label can coexist (per user request).
            main_layout = QVBoxLayout(widget)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            
            # Create circular progress border frame
            progress_border = CircularProgressborder(theme=self._theme)
            progress_border.setFixedSize(190, 215)  # mirrors widget height
            border_layout = QVBoxLayout(progress_border)
            border_layout.setContentsMargins(8, 8, 8, 8)
            border_layout.setSpacing(3)
            
            # Inner content widget
            content_widget = QWidget()
            content_widget.setStyleSheet(f"""
                QWidget {{
                    background: {self._theme.get('panel_alt_bg', '#2d3748')};
                    border: none;
                    border-radius: 6px;
                }}
            """)
            content_layout = QVBoxLayout(content_widget)
            content_layout.setContentsMargins(6, 6, 6, 6)
            content_layout.setSpacing(3)
            
            # Simple header - text only with REAL series number
            header_label = QLabel(f"Series {display_series}")
            header_label.setFixedHeight(18)
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    font-weight: bold;
                    color: {self._theme.get('text_primary', '#ffffff')};
                    background: transparent;
                    border: none;
                    padding: 2px;
                }}
            """)
            content_layout.addWidget(header_label)
            
            # Create draggable button for the image
            scaled_pixmap = pixmap.scaled(160, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # ✅ Use real series_number for drag-and-drop
            image_button = DraggableButton(scaled_pixmap, thumbnail_index=thumbnail_index, series_number=series_number)
            image_button.setFixedSize(160, 120)
            image_button.setIconSize(QSize(160, 120))
            image_button.setCheckable(True)
            image_button.setStyleSheet(f"""
                QPushButton {{
                    border: none;
                    border-radius: 6px;
                    background: {self._theme.get('panel_bg', '#1a202c')};
                }}
            """)
            content_layout.addWidget(image_button)
            
            # Set initial state
            if show_progress:
                progress_border.setDownloading(True)
                progress_border.setProgressAnimated(0)
            
            # Series info with description and image count
            if series_info:
                # Description label
                # ✅ Check both nested 'series' dict and top-level
                desc = ''
                if 'series' in series_info and isinstance(series_info['series'], dict):
                    desc = series_info['series'].get('series_description', '')
                if not desc:
                    desc = series_info.get('series_description', '')
                    
                if desc and desc.strip() and desc not in ['No description', 'Unknown']:
                    if len(desc) > 20:
                        desc = desc[:17] + "..."
                    desc_label = QLabel(desc)
                    desc_label.setFixedHeight(16)
                    desc_label.setAlignment(Qt.AlignCenter)
                    desc_label.setStyleSheet("""
                        QLabel {
                            font-size: 9px;
                            color: #cbd5e0;
                            background: transparent;
                            border: none;
                            padding: 0px;
                        }
                    """)
                    content_layout.addWidget(desc_label)
                
                # Image count label
                image_count = series_info.get('image_count', 0)
                if image_count is not None and image_count > 0:
                    count_label = QLabel(f"{image_count} images")
                    count_label.setFixedHeight(20)
                    count_label.setAlignment(Qt.AlignCenter)
                    count_label.setStyleSheet(f"""
                        QLabel {{
                            font-size: 12px;
                            font-weight: bold;
                            color: {self._theme.get('accent', '#3b82f6')};
                            background: transparent;
                            border: none;
                            padding: 2px;
                        }}
                    """)
                    content_layout.addWidget(count_label)
                    widget.count_label = count_label
                elif not desc or not desc.strip():
                    # If no count and no desc, show series number
                    # ✅ Get series_number from nested 'series' dict first
                    series_num_display = ''
                    if 'series' in series_info and isinstance(series_info['series'], dict):
                        series_num_display = series_info['series'].get('series_number', '')
                    if not series_num_display:
                        series_num_display = series_info.get('series_number', '')
                    
                    if series_num_display:
                        fallback_label = QLabel(f"Series {series_num_display}")
                        fallback_label.setFixedHeight(18)
                        fallback_label.setAlignment(Qt.AlignCenter)
                        fallback_label.setStyleSheet("""
                            QLabel {
                                font-size: 10px;
                                color: #94a3b8;
                                background: transparent;
                                border: none;
                                padding: 0px;
                            }
                        """)
                        content_layout.addWidget(fallback_label)
            else:
                # No series info available
                no_info_label = QLabel("No series info")
                no_info_label.setFixedHeight(20)
                no_info_label.setAlignment(Qt.AlignCenter)
                no_info_label.setStyleSheet("""
                    QLabel {
                        font-size: 9px;
                        color: #64748b;
                        background: transparent;
                        border: none;
                        padding: 2px;
                    }
                """)
                content_layout.addWidget(no_info_label)
            
            # Glass overlay for progress
            glass_overlay = QWidget(widget)
            glass_overlay.setGeometry(0, 0, 190, 215)  # mirrors widget
            glass_overlay.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(15, 23, 42, 200),
                        stop:1 rgba(30, 41, 59, 220));
                    border: 1px solid rgba(148, 163, 184, 60);
                    border-radius: 8px;
                }
            """)
            # Allow clicks to reach retry button and thumbnail.
            glass_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            glass_overlay.setVisible(False)
            
            # Add frosted glass blur effect
            glass_blur = QGraphicsDropShadowEffect(glass_overlay)
            glass_blur.setOffset(0, 0)
            glass_blur.setBlurRadius(40)
            glass_blur.setColor(QColor(0, 0, 0, 100))
            glass_overlay.setGraphicsEffect(glass_blur)
            
            # Progress text label
            progress_overlay = QLabel(glass_overlay)
            progress_overlay.setAlignment(Qt.AlignCenter)
            progress_overlay.setStyleSheet("""
                QLabel {
                    background: transparent;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: bold;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    border: none;
                    padding: 0px;
                    line-height: 1.3;
                }
            """)
            progress_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            progress_overlay.setText("0%")
            
            # Position progress label
            label_width = 100
            label_height = 65
            label_x = (190 - label_width) // 2
            label_y = (215 - label_height) // 2  # mirrors widget height
            progress_overlay.setGeometry(label_x, label_y, label_width, label_height)
            
            # Add inner glow effect
            inner_glow = QGraphicsDropShadowEffect(progress_overlay)
            inner_glow.setOffset(0, 0)
            inner_glow.setBlurRadius(15)
            inner_glow.setColor(QColor(59, 130, 246, 150))
            progress_overlay.setGraphicsEffect(inner_glow)
            
            # Ensure glass overlay is on top
            glass_overlay.raise_()
            progress_overlay.setAutoFillBackground(False)
            
            # Add content widget to progress border
            border_layout.addWidget(content_widget)
            
            # Add progress border to main widget
            main_layout.addWidget(progress_border)
            
            # Setup drag functionality
            def on_drag_started(_btn):
                # ✅ Use real series_number, NOT thumbnail_index
                self.selected_series = series_key
                self.apply_border_states_new()

            image_button.dragStarted.connect(on_drag_started)
            
            # Setup click functionality
            def on_thumb_clicked():
                if image_button.isChecked():
                    # ✅ Use real series_number, NOT thumbnail_index
                    self.selected_series = series_key

                    # 🔥 Emit priority download for series
                    study_uid = ''
                    if series_info and 'study_uid' in series_info:
                        study_uid = series_info.get('study_uid', '')
                    elif self.current_study_uid:
                        study_uid = self.current_study_uid

                    _tm_logger.debug("ThumbnailManager: priority download requested series=%s study=%s", series_number, study_uid)
                    self.priority_download_requested.emit(series_key, study_uid)

                    # First try to change series normally (this will trigger loading if needed)
                    # ✅ Pass series_number, NOT thumbnail_index
                    self.method_change_series(int(series_number) if isinstance(series_number, str) and series_number.isdigit() else series_number)
                    self.apply_border_states_new()

            image_button.clicked.connect(on_thumb_clicked)
            
            # ✅ ADD RETRY BUTTON (emoji style) at top-right corner
            retry_button = QPushButton(widget)
            retry_button.setText("🔄")
            retry_button.setFixedSize(28, 28)
            retry_button.setStyleSheet("""
                QPushButton {
                    background-color: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 4px;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 2px;
                }
                QPushButton:hover {
                    background-color: #3d4758;
                    border: 1px solid #6b7ba8;
                }
                QPushButton:pressed {
                    background-color: #1d2638;
                    border: 1px solid #2b3e5f;
                }
            """)
            retry_button.setToolTip("Retry download for this series")
            
            # Position retry button at top-left corner
            retry_button.move(4, 4)  # 4px padding from top-left
            retry_button.raise_()  # Ensure it's on top
            
            # Extract series_uid from series_info
            series_uid = None
            if series_info and isinstance(series_info, dict):
                if 'series_uid' in series_info:
                    series_uid = series_info['series_uid']
                elif 'series' in series_info and isinstance(series_info['series'], dict):
                    series_uid = series_info['series'].get('series_uid')

            if series_uid:
                try:
                    series_uid = str(series_uid)
                    self._series_uid_to_number[series_uid] = series_key
                except Exception:
                    pass
            
            # Store series info in button for later use
            retry_button.series_number = series_key
            retry_button.series_uid = series_uid
            retry_button.series_info = series_info
            
            # Connect retry button to emission signal
            def on_retry_clicked():
                try:
                    study_uid = ''
                    if series_info and 'study_uid' in series_info:
                        study_uid = series_info.get('study_uid', '')
                    elif self.current_study_uid:
                        study_uid = self.current_study_uid
                    
                    # ✅ Use real series_number, NOT thumbnail_index
                    _tm_logger.debug("ThumbnailManager: retry download requested series=%s uid=%s study=%s", series_number, series_uid, study_uid)
                    
                    # Emit retry signal with series info
                    if hasattr(self, 'retry_download_requested'):
                        self.retry_download_requested.emit(series_key, study_uid, series_uid)
                except Exception as e:
                    _tm_logger.debug("error in retry button click: %s", e)
            
            retry_button.clicked.connect(on_retry_clicked)
            
            # Clean main widget styling
            widget.setStyleSheet("""
                QWidget {
                    background: transparent;
                    border: none;
                }
            """)
            
            # Store references
            widget.progress_border = progress_border
            widget.progress_overlay = progress_overlay
            widget.glass_overlay = glass_overlay
            widget.content_widget = content_widget
            widget.content_layout = content_layout
            widget.image_button = image_button
            # ✅ Use real series_number as the key, NOT thumbnail_index
            widget.series_number = series_key
            widget.thumbnail_index = thumbnail_index
            widget.series_uid = series_uid
            
            # Register button
            self.register_button(image_button, label_text)

            # ✅ Store widget using real series_number as key, NOT thumbnail_index
            self.series_widgets[series_key] = widget
            _tm_logger.debug("ThumbnailManager: stored in series_widgets key=%s", series_key)

            # Apply deferred download state if start_series_download was called
            # before this widget was created (download started before thumbnails built).
            if getattr(self, '_pending_download_series', None) and series_key in self._pending_download_series:
                self._pending_download_series.discard(series_key)
                _tm_logger.debug("ThumbnailManager: applying deferred download state for series %s", series_key)
                pending_total = None
                try:
                    pending_total = getattr(self, '_pending_download_totals', {}).pop(series_key, None)
                except Exception:
                    pending_total = None
                self.start_series_download(series_key, total_images=pending_total)

            # Replay completed state when the widget is created after the series
            # already finished downloading. Without this, the series stays visually
            # pending until some later unrelated refresh happens.
            if (
                series_key in self.ready_series
                or self._get_series_projection_state(series_key) == "completed"
            ):
                self.complete_series_download(series_key, total_images=image_count if series_info else None)

            return widget
            
        except Exception as e:
            _tm_logger.exception("error creating thumbnail widget: %s", e)
            error_widget = QWidget()
            error_widget.setFixedSize(180, 120)
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Error: {str(e)}")
            error_label.setStyleSheet("color: red; font-size: 8px;")
            error_layout.addWidget(error_label)
            return error_widget


    def _resolve_series_key(self, series_identifier) -> str:
        """Resolve series identifier (number or UID) to an existing widget key."""
        series_key = str(series_identifier)
        if series_key in self.series_widgets:
            return series_key

        if hasattr(self, 'parent_widget') and self.parent_widget and hasattr(self.parent_widget, 'resolve_series_key'):
            try:
                mapped = str(self.parent_widget.resolve_series_key(series_key))
                if mapped in self.series_widgets:
                    return mapped
            except Exception:
                pass

        mapped = self._series_uid_to_number.get(series_key)
        if mapped:
            mapped_key = str(mapped)
            if mapped_key in self.series_widgets:
                return mapped_key

        for key, widget in list(self.series_widgets.items()):
            try:
                if getattr(widget, "series_uid", None) == series_key:
                    return key
            except Exception:
                continue

        return series_key
    

    def set_series_pending(self, series_number: str):
        try:
            series_key = self._resolve_series_key(series_number)

            # Do not downgrade a series that has already finished
            # downloading. A thumbnail re-render or refresh (e.g. on a
            # patient-tab switch) must not gray out a completed series.
            # Genuine restarts reset state via start_series_download() /
            # reset_all_states(), never through this method.
            if (
                series_key in self.ready_series
                or self._get_series_projection_state(series_key) == "completed"
            ):
                return

            self.ready_series.discard(series_key)

            # Update new border style
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                try:
                    if widget and hasattr(widget, 'progress_border'):
                        # Check if the progress_border still exists before accessing it
                        try:
                            if widget.progress_border:
                                widget.progress_border.setReady(False)
                                widget.progress_border.setDownloading(False)
                                widget.progress_border.update()
                        except (RuntimeError, AttributeError):
                            # Widget or progress_border has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]

            # Apply unified border state update (coalesced)
            self.apply_border_states_new()
        except Exception as e:
            _tm_logger.debug("set_series_pending error: %s", e)

    def set_series_ready(self, series_number: str):
        try:
            series_key = self._resolve_series_key(series_number)
            if self._set_ready_reentrant_guard:
                return

            # Fast no-op: already ready and no widget state transition required.
            if series_key in self.ready_series:
                return

            self._set_ready_reentrant_guard = True
            self.ready_series.add(series_key)  # مهم: این مجموعه تعیین‌کننده "کادر سبز" است
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                if hasattr(widget, 'progress_border'):
                    try:
                        # Check if the widget and its progress_border still exist
                        if widget and widget.progress_border:
                            widget.progress_border.setReady(True)
                    except (RuntimeError, AttributeError):
                        # Widget or progress_border has been deleted, remove from tracking
                        if series_key in self.series_widgets:
                            del self.series_widgets[series_key]
            self.apply_border_states_new()
        except Exception as e:
            _tm_logger.debug("set_series_ready error: %s", e)
        finally:
            self._set_ready_reentrant_guard = False

    def mark_series_viewed(self, series_number):
        """Mark a series as 'viewed' — it has been loaded into a viewport.

        Session-scoped and in-memory: the series is added to ``viewed_series``
        (the source of truth); its thumbnail then shows the green "viewed"
        border once it is no longer the active series.
        The mark persists for the life of the patient tab and survives sidebar
        re-renders because apply_border_states_new() re-applies it. It is
        cleared only by reset_all_states() (a new patient).

        Cheap and idempotent: a series already marked is a no-op with no
        repaint, so repeated loads of the same series cost nothing.
        """
        try:
            series_key = self._resolve_series_key(series_number)
            if series_key in self.viewed_series:
                return  # already viewed — no state change, no repaint
            self.viewed_series.add(series_key)

            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                try:
                    if widget and hasattr(widget, 'progress_border') and widget.progress_border:
                        widget.progress_border._viewed = True
                except (RuntimeError, AttributeError):
                    # Widget or progress_border deleted — drop from tracking.
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]

            # Coalesced repaint (shared with ready/selected updates).
            self.apply_border_states_new()
        except Exception as e:
            _tm_logger.debug("mark_series_viewed error: %s", e)

    def update_widget_borders(self, selected_widget=None):
        # اگر selected_widget داریم از parentش سری را حدس بزنیم
        if selected_widget and hasattr(selected_widget, "series_number"):
            self.selected_series = str(selected_widget.series_number)
        self.apply_border_states_new()

    def highlight_priority_series(self, series_number):
        """
        Highlight a series with special priority styling
        سری را با استایل خاص اولویت هایلایت کن
        """
        try:
            series_key = self._resolve_series_key(series_number)
            _tm_logger.debug("ThumbnailManager: apply priority styling to series %s", series_key)

            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                
                try:
                    if widget and hasattr(widget, 'progress_border'):
                        # Check if the progress_border still exists before accessing it
                        try:
                            if widget.progress_border:
                                # Add priority animation
                                from PySide6.QtCore import QTimer, QPropertyAnimation

                                # Store original border width
                                original_width = widget.progress_border._border_width

                                # Flash animation
                                def flash_priority():
                                    # Double-check that objects still exist before animation
                                    try:
                                        if widget and widget.progress_border:
                                            anim = QPropertyAnimation(widget.progress_border, b"_border_width")
                                            anim.setDuration(500)
                                            anim.setStartValue(original_width)
                                            anim.setEndValue(original_width * 2)  # Thicker border
                                            anim.setEasingCurve(QEasingCurve.InOutSine)

                                            def on_finished():
                                                # Return to original
                                                try:
                                                    if widget and widget.progress_border:
                                                        anim2 = QPropertyAnimation(widget.progress_border, b"_border_width")
                                                        anim2.setDuration(500)
                                                        anim2.setStartValue(original_width * 2)
                                                        anim2.setEndValue(original_width)
                                                        anim2.setEasingCurve(QEasingCurve.InOutSine)
                                                        anim2.start()
                                                except (RuntimeError, AttributeError):
                                                    pass  # Widget deleted during animation

                                            anim.finished.connect(on_finished)
                                            anim.start()
                                    except (RuntimeError, AttributeError):
                                        pass  # Widget deleted before animation

                                # Flash 3 times
                                for i in range(3):
                                    QTimer.singleShot(i * 1000, flash_priority)

                                _tm_logger.debug("ThumbnailManager: priority animation started for series %s", series_key)
                        except (RuntimeError, AttributeError):
                            # Widget or progress_border has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]

                # Update border state immediately
                self.apply_border_states_new()

        except Exception as e:
            _tm_logger.debug("error highlighting priority series: %s", e)


    @_g6_slot_timing("thumbnail.update_series_progress", series_arg="series_number")
    def update_series_progress(self, series_number, progress_percent, status_text="", *, _force=False):
        """
        Update download progress with PRIORITY indicator
        """
        try:
            series_key = self._resolve_series_key(series_number)
            try:
                progress_percent = float(progress_percent)
            except Exception:
                progress_percent = 0.0

            # Stale-update guard: once a series has completed, a late or
            # deferred sub-100% progress tick must NOT resurrect the blue
            # "downloading" matte. complete_series_download() has already
            # hidden the overlays and early-returns on re-entry, so a stale
            # update here would re-show glass_overlay/progress_overlay with
            # nothing left to hide them again. Drop it.
            if progress_percent < 100.0 and (
                self._get_series_projection_state(series_key) == "completed"
                or series_key in self.ready_series
            ):
                return

            if (
                not _force
                and 0.0 < progress_percent < 100.0
                and not _ui_should_admit(
                    "thumbnail_ui",
                    {
                        "key": f"thumbnail-progress:{id(self)}:{series_key}",
                        "series_key": series_key,
                    },
                )
            ):
                self._progress_update_pending[series_key] = (
                    series_number,
                    progress_percent,
                    status_text,
                )
                self._schedule_progress_flush(self._progress_update_interval_ms())
                return

            if not _force and 0.0 < progress_percent < 100.0:
                now_ms = time.monotonic() * 1000.0
                last_ms = self._progress_update_last_ts.get(series_key, 0.0)
                interval_ms = self._progress_update_interval_ms()
                elapsed_ms = now_ms - last_ms
                if elapsed_ms < interval_ms:
                    self._progress_update_pending[series_key] = (
                        series_number,
                        progress_percent,
                        status_text,
                    )
                    self._schedule_progress_flush(interval_ms - elapsed_ms)
                    return
                self._progress_update_last_ts[series_key] = now_ms
            else:
                self._progress_update_last_ts[series_key] = time.monotonic() * 1000.0

            # Add priority indicator if this is a high priority download
            is_priority = "⚡" in status_text or "🎯" in status_text or "🔄" in status_text
            
            if is_priority and (progress_percent % 25 == 0 or progress_percent >= 100):
                _tm_logger.debug("PRIORITY PROGRESS series=%s pct=%.1f status=%s", series_key, progress_percent, status_text)
            
            # Log state transitions at a bounded cadence to avoid log storms.
            if self._should_log_thumb_state(series_key, progress_percent, force=_force):
                _tm_logger.info(
                    "[FAST-THUMB-STATE] series=%s state=downloading progress=%.0f count_label=%s",
                    series_key, progress_percent, status_text,
                )
            
            # Rest of the existing code...
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                compact_ui = self._should_use_compact_progress_ui(series_key, progress_percent)
                widget_changed = False

                # Check if widget is still valid
                try:
                    if widget is None:
                        return
                    # Test if widget is still alive by checking a property
                    _ = widget.isVisible()
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]
                    return

                # Batch UI updates to prevent recursive repaints
                try:
                    widget.setUpdatesEnabled(False)
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]
                    return

                try:
                    # Show glass overlay background
                    if hasattr(widget, 'glass_overlay'):
                        try:
                            if compact_ui:
                                widget_changed = self._set_widget_visible_if_needed(widget.glass_overlay, False) or widget_changed
                            else:
                                if self._set_widget_visible_if_needed(widget.glass_overlay, True):
                                    widget.glass_overlay.raise_()
                                    widget_changed = True
                        except RuntimeError:
                            # Widget has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                            return

                    # Update progress overlay (PRIMARY method - always visible during download)
                    if hasattr(widget, 'progress_overlay'):
                        try:
                            progress_overlay = widget.progress_overlay
                        except RuntimeError:
                            # Widget has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                            return

                        if compact_ui and progress_percent > 0 and progress_percent < 100:
                            try:
                                widget_changed = self._set_widget_visible_if_needed(progress_overlay, False) or widget_changed
                            except RuntimeError:
                                if series_key in self.series_widgets:
                                    del self.series_widgets[series_key]
                                return
                        elif progress_percent > 0 and progress_percent < 100:
                            # Show percentage and count during download
                            # status_text format: "current/total" (e.g., "3/8")
                            display_text = f"{int(progress_percent)}%"
                            if status_text:
                                display_text = f"{int(progress_percent)}%\n{status_text}"

                            try:
                                text_changed = self._set_label_text_if_needed(progress_overlay, display_text)
                                # B3.5: Cache stylesheet — setStyleSheet() parses CSS
                                # on every call (~0.5-2ms).  Apply only once per overlay.
                                if not getattr(progress_overlay, '_b35_style_applied', False):
                                    progress_overlay.setStyleSheet("""
                                        QLabel {
                                            background: transparent;
                                            color: #ffffff;
                                            font-size: 14px;
                                            font-weight: bold;
                                            font-family: 'Segoe UI', 'Roboto', sans-serif;
                                            border: none;
                                            padding: 0px;
                                            line-height: 1.3;
                                        }
                                    """)
                                    progress_overlay._b35_style_applied = True
                                    widget_changed = True
                                became_visible = self._set_widget_visible_if_needed(progress_overlay, True)
                                if text_changed or became_visible:
                                    progress_overlay.raise_()  # Ensure it's on top
                                    progress_overlay.update()
                                    widget_changed = True
                            except RuntimeError:
                                # Widget has been deleted, remove from tracking
                                if series_key in self.series_widgets:
                                    del self.series_widgets[series_key]
                                return

                        elif progress_percent >= 100:
                            # Show "Ready" message briefly, then hide
                            try:
                                text_changed = self._set_label_text_if_needed(progress_overlay, "✅")
                                if not getattr(progress_overlay, '_thumb_ready_style_applied', False):
                                    progress_overlay.setStyleSheet("""
                                        QLabel {
                                            background: transparent;
                                            color: #10b981;
                                            font-size: 24px;
                                            font-weight: bold;
                                            font-family: 'Segoe UI', 'Roboto', sans-serif;
                                            border: none;
                                            padding: 0px;
                                        }
                                    """)
                                    progress_overlay._thumb_ready_style_applied = True
                                    widget_changed = True
                                became_visible = self._set_widget_visible_if_needed(progress_overlay, True)
                                if text_changed or became_visible:
                                    progress_overlay.raise_()
                                    progress_overlay.update()
                                    widget_changed = True
                            except RuntimeError:
                                # Widget has been deleted, remove from tracking
                                if series_key in self.series_widgets:
                                    del self.series_widgets[series_key]
                                return

                            # Hide after 2.5 seconds (both glass and progress)
                            # Use a lambda with error handling to prevent accessing deleted objects
                            QTimer.singleShot(2500, lambda w=widget: self._hide_overlay_safe(w))

                            # Mark as ready
                            self.ready_series.add(series_key)
                        else:
                            try:
                                widget_changed = self._set_widget_visible_if_needed(progress_overlay, False) or widget_changed
                            except RuntimeError:
                                # Widget has been deleted, remove from tracking
                                if series_key in self.series_widgets:
                                    del self.series_widgets[series_key]
                                return
                                
                            # Hide glass overlay when not in progress
                            if hasattr(widget, 'glass_overlay'):
                                try:
                                    widget_changed = self._set_widget_visible_if_needed(widget.glass_overlay, False) or widget_changed
                                except RuntimeError:
                                    # Widget has been deleted, remove from tracking
                                    if series_key in self.series_widgets:
                                        del self.series_widgets[series_key]
                                    return

                    # Update border state (secondary visual indicator)
                    if hasattr(widget, 'progress_border'):
                        try:
                            progress_border = widget.progress_border

                            if progress_percent >= 100:
                                widget_changed = self._set_progress_border_downloading_if_needed(progress_border, False) or widget_changed
                                widget_changed = self._set_progress_border_ready_if_needed(progress_border, True) or widget_changed
                            elif progress_percent > 0:
                                widget_changed = self._set_progress_border_downloading_if_needed(progress_border, True) or widget_changed
                        except RuntimeError:
                            # Widget has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                            return

                finally:
                    # Re-enable updates and force single repaint
                    try:
                        widget.setUpdatesEnabled(True)
                        if compact_ui:
                            self._apply_compact_progress_state(widget, series_key, progress_percent, status_text)
                        elif widget_changed:
                            widget.update()
                    except RuntimeError:
                        # Widget has been deleted, remove from tracking
                        if series_key in self.series_widgets:
                            del self.series_widgets[series_key]
                        return
                    
        except Exception as e:
            _tm_logger.exception("ThumbnailManager: error in update_series_progress: %s", e)
    
    def _hide_overlay(self, widget):
        """Helper method to hide overlay safely (including glass background)"""
        try:
            if widget is None:
                return
            
            # Check if widget is still valid
            try:
                _ = widget.isVisible()
            except RuntimeError:
                return  # Widget already deleted
            
            # Hide progress overlay
            if hasattr(widget, 'progress_overlay'):
                try:
                    # Check if progress_overlay still exists
                    _ = widget.progress_overlay.isVisible()
                    widget.progress_overlay.setVisible(False)
                except RuntimeError:
                    pass
            
            # Hide glass overlay
            if hasattr(widget, 'glass_overlay'):
                try:
                    _ = widget.glass_overlay.isVisible()
                    widget.glass_overlay.setVisible(False)
                except RuntimeError:
                    pass
        except Exception as e:
            _tm_logger.debug("error hiding overlay: %s", e)


    def _hide_overlay_safe(self, widget):
        """Helper method to hide overlay safely with extra error handling for delayed calls"""
        try:
            if widget is None:
                return

            # Check if widget is still valid
            try:
                _ = widget.isVisible()
            except RuntimeError:
                return  # Widget already deleted

            # Hide progress overlay
            if hasattr(widget, 'progress_overlay'):
                try:
                    # Check if progress_overlay still exists
                    _ = widget.progress_overlay.isVisible()
                    widget.progress_overlay.setVisible(False)
                except RuntimeError:
                    pass

            # Hide glass overlay
            if hasattr(widget, 'glass_overlay'):
                try:
                    _ = widget.glass_overlay.isVisible()
                    widget.glass_overlay.setVisible(False)
                except RuntimeError:
                    pass
        except Exception as e:
            _tm_logger.debug("error hiding overlay (safe): %s", e)


    @_g6_slot_timing("thumbnail.start_series_download", series_arg="series_number")
    def start_series_download(self, series_number, total_images=None):
        """
        Mark series as starting download - THREAD SAFE
        علامت‌گذاری شروع دانلود سری - thread safe
        """
        try:
            series_key = self._resolve_series_key(series_number)
            total_images = self._remember_series_total_images(series_key, total_images)
            current_state = self._get_series_projection_state(series_key)
            if current_state == "downloading" and series_key in self.series_widgets:
                if total_images is not None:
                    self._set_series_count_label_text(series_key, f"{total_images} images")
                return

            self._set_series_projection_state(series_key, "downloading")
            self.ready_series.discard(series_key)
            _t_thumb_start = time.perf_counter()
            if not hasattr(self, '_thumb_pipeline_start'):
                self._thumb_pipeline_start = {}
            self._thumb_pipeline_start[series_key] = _t_thumb_start
            _tm_logger.info(
                "FAST:thumbnail_pipeline event=start series=%s t_abs=%.6f",
                series_key, _t_thumb_start,
            )
            _tm_logger.info("[FAST-THUMB-STATE] series=%s state=downloading bg_color=blue", series_key)
            
            # Find widget in series_widgets dictionary
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                compact_ui = self._should_use_compact_progress_ui(series_key, 0.0)

                # Check if widget is still valid
                try:
                    if widget is None:
                        return
                    _ = widget.isVisible()
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]
                    return

                # Prevent recursive repaints
                try:
                    widget.setUpdatesEnabled(False)
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]
                    return

                try:
                    # Show glass overlay background
                    if hasattr(widget, 'glass_overlay'):
                        try:
                            if compact_ui:
                                self._set_widget_visible_if_needed(widget.glass_overlay, False)
                            else:
                                if self._set_widget_visible_if_needed(widget.glass_overlay, True):
                                    widget.glass_overlay.raise_()
                        except RuntimeError:
                            # Widget has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                            return

                    # Show progress overlay with "0%"
                    if hasattr(widget, 'progress_overlay'):
                        try:
                            progress_overlay = widget.progress_overlay
                            overlay_text = "Downloading"
                            if total_images is not None and total_images > 0:
                                overlay_text = f"{total_images} images"
                                self._set_series_count_label_text(series_key, overlay_text)
                            if compact_ui:
                                self._set_widget_visible_if_needed(progress_overlay, False)
                            else:
                                self._set_label_text_if_needed(progress_overlay, overlay_text)
                                if not getattr(progress_overlay, '_b35_style_applied', False):
                                    progress_overlay.setStyleSheet("""
                                        QLabel {
                                            background: transparent;
                                            color: #ffffff;
                                            font-size: 14px;
                                            font-weight: bold;
                                            font-family: 'Segoe UI', 'Roboto', sans-serif;
                                            border: none;
                                            padding: 0px;
                                            line-height: 1.3;
                                        }
                                    """)
                                    progress_overlay._b35_style_applied = True
                                if self._set_widget_visible_if_needed(progress_overlay, True):
                                    progress_overlay.raise_()
                                progress_overlay.update()
                        except RuntimeError:
                            # Widget has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                            return

                    if total_images is not None and total_images > 0:
                            self._set_series_count_label_text(series_key, f"{total_images} images")

                    # Update border
                    if hasattr(widget, 'progress_border'):
                        try:
                            progress_border = widget.progress_border
                            self._set_progress_border_downloading_if_needed(progress_border, True)
                        except RuntimeError:
                            # Widget has been deleted, remove from tracking
                            if series_key in self.series_widgets:
                                del self.series_widgets[series_key]
                            return

                finally:
                    try:
                        widget.setUpdatesEnabled(True)
                        if compact_ui:
                            compact_text = f"0/{total_images}" if total_images is not None else ""
                            self._apply_compact_progress_state(widget, series_key, 0.0, compact_text)
                        widget.update()
                    except RuntimeError:
                        # Widget has been deleted, remove from tracking
                        if series_key in self.series_widgets:
                            del self.series_widgets[series_key]
                        return
            else:
                # Widget not created yet — queue so we apply the download state
                # as soon as create_thumbnail_widget registers it.
                if not hasattr(self, '_pending_download_series'):
                    self._pending_download_series = set()
                self._pending_download_series.add(series_key)
                if total_images is not None:
                    if not hasattr(self, '_pending_download_totals'):
                        self._pending_download_totals = {}
                    self._pending_download_totals[series_key] = total_images
                _tm_logger.debug("ThumbnailManager: start_series_download deferred for series %s", series_key)
                        
        except Exception as e:
            _tm_logger.exception("ThumbnailManager: error in start_series_download: %s", e)
    
    @_g6_slot_timing("thumbnail.complete_series_download", series_arg="series_number")
    def complete_series_download(self, series_number, total_images=None):
        """
        Mark series as download complete AND ready for display - با سیستم اولویت‌دار
        """
        try:
            series_key = self._resolve_series_key(series_number)
            total_images = self._remember_series_total_images(series_key, total_images)
            current_state = self._get_series_projection_state(series_key)
            if current_state == "completed":
                if series_key in self.series_widgets:
                    widget = self.series_widgets[series_key]
                    state_changed = False
                    try:
                        if widget and hasattr(widget, 'progress_border'):
                            state_changed = self._set_progress_border_downloading_if_needed(widget.progress_border, False) or state_changed
                            state_changed = self._set_progress_border_ready_if_needed(widget.progress_border, True) or state_changed
                    except (RuntimeError, AttributeError):
                        pass
                    try:
                        if widget and hasattr(widget, 'progress_overlay'):
                            state_changed = self._set_widget_visible_if_needed(widget.progress_overlay, False) or state_changed
                        if widget and hasattr(widget, 'glass_overlay'):
                            state_changed = self._set_widget_visible_if_needed(widget.glass_overlay, False) or state_changed
                    except (RuntimeError, AttributeError):
                        pass
                    if total_images is not None and total_images > 0:
                        label_text = f"{total_images}/{total_images}"
                        existing_label = getattr(widget, 'count_label', None)
                        if existing_label is None or existing_label.text() != label_text:
                            self._set_series_count_label_text(series_key, label_text)
                            state_changed = True
                    if state_changed:
                        self.apply_border_states_new()
                return

            self._set_series_projection_state(series_key, "completed")

            # 1. Mark as ready
            self.ready_series.add(series_key)
            _t_thumb_end = time.perf_counter()
            _t_thumb_start = getattr(self, '_thumb_pipeline_start', {}).pop(series_key, None)
            _dl_ms = (_t_thumb_end - _t_thumb_start) * 1000 if _t_thumb_start is not None else -1
            _tm_logger.info(
                "FAST:thumbnail_pipeline event=end series=%s t_abs=%.6f dl_ms=%.1f",
                series_key, _t_thumb_end, _dl_ms,
            )
            _tm_logger.info("[FAST-THUMB-STATE] series=%s state=completed bg_color=green", series_key)
            # do NOT depend on parent_widget being set (it is rarely set in production).
            # This is the primary path that makes the thumbnail turn green
            # when a download completes.
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                try:
                    if widget and hasattr(widget, 'progress_border'):
                        self._set_progress_border_downloading_if_needed(widget.progress_border, False)
                        self._set_progress_border_ready_if_needed(widget.progress_border, True)
                except (RuntimeError, AttributeError):
                    pass
                try:
                    if widget and hasattr(widget, 'progress_overlay'):
                        self._set_widget_visible_if_needed(widget.progress_overlay, False)
                    if widget and hasattr(widget, 'glass_overlay'):
                        self._set_widget_visible_if_needed(widget.glass_overlay, False)
                except (RuntimeError, AttributeError):
                    pass
                try:
                    if total_images is not None and total_images > 0:
                        self._set_series_count_label_text(series_key, f"{total_images}/{total_images}")
                except Exception:
                    pass

            # Schedule coalesced border repaint (immediate=False batches within 150ms)
            self.apply_border_states_new()

            # 3. Optionally notify parent widget (priority display, etc.)
            if hasattr(self, 'parent_widget') and self.parent_widget:
                try:
                    if hasattr(self.parent_widget, '_trigger_priority_display'):
                        self.parent_widget._trigger_priority_display(series_key)
                    elif hasattr(self.parent_widget, '_trigger_priority_display_after_download'):
                        self.parent_widget._trigger_priority_display_after_download(series_key)
                except Exception as e:
                    _tm_logger.debug("error triggering priority display: %s", e)

            _tm_logger.debug("ThumbnailManager: series %s complete and ready for display", series_key)

        except Exception as e:
            _tm_logger.exception("ThumbnailManager: error in complete_series_download: %s", e)


    def _force_border_update(self, series_key):
        """Force border update after delay"""
        try:
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                
                # Check if widget still exists
                try:
                    if widget is None:
                        return
                    _ = widget.isVisible()
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]
                    return

                if hasattr(widget, 'progress_border'):
                    try:
                        if widget.progress_border:
                            widget.progress_border.update()
                            widget.progress_border.repaint()
                    except (RuntimeError, AttributeError):
                        # Widget or progress_border has been deleted, remove from tracking
                        if series_key in self.series_widgets:
                            del self.series_widgets[series_key]
                        return

                try:
                    widget.update()
                    widget.repaint()
                except RuntimeError:
                    # Widget has been deleted, remove from tracking
                    if series_key in self.series_widgets:
                        del self.series_widgets[series_key]
                    return
        except Exception:
            pass
        

    def hide_all_progress_bars(self):
        """
        Reset all progress bars to pending state (used when thumbnails are first displayed)
        بازنشانی همه پروگرس بارها به حالت انتظار (برای نمایش اولیه تامب‌نیل‌ها)
        """
        try:
            for btn in self.buttons:
                widget = btn.parentWidget()
                if widget:
                    if hasattr(widget, 'progress_bar'):
                        widget.progress_bar.setVisible(False)
                    if hasattr(widget, 'status_label'):
                        widget.status_label.setPendingStyle()
        except Exception as e:
            _tm_logger.debug("error resetting progress bars: %s", e)
    
    def show_auto_download_progress(self, study_uid, total_series):
        """
        نمایش پیشرفت دانلود خودکار تامب‌نیل‌ها
        """
        try:
            _tm_logger.debug("showing auto-download progress for %d series", total_series)
            
            # ایجاد ویجت پیشرفت کلی
            if not hasattr(self, 'auto_download_widget'):
                self.create_auto_download_widget()
            
            # نمایش ویجت پیشرفت
            if hasattr(self, 'auto_download_widget'):
                self.auto_download_widget.setVisible(True)
                self.auto_download_widget.update_progress(0, total_series, "Starting download...")
            
        except Exception as e:
            _tm_logger.debug("error showing auto-download progress: %s", e)
    
    def create_auto_download_widget(self):
        """
        ایجاد ویجت نمایش پیشرفت دانلود خودکار
        """
        try:
            # Auto-download widget: previously stamped Material blue
            # (#3182ce) on every theme. Now derives from the active theme:
            # accent for borders + key labels, panel_bg for chrome, text
            # tokens for the body status text.
            t = self._theme if hasattr(self, '_theme') and self._theme else {}
            accent = t.get('accent', '#3182ce')
            panel_alt = t.get('panel_alt_bg', '#2d3748')
            panel_deep = t.get('panel_deep_bg', '#1a202c')
            text_secondary = t.get('text_secondary', '#cbd5e0')
            text_primary = t.get('text_primary', '#ffffff')

            # ایجاد ویجت اصلی
            self.auto_download_widget = QWidget()
            self.auto_download_widget.setFixedSize(180, 120)
            self.auto_download_widget.setStyleSheet(f"""
                QWidget {{
                    background: {panel_alt};
                    border: 2px solid {accent};
                    border-radius: 8px;
                    margin: 2px;
                }}
            """)

            # ایجاد layout
            layout = QVBoxLayout(self.auto_download_widget)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(4)

            # عنوان
            title_label = QLabel("Auto Download")
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    font-weight: bold;
                    color: {accent};
                    background: transparent;
                    border: none;
                }}
            """)
            layout.addWidget(title_label)

            # پیشرفت کلی
            self.auto_progress_bar = QProgressBar()
            self.auto_progress_bar.setRange(0, 100)
            self.auto_progress_bar.setValue(0)
            self.auto_progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: none;
                    border-radius: 4px;
                    background: {panel_deep};
                    text-align: center;
                    font-size: 10px;
                    font-weight: bold;
                    color: {text_primary};
                    height: 20px;
                }}
                QProgressBar::chunk {{
                    background: {accent};
                    border-radius: 4px;
                }}
            """)
            layout.addWidget(self.auto_progress_bar)

            # وضعیت
            self.auto_status_label = QLabel("Preparing...")
            self.auto_status_label.setAlignment(Qt.AlignCenter)
            self.auto_status_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 9px;
                    color: {text_secondary};
                    background: transparent;
                    border: none;
                }}
            """)
            layout.addWidget(self.auto_status_label)

            # شمارنده
            self.auto_counter_label = QLabel("0/0")
            self.auto_counter_label.setAlignment(Qt.AlignCenter)
            self.auto_counter_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 10px;
                    font-weight: bold;
                    color: {accent};
                    background: transparent;
                    border: none;
                }}
            """)
            layout.addWidget(self.auto_counter_label)
            
            # مخفی کردن در ابتدا
            self.auto_download_widget.setVisible(False)
            
            _tm_logger.debug("auto download widget created")
            
        except Exception as e:
            _tm_logger.debug("error creating auto download widget: %s", e)
    
    def update_auto_download_progress(self, current, total, status=""):
        """
        به‌روزرسانی پیشرفت دانلود خودکار
        """
        try:
            if hasattr(self, 'auto_download_widget') and self.auto_download_widget:
                # محاسبه درصد
                progress_percent = int((current / total) * 100) if total > 0 else 0
                
                # به‌روزرسانی پیشرفت
                if hasattr(self, 'auto_progress_bar'):
                    self.auto_progress_bar.setValue(progress_percent)
                    self.auto_progress_bar.setFormat(f"{progress_percent}%")
                
                # به‌روزرسانی وضعیت
                if hasattr(self, 'auto_status_label'):
                    self.auto_status_label.setText(status)
                
                # به‌روزرسانی شمارنده
                if hasattr(self, 'auto_counter_label'):
                    self.auto_counter_label.setText(f"{current}/{total}")
                
                # تغییر رنگ در صورت تکمیل
                if current >= total:
                    if hasattr(self, 'auto_progress_bar'):
                        self.auto_progress_bar.setStyleSheet("""
                            QProgressBar {
                                border: none;
                                border-radius: 4px;
                                background: #1a202c;
                                text-align: center;
                                font-size: 10px;
                                font-weight: bold;
                                color: #ffffff;
                                height: 20px;
                            }
                            QProgressBar::chunk {
                                background: #10b981;
                                border-radius: 4px;
                            }
                        """)
                    
                    if hasattr(self, 'auto_status_label'):
                        self.auto_status_label.setText("✅ Complete")
                        self.auto_status_label.setStyleSheet("""
                            QLabel {
                                font-size: 9px;
                                color: #10b981;
                                background: transparent;
                                border: none;
                            }
                        """)
                    
                    # مخفی کردن پس از 3 ثانیه
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(3000, self.hide_auto_download_widget)
                
        except Exception as e:
            _tm_logger.debug("error updating auto download progress: %s", e)
    
    def hide_auto_download_widget(self):
        """
        مخفی کردن ویجت پیشرفت دانلود خودکار
        """
        try:
            if hasattr(self, 'auto_download_widget') and self.auto_download_widget:
                self.auto_download_widget.setVisible(False)
                _tm_logger.debug("auto download widget hidden")
        except Exception as e:
            _tm_logger.debug("error hiding auto download widget: %s", e)
    
    def show_all_progress_bars_for_test(self):
        """
        Show all progress bars for testing - TEMPORARY DEBUG METHOD
        نمایش همه پروگرس بارها برای تست
        """
        try:
            for i, btn in enumerate(self.buttons):
                widget = btn.parentWidget()
                if widget:
                    if hasattr(widget, 'progress_bar'):
                        widget.progress_bar.setVisible(True)
                        widget.progress_bar.setValue(50)  # 50% for test
                        widget.progress_bar.setFormat("TEST 50%")
                    
                    if hasattr(widget, 'status_label'):
                        widget.status_label.setText("🧪 Testing...")
                        widget.status_label.setStyleSheet("""
                            QLabel {
                                font-size: 8px;
                                color: #f59e0b;
                                background: transparent;
                                border: none;
                                padding: 1px;
                            }
                        """)
        except Exception as e:
            _tm_logger.debug("error in test method: %s", e)
            import traceback
            traceback.print_exc()
