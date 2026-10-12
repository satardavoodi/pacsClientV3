"""Offscreen real Qt input and worker ownership; not live workstation acceptance."""
import threading
import time
import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from modules.LicenseGenerator.manage_dialog import ManageLicenseDialog


class SyntheticManager:
    def __init__(self):
        self.threads = []
        self.applied = False
    def status(self):
        self.threads.append(threading.get_ident())
        return {'valid': True, 'product': 'client', 'days_remaining': 30,
                'message': 'License is valid. 30 days remaining', 'expires_at': '2026-11-06T12:00:00Z'}
    def generate_request(self):
        self.threads.append(threading.get_ident())
        return 'AIR3.synthetic-request'
    def preview(self, code):
        self.threads.append(threading.get_ident())
        return {'previous_expiry': '2026-11-06T12:00:00Z', 'expires_at': '2027-11-01T12:00:00Z',
                'added_days': 360, 'days_remaining': 390, 'already_applied': False}
    def save_license(self, code):
        self.threads.append(threading.get_ident())
        self.applied = True
        return True, 'License updated. 390 days remaining.'


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    instance.processEvents()


def wait(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), 'Synthetic Qt operation did not complete'


def test_request_preview_apply_and_changed_input_are_owned_workers(app):
    manager = SyntheticManager()
    dialog = ManageLicenseDialog(manager=manager)
    dialog.show()
    wait(app, lambda: dialog._operation.future is None)
    dialog.generate_button.click()
    wait(app, lambda: dialog.request_text.toPlainText() == 'AIR3.synthetic-request')
    assert 'send it to company support' in dialog.message.text()
    dialog.response.setPlainText('AIP3.synthetic.response')
    assert not dialog.apply_button.isEnabled()
    dialog.preview_button.click()
    wait(app, lambda: dialog.apply_button.isEnabled())
    assert dialog.total_days.text() == '390'
    dialog.response.setPlainText('AIP3.changed.response')
    assert not dialog.apply_button.isEnabled()
    dialog.preview_button.click()
    wait(app, lambda: dialog.apply_button.isEnabled())
    dialog.apply_button.click()
    wait(app, lambda: manager.applied and dialog._operation.future is None)
    assert all(thread != threading.get_ident() for thread in manager.threads)
    dialog.close()
    dialog.deleteLater()


def test_cancel_does_not_apply_and_oversized_code_is_visible(app):
    manager = SyntheticManager()
    dialog = ManageLicenseDialog(manager=manager)
    dialog.show()
    wait(app, lambda: dialog._operation.future is None)
    dialog.response.setPlainText('x' * 33000)
    dialog.preview_button.click()
    assert 'too large' in dialog.message.text()
    dialog.close_button.click()
    assert not manager.applied
    dialog.deleteLater()


def test_issuer_export_cannot_overwrite_protected_key(tmp_path):
    import pytest
    from modules.LicenseGenerator.license_generator import export_license
    private = tmp_path / 'issuer.key'
    private.write_bytes(b'protected-synthetic-key')
    with pytest.raises(ValueError):
        export_license(private, 'AIP3.synthetic.response', private)
    assert private.read_bytes() == b'protected-synthetic-key'


def test_startup_license_check_uses_worker_and_accepts_valid_state(app, monkeypatch):
    from modules.LicenseGenerator import manage_dialog
    from modules.LicenseGenerator.license_dialog import ensure_license
    manager = SyntheticManager()
    monkeypatch.setattr(manage_dialog, 'create_manager', lambda: manager)
    assert ensure_license()
    assert manager.threads and all(value != threading.get_ident() for value in manager.threads)


def test_company_ui_requires_inspection_and_invalidates_it_on_edits(app, monkeypatch):
    from modules.LicenseGenerator import license_generator as generator_gui
    monkeypatch.setattr(generator_gui, 'inspect_response', lambda *args: {
        'product': 'client', 'expires_at': None, 'legacy': False, 'initial': True})
    window = generator_gui.LicenseGeneratorWindow()
    window.show()
    window.request.setPlainText('AIR3.synthetic-request')
    assert not window.issue_button.isEnabled()
    window.inspect_button.click()
    wait(app, lambda: window.issue_button.isEnabled())
    window.days.setValue(365)
    assert not window.issue_button.isEnabled()
    window.close()
    window.deleteLater()
