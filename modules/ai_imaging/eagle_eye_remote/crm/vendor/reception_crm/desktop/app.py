"""Reception CRM — native desktop application.

A Qt shell over the existing, unchanged core:

    UI page  ->  workers.run_tool  ->  core.dispatcher.dispatch  ->  guard chain
                                                                     -> registry tool

The UI gets no private path to the CRM. Every call passes the same validation,
permission, and audit guards the CLI and MCP server use, so a read-only role
stays read-only here too.

Connections are split into three isolated areas (see connection_pages.py):
reception API, external MCP clients, and mobile + internal LLM.

Run:
    python -m reception_crm.desktop
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import secrets as secret_store
from ..adapters.mcp_http import McpHttpServer
from ..agent_router import route_command
from ..connections import (
    ExternalMcpConnection,
    ReceptionApiConnection,
    connections_path,
    load_connections,
)
from ..management import render_persian_report
from ..operations import load_operations
from . import theme
from .connection_pages import ConnectionPage
from .conversation_page import ConversationHistoryPage
from .friendly_errors import explain
from .help import PAGE_HELP, SECTION_HELP, TROUBLESHOOTING
from . import icons
from .help_widgets import Callout, Disclosure, HelpButton, StatusChip
from .prompts_page import PromptsPage
from .wizard import SetupWizard, architecture_diagram
from .workers import TaskRunner, run_tool

APP_NAME = "Reception CRM"
APP_SUBTITLE = "دستیار مدیریت مرکز تصویربرداری"

#: The sidebar labels, in order. ``icons.NAV_GLYPHS`` is keyed by these, and a
#: test asserts the two agree — a renamed page would otherwise silently lose its
#: glyph and fall back to the help mark.
PAGE_LABELS: tuple[str, ...] = (
    "داشبورد",
    "گزارش‌های مدیریتی",
    "گفت‌وگوها و داده‌ها",
    "صف گزارش‌دهی",
    "قالب‌های گزارش",
    "کنسول فرمان",
    "اتصال‌ها",
    "دستورهای هوش مصنوعی",
    "راهنما",
)

ANALYTICS_SKILLS: list[tuple[str, str]] = [
    ("daily-summary", "خلاصه عملکرد روزانه"),
    ("financial-analysis", "تحلیل مالی"),
    ("cashier-reconciliation", "مغایرت‌گیری صندوق"),
    ("risk-analysis", "تحلیل ریسک و پیگیری"),
    ("trend-analysis", "مقایسه روند"),
    ("patient-list", "فهرست بیماران"),
]


# --------------------------------------------------------------------------- #
# small building blocks
# --------------------------------------------------------------------------- #
def card(*widgets: QWidget, spacing: int = 10) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return frame


def title_block(topic) -> QWidget:
    """Page heading: name, one-line purpose, and the «؟» that explains the rest.

    Takes a ``Help`` record rather than loose strings so the page title, its
    hover summary, and the popup can never drift apart.
    """
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)

    top = QWidget()
    row = QHBoxLayout(top)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(7)
    label = QLabel(topic.title)
    label.setObjectName("PageTitle")
    row.addWidget(label)
    row.addWidget(HelpButton(topic))
    row.addStretch(1)
    layout.addWidget(top)

    sub = QLabel(topic.what)
    sub.setObjectName("PageHint")
    sub.setWordWrap(True)
    layout.addWidget(sub)
    return box


class KpiCard(QFrame):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)
        self.value = QLabel("—")
        self.value.setObjectName("KpiValue")
        self.caption = QLabel(label)
        self.caption.setObjectName("KpiLabel")
        layout.addWidget(self.value)
        layout.addWidget(self.caption)

    def set_value(self, value: Any) -> None:
        self.value.setText("—" if value in (None, "") else f"{value:,}" if isinstance(value, int) else str(value))


class Page(QWidget):
    """Base page: title, help, busy bar, and shared access to the window."""

    #: short phrase naming the attempt, prefixed to any failure headline
    error_context = "هنگام خواندن اطلاعات از نرم‌افزار پذیرش،"

    def __init__(self, window: "MainWindow", key: str) -> None:
        super().__init__()
        self.window_ref = window
        self.runner = window.runner
        self.topic = PAGE_HELP[key]

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(14)
        self.root.addWidget(title_block(self.topic))

        if self.topic.warning:
            self.root.addWidget(Callout(self.topic.warning, "info"))

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(3)
        self.busy.hide()
        self.root.addWidget(self.busy)

    def call(self, fn, on_success, buttons: list[QPushButton] | None = None) -> None:
        buttons = buttons or []
        for button in buttons:
            button.setEnabled(False)
        self.busy.show()

        def done() -> None:
            self.busy.hide()
            for button in buttons:
                button.setEnabled(True)

        self.runner.run(fn, on_success, self.show_error, done)

    def restyle(self) -> None:
        """Re-render anything that baked colours into HTML.

        Qt re-polishes widgets when the stylesheet changes, but a document
        already handed to a QTextBrowser keeps the old ``REPORT_CSS``. Pages
        that render HTML override this to redraw from their last payload.
        """
        return

    def show_error(self, message: str, trace: str) -> None:
        """Report a failure the way a receptionist can act on.

        The raw text is never the headline — it is almost always English and
        often a stack fragment. It stays available under "جزئیات فنی" so support
        still gets the exact error.
        """
        explained = explain(message, self.error_context)
        self.window_ref.set_status(explained.headline, "bad")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("مشکلی پیش آمد")
        box.setText(explained.headline)
        box.setInformativeText(explained.advice)
        box.setDetailedText(trace or explained.details)
        box.setStandardButtons(QMessageBox.Ok)
        box.button(QMessageBox.Ok).setText("متوجه شدم")
        # Qt labels the details toggle "Show Details..." in English regardless of
        # locale; it is the only untranslated string left on this dialog.
        for button in box.buttons():
            if box.buttonRole(button) == QMessageBox.ActionRole:
                button.setText("جزئیات فنی")
        box.exec()

    @property
    def user(self) -> str:
        return self.window_ref.user

    @property
    def center(self) -> str:
        return self.window_ref.center

    @property
    def data_root(self) -> str:
        return self.window_ref.data_root

    def tool(self, name: str, arguments: dict[str, Any]):
        user, center, root = self.user, self.center, self.data_root
        return lambda: run_tool(name, arguments, user=user, center=center, data_root=root)


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
class DashboardPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, "dashboard")

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.date_input = QLineEdit("today")
        self.date_input.setPlaceholderText("today / yesterday / 1404-04-22")
        self.date_input.setFixedWidth(220)
        self.refresh_btn = QPushButton("بارگذاری")
        self.refresh_btn.setObjectName("Primary")
        self.refresh_btn.clicked.connect(self.load)
        row.addWidget(QLabel("تاریخ:"))
        row.addWidget(self.date_input)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        self.root.addWidget(controls)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.kpis = {
            "receptions": KpiCard("پذیرش"),
            "revenue": KpiCard("درآمد کل"),
            "paid": KpiCard("دریافتی"),
            "outstanding": KpiCard("مانده"),
        }
        for column, kpi in enumerate(self.kpis.values()):
            grid.addWidget(kpi, 0, column)
        self.root.addWidget(grid_host)

        self.report = QTextBrowser()
        self.report.setOpenExternalLinks(True)
        self.root.addWidget(card(self.report), 1)
        self._last: dict[str, Any] | None = None
        self.empty_state()

    def empty_state(self) -> None:
        if not self.window_ref.has_reception():
            body = (
                "<p><b>هنوز به نرم‌افزار پذیرش وصل نشده‌اید.</b></p>"
                f"<p style='color:{theme.active().muted}'>تا وقتی این اتصال کامل نشود، داده‌ای برای نمایش وجود ندارد. "
                "از صفحهٔ «اتصال‌ها» بخش «۱. نرم‌افزار پذیرش» را کامل کنید، یا از صفحهٔ «راهنما» "
                "راه‌اندازی گام‌به‌گام را اجرا کنید.</p>"
            )
        else:
            body = (
                f"<p style='color:{theme.active().muted}'>تاریخ موردنظر را انتخاب کنید و «بارگذاری» را بزنید.<br>"
                "برای امروز کافی است مقدار <b>today</b> را نگه دارید.</p>"
            )
        self.report.setHtml(theme.REPORT_CSS + body)

    def load(self) -> None:
        if not self.window_ref.require_reception():
            return
        self.window_ref.set_status("در حال خواندن خلاصه روزانه…", "muted")
        self.call(
            self.tool("daily-summary", {"date": self.date_input.text().strip() or "today", "days": 1}),
            self.render,
            [self.refresh_btn],
        )

    def restyle(self) -> None:
        if self._last is None:
            self.empty_state()
        else:
            self.render(self._last)

    def render(self, result: dict[str, Any]) -> None:
        self._last = result
        totals = result.get("totals") or result.get("summary") or {}
        if isinstance(totals, dict):
            self.kpis["receptions"].set_value(totals.get("receptions") or totals.get("count") or result.get("count"))
            self.kpis["revenue"].set_value(totals.get("total") or totals.get("revenue"))
            self.kpis["paid"].set_value(totals.get("paid") or totals.get("received"))
            self.kpis["outstanding"].set_value(totals.get("outstanding") or totals.get("remaining"))
        self.report.setMarkdown(render_persian_report(result))
        self.window_ref.set_status("خلاصه روزانه بارگذاری شد.", "ok")


class ReportsPage(Page):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, "reports")

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)

        self.skill = QComboBox()
        for name, label in ANALYTICS_SKILLS:
            self.skill.addItem(f"{label}  ({name})", name)
        self.skill.currentIndexChanged.connect(self.sync_fields)

        self.date_input = QLineEdit("today")
        self.date_input.setFixedWidth(160)
        self.days = QSpinBox()
        self.days.setRange(1, 90)
        self.modality = QComboBox()
        self.modality.addItems(["", "MRI", "CT", "US", "XR"])
        self.compare = QComboBox()
        self.compare.addItems(["yesterday", "last-week", "last-month"])

        self.run_btn = QPushButton("اجرا")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self.run)

        for label, widget in [
            ("مهارت:", self.skill),
            ("تاریخ:", self.date_input),
            ("تعداد روز:", self.days),
            ("مودالیته:", self.modality),
            ("مقایسه با:", self.compare),
        ]:
            caption = QLabel(label)
            row.addWidget(caption)
            row.addWidget(widget)
            widget.setProperty("caption", caption)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        self.root.addWidget(controls)

        self.tabs = QTabWidget()
        self.rendered = QTextBrowser()
        self.raw = QTextBrowser()
        self.raw.setFont(QFont("Consolas", 10))
        self.tabs.addTab(self.rendered, "گزارش")
        self.tabs.addTab(self.raw, "JSON خام")
        self.root.addWidget(self.tabs, 1)
        self._last: dict[str, Any] | None = None
        self.sync_fields()

    def sync_fields(self) -> None:
        skill = self.skill.currentData()
        for widget, visible in [(self.modality, skill == "patient-list"), (self.compare, skill == "trend-analysis")]:
            widget.setVisible(visible)
            caption = widget.property("caption")
            if caption:
                caption.setVisible(visible)

    def run(self) -> None:
        if not self.window_ref.require_reception():
            return
        skill = self.skill.currentData()
        args: dict[str, Any] = {"date": self.date_input.text().strip() or "today", "days": self.days.value()}
        if skill == "patient-list" and self.modality.currentText():
            args["modality"] = self.modality.currentText()
        if skill == "trend-analysis":
            args["compare"] = self.compare.currentText()
        self.window_ref.set_status(f"در حال اجرای {skill}…", "muted")
        self.call(self.tool(skill, args), self.render, [self.run_btn])

    def restyle(self) -> None:
        if self._last is not None:
            self.render(self._last)

    def render(self, result: dict[str, Any]) -> None:
        self._last = result
        self.rendered.setMarkdown(render_persian_report(result))
        self.raw.setPlainText(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        self.window_ref.set_status("گزارش آماده شد.", "ok")


class ReportingQueuePage(Page):
    COLUMNS = [
        ("reception_id", "شماره پذیرش"),
        ("patient_name", "بیمار"),
        ("modality", "مودالیته"),
        ("date", "تاریخ"),
        ("report_status", "وضعیت گزارش"),
        ("radiologist", "رادیولوژیست"),
        ("workflow_id", "شناسه ورک‌فلو"),
    ]

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, "queue")

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("نام بیمار / کد ملی")
        self.status = QComboBox()
        self.status.addItems(["", "pending", "awaiting_physician_approval", "physician_approved", "completed"])
        self.limit = QSpinBox()
        self.limit.setRange(5, 100)
        self.limit.setValue(20)
        self.load_btn = QPushButton("بارگذاری صف")
        self.load_btn.setObjectName("Primary")
        self.load_btn.clicked.connect(self.load)
        self.open_btn = QPushButton("گزارش ردیف انتخابی")
        self.open_btn.clicked.connect(self.open_selected)

        row.addWidget(QLabel("جستجو:"))
        row.addWidget(self.search)
        row.addWidget(QLabel("وضعیت:"))
        row.addWidget(self.status)
        row.addWidget(QLabel("تعداد:"))
        row.addWidget(self.limit)
        row.addWidget(self.load_btn)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        self.root.addWidget(controls)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.root.addWidget(self.table, 2)

        self.detail = QTextBrowser()
        self._last_detail: dict[str, Any] | None = None
        self.root.addWidget(card(self.detail), 1)

    def load(self) -> None:
        if not self.window_ref.require_reception():
            return
        args: dict[str, Any] = {"page": 1, "limit": self.limit.value()}
        if self.search.text().strip():
            args["search"] = self.search.text().strip()
        if self.status.currentText():
            args["status"] = self.status.currentText()
        self.window_ref.set_status("در حال خواندن صف گزارش‌دهی…", "muted")
        self.call(self.tool("reporting-queue", args), self.render, [self.load_btn])

    def render(self, result: dict[str, Any]) -> None:
        rows = result.get("rows") or []
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, (key, _) in enumerate(self.COLUMNS):
                value = row.get(key)
                if isinstance(value, list):
                    value = "، ".join(str(item) for item in value)
                self.table.setItem(index, column, QTableWidgetItem("" if value is None else str(value)))
        self.window_ref.set_status(f"{len(rows)} ردیف در صف گزارش‌دهی.", "ok")

    def open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.window_ref.set_status("ابتدا یک ردیف را انتخاب کنید.", "warn")
            return
        item = self.table.item(row, 0)
        if not item or not item.text():
            return
        reception_id = item.text()
        self.window_ref.set_status(f"در حال خواندن گزارش پذیرش {reception_id}…", "muted")
        self.call(self.tool("report-current", {"reception_id": reception_id}), self.render_detail, [self.open_btn])

    def restyle(self) -> None:
        if self._last_detail is not None:
            self.render_detail(self._last_detail)

    def render_detail(self, result: dict[str, Any]) -> None:
        self._last_detail = result
        patient = result.get("patient") or {}
        report = result.get("report") or {}
        body = report.get("html") or "<p><i>گزارشی ثبت نشده است.</i></p>"
        header = (
            f"<h3>{patient.get('name') or '—'} "
            f"<small style='color:{theme.active().muted}'>({result.get('reception_id')})</small></h3>"
            f"<p style='color:{theme.active().muted}'>وضعیت: {report.get('status') or '—'} | "
            f"رادیولوژیست: {report.get('radiologist') or '—'} | "
            f"خدمات: {'، '.join(result.get('services') or []) or '—'}</p><hr>"
        )
        self.detail.setHtml(theme.REPORT_CSS + header + body)
        self.window_ref.set_status("گزارش بارگذاری شد.", "ok")


class TemplatesPage(Page):
    error_context = "هنگام جستجوی قالب‌ها،"

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, "templates")

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.query = QLineEdit()
        self.query.setPlaceholderText("مثال: سونوگرافی شکم")
        self.query.returnPressed.connect(self.search)
        self.modality_id = QLineEdit()
        self.modality_id.setPlaceholderText("کد مودالیته (مثلاً 3)")
        self.modality_id.setFixedWidth(160)
        self.search_btn = QPushButton("جستجو")
        self.search_btn.setObjectName("Primary")
        self.search_btn.clicked.connect(self.search)

        row.addWidget(QLabel("عبارت:"))
        row.addWidget(self.query, 1)
        row.addWidget(self.modality_id)
        row.addWidget(self.search_btn)
        self.root.addWidget(controls)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["عنوان", "دسته", "مودالیته", "شناسه"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.preview)
        self.root.addWidget(self.table, 1)

        self.body = QTextBrowser()
        self.root.addWidget(card(self.body), 1)
        self.rows: list[dict[str, Any]] = []

    def search(self) -> None:
        args: dict[str, Any] = {"limit": 50, "include_html": True, "max_content_chars": 4000}
        if self.query.text().strip():
            args["query"] = self.query.text().strip()
        if self.modality_id.text().strip():
            args["modality_id"] = self.modality_id.text().strip()
        self.window_ref.set_status("در حال جستجوی قالب‌ها…", "muted")
        self.call(self.tool("report-template-search", args), self.render, [self.search_btn])

    def render(self, result: dict[str, Any]) -> None:
        self.rows = result.get("results") or []
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            for column, key in enumerate(["title", "category", "modality_id", "template_id"]):
                value = row.get(key)
                self.table.setItem(index, column, QTableWidgetItem("" if value is None else str(value)))
        self.window_ref.set_status(f"{len(self.rows)} قالب یافت شد.", "ok")

    def restyle(self) -> None:
        self.preview()

    def preview(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.rows):
            data = self.rows[row]
            html = data.get("content_html") or f"<p>{data.get('plain_preview') or ''}</p>"
            self.body.setHtml(theme.REPORT_CSS + html)


class CommandPage(Page):
    error_context = "هنگام بررسی فرمان،"

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, "command")

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("مثال: گزارش کارکرد امروز را بده")
        self.input.setFixedHeight(90)

        self.route_btn = QPushButton("بررسی فرمان")
        self.route_btn.setObjectName("Primary")
        self.route_btn.clicked.connect(self.route)

        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.route_btn)
        row.addStretch(1)

        self.root.addWidget(card(self.input, buttons))

        self.output = QTextBrowser()
        self.output.setFont(QFont("Consolas", 10))
        self.root.addWidget(self.output, 1)

    def route(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        user, center = self.user, self.center
        self.window_ref.set_status("در حال مسیریابی فرمان…", "muted")
        self.call(lambda: route_command(text=text, user=user, center=center), self.render, [self.route_btn])

    def render(self, decision: dict[str, Any]) -> None:
        self.output.setPlainText(json.dumps(decision, ensure_ascii=False, indent=2, default=str))
        self.window_ref.set_status("فرمان مسیریابی شد.", "ok")


class HelpPage(Page):
    """What this software is, how to set it up, and what to do when it breaks.

    Replaces the old "About" screen. The system-status table is still here — it
    is what support asks for — but it now sits below the three things a user
    actually comes looking for: how it works, how to start, and why it isn't
    working.
    """

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window, "help")

        self.root.addWidget(self.build_appearance())

        tabs = QTabWidget()
        tabs.addTab(self.build_overview(), "این سامانه چه می‌کند؟")
        tabs.addTab(self.build_setup(), "راه‌اندازی")
        tabs.addTab(self.build_troubleshooting(), "رفع مشکل")
        self.system_view = self.build_system(window)
        tabs.addTab(self.system_view, "اطلاعات سامانه")
        self.root.addWidget(tabs, 1)

    def restyle(self) -> None:
        self.render_system(self.window_ref)

    # -- overview ------------------------------------------------------------ #
    def build_overview(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(12)

        intro = QLabel(
            "این برنامه یک دستیار مدیریت برای مرکز تصویربرداری است. اطلاعات را از نرم‌افزار پذیرش "
            "می‌خواند، گزارش‌های مدیریتی می‌سازد، و می‌تواند از طریق گوشی یا دستیار هوش مصنوعی هم "
            "به همان گزارش‌ها پاسخ بدهد."
        )
        intro.setWordWrap(True)
        column.addWidget(intro)

        column.addWidget(
            Callout(
                "سیاست فعلی سامانه «فقط خواندن» است: هیچ تغییری در پروندهٔ بیمار یا اطلاعات مالی "
                "مرکز ثبت نمی‌شود. این وضعیت در نوار پایین پنجره هم نمایش داده می‌شود.",
                "info",
            )
        )

        flow_title = QLabel("مسیر اطلاعات")
        flow_title.setObjectName("SectionTitle")
        column.addWidget(flow_title)
        column.addWidget(architecture_diagram())

        why_title = QLabel("چرا هر اتصال لازم است؟")
        why_title.setObjectName("SectionTitle")
        column.addWidget(why_title)
        for namespace in ("receptionApi", "externalMcpClients", "mobileInternalLlm"):
            topic = SECTION_HELP[namespace]
            required = "الزامی" if topic.required else "اختیاری"
            item = QLabel(f"<b>{topic.title}</b> — {required}<br>{topic.why}")
            item.setWordWrap(True)
            item.setObjectName("HelpBody")
            column.addWidget(item)

        column.addStretch(1)
        page.setWidget(inner)
        return page

    # -- setup ---------------------------------------------------------------- #
    def build_setup(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(12)

        lead = QLabel(
            "ساده‌ترین راه راه‌اندازی، اجرای راهنمای گام‌به‌گام است. همان مراحل را می‌توانید "
            "به‌صورت دستی هم از صفحهٔ «اتصال‌ها» انجام دهید."
        )
        lead.setWordWrap(True)
        column.addWidget(lead)

        wizard_btn = QPushButton("اجرای راه‌اندازی گام‌به‌گام")
        wizard_btn.setObjectName("Primary")
        wizard_btn.clicked.connect(self.window_ref.open_wizard)
        column.addWidget(wizard_btn, alignment=Qt.AlignRight)

        for namespace in ("receptionApi", "externalMcpClients", "mobileInternalLlm"):
            topic = SECTION_HELP[namespace]
            if not topic.steps:
                continue
            title = QLabel(topic.title)
            title.setObjectName("SectionTitle")
            column.addWidget(title)
            for index, step in enumerate(topic.steps, start=1):
                step_label = QLabel(f"{index}.  {step}")
                step_label.setObjectName("HelpBody")
                step_label.setWordWrap(True)
                column.addWidget(step_label)

        column.addStretch(1)
        page.setWidget(inner)
        return page

    # -- troubleshooting -------------------------------------------------------- #
    def build_troubleshooting(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(9)

        lead = QLabel("رایج‌ترین مشکل‌ها و راه‌حلشان. روی هر مورد کلیک کنید تا باز شود.")
        lead.setObjectName("PageHint")
        lead.setWordWrap(True)
        column.addWidget(lead)

        for question, answer in TROUBLESHOOTING:
            body = QLabel(answer)
            body.setObjectName("HelpBody")
            body.setWordWrap(True)
            column.addWidget(Disclosure(question, body))

        column.addStretch(1)
        page.setWidget(inner)
        return page

    # -- appearance ----------------------------------------------------------- #
    def build_appearance(self) -> QWidget:
        """Light or dark, or whatever Windows is set to."""
        host = QFrame()
        host.setObjectName("Card")
        row = QHBoxLayout(host)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(9)

        label = QLabel("ظاهر برنامه:")
        label.setObjectName("FieldLabel")
        row.addWidget(label)

        self.appearance = QComboBox()
        for mode in (theme.AUTO, theme.LIGHT_MODE, theme.DARK_MODE):
            self.appearance.addItem(theme.MODE_LABELS[mode], mode)
        current = load_theme_preference()
        index = self.appearance.findData(current)
        self.appearance.setCurrentIndex(index if index >= 0 else 0)
        self.appearance.currentIndexChanged.connect(
            lambda _: self.window_ref.set_theme(self.appearance.currentData())
        )
        row.addWidget(self.appearance)

        note = QLabel("در حالت خودکار، برنامه از تنظیم روشن/تیرهٔ ویندوز پیروی می‌کند.")
        note.setObjectName("FieldNote")
        note.setWordWrap(True)
        row.addWidget(note, 1)
        return host

    # -- system info -------------------------------------------------------------- #
    def build_system(self, window: "MainWindow") -> QWidget:
        self.system_body = QTextBrowser()
        self.render_system(window)
        return self.system_body

    def render_system(self, window: "MainWindow") -> None:
        registry = load_operations()
        write_mode = registry.defaults.get("write_mode", "dry_run_only")
        reception = window.reception
        write_label = "فقط خواندن — هیچ تغییری ثبت نمی‌شود" if write_mode == "dry_run_only" else write_mode
        secrets_label = "فعال (رمزنگاری ویندوز)" if secret_store.is_available() else "در دسترس نیست"

        self.system_body.setHtml(
            theme.REPORT_CSS
            + f"""
            <p style='color:{theme.active().muted}'>اگر با پشتیبانی تماس می‌گیرید، این اطلاعات را در اختیارشان بگذارید.</p>
            <table>
              <tr><th>نام برنامه</th><td>{APP_NAME}</td></tr>
              <tr><th>کاربر فعال</th><td>{window.user}</td></tr>
              <tr><th>مرکز</th><td>{window.center}</td></tr>
              <tr><th>آدرس نرم‌افزار پذیرش</th><td>{reception.api_url}</td></tr>
              <tr><th>وضعیت اتصال پذیرش</th><td>{'تنظیم شده' if window.has_reception() else 'تنظیم نشده'}</td></tr>
              <tr><th>پوشهٔ داده‌های محلی</th><td>{window.data_root}</td></tr>
              <tr><th>تعداد ابزارهای ثبت‌شده</th><td>{len(registry.operations)}</td></tr>
              <tr><th>سیاست ثبت تغییر</th><td><b>{write_label}</b></td></tr>
              <tr><th>ذخیرهٔ امن رمزها</th><td>{secrets_label}</td></tr>
            </table>
            <h4>روش‌های اجرا (برای پشتیبانی فنی)</h4>
            <pre>python -m reception_crm.desktop               # همین برنامه
