"""Worker-backed CRM page using shared Eagle Eye pairing and reception identity."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QComboBox, QPlainTextEdit)
from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError


_TASKS = set()


class Task(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.completed.emit(self.operation())
        except ServerHTTPError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit('CRM request failed. Check Eagle Eye connection, CRM readiness and reception access.')
        finally:
            self.operation = None


class CRMSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.client = None
        self.worker = None
        self.conversation = None
        self.completion = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Reception CRM'))
        note = QLabel('Uses the authenticated Eagle Eye Server connection. Reception sign-in grants '
                      'user access. Report and Analysis are read-only. Configure reception sources on the server.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.username = QLineEdit()
        self.username.setPlaceholderText('Reception username')
        self.password = QLineEdit()
        self.password.setPlaceholderText('Reception password')
        self.password.setEchoMode(QLineEdit.Password)
        self.login_button = QPushButton('Sign in to reception')
        self.login_button.clicked.connect(self.login)
        row = QHBoxLayout()
        for widget in (self.username, self.password, self.login_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.mode = QComboBox()
        self.mode.addItem('Report', 'report')
        self.mode.addItem('Analysis', 'analysis')
        layout.addWidget(self.mode)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText('Ask about admissions, cashier activity, reports or appointments.')
        self.question.setMaximumHeight(110)
        layout.addWidget(self.question)
        self.send_button = QPushButton('Send')
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send)
        layout.addWidget(self.send_button)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

    def execute(self, operation, done):
        if self.worker is not None:
            return
        self.login_button.setEnabled(False)
        self.send_button.setEnabled(False)
        worker = Task(operation, self)
        _TASKS.add(worker)
        worker.finished.connect(lambda: (_TASKS.discard(worker), worker.deleteLater()))
        self.worker = worker
        self.completion = done
        worker.completed.connect(self.complete)
        worker.failed.connect(self.output.setPlainText)
        worker.finished.connect(self.retire)
        worker.start()

    def complete(self, result):
        if self.completion:
            self.completion(result)

    def retire(self):
        worker, self.worker = self.worker, None
        self.completion = None
        if worker:
            worker.deleteLater()
        self.login_button.setEnabled(True)
        self.send_button.setEnabled(bool(self.client and self.client.session))

    def login(self):
        username, password = self.username.text(), self.password.text()
        self.password.clear()
        def operation():
            from modules.ai_imaging.eagle_eye_remote.crm.client import CRMClient
            client = CRMClient()
            client.login(username, password)
            return client
        def done(client):
            self.client = client
            self.conversation = None
            self.output.setPlainText('Reception sign-in accepted. Read-only CRM is ready.')
        self.execute(operation, done)

    def send(self):
        if not self.client or not self.question.toPlainText().strip():
            return
        text, mode, conversation = self.question.toPlainText(), self.mode.currentData(), self.conversation
        client = self.client
        def operation():
            import uuid
            cid = conversation
            if not cid:
                result = client.request('conversations/create', {'mode': mode})
                cid = result.get('conversation', {}).get('id')
                if not cid:
                    raise ValueError('CRM conversation could not be created.')
            result = client.request('command', {'text': text, 'mode': mode,
                'conversationId': cid, 'requestId': uuid.uuid4().hex, 'source': 'eagle_eye_ui'})
            return cid, result
        def done(value):
            self.conversation, result = value
            self.output.setPlainText(result.get('message') or result.get('answer') or 'CRM returned no display text.')
        self.execute(operation, done)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)
