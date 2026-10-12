"""CRM connection controls, with server-only private configuration attachment."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox
from .crm_settings import Task, _TASKS


class CRMConnectionsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.snapshot = None
        layout = QVBoxLayout(self)
        note = QLabel('CRM uses the shared Eagle Eye HTTP connection and AI provider gateway. '
                      'Reception credentials and data-source settings stay on the server. '
                      'Configuration changes apply after a controlled service restart.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enabled = QCheckBox('Enable hosted read-only CRM')
        self.directory = QLineEdit()
        self.directory.setPlaceholderText('Private server CRM configuration directory')
        self.save = QPushButton('Save CRM service configuration')
        self.reload = QPushButton('Reload')
        self.test = QPushButton('Test CRM Connection')
        self.test.clicked.connect(self.test_connection)
        self.status = QLabel('Loading CRM connection configuration...')
        self.status.setWordWrap(True)
        for widget in (self.enabled, self.directory, self.save, self.reload, self.test, self.status):
            layout.addWidget(widget)
        self.save.clicked.connect(self.store)
        self.reload.clicked.connect(self.load)
        self.load()

    def execute(self, operation):
        if self.worker:
            return
        self.test.setEnabled(False)
        self.save.setEnabled(False)
        self.reload.setEnabled(False)
        self.worker = worker = Task(operation, None)
        _TASKS.add(worker)
        worker.completed.connect(self.render)
        worker.failed.connect(self.status.setText)
        worker.finished.connect(self.retire)
        worker.finished.connect(lambda: (_TASKS.discard(worker), worker.deleteLater()))
        worker.start()

    def load(self):
        from modules.ai_imaging.eagle_eye_remote.crm import administration
        self.execute(administration.snapshot)

    def store(self):
        if not self.snapshot or not self.snapshot.get('editable'):
            return
        from modules.ai_imaging.eagle_eye_remote.crm import administration
        snapshot, directory, enabled = self.snapshot, self.directory.text(), self.enabled.isChecked()
        self.execute(lambda: administration.attach(snapshot['path'], snapshot['revision'], directory, enabled))

    def test_connection(self):
        from modules.ai_imaging.eagle_eye_remote.crm import administration
        self.execute(administration.test_connection)

    def render(self, snapshot):
        if snapshot.get('diagnostic'):
            lines = [f"Reception API: {snapshot['api']['status']} (port {snapshot['api'].get('port', 'configured')})",
                     f"Local MongoDB: {snapshot['mongo']['status']} (127.0.0.1:27017)"]
            lines.extend(f"{row['name']}: {row['status']} - {row['path']}" for row in snapshot['folders'])
            lines.append('For failures, check the configured API credentials/port, MongoDB service, or folder access. No patient records were queried.')
            self.status.setText('\n'.join(lines))
            return
        self.snapshot = snapshot
        editable = snapshot.get('editable', False)
        self.enabled.setChecked(snapshot.get('enabled', False))
        self.directory.setText(snapshot.get('config_dir', ''))
        self.enabled.setVisible(editable)
        self.directory.setVisible(editable)
        self.save.setVisible(editable)
        self.test.setVisible(editable)
        self.status.setText('Private server configuration loaded; service activation is separate.' if editable
                            else 'Use the Eagle Eye connection above. Sign in to reception in AI > CRM.')

    def retire(self):
        self.worker = None
        self.test.setEnabled(bool(self.snapshot and self.snapshot.get('editable')))
        self.reload.setEnabled(True)
        self.save.setEnabled(bool(self.snapshot and self.snapshot.get('editable')))
