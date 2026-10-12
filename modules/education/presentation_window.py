"""Presenter shell around the existing Education viewer, without reparenting it."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QApplication, QInputDialog

from modules.education.authoring_tasks import CoursePreflightTask


class AudienceViewerWindow(QMainWindow):
    """An audience host that returns the existing viewer on close."""
    def __init__(self, controller):
        super().__init__(controller, Qt.Window)
        self.controller = controller
        self.setWindowTitle("Course Presentation")
        self.escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.escape_shortcut.activated.connect(self.close)

    def closeEvent(self, event):
        self.controller._restore_single_screen()
        event.accept()


class CoursePresentationWindow(QMainWindow):
    def __init__(self, course, parent=None, auto_start=False):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(str(course.get("course_name") or "Course Presentation"))
        self.resize(640, 320)
        self.auto_start = auto_start
        self.audience_window = None
        self._footer_home = None
        self.course = course
        self.viewer = None
        self._close_requested = False
        self._shortcuts = []
        host = QWidget(self)
        self.layout = QVBoxLayout(host)
        self.setCentralWidget(host)
        self.navigation = QWidget()
        controls = QHBoxLayout(self.navigation)
        controls.setContentsMargins(0, 0, 0, 0)
        for text, callback in (("Previous (Page Up)", lambda: self._step(-1)),
                               ("Next (Page Down)", lambda: self._step(1)),
                               ("Full Screen (F11)", self._toggle_fullscreen),
                               ("Display Mode", self.choose_display_mode),
                               ("Close", self.close)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.layout.addWidget(self.navigation)
        self.navigation.hide()
        self.position = QLabel("Checking saved course and local resources...")
        self.layout.addWidget(self.position)
        self.check_results = QTextBrowser()
        self.check_results.setPlainText("Checking availability before the presentation. No content is uploaded.")
        self.layout.addWidget(self.check_results, 1)
        self.start_button = QPushButton("Start Presentation")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        self.layout.addWidget(self.start_button)
        for key, callback in (("PgDown", lambda: self._step(1)), ("PgUp", lambda: self._step(-1)),
                               ("F11", self._toggle_fullscreen), ("Esc", self._escape)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        self._preflight = CoursePreflightTask(course, self)
        self._preflight.finished.connect(self._checked)
        self._preflight.start()

    def _checked(self):
        task = self._preflight
        self._preflight = None
        issues = task.issues
        task.deleteLater()
        if self._close_requested:
            self.close()
            return
        message = "Local resource check complete."
        if issues:
            message += "\n\nReview before presenting:\n" + "\n".join(issues)
        else:
            message += "\nSaved slides and referenced resources are available."
        message += "\n\nThis check does not verify codecs, image quality or permission to show patient information."
        self.check_results.setPlainText(message)
        self.position.setText("Ready to preview" if not issues else "Review the resource check")
        self.start_button.setEnabled(any(s.get("content") for s in self.course.get("slides", [])))
        if self.auto_start and not issues and self.start_button.isEnabled():
            self._start()

    def _start(self):
        if self.viewer is not None:
            return
        from modules.education.educational_patient_viewer_widget import EducationalCourseViewerWidget
        try:
            self.viewer = EducationalCourseViewerWidget(self.course, parent=self.centralWidget())
        except Exception:
            self.check_results.setPlainText("Could not open the course viewer. Close this window and retry from the saved draft.")
            return
        self.check_results.hide()
        self.start_button.hide()
        self.layout.addWidget(self.viewer, 1)
        self.navigation.show()
        self.showMaximized()
        self.viewer.slides_list.currentRowChanged.connect(self._update_position)
        self.viewer.items_list.currentRowChanged.connect(self._update_position)
        self._update_position()

    def choose_display_mode(self):
        if self.viewer is None:
            return
        screens = QApplication.screens()
        current = self.screen() or QApplication.primaryScreen()
        targets = [screen for screen in screens if screen is not current]
        choices = ["Single monitor"] + [f"Two monitors: {screen.name()} ({i + 1})" for i, screen in enumerate(targets)]
        choice, accepted = QInputDialog.getItem(self, "Presentation Display", "Presentation mode", choices, 0, False)
        if accepted:
            index = choices.index(choice)
            self.present_on_screen(None if index == 0 else targets[index - 1])

    def present_on_screen(self, screen):
        if self.viewer is None:
            return
        self._restore_single_screen()
        if screen is None:
            self.showFullScreen()
            return
        self.showNormal()
        self.resize(900, 450)
        audience = AudienceViewerWindow(self)
        self.audience_window = audience
        # Keep the existing live viewer and its decoding domain; do not create a
        # second DICOM session. Navigation stays on the controller display.
        self.layout.removeWidget(self.viewer)
        footer = getattr(self.viewer, "education_footer", None)
        if footer is not None:
            home = footer.parentWidget().layout()
            self._footer_home = (home, home.indexOf(footer), footer.parentWidget())
            home.removeWidget(footer)
            self.layout.addWidget(footer, 1)
        audience.setCentralWidget(self.viewer)
        audience.winId()
        audience.windowHandle().setScreen(screen)
        audience.setGeometry(screen.geometry())
        QApplication.instance().screenRemoved.connect(self._screen_removed)
        audience.showFullScreen()

    def _screen_removed(self, screen):
        if self.audience_window is not None and self.audience_window.screen() is screen:
            self._restore_single_screen()

    def _restore_single_screen(self):
        audience = self.audience_window
        if audience is None:
            return
        self.audience_window = None
        QApplication.instance().screenRemoved.disconnect(self._screen_removed)
        audience.takeCentralWidget()
        if self._footer_home is not None:
            home, index, parent = self._footer_home
            footer = self.viewer.education_footer
            self.layout.removeWidget(footer)
            footer.setParent(parent)
            home.insertWidget(index, footer)
            self._footer_home = None
        self.layout.addWidget(self.viewer, 1)
        self.viewer.show()
        audience.hide()
        audience.deleteLater()
        self.showMaximized()

    def _step(self, direction):
        if self.viewer is None:
            return
        row = self.viewer.items_list.currentRow()
        target = row + direction
        if 0 <= target < self.viewer.items_list.count():
            item = self.viewer.items_list.item(target)
            if item.data(Qt.UserRole):
                self.viewer.items_list.setCurrentRow(target)
                self.viewer._on_item_clicked(item)
        else:
            index = self.viewer.current_slide_index + direction
            if 0 <= index < len(self.viewer.slides):
                self.viewer._set_current_slide(index)
                if direction < 0 and self.viewer.items_list.count():
                    last = self.viewer.items_list.count() - 1
                    self.viewer.items_list.setCurrentRow(last)
                    item = self.viewer.items_list.item(last)
                    if item.data(Qt.UserRole):
                        self.viewer._on_item_clicked(item)
        self._update_position()

    def _update_position(self, *_):
        if self.viewer is not None:
            self.position.setText(f"Slide {self.viewer.current_slide_index + 1} / {len(self.viewer.slides)}"
                                  f" - Resource {max(0, self.viewer.items_list.currentRow() + 1)} / {self.viewer.items_list.count()}")

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _escape(self):
        self._restore_single_screen()
        if self.isFullScreen():
            self.showNormal()

    def closeEvent(self, event):
        if self._preflight is not None:
            self._close_requested = True
            self.hide()
            event.ignore()
            return
        self._restore_single_screen()
        if self.viewer is not None and not self.viewer.close():
            event.ignore()
            return
        super().closeEvent(event)
