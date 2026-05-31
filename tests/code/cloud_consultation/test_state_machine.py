"""Status-transition + conflict-detection tests (pure functions)."""

import pytest

from modules.cloud_consultation.consultation.models import ConsultationStatus as S
from modules.cloud_consultation.sync import state_machine as sm


def test_allowed_transitions():
    assert sm.can_transition(S.PENDING.value, S.UPLOADED.value)
    assert sm.can_transition(S.UPLOADED.value, S.DOWNLOADED.value)
    assert sm.can_transition(S.DOWNLOADED.value, S.REVIEWED.value)
    assert sm.can_transition(S.REVIEWED.value, S.ANSWERED.value)
    assert sm.can_transition(S.ANSWERED.value, S.CLOSED.value)
    assert sm.can_transition(S.PENDING.value, S.PENDING.value)   # idempotent
    assert sm.can_transition(S.UPLOADED.value, S.CONFLICT.value)


def test_illegal_transitions():
    assert not sm.can_transition(S.PENDING.value, S.REVIEWED.value)
    assert not sm.can_transition(S.PENDING.value, S.ANSWERED.value)
    assert not sm.can_transition(S.CLOSED.value, S.UPLOADED.value)   # terminal
    with pytest.raises(ValueError):
        sm.assert_transition(S.PENDING.value, S.ANSWERED.value)


def test_conflict_detection():
    base = {"package_version": 1, "integrity": {"files_sha256": {"a": "H1"}}}
    same = {"package_version": 1, "integrity": {"files_sha256": {"a": "H1"}}}
    diverged = {"package_version": 1, "integrity": {"files_sha256": {"a": "H2"}}}
    newer = {"package_version": 2, "integrity": {"files_sha256": {"a": "H2"}}}

    assert sm.detect_conflict(base, same) is None
    conflict = sm.detect_conflict(base, diverged)
    assert conflict is not None
    assert conflict.reason == "divergent_same_version"
    assert conflict.local_version == 1 and conflict.remote_version == 1
    # Higher remote version is a normal update, not a conflict.
    assert sm.detect_conflict(base, newer) is None
