"""Shared native viewer artwork. No workstation Qt, scene or imaging dependencies."""


def _qt_value(owner, name):
    value = getattr(owner, name)
    return value() if callable(value) else value


# Original AI-PACS line artwork, embedded so frozen editors need no icon files.
_REVIEW_ICON_LINES = {
    'AddSegmentButton': [[(5, 9), (12, 5), (19, 9), (12, 13), (5, 9)], [(5, 14), (12, 18)], [(17, 15), (17, 21)], [(14, 18), (20, 18)]],
    'RemoveSegmentButton': [[(6, 7), (18, 7), (17, 20), (7, 20), (6, 7)], [(5, 4), (19, 4)], [(10, 12), (14, 12)]],
    'Show3DButton': [[(12, 3), (21, 8), (21, 17), (12, 22), (3, 17), (3, 8), (12, 3)], [(3, 8), (12, 13), (21, 8)], [(12, 13), (12, 22)]],
    'SwitchToSegmentationsButton': [[(4, 5), (12, 5), (12, 13), (4, 13), (4, 5)], [(12, 18), (21, 18)], [(17, 14), (21, 18), (17, 22)]],
    'Paint': [[(7, 15), (15, 5), (19, 9), (10, 18), (7, 15)], [(6, 15), (4, 21), (10, 19)]],
    'Erase': [[(4, 14), (13, 5), (20, 12), (12, 20), (9, 20), (4, 14)], [(8, 10), (15, 17)], [(12, 21), (21, 21)]],
    'Draw': [[(4, 18), (5, 10), (10, 6), (17, 8)], [(12, 18), (20, 6), (22, 8), (14, 20), (11, 21), (12, 18)]],
    'Scissors': [[(8, 8), (20, 20)], [(8, 16), (20, 4)]],
    'Smoothing': [[(3, 16), (6, 7), (10, 18), (14, 6), (18, 14), (21, 10)]],
    'Threshold': [[(4, 20), (4, 15)], [(8, 20), (8, 10)], [(12, 20), (12, 5)], [(16, 20), (16, 8)], [(20, 20), (20, 13)], [(3, 11), (21, 11)]],
    'Level tracing': [[(4, 17), (5, 8), (12, 3), (20, 8), (20, 17), (12, 21), (4, 17)], [(8, 15), (8, 10), (12, 7), (16, 11), (15, 16), (8, 15)]],
    'Grow from seeds': [[(12, 12), (5, 5)], [(12, 12), (20, 6)], [(12, 12), (18, 20)], [(12, 12), (4, 19)]],
    'Fill between slices': [[(3, 6), (11, 3), (21, 6)], [(3, 12), (11, 9), (21, 12)], [(3, 18), (11, 15), (21, 18)], [(12, 6), (12, 18)]],
    'Margin': [[(8, 8), (16, 8), (16, 16), (8, 16), (8, 8)], [(3, 3), (7, 3)], [(3, 3), (3, 7)], [(17, 21), (21, 21), (21, 17)]],
    'Hollow': [[(4, 4), (20, 4), (20, 20), (4, 20), (4, 4)], [(9, 9), (15, 9), (15, 15), (9, 15), (9, 9)]],
    'Logical operators': [[(3, 6), (14, 6), (14, 17), (3, 17), (3, 6)], [(10, 10), (21, 10), (21, 21), (10, 21), (10, 10)]],
    'Mask volume': [[(4, 6), (20, 6), (20, 19), (4, 19), (4, 6)], [(8, 6), (8, 19)], [(12, 6), (12, 19)], [(16, 6), (16, 19)]],
    'UndoButton': [[(9, 5), (4, 10), (9, 15)], [(4, 10), (15, 10), (19, 14), (19, 20)]],
    'RedoButton': [[(15, 5), (20, 10), (15, 15)], [(20, 10), (9, 10), (5, 14), (5, 20)]],
    'None': [[(5, 3), (5, 19), (10, 15), (14, 21), (17, 19), (13, 13), (20, 12), (5, 3)]],
    'Islands': [[(3, 4), (9, 4), (9, 10), (3, 10), (3, 4)], [(14, 7), (20, 7), (20, 13), (14, 13), (14, 7)], [(7, 16), (12, 16), (12, 21), (7, 21), (7, 16)]],
}
_REVIEW_ICON_LINES['NULL'] = _REVIEW_ICON_LINES['None']
_REVIEW_ICON_LINES.update({
    'SpecifyGeometryButton': [[(3, 4), (18, 4), (18, 19), (3, 19), (3, 4)], [(8, 4), (8, 19)], [(3, 9), (18, 9)], [(13, 4), (13, 19)], [(3, 14), (18, 14)], [(18, 19), (22, 23)]],
    'Models': [[(12, 3), (21, 9), (18, 20), (5, 18), (3, 8), (12, 3)], [(3, 8), (12, 12), (21, 9)], [(12, 12), (18, 20)], [(12, 3), (12, 12), (5, 18)]],
    'Markups': [[(4, 19), (10, 5), (20, 15), (4, 19)], [(3, 16), (6, 20)], [(8, 4), (12, 6)], [(19, 13), (21, 17)]],
    'Informatics': [[(3, 4), (21, 4), (21, 20), (3, 20), (3, 4)], [(7, 9), (17, 9)], [(7, 14), (12, 14)], [(17, 13), (17, 17)]],
    'Rendering': [[(12, 2), (21, 7), (21, 17), (12, 22), (3, 17), (3, 7), (12, 2)], [(8, 12), (12, 7), (16, 12), (12, 17), (8, 12)]],
    'Registration': [[(3, 3), (12, 3), (12, 12), (3, 12), (3, 3)], [(12, 12), (21, 12), (21, 21), (12, 21), (12, 12)], [(7, 17), (17, 7)], [(12, 7), (17, 7), (17, 12)]],
    'Quantification': [[(4, 3), (4, 21), (21, 21)], [(8, 18), (8, 14)], [(13, 18), (13, 9)], [(18, 18), (18, 5)]],
    'Diffusion': [[(12, 12), (3, 5)], [(12, 12), (20, 3)], [(12, 12), (22, 17)], [(12, 12), (7, 22)]],
    'Converters': [[(3, 6), (20, 6), (16, 2)], [(20, 6), (16, 10)], [(21, 18), (4, 18), (8, 14)], [(4, 18), (8, 22)]],
    'Developer': [[(8, 5), (2, 12), (8, 19)], [(16, 5), (22, 12), (16, 19)], [(14, 3), (10, 21)]],
    'Sequences': [[(3, 4), (17, 4), (17, 16), (3, 16), (3, 4)], [(7, 16), (7, 20), (21, 20), (21, 8), (17, 8)]],
    'Servers': [[(3, 3), (21, 3), (21, 9), (3, 9), (3, 3)], [(3, 14), (21, 14), (21, 20), (3, 20), (3, 14)], [(7, 6), (10, 6)], [(7, 17), (10, 17)]],
    'Pin': [[(8, 3), (16, 3), (15, 10), (19, 14), (5, 14), (9, 10), (8, 3)], [(12, 14), (12, 22)]],
    'Fit': [[(3, 9), (3, 3), (9, 3)], [(15, 3), (21, 3), (21, 9)], [(21, 15), (21, 21), (15, 21)], [(9, 21), (3, 21), (3, 15)], [(8, 12), (16, 12)], [(12, 8), (12, 16)]],
    'Maximize': [[(3, 9), (3, 3), (9, 3)], [(15, 3), (21, 3), (21, 9)], [(21, 15), (21, 21), (15, 21)], [(9, 21), (3, 21), (3, 15)]],
    'Link': [[(10, 7), (13, 4), (20, 4), (22, 7), (16, 13)], [(14, 17), (11, 20), (4, 20), (2, 17), (8, 11)], [(8, 16), (16, 8)]],
    'Visibility': [[(2, 12), (7, 6), (17, 6), (22, 12), (17, 18), (7, 18), (2, 12)], [(9, 12), (12, 9), (15, 12), (12, 15), (9, 12)]],
    'Orientation': [[(4, 19), (4, 5), (18, 5)], [(1, 8), (4, 5), (7, 8)], [(15, 2), (18, 5), (15, 8)], [(10, 12), (19, 12), (19, 21), (10, 21), (10, 12)]],
    'Scroll': [[(12, 2), (7, 7)], [(12, 2), (17, 7)], [(12, 2), (12, 22)], [(7, 17), (12, 22), (17, 17)]],
    'Layers': [[(3, 8), (12, 3), (21, 8), (12, 13), (3, 8)], [(3, 13), (12, 18), (21, 13)], [(3, 18), (12, 23), (21, 18)]],
    'Ruler': [[(3, 7), (21, 7), (21, 17), (3, 17), (3, 7)], [(7, 7), (7, 12)], [(12, 7), (12, 14)], [(17, 7), (17, 12)]],
    'Slab': [[(3, 6), (21, 6), (21, 18), (3, 18), (3, 6)], [(3, 10), (21, 10)], [(3, 14), (21, 14)]],
    'Interpolation': [[(3, 18), (7, 18), (7, 12), (13, 12), (13, 6), (21, 6)], [(3, 21), (21, 3)]],
    'Settings': [[(4, 6), (20, 6)], [(4, 12), (20, 12)], [(4, 18), (20, 18)], [(8, 3), (8, 9)], [(16, 9), (16, 15)], [(11, 15), (11, 21)]],
    'Home': [[(3, 11), (12, 3), (21, 11)], [(6, 10), (6, 21), (18, 21), (18, 10)], [(10, 21), (10, 15), (14, 15), (14, 21)]],
    'Data': [[(4, 5), (20, 5), (20, 20), (4, 20), (4, 5)], [(8, 10), (16, 10)], [(8, 15), (16, 15)]],
    'AddData': [[(3, 7), (9, 7), (11, 10), (21, 10), (21, 20), (3, 20), (3, 7)], [(15, 3), (15, 9)], [(12, 6), (18, 6)]],
    'History': [[(5, 7), (12, 3), (20, 8), (20, 17), (12, 21), (4, 17)], [(3, 3), (3, 9), (9, 9)], [(12, 7), (12, 12), (16, 14)]],
    'Previous': [[(14, 5), (7, 12), (14, 19)], [(7, 12), (21, 12)]],
    'Next': [[(10, 5), (17, 12), (10, 19)], [(3, 12), (17, 12)]],
    'ModuleFinder': [[(3, 3), (15, 3), (15, 15), (3, 15), (3, 3)], [(15, 15), (22, 22)], [(7, 9), (11, 9)], [(9, 7), (9, 11)]],
    'Modules': [[(3, 3), (9, 3), (9, 9), (3, 9), (3, 3)], [(15, 3), (21, 3), (21, 9), (15, 9), (15, 3)], [(3, 15), (9, 15), (9, 21), (3, 21), (3, 15)], [(15, 15), (21, 15), (21, 21), (15, 21), (15, 15)]],
})

