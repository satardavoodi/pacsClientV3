"""Source-only synthetic shared-component acceptance; not production-page proof."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from uuid import UUID, uuid4


def enabled():
    return os.environ.get('AIPACS_TEST_SERVER', '').strip() == '1' and not getattr(sys, 'frozen', False)


def _fixtures():
    text = 'Synthetic fixture: the lungs are clear. Heart size is normal.'
    result = {key: {'workflow': key, 'text': text, 'response_format': 'json'} for key in (
        'report', 'turbo', 'chat', 'assistant', 'search', 'web_search', 'standardize',
        'standardize_assist', 'translate_report', 'translate_text', 'correction',
        'breast', 'organize_template', 'template_languages', 'add_reference')}
    for key in ('assistant', 'search'):
        result[key]['provider'] = 'aipacs'
    questions = {'chat': 'Explain the purpose of a radiology report impression.',
                 'assistant': 'Explain general MRI safety screening.',
                 'search': 'Find general lung nodule reporting references.',
                 'web_search': 'Find general lung nodule reporting guidance with sources.',
                 'standardize_assist': 'MRI safety screening general reference question',
                 'breast': 'Explain general BI-RADS terminology.'}
    for key, question in questions.items(): result[key]['text'] = question
    result['correction'].update(text='Synthetic report: no left knee effusion.',
                                correction_note='Replace left with right.', target_section='Findings')
    result['organize_template']['text'] = json.dumps({'name': 'Synthetic chest', 'modality': 'RADIOLOGY',
        'blocks': [{'id': 'L0000', 'text': 'The lungs are clear.'}]})
    result['add_reference'].update(text='Synthetic fixture: HC 260 mm, AC 240 mm, FL 52 mm, BPD 72 mm, EFW 1200 g.',
        modality='OBSTETRIC ULTRASOUND', reference_context={'ga_days': 196, 'singleton': True,
        'bpd_method': 'outer-to-outer', 'efw_method': 'Hadlock HC/AC/FL'})
    for modality in ('CT', 'MRI', 'SONOGRAPHY', 'MAMOGRAPHY', 'RADIOLOGY'):
        result['report_' + modality] = dict(result['report'], modality=modality,
            normal_template='Findings: [supplied findings]. Impression: [supplied conclusion].',
            study_profile={'regions': ['synthetic region'], 'protocol': 'Synthetic test only'})
    attachment = {'name': 'synthetic-report.txt', 'data': base64.b64encode(text.encode()).decode()}
    result['report_attachment'] = dict(result['report'], attachments=[attachment])
    result['saved_correction'] = dict(result['correction'], correction_source=attachment)
    return result


def fixture_keys():
    return tuple(_fixtures())


def fixture(key):
    if key not in fixture_keys(): raise ValueError('Unknown synthetic fixture')
    return copy.deepcopy(_fixtures()[key])


class RunLedger:
    """One attempt per fixed fixture; unknown outcomes cannot be resubmitted."""
    def __init__(self):
        self.session = str(uuid4())
        self._lock = threading.Lock()
        self._attempted = set()
        self.current = None
        self.closed = False

    def reserve(self, key):
        fixture(key)
        with self._lock:
            if self.closed or self.current or key in self._attempted: return None
            self._attempted.add(key)
            self.current = str(uuid4())
            return self.current

    def accepts(self, rid):
        with self._lock: return not self.closed and self.current == rid

    def finish(self, rid):
        with self._lock:
            if self.current == rid: self.current = None

    def close(self):
        with self._lock: self.closed = True


def _receipt(directory, rid, value):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (rid + '.json')
    temporary = path.with_suffix('.pending')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def run_fixture(key, rid, sid, directory, *, client_factory=None):
    """Worker-only file/network work. Unit tests inject a fake transport."""
    from PySide6.QtCore import QCoreApplication, QThread
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        raise RuntimeError('Acceptance work requires a worker thread')
    if str(UUID(rid)) != rid or str(UUID(sid)) != sid: raise ValueError('Invalid acceptance identity')
    directory = Path(directory).resolve()
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    body = fixture(key)
    context = {'session_id': sid}
    body.update(request_id=rid, case_context=context)
    safe = {'fixture': key, 'workflow': body['workflow'], 'request_id': rid, 'session_id': sid,
            'fixture_sha256': hashlib.sha256(json.dumps(fixture(key), sort_keys=True).encode()).hexdigest()}
    history = History(directory / 'history')
    try:
        history.begin(rid, 'synthetic-acceptance', context, body)
        with sqlite3.connect(directory / 'history' / 'history.sqlite3') as db:
            if db.execute('select state from requests where request_id=?', (rid,)).fetchone() != ('running',):
                raise ValueError('Missing durable identity')
        _receipt(directory, rid, dict(safe, state='prewire'))
    except Exception:
        return dict(safe, state='not_sent', code='PREWIRE_FAILED')
    if client_factory is None:
        from modules.ai_imaging.eagle_eye_remote.client import Client
        client_factory = Client
    try:
        with client_factory().open('/v1/echomind/process', body, timeout=480) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024: raise ValueError('Bounded response exceeded')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('request_id') != rid:
            terminal = dict(safe, state='unknown', code='RESPONSE_ID_MISMATCH')
        elif not result.get('content'):
            terminal = dict(safe, state='unknown', code='EMPTY_RESPONSE')
        else:
            history.finish(rid, 'synthetic-acceptance', result)
            terminal = dict(safe, state='succeeded', code='', content=result['content'])
    except Exception as exc:
        status = getattr(exc, 'status', None)
        terminal = dict(safe, state='unknown', code='REQUEST_OUTCOME_UNKNOWN')
        if type(status) is int and status in (401, 403, 409, 422, 429, 502, 503):
            terminal.update(code='HTTP_' + str(status))
    try:
        _receipt(directory, rid, {k: v for k, v in terminal.items() if k != 'content'})
    except Exception:
        return dict(safe, state='unknown', code='TERMINAL_RECEIPT_FAILED')
    return terminal


def open_host():
    """Called only by the fixed, source/env-gated TestControl builtin."""
    if not enabled(): raise RuntimeError('Synthetic host requires explicit source test mode')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None: raise RuntimeError('Source GUI is required')
    existing = getattr(app, '_echomind_acceptance_host', None)
    if existing is not None:
        existing.show()
        existing.raise_()
        return
    # Composer's legacy constructor sweeps capture files synchronously. Never
    # trigger that cleanup from this test host or change the process setting.
    from modules.EchoMind.viewer_chat import ai_chat_widgets as widgets
    if not widgets._temp_sweep_done and os.environ.get('AIPACS_ECHOMIND_TEMP_SWEEP', '1').lower() not in ('0','false','no','off'):
        raise RuntimeError('Start the reviewed test session with capture cleanup disabled')
    host = _make_host(widgets)
    app._echomind_acceptance_host = host
    host.show()


def _make_host(widgets):
    from html import escape
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QAbstractButton, QTabBar
    from modules.EchoMind.viewer_chat.ai_chat_api import ApiWorker

    class Host(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('EchoMind synthetic component acceptance - TEST ONLY')
            self.resize(850, 720)
            self.ledger = RunLedger()
            self.worker = None
            self.detached = False
            self.directory = Path(__file__).resolve().parents[2] / 'generated-files' / 'echomind-component-acceptance' / self.ledger.session
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel('Synthetic shared-component test. Production patient-page acceptance is separate.'))
            self.selector = QComboBox()
            self.selector.addItems(fixture_keys())
            layout.addWidget(self.selector)
            self.status = QLabel('Ready - one attempt per fixture')
            layout.addWidget(self.status)
            self.history = widgets.ChatHistory()
            layout.addWidget(self.history, 1)
            self.composer = widgets.UnifiedComposer('Fixed synthetic fixture')
            self.composer.setAcceptDrops(False)
            for child in self.composer.findChildren(QAbstractButton):
                if child is not self.composer.btn_send: child.setEnabled(False)
            for child in self.composer.findChildren(QComboBox): child.setEnabled(False)
            for child in self.composer.findChildren(QTabBar): child.setEnabled(False)
            self.composer.box.setReadOnly(True)
            self.composer.box.setAcceptDrops(False)
            self.composer.sendClicked.connect(self.start)
            layout.addWidget(self.composer)
            self.selector.currentTextChanged.connect(self.preview)
            self.preview()

        def preview(self, *_):
            self.composer.box.setPlainText(fixture(self.selector.currentText())['text'])
            self.composer.btn_send.setEnabled(self.ledger.current is None and not self.detached)

        def start(self, *_):
            key = self.selector.currentText()
            rid = self.ledger.reserve(key)
            if rid is None: return
            self.selector.setEnabled(False)
            self.composer.btn_send.setEnabled(False)
            self.status.setText('Reserved ' + rid + ' - preparing durable request')
            worker = ApiWorker(run_fixture, key, rid, self.ledger.session, self.directory)
            self.worker = worker
            worker.done.connect(self.deliver)
            worker.failed.connect(lambda _: self.deliver({'request_id': rid, 'state': 'unknown', 'code': 'WORKER_FAILED'}))
            worker.finished.connect(worker.deleteLater)
            worker.start()

        def deliver(self, result):
            rid = result['request_id']
            accepted = self.ledger.accepts(rid) and not self.detached
            self.ledger.finish(rid)
            if not accepted: return
            self.status.setText(result['state'] + ' ' + result.get('code', '') + ' ' + rid)
            if result.get('content'):
                value = result['content']
                text = value if isinstance(value, str) else json.dumps(value, indent=2)
                self.history.add_bubble('EchoMind', '<pre>' + escape(text) + '</pre>')
            self.selector.setEnabled(True)
            self.preview()

        def closeEvent(self, event):
            # QApplication retains this host/worker through terminal completion.
            # No QThread termination or deletion and no automatic resubmission.
            self.detached = True
            self.ledger.close()
            self.composer.setEnabled(False)
            self.selector.setEnabled(False)
            event.accept()

    return Host()
