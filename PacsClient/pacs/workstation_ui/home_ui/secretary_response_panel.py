"""Readable Secretary replies with optional local asynchronous English speech."""
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, Signal, QEvent, QPoint
from PySide6.QtGui import QFont
import qtawesome as qta
from PacsClient.utils.scroll_style import get_scroll_area_style
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPlainTextEdit, QPushButton, QCheckBox, QLineEdit


def local_english_speech(parent):
    # SAPI uses installed Windows voices; never send reply text to a provider.
    from PySide6.QtTextToSpeech import QTextToSpeech
    if "sapi" not in QTextToSpeech.availableEngines():
        return None
    speech = QTextToSpeech("sapi", parent)
    locales = [locale for locale in speech.availableLocales()
               if locale.language() == QLocale.Language.English]
    if not locales:
        speech.deleteLater()
        return None
    speech.setLocale(locales[0])
    return speech


class SecretaryResponsePanel(QDialog):
    detailsRequested = Signal()
    commandSubmitted = Signal(str)

    def __init__(self, parent=None, *, speech_factory=local_english_speech):
        super().__init__(parent)
        self.setObjectName("SecretaryResponseSurface")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QDialog#SecretaryResponseSurface {
                background-color: #172334;
                border: 1px solid #455b70;
                border-radius: 8px;
            }
        """)
        self.setFont(QFont("Segoe UI", 10))
        self.setWindowTitle("Secretary EchoMind")
        self.setModal(False)
        self.resize(560, 340)
        layout = QVBoxLayout(self)
        self._expanded = False
        self._header_fraction = .5
        self._drag_start = None
        self._title = QLabel("Secretary response")
        header = QHBoxLayout()
        header.addWidget(self._title, 1)
        self.expand_button = QPushButton("Open", self)
        self.expand_button.setToolTip("Open the full conversation")
        self.expand_button.clicked.connect(lambda: self.open_response(expanded=not self._expanded))
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        header.addWidget(self.expand_button)
        header.addWidget(close_button)
        self.secretary_icon = QLabel(self)
        self.secretary_icon.setPixmap(qta.icon('fa5s.user-tie', color='#a9e7f3').pixmap(24, 24))
        self.secretary_icon.setFixedSize(30, 28)
        self.secretary_icon.setAlignment(Qt.AlignCenter)
        self.secretary_icon.setAccessibleName('Secretary Command')
        self.secretary_icon.setToolTip('Secretary Command - drag left or right')
        self.secretary_icon.setCursor(Qt.SizeHorCursor)
        self.secretary_icon.installEventFilter(self)
        header.addWidget(self.secretary_icon)
        layout.addLayout(header)
        if parent is not None:
            parent.installEventFilter(self)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        # Reuse the same Material keyboard arrows as the Settings fields.
        up_arrow = Path("Qss/icons/fefefe/material_design/keyboard_arrow_up.png").resolve().as_posix()
        down_arrow = Path("Qss/icons/fefefe/material_design/keyboard_arrow_down.png").resolve().as_posix()
        self.text.verticalScrollBar().setStyleSheet(get_scroll_area_style() + f"""
            QScrollBar:vertical {{ width: 16px; margin: 12px 0 12px 0; }}
            QScrollBar::handle:vertical {{ min-height: 6px; }}
            QScrollBar::sub-line:vertical {{ subcontrol-position: top; height: 12px; width: 16px; background: #263b50; }}
            QScrollBar::add-line:vertical {{ subcontrol-position: bottom; height: 12px; width: 16px; background: #263b50; }}
            QScrollBar::up-arrow:vertical {{ image: url("{up_arrow}"); width: 12px; height: 12px; }}
            QScrollBar::down-arrow:vertical {{ image: url("{down_arrow}"); width: 12px; height: 12px; }}
        """)
        self.text.setStyleSheet("QPlainTextEdit { font-family: 'Segoe UI'; font-size: 16px; padding: 10px; }")
        self.text.document().setMaximumBlockCount(300)
        layout.addWidget(self.text, 1)
        self.status = QLabel("Text response ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QGridLayout()
        self.play = QPushButton("Read aloud")
        self.stop_button = QPushButton("Stop")
        self.auto_voice = QCheckBox("Speak new replies")
        self.include_screen = QCheckBox('Include screen context')
        self.include_screen.setToolTip('Send redacted UI controls to Eagle Eye with the next request. Clinical images and text field values are excluded.')
        details = QPushButton("Details")
        for index, widget in enumerate((self.play, self.stop_button, self.auto_voice, details)):
            row.addWidget(widget, index // 2, index % 2)
        row.addWidget(self.include_screen,2,0,1,2)
        layout.addLayout(row)
        composer = QHBoxLayout()
        self.command_input = QLineEdit(self)
        self.command_input.setPlaceholderText("Type a command...")
        self.command_input.setAccessibleName("Secretary command")
        self.command_input.setMaxLength(20000)
        send = QPushButton("Send", self)
        send.clicked.connect(self._submit_command)
        self.command_input.returnPressed.connect(self._submit_command)
        composer.addWidget(self.command_input, 1)
        composer.addWidget(send)
        layout.addLayout(composer)
        self._full_controls = [self.status, self.play, self.stop_button,
                               self.auto_voice, self.include_screen, details, self.command_input, send]
        self._speech = None
        self._muted = False
        try:
            self._speech = speech_factory(self)
        except Exception:
            pass
        self.play.setEnabled(self._speech is not None)
        self.stop_button.setEnabled(self._speech is not None)
        self.auto_voice.setEnabled(self._speech is not None)
        if self._speech is None:
            self.status.setText("English voice unavailable. Text responses remain available.")
        else:
            signal = getattr(self._speech, "errorOccurred", None)
            if signal is not None:
                signal.connect(self._speech_error)
            state_signal = getattr(self._speech, "stateChanged", None)
            if state_signal is not None:
                state_signal.connect(self._speech_state)
        self.play.clicked.connect(self.speak)
        self.stop_button.clicked.connect(self.stop)
        details.clicked.connect(self.detailsRequested.emit)

    def _submit_command(self):
        text = self.command_input.text().strip()
        if text:
            self.commandSubmitted.emit(text)

    def _speech_state(self, state):
        from PySide6.QtTextToSpeech import QTextToSpeech
        if state == QTextToSpeech.State.Ready:
            self.status.setText("Text response ready")

    def _speech_error(self, *args):
        self.status.setText("Voice playback unavailable. You can read the response above.")
        self.auto_voice.setChecked(False)

    def set_response(self, text):
        self.stop()
        if self._speech is not None:
            self.status.setText("Text response ready")
        self.text.setPlainText(str(text or ""))
        if self.auto_voice.isChecked():
            self.speak()

    def speak(self):
        if self._speech is None or self._muted:
            return
        text = self.text.toPlainText().strip()
        # English voice does not translate a reply in another language.
        if not text or any("\u0600" <= char <= "\u06ff" for char in text):
            self.status.setText("English voice is available for English replies.")
            return
        self.stop()
        try:
            self._speech.say(text[:4000])
            self.status.setText("Playing English response")
        except Exception:
            self._speech_error()

    def stop(self):
        if self._speech is not None:
            try:
                self._speech.stop()
            except Exception:
                pass

    def set_muted(self, muted):
        self._muted = bool(muted)
        if self._muted:
            self.stop()
        self.play.setEnabled(self._speech is not None and not self._muted)

    def _header_metrics(self):
        host = self.parentWidget()
        logo = host.findChild(QPushButton, "LogoButton") if host is not None else None
        if logo is not None:
            return logo.mapTo(host, QPoint(0, 0)).y(), logo.height()
        return 8, 70

    def _position_header_response(self):
        host = self.parentWidget()
        if host is None:
            return
        # Middle third of the application's top header, above the study toolbar.
        width = max(1, host.width() // 3)
        travel = max(0, host.width() - width)
        top, collapsed_height = self._header_metrics()
        height = min(340, max(collapsed_height, host.height() - top - 8)) if self._expanded else collapsed_height
        self.setGeometry(round(travel * self._header_fraction), top, width, height)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "secretary_icon", None) and self.parentWidget() is not None:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_start = (event.globalPosition().x(), self.x())
                return True
            if event.type() == QEvent.MouseMove and self._drag_start is not None:
                host = self.parentWidget()
                travel = max(0, host.width() - self.width())
                start, original_x = self._drag_start
                x = max(0, min(travel, round(original_x + event.globalPosition().x() - start)))
                self._header_fraction = x / travel if travel else .5
                self.move(x, self._header_metrics()[0])
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self._drag_start = None
                return True
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._position_header_response()
        return super().eventFilter(watched, event)

    def open_response(self, *, expanded=False):
        self._expanded = bool(expanded or self.parentWidget() is None)
        flags = Qt.Widget if self.parentWidget() is not None else Qt.Dialog
        if self.windowType() != flags:
            self.setWindowFlags(flags)
        for control in self._full_controls:
            control.setVisible(self._expanded)
        self._title.setVisible(self._expanded)
        self.expand_button.setVisible(True)
        self.expand_button.setText("Collapse" if self._expanded else "Open")
        self.expand_button.setIcon(qta.icon("fa5s.chevron-up" if self._expanded else "fa5s.chevron-down", color="#a9e7f3"))
        self.layout().setContentsMargins(6, 4, 6, 4)
        self.layout().setSpacing(2 if not self._expanded else 6)
        self.text.setStyleSheet("QPlainTextEdit { font-family: 'Segoe UI'; font-size: 14px; padding: 2px; }")
        if self.parentWidget() is None:
            screen = self.screen()
            if screen:
                available = screen.availableGeometry()
                self.resize(min(560, available.width()), min(340, available.height()))
                self.move(available.center() - self.rect().center())
        else:
            self._position_header_response()
        self.show()
        self.raise_()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