_REVIEW_BUTTON_STYLE = '''
QToolButton, QPushButton {
    background: #172738; color: #e1edf6; border: 1px solid #38516a;
    border-radius: 5px; padding: 4px;
}
QToolButton:hover, QPushButton:hover { background: #293952; border-color: #b8a4ed; }
QToolButton:checked, QPushButton:checked, QToolButton:pressed, QPushButton:pressed {
    background: #403453; border-color: #b8a4ed;
}
QToolButton:disabled, QPushButton:disabled { color: #8192a3; border-color: #293746; }
QToolButton::menu-indicator, QToolButton::menu-arrow {
    image: none; width: 5px; height: 5px; background: #b8a4ed; border-radius: 2px;
}
QToolTip { background: #233248; color: #edf3fa; border: 1px solid #b8a4ed; padding: 6px; }
'''


def review_tool_icon(qt, name, compact=False):
    pixmap = qt.QPixmap(48, 48)
    pixmap.fill(qt.Qt.transparent)
    painter = qt.QPainter(pixmap)
    try:
        painter.setRenderHint(qt.QPainter.Antialiasing, True)
        painter.scale(2, 2)
        pen = qt.QPen(qt.QColor('#67d6ed'))
        pen.setWidthF(1.7)
        painter.setPen(pen)
        painter.setBrush(qt.QBrush(qt.Qt.NoBrush))
        paths = _REVIEW_ICON_LINES.get(name, [[(12, 3), (21, 12), (12, 21), (3, 12), (12, 3)]])
        for points in paths:
            path = qt.QPainterPath()
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)
            painter.drawPath(path)
        if name == 'Scissors':
            painter.drawEllipse(2, 3, 6, 6)
            painter.drawEllipse(2, 15, 6, 6)
        pen.setColor(qt.QColor('#a995ff'))
        painter.setPen(pen)
        if not compact:
            painter.drawLine(18, 23, 23, 23)
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(2)
    variants = {}
    for color in ('#b8a4ed', '#8192a3'):
        variant = qt.QPixmap(pixmap)
        tint = qt.QPainter(variant)
        try:
            tint.setCompositionMode(qt.QPainter.CompositionMode_SourceIn)
            tint.fillRect(variant.rect(), qt.QColor(color))
        finally:
            tint.end()
        variants[color] = variant
    icon = qt.QIcon()
    for mode in (qt.QIcon.Normal, qt.QIcon.Active, qt.QIcon.Selected, qt.QIcon.Disabled):
        for state in (qt.QIcon.Off, qt.QIcon.On):
            artwork = (variants['#8192a3'] if mode == qt.QIcon.Disabled else
                       variants['#b8a4ed'] if mode in (qt.QIcon.Active, qt.QIcon.Selected) or state == qt.QIcon.On else pixmap)
            icon.addPixmap(artwork, mode, state)
    return icon


