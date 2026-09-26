"""Local presentation adapter; no patient access, scene changes or window promotion."""
import qt
import re
import importlib.util
from pathlib import Path

# Load immutable styling only; never import workstation Qt/DB packages in Slicer.
_numeric_spec = importlib.util.spec_from_file_location(
    'aipacs_numeric_controls', Path(__file__).resolve().parents[4] / 'Qss' / 'numeric_controls.py')
_numeric_style = importlib.util.module_from_spec(_numeric_spec)
_numeric_spec.loader.exec_module(_numeric_style)

WINDOW_TITLE = 'AI-PACS Advanced Viewer v3.6.8'

# This viewer is entered with a selected series. Specialized pipelines remain
# owned by Eagle Eye; retain their modules for programmatic use, not discovery.
VIEWER_MODULES = ('NewMPR2MPR', 'Data', 'Volumes', 'Markups', 'Models',
                  'VolumeRendering', 'SegmentEditor', 'Segmentations')

PANEL_LABELS = {
    'NewMPR2MPR': ('Home / MPR', 'Multiplanar image review'),
    'Data': ('Scene Data', 'Images and objects in this session'),
    'Volumes': ('Image Display', 'Window, level and image appearance'),
    'Markups': ('Measurements', 'Points, distances, angles and contours'),
    'Models': ('3D Surfaces', 'Surface visibility and appearance'),
    'VolumeRendering': ('3D Rendering', 'Volume appearance and rendering controls'),
    'SegmentEditor': ('Segmentation Editor', 'Create and refine regions on the source image'),
    'Segmentations': ('Segmentation Manager', 'Organize regions and their display'),
}

PANEL_STYLE = '''
QWidget { color:#deebf5; font-size:12px; }
QLabel { color:#deebf5; background:transparent; }
QFrame#aipacsPanelHeader { background:#18334c; border:1px solid #315974;
    border-left:3px solid #68cfe4; border-radius:7px; }
QLabel#aipacsPanelBrand { color:#75d5e8; font-size:10px; font-weight:600; }
QLabel#aipacsPanelTitle { color:#f3f8ff; font-size:17px; font-weight:600; }
QLabel#aipacsPanelCaption { color:#b2c9db; font-size:11px; }
QPushButton, QToolButton { background:#203b50; color:#e7f3fb;
    border:1px solid #3b6079; border-radius:5px; padding:5px; }
QPushButton:hover, QToolButton:hover { background:#2a526a; border-color:#76cee1; }
QPushButton:checked, QToolButton:checked { background:#28647c; border-color:#83deec; }
QPushButton:disabled, QToolButton:disabled { color:#8b9cac; background:#1c2b37; border-color:#354653; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#132737; color:#eff7ff;
    border:1px solid #416079; border-radius:4px; padding:3px; min-height:20px; }
QTreeView, QTableView, QListView { background:#132534; alternate-background-color:#1a3042;
    color:#e6f2fc; border:1px solid #344f66; border-radius:5px;
    selection-background-color:#285d78; selection-color:#ffffff; }
QHeaderView::section { background:#203b50; color:#bed9e9; padding:5px; border:0; }
QTabBar::tab { background:#1b3042; color:#bed2e2; padding:6px 9px; }
QTabBar::tab:selected { background:#28526a; color:#ffffff; }
ctkCollapsibleButton { color:#a5dfec; background:#1b3347; border:0; padding:5px; }
QCheckBox { color:#e0edf7; spacing:6px; }
QCheckBox::indicator { width:14px; height:14px; border:1px solid #78a2ba; border-radius:3px; background:#142737; }
QCheckBox::indicator:checked { background:#65c8dd; border:2px solid #a8ebf6; }
'''

