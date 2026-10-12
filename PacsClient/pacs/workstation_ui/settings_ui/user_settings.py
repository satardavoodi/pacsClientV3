"""Server-only human grants; source identity is never created from a display name."""
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QListWidget, QCheckBox, QPushButton, QPlainTextEdit, QInputDialog, QLineEdit)
from modules.LicenseGenerator.async_ui import LicenseOperation
from modules.ai_imaging.eagle_eye_remote import user_administration as administration
from modules.ai_imaging.eagle_eye_remote.usage import GROUP_LABELS


class UserSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = QApplication.instance().property('eagleEyeConsoleSession')
        self.users = []
        self.operation = LicenseOperation(self)
        self.operation.completed.connect(self.render)
        self.operation.failed.connect(lambda _: self.status.setText('User operation failed. Check administrator session and upstream access.'))
        self.operation.busy_changed.connect(self.busy)
        layout = QVBoxLayout(self)
        note = QLabel('PACS or Reception verifies the signed-in client user. Select that user below, '
                      'approve access, then choose EchoMind, Eagle Eye image analysis, Agent or CRM. '
                      'Image analysis also requires the selected module permissions. '
                      'New users and new modules start denied. This page never creates upstream accounts.')
        note.setWordWrap(True); layout.addWidget(note)
        actions = QHBoxLayout()
        self.reload = QPushButton('Reload users')
        self.import_button = QPushButton('Import PACS users')
        self.import_reception_button = QPushButton('Import Reception users')
        self.show_logs = QCheckBox('Show selected user logs')
        self.save = QPushButton('Save selected user permissions')
        for button in (self.reload,self.import_button,self.import_reception_button,self.save): actions.addWidget(button)
        layout.addLayout(actions)
        self.list = QListWidget(); layout.addWidget(self.list)
        self.flags = {key:QCheckBox(label) for key,label in (
            ('enabled','Approved Eagle Eye user'),('echomind','EchoMind'),
            ('imaging','Eagle Eye image analysis'),('crm','Reception CRM'),
            ('secretary','Agent / EchoMind Secretary'))}
        for check in self.flags.values(): layout.addWidget(check)
        self.module_layout = QGridLayout(); layout.addLayout(self.module_layout)
        self.modules = {}
        layout.addWidget(self.show_logs)
        self.audit = QPlainTextEdit(); self.audit.setReadOnly(True); self.audit.hide(); layout.addWidget(self.audit)
        self.status = QLabel('Loading Server users...'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.reload.clicked.connect(self.load)
        self.import_button.clicked.connect(lambda: self.import_users('PACS'))
        self.import_reception_button.clicked.connect(lambda: self.import_users('Reception'))
        self.show_logs.toggled.connect(self.toggle_logs)
        self.save.clicked.connect(self.store)
        self.list.currentRowChanged.connect(self.select)
        self.load()

    def busy(self, busy):
        for widget in (self.reload,self.import_button,self.import_reception_button,self.save,self.list,self.show_logs): widget.setEnabled(not busy)

    def load(self):
        self.operation.start('users',administration.snapshot,self.session)

    def render(self, operation, value):
        if operation == 'history':
            import json
            self.audit.setPlainText(json.dumps(value,indent=2))
            return
        self.users = value['users']
        for module in value['modules']:
            if module not in self.modules:
                check = QCheckBox(GROUP_LABELS['eagle_eye'].get(module,module))
                self.modules[module] = check
                index = len(self.modules) - 1
                self.module_layout.addWidget(check, index // 3, index % 3)
        self.list.blockSignals(True); self.list.clear()
        for user in self.users:
            self.list.addItem(f"{user['username']} â€” {user['provider']} â€” {'Approved' if user['enabled'] else 'Pending approval'}")
        self.list.blockSignals(False)
        self.status.setText('User permissions loaded. Import requires an upstream administrator; imported users remain denied until approved.')
        if self.users: self.list.setCurrentRow(0)

    def select(self, index):
        if not 0 <= index < len(self.users): return
        user = self.users[index]
        for key,check in self.flags.items(): check.setChecked(bool(user[key]))
        for key,check in self.modules.items(): check.setChecked(key in user['modules'])
        self.audit.clear()
        if self.show_logs.isChecked():
            self.operation.start('history',administration.history,self.session,user['principal'])

    def store(self):
        index = self.list.currentRow()
        if not 0 <= index < len(self.users): return
        changes = {key:check.isChecked() for key,check in self.flags.items()}
        changes['modules'] = [key for key,check in self.modules.items() if check.isChecked()]
        self.operation.start('users',administration.save,self.session,self.users[index]['principal'],changes)

    def toggle_logs(self, enabled):
        self.audit.setVisible(enabled)
        if enabled:
            self.select(self.list.currentRow())
        else:
            self.audit.clear()

    def import_users(self, source='PACS'):
        username, accepted = QInputDialog.getText(self,source + ' administrator',source + ' account with administrator permission')
        if not accepted: return
        password, accepted = QInputDialog.getText(self,source + ' administrator',source + ' password',QLineEdit.Password)
        if not accepted: return
        callback = administration.import_reception if source == 'Reception' else administration.import_pacs
        self.operation.start('users',callback,self.session,username,password)