def brand_review_editor(qt, editor):
    """Replace presentation only; preserve native actions, help and state."""
    class ReviewIconGuard(qt.QObject):
        def __init__(self):
            super().__init__(editor)
            self.icons = {}

        def eventFilter(self, watched, event):
            if event.type() == qt.QEvent.Paint:
                key = watched.property('aipacsReviewIconKey')
                icon = self.icons.get(key)
                if icon is not None and _qt_value(_qt_value(watched, 'icon'), 'cacheKey') != icon.cacheKey():
                    watched.setIcon(icon)
            return False

    guard = ReviewIconGuard()

    def visit(parent, in_effects=False):
        in_effects = in_effects or _qt_value(parent, 'objectName') == 'EffectsGroupBox'
        for child in parent.children():
            name = _qt_value(child, 'objectName')
            if child.inherits('QAbstractButton') and (in_effects or name in _REVIEW_ICON_LINES):
                icon = guard.icons.setdefault(name, review_tool_icon(qt, name))
                child.setIcon(icon)
                child.setIconSize(qt.QSize(20, 20))
                child.setProperty('aipacsReviewIconKey', name)
                child.setProperty('aipacsReviewTool', True)
                child.setStyleSheet(_REVIEW_BUTTON_STYLE)
                child.installEventFilter(guard)
            visit(child, in_effects)

    visit(editor)
    return guard


