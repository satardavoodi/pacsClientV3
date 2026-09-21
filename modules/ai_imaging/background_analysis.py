"""Nonmodal, owner-bound Eagle Eye progress and analysis windows."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QProgressBar
from shiboken6 import isValid


class BackgroundAnalysisDialog(QDialog):
    """Dismissing a running analysis hides its UI without cancelling its worker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.analysis_widget = None
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

    def bind_analysis(self, widget):
        self.analysis_widget = widget
        self.activity_status = QLabel(self)
        self.activity_status.setWordWrap(True)
        self.activity_bar = QProgressBar(self)
        self.activity_bar.setRange(0, 0)
        self.activity_bar.setAccessibleName('Analysis activity')
        self.layout().insertWidget(0, self.activity_status)
        self.layout().insertWidget(1, self.activity_bar)
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(200)
        self._activity_timer.timeout.connect(self._update_activity)
        self._activity_timer.start()
        self._update_activity()
        button = QPushButton('Hide window / return to PACS', self)
        button.setObjectName('eagleEyeBackgroundButton')
        button.setToolTip('This does not start analysis. Hide this window; reopen the same Eagle Eye function to see progress or results.')
        button.clicked.connect(self.close)
        self.layout().addWidget(button)

    def _update_activity(self):
        widget = self.analysis_widget
        if widget is None or not isValid(widget):
            self._activity_timer.stop()
            return
        busy = getattr(widget, '_future', None) is not None
        self.activity_bar.setVisible(busy)
        status = getattr(widget, 'status', None)
        self.activity_status.setText(status.text() if isinstance(status, QLabel)
                                     else ('Analysis in progress...' if busy else 'Ready'))
        from .analysis_progress import display_progress
        if busy:
            display_progress(self.activity_bar, self.activity_status,
                             getattr(widget, 'analysis_progress', None))

    def reject(self):
        widget = self.analysis_widget
        if widget is not None and isValid(widget):
            future = getattr(widget, '_future', None)
            kind = getattr(widget, '_future_kind', getattr(widget, '_kind', ''))
            # Pending selectors must not appear over a different patient's tab.
            # Actual computation/export retains its immutable study-bound inputs.
            if future is None or kind in ('series', 'demographics', 'scan', 'load'):
                widget._cancel.set()
        super().reject()


class BackgroundProgress(QDialog):
    """Compact server-job progress; closing it never stops the owned QThread."""

    @classmethod
    def show_overlay(cls, parent, title='', status='', subtitle=''):
        dialog = cls(parent)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setAttribute(Qt.WA_DeleteOnClose, False)
        dialog.resize(420, 160)
        layout = QVBoxLayout(dialog)
        text = QLabel(status, dialog)
        dialog.status_label = text
        text.setWordWrap(True)
        layout.addWidget(text)
        progress = QProgressBar(dialog)
        progress.setRange(0, 0)
        layout.addWidget(progress)
        note = QLabel('Analysis runs in the background. You can keep using PACS.', dialog)
        note.setWordWrap(True)
        layout.addWidget(note)
        button = QPushButton('Hide progress / return to PACS', dialog)
        button.clicked.connect(dialog.hide)
        layout.addWidget(button)
        dialog.show()
        return dialog

    def set_status(self, text):
        self.status_label.setText(text)

    @staticmethod
    def hide_overlay(dialog, fade_ms=0, delay_ms=0):
        def dispose():
            if dialog is not None and isValid(dialog):
                dialog.hide()
                dialog.deleteLater()
        if delay_ms:
            QTimer.singleShot(delay_ms, dispose)
        else:
            dispose()
