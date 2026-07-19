# -*- coding: utf-8 -*-
"""Self-contained QPainter charts + summary cards for the Admission dashboard.

Deliberately independent of the storage-dashboard chart widgets in
``widget.py`` so the admission feature is fully additive and cannot be broken
by changes to the storage charts' row-key contracts. Pure QPainter — no
third-party charting dependency, works in the frozen build.

All widgets are theme-able via :meth:`set_palette` and render Persian/RTL
labels correctly. They never do I/O and are cheap to repaint.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

# Vibrant, colour-blind-friendly-ish categorical palette.
_SERIES_COLORS = [
    "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
]

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(text: str) -> str:
    return str(text).translate(_PERSIAN_DIGITS)


def format_int(n: int, persian: bool = True) -> str:
    """Group thousands and (optionally) convert to Persian digits."""
    try:
        s = f"{int(round(float(n))):,}"
    except Exception:
        s = str(n)
    return to_persian_digits(s) if persian else s


def format_rial(n: int, persian: bool = True) -> str:
    return format_int(n, persian) + (" ریال" if persian else " Rial")


class _BaseChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []
        self._bg = QColor("#0f1624")
        self._grid = QColor("#23314a")
        self._text = QColor("#eaf2ff")
        self._muted = QColor("#9cb6d6")
        self.setMinimumHeight(240)
        self.setMouseTracking(True)

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = list(rows or [])
        self.update()

    def set_palette(self, bg: str, grid: str, text: str, muted: str) -> None:
        self._bg = QColor(bg)
        self._grid = QColor(grid)
        self._text = QColor(text)
        self._muted = QColor(muted)
        self.update()

    def _empty(self, p: QPainter, msg: str) -> None:
        p.setPen(self._muted)
        p.drawText(self.rect(), Qt.AlignCenter, msg)


class PersianBarChart(_BaseChart):
    """Vertical bar chart — patient count per modality (Persian labels)."""

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self._bg)
        self._bar_rects: List[Any] = []
        if not self._rows:
            self._empty(p, "داده‌ای برای نمایش وجود ندارد")
            return

        r = self.rect().adjusted(14, 16, -14, -34)
        n = len(self._rows)
        max_val = max(1, max(int(x.get("count", 0)) for x in self._rows))
        gap = 12
        bar_w = max(22, int((r.width() - gap * (n - 1)) / max(1, n)))

        for i, row in enumerate(self._rows):
            x = r.left() + i * (bar_w + gap)
            value = int(row.get("count", 0))
            h = int((value / max_val) * (r.height() - 30))
            top = r.bottom() - h
            color = QColor(_SERIES_COLORS[i % len(_SERIES_COLORS)])
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, top, bar_w, h, 6, 6)
            self._bar_rects.append((QRect(x, top, bar_w, h), row))

            p.setPen(self._text)
            p.drawText(x - 6, top - 18, bar_w + 12, 16, Qt.AlignCenter, to_persian_digits(str(value)))
            p.setPen(self._muted)
            label = str(row.get("label", ""))
            if len(label) > 12:
                label = label[:11] + "…"
            p.drawText(x - 10, r.bottom() + 4, bar_w + 20, 26, Qt.AlignCenter | Qt.TextWordWrap, label)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        for rect, row in getattr(self, "_bar_rects", []):
            if rect.contains(pt):
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{row.get('label','')}\nتعداد: {to_persian_digits(str(int(row.get('count',0))))}",
                )
                return super().mouseMoveEvent(event)
        QToolTip.hideText()
        return super().mouseMoveEvent(event)


class PersianLineChart(_BaseChart):
    """Line chart — admissions per day over the selected window."""

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self._bg)
        self._points: List[Any] = []
        r = self.rect().adjusted(14, 18, -14, -26)

        if len(self._rows) < 2:
            self._empty(p, "برای نمودار روند، بازهٔ بزرگ‌تری انتخاب کنید")
            return

        max_val = max(1, max(int(x.get("count", 0)) for x in self._rows))
        p.setPen(QPen(self._grid, 1))
        for i in range(5):
            y = r.top() + int((i / 4) * r.height())
            p.drawLine(r.left(), y, r.right(), y)

        pts: List[QPointF] = []
        n = len(self._rows)
        for i, row in enumerate(self._rows):
            x = r.left() + (i / (n - 1)) * r.width()
            v = int(row.get("count", 0))
            y = r.bottom() - (v / max_val) * r.height()
            pt = QPointF(x, y)
            pts.append(pt)
            self._points.append((pt, row))

        p.setPen(QPen(QColor("#40c4ff"), 3))
        p.drawPolyline(QPolygonF(pts))
        p.setPen(QPen(QColor("#ffd166"), 2))
        p.setBrush(QColor("#ffd166"))
        for pt in pts:
            p.drawEllipse(pt, 3, 3)

        p.setPen(self._muted)
        p.drawText(r.adjusted(0, 0, 0, -r.height() + 16), Qt.AlignLeft | Qt.AlignTop, "روند پذیرش روزانه")
        p.drawText(
            r.adjusted(0, r.height() - 18, 0, 0),
            Qt.AlignRight | Qt.AlignBottom,
            to_persian_digits(str(self._rows[-1].get("date", ""))),
        )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pts = getattr(self, "_points", [])
        if not pts:
            return super().mouseMoveEvent(event)
        pos = event.position()
        nearest, nd = None, 9999.0
        for point, row in pts:
            d = ((point.x() - pos.x()) ** 2 + (point.y() - pos.y()) ** 2) ** 0.5
            if d < nd:
                nd, nearest = d, (point, row)
        if nearest and nd <= 18:
            row = nearest[1]
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"تاریخ: {to_persian_digits(str(row.get('date','')))}\n"
                f"پذیرش: {to_persian_digits(str(int(row.get('count',0))))}",
            )
        else:
            QToolTip.hideText()
        return super().mouseMoveEvent(event)


class PersianDonutChart(_BaseChart):
    """Donut chart with side legend — modality or insurance distribution."""

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self._bg)
        self._segments: List[Dict[str, Any]] = []
        self._pie_rect = None
        if not self._rows:
            self._empty(p, "داده‌ای برای نمایش وجود ندارد")
            return

        area = self.rect().adjusted(12, 12, -12, -12)
        legend_w = min(190, int(area.width() * 0.42))
        pie_area = QRect(area.left(), area.top(), area.width() - legend_w, area.height())
        size = min(pie_area.width(), pie_area.height()) - 20
        size = max(60, size)
        pie_rect = QRect(0, 0, size, size)
        pie_rect.moveCenter(pie_area.center())
        self._pie_rect = pie_rect

        total = max(1, sum(int(r.get("count", 0)) for r in self._rows))
        start_qt = 90 * 16
        start_deg = 0.0
        for idx, row in enumerate(self._rows):
            count = int(row.get("count", 0))
            span = int((count / total) * 360 * 16)
            span_deg = (count / total) * 360.0
            color = QColor(_SERIES_COLORS[idx % len(_SERIES_COLORS)])
            p.setBrush(color)
            p.setPen(QPen(self._bg, 2))
            p.drawPie(pie_rect, -start_qt, -span)
            self._segments.append({"start": start_deg, "end": start_deg + span_deg, "row": row})
            start_qt += span
            start_deg += span_deg

        hole = pie_rect.adjusted(44, 44, -44, -44)
        p.setBrush(self._bg)
        p.setPen(Qt.NoPen)
        p.drawEllipse(hole)
        p.setPen(self._text)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.drawText(hole, Qt.AlignCenter, f"{to_persian_digits(str(total))}\nمجموع")
        p.setFont(self.font())

        # Legend
        lx = pie_area.right() + 12
        ly = area.top() + 6
        for idx, row in enumerate(self._rows[:10]):
            color = QColor(_SERIES_COLORS[idx % len(_SERIES_COLORS)])
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(lx, ly + 2, 12, 12, 3, 3)
            p.setPen(self._text)
            label = str(row.get("label", ""))
            if len(label) > 16:
                label = label[:15] + "…"
            pct_txt = to_persian_digits("%.1f" % float(row.get("percent", 0.0)))
            p.drawText(
                lx + 18, ly, legend_w - 30, 16, Qt.AlignLeft | Qt.AlignVCenter,
                f"{label}  {pct_txt}٪",
            )
            ly += 22

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        segs = getattr(self, "_segments", [])
        pr = getattr(self, "_pie_rect", None)
        if not segs or pr is None or not pr.contains(event.position().toPoint()):
            QToolTip.hideText()
            return super().mouseMoveEvent(event)
        import math
        c = pr.center()
        dx = event.position().x() - c.x()
        dy = event.position().y() - c.y()
        angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
        for seg in segs:
            if seg["start"] <= angle <= seg["end"]:
                row = seg["row"]
                pct_txt = to_persian_digits("%.1f" % float(row.get("percent", 0.0)))
                count_txt = to_persian_digits(str(int(row.get("count", 0))))
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{row.get('label','')}\n"
                    f"تعداد: {count_txt}\n"
                    f"سهم: {pct_txt}٪",
                )
                break
        return super().mouseMoveEvent(event)


class SummaryCard(QFrame):
    """Colored KPI card: a big value with a Persian caption and accent bar."""

    def __init__(self, title: str, accent: str = "#4e79a7", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._accent = accent
        self.setObjectName("admission_kpi_card")
        # Min size + expanding width so cards grow/shrink with the window and
        # never crush their contents; height grows if the title wraps.
        self.setMinimumHeight(88)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.value_label = QLabel("۰")
        self.value_label.setObjectName("admission_kpi_value")
        # +4 (not +6) so long Rial figures fit inside a narrow card; the full
        # value is always available via tooltip (set in set_value).
        vf = QFont(self.font())
        vf.setPointSize(vf.pointSize() + 4)
        vf.setBold(True)
        self.value_label.setFont(vf)
        self.value_label.setWordWrap(False)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("admission_kpi_title")
        self.title_label.setWordWrap(True)  # long Persian captions wrap, never clip
        self.sub_label = QLabel("")
        self.sub_label.setObjectName("admission_kpi_sub")
        self.sub_label.setWordWrap(True)
        lay.addWidget(self.value_label)
        lay.addWidget(self.title_label)
        lay.addWidget(self.sub_label)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#admission_kpi_card {{
                background: #131c2b;
                border: 1px solid #22304a;
                border-right: 4px solid {self._accent};
                border-radius: 10px;
            }}
            QLabel#admission_kpi_value {{ color: #ffffff; }}
            QLabel#admission_kpi_title {{ color: #9cb6d6; }}
            QLabel#admission_kpi_sub {{ color: #6f88ab; font-size: 11px; }}
            """
        )

    def set_value(self, value: str, subtitle: str = "") -> None:
        self.value_label.setText(value)
        self.sub_label.setText(subtitle)
        self.sub_label.setVisible(bool(subtitle))
        # Full value/label always readable on hover even if the card is narrow.
        tip = self.title_label.text()
        tip = f"{tip}: {value}" if tip else value
        if subtitle:
            tip = f"{tip}\n{subtitle}"
        self.setToolTip(tip)
        self.value_label.setToolTip(value)


# End of admission_charts — self-contained QPainter widgets, no I/O.
