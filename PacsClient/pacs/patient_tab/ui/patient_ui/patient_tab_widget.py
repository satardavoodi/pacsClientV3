from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                               QFrame, QSizePolicy, QGraphicsDropShadowEffect, QPushButton)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QTimer, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QLinearGradient, QPen, QMouseEvent
import os

# Theme-aware tab chrome: when the user switches workstation theme (Blue → Green
# → Yellow, etc.) the tab's painted border and gradient backdrop should follow
# the active accent. Case-of-Day mode still wins so educational cases stay
# unambiguously green regardless of theme.
try:
    from PacsClient.utils.theme_manager import get_theme_manager
except Exception:  # pragma: no cover — defensive fallback
    get_theme_manager = None


class PatientTabWidget(QWidget):
    """
    Custom tab widget for patient tabs with beautiful UI
    Shows patient name, patient ID, and first thumbnail
    Supports study_uid for duplicate prevention
    """

    # Signal for close button click
    close_requested = Signal()

    def __init__(self, patient_name="Unknown", patient_id="N/A", thumbnail_path=None, study_uid=None, parent=None):
        super().__init__(parent)
        self.patient_name = patient_name
        self.patient_id = patient_id
        self.thumbnail_path = thumbnail_path
        self.study_uid = study_uid
        self.thumbnail_pixmap = None
        # Case-of-Day mode — when enabled, the tab's name/id labels are
        # repurposed for educational case context (name slot shows
        # "Case of the Day", id slot shows the diagnosis) and the painted
        # border switches from the normal blue/grey to green so the user
        # can tell at a glance this is an educational view, not the
        # routine clinical patient open.
        self.case_of_day_mode = False
        self.case_of_day_diagnosis = ""

        # Set cursor to pointing hand
        self.setCursor(Qt.PointingHandCursor)

        self.setup_ui()
        self.load_thumbnail()
        self.apply_styling()

        # Subscribe to theme switches so the tab chrome re-styles live without
        # waiting for the widget to be re-shown. Best-effort: the wrapped
        # try/except keeps the legacy demo / standalone-import paths from
        # crashing if the theme manager isn't available.
        try:
            if get_theme_manager is not None:
                get_theme_manager().themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass

    def _on_theme_changed(self, _theme: dict) -> None:
        """ThemeManager.themeChanged callback — re-apply styling + repaint border."""
        try:
            self.apply_styling()
            self.update()
        except Exception:
            pass

    def _current_theme(self) -> dict:
        """Active theme dict or an empty dict if the theme manager is missing."""
        try:
            if get_theme_manager is not None:
                return get_theme_manager().current_theme() or {}
        except Exception:
            pass
        return {}

    def setup_ui(self):
        """Setup the main layout and widgets"""
        # Create main layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Create thumbnail container (reduced by 30%)
        self.thumbnail_container = QFrame()
        self.thumbnail_container.setObjectName("ThumbnailContainer")
        self.thumbnail_container.setFixedSize(52, 63)

        # Create thumbnail label
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("ThumbnailLabel")
        self.thumbnail_label.setFixedSize(52, 63)  # Set fixed size to match container
        self.thumbnail_label.setScaledContents(False)  # Don't stretch - preserve aspect ratio!
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                background: #1a202c;
                border: none;
                border-radius: 6px;
                padding: 2px;
            }
        """)

        # Set default thumbnail (placeholder)
        self.set_default_thumbnail()

        # Add thumbnail to container
        thumbnail_layout = QVBoxLayout(self.thumbnail_container)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0)
        thumbnail_layout.addWidget(self.thumbnail_label, alignment=Qt.AlignCenter)

        main_layout.addWidget(self.thumbnail_container)

        # Patient info container
        info_container = QFrame()
        info_container.setObjectName("InfoContainer")
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        # Patient name label — Archetype 3 (PatientNameLabel, a DICOM-aware
        # variant of ElidedLabel). For names in DICOM PN format
        # (e.g. "ABDOLHOSEIN^MOHAMMAD ABAS"), it prefers showing whole
        # name components rather than chopping the family name mid-character:
        #   1. Full string fits     → "ABDOLHOSEIN MOHAMMAD ABAS"
        #   2. Family+given fits    → "ABDOLHOSEIN MOHAMMAD ABAS" (space-joined)
        #   3. Just family fits     → "ABDOLHOSEIN" (no ellipsis)
        #   4. Family overflows     → "ABDOLHOSE…" (last-resort right-elide)
        # Full name is always available as a tooltip.
        # See docs/conventions/RESPONSIVE_UI_CONVENTION.md.
        try:
            from PacsClient.utils.responsive_layout import PatientNameLabel
            self.name_label = PatientNameLabel(self.patient_name)
        except Exception:  # pragma: no cover — defensive fallback
            self.name_label = QLabel(self.patient_name)
        self.name_label.setObjectName("PatientName")
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Patient ID label with line
        self.id_label = QLabel(f"ID: {self.patient_id}")
        self.id_label.setObjectName("PatientID")
        self.id_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Separator line
        # self.separator_line = QFrame()
        # self.separator_line.setObjectName("SeparatorLine")
        # self.separator_line.setFixedHeight(1)

        info_layout.addWidget(self.name_label)
        # info_layout.addWidget(self.separator_line)
        info_layout.addWidget(self.id_label)

        # Add widgets to main layout — give info_container stretch=1 so it
        # claims the row's remaining width instead of being squeezed to its
        # sizeHint by a sibling addStretch(). Without this, the PatientNameLabel
        # only ever sees its (small) sizeHint width and elides too aggressively
        # — the user-visible truncation regression. The close button still hugs
        # the right edge because nothing follows it in the row.
        main_layout.addWidget(info_container, 1)

        # Add close button with minimal space (reduced by 30%)
        self.close_button = QLabel("×")
        self.close_button.setObjectName("CloseButton")
        self.close_button.setFixedSize(18, 18)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("Close tab")
        self.close_button.mousePressEvent = self.close_button_clicked

        # Add close button with better spacing
        # main_layout.addWidget(self.close_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        main_layout.addWidget(self.close_button, 0, Qt.AlignRight | Qt.AlignmentFlag.AlignTop)

        # Set size policy - Fixed width for tabs (reduced by 30%)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(252)  # Reduced by 30% from 360
        self.setFixedHeight(70)  # Reduced by 30% from 100

    def load_thumbnail(self):
        """Load and display the thumbnail image"""
        if self.thumbnail_path and os.path.exists(self.thumbnail_path):
            try:
                # Load thumbnail
                pixmap = QPixmap(self.thumbnail_path)
                if not pixmap.isNull():
                    # Scale to fit container while maintaining aspect ratio
                    scaled_pixmap = pixmap.scaled(
                        52, 63,  # Match thumbnail_label size
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.thumbnail_pixmap = scaled_pixmap
                    self.thumbnail_label.setPixmap(scaled_pixmap)
                else:
                    self.set_default_thumbnail()
            except Exception as e:
                print(f"Error loading thumbnail: {e}")
                self.set_default_thumbnail()
        else:
            self.set_default_thumbnail()

    def set_default_thumbnail(self):
        """Set a default medical icon when no thumbnail is available"""
        # Create a simple medical icon
        pixmap = QPixmap(28, 28)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw medical cross
        painter.setPen(QPen(QColor("#4A90E2"), 2))
        painter.drawLine(14, 8, 14, 20)  # Vertical line
        painter.drawLine(8, 14, 20, 14)  # Horizontal line

        painter.end()

        self.thumbnail_pixmap = pixmap
        self.thumbnail_label.setPixmap(pixmap)

    def apply_styling(self):
        """Apply beautiful styling to the tab widget.

        The default/hover/active gradients used to be hard-coded indigo→violet
        (`#667eea→#764ba2`), which clashed with every non-Blue theme. The
        gradient now derives from the active theme's `tab_bg`, `accent`, and
        `accent_secondary` tokens so a Green theme produces a green tab, a
        Yellow theme produces an amber tab, etc. The `!important` flags stay
        to defeat the global stylesheet's button styling.
        """
        t = self._current_theme()
        # Fallbacks line up with the Blue baseline so an unthemed instance
        # still renders the historical look.
        tab_bg = t.get("tab_bg", "#1f2850")
        panel_bg = t.get("panel_bg", "#111a34")
        accent = t.get("accent", "#3182ce")
        accent_secondary = t.get("accent_secondary", "#0284c7")
        accent_pressed = t.get("accent_pressed", "#2c5282")
        border_color = t.get("border", "#4a5568")
        text_primary = t.get("text_primary", "#f8fafc")

        # Theme-aware prefix (f-string — needs braces escaped). The rest of
        # the stylesheet below stays raw with regular CSS braces.
        themed_prefix = f"""
            PatientTabWidget {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {tab_bg}, stop:0.55 {panel_bg}, stop:1 {tab_bg}) !important;
                border: 2px solid {border_color} !important;
                border-radius: 8px !important;
                min-height: 45px !important;
                max-width: 170px !important;
                color: {text_primary} !important;
            }}

            PatientTabWidget:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {accent_secondary}, stop:0.55 {tab_bg}, stop:1 {panel_bg}) !important;
                border: 2px solid {accent} !important;
            }}

            PatientTabWidget.active {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {accent}, stop:0.55 {accent_pressed}, stop:1 {panel_bg}) !important;
                border: 2px solid {accent} !important;
            }}
        """

        stylesheet = themed_prefix + """
            QFrame#ThumbnailContainer {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 6px;
            }
            
            PatientTabWidget.active QFrame#ThumbnailContainer {
                background: rgba(255, 255, 255, 0.3);
            }
            
            QLabel#ThumbnailLabel {
                background: transparent;
                border-radius: 4px;
            }
            
            QFrame#InfoContainer {
                background: transparent;
            }
            
            QLabel#PatientName {
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
                font-size: 16px;
                font-weight: bold;
                background: transparent;
                padding: 0px;
                margin: 0px;
            }
            
            PatientTabWidget.active QLabel#PatientName {
                color: #ffffff;
                font-weight: bold;
                font-size: 16px;
            }
            
            QLabel#PatientID {
                color: rgba(255, 255, 255, 0.8);
                font-family: 'Segoe UI', sans-serif;
                font-size: 16px;
                font-weight: bold;
                background: transparent;
                padding: 0px;
                margin: 0px;
            }
                
            PatientTabWidget.active QLabel#PatientID {
                color: rgba(255, 255, 255, 0.9);
                font-weight: bold;
                font-size: 16px;
            }
            
            QFrame#SeparatorLine {
                background: rgba(255, 255, 255, 0.6);
                border-radius: 1px;
                margin: 1px 0px;
                height: 1px;
            }
            
            PatientTabWidget.active QFrame#SeparatorLine {
                background: #ffffff;
                height: 2px;
            }
            
            QLabel#CloseButton {
                background: rgba(239, 68, 68, 0.7);
                border: 1px solid rgba(239, 68, 68, 0.8);
                border-radius: 5px;
                color: white;
                font-size: 12px;
                font-weight: bold;
                margin: 0px;
                padding-bottom: 1px;

            }
            
            QLabel#CloseButton:hover {
                background: rgba(239, 68, 68, 0.9);
                border: 1px solid rgba(239, 68, 68, 1.0);
            }
        """

        self.setStyleSheet(stylesheet)

        # Simple shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def update_patient_info(self, patient_name=None, patient_id=None, thumbnail_path=None, study_uid=None):
        """Update patient information"""
        lst_nulls = ['N/A', '', None]
        # In Case-of-Day mode, the name/id labels are repurposed — DO NOT
        # let the regular metadata pipeline overwrite them with real patient
        # values; that would erase the educational header the user just set.
        if self.case_of_day_mode:
            # Still pick up study_uid (used for dedupe) and thumbnail
            # (purely cosmetic) but skip the text overrides.
            if thumbnail_path and thumbnail_path not in lst_nulls:
                if self.thumbnail_path != thumbnail_path:
                    self.thumbnail_path = thumbnail_path
                    self.load_thumbnail()
            if study_uid and self.study_uid in lst_nulls:
                self.study_uid = study_uid
            return

        if patient_name and self.patient_name in lst_nulls:
            self.patient_name = patient_name
            self.name_label.setText(patient_name)

        if patient_id and self.patient_id in lst_nulls:
            self.patient_id = patient_id
            self.id_label.setText(f"ID: {patient_id}")

        # Update thumbnail if provided and different from current
        if thumbnail_path and thumbnail_path not in lst_nulls:
            if self.thumbnail_path != thumbnail_path:
                self.thumbnail_path = thumbnail_path
                self.load_thumbnail()

        if study_uid and self.study_uid in lst_nulls:
            self.study_uid = study_uid

    def set_case_of_day_mode(self, diagnosis: str = ""):
        """Switch this tab chrome into Case-of-Day educational mode.

        - Replaces the patient name label with "Case of the Day"
        - Replaces the patient ID label with the diagnosis
        - Re-paints with a green border instead of the clinical blue
        - Future metadata refreshes from the PatientWidget are ignored
          (see update_patient_info), so the educational header sticks.

        The real `patient_id`, `patient_name`, and `study_uid` are NOT
        touched — only the on-screen labels — so the underlying viewer
        keeps working with the original study identity.
        """
        self.case_of_day_mode = True
        self.case_of_day_diagnosis = (diagnosis or "").strip()
        try:
            self.name_label.setText("Case of the Day")
        except Exception:
            pass
        try:
            display_diag = self.case_of_day_diagnosis or "—"
            self.id_label.setText(f"Dx: {display_diag}")
        except Exception:
            pass
        # Force the paintEvent to refresh so the green border is drawn.
        self.update()

    def get_tab_text(self):
        """Get the text to display on the tab"""
        return f"{self.patient_name} ({self.patient_id})"

    def get_study_uid(self):
        """Get the study UID for this tab"""
        return self.study_uid

    def close_tab_requested(self):
        """Handle close button click"""
        # Emit a signal or call a callback to close the tab
        # This will be handled by the parent tab manager
        if hasattr(self, 'close_requested'):
            self.close_requested.emit()

    def close_button_clicked(self, event):
        """Handle close button click for QLabel"""
        if event.button() == Qt.LeftButton:
            self.close_tab_requested()
        event.accept()

    def enterEvent(self, event):
        """Handle mouse enter event for hover effects"""
        super().enterEvent(event)
        # Add hover animation
        self.animate_hover(True)

    def leaveEvent(self, event):
        """Handle mouse leave event for hover effects"""
        super().leaveEvent(event)
        # Remove hover animation
        self.animate_hover(False)

    def animate_hover(self, hover_in):
        """Animate the hover effect"""
        animation = QPropertyAnimation(self, b"geometry")
        animation.setDuration(150)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        current_geometry = self.geometry()
        if hover_in:
            # Slightly move up and scale
            new_geometry = current_geometry.adjusted(0, -1, 0, -1)
        else:
            # Return to original position
            new_geometry = current_geometry.adjusted(0, 1, 0, 1)

        animation.setStartValue(current_geometry)
        animation.setEndValue(new_geometry)
        animation.start()

    def animate_active(self, active):
        """Animate the active state change"""
        animation = QPropertyAnimation(self, b"geometry")
        animation.setDuration(200)
        animation.setEasingCurve(QEasingCurve.OutBack)

        current_geometry = self.geometry()
        if active:
            # Move up slightly when active
            new_geometry = current_geometry.adjusted(0, -2, 0, -2)
        else:
            # Return to normal position
            new_geometry = current_geometry.adjusted(0, 2, 0, 2)

        animation.setStartValue(current_geometry)
        animation.setEndValue(new_geometry)
        animation.start()

    def set_active(self, active=True):
        """Set the tab as active or inactive"""

        if active:
            self.setProperty("active", True)
            self.setStyle(self.style())  # Refresh style
            # Force style update
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            self.setProperty("active", False)
            self.setStyle(self.style())  # Refresh style
            # Force style update
            self.style().unpolish(self)
            self.style().polish(self)

    def is_active(self):
        """Check if the tab is active"""
        return self.property("active") == True

    def showEvent(self, event):
        """Override show event to ensure styling is applied"""
        super().showEvent(event)
        # Force style refresh when widget is shown
        self.force_style_refresh()

    def paintEvent(self, event):
        """Override paint event to ensure styling is applied"""
        super().paintEvent(event)

        # Force draw borders manually if styling isn't working
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get current state
        is_active = self.is_active()

        # Set border color based on state.
        # Case-of-Day mode overrides both active and inactive colors with
        # green so the user can visually tell an educational case apart
        # from a routine clinical patient tab. Otherwise the border tracks
        # the active workstation theme — active tab uses `accent`, inactive
        # uses the theme's `border` token.
        if self.case_of_day_mode:
            if is_active:
                border_color = QColor("#15803d")  # green-700 — active educational
            else:
                border_color = QColor("#22c55e")  # green-500 — inactive educational
            border_width = 2
        else:
            t = self._current_theme()
            if is_active:
                border_color = QColor(t.get("accent", "#2b6cb0"))
            else:
                border_color = QColor(t.get("border", "#4a5568"))
            border_width = 2

        # Draw border
        pen = QPen(border_color, border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.transparent)

        # Draw rounded rectangle border with AiPacs button radius
        rect = self.rect().adjusted(border_width // 2, border_width // 2, -border_width // 2, -border_width // 2)
        painter.drawRoundedRect(rect, 8, 8)

        # Add subtle shadow for active tabs. Glow uses the theme accent (with
        # low alpha) so it harmonises with whatever palette the user picks;
        # Case-of-Day keeps its dedicated green halo.
        if is_active:
            if self.case_of_day_mode:
                shadow_color = QColor(34, 197, 94, 60)  # green-500 glow
            else:
                # Use the theme accent border color, just with reduced alpha.
                shadow_color = QColor(border_color)
                shadow_color.setAlpha(60)
            shadow_pen = QPen(shadow_color, 1)
            painter.setPen(shadow_pen)
            shadow_rect = rect.adjusted(1, 1, 1, 1)
            painter.drawRoundedRect(shadow_rect, 8, 8)

        painter.end()

    def force_style_refresh(self):
        """Force refresh the styling"""
        self.apply_styling()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def test_styling(self):
        """Test method to verify styling is working"""

        # Test with a very simple, obvious style
        test_style = """
            PatientTabWidget {
                background: #4A90E2 !important;
                border: 3px solid #F59E0B !important;
            }
        """
        self.setStyleSheet(test_style)
        self.update()

        # Wait a moment, then restore normal style
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(self.force_style_refresh)
        timer.start(2000)  # Restore after 2 seconds