# Original, compact line symbols. Render from memory; no icon-file I/O on the UI thread.
SYMBOLS = {
    'brand': '<path d="m6 26 10-20 10 20M10 19h12"/>',
    'save': '<path d="M7 6h15l4 4v17H6V6ZM11 6v8h10V6M11 27v-8h10v8"/>',
    'bundle': '<rect x="6" y="9" width="20" height="18" rx="2"/><path d="M5 9h22V5H5ZM12 15h8M16 15v7"/>',
    'markups': '<path d="M9 23 16 10 25 19M9 23l16-4"/><circle cx="9" cy="23" r="2"/><circle cx="16" cy="10" r="2"/><circle cx="25" cy="19" r="2"/>',
    'models': '<path d="m16 6 10 6v12l-10 5-10-5V12ZM6 12l10 6 10-6M16 18v11"/>',
    'segmenteditor': '<path d="M7 8h12M7 8v18h18v-9M12 21l2-6 10-9 4 4-10 9Z"/>',
    'segmentations': '<path d="M6 12 16 6l10 6-10 6ZM6 18l10 6 10-6M6 24l10 6 10-6"/>',
    'volumerendering': '<path d="M6 12 16 6l10 6v12l-10 5-10-5ZM6 12l10 6 10-6M16 18v11"/><circle cx="16" cy="14" r="3"/>',
    'volumes': '<path d="M8 7h16v20H8ZM8 13h16M8 20h16"/>',
    'data': '<path d="M5 10h9l3 3h10v14H5ZM5 10V7h10l3 3"/>',
    'dicom': '<path d="M7 6h18v22H7ZM12 17h8M16 13v8"/>',
    'transforms': '<path d="M5 16h22M16 5v22M23 12l4 4-4 4M12 9l4-4 4 4"/>',
    'home': '<path d="m5 15 11-9 11 9M9 13v14h14V13M14 27v-8h4v8"/>',
    'search': '<circle cx="14" cy="14" r="7"/><path d="m19 19 8 8"/>',
    'previous': '<path d="m19 7-9 9 9 9"/>',
    'next': '<path d="m13 7 9 9-9 9"/>',
    'history': '<path d="M7 12a10 10 0 1 1-1 9M6 6v7h7M16 10v7l5 3"/>',
    'tools': '<rect x="6" y="6" width="8" height="8" rx="2"/><rect x="19" y="6" width="8" height="8" rx="2"/><rect x="6" y="19" width="8" height="8" rx="2"/><path d="M19 23h8M23 19v8"/>',
    'line': '<path d="m7 25 18-18"/><circle cx="7" cy="25" r="2"/><circle cx="25" cy="7" r="2"/>',
    'angle': '<path d="m9 6-3 20h22M9 17a9 9 0 0 1 7 9"/>',
    'curve': '<path d="M5 25C8 3 23 30 27 7"/><circle cx="5" cy="25" r="2"/><circle cx="27" cy="7" r="2"/>',
    'plane': '<path d="m4 23 7-15 17 1-7 15Z"/>',
    'roi': '<rect x="7" y="7" width="18" height="18" rx="2"/><path d="M3 11V3h8M21 29h8v-8"/>',
    'pointlist': '<circle cx="9" cy="8" r="2"/><circle cx="9" cy="16" r="2"/><circle cx="9" cy="24" r="2"/><path d="M16 8h10M16 16h10M16 24h10"/>',
    'closedcurve': '<path d="M8 7C24 2 29 18 23 25S2 26 6 16Z"/>',
}


def value(obj, name):
    result = getattr(obj, name)
    return result() if callable(result) else result


def symbol_name(name):
    key = ''.join(c for c in str(name).lower() if c.isalnum())
    if key in SYMBOLS:
        return key
    if 'dicom' in key:
        return 'dicom'
    if 'segment' in key or 'lumbar' in key:
        return 'segmentations'
    return 'tools'


def module_icon(name):
    key = symbol_name(name)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
           '<rect x="1" y="1" width="30" height="30" rx="7" fill="#172c42"/>'
           '<g fill="none" stroke="#78d9ef" stroke-width="1.8" stroke-linecap="round" '
           'stroke-linejoin="round">' + SYMBOLS[key] + '</g></svg>')
    pixmap = qt.QPixmap()
    if not pixmap.loadFromData(qt.QByteArray(svg.encode('utf-8')), 'SVG'):
        raise RuntimeError('Analysis icon renderer is unavailable')
    return qt.QIcon(pixmap)


