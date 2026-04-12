"""
SliceTickSlider — custom QSlider that paints per-slice tick marks.
Extracted from patient_widget_viewer_controller.py to allow clean import
from _vc_layout.py without circular dependency (v2.2.9.0).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSlider


class SliceTickSlider(QSlider):
    """
    Custom QSlider that paints per-slice tick marks along the groove.
    • Non-current ticks: thin, semi-transparent.
    • Current-position tick: wider, bright accent colour.
    All painting is done *after* the base QSlider paint so the handle
    is always drawn on top.
    """

    def __init__(self, orientation=Qt.Vertical, parent=None):
        super().__init__(orientation, parent)
        # Theme: muted purple-blue blend
        self._theme_r, self._theme_g, self._theme_b = 110, 90, 210
        self._unvisited_color = QColor(140, 140, 160, 80)   # gray for future slices
        self._current_tick_color = QColor(self._theme_r, self._theme_g, self._theme_b, 240)

    # ------------------------------------------------------------------ #
    def paintEvent(self, event):
        # Let Qt draw the normal slider first (groove + handle)
        super().paintEvent(event)

        total = self.maximum() - self.minimum()
        if total <= 0:
            return  # nothing to draw

        painter = QPainter(self)
        # Antialiasing OFF for tick lines so they stay crisp dashes, not blobs
        painter.setRenderHint(QPainter.Antialiasing, False)

        # Usable range (exclude top/bottom padding of 8 px matches stylesheet)
        pad = 8
        groove_top = pad
        groove_bottom = self.height() - pad
        groove_len = groove_bottom - groove_top
        if groove_len <= 0:
            painter.end()
            return

        # Decide max ticks to draw so we don't paint thousands of lines
        max_ticks = min(total + 1, 200)
        step = max(1, total // max_ticks)

        cur_val = self.value()
        inverted = self.invertedAppearance()

        tick_half_w = 4  # dash extends 4px each side of centre (clear line shape)
        cx = self.width() // 2

        # --- draw non-current ticks as flat dashes (never circles) ---
        for i in range(self.minimum(), self.maximum() + 1, step):
            if i == cur_val:
                continue  # draw current separately as dot

            frac = (i - self.minimum()) / total
            if inverted:
                y = int(groove_top + frac * groove_len)
            else:
                y = int(groove_bottom - frac * groove_len)

            passed = (i < cur_val)  # slices the user has scrolled past

            if passed:
                # Fade: slices close to current are vivid, distant ones fade out
                distance = cur_val - i  # always > 0
                alpha = max(40, int(200 - distance * 2.7))
                color = QColor(self._theme_r, self._theme_g, self._theme_b, alpha)
            else:
                # Future / unvisited slices — neutral gray
                color = self._unvisited_color

            pen = QPen(color, 1.0)
            pen.setCapStyle(Qt.FlatCap)  # flat ends → crisp dash, not rounded blob
            painter.setPen(pen)
            painter.drawLine(cx - tick_half_w, y, cx + tick_half_w, y)

        # --- current-position indicator: single filled circle / dot ---
        painter.setRenderHint(QPainter.Antialiasing, True)  # smooth circle only
        frac_cur = (cur_val - self.minimum()) / total
        if inverted:
            y_cur = int(groove_top + frac_cur * groove_len)
        else:
            y_cur = int(groove_bottom - frac_cur * groove_len)

        dot_radius = 5  # 10 px diameter — easy to see and grab
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._current_tick_color)
        painter.drawEllipse(cx - dot_radius, y_cur - dot_radius,
                            dot_radius * 2, dot_radius * 2)

        painter.end()
