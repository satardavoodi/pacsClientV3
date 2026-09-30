"""Viewport-owned SR panel, with worker-only reads and superseded-result guards."""
from threading import Event

from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPlainTextEdit, QVBoxLayout

from PacsClient.utils.structured_report import SR_CLASSES, load_reports


class _Result(QObject):
    ready = Signal(int, object, str)


class _ReadReport(QRunnable):
    def __init__(self, result, generation, identity, cancelled):
        super().__init__()
        self.result, self.generation, self.identity = result, generation, identity
        self.cancelled = cancelled

    def run(self):
        try:
            documents = load_reports(*self.identity, cancelled=self.cancelled.is_set)
            error = ""
        except Exception:
            # Exceptions may contain patient paths or report content.
            documents = ()
            error = ("Unable to read this structured report. Check that the series is fully "
                     "downloaded and contains supported SR documents with matching identity.")
        if not self.cancelled.is_set():
            self.result.ready.emit(self.generation, documents, error)


class StructuredReportPanel(QFrame):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.generation = 0
        self.documents = ()
        self.active = False
        self.cancelled = Event()
        cancellation = [self.cancelled]
        self._cancellation = cancellation
        self.destroyed.connect(lambda *_: cancellation[0].set())
        self.setObjectName("structuredReportPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("#structuredReportPanel {background: #111b29; color: #edf3fa;}")
        layout = QVBoxLayout(self)
        title = QLabel("Structured Report", self)
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)
        notice = QLabel("Image tools are unavailable for documents. Drop an image series to return.", self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.selector = QComboBox(self)
        layout.addWidget(self.selector)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setAcceptDrops(False)
        layout.addWidget(self.text)
        self.selector.currentIndexChanged.connect(self._select)
        self.result = _Result()  # Jobs retain this signal object after panel destruction.
        self.result.ready.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        viewport.installEventFilter(self)
        self.hide()

    def paintEvent(self, event):
        # A native VTK window has no Qt backing-store pixels to compose against.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111b29"))
        painter.end()
        super().paintEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return False

    def begin(self, identity):
        self.cancelled.set()
        self.cancelled = Event()
        self._cancellation[0] = self.cancelled
        self.generation += 1
        self.active = True
        self.documents = ()
        self.selector.clear()
        self.selector.setEnabled(False)
        self.text.setPlainText("Loading structured report...")
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        QThreadPool.globalInstance().start(
            _ReadReport(self.result, self.generation, identity, self.cancelled))

    def dismiss(self):
        self.cancelled.set()
        self.generation += 1
        self.active = False
        self.documents = ()
        self.selector.clear()
        self.text.clear()
        self.hide()

    @Slot(int)
    def _select(self, index):
        if 0 <= index < len(self.documents):
            self.text.setPlainText(self.documents[index][1])

    @Slot(int, object, str)
    def _receive(self, generation, documents, error):
        if not self.active or generation != self.generation:
            return
        self.documents = documents
        self.selector.addItems([document[0] for document in documents])
        self.selector.setEnabled(len(documents) > 1)
        if error:
            self.text.setPlainText(error)
        else:
            self._select(0)
        self.raise_()


def route_report(controller, viewport, series_number):
    """Consume catalogued SR selections; return False for the image pipeline.

    Catalog modality is only a routing hint. The worker verifies the actual SOP
    Class and both UIDs before presenting any content.
    """
    entries = getattr(controller.parent_widget, "_server_series_info", {}) or {}
    entry = entries.get(series_number, entries.get(str(series_number), {})) or {}
    is_report = (str(entry.get("modality", "")).upper() == "SR"
                 or str(entry.get("sop_class_uid", "")) in SR_CLASSES)
    panel = getattr(viewport, "_structured_report_panel", None)
    if not is_report:
        if panel is not None and panel.active:
            panel.dismiss()
        viewport._structured_report_active = False
        slider = getattr(viewport, "slider", None)
        if slider is not None and hasattr(viewport, "_report_slider_enabled"):
            slider.setEnabled(viewport._report_slider_enabled)
            del viewport._report_slider_enabled
        return False
    controller._next_request_token(viewport)
    toolbar = getattr(controller.parent_widget, "toolbar_manager", None)
    if toolbar is not None and not getattr(viewport, "_structured_report_active", False):
        toolbar.turn_off_all_tools_after_switch(target_widget=viewport)
    viewport._structured_report_active = True
    viewport._awaiting_series_number = None
    viewport._render_drop_gen = int(getattr(viewport, "_render_drop_gen", 0)) + 1
    controller._hide_spinner_for_widget(viewport)
    stop_cine = getattr(viewport, "stop_cine", None)
    if callable(stop_cine):
        stop_cine()
    slider = getattr(viewport, "slider", None)
    if slider is not None:
        if not hasattr(viewport, "_report_slider_enabled"):
            viewport._report_slider_enabled = slider.isEnabled()
        slider.setEnabled(False)
    if panel is None:
        panel = StructuredReportPanel(viewport)
        viewport._structured_report_panel = panel
    ref = controller._resolve_series_ref(series_number)
    identity = (ref.series_path, ref.study_uid, ref.series_uid) if (
        ref is not None and ref.source != "derived"
    ) else ("", "", "")
    panel.begin(identity)
    return True
