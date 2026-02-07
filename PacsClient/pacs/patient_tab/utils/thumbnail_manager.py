from PySide6.QtCore import QSize, Signal, QPropertyAnimation, QEasingCurve, QTimer, QRect
from PySide6.QtGui import QPixmap, Qt, QFont, QPainter, QPen, QBrush, QLinearGradient, QColor, QPainterPath
from PySide6.QtWidgets import QPushButton, QWidget, QLabel, QVBoxLayout, QApplication, QGridLayout, QProgressBar, QHBoxLayout, QFrame, QGraphicsDropShadowEffect
import weakref 
from PySide6.QtCore import QObject, Signal, QTimer, QThread

from PySide6.QtCore import QMimeData, QByteArray, Qt, Property, QRectF
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QDrag, QMouseEvent, QPixmap, QConicalGradient
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QWidget, QLabel, QProgressBar
from PySide6.QtCore import Qt
import math


class CircularProgressborder(QFrame):
    """
    Circular progress border widget that shows download progress as a colored border around thumbnail
    ویجت بوردر دایره‌ای که پیشرفت دانلود را به صورت یک بوردر رنگی دور تامب‌نیل نمایش می‌دهد
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress = 0  # 0-100
        self._border_width = 4  # border thickness
        self._downloading = False
        self._is_ready = False
        self._is_selected = False
        
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
        self._border_width = 4
        
        # Force immediate repaint
        self.update()
        self.repaint()
        
        # Also update via style sheet as backup
        self.setStyleSheet("""
            CircularProgressborder {
                border: 4px solid #10b981;
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
        """Hide the ready label with safety checks"""
        try:
            # ✅ FIX: Check if object still exists before calling update
            if not hasattr(self, '_ready_label') or self._ready_label is None:
                return
                
            # Check if the underlying C++ object still exists
            try:
                self._ready_label.hide()
                self._ready_label.update()
            except RuntimeError:
                # Object already deleted, ignore
                pass
                
        except Exception as e:
            print(f"⚠️ Error hiding ready label: {e}")

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
            print(f"Error in on_thumbnail_ready: {e}")

    def cleanup(self):
        """Clean up resources and timers"""
        try:
            if hasattr(self, 'dot_timer') and self.dot_timer:
                self.dot_timer.stop()
                self.dot_timer.deleteLater()
            
            if hasattr(self, '_animation') and self._animation:
                self._animation.stop()
                self._animation.deleteLater()
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
        
        # Determine border color and style based on state
        if self._is_selected:
            # Selected - Cyan border
            border_color = QColor(34, 211, 238)  # Cyan
            bg_color = QColor(34, 211, 238, 30)  # Light cyan background
        elif self._is_ready:
            # Ready - Green border
            border_color = QColor(16, 185, 129)  # Green
            bg_color = QColor(16, 185, 129, 20)  # Light green background
        elif self._downloading and self._progress > 0:
            # Downloading - Blue border with gradient based on progress
            border_color = QColor(59, 130, 246)  # Blue
            bg_color = QColor(59, 130, 246, 20)  # Light blue background
        else:
            # Pending - Gray dashed border
            border_color = QColor(113, 128, 150)  # Gray
            bg_color = QColor(113, 128, 150, 10)  # Light gray background
        
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
            # Solid border for pending/ready/selected
            if self._is_ready or self._is_selected:
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
                background: #3182ce;
                border-radius: 6px;
            }
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
    
    def setPendingStyle(self):
        """Set pending status style"""
        self.setText("Pending...")
        self.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-weight: bold;
                color: #fbbf24;
                background: transparent;
                border: 1px solid #fbbf24;
                border-radius: 4px;
                padding: 2px 4px;
            }
        """)
    
    def setDownloadingStyle(self, text=""):
        """Set downloading status style"""
        self.setText(text)
        self.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-weight: bold;
                color: #3182ce;
                background: transparent;
                border: 1px solid #3182ce;
                border-radius: 4px;
                padding: 2px 4px;
            }
        """)
    
    def setCompleteStyle(self):
        """Set complete status style"""
        self.setText("Ready")
        self.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-weight: bold;
                color: #10b981;
                background: transparent;
                border: 1px solid #10b981;
                border-radius: 4px;
                padding: 2px 4px;
            }
        """)


class DraggableButton(QPushButton):
    dragStarted = Signal(object)

    def __init__(self, pixmap, parent=None, thumbnail_index=0):
        super().__init__(parent)
        self.setIcon(pixmap)
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
                    mime_data.setText(str(self.thumbnail_index))  # send mime_data's value to interactor
                    drag.setMimeData(mime_data)
                    drag.setPixmap(self.icon().pixmap(self.iconSize()))
                    drag.exec(Qt.MoveAction)
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

    def __init__(self, method_change_series):
        super().__init__()  # فراخوانی سازنده QObject
        self.buttons = []
        self.lst_buttons_name = []
        self.method_change_series = method_change_series
        self.selected_series = None
        self.series_widgets = {}
        self.ready_series = set()
        self._pending_series_updates = {}
        self.current_study_uid = None  # برای ذخیره study_uid فعلی
    
    def set_current_study_uid(self, study_uid):
        """Set the current study UID - fixes the AttributeError"""
        self.current_study_uid = study_uid
        print(f"📝 [ThumbnailManager] Set current study UID: {study_uid}")
        
    def apply_border_states(self):
        """
        همه‌ی ویجت‌ها را مرور می‌کند و بر اساس سه حالت زیر استایل می‌دهد:
          - انتخاب‌شده (selected)
          - آماده (ready)
          - هیچ‌کدام
        """
        try:
            for key, w in self.series_widgets.items():
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
        except Exception as e:
            print(f"⚠️ apply_border_states error: {e}")
    
    def apply_border_states_new(self):
        """
        Apply border states using new CircularProgressborder - OPTIMIZED VERSION
        """
        try:
            # Skip if no widgets
            if not self.series_widgets:
                return
                
            print(f"🔄 [ThumbnailManager] apply_border_states_new called (widgets: {len(self.series_widgets)})")
            
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
                        
                        # Update progress border properties WITHOUT painting yet
                        progress_border._is_ready = is_ready
                        progress_border._is_selected = is_selected
                        
                        if is_ready:
                            progress_border._downloading = False
                            progress_border._progress = 100
                    
                    except Exception as e:
                        if "deleted" not in str(e).lower():
                            print(f"⚠️ Error processing widget {key}: {e}")
                        continue
                
                # Now do a single update for all widgets
                for w in self.series_widgets.values():
                    try:
                        if w and hasattr(w, 'progress_border'):
                            # Schedule update instead of immediate repaint
                            w.progress_border.update()
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
            
            print(f"✅ [ThumbnailManager] Border states applied")
            
        except Exception as e:
            if "deleted" not in str(e).lower():
                print(f"⚠️ apply_border_states_new error: {e}")
                

    @staticmethod
    def create_standard_metadata(series_number, modality='Unknown', series_description='', 
                                image_count=1, protocol_name='', body_part_examined='', 
                                is_downloading=False, main_thumbnail=True):
        """Create standardized metadata structure for consistent thumbnail creation"""
        return {
            'series': {
                'series_number': series_number,
                'modality': modality,
                'series_description': series_description,
                'protocol_name': protocol_name,
                'body_part_examined': body_part_examined,
                'main_thumbnail': main_thumbnail
            },
            'instances': [{'dummy': 'data'}] * image_count,
            'is_downloading': is_downloading
        }

    def register_button(self, button: QPushButton, button_name):
        self.buttons.append(button)
        self.lst_buttons_name.append(button_name)

    def uncheck_others(self, selected_button: QPushButton):
        for btn in self.buttons:
            btn.setChecked(btn is selected_button)


    def create_thumbnail_widget(self, pixmap: QPixmap, label_text: str, sop_instance_uid='test uid', thumbnail_index=0, series_info=None, show_progress=False):
        """Create unified and consistent thumbnail widget for all scenarios"""
        try:
            # Main container widget - SQUARE dimensions
            widget = QWidget()
            widget.setFixedSize(190, 190)
            main_layout = QVBoxLayout(widget)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            
            # Create circular progress border frame
            progress_border = CircularProgressborder()
            progress_border.setFixedSize(190, 190)
            border_layout = QVBoxLayout(progress_border)
            border_layout.setContentsMargins(8, 8, 8, 8)
            border_layout.setSpacing(3)
            
            # Inner content widget
            content_widget = QWidget()
            content_widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: none;
                    border-radius: 6px;
                }
            """)
            content_layout = QVBoxLayout(content_widget)
            content_layout.setContentsMargins(6, 6, 6, 6)
            content_layout.setSpacing(3)
            
            # Simple header - text only
            header_label = QLabel(f"Series {label_text}")
            header_label.setFixedHeight(18)
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #ffffff;
                    background: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            content_layout.addWidget(header_label)
            
            # Create draggable button for the image
            scaled_pixmap = pixmap.scaled(160, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_button = DraggableButton(scaled_pixmap, thumbnail_index=thumbnail_index)
            image_button.setFixedSize(160, 120)
            image_button.setIconSize(QSize(160, 120))
            image_button.setCheckable(True)
            image_button.setStyleSheet("""
                QPushButton {
                    border: none;
                    border-radius: 6px;
                    background: #1a202c;
                }
            """)
            content_layout.addWidget(image_button)
            
            # Set initial state
            if show_progress:
                progress_border.setDownloading(True)
                progress_border.setProgressAnimated(0)
            
            # Series info with description and image count
            if series_info:
                # Description label
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
                    count_label.setStyleSheet("""
                        QLabel {
                            font-size: 12px;
                            font-weight: bold;
                            color: #3b82f6;
                            background: transparent;
                            border: none;
                            padding: 2px;
                        }
                    """)
                    content_layout.addWidget(count_label)
                elif not desc or not desc.strip():
                    # If no count and no desc, show series number
                    series_number = series_info.get('series_number', '')
                    if series_number:
                        fallback_label = QLabel(f"Series {series_number}")
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
            glass_overlay.setGeometry(0, 0, 190, 190)
            glass_overlay.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(15, 23, 42, 200),
                        stop:1 rgba(30, 41, 59, 220));
                    border: 1px solid rgba(148, 163, 184, 60);
                    border-radius: 8px;
                }
            """)
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
            progress_overlay.setText("0%")
            
            # Position progress label
            label_width = 100
            label_height = 65
            label_x = (190 - label_width) // 2
            label_y = (190 - label_height) // 2
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
                self.selected_series = str(thumbnail_index)
                self.apply_border_states_new()

            image_button.dragStarted.connect(on_drag_started)
            
            # Setup click functionality - با افزودن انتشار سیگنال
            # Setup click functionality - با افزودن انتشار سیگنال
            def on_thumb_clicked():
                if image_button.isChecked():
                    self.selected_series = str(thumbnail_index)

                    # 🔥 انتشار سیگنال برای دانلود اولویت‌دار
                    study_uid = ''
                    if series_info and 'study_uid' in series_info:
                        study_uid = series_info.get('study_uid', '')
                    elif self.current_study_uid:
                        study_uid = self.current_study_uid

                    print(f"🔥 [ThumbnailManager] Emitting priority download for series {thumbnail_index}, study {study_uid}")
                    self.priority_download_requested.emit(str(thumbnail_index), study_uid)

                    # First try to change series normally (this will trigger loading if needed)
                    self.method_change_series(thumbnail_index)
                    self.apply_border_states_new()

            image_button.clicked.connect(on_thumb_clicked)
            
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
            widget.series_number = str(thumbnail_index)
            widget.thumbnail_index = thumbnail_index
            
            # Register button
            self.register_button(image_button, label_text)

            # Store widget in series_widgets
            self.series_widgets[str(thumbnail_index)] = widget

            # Apply any pending download state captured before the widget existed
            self._apply_pending_series_update(str(thumbnail_index))

            return widget
            
        except Exception as e:
            print(f"Error creating thumbnail widget: {str(e)}")
            error_widget = QWidget()
            error_widget.setFixedSize(180, 120)
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Error: {str(e)}")
            error_label.setStyleSheet("color: red; font-size: 8px;")
            error_layout.addWidget(error_label)
            return error_widget
    

    def set_series_pending(self, series_number: str):
        try:
            series_key = str(series_number)
            self.ready_series.discard(series_key)
            
            # Update new border style
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                if hasattr(widget, 'progress_border'):
                    widget.progress_border.setReady(False)
                    widget.progress_border.setDownloading(False)
                    widget.progress_border.update()
            
            # Also update old style for backward compatibility
            self.apply_border_states()
            self.apply_border_states_new()
        except Exception as e:
            print(f"⚠️ set_series_pending error: {e}")

    def set_series_ready(self, series_number: str):
        try:
            series_key = str(series_number)
            self.ready_series.add(series_key)  # مهم: این مجموعه تعیین‌کننده "کادر سبز" است
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                if hasattr(widget, 'progress_border'):
                    widget.progress_border.setReady(True)
            self.apply_border_states_new()
        except Exception as e:
            print(f"⚠️ set_series_ready error: {e}")


    def update_widget_borders(self, selected_widget=None):
        # اگر selected_widget داریم از parentش سری را حدس بزنیم
        if selected_widget and hasattr(selected_widget, "series_number"):
            self.selected_series = str(selected_widget.series_number)
        self.apply_border_states()
        self.apply_border_states_new()

    def highlight_priority_series(self, series_number):
        """
        Highlight a series with special priority styling
        سری را با استایل خاص اولویت هایلایت کن
        """
        try:
            series_key = str(series_number)
            print(f"🎨 Applying priority styling to series {series_key}")
            
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                
                # Add priority animation
                if hasattr(widget, 'progress_border'):
                    # Flash animation for priority
                    from PySide6.QtCore import QTimer, QPropertyAnimation
                    
                    # Store original border width
                    original_width = widget.progress_border._border_width
                    
                    # Flash animation
                    def flash_priority():
                        anim = QPropertyAnimation(widget.progress_border, b"_border_width")
                        anim.setDuration(500)
                        anim.setStartValue(original_width)
                        anim.setEndValue(original_width * 2)  # Thicker border
                        anim.setEasingCurve(QEasingCurve.InOutSine)
                        
                        def on_finished():
                            # Return to original
                            anim2 = QPropertyAnimation(widget.progress_border, b"_border_width")
                            anim2.setDuration(500)
                            anim2.setStartValue(original_width * 2)
                            anim2.setEndValue(original_width)
                            anim2.setEasingCurve(QEasingCurve.InOutSine)
                            anim2.start()
                        
                        anim.finished.connect(on_finished)
                        anim.start()
                    
                    # Flash 3 times
                    for i in range(3):
                        QTimer.singleShot(i * 1000, flash_priority)
                    
                    print(f"✅ Priority animation started for series {series_key}")
                
                # Update border state immediately
                self.apply_border_states_new()
                
        except Exception as e:
            print(f"⚠️ Error highlighting priority series: {e}")


    def update_series_progress(self, series_number, progress_percent, status_text=""):
        """
        Update download progress with PRIORITY indicator
        """
        try:
            series_key = str(series_number)
            
            # Add priority indicator if this is a high priority download
            is_priority = "⚡" in status_text or "🎯" in status_text or "🔄" in status_text
            
            if is_priority and (progress_percent % 25 == 0 or progress_percent >= 100):
                print(f"⚡ [PRIORITY PROGRESS] Series {series_key}: {progress_percent:.1f}% - {status_text}")
            
            # Rest of the existing code...
            if series_key not in self.series_widgets:
                self._queue_pending_series_update(
                    series_key,
                    started=True,
                    progress_percent=progress_percent,
                    status_text=status_text
                )
                return
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]


                
                # Check if widget is still valid
                try:
                    if widget is None:
                        return
                    # Test if widget is still alive by checking a property
                    _ = widget.isVisible()
                except RuntimeError:
                    # Widget has been deleted
                    return
                
                # Batch UI updates to prevent recursive repaints
                widget.setUpdatesEnabled(False)
                
                try:
                    # Show glass overlay background
                    if hasattr(widget, 'glass_overlay'):
                        widget.glass_overlay.setVisible(True)
                        widget.glass_overlay.raise_()
                    
                    # Update progress overlay (PRIMARY method - always visible during download)
                    if hasattr(widget, 'progress_overlay'):
                        progress_overlay = widget.progress_overlay
                        
                        if progress_percent > 0 and progress_percent < 100:
                            # Show percentage and count during download
                            # status_text format: "current/total" (e.g., "3/8")
                            display_text = f"{int(progress_percent)}%"
                            if status_text:
                                display_text = f"{int(progress_percent)}%\n{status_text}"
                            
                            progress_overlay.setText(display_text)
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
                            progress_overlay.setVisible(True)
                            progress_overlay.raise_()  # Ensure it's on top
                            
                            # Force update to make sure it's visible
                            progress_overlay.update()
                            
                        elif progress_percent >= 100:
                            # Show "Ready" message briefly, then hide
                            progress_overlay.setText("✅")
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
                            progress_overlay.setVisible(True)
                            progress_overlay.raise_()
                            progress_overlay.update()

                        else:
                            progress_overlay.setVisible(False)
                            # Hide glass overlay when not in progress
                            if hasattr(widget, 'glass_overlay'):
                                widget.glass_overlay.setVisible(False)
                                
                        # Hide after 2.5 seconds (both glass and progress)
                        QTimer.singleShot(2500, lambda: self._hide_overlay(widget))

                        # Mark as ready
                        self.ready_series.add(series_key)

                    # Update border state (secondary visual indicator)
                    if hasattr(widget, 'progress_border'):
                        progress_border = widget.progress_border

                        if progress_percent >= 100:
                            progress_border.setDownloading(False)
                            progress_border.setReady(True)
                        elif progress_percent > 0:
                            progress_border.setDownloading(True)

                finally:
                    # Re-enable updates and force single repaint
                    widget.setUpdatesEnabled(True)
                    widget.update()

            if series_key not in self.series_widgets:
                self._queue_pending_series_update(series_key, completed=True)
                    
        except Exception as e:
            print(f"⚠️ Error updating series progress: {e}")
            import traceback
            traceback.print_exc()
    
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
            print(f"⚠️ Error hiding overlay: {e}")

            
    def _queue_pending_series_update(self, series_key, **updates):
        state = self._pending_series_updates.get(series_key, {})
        state.update(updates)
        self._pending_series_updates[series_key] = state

    def _apply_pending_series_update(self, series_key):
        state = self._pending_series_updates.pop(series_key, None)
        if not state:
            return

        # Apply the most recent known state to the new widget
        if state.get('started'):
            self.start_series_download(series_key)
        if 'progress_percent' in state:
            self.update_series_progress(
                series_key,
                state.get('progress_percent', 0),
                state.get('status_text', '')
            )
        if state.get('completed'):
            self.complete_series_download(series_key)

    def start_series_download(self, series_number):
        """
        Mark series as starting download - THREAD SAFE
        ??????????????????????? ???????? ???????????? ?????? - thread safe
        """
        try:
            series_key = str(series_number)

            # DEBUG: Print available keys
            print(f"???? [ThumbnailManager] start_series_download called for series: {series_key}")
            print(f"   ???? Available series_widgets keys: {list(self.series_widgets.keys())}")

            # Find widget in series_widgets dictionary
            if series_key not in self.series_widgets:
                # Widget not ready yet; queue update and apply when thumbnail is created
                self._queue_pending_series_update(
                    series_key,
                    started=True,
                    progress_percent=0,
                    status_text="0%"
                )
                return

            widget = self.series_widgets[series_key]

            # Check if widget is still valid
            try:
                if widget is None:
                    return
                _ = widget.isVisible()
            except RuntimeError:
                return

            # Prevent recursive repaints
            widget.setUpdatesEnabled(False)

            try:
                # Show glass overlay background
                if hasattr(widget, 'glass_overlay'):
                    widget.glass_overlay.setVisible(True)
                    widget.glass_overlay.raise_()

                # Show progress overlay with "0%"
                if hasattr(widget, 'progress_overlay'):
                    progress_overlay = widget.progress_overlay
                    progress_overlay.setText("0%...")
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
                    progress_overlay.setVisible(True)
                    progress_overlay.raise_()
                    progress_overlay.update()

                # Update border
                if hasattr(widget, 'progress_border'):
                    progress_border = widget.progress_border
                    progress_border.setDownloading(True)

            finally:
                widget.setUpdatesEnabled(True)
                widget.update()
                print(f"   ??? Progress overlay shown for series {series_key}")

        except Exception as e:
            print(f"?????? Error starting series download: {e}")
            import traceback
            traceback.print_exc()

    def complete_series_download(self, series_number):
        """
        Mark series as download complete AND ready for display - با سیستم اولویت‌دار
        """
        try:
            series_key = str(series_number)
            print(f"🎯 [PRIORITY COMPLETE] Completing download for series {series_key}")

            # 1. علامت‌گذاری به عنوان آماده
            self.ready_series.add(series_key)

            if series_key not in self.series_widgets:
                self._queue_pending_series_update(series_key, completed=True)

            # 2. فراخوانی نمایش اولویت‌دار در parent widget
            if hasattr(self, 'parent_widget') and self.parent_widget:
                # اینجا باید parent widget (PatientWidget) را پیدا کنیم
                # فرض می‌کنیم که parent_widget به PatientWidget اشاره دارد
                try:
                    # First try the existing method
                    if hasattr(self.parent_widget, '_trigger_priority_display'):
                        self.parent_widget._trigger_priority_display(series_key)
                    # If that doesn't work, try the new method for post-download display
                    elif hasattr(self.parent_widget, '_trigger_priority_display_after_download'):
                        self.parent_widget._trigger_priority_display_after_download(series_key)
                except Exception as e:
                    print(f"⚠️ Error triggering priority display: {e}")

            # 3. به‌روزرسانی border
            self.apply_border_states_new()

            print(f"✅ [PRIORITY COMPLETE] Series {series_key} ready for immediate display")

        except Exception as e:
            print(f"❌ Error in complete_series_download: {e}")
            import traceback
            traceback.print_exc()


    def _force_border_update(self, series_key):
        """Force border update after delay"""
        try:
            if series_key in self.series_widgets:
                widget = self.series_widgets[series_key]
                if hasattr(widget, 'progress_border'):
                    widget.progress_border.update()
                    widget.progress_border.repaint()
                widget.update()
                widget.repaint()
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
            print(f"⚠️ Error resetting progress bars: {e}")
    
    def show_auto_download_progress(self, study_uid, total_series):
        """
        نمایش پیشرفت دانلود خودکار تامب‌نیل‌ها
        """
        try:
            print(f"📊 Showing auto-download progress for {total_series} series")
            
            # ایجاد ویجت پیشرفت کلی
            if not hasattr(self, 'auto_download_widget'):
                self.create_auto_download_widget()
            
            # نمایش ویجت پیشرفت
            if hasattr(self, 'auto_download_widget'):
                self.auto_download_widget.setVisible(True)
                self.auto_download_widget.update_progress(0, total_series, "Starting download...")
            
        except Exception as e:
            print(f"⚠️ Error showing auto-download progress: {e}")
    
    def create_auto_download_widget(self):
        """
        ایجاد ویجت نمایش پیشرفت دانلود خودکار
        """
        try:
            # ایجاد ویجت اصلی
            self.auto_download_widget = QWidget()
            self.auto_download_widget.setFixedSize(180, 120)
            self.auto_download_widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 2px solid #3182ce;
                    border-radius: 8px;
                    margin: 2px;
                }
            """)
            
            # ایجاد layout
            layout = QVBoxLayout(self.auto_download_widget)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(4)
            
            # عنوان
            title_label = QLabel("Auto Download")
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #3182ce;
                    background: transparent;
                    border: none;
                }
            """)
            layout.addWidget(title_label)
            
            # پیشرفت کلی
            self.auto_progress_bar = QProgressBar()
            self.auto_progress_bar.setRange(0, 100)
            self.auto_progress_bar.setValue(0)
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
                    background: #3182ce;
                    border-radius: 4px;
                }
            """)
            layout.addWidget(self.auto_progress_bar)
            
            # وضعیت
            self.auto_status_label = QLabel("Preparing...")
            self.auto_status_label.setAlignment(Qt.AlignCenter)
            self.auto_status_label.setStyleSheet("""
                QLabel {
                    font-size: 9px;
                    color: #cbd5e0;
                    background: transparent;
                    border: none;
                }
            """)
            layout.addWidget(self.auto_status_label)
            
            # شمارنده
            self.auto_counter_label = QLabel("0/0")
            self.auto_counter_label.setAlignment(Qt.AlignCenter)
            self.auto_counter_label.setStyleSheet("""
                QLabel {
                    font-size: 10px;
                    font-weight: bold;
                    color: #3182ce;
                    background: transparent;
                    border: none;
                }
            """)
            layout.addWidget(self.auto_counter_label)
            
            # مخفی کردن در ابتدا
            self.auto_download_widget.setVisible(False)
            
            print("✅ Auto download widget created")
            
        except Exception as e:
            print(f"❌ Error creating auto download widget: {e}")
    
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
            print(f"⚠️ Error updating auto download progress: {e}")
    
    def hide_auto_download_widget(self):
        """
        مخفی کردن ویجت پیشرفت دانلود خودکار
        """
        try:
            if hasattr(self, 'auto_download_widget') and self.auto_download_widget:
                self.auto_download_widget.setVisible(False)
                print("✅ Auto download widget hidden")
        except Exception as e:
            print(f"⚠️ Error hiding auto download widget: {e}")
    
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
            print(f"⚠️ Error in test method: {e}")
            import traceback
            traceback.print_exc()
