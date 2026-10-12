"""Shared AI connection page using the original settings owners."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QGroupBox

class AIConnectionSettingsWidget(QWidget):
    def __init__(self, sections, parent=None, *, server=False):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        title = QLabel('AI Connections')
        title.setStyleSheet('font-size:18px; font-weight:700;')
        layout.addWidget(title)
        note = QLabel('Eagle AI Brain is the shared external AI connection for EchoMind, '
                      'Eagle Eye LLM analysis, Agent / Secretary and CRM. Local imaging models run locally. '
                      'Desktop account settings and the running service private configuration are separate; '
                      'service changes require a controlled activation.' if server else
                      'Company AI uses one authenticated Eagle Eye Server connection. '
                      'Personal API mode requires your own credentials and explicit prompts. '
                      'Agent Gateway pairing controls access to this workstation.')
        note.setWordWrap(True)
        layout.addWidget(note)
        for label, page in sections:
            group = QGroupBox('Mobile and workstation access' if label == 'Agent' else label)
            group_layout = QVBoxLayout(group)
            group_layout.addWidget(page)
            page.show()
            layout.addWidget(group)
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)
