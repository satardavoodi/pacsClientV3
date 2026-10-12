"""Move the existing teaching media surface to an audience display, reversibly."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QStackedLayout, QWidget


class AudiencePresentation(QWidget):
    finished = Signal()
    step = Signal(int)

    def __init__(self, surface, home_layout, owner):
        super().__init__(owner, Qt.Window)
        self.setWindowTitle('Course Presentation')
        self.setStyleSheet('background:#10283b;color:#eef5fc;')
        self.surface = surface
        self.home_layout = home_layout
        self.home_parent = surface.parentWidget()
        self.home_index = home_layout.indexOf(surface)
        self.screen_target = None
        self.active = False
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.message = QLabel('DICOM content is displayed in the workstation viewer.')
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.stack.addWidget(self.message)
        self.shortcuts = []
        for key, callback in [('Escape', self.close), ('Right', lambda: self.step.emit(1)),
                              ('PageDown', lambda: self.step.emit(1)),
                              ('Left', lambda: self.step.emit(-1)),
                              ('PageUp', lambda: self.step.emit(-1))]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    def start(self, screen):
        if self.active:
            return
        self.screen_target = screen
        self.active = True
        self.home_layout.removeWidget(self.surface)
        self.stack.addWidget(self.surface)
        self.stack.setCurrentWidget(self.surface)
        self.winId()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        QApplication.instance().screenRemoved.connect(self._screen_removed)
        self.showFullScreen()
        self.setFocus()

    def set_media_active(self, active):
        self.stack.setCurrentWidget(self.surface if active else self.message)

    def _screen_removed(self, screen):
        if screen is self.screen_target:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Space):
            self.step.emit(1)
        elif event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.step.emit(-1)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.active:
            self.active = False
            QApplication.instance().screenRemoved.disconnect(self._screen_removed)
            self.stack.removeWidget(self.surface)
            self.surface.setParent(self.home_parent)
            self.home_layout.insertWidget(self.home_index, self.surface, 1)
            self.surface.show()
            self.finished.emit()
        super().closeEvent(event)
