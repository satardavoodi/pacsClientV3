from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLabel
)
from PySide6.QtCore import Qt
from .abstract_tab import AbstractTab

import os
import glob
import logging
import qtawesome as qta

logger = logging.getLogger(__name__)

PREFERRED_COLUMNS = [
    "source_csv_file",
    "case_id",
    "patient_id",
    "patient_uid",
    "study_instance_uid",
    "series_instance_uid",
    "sop_instance_uid",
    "module_name",
    "modality",
    "labels_pred",
    "pred_mass",
    "patient_name",
    "dicom_full_path",
    "box",
    "scores",
    "ai_bone_age_years",
    "ai_bone_age_months",
    "ai_sex",
    "corrected_bone_age_years",
    "corrected_bone_age_months",
    "corrected_sex",
    "validation_status",
    "reviewer_id",
    "review_timestamp",
    "correction_notes",
    "export_status",
    "server_sync_status",
]
# =========================================================
# DataSet CSV Reader (NOW CONNECTABLE + debuggable)
# =========================================================
def read_dataset_csvs(csv_paths):
    import csv
    import os
    import glob

    if not csv_paths:
        return []

    # normalize
    if isinstance(csv_paths, (str, os.PathLike)):
        csv_paths = [str(csv_paths)]
    else:
        csv_paths = [str(p) for p in csv_paths]

    # expand dirs -> *.csv
    expanded = []
    for p in csv_paths:
        if os.path.isdir(p):
            expanded.extend(sorted(glob.glob(os.path.join(p, "*.csv"))))
        else:
            expanded.append(p)

    def pick(d, keys):
        for k in keys:
            if k in d and d.get(k) not in (None, ""):
                return d.get(k)
        return None

    rows = []
    for path in expanded:
        try:
            if not os.path.exists(path):
                logger.info(f"[DataSetTab] CSV not found: {path}")
                continue

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                n = 0
                for r in reader:
                    # box: either "box" string or x/y columns
                    box = pick(r, ["box", "bbox", "boxes"])
                    if box is None:
                        x1 = pick(r, ["x1", "xmin", "left"])
                        y1 = pick(r, ["y1", "ymin", "top"])
                        x2 = pick(r, ["x2", "xmax", "right"])
                        y2 = pick(r, ["y2", "ymax", "bottom"])
                        if all(v is not None for v in (x1, y1, x2, y2)):
                            box = f"[{x1},{y1},{x2},{y2}]"

                    score = pick(r, ["scores", "score", "prob", "confidence", "conf", "p"])
                    label = pick(r, ["labels_pred", "label", "class", "pred", "prediction"])

                    row_out = dict(r)
                    row_out.setdefault("source_csv_file", os.path.basename(path))
                    row_out.setdefault("patient_uid", pick(r, ["patient_uid", "patient_id", "PatientID"]))
                    row_out.setdefault("study_instance_uid", pick(r, ["study_instance_uid", "study_uid", "StudyInstanceUID"]))
                    row_out.setdefault("labels_pred", label)
                    row_out.setdefault("pred_mass", pick(r, ["pred_mass", "mass", "pred", "prediction", "value"]))
                    row_out.setdefault("patient_name", pick(r, ["patient_name", "PatientName"]))
                    row_out.setdefault("dicom_full_path", pick(r, ["dicom_full_path", "dicom_path", "path", "file"]))
                    row_out.setdefault("box", box)
                    row_out.setdefault("scores", score)
                    rows.append(row_out)
                    n += 1

            logger.info(f"[DataSetTab] loaded {n} rows from: {path}  cols={cols}")
        except Exception as e:
            logger.info(f"[DataSetTab] ERROR reading CSV '{path}': {e}")

    return rows


