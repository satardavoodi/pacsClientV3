"""Connection Settings — three isolated integration areas.

    1. Reception software   this app  -> the practice/reception CRM
    2. Desktop AI clients   Claude Desktop / Cowork -> this app's MCP server
    3. Mobile + AI brain    phone -> this app -> AI brain -> orchestrator

Each tab owns its fields, its Save button, its Test button, and its status.
Nothing is shared: a tab reads and writes exactly one namespace in
``connections.json`` via ``save_section``, so saving the mobile section cannot
touch the reception password. Secrets are DPAPI-encrypted before they hit disk
and are shown as a mask, never as their value.

The layout follows one rule: a user who has never seen this screen should be
able to finish the required setup without asking anyone. That means

* every field carries a «؟» explaining what it is and where to find the value,
* only the handful of fields that actually must be set are on screen — the
  rest live behind «تنظیمات پیشرفته»,
* each area shows its own state as a chip, and
* failures are reported in plain Persian, with the raw error kept behind
  «جزئیات فنی» for support.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import secrets as secret_store
from ..connections import (
    EXTERNAL_MCP,
    MOBILE_LLM,
    RECEPTION,
    ExternalMcpConnection,
    MobileInternalLlmConnection,
    ReceptionApiConnection,
    connections_path,
    load_connections,
    save_section,
)
from ..adapters.mcp_http import new_token
from ..ino_api import InoClient
from ..llm import client as llm_client
from ..llm import company_backend
from ..settings import ConnectionProfile, resolve_center
from . import icons, theme
from .friendly_errors import explain
from .help import PAGE_HELP, SECTION_HELP, field_help
from .help_widgets import (
    Callout,
    Disclosure,
    HelpButton,
    StatusChip,
    described,
    labeled,
    section_header,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# form helpers
# --------------------------------------------------------------------------- #
def card(inner: QWidget, title: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    if title:
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
    layout.addWidget(inner)
    return frame


def form(namespace: str, rows: list[tuple[str, str, QWidget]]) -> QWidget:
    """Build a form where every row carries its own help.

    Rows are ``(field_key, label, widget)``. The key looks the explanation up in
    ``help.py``; passing ``""`` means the widget labels itself (a checkbox), and
    the explanation is then rendered underneath it instead of beside it.
    """
    host = QWidget()
    layout = QFormLayout(host)
    layout.setLabelAlignment(Qt.AlignRight)
    layout.setFormAlignment(Qt.AlignRight | Qt.AlignTop)
    layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    layout.setSpacing(11)

    for key, label, widget in rows:
        topic = field_help(namespace, key) if key else None
        if not label:
            # Self-labelling control (checkbox): hang the one-liner beneath it,
            # and span both columns so the wrapped note gets the full width
            # instead of being squeezed into the narrow field column.
            note = topic.summary() if topic else ""
            layout.addRow(described(widget, note) if note else widget)
            continue
        layout.addRow(labeled(label, topic), widget)
    return host


def port_box(value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(1, 65535)
    box.setValue(int(value))
    return box


def secret_row(field: QLineEdit, button: QPushButton) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(field, 1)
    layout.addWidget(button)
    return host


def steps_block(steps: list[str]) -> QWidget:
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(2, 0, 2, 0)
    column.setSpacing(5)
    for index, step in enumerate(steps, start=1):
        label = QLabel(f"{index}.  {step}")
        label.setObjectName("CalloutText")
        label.setWordWrap(True)
        column.addWidget(label)
    return host


# --------------------------------------------------------------------------- #
# shared section scaffolding
# --------------------------------------------------------------------------- #
class SectionTab(QWidget):
    """One integration area: purpose, state, fields, Save, Test, result."""

    #: short phrase naming the attempt, prefixed to any failure headline
    context = ""

    def __init__(self, page: "ConnectionPage", namespace: str) -> None:
        super().__init__()
        self.page = page
        self.namespace = namespace
        self.topic = SECTION_HELP[namespace]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        # -- purpose + live state ------------------------------------------ #
        self.chip = StatusChip("idle")
        outer.addWidget(section_header(self.topic, self.chip))

        why = QLabel(self.topic.why)
        why.setObjectName("PageHint")
        why.setWordWrap(True)
        outer.addWidget(why)

        if self.topic.steps:
            outer.addWidget(
                Disclosure(
                    "راهنمای گام‌به‌گام این بخش",
                    steps_block(self.topic.steps),
                    expanded=False,
                )
            )

        # The cards must keep their natural height. Without a scroll area Qt
        # compresses them to fit the tab and the form rows overlap.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # -- result panel --------------------------------------------------- #
        self.result = Callout("", "info")
        self.result.hide()
        self.details_text = QLabel("")
        self.details_text.setObjectName("HelpTechnical")
        self.details_text.setWordWrap(True)
        self.details_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details_text.setLayoutDirection(Qt.LeftToRight)
        self.details = Disclosure("جزئیات فنی", self.details_text)
        self.details.hide()

        # -- actions --------------------------------------------------------- #
        self.save_btn = QPushButton("ذخیره")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setToolTip("تنظیمات این بخش را روی همین رایانه ذخیره می‌کند. بخش‌های دیگر تغییر نمی‌کنند.")
        self.save_btn.clicked.connect(self.on_save)
        self.test_btn = QPushButton("تست اتصال")
        self.test_btn.setToolTip("بررسی می‌کند تنظیمات ذخیره‌شده واقعاً کار می‌کنند.")
        self.test_btn.clicked.connect(self.on_test)

        self.actions = QHBoxLayout()
        self.actions.addWidget(self.save_btn)
        self.actions.addWidget(self.test_btn)
        self.actions.addStretch(1)

        outer.addLayout(self.actions)
        outer.addWidget(self.result)
        outer.addWidget(self.details)

    def finalize(self) -> None:
        """Push the cards to the top; called once the subclass has added them."""
        self.body.addStretch(1)
        self.refresh_chip()

    # -- reporting ---------------------------------------------------------- #
    def report(self, headline: str, tone: str = "info", advice: str = "", details: str = "") -> None:
        """Show one outcome: what happened, what to do, and (optionally) why."""
        text = f"{headline}  {advice}".strip() if advice else headline
        self.result.set_text(text)
        self.result.setObjectName(Callout.OBJECT_NAMES.get(tone, "CalloutInfo"))
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)
        self.result.show()

        if details:
            self.details_text.setText(details)
            self.details.set_expanded(False)
            self.details.show()
        else:
            self.details.hide()

    def say(self, message: str, tone: str = "muted") -> None:
        """Compatibility shim for short progress notes."""
        self.report(message, {"ok": "ok", "warn": "warn", "bad": "bad"}.get(tone, "info"))

    def show_errors(self, errors: list[str]) -> bool:
        if errors:
            self.report(
                "برای ادامه، این موارد را کامل کنید:",
                "warn",
                advice="\n• " + "\n• ".join(errors),
            )
            return True
        return False

    def run(self, fn: Callable[[], Any], ok: Callable[[Any], None]) -> None:
        self.page.call(fn, ok, self.busy_buttons())

    def busy_buttons(self) -> list[QPushButton]:
        return [self.save_btn, self.test_btn]

    def fail(self, message: str, trace: str = "") -> None:
        explained = explain(message, self.context)
        self.report(explained.headline, "bad", explained.advice, trace or explained.details)
        self.refresh_chip()

    def testing(self, message: str) -> None:
        self.chip.set_state("busy")
        self.report(message, "info")

    def succeed(self, message: str) -> None:
        self.report(message, "ok")
        self.refresh_chip()

    # -- state -------------------------------------------------------------- #
    def state(self) -> tuple[str, str]:
        """(chip state, chip text) describing this area right now."""
        return "idle", ""

    def refresh_chip(self) -> None:
        state, text = self.state()
        self.chip.set_state(state, text)

    # -- contract ----------------------------------------------------------- #
    def collect(self) -> dict[str, Any]:
        raise NotImplementedError

    def validate(self) -> list[str]:
        raise NotImplementedError

    def on_save(self) -> None:
        if self.show_errors(self.validate()):
            return
        values = self.collect()
        namespace = self.namespace

        def persist() -> Any:
            connections = save_section(namespace, values)
            section = connections.section(namespace)
            if hasattr(section, "apply_env"):
                section.apply_env()
            return section

        def done(section: Any) -> None:
            self.page.reload(section, namespace)
            self.after_save(section)
            self.report(
                "تنظیمات ذخیره شد.",
                "ok",
                advice="برای اطمینان از درست بودن مقادیر، «تست اتصال» را بزنید. بخش‌های دیگر تغییر نکردند.",
            )
            self.refresh_chip()

        self.run(persist, done)

    def after_save(self, section: Any) -> None:
        return

    def on_test(self) -> None:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# 1. Reception software
# --------------------------------------------------------------------------- #
class ReceptionTab(SectionTab):
    context = "هنگام اتصال به نرم‌افزار پذیرش،"

    def __init__(self, page: "ConnectionPage") -> None:
        super().__init__(page, RECEPTION)
        c: ReceptionApiConnection = page.connections.receptionApi

        self.center = QLineEdit(c.center)
        self.center.setPlaceholderText("مثلاً razi")
        self.protocol = QComboBox()
        self.protocol.addItems(["http", "https"])
        self.protocol.setCurrentText(c.protocol)
        self.host = QLineEdit(c.host)
        self.host.setPlaceholderText("مثلاً 192.168.1.10 — بدون http و بدون پورت")
        self.crm_port = port_box(c.crm_port)
        self.pacs_port = port_box(c.pacs_port)
        self.api_base_path = QLineEdit(c.api_base_path)
        self.auth_method = QComboBox()
        self.auth_method.addItems(["password", "token"])
        self.auth_method.setItemText(0, "نام کاربری و رمز عبور")
        self.auth_method.setItemText(1, "توکن دسترسی")
        self.auth_method.setCurrentIndex(1 if c.auth_method == "token" else 0)
        self.auth_method.currentIndexChanged.connect(lambda _: self.sync_auth(self.auth_value()))
        self.username = QLineEdit(c.username)
        self.username.setPlaceholderText("همان نام کاربری نرم‌افزار پذیرش")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(
            "ذخیره‌شده — برای تغییر، مقدار جدید وارد کنید" if c.password else "رمز عبور نرم‌افزار پذیرش"
        )
        self.access_token = QLineEdit()
        self.access_token.setEchoMode(QLineEdit.Password)
        self.access_token.setPlaceholderText("ذخیره‌شده" if c.access_token else "توکنی که مسئول فنی داده است")
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 600)
        self.timeout.setValue(int(c.timeout))
        self.timeout.setSuffix(" ثانیه")
        self.data_root = QLineEdit(c.data_root)

        # -- what almost everyone has to fill in ---------------------------- #
        self.body.addWidget(
            card(
                form(
                    RECEPTION,
                    [
                        ("host", "آدرس سرور پذیرش:", self.host),
                        ("crm_port", "پورت نرم‌افزار پذیرش:", self.crm_port),
                        ("auth_method", "روش ورود:", self.auth_method),
                        ("username", "نام کاربری پذیرش:", self.username),
                        ("password", "رمز عبور پذیرش:", self.password),
                        ("access_token", "توکن دسترسی:", self.access_token),
                    ],
                ),
                "اطلاعات لازم برای ورود",
            )
        )

        # -- what almost nobody has to touch -------------------------------- #
        advanced = form(
            RECEPTION,
            [
                ("center", "نام مرکز:", self.center),
                ("protocol", "نوع ارتباط:", self.protocol),
                ("pacs_port", "پورت سامانهٔ تصاویر:", self.pacs_port),
                ("api_base_path", "مسیر پایهٔ سرویس:", self.api_base_path),
                ("timeout", "مهلت پاسخ سرور:", self.timeout),
                ("data_root", "پوشهٔ داده‌های محلی:", self.data_root),
            ],
        )
        self.body.addWidget(
            card(
                Disclosure(
                    "تنظیمات پیشرفته",
                    advanced,
                    note="این مقادیر پیش‌فرض برای بیشتر مراکز درست است. فقط در صورت راهنمایی مسئول فنی تغییر دهید.",
                )
            )
        )

        self.test_btn.setText("تست اتصال به پذیرش")
        self.sync_auth(c.auth_method)

    # -- auth mode ----------------------------------------------------------- #
    def auth_value(self) -> str:
        return "token" if self.auth_method.currentIndex() == 1 else "password"

    def sync_auth(self, method: str) -> None:
        password = method == "password"
        self.password.setEnabled(password)
        self.access_token.setEnabled(not password)
        self.password.setToolTip("" if password else "در حالت «توکن دسترسی» رمز عبور استفاده نمی‌شود.")
        self.access_token.setToolTip(
            "" if not password else "در حالت «نام کاربری و رمز عبور» توکن استفاده نمی‌شود."
        )

    # -- state --------------------------------------------------------------- #
    def state(self) -> tuple[str, str]:
        c = self.page.connections.receptionApi
        if not c.host:
            return "idle", "تنظیم نشده"
        has_secret = bool(
            secret_store.unprotect(c.access_token if c.auth_method == "token" else c.password)
        )
        if not (c.username and has_secret):
            return "warn", "نیازمند نام کاربری و رمز"
        return "warn", "ذخیره‌شده — تست نشده"

    def collect(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "center": self.center.text().strip() or resolve_center(),
            "protocol": self.protocol.currentText(),
            "host": self.host.text().strip(),
            "crm_port": self.crm_port.value(),
            "pacs_port": self.pacs_port.value(),
            "api_base_path": self.api_base_path.text().strip() or "/api",
            "auth_method": self.auth_value(),
            "username": self.username.text().strip(),
            "timeout": self.timeout.value(),
            "data_root": self.data_root.text().strip() or str(PROJECT_ROOT),
        }
        # Only send the secret when the user actually typed one: an empty box
        # means "unchanged", not "delete".
        if self.password.text():
            values["password"] = self.password.text()
        if self.access_token.text():
            values["access_token"] = self.access_token.text()
        return values

    def draft(self) -> ReceptionApiConnection:
        stored = self.page.connections.receptionApi
        draft = ReceptionApiConnection(**{**stored.__dict__, **self.collect()})
        if self.password.text():
            draft.password = self.password.text()  # plaintext, in-memory only
        return draft

    def validate(self) -> list[str]:
        draft = self.draft()
        errors = draft.validate()
        if draft.auth_method == "password" and not (
            self.password.text() or secret_store.unprotect(self.page.connections.receptionApi.password)
        ):
            errors.append("رمز عبور پذیرش وارد نشده است.")
        if draft.normalized_host in {"127.0.0.1", "localhost"}:
            errors.append(
                "آدرس ۱۲۷٫۰٫۰٫۱ یعنی «همین رایانه». اگر نرم‌افزار پذیرش روی رایانهٔ دیگری است، "
                "آدرس واقعی آن را وارد کنید."
            )
        return errors

    def after_save(self, section: ReceptionApiConnection) -> None:
        self.password.clear()
        self.password.setPlaceholderText("ذخیره‌شده — برای تغییر، مقدار جدید وارد کنید")
        self.access_token.clear()
        self.page.window_ref.on_reception_saved(section)

    def on_test(self) -> None:
        if self.show_errors(self.validate()):
            return
        draft = self.draft()
        stored_password = secret_store.unprotect(self.page.connections.receptionApi.password)
        password = self.password.text() or stored_password

        def probe() -> str:
            profile = ConnectionProfile(
                name="test",
                center=draft.center,
                host=draft.normalized_host,
                crm_port=draft.crm_port,
                dashboard_port=draft.dashboard_port,
                pacs_port=draft.pacs_port,
                socket_port=draft.socket_port,
                username=draft.username,
                password=password,
                data_root=draft.data_root,
            )
            InoClient.from_profile(profile, password_override=password or None).login()
            return draft.api_url

        def done(url: str) -> None:
            self.report(
                "اتصال به نرم‌افزار پذیرش برقرار است.",
                "ok",
                advice=f"ورود با نام کاربری «{draft.username}» پذیرفته شد. حالا می‌توانید به داشبورد بروید.",
                details=f"endpoint: {url}",
            )
            self.chip.set_state("ok", "متصل")
            self.page.window_ref.refresh_status_bar()

        self.testing("در حال بررسی اتصال به نرم‌افزار پذیرش…")
        self.run(probe, done)


# --------------------------------------------------------------------------- #
# 2. Desktop AI clients (MCP)
# --------------------------------------------------------------------------- #
class ExternalMcpTab(SectionTab):
    context = "هنگام بررسی سرویس هوش مصنوعی،"

    def __init__(self, page: "ConnectionPage") -> None:
        super().__init__(page, EXTERNAL_MCP)
        c: ExternalMcpConnection = page.connections.externalMcpClients

        self.transport = QComboBox()
        self.transport.addItems(["stdio", "http"])
        self.transport.setItemText(0, "مستقیم — برنامهٔ هوش مصنوعی روی همین رایانه")
        self.transport.setItemText(1, "شبکه‌ای — اتصال از طریق پورت")
        self.transport.setCurrentIndex(1 if c.transport == "http" else 0)
        self.transport.currentIndexChanged.connect(lambda _: self.sync_transport(self.transport_value()))

        self.host = QLineEdit(c.host)
        self.port = port_box(c.port)
        self.allow_remote = QCheckBox("اجازهٔ اتصال از رایانه‌های دیگر شبکه")
        self.allow_remote.setChecked(c.allow_remote)
        self.require_auth = QCheckBox("الزام توکن برای اتصال (توصیه می‌شود)")
        self.require_auth.setChecked(c.require_auth)
        self.autostart = QCheckBox("سرویس هنگام باز شدن برنامه خودکار اجرا شود")
        self.autostart.setChecked(c.autostart)

        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("ذخیره‌شده" if c.access_token else "برای ساختن، «تولید توکن» را بزنید")
        self.generate_btn = QPushButton("تولید توکن")
        self.generate_btn.setToolTip("یک رمز تصادفی امن می‌سازد. نیازی به حفظ کردن آن نیست.")
        self.generate_btn.clicked.connect(self.generate_token)

        self.body.addWidget(
            card(
                form(
                    EXTERNAL_MCP,
                    [
                        ("transport", "نحوهٔ اتصال:", self.transport),
                        ("access_token", "توکن دسترسی:", secret_row(self.token, self.generate_btn)),
                        ("require_auth", "", self.require_auth),
                        ("autostart", "", self.autostart),
                    ],
                ),
                "نحوهٔ اتصال برنامهٔ هوش مصنوعی",
            )
        )

        advanced = form(
            EXTERNAL_MCP,
            [
                ("host", "آدرس گوش‌دادن:", self.host),
                ("port", "پورت سرویس:", self.port),
                ("allow_remote", "", self.allow_remote),
            ],
        )
        self.body.addWidget(
            card(
                Disclosure(
                    "تنظیمات پیشرفته",
                    advanced,
                    note="فقط در حالت «شبکه‌ای» معنا دارند.",
                )
            )
        )

        # -- service control ------------------------------------------------- #
        self.server_state = StatusChip("off", "متوقف")
        self.start_btn = QPushButton("راه‌اندازی سرویس")
        self.stop_btn = QPushButton("توقف سرویس")
        self.start_btn.clicked.connect(self.start_server)
        self.stop_btn.clicked.connect(self.stop_server)
        control = QWidget()
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.server_state)
        control_layout.addStretch(1)
        self.service_note = QLabel("")
        self.service_note.setObjectName("FieldNote")
        self.service_note.setWordWrap(True)
        service_host = QWidget()
        service_column = QVBoxLayout(service_host)
        service_column.setContentsMargins(0, 0, 0, 0)
        service_column.setSpacing(6)
        service_column.addWidget(control)
        service_column.addWidget(self.service_note)
        self.body.addWidget(card(service_host, "وضعیت سرویس"))

        # -- config snippet -------------------------------------------------- #
        snippet_help = QLabel(
            "این متن را در تنظیمات برنامهٔ هوش مصنوعی جای‌گذاری کنید تا بتواند به این سامانه وصل شود."
        )
        snippet_help.setObjectName("FieldNote")
        snippet_help.setWordWrap(True)
        self.snippet = QPlainTextEdit()
        self.snippet.setReadOnly(True)
        self.snippet.setFont(QFont("Consolas", 10))
        self.snippet.setFixedHeight(150)
        self.snippet.setLayoutDirection(Qt.LeftToRight)
        self.copy_btn = QPushButton("کپی پیکربندی")
        self.copy_btn.clicked.connect(self.copy_snippet)
        snippet_host = QWidget()
        snippet_layout = QVBoxLayout(snippet_host)
        snippet_layout.setContentsMargins(0, 0, 0, 0)
        snippet_layout.setSpacing(6)
        snippet_layout.addWidget(snippet_help)
        snippet_layout.addWidget(self.snippet)
        snippet_layout.addWidget(self.copy_btn, alignment=Qt.AlignRight)
        self.body.addWidget(card(snippet_host, "پیکربندی برای برنامهٔ هوش مصنوعی"))

        # -- connected clients ------------------------------------------------ #
        self.clients = QTableWidget(0, 4)
        self.clients.setHorizontalHeaderLabels(["برنامه", "نسخه", "آدرس", "آخرین درخواست"])
        self.clients.horizontalHeader().setStretchLastSection(True)
        self.clients.setEditTriggers(QTableWidget.NoEditTriggers)
        self.clients.setFixedHeight(130)
        self.refresh_btn = QPushButton("بازخوانی")
        self.refresh_btn.clicked.connect(self.refresh_clients)
        clients_host = QWidget()
        clients_layout = QVBoxLayout(clients_host)
        clients_layout.setContentsMargins(0, 0, 0, 0)
        clients_layout.addWidget(self.clients)
        clients_layout.addWidget(self.refresh_btn, alignment=Qt.AlignRight)
        self.body.addWidget(card(clients_host, "برنامه‌های متصل"))

        self.test_btn.setText("بررسی سرویس")
        self.sync_transport(c.transport)
        self.render_snippet()
        self.render_server_state()

    # -- transport ----------------------------------------------------------- #
    def transport_value(self) -> str:
        return "http" if self.transport.currentIndex() == 1 else "stdio"

    def sync_transport(self, transport: str) -> None:
        http = transport == "http"
        for widget in (self.host, self.port, self.allow_remote, self.require_auth,
                       self.token, self.generate_btn, self.autostart,
                       self.start_btn, self.stop_btn, self.refresh_btn, self.clients):
            widget.setEnabled(http)
        self.render_snippet()
        self.service_note.setText(
            "در حالت «شبکه‌ای» سرویس روی یک پورت گوش می‌دهد و باید آن را اینجا راه‌اندازی کنید."
            if http
            else "در حالت «مستقیم» نیازی به راه‌اندازی نیست: برنامهٔ هوش مصنوعی خودش سرویس را هنگام نیاز "
            "اجرا می‌کند و هیچ پورتی روی شبکه باز نمی‌شود."
        )
        self.render_server_state()

    def generate_token(self) -> None:
        self.token.setEchoMode(QLineEdit.Normal)
        self.token.setText(new_token())
        self.report(
            "توکن ساخته شد.",
            "warn",
            advice="تا وقتی «ذخیره» را نزنید فعال نمی‌شود.",
        )

    def draft(self) -> ExternalMcpConnection:
        stored = self.page.connections.externalMcpClients
        return ExternalMcpConnection(**{**stored.__dict__, **self.collect()})

    def collect(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "transport": self.transport_value(),
            "host": self.host.text().strip() or "127.0.0.1",
            "port": self.port.value(),
            "require_auth": self.require_auth.isChecked(),
            "allow_remote": self.allow_remote.isChecked(),
            "autostart": self.autostart.isChecked(),
        }
        if self.token.text():
            values["access_token"] = self.token.text()
        return values

    def validate(self) -> list[str]:
        draft = self.draft()
        if self.token.text():
            # validate() checks the stored (encrypted) token; a freshly typed one
            # has not been saved yet, so tell it the token exists.
            draft.access_token = secret_store.protect(self.token.text()) if secret_store.is_available() else "x"
        return draft.validate()

    def after_save(self, section: ExternalMcpConnection) -> None:
        self.token.clear()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("ذخیره‌شده" if section.access_token else "برای ساختن، «تولید توکن» را بزنید")
        self.render_snippet()
        self.render_server_state()

    # -- state ---------------------------------------------------------------- #
    def state(self) -> tuple[str, str]:
        section = self.page.connections.externalMcpClients
        if section.transport == "stdio":
            return "ok", "آماده (مستقیم)"
        server = self.page.window_ref.mcp_server
        if server and server.running:
            return "ok", "در حال اجرا"
        return "off", "متوقف"

    # -- server --------------------------------------------------------------- #
    def start_server(self) -> None:
        section = self.page.connections.externalMcpClients
        if section.transport != "http":
            self.report(
                "برای راه‌اندازی سرویس، ابتدا نحوهٔ اتصال را «شبکه‌ای» کنید.",
                "warn",
                advice="پس از تغییر، «ذخیره» را بزنید.",
            )
            return
        if self.show_errors(section.validate()):
            return
        try:
            self.page.window_ref.start_mcp_http(section)
        except Exception as exc:  # noqa: BLE001
            self.fail(str(exc))
            self.render_server_state()
            return
        self.render_server_state()
        self.report(
            "سرویس هوش مصنوعی راه‌اندازی شد.",
            "ok",
            advice=f"آدرس آن {section.url} است. اکنون «کپی پیکربندی» را بزنید و در برنامهٔ هوش مصنوعی جای‌گذاری کنید.",
        )

    def stop_server(self) -> None:
        self.page.window_ref.stop_mcp_http()
        self.render_server_state()
        self.report("سرویس متوقف شد.", "info", advice="برنامه‌های هوش مصنوعی تا راه‌اندازی دوباره وصل نمی‌شوند.")

    def render_server_state(self) -> None:
        server = self.page.window_ref.mcp_server
        section = self.page.connections.externalMcpClients
        if server and server.running:
            status = server.status()
            auth = "با توکن" if section.require_auth else "بدون توکن"
            self.server_state.set_state("ok", f"در حال اجرا — {status['tool_count']} ابزار، {auth}")
        elif self.transport_value() == "stdio":
            self.server_state.set_state("ok", "آماده — نیازی به راه‌اندازی نیست")
        else:
            self.server_state.set_state("off", "متوقف")
        self.refresh_chip()

    def refresh_clients(self) -> None:
        server = self.page.window_ref.mcp_server
        rows = server.clients.list() if server and server.running else []
        self.clients.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, key in enumerate(["name", "version", "address", "last_method"]):
                self.clients.setItem(index, column, QTableWidgetItem(str(row.get(key) or "")))
        self.render_server_state()
        if not rows:
            self.report(
                "هیچ برنامه‌ای متصل نیست.",
                "info",
                advice="اگر پیکربندی را در برنامهٔ هوش مصنوعی وارد کرده‌اید، آن برنامه را یک بار ببندید و باز کنید.",
            )

    # -- snippet ---------------------------------------------------------------- #
    def render_snippet(self) -> None:
        draft = self.draft()
        self.snippet.setPlainText(json.dumps(draft.client_config(PROJECT_ROOT), indent=2))

    def copy_snippet(self) -> None:
        QGuiApplication.clipboard().setText(self.snippet.toPlainText())
        self.report(
            "پیکربندی کپی شد.",
            "ok",
            advice="حالا آن را در تنظیمات برنامهٔ هوش مصنوعی جای‌گذاری کنید و آن برنامه را دوباره باز کنید.",
        )

    # -- test ------------------------------------------------------------------- #
    def on_test(self) -> None:
        """Real MCP handshake: initialize + tools/list against the live server."""
        server = self.page.window_ref.mcp_server
        section = self.page.connections.externalMcpClients

        if section.transport == "stdio":
            def probe_stdio() -> tuple[str, int]:
                from ..mcp_server import handle_request, mcp_tools

                init = handle_request(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                )
                return init["result"]["protocolVersion"], len(mcp_tools())

            def done(result: tuple[str, int]) -> None:
                version, count = result
                self.report(
                    "سرویس سالم است.",
                    "ok",
                    advice=f"{count} ابزار در دسترس برنامهٔ هوش مصنوعی است. پیکربندی را کپی کنید و در آن برنامه وارد کنید.",
                    details=f"protocol {version}",
                )
                self.refresh_chip()

            self.testing("در حال بررسی سرویس…")
            self.run(probe_stdio, done)
            return

        if not (server and server.running):
            self.report(
                "سرویس در حال اجرا نیست.",
                "warn",
                advice="ابتدا دکمهٔ «راه‌اندازی سرویس» را بزنید.",
            )
            return

        url = f"http://127.0.0.1:{section.port}/mcp"
        token = secret_store.unprotect(section.access_token)

        def probe_http() -> tuple[str, int]:
            import urllib.request

            def rpc(method: str, request_id: int) -> dict[str, Any]:
                body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}}).encode()
                request = urllib.request.Request(url, data=body, method="POST")
                request.add_header("Content-Type", "application/json")
                if section.require_auth and token:
                    request.add_header("Authorization", f"Bearer {token}")
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))

            init = rpc("initialize", 1)
            tools = rpc("tools/list", 2)
            return init["result"]["protocolVersion"], len(tools["result"]["tools"])

        def done(result: tuple[str, int]) -> None:
            version, count = result
            self.report(
                "سرویس سالم است و پاسخ می‌دهد.",
                "ok",
                advice=f"{count} ابزار از طریق شبکه در دسترس است.",
                details=f"{url} — protocol {version}",
            )
            self.refresh_chip()

        self.testing("در حال بررسی سرویس…")
        self.run(probe_http, done)


# --------------------------------------------------------------------------- #
# 3. Mobile app + AI brain
# --------------------------------------------------------------------------- #
class MobileLlmTab(SectionTab):
    context = "هنگام بررسی درگاه موبایل،"

    def __init__(self, page: "ConnectionPage") -> None:
        super().__init__(page, MOBILE_LLM)
        c: MobileInternalLlmConnection = page.connections.mobileInternalLlm

        self.enabled = QCheckBox("این بخش فعال باشد")
        self.enabled.setChecked(c.enabled)
        self.gateway_host = QLineEdit(c.gateway_host)
        self.gateway_port = port_box(c.gateway_port)
        self.protocol = QComboBox()
        self.protocol.addItems(["http", "https"])
        self.protocol.setCurrentText(c.protocol)
        self.allow_lan = QCheckBox("اجازهٔ اتصال گوشی از وای‌فای مرکز")
        self.allow_lan.setChecked(c.allow_lan)
        self.device_token = QLineEdit()
        self.device_token.setEchoMode(QLineEdit.Password)
        self.device_token.setPlaceholderText("ذخیره‌شده" if c.device_token else "برای ساختن، «تولید» را بزنید")
        self.device_generate = QPushButton("تولید")
        self.device_generate.clicked.connect(lambda: self._fill(self.device_token))

        self.api_user = QLineEdit(c.api_user)
        self.api_center = QLineEdit(c.api_center)
        self.api_roles = QLineEdit(c.api_roles)

        self.mobile_address = QLabel("")
        self.mobile_address.setObjectName("FieldNote")
        self.mobile_address.setWordWrap(True)
        self.mobile_address.setTextInteractionFlags(Qt.TextSelectableByMouse)

        gateway_host_widget = QWidget()
        gateway_column = QVBoxLayout(gateway_host_widget)
        gateway_column.setContentsMargins(0, 0, 0, 0)
        gateway_column.setSpacing(8)
        gateway_column.addWidget(
            form(
                MOBILE_LLM,
                [
                    ("enabled", "", self.enabled),
                    ("gateway_port", "پورت اتصال موبایل:", self.gateway_port),
                    ("device_token", "رمز اتصال گوشی:", secret_row(self.device_token, self.device_generate)),
                    ("allow_lan", "", self.allow_lan),
                ],
            )
        )
        gateway_column.addWidget(self.mobile_address)
        self.body.addWidget(card(gateway_host_widget, "اتصال اپ موبایل"))

        # -- the AI brain: two choices, and the default needs no configuration -- #
        self.use_company = QRadioButton(f"{company_backend.DISPLAY_NAME_FA}  —  پیشنهادشده")
        self.use_openai = QRadioButton("استفاده از حساب OpenAI خودم")
        self.use_company.setChecked(c.uses_company_backend)
        self.use_openai.setChecked(not c.uses_company_backend)
        self.use_company.toggled.connect(lambda _: self.sync_backend())

        self.company_state = StatusChip("idle")
        self.llm_model = QLineEdit(c.llm_model)
        self.llm_model.setPlaceholderText("مثلاً gpt-4o")
        self.llm_api_key = QLineEdit()
        self.llm_api_key.setEchoMode(QLineEdit.Password)
        self.llm_api_key.setPlaceholderText("ذخیره‌شده" if c.llm_api_key else "کلید حساب OpenAI شما")
        self.llm_base_url = QLineEdit(c.llm_base_url)
        self.llm_timeout = QSpinBox()
        self.llm_timeout.setRange(1, 600)
        self.llm_timeout.setValue(int(c.llm_timeout))
        self.llm_timeout.setSuffix(" ثانیه")
        self.llm_temperature = QDoubleSpinBox()
        self.llm_temperature.setRange(0.0, 2.0)
        self.llm_temperature.setSingleStep(0.1)
        self.llm_temperature.setValue(float(c.llm_temperature))
        self.llm_max_tokens = QSpinBox()
        self.llm_max_tokens.setRange(64, 32000)
        self.llm_max_tokens.setValue(int(c.llm_max_tokens))
        self.llm_proxy = QLineEdit(c.llm_proxy)
        self.llm_proxy.setPlaceholderText("اگر پروکسی ندارید خالی بگذارید")
        self.retry_attempts = QSpinBox()
        self.retry_attempts.setRange(0, 5)
        self.retry_attempts.setValue(int(c.retry_attempts))
        self.enable_writes = QCheckBox("اجازهٔ ثبت تغییر از موبایل (پس از تأیید انسانی)")
        self.enable_writes.setChecked(c.enable_writes)

        self.body.addWidget(card(self.build_brain_card(), "مغز هوش مصنوعی"))

        advanced = form(
            MOBILE_LLM,
            [
                ("gateway_host", "آدرس گوش‌دادن درگاه:", self.gateway_host),
                ("protocol", "نوع ارتباط موبایل:", self.protocol),
                ("api_user", "کاربر فرمان‌های موبایل:", self.api_user),
                ("api_center", "مرکز فرمان‌های موبایل:", self.api_center),
                ("api_roles", "سطح دسترسی:", self.api_roles),
                ("llm_timeout", "مهلت پاسخ هوش مصنوعی:", self.llm_timeout),
                ("llm_temperature", "میزان خلاقیت پاسخ:", self.llm_temperature),
                ("llm_max_tokens", "حداکثر طول پاسخ:", self.llm_max_tokens),
                ("llm_proxy", "پروکسی اینترنت:", self.llm_proxy),
                ("retry_attempts", "تعداد تلاش مجدد:", self.retry_attempts),
                ("enable_writes", "", self.enable_writes),
            ],
        )
        self.body.addWidget(
            card(
                Disclosure(
                    "تنظیمات پیشرفته",
                    advanced,
                    note="برای راه‌اندازی معمولی نیازی به تغییر این مقادیر نیست.",
                )
            )
        )

        self.test_llm_btn = QPushButton("تست مغز هوش مصنوعی")
        self.test_llm_btn.setToolTip("بررسی می‌کند کلید API درست است و مدل پاسخ می‌دهد.")
        self.test_llm_btn.clicked.connect(self.test_llm)
        self.actions.insertWidget(2, self.test_llm_btn)
        self.test_btn.setText("تست درگاه موبایل")

        self.sync_backend()
        self.render_mobile_address()
        self.gateway_port.valueChanged.connect(lambda _: self.render_mobile_address())
        self.allow_lan.toggled.connect(lambda _: self.render_mobile_address())

    def busy_buttons(self) -> list[QPushButton]:
        return [self.save_btn, self.test_btn, self.test_llm_btn]

    def backend_value(self) -> str:
        return "openai" if self.use_openai.isChecked() else "company"

    def _fill(self, field: QLineEdit) -> None:
        field.setEchoMode(QLineEdit.Normal)
        field.setText(new_token())
        self.report(
            "رمز اتصال ساخته شد.",
            "warn",
            advice="آن را کپی کنید، «ذخیره» را بزنید، و همان را در اپ موبایل وارد کنید.",
        )

    # -- the AI brain ---------------------------------------------------------- #
    def build_brain_card(self) -> QWidget:
        """Two radio choices; only the second one has anything to fill in."""
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        # -- choice 1: nothing to configure -------------------------------- #
        company_row = QWidget()
        company_line = QHBoxLayout(company_row)
        company_line.setContentsMargins(0, 0, 0, 0)
        company_line.setSpacing(8)
        company_badge = QLabel()
        company_badge.setPixmap(icons.pixmap("ai", theme.active().brand_text, 18))
        company_line.addWidget(company_badge)
        company_line.addWidget(self.use_company)
        company_line.addWidget(HelpButton(field_help(MOBILE_LLM, "llm_backend")))
        company_line.addWidget(self.company_state)
        company_line.addStretch(1)
        column.addWidget(company_row)

        company_note = QLabel(
            "سرویس آمادهٔ شرکت. کلید، مدل و آدرس سرویس از قبل در برنامه تنظیم شده‌اند "
            "و شما چیزی وارد نمی‌کنید."
        )
        company_note.setObjectName("FieldNote")
        company_note.setWordWrap(True)
        company_note.setContentsMargins(26, 0, 0, 6)
        column.addWidget(company_note)

        # -- choice 2: the user's own account -------------------------------- #
        column.addWidget(self.use_openai)
        openai_note = QLabel(
            "فقط اگر می‌خواهید هزینه و مدل را خودتان مدیریت کنید. در این حالت باید کلید "
            "حساب OpenAI خود را وارد کنید."
        )
        openai_note.setObjectName("FieldNote")
        openai_note.setWordWrap(True)
        openai_note.setContentsMargins(26, 0, 0, 4)
        column.addWidget(openai_note)

        self.openai_fields = QWidget()
        openai_column = QVBoxLayout(self.openai_fields)
        openai_column.setContentsMargins(26, 0, 0, 0)
        openai_column.setSpacing(0)
        openai_column.addWidget(
            form(
                MOBILE_LLM,
                [
                    ("llm_api_key", "کلید API حساب OpenAI:", self.llm_api_key),
                    ("llm_model", "مدل:", self.llm_model),
                    ("llm_base_url", "آدرس سرویس (اختیاری):", self.llm_base_url),
                ],
            )
        )
        column.addWidget(self.openai_fields)
        return host

    def sync_backend(self) -> None:
        """Show the OpenAI fields only when they are the ones being used."""
        openai = self.use_openai.isChecked()
        self.openai_fields.setVisible(openai)

        status = company_backend.status()
        if status["source"] == "missing":
            # A build packaged without its key. The clinic cannot fix this, so
            # say what it is rather than asking them for a key.
            self.company_state.set_state("bad", "کلید در این نسخه موجود نیست")
            self.company_state.setToolTip(
                "این نسخه بدون کلید سرویس شرکت ساخته شده است. با پشتیبانی تماس بگیرید."
            )
        else:
            self.company_state.set_state("ok", "آماده — نیازی به تنظیم ندارد")
            self.company_state.setToolTip(f"مدل: {status['model']}")
        self.refresh_chip()

    def render_mobile_address(self) -> None:
        """Tell the user exactly what to type into the phone."""
        if not self.allow_lan.isChecked():
            self.mobile_address.setText(
                "برای اتصال از گوشی واقعی، گزینهٔ «اجازهٔ اتصال گوشی از وای‌فای مرکز» را روشن کنید."
            )
            return
        self.mobile_address.setText(
            "در اپ موبایل این آدرس را وارد کنید:  "
            f"{self.protocol.currentText()}://«آدرس این رایانه»:{self.gateway_port.value()}  "
            "— آدرس این رایانه را می‌توانید از مسئول فنی مرکز بگیرید."
        )

    # -- state ---------------------------------------------------------------- #
    def state(self) -> tuple[str, str]:
        c = self.page.connections.mobileInternalLlm
        if not c.enabled:
            return "off", "غیرفعال"
        if c.uses_company_backend:
            if not company_backend.is_available():
                return "bad", "کلید سرویس شرکت در این نسخه نیست"
        elif not secret_store.unprotect(c.llm_api_key):
            return "warn", "نیازمند کلید OpenAI"
        if c.allow_lan and not secret_store.unprotect(c.device_token):
            return "warn", "نیازمند رمز اتصال گوشی"
        return "warn", "ذخیره‌شده — تست نشده"

    def collect(self) -> dict[str, Any]:
        values: dict[str, Any] = {
            "enabled": self.enabled.isChecked(),
            "gateway_host": self.gateway_host.text().strip() or "127.0.0.1",
            "gateway_port": self.gateway_port.value(),
            "protocol": self.protocol.currentText(),
            "allow_lan": self.allow_lan.isChecked(),
            "api_user": self.api_user.text().strip() or "vahid",
            "api_center": self.api_center.text().strip() or resolve_center(),
            "api_roles": self.api_roles.text().strip() or "owner",
            "llm_backend": self.backend_value(),
            "llm_model": self.llm_model.text().strip() or "gpt-5.2",
            "llm_base_url": self.llm_base_url.text().strip(),
            "llm_timeout": self.llm_timeout.value(),
            "llm_temperature": float(self.llm_temperature.value()),
            "llm_max_tokens": self.llm_max_tokens.value(),
            "llm_proxy": self.llm_proxy.text().strip(),
            "retry_attempts": self.retry_attempts.value(),
            "enable_writes": self.enable_writes.isChecked(),
        }
        if self.device_token.text():
            values["device_token"] = self.device_token.text()
        if self.llm_api_key.text():
            values["llm_api_key"] = self.llm_api_key.text()
        return values

    def draft(self) -> MobileInternalLlmConnection:
        stored = self.page.connections.mobileInternalLlm
        draft = MobileInternalLlmConnection(**{**stored.__dict__, **self.collect()})
        # Typed-but-unsaved secrets: mark them present so validation is truthful.
        if self.device_token.text():
            draft.device_token = stored.device_token or "unsaved"
        if self.llm_api_key.text():
            draft.llm_api_key = stored.llm_api_key or "unsaved"
        return draft

    def validate(self) -> list[str]:
        draft = self.draft()
        errors = [
            error
            for error in draft.validate()
            # These two are satisfied by a value typed in this session.
            if not (self.llm_api_key.text() and "OpenAI" in error)
            and not (self.device_token.text() and "توکن دستگاه" in error)
        ]
        # Restate the two library-level messages in the vocabulary of this screen.
        replacements = {
            "برای دسترسی از شبکه، توکن دستگاه الزامی است.":
                "برای اتصال گوشی از وای‌فای مرکز، ابتدا «رمز اتصال گوشی» را بسازید و ذخیره کنید.",
        }
        return [replacements.get(error, error) for error in errors]

    def after_save(self, section: MobileInternalLlmConnection) -> None:
        self.device_token.clear()
        self.device_token.setEchoMode(QLineEdit.Password)
        self.device_token.setPlaceholderText("ذخیره‌شده" if section.device_token else "برای ساختن، «تولید» را بزنید")
        self.llm_api_key.clear()
        self.llm_api_key.setEchoMode(QLineEdit.Password)
        self.llm_api_key.setPlaceholderText("ذخیره‌شده" if section.llm_api_key else "کلید حساب OpenAI شما")
        self.render_mobile_address()

    def test_llm(self) -> None:
        """Ping the AI brain. On the company backend there is nothing to enter."""
        section = self.page.connections.mobileInternalLlm
        backend = self.backend_value()
        typed = self.llm_api_key.text()

        if backend == "company":
            if not company_backend.is_available():
                self.report(
                    "این نسخهٔ برنامه بدون کلید سرویس شرکت ساخته شده است.",
                    "bad",
                    advice="این مورد از سمت شما قابل رفع نیست — با پشتیبانی تماس بگیرید.",
                    details="reception_crm/llm/company_key.txt was not bundled in this build",
                )
                return
            key = company_backend.api_key()
            model = company_backend.MODEL
            base_url = ""
        else:
            if not (typed or secret_store.unprotect(section.llm_api_key)):
                self.report(
                    "کلید حساب OpenAI وارد نشده است.",
                    "warn",
                    advice="کلید را وارد کنید و «ذخیره» را بزنید، یا گزینهٔ سرویس شرکت را انتخاب کنید.",
                )
                return
            key = typed or secret_store.unprotect(section.llm_api_key)
            model = self.llm_model.text().strip()
            base_url = self.llm_base_url.text().strip()

        timeout = self.llm_timeout.value()

        def probe() -> dict[str, Any]:
            import os

            # Apply to this process only, so a test never half-writes settings.
            os.environ["RECEPTION_LLM_BACKEND"] = backend
            os.environ["RECEPTION_LLM_MODEL"] = model
            if backend == "openai":
                os.environ["RECEPTION_OPENAI_API_KEY"] = key
                if base_url:
                    os.environ["RECEPTION_OPENAI_BASE_URL"] = base_url
            else:
                os.environ["RECEPTION_LLM_API_KEY"] = key
            return llm_client.test_connection(timeout=min(int(timeout), 20))

        def done(result: dict[str, Any]) -> None:
            name = result.get("display_name")
            self.report(
                f"«{name}» پاسخ داد.",
                "ok",
                advice=f"مدل «{model}» آمادهٔ تفسیر فرمان‌های گوشی است.",
                details=f"{name} ({result.get('provider')})",
            )
            self.refresh_chip()

        def failed(message: str, trace: str) -> None:
            explained = explain(message, "هنگام تماس با سرویس هوش مصنوعی،")
            self.report(explained.headline, "bad", explained.advice, trace or explained.details)
            self.refresh_chip()

        self.chip.set_state("busy")
        self.report("در حال تماس با سرویس هوش مصنوعی…", "info")
        self.page.call(probe, done, self.busy_buttons(), on_error=failed)

    def on_test(self) -> None:
        """Check the mobile gateway endpoint is reachable."""
        section = self.page.connections.mobileInternalLlm
        port = self.gateway_port.value()
        url = f"http://127.0.0.1:{port}/api/health"

        def probe() -> dict[str, Any]:
            import urllib.error
            import urllib.request

            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError as exc:
                raise RuntimeError(f"gateway not running on port {port}: {exc}") from exc

        def done(body: dict[str, Any]) -> None:
            llm_state = "آماده" if body.get("llm_configured") else "تنظیم نشده"
            writes = "فعال" if body.get("writes_enabled") else "غیرفعال (فقط خواندن)"
            self.report(
                "درگاه موبایل سالم است.",
                "ok",
                advice=f"{body.get('tool_count')} ابزار در دسترس است — مغز هوش مصنوعی: {llm_state}، ثبت تغییر: {writes}.",
                details=url,
            )
            self.chip.set_state("ok", "متصل")

        def failed(message: str, trace: str) -> None:
            if "gateway not running" in message:
                self.report(
                    "درگاه موبایل در حال اجرا نیست.",
                    "warn",
                    advice="این سرویس جداگانه اجرا می‌شود. از مسئول فنی بخواهید آن را راه‌اندازی کند، "
                    "یا دستور نمایش‌داده‌شده در «جزئیات فنی» را اجرا کنید.",
                    details=f"python -m reception_crm.cli http-api --host {section.bind_host} "
                    f"--port {section.gateway_port}\n\n{trace or message}",
                )
                self.refresh_chip()
                return
            explained = explain(message, self.context)
            self.report(explained.headline, "bad", explained.advice, trace or explained.details)
            self.refresh_chip()

        self.testing("در حال بررسی درگاه موبایل…")
        self.page.call(probe, done, self.busy_buttons(), on_error=failed)


# --------------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------------- #
class ConnectionPage(QWidget):
    """Three tabs, three namespaces, no shared state."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.runner = window.runner
        self.connections = load_connections()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        topic = PAGE_HELP["connections"]
        header = QWidget()
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(7)
        title = QLabel(topic.title)
        title.setObjectName("PageTitle")
        header_row.addWidget(title)
        header_row.addWidget(HelpButton(topic))
        header_row.addStretch(1)
        root.addWidget(header)

        hint = QLabel(topic.why)
        hint.setObjectName("PageHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(
            Callout(
                "برای شروع فقط بخش «۱. نرم‌افزار پذیرش» لازم است. دو بخش دیگر اختیاری‌اند و "
                "می‌توانید بعداً سراغشان بروید.",
                "info",
                ("راه‌اندازی گام‌به‌گام", lambda: self.window_ref.open_wizard()),
            )
        )

        if not secret_store.is_available():
            root.addWidget(
                Callout(
                    "ذخیرهٔ امن رمز روی این رایانه در دسترس نیست، بنابراین رمزها ذخیره نمی‌شوند. "
                    "تا رفع این مشکل باید مقادیر را از طریق متغیرهای محیطی تنظیم کنید.",
                    "warn",
                )
            )

        self.busy = None  # set by Page-like call()
        self.tabs = QTabWidget()
        self.reception = ReceptionTab(self)
        self.external = ExternalMcpTab(self)
        self.mobile = MobileLlmTab(self)
        for tab in (self.reception, self.external, self.mobile):
            tab.finalize()
        self.tabs.setIconSize(QSize(18, 18))
        for tab, glyph, label in (
            (self.reception, "reception", "۱. نرم‌افزار پذیرش  (الزامی)"),
            (self.external, "desktop_ai", "۲. برنامه‌های هوش مصنوعی  (اختیاری)"),
            (self.mobile, "mobile", "۳. موبایل و هوش مصنوعی  (اختیاری)"),
        ):
            self.tabs.addTab(tab, icons.themed_icon(glyph, "brand_text", 18), label)
        root.addWidget(self.tabs, 1)

        footer = QLabel(f"تنظیمات روی همین رایانه ذخیره می‌شود: {connections_path()}")
        footer.setObjectName("FieldNote")
        footer.setWordWrap(True)
        footer.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(footer)

    def show_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(index)

    # -- async ---------------------------------------------------------------- #
    def call(self, fn, on_success, buttons: list[QPushButton], on_error=None) -> None:
        for button in buttons:
            button.setEnabled(False)

        def done() -> None:
            for button in buttons:
                button.setEnabled(True)

        def failed(message: str, trace: str) -> None:
            if on_error is not None:
                on_error(message, trace)
                return
            tab = self.tabs.currentWidget()
            if isinstance(tab, SectionTab):
                tab.fail(message, trace)

        self.runner.run(fn, on_success, failed, done)

    def reload(self, section: Any, namespace: str) -> None:
        setattr(self.connections, namespace, section)
        for tab in (self.reception, self.external, self.mobile):
            tab.refresh_chip()

    def refresh_all_chips(self) -> None:
        for tab in (self.reception, self.external, self.mobile):
            tab.refresh_chip()
