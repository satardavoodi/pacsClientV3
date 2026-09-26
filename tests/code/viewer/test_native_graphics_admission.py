"""A failed native graphics probe must never admit VTK, even for empty cells."""
import pytest
import ast
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from aipacs_runtime import SAFE_VIEWER_BACKEND_ENV
from modules.viewer.viewer_backend_config import resolve_viewer_backend
from modules.viewer import native_graphics_probe as probe


@pytest.mark.parametrize("configured", ["pydicom_qt", "pydicom_2d", "vtk_simpleitk"])
@pytest.mark.parametrize("instances", [[], [{"instance_path": "synthetic.dcm"}]])
@pytest.mark.parametrize("legacy", ["0", "1"])
def test_safe_graphics_cannot_fall_back_to_vtk(monkeypatch, configured, instances, legacy):
    monkeypatch.setenv(SAFE_VIEWER_BACKEND_ENV, "pydicom_qt")
    monkeypatch.setenv("AIPACS_FORCE_PYDICOM_2D", legacy)
    result = resolve_viewer_backend(
        {"series": {"force_vtk_fallback": True}, "instances": instances}, configured
    )
    assert result["backend"] == "pydicom_qt"
    assert result["requested_backend"] == "pydicom_qt"
    assert result["metadata_complete"] is bool(instances)
    assert result["safe_backend_forced"] is True


@pytest.mark.parametrize("payload,expected", [
    ('{"supported":true}', True), ('{"supported":false}', False),
    ('{"supported":"true"}', False), ('broken', False), ('[]', False),
])
def test_child_receipt_is_strict_and_private(monkeypatch, payload, expected):
    receipts = []
    def run(command, **kwargs):
        assert probe.PROBE_ARGUMENT in command
        assert kwargs["timeout"] <= 15
        path = Path(kwargs["env"]["AIPACS_GRAPHICS_PROBE_RECEIPT"])
        receipts.append(path)
        path.write_text(payload, encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.probe_native_graphics()["supported"] is expected
    assert not receipts[0].exists()


@pytest.mark.parametrize("outcome,reason", [
    ("crash", "probe_process_failed"), ("timeout", "probe_timeout"),
    ("missing", "invalid_probe_receipt"), ("launch", "probe_launch_failed"),
])
def test_child_failure_is_contained(monkeypatch, outcome, reason):
    def run(command, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if outcome == "launch":
            raise OSError("synthetic")
        return SimpleNamespace(returncode=-1073741819 if outcome == "crash" else 0)
    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.probe_native_graphics() == {"supported": False, "reason": reason}


def test_frozen_probe_uses_executable_and_no_console_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(probe.sys, "frozen", True, raising=False)
    def run(command, **kwargs):
        assert command == [probe.sys.executable, probe.PROBE_ARGUMENT]
        assert json.loads(kwargs["env"]["AIPACS_GRAPHICS_PROBE_DLL_DIRS"]) == [str(tmp_path)]
        Path(kwargs["env"]["AIPACS_GRAPHICS_PROBE_RECEIPT"]).write_text('{"supported":true}')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.probe_native_graphics(dll_directories=[str(tmp_path)])["supported"]


def test_failed_native_probe_overrides_persisted_mpr_pass(monkeypatch):
    from modules.mpr import opengl_preflight as mpr
    monkeypatch.setenv(probe.BLOCKED_ENV, "1")
    monkeypatch.setenv("AIPACS_MPR_OPENGL_PREFLIGHT", "0")
    monkeypatch.setattr(mpr, "_cached_result", (True, "old machine"))
    assert mpr.opengl_preflight()[0] is False


def test_controller_override_cannot_bypass_safety(monkeypatch):
    # Exercise the real method without importing the controller's GUI/database graph.
    root = Path(__file__).resolve().parents[3]
    path = root / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_backend.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_get_requested_viewer_backend")
    namespace = {"BACKEND_PYDICOM_QT": "pydicom_qt", "BACKEND_PYDICOM": "pydicom_2d",
                 "load_viewer_backend": lambda **_: "pydicom_qt",
                 "resolve_viewer_backend": resolve_viewer_backend}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    monkeypatch.setenv(SAFE_VIEWER_BACKEND_ENV, "pydicom_qt")
    owner = SimpleNamespace(parent_widget=SimpleNamespace(viewer_backend_override="vtk_simpleitk"))
    assert namespace[method.name](owner) == "pydicom_qt"


def test_probe_dispatch_does_not_start_the_application(monkeypatch, tmp_path):
    receipt = tmp_path / "probe.json"
    monkeypatch.setenv("AIPACS_GRAPHICS_PROBE_RECEIPT", str(receipt))
    monkeypatch.setattr(probe, "_probe_child", lambda: False)
    assert probe.dispatch_probe(["app", probe.PROBE_ARGUMENT]) is True
    assert json.loads(receipt.read_text()) == {"supported": False}
    assert probe.dispatch_probe(["app"]) is False