def brand_review_chrome(qt, window):
    """Brand native navigation in place, without replacing module actions."""
    class ChromeGuard(qt.QObject):
        def __init__(self):
            super().__init__(window)
            self.icons = {}

        def icon(self, key):
            if key not in self.icons:
                self.icons[key] = review_tool_icon(qt, key)
            return self.icons[key]

        def key(self, text):
            text = ''.join(c for c in str(text).lower() if c.isalnum())
            return {'home': 'Home', 'welcome': 'Home', 'data': 'Data',
                    'adddata': 'AddData', 'adddicomdata': 'AddData',
                    'dicom': 'AddData', 'history': 'History',
                    'previous': 'Previous', 'next': 'Next',
                    'modulefinder': 'ModuleFinder', 'homempr': 'Home',
                    'models': 'Models', '3dsurfaces': 'Models',
                    'markups': 'Markups', 'measurements': 'Markups',
                    'segmenteditor': 'Draw', 'segmentationeditor': 'Draw',
                    'segmentations': 'Layers', 'segmentationmanager': 'Layers',
                    'segmentation': 'Layers', 'volumes': 'Slab', 'imagedisplay': 'Slab',
                    'volumerendering': 'Rendering', '3drendering': 'Rendering',
                    'informatics': 'Informatics', 'registration': 'Registration',
                    'transforms': 'Orientation', 'quantification': 'Quantification',
                    'diffusion': 'Diffusion', 'converters': 'Converters',
                    'utilities': 'Settings', 'developertools': 'Developer',
                    'aipacs': 'Home', 'sequences': 'Sequences', 'servers': 'Servers'
                    }.get(text, 'Modules')

        def decorate_menu(self, menu):
            for action in menu.actions():
                if not _qt_value(action, 'isSeparator'):
                    action.setIcon(self.icon(self.key(_qt_value(action, 'text'))))
                submenu = action.menu()
                if submenu is not None:
                    self.decorate_menu(submenu)

        def eventFilter(self, watched, event):
            if watched.inherits('QMenu') and event.type() == qt.QEvent.Show:
                self.decorate_menu(watched)
            elif watched.inherits('QMenuBar') and event.type() == qt.QEvent.Show:
                watched.hide()
            elif watched.inherits('QAbstractButton') and event.type() == qt.QEvent.Paint:
                icon = self.icon(self.key(_qt_value(watched, 'text')))
                if _qt_value(_qt_value(watched, 'icon'), 'cacheKey') != icon.cacheKey():
                    watched.setIcon(icon)
            return False

    guard = ChromeGuard()
    menu_bar = window.menuBar()
    menu_bar.hide()
    menu_bar.installEventFilter(guard)

    def visit(parent, in_selector=False):
        in_selector = in_selector or _qt_value(parent, 'objectName') == 'ModuleSelectorToolBar'
        for child in parent.children():
            if in_selector and child.inherits('QAbstractButton'):
                child.setIcon(guard.icon(guard.key(_qt_value(child, 'text'))))
                child.setIconSize(qt.QSize(20, 20))
                child.setStyleSheet(_REVIEW_BUTTON_STYLE)
                child.installEventFilter(guard)
            if in_selector and child.inherits('QMenu'):
                guard.decorate_menu(child)
                child.installEventFilter(guard)
            visit(child, in_selector)

    visit(window)
    return guard


