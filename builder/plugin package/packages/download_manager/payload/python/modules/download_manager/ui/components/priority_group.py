"""
Priority Group Header - Collapsible priority section header

Modern, prominent header for priority groups with colored gradient background.
"""

import logging
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QLinearGradient, QColor, QPainter, QPen, QBrush
import qtawesome as qta

from ...core.enums import DownloadPriority
from ..styles.colors import ColorPalette
from ..styles.animations import AnimationManager

logger = logging.getLogger(__name__)

# Module-level QIcon cache — qta.icon() loads font glyphs and renders a pixmap
# on every call (~10-30 ms each on Windows).  With 4 group headers × 2 icons
# and N data rows × 4 action-button icons per rebuild, uncached calls dominate
# the DM_REBUILD hot path.  The cache is keyed by (icon_name, sorted_kwargs)
# and persists for the lifetime of the process.
_QTA_ICON_CACHE: dict = {}


def _qta_cached(name: str, **kwargs):
    """Return a cached QIcon for *name*, creating it once on first access."""
    key = (name, tuple(sorted(kwargs.items())))
    if key not in _QTA_ICON_CACHE:
        _QTA_ICON_CACHE[key] = qta.icon(name, **kwargs)
    return _QTA_ICON_CACHE[key]


class PriorityGroupHeader(QWidget):
    """
    Modern priority group header with gradient background
    
    Features:
    - Colored gradient background
    - White text with shadow
    - Icon + title + count badge
    - Expand/collapse button with animation
    - Hover effects
    
    Signals:
        collapsed_changed: (priority_name, is_collapsed)
    """
    
    # Signal
    collapsed_changed = Signal(str, bool)
    
    # Priority icons
    ICONS = {
        DownloadPriority.CRITICAL: 'fa5s.exclamation-circle',
        DownloadPriority.HIGH: 'fa5s.arrow-up',
        DownloadPriority.NORMAL: 'fa5s.minus',
        DownloadPriority.LOW: 'fa5s.arrow-down',
    }
    
    def __init__(self, priority: DownloadPriority, count: int = 0, parent=None):
        """
        Initialize priority group header
        
        Args:
            priority: Priority level
            count: Number of downloads in group
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.priority = priority
        self.count = count
        self.is_collapsed = False
        
        # Get colors
        self.colors = ColorPalette.get_priority_colors(priority.name)
        self.icon_name = self.ICONS.get(priority, 'fa5s.minus')
        
        self._setup_ui()
        self._apply_styles()
        
        logger.debug(f"✅ PriorityGroupHeader created ({priority.name}, count={count})")
    
    def _setup_ui(self) -> None:
        """Setup UI components"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        
        # Collapse/expand button
        self.collapse_btn = QPushButton()
        self.collapse_btn.setIcon(_qta_cached('fa5s.chevron-down', color='white'))
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        layout.addWidget(self.collapse_btn)
        
        # Priority icon
        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_label.setPixmap(_qta_cached(self.icon_name, color='white').pixmap(20, 20))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)
        
        # Priority name (UPPERCASE, bold)
        self.name_label = QLabel(self.priority.name.upper())
        self.name_label.setStyleSheet("""
            QLabel {
                font-size: 17px;
                font-weight: 700;
                color: #ffffff;
                letter-spacing: 1.0px;
            }
        """)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.name_label)

        layout.addStretch()

        # Count badge
        self.count_label = QLabel(str(self.count))
        self.count_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: 600;
                color: #ffffff;
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                padding: 5px 12px;
                border-radius: 12px;
                min-width: 48px;
            }
        """)
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setFixedWidth(60)
        layout.addWidget(self.count_label)
    
    def _apply_styles(self) -> None:
        """Apply gradient background and styling"""
        self.setStyleSheet(f"""
            PriorityGroupHeader {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e293b,
                    stop:1 #0f172a
                );
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-bottom: 2px solid {self.colors['border']};
                border-left: 4px solid {self.colors['border']};
                border-radius: 10px;
                margin: 6px 6px 2px 6px;
            }}
        """)
        
        self.setMinimumHeight(56)
    
    def _toggle_collapse(self) -> None:
        """Toggle collapse state with animation"""
        self.is_collapsed = not self.is_collapsed
        
        # Update icon with animation
        icon_name = 'fa5s.chevron-up' if self.is_collapsed else 'fa5s.chevron-down'
        self.collapse_btn.setIcon(_qta_cached(icon_name, color='white'))
        
        # Emit signal
        self.collapsed_changed.emit(self.priority.name, self.is_collapsed)
        
        logger.debug(f"{'▲' if self.is_collapsed else '▼'} {self.priority.name} group")
    
    def update_count(self, new_count: int) -> None:
        """
        Update count badge
        
        Args:
            new_count: New count value
        """
        self.count = new_count
        self.count_label.setText(str(new_count))
