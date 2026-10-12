"""Company license generator; keys and issuance work stay off the GUI thread."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import (QApplication, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget, QComboBox)

from modules.LicenseGenerator.async_ui import LicenseOperation
from modules.LicenseGenerator.code_files import read_code
from modules.LicenseGenerator.signed_license import LicenseError, decode_request, decode_token, normalize
from tools.licensing.issuer import load_issuer


def inspect_response(store, request, product):
    return load_issuer(store).inspect_request(request, expected_product=product)


def issue_response(store, request, days, order, legacy_expiry, product):
    issuer = load_issuer(store)
    issuer.inspect_request(request, expected_product=product)
    token = issuer.issue(request, days=days, order_id=order,
                         approved_legacy_expiry=legacy_expiry or None)
    return token, decode_token(token, issuer.trusted)


def export_license(path, code, store):
    destination, private = Path(path).resolve(), Path(store).resolve()
    if destination in (private, private.with_suffix('.sqlite')) or destination.suffix.lower() != '.aiplic':
        raise LicenseError('Save the response as an .aiplic file, separate from company private storage.')
    destination.write_text(code, encoding='utf-8')


class LicenseGeneratorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('AI-PACS Company License Issuer')
        self.resize(780, 730)
        self._inspected_code = ''
        self.operation = LicenseOperation(self)
        self.operation.completed.connect(self._completed)
        self.operation.failed.connect(self._failed)
        self.operation.busy_changed.connect(self._busy)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        explanation = QLabel('Issue a signed activation or extension from a customer request. '
                             'The private key stays in a Windows-protected company store outside the application. '
                             'A unique paid order reference prevents duplicate credit.')
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.store = QLineEdit()
        self.store.setPlaceholderText('Company DPAPI signing-store file')
        self.store.setText(str(Path.home() / 'AppData/Local/AI-PACS Company Licensing/issuer-2026-10.key'))
        choose = QPushButton('Choose Signing Store')
        choose.clicked.connect(self._choose_store)
        row = QHBoxLayout()
        row.addWidget(self.store)
        row.addWidget(choose)
        form.addRow('Signing store', row)
        self.order = QLineEdit()
        self.order.setPlaceholderText('Unique company invoice or order reference')
        form.addRow('Order reference', self.order)
        self.product = QComboBox()
        self.product.addItem('AI-PACS Client', 'client')
        self.product.addItem('Eagle Eye Server', 'eagle-eye-server')
        form.addRow('Purchased product', self.product)
        self.days = QSpinBox()
        self.days.setRange(1, 36500)
        self.days.setValue(360)
        form.addRow('Purchased additional days', self.days)
        self.legacy_expiry = QLineEdit()
        self.legacy_expiry.setPlaceholderText('YYYY-MM-DDTHH:MM:SSZ, verified against company records')
        form.addRow('Approved legacy expiry (UTC)', self.legacy_expiry)
        layout.addLayout(form)
        note = QLabel('Legacy migration only: confirm the old expiry against company records. '
                      'The old symmetric format alone is not reliable proof of a purchased entitlement. '
                      'Leave this field empty for signed renewals or initial activation.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.request = QPlainTextEdit()
        self.request.setPlaceholderText('Paste the AIR3 customer request.')
        self.request.textChanged.connect(self._invalidate)
        layout.addWidget(self.request)
        import_button = QPushButton('Import Request File')
        import_button.clicked.connect(self._import)
        layout.addWidget(import_button)
        self.details = QLabel('No request inspected.')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.inspect_button = QPushButton('Inspect Request')
        self.inspect_button.clicked.connect(self._inspect)
        layout.addWidget(self.inspect_button)
        self.issue_button = QPushButton('Issue Signed License')
        self.issue_button.clicked.connect(self._issue)
        layout.addWidget(self.issue_button)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText('Signed company response')
        layout.addWidget(self.result)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton('Copy License')
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.result.toPlainText()))
        self.save_button = QPushButton('Save License File')
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        self.status = QLabel('Provision the company signing store and distribute its public root before issuing real licenses.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._inputs = (self.store, self.order, self.days, self.product, self.legacy_expiry, self.request, choose, import_button)
        for field in (self.store, self.order, self.legacy_expiry):
            field.textChanged.connect(self._invalidate)
        self.days.valueChanged.connect(self._invalidate)
        self.product.currentIndexChanged.connect(self._invalidate)
        self._busy(False)

    def _invalidate(self):
        self._inspected_code = ''
        self.result.clear()
        self._busy(self.operation.future is not None)

    def _busy(self, busy):
        for field in self._inputs:
            field.setEnabled(not busy)
        self.inspect_button.setEnabled(not busy)
        self.issue_button.setEnabled(not busy and bool(self._inspected_code))
        self.copy_button.setEnabled(not busy and bool(self.result.toPlainText()))
        self.save_button.setEnabled(not busy and bool(self.result.toPlainText()))

    def _choose_store(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose Company Signing Store', '', 'Protected stores (*.key);;All files (*)')
        if path:
            self.store.setText(path)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import Customer Request', '', 'AI-PACS requests (*.aipreq *.txt);;All files (*)')
        if path:
            self.operation.start('import', read_code, path)

    def _issue(self):
        from modules.LicenseGenerator.signed_license import LicenseError
        try:
            request = decode_request(self.request.toPlainText())
            self.details.setText(f"Product: {request['product']} | Request created (UTC): {request['created_at']}")
            code = normalize(self.request.toPlainText())
        except LicenseError as exc:
            self.status.setText(str(exc))
            return
        if not self._inspected_code or self._inspected_code != code:
            self.status.setText('Inspect the current request and verify the purchased product before issuing.')
            return
        self.result.clear()
        self.status.setText('Verifying the request and recording signed issuance...')
        self.operation.start('issue', issue_response, self.store.text().strip(), code,
                             self.days.value(), self.order.text().strip(), self.legacy_expiry.text().strip(),
                             self.product.currentData())

    def _inspect(self):
        self._inspected_code = ''
        self.result.clear()
        self.status.setText('Inspecting the request and checking the previous entitlement...')
        self.operation.start('inspect', inspect_response, self.store.text().strip(),
                             self.request.toPlainText(), self.product.currentData())

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Company License', 'license.aiplic', 'AI-PACS license (*.aiplic)')
        if path:
            self.operation.start('export', export_license, path, self.result.toPlainText(), self.store.text().strip())

    def _completed(self, name, value):
        if name == 'import':
            self.request.setPlainText(value)
            self.status.setText('Request imported. Verify the order details before issuing.')
        elif name == 'inspect':
            self._inspected_code = normalize(self.request.toPlainText())
            self.details.setText(f"Product: {value['product']} | Previous expiry (UTC): {value['expires_at'] or 'Initial activation'}")
            self.status.setText('Legacy proof checked. Confirm the expiry against company records before issuing.'
                                if value['legacy'] else 'Previous signature verified. Check the paid order and additional days.'
                                if not value['initial'] else 'Initial activation request. Check the purchased product and paid order.')
        elif name == 'issue':
            token, claim = value
            self.result.setPlainText(token)
            self.details.setText(f"Product: {claim['product']} | Added days: {claim['added_days']} | "
                                 f"New expiry (UTC): {claim['expires_at']}")
            self.status.setText('Signed response recorded. Send it to the customer. Reusing this order recovers the same response.')
        elif name == 'export':
            self.status.setText('Signed license file saved.')

    def _failed(self, message):
        self._inspected_code = ''
        self.result.clear()
        self.status.setText(message)

    def closeEvent(self, event):
        if self.operation.future is not None:
            event.ignore()
            self.status.setText('Wait for the current issuance or file operation to finish before closing.')
        else:
            super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = LicenseGeneratorWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
