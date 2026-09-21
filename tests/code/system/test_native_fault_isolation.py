"""Process-exclusive native sinks; synthetic files only, never deliberate crashes."""
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from PacsClient.utils import native_fault_log as sink
from tools.diagnostics.native_fault_probe import NativeFaultWindow, native_fault_inventory


@pytest.fixture
def fake_capture(monkeypatch):
    monkeypatch.setattr(sink, "_handle", None)
    monkeypatch.setenv("AIPACS_NATIVE_FAULT_LOG", "1")
    monkeypatch.setattr(faulthandler, "enable", lambda **kw: None)
    handles = []
    yield handles
    if sink._handle is not None:
        handles.append(sink._handle)
    for handle in handles:
        handle.close()


def test_capture_does_not_append_to_shared_legacy_evidence(tmp_path, fake_capture):
    legacy = tmp_path / "native_fault.log"
    legacy.write_bytes(b"historical evidence\n")
    path = Path(sink.enable_native_fault_log(tmp_path))
    assert path != legacy
    assert legacy.read_bytes() == b"historical evidence\n"
    assert path.name.startswith(f"native_fault.{os.getpid()}.")


def test_reused_pid_does_not_reuse_a_previous_sink(tmp_path, fake_capture):
    first = sink.enable_native_fault_log(tmp_path)
    fake_capture.append(sink._handle)
    sink.reset_for_tests()
    second = sink.enable_native_fault_log(tmp_path)
    assert first != second
    assert Path(first).read_text().count("session start") == 1


def test_second_process_cannot_mix_with_first_dump(tmp_path, fake_capture, monkeypatch):
    monkeypatch.setattr(sink.os, "getpid", lambda: 101)
    first = sink.enable_native_fault_log(tmp_path)
    fake_capture.append(sink._handle)
    sink.reset_for_tests()
    monkeypatch.setattr(sink.os, "getpid", lambda: 202)
    second = sink.enable_native_fault_log(tmp_path)
    assert first != second
    assert "pid=202" not in Path(first).read_text()
    assert "pid=101" not in Path(second).read_text()


def write_sink(root, pid, token="a", text=""):
    path = root / f"native_fault.{pid}.{token * 32}.log"
    path.write_text(f"=== session start synthetic pid={pid} ===\n" + text, encoding="utf-8")
    return path


def test_window_finds_process_sink_without_legacy_file(tmp_path):
    path = write_sink(tmp_path, 101)
    window = NativeFaultWindow(tmp_path / "native_fault.log", expected_pid=101)
    assert window.error is None
    with path.open("a") as stream:
        stream.write("Windows fatal exception: access violation\n")
    result = window.check()
    assert result["ok"] and result["data"]["total"] == 1


def test_new_child_sink_is_included_after_baseline(tmp_path):
    write_sink(tmp_path, 101)
    window = NativeFaultWindow(tmp_path / "native_fault.log", expected_pid=101)
    write_sink(tmp_path, 202, text="Fatal Python error: Aborted\n")
    result = window.check()
    assert result["ok"] and result["data"]["total"] == 1


def test_inventory_includes_legacy_and_isolated_but_not_filtered_reports(tmp_path):
    (tmp_path / "native_fault.log").write_text("Windows fatal exception: access violation\n")
    write_sink(tmp_path, 101, text="Fatal Python error: Aborted\n")
    (tmp_path / "native_fault_crashes.log").write_text("Fatal Python error: Aborted\n")
    result = native_fault_inventory(tmp_path / "native_fault.log", 10)
    assert result["ok"] and result["data"]["total"] == 2


def test_new_child_records_cannot_disappear_between_checks(tmp_path):
    write_sink(tmp_path, 101)
    window = NativeFaultWindow(tmp_path / "native_fault.log", expected_pid=101)
    path = write_sink(tmp_path, 202, text="Fatal Python error: Aborted\n")
    assert window.check()["data"]["total"] == 1
    path.write_text("=== session start synthetic pid=202 ===\n")
    assert not window.check()["ok"]


def test_raw_in_app_counter_fails_closed_without_filesystem_io(monkeypatch):
    from modules.EchoMind.secretary.adapters.system_command_adapter import SystemCommandAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan

    def no_io(*a, **kw):
        raise AssertionError("Native log reads must not run on the GUI bus")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "exists", no_io)
        result = SystemCommandAdapter().count_native_faults_since(
            CommandPlan(action="count_native_faults_since"), {})
    assert not result.ok
    assert result.error_code == "EXTERNAL_NATIVE_PROBE_REQUIRED"
    assert result.data["total"] is None