# =========================================================
# DataSet Table Widget
# =========================================================
class DataSetTableWidget(QWidget):
    """
    Simple, clean, future-expandable table.
    Supports generic CSV/feedback structures, not only MG rows.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.table = QTableWidget()
        self.table.setColumnCount(0)
        self._columns = []

        # Behavior
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        # Header
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setHighlightSections(False)

        # Styling (aligned with patient_table_widget vibe)
        self.table.setStyleSheet("""
            QTableWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                color: #f7fafc;
                font-size: 13px;
            }

            QTableWidget::item {
                padding: 6px;
                border: none;
            }

            QTableWidget::item:selected {
                background: #3182ce;
                color: #ffffff;
            }

            QTableWidget::item:hover {
                background: #2d3748;
            }

            QTableWidget::item:alternate {
                background: #1a202c;
            }

            QHeaderView::section {
                background: #0f1419;
                color: #f7fafc;
                padding: 8px;
                border: none;
                font-weight: 600;
                text-align: center;
            }

            QHeaderView::section:hover {
                background: #2d3748;
            }
        """)

        layout.addWidget(self.table)

    # -----------------------------------------------------
    # Public API (future AI / CSV connection)
    # -----------------------------------------------------
    def clear(self):
        self.table.setRowCount(0)

    def set_rows(self, rows):
        self.clear()
        self._columns = self._resolve_columns(rows)
        self.table.setColumnCount(len(self._columns))
        self.table.setHorizontalHeaderLabels(self._columns)

        for row_data in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)

            for col_idx, col_name in enumerate(self._columns):
                self._set_item(row, col_idx, row_data.get(col_name))

    def _resolve_columns(self, rows):
        seen = set()
        columns = []
        for col in PREFERRED_COLUMNS:
            for row in rows:
                if col in row and col not in seen:
                    seen.add(col)
                    columns.append(col)
                    break
        for row in rows:
            for col in row.keys():
                if col not in seen:
                    seen.add(col)
                    columns.append(col)
        return columns

    def _set_item(self, row, col, value):
        item = QTableWidgetItem("" if value is None else str(value))
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, col, item)


# =========================================================
# DataSet Tab (AbstractTab)  (NOW UPDATABLE)
# =========================================================
def _normalize_module_mode(mode):
    value = str(mode or "").strip().lower()
    if value in ("mg", "mammo", "mammography", "breast"):
        return "mammography"
    if value in ("dx", "bone", "bone_age", "bone-age", "boneage"):
        return "bone_age"
    return None


class DataSetTab(AbstractTab):
    """
    New AI Tool Tab: Data Set
    Can be populated either by:
      - pushing rows directly from EagleEye (recommended)
      - reading from CSV paths
    """

    def __init__(self, study_uid=None, csv_paths=None, data_provider=None, module_mode=None):
        super().__init__()
        self.study_uid = study_uid
        self.module_mode = _normalize_module_mode(module_mode)
        self._csv_paths = []
        self._data_provider = data_provider  # optional callable -> list[dict]
        self._rows_cache = []

        self.add_section("Data Set", self._build_main_layout())

        if csv_paths:
            self.set_csv_paths(csv_paths, refresh=False)
        
        logger.info(f"[DataSetTab] Initialized with study_uid={study_uid}")

    def _build_main_layout(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        # Header section with title, status, and refresh button
        header_layout = QHBoxLayout()
        
        # Title
        title_label = QLabel("Dataset Viewer")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #f7fafc;
                background: transparent;
            }
        """)
        header_layout.addWidget(title_label)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #6b7280;
                background: transparent;
                font-size: 12px;
                padding: 4px 8px;
            }
        """)
        header_layout.addWidget(self.status_label)
        
        header_layout.addStretch()
        
        # Refresh button
        self.refresh_btn = QPushButton()
        try:
            self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#3182ce'))
        except:
            pass
        self.refresh_btn.setText("Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #1a202c;
                border: 1px solid #2d3748;
                padding: 8px 16px;
                border-radius: 6px;
                color: #f7fafc;
                font-weight: bold;
            }
            QPushButton:hover { background: #2d3748; }
            QPushButton:pressed { background: #0b1015; }
        """)
        self.refresh_btn.clicked.connect(self.refresh)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Info label showing study UID
        if self.study_uid:
            info_label = QLabel(f"Study UID: {self.study_uid}")
            info_label.setStyleSheet("""
                QLabel {
                    color: #6b7280;
                    background: transparent;
                    font-size: 11px;
                    font-family: monospace;
                }
            """)
            layout.addWidget(info_label)
        
        # Table widget
        self.dataset_table = DataSetTableWidget()
        layout.addWidget(self.dataset_table)
        
        return layout

    # -----------------------------
    # Public API
    # -----------------------------
    def set_data_provider(self, fn):
        """fn: callable that returns list[dict] rows"""
        self._data_provider = fn

    def set_csv_paths(self, csv_paths, *, refresh=True):
        if not csv_paths:
            self._csv_paths = []
        elif isinstance(csv_paths, (str, os.PathLike)):
            self._csv_paths = [str(csv_paths)]
        else:
            self._csv_paths = [str(p) for p in csv_paths]

        if refresh:
            self.refresh()

    def _guess_attachment_dir(self):
        """
        Tries to locate: <attachment_path>/<study_uid>
        First tries ATTACHMENT_PATH from config, then falls back to project search
        """
        import os
        if not self.study_uid:
            logger.info("[DataSetTab] No study_uid provided")
            return None

        # Try to use ATTACHMENT_PATH from config
        try:
            from PacsClient.utils.config import ATTACHMENT_PATH
            from pathlib import Path
            attach_path = Path(ATTACHMENT_PATH) / self.study_uid
            if attach_path.exists() and attach_path.is_dir():
                logger.info(f"[DataSetTab] Found attachment dir via ATTACHMENT_PATH: {attach_path}")
                return str(attach_path)
            else:
                logger.info(f"[DataSetTab] Attachment dir not found at: {attach_path}")
        except Exception as e:
            logger.info(f"[DataSetTab] Could not use ATTACHMENT_PATH: {e}")

        # Fallback: search from current working directory
        candidates = []
        cwd = os.getcwd()

        # cwd/attachment/<uid>
        candidates.append(os.path.join(cwd, "attachment", self.study_uid))

        # parent/attachment/<uid> (up to 5 levels)
        p = cwd
        for _ in range(5):
            p = os.path.dirname(p)
            if not p or p == os.path.dirname(p):
                break
            candidates.append(os.path.join(p, "attachment", self.study_uid))

        for c in candidates:
            if os.path.isdir(c):
                logger.info(f"[DataSetTab] Found attachment dir via search: {c}")
                return c
        
        logger.info(f"[DataSetTab] No attachment directory found for study_uid: {self.study_uid}")
        logger.info(f"[DataSetTab] Searched candidates: {candidates[:3]}")
        return None


    def _auto_discover_csv_paths(self):
        import os, glob
        attach_dir = self._guess_attachment_dir()
        if not attach_dir:
            logger.info("[DataSetTab] Cannot auto-discover CSVs: attachment directory not found")
            return []

        csvs = sorted(glob.glob(os.path.join(attach_dir, "*.csv")))
        logger.info(f"[DataSetTab] Found {len(csvs)} CSV files in {attach_dir}")
        
        if not csvs:
            return []
        
        # prefer module-specific feedback and server-result CSVs first
        preferred = []
        rest = []
        for p in csvs:
            name = os.path.basename(p).lower()
            if self.module_mode == "bone_age":
                is_preferred = name in ("bone_age_feedback.csv", "bone_age.csv") or name.startswith("bone_age")
            elif self.module_mode == "mammography":
                is_preferred = (
                    name == "mg_feedback.csv"
                    or "updated_csv_with_boxes" in name
                    or "classification" in name
                    or "mammography" in name
                    or "dataset" in name
                )
            else:
                is_preferred = (
                    name in ("mg_feedback.csv", "bone_age_feedback.csv")
                    or "updated_csv_with_boxes" in name
                    or "classification" in name
                    or "dataset" in name
                )

            if is_preferred:
                preferred.append(p)
                logger.info(f"[DataSetTab]   ✓ Preferred: {os.path.basename(p)}")
            else:
                rest.append(p)
                logger.info(f"[DataSetTab]   - Other: {os.path.basename(p)}")
        
        result = preferred + rest
        logger.info(f"[DataSetTab] Auto-discovered {len(result)} CSV files")
        return result


    def set_rows(self, rows, *, cache=True):
        """Best option: Eagle Eye calls this with its results."""
        rows = [] if rows is None else list(rows)
        if cache:
            self._rows_cache = rows
        self.dataset_table.set_rows(rows)
        
        # Update status
        if rows:
            self._update_status(f"Displaying {len(rows)} rows", "success")
        else:
            self._update_status("No data to display", "warning")

    def append_rows(self, rows, *, cache=True):
        rows = [] if rows is None else list(rows)
        merged = (self._rows_cache + rows) if cache else (rows)
        self.set_rows(merged, cache=cache)

    def clear(self, *, cache=True):
        if cache:
            self._rows_cache = []
        self.dataset_table.clear()
        self._update_status("Data cleared", "info")

    def refresh(self):
        try:
            # Update status
            self._update_status("Loading data...", "loading")
            
            # Try data provider first
            if callable(self._data_provider):
                logger.info("[DataSetTab] Using data_provider")
                rows = self._data_provider() or []
                self.set_rows(rows, cache=True)
                if rows:
                    self._update_status(f"Loaded {len(rows)} rows from provider", "success")
                else:
                    self._update_status("Data provider returned no rows", "warning")
                return

            # Try cached rows only for provider/pushed datasets. CSV refresh should reread disk.
            if self._rows_cache and not self._csv_paths:
                logger.info(f"[DataSetTab] Using cached rows: {len(self._rows_cache)}")
                self.dataset_table.set_rows(self._rows_cache)
                self._update_status(f"Displaying {len(self._rows_cache)} cached rows", "success")
                return

            # ✅ auto-discover CSVs if none provided
            if not self._csv_paths:
                logger.info("[DataSetTab] Auto-discovering CSV files...")
                auto = self._auto_discover_csv_paths()
                if auto:
                    self._csv_paths = auto
                    logger.info(f"[DataSetTab] Auto-discovered CSVs: {self._csv_paths}")
                else:
                    logger.info("[DataSetTab] No CSV files auto-discovered")

            # Try to load from CSV paths
            if self._csv_paths:
                logger.info(f"[DataSetTab] Loading from CSV paths: {self._csv_paths}")
                rows = read_dataset_csvs(self._csv_paths)
                if rows:
                    self.set_rows(rows, cache=True)
                    self._update_status(f"Loaded {len(rows)} rows from {len(self._csv_paths)} CSV file(s)", "success")
                else:
                    self._update_status(f"No data found in {len(self._csv_paths)} CSV file(s)", "warning")
                return

            # No data found
            logger.info("[DataSetTab] No data source available")
            self.clear(cache=False)
            self._update_status("No data available. No CSV files found for this study.", "error")

        except Exception as e:
            logger.info(f"[DataSetTab] refresh() ERROR: {e}")
            import traceback
            traceback.print_exc()
            self._update_status(f"Error loading data: {str(e)}", "error")
    
    def _update_status(self, message: str, status_type: str = "info"):
        """Update status label with message and color based on type"""
        if not hasattr(self, 'status_label'):
            return
        
        colors = {
            "info": "#6b7280",
            "loading": "#3182ce",
            "success": "#10b981",
            "warning": "#f59e0b",
            "error": "#ef4444"
        }
        
        color = colors.get(status_type, colors["info"])
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background: transparent;
                font-size: 12px;
                padding: 4px 8px;
            }}
        """)
        logger.info(f"[DataSetTab] Status: {message}")
