"""Patient-owned availability and explicit saved-result reads, all I/O on workers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import json
import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QPushButton, QTextBrowser, QMessageBox)
from PySide6.QtWidgets import QMenu

from .case_receiver import CaseReceiver


def local_brain_results(reference):
    """Worker-only, exact-study inventory of locally retained Eagle Eye artifacts."""
    from PacsClient.utils.data_paths import AI_DIR, ATTACHMENTS_DIR
    from ..eagle_eye_brain.saved_results import discover_results
    from ..eagle_eye_alignment.saved_results import discover_results as alignment_results
    root = Path(AI_DIR) / 'eagle_eye'
    from .local_results import discover_results as retained_results, echo_results
    alignment = [dict(row, storage='alignment-report') for row in alignment_results(root, reference['study_uid'])]
    return (discover_results(root, reference['study_uid']) + alignment
            + retained_results(root, reference['study_uid'])
            + [dict(row, root=str(Path(ATTACHMENTS_DIR) / reference['study_uid'])) for row in
               retained_results(Path(ATTACHMENTS_DIR) / reference['study_uid'], reference['study_uid'])]
            + echo_results(reference))


def availability_style(base, available, checked):
    if not available:
        return base
    border = '#79bde8' if checked else '#f87171'
    return base + f'''QPushButton {{ background-color: #54232b; color: #fecaca;
        border: 2px solid {border}; }} QPushButton:hover {{ background-color: #71303b; }}'''


def saved_content(value):
    """Present clinical response fields without transport or filesystem details."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return value
    if not isinstance(value, dict):
        return str(value)
    excluded = {'artifact_directory', 'server_job_id', 'server_module', 'remote_analysis',
        'source_binding', 'study_uid', 'request_id', 'protocol', 'saved_files', 'report',
        'analysis_type', 'engine', 'source_files', 'files', 'pdf_available'}
    lines = []
    for key, item in value.items():
        if key in excluded or key.startswith('_') or key.endswith(('_path', '_directory')):
            continue
        if isinstance(item, dict):
            content = saved_content(item)
        elif isinstance(item, list):
            content = '\n'.join(saved_content(v) for v in item)
        else:
            content = str(item)
        if content:
            lines.append(key.replace('_', ' ').capitalize() + '\n' + content)
    return '\n\n'.join(lines) or 'The saved report and derived images are available below.'


def require_current_source(connection):
    """Worker-only check before applying an explicit read after profile changes."""
    profile_id = getattr(connection, 'case_profile_id', None)
    if profile_id is None:
        return
    from PacsClient.utils.server_profiles import get_active_profile
    from .client import Client
    profile, latest = get_active_profile(), Client()
    if (not profile or profile.id != profile_id or profile.socket_port != connection.case_socket_port
            or profile.host != connection.case_pacs_host
            or latest.url != connection.url or latest.token != connection.token):
        raise ValueError('The case source or credentials changed during retrieval.')


