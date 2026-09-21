"""Health assertions must fail closed; fixtures never use application logs."""
import json

import pytest

pytest.importorskip("mcp.server.fastmcp", reason="Optional external MCP tool dependency")

from tools.testing.aipacs_control_mcp import server


@pytest.fixture
def harness(tmp_path, monkeypatch):
    native = tmp_path / "native_fault.log"
    native.write_text("=== session start synthetic pid=101 ===\n", encoding="utf-8")
    monkeypatch.setattr(server, "_NATIVE_LOG_PATH", native, raising=False)
    monkeypatch.setattr(server, "_record", lambda *a, **kw: None)
    calls = []

    def run(append="", *, missing=False, truncate=False, disconnected=False,
            changed_pid=False, limit=0):
        if missing:
            native.unlink()

        stepped = False

        def send(action, *args, **kwargs):
            nonlocal stepped
            calls.append(action)
            if action == "synthetic_step":
                stepped = True
                if truncate:
                    native.write_text("short\n", encoding="utf-8")
                elif append:
                    with native.open("a", encoding="utf-8") as stream:
                        stream.write(append)
            if action == "snapshot_resources" and disconnected and stepped:
                return {"ok": False, "error_code": "TRANSPORT"}
            if action == "snapshot_resources":
                return {"ok": True, "data": {"pid": 202 if stepped and changed_pid else 101}}
            # Simulate the old wrong-path adapter returning a plausible zero.
            return {"ok": True, "data": {"total": 0, "file_exists": False}}

        monkeypatch.setattr(server, "_send", send)
        spec = tmp_path / "scenario.json"
        spec.write_text(json.dumps({
            "name": "synthetic-health", "max_new_native_faults": limit,
            "steps": [{"action": "synthetic_step"}, {
                "action": "assert_health", "entities": {"max_new_native_faults": limit},
            }],
        }), encoding="utf-8")
        return json.loads(server.run_scenario(str(spec))), calls

    return run


def test_new_native_record_is_not_a_successful_health_assertion(harness):
    result, calls = harness("Windows fatal exception: access violation\n")
    assert any(f["error"] == "NATIVE_FAULT_LIMIT" for f in result["failures"])
    assert "count_native_faults_since" not in calls


@pytest.mark.parametrize("case", ["missing", "truncate", "disconnected"])
def test_missing_evidence_or_transport_cannot_pass(harness, case):
    result, _ = harness(**{case: True})
    assert result["failures"], "Unavailable evidence is not a zero-fault pass"


def test_python_fatal_header_is_also_a_health_failure(harness):
    result, _ = harness("Fatal Python error: Aborted\n")
    assert result["failures"]


def test_clean_observed_window_passes_without_gui_log_read(harness):
    result, calls = harness()
    assert not result["failures"]
    assert "count_native_faults_since" not in calls


def test_explicit_fault_budget_is_honored(harness):
    result, _ = harness("Windows fatal exception: code 0x8001010d\n", limit=1)
    assert not result["failures"]


def test_snapshot_does_not_claim_requested_minutes_from_untimed_log(harness):
    harness()
    result = json.loads(server.snapshot_health(since_minutes=10))
    native = result["native_faults"]
    assert native["data"]["requested_window_exact"] is False
    assert native["data"]["verdict"] == "inconclusive"


def test_restarted_app_cannot_pass_for_original_session(harness):
    result, _ = harness(changed_pid=True)
    assert any(f["error"] == "HEALTH_PROCESS_CHANGED" for f in result["failures"])


def test_watchdog_overrun_is_a_separate_failure(harness):
    result, _ = harness("Timeout (0:00:05)!\n")
    assert any(f["error"] == "NATIVE_WATCHDOG_LIMIT" for f in result["failures"])


@pytest.mark.parametrize("limit", [-1, True, "1", None])
def test_invalid_health_budget_cannot_pass(harness, limit):
    result, _ = harness(limit=limit)
    assert result["failures"]


def test_missing_baseline_stops_before_any_scenario_work(harness):
    result, calls = harness(missing=True)
    assert result["steps_executed"] == 0
    assert "synthetic_step" not in calls
