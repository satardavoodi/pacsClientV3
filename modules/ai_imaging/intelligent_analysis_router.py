"""Route the shared Intelligent AI Analyze action by study modality."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QPushButton


class IntelligentAnalysisRouter(QObject):
    """Select a modality controller while keeping work out of the UI class."""

    def __init__(self, owner, *, mammography, dx_wrist):
        super().__init__(owner)
        self._owner = owner
        self._mammography = mammography
        self._dx_wrist = dx_wrist
        self._button = None

    def bind_button(self, button: QPushButton) -> None:
        self._button = button
        button.clicked.connect(self.start)
        self.refresh_visibility()

    def refresh_visibility(self) -> None:
        if self._button is not None:
            self._button.setVisible(self._modality() in {"MG", "DX"})

    def start(self) -> None:
        from PacsClient.pacs.patient_tab.utils import show_message

        modality = self._modality()
        if modality == "DX":
            self._dx_wrist.start()
            return
        if modality == "MG":
            self._mammography.start()
            return
        show_message(
            "Intelligent AI Analyze is only available for mammography and DX wrist studies."
        )

    def _modality(self) -> str:
        return str(self._owner.detect_modality() or "").upper()
