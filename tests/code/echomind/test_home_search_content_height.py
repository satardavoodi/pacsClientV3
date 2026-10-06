"""Window slack must not create an empty gap below the date controls."""
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PacsClient.pacs.workstation_ui.home_ui.patient_search_widget import PatientSearchWidget


def test_search_height_does_not_expand_with_taller_window():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    search = PatientSearchWidget()
    layout.addWidget(search)
    layout.addStretch(1)
    heights = []
    for height in (900, 650):
        host.resize(300, height)
        host.show()
        app.processEvents()
        heights.append(search.height())
        assert search.search_btn.isVisible()
        assert search.search_btn.geometry().bottom() < search.height()
    assert heights[0] == heights[1]
    host.close()
