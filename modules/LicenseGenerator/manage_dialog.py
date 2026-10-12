"""Manage, request and preview a signed renewal without interrupting sign-in."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout)

from .async_ui import LicenseOperation
from .renewal import create_manager
from .signed_license import LicenseError, normalize
from .code_files import read_code, save_request




class ManageLicenseDialog(QDialog):
    license_activated = Signal()

    def __init__(self, parent=None, *, manager=None, activation_required=False):
        super().__init__(parent)
        self.setWindowTitle('Manage License - AI-PACS')
        self.setLayoutDirection(Qt.LeftToRight)
        self.setMinimumSize(680, 620)
        self.activation_required = activation_required
        self.manager = manager
        self._request = ''
        self._preview_code = ''
        self._operation = LicenseOperation(self)
        self._operation.completed.connect(self._completed)
        self._operation.failed.connect(self._failed)
        self._operation.busy_changed.connect(self._busy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel('Manage License')
        title.setStyleSheet('font-size: 23px; font-weight: 600;')
        layout.addWidget(title)
        self.summary = QLabel('Checking license...')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        explanation = QLabel('Extend your license at any time. Your remaining validity is preserved. '
                             'Generate a request, send it to company support, then apply the signed response.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        request_buttons = QHBoxLayout()
        self.generate_button = QPushButton('Generate Renewal Request')
        self.generate_button.clicked.connect(self._generate)
        self.copy_button = QPushButton('Copy Request')
        self.copy_button.clicked.connect(self._copy)
        self.save_button = QPushButton('Save Request File')
        self.save_button.clicked.connect(self._save_request)
        for button in (self.generate_button, self.copy_button, self.save_button):
            request_buttons.addWidget(button)
        layout.addLayout(request_buttons)
        self.request_text = QPlainTextEdit()
        self.request_text.setReadOnly(True)
        self.request_text.setPlaceholderText('Generate a device-specific request to send to company support.')
        self.request_text.setMaximumHeight(95)
        layout.addWidget(self.request_text)
        self.response = QPlainTextEdit()
        self.response.setPlaceholderText('Paste the signed company license response here.')
        self.response.setMaximumHeight(105)
        self.response.textChanged.connect(self._response_changed)
        layout.addWidget(self.response)
        response_buttons = QHBoxLayout()
        self.import_button = QPushButton('Import License File')
        self.import_button.clicked.connect(self._import)
        self.preview_button = QPushButton('Preview Renewal')
        self.preview_button.clicked.connect(self._preview)
        response_buttons.addWidget(self.import_button)
        response_buttons.addWidget(self.preview_button)
        layout.addLayout(response_buttons)
        preview_form = QFormLayout()
        self.current_expiry = QLabel('-')
        self.added_days = QLabel('-')
        self.new_expiry = QLabel('-')
        self.total_days = QLabel('-')
        preview_form.addRow('Current expiry (UTC)', self.current_expiry)
        preview_form.addRow('Purchased additional days', self.added_days)
        preview_form.addRow('New expiry (UTC)', self.new_expiry)
        preview_form.addRow('Days remaining after applying', self.total_days)
        layout.addLayout(preview_form)
        self.message = QLabel('No request has been sent automatically.')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()
        actions = QHBoxLayout()
        self.apply_button = QPushButton('Apply Renewal')
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        self.close_button = QPushButton('Exit Application' if activation_required else 'Close')
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.setStyleSheet('''QDialog {background:#152131;} QLabel {color:#e7eef7;}
            QPlainTextEdit {background:#0f1825; color:#e7eef7; border:1px solid #42516a; border-radius:5px; padding:8px;}
            QPushButton {background:#28425f; color:white; border:1px solid #42516a; border-radius:5px; padding:10px;}
            QPushButton:hover {background:#36597d;} QPushButton:disabled {color:#8592a3;}
        ''')
        self._operation.start('initialize', self._initialize, manager)

    @staticmethod
    def _initialize(manager):
        manager = manager or create_manager()
        return manager, manager.status()

    def _busy(self, busy):
        ready = self.manager is not None and not busy
        self.generate_button.setEnabled(ready)
        self.import_button.setEnabled(ready)
        self.preview_button.setEnabled(ready and bool(self.response.toPlainText().strip()))
        self.copy_button.setEnabled(not busy and bool(self._request))
        self.save_button.setEnabled(not busy and bool(self._request))
        self.apply_button.setEnabled(ready and bool(self._preview_code))
        self.response.setReadOnly(busy)
        # Keep the widget alive until the bounded save finishes, then allow close.
        self.close_button.setEnabled(not busy)

    def reject(self):
        if self._operation.future is None:
            super().reject()

    def _response_changed(self):
        self._preview_code = ''
        for field in (self.current_expiry, self.added_days, self.new_expiry, self.total_days):
            field.setText('-')
        self._busy(self._operation.future is not None)

    def _generate(self):
        self.message.setText('Preparing a renewal request...')
        self._operation.start('request', self.manager.generate_request)

    def _copy(self):
        QApplication.clipboard().setText(self._request)
        self.message.setText('Request copied. Send it to company support. It has not been sent automatically.')

    def _save_request(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Renewal Request', 'renewal-request.aipreq',
                                             'AI-PACS request (*.aipreq);;Text files (*.txt)')
        if path:
            self._operation.start('export', save_request, path, self._request)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import Company License', '',
                                             'AI-PACS license (*.aiplic *.txt);;All files (*)')
        if path:
            self._operation.start('import', read_code, path)

    def _preview(self):
        try:
            code = normalize(self.response.toPlainText())
        except LicenseError as exc:
            self._failed(str(exc))
            self._busy(False)
            return
        self._preview_code = ''
        if not code.startswith('AIP3.') and self.activation_required:
            # Initial install only: old keys remain usable while customers migrate.
            self._preview_code = code
            self.message.setText('Legacy activation key. Applying checks this device and expiry. Future renewals require a signed response.')
            self._busy(False)
            return
        self._operation.start('preview', self.manager.preview, code)

    def _apply(self):
        try:
            code = normalize(self.response.toPlainText())
        except LicenseError as exc:
            self._failed(str(exc))
            return
        if not self._preview_code or code != self._preview_code:
            self.message.setText('Preview the current response before applying it.')
            return
        self._operation.start('apply', self.manager.save_license, code)

    def _completed(self, operation, value):
        if operation == 'initialize':
            self.manager, status = value
            self._show_status(status)
        elif operation == 'status':
            self._show_status(value)
        elif operation == 'request':
            self._request = value
            self.request_text.setPlainText(value)
            self.message.setText('Request ready. Copy or save it and send it to company support.')
        elif operation == 'import':
            self.response.setPlainText(value)
            self.message.setText('License imported. Preview it before applying.')
        elif operation == 'export':
            self.message.setText('Request file saved. Send it to company support.')
        elif operation == 'preview':
            self._preview_code = normalize(self.response.toPlainText())
            self.current_expiry.setText(value['previous_expiry'] or 'Not activated')
            self.added_days.setText('0 (already applied)' if value['already_applied'] else str(value['added_days']))
            self.new_expiry.setText(value['expires_at'])
            self.total_days.setText(str(value['days_remaining']))
            self.message.setText('This license is already applied.' if value['already_applied'] else 'Signature verified. Ready to apply.')
        elif operation == 'apply':
            success, message = value
            self.message.setText(message)
            if success:
                self.license_activated.emit()
                self._preview_code = ''
                if self.activation_required:
                    self.accept()
                else:
                    self._operation.start('status', self.manager.status)

    def _show_status(self, status):
        product = 'Eagle Eye Server' if status['product'] == 'eagle-eye-server' else 'AI-PACS Client'
        self.summary.setText(f"{product} | {status['message']}\nExpiry (UTC): {status.get('expires_at', '-')}")
        if self.activation_required and not status['valid']:
            self.generate_button.setText('Generate Activation Request')

    def _failed(self, message):
        self.message.setText(message)
        self._preview_code = ''
