from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import shutil

import pydicom
import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.theme_manager import get_theme_manager


_DICOM_TAGS = [
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "SeriesNumber",
    "SeriesDescription",
    "Modality",
    "ProtocolName",
    "BodyPartExamined",
    "Manufacturer",
    "InstitutionName",
    "PatientID",
    "PatientName",
    "StudyDate",
    "StudyTime",
    "StudyDescription",
    "InstanceNumber",
    "SOPInstanceUID",
]


def _safe_text(value, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _safe_int(value, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except Exception:
        return default


def _format_study_date(value) -> str:
    text = _safe_text(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}/{text[4:6]}/{text[6:8]}"
    return text or "N/A"


def _format_study_time(value) -> str:
    text = _safe_text(value)
    if len(text) >= 6 and text[:6].isdigit():
        return f"{text[0:2]}:{text[2:4]}:{text[4:6]}"
    return text or "N/A"


def _series_sort_key(series_info: dict) -> tuple:
    series_number = _safe_text(series_info.get("series_number"))
    numeric = _safe_int(series_number)
    if numeric is not None:
        return (0, numeric, series_info.get("series_uid", ""))
    return (1, series_number.lower(), series_info.get("series_uid", ""))


def _study_sort_key(study_info: dict) -> tuple:
    patient_name = _safe_text(study_info.get("patient_name"), "unknown").lower()
    study_date = _safe_text(study_info.get("study_date"), "99999999")
    study_uid = _safe_text(study_info.get("study_uid"), "unknown")
    return (patient_name, study_date, study_uid)


def _sanitize_filename(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", _safe_text(value, "dicom"))
    return clean.strip("._") or "dicom"


def _build_series_storage_name(series_info: dict, used_names: set[str]) -> str:
    base = _safe_text(series_info.get("series_number"))
    if not base or base.upper() == "N/A":
        base = f"series_{len(used_names) + 1:03d}"
    name = _sanitize_filename(base)
    candidate = name
    suffix = 2
    while candidate in used_names:
        candidate = f"{name}_{suffix}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _build_destination_name(file_info: dict, index: int) -> str:
    instance_number = _safe_int(file_info.get("instance_number"))
    prefix = f"{instance_number:05d}" if instance_number is not None else f"{index:05d}"
    sop_uid = _sanitize_filename(_safe_text(file_info.get("sop_uid"), ""))[:64]
    stem = sop_uid or _sanitize_filename(Path(file_info["source_path"]).stem)
    return f"{prefix}_{stem}.dcm"


def _collect_source_files(scan_result: dict) -> list[str]:
    files: list[str] = []
    for study in scan_result.get("studies", []) or []:
        for series in study.get("series", []) or []:
            for file_info in series.get("files", []) or []:
                source_path = _safe_text(file_info.get("source_path"))
                if source_path:
                    files.append(source_path)
    return sorted(files, key=lambda item: item.lower())


def _study_summary_text(study_info: dict) -> str:
    description = _safe_text(study_info.get("study_description"), "Imported DICOM Study")
    study_date = _format_study_date(study_info.get("study_date"))
    study_time = _format_study_time(study_info.get("study_time"))
    return f"{description} ({study_date} {study_time})"


def scan_dicom_import_folder(folder_path: str | Path) -> dict:
    root = Path(folder_path).expanduser()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Folder does not exist: {root}")

    studies: dict[str, dict] = {}
    total_dicom_files = 0
    patient_keys = set()

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            dataset = pydicom.dcmread(
                str(file_path),
                stop_before_pixels=True,
                force=True,
                specific_tags=_DICOM_TAGS,
            )
        except Exception:
            continue

        study_uid = _safe_text(getattr(dataset, "StudyInstanceUID", None))
        series_uid = _safe_text(getattr(dataset, "SeriesInstanceUID", None))
        if not study_uid:
            study_uid = f"import-study-{_sanitize_filename(file_path.parent.name)}"
        if not series_uid:
            series_uid = f"{study_uid}-series-{_sanitize_filename(file_path.parent.name)}"

        patient_id = _safe_text(getattr(dataset, "PatientID", None), "Unknown Patient ID")
        patient_name = _safe_text(getattr(dataset, "PatientName", None), "Unknown Patient")
        study = studies.setdefault(
            study_uid,
            {
                "study_uid": study_uid,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "study_date": _safe_text(getattr(dataset, "StudyDate", None)),
                "study_time": _safe_text(getattr(dataset, "StudyTime", None)),
                "study_description": _safe_text(getattr(dataset, "StudyDescription", None), "Imported DICOM Study"),
                "count_of_series": 0,
                "series": [],
                "_series_map": {},
                "_patient_ids": {patient_id},
                "_patient_names": {patient_name},
            },
        )
        study["_patient_ids"].add(patient_id)
        study["_patient_names"].add(patient_name)

        series_map = study["_series_map"]
        series = series_map.get(series_uid)
        if series is None:
            series = {
                "series_uid": series_uid,
                "series_number": _safe_text(getattr(dataset, "SeriesNumber", None), str(len(series_map) + 1)),
                "series_description": _safe_text(getattr(dataset, "SeriesDescription", None), "Untitled Series"),
                "modality": _safe_text(getattr(dataset, "Modality", None), "N/A"),
                "image_count": 0,
                "protocol_name": _safe_text(getattr(dataset, "ProtocolName", None)),
                "body_part_examined": _safe_text(getattr(dataset, "BodyPartExamined", None)),
                "manufacturer": _safe_text(getattr(dataset, "Manufacturer", None)),
                "institution_name": _safe_text(getattr(dataset, "InstitutionName", None)),
                "files": [],
            }
            series_map[series_uid] = series
            study["series"].append(series)

        series["files"].append(
            {
                "source_path": str(file_path),
                "instance_number": _safe_int(getattr(dataset, "InstanceNumber", None)),
                "sop_uid": _safe_text(getattr(dataset, "SOPInstanceUID", None)),
            }
        )
        series["image_count"] += 1
        total_dicom_files += 1
        patient_keys.add((patient_id, patient_name))

    studies_list = []
    warnings = []

    for study in studies.values():
        study["series"].sort(key=_series_sort_key)
        study["count_of_series"] = len(study["series"])

        if len(study["_patient_ids"]) > 1 or len(study["_patient_names"]) > 1:
            warnings.append(
                f"Study {study['study_uid']} contains headers for more than one patient identity."
            )

        study.pop("_series_map", None)
        study.pop("_patient_ids", None)
        study.pop("_patient_names", None)
        studies_list.append(study)

    studies_list.sort(key=_study_sort_key)

    if len(patient_keys) > 1:
        warnings.append(
            f"The selected folder contains DICOM files for {len(patient_keys)} patients."
        )
    if len(studies_list) > 1:
        warnings.append(
            f"The selected folder contains {len(studies_list)} studies. All will be imported; the primary study will open first."
        )

    primary_study = None
    if studies_list:
        primary_study = max(
            studies_list,
            key=lambda study: (
                sum(series.get("image_count", 0) for series in study.get("series", [])),
                study.get("study_uid", ""),
            ),
        )

    return {
        "folder_path": str(root),
        "dicom_file_count": total_dicom_files,
        "patient_count": len(patient_keys),
        "study_count": len(studies_list),
        "series_count": sum(len(study.get("series", [])) for study in studies_list),
        "studies": studies_list,
        "primary_study_uid": primary_study.get("study_uid") if primary_study else "",
        "warnings": warnings,
    }


def import_scanned_dicom_studies(scan_result: dict, base_output_dir: str | Path = SOURCE_PATH) -> dict:
    output_root = Path(base_output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    imported_studies = []
    copied_files = 0
    skipped_files = 0
    errors = []

    for study in deepcopy(scan_result.get("studies", []) or []):
        study_uid = _safe_text(study.get("study_uid"))
        if not study_uid:
            continue

        target_study_dir = output_root / study_uid
        target_study_dir.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()

        for series in study.get("series", []) or []:
            storage_name = _build_series_storage_name(series, used_names)
            series["series_path_name"] = storage_name

            target_series_dir = target_study_dir / storage_name
            target_series_dir.mkdir(parents=True, exist_ok=True)

            ordered_files = sorted(
                series.get("files", []) or [],
                key=lambda item: (
                    _safe_int(item.get("instance_number"), 10**9),
                    _safe_text(item.get("source_path")).lower(),
                ),
            )

            for index, file_info in enumerate(ordered_files, start=1):
                src = Path(file_info["source_path"]).expanduser()
                if not src.exists():
                    errors.append(f"Missing source file: {src}")
                    continue

                dest = target_series_dir / _build_destination_name(file_info, index)
                try:
                    if src.resolve() == dest.resolve():
                        skipped_files += 1
                        continue
                except Exception:
                    pass

                if dest.exists():
                    skipped_files += 1
                    continue

                shutil.copy2(src, dest)
                copied_files += 1

        imported_studies.append(study)

    primary_study_uid = _safe_text(scan_result.get("primary_study_uid"))
    primary_study = next(
        (study for study in imported_studies if study.get("study_uid") == primary_study_uid),
        imported_studies[0] if imported_studies else None,
    )

    return {
        "studies": imported_studies,
        "primary_study": primary_study,
        "copied_files": copied_files,
        "skipped_files": skipped_files,
        "errors": errors,
    }


def filter_scan_result_for_selection(
    scan_result: dict,
    selected_series_by_study_uid: dict[str, set[str] | list[str] | tuple[str, ...]],
    selected_study_uids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict:
    selected_study_uid_set = set(selected_study_uids or selected_series_by_study_uid.keys())
    selected_series_map = {
        study_uid: {str(series_uid) for series_uid in (series_uids or [])}
        for study_uid, series_uids in selected_series_by_study_uid.items()
    }

    filtered_studies = []
    patient_keys = set()

    for study in deepcopy(scan_result.get("studies", []) or []):
        study_uid = _safe_text(study.get("study_uid"))
        if study_uid not in selected_study_uid_set:
            continue

        selected_series_uids = selected_series_map.get(study_uid, set())
        if not selected_series_uids:
            continue

        filtered_series = [
            series for series in study.get("series", []) or []
            if _safe_text(series.get("series_uid")) in selected_series_uids
        ]
        if not filtered_series:
            continue

        study["series"] = filtered_series
        study["count_of_series"] = len(filtered_series)
        filtered_studies.append(study)
        patient_keys.add(
            (
                _safe_text(study.get("patient_id"), "Unknown Patient ID"),
                _safe_text(study.get("patient_name"), "Unknown Patient"),
            )
        )

    dicom_file_count = 0
    for study in filtered_studies:
        for series in study.get("series", []) or []:
            file_count = len(series.get("files", []) or [])
            dicom_file_count += file_count if file_count else int(series.get("image_count", 0) or 0)

    warnings = []
    if len(patient_keys) > 1:
        warnings.append(
            f"The selected import contains DICOM files for {len(patient_keys)} patients."
        )
    if len(filtered_studies) > 1:
        warnings.append(
            f"The selected import contains {len(filtered_studies)} studies. The largest selected study will open first."
        )

    primary_study = None
    if filtered_studies:
        primary_study = max(
            filtered_studies,
            key=lambda study: (
                sum(series.get("image_count", 0) for series in study.get("series", [])),
                study.get("study_uid", ""),
            ),
        )

    return {
        "folder_path": scan_result.get("folder_path", ""),
        "dicom_file_count": dicom_file_count,
        "patient_count": len(patient_keys),
        "study_count": len(filtered_studies),
        "series_count": sum(len(study.get("series", [])) for study in filtered_studies),
        "studies": filtered_studies,
        "primary_study_uid": primary_study.get("study_uid") if primary_study else "",
        "warnings": warnings,
    }


class DicomImportPreviewDialog(QDialog):
    def __init__(self, scan_result: dict, parent=None):
        super().__init__(parent)
        self.scan_result = scan_result
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()
        self._studies = list(self.scan_result.get("studies", []) or [])
        self._studies_by_uid = {
            _safe_text(study.get("study_uid")): study for study in self._studies
        }
        self._study_labels_by_uid: dict[str, str] = {}
        self._study_row_by_uid: dict[str, int] = {}
        self._study_selected: dict[str, bool] = {}
        self._series_selected_by_study_uid: dict[str, set[str]] = {}
        self._focused_study_uid = ""
        self._syncing_tables = False
        self._initialize_selection_state()

        self.setModal(True)
        self.setWindowTitle("Review DICOM Import")
        self.setMinimumSize(1020, 620)
        self._build_ui()
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.apply_theme(self._active_theme)
        self._populate_study_table()
        self._sync_selection_summary()

    def _initialize_selection_state(self) -> None:
        for index, study in enumerate(self._studies, start=1):
            study_uid = _safe_text(study.get("study_uid"))
            self._study_labels_by_uid[study_uid] = f"Study {index}"
            self._study_selected[study_uid] = True
            self._series_selected_by_study_uid[study_uid] = {
                _safe_text(series.get("series_uid"))
                for series in study.get("series", []) or []
                if _safe_text(series.get("series_uid"))
            }
        if self._studies:
            self._focused_study_uid = _safe_text(self._studies[0].get("study_uid"))

    def _build_metric_card(self, title: str, value: str, icon_name: str, accent: str) -> QWidget:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)

        icon_label = QLabel()
        try:
            icon_label.setPixmap(qta.icon(icon_name, color=accent).pixmap(14, 14))
        except Exception:
            pass
        header.addWidget(icon_label, 0)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        header.addWidget(title_label, 1)
        layout.addLayout(header)

        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setProperty("accentColor", accent)
        layout.addWidget(value_label)
        return card

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        header_card = QFrame()
        header_card.setObjectName("headerCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        icon_label = QLabel()
        try:
            icon_label.setPixmap(qta.icon("fa5s.file-import", color="#f59e0b").pixmap(20, 20))
        except Exception:
            pass
        header_row.addWidget(icon_label, 0)

        title_label = QLabel("Review DICOM Import")
        title_label.setObjectName("titleLabel")
        header_row.addWidget(title_label, 1)
        header_layout.addLayout(header_row)

        subtitle = QLabel(
            "AI-PACS scanned the selected folder, read the DICOM headers, and prepared the studies and series below."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("subtitleLabel")
        header_layout.addWidget(subtitle)

        folder_label = QLabel(f"Selected Folder: {self.scan_result.get('folder_path', '')}")
        folder_label.setWordWrap(True)
        folder_label.setObjectName("folderLabel")
        folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header_layout.addWidget(folder_label)
        outer.addWidget(header_card)

        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(8)
        metrics = [
            ("DICOM Files", str(self.scan_result.get("dicom_file_count", 0)), "fa5s.file-medical", "#3b82f6"),
            ("Patients", str(self.scan_result.get("patient_count", 0)), "fa5s.user-injured", "#10b981"),
            ("Studies", str(self.scan_result.get("study_count", 0)), "fa5s.folder-open", "#f59e0b"),
            ("Series", str(self.scan_result.get("series_count", 0)), "fa5s.layer-group", "#8b5cf6"),
        ]
        for index, metric in enumerate(metrics):
            metrics_grid.addWidget(self._build_metric_card(*metric), index // 2, index % 2)
        outer.addLayout(metrics_grid)

        warnings = self.scan_result.get("warnings", []) or []
        if warnings:
            warning_card = QFrame()
            warning_card.setObjectName("warningCard")
            warning_layout = QVBoxLayout(warning_card)
            warning_layout.setContentsMargins(14, 10, 14, 10)
            warning_layout.setSpacing(4)

            warning_title = QLabel("Import Notes")
            warning_title.setObjectName("sectionTitle")
            warning_layout.addWidget(warning_title)

            for warning in warnings:
                warning_label = QLabel(f"- {warning}")
                warning_label.setWordWrap(True)
                warning_label.setObjectName("warningLabel")
                warning_layout.addWidget(warning_label)
            outer.addWidget(warning_card)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        studies_card = QFrame()
        studies_card.setObjectName("tableCard")
        studies_layout = QVBoxLayout(studies_card)
        studies_layout.setContentsMargins(14, 12, 14, 14)
        studies_layout.setSpacing(8)

        studies_title = QLabel("Studies Found")
        studies_title.setObjectName("sectionTitle")
        studies_layout.addWidget(studies_title)

        studies_note = QLabel(
            "Select one or more studies to import. Click a study to review and choose its series."
        )
        studies_note.setWordWrap(True)
        studies_note.setObjectName("selectionNote")
        studies_layout.addWidget(studies_note)

        self.study_table = QTableWidget(0, 4)
        self.study_table.setHorizontalHeaderLabels(["Import", "Study", "Patient", "Series"])
        self.study_table.verticalHeader().setVisible(False)
        self.study_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.study_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.study_table.setSelectionMode(QTableWidget.SingleSelection)
        self.study_table.setAlternatingRowColors(True)
        self.study_table.setMinimumWidth(360)
        self.study_table.setMinimumHeight(300)
        self.study_table.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.study_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.study_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.study_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.study_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.study_table.itemChanged.connect(self._on_study_item_changed)
        self.study_table.itemSelectionChanged.connect(self._on_study_focus_changed)
        studies_layout.addWidget(self.study_table, 1)

        studies_hint = QLabel("Series counts show selected / found for each study.")
        studies_hint.setObjectName("selectionHint")
        studies_layout.addWidget(studies_hint)
        splitter.addWidget(studies_card)

        series_card = QFrame()
        series_card.setObjectName("tableCard")
        series_layout = QVBoxLayout(series_card)
        series_layout.setContentsMargins(14, 12, 14, 14)
        series_layout.setSpacing(8)

        series_header = QHBoxLayout()
        series_header.setSpacing(10)

        self.series_title_label = QLabel("Series")
        self.series_title_label.setObjectName("sectionTitle")
        series_header.addWidget(self.series_title_label, 1)

        self.select_all_series_button = QPushButton("Select All")
        self.select_all_series_button.setObjectName("secondaryButton")
        self.select_all_series_button.clicked.connect(lambda: self._set_all_series_for_focused_study(True))
        series_header.addWidget(self.select_all_series_button, 0)

        self.clear_series_button = QPushButton("Clear")
        self.clear_series_button.setObjectName("secondaryButton")
        self.clear_series_button.clicked.connect(lambda: self._set_all_series_for_focused_study(False))
        series_header.addWidget(self.clear_series_button, 0)
        series_layout.addLayout(series_header)

        self.series_context_label = QLabel("")
        self.series_context_label.setWordWrap(True)
        self.series_context_label.setObjectName("selectionNote")
        series_layout.addWidget(self.series_context_label)

        self.series_table = QTableWidget(0, 5)
        self.series_table.setHorizontalHeaderLabels(
            ["Import", "Series", "Modality", "Images", "Description"]
        )
        self.series_table.verticalHeader().setVisible(False)
        self.series_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.series_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.series_table.setSelectionMode(QTableWidget.SingleSelection)
        self.series_table.setAlternatingRowColors(True)
        self.series_table.setMinimumHeight(340)
        self.series_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.series_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.series_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.series_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.series_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.series_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.series_table.itemChanged.connect(self._on_series_item_changed)
        series_layout.addWidget(self.series_table, 1)

        splitter.addWidget(series_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)
        outer.addWidget(splitter, 1)

        question_card = QFrame()
        question_card.setObjectName("questionCard")
        question_layout = QVBoxLayout(question_card)
        question_layout.setContentsMargins(14, 10, 14, 10)
        question_layout.setSpacing(6)

        self.summary_toggle_button = QToolButton()
        self.summary_toggle_button.setObjectName("summaryToggle")
        self.summary_toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.summary_toggle_button.setArrowType(Qt.RightArrow)
        self.summary_toggle_button.setCheckable(True)
        self.summary_toggle_button.setChecked(False)
        self.summary_toggle_button.setText("Selection Summary")
        self.summary_toggle_button.toggled.connect(self._set_summary_expanded)
        question_layout.addWidget(self.summary_toggle_button)

        self.summary_content_widget = QWidget()
        self.summary_content_widget.setVisible(False)
        summary_content_layout = QVBoxLayout(self.summary_content_widget)
        summary_content_layout.setContentsMargins(4, 2, 4, 0)
        summary_content_layout.setSpacing(6)

        self.selection_summary_label = QLabel("")
        self.selection_summary_label.setWordWrap(True)
        self.selection_summary_label.setObjectName("questionLabel")
        summary_content_layout.addWidget(self.selection_summary_label)

        self.primary_preview_label = QLabel("")
        self.primary_preview_label.setWordWrap(True)
        self.primary_preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.primary_preview_label.setObjectName("studyDetails")
        summary_content_layout.addWidget(self.primary_preview_label)

        self.question_label = QLabel("")
        self.question_label.setWordWrap(True)
        self.question_label.setObjectName("questionLabel")
        summary_content_layout.addWidget(self.question_label)
        question_layout.addWidget(self.summary_content_widget)
        outer.addWidget(question_card)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        self.import_button = QPushButton("Import Selected Into AI-PACS")
        self.import_button.setObjectName("primaryButton")
        try:
            self.import_button.setIcon(qta.icon("fa5s.download", color="#ffffff"))
        except Exception:
            pass
        self.import_button.clicked.connect(self._accept_if_selection_valid)
        button_row.addWidget(self.import_button)
        outer.addLayout(button_row)

    def _set_summary_expanded(self, expanded: bool) -> None:
        self.summary_content_widget.setVisible(expanded)
        self.summary_toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _study_uid_from_row(self, row: int) -> str:
        item = self.study_table.item(row, 0)
        return _safe_text(item.data(Qt.UserRole)) if item is not None else ""

    def _series_count_text(self, study_uid: str) -> str:
        study = self._studies_by_uid.get(study_uid, {})
        total_count = len(study.get("series", []) or [])
        selected_count = len(self._series_selected_by_study_uid.get(study_uid, set()))
        return f"{selected_count} / {total_count}"

    def _selected_study_uids(self) -> list[str]:
        return [
            study_uid
            for study_uid, is_selected in self._study_selected.items()
            if is_selected and self._series_selected_by_study_uid.get(study_uid)
        ]

    def selected_scan_result(self) -> dict:
        selected_study_uids = self._selected_study_uids()
        selected_series_map = {
            study_uid: set(self._series_selected_by_study_uid.get(study_uid, set()))
            for study_uid in selected_study_uids
        }
        return filter_scan_result_for_selection(
            self.scan_result,
            selected_series_map,
            set(selected_study_uids),
        )

    def _populate_study_table(self) -> None:
        self._syncing_tables = True
        try:
            self.study_table.setRowCount(len(self._studies))
            self._study_row_by_uid.clear()
            for row_index, study in enumerate(self._studies):
                study_uid = _safe_text(study.get("study_uid"))
                self._study_row_by_uid[study_uid] = row_index

                import_item = QTableWidgetItem()
                import_item.setData(Qt.UserRole, study_uid)
                import_item.setFlags(import_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                import_item.setCheckState(Qt.Checked if self._study_selected.get(study_uid, False) else Qt.Unchecked)
                import_item.setTextAlignment(Qt.AlignCenter)
                self.study_table.setItem(row_index, 0, import_item)

                study_label = self._study_labels_by_uid.get(study_uid, f"Study {row_index + 1}")
                patient_text = (
                    f"{_safe_text(study.get('patient_name'), 'Unknown Patient')} "
                    f"({_safe_text(study.get('patient_id'), 'Unknown ID')})"
                )
                tooltip = (
                    f"{study_label}\n"
                    f"{patient_text}\n"
                    f"{_safe_text(study.get('study_description'), 'Imported DICOM Study')}\n"
                    f"Study UID: {study_uid}\n"
                    f"{_study_summary_text(study)}"
                )

                label_item = QTableWidgetItem(study_label)
                label_item.setData(Qt.UserRole, study_uid)
                label_item.setToolTip(tooltip)
                self.study_table.setItem(row_index, 1, label_item)

                patient_item = QTableWidgetItem(patient_text)
                patient_item.setData(Qt.UserRole, study_uid)
                patient_item.setToolTip(tooltip)
                self.study_table.setItem(row_index, 2, patient_item)

                series_count_item = QTableWidgetItem(self._series_count_text(study_uid))
                series_count_item.setData(Qt.UserRole, study_uid)
                series_count_item.setTextAlignment(Qt.AlignCenter)
                self.study_table.setItem(row_index, 3, series_count_item)
                self.study_table.setRowHeight(row_index, 38)
        finally:
            self._syncing_tables = False

        if self._focused_study_uid and self._focused_study_uid in self._study_row_by_uid:
            self.study_table.selectRow(self._study_row_by_uid[self._focused_study_uid])
        elif self._studies:
            self._focused_study_uid = _safe_text(self._studies[0].get("study_uid"))
            self.study_table.selectRow(0)
        self._populate_series_table()

    def _populate_series_table(self) -> None:
        study = self._studies_by_uid.get(self._focused_study_uid)
        self._syncing_tables = True
        try:
            if not study:
                self.series_title_label.setText("Series")
                self.series_context_label.setText("Select a study to review its series.")
                self.series_table.setRowCount(0)
                self.select_all_series_button.setEnabled(False)
                self.clear_series_button.setEnabled(False)
                return

            series_list = list(study.get("series", []) or [])
            selected_series_uids = self._series_selected_by_study_uid.setdefault(
                self._focused_study_uid, set()
            )
            study_label = self._study_labels_by_uid.get(self._focused_study_uid, "Study")
            self.series_title_label.setText(f"{study_label} Series")
            self.series_context_label.setText(
                f"{_safe_text(study.get('patient_name'), 'Unknown Patient')} "
                f"({_safe_text(study.get('patient_id'), 'Unknown ID')}) | "
                f"{len(series_list)} series found | "
                f"{len(selected_series_uids)} selected"
            )
            self.select_all_series_button.setEnabled(True)
            self.clear_series_button.setEnabled(True)

            self.series_table.setRowCount(len(series_list))
            for row_index, series in enumerate(series_list):
                series_uid = _safe_text(series.get("series_uid"))

                import_item = QTableWidgetItem()
                import_item.setData(Qt.UserRole, series_uid)
                import_item.setFlags(import_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                import_item.setCheckState(Qt.Checked if series_uid in selected_series_uids else Qt.Unchecked)
                import_item.setTextAlignment(Qt.AlignCenter)
                self.series_table.setItem(row_index, 0, import_item)

                series_number_item = QTableWidgetItem(_safe_text(series.get("series_number"), "N/A"))
                series_number_item.setTextAlignment(Qt.AlignCenter)
                self.series_table.setItem(row_index, 1, series_number_item)

                modality_item = QTableWidgetItem(_safe_text(series.get("modality"), "N/A"))
                modality_item.setTextAlignment(Qt.AlignCenter)
                self.series_table.setItem(row_index, 2, modality_item)

                image_count_item = QTableWidgetItem(str(series.get("image_count", 0)))
                image_count_item.setTextAlignment(Qt.AlignCenter)
                self.series_table.setItem(row_index, 3, image_count_item)

                description_item = QTableWidgetItem(
                    _safe_text(series.get("series_description"), "Untitled Series")
                )
                self.series_table.setItem(row_index, 4, description_item)
                self.series_table.setRowHeight(row_index, 34)
        finally:
            self._syncing_tables = False

    def _refresh_study_row(self, study_uid: str) -> None:
        row_index = self._study_row_by_uid.get(study_uid)
        if row_index is None:
            return
        series_count_item = self.study_table.item(row_index, 3)
        if series_count_item is not None:
            series_count_item.setText(self._series_count_text(study_uid))

    def _on_study_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_tables or item.column() != 0:
            return
        study_uid = _safe_text(item.data(Qt.UserRole))
        if not study_uid:
            return

        is_checked = item.checkState() == Qt.Checked
        self._study_selected[study_uid] = is_checked

        if is_checked and not self._series_selected_by_study_uid.get(study_uid):
            study = self._studies_by_uid.get(study_uid, {})
            self._series_selected_by_study_uid[study_uid] = {
                _safe_text(series.get("series_uid"))
                for series in study.get("series", []) or []
                if _safe_text(series.get("series_uid"))
            }

        self._refresh_study_row(study_uid)
        if study_uid == self._focused_study_uid:
            self._populate_series_table()
        self._sync_selection_summary()

    def _on_study_focus_changed(self) -> None:
        if self._syncing_tables:
            return
        current_row = self.study_table.currentRow()
        if current_row < 0:
            return
        study_uid = self._study_uid_from_row(current_row)
        if not study_uid:
            return
        self._focused_study_uid = study_uid
        self._populate_series_table()

    def _on_series_item_changed(self, item: QTableWidgetItem) -> None:
        if self._syncing_tables or item.column() != 0 or not self._focused_study_uid:
            return
        series_uid = _safe_text(item.data(Qt.UserRole))
        if not series_uid:
            return

        selected_series_uids = self._series_selected_by_study_uid.setdefault(
            self._focused_study_uid, set()
        )
        if item.checkState() == Qt.Checked:
            selected_series_uids.add(series_uid)
            self._study_selected[self._focused_study_uid] = True
            study_row = self._study_row_by_uid.get(self._focused_study_uid)
            if study_row is not None:
                study_item = self.study_table.item(study_row, 0)
                if study_item is not None and study_item.checkState() != Qt.Checked:
                    self._syncing_tables = True
                    try:
                        study_item.setCheckState(Qt.Checked)
                    finally:
                        self._syncing_tables = False
        else:
            selected_series_uids.discard(series_uid)
            if not selected_series_uids:
                self._study_selected[self._focused_study_uid] = False
                study_row = self._study_row_by_uid.get(self._focused_study_uid)
                if study_row is not None:
                    study_item = self.study_table.item(study_row, 0)
                    if study_item is not None and study_item.checkState() != Qt.Unchecked:
                        self._syncing_tables = True
                        try:
                            study_item.setCheckState(Qt.Unchecked)
                        finally:
                            self._syncing_tables = False

        self._refresh_study_row(self._focused_study_uid)
        self._populate_series_table()
        self._sync_selection_summary()

    def _set_all_series_for_focused_study(self, select_all: bool) -> None:
        study = self._studies_by_uid.get(self._focused_study_uid)
        if not study:
            return

        if select_all:
            self._series_selected_by_study_uid[self._focused_study_uid] = {
                _safe_text(series.get("series_uid"))
                for series in study.get("series", []) or []
                if _safe_text(series.get("series_uid"))
            }
            self._study_selected[self._focused_study_uid] = True
            study_row = self._study_row_by_uid.get(self._focused_study_uid)
            if study_row is not None:
                study_item = self.study_table.item(study_row, 0)
                if study_item is not None and study_item.checkState() != Qt.Checked:
                    self._syncing_tables = True
                    try:
                        study_item.setCheckState(Qt.Checked)
                    finally:
                        self._syncing_tables = False
        else:
            self._series_selected_by_study_uid[self._focused_study_uid] = set()
            self._study_selected[self._focused_study_uid] = False
            study_row = self._study_row_by_uid.get(self._focused_study_uid)
            if study_row is not None:
                study_item = self.study_table.item(study_row, 0)
                if study_item is not None and study_item.checkState() != Qt.Unchecked:
                    self._syncing_tables = True
                    try:
                        study_item.setCheckState(Qt.Unchecked)
                    finally:
                        self._syncing_tables = False

        self._refresh_study_row(self._focused_study_uid)
        self._populate_series_table()
        self._sync_selection_summary()

    def _sync_selection_summary(self) -> None:
        selected_scan_result = self.selected_scan_result()
        selected_study_count = selected_scan_result.get("study_count", 0)
        selected_series_count = selected_scan_result.get("series_count", 0)
        selected_file_count = selected_scan_result.get("dicom_file_count", 0)

        if selected_study_count == 0 or selected_series_count == 0:
            self.summary_toggle_button.setText("Selection Summary")
            self.selection_summary_label.setText(
                "No studies or series are selected for import yet."
            )
            self.primary_preview_label.setText(
                "Select at least one study and one series to continue."
            )
            self.question_label.setText(
                f"When you confirm, AI-PACS will copy the selected DICOM files into {SOURCE_PATH} "
                "and store the selected metadata in the local database."
            )
            self.import_button.setEnabled(False)
            return

        self.selection_summary_label.setText(
            f"{selected_study_count} studies selected | "
            f"{selected_series_count} series selected | "
            f"{selected_file_count} DICOM files selected"
        )
        self.summary_toggle_button.setText(
            f"Selection Summary ({selected_study_count} studies / {selected_series_count} series)"
        )

        primary_study = next(
            (
                study for study in selected_scan_result.get("studies", []) or []
                if study.get("study_uid") == selected_scan_result.get("primary_study_uid")
            ),
            None,
        )
        if primary_study:
            study_uid = _safe_text(primary_study.get("study_uid"))
            self.primary_preview_label.setText(
                f"Study that will open after import: "
                f"{self._study_labels_by_uid.get(study_uid, 'Selected Study')}\n"
                f"Patient: {_safe_text(primary_study.get('patient_name'), 'Unknown Patient')} "
                f"({_safe_text(primary_study.get('patient_id'), 'Unknown ID')})\n"
                f"Study: {_safe_text(primary_study.get('study_description'), 'Imported DICOM Study')}\n"
                f"Series selected in this study: {len(primary_study.get('series', []) or [])}"
            )
        else:
            self.primary_preview_label.setText("No primary study is available for the current selection.")

        self.question_label.setText(
            f"Import the selected studies and series into AI-PACS now?\n"
            f"The selected DICOM files will be copied into {SOURCE_PATH}, saved in the local database, "
            "and the selected primary study will open in the viewer."
        )
        self.import_button.setEnabled(True)

    def _accept_if_selection_valid(self) -> None:
        selected_scan_result = self.selected_scan_result()
        if selected_scan_result.get("study_count", 0) == 0 or selected_scan_result.get("series_count", 0) == 0:
            QMessageBox.warning(
                self,
                "Nothing Selected",
                "Select at least one study and one series before importing into AI-PACS.",
            )
            return
        self.accept()

    def apply_theme(self, theme=None) -> None:
        self._active_theme = theme or self.theme_manager.current_theme()
        t = self._active_theme
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {t['window_bg']};
            }}
            QFrame#headerCard, QFrame#tableCard, QFrame#questionCard {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t['panel_alt_bg']}, stop:1 {t['panel_bg']});
                border: 1px solid {t['border']};
                border-radius: 14px;
            }}
            QFrame#warningCard {{
                background: rgba(245, 158, 11, 0.10);
                border: 1px solid rgba(245, 158, 11, 0.35);
                border-radius: 14px;
            }}
            QFrame#metricCard {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t['card_bg']}, stop:1 {t['panel_deep_bg']});
                border: 1px solid {t['border']};
                border-radius: 12px;
            }}
            QLabel {{
                color: {t['text_primary']};
            }}
            QLabel#titleLabel {{
                font-size: 18px;
                font-weight: 700;
                color: {t['text_primary']};
            }}
            QLabel#subtitleLabel {{
                font-size: 12px;
                color: {t['text_secondary']};
            }}
            QLabel#folderLabel {{
                font-size: 11px;
                color: {t['text_muted']};
                background: rgba(15, 23, 42, 0.45);
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 6px 8px;
            }}
            QLabel#metricTitle {{
                font-size: 10px;
                font-weight: 600;
                color: {t['text_muted']};
                text-transform: uppercase;
            }}
            QLabel#metricValue {{
                font-size: 18px;
                font-weight: 700;
                color: {t['text_primary']};
            }}
            QLabel#sectionTitle {{
                font-size: 13px;
                font-weight: 700;
                color: {t['text_primary']};
            }}
            QLabel#selectionNote {{
                font-size: 11px;
                color: {t['text_secondary']};
                line-height: 1.45;
            }}
            QLabel#selectionHint {{
                font-size: 10px;
                color: {t['text_muted']};
            }}
            QLabel#studyDetails {{
                font-size: 12px;
                color: {t['text_secondary']};
                line-height: 1.4;
            }}
            QLabel#warningLabel {{
                font-size: 11px;
                color: {t['text_primary']};
            }}
            QLabel#questionLabel {{
                font-size: 12px;
                color: {t['text_secondary']};
                line-height: 1.5;
            }}
            QTableWidget {{
                background: {t['panel_deep_bg']};
                alternate-background-color: {t['card_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 10px;
                gridline-color: {t['border']};
                selection-background-color: {t['accent_soft']};
                selection-color: {t['text_primary']};
                font-size: 12px;
            }}
            QHeaderView::section {{
                background: {t['panel_alt_bg']};
                color: {t['text_primary']};
                padding: 8px 10px;
                border: none;
                border-bottom: 1px solid {t['border']};
                font-size: 12px;
                font-weight: 700;
            }}
            QSplitter::handle {{
                background: {t['window_bg']};
            }}
            QSplitter::handle:hover {{
                background: {t['accent_soft']};
            }}
            QToolButton#summaryToggle {{
                background: transparent;
                color: {t['text_primary']};
                border: none;
                padding: 2px 0px;
                text-align: left;
                font-size: 13px;
                font-weight: 700;
            }}
            QToolButton#summaryToggle:hover {{
                color: {t['accent_hover']};
            }}
            QPushButton#secondaryButton {{
                background: {t['panel_alt_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 9px;
                padding: 8px 14px;
                min-width: 110px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#secondaryButton:hover {{
                border-color: {t['accent']};
                background: {t['card_bg']};
            }}
            QPushButton#primaryButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {t['accent_hover']}, stop:1 {t['accent']});
                color: #ffffff;
                border: none;
                border-radius: 9px;
                padding: 8px 16px;
                min-width: 180px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#primaryButton:hover {{
                background: {t['accent_hover']};
            }}
            QPushButton#primaryButton:pressed {{
                background: {t['accent_pressed']};
            }}
            """
        )