def test_real_child_processes_keep_native_tracebacks_separate(tmp_path):
    code = (
        "import faulthandler, sys, os, json; from PacsClient.utils import native_fault_log as n; "
        "p=n.enable_native_fault_log(sys.argv[1]); assert p; "
        "faulthandler.dump_traceback(file=n._handle); print(json.dumps({'pid':os.getpid(),'path':p}))"
    )
    children = [subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) for _ in range(2)]
    paths = []
    for child in children:
        out, err = child.communicate(timeout=20)
        assert child.returncode == 0, err
        receipt = json.loads(out)
        path = Path(receipt["path"])
        # Windows venv launchers can redirect to a different native Python PID.
        assert sink.native_fault_log_pid(path) == receipt["pid"]
        content = path.read_text()
        assert content.count("session start") == 1
        assert "Current thread" in content
        paths.append(path)
    assert len(set(paths)) == 2
    assert not (tmp_path / "native_fault.log").exists()


def test_exclusive_creation_never_overwrites_a_collision(tmp_path, fake_capture, monkeypatch):
    monkeypatch.setattr(sink.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    existing = write_sink(tmp_path, os.getpid(), text="original\n")
    before = existing.read_bytes()
    assert sink.enable_native_fault_log(tmp_path) is None
    assert existing.read_bytes() == before


def test_failed_enable_closes_unpublished_handle(tmp_path, fake_capture, monkeypatch):
    captured = []

    def fail_enable(**kwargs):
        captured.append(kwargs["file"])
        raise RuntimeError("synthetic setup failure")

    monkeypatch.setattr(faulthandler, "enable", fail_enable)
    assert sink.enable_native_fault_log(tmp_path) is None
    assert captured[0].closed
    assert sink._handle is None


def test_capture_start_is_published_only_after_native_handler_is_enabled(tmp_path, fake_capture, monkeypatch):
    seen = []

    def enable(**kwargs):
        seen.append(Path(kwargs["file"].name).read_bytes())

    monkeypatch.setattr(faulthandler, "enable", enable)
    assert sink.enable_native_fault_log(tmp_path)
    assert seen == [b""], "A failed enable must not leave a ready-looking session header"


def test_frozen_capture_and_repeated_enable_preserve_same_live_handle(tmp_path, fake_capture, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    first = sink.enable_native_fault_log(tmp_path)
    assert sink.enable_native_fault_log(tmp_path) == first
    assert "frozen=True" in Path(first).read_text()
    assert not sink._handle.closed


def test_discovery_rejects_source_count_overflow(tmp_path):
    write_sink(tmp_path, 101)
    write_sink(tmp_path, 202)
    with pytest.raises(ValueError, match="FILE_LIMIT"):
        sink.discover_native_fault_logs(tmp_path, max_files=1)


def test_filename_and_header_pid_must_agree(tmp_path):
    path = write_sink(tmp_path, 101)
    path.write_text("=== session start synthetic pid=202 ===\n")
    assert NativeFaultWindow(tmp_path / "native_fault.log").error == "NATIVE_SESSION_UNVERIFIED"


def test_child_header_publication_can_be_retried_without_losing_records(tmp_path):
    write_sink(tmp_path, 101)
    window = NativeFaultWindow(tmp_path / "native_fault.log")
    child = tmp_path / f"native_fault.202.{'b' * 32}.log"
    child.write_bytes(b"")
    assert not window.check()["ok"]
    child.write_text("=== session start synthetic pid=202 ===\nFatal Python error: Aborted\n")
    assert window.check()["data"]["total"] == 1


def test_default_filter_reads_exclusive_and_legacy_with_source_boundaries(tmp_path):
    from tools.diagnostics.filter_native_fault import main
    (tmp_path / "native_fault.log").write_text("Windows fatal exception: access violation\n")
    path = write_sink(tmp_path, 101, text="Fatal Python error: Aborted\n")
    assert main(["--logs-dir", str(tmp_path)]) == 0
    report = (tmp_path / "native_fault_crashes.log").read_text(encoding="utf-8")
    assert path.name in report and "access violation" in report and "Aborted" in report
    assert main(["--logs-dir", str(tmp_path), "--out", str(path)]) == 2


def test_dashboard_uses_exclusive_sources_without_claiming_recent_crash_count(tmp_path, monkeypatch):
    from tools import kpi_dashboard
    logs = tmp_path / "user_data" / "logs"
    logs.mkdir(parents=True)
    write_sink(logs, 101, text="Windows fatal exception: access violation\n")
    monkeypatch.setattr(kpi_dashboard, "PROJECT_ROOT", tmp_path)
    result = kpi_dashboard._probe_recent_crashes()
    assert result["ok"] and result["total"] == 1
    assert result["requested_window_exact"] is False


def test_gui_native_guard_detects_a_new_child_fault(tmp_path):
    from tests.gui.pywinauto.test_eagle_eye_dragdrop import _diff_native_fault
    write_sink(tmp_path, 101)
    window = NativeFaultWindow(tmp_path / "native_fault.log")
    write_sink(tmp_path, 202, text="Windows fatal exception: access violation\n")
    with pytest.raises(AssertionError, match="New native"):
        _diff_native_fault(window)
