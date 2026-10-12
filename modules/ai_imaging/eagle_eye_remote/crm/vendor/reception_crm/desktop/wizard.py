"""First-run setup — the guided path from "just installed" to "ready to use".

The Connections page is complete but wide: three areas, dozens of fields, and
no opinion about what to do first. On a machine that has just been installed at
a clinic, that is the wrong first screen. This wizard is the opinionated path:

    خوش‌آمد  ->  نرم‌افزار پذیرش  ->  هوش مصنوعی  ->  موبایل  ->  آماده

Only the reception step is required; the AI and mobile steps can each be
skipped and completed later from the Connections page. Every step saves through
``save_section`` — the same code path the Connections page uses — so the wizard
holds no private state and cannot leave a half-written configuration behind.

It appears automatically the first time the app opens with no reception
credentials, and can be reopened any time from «راهنما → راه‌اندازی گام‌به‌گام».
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import secrets as secret_store
from ..connections import (
    MOBILE_LLM,
    RECEPTION,
    ReceptionApiConnection,
    load_connections,
    save_section,
)
from ..adapters.mcp_http import new_token
from ..ino_api import InoClient
from ..llm import client as llm_client
from ..settings import ConnectionProfile, resolve_center
from .friendly_errors import explain
from .help import ARCHITECTURE_STEPS, MOBILE_LLM_FIELDS, RECEPTION_FIELDS
from . import icons, theme
from .help_widgets import Callout, StatusChip, labeled

STEP_TITLES = [
    "خوش آمدید",
    "نرم‌افزار پذیرش",
    "هوش مصنوعی",
    "اپ موبایل",
    "آماده است",
]


# --------------------------------------------------------------------------- #
# chrome
# --------------------------------------------------------------------------- #
class StepBar(QWidget):
    """Where am I, how far to go — the same five words on every step."""

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.labels: list[QLabel] = []
        for index, title in enumerate(STEP_TITLES):
            label = QLabel(title)
            self.labels.append(label)
            row.addWidget(label)
            if index < len(STEP_TITLES) - 1:
                arrow = QLabel("◀")
                arrow.setObjectName("StepArrow")
                row.addWidget(arrow)
        row.addStretch(1)
        self.set_current(0)

    def set_current(self, current: int) -> None:
        for index, label in enumerate(self.labels):
            if index < current:
                name = "StepDone"
                label.setText(f"✓  {STEP_TITLES[index]}")
            elif index == current:
                name = "StepCurrent"
                label.setText(f"{index + 1}.  {STEP_TITLES[index]}")
            else:
                name = "StepPending"
                label.setText(f"{index + 1}.  {STEP_TITLES[index]}")
            label.setObjectName(name)
            label.style().unpolish(label)
            label.style().polish(label)


#: One glyph per box in the architecture diagram, in the order they appear.
FLOW_GLYPHS = ("reception", "app", "ai", "mobile")


def flow_box(title: str, role: str, note: str, glyph: str = "app") -> QFrame:
    frame = QFrame()
    frame.setObjectName("FlowBox")
    row = QHBoxLayout(frame)
    row.setContentsMargins(14, 11, 14, 11)
    row.setSpacing(12)

    mark = QLabel()
    mark.setPixmap(icons.pixmap(glyph, theme.active().brand_text, 26))
    mark.setFixedSize(26, 26)
    row.addWidget(mark, 0, Qt.AlignTop)

    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(2)
    role_label = QLabel(role)
    role_label.setObjectName("FlowRole")
    title_label = QLabel(title)
    title_label.setObjectName("FlowTitle")
    note_label = QLabel(note)
    note_label.setObjectName("FlowNote")
    note_label.setWordWrap(True)
    column.addWidget(role_label)
    column.addWidget(title_label)
    column.addWidget(note_label)
    row.addLayout(column, 1)
    return frame


def architecture_diagram() -> QWidget:
    """The four boxes that explain why each connection exists."""
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(4)
    for index, (title, role, note) in enumerate(ARCHITECTURE_STEPS):
        column.addWidget(flow_box(title, role, note, FLOW_GLYPHS[index % len(FLOW_GLYPHS)]))
        if index < len(ARCHITECTURE_STEPS) - 1:
            arrow = QLabel("↓")
            arrow.setObjectName("FlowArrow")
            arrow.setAlignment(Qt.AlignCenter)
            column.addWidget(arrow)
    return host


def heading(text: str, lead: str) -> QWidget:
    host = QWidget()
    column = QVBoxLayout(host)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(5)
    title = QLabel(text)
    title.setObjectName("WizardHeading")
    title.setWordWrap(True)
    sub = QLabel(lead)
    sub.setObjectName("WizardLead")
    sub.setWordWrap(True)
    column.addWidget(title)
    column.addWidget(sub)
    return host


# --------------------------------------------------------------------------- #
# the wizard
# --------------------------------------------------------------------------- #
class SetupWizard(QDialog):
    """Five steps; only the second one is required."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ref = window
        self.runner = window.runner
        self.connections = load_connections()

        self.setWindowTitle("راه‌اندازی سامانه")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setModal(True)
        self.resize(760, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        self.step_bar = StepBar()
        root.addWidget(self.step_bar)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(3)
        self.busy.hide()
        root.addWidget(self.busy)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_welcome())
        self.stack.addWidget(self.build_reception())
        self.stack.addWidget(self.build_llm())
        self.stack.addWidget(self.build_mobile())
        self.stack.addWidget(self.build_done())
        root.addWidget(self.stack, 1)

        self.result_note = Callout("", "info")
        self.result_note.hide()
        root.addWidget(self.result_note)

        self.back_btn = QPushButton("مرحلهٔ قبل")
        self.back_btn.clicked.connect(self.go_back)
        self.skip_btn = QPushButton("فعلاً رد شو")
        self.skip_btn.clicked.connect(self.skip_step)
        self.next_btn = QPushButton("مرحلهٔ بعد")
        self.next_btn.setObjectName("Primary")
        self.next_btn.clicked.connect(self.go_next)

        buttons = QHBoxLayout()
        buttons.addWidget(self.back_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.skip_btn)
        buttons.addWidget(self.next_btn)
        root.addLayout(buttons)

        self.sync_buttons()

    # -- step 0: what this is ------------------------------------------------ #
    def build_welcome(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        crest = QLabel()
        crest.setPixmap(icons.logo_pixmap(52))
        crest.setFixedSize(52, 52)
        column.addWidget(crest)
        column.addWidget(
            heading(
                "به دستیار مدیریت مرکز تصویربرداری خوش آمدید",
                "این راهنما در چند مرحله سامانه را آمادهٔ استفاده می‌کند. "
                "فقط مرحلهٔ دوم الزامی است؛ بقیه را می‌توانید بعداً کامل کنید.",
            )
        )
        column.addWidget(
            Callout(
                "این سامانه اطلاعات مرکز شما را فقط می‌خواند و گزارش می‌سازد. "
                "در وضعیت فعلی هیچ تغییری در پروندهٔ بیمار یا اطلاعات مالی ثبت نمی‌کند.",
                "info",
            )
        )
        column.addWidget(QLabel("مسیر اطلاعات در این سامانه چنین است:"))
        column.addWidget(architecture_diagram())
        column.addStretch(1)
        return page

    # -- step 1: reception ---------------------------------------------------- #
    def build_reception(self) -> QWidget:
        c: ReceptionApiConnection = self.connections.receptionApi
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(
            heading(
                "اتصال به نرم‌افزار پذیرش",
                "این تنها بخش الزامی است. اطلاعات ورود خودتان به نرم‌افزار پذیرش را وارد کنید — "
                "سامانه دقیقاً با همان اختیارات کار خواهد کرد.",
            )
        )

        self.w_host = QLineEdit(c.host)
        self.w_host.setPlaceholderText("مثلاً 192.168.1.10 — بدون http و بدون پورت")
        self.w_port = QSpinBox()
        self.w_port.setRange(1, 65535)
        self.w_port.setValue(int(c.crm_port))
        self.w_username = QLineEdit(c.username)
        self.w_username.setPlaceholderText("همان نام کاربری نرم‌افزار پذیرش")
        self.w_password = QLineEdit()
        self.w_password.setEchoMode(QLineEdit.Password)
        self.w_password.setPlaceholderText("ذخیره‌شده" if c.password else "رمز عبور نرم‌افزار پذیرش")

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(11)
        form.addRow(labeled("آدرس سرور پذیرش:", RECEPTION_FIELDS["host"]), self.w_host)
        form.addRow(labeled("پورت نرم‌افزار پذیرش:", RECEPTION_FIELDS["crm_port"]), self.w_port)
        form.addRow(labeled("نام کاربری:", RECEPTION_FIELDS["username"]), self.w_username)
        form.addRow(labeled("رمز عبور:", RECEPTION_FIELDS["password"]), self.w_password)
        column.addWidget(form_host)

        column.addWidget(
            Callout(
                "آدرس و پورت را می‌توانید از نوار آدرس مرورگری که نرم‌افزار پذیرش در آن باز می‌شود بردارید. "
                "اگر مطمئن نیستید، از مسئول فنی مرکز بپرسید.",
                "info",
            )
        )

        self.reception_chip = StatusChip("idle", "هنوز آزمایش نشده")
        self.reception_test = QPushButton("ذخیره و تست اتصال")
        self.reception_test.clicked.connect(self.test_reception)
        row = QHBoxLayout()
        row.addWidget(self.reception_test)
        row.addWidget(self.reception_chip)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        return page

    # -- step 2: AI brain ------------------------------------------------------ #
    def build_llm(self) -> QWidget:
        c = self.connections.mobileInternalLlm
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(
            heading(
                "مغز هوش مصنوعی",
                "این بخش فقط برای فرمان‌های صوتی و متنی اپ موبایل لازم است. "
                "اگر فعلاً از گوشی استفاده نمی‌کنید، «فعلاً رد شو» را بزنید — گزارش‌های داخل برنامه بدون آن هم کار می‌کنند.",
            )
        )

        self.w_backend = QComboBox()
        self.w_backend.addItems(["company", "openai"])
        self.w_backend.setCurrentText(c.llm_backend)
        self.w_model = QLineEdit(c.llm_model)
        self.w_api_key = QLineEdit()
        self.w_api_key.setEchoMode(QLineEdit.Password)
        self.w_api_key.setPlaceholderText("ذخیره‌شده" if c.llm_api_key else "کلیدی که از سرویس‌دهنده گرفته‌اید")

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(11)
        form.addRow(labeled("ارائه‌دهنده:", MOBILE_LLM_FIELDS["llm_backend"]), self.w_backend)
        form.addRow(labeled("مدل:", MOBILE_LLM_FIELDS["llm_model"]), self.w_model)
        form.addRow(labeled("کلید API:", MOBILE_LLM_FIELDS["llm_api_key"]), self.w_api_key)
        column.addWidget(form_host)

        self.llm_chip = StatusChip("idle", "هنوز آزمایش نشده")
        self.llm_test = QPushButton("ذخیره و تست هوش مصنوعی")
        self.llm_test.clicked.connect(self.test_llm)
        row = QHBoxLayout()
        row.addWidget(self.llm_test)
        row.addWidget(self.llm_chip)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        return page

    # -- step 3: mobile --------------------------------------------------------- #
    def build_mobile(self) -> QWidget:
        c = self.connections.mobileInternalLlm
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(
            heading(
                "اتصال اپ موبایل",
                "اگر می‌خواهید از گوشی فرمان بدهید، این مرحله را کامل کنید. در غیر این صورت «فعلاً رد شو».",
            )
        )

        self.w_gateway_port = QSpinBox()
        self.w_gateway_port.setRange(1, 65535)
        self.w_gateway_port.setValue(int(c.gateway_port))
        self.w_allow_lan = QCheckBox("گوشی‌های متصل به وای‌فای مرکز بتوانند وصل شوند")
        self.w_allow_lan.setChecked(c.allow_lan)
        self.w_device_token = QLineEdit()
        self.w_device_token.setEchoMode(QLineEdit.Normal)
        self.w_device_token.setPlaceholderText("ذخیره‌شده" if c.device_token else "«ساخت رمز» را بزنید")
        make_token = QPushButton("ساخت رمز")
        make_token.clicked.connect(self.make_device_token)
        token_row = QWidget()
        token_layout = QHBoxLayout(token_row)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.addWidget(self.w_device_token, 1)
        token_layout.addWidget(make_token)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(11)
        form.addRow(labeled("پورت اتصال موبایل:", MOBILE_LLM_FIELDS["gateway_port"]), self.w_gateway_port)
        form.addRow(labeled("رمز اتصال گوشی:", MOBILE_LLM_FIELDS["device_token"]), token_row)
        form.addRow(labeled("اتصال از وای‌فای مرکز:", MOBILE_LLM_FIELDS["allow_lan"]), self.w_allow_lan)
        column.addWidget(form_host)

        column.addWidget(
            Callout(
                "رمز ساخته‌شده را یادداشت کنید — پس از ذخیره دیگر نمایش داده نمی‌شود و باید همان را در اپ موبایل وارد کنید.",
                "warn",
            )
        )
        column.addStretch(1)
        return page

    # -- step 4: done ------------------------------------------------------------ #
    def build_done(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(
            heading(
                "سامانه آمادهٔ استفاده است",
                "می‌توانید این پنجره را ببندید و کار را از داشبورد شروع کنید.",
            )
        )
        self.summary_host = QWidget()
        self.summary = QVBoxLayout(self.summary_host)
        self.summary.setContentsMargins(0, 0, 0, 0)
        self.summary.setSpacing(7)
        column.addWidget(self.summary_host)
        column.addWidget(
            Callout(
                "هر زمان خواستید می‌توانید این تنظیمات را از صفحهٔ «اتصال‌ها» تغییر دهید، "
                "و توضیح هر بخش را از صفحهٔ «راهنما» ببینید.",
                "info",
            )
        )
        column.addStretch(1)
        return page

    def render_summary(self) -> None:
        while self.summary.count():
            item = self.summary.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        connections = load_connections()
        reception = connections.receptionApi
        mobile = connections.mobileInternalLlm

        ready = bool(reception.username and secret_store.unprotect(reception.password))
        self.summary.addWidget(
            Callout(
                f"نرم‌افزار پذیرش: {'تنظیم شد — ' + reception.api_url if ready else 'هنوز کامل نشده است'}",
                "ok" if ready else "warn",
            )
        )
        has_key = bool(secret_store.unprotect(mobile.llm_api_key))
        self.summary.addWidget(
            Callout(
                f"هوش مصنوعی: {'کلید ثبت شد' if has_key else 'تنظیم نشده (اختیاری)'}",
                "ok" if has_key else "info",
            )
        )
        has_token = bool(secret_store.unprotect(mobile.device_token))
        self.summary.addWidget(
            Callout(
                f"اپ موبایل: {'رمز اتصال ساخته شد' if has_token else 'تنظیم نشده (اختیاری)'}",
                "ok" if has_token else "info",
            )
        )

    # -- shared plumbing ---------------------------------------------------------- #
    def note(self, text: str, tone: str = "info") -> None:
        self.result_note.set_text(text)
        self.result_note.setObjectName(Callout.OBJECT_NAMES.get(tone, "CalloutInfo"))
        self.result_note.style().unpolish(self.result_note)
        self.result_note.style().polish(self.result_note)
        self.result_note.show()

    def call(self, fn: Callable[[], Any], ok: Callable[[Any], None], failed: Callable[[str, str], None]) -> None:
        self.busy.show()
        self.set_enabled(False)

        def done() -> None:
            self.busy.hide()
            self.set_enabled(True)

        self.runner.run(fn, ok, failed, done)

    def set_enabled(self, enabled: bool) -> None:
        for button in (self.back_btn, self.next_btn, self.skip_btn,
                       self.reception_test, self.llm_test):
            button.setEnabled(enabled)
        if enabled:
            # sync_buttons may keep "next" disabled while the required step is
            # still incomplete, so it has to run after the blanket re-enable.
            self.sync_buttons()

    # -- step 1 action ------------------------------------------------------------- #
    def test_reception(self) -> None:
        host = self.w_host.text().strip()
        username = self.w_username.text().strip()
        password = self.w_password.text() or secret_store.unprotect(self.connections.receptionApi.password)

        problems = []
        if not host:
            problems.append("آدرس سرور پذیرش را وارد کنید.")
        if host in {"127.0.0.1", "localhost"}:
            problems.append("۱۲۷٫۰٫۰٫۱ یعنی «همین رایانه» — اگر نرم‌افزار پذیرش جای دیگری است، آدرس واقعی آن را بنویسید.")
        if not username:
            problems.append("نام کاربری را وارد کنید.")
        if not password:
            problems.append("رمز عبور را وارد کنید.")
        if problems:
            self.note("• " + "\n• ".join(problems), "warn")
            self.reception_chip.set_state("warn", "نیازمند تکمیل")
            return

        values: dict[str, Any] = {
            "host": host,
            "crm_port": self.w_port.value(),
            "username": username,
            "auth_method": "password",
        }
        if self.w_password.text():
            values["password"] = self.w_password.text()

        def work() -> str:
            connections = save_section(RECEPTION, values)
            section = connections.receptionApi
            section.apply_env()
            profile = ConnectionProfile(
                name="setup",
                center=section.center or resolve_center(),
                host=section.normalized_host,
                crm_port=section.crm_port,
                dashboard_port=section.dashboard_port,
                pacs_port=section.pacs_port,
                socket_port=section.socket_port,
                username=section.username,
                password=password,
                data_root=section.data_root,
            )
            InoClient.from_profile(profile, password_override=password).login()
            return section.api_url

        def ok(url: str) -> None:
            self.connections = load_connections()
            self.window_ref.on_reception_saved(self.connections.receptionApi)
            self.reception_chip.set_state("ok", "متصل")
            self.w_password.clear()
            self.w_password.setPlaceholderText("ذخیره‌شده")
            self.note(f"اتصال برقرار شد و تنظیمات ذخیره شد. ({url})", "ok")
            self.sync_buttons()

        def failed(message: str, _trace: str) -> None:
            explained = explain(message, "هنگام اتصال به نرم‌افزار پذیرش،")
            self.reception_chip.set_state("bad", "اتصال برقرار نشد")
            self.note(f"{explained.headline}  {explained.advice}", "bad")

        self.reception_chip.set_state("busy")
        self.note("در حال ذخیره و بررسی اتصال…", "info")
        self.call(work, ok, failed)

    # -- step 2 action ---------------------------------------------------------------- #
    def test_llm(self) -> None:
        typed = self.w_api_key.text()
        stored = secret_store.unprotect(self.connections.mobileInternalLlm.llm_api_key)
        if not (typed or stored):
            self.note("برای آزمایش، ابتدا کلید API را وارد کنید. اگر کلید ندارید «فعلاً رد شو» را بزنید.", "warn")
            self.llm_chip.set_state("warn", "کلید وارد نشده")
            return

        backend = self.w_backend.currentText()
        model = self.w_model.text().strip() or "gpt-5.2"
        key = typed or stored

        values: dict[str, Any] = {"llm_backend": backend, "llm_model": model}
        if typed:
            values["llm_api_key"] = typed

        def work() -> dict[str, Any]:
            import os

            save_section(MOBILE_LLM, values)
            os.environ["RECEPTION_LLM_BACKEND"] = backend
            os.environ["RECEPTION_LLM_MODEL"] = model
            if backend == "openai":
                os.environ["RECEPTION_OPENAI_API_KEY"] = key
            else:
                os.environ["RECEPTION_LLM_API_KEY"] = key
            return llm_client.test_connection(timeout=20)

        def ok(result: dict[str, Any]) -> None:
            self.connections = load_connections()
            self.llm_chip.set_state("ok", "پاسخ داد")
            self.w_api_key.clear()
            self.w_api_key.setPlaceholderText("ذخیره‌شده")
            self.note(f"مغز هوش مصنوعی پاسخ داد: {result.get('display_name')} — مدل {model}", "ok")

        def failed(message: str, _trace: str) -> None:
            explained = explain(message, "هنگام تماس با سرویس هوش مصنوعی،")
            self.llm_chip.set_state("bad", "پاسخ نداد")
            self.note(f"{explained.headline}  {explained.advice}", "bad")

        self.llm_chip.set_state("busy")
        self.note("در حال ذخیره و بررسی سرویس هوش مصنوعی…", "info")
        self.call(work, ok, failed)

    # -- step 3 action -------------------------------------------------------------------- #
    def make_device_token(self) -> None:
        self.w_device_token.setText(new_token())
        self.note("رمز ساخته شد. آن را یادداشت کنید؛ با «مرحلهٔ بعد» ذخیره می‌شود.", "warn")

    def save_mobile(self) -> None:
        values: dict[str, Any] = {
            "gateway_port": self.w_gateway_port.value(),
            "allow_lan": self.w_allow_lan.isChecked(),
        }
        if self.w_device_token.text():
            values["device_token"] = self.w_device_token.text()
            values["enabled"] = True
        try:
            save_section(MOBILE_LLM, values)
            self.connections = load_connections()
        except Exception as exc:  # noqa: BLE001 - a failed optional step must not trap the user
            explained = explain(exc, "هنگام ذخیرهٔ تنظیمات موبایل،")
            self.note(f"{explained.headline}  {explained.advice}", "bad")

    # -- navigation ------------------------------------------------------------------------- #
    def reception_ready(self) -> bool:
        c = load_connections().receptionApi
        return bool(c.host and c.username and secret_store.unprotect(c.password))

    def sync_buttons(self) -> None:
        index = self.stack.currentIndex()
        last = self.stack.count() - 1
        self.back_btn.setVisible(index > 0)
        self.skip_btn.setVisible(index in (2, 3))
        self.next_btn.setText("بستن و شروع کار" if index == last else "مرحلهٔ بعد")

        if index == 1 and not self.reception_ready():
            self.next_btn.setEnabled(False)
            self.next_btn.setToolTip("ابتدا «ذخیره و تست اتصال» را با موفقیت انجام دهید.")
        else:
            self.next_btn.setEnabled(True)
            self.next_btn.setToolTip("")

    def go_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.step_bar.set_current(index)
        self.result_note.hide()
        if index == self.stack.count() - 1:
            self.render_summary()
        self.sync_buttons()

    def go_back(self) -> None:
        self.go_to(max(0, self.stack.currentIndex() - 1))

    def skip_step(self) -> None:
        self.go_to(min(self.stack.count() - 1, self.stack.currentIndex() + 1))

    def go_next(self) -> None:
        index = self.stack.currentIndex()
        if index == self.stack.count() - 1:
            self.accept()
            return
        if index == 3:
            self.save_mobile()
        self.go_to(index + 1)

    def accept(self) -> None:
        self.window_ref.mark_setup_seen()
        self.window_ref.refresh_after_wizard()
        super().accept()

    def reject(self) -> None:
        self.window_ref.mark_setup_seen()
        self.window_ref.refresh_after_wizard()
        super().reject()
