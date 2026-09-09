"""Deleted sidebar controls must not prevent the Advanced Analysis launch."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from shiboken6 import delete, isValid

from PacsClient.pacs.patient_tab.utils.button_safeguard import ButtonSafeguard


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def controls(qapp):
    parent = QWidget()
    retired = QPushButton("Retired sidebar control", parent)
    launch = QPushButton("Advanced Analysis", parent)
    disabled = QPushButton("Unavailable operation", parent)
    disabled.setEnabled(False)
    guard = ButtonSafeguard(parent)
    guard.register_buttons([retired, launch, disabled])
    yield parent, retired, launch, disabled, guard
    delete(parent)


@pytest.mark.parametrize("deferred", [False, True])
def test_deleted_sidebar_button_does_not_block_launch_or_next_operation(controls, deferred):
    parent, retired, launch, disabled, guard = controls
    started, completed = [], []
    guard.operation_started.connect(lambda: started.append(True))
    guard.operation_completed.connect(completed.append)
    if deferred:
        retired.deleteLater()
        QCoreApplication.sendPostedEvents(retired, QEvent.DeferredDelete)
    else:
        delete(retired)
    assert not isValid(retired)

    for _ in range(2):
        assert guard.start_operation("Advanced MPR Launch")
        assert not launch.isEnabled() and not disabled.isEnabled()
        assert not guard.start_operation("Duplicate launch")
        guard.end_operation(operation_name="Advanced MPR Launch")
        assert launch.isEnabled() and not disabled.isEnabled()
        assert not guard.is_operation_in_progress()
    assert len(started) == 2 and completed == [True, True]


def test_deleted_button_in_registration_batch_does_not_drop_live_controls(controls):
    parent, retired, launch, disabled, guard = controls
    stale = QPushButton("Already deleted", parent)
    delete(stale)
    replacement = QPushButton("Replacement", parent)
    guard.register_buttons([stale, replacement, replacement])
    assert guard.start_operation()
    assert not replacement.isEnabled()
    guard.end_operation()
    assert replacement.isEnabled()


def test_button_deleted_during_operation_does_not_poison_retry(controls):
    parent, retired, launch, disabled, guard = controls
    assert guard.start_operation()
    delete(retired)
    guard.end_operation(success=False)
    assert launch.isEnabled() and not guard.is_operation_in_progress()
    assert guard.start_operation("Retry")
    guard.end_operation()
    assert launch.isEnabled() and not disabled.isEnabled()


def test_advanced_button_reaches_deferred_launcher_after_sidebar_rebuild(controls, tmp_path):
    """Exercise the real handler without importing the patient/database controllers."""
    parent, retired, launch, disabled, guard = controls
    source = Path(__file__).resolve().parents[3] / (
        "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_advanced.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    handler = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "_on_advanced_mpr_clicked")
    scheduled, launched, overlays = [], [], []
    import os
    namespace = {"os": os, "QTimer": SimpleNamespace(
        singleShot=lambda delay, callback: scheduled.append(callback))}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"), namespace)
    series = {"series_path": str(tmp_path), "series_uid": "1.2.826.0.1.3680043.10.999.1"}
    widget = SimpleNamespace(
        button_safeguard=guard,
        selected_widget=SimpleNamespace(image_viewer=SimpleNamespace(
            metadata={"series": series, "instances": [{}]})),
        _show_advanced_mpr_loading_ui=lambda: overlays.append(True),
        _launch_advanced_mpr_async=lambda **kwargs: launched.append(kwargs),
    )
    delete(retired)
    namespace["_on_advanced_mpr_clicked"](widget)
    assert overlays == [True] and len(scheduled) == 1 and not launched
    scheduled[0]()
    assert launched[0]["dicom_dir"] == str(tmp_path)
    assert launched[0]["series_uid"] == series["series_uid"]
    guard.end_operation(operation_name="Advanced MPR Launch")
    assert not guard.is_operation_in_progress()
