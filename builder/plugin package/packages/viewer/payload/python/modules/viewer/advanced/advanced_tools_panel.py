from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class AdvancedToolsPanel(QWidget):
    """Compatibility placeholder for the legacy advanced tools side panel."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Advanced Tools")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet("font-weight: 600; font-size: 14px;")

        description = QLabel(
            "The legacy advanced tools panel is not bundled in this build. "
            "Core viewer functionality remains available."
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch(1)
