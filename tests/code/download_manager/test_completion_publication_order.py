"""Exercise the production success branch with real Qt delivery, no live DB."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[3]


class Sender(QObject):
    completed = Signal(str)


def run_success(on_signal=None, on_update=None, observed=None):
    app = QApplication.instance() or QApplication([])
    source = ast.parse((ROOT / "modules/download_manager/ui/widget/_dm_workers.py").read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == "_on_worker_completed")
    branch = next(n for n in ast.walk(method) if isinstance(n, ast.If) and ast.unparse(n.test) == "success")
    fn = ast.FunctionDef(name="complete", args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="self"), ast.arg(arg="study_uid")], kwonlyargs=[], kw_defaults=[], defaults=[]), body=branch.body, decorator_list=[])
    ns = {"logger": Mock(), "DownloadStatus": SimpleNamespace(COMPLETED="completed")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<production-completion>", "exec"), ns)
    sender = Sender()
    state = SimpleNamespace(status="downloading", total_count=3, patient_name="synthetic")
    task = SimpleNamespace(total_image_count=3, series_list=[SimpleNamespace(series_uid="synthetic-series")])
    owner = SimpleNamespace(_tasks={"synthetic": task}, download_completed=sender.completed, _cleanup_task_state=Mock(), log_message=Mock())
    def update(uid, **changes):
        state.__dict__.update(changes)
        if on_update:
            on_update(owner)
    owner.state_store = SimpleNamespace(get=lambda uid: state, update=update)
    observed = [] if observed is None else observed
    def receive(uid):
        observed.append((state.status, state.downloaded_count if hasattr(state, "downloaded_count") else 0))
        if on_signal:
            on_signal(owner)
    sender.completed.connect(receive)
    ns["complete"](owner, "synthetic")
    return observed, owner


def test_completion_subscriber_sees_committed_state():
    seen, owner = run_success()
    assert seen == [("completed", 3)]
    owner._cleanup_task_state.assert_called_once_with("synthetic")


def test_reentrant_receiver_cannot_clear_replacement_task():
    def replace(owner):
        owner._tasks["synthetic"] = object()
    seen, owner = run_success(on_signal=replace)
    assert seen == [("completed", 3)]
    owner._cleanup_task_state.assert_not_called()


def test_state_observer_replacement_suppresses_old_completion():
    def replace(owner):
        owner._tasks["synthetic"] = object()
    seen, owner = run_success(on_update=replace)
    assert seen == []
    owner._cleanup_task_state.assert_not_called()


def test_failed_state_update_does_not_publish_success():
    seen = []
    def fail(owner):
        raise RuntimeError("synthetic persistence failure")
    with pytest.raises(RuntimeError, match="synthetic persistence"):
        run_success(on_update=fail, observed=seen)
    assert seen == []


def test_state_observer_cancellation_suppresses_success():
    def cancel(owner):
        owner.state_store.get("synthetic").status = "cancelled"
    seen, owner = run_success(on_update=cancel)
    assert seen == []
    owner._cleanup_task_state.assert_not_called()
