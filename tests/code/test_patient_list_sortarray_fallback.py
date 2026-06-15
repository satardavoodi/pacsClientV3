"""MongoDB $sortArray compatibility fallback for GetPatientList (incident 2026-06-15).

The backend's GetPatientList aggregation uses $sortArray, unsupported on MongoDB
< 5.2 -> the pipeline fails (InvalidPipelineOperator / code 168) and the client got
no patient data. The client now degrades gracefully: normal first, then ONLY on the
$sortArray error fall back to compatibility -> simple/no_sort + client-side sort,
caching the first working mode. A healthy server is unaffected; unrelated failures
(timeouts) are not degraded.

Tested with a fake send_request (no real socket / server).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from modules.network import socket_client as sc

_SORT_ERR = {
    "status": "error",
    "error": "Invalid $addFields :: caused by :: Unrecognized expression '$sortArray'",
    "code": 168,
    "codeName": "InvalidPipelineOperator",
}


def _ok(patients):
    return {"status": "success", "data": {"patients": patients}}


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(sc, "_PATIENT_LIST_FALLBACK_MODE", None, raising=False)
    yield


def _client(send_impl, monkeypatch):
    c = sc.PatientListSocketClient(host="x", port=1, timeout=1)  # real cfg, no connect
    monkeypatch.setattr(c, "send_request", send_impl)
    return c


def test_compat_error_detection():
    assert sc._is_sortarray_compat_error(_SORT_ERR)
    assert sc._is_sortarray_compat_error({"error": "blah code: 168 blah"})
    assert sc._is_sortarray_compat_error({"codeName": "InvalidPipelineOperator"})
    # Must NOT fire on unrelated failures.
    assert not sc._is_sortarray_compat_error({"status": "error", "error": "timed out"})
    assert not sc._is_sortarray_compat_error(None)


def test_client_sort_newest_first():
    out = sc._patient_list_client_sort(
        [{"study_date": "20200101"}, {"study_date": "20260101"}, {"study_date": "20230101"}]
    )
    assert [p["study_date"] for p in out] == ["20260101", "20230101", "20200101"]


def test_healthy_server_uses_normal_no_fallback(monkeypatch):
    calls = []

    def send(ep, params):
        calls.append(dict(params))
        return _ok([{"patient_id": "1"}])

    res = _client(send, monkeypatch).get_patient_list_safe(limit=100)
    assert res == [{"patient_id": "1"}]
    assert len(calls) == 1                                   # only the normal request
    assert "compatibility_mode" not in calls[0]
    assert "simple_query" not in calls[0]
    assert sc._PATIENT_LIST_FALLBACK_MODE is None            # nothing cached on healthy path


def test_sortarray_error_falls_back_to_compatibility(monkeypatch):
    calls = []

    def send(ep, params):
        calls.append(dict(params))
        return _ok([{"patient_id": "1"}]) if params.get("compatibility_mode") else _SORT_ERR

    res = _client(send, monkeypatch).get_patient_list_safe(limit=100)
    assert res == [{"patient_id": "1"}]
    assert len(calls) == 2                                   # normal -> compatibility
    assert calls[1].get("compatibility_mode") is True
    assert sc._PATIENT_LIST_FALLBACK_MODE == "compatibility"  # cached


def test_cached_mode_is_reused(monkeypatch):
    monkeypatch.setattr(sc, "_PATIENT_LIST_FALLBACK_MODE", "compatibility", raising=False)
    calls = []

    def send(ep, params):
        calls.append(dict(params))
        return _ok([{"patient_id": "1"}]) if params.get("compatibility_mode") else _SORT_ERR

    res = _client(send, monkeypatch).get_patient_list_safe(limit=100)
    assert res == [{"patient_id": "1"}]
    assert len(calls) == 1                                   # straight to the cached mode
    assert calls[0].get("compatibility_mode") is True


def test_falls_back_to_simple_and_client_sorts(monkeypatch):
    calls = []

    def send(ep, params):
        calls.append(dict(params))
        if params.get("simple_query"):
            return _ok([
                {"patient_id": "a", "study_date": "20200101"},
                {"patient_id": "b", "study_date": "20260101"},
            ])
        return _SORT_ERR  # both normal and compatibility fail with $sortArray

    res = _client(send, monkeypatch).get_patient_list_safe(limit=100)
    assert [p["patient_id"] for p in res] == ["b", "a"]      # client-side sorted newest first
    assert len(calls) == 3                                   # normal -> compatibility -> simple
    assert calls[2].get("no_sort") is True
    assert sc._PATIENT_LIST_FALLBACK_MODE == "simple"


def test_non_compat_error_does_not_escalate(monkeypatch):
    calls = []

    def send(ep, params):
        calls.append(dict(params))
        return {"status": "error", "error": "timed out"}

    res = _client(send, monkeypatch).get_patient_list_safe(limit=100)
    assert res is None
    assert len(calls) == 1                                   # no escalation on a non-$sortArray error


def test_force_compatibility_starts_in_compat(monkeypatch):
    calls = []

    def send(ep, params):
        calls.append(dict(params))
        return _ok([{"patient_id": "1"}]) if params.get("compatibility_mode") else _SORT_ERR

    c = _client(send, monkeypatch)  # build with real cfg first

    class _Cfg:
        def get_patient_list_fallback_mode(self):
            return None

        def is_force_compatibility_mode(self):
            return True

    monkeypatch.setattr(sc, "get_socket_config", lambda: _Cfg())
    res = c.get_patient_list_safe(limit=100)
    assert res == [{"patient_id": "1"}]
    assert calls[0].get("compatibility_mode") is True        # started in compat, skipped normal
