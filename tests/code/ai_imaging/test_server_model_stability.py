"""Synthetic server scheduler lifecycle probes; never load models or contact PACS."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import subprocess
import sys

import pytest

from modules.ai_imaging.eagle_eye_remote.scheduling import Resources
from modules.ai_imaging.eagle_eye_remote.server import Jobs, QueueFull
from tests.code.ai_imaging.test_eagle_eye_remote import (
    SyntheticSource, request, synthetic_runner,
)
from tests.code.ai_imaging.test_eagle_eye_scheduling import configuration


@pytest.mark.parametrize('mode', ['crash', 'hang'])
def test_real_synthetic_worker_crash_or_cancelled_hang_leaves_no_running_process(
        tmp_path, monkeypatch, mode):
    from modules.ai_imaging.eagle_eye_remote import server

    real_popen = subprocess.Popen
    spawned = threading.Event()
    processes = []
    cancel = threading.Event()
    script = ('raise SystemExit(17)' if mode == 'crash' else
              'import time; time.sleep(60)')

    def launch(command, **options):
        process = real_popen([sys.executable, '-c', script], **options)
        processes.append(process)
        spawned.set()
        return process

    monkeypatch.setattr(server.subprocess, 'Popen', launch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(server.run_worker, tmp_path, cancel)
        try:
            assert spawned.wait(3)
            if mode == 'hang':
                cancel.set()
            with pytest.raises(RuntimeError, match='cancelled|execution failed'):
                future.result(timeout=10)
        finally:
            cancel.set()
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed
    assert not (tmp_path / 'worker-result.json').exists()


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), "Synthetic server did not reach its expected lifecycle boundary"


def settled(jobs, owner, job_id):
    wait_until(lambda: jobs.get(owner, job_id)['status'] in
               {'succeeded', 'failed', 'cancelled', 'interrupted'})
    wait_until(lambda: job_id not in jobs.cancelled)
    return jobs.get(owner, job_id)


def test_cancelled_fifo_head_does_not_strand_following_model():
    resources = Resources(configuration(ram=2))
    head_cancel = threading.Event()
    follower_entered = threading.Event()

    def head():
        with resources.lease('brain', head_cancel):
            pytest.fail('Cancelled FIFO head must not acquire a model reservation')

    def follower():
        with resources.lease('breast', threading.Event()):
            follower_entered.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        with resources.lease('brain', threading.Event()):
            first = pool.submit(head)
            wait_until(lambda: len(resources.pending) == 1)
            second = pool.submit(follower)
            wait_until(lambda: len(resources.pending) == 2)
            head_cancel.set()
            with pytest.raises(RuntimeError, match='cancelled'):
                first.result(timeout=2)
            assert not follower_entered.is_set()
        second.result(timeout=2)
    assert follower_entered.is_set()
    assert resources.used == dict.fromkeys(resources.capacity, 0)
    assert not resources.pending


@pytest.mark.parametrize('limiting_resource', ['ram_mb', 'cpu_threads'])
def test_parallel_job_limit_never_overrides_individual_resource_budget(limiting_resource):
    config = configuration()
    config['capacity'][limiting_resource] = 2
    resources = Resources(config)
    entered = threading.Event()

    def contender():
        with resources.lease('breast', threading.Event()):
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with resources.lease('brain', threading.Event()):
            future = pool.submit(contender)
            wait_until(lambda: len(resources.pending) == 1)
            assert resources.used['jobs'] == 1
            assert resources.used[limiting_resource] == 2
            assert not entered.is_set()
        future.result(timeout=2)
    assert entered.is_set()
    assert resources.used == dict.fromkeys(resources.capacity, 0)


def test_repeated_model_failures_release_client_quota_and_allow_later_success(tmp_path):
    calls = []

    def runner(job, cancel):
        calls.append(job.name)
        if len(calls) <= 20:
            raise RuntimeError('Synthetic model failure')
        return synthetic_runner(job, cancel)

    jobs = Jobs(tmp_path, SyntheticSource(), runner, max_jobs_per_client=1)
    try:
        for _ in range(20):
            job_id = jobs.submit('synthetic-owner', request())['job_id']
            assert settled(jobs, 'synthetic-owner', job_id)['status'] == 'failed'
            assert not (tmp_path / job_id / 'artifacts.zip').exists()
            assert jobs.resources.used == {'jobs': 0}
        recovered = jobs.submit('synthetic-owner', request())['job_id']
        assert settled(jobs, 'synthetic-owner', recovered)['status'] == 'succeeded'
        assert len(calls) == 21
    finally:
        jobs.close()


def test_saturated_global_queue_recovers_after_cooperative_cancel(tmp_path):
    entered = threading.Event()

    def runner(job, cancel):
        entered.set()
        if not cancel.wait(5):
            raise RuntimeError('Synthetic test cancellation deadline expired')
        raise RuntimeError('Synthetic cooperative cancellation')

    jobs = Jobs(tmp_path, SyntheticSource(), runner, max_jobs_per_client=16)
    try:
        ids = [jobs.submit('owner-a', request())['job_id'] for _ in range(16)]
        assert entered.wait(2)
        with pytest.raises(QueueFull, match='queue is full'):
            jobs.submit('owner-b', request())
        for job_id in ids:
            jobs.cancel('owner-a', job_id)
        for job_id in ids:
            assert settled(jobs, 'owner-a', job_id)['status'] == 'cancelled'
        jobs.runner = synthetic_runner
        recovered = jobs.submit('owner-b', request())['job_id']
        assert settled(jobs, 'owner-b', recovered)['status'] == 'succeeded'
        assert jobs.resources.used == {'jobs': 0}
        assert not jobs.resources.pending
    finally:
        jobs.close()


def test_one_owner_cannot_cancel_other_owner_active_model(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def runner(job, cancel):
        entered.set()
        assert release.wait(3)
        assert not cancel.is_set()
        return synthetic_runner(job, cancel)

    jobs = Jobs(tmp_path, SyntheticSource(), runner)
    try:
        job_id = jobs.submit('owner-a', request())['job_id']
        assert entered.wait(2)
        with pytest.raises(KeyError):
            jobs.cancel('owner-b', job_id)
        assert not jobs.cancelled[job_id].is_set()
        release.set()
        assert settled(jobs, 'owner-a', job_id)['status'] == 'succeeded'
    finally:
        release.set()
        jobs.close()


def test_restart_preserves_completed_job_idempotency_without_rerunning_model(tmp_path):
    original_request = request()
    calls = []

    def runner(job, cancel):
        calls.append(job.name)
        return synthetic_runner(job, cancel)

    first = Jobs(tmp_path, SyntheticSource(), runner)
    try:
        job_id = first.submit('owner-a', original_request)['job_id']
        assert settled(first, 'owner-a', job_id)['status'] == 'succeeded'
    finally:
        first.close()
    restarted = Jobs(tmp_path, SyntheticSource(), runner)
    try:
        assert restarted.submit('owner-a', original_request) == {'job_id': job_id}
        assert restarted.get('owner-a', job_id)['status'] == 'succeeded'
        assert calls == [job_id]
        with pytest.raises(KeyError):
            restarted.get('owner-b', job_id)
    finally:
        restarted.close()
