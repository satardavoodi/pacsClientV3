"""Card creation yields and obsolete filter results never populate the grid."""
import time
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel
from PySide6.QtCore import Signal
import threading


def test_library_grid_yields_and_replaces_pending_filter(monkeypatch):
    from modules.education import education_module_redesigned as module
    app = QApplication.instance() or QApplication([])
    made = []

    class Card(QLabel):
        clicked = Signal(dict)
        action_requested = Signal(str, dict)
        def __init__(self, course):
            super().__init__(str(course['course_pk']))
            made.append(course['course_pk'])

    monkeypatch.setattr(module, 'ModernCourseCard', Card)
    host = QWidget()
    host.grid_layout = QGridLayout(host)
    host.filtered_courses = [{'course_pk': n} for n in range(20)]
    host._responsive_columns = lambda: 3
    host._update_cards_scroll_height = lambda: None
    host.on_card_clicked = lambda value: None
    host.on_card_action = lambda *args: None
    module.LibraryPage.update_grid(host)
    assert len(made) <= 1, 'A filter change must not construct the entire grid inline'
    host.filtered_courses = [{'course_pk': 99}]
    module.LibraryPage.update_grid(host)
    until = time.monotonic() + 2
    while time.monotonic() < until and host.grid_layout.count() != 1:
        app.processEvents()
    app.processEvents()
    assert [host.grid_layout.itemAt(i).widget().text() for i in range(host.grid_layout.count())] == ['99']
    assert not any(1 <= pk < 20 for pk in made)
    host.deleteLater()
    app.processEvents()


def test_cover_worker_rejects_retired_generation(monkeypatch):
    from modules.education import authoring_thumbnails as module
    from PySide6.QtGui import QImage, QColor
    app = QApplication.instance() or QApplication([])
    release = threading.Event()
    entered = threading.Event()
    threads = []
    def decode(path, target_size):
        threads.append(threading.get_ident())
        if path == 'old':
            entered.set()
            assert release.wait(3)
        image = QImage(10, 10, QImage.Format_RGB32)
        image.fill(QColor('red' if path == 'old' else 'blue'))
        return image
    monkeypatch.setattr(module, '_cover_image', decode)
    owner = QWidget()
    label = QLabel(owner)
    controller = module.AuthoringThumbnails(owner)
    controller.request_cover(label, 'old')
    try:
        assert entered.wait(2)
        controller.request_cover(label, 'new')
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while (label.pixmap() is None or label.pixmap().isNull()) and time.monotonic() < deadline:
        app.processEvents()
    module._pool.waitForDone(3000)
    app.processEvents()
    assert label.pixmap().toImage().pixelColor(0, 0) == QColor('blue')
    assert all(value != threading.get_ident() for value in threads)
    owner.deleteLater()
    app.processEvents()


def test_cover_constructor_never_reads_pixels_inline(monkeypatch):
    from modules.education import education_module_redesigned as module
    app = QApplication.instance() or QApplication([])
    original = module.content_diagnostic_work
    def work(phase, fn, *args, **kwargs):
        assert phase != 'cover_read', 'Cover decoding belongs to the image worker'
        return original(phase, fn, *args, **kwargs)
    monkeypatch.setattr(module, 'content_diagnostic_work', work)
    # Existing source is used only to reach the old exists/read boundary.
    card = module.ModernCourseCard({'course_pk': 1, 'course_name': 'Synthetic',
                                   'thumbnail_path': __file__})
    card.deleteLater()
    app.processEvents()


def test_grid_hides_intermediate_layout_until_covers_settle():
    from modules.education.card_grid_build import CardGridBuild
    app = QApplication.instance() or QApplication([])
    surface = QWidget()
    surface.resize(640, 480)
    surface.show()
    ready = [False]
    built = []
    helper = CardGridBuild(surface)
    helper.start([1, 2], lambda i, entry: built.append(entry),
                 surface=surface, ready=lambda: ready[0])
    deadline = time.monotonic() + 1
    while len(built) < 2 and time.monotonic() < deadline:
        app.processEvents()
    assert built == [1, 2]
    assert helper.overlay.isVisible()
    surface.resize(720, 500)
    app.processEvents()
    assert helper.overlay.geometry() == surface.rect()
    ready[0] = True
    deadline = time.monotonic() + 2
    while helper.overlay is not None and time.monotonic() < deadline:
        app.processEvents()
    assert helper.overlay is None
    surface.close()
