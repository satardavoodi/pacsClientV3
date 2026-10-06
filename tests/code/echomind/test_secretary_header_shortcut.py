from PySide6.QtWidgets import QApplication, QWidget


def test_header_shortcut_uses_existing_f12_popup(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui.secretary_header_shortcut import create_secretary_header_shortcut
    from PacsClient.pacs.workstation_ui.home_ui.secretary_popup import SecretaryPopup
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    calls = []
    monkeypatch.setattr(SecretaryPopup, "toggle_for", lambda window: calls.append(window))
    button = create_secretary_header_shortcut(host)
    assert button.height() == 70
    assert not button.icon().isNull()
    assert "F12" in button.toolTip()
    button.click()
    button.click()
    assert calls == [host, host]
    host.close()
