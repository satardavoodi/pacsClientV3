"""Synthetic, bounded native-window evidence; no GUI, database or real log I/O."""
from pathlib import Path

import pytest

from tools.diagnostics import native_fault_probe as probe

MARKER = b"=== session start synthetic pid=101 ===\n"
AV = b"Windows fatal exception: access violation\n"


@pytest.fixture
def native(tmp_path):
    path = tmp_path / "native_fault.log"
    path.write_bytes(MARKER + AV)
    return path


def append(path, data):
    with path.open("ab") as stream:
        stream.write(data)


def test_baseline_excludes_history_and_checks_are_cumulative(native):
    window = probe.NativeFaultWindow(native, expected_pid=101)
    assert window.check()["data"]["total"] == 0
    append(native, AV)
    assert window.check()["data"]["total"] == 1
    assert window.check()["data"]["total"] == 1
    append(native, AV)
    assert window.check()["data"]["total"] == 2


def test_fault_types_are_distinct_and_not_terminal_classification(native):
    window = probe.NativeFaultWindow(native)
    append(native, b"Fatal Python error: Aborted\nTimeout (0:00:05)!\n" + AV)
    data = window.check()["data"]
    assert (data["total"], data["windows_exceptions"],
            data["python_fatal_records"], data["watchdog_dumps"]) == (2, 1, 1, 1)
    assert data["terminal_crash_count"] is None
    assert data["process_attribution"] == "unavailable_shared_log"


def test_embedded_text_does_not_inflate_exception_count(native):
    window = probe.NativeFaultWindow(native)
    append(native, b"  File 'Windows fatal exception: example.py', line 1\n")
    assert window.check()["data"]["total"] == 0


@pytest.mark.parametrize("mutation", ["delete", "truncate", "rewrite", "replace"])
def test_lost_or_rewritten_evidence_is_not_zero(native, mutation):
    window = probe.NativeFaultWindow(native)
    if mutation == "delete":
        native.unlink()
    elif mutation == "truncate":
        native.write_bytes(MARKER)
    elif mutation == "rewrite":
        native.write_bytes(native.read_bytes().replace(b"101", b"202"))
    else:
        replacement = native.with_suffix(".replacement")
        replacement.write_bytes(native.read_bytes())
        replacement.replace(native)
    result = window.check()
    assert not result["ok"]
    assert result["data"]["total"] is None


def test_incomplete_concurrent_record_is_inconclusive_until_complete(native):
    window = probe.NativeFaultWindow(native)
    append(native, b"Windows fatal exception: access violation")
    assert window.check()["error_code"] == "NATIVE_LOG_PARTIAL"
    append(native, b"\n")
    assert window.check()["data"]["total"] == 1


def test_partial_baseline_never_becomes_a_false_zero(native):
    native.write_bytes(MARKER + b"Windows fatal exception:")
    window = probe.NativeFaultWindow(native)
    append(native, b" access violation\n")
    assert not window.check()["ok"]


@pytest.mark.parametrize("pid", [10, 1010, 202])
def test_current_process_capture_must_have_exact_pid_marker(native, pid):
    assert probe.NativeFaultWindow(native, expected_pid=pid).error == "NATIVE_SESSION_UNVERIFIED"


def test_child_header_does_not_reassign_main_dump_ownership(native):
    append(native, MARKER.replace(b"101", b"202"))
    window = probe.NativeFaultWindow(native, expected_pid=101)
    assert window.error is None
    append(native, AV)
    assert window.check()["data"]["process_attribution"] == "unavailable_shared_log"


def test_byte_budget_exceeded_is_not_a_partial_pass(native, monkeypatch):
    window = probe.NativeFaultWindow(native)
    monkeypatch.setattr(probe, "MAX_LOG_BYTES", native.stat().st_size)
    append(native, AV)
    assert window.check()["error_code"] == "NATIVE_LOG_LIMIT"


def test_permission_failure_does_not_expose_path(native, monkeypatch):
    window = probe.NativeFaultWindow(native)
    monkeypatch.setattr(Path, "open", lambda *a, **kw: (_ for _ in ()).throw(
        PermissionError("sensitive/path")))
    result = window.check()
    assert result["error_code"] == "NATIVE_LOG_UNREADABLE"
    assert "sensitive" not in str(result)


def test_empty_baseline_does_not_prove_capture_enabled(native):
    native.write_bytes(b"")
    assert probe.NativeFaultWindow(native).error == "NATIVE_LOG_EMPTY"


def test_inventory_never_claims_exact_retrospective_window(native):
    result = probe.native_fault_inventory(native, 10)
    assert result["ok"] and result["data"]["total"] == 1
    assert result["data"]["new_native_faults"] is None
    assert result["data"]["requested_window_exact"] is False