class PatientCaseController(QObject):
    def __init__(self, patient, *, receiver_factory=CaseReceiver, local_finder=None):
        super().__init__(patient)
        self.patient = patient
        self.factory = receiver_factory
        self.receiver = None
        self.reference = None
        self.snapshot = None
        self.local_finder = local_finder or local_brain_results
        self.image_counts = None
        self.thumbnail_refresh_pending = False
        self.local_count = 0
        self.local_rows = []
        self.local_future = None
        self.local_binding = None
        self.local_checked_at = 0.0
        self.dialog = None
        self.future = None
        self.future_binding = None
        self.cancel = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='SavedCaseRead')
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.holder = [None]
        holder, executor, cancel = self.holder, self.executor, self.cancel
        def dispose():
            cancel.set()
            if holder[0]:
                holder[0].stop()
            executor.shutdown(wait=False, cancel_futures=True)
        self.destroyed.connect(dispose)
        reception = getattr(patient, 'btn_reception', None)
        if reception:
            reception.setContextMenuPolicy(Qt.CustomContextMenu)
            def resources_menu(point):
                menu = QMenu(reception)
                action = menu.addAction('View server reports, recordings and images')
                action.triggered.connect(lambda: self.open_resources(''))
                menu.exec(reception.mapToGlobal(point))
            reception.customContextMenuRequested.connect(resources_menu)

    def current_case(self):
        from modules.ai_imaging.eagle_eye_function_dialog import active_viewer_context
        uid = active_viewer_context(self.patient)['study_uid']
        pid = str(getattr(self.patient, 'patient_id', '') or '')
        return {'study_uid': uid, 'patient_id': pid} if uid and pid else None

    def tick(self):
        reference = self.current_case()
        if reference != self.reference:
            self.image_counts = None
            self.thumbnail_refresh_pending = False
            self.local_count = 0
            self.local_rows = []
            self.local_checked_at = 0.0
            if self.receiver:
                self.receiver.stop()
                if self.receiver.is_alive():
                    self.clear('Waiting for the previous case connection to close.')
                    return
            self.receiver = None
            self.holder[0] = None
            self.reference = reference
            self.clear('Checking saved server results.')
            if reference:
                try:
                    self.receiver = self.factory(reference)
                    self.holder[0] = self.receiver
                    self.receiver.start()
                except ValueError:
                    self.clear('A verified patient and study reference is required.')
        if self.thumbnail_refresh_pending and not getattr(self.patient, '_thumbnail_load_inflight', False):
            self.thumbnail_refresh_pending = False
            loader = getattr(self.patient, '_load_server_thumbnails', None)
            if loader:
                loader()
        self.check_local_results()
        if self.receiver:
            value = self.receiver.drain()
            if value and value.get('case') == self.reference:
                if value.get('status') == 'connected':
                    self.snapshot = value
                    self.apply()
                else:
                    self.clear('Server availability is unknown. Check the Eagle Eye connection.')
        if self.future and self.future.done():
            future, binding = self.future, self.future_binding
            self.future = None
            if (binding[0] != self.reference or not self.receiver
                    or binding[1] is not self.receiver.connection or binding[3] is not self.dialog):
                return
            try:
                value = future.result()
                if binding[2].startswith('page:'):
                    self.populate(self.dialog, binding[2].split(':', 1)[1], value)
                elif binding[2] == 'resources-list':
                    resource_client, rows = value
                    self.dialog.resource_client = resource_client
                    self.dialog.results.clear()
                    for row in rows:
                        self.dialog.results.addItem(row['file_name'])
                        self.dialog.results.item(self.dialog.results.count() - 1).setData(Qt.UserRole, row)
                    self.dialog.results.setCurrentRow(0)
                    self.dialog.status.setText('Select a server file to retrieve the original.' if rows else 'No matching server files.')
                elif binding[2] == 'local-echo':
                    self.show_result('echomind', value)
                elif binding[2] == 'local-alignment':
                    self.show_result('eagle_eye', value)
                elif binding[2] == 'resource-file':
                    QDesktopServices.openUrl(QUrl.fromLocalFile(value))
                    self.dialog.status.setText('The original server file is ready.')
                else:
                    self.show_result(binding[2], value)
            except Exception:
                QMessageBox.warning(self.patient, 'Saved server result',
                    'The saved result could not be retrieved. Check the connection and case access.')
            if self.dialog:
                self.dialog.open_button.setEnabled(True)

    def clear(self, message):
        self.snapshot = None
        self.clear_workflow()
        for name in ('btn_ai_chat', 'btn_ai_module'):
            button = getattr(self.patient, name, None)
            if button:
                button.setProperty('savedResultAvailable', False)
                button.setToolTip(message)
                self.patient._safe_set_sidebar_button_style(button, button.isChecked())
        if self.local_count or self.local_rows:
            self.apply_availability()
        if self.dialog:
            self.dialog.status.setText(message)
            self.dialog.open_button.setEnabled(self.dialog.kind == 'local' and bool(self.local_count))

    def clear_workflow(self):
        self.patient.setProperty('serverVoiceCount', None)
        self.patient.setProperty('serverAttachmentRevision', None)
        self.patient.setProperty('serverReportingDoctor', None)
        self.patient.setProperty('serverImageCount', None)
        toolbar = getattr(self.patient, 'toolbar_manager', None)
        if toolbar:
            access = getattr(toolbar, 'tool_access', None)
            mic = getattr(toolbar, 'tools_button', {}).get(getattr(access, 'MICROPHONE', None))
            if mic:
                mic.setProperty('serverVoiceCount', None)
                if hasattr(mic, 'setCount'):
                    mic.setCount(int(getattr(toolbar, '_audio_counter_cache_count', 0) or 0))
                mic.setToolTip('Server voice availability is unknown. The count shows local recordings.')

    def check_local_results(self):
        if self.local_future is not None and self.local_future.done():
            future, binding = self.local_future, self.local_binding
            self.local_future = None
            if binding == self.reference:
                try:
                    self.local_rows = future.result()
                    self.local_count = len(self.local_rows)
                except Exception:
                    self.local_rows = []
                    self.local_count = 0
                self.apply_availability()
        if (self.reference and self.local_future is None and not self.cancel.is_set()
                and time.monotonic() - self.local_checked_at >= 10):
            self.local_checked_at = time.monotonic()
            self.local_binding = dict(self.reference)
            self.local_future = self.executor.submit(self.local_finder, dict(self.reference))

    def apply_availability(self):
        for name, kind in (('btn_ai_chat', 'echomind'), ('btn_ai_module', 'eagle_eye')):
            button = getattr(self.patient, name, None)
            if button:
                count = len((self.snapshot or {}).get(kind, []))
                local = sum(row.get('kind') == 'echomind' for row in self.local_rows) if kind == 'echomind' else sum(row.get('kind') != 'echomind' for row in self.local_rows)
                if kind == 'eagle_eye' and not self.local_rows:
                    local = self.local_count
                button.setProperty('savedResultAvailable', bool(count or local))
                if local:
                    button.setToolTip(f'Saved {"EchoMind" if kind == "echomind" else "Eagle Eye"} results on this workstation: {local}. '
                                      'Click to review existing results.')
                else:
                    button.setToolTip(f'Saved server results: {count}. Click to retrieve an existing result.'
                                      if count else ('No saved server result for this study.' if self.snapshot
                                                     else 'Server availability is unknown. Check the Eagle Eye connection.'))
                self.patient._safe_set_sidebar_button_style(button, button.isChecked())

    def apply(self):
        self.apply_availability()
        workflow = self.snapshot.get('workflow') or {}
        toolbar = getattr(self.patient, 'toolbar_manager', None)
        toolbar_study = (toolbar._get_study_uid() if toolbar and hasattr(toolbar, '_get_study_uid')
                         else str(getattr(self.patient, 'study_uid', '') or ''))
        if not workflow or toolbar_study != self.reference['study_uid']:
            self.clear_workflow()
        if (workflow.get('patient_id') == self.reference['patient_id']
                and toolbar_study == self.reference['study_uid']):
            doctor = (workflow.get('assignment') or {}).get('radiologist') or {}
            self.patient.setProperty('serverReportingDoctor', dict(doctor))
            if type(workflow.get('image_count')) is int and type(workflow.get('series_count')) is int:
                counts = (workflow['image_count'], workflow['series_count'])
                if self.image_counts is not None and counts != self.image_counts:
                    self.thumbnail_refresh_pending = True
                self.image_counts = counts
                self.patient.setProperty('serverImageCount', counts[0])
            self.patient.report_status = workflow['report_status']
            if toolbar and hasattr(toolbar, '_update_report_status_display'):
                toolbar._update_report_status_display()
            self.patient.setProperty('serverVoiceCount', workflow['audio_count'])
            if toolbar:
                buttons = getattr(toolbar, 'tools_button', {})
                access = getattr(toolbar, 'tool_access', None)
                mic = buttons.get(getattr(access, 'MICROPHONE', None))
                if mic:
                    mic.setProperty('serverVoiceCount', workflow['audio_count'])
                    local_count = int(getattr(toolbar, '_audio_counter_cache_count', 0) or 0)
                    if hasattr(mic, 'setCount'):
                        mic.setCount(max(local_count, workflow['audio_count']))
                    mic.setToolTip(f"Server voice files: {workflow['audio_count']}. Open recordings to retrieve them.")
            reception = getattr(self.patient, 'btn_reception', None)
            if reception and 'document_count' in workflow:
                reception.setToolTip(f"Server report/document files: {workflow['document_count']}\nReporting physician: {doctor.get('name') or 'Unassigned'}\nServer images: {workflow.get('image_count', 'Unknown')}")
            self.patient.setProperty('serverAttachmentRevision', workflow.get('attachment_revision'))
        if self.dialog:
            self.dialog.status.setText('Saved results are current.')
            self.dialog.open_button.setEnabled(self.future is None)
            if self.dialog.kind == 'resources':
                revision = workflow.get('attachment_revision')
                if revision != self.dialog.revision and self.future is None:
                    self.dialog.revision = revision
                    self.resource_inventory()
            elif self.dialog.kind != 'local' and self.dialog.offset == 0 and self.future is None:
                self.populate(self.dialog, self.dialog.kind, self.snapshot)

    def open_resources(self, kind=''):
        if (not self.snapshot or not self.receiver or not self.receiver.connection
                or self.current_case() != self.reference):
            return False
        if self.dialog:
            self.dialog.close()
        dialog = QDialog(self.patient)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle('Server recordings' if kind == 'audio' else 'Server reports and recordings')
        dialog.resize(650, 400)
        dialog.kind, dialog.offset, dialog.resource_kind = 'resources', 0, kind
        dialog.resource_client, dialog.revision = None, None
        dialog.revision = (self.snapshot.get('workflow') or {}).get('attachment_revision')
        layout = QVBoxLayout(dialog)
        dialog.status = QLabel('Reading the current server inventory...', dialog)
        layout.addWidget(dialog.status)
        dialog.results = QListWidget(dialog)
        layout.addWidget(dialog.results)
        actions = QHBoxLayout()
        dialog.open_button = QPushButton('Retrieve and open selected file', dialog)
        dialog.open_button.clicked.connect(self.retrieve_resource)
        actions.addWidget(dialog.open_button)
        refresh = QPushButton('Refresh server files', dialog)
        refresh.clicked.connect(self.resource_inventory)
        actions.addWidget(refresh)
        layout.addLayout(actions)
        self.dialog = dialog
        dialog.destroyed.connect(lambda: self._dialog_closed(dialog))
        dialog.show()
        self.resource_inventory()
        return True

    def resource_inventory(self):
        if (self.future or not self.dialog or self.dialog.kind != 'resources'
                or not self.receiver or not self.receiver.connection or not self.snapshot):
            return
        reference, connection = dict(self.reference), self.receiver.connection
        kind = self.dialog.resource_kind
        host, port = self.snapshot['pacs_host'], self.snapshot['pacs_socket_port']
        self.future_binding = (reference, connection, 'resources-list', self.dialog)
        self.dialog.open_button.setEnabled(False)
        def work():
            require_current_source(connection)
            from modules.network.socket_token_manager import get_socket_token_manager
            from .pacs_resources import PacsResources
            resources = PacsResources(reference, host, port, get_socket_token_manager().get_token())
            rows = resources.inventory(kind)
            require_current_source(connection)
            return resources, rows
        self.future = self.executor.submit(work)

    def retrieve_resource(self):
        if (self.future or not self.dialog or self.dialog.kind != 'resources'
                or not self.dialog.resource_client or not self.receiver or not self.receiver.connection):
            return
        item = self.dialog.results.currentItem()
        if not item:
            return
        reference, connection = dict(self.reference), self.receiver.connection
        resources, row = self.dialog.resource_client, item.data(Qt.UserRole)
        self.future_binding = (reference, connection, 'resource-file', self.dialog)
        self.dialog.open_button.setEnabled(False)
        self.dialog.status.setText('Retrieving the original server file...')
        def work():
            require_current_source(connection)
            from PacsClient.utils.data_paths import ATTACHMENTS_DIR
            path = resources.download(row, ATTACHMENTS_DIR / reference['study_uid'] / '.server-media')
            require_current_source(connection)
            return path
        self.future = self.executor.submit(work)

    def populate(self, dialog, kind, snapshot):
        selected = dialog.results.currentItem()
        selected_id = selected.data(Qt.UserRole) if selected else None
        dialog.results.clear()
        dialog.offset = snapshot.get('offset', 0)
        for row in snapshot[kind]:
            timestamp = row.get('completed_at', row.get('created_at'))
            date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M') if timestamp else ''
            label = str(row.get('workflow', row.get('module', 'Saved result')))
            dialog.results.addItem(f'{label}  {date}')
            item = dialog.results.item(dialog.results.count() - 1)
            item.setData(Qt.UserRole, dict(row))
            if selected_id == row:
                dialog.results.setCurrentItem(item)
        if dialog.offset == 0:
            for row in self.local_rows:
                if (row.get('kind') == 'echomind') != (kind == 'echomind'):
                    continue
                local = dict(row, local=True)
                dialog.results.addItem('On this workstation: ' + row.get('kind', 'Saved result'))
                item = dialog.results.item(dialog.results.count() - 1)
                item.setData(Qt.UserRole, local)
                if selected_id == local:
                    dialog.results.setCurrentItem(item)
        if dialog.results.currentRow() < 0:
            dialog.results.setCurrentRow(0)
        dialog.older_button.setEnabled(bool(snapshot.get('more_' + kind)))
        dialog.newer_button.setEnabled(dialog.offset > 0)

    def open(self, kind):
        if self.current_case() != self.reference:
            self.tick()
            return False
        local_rows = [row for row in self.local_rows if (row.get('kind') == 'echomind') == (kind == 'echomind')]
        if (local_rows or kind == 'eagle_eye' and self.local_count) and not (self.snapshot or {}).get(kind):
            if any(row.get('kind') not in ('brain', 'lesion') or row.get('storage') for row in local_rows):
                if self.dialog:
                    self.dialog.close()
                dialog = QDialog(self.patient)
                dialog.setAttribute(Qt.WA_DeleteOnClose)
                dialog.setWindowTitle('Saved EchoMind results on this workstation' if kind == 'echomind' else 'Saved Eagle Eye results on this workstation')
                dialog.kind = 'local'
                dialog.offset = 0
                layout = QVBoxLayout(dialog)
                dialog.status = QLabel('Select an existing result. No new analysis will be submitted.', dialog)
                layout.addWidget(dialog.status)
                results = QListWidget(dialog)
                layout.addWidget(results)
                for row in local_rows:
                    results.addItem(row.get('kind', 'brain').replace('_', ' ').title())
                    results.item(results.count() - 1).setData(Qt.UserRole, row)
                button = QPushButton('Open saved result', dialog)
                dialog.open_button = button
                layout.addWidget(button)
                def open_selected():
                    item = results.currentItem()
                    if item is None or self.future:
                        return
                    row = item.data(Qt.UserRole)
                    if row.get('kind') in ('brain', 'lesion') and not row.get('storage'):
                        from modules.ai_imaging.eagle_eye_workspace import open_eagle_eye_workspace
                        workspace = open_eagle_eye_workspace(self.patient)
                        if workspace:
                            workspace.ensure_saved_brain_results()
                            workspace.tab_widget.setCurrentWidget(workspace.saved_brain_results)
                        return
                    reference = dict(self.reference)
                    def read():
                        from PacsClient.utils.data_paths import AI_DIR
                        from .local_results import load_result, load_echo
                        if row.get('kind') == 'echomind':
                            return load_echo(reference, row)
                        if row.get('kind') == 'alignment' and not row.get('storage'):
                            row['storage'] = 'alignment-report'
                        return load_result(row.get('root') or Path(AI_DIR) / 'eagle_eye', reference['study_uid'], row)
                    self.future_binding = (reference, self.receiver.connection, 'local-echo' if kind == 'echomind' else 'local-alignment', dialog)
                    self.future = self.executor.submit(read)
                button.clicked.connect(open_selected)
                results.setCurrentRow(0)
                self.dialog = dialog
                dialog.destroyed.connect(lambda: self._dialog_closed(dialog))
                dialog.show()
                return True
            from modules.ai_imaging.eagle_eye_workspace import open_eagle_eye_workspace
            action = getattr(self.patient, '_eagle_eye_function_action', None)
            workspace = getattr(getattr(action, '__self__', None), 'window', None)
            if workspace is None:
                workspace = open_eagle_eye_workspace(self.patient)
            if workspace is not None:
                workspace.ensure_saved_brain_results()
                workspace.tab_widget.setCurrentWidget(workspace.saved_brain_results)
                return True
            return False
        if not self.snapshot or not self.snapshot.get(kind):
            return False
        if self.dialog:
            self.dialog.close()
        dialog = QDialog(self.patient)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle('EchoMind saved results' if kind == 'echomind' else 'Eagle Eye saved results')
        dialog.resize(650, 400)
        dialog.kind, dialog.offset = kind, 0
        layout = QVBoxLayout(dialog)
        dialog.status = QLabel('Select an existing result. No new analysis will be submitted.', dialog)
        layout.addWidget(dialog.status)
        dialog.results = QListWidget(dialog)
        layout.addWidget(dialog.results)
        pages = QHBoxLayout()
        dialog.newer_button = QPushButton('Newer results', dialog)
        dialog.older_button = QPushButton('Older results', dialog)
        dialog.newer_button.clicked.connect(lambda: self.page(kind, max(0, dialog.offset - 50)))
        dialog.older_button.clicked.connect(lambda: self.page(kind, dialog.offset + 50))
        pages.addWidget(dialog.newer_button)
        pages.addWidget(dialog.older_button)
        layout.addLayout(pages)
        self.populate(dialog, kind, self.snapshot)
        actions = QHBoxLayout()
        dialog.open_button = QPushButton('Retrieve selected result', dialog)
        dialog.open_button.clicked.connect(lambda: self.retrieve(kind))
        actions.addWidget(dialog.open_button)
        new_button = QPushButton('Open workspace', dialog)
        def workspace():
            dialog.close()
            if kind == 'echomind':
                self.patient.switch_right_panel('ai_chat')
            else:
                from modules.ai_imaging.eagle_eye_workspace import open_eagle_eye_workspace
                open_eagle_eye_workspace(self.patient)
        new_button.clicked.connect(workspace)
        actions.addWidget(new_button)
        layout.addLayout(actions)
        self.dialog = dialog
        dialog.destroyed.connect(lambda: self._dialog_closed(dialog))
        dialog.show()
        return True

    def _dialog_closed(self, dialog):
        if self.dialog is dialog:
            self.dialog = None

    def retrieve(self, kind):
        if self.future or not self.dialog or not self.receiver or not self.receiver.connection:
            return
        item = self.dialog.results.currentItem()
        if item is None:
            return
        row = item.data(Qt.UserRole)
        connection, reference = self.receiver.connection, dict(self.reference)
        if row.get('local'):
            def local_read():
                from PacsClient.utils.data_paths import AI_DIR
                from .local_results import load_result, load_echo
                if kind == 'echomind':
                    return load_echo(reference, row)
                if row.get('kind') in ('brain', 'lesion') and not row.get('storage'):
                    from ..eagle_eye_brain.saved_results import load_result as brain
                    value = brain(Path(AI_DIR) / 'eagle_eye', reference['study_uid'], row['path'])
                    value['server_module'] = 'brain-lesions' if row['kind'] == 'lesion' else 'brain'
                    return value
                return load_result(row.get('root') or Path(AI_DIR) / 'eagle_eye', reference['study_uid'], row)
            self.future_binding = (reference, connection, kind, self.dialog)
            self.future = self.executor.submit(local_read)
            self.dialog.open_button.setEnabled(False)
            return
        self.future_binding = (reference, connection, kind, self.dialog)
        self.dialog.open_button.setEnabled(False)
        self.dialog.status.setText('Retrieving the original saved result...')
        def work():
            require_current_source(connection)
            if kind == 'echomind':
                result = connection.saved_text(reference, row['request_id'])
            else:
                from PacsClient.utils.data_paths import ATTACHMENTS_DIR
                result = connection.saved_analysis(reference, row['job_id'],
                    ATTACHMENTS_DIR / reference['study_uid'], cancel=self.cancel)
            require_current_source(connection)
            return result
        self.future = self.executor.submit(work)

    def page(self, kind, offset):
        if self.future or not self.dialog or not self.receiver or not self.receiver.connection:
            return
        connection, reference = self.receiver.connection, dict(self.reference)
        self.future_binding = (reference, connection, 'page:' + kind, self.dialog)
        self.dialog.open_button.setEnabled(False)
        def work():
            require_current_source(connection)
            value = connection.case_snapshot(reference, offset=offset)
            require_current_source(connection)
            return value
        self.future = self.executor.submit(work)

    def show_result(self, kind, value):
        if kind == 'eagle_eye' and value.get('server_module') in ('brain', 'brain-lesions'):
            from modules.ai_imaging.eagle_eye_workspace import open_eagle_eye_workspace
            workspace = open_eagle_eye_workspace(self.patient)
            controller = getattr(workspace, 'workspace_controller', None)
            if controller:
                controller.open_saved_brain_result(value)
                return
        dialog = QDialog(self.patient)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle('Saved EchoMind response' if kind == 'echomind' else 'Saved Eagle Eye result')
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        view = QTextBrowser(dialog)
        view.setOpenExternalLinks(False)
        content = value.get('content') if kind == 'echomind' else None
        view.setPlainText(saved_content(content if content is not None else value))
        layout.addWidget(view)
        if kind == 'eagle_eye':
            for index, file in enumerate(value.get('saved_files', ())):
                suffix = Path(file).suffix.lower()
                label = 'Open saved report' if suffix == '.pdf' else 'Open measurements' if suffix == '.csv' else f'Open saved image {index + 1}'
                button = QPushButton(label, dialog)
                button.clicked.connect(lambda _checked=False, path=file: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
                layout.addWidget(button)
        dialog.show()