.\\scripts\\run_desktop.ps1               # اجرا با بررسی محیط
python -m reception_crm.cli mcp               # سرویس MCP (stdio)
python -m reception_crm.adapters.mcp_http     # سرویس MCP (HTTP)
python -m reception_crm.cli http-api          # درگاه موبایل</pre>
            """
        )


# --------------------------------------------------------------------------- #
# main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_SUBTITLE}")
        self.resize(1280, 860)
        self.setMinimumSize(1040, 680)

        self.runner = TaskRunner()
        self.mcp_server: McpHttpServer | None = None

        self.connections = load_connections()
        self.connections.apply_env()  # reception + mobile/LLM env projection

        root = QWidget()
        root.setObjectName("Content")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_sidebar())

        self.stack = QStackedWidget()
        self.connection_page = ConnectionPage(self)
        # (label, page, one-line purpose shown as the nav tooltip)
        self.pages = [
            ("داشبورد", DashboardPage(self), "خلاصهٔ عملکرد امروز مرکز"),
            ("گزارش‌های مدیریتی", ReportsPage(self), "گزارش‌های تحلیلی آماده"),
            (
                "گفت‌وگوها و داده‌ها",
                ConversationHistoryPage(self),
                "پاسخ‌های قبلی و فایل‌های کامل هر تحلیل",
            ),
            ("صف گزارش‌دهی", ReportingQueuePage(self), "کارتابل گزارش‌های تصویربرداری"),
            ("قالب‌های گزارش", TemplatesPage(self), "جستجو در قالب‌های نمونهٔ گزارش"),
            ("کنسول فرمان", CommandPage(self), "آزمودن فرمان‌های فارسی"),
            ("اتصال‌ها", self.connection_page, "تنظیم ارتباط با پذیرش، هوش مصنوعی و موبایل"),
            ("دستورهای هوش مصنوعی", PromptsPage(self), "ویرایش دستور هر حالت دستیار — پیشرفته"),
            ("راهنما", HelpPage(self), "توضیح سامانه، راه‌اندازی، و رفع مشکل"),
        ]
        for _, page, _hint in self.pages:
            self.stack.addWidget(page)
        self.nav.setIconSize(QSize(19, 19))
        for label, _page, hint in self.pages:
            item = QListWidgetItem(label)
            item.setToolTip(hint)
            item.setIcon(icons.nav_icon(icons.NAV_GLYPHS.get(label, "help")))
            self.nav.addItem(item)

        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.status_label = QLabel("")
        self.statusBar().addWidget(self.status_label, 1)

        # State as chips rather than one long pipe-separated sentence: the user
        # should be able to read "is it connected?" without parsing a line.
        self.reception_chip = StatusChip("idle")
        self.reception_chip.setToolTip("وضعیت اتصال به نرم‌افزار پذیرش")
        self.mcp_chip = StatusChip("off", "سرویس هوش مصنوعی: خاموش")
        self.mcp_chip.setToolTip("وضعیت سرویسی که برنامه‌های هوش مصنوعی رومیزی به آن وصل می‌شوند")
        self.write_chip = StatusChip("ok", "فقط خواندن")
        self.write_chip.setToolTip("هیچ تغییری در پروندهٔ بیمار یا اطلاعات مالی ثبت نمی‌شود")
        self.identity_label = QLabel("")
        self.identity_label.setObjectName("FieldNote")
        for widget in (self.identity_label, self.write_chip, self.mcp_chip, self.reception_chip):
            self.statusBar().addPermanentWidget(widget)
        self.refresh_status_bar()

        if self.connections.externalMcpClients.autostart:
            try:
                self.start_mcp_http(self.connections.externalMcpClients)
            except Exception:  # noqa: BLE001 - autostart must never block the window
                pass

        # A machine that has just been installed gets the guided path, not the
        # settings screen. Once the user has seen it, we never push it again —
        # the Help page keeps it available on demand.
        if not self.has_reception():
            if self.first_run():
                QTimer.singleShot(300, self.open_wizard)
            else:
                self.nav.setCurrentRow(self.connections_index)
                self.set_status(
                    "برای شروع، اتصال به نرم‌افزار پذیرش را کامل کنید.", "warn"
                )

    # -- chrome ------------------------------------------------------------- #
    def build_sidebar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(252)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        # The mark beside the name, not instead of it: staff who have never seen
        # the app still need to read what it is.
        brand_row = QWidget()
        brand_layout = QHBoxLayout(brand_row)
        brand_layout.setContentsMargins(14, 16, 14, 12)
        brand_layout.setSpacing(9)

        mark = QLabel()
        mark.setPixmap(icons.logo_pixmap(30))
        mark.setFixedSize(30, 30)
        brand_layout.addWidget(mark, 0, Qt.AlignTop)

        words = QWidget()
        word_column = QVBoxLayout(words)
        word_column.setContentsMargins(0, 0, 0, 0)
        word_column.setSpacing(1)
        brand = QLabel(APP_NAME)
        brand.setObjectName("BrandTitle")
        sub = QLabel(APP_SUBTITLE)
        sub.setObjectName("BrandSub")
        sub.setWordWrap(True)
        word_column.addWidget(brand)
        word_column.addWidget(sub)
        brand_layout.addWidget(words, 1)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav.setWordWrap(False)
        self.nav.setTextElideMode(Qt.ElideNone)

        # Always-visible escape hatch: whatever page the user is lost on, the
        # guided setup is one click away.
        self.wizard_btn = QPushButton("راه‌اندازی گام‌به‌گام")
        self.wizard_btn.setObjectName("SidebarAction")
        self.wizard_btn.setToolTip("راهنمای مرحله‌به‌مرحله برای آماده‌سازی سامانه")
        self.wizard_btn.clicked.connect(self.open_wizard)

        layout.addWidget(brand_row)
        layout.addWidget(self.nav, 1)
        layout.addWidget(self.wizard_btn)
        layout.setContentsMargins(0, 0, 0, 12)
        return bar

    @property
    def connections_index(self) -> int:
        return next(
            index for index, (label, _page, _hint) in enumerate(self.pages)
            if label == "اتصال‌ها"
        )

    def set_status(self, message: str, tone: str = "muted") -> None:
        names = {"ok": "PillOk", "warn": "PillWarn", "bad": "PillBad", "muted": "PillMuted"}
        self.status_label.setText(message)
        self.status_label.setObjectName(names.get(tone, "PillMuted"))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def refresh_status_bar(self) -> None:
        if self.has_reception():
            self.reception_chip.set_state("ok", "پذیرش: تنظیم شده")
        else:
            self.reception_chip.set_state("warn", "پذیرش: تنظیم نشده")
        self.reception_chip.setToolTip(f"آدرس نرم‌افزار پذیرش: {self.reception.api_url}")

        running = bool(self.mcp_server and self.mcp_server.running)
        self.mcp_chip.set_state(
            "ok" if running else "off",
            "سرویس هوش مصنوعی: در حال اجرا" if running else "سرویس هوش مصنوعی: خاموش",
        )
        self.identity_label.setText(f"{self.user} — {self.center}")

    # -- reception ---------------------------------------------------------- #
    @property
    def reception(self) -> ReceptionApiConnection:
        return self.connections.receptionApi

    @property
    def user(self) -> str:
        return self.reception.username or "vahid"

    @property
    def center(self) -> str:
        return self.reception.center

    @property
    def data_root(self) -> str:
        return self.reception.data_root

    def has_reception(self) -> bool:
        reception = self.reception
        if not reception.username:
            return False
        if reception.auth_method == "token":
            return bool(secret_store.unprotect(reception.access_token))
        return bool(secret_store.unprotect(reception.password))

    def require_reception(self) -> bool:
        if self.has_reception():
            return True
        self.set_status(
            "برای دیدن داده‌ها ابتدا اتصال به نرم‌افزار پذیرش را کامل کنید.", "warn"
        )
        self.nav.setCurrentRow(self.connections_index)
        self.connection_page.show_tab(0)
        return False

    def on_reception_saved(self, section: ReceptionApiConnection) -> None:
        self.connections.receptionApi = section
        self.refresh_status_bar()

    # -- guided setup -------------------------------------------------------- #
    def setup_marker(self) -> Path:
        """Marker file recording that the wizard has been offered once."""
        return connections_path().with_name("setup-seen")

    def first_run(self) -> bool:
        try:
            return not self.setup_marker().exists()
        except OSError:
            # An unreadable config dir must not stop the app from opening; the
            # worst case is that the wizard is offered again next time.
            return False

    def mark_setup_seen(self) -> None:
        try:
            marker = self.setup_marker()
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("seen", encoding="utf-8")
        except OSError:
            pass

    def open_wizard(self) -> None:
        SetupWizard(self).exec()

    # -- appearance ---------------------------------------------------------- #
    def set_theme(self, mode: str) -> None:
        """Switch light/dark without restarting.

        Re-applying the stylesheet repaints every styled widget, but HTML that
        was already handed to a QTextBrowser keeps the old colours — hence the
        ``restyle()`` pass over the pages that render documents.
        """
        app = QApplication.instance()
        if app is None:
            return
        save_theme_preference(mode)
        theme.apply(app, mode)

        # The glyphs are tinted, so every cached pixmap is stale the moment the
        # palette swaps. Drop them, then rebuild the ones already on screen.
        icons.clear_cache()
        for row, (label, _page, _hint) in enumerate(self.pages):
            item = self.nav.item(row)
            if item is not None:
                item.setIcon(icons.nav_icon(icons.NAV_GLYPHS.get(label, "help")))

        for _label, page, _hint in self.pages:
            if hasattr(page, "restyle"):
                page.restyle()
        self.refresh_status_bar()

    def refresh_after_wizard(self) -> None:
        """Re-read what the wizard saved so every page agrees with the file."""
        self.connections = load_connections()
        self.connections.apply_env()
        self.connection_page.connections = load_connections()
        self.connection_page.refresh_all_chips()
        self.refresh_status_bar()
        if self.has_reception():
            self.nav.setCurrentRow(0)
            self.set_status("سامانه آمادهٔ استفاده است. «بارگذاری» را بزنید.", "ok")
        else:
            self.set_status("برای شروع، اتصال به نرم‌افزار پذیرش را کامل کنید.", "warn")

    # -- MCP HTTP ----------------------------------------------------------- #
    def start_mcp_http(self, section: ExternalMcpConnection) -> None:
        self.stop_mcp_http()
        token = secret_store.unprotect(section.access_token)
        server = McpHttpServer(
            host=section.bind_host,
            port=section.port,
            token=token,
            require_auth=section.require_auth,
        )
        server.start()
        self.mcp_server = server
        self.refresh_status_bar()

    def stop_mcp_http(self) -> None:
        if self.mcp_server:
            self.mcp_server.stop()
            self.mcp_server = None
        self.refresh_status_bar()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt signature
        # An unsaved prompt edit is real work; closing must not throw it away
        # without asking.
        for _label, page, _hint in self.pages:
            if getattr(page, "has_unsaved", lambda: False)():
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle("تغییرات ذخیره نشده")
                box.setText("یک دستور هوش مصنوعی ذخیره نشده است.")
                box.setInformativeText("اگر ببندید، آن تغییر از بین می‌رود.")
                close = box.addButton("بستن بدون ذخیره", QMessageBox.DestructiveRole)
                box.addButton("برگرد", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is not close:
                    event.ignore()
                    return
                break
        self.stop_mcp_http()
        super().closeEvent(event)


def load_theme_preference() -> str:
    """Appearance choice, stored per user via QSettings."""
    try:
        return QSettings("Reception CRM", APP_NAME).value("appearance", theme.AUTO) or theme.AUTO
    except Exception:  # noqa: BLE001 - a missing registry key must not stop startup
        return theme.AUTO


def save_theme_preference(mode: str) -> None:
    try:
        QSettings("Reception CRM", APP_NAME).setValue("appearance", mode)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Reception CRM")
    app.setLayoutDirection(Qt.RightToLeft)
    # Install palette + stylesheet together. Setting only the stylesheet leaves
    # dialogs and tooltips on the desktop's own colours, which reads as
    # dark-on-dark when Windows is in dark mode.
    theme.apply(app, load_theme_preference())

    # Carries every size Windows asks for, each drawn from the vector rather
    # than downscaled from one bitmap.
    app.setWindowIcon(icons.app_icon())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