def decorate_menu(menu):
    """Mutate only presentation: retain QAction identity, data, state and connections."""
    for action in value(menu, 'actions'):
        if value(action, 'isSeparator'):
            continue
        child = value(action, 'menu')
        if child:
            decorate_menu(child)
        else:
            key = value(action, 'data') or value(action, 'text')
            action.setIcon(module_icon(key))


def curate_module_menu(menu):
    """Expose installed viewer tools using their original module actions."""
    available = {}

    def collect(current):
        for action in value(current, 'actions'):
            child = value(action, 'menu')
            if child:
                collect(child)
            elif not value(action, 'isSeparator'):
                available[str(value(action, 'data'))] = action

    collect(menu)
    for action in value(menu, 'actions'):
        action.setVisible(False)
    for name in VIEWER_MODULES:
        action = available.get(name)
        if action is None:
            continue
        # qSlicerModulesMenu disconnects native routing on ActionRemoved.
        # Keep existing root actions attached; share nested tools without removal.
        if action not in value(menu, 'actions'):
            menu.addAction(action)
        action.setVisible(True)
        action.setText(PANEL_LABELS[name][0])
        if name == 'NewMPR2MPR':
            action.setText('Home / MPR')
            action.setIcon(module_icon('home'))
        else:
            action.setIcon(module_icon(name))


