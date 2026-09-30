"""Presenter shell around the existing Education viewer, without reparenting it."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser

from modules.education.authoring_tasks import CoursePreflightTask


class CoursePresentationWindow(QMainWindow):
    def __init__(self, course, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(str(course.get("course_name") or "Course Presentation"))
        self.resize(1280, 800)
        self.course = course
        self.viewer = None
        self._close_requested = False
        self._shortcuts = []
        host = QWidget(self)
        self.layout = QVBoxLayout(host)
        self.setCentralWidget(host)
        controls = QHBoxLayout()
        for text, callback in (("Previous (Page Up)", lambda: self._step(-1)),
                               ("Next (Page Down)", lambda: self._step(1)),
                               ("Full Screen (F11)", self._toggle_fullscreen),
                               ("Close", self.close)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.layout.addLayout(controls)
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
        self.viewer.slides_list.currentRowChanged.connect(self._update_position)
        self.viewer.items_list.currentRowChanged.connect(self._update_position)
        self._update_position()

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
        if self.isFullScreen():
            self.showNormal()

    def closeEvent(self, event):
        if self._preflight is not None:
            self._close_requested = True
            self.hide()
            event.ignore()
            return
        if self.viewer is not None and not self.viewer.close():
            event.ignore()
            return
        super().closeEvent(event)
