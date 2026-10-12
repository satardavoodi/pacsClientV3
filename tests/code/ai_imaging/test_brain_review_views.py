"""Brain correction presentation must never change label data."""
from types import SimpleNamespace
from xml.etree import ElementTree
from modules.ai_imaging.eagle_eye_brain import manual_slicer as review


def test_anatomical_groups_cover_names_without_losing_unknown_labels():
    cases = {'left amygdala': 'Medial temporal', 'right hippocampus': 'Medial temporal',
             'ctx-lh-entorhinal': 'Medial temporal', 'ctx-rh-superiorfrontal': 'Cortex / Frontal',
             'ctx-lh-cuneus': 'Cortex / Occipital', 'left thalamus': 'Thalamus / Diencephalon',
             'left caudate': 'Basal ganglia', 'brainstem': 'Brainstem',
             'left cerebellum white matter': 'Cerebellum',
             'left cerebral white matter': 'Cerebral white matter',
             '3rd ventricle': 'CSF / Ventricles', 'unmapped': 'Other structures'}
    for name, expected in cases.items():
        assert review.review_group(name) == expected
    assert review.review_group('unmapped', lesion=True) == 'White-matter lesion candidates'


def test_paired_layout_has_three_orientations_and_explicit_raw_overlay_titles():
    root = ElementTree.fromstring(review.paired_layout_xml())
    views = root.findall('.//view')
    assert len(views) == 6
    for orientation in ('Axial', 'Coronal', 'Sagittal'):
        pair = [v for v in views if orientation in v.attrib['singletontag']]
        assert len(pair) == 2
        assert {v.find("property[@name='viewlabel']").text for v in pair} == {
            orientation + ' | Raw', orientation + ' | Segmentation'}


def test_initial_visibility_is_off_and_raw_views_excluded():
    events = []
    display = SimpleNamespace(
        SetAllSegmentsVisibility=lambda v: events.append(('all', v)),
        RemoveAllViewNodeIDs=lambda: events.append(('clear',)),
        AddViewNodeID=lambda v: events.append(('view', v)),
        SetOpacity2DFill=lambda v: None, SetOpacity2DOutline=lambda v: None)
    review.configure_review_display(display, ['axial-overlay', 'coronal-overlay', 'sagittal-overlay'])
    assert events == [('all', False), ('clear',), ('view', 'axial-overlay'),
                      ('view', 'coronal-overlay'), ('view', 'sagittal-overlay')]


def test_panel_teardown_detaches_each_callback():
    removed = []
    node = SimpleNamespace(RemoveObserver=removed.append)
    review.remove_review_observers([(node, 12, object()), (node, 15, object())])
    assert removed == [12, 15]


def test_review_callbacks_are_owned_by_python_module_not_cpp_widget():
    owner = SimpleNamespace()
    panel = object()
    state = (object(), object())
    review.retain_review_state(owner, panel, state)
    assert owner._aipacsManualReviewPanel is panel
    assert owner._aipacsManualReviewState is state


def test_initialization_failure_without_window_exits_instead_of_hiding_error():
    events = []
    slicer = SimpleNamespace(util=SimpleNamespace(mainWindow=lambda: None),
                             app=SimpleNamespace(quit=lambda: events.append('quit')))
    review.show_review_failure(slicer)
    assert events == ['quit']


def test_anatomical_browser_replaces_native_list_inside_existing_resizable_frame():
    events = []
    container = SimpleNamespace(show=lambda: events.append('show-browser'))
    native_layout = SimpleNamespace(replaceWidget=lambda old, new: events.append(('replace', old, new)))
    native_frame = SimpleNamespace(layout=lambda: native_layout)
    native = SimpleNamespace(parent=lambda: native_frame, hide=lambda: events.append('hide-native'))
    review.replace_native_segment_list(native, container)
    assert events == [('replace', native, container), 'hide-native', 'show-browser']


