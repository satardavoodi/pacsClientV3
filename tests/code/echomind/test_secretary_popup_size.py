from PySide6.QtWidgets import QApplication, QWidget
from PacsClient.pacs.workstation_ui.home_ui.secretary_popup import SecretaryPopup


def test_popup_content_matches_home_companion_size():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    home = QWidget(host)
    home.setObjectName("secretaryButtonWidget")
    home.resize(294, 267)
    popup = SecretaryPopup(host, inner_factory=QWidget)
    popup._match_home_companion(host)
    assert popup.inner.width() == home.width()
    assert popup.inner.height() == home.height()
    assert popup.width() == 314
    home.resize(280, 240)
    popup._match_home_companion(host)
    assert popup.inner.size() == home.size()
    popup.hide()
    popup.deleteLater()
