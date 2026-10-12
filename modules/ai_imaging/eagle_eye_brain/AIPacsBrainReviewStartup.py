"""Early Slicer module: conceal the generic window until brain review is ready.

Slicer instantiates additional modules before constructing/showing its main
window; --python-script runs after that first show and is too late on its own.
"""
from slicer.ScriptedLoadableModule import ScriptedLoadableModule


def install_guard(qt, slicer):
    class VisibilityGuard(qt.QObject):
        def __init__(self):
            super().__init__()
            self.ready = False

        def eventFilter(self, watched, event):
            if (not self.ready and event.type() in (qt.QEvent.Polish, qt.QEvent.Show)
                    and watched.inherits('qSlicerMainWindow')):
                # Opacity alone leaves an invisible application in the taskbar.
                # Polish precedes native exposure; prepare off-desktop instead.
                watched.setAttribute(qt.Qt.WA_DontShowOnScreen, True)
                watched.setWindowOpacity(0.0)
            return False

        def release(self, window):
            self.ready = True
            slicer.app.removeEventFilter(self)
            window.hide()
            window.setAttribute(qt.Qt.WA_DontShowOnScreen, False)
            window.setWindowOpacity(1.0)
            window.show()

    guard = VisibilityGuard()
    slicer._aipacsBrainVisibilityGuard = guard
    slicer.app.installEventFilter(guard)
    return guard


class AIPacsBrainReviewStartup(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = 'AI-PACS Brain Review Startup'
        parent.categories = ['Developer Tools']
        parent.hidden = True
        import os
        if os.environ.get('AIPACS_MANUAL_REVIEW'):
            import qt
            import slicer
            install_guard(qt, slicer)
