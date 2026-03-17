from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget


class CaseOfDayViewerWidget(QWidget):
    """Wrapper that shows Case-of-Day metadata + the standard PatientWidget (loaded from a DICOM folder)."""

    def __init__(self, case_data: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.case_data = dict(case_data or {})
        dicom_folder = str(self.case_data.get("dicom_folder_path") or "").strip()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(78)
        header.setStyleSheet("QFrame { background-color: #0d1117; border-bottom: 1px solid #1e2530; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)

        title = QLabel("Case of the Day")
        font = QFont()
        font.setPointSize(16)
        font.setWeight(QFont.DemiBold)
        title.setFont(font)
        title.setStyleSheet("color: #f0f4f8;")
        header_layout.addWidget(title)
        header_layout.addStretch(1)

        diagnosis = QLabel(str(self.case_data.get("diagnosis") or ""))
        diagnosis.setStyleSheet("color: #d7dfeb; font-size: 12pt; font-weight: 700;")
        diagnosis.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        diagnosis.setWordWrap(True)
        header_layout.addWidget(diagnosis)

        meta = QLabel(
            f"{self.case_data.get('modality', '')} | {self.case_data.get('body_part', '')} | "
            f"Saved by: {self.case_data.get('saved_by', '')}"
        )
        meta.setStyleSheet("color: #9bb0c6; font-size: 10pt; padding: 6px 16px 10px 16px;")

        info = QFrame()
        info.setStyleSheet("QFrame { background-color: #0f141b; border-bottom: 1px solid #1e2530; }")
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(16, 8, 16, 10)
        info_layout.setSpacing(14)

        def _block(label: str, value: str) -> QWidget:
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)
            l.setSpacing(2)
            k = QLabel(label)
            k.setStyleSheet("color: #95a7bb; font-size: 9.5pt; font-weight: 700;")
            v = QLabel(value or "-")
            v.setStyleSheet("color: #d7dfeb; font-size: 10pt;")
            v.setWordWrap(True)
            l.addWidget(k)
            l.addWidget(v)
            return w

        info_layout.addWidget(_block("Protocol", str(self.case_data.get("protocol_details") or "")), 1)
        info_layout.addWidget(_block("Differential Dx", str(self.case_data.get("differential_diagnosis") or "")), 1)
        info_layout.addWidget(_block("Description", str(self.case_data.get("description") or "")), 2)

        root.addWidget(header)
        root.addWidget(meta)
        root.addWidget(info)

        self.viewer = PatientWidget(
            parent=self,
            import_folder_path=dicom_folder or None,
            size_init_viewers=(1, 1),
            caller=None,
            study_uid=None,
            patient_id=self.case_data.get("patient_id") or None,
            enable_progressive_mode=False,
        )
        root.addWidget(self.viewer, 1)
