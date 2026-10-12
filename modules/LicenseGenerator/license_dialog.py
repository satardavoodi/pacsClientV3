"""Startup activation and responsive license admission gate."""
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QPushButton

from .async_ui import LicenseOperation
from .manage_dialog import ManageLicenseDialog


class LicenseDialog(ManageLicenseDialog):
    def __init__(self, parent=None, *, manager=None):
        super().__init__(parent, manager=manager, activation_required=True)


def ensure_license(parent=None):
    """Check in a worker while Qt stays responsive; the user owns activation."""
    gate = QDialog(parent)
    gate.setWindowTitle('AI-PACS License')
    layout = QVBoxLayout(gate)
    message = QLabel('Checking license...')
    layout.addWidget(message)
    cancel = QPushButton('Exit Application')
    cancel.clicked.connect(gate.reject)
    layout.addWidget(cancel)
    operation = LicenseOperation(gate)

    def completed(name, value):
        if not gate.isVisible():
            return
        manager, status = value
        if status['valid']:
            gate.accept()
            return
        activation = LicenseDialog(gate, manager=manager)
        result = activation.exec()
        activation.deleteLater()
        gate.done(result)

    operation.completed.connect(completed)
    operation.failed.connect(lambda error: message.setText(error))
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: operation.start('initialize', ManageLicenseDialog._initialize, None))
    result = gate.exec() == QDialog.Accepted
    gate.deleteLater()
    return result
