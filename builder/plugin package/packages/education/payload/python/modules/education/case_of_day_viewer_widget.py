from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
from PacsClient.utils import CallerTypes


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

        # Build the secondary meta line from whatever non-empty pieces we have.
        # Older cases may have empty modality / body_part — we don't want to
        # render dangling " | " separators in that case.
        def _join_non_empty(parts):
            return "  |  ".join(str(p).strip() for p in parts if str(p or "").strip())

        patient_ref = ""
        pn = str(self.case_data.get("patient_name") or "").strip()
        pid = str(self.case_data.get("patient_id") or "").strip()
        if pn and pid:
            patient_ref = f"Patient: {pn} ({pid})"
        elif pn:
            patient_ref = f"Patient: {pn}"
        elif pid:
            patient_ref = f"Patient: {pid}"

        study_date = str(self.case_data.get("study_date") or "").strip()
        if len(study_date) == 8 and study_date.isdigit():
            study_date = f"{study_date[0:4]}-{study_date[4:6]}-{study_date[6:8]}"

        saved_by_text = str(self.case_data.get("saved_by") or "").strip()
        meta_line = _join_non_empty([
            self.case_data.get("modality"),
            self.case_data.get("body_part"),
            f"Saved by: {saved_by_text}" if saved_by_text else "",
            patient_ref,
            study_date,
        ])
        meta = QLabel(meta_line if meta_line else "Case of the Day")
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

        # DICOM folder is now optional — notes-only cases skip the PatientWidget
        # entirely and show a friendly placeholder instead.
        from pathlib import Path
        if dicom_folder and Path(dicom_folder).exists():
            # CALLER MODE — why SERVER, not IMPORT.
            #
            # IMPORT mode scans the folder and creates fresh patient/study/
            # series/instance rows in the DB, but its on-disk → ITK volume
            # builder has a multi-slice quirk: when the click-to-load handler
            # fires for a series, the cached single-slice volume from the
            # initial pipeline-thumbnail pass wins, and the user sees "1/1"
            # for series that actually have 11+ slices (visible bug:
            # scrollwheel does nothing).
            #
            # SERVER mode goes through the regular study-by-UID path. Every
            # patient saved via the toolbar export already has a DB row
            # under the original study_uid pointing at
            # ``user_data/patients/dicom/<uid>/``; the case package is a
            # parallel COPY for offline archival, but when the original is
            # still on disk SERVER mode loads the full multi-slice volume
            # exactly the same way the normal viewer does.
            #
            # If the original is missing we fall back to IMPORT against the
            # case package so cases stay viewable even when the source
            # study has been deleted.
            study_uid_for_viewer = (
                str(self.case_data.get("study_uid") or "").strip() or None
            )

            # ⚠ ``get_study_source_path`` CREATES the directory if it doesn't
            # exist (it always mkdir's), so a plain ``.exists()`` check would
            # always pass — even for cases whose source study has been deleted.
            # We must check that the folder has CONTENT (series subfolders or
            # DICOM files). Use the helper's own ``have_subfolders`` return value
            # rather than re-walking the tree.
            original_study_path = None
            if study_uid_for_viewer:
                try:
                    from PacsClient.pacs.patient_tab.utils import get_study_source_path
                    candidate, have_content = get_study_source_path(str(study_uid_for_viewer))
                    if candidate and have_content:
                        # Belt + braces: require at least one numbered series
                        # subfolder so we don't try to SERVER-load an empty
                        # placeholder dir.
                        candidate_path = Path(candidate)
                        has_series = any(
                            child.is_dir() and child.name.isdigit()
                            for child in candidate_path.iterdir()
                        )
                        if has_series:
                            original_study_path = str(candidate_path)
                except Exception:
                    original_study_path = None

            if original_study_path:
                # Preferred path — DB-driven, multi-slice safe.
                from PacsClient.utils import CallerTypes as _CT
                print(
                    f"[CASE-OF-DAY] viewer mode=SERVER study_uid={study_uid_for_viewer} "
                    f"path={original_study_path}"
                )
                self.viewer = PatientWidget(
                    parent=self,
                    import_folder_path=original_study_path,
                    size_init_viewers=(1, 1),
                    caller=_CT.SERVER,
                    study_uid=study_uid_for_viewer,
                    patient_id=self.case_data.get("patient_id") or None,
                    enable_progressive_mode=False,
                )
            else:
                # Fallback — read directly from the case package.
                print(
                    f"[CASE-OF-DAY] viewer mode=IMPORT (original study missing) "
                    f"path={dicom_folder}"
                )
                self.viewer = PatientWidget(
                    parent=self,
                    import_folder_path=dicom_folder,
                    size_init_viewers=(1, 1),
                    caller=CallerTypes.IMPORT,
                    study_uid=study_uid_for_viewer,
                    patient_id=self.case_data.get("patient_id") or None,
                    enable_progressive_mode=False,
                )
            root.addWidget(self.viewer, 1)
        else:
            self.viewer = None
            placeholder = QLabel(
                "No DICOM folder is attached to this case.\n"
                "This is a notes-only Case of the Day."
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setWordWrap(True)
            placeholder.setStyleSheet(
                "QLabel { color: #8ea1b7; font-size: 13pt; background-color: #0a0f18; "
                "padding: 40px; }"
            )
            root.addWidget(placeholder, 1)
