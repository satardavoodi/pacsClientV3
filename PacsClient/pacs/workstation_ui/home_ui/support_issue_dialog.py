"""User-reviewed issue form. Workers own all diagnostic, disk and network work."""
from PySide6.QtCore import QDateTime, QTimer, Qt, Signal
from queue import SimpleQueue, Empty
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog,
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from PacsClient.utils.support_diagnostics import OperationStore


def _microphone_icon():
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    svg = QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="#30496E" stroke-width="2" stroke-linecap="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></g></svg>')
    pixels = QPixmap(24, 24)
    pixels.fill(Qt.transparent)
    painter = QPainter(pixels)
    QSvgRenderer(svg).render(painter)
    painter.end()
    return QIcon(pixels)


class SupportIssueDialog(QDialog):
    deliveryChanged = Signal(dict)

    def __init__(self, user, connection_name='', description='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Report an AI-PACS issue')
        self.setMinimumSize(420, 420)
        self.resize(560, 480)
        self.user = user
        self.connection_name = connection_name
        self.app_version = QApplication.applicationVersion() or 'unknown'
        self._operations = OperationStore()
        self._operation = None
        self._delivery_progress = SimpleQueue()
        self._delivery_active = False
        self._ticket_recordings = []
        self._voice_take = None
        self._voice_context = None
        self.public_result = {'state':'awaiting_local_input', 'ticket_submitted':False}
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        hint = QLabel('Describe what happened and what you expected. Use Speak issue to dictate instead of typing. Do not include patient details, passwords or access tokens.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        identity = QLabel(f'PACS user: {user}\nConnection: {connection_name or "Not reported"}\nVersion: {self.app_version}')
        identity.setTextFormat(Qt.PlainText)
        identity.setWordWrap(True)
        layout.addWidget(identity)
        self.identity_label = identity
        self.category = QComboBox()
        for label, value in [('Error','error'), ('Crash','crash'), ('Hang / freeze','hang'), ('Other','other')]:
            self.category.addItem(label, value)
        layout.addWidget(QLabel('Issue category'))
        layout.addWidget(self.category)
        self.incident_time = QDateTimeEdit(QDateTime.currentDateTime())
        self.incident_time.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.incident_time.setCalendarPopup(True)
        layout.addWidget(QLabel('When did the issue occur? (local time)'))
        layout.addWidget(self.incident_time)
        self.description = QPlainTextEdit(description)
        self.description.setPlaceholderText('What were you doing? What happened? Can it be reproduced?')
        self.description.setAccessibleName('Issue description')
        self.voice = QPushButton('Speak issue')
        self.voice.setIcon(_microphone_icon())
        self.voice.setAccessibleName('Record issue description by voice')
        self.voice.setToolTip('Record up to two minutes, then stop to transcribe. Review the text before sending.')
        self.voice.clicked.connect(self._voice_clicked)
        layout.addWidget(self.voice)
        layout.addWidget(self.description)
        voice_hint = QLabel('Voice uses your current EchoMind Voice to Text settings. The recording is included in the Help Ticket package sent after your review. You can edit the text before sending.')
        voice_hint.setWordWrap(True)
        layout.addWidget(voice_hint)
        self.windows = QCheckBox('Include Windows crash / hang fields (last 24 hours)')
        layout.addWidget(self.windows)
        self.log_archive = QCheckBox('Attach raw log ZIP from the last 24 hours (may include sensitive information)')
        layout.addWidget(self.log_archive)
        notice = QLabel('Summaries exclude raw messages. The optional ZIP includes raw log text and may contain patient details or credentials; select it only if you agree to share those logs privately with AI-PACS support. Timestamped records are filtered to 24 hours; untimed files use modification time and may include older records. ZIP limits: 32 files, 8 MiB total read, 2 MiB compressed. Images and memory dumps are excluded from uploads. Help Ticket packages retain recordings and reports locally and upload them after your review. Reports are retained for 90 days; encrypted failed sends expire after 7 days.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.consent = QCheckBox('I reviewed this report and agree to send it.')
        layout.addWidget(self.consent)
        self.status = QLabel('Ready. An AI-PACS website account must be linked in Settings.')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.status)
        row = QHBoxLayout()
        self.send = QPushButton('Send issue')
        self.send.setEnabled(False)
        self.retry = QPushButton('Retry pending issue')
        self.retry.setEnabled(False)
        self.discard = QPushButton('Discard pending issue')
        self.discard.setEnabled(False)
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.close)
        self.send.clicked.connect(self._submit)
        self.retry.clicked.connect(self._retry)
        self.discard.clicked.connect(self._discard)
        self.consent.toggled.connect(self._buttons)
        self.description.textChanged.connect(self._buttons)
        for button in (self.send, self.retry):
            row.addWidget(button)
        outer.addLayout(row)
        second_row = QHBoxLayout()
        second_row.addWidget(self.discard)
        second_row.addWidget(self.close_button)
        outer.addLayout(second_row)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        user_key = self.user
        def restore():
            from PacsClient.utils.support_issue_reporting import ProtectedOutbox
            from datetime import datetime, timezone
            store = ProtectedOutbox(user_key)
            record = store.load()
            if record and datetime.fromisoformat(record['expires_at']) <= datetime.now(timezone.utc):
                store.clear()
                record = None
            receipt = None
            if record is None:
                from modules.Identity.providers.aipacs_web import get_aipacs_web_client
                client = get_aipacs_web_client(user_key)
                if client is not None:
                    from PacsClient.utils.support_issue_reporting import load_delivery_receipt
                    receipt = load_delivery_receipt(user_key,client)
            return {'state':'draft_loaded', 'record':record, 'receipt':receipt}
        self._start(restore)

    def _buttons(self):
        enabled = self._operation is None and self.public_result['state'] != 'received'
        self.send.setEnabled(enabled and self.public_result['state'] != 'pending' and self.consent.isChecked() and 5 <= len(self.description.toPlainText().strip()) <= 4000)
        self.retry.setEnabled(enabled and self.public_result['state'] == 'pending' and self.consent.isChecked())
        self.discard.setEnabled(enabled and self.public_result['state'] == 'pending')
        recording = self._voice_take is not None and not self._voice_take.stopped.is_set()
        self.voice.setEnabled(recording or (enabled and self.public_result['state'] != 'pending' and len(self._ticket_recordings) < 10))
        self.voice.setText('Stop and transcribe' if recording else 'Speak issue')

    def _voice_clicked(self):
        if self._voice_take is not None:
            self._voice_take.stop()
            self.status.setText('Transcribing your issue description...')
            self._buttons()
            return
        if self._operation is not None or not self.voice.isEnabled() or not self._context_is_current(check_connection=True):
            return
        home = self.parentWidget()
        secretary = home.findChild(QWidget, 'secretaryButtonWidget') if home else None
        if secretary is not None and (getattr(secretary, '_rec_running', False) or getattr(secretary, '_secretary_busy', False)):
            self.status.setText('Finish the active Secretary recording or request before dictating an issue.')
            return
        from PacsClient.utils.support_issue_voice import IssueVoiceTake
        take = IssueVoiceTake()
        take.retain_audio = True
        self._voice_take = take
        self._voice_context = (self.user, self.connection_name)
        self._voice_original = self.description.toPlainText()
        self.description.setReadOnly(True)
        self._operation = self._operations.start('issue_dictation', take.run)['operation_id']
        self.status.setText('Listening... Describe the problem, then click Stop and transcribe. Maximum two minutes.')
        self._buttons()
        self._timer.start()

    def closeEvent(self, event):
        if self._voice_take is not None:
            self._voice_take.cancel()
        self._timer.stop()
        super().closeEvent(event)

    def _start(self, worker, delivery=False):
        self._delivery_active = delivery
        self._operation = self._operations.start('issue_submission', worker)['operation_id']
        self.status.setText('Preparing and sending the Help Ticket...' if delivery else 'Loading the local Help Ticket...')
        if delivery:
            self.public_result = {'state':'running', 'ticket_submitted':False}
            self.deliveryChanged.emit(dict(self.public_result))
        self._buttons()
        self._timer.start()

    def _submit(self):
        if not self.send.isEnabled():
            return
        if not self._context_is_current(check_connection=True):
            return
        text, category, windows = self.description.toPlainText().strip(), self.category.currentData(), self.windows.isChecked()
        occurred_at = self.incident_time.dateTime().toUTC().toString(Qt.ISODateWithMs)
        archive = self.log_archive.isChecked()
        recordings = tuple(self._ticket_recordings)
        # Capture only GUI-owned scalar context before starting the worker.
        context = {'app_version':self.app_version, 'pacs_user':self.user,
                   'center_id':self.connection_name or None, 'server_id':None}
        user = self.user
        progress = self._delivery_progress.put
        def submit():
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client
            from PacsClient.utils.support_issue_reporting import IssueReporter
            client = get_aipacs_web_client(user)
            if client is None:
                return {'state':'failed', 'error_code':'WEBSITE_ACCOUNT_REQUIRED'}
            from PacsClient.utils import get_selectable_server
            selected = get_selectable_server(context['center_id']) if context['center_id'] else None
            if selected:
                context['server_id'] = str(selected.get('profile_id') or selected.get('id') or selected.get('name') or '')[:191] or None
            return IssueReporter(user, client, progress=progress).submit(text, category, windows, context, occurred_at=occurred_at, include_log_archive=archive, recordings=recordings)
        self._start(submit, delivery=True)

    def _retry(self):
        if not self.retry.isEnabled():
            return
        if not self._context_is_current():
            return
        user = self.user
        progress = self._delivery_progress.put
        def retry():
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client
            from PacsClient.utils.support_issue_reporting import IssueReporter
            client = get_aipacs_web_client(user)
            if client is None:
                return {'state':'failed', 'error_code':'WEBSITE_ACCOUNT_REQUIRED'}
            return IssueReporter(user, client, progress=progress).retry()
        self._start(retry, delivery=True)

    def _discard(self):
        if not self.discard.isEnabled():
            return
        if not self._context_is_current():
            return
        if QMessageBox.question(self, 'Discard pending issue',
                'Remove the local pending request? If support already received it, the server copy will remain.',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        user = self.user
        def discard():
            from PacsClient.utils.support_issue_reporting import ProtectedOutbox, _LOCK
            with _LOCK:
                ProtectedOutbox(user).clear()
            return {'state':'discarded'}
        self._start(discard)

    def _context_is_current(self, check_connection=False):
        home = self.parentWidget()
        if home is None:
            return True
        from modules.Identity.ui.host_user import resolve_host_auth_user
        auth = resolve_host_auth_user(home) or {}
        panel = getattr(home, 'data_access_panel_widget', None)
        selected = str(getattr(panel, 'server_selected', '') or '')
        if auth.get('username') != self.user or (check_connection and selected != self.connection_name):
            self.status.setText('PACS account or connection changed. Close this form and reopen it in the intended session.')
            return False
        return True

    def _poll(self):
        try:
            latest = None
            while True:
                latest = self._delivery_progress.get_nowait()
        except Empty:
            if latest is not None:
                self.status.setText(f"Sending Help Ticket: {latest['completed_chunks']} of {latest['total_chunks']} parts received.")
                self.deliveryChanged.emit(dict(latest))
        result = self._operations.status(self._operation)
        if result['state'] == 'running':
            if self._voice_take is not None and self._voice_take.stopped.is_set():
                self.voice.setEnabled(False)
                self.voice.setText('Transcribing...')
            return
        self._timer.stop()
        self._operation = None
        loaded = result.get('data', {})
        if self._voice_take is not None:
            self._voice_take = None
            self.description.setReadOnly(False)
            if (loaded.get('state') == 'voice_transcribed' and self._voice_context == (self.user, self.connection_name)
                    and self._context_is_current(check_connection=True)):
                text = loaded['text']
                combined = (self._voice_original.strip()+'\n\n'+text).strip()
                if len(combined) <= 4000:
                    self.description.setPlainText(combined)
                    if loaded.get("recording") and len(self._ticket_recordings) < 10:
                        self._ticket_recordings.append(loaded["recording"])
                    self.consent.setChecked(False)
                    self.status.setText('Voice transcribed. Review or edit the description, confirm consent, then click Send issue.')
                else:
                    self.status.setText('The combined description exceeds 4000 characters. Shorten the existing text before dictating again.')
            elif loaded.get('state') == 'voice_transcribed':
                self.status.setText('PACS account or connection changed. The voice result was discarded; reopen the form in the intended session.')
            else:
                self.status.setText('Voice could not be transcribed. Check your microphone and Voice to Text settings, or type the description.')
            self._voice_context = None
            self._buttons()
            return
        if loaded.get('state') == 'draft_loaded':
            record = loaded.get('record')
            if record:
                payload = record['payload']
                context = payload['context']
                self.identity_label.setText(f'Pending PACS user: {context["pacs_user"]}\nPending connection: {context.get("center_id") or "Not reported"}\nVersion: {context["app_version"]}')
                self.description.setPlainText(payload['description'])
                self.description.setReadOnly(True)
                self.category.setCurrentIndex(self.category.findData(payload['category']))
                self.category.setEnabled(False)
                self.windows.setChecked(payload['diagnostics'].get('windows_state') != 'not_requested')
                self.windows.setEnabled(False)
                self.log_archive.setChecked(bool(payload.get('log_archive')))
                self.log_archive.setEnabled(False)
                self.incident_time.setDateTime(QDateTime.fromString(payload['occurred_at'], Qt.ISODateWithMs).toLocalTime())
                self.incident_time.setEnabled(False)
                self.public_result = {'state':'pending', 'ticket_submitted':False, 'restored':True}
                self.status.setText('A previous request is pending. Review its restored description and retry the original request. Its account, connection and diagnostic snapshot remain fixed.')
                self.deliveryChanged.emit(dict(self.public_result))
            else:
                if getattr(self,'_requested_ticket_operation','prepare') != 'prepare':
                    receipt = loaded.get('receipt')
                    self.public_result = dict(receipt, ticket_submitted=True, historical=True) if receipt else {'state':'not_found','ticket_submitted':False}
                    self.status.setText('Previous ticket received by support. Issue: '+receipt['issue_id'] if receipt else 'No saved pending ticket or confirmed receipt was found for this linked account.')
                    self.deliveryChanged.emit(dict(self.public_result))
                else:
                    self.status.setText('Ready. An AI-PACS website account must be linked in Settings.')
            self._buttons()
            if record:
                self.send.setEnabled(False)
            return
        if loaded.get('state') == 'discarded':
            self.public_result = {'state':'awaiting_local_input', 'ticket_submitted':False}
            self.description.setReadOnly(False)
            self.description.clear()
            self.category.setEnabled(True)
            self.windows.setEnabled(True)
            self.log_archive.setEnabled(True)
            self.log_archive.setChecked(False)
            self.incident_time.setEnabled(True)
            self.incident_time.setDateTime(QDateTime.currentDateTime())
            self.consent.setChecked(False)
            self.identity_label.setText(f'PACS user: {self.user}\nConnection: {self.connection_name or "Not reported"}\nVersion: {self.app_version}')
            self.status.setText('Local pending request discarded. You can prepare a new issue.')
            self._buttons()
            return
        self.public_result = result.get('data', {'state':'failed', 'error_code':'SUPPORT_OPERATION_FAILED'})
        if self.public_result.get('state') == 'received':
            self.public_result['ticket_submitted'] = True
            self.status.setText('Received by support. Issue: '+self.public_result['issue_id'])
        elif self.public_result.get('state') == 'pending':
            self.description.setReadOnly(True)
            self.category.setEnabled(False)
            self.windows.setEnabled(False)
            self.log_archive.setEnabled(False)
            self.incident_time.setEnabled(False)
            messages = {
                'WEBSITE_SESSION_EXPIRED':'The website session expired. Reconnect the website account, then discard and prepare a new request.',
                'WEBSITE_PAIRING_REVOKED':'The website pairing was revoked. Reconnect the intended account, then discard and prepare a new request.',
                'SUPPORT_ENDPOINT_UNAVAILABLE':'The support endpoint is unavailable on this website. The encrypted request is saved; retry after the website update.',
                'ISSUE_CONTENT_CONFLICT':'The server rejected this issue identifier because its content differs. Contact support before preparing another request.',
                'ISSUE_REJECTED':'The website rejected the report format or size. The request remains saved locally; contact support or discard it.',
                'RATE_LIMITED':'The support submission limit was reached. The encrypted request is saved; retry later.',
            }
            self.status.setText(messages.get(self.public_result.get('error_code'),
                'Delivery is unconfirmed. The encrypted request is saved locally. Retry uses the same issue identifier.'))
        elif self.public_result.get('error_code') == 'WEBSITE_ACCOUNT_REQUIRED':
            self.status.setText('Link your AI-PACS website account in Settings before sending.')
        else:
            self.status.setText('The operation could not complete. Check your linked account; retry any pending issue before creating another.')
        self._buttons()
        if self._delivery_active:
            self._delivery_active = False
            self.deliveryChanged.emit(dict(self.public_result))


def open_support_issue_form(home, description=''):
    """Open one form per Home widget; never submit merely by opening it."""
    existing = getattr(home, '_support_issue_dialog', None)
    if existing is not None and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return existing
    from modules.Identity.ui.host_user import resolve_host_auth_user
    auth = resolve_host_auth_user(home)
    if not auth or not auth.get('username'):
        raise ValueError('Signed-in PACS user required')
    panel = getattr(home, 'data_access_panel_widget', None)
    connection = str(getattr(panel, 'server_selected', '') or '')
    dialog = SupportIssueDialog(str(auth['username']), connection, description, home)
    home._support_issue_dialog = dialog
    secretary = getattr(home,'secretary_button_widget',None)
    if secretary is not None:
        secretary._watch_help_ticket(dialog)
    dialog.show()
    return dialog
