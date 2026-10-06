"""Corner treatment leaves header text visible and does not intercept input."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidget
from PacsClient.pacs.workstation_ui.home_ui.rounded_table_header import RoundedHeaderClip


def test_header_surface_tracks_resize_without_clipping_text():
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(['Selection', 'Patient Name', 'Patient ID'])
    table.setStyleSheet('QTableWidget {background: #101820;} QHeaderView::section {background: #304050; color:white;}')
    clip = RoundedHeaderClip(table.horizontalHeader())
    table.show()
    for width in (320, 600):
        table.resize(width, 180)
        app.processEvents()
        header = table.horizontalHeader()
        assert header.mask().isEmpty()
        assert clip.surface.geometry() == header.rect()
        assert clip.surface.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        image = header.grab().toImage()
        assert image.pixelColor(0, 0).name() == '#101820'
        assert image.pixelColor(header.width()//2, header.height()//2).name() != '#101820'
    table.close()