_VIEWPORT_BUTTON_STYLE = '''
QToolButton, QPushButton {
    background: transparent; color: #dce5ef; border: 1px solid transparent;
    border-radius: 3px; padding: 1px; min-width: 18px; min-height: 18px;
}
QToolButton:hover, QPushButton:hover { background: #293446; border-color: #59667c; }
QToolButton:checked, QPushButton:checked, QToolButton:pressed, QPushButton:pressed {
    background: #373248; border-color: #9e91bf;
}
QToolButton:disabled, QPushButton:disabled { color: #8192a3; }
QToolButton::menu-indicator, QToolButton::menu-arrow {
    image: none; width: 3px; height: 3px; background: #a79bbf; border-radius: 1px;
}
QToolTip { background: #233248; color: #edf3fa; border: 1px solid #59667c; padding: 5px; }
'''

_SLIDER_STYLE = '''
QSlider::groove:horizontal { background: #344458; height: 2px; border-radius: 1px; }
QSlider::handle:horizontal { background: #b8a4ed; border: 1px solid #e5dcfb;
    width: 8px; margin: -3px 0; border-radius: 4px; }
QSlider::sub-page:horizontal { background: #67b8c8; border-radius: 2px; }
QSlider::groove:vertical { background: #344458; width: 2px; border-radius: 1px; }
QSlider::handle:vertical { background: #b8a4ed; border: 1px solid #e5dcfb;
    height: 8px; margin: 0 -3px; border-radius: 4px; }
'''

