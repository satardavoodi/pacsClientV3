"""Lazy role-aware Eagle Eye connection UI; all I/O stays in an owned worker."""
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                              QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                              QAbstractItemView, QHeaderView, QGroupBox, QSpinBox, QScrollArea,
                              QComboBox, QPlainTextEdit)

from modules.ai_imaging.eagle_eye_remote import administration as admin


class EagleEyeSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot = None
        self._future = None
        self._operation = ''
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='EagleEyeSettings')
        pool = self._pool
        self.destroyed.connect(lambda: pool.shutdown(wait=False, cancel_futures=True))
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.role = QLabel('Eagle Eye')
        layout.addWidget(self.role)
        self.description = QLabel('One connection for Eagle Eye analysis. Images are obtained by the server from PACS; '
                             'this workstation receives derived results. Existing jobs keep their original connection.')
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.connection_panel = QGroupBox('Client connection')
        form = QFormLayout(self.connection_panel)
        self.url = QLineEdit()
        self.url.setPlaceholderText('https://eagle-eye.example:8042')
        self.token_file = QLineEdit()
        self.token_file.setPlaceholderText('Absolute path to the client credential file')
        self.ca_file = QLineEdit()
        self.ca_file.setPlaceholderText('Optional trusted CA file')
        self.client_certificate = QLineEdit()
        self.client_private_key = QLineEdit()
        for label, field in [('Eagle Eye Server', self.url), ('Credential file', self.token_file),
                             ('Trusted CA file', self.ca_file),
                             ('Paired client certificate', self.client_certificate),
                             ('Paired client private key file', self.client_private_key)]:
            form.addRow(label, field)
        layout.addWidget(self.connection_panel)
        self.credential_note = QLabel()
        self.credential_note.setWordWrap(True)
        layout.addWidget(self.credential_note)
        buttons = QHBoxLayout()
        self.save_button = QPushButton('Save connection')
        self.test_button = QPushButton('Test connection')
        self.reload_button = QPushButton('Reload')
        self.jobs_button = QPushButton('Refresh my jobs')
        for button in (self.save_button, self.test_button, self.reload_button, self.jobs_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.status = QLabel('Loading Eagle Eye settings...')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.server_details = QLabel()
        self.server_details.setWordWrap(True)
        layout.addWidget(self.server_details)
        self.listener_panel = QGroupBox('Client access — apply after service restart')
        listener_form = QFormLayout(self.listener_panel)
        self.listen_host = QLineEdit()
        self.listen_port = QSpinBox()
        self.listen_port.setRange(1, 65535)
        self.listen_certificate = QLineEdit()
        self.listen_private_key = QLineEdit()
        for label, field in [('Listen address', self.listen_host), ('Request and result port', self.listen_port),
                             ('TLS certificate file', self.listen_certificate), ('TLS private key file', self.listen_private_key)]:
            listener_form.addRow(label, field)
        listener_note = QLabel('Clients submit analysis requests and retrieve results through this same port. '
                              'Use 8002 to replace the previous mammography endpoint after testing. '
                              'Network access requires HTTPS and authorized clients. For all network interfaces, '
                              'use 0.0.0.0. The certificate must cover the client-facing address and 127.0.0.1 '
                              'for this desktop. Saving does not stop another application or change port forwarding.')
        listener_note.setWordWrap(True)
        listener_form.addRow(listener_note)
        self.listener_button = QPushButton('Save listener settings for next start')
        self.listener_button.clicked.connect(self._save_listener)
        listener_form.addRow(self.listener_button)
        self.listener_panel.hide()
        layout.addWidget(self.listener_panel)
        self.source_panel = QGroupBox('PACS source and server storage — apply after service restart')
        source_form = QFormLayout(self.source_panel)
        self.source_mode = QComboBox()
        self.source_mode.addItem('Existing workstation cache', 'workstation-cache')
        self.source_mode.addItem('PACS metadata and mapped storage', 'pacs-storage')
        self.pacs_url = QLineEdit()
        self.dicom_port = QSpinBox(); self.dicom_port.setRange(1, 65535); self.dicom_port.setValue(105)
        self.socket_port = QSpinBox(); self.socket_port.setRange(1, 65535); self.socket_port.setValue(50052)
        self.local_pacs_button = QPushButton('Use PACS on this computer')
        self.local_pacs_button.clicked.connect(self._local_pacs)
        source_form.addRow(self.local_pacs_button)
        source_form.addRow('DICOM port', self.dicom_port)
        source_form.addRow('Patient/download socket port', self.socket_port)
        self.database = QLineEdit()
        self.job_root = QLineEdit()
        self.allowed_roots = QPlainTextEdit()
        self.allowed_roots.setMaximumHeight(75)
        for label, field in [('Source mode', self.source_mode), ('PACS metadata URL', self.pacs_url),
                             ('Server database file', self.database), ('Job/result folder', self.job_root),
                             ('Allowed source folders (one per line)', self.allowed_roots)]:
            source_form.addRow(label, field)
        source_note = QLabel('Cache mode requires completed downloads. Mapped storage requires direct server access. '
                             'Automatic download of uncached studies is not enabled. Existing path mappings and '
                             'PACS credentials are preserved. Changing the job folder does not move previous results.')
        source_note.setWordWrap(True)
        source_form.addRow(source_note)
        self.source_button = QPushButton('Save source settings for next start')
        self.source_button.clicked.connect(self._save_source)
        source_form.addRow(self.source_button)
        self.pacs_username = QLineEdit()
        self.pacs_password = QLineEdit()
        self.pacs_password.setEchoMode(QLineEdit.Password)
        source_form.addRow('PACS service username', self.pacs_username)
        source_form.addRow('PACS service password', self.pacs_password)
        self.account_button = QPushButton('Save encrypted PACS account')
        self.account_button.clicked.connect(self._save_account)
        source_form.addRow(self.account_button)
        self.pacs_test_button = QPushButton('Test saved PACS connection')
        self.pacs_test_button.clicked.connect(self._test_pacs)
        source_form.addRow(self.pacs_test_button)
        account_note = QLabel('The account is encrypted for this Windows computer. The service signs in after '
                             'startup and renews rejected tokens automatically. Save using an administrator account. '
                             'DICOM and socket ports are separate from the metadata URL.')
        account_note.setWordWrap(True)
        source_form.addRow(account_note)
        self.source_panel.hide()
        layout.addWidget(self.source_panel)
        self.service_panel = QGroupBox('Independent Windows service')
        service_layout = QVBoxLayout(self.service_panel)
        self.service_status = QLabel('Refresh to inspect the service. Closing the workstation does not stop an installed service.')
        self.service_status.setWordWrap(True)
        service_layout.addWidget(self.service_status)
        self.service_refresh_button = QPushButton('Refresh service status')
        self.service_refresh_button.clicked.connect(self._service_status)
        service_layout.addWidget(self.service_refresh_button)
        self.service_install_button = QPushButton('Install automatic service (administrator)')
        self.service_install_button.clicked.connect(self._install_service)
        service_layout.addWidget(self.service_install_button)
        service_note = QLabel('Installs only Eagle Eye, with delayed start after boot and restart after failure. '
                             'An existing service is never replaced. Storage permissions and the first controlled '
                             'start must be checked by the server administrator.')
        service_note.setWordWrap(True)
        service_layout.addWidget(service_note)
        self.service_panel.hide()
        layout.addWidget(self.service_panel)
        self.capacity_panel = QGroupBox('Server resource reservations — apply after service restart')
        capacity_layout = QVBoxLayout(self.capacity_panel)
        capacity_form = QFormLayout()
        self.parallel = QSpinBox(); self.parallel.setRange(1, 8)
        self.cpu = QSpinBox(); self.cpu.setRange(0, 512)
        self.ram = QSpinBox(); self.ram.setRange(0, 4194304)
        self.cpu.setSpecialValueText('Not configured')
        self.ram.setSpecialValueText('Not configured')
        self.quota = QSpinBox(); self.quota.setRange(1, 16)
        for label, field in [('Simultaneous analyses', self.parallel), ('CPU thread budget', self.cpu),
                             ('RAM budget (MB)', self.ram), ('Active jobs per client', self.quota)]:
            capacity_form.addRow(label, field)
        capacity_layout.addLayout(capacity_form)
        self.costs = QTableWidget(0, 3)
        self.costs.setHorizontalHeaderLabels(['Operation', 'CPU threads', 'RAM (MB)'])
        self.costs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        capacity_layout.addWidget(self.costs)
        note = QLabel('Parallel CPU execution requires measured budgets for every operation. '
                      'Reservations are admission limits, not operating-system memory caps. GPU scheduling is not configured here.')
        note.setWordWrap(True)
        capacity_layout.addWidget(note)
        self.resources_button = QPushButton('Save resource policy for next start')
        self.resources_button.clicked.connect(self._save_resources)
        capacity_layout.addWidget(self.resources_button)
        self.capacity_panel.hide()
        layout.addWidget(self.capacity_panel)
        self.jobs = QTableWidget(0, 3)
        self.jobs.setHorizontalHeaderLabels(['Job', 'Operation', 'Status'])
        self.jobs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.jobs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.jobs)
        self.save_button.clicked.connect(self._save)
        self.test_button.clicked.connect(self._test)
        self.reload_button.clicked.connect(self._load)
        self.jobs_button.clicked.connect(self._jobs)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)
        self._load()

    def _busy(self, busy):
        server = bool(self._snapshot and self._snapshot.get('role') == 'server')
        self.save_button.setEnabled(not busy and self._snapshot is not None and not server)
        self.test_button.setEnabled(not busy and self._snapshot is not None)
        self.jobs_button.setEnabled(not busy and self._snapshot is not None)
        self.reload_button.setEnabled(not busy)
        self.capacity_panel.setEnabled(not busy)
        self.source_panel.setEnabled(not busy)
        self.service_panel.setEnabled(not busy)
        self.listener_panel.setEnabled(not busy)
        for field in (self.url, self.token_file, self.ca_file, self.client_certificate, self.client_private_key):
            field.setReadOnly(busy or server)

    def _start(self, operation, function, *args):
        if self._future is not None:
            return
        self._operation = operation
        self._busy(True)
        self._future = self._pool.submit(function, *args)
        self._timer.start()

    def _load(self):
        self.status.setText('Loading Eagle Eye settings...')
        self._start('load', admin.load_settings)

    def _values(self):
        return {'url': self.url.text().strip(), 'token_file': self.token_file.text().strip(),
                'ca_file': self.ca_file.text().strip(),
                'client_certificate': self.client_certificate.text().strip(),
                'client_private_key': self.client_private_key.text().strip()}

    def _save(self):
        if self._snapshot is None or self._snapshot.get('role') == 'server':
            return
        self.status.setText('Saving connection...')
        self._start('save', admin.save_connection, self._snapshot['path'],
                    self._snapshot['revision'], self._values())

    def _test(self):
        self.status.setText('Testing authenticated server connection...')
        value = {**self._snapshot['value'], **self._values()}
        self._start('test', admin.probe_connection, value)

    def _jobs(self):
        self.jobs.setRowCount(0)
        self.status.setText('Loading jobs for this client identity...')
        self._start('jobs', admin.recent_jobs, {**self._snapshot['value'], **self._values()})

    def _save_resources(self):
        from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
        try:
            capacity = {'jobs': self.parallel.value()}
            modules = {name: {'jobs': 1} for name in MODULES}
            if self.parallel.value() > 1 or self.cpu.value() or self.ram.value():
                capacity.update(cpu_threads=self.cpu.value(), ram_mb=self.ram.value())
                for row, name in enumerate(MODULES):
                    modules[name].update(cpu_threads=int(self.costs.item(row, 1).text()),
                                         ram_mb=int(self.costs.item(row, 2).text()))
            server = self._snapshot['server']
            self.status.setText('Saving resource policy; active jobs are unchanged...')
            self._start('resources', admin.save_resources, server['configuration_path'], server['revision'],
                        {'capacity': capacity, 'modules': modules}, self.quota.value())
        except (ValueError, AttributeError, KeyError):
            self.status.setText('Enter a positive CPU and RAM reservation for every operation before enabling parallel work.')

    def _save_listener(self):
        server = self._snapshot['server']
        options = {'host': self.listen_host.text().strip(), 'port': self.listen_port.value(),
                   'certificate': self.listen_certificate.text().strip(),
                   'private_key': self.listen_private_key.text().strip()}
        self.status.setText('Validating listener settings; the running service is unchanged...')
        self._start('listener', admin.save_listener_options, server['configuration_path'], server['revision'], options)

    def _save_source(self):
        server = self._snapshot['server']
        options = {'type': self.source_mode.currentData(), 'url': self.pacs_url.text().strip(),
                   'database': self.database.text().strip(), 'job_root': self.job_root.text().strip(),
                   'allowed_roots': [line.strip() for line in self.allowed_roots.toPlainText().splitlines() if line.strip()],
                   'dicom_port': self.dicom_port.value(), 'socket_port': self.socket_port.value()}
        self.status.setText('Checking and saving server source settings...')
        self._start('source', admin.save_source_options, server['configuration_path'], server['revision'], options)

    def _local_pacs(self):
        self.pacs_url.setText('http://127.0.0.1:8000')
        self.dicom_port.setValue(105)
        self.socket_port.setValue(50052)
        self.source_mode.setCurrentIndex(self.source_mode.findData('pacs-storage'))

    def _save_account(self):
        server = self._snapshot['server']
        password = self.pacs_password.text()
        self.pacs_password.clear()
        self._start('account', admin.save_pacs_account, server['configuration_path'], server['revision'],
                    self.pacs_url.text().strip(), self.pacs_username.text().strip(), password)

    def _test_pacs(self):
        self._start('pacs-test', admin.probe_pacs, self._snapshot['server']['configuration_path'])

    def _service_status(self):
        from modules.ai_imaging.eagle_eye_remote.service_admin import inspect_service
        self._start('service-status', inspect_service, self._snapshot['server']['configuration_path'])

    def _install_service(self):
        from modules.ai_imaging.eagle_eye_remote.service_admin import install_service
        self._start('service-status', install_service, self._snapshot['server']['configuration_path'])

    def _poll(self):
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self._timer.stop()
        try:
            value = future.result()
            if self._operation in ('resources', 'source', 'account', 'listener'):
                self._snapshot['server']['revision'] = value['revision']
                self.status.setText('Server settings saved. They apply after a controlled service restart; active jobs are unchanged.')
            elif self._operation == 'pacs-test':
                self.status.setText('PACS sign-in verified.' if value['authenticated'] else
                                    'PACS health endpoint reachable. No saved service account was tested.')
            elif self._operation == 'service-status':
                self.service_status.setText('Service is not installed.' if not value['installed'] else
                    'Service belongs to another installation; no changes made.' if not value['owned'] else
                    ('Service running. ' if value['running'] else 'Service stopped. ') +
                    ('Automatic startup enabled.' if value['automatic'] else 'Automatic startup disabled.'))
                self.status.setText('Service status checked.')
            elif self._operation == 'jobs':
                self.jobs.setRowCount(len(value))
                for row, job in enumerate(value):
                    for column, key in enumerate(('job_id', 'module', 'status')):
                        self.jobs.setItem(row, column, QTableWidgetItem(str(job.get(key, ''))))
                self.status.setText('Latest 50 jobs for this client identity. Other clients remain private.')
            elif self._operation == 'test':
                self.status.setText('Connected. Supported operations: ' + ', '.join(value['modules']) +
                                    '. Model readiness is not certified by this connection test.')
            else:
                if self._operation == 'save':
                    value['role'] = self._snapshot['role']
                self._snapshot = value
                self.jobs.setRowCount(0)
                self.role.setText('Eagle Eye Server' if value['role'] == 'server' else 'Eagle Eye Client')
                is_server = value['role'] == 'server'
                self.connection_panel.setVisible(not is_server)
                self.credential_note.setVisible(not is_server)
                self.save_button.setVisible(not is_server)
                self.test_button.setText('Check local AI service' if is_server else 'Test connection')
                self.jobs_button.setText('Refresh desktop test jobs' if is_server else 'Refresh my jobs')
                self.description.setText(
                    'This workstation hosts Eagle Eye AI. It obtains images from PACS, runs the local models '
                    'and returns analysis results to connected clients. Configure PACS, storage, resources '
                    'and the Windows service below.' if is_server else
                    'Connect to Eagle Eye Server for AI analysis. The server obtains images from PACS '
                    'and returns results to this workstation.')
                for key, field in [('url', self.url), ('token_file', self.token_file), ('ca_file', self.ca_file),
                                   ('client_certificate', self.client_certificate), ('client_private_key', self.client_private_key)]:
                    field.setText(value['value'].get(key, ''))
                self.credential_note.setText('A deployment environment credential takes precedence over the credential file. '
                                             'Credential values are never displayed here.')
                self.status.setText('Connection saved for new analyses.' if self._operation == 'save'
                                    else 'Settings loaded. Test the connection before starting an analysis.')
                if is_server:
                    self.status.setText('Server settings loaded. Check the local AI service before accepting analyses.'
                                        if value.get('server') else
                                        'Server role selected. Launch with an Eagle Eye server configuration to manage the service.')
                server = value.get('server')
                if server:
                    self.listen_host.setText(server['host'])
                    self.listen_port.setValue(server['port'])
                    self.listen_certificate.setText(server.get('certificate', ''))
                    self.listen_private_key.setText(server.get('private_key', ''))
                    self.listener_panel.show()
                    self.server_details.setText(
                        f"Hosted listener: {server['host']}:{server['port']}\n"
                        f"Source mode: {server['source_type']}\nJob storage: {server['job_root']}\n"
                        f"Configured clients: {server['client_count']}\n"
                        'The hosted connection is managed by the server launch configuration. '
                        'Service and PACS configuration changes require a controlled restart.')
                    from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
                    resources = server.get('resources') or {}
                    capacity = resources.get('capacity') or {'jobs': 1}
                    self.parallel.setValue(capacity['jobs'])
                    self.cpu.setValue(capacity.get('cpu_threads', 0))
                    self.ram.setValue(capacity.get('ram_mb', 0))
                    self.quota.setValue(server['max_jobs_per_client'])
                    self.costs.setRowCount(len(MODULES))
                    for row, name in enumerate(MODULES):
                        profile = resources.get('modules', {}).get(name, {})
                        for column, text in enumerate((name, str(profile.get('cpu_threads', 0)), str(profile.get('ram_mb', 0)))):
                            item = QTableWidgetItem(text)
                            if column == 0:
                                from PySide6.QtCore import Qt
                                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                            self.costs.setItem(row, column, item)
                    self.capacity_panel.show()
                    source = server.get('source', {})
                    self.source_mode.setCurrentIndex(max(0, self.source_mode.findData(server['source_type'])))
                    self.pacs_url.setText(source.get('url', ''))
                    self.dicom_port.setValue(source.get('dicom_port') or 105)
                    self.socket_port.setValue(source.get('socket_port') or 50052)
                    self.pacs_password.clear()
                    self.database.setText(source.get('database', ''))
                    self.job_root.setText(server['job_root'])
                    self.allowed_roots.setPlainText('\n'.join(source.get('allowed_roots', [])))
                    self.source_panel.show()
                    self.service_panel.show()
                else:
                    self.listener_panel.hide()
                    self.capacity_panel.hide()
                    self.source_panel.hide()
                    self.service_panel.hide()
                    self.server_details.clear()
        except Exception:
            self.status.setText(
                'Listener settings were not saved. Check the bind IP, port, TLS certificate/key pair and '
                'independent-service configuration. Reload if settings changed elsewhere.'
                if self._operation == 'listener' else
                'Resource policy was not saved. Check every module budget against capacity and reload if settings changed.'
                if self._operation == 'resources' else
                'Operation failed. Check the address, credential/certificate files and configuration. '
                'If settings changed elsewhere, reload before saving.')
        self._busy(False)
