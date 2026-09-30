"""Process-exit bookkeeping must not interrupt the workstation with a modal."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest


def handler(name, namespace):
    source = Path("modules/mpr/advanced_3d_slicer/slicer_launcher.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("code", [0, 1, -1073741819])
def test_exit_is_nonmodal_and_preserves_status_and_diagnostics(code, caplog):
    dialogs, completed = [], []
    logger = logging.getLogger("slicer-exit-test")
    namespace = {"logger": logger,
        "QMessageBox": SimpleNamespace(warning=lambda *args: dialogs.append(args)),
        "SlicerLauncherWorker": SimpleNamespace(_find_latest_log=lambda: None)}
    viewer = SimpleNamespace(_is_running=True, parent_widget=None,
                             slicer_finished=SimpleNamespace(emit=completed.append))
    with caplog.at_level(logging.INFO):
        handler("_on_finished", namespace)(viewer, code)
    assert dialogs == []
    assert not viewer._is_running and completed == [code]
    assert f"exit_code={code}" in caplog.text


def test_launch_failure_still_reports_actionable_error():
    dialogs, errors = [], []
    namespace = {"logger": logging.getLogger("slicer-exit-test"),
        "QMessageBox": SimpleNamespace(critical=lambda *args: dialogs.append(args))}
    viewer = SimpleNamespace(_is_running=True, parent_widget=None,
                             slicer_error=SimpleNamespace(emit=errors.append))
    handler("_on_error", namespace)(viewer, "Runtime unavailable")
    assert errors == ["Runtime unavailable"]
    assert len(dialogs) == 1 and dialogs[0][-1] == "Runtime unavailable"
