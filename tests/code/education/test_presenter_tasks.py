"""Resource checks, worker ownership and presentation shell using synthetic data."""
import sys
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QListWidget, QListWidgetItem

from modules.education.authoring_tasks import CourseAssetCopyTask, presentation_issues
from modules.education.presentation_window import CoursePresentationWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def settle(app, predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def test_preflight_reports_missing_empty_and_external_resources(tmp_path, monkeypatch):
    from modules.education import presentation_conversion
    monkeypatch.setattr(presentation_conversion, "find_libreoffice", lambda: None)
    deck = tmp_path / "example.pptx"
    deck.write_bytes(b"synthetic")
    course = {"slides": [{"content": [
        {"content_type": "text", "content_data": {"text": " "}},
        {"content_type": "image", "content_data": {"path": str(tmp_path / "absent.png")}},
        {"content_type": "presentation", "content_data": {"path": str(deck)}},
    ]}, {"content": []}]}
    issues = presentation_issues(course)
    assert len(issues) == 4
    assert "empty" in issues[0]
    assert "unavailable" in issues[1]
    assert "external application" in issues[2]
    assert all(str(tmp_path) not in issue for issue in issues)


def test_asset_copy_runs_outside_gui_thread(app, monkeypatch):
    from modules.education import course_database
    called = []
    def copy(source, pk):
        called.append(QThread.currentThread() == app.thread())
        return "synthetic-copy.png"
    monkeypatch.setattr(course_database, "save_course_asset", copy)
    worker = CourseAssetCopyTask("synthetic.png", 7)
    worker.start()
    assert worker.wait(4000)
    assert called == [False]
    assert worker.result == "synthetic-copy.png" and not worker.error


class FakeViewer(QWidget):
    def __init__(self, course, parent=None):
        super().__init__(parent)
        self.slides = course["slides"]
        self.slides_list = QListWidget(self)
        self.items_list = QListWidget(self)
        self.seen = []
        self.closed = False
        self._set_current_slide(0)

    def _set_current_slide(self, index):
        self.current_slide_index = index
        self.items_list.clear()
        for payload in self.slides[index]["content"]:
            item = QListWidgetItem("Synthetic")
            item.setData(Qt.UserRole, payload)
            self.items_list.addItem(item)
        self.items_list.setCurrentRow(0)
        self._on_item_clicked(self.items_list.item(0))

    def _on_item_clicked(self, item):
        self.seen.append(item.data(Qt.UserRole)["content_data"]["text"])

    def closeEvent(self, event):
        self.closed = True
        super().closeEvent(event)


def test_presenter_visits_resources_and_restores_window(app, monkeypatch):
    monkeypatch.setitem(sys.modules, "modules.education.educational_patient_viewer_widget",
                        SimpleNamespace(EducationalCourseViewerWidget=FakeViewer))
    item = lambda text: {"content_type": "text", "content_data": {"text": text}}
    window = CoursePresentationWindow({"slides": [{"content": [item("A"), item("B")]}, {"content": [item("C")]}]})
    window.show()
    settle(app, lambda: window._preflight is None)
    assert window.start_button.isEnabled()
    window._start()
    viewer = window.viewer
    window._step(1)
    window._step(1)
    assert viewer.seen == ["A", "B", "C"]
    window._step(-1)
    assert viewer.seen[-1] == "B"
    window._toggle_fullscreen()
    assert window.isFullScreen()
    window._escape()
    assert not window.isFullScreen()
    window.close()
    assert viewer.closed


def test_close_during_preflight_retires_worker(app, monkeypatch):
    from modules.education import authoring_tasks
    original = authoring_tasks.presentation_issues
    def delayed(course):
        QThread.msleep(50)
        return original(course)
    monkeypatch.setattr(authoring_tasks, "presentation_issues", delayed)
    window = CoursePresentationWindow({"slides": []})
    window.show()
    worker = window._preflight
    window.close()
    assert window._close_requested
    assert worker.wait(4000)
    settle(app, lambda: window._preflight is None)
