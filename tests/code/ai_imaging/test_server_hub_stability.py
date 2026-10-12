"""Synthetic server hub concurrency and paid-call safety qualification.

No listener, live database, credentials, model or external provider is used.
"""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from uuid import uuid4

import pytest

from modules.ai_imaging.eagle_eye_remote.echomind import hosting, runtime
from modules.ai_imaging.eagle_eye_remote.usage import record_tokens


@pytest.fixture
def hub(tmp_path):
    (tmp_path / 'settings.json').write_text('{}', encoding='utf-8')
    return hosting.EchoMind(
        {'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'history'),
         'max_requests': 2, 'max_requests_per_client': 1},
        ['alpha', 'beta', 'gamma'],
    )


def body(text='Synthetic request', rid=None):
    return {'workflow': 'chat', 'text': text, 'request_id': rid or str(uuid4()),
            'case_context': {'study_uid': '1.2.840.999'}}


def rejected(hub, owner, request, status):
    with pytest.raises(hosting.RequestFailed) as error:
        hub.process(owner, request)
    assert error.value.status == status


def test_parallel_clients_have_isolated_results_accounting_and_history(hub, monkeypatch):
    barrier = threading.Barrier(2)
    outside_directory = runtime.private_dir()

    def provider(request):
        barrier.wait(timeout=5)
        assert runtime.private_dir() == hub.directory
        count = 3 if request.text == 'alpha' else 7
        record_tokens({'input_tokens': count, 'output_tokens': 1}, 'synthetic')
        return {'content': request.text}

    monkeypatch.setattr(hosting.service, 'process', provider)
    requests = [body('alpha'), body('beta')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(hub.process, owner, request)
                   for owner, request in zip(('alpha', 'beta'), requests)]
        results = [future.result(timeout=10) for future in futures]
    assert [result['content'] for result in results] == ['alpha', 'beta']
    assert results[0]['accounting'] != results[1]['accounting']
    assert runtime.private_dir() == outside_directory
    for index, owner in enumerate(('alpha', 'beta')):
        assert hub.history.case_result([owner], '1.2.840.999', requests[index]['request_id'])['content'] == owner
        with pytest.raises(KeyError):
            hub.history.case_result([owner], '1.2.840.999', requests[1-index]['request_id'])


def test_exhausted_global_and_owner_slots_reject_without_provider_and_recover(hub, monkeypatch):
    release = threading.Event()
    entered = threading.Barrier(3)
    calls = []

    def provider(request):
        calls.append(request.text)
        entered.wait(timeout=5)
        assert release.wait(5)
        return {'content': request.text}

    monkeypatch.setattr(hosting.service, 'process', provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(hub.process, owner, body(owner)) for owner in ('alpha', 'beta')]
        try:
            entered.wait(timeout=5)
            rejected(hub, 'alpha', body('owner-overflow'), 429)
            rejected(hub, 'gamma', body('global-overflow'), 429)
            assert sorted(calls) == ['alpha', 'beta']
        finally:
            release.set()
        for future in futures:
            future.result(timeout=10)
    monkeypatch.setattr(hosting.service, 'process', lambda request: {'content': request.text})
    assert hub.process('gamma', body('recovered'))['content'] == 'recovered'


@pytest.mark.parametrize('failure', [OSError('synthetic disk failure'), sqlite3.OperationalError('synthetic lock')])
def test_history_admission_failure_never_calls_provider(hub, monkeypatch, failure):
    calls = []
    monkeypatch.setattr(hosting.service, 'process', lambda request: calls.append(request))
    def fail(*args):
        raise failure
    monkeypatch.setattr(hub.history, 'begin', fail)
    rejected(hub, 'alpha', body(), 503)
    assert calls == []


@pytest.mark.parametrize('provider_fails,save_fails', [(False, False), (True, False), (False, True), (True, True)])
def test_retry_of_accepted_identifier_never_repeats_paid_call(hub, monkeypatch, provider_fails, save_fails):
    calls = []
    def provider(request):
        calls.append(request.text)
        if provider_fails:
            raise RuntimeError('synthetic provider outage')
        return {'content': 'Synthetic answer'}
    monkeypatch.setattr(hosting.service, 'process', provider)
    if save_fails:
        def fail(*args, **kwargs):
            raise sqlite3.OperationalError('synthetic history outage')
        monkeypatch.setattr(hub.history, 'finish', fail)
    request = body()
    if provider_fails or save_fails:
        rejected(hub, 'alpha', request, 502 if provider_fails else 503)
    else:
        hub.process('alpha', request)
    rejected(hub, 'alpha', request, 409)
    assert len(calls) == 1
    # Both semaphores must be usable after every success/error combination.
    assert hub.slots.acquire(blocking=False)
    hub.slots.release()
    assert hub.clients['alpha'].acquire(blocking=False)
    hub.clients['alpha'].release()


def test_invalid_and_case_denied_work_never_reaches_provider(hub, monkeypatch):
    calls = []
    monkeypatch.setattr(hosting.service, 'process', lambda request: calls.append(request))
    rejected(hub, 'alpha', dict(body(), endpoint='https://synthetic.invalid'), 422)
    def deny(*args):
        raise PermissionError('synthetic case denial')
    hub.verify_case = deny
    rejected(hub, 'alpha', body(), 403)
    assert calls == []


def test_concurrent_duplicate_identifier_sends_only_one_provider_call(hub, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    def provider(request):
        calls.append(request.text)
        entered.set()
        assert release.wait(5)
        return {'content': 'Synthetic answer'}
    monkeypatch.setattr(hosting.service, 'process', provider)
    request = body()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(hub.process, 'alpha', request)
        try:
            assert entered.wait(5)
            # A different admitted owner can reach the global history uniqueness guard.
            rejected(hub, 'beta', request, 409)
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=10)['content'] == 'Synthetic answer'