def test_window_layout_settles_off_desktop_before_reveal_and_ready(monkeypatch):
    events, queued = [], []
    signature = [0]
    ticks = [0.0]
    size = lambda: SimpleNamespace(width=lambda: 900 + signature[0], height=lambda: 700)
    window = SimpleNamespace(
        ensurePolished=lambda: events.append('polished'),
        layout=lambda: SimpleNamespace(activate=lambda: events.append('layout')),
        setAttribute=lambda attr, value: events.append(('off-desktop', value)),
        show=lambda: events.append('logical-show'),
        size=size, minimumSizeHint=size, sizeHint=size)
    qt = SimpleNamespace(Qt=SimpleNamespace(WA_DontShowOnScreen=1),
                         QTimer=SimpleNamespace(singleShot=lambda delay, fn: queued.append(fn)))
    owner = SimpleNamespace(util=SimpleNamespace(resetSliceViews=lambda: events.append('reset')))
    monkeypatch.setattr(review, 'reveal_review_window', lambda *args: events.append('reveal'))
    monkeypatch.setattr(review, 'publish_review_state', lambda state: events.append(state))
    monkeypatch.setattr(review.time, 'monotonic', lambda: ticks[0])
    review.prepare_presentation(qt, owner, window)
    assert 'reveal' not in events
    # Simulate a deferred dock/layout minimum-size update after logical show.
    signature[0] = 50
    for _ in range(8):
        if not queued: break
        ticks[0] += .05
        queued.pop(0)()
    assert events.index(('off-desktop', True)) < events.index('logical-show')
    assert events.index('reset') < events.index('reveal') < events.index('ready')
    assert events.count('reveal') == 1 and not queued


def test_real_qt_deferred_minimum_size_is_applied_before_visible_ready(monkeypatch):
    from PySide6 import QtCore, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    central = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(central)
    layout.addWidget(QtWidgets.QLabel('Synthetic editor'))
    window.setCentralWidget(central)
    window.resize(600, 400)
    loop = QtCore.QEventLoop()
    observed = []
    def ready(status):
        observed.append((status, window.width(), window.testAttribute(QtCore.Qt.WA_DontShowOnScreen)))
        loop.quit()
    owner = SimpleNamespace(util=SimpleNamespace(resetSliceViews=lambda: None))
    monkeypatch.setattr(review, 'publish_review_state', ready)
    review.prepare_presentation(SimpleNamespace(Qt=QtCore.Qt, QTimer=QtCore.QTimer), owner, window)
    QtCore.QTimer.singleShot(25, lambda: central.setMinimumWidth(650))
    QtCore.QTimer.singleShot(3000, loop.quit)
    loop.exec()
    assert observed and observed[0][0] == 'ready'
    assert observed[0][1] >= 650 and not observed[0][2]
    assert window.minimumWidth() < window.maximumWidth()
    window.close()


