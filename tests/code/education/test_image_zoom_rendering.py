"""Exercise the actual image surface without clinical viewer initialization."""
import ast
from pathlib import Path
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets


def make_view():
    tree = ast.parse(Path('modules/education/educational_patient_viewer_widget.py').read_text(encoding='utf-8-sig'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_ZoomPanGraphicsView')
    ns = {'Optional': Optional}
    for module in (QtCore, QtGui, QtWidgets):
        ns.update({k: getattr(module, k) for k in dir(module) if not k.startswith('__')})
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<image-view>', 'exec'), ns)
    return ns['_ZoomPanGraphicsView']()


def test_original_image_uses_smooth_sampling_and_zoom_has_no_stale_strips():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view = make_view()
    image = QtGui.QImage(128, 128, QtGui.QImage.Format_RGB32)
    image.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(image)
    painter.fillRect(0, 0, 64, 128, QtCore.Qt.black)
    painter.end()
    pixmap = QtGui.QPixmap.fromImage(image)
    view.resize(320, 280)
    view.show()
    view.set_pixmap(pixmap)
    app.processEvents()
    assert view._item.transformationMode() == QtCore.Qt.SmoothTransformation
    assert view.viewportUpdateMode() == QtWidgets.QGraphicsView.FullViewportUpdate
    for factor in (1.25, 1.25, .8, .8):
        view.zoom(factor)
        app.processEvents()
        rendered = view.viewport().grab().toImage()
        point = view.mapFromScene(QtCore.QPointF(64, 64))
        samples = [rendered.pixelColor(point.x() + dx, point.y()).red() for dx in range(-3, 4)]
        assert any(0 < value < 255 for value in samples)
        assert view._item.pixmap().toImage() == image
    view.fit()
    app.processEvents()
    bounds = view.mapFromScene(view._item.boundingRect()).boundingRect()
    assert view.viewport().rect().contains(bounds)
    view.close()


def test_high_dpi_image_fit_uses_logical_bounds_and_pan_keeps_visible_pixels():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    view = make_view()
    image = QtGui.QImage(800, 600, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor('#f0b020'))
    pixmap = QtGui.QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(2)
    view.resize(420, 340)
    view.show()
    view.set_pixmap(pixmap)
    app.processEvents()
    assert view.sceneRect() == view._item.boundingRect()
    view.zoom(3)
    app.processEvents()
    for fraction in (0, .5, 1):
        for bar in (view.horizontalScrollBar(), view.verticalScrollBar()):
            bar.setValue(round(bar.minimum() + fraction * (bar.maximum() - bar.minimum())))
        app.processEvents()
        rendered = view.viewport().grab().toImage()
        assert rendered.pixelColor(rendered.width() // 2, rendered.height() // 2).name() == '#f0b020'
    assert view._item.pixmap().size() == pixmap.size()
    view.close()
