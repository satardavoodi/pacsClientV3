"""Owner-bound GUI-loop facade over the existing Secretary widget.

The authenticated bridge supplies owner_id; it must never trust a phone body
for that value. This object neither authenticates users nor creates a brain.
Construct and call on the widget's existing qasync GUI loop only.
"""
from copy import deepcopy
import hashlib
import json
import threading
from uuid import UUID, uuid4


class NativeSecretaryRuntime:
    MAX_HISTORY_SESSIONS = 64
    MAX_HISTORY_TURNS = 128
    MAX_HISTORY_BYTES = 192 * 1024
    MAX_RECEIPT_BYTES = 192 * 1024
    MAX_RESULT_JSON_BYTES = 384 * 1024

    def __init__(self, widget, owner_getter):
        if getattr(widget, '_native_secretary_runtime', None) is not None:
            raise ValueError('The Secretary widget already has a native runtime')
        self.widget = widget
        self.gui_thread_id = threading.get_ident()
        self.owner_getter = owner_getter
        self.owner = owner_getter()
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise ValueError('An authenticated Windows human is required')
        self.command = None
        self.pending = None
        self.runtime_instance = str(uuid4())
        self.receipts = {}
        # Private aggregate corroboration; never part of mobile DTOs/history.
        self.terminal_receipts = {}
        self.terminal_receipt_sessions = {}
        self.terminal_provenance = {}
        self.terminal_diagnostics = {}
        self.terminal_diagnostic_sessions = {}
        self.last_local_result_id = None
        self.turns = []
        self.sessions = {}
        self.evicted_sessions = 0
        self.evicted_turns = 0
        self.local_request_id = None
        self.stage = 'Ready'
        self.closed = False
        self.tasks = set()
        self.confirmations = {}
        self.new_request_id = None
        self.service_transition_id = None
        self.last_released_transition_id = None
        self.terminal_detach_id = None
        widget._native_secretary_runtime = self
        self._session()

    @staticmethod
    def _encoded_bytes(value):
        # Count the conservative escaped JSON UTF-8 representation as well as
        # text, IDs and metadata, leaving space in the 512 KiB RPC frame.
        return len(json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode('utf-8'))

    def _history_bytes(self):
        return self._encoded_bytes({'sessions': list(self.sessions.values()), 'turns': self.turns})

    def _trim_history(self):
        while len(self.turns) > self.MAX_HISTORY_TURNS:
            self.turns.pop(0)
            self.evicted_turns += 1
        while len(self.sessions) > self.MAX_HISTORY_SESSIONS:
            self._evict_session()
        while self._history_bytes() > self.MAX_HISTORY_BYTES:
            if self.turns:
                self.turns.pop(0)
                self.evicted_turns += 1
            elif not self._evict_session():
                break  # Canonical current metadata is schema-bounded.

    def _evict_session(self):
        key = next((key for key, value in self.sessions.items() if not value['current']), None)
        if key is None:
            return False
        del self.sessions[key]
        self.evicted_sessions += 1
        removed = [turn for turn in self.turns if turn['session_id'] == key]
        self.evicted_turns += len(removed)
        self.turns = [turn for turn in self.turns if turn['session_id'] != key]
        return True

    def _history_coverage(self):
        return {'scope': 'authenticated_runtime',
                'complete': not (self.evicted_sessions or self.evicted_turns),
                'retained_sessions': len(self.sessions), 'retained_turns': len(self.turns),
                'retained_utf8_bytes': self._history_bytes(),
                'evicted_sessions': self.evicted_sessions, 'evicted_turns': self.evicted_turns,
                'session_limit': self.MAX_HISTORY_SESSIONS, 'turn_limit': self.MAX_HISTORY_TURNS,
                'utf8_byte_limit': self.MAX_HISTORY_BYTES}

    def _project_result(self, value):
        if self._encoded_bytes(value) <= self.MAX_RESULT_JSON_BYTES:
            return deepcopy(value)
        return {key: value.get(key) for key in
                ('request_id', 'session_id', 'runtime_instance', 'state')} | {
                    'ok': False, 'error_code': 'RESULT_TOO_LARGE',
                    'text_bytes': len(str(value.get('text') or '').encode('utf-8'))}

    def _trim_receipts(self):
        # Execution/idempotency receipts survive even when their text expires.
        for key, entry in list(self.receipts.items()):
            if self._encoded_bytes(self.receipts) <= self.MAX_RECEIPT_BYTES:
                break
            value = entry[2]
            if value.get('error_code') == 'RESULT_EVICTED':
                continue
            summary = {field: value.get(field) for field in
                       ('request_id', 'session_id', 'runtime_instance', 'state')}
            summary.update(ok=False, error_code='RESULT_EVICTED')
            self.receipts[key] = (*entry[:2], summary)

    @staticmethod
    def _uuid(value):
        try:
            return isinstance(value, str) and str(UUID(value)) == value
        except (ValueError, TypeError):
            return False

    @staticmethod
    def error(code):
        return {'ok': False, 'error_code': code}

    def _session(self):
        orchestrator = getattr(self.widget, '_secretary_orchestrator', None)
        # Attachment primes storage on a worker before constructing this facade.
        # Never fall back to a lazy database-opening property on the GUI loop.
        memory = getattr(orchestrator, '_memory_store', None)
        if memory is None:
            return None
        value = memory.get_conversation()
        number, cycles = memory.get_current_info()
        session = {**value, 'memory_number': number, 'cycle_count': cycles, 'cycle_limit': 10,
                   'current': True, 'read_only': False}
        for previous in self.sessions.values():
            previous.update(current=False, read_only=True)
        self.sessions[value['id']] = deepcopy(session)
        self._trim_history()
        return session

    def _busy(self):
        if self.widget._secretary_busy or self.widget._rec_running or self.pending:
            return True
        if any(not task.done() for task in self.tasks):
            return True
        if any(not task.done() for task in getattr(self.widget, '_execution_tasks', ())):
            return True
        states = getattr(getattr(self.widget, '_secretary_orchestrator', None), '_sessions', {})
        if any(state.get('pending') for state in states.values()):
            return True
        for worker in getattr(self.widget, '_workers', ()):
            try:
                if worker.isRunning():
                    return True
            except RuntimeError:
                return True  # Uncertain worker lifetime is not idle proof.
        return False

    def _release_owned_fence(self):
        if (self.service_transition_id is not None and
                getattr(self.widget, '_native_secretary_service_transition_id', None) == self.service_transition_id):
            self.widget._native_secretary_service_quiesced = False
            self.widget._native_secretary_service_transition_id = None
            self.last_released_transition_id = self.service_transition_id
            self.service_transition_id = None

    def after_idle(self):
        if self.closed and not self._busy():
            self._release_owned_fence()

    def prepare_idle_detach(self, detach_id):
        """Atomically fence an idle widget before its private detach handshake.

        This is GUI-only proof preparation, not proof that the remote broker
        received/acknowledged it. A busy or uncertain lifecycle emits no proof.
        """
        from PySide6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        if threading.get_ident() != self.gui_thread_id or (app is not None and QThread.currentThread() != app.thread()):
            return None
        try:
            eligible = self._uuid(detach_id) and not self.closed and self.owner_getter() == self.owner and not self._busy()
        except Exception:
            return None
        if not eligible:
            return None
        if self.terminal_detach_id is not None and detach_id != self.terminal_detach_id:
            return None
        self.terminal_detach_id = detach_id
        self.widget._native_secretary_terminal_fenced = True
        return {'protocol': 1, 'detach_id': detach_id, 'runtime_instance': self.runtime_instance,
                'owner_id': self.owner, 'terminal_fence': True, 'busy': False}

    def _admission(self, operation, payload):
        transition_id = payload.get('transition_id')
        if not self._uuid(transition_id):
            return self.error('INVALID_TRANSITION_ID')
        busy = self._busy()
        if operation == 'admission.hold':
            if self.service_transition_id is not None:
                if transition_id != self.service_transition_id:
                    return self.error('HOLD_CONFLICT')
            elif transition_id == self.last_released_transition_id:
                return self.error('HOLD_MISMATCH')
            elif not busy:
                self.service_transition_id = transition_id
                self.widget._native_secretary_service_transition_id = transition_id
                self.widget._native_secretary_service_quiesced = True
        else:
            expected = self.service_transition_id or self.last_released_transition_id
            if transition_id != expected:
                return self.error('HOLD_MISMATCH')
            if not busy:
                self._release_owned_fence()
        return {'ok': True, 'runtime_instance': self.runtime_instance,
                'transition_id': transition_id, 'held': self.service_transition_id is not None,
                'busy': busy}

    async def dispatch(self, operation, payload):
        # Thread checks occur before any QWidget or mutable state access.
        from PySide6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() != app.thread():
            return self.error('GUI_THREAD_REQUIRED')
        if not isinstance(payload, dict):
            return self.error('INVALID_INPUT')
        if self.closed or self.owner_getter() != self.owner or payload.get('owner_id') != self.owner:
            return self.error('OWNER_MISMATCH')
        if operation == 'transport.ping':
            return {'ok': True, 'runtime_instance': self.runtime_instance}
        if operation in {'admission.hold', 'admission.release'}:
            if operation == 'admission.hold' and self.terminal_detach_id is not None:
                return self.error('TERMINAL_FENCED')
            return self._admission(operation, payload)
        if operation not in {'status', 'session.list', 'session.get', 'session.new', 'command.submit',
                             'command.result', 'confirmation.answer'}:
            return self.error('UNSUPPORTED_OPERATION')
        if operation in {'session.new', 'command.submit', 'confirmation.answer'}:
            request_id = payload.get('request_id')
            if not self._uuid(request_id):
                return self.error('INVALID_REQUEST_ID')
            signature = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != 'owner_id'},
                sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')).hexdigest()
            previous = self.receipts.get(request_id)
            if previous:
                if previous[0] != operation or previous[1] != signature:
                    return self.error('REQUEST_ID_CONFLICT')
                if self.command and self.command['request_id'] == request_id:
                    return self._project_result({'ok': True, **self.command})
                return deepcopy(previous[2])
            if len(self.receipts) >= 256:
                return self.error('RUNTIME_REQUEST_LIMIT')
            if self.terminal_detach_id is not None:
                return self.error('TERMINAL_FENCED')
            if self.service_transition_id is not None:
                return self.error('SERVICE_QUIESCED')
        session = self._session()
        if operation == 'status':
            return {'ok': True, 'busy': self._busy(), 'stage': self.stage,
                    'runtime_instance': self.runtime_instance,
                    'session': session, 'history_supported': True, 'resume_supported': False,
                    'history_coverage': self._history_coverage()}
        if operation == 'session.list':
            return {'ok': True, 'runtime_instance': self.runtime_instance,
                    'sessions': deepcopy(list(self.sessions.values())),
                    'history_coverage': self._history_coverage()}
        if operation == 'session.get':
            selected = self.sessions.get(payload.get('session_id'))
            if selected is None:
                return self.error('SESSION_CHANGED')
            return {'ok': True, 'runtime_instance': self.runtime_instance, 'session': deepcopy(selected),
                    'turns': deepcopy([t for t in self.turns if t['session_id'] == selected['id']]),
                    'history_coverage': self._history_coverage()}
        if session is None:
            return self.error('NATIVE_SESSION_UNAVAILABLE')
        if operation != 'command.result' and payload.get('session_id') != session['id']:
            return self.error('SESSION_CHANGED')
        if operation == 'command.result':
            if not self.command or payload.get('request_id') != self.command['request_id']:
                receipt = self.receipts.get(payload.get('request_id'))
                if receipt and receipt[0] in {'command.submit', 'confirmation.answer', 'session.new'}:
                    return deepcopy(receipt[2])
                return self.error('REQUEST_NOT_FOUND')
            return self._project_result({'ok': True, **self.command, 'stage': self.stage})
        if operation == 'confirmation.answer':
            if not self.command:
                return self.error('REQUEST_NOT_FOUND')
            if not self.pending or type(payload.get('confirmed')) is not bool:
                return self.error('CONFIRMATION_EXPIRED')
            if payload.get('pending_request_id') != self.command['request_id']:
                return self.error('CONFIRMATION_EXPIRED')
            original = self.pending
            self.pending = None
            self.command['state'] = 'running'
            self.receipts[request_id] = (operation, signature, {'ok': True, 'request_id': request_id,
                'session_id': session['id'], 'state': 'running', 'runtime_instance': self.runtime_instance})
            self.confirmations[request_id] = self.command['request_id']
            self._save_command()
            self._own_task(self._run_confirmation(original, payload['confirmed']))
            return deepcopy(self.receipts[request_id][2])
        if self._busy():
            return self.error('BUSY')
        if operation == 'session.new':
            self.widget._secretary_busy = True
            self.new_request_id = request_id
            response = {'ok': True, 'request_id': request_id, 'session_id': session['id'],
                        'state': 'queued', 'runtime_instance': self.runtime_instance}
            self.receipts[request_id] = (operation, signature, response)
            self._trim_receipts()
            self._own_task(self._run_new_session(request_id, session['id']))
            return response
        text = payload.get('text')
        preference = payload.get('language_preference')
        if preference is not None and preference not in ('fa', 'en'):
            return self.error('INVALID_LANGUAGE_PREFERENCE')
        mode = payload.get('mode', session['mode'])
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            return self.error('INVALID_INPUT')
        if mode not in {'act', 'ask', 'guide'}:
            # Help Ticket has a separate packaging/delivery UI; do not fabricate
            # a terminal receipt for that workflow through this interface.
            return self.error('MODE_UNSUPPORTED')
        from modules.EchoMind.secretary.credential_guard import contains_api_credential
        if contains_api_credential(text):
            return self.error('LOCAL_CREDENTIAL_ENTRY_REQUIRED')
        index = self.widget.mode_selector.findData(mode)
        if index < 0:
            return self.error('MODE_UNSUPPORTED')
        self.widget.mode_selector.setCurrentIndex(index)
        self.command = {'request_id': request_id, 'session_id': session['id'],
                        'state': 'running', 'mode': mode, 'runtime_instance': self.runtime_instance,
                        'language_preference': preference}
        self.receipts[request_id] = (operation, signature, {'ok': True, **deepcopy(self.command)})
        turn = {'id': str(uuid4()), 'role': 'user', 'text': text,
                'request_id': request_id, 'session_id': session['id']}
        self.turns.append(turn)
        self._trim_history()
        try:
            accepted = self.widget.submit_text_command(text)
        except Exception:
            self.command = None
            if turn in self.turns:
                self.turns.remove(turn)
            self.receipts[request_id] = (operation, signature, self.error('SUBMISSION_FAILED'))
            return self.error('SUBMISSION_FAILED')
        if not accepted:
            self.command = None
            if turn in self.turns:
                self.turns.remove(turn)
            self.receipts[request_id] = (operation, signature, self.error('SUBMISSION_REJECTED'))
            return self.error('SUBMISSION_REJECTED')
        self._trim_receipts()
        return self._project_result({'ok': True, **self.command})

    def record_stage(self, stage):
        self.stage = str(stage)[:200]

    def _own_task(self, coroutine):
        import asyncio
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def finished(done):
            self.tasks.discard(done)
            self.after_idle()
        task.add_done_callback(finished)

    async def _run_confirmation(self, original, confirmed):
        from .secretary_result_text import confirmation_request
        original_id = original['_native_request_id']
        try:
            reply = confirmation_request(original, confirmed)
            if original.get('language_preference') is not None:
                reply['language_preference'] = original['language_preference']
            await self.widget._secretary_execute_and_render_async(reply)
            if (self.command and self.command['request_id'] == original_id and not confirmed
                    and self.command['state'] in {'succeeded', 'failed'}):
                self.command['state'] = 'cancelled'
        except BaseException:
            # Loop teardown/failed task does not prove side effects were undone.
            if self.command and self.command['request_id'] == original_id:
                self.command['state'] = 'completion_unknown'
        finally:
            if self.command and self.command['request_id'] == original_id:
                self._save_command()

    async def _run_new_session(self, request_id, old_session_id):
        import asyncio
        entry = self.receipts[request_id]
        value = dict(entry[2], state='running')
        self.receipts[request_id] = (*entry[:2], value)
        worker = asyncio.create_task(asyncio.to_thread(
            self.widget._secretary_orchestrator.memory_store.new_memory))
        try:
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Preserve the shared lock until the accepted worker stops.
                await asyncio.shield(worker)
                raise
            if self.closed or self.owner_getter() != self.owner:
                value.update(ok=False, state='completion_unknown', error_code='SESSION_NEW_COMPLETION_UNKNOWN')
            else:
                self.widget._secretary_session_id = 'secretary-home-' + uuid4().hex[:10]
                self.widget._refresh_memory_label()
                current = self._session()
                if current is None or current['id'] == old_session_id:
                    value.update(ok=False, state='failed', error_code='SESSION_NEW_FAILED')
                else:
                    self.command = None
                    value.update(state='succeeded', session=current, session_id=current['id'])
        except BaseException:
            value.update(ok=False, state='completion_unknown', error_code='SESSION_NEW_COMPLETION_UNKNOWN')
        finally:
            self.receipts[request_id] = (*entry[:2], value)
            self._trim_receipts()
            self.new_request_id = None
            self.widget._secretary_busy = False

    def capture_session(self):
        if not self.closed and self.owner_getter() == self.owner:
            self._session()

    def observe_input(self, text):
        """Record only new native input, never import the legacy log buffer."""
        if self.closed or self.owner_getter() != self.owner:
            return
        if self.command and self.command['state'] in {'running', 'awaiting_confirmation'}:
            return  # Mobile submit already registered this input.
        session = self._session()
        if session is None:
            return
        self.local_request_id = str(uuid4())
        self.last_local_result_id = None
        self.turns.append({'id': str(uuid4()), 'role': 'user', 'text': str(text),
                           'request_id': self.local_request_id, 'session_id': session['id']})
        self._trim_history()

    def observe_output(self, text):
        if self.closed or self.owner_getter() != self.owner or not self.local_request_id:
            return
        if self.command and self.command['state'] in {'running', 'awaiting_confirmation'}:
            return  # record_result captures the canonical mobile rendering.
        session = self._session()
        if session is None:
            return
        for turn in self.turns:
            if turn['request_id'] == self.local_request_id:
                turn['session_id'] = session['id']
        self.turns.append({'id': str(uuid4()), 'role': 'assistant', 'text': str(text),
                           'request_id': self.local_request_id, 'session_id': session['id']})
        self.last_local_result_id = self.local_request_id
        self.local_request_id = None
        self._trim_history()

    def defer_confirmation(self, payload, result):
        if not self.command or self.command['state'] != 'running':
            return False
        if self.closed or self.owner_getter() != self.owner:
            self.close()
            # Never turn a disconnected remote approval into a desktop modal.
            return True
        self.pending = dict(payload)
        self.pending['_native_request_id'] = self.command['request_id']
        self.command['state'] = 'awaiting_confirmation'
        self.command['pending_request_id'] = self.command['request_id']
        self.command['confirmation'] = {'message': str(result.get('message') or ''),
                                        'action': str(result.get('action') or '')}
        self._save_command()
        return True

    def _save_command(self):
        entry = self.receipts.get(self.command['request_id'])
        if entry:
            self.receipts[self.command['request_id']] = (*entry[:2], {'ok': True, **deepcopy(self.command)})
        for key, original_id in self.confirmations.items():
            if original_id == self.command['request_id'] and key in self.receipts:
                alias = self.receipts[key]
                response = {'ok': True, **deepcopy(self.command), 'request_id': key,
                            'pending_request_id': original_id}
                self.receipts[key] = (*alias[:2], response)
        self._trim_receipts()

    def record_result(self, result, rendered_text=None):
        from modules.EchoMind.secretary.patient_list_receipt import (
            aggregate_text, is_patient_list_result, terminal_receipt, terminal_provenance)
        patient_list = is_patient_list_result(result)
        text = aggregate_text(result) if patient_list else str(
            rendered_text if rendered_text is not None else result.get('message') or '')
        if not self.command or self.command['state'] != 'running':
            # Desktop rendering precedes the final result hook. Replace only
            # that correlated assistant turn, never another conversation.
            if patient_list and self.last_local_result_id:
                for turn in self.turns:
                    if (turn['request_id'] == self.last_local_result_id
                            and turn['role'] == 'assistant'):
                        turn['text'] = text
                self._retain_terminal_diagnostic(self.last_local_result_id, result)
                self._retain_terminal_receipt(self.last_local_result_id, terminal_receipt(result), terminal_provenance(result))
                self.last_local_result_id = None
                self._trim_history()
            return
        self._retain_terminal_diagnostic(self.command['request_id'], result)
        self.pending = None
        self.command['state'] = 'succeeded' if result.get('ok') else 'failed'
        if patient_list and result.get('ok') and not terminal_receipt(result):
            self.command['state'] = 'completion_unknown'
        self.command.pop('confirmation', None)
        self.command.pop('pending_request_id', None)
        self.command['response'] = {key: result.get(key) for key in
                                    ('ok', 'action', 'message', 'error_code')}
        if patient_list:
            self.command['response']['message'] = text
            self._retain_terminal_receipt(self.command['request_id'], terminal_receipt(result), terminal_provenance(result))
        session = self._session()
        if session:
            self.command['session_id'] = session['id']
            # A ten-cycle rollover occurs in the canonical preplan worker.
            # Its new request belongs to the actual new conversation, while
            # all earlier captured turns remain with the previous session.
            for turn in self.turns:
                if turn['request_id'] == self.command['request_id']:
                    turn['session_id'] = session['id']
        self.command['text'] = text
        self.turns.append({'id': str(uuid4()), 'role': 'assistant',
                           'text': self.command['text'], 'request_id': self.command['request_id'],
                           'session_id': self.command['session_id']})
        self._trim_history()
        self._save_command()

    def _retain_terminal_receipt(self, request_id, receipt, provenance=None):
        if receipt:
            from modules.EchoMind.secretary.patient_list_receipt import safe_provenance
            self.terminal_receipts[request_id] = deepcopy(receipt)
            self.terminal_provenance[request_id] = safe_provenance(provenance)
            session = self.widget._secretary_orchestrator.memory_store.get_conversation()
            self.terminal_receipt_sessions[request_id] = session['id']
            while len(self.terminal_receipts) > 256:
                expired = next(iter(self.terminal_receipts))
                del self.terminal_receipts[expired]
                self.terminal_receipt_sessions.pop(expired, None)
                self.terminal_provenance.pop(expired, None)

    def _retain_terminal_diagnostic(self, request_id, result):
        from modules.EchoMind.secretary.patient_list_receipt import result_diagnostic
        memory = self.widget._secretary_orchestrator._memory_store
        if memory is None:
            return
        self.terminal_diagnostics[request_id] = result_diagnostic(result)
        self.terminal_diagnostic_sessions[request_id] = memory.get_conversation()['id']
        while len(self.terminal_diagnostics) > 256:
            expired = next(iter(self.terminal_diagnostics))
            self.terminal_diagnostics.pop(expired, None)
            self.terminal_diagnostic_sessions.pop(expired, None)

    def test_terminal_diagnostic(self, entities):
        """Source-only fixed-shape observation, with no runtime initialization."""
        missing = {'ok': False, 'error_code': 'NOT_FOUND'}
        if (threading.get_ident() != self.gui_thread_id or self.closed
                or not isinstance(entities, dict)
                or set(entities) != {'request_id', 'session_id', 'runtime_instance'}):
            return missing
        try:
            memory = self.widget._secretary_orchestrator._memory_store
            request_id = entities['request_id']
            if not all(self._uuid(entities[key]) for key in ('request_id','session_id','runtime_instance')):
                return missing
            if (memory is None or self.owner_getter() != self.owner
                    or not self._uuid(request_id)
                    or entities['runtime_instance'] != self.runtime_instance
                    or self.terminal_diagnostic_sessions.get(request_id) != entities['session_id']
                    or memory.get_conversation()['id'] != entities['session_id']):
                return missing
            diagnostic = self.terminal_diagnostics.get(request_id)
            return {'ok': True, 'data': deepcopy(diagnostic)} if diagnostic else missing
        except Exception:
            return missing

    def test_terminal_receipt(self, entities):
        """Strict aggregate lookup for the source-only local Test Control channel."""
        missing = {'ok': False, 'error_code': 'NOT_FOUND'}
        if (threading.get_ident() != self.gui_thread_id or self.closed
                or not isinstance(entities, dict)
                or set(entities) != {'request_id', 'session_id', 'runtime_instance'}):
            return missing
        try:
            if self.owner_getter() != self.owner:
                return missing
            request_id = entities['request_id']
            if (not self._uuid(request_id) or entities['runtime_instance'] != self.runtime_instance
                    or self.terminal_receipt_sessions.get(request_id) != entities['session_id']
                    or self.widget._secretary_orchestrator.memory_store.get_conversation()['id']
                    != entities['session_id']):
                return missing
            from modules.EchoMind.secretary.patient_list_receipt import safe_receipt, safe_provenance
            receipt = safe_receipt(self.terminal_receipts.get(request_id))
            if not receipt:
                return missing
            dates = safe_provenance(self.terminal_provenance.get(request_id))
            if dates:
                receipt = dict(receipt, **dates)
            return {'ok': True, 'data': receipt} if receipt else missing
        except Exception:
            return missing

    def finish(self):
        if self.command and self.command['state'] == 'running':
            self.record_result({'ok': False, 'error_code': 'NATIVE_PIPELINE_FAILED',
                                'message': 'The native Secretary pipeline did not return a result.'})

    def close(self):
        """Invalidate admission without cancelling or replaying native work.

        The connector must tear down on logout. A running/pending operation is
        completion_unknown, not evidence that any local side effect was undone.
        """
        self.closed = True
        if self.new_request_id and self.new_request_id in self.receipts:
            entry = self.receipts[self.new_request_id]
            self.receipts[self.new_request_id] = (*entry[:2], dict(entry[2],
                state='completion_unknown', ok=False, error_code='SESSION_NEW_COMPLETION_UNKNOWN'))
        if self.command and self.command['state'] in {'running', 'awaiting_confirmation'}:
            self.command['state'] = 'completion_unknown'
            self._save_command()
        self.after_idle()
