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
        src = (source or "server").lower()
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
                    "date": str(row.get("date") or row.get("study_date") or "").strip(),
                    "time": str(row.get("time") or row.get("study_time") or "").strip(),
                    "description": str(row.get("description") or row.get("study_description") or "").strip(),
                    "report_status": str(row.get("report_status") or "pending").strip() or "pending",
                    "images_count": row.get("images_count"),
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
