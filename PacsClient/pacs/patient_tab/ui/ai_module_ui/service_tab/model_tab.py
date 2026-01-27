import sys
from PySide6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QWidget, QFileDialog, QApplication,
    QHBoxLayout, QVBoxLayout, QPushButton, QLabel
)
from . import AbstractTab


class ModelTrainingTab(AbstractTab):
    def __init__(self):
        super().__init__()