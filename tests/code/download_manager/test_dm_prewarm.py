"""Guard tests for the download subprocess pre-warm (Phase 1).

Pins the safety contract: the feature is OFF unless AIPACS_DM_PREWARM is set,
and when OFF every pool method is a no-op that spawns nothing and forces the
caller to fall back to the normal spawn path. Also pins the warm-worker entry
signature. No real subprocess is spawned here.
"""
import inspect

from modules.download_manager.workers import prewarm
from modules.download_manager.workers.download_process_entry import (
    _prewarmed_download_worker_main,
)


def test_prewarm_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AIPACS_DM_PREWARM", raising=False)
    assert prewarm.prewarm_enabled() is False


def test_prewarm_flag_parsing(monkeypatch):
    for val, expected in [("1", True), ("true", True), ("YES", True),
                          ("0", False), ("", False), ("off", False)]:
        monkeypatch.setenv("AIPACS_DM_PREWARM", val)
        assert prewarm.prewarm_enabled() is expected, val


def test_acquire_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("AIPACS_DM_PREWARM", raising=False)
    pool = prewarm.DownloadPrewarmPool()
    assert pool.acquire(task=object(), config_dict={}) is None
    assert pool._spare is None  # disabled => nothing spawned


def test_ensure_warm_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("AIPACS_DM_PREWARM", raising=False)
    pool = prewarm.DownloadPrewarmPool()
    pool.ensure_warm()
    assert pool._spare is None  # disabled => no spare spawned


def test_shutdown_safe_when_no_spare():
    pool = prewarm.DownloadPrewarmPool()
    pool.shutdown()  # must not raise with no spare


def test_warm_worker_entry_signature():
    assert callable(_prewarmed_download_worker_main)
    params = list(inspect.signature(_prewarmed_download_worker_main).parameters)
    assert params == [
        "task_queue", "result_queue", "cancel_event", "working_dir", "ready_event",
    ]


def test_singleton_pool():
    a = prewarm.get_download_prewarm_pool()
    b = prewarm.get_download_prewarm_pool()
    assert a is b
