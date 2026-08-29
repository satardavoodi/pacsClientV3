"""Qt dialogs for configuring Legion Consult MRI series."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate

from .models import SeriesSelectionPlan
from .series_selection import (
    SelectionError,
    build_selection_plan,
    default_candidate_for_role,
    is_eligible_diagnostic_mr,
    series_key,
)


_STYLE = """
QDialog { background: #1a202c; }
QLabel, QCheckBox { color: #f7fafc; font-size: 12px; }
QLabel#secondary { color: #9ca3af; }
QLabel#error { color: #fc8181; }
QComboBox, QListWidget {
    background: #0f1419; color: #f7fafc; border: 1px solid #2d3748;
    border-radius: 5px; padding: 5px;
}
QPushButton {
    background: #1a202c; color: #f7fafc; border: 1px solid #2d3748;
    border-radius: 4px; padding: 6px 16px;
}
QPushButton:hover { background: #2d3748; }
"""


def _series_label(candidate: SeriesCandidate) -> str:
    description = candidate.series_description or candidate.protocol_name or "No description"
    details = [str(candidate.plane or "unknown plane")]
    if candidate.slice_count:
        details.append(f"{candidate.slice_count} images")
    return f"Series {candidate.series_number} — {description} ({', '.join(details)})"


class SeriesSelectionDialog(QDialog):
    """Collect mandatory and optional series while showing the input size."""

    def __init__(
        self,
        *,
        study_uid: str,
        candidates: list[SeriesCandidate],
        source: SeriesCandidate,
        parent=None,
    ):
        super().__init__(parent)
        self._study_uid = study_uid
        self._candidates = [candidate for candidate in candidates if is_eligible_diagnostic_mr(candidate)]
        self._source = source
        self._plan: SeriesSelectionPlan | None = None

        self.setWindowTitle("Legion Consult — Select MRI Series")
        self.setModal(True)
        self.resize(700, 570)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        explanation = QLabel(
            "The source series, one T1 series, and one T2 series are required. "
            "Choose only additional series that may help the consultation to control AI cost."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        source_label = QLabel(_series_label(source))
        source_label.setWordWrap(True)
        form.addRow("Source series:", source_label)
        self.t1_combo = QComboBox()
        self.t2_combo = QComboBox()
        self._fill_combo(self.t1_combo, default_candidate_for_role(self._candidates, "t1", source))
        self._fill_combo(self.t2_combo, default_candidate_for_role(self._candidates, "t2", source))
        form.addRow("Required T1:", self.t1_combo)
        form.addRow("Required T2:", self.t2_combo)
        layout.addLayout(form)

        optional_label = QLabel("Optional diagnostic series")
        layout.addWidget(optional_label)
        self.optional_list = QListWidget()
        for candidate in self._candidates:
            item = QListWidgetItem(_series_label(candidate))
            item.setData(Qt.UserRole, series_key(candidate))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.optional_list.addItem(item)
        layout.addWidget(self.optional_list, 1)

        self.select_all = QCheckBox("Include all eligible diagnostic series")
        layout.addWidget(self.select_all)
        note = QLabel(
            "Localizers, scouts, reports, and screen captures are excluded. "
            "No images are sent during this configuration step."
        )
        note.setObjectName("secondary")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.estimate = QLabel()
        self.estimate.setObjectName("secondary")
        layout.addWidget(self.estimate)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.t1_combo.currentIndexChanged.connect(self._refresh)
        self.t2_combo.currentIndexChanged.connect(self._refresh)
        self.optional_list.itemChanged.connect(self._refresh)
        self.select_all.toggled.connect(self._refresh)
        self._refresh()

    def _fill_combo(self, combo: QComboBox, suggestion: SeriesCandidate | None) -> None:
        combo.addItem("Select a series", None)
        suggested_index = 0
        for candidate in self._candidates:
            combo.addItem(_series_label(candidate), candidate)
            if candidate is suggestion:
                suggested_index = combo.count() - 1
        combo.setCurrentIndex(suggested_index)

    def _optional_keys(self) -> list[str]:
        return [
            str(self.optional_list.item(index).data(Qt.UserRole))
            for index in range(self.optional_list.count())
            if self.optional_list.item(index).checkState() == Qt.Checked
        ]

    def _current_plan(self) -> SeriesSelectionPlan:
        return build_selection_plan(
            study_uid=self._study_uid,
            candidates=self._candidates,
            source=self._source,
            t1=self.t1_combo.currentData(),
            t2=self.t2_combo.currentData(),
            optional_keys=self._optional_keys(),
            select_all=self.select_all.isChecked(),
        )

    def _refresh(self, *_args) -> None:
        self.optional_list.setEnabled(not self.select_all.isChecked())
        try:
            plan = self._current_plan()
        except SelectionError as exc:
            self.estimate.setText("Complete the required T1 and T2 assignments.")
            self.error.setText(str(exc))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self.error.clear()
        self.estimate.setText(
            f"Selected input: {len(plan.selected_series_keys)} series, "
            f"approximately {plan.estimated_image_count} images."
        )
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    def _validate_and_accept(self) -> None:
        try:
            self._plan = self._current_plan()
        except SelectionError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def selection_plan(self) -> SeriesSelectionPlan | None:
        if self.exec() != QDialog.Accepted:
            return None
        return self._plan