_SEGMENT_ACTIONS = {'AddSegmentButton', 'RemoveSegmentButton', 'Show3DButton',
                    'SwitchToSegmentationsButton', 'SpecifyGeometryButton'}
_SEGMENT_ACTION_STYLE = _VIEWPORT_BUTTON_STYLE + '''
QToolButton, QPushButton { background: #202b34; border: 1px solid #35434f;
    padding: 3px 6px; min-height: 20px; }
QToolButton:hover, QPushButton:hover { background: #2a3543; border-color: #9389ae; }
QToolButton:checked, QPushButton:checked { background: #373248; border-color: #a79bbf; }
'''

_POSITION_STYLE = '''
QAbstractSpinBox, QLineEdit { background: #202830; color: #e1edf6;
    border: 1px solid #34404c; border-radius: 3px; padding: 2px 3px;
    font-size: 11px; selection-background-color: #403453; selection-color: #ffffff; }
QAbstractSpinBox:focus, QLineEdit:focus { border-color: #a79bbf; }
'''

_COMBO_STYLE = '''
QComboBox { background: #202830; color: #e1edf6; border: 1px solid #34404c;
    border-radius: 3px; padding: 1px 14px 1px 3px; }
QComboBox:hover { border-color: #b8a4ed; }
QComboBox::drop-down { border: 0; width: 16px; }
QComboBox::down-arrow { image: none; width: 5px; height: 5px;
    background: #b8a4ed; border-radius: 2px; }
QComboBox QAbstractItemView { background: #172738; color: #e1edf6;
    selection-background-color: #403453; selection-color: #ffffff; }
'''


def viewport_icon_key(widget):
    text = (str(_qt_value(widget, 'objectName')) + ' ' +
            str(_qt_value(widget, 'toolTip'))).lower()
    for words, key in ((('pin', 'popup'), 'Pin'),
                       (('fit', 'field of view', 'reset'), 'Fit'),
                       (('maximize', 'restore', 'minimize'), 'Maximize'),
                       (('link',), 'Link'), (('visib', 'outline'), 'Visibility'),
                       (('orient', 'rotate', 'reformat'), 'Orientation'),
                       (('scroll', 'offset', 'slice spacing'), 'Scroll'),
                       (('ruler',), 'Ruler'), (('slab',), 'Slab'),
                       (('interpol',), 'Interpolation'), (('more', 'option'), 'Settings'),
                       (('layer', 'composite', 'volume', 'image'), 'Layers')):
        if any(word in text for word in words):
            return key
    return 'Modules'


