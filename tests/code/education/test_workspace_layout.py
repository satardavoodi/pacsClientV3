"""Synthetic geometry checks for the Education workspace."""
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
from PySide6.QtCore import QPoint

def test_course_actions_stay_outside_scrolling_details(monkeypatch):
    from modules.education import education_module_redesigned as m
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(m, 'get_course_with_slides', lambda *a: {'slides': []})
    panel = m.CourseDetailsPanel(); panel.resize(440, 500)
    panel.show_course({'course_pk': -1, 'course_name': 'Synthetic lesson', 'course_description': 'Long description. ' * 300})
    panel.show(); app.processEvents()
    scroll = panel.findChild(QScrollArea)
    buttons = [b for b in panel.findChildren(QPushButton) if b.text() in ('Open Course', 'Edit Course', 'Download to My Courses')]
    assert len(buttons) == 3
    for button in buttons:
        assert not scroll.isAncestorOf(button)
        assert panel.rect().contains(button.mapTo(panel, QPoint(0, button.height()-1)))
    panel.close()

def test_build_form_uses_available_width():
    from modules.education.education_module_redesigned import BuildCoursePage
    app = QApplication.instance() or QApplication([])
    page = BuildCoursePage(); page.resize(1800, 900); page.show()
    for _ in range(3): app.processEvents()
    assert page.title_input.width() >= 600
    assert page.author_input.y() - page.title_input.y() < 130
    page.close()

def test_library_reflows_after_viewport_resize(monkeypatch):
    from modules.education import education_module_redesigned as m
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(m.LibraryPage, 'load_courses', lambda self: None)
    page = m.LibraryPage(); page.resize(1850, 850); page.show()
    for _ in range(4): app.processEvents()
    assert page._last_grid_cols == page._responsive_columns()
    assert page._last_grid_cols >= 2
    page.close()
