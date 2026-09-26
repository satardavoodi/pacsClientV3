"""Synthetic server reservations and concurrent job execution boundaries."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
from modules.ai_imaging.eagle_eye_remote.scheduling import Resources


def configuration(jobs=2, ram=4):
    return {'capacity': {'jobs': jobs, 'cpu_threads': 4, 'ram_mb': ram},
            'modules': {name: {'jobs': 1, 'cpu_threads': 2, 'ram_mb': 2} for name in MODULES}}


def test_parallel_execution_requires_explicit_ram_and_cpu_budgets():
    with pytest.raises(ValueError, match='CPU and RAM'):
        Resources({'capacity': {'jobs': 2}})


def test_waiting_lease_cancel_and_worker_failure_release_all_resources():
    resource = Resources(configuration(ram=2))
    cancelled = threading.Event()
    started = threading.Event()
    def waiter():
        started.set()
        with resource.lease('brain', cancelled):
            pytest.fail('Overcommitted RAM')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match='synthetic failure'):
            with resource.lease('brain', threading.Event()):
                future = pool.submit(waiter)
                assert started.wait(2)
                cancelled.set()
                with pytest.raises(RuntimeError, match='cancelled'):
                    future.result(timeout=2)
                raise RuntimeError('synthetic failure')
    assert resource.used == dict.fromkeys(resource.capacity, 0)
    assert not resource.pending


def test_two_owners_execute_concurrently_with_budget_and_isolated_results(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.server import Jobs
    from tests.code.ai_imaging.test_eagle_eye_remote import SyntheticSource, synthetic_runner, request
    barrier = threading.Barrier(2)
    def runner(job, cancel):
        barrier.wait(timeout=4)
        return synthetic_runner(job, cancel)
    jobs = Jobs(tmp_path, SyntheticSource(), runner, resources=configuration())
    try:
        first = jobs.submit('first', request())['job_id']
        second = jobs.submit('second', request('breast'))['job_id']
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if all(jobs.get(owner, job)['status'] == 'succeeded' for owner, job in [('first', first), ('second', second)]):
                break
            time.sleep(.02)
        assert jobs.get('first', first)['status'] == 'succeeded'
        assert jobs.get('second', second)['status'] == 'succeeded'
        with pytest.raises(KeyError):
            jobs.get('second', first)
        assert (tmp_path / first / 'artifacts.zip').is_file()
        assert (tmp_path / second / 'artifacts.zip').is_file()
    finally:
        jobs.close()


def test_default_stays_serial_client_quota_and_shutdown_are_bounded(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.server import Jobs, QueueFull
    from tests.code.ai_imaging.test_eagle_eye_remote import SyntheticSource, synthetic_runner, request
    entered = threading.Event()
    release = threading.Event()
    count = []
    def runner(job, cancel):
        count.append(job.name)
        entered.set()
        while not release.wait(.01):
            if cancel.is_set():
                raise RuntimeError('Cancelled')
        return synthetic_runner(job, cancel)
    jobs = Jobs(tmp_path, SyntheticSource(), runner, max_jobs_per_client=1)
    try:
        first = jobs.submit('first', request())['job_id']
        assert entered.wait(2)
        with pytest.raises(QueueFull):
            jobs.submit('first', request())
        second = jobs.submit('second', request())['job_id']
        deadline = time.monotonic() + 2
        while jobs.get('second', second)['status'] != 'waiting_for_resources' and time.monotonic() < deadline:
            time.sleep(.01)
        assert jobs.get('second', second)['status'] == 'waiting_for_resources'
        assert count == [first]
        jobs.cancel('second', second)
    finally:
        release.set()
        jobs.close()
    assert jobs.get('second', second)['status'] == 'cancelled'
    assert not jobs.cancelled
    assert jobs.resources.used == {'jobs': 0}
    with pytest.raises(QueueFull):
        jobs.submit('third', request())


def test_job_directory_has_one_service_owner_even_with_different_listeners(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.server import Jobs
    from tests.code.ai_imaging.test_eagle_eye_remote import SyntheticSource, synthetic_runner
    first = Jobs(tmp_path, SyntheticSource(), synthetic_runner)
    second = None
    try:
        with pytest.raises(ValueError, match='already owned'):
            second = Jobs(tmp_path, SyntheticSource(), synthetic_runner)
    finally:
        if second is not None:
            second.close()
        first.close()
    successor = Jobs(tmp_path, SyntheticSource(), synthetic_runner)
    successor.close()
