"""Regression guard: cross-patient study isolation in patient open.

A patient tab must only ever contain studies that belong to that patient_id.
`_resolve_patient_study_uids` aggregates study UIDs from several fallbacks
(grouped table rows, the right-panel payload, search caches). Those fallbacks
could surface a study UID that actually belongs to a *different*, previously
viewed patient — which opened the tab as a bogus "multi-study" patient and
mixed another patient's thumbnails AND download-queue jobs in (observed live
2026-05-31: patient 43989 showed 41522's studies; `all_studies` grew 1->2->3
across opens).

The fix adds a pid-scope guard that drops any resolved study positively
attributable (via the local DB studies->patients join) to a different patient,
while keeping the clicked study and any study whose owner is unknown (a fresh
server patient not yet in the DB) so normal opens never break.

These tests pin that contract. They do NOT touch the multi-study render/offset
machinery — a genuine multi-study patient (several studies under ONE patient_id)
must still resolve all of them.
"""
import types

import pytest

import PacsClient.utils.db_manager as dbm
from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_patient_open as mod

_Mixin = mod._HPPatientOpenMixin

# study_uid -> owning patient row (as the studies->patients DB join returns)
_OWNERS = {
    "UID_A_41522": {"patient_id": "41522"},
    "UID_B_43989": {"patient_id": "43989"},
    "UID_X_42471": {"patient_id": "42471"},
    "UID_Y_42471": {"patient_id": "42471"},
    "UID_S_50000": {"patient_id": "50000"},
    "UID_OWN_60000": {"patient_id": "60000"},
    # "UID_UNK_*" intentionally absent -> owner unknown
}


@pytest.fixture(autouse=True)
def _fake_db(monkeypatch):
    monkeypatch.setattr(dbm, "get_patient_by_study_uid", lambda uid: _OWNERS.get(uid))


def _stub(study_map):
    """Minimal home-panel stub: no table / no right panel, only the pid-keyed
    study map fallback, so the test exercises the resolver + guard in isolation."""
    obj = types.SimpleNamespace()
    obj.patient_table_widget = None
    obj.right_panel_widget = None
    obj._patient_study_uid_map = dict(study_map)
    obj._log_open_trace = lambda *a, **k: None
    obj._resolve_patient_study_uids = _Mixin._resolve_patient_study_uids.__get__(obj)
    obj._study_owner_patient_id = _Mixin._study_owner_patient_id.__get__(obj)
    return obj


def test_cross_patient_study_is_dropped():
    # 43989's resolution wrongly contains 41522's study -> must be dropped.
    obj = _stub({"43989": ["UID_A_41522", "UID_B_43989"]})
    resolved = obj._resolve_patient_study_uids("43989", "UID_B_43989")
    assert "UID_A_41522" not in resolved
    assert "UID_B_43989" in resolved


def test_genuine_multistudy_same_patient_is_preserved():
    # Two studies under ONE patient_id (42471) must both survive the guard.
    obj = _stub({"42471": ["UID_X_42471", "UID_Y_42471"]})
    resolved = obj._resolve_patient_study_uids("42471", "UID_X_42471")
    assert set(resolved) == {"UID_X_42471", "UID_Y_42471"}


def test_single_study_unchanged():
    obj = _stub({"50000": ["UID_S_50000"]})
    resolved = obj._resolve_patient_study_uids("50000", "UID_S_50000")
    assert resolved == ["UID_S_50000"]


def test_unknown_owner_study_is_kept():
    # A study not yet in the local DB (server patient) has unknown owner and must
    # NOT be dropped, or fresh server opens would break.
    obj = _stub({"60000": ["UID_OWN_60000", "UID_UNK_999"]})
    resolved = obj._resolve_patient_study_uids("60000", "UID_OWN_60000")
    assert "UID_UNK_999" in resolved
    assert "UID_OWN_60000" in resolved


def test_clicked_study_always_kept_even_if_db_disagrees():
    # The fallback (clicked study) is authoritative — the user clicked this
    # patient's row — so it is never dropped even if the DB owner mismatches.
    obj = _stub({"43989": ["UID_A_41522", "UID_B_43989"]})
    resolved = obj._resolve_patient_study_uids("43989", "UID_A_41522")
    assert "UID_A_41522" in resolved
