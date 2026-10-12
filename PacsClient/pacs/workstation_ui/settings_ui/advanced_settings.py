"""Reusable collapsed settings detail panel; values remain owned by their forms."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

class AdvancedSettingsPanel(QWidget):
    def __init__(self, title='Advanced settings', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton(title)
        self.toggle.setCheckable(True)
        self.toggle.setProperty('role', 'secondary')
        self.toggle.setToolTip('Show or hide details without changing saved values.')
        layout.addWidget(self.toggle)
        self.content = QWidget(self)
        QVBoxLayout(self.content).setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.content)
        self.content.hide()
        self.toggle.toggled.connect(self.content.setVisible)
