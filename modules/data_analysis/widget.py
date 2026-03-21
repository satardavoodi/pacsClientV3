from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .service import DataAnalysisService


class DonutChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._colors = [
            QColor("#ff6b6b"), QColor("#4ecdc4"), QColor("#ffe66d"), QColor("#5da9e9"),
            QColor("#b084f5"), QColor("#ff9f1c"), QColor("#2ec4b6"), QColor("#e71d36"),
        ]
        self._segments: list[dict[str, Any]] = []
        self._hole_rect = None
        self._pie_rect = None
        self.setMinimumHeight(250)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._segments = []
        self._hole_rect = None
        self._pie_rect = None

        if not self._rows:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "No modality data")
            return

        rect = self.rect().adjusted(16, 16, -16, -16)
        size = min(rect.width(), rect.height()) - 30
        cx = rect.center().x()
        cy = rect.center().y()
        pie_rect = rect
        pie_rect.setWidth(size)
        pie_rect.setHeight(size)
        pie_rect.moveCenter(rect.center())

        total = max(1, sum(int(r.get("count", 0)) for r in self._rows))
        start_qt = 90 * 16
        start_deg_clockwise = 0.0

        for idx, row in enumerate(self._rows):
            count = int(row.get("count", 0))
            span = int((count / total) * 360 * 16)
            span_deg = (count / total) * 360.0
            color = self._colors[idx % len(self._colors)]
            p.setBrush(color)
            p.setPen(QPen(QColor("#0f1520"), 2))
            p.drawPie(pie_rect, -start_qt, -span)
            self._segments.append(
                {
                    "start": start_deg_clockwise,
                    "end": start_deg_clockwise + span_deg,
                    "row": row,
                }
            )
            start_qt += span
            start_deg_clockwise += span_deg

        hole = pie_rect.adjusted(46, 46, -46, -46)
        self._pie_rect = pie_rect
        self._hole_rect = hole
        p.setBrush(QColor("#0f1624"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(hole)

        p.setPen(QColor("#eaf2ff"))
        p.drawText(hole, Qt.AlignCenter, f"{total}\nStudies")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._segments or self._pie_rect is None or self._hole_rect is None:
            return super().mouseMoveEvent(event)

        pt = event.position().toPoint()
        if not self._pie_rect.contains(pt):
            QToolTip.hideText()
            return super().mouseMoveEvent(event)
        if self._hole_rect.contains(pt):
            QToolTip.showText(event.globalPosition().toPoint(), "Total studies in selected scope")
            return super().mouseMoveEvent(event)

        center = self._pie_rect.center()
        dx = pt.x() - center.x()
        dy = pt.y() - center.y()

        # Convert to clockwise angle from top (0 at 12 o'clock)
        import math
        angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
        for seg in self._segments:
            if seg["start"] <= angle <= seg["end"]:
                row = seg["row"]
                text = (
                    f"{row.get('modality', 'Unknown')}\n"
                    f"Studies: {int(row.get('count', 0))}\n"
                    f"Share: {float(row.get('percent', 0.0)):.1f}%"
                )
                QToolTip.showText(event.globalPosition().toPoint(), text)
                break
        return super().mouseMoveEvent(event)


class LineTrendWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._points: list[tuple[QPointF, dict[str, Any]]] = []
        self.setMinimumHeight(250)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(12, 18, -12, -20)
        self._points = []

        p.fillRect(self.rect(), QColor("#0f1624"))

        if len(self._rows) < 2:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "Not enough trend points")
            return

        max_val = max(int(x.get("count", 0)) for x in self._rows)
        max_val = max(1, max_val)

        p.setPen(QPen(QColor("#23314a"), 1))
        for i in range(5):
            y = r.top() + int((i / 4) * r.height())
            p.drawLine(r.left(), y, r.right(), y)

        points: list[QPointF] = []
        n = len(self._rows)
        for i, row in enumerate(self._rows):
            x = r.left() + (i / (n - 1)) * r.width()
            v = int(row.get("count", 0))
            y = r.bottom() - (v / max_val) * r.height()
            pt = QPointF(x, y)
            points.append(pt)
            self._points.append((pt, row))

        p.setPen(QPen(QColor("#40c4ff"), 3))
        p.drawPolyline(QPolygonF(points))

        p.setPen(QPen(QColor("#ffd166"), 2))
        p.setBrush(QColor("#ffd166"))
        for pt in points:
            p.drawEllipse(pt, 3, 3)

        p.setPen(QColor("#9cb6d6"))
        p.drawText(r.adjusted(0, 0, 0, -r.height() + 16), Qt.AlignLeft | Qt.AlignTop, "Study Trend")
        p.drawText(r.adjusted(0, r.height() - 18, 0, 0), Qt.AlignRight | Qt.AlignBottom, self._rows[-1].get("date", ""))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._points:
            return super().mouseMoveEvent(event)
        pt = event.position()
        nearest = None
        nearest_dist = 9999.0
        for point, row in self._points:
            dx = point.x() - pt.x()
            dy = point.y() - pt.y()
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = (point, row)
        if nearest and nearest_dist <= 16:
            row = nearest[1]
            text = f"Date: {row.get('date', '')}\nStudies: {int(row.get('count', 0))}"
            QToolTip.showText(event.globalPosition().toPoint(), text)
        else:
            QToolTip.hideText()
        return super().mouseMoveEvent(event)


class StatusBarChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._palette = [QColor("#a0e7e5"), QColor("#b4f8c8"), QColor("#fbe7c6"), QColor("#ffaebc"), QColor("#cdb4db")]
        self._bar_rects: list[tuple[Any, dict[str, Any]]] = []
        self.setMinimumHeight(220)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0f1624"))
        self._bar_rects = []

        if not self._rows:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "No report status data")
            return

        r = self.rect().adjusted(16, 16, -16, -26)
        n = len(self._rows)
        max_val = max(1, max(int(x.get("count", 0)) for x in self._rows))
        gap = 10
        bar_w = max(24, int((r.width() - gap * (n - 1)) / max(1, n)))

        for i, row in enumerate(self._rows):
            x = r.left() + i * (bar_w + gap)
            value = int(row.get("count", 0))
            h = int((value / max_val) * (r.height() - 34))
            top = r.bottom() - h
            color = self._palette[i % len(self._palette)]
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, top, bar_w, h, 6, 6)
            self._bar_rects.append((QRect(x, top, bar_w, h), row))

            p.setPen(QColor("#eaf2ff"))
            p.drawText(x, top - 4, bar_w, 14, Qt.AlignCenter, str(value))
            p.setPen(QColor("#9cb6d6"))
            p.drawText(x - 8, r.bottom() + 4, bar_w + 16, 18, Qt.AlignCenter, str(row.get("status", "")))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        for bar_rect, row in self._bar_rects:
            if bar_rect.contains(pt):
                text = f"Status: {row.get('status', '')}\nCount: {int(row.get('count', 0))}"
                QToolTip.showText(event.globalPosition().toPoint(), text)
                return super().mouseMoveEvent(event)
        QToolTip.hideText()
        return super().mouseMoveEvent(event)


class ModuleActivityChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._regions: list[tuple[QRect, dict[str, Any]]] = []
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows[:8]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        self._regions = []
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0f1624"))
        if not self._rows:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "No module usage data")
            return

        r = self.rect().adjusted(16, 16, -16, -12)
        max_val = max(1, max(int(x.get("count", 0)) for x in self._rows))
        row_h = max(22, int((r.height() - 12) / max(1, len(self._rows))))
        y = r.top()
        palette = [QColor("#5ad1ff"), QColor("#ffd166"), QColor("#7ae582"), QColor("#ff8fab")]
        for i, row in enumerate(self._rows):
            label = str(row.get("module", ""))
            value = int(row.get("count", 0))
            bar_w = int((value / max_val) * (r.width() * 0.62))
            bar_rect = QRect(r.left() + 150, y + 4, max(2, bar_w), row_h - 8)
            self._regions.append((bar_rect, row))

            p.setPen(QColor("#c9ddf7"))
            p.drawText(QRect(r.left(), y, 145, row_h), Qt.AlignVCenter | Qt.AlignLeft, label[:20])

            p.setBrush(palette[i % len(palette)])
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bar_rect, 6, 6)

            p.setPen(QColor("#e8f1ff"))
            p.drawText(QRect(bar_rect.right() + 8, y, 80, row_h), Qt.AlignVCenter | Qt.AlignLeft, f"{value:,}")
            y += row_h

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        for rect, row in self._regions:
            if rect.contains(pt):
                text = (
                    f"{row.get('module', '')}\n"
                    f"Activity Count: {int(row.get('count', 0))}\n"
                    "Represents module/job usage volume in current scope."
                )
                QToolTip.showText(event.globalPosition().toPoint(), text)
                return super().mouseMoveEvent(event)
        QToolTip.hideText()
        return super().mouseMoveEvent(event)


class DriveUsageChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._regions: list[tuple[QRect, dict[str, Any]]] = []
        self.setMinimumHeight(250)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        self._regions = []
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0f1624"))
        if not self._rows:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "No drive usage data")
            return

        r = self.rect().adjusted(16, 16, -16, -12)
        row_h = max(36, int((r.height() - 8) / max(1, len(self._rows))))
        y = r.top()
        for row in self._rows:
            drive = str(row.get("drive", ""))
            used_pct = float(row.get("used_percent", 0.0))
            bar_bg = QRect(r.left() + 120, y + 16, r.width() - 140, 14)
            bar_fg = QRect(bar_bg.left(), bar_bg.top(), int(bar_bg.width() * (used_pct / 100.0)), bar_bg.height())
            color = QColor("#22c55e") if used_pct < 70 else QColor("#f59e0b") if used_pct < 85 else QColor("#ef4444")
            self._regions.append((bar_bg, row))

            p.setPen(QColor("#d4e5ff"))
            p.drawText(QRect(r.left(), y, 110, 34), Qt.AlignVCenter | Qt.AlignLeft, drive)
            p.setPen(QColor("#7f9cc0"))
            p.drawText(QRect(r.left() + 120, y, 180, 14), Qt.AlignVCenter | Qt.AlignLeft, f"{used_pct:.1f}% used")

            p.setBrush(QColor("#243246"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bar_bg, 7, 7)
            p.setBrush(color)
            p.drawRoundedRect(bar_fg, 7, 7)
            y += row_h

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        for rect, row in self._regions:
            if rect.contains(pt):
                text = (
                    f"Drive: {row.get('drive', '')}\n"
                    f"Used: {float(row.get('used_percent', 0.0)):.1f}%\n"
                    f"Free: {DataAnalysisDashboard._format_bytes_static(int(row.get('free', 0)))}"
                )
                QToolTip.showText(event.globalPosition().toPoint(), text)
                return super().mouseMoveEvent(event)
        QToolTip.hideText()
        return super().mouseMoveEvent(event)


class FolderStorageChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._regions: list[tuple[QRect, dict[str, Any]]] = []
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        self._regions = []
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0f1624"))
        if not self._rows:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "No managed-folder data")
            return

        r = self.rect().adjusted(16, 16, -16, -12)
        max_size = max(1, max(int(x.get("size_bytes", 0)) for x in self._rows))
        row_h = max(30, int((r.height() - 6) / max(1, len(self._rows))))
        y = r.top()
        for i, row in enumerate(self._rows):
            name = str(row.get("name", ""))
            size_b = int(row.get("size_bytes", 0))
            size_text = str(row.get("size_text", "0 B"))
            bar_w = int((size_b / max_size) * (r.width() * 0.62))
            bar_rect = QRect(r.left() + 170, y + 6, max(2, bar_w), row_h - 12)
            color = QColor(["#3b82f6", "#06b6d4", "#10b981", "#f59e0b"][i % 4])
            self._regions.append((bar_rect, row))

            p.setPen(QColor("#d4e5ff"))
            p.drawText(QRect(r.left(), y, 165, row_h), Qt.AlignVCenter | Qt.AlignLeft, name)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bar_rect, 6, 6)
            p.setPen(QColor("#e8f1ff"))
            p.drawText(QRect(bar_rect.right() + 8, y, 120, row_h), Qt.AlignVCenter | Qt.AlignLeft, size_text)
            y += row_h

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        for rect, row in self._regions:
            if rect.contains(pt):
                paths = row.get("paths", []) or []
                text = (
                    f"{row.get('name', '')}\n"
                    f"Size: {row.get('size_text', '')}\n"
                    f"Disk impact: {float(row.get('used_disk_percent', 0.0)):.2f}%\n"
                    f"Path: {paths[0] if paths else '-'}"
                )
                QToolTip.showText(event.globalPosition().toPoint(), text)
                return super().mouseMoveEvent(event)
        QToolTip.hideText()
        return super().mouseMoveEvent(event)


class ServerMixDonutWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._segments: list[dict[str, Any]] = []
        self._pie_rect = None
        self._hole_rect = None
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        self._segments = []
        self._pie_rect = None
        self._hole_rect = None
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0f1624"))
        if not self._rows:
            p.setPen(QColor("#9cb6d6"))
            p.drawText(self.rect(), Qt.AlignCenter, "No server data")
            return

        # Group by source
        grouped: dict[str, int] = {}
        for row in self._rows:
            source = str(row.get("source", "unknown"))
            grouped[source] = grouped.get(source, 0) + 1
        items = [{"source": k, "count": v} for k, v in grouped.items()]
        total = max(1, sum(x["count"] for x in items))

        rect = self.rect().adjusted(16, 16, -16, -16)
        size = min(rect.width(), rect.height()) - 26
        pie_rect = QRect(0, 0, size, size)
        pie_rect.moveCenter(rect.center())
        colors = [QColor("#60a5fa"), QColor("#34d399"), QColor("#fbbf24"), QColor("#f87171")]
        start_qt = 90 * 16
        start_deg = 0.0
        for i, item in enumerate(items):
            span_deg = (item["count"] / total) * 360.0
            span_qt = int(span_deg * 16)
            p.setBrush(colors[i % len(colors)])
            p.setPen(QPen(QColor("#0f1520"), 2))
            p.drawPie(pie_rect, -start_qt, -span_qt)
            self._segments.append({"start": start_deg, "end": start_deg + span_deg, "item": item})
            start_qt += span_qt
            start_deg += span_deg

        hole = pie_rect.adjusted(42, 42, -42, -42)
        self._pie_rect = pie_rect
        self._hole_rect = hole
        p.setBrush(QColor("#0f1624"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(hole)
        p.setPen(QColor("#eaf2ff"))
        p.drawText(hole, Qt.AlignCenter, f"{len(self._rows)}\nServers")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._segments or self._pie_rect is None or self._hole_rect is None:
            return super().mouseMoveEvent(event)
        pt = event.position().toPoint()
        if not self._pie_rect.contains(pt):
            QToolTip.hideText()
            return super().mouseMoveEvent(event)
        if self._hole_rect.contains(pt):
            QToolTip.showText(event.globalPosition().toPoint(), "Total configured servers")
            return super().mouseMoveEvent(event)
        import math
        center = self._pie_rect.center()
        angle = (math.degrees(math.atan2(pt.y() - center.y(), pt.x() - center.x())) + 90.0) % 360.0
        for seg in self._segments:
            if seg["start"] <= angle <= seg["end"]:
                item = seg["item"]
                text = f"Source: {item.get('source', '')}\nServers: {int(item.get('count', 0))}"
                QToolTip.showText(event.globalPosition().toPoint(), text)
                break
        return super().mouseMoveEvent(event)


class DataAnalysisDashboard(QWidget):
    """Colorful and interactive dashboard for operational analytics."""

    def __init__(self, parent: QWidget | None = None, auth_user: dict[str, Any] | None = None):
        super().__init__(parent)
        self._auth_user = auth_user or {}
        self._service = DataAnalysisService()
        self._snapshot: dict[str, Any] = {}
        self._kpi_labels: dict[str, QLabel] = {}
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(30000)
        self._auto_refresh_timer.timeout.connect(self.refresh_data)

        self._build_ui()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        hero = QFrame(self)
        hero.setObjectName("hero")
        hero_lay = QHBoxLayout(hero)
        hero_lay.setContentsMargins(14, 12, 14, 12)

        title_col = QVBoxLayout()
        self.title_label = QLabel("Data Analysis Command Center")
        self.subtitle_label = QLabel("Live dashboards for users, studies, modules, servers and storage")
        self.account_label = QLabel("Account: -")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        title_col.addWidget(self.account_label)

        controls = QVBoxLayout()
        controls.setAlignment(Qt.AlignTop)
        top_row = QHBoxLayout()
        self.generated_at_label = QLabel("Last update: -")
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        top_row.addWidget(self.generated_at_label)
        top_row.addWidget(self.refresh_btn)

        filter_row = QHBoxLayout()
        self.date_filter = QComboBox()
        self.date_filter.currentIndexChanged.connect(self._on_data_filter_changed)
        self.server_filter = QComboBox()
        self.server_filter.currentIndexChanged.connect(self._on_data_filter_changed)
        self.user_filter = QComboBox()
        self.user_filter.currentIndexChanged.connect(self._on_data_filter_changed)
        self.modality_filter = QComboBox()
        self.modality_filter.currentIndexChanged.connect(self._apply_filters)
        self.auto_refresh_checkbox = QCheckBox("Auto refresh")
        self.auto_refresh_checkbox.toggled.connect(self._toggle_auto_refresh)
        filter_row.addWidget(QLabel("Date:"))
        filter_row.addWidget(self.date_filter)
        filter_row.addWidget(QLabel("Server:"))
        filter_row.addWidget(self.server_filter)
        filter_row.addWidget(QLabel("User:"))
        filter_row.addWidget(self.user_filter)
        filter_row.addWidget(QLabel("Modality:"))
        filter_row.addWidget(self.modality_filter)
        filter_row.addWidget(self.auto_refresh_checkbox)

        controls.addLayout(top_row)
        controls.addLayout(filter_row)

        hero_lay.addLayout(title_col, 1)
        hero_lay.addLayout(controls)

        root.addWidget(hero)

        kpi_frame = QFrame(self)
        kpi_frame.setObjectName("kpi_frame")
        self.kpi_grid = QGridLayout(kpi_frame)
        self.kpi_grid.setContentsMargins(10, 10, 10, 10)
        self.kpi_grid.setHorizontalSpacing(10)
        self.kpi_grid.setVerticalSpacing(10)
        root.addWidget(kpi_frame)
        self._build_kpis()

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        self.overview_tab = QWidget()
        ov = QVBoxLayout(self.overview_tab)
        ov.setContentsMargins(6, 6, 6, 6)
        ov.setSpacing(8)

        split = QSplitter(Qt.Horizontal)
        self.donut_chart = DonutChartWidget()
        self.trend_chart = LineTrendWidget()
        split.addWidget(self._section("Modality Share (Donut)", self.donut_chart))
        split.addWidget(self._section("Daily Study Trend (Line)", self.trend_chart))
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        ov.addWidget(split)

        self.status_chart = StatusBarChartWidget()
        ov.addWidget(self._section("Report Status (Bar)", self.status_chart))

        self.tabs.addTab(self.overview_tab, "Overview")

        self.studies_tab = QWidget()
        st = QVBoxLayout(self.studies_tab)
        st.setContentsMargins(6, 6, 6, 6)
        st.setSpacing(8)

        self.modality_table = self._create_table(["Modality", "Studies", "Share"])
        st.addWidget(self._section("Patients by Modality", self.modality_table))

        self.recent_studies_table = self._create_table(
            ["Patient", "Study UID", "Modality", "Date", "Images", "Report Status"]
        )
        st.addWidget(self._section("Recent Studies", self.recent_studies_table), 1)

        self.tabs.addTab(self.studies_tab, "Studies")

        self.ops_tab = QWidget()
        op = QVBoxLayout(self.ops_tab)
        op.setContentsMargins(6, 6, 6, 6)
        op.setSpacing(8)

        op_top = QSplitter(Qt.Horizontal)
        self.module_activity_chart = ModuleActivityChartWidget()
        self.drive_usage_chart = DriveUsageChartWidget()
        op_top.addWidget(self._section("Module Activity (Horizontal Bars)", self.module_activity_chart))
        op_top.addWidget(self._section("Drive Usage (Progress Graph)", self.drive_usage_chart))
        op_top.setStretchFactor(0, 1)
        op_top.setStretchFactor(1, 1)
        op.addWidget(op_top)

        op_bottom = QSplitter(Qt.Horizontal)
        self.folder_storage_chart = FolderStorageChartWidget()
        self.server_mix_chart = ServerMixDonutWidget()
        op_bottom.addWidget(self._section("Local Storage & Database Breakdown", self.folder_storage_chart))
        op_bottom.addWidget(self._section("Server Mix (Donut)", self.server_mix_chart))
        op_bottom.setStretchFactor(0, 1)
        op_bottom.setStretchFactor(1, 1)
        op.addWidget(op_bottom)

        self.storage_footprint_chart = FolderStorageChartWidget()
        op.addWidget(self._section("Storage Footprint by Section", self.storage_footprint_chart))

        self.tabs.addTab(self.ops_tab, "Operations")

        self.apply_theme()

    def _build_kpis(self) -> None:
        kpi_tooltips = {
            "patients": "Unique patients based on filtered studies.",
            "studies": "Number of studies after applying Date/Server filters.",
            "series": "Total imaging series in filtered studies.",
            "instances": "Total DICOM images in filtered studies.",
            "download_jobs": "All tracked download jobs.",
            "pending_reports": "Studies waiting for finalized report.",
            "echomind_sessions": "Total EchoMind sessions.",
            "total_api_tokens": "API token usage for selected user filter.",
        }
        kpis = [
            ("patients", "Patients"),
            ("studies", "Studies"),
            ("series", "Series"),
            ("instances", "Images"),
            ("download_jobs", "Downloads"),
            ("pending_reports", "Pending Reports"),
            ("echomind_sessions", "EchoMind Sessions"),
            ("total_api_tokens", "API Tokens"),
        ]
        for i, (key, title) in enumerate(kpis):
            card = QFrame(self)
            card.setObjectName("kpi_card")
            lay = QVBoxLayout(card)
            t = QLabel(title)
            t.setObjectName("kpi_title")
            v = QLabel("0")
            v.setObjectName("kpi_value")
            tip = kpi_tooltips.get(key, title)
            t.setToolTip(tip)
            v.setToolTip(tip)
            lay.addWidget(t)
            lay.addWidget(v)
            self.kpi_grid.addWidget(card, i // 4, i % 4)
            self._kpi_labels[key] = v

    def _section(self, title: str, body: QWidget) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("section")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("section_title")
        lay.addWidget(title_lbl)
        lay.addWidget(body)
        return frame

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        return table

    def _toggle_auto_refresh(self, enabled: bool) -> None:
        if enabled:
            self._auto_refresh_timer.start()
        else:
            self._auto_refresh_timer.stop()

    def refresh_data(self) -> None:
        self._snapshot = self._service.build_snapshot(self._auth_user, self._current_service_filters())
        self._populate_filter_options()
        self._apply_filters()

    def _on_data_filter_changed(self) -> None:
        self.refresh_data()

    def _current_service_filters(self) -> dict[str, str]:
        return {
            "date_range": self.date_filter.currentText().strip() or "All Time",
            "server": self.server_filter.currentText().strip() or "All Servers",
            "user": self.user_filter.currentText().strip() or "All Users",
        }

    def _populate_filter_options(self) -> None:
        options = self._snapshot.get("filter_options", {}) or {}

        current_date = self.date_filter.currentText()
        current_server = self.server_filter.currentText()
        current_user = self.user_filter.currentText()
        current_modality = self.modality_filter.currentText()

        self.date_filter.blockSignals(True)
        self.server_filter.blockSignals(True)
        self.user_filter.blockSignals(True)
        self.modality_filter.blockSignals(True)

        self.date_filter.clear()
        for value in options.get("date_ranges", ["All Time"]):
            self.date_filter.addItem(str(value))
        idx = self.date_filter.findText(current_date)
        self.date_filter.setCurrentIndex(idx if idx >= 0 else 0)

        self.server_filter.clear()
        for value in options.get("servers", ["All Servers"]):
            self.server_filter.addItem(str(value))
        idx = self.server_filter.findText(current_server)
        self.server_filter.setCurrentIndex(idx if idx >= 0 else 0)

        self.user_filter.clear()
        for value in options.get("users", ["All Users"]):
            self.user_filter.addItem(str(value))
        idx = self.user_filter.findText(current_user)
        self.user_filter.setCurrentIndex(idx if idx >= 0 else 0)

        self.modality_filter.clear()
        self.modality_filter.addItem("All")
        for row in self._snapshot.get("modalities", []):
            self.modality_filter.addItem(str(row.get("modality", "")))
        idx = self.modality_filter.findText(current_modality)
        self.modality_filter.setCurrentIndex(idx if idx >= 0 else 0)

        self.date_filter.blockSignals(False)
        self.server_filter.blockSignals(False)
        self.user_filter.blockSignals(False)
        self.modality_filter.blockSignals(False)

    def _apply_filters(self) -> None:
        selected_modality = self.modality_filter.currentText().strip()
        if not selected_modality:
            selected_modality = "All"

        account = self._snapshot.get("account", {}) or {}
        active = self._snapshot.get("active_filters", {}) or {}
        self.account_label.setText(
            f"Account: {account.get('full_name', '-') }   |   "
            f"Role: {str(account.get('role', '-')).upper()}   |   "
            f"Username: {account.get('username', '-') }   |   "
            f"Date: {active.get('date_range', 'All Time')}   |   "
            f"Server: {active.get('server', 'All Servers')}   |   "
            f"User Filter: {active.get('user', 'All Users')}"
        )
        self.generated_at_label.setText(f"Last update: {self._snapshot.get('generated_at', '-')}")

        totals = self._snapshot.get("totals", {}) or {}
        for key, lbl in self._kpi_labels.items():
            lbl.setText(f"{int(totals.get(key, 0)):,}")

        modalities = self._snapshot.get("modalities", []) or []
        if selected_modality != "All":
            modalities = [m for m in modalities if str(m.get("modality", "")) == selected_modality]

        recent_rows = self._snapshot.get("recent_studies", []) or []
        if selected_modality != "All":
            recent_rows = [r for r in recent_rows if str(r.get("modality", "")) == selected_modality]

        self.donut_chart.set_rows(modalities if modalities else self._snapshot.get("modalities", []))
        self.trend_chart.set_rows(self._snapshot.get("study_trend", []))
        self.status_chart.set_rows(self._snapshot.get("report_status", []))

        self._fill_modality_table(modalities if modalities else self._snapshot.get("modalities", []))
        self._fill_recent_studies_table(recent_rows)
        cleanup = self._snapshot.get("storage_cleanup", {}) or {}
        self.module_activity_chart.set_rows(self._snapshot.get("module_usage", []) or [])
        self.drive_usage_chart.set_rows(cleanup.get("drives", []) or [])
        self.folder_storage_chart.set_rows(cleanup.get("folders", []) or [])
        self.server_mix_chart.set_rows(self._snapshot.get("servers", []) or [])

        storage_rows = self._snapshot.get("storage", []) or []
        footprint_rows: list[dict[str, Any]] = []
        for row in storage_rows:
            size_bytes = int(row.get("size_bytes", 0))
            footprint_rows.append(
                {
                    "name": str(row.get("name", "")),
                    "size_bytes": size_bytes,
                    "size_text": self._format_bytes_static(size_bytes),
                    "used_disk_percent": 0.0,
                    "paths": [str(row.get("path", ""))],
                }
            )
        self.storage_footprint_chart.set_rows(footprint_rows)

    def _fill_modality_table(self, rows: list[dict[str, Any]]) -> None:
        self.modality_table.setSortingEnabled(False)
        self.modality_table.setRowCount(0)
        for row_idx, row in enumerate(rows):
            self.modality_table.insertRow(row_idx)
            self.modality_table.setItem(row_idx, 0, QTableWidgetItem(str(row.get("modality", ""))))
            self.modality_table.setItem(row_idx, 1, QTableWidgetItem(str(int(row.get("count", 0)))))
            bar = QProgressBar(self.modality_table)
            bar.setRange(0, 100)
            bar.setValue(int(float(row.get("percent", 0.0))))
            bar.setFormat(f"{float(row.get('percent', 0.0)):.1f}%")
            self.modality_table.setCellWidget(row_idx, 2, bar)
        self.modality_table.setSortingEnabled(True)

    def _fill_recent_studies_table(self, rows: list[dict[str, Any]]) -> None:
        self.recent_studies_table.setSortingEnabled(False)
        self.recent_studies_table.setRowCount(0)
        for i, row in enumerate(rows):
            self.recent_studies_table.insertRow(i)
            self.recent_studies_table.setItem(i, 0, QTableWidgetItem(str(row.get("patient_name", ""))))
            self.recent_studies_table.setItem(i, 1, QTableWidgetItem(str(row.get("study_uid", ""))))
            self.recent_studies_table.setItem(i, 2, QTableWidgetItem(str(row.get("modality", ""))))
            self.recent_studies_table.setItem(i, 3, QTableWidgetItem(str(row.get("study_date", ""))))
            self.recent_studies_table.setItem(i, 4, QTableWidgetItem(str(int(row.get("images", 0)))))
            self.recent_studies_table.setItem(i, 5, QTableWidgetItem(str(row.get("report_status", ""))))
        self.recent_studies_table.setSortingEnabled(True)

    def _format_bytes(self, size: int) -> str:
        return self._format_bytes_static(size)

    @staticmethod
    def _format_bytes_static(size: int) -> str:
        value = float(size)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                return f"{int(value)} {unit}" if unit == "B" else f"{value:.2f} {unit}"
            value /= 1024.0
        return f"{size} B"

    def apply_theme(self, theme: dict[str, str] | None = None) -> None:
        t = theme or {
            "window_bg": "#090f1a",
            "panel_bg": "#131d2e",
            "panel_alt_bg": "#10192a",
            "window_alt_bg": "#0b1320",
            "border": "#2b3d57",
            "text_primary": "#eaf2ff",
            "text_secondary": "#9cb6d6",
            "accent": "#4cc9f0",
            "accent_hover": "#58d5ff",
            "button_text": "#04121f",
        }

        stylesheet = """
            QWidget {
                background: __WINDOW_BG__;
                color: __TEXT_PRIMARY__;
            }
            QFrame#hero {
                border-radius: 12px;
                border: 1px solid __BORDER__;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 __PANEL_BG__, stop:0.45 #1a2740, stop:1 #2a1f43);
            }
            QFrame#kpi_frame, QFrame#section, QFrame#kpi_card {
                border-radius: 10px;
                border: 1px solid __BORDER__;
                background: __PANEL_BG__;
            }
            QLabel {
                background: transparent;
            }
            QLabel#kpi_title {
                color: __TEXT_SECONDARY__;
                font-size: 10px;
                font-weight: 600;
            }
            QLabel#kpi_value {
                color: #ffffff;
                font-size: 20px;
                font-weight: 800;
            }
            QLabel#section_title {
                color: __TEXT_PRIMARY__;
                font-size: 13px;
                font-weight: 700;
            }
            QTableWidget {
                background: __WINDOW_ALT_BG__;
                alternate-background-color: __PANEL_ALT_BG__;
                border: 1px solid __BORDER__;
                gridline-color: __BORDER__;
                color: __TEXT_PRIMARY__;
            }
            QTableWidget::item:selected {
                background: #2b5ea7;
                color: #ffffff;
            }
            QHeaderView::section {
                background: __PANEL_BG__;
                color: __TEXT_PRIMARY__;
                border: 1px solid __BORDER__;
                padding: 6px;
                font-weight: 700;
            }
            QProgressBar {
                border: 1px solid __BORDER__;
                border-radius: 6px;
                text-align: center;
                background: __WINDOW_ALT_BG__;
                color: __TEXT_PRIMARY__;
            }
            QProgressBar::chunk {
                background-color: __ACCENT__;
                border-radius: 5px;
            }
            QPushButton {
                background: __ACCENT__;
                color: __BUTTON_TEXT__;
                border: none;
                border-radius: 8px;
                font-weight: 700;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background: __ACCENT_HOVER__;
            }
            QComboBox, QCheckBox {
                background: __PANEL_ALT_BG__;
                border: 1px solid __BORDER__;
                border-radius: 7px;
                padding: 4px 8px;
            }
            QTabWidget::pane {
                border: 1px solid __BORDER__;
                border-radius: 10px;
                background: __WINDOW_BG__;
                top: -1px;
            }
            QTabBar::tab {
                background: __PANEL_ALT_BG__;
                color: __TEXT_SECONDARY__;
                border: 1px solid __BORDER__;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 7px 14px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: __PANEL_BG__;
                color: __TEXT_PRIMARY__;
            }
        """
        for key, val in {
            "__WINDOW_BG__": t["window_bg"],
            "__PANEL_BG__": t["panel_bg"],
            "__PANEL_ALT_BG__": t["panel_alt_bg"],
            "__WINDOW_ALT_BG__": t["window_alt_bg"],
            "__BORDER__": t["border"],
            "__TEXT_PRIMARY__": t["text_primary"],
            "__TEXT_SECONDARY__": t["text_secondary"],
            "__ACCENT__": t["accent"],
            "__ACCENT_HOVER__": t["accent_hover"],
            "__BUTTON_TEXT__": t["button_text"],
        }.items():
            stylesheet = stylesheet.replace(key, val)

        self.setStyleSheet(stylesheet)
