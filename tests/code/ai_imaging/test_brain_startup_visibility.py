"""A brain review window is opaque only after preparation, including failure."""
import importlib
import sys
from types import ModuleType, SimpleNamespace


def test_early_guard_blocks_default_frame_then_releases_on_ready(monkeypatch):
    from PySide6 import QtCore, QtWidgets
    module = ModuleType('slicer.ScriptedLoadableModule')
    module.ScriptedLoadableModule = object
    monkeypatch.setitem(sys.modules, 'slicer.ScriptedLoadableModule', module)
    startup = importlib.import_module('modules.ai_imaging.eagle_eye_brain.AIPacsBrainReviewStartup')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    owner = SimpleNamespace(app=app)
    guard = startup.install_guard(SimpleNamespace(QObject=QtCore.QObject, QEvent=QtCore.QEvent, Qt=QtCore.Qt), owner)

    class ReviewWindow(QtWidgets.QMainWindow):
        def inherits(self, name):
            return name == 'qSlicerMainWindow' or super().inherits(name)

    window = ReviewWindow()
    # Polish occurs before the first native show; no event-loop polling is used.
    guard.eventFilter(window, QtCore.QEvent(QtCore.QEvent.Type.Polish))
    assert window.testAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
    assert window.windowOpacity() == 0
    guard.release(window)
    assert window.windowOpacity() == 1 and guard.ready
    assert not window.testAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.hide()
    guard.eventFilter(window, QtCore.QEvent(QtCore.QEvent.Type.Show))
    assert window.windowOpacity() == 1
    window.close()


def test_failure_releases_visibility_guard_before_error_dialog():
    from modules.ai_imaging.eagle_eye_brain.manual_slicer import show_review_failure
    events = []
    window = object()
    owner = SimpleNamespace(
        _aipacsBrainVisibilityGuard=SimpleNamespace(release=lambda w: events.append(('release', w))),
        util=SimpleNamespace(mainWindow=lambda: window, errorDisplay=lambda text: events.append(('error', text))))
    show_review_failure(owner)
    assert events[0] == ('release', window) and events[1][0] == 'error'


def test_both_installer_backends_include_physical_startup_module(monkeypatch):
    from pathlib import Path
    from builder.spec import spec_utils
    monkeypatch.setattr(spec_utils, 'common_app_datas', lambda: [])
    monkeypatch.setattr(spec_utils, 'collect_tree_datas', lambda rel: [(rel, str(Path(rel).parent))])
    import ast
    destination = 'modules/ai_imaging/eagle_eye_brain'
    filenames = ('AIPacsBrainReviewStartup.py', 'manual_slicer.py', 'slicer_worker.py')
    pyinstaller = spec_utils.app_a_datas()
    spec = ast.parse(Path('builder nuitka/AIPacs_nuitka.spec.py').read_text(encoding='utf-8-sig'))
    entries = next(node.value.elts for node in spec.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'OPTIONAL_DATA' for target in node.targets))
    nuitka = [ast.literal_eval(entry) for entry in entries if isinstance(entry, ast.Tuple)
              and all(isinstance(value, ast.Constant) for value in entry.elts)]
    for filename in filenames:
        source = destination + '/' + filename
        assert any(Path(src).as_posix() == source and Path(src).is_file()
                   and Path(dest).as_posix() == destination for src, dest in pyinstaller)
        assert (source, destination) in nuitka
    shared = 'modules/mpr/advanced_3d_slicer/slicer_custom_app/viewer_chrome.py'
    target = str(Path(shared).parent).replace('\\', '/')
    assert (shared, target) in nuitka
    assert any(Path(src).as_posix() == shared and Path(src).is_file()
               and Path(dest).as_posix() == target for src, dest in pyinstaller)
