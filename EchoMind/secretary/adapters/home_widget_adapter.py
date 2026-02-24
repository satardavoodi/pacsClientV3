from __future__ import annotations

import time
from typing import Any, Literal


class HomeWidgetAdapter:
    def __init__(self, home_widget=None):
        self.home = home_widget or self._try_get_home_widget()

    def _try_get_home_widget(self):
        try:
            from PacsClient.pacs.patient_tab.viewers.secretary_bridge import get_runtime_home_widget

            return get_runtime_home_widget()
        except Exception:
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget

                return get_home_widget()
            except Exception:
                return None

    def is_available(self) -> bool:
        return self.home is not None

    def get_active_source(self) -> Literal["local", "server", "import"]:
        if not self.home:
            return "server"
        try:
            tabs = self.home.data_access_panel_widget.tabs
            idx = tabs.currentIndex()
            text = (tabs.tabText(idx) or "").strip().lower()
            if "local" in text:
                return "local"
            if "server" in text:
                return "server"
            return "import"
        except Exception:
            return "server"

    def _set_active_source(self, source: str) -> None:
        if not self.home:
            return
        source = (source or "").lower()
        try:
            tabs = self.home.data_access_panel_widget.tabs
            mapping = {"local": 0, "server": 1, "import": 2}
            idx = mapping.get(source)
            if idx is not None and 0 <= idx < tabs.count() and tabs.currentIndex() != idx:
                tabs.setCurrentIndex(idx)
        except Exception:
            return

    def _set_modalities(self, modality_csv: str | None) -> None:
        if not self.home:
            return
        try:
            widget = self.home.patient_search_widget
            checks = getattr(widget, "modality_checks", None)
            if not isinstance(checks, dict):
                return
            for box in checks.values():
                try:
                    box.setChecked(False)
                except Exception:
                    pass
            if not modality_csv:
                return
            wanted = {m.strip().upper() for m in str(modality_csv).split(",") if m.strip()}
            for key, box in checks.items():
                if str(key).upper() in wanted:
                    try:
                        box.setChecked(True)
                    except Exception:
                        pass
        except Exception:
            return

    def search(self, source: str, criteria: dict[str, Any], timeout_s: int = 45) -> None:
        if not self.home:
            raise RuntimeError("Home widget is unavailable")
        src = (source or "server").lower().strip()
        if src in {"active_tab", "active", "current"}:
            src = self.get_active_source()
        self._set_active_source(src)

        payload = {
            "patient_id": str(criteria.get("patient_id") or ""),
            "patient_name": str(criteria.get("patient_name") or ""),
            "date_from": str(criteria.get("date_from") or "19000101"),
            "date_to": str(criteria.get("date_to") or "20991231"),
        }
        modality = criteria.get("modality")
        if modality:
            payload["modality"] = str(modality)

        try:
            self.home.patient_search_widget.set_search_data(payload)
            self._set_modalities(str(modality or ""))
        except Exception:
            pass

        self.home.patient_list_function_identifier(src)

        task = getattr(self.home, "_search_task", None)
        if task is None:
            return

        deadline = time.time() + max(1, int(timeout_s))
        while not task.done() and time.time() < deadline:
            try:
                from PySide6.QtWidgets import QApplication

                QApplication.processEvents()
            except Exception:
                pass
            time.sleep(0.05)

    def list_rows(self) -> list[dict[str, Any]]:
        if not self.home:
            return []
        try:
            rows = self.home.get_all_patient_data() or []
        except Exception:
            rows = []

        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "patient_id": str(row.get("patient_id") or "").strip(),
                    "patient_name": str(row.get("patient_name") or "").strip(),
                    "study_uid": str(row.get("study_uid") or "").strip(),
                    "modality": str(row.get("modality") or "").strip(),
                    "body_part": str(row.get("body_part") or "").strip(),
                    "date": str(row.get("date") or row.get("study_date") or "").strip(),
                    "time": str(row.get("time") or row.get("study_time") or "").strip(),
                    "description": str(row.get("description") or row.get("study_description") or "").strip(),
                    "report_status": str(row.get("report_status") or "pending").strip() or "pending",
                    "images_count": str(row.get("images_count") or "").strip(),
                }
            )
        return out

    def get_selected_row(self) -> dict[str, Any] | None:
        if not self.home:
            return None
        try:
            row = self.home.get_selected_patient_data()
            return row if isinstance(row, dict) else None
        except Exception:
            return None

    def open_patient(
        self,
        patient_id: str,
        patient_name: str,
        study_uid: str,
        report_status: str = "pending",
    ) -> None:
        if not self.home:
            raise RuntimeError("Home widget is unavailable")
        self.home._on_patient_double_clicked(patient_id, patient_name, study_uid, report_status)

    def download_studies(self, studies: list[dict[str, Any]], set_current_tab: bool = False) -> None:
        if not self.home:
            raise RuntimeError("Home widget is unavailable")
        self.home._on_download_requested(studies, set_current_tab=set_current_tab)

    # ──────────────────────────────────────────────────────────────────────────
    # Source-mode control
    # ──────────────────────────────────────────────────────────────────────────

    def set_source_mode(self, source: str) -> bool:
        """Switch the active data-source tab (local / server / import)."""
        try:
            self._set_active_source(source)
            return True
        except Exception:
            return False

    def trigger_import_dicom(self) -> bool:
        """Switch to Import tab and programmatically click the Select-Folder button."""
        if not self.home:
            return False
        try:
            self._set_active_source("import")
            dap = self.home.data_access_panel_widget
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, dap.select_folder_btn.click)
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Patient selection helpers
    # ──────────────────────────────────────────────────────────────────────────

    # Maps human-friendly column names → logical column index used by the table
    _SORT_COLUMN_MAP: dict[str, int] = {
        "date": 8,
        "study_date": 8,
        "time": 7,
        "study_time": 7,
        "images": 9,
        "images_count": 9,
        "image_count": 9,
        "modality": 10,
        "patient_name": 1,
        "name": 1,
        "patient_id": 2,
        "id": 2,
        "description": 12,
        "study_description": 12,
        "age": 11,
        "body_part": 3,
    }

    def sort_patients(self, column: str, order: str = "desc") -> bool:
        """Sort the patient list table by *column*.

        Parameters
        ----------
        column : str
            Logical column name (e.g. ``"date"``, ``"images_count"``).
        order : str
            ``"asc"`` or ``"desc"`` (default ``"desc"``).
        """
        if not self.home:
            return False
        try:
            col_idx = self._SORT_COLUMN_MAP.get((column or "").lower().strip())
            if col_idx is None:
                return False
            from PySide6.QtCore import Qt
            qt_order = Qt.AscendingOrder if (order or "").lower().startswith("asc") else Qt.DescendingOrder
            tw = self.home.patient_table_widget
            tw._programmatic_sort(col_idx, qt_order)
            return True
        except Exception:
            return False

    def select_rows_by_code(self, patient_code: str, uncheck_others: bool = True) -> int:
        """Check row(s) whose patient_id or patient_name matches *patient_code*.

        Returns the number of rows checked.
        """
        if not self.home:
            return 0
        try:
            tw = self.home.patient_table_widget
            if uncheck_others:
                tw.clear_all_selections()
            code = (patient_code or "").strip().lower()
            count = 0
            for row in range(tw.results_table.rowCount()):
                row_data = tw.get_patient_data_by_row(row)
                if not row_data:
                    continue
                pid = (row_data.get("patient_id") or "").lower()
                pname = (row_data.get("patient_name") or "").lower()
                if code in pid or code in pname:
                    tw.set_row_checked(row, True)
                    count += 1
            return count
        except Exception:
            return 0

    def select_top_n_rows(self, n: int, uncheck_others: bool = True) -> int:
        """Check the first *n* rows in current display order.

        Returns the number of rows checked.
        """
        if not self.home:
            return 0
        try:
            tw = self.home.patient_table_widget
            if uncheck_others:
                tw.clear_all_selections()
            total = tw.results_table.rowCount()
            limit = min(max(1, int(n)), total)
            for row in range(limit):
                tw.set_row_checked(row, True)
            return limit
        except Exception:
            return 0

    def get_checked_studies(self) -> list[dict[str, Any]]:
        """Return the list of studies that currently have their checkbox checked."""
        if not self.home:
            return []
        try:
            return self.home.patient_table_widget.get_selected_patient_data_list() or []
        except Exception:
            return []

    def trigger_download_selected(self, set_current_tab: bool = False) -> int:
        """Trigger a download of all currently checked rows.

        Returns the number of studies submitted for download.
        """
        if not self.home:
            return 0
        try:
            studies = self.get_checked_studies()
            if studies:
                self.download_studies(studies, set_current_tab=set_current_tab)
            return len(studies)
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Font size
    # ──────────────────────────────────────────────────────────────────────────

    def change_font_size(self, direction: str) -> bool:
        """Increase or decrease the patient-table font size.

        Parameters
        ----------
        direction : str
            ``"increase"`` / ``"up"`` / ``"larger"`` → +2 pt
            ``"decrease"`` / ``"down"`` / ``"smaller"`` → -2 pt
        """
        if not self.home:
            return False
        try:
            d = (direction or "").lower().strip()
            if d in ("increase", "up", "larger", "bigger", "more", "+"):
                delta = 2
            elif d in ("decrease", "down", "smaller", "less", "-"):
                delta = -2
            else:
                return False
            self.home.patient_table_widget._change_font_size(delta)
            return True
        except Exception:
            return False
