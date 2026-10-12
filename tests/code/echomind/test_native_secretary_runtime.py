"""Synthetic native bridge tests without providers, patient data or live Qt."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest


from contextlib import contextmanager


@contextmanager
def isolated_audio_imports(monkeypatch, package='PacsClient.pacs.workstation_ui.home_ui'):
    """Restore existing UI references or evict newly imported UI cache entries."""
    import sys
    from types import ModuleType
    name = package + '.secretary_button_widget'
    before = {key for key in sys.modules if key == package or key.startswith(package + '.')}
    parent_before = sys.modules.get(package)
    missing = object()
    class_before = getattr(parent_before, 'SecretaryButtonWidget', missing)
    audio = ModuleType('sounddevice')
    def forbidden(*args, **kwargs):
        pytest.fail('Synthetic native bridge tests must not access audio hardware')
    audio.query_devices = audio.InputStream = audio.sleep = forbidden
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'sounddevice', audio)
        previous = sys.modules.get(name)
        if previous is not None:
            patch.setattr(previous, 'sd', audio)
        try:
            yield audio
        finally:
            # Never import real PortAudio to restore a headless test. Remove the
            # new UI namespace and parent bindings instead of retaining a stub.
            new = [key for key in sys.modules if
                   (key == package or key.startswith(package + '.')) and key not in before]
            for key in sorted(new, key=len, reverse=True):
                module = sys.modules.pop(key)
                parent_name, _, attribute = key.rpartition('.')
                parent = sys.modules.get(parent_name)
                if parent is not None and getattr(parent, attribute, missing) is module:
                    delattr(parent, attribute)
            if parent_before is not None:
                if class_before is missing:
                    if hasattr(parent_before, 'SecretaryButtonWidget'):
                        delattr(parent_before, 'SecretaryButtonWidget')
                else:
                    parent_before.SecretaryButtonWidget = class_before


@pytest.fixture(autouse=True)
def synthetic_audio_only(monkeypatch):
    """Native bridge guards never initialize PortAudio or capture real audio."""
    with isolated_audio_imports(monkeypatch) as audio:
        yield audio


@pytest.mark.parametrize('preexisting', [False, True])
def test_audio_isolation_restores_preexisting_and_first_import_cache(monkeypatch, preexisting):
    import sys
    from types import ModuleType
    package = '_synthetic_native_ui'
    name = package + '.secretary_button_widget'
    parent, ui, original = ModuleType(package), ModuleType(name), object()
    ui.sd = original
    if preexisting:
        parent.secretary_button_widget = ui
        parent.SecretaryButtonWidget = original
        monkeypatch.setitem(sys.modules, package, parent)
        monkeypatch.setitem(sys.modules, name, ui)
    with isolated_audio_imports(monkeypatch, package) as audio:
        if not preexisting:
            sys.modules[package], sys.modules[name] = parent, ui
            parent.secretary_button_widget = ui
            parent.SecretaryButtonWidget = object()
            ui.sd = audio
        assert ui.sd is audio
    if preexisting:
        assert sys.modules[name] is ui and ui.sd is original
        assert parent.SecretaryButtonWidget is original
    else:
        assert name not in sys.modules and package not in sys.modules
        assert not hasattr(parent, 'secretary_button_widget')


def test_native_guard_audio_is_explicitly_synthetic(synthetic_audio_only):
    import sounddevice
    assert sounddevice is synthetic_audio_only
    with pytest.raises(pytest.fail.Exception, match='must not access audio hardware'):
        sounddevice.query_devices()


def fixture():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_native_runtime import NativeSecretaryRuntime
    owner = ['human-a']
    memory = SimpleNamespace(get_conversation=lambda: {'id': 'session-a', 'mode': 'ask', 'title': 'Example'},
                             get_current_info=lambda: (3, 2))
    selector = SimpleNamespace(currentData=lambda: 'ask', findData=lambda mode: 0, setCurrentIndex=lambda index: None)
    widget = SimpleNamespace(_secretary_busy=False, _rec_running=False, mode_selector=selector,
                             _secretary_orchestrator=SimpleNamespace(memory_store=memory, _memory_store=memory))
    widget.submit_text_command = lambda text: setattr(widget, '_secretary_busy', True) or True
    runtime = NativeSecretaryRuntime(widget, lambda: owner[0])
    return runtime, widget, owner


def call(runtime, operation, **payload):
    if operation in {'command.submit', 'session.new', 'confirmation.answer'}:
        payload.setdefault('request_id', str(uuid4()))
    async def completed_call():
        result = await runtime.dispatch(operation, dict(owner_id='human-a', **payload))
        if operation in {'session.new', 'confirmation.answer'} and result.get('ok') and result.get('state') in {'queued', 'running'}:
            await asyncio.gather(*runtime.tasks)
            return await runtime.dispatch('command.result', {'owner_id': 'human-a', 'request_id': payload['request_id']})
        return result
    return asyncio.run(completed_call())


def test_owner_mismatch_and_changed_login_fail_closed():
    runtime, _, owner = fixture()
    assert asyncio.run(runtime.dispatch('status', {'owner_id': 'other'}))['error_code'] == 'OWNER_MISMATCH'
    owner[0] = 'human-b'
    assert call(runtime, 'status')['error_code'] == 'OWNER_MISMATCH'


def test_native_session_never_initializes_cold_memory_on_gui():
    runtime, widget, _ = fixture()
    class Cold:
        _memory_store = None
        @property
        def memory_store(self):
            pytest.fail('GUI must not initialize storage')
    widget._secretary_orchestrator = Cold()
    assert runtime._session() is None


def test_submission_uses_native_entry_busy_lock_and_actual_result():
    runtime, widget, _ = fixture()
    result = call(runtime, 'command.submit', session_id='session-a', text='Explain this page', mode='ask')
    assert result['state'] == 'running'
    assert call(runtime, 'command.submit', session_id='session-a', text='Again')['error_code'] == 'BUSY'
    runtime.record_result({'ok': True, 'message': 'Actual answer', 'action': 'ask'})
    widget._secretary_busy = False
    response = call(runtime, 'command.result', request_id=result['request_id'])
    assert response['response']['message'] == 'Actual answer'
    assert response['state'] == 'succeeded'


def test_stale_session_and_unknown_history_are_not_adopted():
    runtime, _, _ = fixture()
    assert call(runtime, 'session.get', session_id='old')['error_code'] == 'SESSION_CHANGED'
    assert call(runtime, 'session.resume', session_id='old')['error_code'] == 'UNSUPPORTED_OPERATION'


def test_confirmation_is_request_and_session_bound():
    runtime, widget, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Example', mode='act')
    assert runtime.defer_confirmation({'session_id': 'native:act'}, {'error_code': 'CONFIRM_REQUIRED', 'message': 'Confirm example'})
    pending = call(runtime, 'command.result', request_id=request['request_id'])
    assert pending['state'] == 'awaiting_confirmation'
    assert call(runtime, 'confirmation.answer', session_id='session-a', pending_request_id='wrong', confirmed=True)['error_code'] == 'CONFIRMATION_EXPIRED'
    assert call(runtime, 'confirmation.answer', session_id='other', pending_request_id=request['request_id'], confirmed=True)['error_code'] == 'SESSION_CHANGED'


@pytest.mark.parametrize('text', ['', 'x' * 20001])
def test_invalid_input_does_not_acquire_busy(text):
    runtime, widget, _ = fixture()
    assert call(runtime, 'command.submit', session_id='session-a', text=text)['error_code'] == 'INVALID_INPUT'
    assert not widget._secretary_busy


def test_submit_replay_does_not_execute_twice_and_payload_conflict_rejected():
    runtime, widget, _ = fixture()
    calls = []
    widget.submit_text_command = lambda text: calls.append(text) or True
    request_id = str(uuid4())
    payload = dict(request_id=request_id, session_id='session-a', text='Example')
    first = call(runtime, 'command.submit', **payload)
    assert call(runtime, 'command.submit', **payload) == first
    assert calls == ['Example']
    assert call(runtime, 'command.submit', **dict(payload, text='Changed'))['error_code'] == 'REQUEST_ID_CONFLICT'


def test_confirmation_uses_exact_native_session_and_renderer():
    runtime, widget, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Example')
    runtime.defer_confirmation({'session_id': 'native:act'}, {'error_code': 'CONFIRM_REQUIRED'})
    calls = []
    async def render(payload):
        calls.append(payload)
        runtime.record_result({'ok': True, 'message': 'Completed'}, rendered_text='Rendered completion')
    widget._secretary_execute_and_render_async = render
    answer_id = str(uuid4())
    payload = dict(session_id='session-a', pending_request_id=request['request_id'], request_id=answer_id, confirmed=True)
    result = call(runtime, 'confirmation.answer', **payload)
    assert result['text'] == 'Rendered completion'
    assert calls[0]['session_id'] == 'native:act'
    assert calls[0]['_confirmation_response'] is True
    assert call(runtime, 'confirmation.answer', **payload) == result
    assert len(calls) == 1


def test_failure_release_and_turn_projection():
    runtime, widget, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Example')
    runtime.finish()
    result = call(runtime, 'command.result', request_id=request['request_id'])
    assert result['state'] == 'failed'
    turns = call(runtime, 'session.get', session_id='session-a')['turns']
    assert [turn['role'] for turn in turns] == ['user', 'assistant']


def test_new_session_is_idempotent_and_uses_same_store_on_worker():
    import threading
    runtime, widget, _ = fixture()
    memory = widget._secretary_orchestrator.memory_store
    calls = []
    def reset():
        calls.append(threading.get_ident())
        memory.get_conversation = lambda: {'id': 'session-b', 'mode': 'act', 'title': 'New conversation'}
    memory.new_memory = reset
    widget._refresh_memory_label = lambda: None
    request_id = str(uuid4())
    result = call(runtime, 'session.new', session_id='session-a', request_id=request_id)
    assert result['session']['id'] == 'session-b'
    assert calls[0] != threading.get_ident()
    assert call(runtime, 'session.new', session_id='session-a', request_id=request_id) == result
    assert len(calls) == 1


def test_closed_runtime_reports_unknown_without_replay_or_modal():
    runtime, widget, owner = fixture()
    call(runtime, 'command.submit', session_id='session-a', text='Example')
    owner[0] = 'human-b'
    assert runtime.defer_confirmation({'session_id': 'native'}, {'error_code': 'CONFIRM_REQUIRED'})
    assert runtime.closed
    assert runtime.command['state'] == 'completion_unknown'
    assert widget._secretary_busy
    assert call(runtime, 'status')['error_code'] == 'OWNER_MISMATCH'


def test_mutation_requires_canonical_request_uuid():
    runtime, _, _ = fixture()
    assert call(runtime, 'command.submit', request_id='not-a-uuid', session_id='session-a', text='Example')['error_code'] == 'INVALID_REQUEST_ID'


def test_captured_history_survives_new_read_only_without_disk_adoption():
    runtime, widget, _ = fixture()
    call(runtime, 'command.submit', session_id='session-a', text='Example')
    runtime.record_result({'ok': True, 'message': 'Actual reply'}, rendered_text='Rendered reply')
    widget._secretary_busy = False
    memory = widget._secretary_orchestrator.memory_store
    memory.new_memory = lambda: setattr(memory, 'get_conversation', lambda: {'id': 'session-b', 'mode': 'ask', 'title': 'Second'})
    widget._refresh_memory_label = lambda: None
    call(runtime, 'session.new', session_id='session-a')
    sessions = call(runtime, 'session.list')['sessions']
    assert [s['id'] for s in sessions] == ['session-a', 'session-b']
    old = call(runtime, 'session.get', session_id='session-a')
    assert old['session']['read_only'] is True and old['session']['current'] is False
    assert [t['text'] for t in old['turns']] == ['Example', 'Rendered reply']
    assert call(runtime, 'session.get', session_id='unowned')['error_code'] == 'SESSION_CHANGED'
    assert call(runtime, 'command.submit', session_id='session-a', text='Do something')['error_code'] == 'SESSION_CHANGED'


def test_rollover_moves_only_current_request_to_actual_new_session():
    runtime, widget, _ = fixture()
    call(runtime, 'command.submit', session_id='session-a', text='Previous')
    runtime.record_result({'ok': True, 'message': 'Previous reply'})
    widget._secretary_busy = False
    call(runtime, 'command.submit', session_id='session-a', text='New cycle')
    memory = widget._secretary_orchestrator.memory_store
    memory.get_conversation = lambda: {'id': 'session-b', 'mode': 'ask', 'title': 'Rollover'}
    runtime.record_result({'ok': True, 'message': 'New reply'})
    assert [t['text'] for t in call(runtime, 'session.get', session_id='session-a')['turns']] == ['Previous', 'Previous reply']
    assert [t['text'] for t in call(runtime, 'session.get', session_id='session-b')['turns']] == ['New cycle', 'New reply']


def test_native_language_preference_validated_and_retained_for_pipeline():
    runtime, widget, _ = fixture()
    assert call(runtime, 'command.submit', session_id='session-a', text='Example', language_preference='invalid')['error_code'] == 'INVALID_LANGUAGE_PREFERENCE'
    seen = []
    widget.submit_text_command = lambda text: seen.append((text, runtime.command.get('language_preference'))) or True
    call(runtime, 'command.submit', session_id='session-a', text='123', language_preference='fa')
    assert seen == [('123', 'fa')]


def test_company_orchestrator_passes_current_text_and_preference_unchanged(monkeypatch):
    from modules.EchoMind.secretary import orchestrator, remote_planner
    engine = object.__new__(orchestrator.SecretaryOrchestrator)
    engine._get_memory_store_safe = lambda: None
    engine.executor = None
    calls = []
    monkeypatch.setattr(remote_planner, 'uses_server', lambda: True)
    monkeypatch.setattr(remote_planner, 'request', lambda phase, text, **fields: calls.append((text, fields)) or
                        {'route': {'modules': []}, 'answer': 'Synthetic reply'})
    engine._parse_plan({'text': '123', 'language_preference': 'fa', 'interaction_mode': 'ask'})
    assert calls[0][0] == '123'
    assert calls[0][1]['language_preference'] == 'fa'


def test_repair_passes_preference_to_same_server(monkeypatch):
    from modules.EchoMind.secretary import execution_repair, remote_planner
    calls = []
    monkeypatch.setattr(remote_planner, 'uses_server', lambda: True)
    monkeypatch.setattr(remote_planner, 'request', lambda phase, text, **fields: calls.append(fields) or {'plan': None})
    execution_repair.repair_plan_after_execution_failure(user_text='123', language='auto',
        language_preference='fa', failed_plan={}, execution_result={'error_code': 'SYNTHETIC'}, attempt=1, max_attempts=1)
    assert calls[0]['language_preference'] == 'fa'


def test_native_desktop_turns_are_captured_once_with_actual_rendered_text():
    runtime, widget, _ = fixture()
    runtime.observe_input('Native typed question')
    runtime.observe_output('Actual desktop rendering')
    turns = call(runtime, 'session.get', session_id='session-a')['turns']
    assert [t['text'] for t in turns] == ['Native typed question', 'Actual desktop rendering']
    call(runtime, 'command.submit', session_id='session-a', text='Mobile question')
    runtime.observe_input('Mobile question')
    runtime.observe_output('Mobile rendering')
    runtime.record_result({'ok': True}, rendered_text='Mobile rendering')
    turns = call(runtime, 'session.get', session_id='session-a')['turns']
    assert [t['text'] for t in turns] == ['Native typed question', 'Actual desktop rendering', 'Mobile question', 'Mobile rendering']


def test_history_is_bounded_by_turn_count_and_utf8_aggregate():
    runtime, _, _ = fixture()
    for _ in range(200):
        runtime.observe_input('Synthetic question')
        runtime.observe_output('Synthetic answer')
    assert len(runtime.turns) <= runtime.MAX_HISTORY_TURNS
    assert runtime.evicted_turns > 0
    for _ in range(20):
        runtime.observe_input('Synthetic question')
        runtime.observe_output('\u03b1' * 12000)
    assert runtime._history_bytes() <= runtime.MAX_HISTORY_BYTES


def test_history_session_count_bounded_and_never_drops_current():
    runtime, widget, _ = fixture()
    memory = widget._secretary_orchestrator.memory_store
    for number in range(100):
        memory.get_conversation = lambda number=number: {'id': str(number), 'title': 'Synthetic', 'mode': 'ask'}
        runtime.capture_session()
    assert len(runtime.sessions) <= runtime.MAX_HISTORY_SESSIONS
    assert runtime.sessions['99']['current']
    assert runtime.evicted_sessions > 0


def test_oversized_history_answer_does_not_truncate_actual_current_result():
    runtime, _, _ = fixture()
    call(runtime, 'command.submit', session_id='session-a', text='Example')
    actual = 'x' * (256 * 1024)
    runtime.record_result({'ok': True, 'message': actual}, rendered_text=actual)
    assert runtime.command['text'] == actual
    assert runtime.command['response']['message'] == actual
    assert runtime._history_bytes() <= runtime.MAX_HISTORY_BYTES
    assert runtime.evicted_turns > 0


def test_history_wire_budget_and_coverage_are_honest_for_unicode():
    import json
    runtime, _, _ = fixture()
    for _ in range(40):
        runtime.observe_input('Synthetic question')
        runtime.observe_output('\u03b1' * 12000)
    projection = call(runtime, 'session.get', session_id='session-a')
    coverage = projection['history_coverage']
    assert coverage['complete'] is False
    assert coverage['evicted_turns'] > 0
    assert coverage['retained_turns'] == len(runtime.turns)
    assert len(json.dumps(projection, ensure_ascii=True).encode('utf-8')) < 512 * 1024


def test_oversized_current_result_returns_explicit_error_not_disconnect_or_truncation():
    runtime, _, _ = fixture()
    request_id = str(uuid4())
    payload = dict(session_id='session-a', request_id=request_id, text='Example')
    call(runtime, 'command.submit', **payload)
    actual = '\u03b1' * 100000
    runtime.record_result({'ok': True, 'message': actual}, rendered_text=actual)
    result = call(runtime, 'command.result', request_id=request_id)
    assert result['error_code'] == 'RESULT_TOO_LARGE'
    assert result['state'] == 'succeeded'
    assert result['text_bytes'] == len(actual.encode('utf-8'))
    assert runtime.command['text'] == actual
    assert call(runtime, 'command.submit', **payload)['error_code'] == 'RESULT_TOO_LARGE'


def test_receipt_budget_preserves_idempotency_and_execution_state():
    runtime, widget, _ = fixture()
    first = None
    for _ in range(100):
        payload = dict(session_id='session-a', request_id=str(uuid4()), text='Synthetic request')
        first = first or payload
        call(runtime, 'command.submit', **payload)
        runtime.record_result({'ok': True, 'message': 'a' * 3000})
        widget._secretary_busy = False
    assert runtime._encoded_bytes(runtime.receipts) <= runtime.MAX_RECEIPT_BYTES
    old = call(runtime, 'command.submit', **first)
    assert old['error_code'] == 'RESULT_EVICTED'
    assert old['state'] == 'succeeded'
    assert not widget._secretary_busy
    assert len(runtime.receipts[first['request_id']][1]) == 64
    assert 'Synthetic request' not in runtime.receipts[first['request_id']][1]


@pytest.mark.parametrize('already_ready', [True, False])
def test_native_widget_schedules_connector_only_after_orchestrator_ready(monkeypatch, already_ready):
    from PacsClient.pacs.workstation_ui.home_ui import secretary_button_widget as ui
    from modules.ai_imaging.eagle_eye_remote import secretary_native_connector as connector
    engine = object()
    widget = SimpleNamespace(_secretary_orchestrator=engine if already_ready else None)
    seen = []
    monkeypatch.setattr(ui, 'create_secretary_orchestrator', lambda: engine)
    monkeypatch.setattr(connector, 'schedule_widget', lambda value: seen.append(value._secretary_orchestrator))
    assert ui.SecretaryButtonWidget._ensure_secretary_runtime(widget) is True
    assert seen == [engine]


def test_widget_cleanup_closes_connector_before_panel_teardown_without_cancelling_brain(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui import secretary_button_widget as ui
    from modules.ai_imaging.eagle_eye_remote import secretary_native_connector as connector
    order = []
    engine = SimpleNamespace(cancel=lambda: pytest.fail('Connector hook must not cancel local brain'))
    widget = SimpleNamespace(_secretary_orchestrator=engine,
        _response_panel=SimpleNamespace(close=lambda: order.append('panel')))
    monkeypatch.setattr(connector, 'close_widget', lambda value, *, idle_detach=None: order.append('connector'))
    ui.SecretaryButtonWidget.cleanup(widget)
    assert order == ['connector', 'panel']
    assert widget._secretary_orchestrator is engine


def test_delayed_confirmation_acceptance_is_immediate_and_task_survives_close():
    runtime, widget, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Example')
    runtime.defer_confirmation({'session_id': 'native:act'}, {'error_code': 'CONFIRM_REQUIRED'})
    async def scenario():
        release = asyncio.Event()
        calls = []
        async def render(payload):
            calls.append(payload)
            await release.wait()
            runtime.record_result({'ok': True, 'message': 'Actually complete'})
        widget._secretary_execute_and_render_async = render
        body = dict(owner_id='human-a', session_id='session-a', request_id=str(uuid4()),
                    pending_request_id=request['request_id'], confirmed=True)
        accepted = await asyncio.wait_for(runtime.dispatch('confirmation.answer', body), 0.1)
        assert accepted['state'] == 'running'
        assert (await runtime.dispatch('confirmation.answer', body))['state'] == 'running'
        await asyncio.sleep(0)
        runtime.close()
        assert all(not task.cancelled() for task in runtime.tasks)
        release.set()
        await asyncio.gather(*runtime.tasks)
        assert len(calls) == 1
        assert runtime.command['state'] == 'completion_unknown'
    asyncio.run(scenario())


def test_delayed_new_session_acceptance_and_polling_same_store():
    import threading
    runtime, widget, _ = fixture()
    gate = threading.Event()
    memory = widget._secretary_orchestrator.memory_store
    calls = []
    def reset():
        calls.append(True)
        gate.wait(2)
        memory.get_conversation = lambda: {'id': 'session-b', 'mode': 'act', 'title': 'New'}
    memory.new_memory = reset
    widget._refresh_memory_label = lambda: None
    async def scenario():
        body = dict(owner_id='human-a', session_id='session-a', request_id=str(uuid4()))
        try:
            accepted = await asyncio.wait_for(runtime.dispatch('session.new', body), 0.1)
            assert accepted['state'] in {'queued', 'running'}
            assert widget._secretary_busy
            assert (await runtime.dispatch('session.new', body))['state'] in {'queued', 'running'}
            gate.set()
            await asyncio.gather(*runtime.tasks)
            terminal = await runtime.dispatch('command.result', {'owner_id': 'human-a', 'request_id': body['request_id']})
            assert terminal['state'] == 'succeeded'
            assert terminal['session']['id'] == 'session-b'
            assert len(calls) == 1
            assert not widget._secretary_busy
        finally:
            gate.set()
    asyncio.run(scenario())


def test_confirmation_rejection_updates_original_and_fresh_receipts_to_cancelled():
    runtime, widget, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Example')
    runtime.defer_confirmation({'session_id': 'native:act'}, {'error_code': 'CONFIRM_REQUIRED'})
    async def render(payload):
        assert payload['text'] == 'no'
        runtime.record_result({'ok': True, 'message': 'Cancelled'})
    widget._secretary_execute_and_render_async = render
    answer_id = str(uuid4())
    response = call(runtime, 'confirmation.answer', session_id='session-a', request_id=answer_id,
                    pending_request_id=request['request_id'], confirmed=False)
    assert response['state'] == 'cancelled'
    assert call(runtime, 'command.result', request_id=request['request_id'])['state'] == 'cancelled'
    assert call(runtime, 'command.result', request_id=answer_id)['state'] == 'cancelled'


def test_new_session_task_survives_close_and_keeps_unknown_receipt():
    import threading
    runtime, widget, _ = fixture()
    gate = threading.Event()
    memory = widget._secretary_orchestrator.memory_store
    memory.new_memory = lambda: gate.wait(2)
    async def scenario():
        request_id = str(uuid4())
        await runtime.dispatch('session.new', {'owner_id': 'human-a', 'session_id': 'session-a', 'request_id': request_id})
        await asyncio.sleep(0)
        runtime.close()
        assert widget._secretary_busy
        assert all(not task.cancelled() for task in runtime.tasks)
        gate.set()
        await asyncio.gather(*runtime.tasks)
        assert runtime.receipts[request_id][2]['state'] == 'completion_unknown'
        assert not widget._secretary_busy
    asyncio.run(scenario())


def test_private_admission_hold_refuses_busy_and_fences_remote_mutations():
    runtime, widget, _ = fixture()
    transition_id = str(uuid4())
    widget._secretary_busy = True
    refused = call(runtime, 'admission.hold', transition_id=transition_id)
    assert refused['ok'] and refused['held'] is False and refused['busy'] is True
    widget._secretary_busy = False
    held = call(runtime, 'admission.hold', transition_id=transition_id)
    assert held['held'] is True and held['busy'] is False
    assert widget._native_secretary_service_quiesced
    assert call(runtime, 'command.submit', session_id='session-a', text='Example')['error_code'] == 'SERVICE_QUIESCED'
    assert call(runtime, 'session.new', session_id='session-a')['error_code'] == 'SERVICE_QUIESCED'
    assert call(runtime, 'admission.hold', transition_id=transition_id) == held
    assert call(runtime, 'admission.release', transition_id=str(uuid4()))['error_code'] == 'HOLD_MISMATCH'
    released = call(runtime, 'admission.release', transition_id=transition_id)
    assert released['held'] is False
    assert not widget._native_secretary_service_quiesced


def test_admission_hold_refuses_recording_and_pending_native_state():
    runtime, widget, _ = fixture()
    widget._rec_running = True
    assert call(runtime, 'admission.hold', transition_id=str(uuid4()))['busy'] is True
    widget._rec_running = False
    widget._secretary_orchestrator._sessions = {'native': {'pending': {'type': 'choose'}}}
    assert call(runtime, 'admission.hold', transition_id=str(uuid4()))['held'] is False


def test_widget_input_and_new_memory_respect_service_fence():
    from PacsClient.pacs.workstation_ui.home_ui import secretary_button_widget as ui
    logs = []
    widget = SimpleNamespace(_native_secretary_service_quiesced=True,
                             _post_log=lambda *args: logs.append(args))
    assert ui.SecretaryButtonWidget.submit_text_command(widget, 'Example') is False
    ui.SecretaryButtonWidget._on_new_memory(widget)
    ui.SecretaryButtonWidget._start_recording(widget)
    assert not getattr(widget, '_rec_running', False)
    assert logs


def test_close_owned_hold_releases_only_after_actual_idle():
    runtime, widget, _ = fixture()
    transition_id = str(uuid4())
    call(runtime, 'admission.hold', transition_id=transition_id)
    widget._secretary_busy = True
    runtime.close()
    assert widget._native_secretary_service_quiesced
    widget._secretary_busy = False
    runtime.after_idle()
    assert not widget._native_secretary_service_quiesced


def test_stale_release_cannot_clear_a_new_transition_fence():
    runtime, widget, _ = fixture()
    old_id, new_id = str(uuid4()), str(uuid4())
    call(runtime, 'admission.hold', transition_id=old_id)
    call(runtime, 'admission.release', transition_id=old_id)
    call(runtime, 'admission.hold', transition_id=new_id)
    assert call(runtime, 'admission.release', transition_id=old_id)['error_code'] == 'HOLD_MISMATCH'
    assert widget._native_secretary_service_quiesced
    assert runtime.service_transition_id == new_id


def test_delayed_local_task_prevents_idle_hold_even_if_busy_flag_was_released():
    runtime, widget, _ = fixture()
    async def scenario():
        release = asyncio.Event()
        task = asyncio.create_task(release.wait())
        widget._execution_tasks = {task}
        transition_id = str(uuid4())
        refused = await runtime.dispatch('admission.hold', {'owner_id': 'human-a', 'transition_id': transition_id})
        assert refused['held'] is False and refused['busy'] is True
        assert not task.cancelled()
        release.set()
        await task
        widget._execution_tasks.discard(task)
        accepted = await runtime.dispatch('admission.hold', {'owner_id': 'human-a', 'transition_id': transition_id})
        assert accepted['held'] is True and accepted['busy'] is False
    asyncio.run(scenario())


def test_idle_detach_proof_permanently_fences_this_native_runtime():
    runtime, widget, _ = fixture()
    detach_id = str(uuid4())
    proof = runtime.prepare_idle_detach(detach_id)
    assert proof == {'protocol': 1, 'detach_id': detach_id, 'runtime_instance': runtime.runtime_instance,
                     'owner_id': 'human-a', 'terminal_fence': True, 'busy': False}
    assert widget._native_secretary_terminal_fenced
    assert runtime.prepare_idle_detach(detach_id) == proof
    assert runtime.prepare_idle_detach(str(uuid4())) is None
    assert call(runtime, 'command.submit', session_id='session-a', text='Example')['error_code'] == 'TERMINAL_FENCED'
    assert call(runtime, 'session.new', session_id='session-a')['error_code'] == 'TERMINAL_FENCED'
    assert call(runtime, 'session.get', session_id='session-a')['ok']
    runtime.close()
    assert widget._native_secretary_terminal_fenced


@pytest.mark.parametrize('condition', ['busy', 'recording', 'pending', 'worker'])
def test_idle_detach_declines_active_or_uncertain_native_work(condition):
    runtime, widget, _ = fixture()
    if condition == 'busy':
        widget._secretary_busy = True
    elif condition == 'recording':
        widget._rec_running = True
    elif condition == 'pending':
        widget._secretary_orchestrator._sessions = {'native': {'pending': {'type': 'confirm'}}}
    else:
        widget._workers = [SimpleNamespace(isRunning=lambda: True)]
    assert runtime.prepare_idle_detach(str(uuid4())) is None
    assert not getattr(widget, '_native_secretary_terminal_fenced', False)


def test_idle_detach_rejects_changed_owner_or_invalid_identity():
    runtime, _, owner = fixture()
    assert runtime.prepare_idle_detach('invalid') is None
    owner[0] = 'other'
    assert runtime.prepare_idle_detach(str(uuid4())) is None


def test_terminal_detach_fences_native_input_and_memory_even_after_hold_release():
    from PacsClient.pacs.workstation_ui.home_ui import secretary_button_widget as ui
    runtime, widget, _ = fixture()
    widget._post_log = lambda *args: None
    transition_id = str(uuid4())
    call(runtime, 'admission.hold', transition_id=transition_id)
    runtime.prepare_idle_detach(str(uuid4()))
    call(runtime, 'admission.release', transition_id=transition_id)
    assert not widget._native_secretary_service_quiesced
    assert ui.SecretaryButtonWidget.submit_text_command(widget, 'Example') is False
    ui.SecretaryButtonWidget._on_new_memory(widget)
    ui.SecretaryButtonWidget._start_recording(widget)
    assert widget._native_secretary_terminal_fenced


def test_idle_detach_rejects_foreign_thread_and_uncertain_owner():
    from concurrent.futures import ThreadPoolExecutor
    runtime, _, _ = fixture()
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(runtime.prepare_idle_detach, str(uuid4())).result() is None
    runtime.owner_getter = lambda: (_ for _ in ()).throw(RuntimeError('Synthetic admission unavailable'))
    assert runtime.prepare_idle_detach(str(uuid4())) is None


@pytest.mark.parametrize('busy', [False, True])
def test_widget_cleanup_passes_only_actual_idle_detach_proof(monkeypatch, busy):
    from PacsClient.pacs.workstation_ui.home_ui import secretary_button_widget as ui
    from modules.ai_imaging.eagle_eye_remote import secretary_native_connector as connector
    runtime, widget, _ = fixture()
    widget._secretary_busy = busy
    captured = []
    monkeypatch.setattr(connector, 'close_widget', lambda value, *, idle_detach=None: captured.append(idle_detach))
    ui.SecretaryButtonWidget.cleanup(widget)
    assert len(captured) == 1
    if busy:
        assert captured[0] is None
    else:
        assert captured[0]['runtime_instance'] == runtime.runtime_instance
        assert captured[0]['terminal_fence'] is True
        assert widget._native_secretary_terminal_fenced


@pytest.mark.parametrize('action', ['advanced_search_patients', 'read_patients', 'list_patients'])
def test_native_patient_list_reply_and_history_are_aggregate_only(action):
    runtime, _, _ = fixture()
    call(runtime, 'command.submit', session_id='session-a', text='Bring the current patient list')
    runtime.record_result({'ok': True, 'action': action, 'message': 'SYNTHETIC_PRIVATE_ROW',
        'data': {'state': 'ready', 'count': 7, 'rows': ['SYNTHETIC_PRIVATE_ROW']}}, rendered_text='SYNTHETIC_PRIVATE_ROW')
    assert '7 studies' in runtime.command['text']
    assert 'SYNTHETIC_PRIVATE_ROW' not in str(runtime.command)
    assert 'SYNTHETIC_PRIVATE_ROW' not in str(runtime.turns)


def test_native_failed_patient_search_does_not_expose_raw_fallback():
    runtime, _, _ = fixture()
    call(runtime, 'command.submit', session_id='session-a', text='Bring the current patient list')
    runtime.record_result({'ok': False, 'action': 'advanced_search_patients', 'message': 'SYNTHETIC_PRIVATE_ROW'})
    assert 'SYNTHETIC_PRIVATE_ROW' not in str(runtime.command)


def test_native_desktop_patient_reply_history_replaces_raw_fallback():
    runtime, _, _ = fixture()
    runtime.observe_input('Bring the current patient list')
    runtime.observe_output('SYNTHETIC_PRIVATE_ROW')
    runtime.record_result({'ok': True, 'action': 'advanced_search_patients', 'message': 'SYNTHETIC_PRIVATE_ROW',
                           'data': {'state': 'ready', 'count': 2}}, rendered_text='SYNTHETIC_PRIVATE_ROW')
    assert 'SYNTHETIC_PRIVATE_ROW' not in str(runtime.turns)
    assert '2 studies' in runtime.turns[-1]['text']


def test_private_terminal_receipt_is_original_uuid_bound_and_not_in_mobile_dto():
    runtime, _, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Bring the current patient list')
    runtime.record_result({'ok': True, 'action': 'read_patients',
        'data': {'state': 'ready', 'count': 0, 'source': 'server', 'rows': ['SYNTHETIC_PRIVATE_ROW']}})
    assert runtime.terminal_receipts == {request['request_id']: {'state': 'ready', 'count': 0, 'source': 'server'}}
    result = call(runtime, 'command.result', request_id=request['request_id'])
    assert 'terminal_receipts' not in result and 'data' not in result['response']
    assert 'No matching' in result['text']
    assert 'SYNTHETIC_PRIVATE_ROW' not in str(result)


def test_private_terminal_receipts_are_bounded_and_pending_is_not_retained():
    runtime, _, _ = fixture()
    for _ in range(270):
        runtime._retain_terminal_receipt(str(uuid4()), {'state': 'ready', 'count': 1, 'source': 'local'})
    assert len(runtime.terminal_receipts) == 256
    request = call(runtime, 'command.submit', session_id='session-a', text='Bring the current patient list')
    runtime.record_result({'ok': True, 'action': 'read_patients', 'data': {'state': 'searching', 'count': 999}})
    assert request['request_id'] not in runtime.terminal_receipts
    assert 'still loading' in runtime.command['text']


def test_test_control_aggregate_lookup_is_strict_and_owner_bound():
    runtime, _, owner = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Bring the current patient list')
    runtime.record_result({'ok': True, 'action': 'read_patients',
        'data': {'state': 'ready', 'count': 4, 'source': 'server'}})
    entities = {'request_id': request['request_id'], 'session_id': 'session-a',
                'runtime_instance': runtime.runtime_instance}
    assert runtime.test_terminal_receipt(entities) == {'ok': True,
        'data': {'state': 'ready', 'count': 4, 'source': 'server'}}
    for delta in ({'request_id': 'invalid'}, {'request_id': str(uuid4())},
                  {'runtime_instance': str(uuid4())}, {'session_id': 'another'}, {'extra': 'secret'}):
        assert runtime.test_terminal_receipt(dict(entities, **delta)) == {'ok': False, 'error_code': 'NOT_FOUND'}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(runtime.test_terminal_receipt, entities).result()['ok'] is False
    owner[0] = 'other'
    assert runtime.test_terminal_receipt(entities)['ok'] is False


def test_confirmation_alias_keeps_private_receipt_under_original_uuid():
    runtime, widget, _ = fixture()
    request = call(runtime, 'command.submit', session_id='session-a', text='Bring the current patient list')
    runtime.defer_confirmation({'session_id': 'native:act'}, {'message': 'Confirm', 'action': 'advanced_search_patients'})
    alias = str(uuid4())
    async def execute(payload):
        runtime.record_result({'ok': True, 'action': 'read_patients',
            'data': {'state': 'ready', 'count': 3, 'source': 'server'}})
    widget._secretary_execute_and_render_async = execute
    call(runtime, 'confirmation.answer', session_id='session-a', request_id=alias,
         pending_request_id=request['request_id'], confirmed=True)
    assert request['request_id'] in runtime.terminal_receipts
    assert alias not in runtime.terminal_receipts
    assert call(runtime, 'command.result', request_id=alias)['pending_request_id'] == request['request_id']


def test_expired_and_closed_runtime_aggregate_lookup_is_not_found():
    runtime, _, _ = fixture()
    request = str(uuid4())
    runtime._retain_terminal_receipt(request, {'state': 'ready', 'count': 1, 'source': 'local'})
    entities = {'request_id': request, 'session_id': 'session-a', 'runtime_instance': runtime.runtime_instance}
    for _ in range(256):
        runtime._retain_terminal_receipt(str(uuid4()), {'state': 'ready', 'count': 1, 'source': 'local'})
    assert runtime.test_terminal_receipt(entities)['ok'] is False
    assert request not in runtime.terminal_receipt_sessions
    runtime.close()
    assert runtime.test_terminal_receipt(entities)['ok'] is False


def test_private_executed_dates_never_enter_mobile_text_history_or_response():
    runtime, _, _ = fixture()
    request=call(runtime,'command.submit',session_id='session-a',text='Bring the current patient list')
    runtime.record_result({'ok':True,'action':'__workflow__','data':{'steps':[
        {'tool':'advanced_search_patients','ok':True,'verified':True,
         'receipt':{'state':'ready','count':5,'source':'server'},
         'provenance':{'date_from':'20261009','date_to':'20261009'}}]}})
    result=runtime.test_terminal_receipt({'request_id':request['request_id'],
        'session_id':'session-a','runtime_instance':runtime.runtime_instance})
    assert result['data']['date_from'] == '20261009'
    assert result['data']['date_to'] == '20261009'
    assert '20261009' not in str(runtime.command) and '20261009' not in str(runtime.turns)


def test_terminal_diagnostic_retains_original_unknown_result_without_raw_data():
    runtime,widget,owner=fixture()
    widget._secretary_orchestrator._memory_store.get_conversation=lambda:{'id':'00000000-0000-4000-8000-000000000002','mode':'ask','title':'Synthetic'}
    request=call(runtime,'command.submit',session_id='00000000-0000-4000-8000-000000000002',text='Synthetic')
    runtime.record_result({'ok':True,'action':'advanced_search_patients','message':'PRIVATE_CONTENT',
        'data':{'state':'searching','count':123,'rows':['PRIVATE_CONTENT']}})
    entities={'request_id':request['request_id'],'session_id':'00000000-0000-4000-8000-000000000002','runtime_instance':runtime.runtime_instance}
    value=runtime.test_terminal_diagnostic(entities)
    assert value['ok'] is True
    assert value['data']['data_state']=='searching'
    assert value['data']['terminal_receipt_present'] is False
    assert 'PRIVATE_CONTENT' not in str(value) and '123' not in str(value)
    for delta in ({'request_id':str(uuid4())},{'session_id':'other'},{'runtime_instance':str(uuid4())},{'extra':'private'}):
        assert runtime.test_terminal_diagnostic(dict(entities,**delta))['ok'] is False
    owner[0]='foreign'
    assert runtime.test_terminal_diagnostic(entities)['ok'] is False


def test_terminal_diagnostic_bounds_and_closed_thread_session_fences():
    runtime,widget,owner=fixture()
    session=['00000000-0000-4000-8000-000000000002']
    widget._secretary_orchestrator._memory_store.get_conversation=lambda:{'id':session[0]}
    ids=[str(uuid4()) for _ in range(257)]
    for request in ids:runtime._retain_terminal_diagnostic(request,{'action':[], 'ok':1,
        'data':{'state':{},'count':True,'rows':['PRIVATE_CONTENT']}})
    assert len(runtime.terminal_diagnostics)==len(runtime.terminal_diagnostic_sessions)==256
    entities={'request_id':ids[-1],'session_id':'00000000-0000-4000-8000-000000000002','runtime_instance':runtime.runtime_instance}
    assert runtime.test_terminal_diagnostic(dict(entities,request_id=ids[0]))['ok'] is False
    value=runtime.test_terminal_diagnostic(entities)['data']
    assert value['action']=='unknown' and value['ok_type']=='unknown' and value['count_type']=='unknown'
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(runtime.test_terminal_diagnostic,entities).result()['ok'] is False
    session[0]='other'
    assert runtime.test_terminal_diagnostic(entities)['ok'] is False
    session[0]='00000000-0000-4000-8000-000000000002'
    runtime.closed=True
    assert runtime.test_terminal_diagnostic(entities)['ok'] is False


@pytest.mark.parametrize('field',['request_id','session_id','runtime_instance'])
def test_terminal_diagnostic_rejects_even_matching_noncanonical_identifiers(field):
    runtime,widget,owner=fixture()
    session=str(uuid4())
    widget._secretary_orchestrator._memory_store.get_conversation=lambda:{'id':session}
    request=str(uuid4())
    runtime._retain_terminal_diagnostic(request,{'ok':True,'action':'read_patients','data':{'state':'searching'}})
    entities={'request_id':request,'session_id':session,'runtime_instance':runtime.runtime_instance}
    invalid='not-a-uuid'
    if field=='request_id':
        runtime.terminal_diagnostics[invalid]=runtime.terminal_diagnostics[request]
        runtime.terminal_diagnostic_sessions[invalid]=session
    elif field=='session_id':
        session=invalid
        runtime.terminal_diagnostic_sessions[request]=invalid
    else:runtime.runtime_instance=invalid
    entities[field]=invalid
    assert runtime.test_terminal_diagnostic(entities)['ok'] is False


def test_private_planning_descriptor_keeps_original_uuid_fences_and_no_public_dto():
    runtime,widget,owner=fixture()
    session=str(uuid4())
    widget._secretary_orchestrator._memory_store.get_conversation=lambda:{'id':session,'mode':'act','title':'Synthetic'}
    request=call(runtime,'command.submit',session_id=session,text='Synthetic')
    runtime.record_result({'ok':False,'action':'unknown','error_code':'SERVER_REQUEST_INVALID',
        '_planning_diagnostic':{'stage':'schema','field_root':'conversation','error_type':'value_error',
            'valid':False,'wire_bytes':2000,'limit_bytes':131072,'raw':'PRIVATE_CONTENT'}})
    entities={'request_id':request['request_id'],'session_id':session,'runtime_instance':runtime.runtime_instance}
    value=runtime.test_terminal_diagnostic(entities)
    assert value['data']['planning']['field_root']=='conversation'
    assert 'PRIVATE_CONTENT' not in str(value)
    assert '_planning_diagnostic' not in str(runtime.command)
    assert runtime.test_terminal_diagnostic(dict(entities,session_id=str(uuid4())))['ok'] is False
    runtime.closed=True
    assert runtime.test_terminal_diagnostic(entities)['ok'] is False
