"""Native hover must not composite stale Home pixels over the VTK surface."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_dragdrop import _VWDragDropMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_overlay import _VWOverlayMixin


def test_advanced_hover_is_opaque_and_restores_empty_hint():
    app = QApplication.instance() or QApplication([])

    class Viewport(_VWDragDropMixin, _VWOverlayMixin, QWidget):
        pass

    viewport = Viewport()
    viewport.resize(440, 320)
    viewport.show()
    try:
        viewport._update_empty_drop_hint_visibility()
        assert viewport._empty_drop_hint_label.isVisible()
        captures = []
        for color in ('#ff0000', '#00ff00'):
            viewport.setStyleSheet(f'Viewport {{ background: {color}; }}')
            viewport._show_drop_highlight(True)
            app.processEvents()
            overlay = viewport._drop_overlay
            assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
            assert not viewport._empty_drop_hint_label.isVisible()
            image = overlay.grab().toImage()
            for x, y in ((0, 0), (1, 1), (220, 160), (439, 319)):
                assert image.pixelColor(x, y).alpha() == 255
            captures.append(image)
        assert captures[0] == captures[1]
        viewport._show_drop_highlight(False)
        assert not overlay.isVisible()
        assert viewport._empty_drop_hint_label.isVisible()
    finally:
        viewport.close()
