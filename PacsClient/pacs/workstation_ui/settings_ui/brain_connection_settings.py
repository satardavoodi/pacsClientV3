"""Worker-backed shared Server 1 authentication and model-independent call totals."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QGroupBox, QFormLayout, QPlainTextEdit
from .crm_settings import Task, _TASKS

class BrainConnectionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.snapshot = None
        layout = QVBoxLayout(self)
        note = QLabel('Select LLM G, LLM A, LLM V or your own Custom API. Shared company credentials for EchoMind, Secretary, Agent and CRM. Models and prompts remain workflow-owned. Counts below are upstream calls, including internal calls, across all models; workflow request counts are shown separately. Usage starts when this accounting revision is activated.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.profile = QComboBox()
        for label,key in [('Server 1 - LLM G','server_1'),('Server 2 - LLM A','server_2'),('Server 3 - LLM V','server_3'),('Custom API','custom')]:
            self.profile.addItem(label,key)
        layout.addWidget(self.profile)
        self.save_profile_button=QPushButton('Save Brain connection')
        layout.addWidget(self.save_profile_button)
        self.proxy_group = QGroupBox('Shared Brain network / proxy')
        proxy_form = QFormLayout(self.proxy_group)
        self.proxy_type = QComboBox()
        self.proxy_type.addItem('Direct', 'direct')
        self.proxy_type.addItem('SOCKS5 - 127.0.0.1', 'socks5')
        from PySide6.QtWidgets import QSpinBox
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(2080)
        self.proxy_save = QPushButton('Save shared Brain proxy')
        proxy_form.addRow('Connection', self.proxy_type)
        proxy_form.addRow('Proxy port', self.proxy_port)
        proxy_form.addRow(self.proxy_save)
        layout.addWidget(self.proxy_group)
        self.proxy_save.clicked.connect(self.save_proxy)
        self.custom_group=QGroupBox('Custom API - own credentials, models and prompts')
        form=QFormLayout(self.custom_group)
        self.custom_fields={}
        from modules.ai_imaging.eagle_eye_remote.brain_profiles import CUSTOM_FIELDS
        for key in ('openai_api_key',)+CUSTOM_FIELDS:
            field=QPlainTextEdit() if key.startswith('prompt_') else QLineEdit()
            if isinstance(field,QPlainTextEdit):field.setMaximumHeight(100)
            if key=='openai_api_key':field.setEchoMode(QLineEdit.Password)
            labels = {'prompt_report_mri': 'MRI report prompt',
                      'prompt_report_ct': 'CT Scan report prompt',
                      'prompt_report_sonography': 'Ultrasound report prompt',
                      'prompt_report_obstetrics': 'Obstetrics report prompt',
                      'prompt_report_cardiology': 'Cardiology report prompt',
                      'prompt_report_generation': 'Other EchoMind workflows prompt'}
            form.addRow(labels.get(key, key.replace('openai_','').replace('prompt_','Prompt ').replace('_',' ').title()),field)
            self.custom_fields[key]=field
        self.custom_fields['openai_base_url'].setPlaceholderText('https://api.openai.com/v1')
        layout.addWidget(self.custom_group)
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.save_profile_button.clicked.connect(self.save_profile)
        self.code = QLineEdit()
        self.code.setEchoMode(QLineEdit.Password)
        self.code.setPlaceholderText('Eagle AI Brain center access code')
        self.auth = QPushButton('Authenticate LLM G')
        self.test = QPushButton('Test selected Brain connection')
        self.refresh = QPushButton('Refresh selected Brain usage')
        self.status = QLabel('Loading private server connection...')
        self.status.setWordWrap(True)
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        for widget in (self.code, self.auth, self.test, self.refresh, self.status, self.totals):
            layout.addWidget(widget)
        self.auth.clicked.connect(self.authenticate)
        self.refresh.clicked.connect(self.load)
        self.test.clicked.connect(self.test_connection)
        self.profile_changed()
        self.load()

    def save_proxy(self):
        if not self.snapshot:
            return
        from modules.ai_imaging.eagle_eye_remote.brain_administration import save_proxy
        revision = self.snapshot['revision']
        options = {'connection_type': self.proxy_type.currentData(), 'proxy_port': self.proxy_port.value()}
        self.execute(lambda: save_proxy(revision, options))

    def profile_changed(self):
        self.custom_group.setVisible(self.profile.currentData()=='custom')
        if hasattr(self,'code'):
            self.code.setVisible(self.profile.currentData()=='server_1')
            self.auth.setVisible(self.profile.currentData()=='server_1')

    def save_profile(self):
        if not self.snapshot:return
        from modules.ai_imaging.eagle_eye_remote.brain_administration import save_profile
        values={key:(field.toPlainText() if isinstance(field,QPlainTextEdit) else field.text()) for key,field in self.custom_fields.items()} if self.profile.currentData()=='custom' else {}
        revision,selected=self.snapshot['revision'],self.profile.currentData()
        self.custom_fields['openai_api_key'].clear()
        self.execute(lambda:save_profile(revision,selected,values))

    def execute(self, operation):
        if self.worker:
            return
        self.proxy_save.setEnabled(False)
        self.save_profile_button.setEnabled(False)
        self.profile.setEnabled(False)
        self.auth.setEnabled(False)
        self.test.setEnabled(False)
        self.refresh.setEnabled(False)
        worker = self.worker = Task(operation, None)
        _TASKS.add(worker)
        worker.completed.connect(self.render)
        worker.failed.connect(lambda _: self.status.setText('Brain operation failed. Check the selected profile, API settings and model readiness. Reload before retrying.'))
        worker.finished.connect(self.retire)
        worker.finished.connect(lambda: (_TASKS.discard(worker), worker.deleteLater()))
        worker.start()

    def retire(self):
        self.worker = None
        self.proxy_save.setEnabled(True)
        self.save_profile_button.setEnabled(True)
        self.profile.setEnabled(True)
        self.auth.setEnabled(True)
        self.test.setEnabled(True)
        self.refresh.setEnabled(True)

    def load(self):
        from modules.ai_imaging.eagle_eye_remote.brain_administration import snapshot
        self.execute(snapshot)

    def test_connection(self):
        if not self.snapshot or self.snapshot.get('selected','server_1')!=self.profile.currentData():
            self.status.setText('Save the selected Brain connection before testing.')
            return
        from modules.ai_imaging.eagle_eye_remote.brain_administration import test_connection
        self.execute(test_connection)

    def authenticate(self):
        if not self.snapshot:
            return
        from modules.ai_imaging.eagle_eye_remote.brain_administration import authenticate
        revision, code = self.snapshot['revision'], self.code.text()
        self.code.clear()
        self.execute(lambda: authenticate(revision, code))

    def render(self, value):
        self.snapshot = value
        proxy = value.get('proxy', {})
        self.proxy_type.setCurrentIndex(max(0, self.proxy_type.findData(proxy.get('connection_type', 'direct'))))
        self.proxy_port.setValue(proxy.get('proxy_port', 2080))
        self.profile.setCurrentIndex(max(0,self.profile.findData(value.get('selected','server_1'))))
        for key,text in value.get('custom',{}).items():
            field=self.custom_fields[key]
            field.setPlainText(text) if isinstance(field,QPlainTextEdit) else field.setText(text)
        self.profile_changed()
        self.status.setText('Selected Brain credential configured. This is not a live provider acceptance test.' if value['authenticated'] else 'Authenticate Eagle AI Brain with the existing center access code.')
        if 'connection_ok' in value:
            self.status.setText('Selected Brain connection test passed.' if value['connection_ok'] else 'Selected Brain connection test failed.')
        if value.get('selected') in ('server_2','server_3'):
            self.status.setText('Connection reserved. Model/API readiness is pending; inference and automatic fallback are disabled.')
            if value.get('transport_only'):
                self.status.setText('Network connection succeeded; model/API not ready.' if value.get('connection_ok') else 'Network connection unavailable or API port not configured. Model/API not ready.')
        lines = []
        for row in value['usage']['groups']:
            total = row['total_tokens'] if row['total_tokens'] is not None else 'Not reported'
            lines.append(f"{row['label']}: {row['calls']} provider calls; {total} reported tokens; {row['failed']} failed; {row['pending']} pending; {row['missing_usage']} without complete token usage")
        self.totals.setText('\n'.join(lines))