def test_branding_replaces_native_icons_without_changing_actions_or_states():
    from PySide6 import QtCore, QtGui, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    qt = SimpleNamespace(**{name: getattr(module, name) for module, names in (
        (QtCore, ['Qt', 'QObject', 'QEvent', 'QSize']),
        (QtGui, ['QIcon', 'QPixmap', 'QPainter', 'QPainterPath', 'QColor', 'QPen', 'QBrush']),
        (QtWidgets, ['QAbstractButton'])) for name in names})
    editor = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(editor)
    effects = QtWidgets.QFrame(editor)
    effects.setObjectName('EffectsGroupBox')
    layout.addWidget(effects)
    effect_layout = QtWidgets.QVBoxLayout(effects)
    clicked = []
    buttons = []
    for parent, target, name in [(editor, layout, 'AddSegmentButton'),
                                 (editor, layout, 'RemoveSegmentButton'),
                                 (editor, layout, 'Show3DButton'),
                                 (editor, layout, 'SwitchToSegmentationsButton'),
                                 (effects, effect_layout, 'Paint'),
                                 (effects, effect_layout, 'Erase'),
                                 (effects, effect_layout, 'Scissors'),
                                 (effects, effect_layout, 'Smoothing')]:
        button = QtWidgets.QToolButton(parent)
        button.setObjectName(name)
        button.setText(name)
        button.setToolTip('Original help: ' + name)
        button.clicked.connect(lambda checked=False, n=name: clicked.append(n))
        target.addWidget(button)
        buttons.append(button)
    buttons[2].setCheckable(True)
    buttons[2].setChecked(True)
    buttons[1].setEnabled(False)
    state = review.brand_review_editor(qt, editor)
    assert state is not None
    for button in buttons:
        assert not button.icon().isNull()
        assert button.toolTip() == 'Original help: ' + button.objectName()
    fingerprints = [bytes(button.icon().pixmap(24, 24).toImage().bits()) for button in buttons]
    assert len(set(fingerprints)) == len(buttons)
    assert buttons[2].isChecked() and not buttons[1].isEnabled()
    buttons[0].click()
    buttons[4].click()
    assert clicked == ['AddSegmentButton', 'Paint']
    # Native Show 3D refresh may replace its icon; reapply on the next paint.
    expected = buttons[2].icon().cacheKey()
    buttons[2].setIcon(QtGui.QIcon())
    state.eventFilter(buttons[2], QtCore.QEvent(QtCore.QEvent.Type.Paint))
    assert buttons[2].icon().cacheKey() == expected
    editor.close()


def test_review_chrome_preserves_navigation_and_explicit_hover_artwork():
    from PySide6 import QtCore, QtGui, QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    qt = SimpleNamespace(**{name: getattr(module, name) for module, names in (
        (QtCore, ['Qt', 'QObject', 'QEvent', 'QSize']),
        (QtGui, ['QIcon', 'QPixmap', 'QPainter', 'QPainterPath', 'QColor', 'QPen', 'QBrush']),
        (QtWidgets, ['QApplication'])) for name in names})
    window = QtWidgets.QMainWindow()
    window.menuBar().addMenu('File')
    toolbar = window.addToolBar('Modules')
    toolbar.setObjectName('ModuleSelectorToolBar')
    buttons, calls = [], []
    for name in ('History', 'Previous', 'Next', 'ModuleFinder'):
        action = QtGui.QAction(name, toolbar)
        action.triggered.connect(lambda checked=False, n=name: calls.append(n))
        toolbar.addAction(action)
        buttons.append(toolbar.widgetForAction(action))
    menu = QtWidgets.QMenu(toolbar)
    home = menu.addAction('Home')
    data = menu.addAction('Data')
    buttons[0].setMenu(menu)
    buttons[2].setEnabled(False)
    state = review.brand_review_chrome(qt, window)
    assert window.menuBar().isHidden()
    for button in buttons:
        assert not button.icon().isNull()
    assert not home.icon().isNull() and not data.icon().isNull()
    assert not buttons[2].isEnabled()
    buttons[1].click()
    assert calls == ['Previous']
    original_action = buttons[1].defaultAction()
    buttons[1].setIcon(QtGui.QIcon())
    state.eventFilter(buttons[1], QtCore.QEvent(QtCore.QEvent.Paint))
    assert not buttons[1].icon().isNull()
    assert buttons[1].defaultAction() is original_action
    icon = review.review_tool_icon(qt, 'Paint')
    # Explicit variants prevent the platform style from synthesizing blue artwork.
    for mode in (QtGui.QIcon.Normal, QtGui.QIcon.Active, QtGui.QIcon.Selected, QtGui.QIcon.Disabled):
        for checked in (QtGui.QIcon.Off, QtGui.QIcon.On):
            assert icon.availableSizes(mode, checked)
    normal = icon.pixmap(24, 24, QtGui.QIcon.Normal, QtGui.QIcon.Off).toImage()
    hover = icon.pixmap(24, 24, QtGui.QIcon.Active, QtGui.QIcon.Off).toImage()
    assert normal != hover
    window.close()