def fit_geometry(screen, requested=None):
    sx, sy, sw, sh = map(int, screen)
    # The request identifies the monitor; it must not expand the default window.
    width, height = max(1, int(sw * .70)), max(1, int(sh * .70))
    return (sx + (sw - width) // 2, sy + (sh - height) // 2, width, height)


def place_window(window, requested=None):
    """Use the request's monitor, including negative origins and taskbar offsets."""
    app = qt.QApplication.instance()
    screens = value(app, 'screens')
    screen = None
    if requested:
        point = qt.QPoint(int(requested[0] + requested[2] / 2), int(requested[1] + requested[3] / 2))
        screen = next((s for s in screens if value(s, 'geometry').contains(point)), None)
    if screen is None:
        screen = value(window, 'screen') if hasattr(window, 'screen') else value(app, 'primaryScreen')
    rect = value(screen, 'availableGeometry')
    available = tuple(value(rect, k) for k in ('x', 'y', 'width', 'height'))
    window.setGeometry(*fit_geometry(available, requested))


def descendants(root):
    for child in value(root, 'children'):
        yield child
        yield from descendants(child)


def style_panel(panel, module_name):
    """Style only the selected module widget, never the image viewport or scene."""
    if module_name not in PANEL_LABELS or panel is None:
        return
    layout = value(panel, 'layout')
    if layout is None:
        return
    panel.setStyleSheet(PANEL_STYLE + _numeric_style.numeric_control_style())
    if not hasattr(layout, 'insertWidget') and not layout.inherits('QGridLayout'):
        return
    children = list(descendants(panel))
    if not any(value(o, 'objectName') == 'aipacsPanelHeader' for o in children):
        header = qt.QFrame(panel)
        header.setObjectName('aipacsPanelHeader')
        header_layout = qt.QVBoxLayout(header)
        header_layout.setContentsMargins(10, 7, 10, 7)
        header_layout.setSpacing(2)
        title, caption = PANEL_LABELS[module_name]
        for name, text in (('Brand', 'AI-PACS  /  ADVANCED ANALYSIS'),
                           ('Title', title), ('Caption', caption)):
            label = qt.QLabel(text, header)
            label.setObjectName('aipacsPanel' + name)
            label.setWordWrap(True)
            header_layout.addWidget(label)
        if hasattr(layout, 'insertWidget'):
            layout.insertWidget(0, header)
        else:
            # Move the intact grid to a body widget. No output-pointer Qt APIs,
            # item removal, row renumbering or loss of stretch/span information.
            body = qt.QWidget(panel)
            body.setLayout(layout)
            outer = qt.QVBoxLayout(panel)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(6)
            outer.addWidget(header)
            outer.addWidget(body)
            body.show()
        header.show()
    panel.setStyleSheet(PANEL_STYLE + _numeric_style.numeric_control_style())
    for obj in children:
        if obj.inherits('QAbstractButton') and module_name == 'Markups':
            key = ''.join(c for c in str(value(obj, 'text')).lower() if c.isalnum())
            if key in ('line', 'angle', 'curve', 'closedcurve', 'plane', 'roi', 'pointlist'):
                obj.setIcon(module_icon(key))
        if value(obj, 'objectName') == 'mprHeader':
            obj.hide()  # Replaced by the common panel heading.


def connect(obj, signal, callback):
    bound = getattr(obj, signal.split('(')[0], None)
    if hasattr(bound, 'connect'):
        bound.connect(callback)
    else:
        obj.connect(signal, callback)


def correct_startup_notice(widget):
    """Correct only the known welcome line; retain disclaimer and consent state."""
    if not widget.inherits('QMessageBox'):
        return
    text = str(value(widget, 'text'))
    if 'This software is not intended for clinical use.' not in text:
        return
    corrected, count = re.subn(
        r'^Thank you for using AI-PACS Advanced Viewer [0-9][^!<\n]*!',
        'Welcome to ' + WINDOW_TITLE + '.', text, count=1)
    if count:
        widget.setText(corrected)
        widget.setWindowTitle(WINDOW_TITLE)


class StartupNoticeFilter(qt.QObject):
    def __init__(self, window):
        super().__init__()
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == qt.QEvent.Show:
            correct_startup_notice(obj)
            brand_save_dialog(obj)
            if obj == self.window or (obj.inherits('QWidget') and obj.window() == self.window):
                lock_chrome_widget(obj, self.window)
        if event.type() == qt.QEvent.ContextMenu and (
                obj == self.window or (obj.inherits('QToolBar') and obj.parent() == self.window)):
            return True
        return False


def lock_chrome_widget(widget, window):
    """Keep native actions connected while removing toolbar customization."""
    if widget.parent() != window:
        return
    if widget.inherits('QMenuBar'):
        widget.hide()
    elif widget.inherits('QToolBar'):
        widget.setMovable(False)
        widget.setFloatable(False)
        widget.setContextMenuPolicy(qt.Qt.PreventContextMenu)
        action = value(widget, 'toggleViewAction')
        action.setEnabled(False)
        action.setVisible(False)
        if value(widget, 'objectName') != 'ModuleSelectorToolBar':
            widget.hide()


def brand_save_dialog(widget):
    """Retain native save logic, destinations, statuses and confirmation behavior."""
    if value(widget, 'objectName') != 'qSlicerSaveDataDialog' or not widget.inherits('QDialog'):
        return
    widget.setWindowTitle('AI-PACS | Save Scene and Data')
    widget.setWindowIcon(module_icon('brand'))
    widget.setStyleSheet(PANEL_STYLE)
    icons = {'SelectSceneDataButton': 'save', 'SelectDataButton': 'data',
             'DataBundleButton': 'bundle'}
    for child in descendants(widget):
        name = value(child, 'objectName')
        if name in icons and child.inherits('QAbstractButton'):
            child.setIcon(module_icon(icons[name]))
        elif child.inherits('QDialogButtonBox'):
            for button in value(child, 'buttons'):
                role = child.standardButton(button)
                if role == qt.QDialogButtonBox.Save:
                    button.setIcon(module_icon('save'))
                elif role == qt.QDialogButtonBox.Cancel:
                    button.setIcon(qt.QIcon())


class Presentation:
    def __init__(self, window):
        self.window = window
        self.menus = []
        self.icons = {key: module_icon(key) for key in SYMBOLS}
        self.notice_filter = StartupNoticeFilter(window)
        app = qt.QApplication.instance()
        app.installEventFilter(self.notice_filter)
        for widget in value(app, 'topLevelWidgets'):
            correct_startup_notice(widget)
            brand_save_dialog(widget)
        for widget in descendants(window):
            lock_chrome_widget(widget, window)
        window.setWindowTitle(WINDOW_TITLE)
        # Set display name too: old native runtimes otherwise append their old title.
        qt.QApplication.instance().setApplicationDisplayName(WINDOW_TITLE)
        toolbar = next((o for o in descendants(window)
                        if value(o, 'objectName') == 'ModuleSelectorToolBar'), None)
        if toolbar:
            toolbar.setStyleSheet('QToolBar { background:#122238; border:0; padding:4px; }'
                                 'QLabel { color:#9dddec; font-weight:600; padding:0 6px; }'
                                 'QToolButton { color:#e5eef8; padding:5px; border-radius:5px; }'
                                 'QToolButton:hover { background:#25445f; }')
            toolbar.setIconSize(qt.QSize(24, 24))
            for obj in descendants(toolbar):
                if obj.inherits('QLabel') and 'Modules' in str(value(obj, 'text')):
                    obj.setText('AI-PACS / Analysis')
                if obj.inherits('QMenu'):
                    self.menus.append(obj)
                    obj.setStyleSheet('QMenu { background:#132337; color:#edf4fc; border:1px solid #36516d; }'
                                     'QMenu::item { padding:7px 28px 7px 10px; }'
                                     'QMenu::item:selected { background:#26516b; }'
                                     'QMenu::item:disabled { color:#8293a5; }')
                    decorate = curate_module_menu if obj.inherits('qSlicerModulesMenu') else decorate_menu
                    connect(obj, 'aboutToShow()', lambda menu=obj, decorate=decorate: decorate(menu))
                    decorate(obj)
                if obj.inherits('QToolButton'):
                    text = str(value(obj, 'text')).lower()
                    tip = str(value(obj, 'toolTip')).lower()
                    key = next((k for k in ('previous', 'next', 'history') if k in text), None)
                    if not key and ('finder' in tip or 'find' in text):
                        key = 'search'
                        # The stock finder bypasses the curated module list.
                        obj.hide()
                        for action in value(toolbar, 'actions'):
                            if toolbar.widgetForAction(action) == obj:
                                action.setVisible(False)
                    if key:
                        obj.setIcon(self.icons[key])
            if hasattr(toolbar, 'moduleSelected') or hasattr(toolbar, 'modulesMenu'):
                connect(toolbar, 'moduleSelected(QString)', self.refresh_header)
                connect(toolbar, 'moduleSelected(QString)', self.schedule_panel)
                self.schedule_panel('NewMPR2MPR')
        self.refresh_header()

    def schedule_panel(self, name):
        if str(name) in PANEL_LABELS:
            qt.QTimer.singleShot(0, lambda: self.apply_panel(str(name)))

    def apply_panel(self, name):
        import slicer
        module = slicer.app.moduleManager().module(name)
        if module:
            style_panel(module.widgetRepresentation(), name)

    def refresh_header(self, *unused):
        for obj in descendants(self.window):
            name = value(obj, 'objectName')
            if name == 'mprTitle':
                obj.setText('MPR')
            elif name == 'mprSubtitle':
                obj.setText('Multiplanar views')
            elif name == 'mprHeader':
                obj.setStyleSheet('QFrame#mprHeader { background:#18334c; border-radius:6px; }'
                                 'QLabel { color:#e5f3ff; }')


# PythonQt C++ wrappers forbid arbitrary Python attributes. Keep the adapter
# on this Python module for the lifetime of the process's single main window.
_presentation = None


def install(window):
    global _presentation
    if window is None:
        return None
    if _presentation is None or _presentation.window is not window:
        _presentation = Presentation(window)
    return _presentation
