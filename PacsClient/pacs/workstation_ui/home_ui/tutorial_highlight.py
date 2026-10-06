"""Transient mouse-transparent tutorial marker, positioned on its live target."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

class TutorialHighlight(QWidget):
    def __init__(self, target):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(0, 0, min(64, target.width()), min(64, target.height()))
        self._phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60)
        QTimer.singleShot(8000, self.close)
    def _tick(self):
        self._phase = (self._phase + 1) % 20
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#ef5350'), 3))
        inset = 5 + abs(10-self._phase)/2
        painter.drawEllipse(self.rect().adjusted(int(inset), int(inset), -int(inset), -int(inset)))
    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
