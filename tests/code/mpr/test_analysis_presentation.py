"""Presentation must preserve actions, hidden startup and screen containment."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from PySide6 import QtCore, QtGui, QtWidgets


@pytest.fixture
def ui(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setitem(sys.modules, 'qt', SimpleNamespace(**{
        name: getattr(module, name) for module in (QtCore, QtGui, QtWidgets)
        for name in dir(module) if name.startswith('Q')}))
    from modules.mpr.advanced_3d_slicer.slicer_custom_app import presentation
    return app, presentation


def test_menu_icons_preserve_identity_dispatch_and_disabled_state(ui):
    app, p = ui
    menu = QtWidgets.QMenu()
    events = []
    action = menu.addAction('Markups')
    action.setData('Markups')
    action.triggered.connect(lambda: events.append('original'))
    disabled = menu.addAction('Models'); disabled.setEnabled(False)
    child = QtWidgets.QMenu('Segmentation', menu)
    menu.addMenu(child)
    editor = child.addAction('Segment Editor'); editor.setData('SegmentEditor')
    p.decorate_menu(menu)
    assert action.data() == 'Markups'
    assert action.text() == 'Markups'
    assert not action.icon().isNull() and not editor.icon().isNull()
    assert not disabled.isEnabled()
    action.trigger()
    assert events == ['original']
    p.decorate_menu(menu)
    action.trigger()
    assert events == ['original', 'original']
    menu.deleteLater(); app.processEvents()


def test_startup_notice_uses_product_version_without_changing_warning_or_consent(ui):
    app, p = ui
    notice = QtWidgets.QMessageBox()
    notice.setText('Thank you for using AI-PACS Advanced Viewer 0.1.0-!<br><br>'
                   'This software is not intended for clinical use.')
    check = QtWidgets.QCheckBox("Don't show this message again and always OK")
    notice.setCheckBox(check)
    notice.setStandardButtons(QtWidgets.QMessageBox.Ok)
    p.correct_startup_notice(notice)
    assert notice.text() == ('Welcome to ' + p.WINDOW_TITLE + '.<br><br>'
                             'This software is not intended for clinical use.')
    assert not check.isChecked()
    assert notice.standardButtons() == QtWidgets.QMessageBox.Ok
    assert not notice.isVisible()
    other = QtWidgets.QMessageBox()
    other.setText('Unable to load image: version 0.1.0')
    p.correct_startup_notice(other)
    assert other.text() == 'Unable to load image: version 0.1.0'
    notice.deleteLater(); other.deleteLater(); app.processEvents()


def test_icons_are_distinct_and_render_at_small_sizes(ui):
    _, p = ui
    icons = [p.module_icon(name) for name in ('Markups', 'Models', 'SegmentEditor')]
    for size in (16, 24, 32):
        images = [icon.pixmap(size, size).toImage() for icon in icons]
        assert all(not image.isNull() for image in images)
        assert images[0] != images[1] and images[1] != images[2]


@pytest.mark.parametrize('screen,target', [
    ((1920, 0, 1280, 976), (2100, 50, 1920, 1032)),
    ((-1280, -200, 1280, 976), (-1400, -500, 2000, 1500)),
    ((0, 40, 1024, 728), (0, 0, 1920, 1080)),
])
def test_geometry_fits_available_screen_with_titlebar_margin(ui, screen, target):
    _, p = ui
    x, y, w, h = p.fit_geometry(screen, target)
    sx, sy, sw, sh = screen
    assert sx <= x and sy <= y
    assert x + w <= sx + sw and y + h <= sy + sh
    assert w > 0 and h > 0


@pytest.mark.parametrize('screen', [(0, 0, 1920, 1032), (-1280, 40, 1280, 976)])
@pytest.mark.parametrize('requested', [None, (0, 0, 1920, 1080)])
def test_default_geometry_is_seventy_percent_of_destination_screen(ui, screen, requested):
    _, p = ui
    x, y, w, h = p.fit_geometry(screen, requested)
    sx, sy, sw, sh = screen
    assert (w, h) == (int(sw * .70), int(sh * .70))
    assert (x, y) == (sx + (sw - w) // 2, sy + (sh - h) // 2)


def test_install_is_idempotent_does_not_show_hidden_window_or_expose_identity(ui):
    app, p = ui
    window = QtWidgets.QMainWindow()
    window.setWindowTitle('synthetic-person | very-long-study-uid')
    toolbar = QtWidgets.QToolBar(window)
    toolbar.setObjectName('ModuleSelectorToolBar')
    window.addToolBar(toolbar)
    label = QtWidgets.QLabel('Modules:'); toolbar.addWidget(label)
    window.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
    first = p.install(window)
    second = p.install(window)
    assert first is second
    assert not window.isVisible()
    assert window.testAttribute(QtCore.Qt.WA_DontShowOnScreen)
    assert window.windowTitle() == p.WINDOW_TITLE
    assert len(window.windowTitle()) < 50
    assert label.text() == 'AI-PACS / Analysis'
    window.deleteLater(); app.processEvents()


def test_install_supports_pythonqt_windows_that_reject_python_attributes(ui):
    _, p = ui
    class NativeWindow:
        __slots__ = ('wrapped',)

        def __init__(self):
            self.wrapped = QtWidgets.QMainWindow()

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    window = NativeWindow()
    first = p.install(window)
    assert p.install(window) is first
    assert window.windowTitle() == p.WINDOW_TITLE
    assert not window.isVisible()


def test_curated_menu_promotes_real_home_preserves_tools_and_hides_pipeline_entries(ui):
    _, p = ui
    menu = QtWidgets.QMenu()
    blank = menu.addAction('Home'); blank.setData('Home')
    dicom = menu.addAction('Add DICOM Data'); dicom.setData('DICOM')
    tools = QtWidgets.QMenu('AI-PACS', menu); menu.addMenu(tools)
    home = tools.addAction('AI-PACS MPR Viewer'); home.setData('NewMPR2MPR')
    pipeline = tools.addAction('Offline Lumbar'); pipeline.setData('AIPacsOfflineLumbar')
    editor = tools.addAction('Segment Editor'); editor.setData('SegmentEditor')
    editor.setEnabled(False)
    events = []
    home.triggered.connect(lambda: events.append('mpr'))
    for _ in range(2):
        p.curate_module_menu(menu)
        visible = [a for a in menu.actions() if a.isVisible()]
        assert visible == [home, editor]
        assert home.text() == 'Home / MPR'
        assert home.data() == 'NewMPR2MPR'
        assert not editor.isEnabled()
        home.trigger()
    assert events == ['mpr', 'mpr']
    # Hidden entry points still exist for their owning workflows.
    assert pipeline in tools.actions() and blank in menu.actions()
    assert not blank.isVisible() and not dicom.isVisible()


def test_install_curates_selector_and_refreshes_late_module_actions(ui):
    _, p = ui
    class ModulesMenu(QtWidgets.QMenu):
        def inherits(self, name):
            return name == 'qSlicerModulesMenu' or super().inherits(name)

    window = QtWidgets.QMainWindow()
    toolbar = QtWidgets.QToolBar(window)
    toolbar.setObjectName('ModuleSelectorToolBar')
    window.addToolBar(toolbar)
    menu = ModulesMenu(toolbar)
    home = menu.addAction('Home'); home.setData('Home')
    mpr = menu.addAction('MPR'); mpr.setData('NewMPR2MPR')
    finder = QtWidgets.QToolButton(toolbar)
    finder.setToolTip('Module finder')
    finder.show()
    p.install(window)
    assert not home.isVisible() and mpr.isVisible()
    assert finder.isHidden()
    late = menu.addAction('Developer console'); late.setData('PythonConsole')
    menu.aboutToShow.emit()
    assert not late.isVisible()
    assert [a.data() for a in menu.actions() if a.isVisible()] == ['NewMPR2MPR']


def test_curating_never_removes_native_actions(ui):
    _, p = ui
    class NativeMenu(QtWidgets.QMenu):
        def removeAction(self, action):
            raise AssertionError('Native module menu disconnects removed actions')
    menu = NativeMenu()
    action = menu.addAction('Data'); action.setData('Data')
    p.curate_module_menu(menu)
    p.curate_module_menu(menu)
    assert action.isVisible()


def test_panel_branding_is_scoped_idempotent_and_preserves_controls(ui):
    _, p = ui
    panel = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(panel)
    button = QtWidgets.QPushButton('Line'); layout.addWidget(button)
    disabled = QtWidgets.QPushButton('Remove'); disabled.setEnabled(False); layout.addWidget(disabled)
    field = QtWidgets.QDoubleSpinBox(); field.setValue(12.5); layout.addWidget(field)
    unrelated = QtWidgets.QWidget()
    events = []
    button.clicked.connect(lambda: events.append('line'))
    p.style_panel(panel, 'Markups')
    p.style_panel(panel, 'Markups')
    assert layout.count() == 4
    assert panel.findChild(QtWidgets.QLabel, 'aipacsPanelTitle').text() == 'Measurements'
    assert panel.styleSheet() and not unrelated.styleSheet()
    assert field.value() == 12.5 and not disabled.isEnabled()
    assert not button.icon().isNull()
    button.click()
    assert events == ['line']


def test_grid_panel_keeps_positions_spans_and_controls_below_brand_header(ui):
    _, p = ui
    panel = QtWidgets.QWidget(); layout = QtWidgets.QGridLayout(panel)
    field = QtWidgets.QLineEdit('unchanged'); layout.addWidget(field, 0, 0, 1, 2)
    layout.setRowStretch(0, 1)
    p.style_panel(panel, 'Data'); p.style_panel(panel, 'Data')
    assert panel.styleSheet()
    assert panel.layout().count() == 2
    assert layout.getItemPosition(layout.indexOf(field)) == (0, 0, 1, 2)
    assert layout.rowStretch(0) == 1 and field.text() == 'unchanged'


def test_chrome_locks_toolbars_and_hides_menu_without_changing_actions(ui):
    app, p = ui
    window = QtWidgets.QMainWindow()
    menu = window.menuBar().addMenu('File')
    save = menu.addAction('Save')
    events = []
    save.triggered.connect(lambda: events.append('save'))
    allowed = QtWidgets.QToolBar(window); allowed.setObjectName('ModuleSelectorToolBar')
    other = QtWidgets.QToolBar(window); other.setObjectName('MouseModeToolBar')
    window.addToolBar(allowed); window.addToolBar(other)
    panel = QtWidgets.QWidget(window); window.setCentralWidget(panel)
    internal = QtWidgets.QToolBar(panel); internal.setObjectName('ModuleInternalTools')
    adapter = p.install(window)
    window.show(); app.processEvents()
    assert window.menuBar().isHidden()
    assert allowed.isVisible() and other.isHidden()
    assert internal.isVisible() and internal.toggleViewAction().isEnabled()
    for toolbar in (allowed, other):
        assert not toolbar.isMovable() and not toolbar.isFloatable()
        assert not toolbar.toggleViewAction().isEnabled()
        assert not toolbar.toggleViewAction().isVisible()
    other.show(); window.menuBar().show(); app.processEvents()
    assert other.isHidden() and window.menuBar().isHidden()
    late = QtWidgets.QToolBar(window); late.setObjectName('ExtensionToolBar')
    window.addToolBar(late); late.show(); app.processEvents()
    assert late.isHidden() and not late.toggleViewAction().isEnabled()
    save.trigger()
    assert events == ['save'] and save.isEnabled()
    window.close(); window.deleteLater(); app.processEvents()


def test_save_dialog_branding_preserves_destination_selection_and_callbacks(ui):
    app, p = ui
    dialog = QtWidgets.QDialog(); dialog.setObjectName('qSlicerSaveDataDialog')
    layout = QtWidgets.QVBoxLayout(dialog)
    buttons = []
    events = []
    for name in ('SelectSceneDataButton', 'SelectDataButton', 'DataBundleButton'):
        button = QtWidgets.QToolButton(dialog); button.setObjectName(name)
        button.setCheckable(True); button.setChecked(True)
        button.clicked.connect(lambda: events.append('original'))
        layout.addWidget(button); buttons.append(button)
    destination = QtWidgets.QLineEdit('synthetic-destination', dialog); layout.addWidget(destination)
    box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
    layout.addWidget(box)
    p.brand_save_dialog(dialog)
    assert dialog.windowTitle() == 'AI-PACS | Save Scene and Data'
    assert not dialog.windowIcon().isNull()
    assert all(not b.icon().isNull() and b.isChecked() for b in buttons)
    assert destination.text() == 'synthetic-destination'
    assert box.standardButtons() == (QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
    buttons[0].click(); assert events == ['original']
    unrelated = QtWidgets.QDialog(); unrelated.setWindowTitle('Unrelated')
    p.brand_save_dialog(unrelated)
    assert unrelated.windowTitle() == 'Unrelated' and not unrelated.styleSheet()
    dialog.deleteLater(); unrelated.deleteLater(); app.processEvents()
