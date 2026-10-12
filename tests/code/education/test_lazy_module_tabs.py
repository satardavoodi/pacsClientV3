"""Real Education shell with synthetic pages; no database or clinical assets."""
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture
def shell(monkeypatch, request):
    from modules.education import education_module_redesigned as module
    from modules.education import online_consultation
    app = QApplication.instance() or QApplication([])
    calls = []
    class Theme(QObject):
        themeChanged = Signal(object)
        def current_theme(self): return {}
    theme = Theme()
    monkeypatch.setattr(module, 'get_theme_manager', lambda: theme)
    monkeypatch.setattr(module, '_retint_widget_tree', lambda *a: None)
    monkeypatch.setattr(online_consultation, 'online_consultation_available', lambda: getattr(request, 'param', True))
    def page(kind):
        class Page(QWidget):
            course_opened = Signal(dict); course_edited = Signal(dict)
            case_of_day_opened = Signal(dict); case_opened = Signal(dict)
            course_created = Signal(dict); preview_requested = Signal(dict)
            case_created = Signal(dict)
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs); calls.append(kind)
                self.load_courses = Mock(); self.refresh = Mock()
        return Page
    for name, kind in [('LibraryPage','library'), ('MyCoursesPage','mycourses'), ('BuildCoursePage','build')]:
        monkeypatch.setattr(module, name, page(kind))
    for name, attribute, kind in [
        ('modules.education.case_of_day_widget', 'CaseOfDayLocalServerPage', 'case'),
        ('modules.education.online_consultation.consultation_page', 'OnlineConsultationPage', 'consultation')]:
        fake = ModuleType(name); setattr(fake, attribute, page(kind)); monkeypatch.setitem(sys.modules, name, fake)
    def forbidden(*a, **k): pytest.fail('Shell must not access a database')
    monkeypatch.setattr(module, 'get_all_courses', forbidden)
    widget = module.EducationModuleRedesigned()
    yield widget, calls, app
    from shiboken6 import isValid
    if isValid(widget):
        widget.close(); widget.deleteLater()
    app.processEvents()


def test_shell_constructs_no_pages_or_hidden_services(shell):
    widget, calls, app = shell
    assert calls == []
    assert widget.tab_widget.count() == 5
    widget.show(); app.processEvents()
    assert calls == ['library']


def test_select_only_constructs_target_and_reuses_state(shell):
    widget, calls, app = shell
    assert calls == []
    widget.show(); app.processEvents()
    widget.tab_widget.setCurrentIndex(2); app.processEvents()
    editor = widget.build_page
    editor.synthetic_draft = 'retained'
    widget.tab_widget.setCurrentIndex(0); app.processEvents()
    widget.tab_widget.setCurrentIndex(2); app.processEvents()
    assert calls == ['library', 'build']
    assert widget.build_page is editor and editor.synthetic_draft == 'retained'


def test_secretary_direct_page_access_preserves_real_tab_identity(shell):
    widget, calls, app = shell
    assert calls == []
    saved = Mock(); widget.on_course_created = saved
    editor = widget.build_page
    assert calls == ['build']
    assert widget.tab_widget.indexOf(editor) == 2
    widget.tab_widget.setCurrentWidget(editor)
    editor.course_created.emit({})
    saved.assert_called_once_with({})
    app.processEvents()
    assert calls == ['build']


def test_refresh_does_not_load_unvisited_pages(shell):
    widget, calls, app = shell
    widget.refresh_loaded_pages()
    assert calls == []
    library = widget.library_page
    widget.refresh_loaded_pages()
    library.load_courses.assert_called_once()
    assert calls == ['library']


def test_failed_page_can_retry_without_retiring_other_tabs(shell):
    widget, calls, app = shell
    assert calls == []
    original = widget._page_factories['build']
    widget._page_factories['build'] = Mock(side_effect=RuntimeError('synthetic failure'))
    with pytest.raises(RuntimeError):
        _ = widget.build_page
    widget._page_factories['build'] = original
    editor = widget.build_page
    assert calls == ['build'] and widget.tab_widget.indexOf(editor) == 2


def test_consultation_deep_link_only_loads_requested_page(shell):
    widget, calls, app = shell
    assert calls == []
    widget.show_online_consultation()
    assert calls == ['consultation']
    assert widget.tab_widget.currentWidget() is widget.online_consultation_page


def test_superseded_selection_skips_unused_factories(shell):
    widget, calls, app = shell
    widget.show()
    widget.tab_widget.setCurrentIndex(2)
    widget.tab_widget.setCurrentIndex(3)
    app.processEvents()
    assert calls == ['case']


def test_native_deletion_retires_queued_page_loading(shell):
    widget, calls, app = shell
    from shiboken6 import delete
    widget.show(); delete(widget); app.processEvents()
    assert calls == []


def test_hidden_shell_does_not_run_queued_page_loading(shell):
    widget, calls, app = shell
    widget.show(); widget.hide(); app.processEvents()
    assert calls == []
    widget.show(); app.processEvents()
    assert calls == ['library']


@pytest.mark.parametrize('shell', [False], indirect=True)
def test_disabled_consultation_has_no_slot_or_factory(shell):
    widget, calls, app = shell
    assert widget.tab_widget.count() == 4
    assert widget.online_consultation_page is None
    assert 'consultation' not in widget._page_factories
    assert calls == []


def test_settings_import_refresh_does_not_construct_hidden_pages(shell):
    import ast
    from pathlib import Path
    widget, calls, app = shell
    path = Path('PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == '_refresh_local_education')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    namespace['_refresh_local_education'](object())
    assert calls == []


def test_selected_page_error_offers_retry_in_same_tab(shell):
    from PySide6.QtWidgets import QLabel, QPushButton
    widget, calls, app = shell
    original = widget._page_factories['build']
    widget._page_factories['build'] = Mock(side_effect=RuntimeError('synthetic failure'))
    widget.show(); widget.tab_widget.setCurrentIndex(2); app.processEvents()
    slot = widget.tab_widget.currentWidget()
    assert 'Unable to load' in slot.findChild(QLabel).text()
    assert slot.findChild(QPushButton).isVisible()
    widget._page_factories['build'] = original
    slot.findChild(QPushButton).click(); app.processEvents()
    assert calls == ['build']
    assert widget.tab_widget.currentWidget() is widget.build_page
