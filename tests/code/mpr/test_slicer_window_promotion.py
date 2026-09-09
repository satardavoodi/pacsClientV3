"""Warm viewer promotion must not leave invisible dialogs blocking user input."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def viewer(qapp):
    source = Path(__file__).resolve().parents[3] / (
        "modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsBackgroundRuntime.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name in {"WindowGuard", "Runtime"}]
    main = QtWidgets.QMainWindow()
    namespace = {
        "qt": SimpleNamespace(QObject=QtCore.QObject, QEvent=QtCore.QEvent, Qt=QtCore.Qt),
        "slicer": SimpleNamespace(app=qapp, util=SimpleNamespace(mainWindow=lambda: main)),
        "os": os,
    }
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(source), "exec"), namespace)
    guard = namespace["WindowGuard"]()
    qapp.installEventFilter(guard)
    runtime = namespace["Runtime"].__new__(namespace["Runtime"])
    runtime.guard, runtime.role = guard, "viewer"
    main.show()
    assert main.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    main.hide()  # Same transition as the Slicer startup-completed handler.
    yield main, guard, runtime
    qapp.removeEventFilter(guard)
    if isValid(main):
        delete(main)
    delete(guard)


def test_dialog_polished_during_warmup_is_visible_when_used_after_promotion(viewer, qapp):
    main, guard, runtime = viewer
    dialog = QtWidgets.QDialog(main)
    dialog.setModal(True)
    dialog.ensurePolished()
    assert dialog.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    runtime.viewer_command("show", {})
    dialog.show()
    assert not dialog.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    assert dialog.windowHandle().isVisible()
    assert qapp.activeModalWidget() is dialog
    dialog.accept()
    assert qapp.activeModalWidget() is None
    assert main.isVisible()


def test_already_active_hidden_modal_is_revealed_without_dismissing_it(viewer, qapp):
    main, guard, runtime = viewer
    dialog = QtWidgets.QDialog(main)
    dialog.setModal(True)
    finished = []
    dialog.finished.connect(finished.append)
    dialog.show()
    assert dialog.isVisible() and not dialog.windowHandle().isVisible()
    assert qapp.activeModalWidget() is dialog
    runtime.viewer_command("show", {})
    assert dialog.windowHandle().isVisible(), "An invisible modal blocks every viewer control"
    assert not dialog.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    assert qapp.activeModalWidget() is dialog and not finished
    dialog.reject()
    assert finished == [0] and qapp.activeModalWidget() is None


def test_promotion_preserves_unused_dialogs_and_foreign_offscreen_widgets(viewer):
    main, guard, runtime = viewer
    unused = QtWidgets.QDialog(main)
    unused.ensurePolished()
    retired = QtWidgets.QDialog(main)
    retired.ensurePolished()
    delete(retired)
    foreign = QtWidgets.QDialog(main)
    foreign.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
    foreign.ensurePolished()
    runtime.viewer_command("show", {})
    assert not unused.isVisible()
    assert not unused.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    assert foreign.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    runtime.viewer_command("hide", {})
    runtime.viewer_command("show", {})
    later = QtWidgets.QDialog(main)
    later.show()
    assert not later.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    assert later.windowHandle().isVisible()
