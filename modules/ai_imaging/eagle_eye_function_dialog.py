"""Eagle Eye function picker and active-viewer modality adapter."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .eagle_eye_function_catalog import function_options_for_modality


_STYLE = """
QDialog { background: #1a202c; }
QLabel { color: #f7fafc; font-size: 13px; }
QLabel#functionHint { color: #9ca3af; font-size: 12px; }
QListWidget {
    background: #0f1419; color: #f7fafc; border: 1px solid #2d3748;
    border-radius: 6px; padding: 4px; font-size: 13px;
}
QListWidget::item { padding: 10px 8px; border-radius: 4px; }
QListWidget::item:selected { background: #3182ce; color: #ffffff; }
QListWidget::item:disabled { color: #6b7280; }
QPushButton {
    background: #1a202c; color: #f7fafc; border: 1px solid #2d3748;
    border-radius: 4px; padding: 6px 16px; font-size: 12px;
}
QPushButton:hover { background: #2d3748; }
"""


def active_viewer_context(patient_widget: Any) -> dict[str, Any]:
    """Read the minimum non-PHI identity needed from the selected viewer."""
    selected = getattr(patient_widget, "selected_widget", None)
    vtk_widget = getattr(selected, "vtk_widget", selected)
    image_viewer = getattr(vtk_widget, "image_viewer", None)
    metadata = getattr(image_viewer, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    series = metadata.get("series") if isinstance(metadata.get("series"), dict) else {}
    study = metadata.get("study") if isinstance(metadata.get("study"), dict) else {}
    fixed = getattr(image_viewer, "metadata_fixed", None)
    if not isinstance(fixed, dict):
        fixed = getattr(patient_widget, "metadata_fixed", None)
    fixed = fixed if isinstance(fixed, dict) else {}
    pipeline = getattr(image_viewer, "pipeline", None)

    return {
        "selected_widget": selected,
        "vtk_widget": vtk_widget,
        "image_viewer": image_viewer,
        "modality": str(series.get("modality") or fixed.get("modality") or "").upper(),
        "study_uid": str(
            series.get("study_uid")
            or study.get("study_instance_uid")
            or metadata.get("study_uid")
            or fixed.get("study_uid")
            or getattr(patient_widget, "study_uid", "")
            or ""
        ),
        "series_uid": str(
            series.get("series_uid")
            or series.get("series_instance_uid")
            or getattr(pipeline, "_series_uid", "")
            or ""
        ),
        "series_number": str(series.get("series_number") or ""),
    }


class EagleEyeFunctionDialog(QDialog):
    """Ask which Eagle Eye function should run for the active series."""

    def __init__(self, modality: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Eagle Eye — Select Function")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        prompt = QLabel("Which Eagle Eye function would you like to use?")
        layout.addWidget(prompt)

        hint = QLabel("Legion Consult is currently limited to MRI studies.")
        hint.setObjectName("functionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _item: self._accept_if_enabled())
        layout.addWidget(self.list)

        first_enabled = None
        for option in function_options_for_modality(modality):
            text = option.label
            if option.reason:
                text = f"{text}\n{option.reason}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, option.key)
            if not option.enabled:
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            elif first_enabled is None:
                first_enabled = item
            self.list.addItem(item)
        if first_enabled is not None:
            self.list.setCurrentItem(first_enabled)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._accept_if_enabled)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.list.currentItemChanged.connect(self._sync_ok)
        self._sync_ok()

    def _selected_key(self) -> str | None:
        item = self.list.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return None
        return str(item.data(Qt.UserRole) or "") or None

    def _sync_ok(self, *_args) -> None:
        button = self.buttons.button(QDialogButtonBox.Ok)
        if button is not None:
            button.setEnabled(self._selected_key() is not None)

    def _accept_if_enabled(self) -> None:
        if self._selected_key() is not None:
            self.accept()

    def choice(self) -> str | None:
        if self.exec() != QDialog.Accepted:
            return None
        return self._selected_key()


def choose_eagle_eye_function(modality: str, parent=None) -> str | None:
    return EagleEyeFunctionDialog(modality, parent=parent).choice()
