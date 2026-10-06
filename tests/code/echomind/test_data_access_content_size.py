"""Source switching must preserve the geometry of downstream controls."""
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PacsClient.pacs.workstation_ui.home_ui.data_access_panel import _ContentSizedTabs


def test_source_switching_preserves_height():
    app = QApplication.instance() or QApplication([])
    tabs = _ContentSizedTabs()
    tabs.tabBar().hide()
    for height in (210, 120, 170):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel('Synthetic source controls')
        label.setFixedHeight(height)
        layout.addWidget(label)
        tabs.addTab(page, 'Source')
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.addWidget(tabs)
    downstream = QLabel('Synthetic patient search')
    layout.addWidget(downstream)
    layout.addStretch()
    host.resize(300, 650)
    host.show()
    app.processEvents()
    for width in (300, 240):
        host.resize(width, 650)
        app.processEvents()
        expected = (tabs.sizeHint(), tabs.minimumSizeHint(), downstream.y())
        for index in (1, 2, 0, 2, 1):
            tabs.setCurrentIndex(index)
            app.processEvents()
            assert (tabs.sizeHint(), tabs.minimumSizeHint(), downstream.y()) == expected
            assert tabs.height() >= tabs.currentWidget().minimumSizeHint().height()
    host.close()
