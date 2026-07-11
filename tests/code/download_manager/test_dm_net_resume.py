"""Guard: A3/A4 network auto-resume (OPT-04 / DM resume, 2026-07-08).

Covers the retry-budget policy (`_effective_retry_cap`) and the unified re-arm
(`_rearm_network_failed_studies`). Both are exercised as unbound methods on a
light fake `self` so no live DM widget / Qt event loop is needed. QTimer is
monkeypatched so the re-arm's deferred `_start_next_pending` is a no-op.
"""
from types import SimpleNamespace

import modules.download_manager.ui.widget._dm_workers as W
from modules.download_manager.core.enums import DownloadStatus
from modules.download_manager.core.constants import (
    MAX_RETRIES,
    MAX_RETRIES_TEMPORARY,
    MAX_RETRIES_TEMPORARY_UNSTABLE,
)


def _state(msg):
    return SimpleNamespace(error_message=msg, retry_count=0, study_uid="1.2.3")


# ── A4: retry-cap policy (DEFAULT-ON) ────────────────────────────────────
def test_cap_default_on_extends_temporary(monkeypatch):
    # Feature is default-ON: absent env → unstable cap for a temporary failure.
    monkeypatch.delenv("AIPACS_DM_NET_RESUME", raising=False)
    cap = W._DMWorkersMixin._effective_retry_cap(object(), _state("timeout"))
    assert cap == MAX_RETRIES_TEMPORARY_UNSTABLE == 100000


def test_cap_kill_switch_restores_legacy_temporary(monkeypatch):
    monkeypatch.setenv("AIPACS_DM_NET_RESUME", "0")
    cap = W._DMWorkersMixin._effective_retry_cap(object(), _state("timeout"))
    assert cap == MAX_RETRIES_TEMPORARY == 10


def test_cap_permanent_failure_is_max_retries(monkeypatch):
    # Permanent failures stay at MAX_RETRIES regardless of the policy flag.
    monkeypatch.delenv("AIPACS_DM_NET_RESUME", raising=False)
    assert W._DMWorkersMixin._effective_retry_cap(object(), _state("404 not found")) == MAX_RETRIES == 3
    monkeypatch.setenv("AIPACS_DM_NET_RESUME", "1")
    assert W._DMWorkersMixin._effective_retry_cap(object(), _state("decode error")) == MAX_RETRIES


# ── A3: unified re-arm ───────────────────────────────────────────────────
class _FakeStore:
    def __init__(self, states):
        self._states = states
        self.updates = []

    def get_by_status(self, status):
        return [s for s in self._states if s.status == status]

    def update(self, uid, **kw):
        self.updates.append((uid, kw))


def _fake_self(store):
    return SimpleNamespace(
        state_store=store,
        _start_next_pending=lambda: None,
        _net_exhausted_studies=set(),
    )


def _patch_qtimer(monkeypatch):
    class _FakeQTimer:
        @staticmethod
        def singleShot(_ms, _fn):
            return None
    monkeypatch.setattr(W, "QTimer", _FakeQTimer)


def test_rearm_kill_switch_is_noop(monkeypatch):
    monkeypatch.setenv("AIPACS_DM_NET_RESUME", "0")
    _patch_qtimer(monkeypatch)
    temp = SimpleNamespace(study_uid="A", status=DownloadStatus.FAILED,
                           error_message="connection reset")
    store = _FakeStore([temp])
    n = W._DMWorkersMixin._rearm_network_failed_studies(_fake_self(store), "net_up")
    assert n == 0
    assert store.updates == []


def test_rearm_default_on_revives_only_temporary_failures(monkeypatch):
    # Default-ON: absent env → re-arm acts on temporary failures.
    monkeypatch.delenv("AIPACS_DM_NET_RESUME", raising=False)
    _patch_qtimer(monkeypatch)
    temp = SimpleNamespace(study_uid="A", status=DownloadStatus.FAILED,
                           error_message="connection reset")
    perm = SimpleNamespace(study_uid="B", status=DownloadStatus.FAILED,
                           error_message="404 not found")
    store = _FakeStore([temp, perm])
    n = W._DMWorkersMixin._rearm_network_failed_studies(_fake_self(store), "net_up")
    assert n == 1
    assert len(store.updates) == 1
    uid, kw = store.updates[0]
    assert uid == "A"                                   # temporary revived
    assert kw["status"] == DownloadStatus.PENDING       # FAILED → PENDING
    assert kw["retry_count"] == 0                       # budget reset
    assert kw["error_message"] is None
    # The permanent failure ("B") is left untouched — must never hot-loop.
    assert all(u != "B" for u, _ in store.updates)