def install(qt, window):
    """One common profile for MPR and every function-specific review process."""
    window = window.window()  # Resolve proxy wrappers to the native QObject owner.
    class ViewerChrome(qt.QObject):
        def __init__(self):
            super().__init__(window)
            self.editor = brand_review_editor(qt, window)
            self.navigation = brand_review_chrome(qt, window)

        def contexts(self, widget):
            effects, viewport, selector, owned = False, False, False, False
            parent = widget
            while parent is not None:
                name = str(_qt_value(parent, 'objectName'))
                effects = effects or name == 'EffectsGroupBox'
                viewport = viewport or 'Controller' in name or any(parent.inherits(cls) for cls in (
                    'qMRMLSliceControllerWidget', 'qMRMLThreeDViewControllerWidget',
                    'qMRMLViewControllerBar'))
                selector = selector or name == 'ModuleSelectorToolBar'
                if parent == window:
                    owned = True
                    break
                parent = parent.parent()
            return owned, effects, viewport, selector

        def decorate(self, widget):
            owned, effects, viewport, selector = self.contexts(widget)
            if not owned:
                return
            if widget.inherits('QMenuBar'):
                widget.hide()
            elif selector and widget.inherits('QMenu'):
                self.navigation.decorate_menu(widget)
            elif widget.inherits('QAbstractButton'):
                name = str(_qt_value(widget, 'objectName'))
                if selector:
                    key = self.navigation.key(_qt_value(widget, 'text'))
                    icon = self.navigation.icon(key)
                    filter_owner = self.navigation
                elif effects or name in _REVIEW_ICON_LINES or viewport:
                    key = name if effects or name in _REVIEW_ICON_LINES else viewport_icon_key(widget)
                    artwork_key = key
                    if viewport and not effects or name in _SEGMENT_ACTIONS:
                        key = ('viewport:' if viewport else 'action:') + key
                    if key not in self.editor.icons:
                        self.editor.icons[key] = review_tool_icon(qt, artwork_key, compact=viewport and not effects or name in _SEGMENT_ACTIONS)
                    icon = self.editor.icons[key]
                    filter_owner = self.editor
                else:
                    return
                widget.setIcon(icon)
                compact = viewport and not effects and not selector
                segment_action = name in _SEGMENT_ACTIONS
                widget.setIconSize(qt.QSize(14, 14) if compact else qt.QSize(16, 16) if segment_action else qt.QSize(20, 20))
                widget.setProperty('aipacsReviewIconKey', key)
                if not widget.property('aipacsCommonChrome'):
                    widget.setStyleSheet(_VIEWPORT_BUTTON_STYLE if compact else _SEGMENT_ACTION_STYLE if segment_action else _REVIEW_BUTTON_STYLE)
                    widget.installEventFilter(filter_owner)
                    widget.setProperty('aipacsCommonChrome', True)
            elif viewport and widget.inherits('QSlider'):
                if not widget.property('aipacsCommonChrome'):
                    widget.setStyleSheet(_SLIDER_STYLE)
                    widget.setProperty('aipacsCommonChrome', True)
            elif (viewport or selector) and widget.inherits('QComboBox'):
                key = 'module' if selector else viewport_icon_key(widget)
                widget.setProperty('aipacsCommonCombo', key)
                widget.setStyleSheet(_COMBO_STYLE)
                widget.setIconSize(qt.QSize(14, 14))
                self.combo_icons(widget)
            elif viewport and widget.inherits('QLabel'):
                widget.setStyleSheet('QLabel { color: #cbd6e2; background: transparent; }')
            elif viewport and (widget.inherits('QAbstractSpinBox') or widget.inherits('QLineEdit')):
                widget.setStyleSheet(_POSITION_STYLE)

        def combo_icons(self, widget, current_only=False):
            key = widget.property('aipacsCommonCombo')
            indices = [_qt_value(widget, 'currentIndex')] if current_only else range(_qt_value(widget, 'count'))
            for index in indices:
                if index >= 0:
                    icon = self.navigation.icon(self.navigation.key(widget.itemText(index)) if key == 'module' else key)
                    if _qt_value(widget.itemIcon(index), 'cacheKey') != icon.cacheKey():
                        widget.setItemIcon(index, icon)

        def eventFilter(self, widget, event):
            if event.type() in (qt.QEvent.Polish, qt.QEvent.Show):
                if widget.inherits('QWidget'):
                    self.decorate(widget)
            elif event.type() == qt.QEvent.Paint and widget.property('aipacsCommonCombo'):
                self.combo_icons(widget, current_only=True)
            elif event.type() == qt.QEvent.Paint and widget.property('aipacsCommonChrome'):
                key = widget.property('aipacsReviewIconKey')
                icon = self.editor.icons.get(key) or self.navigation.icons.get(key)
                if icon is not None and _qt_value(_qt_value(widget, 'icon'), 'cacheKey') != icon.cacheKey():
                    widget.setIcon(icon)
            return False

        def walk(self, parent):
            self.decorate(parent)
            for child in parent.children():
                self.walk(child)

    owner = ViewerChrome()
    owner.walk(window)
    qt.QApplication.instance().installEventFilter(owner)
    return owner
