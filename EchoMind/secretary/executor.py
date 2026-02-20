from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from .adapters.home_widget_adapter import HomeWidgetAdapter
from .contracts import SecretaryActionPlan, SecretaryResult
from .resolver import compact_patient_row, resolve_patient_by_code


class SecretaryExecutor:
    def __init__(self, adapter: HomeWidgetAdapter):
        self.adapter = adapter

    @staticmethod
    def _to_yyyymmdd(raw: str) -> str:
        s = "".join(ch for ch in (raw or "") if ch.isdigit())
        if len(s) >= 8:
            return s[:8]
        return ""

    @staticmethod
    def _is_modality_match(value: str, target: str) -> bool:
        if not target:
            return True
        cur = (value or "").upper()
        want = (target or "").upper()
        if want == "MR":
            return "MR" in cur or "MRI" in cur
        return want in cur

    def _list_patients(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        if not self.adapter.is_available():
            return {
                "ok": False,
                "action": "list_patients",
                "message": "PACS home widget is not available.",
                "data": None,
                "error_code": "NO_HOME_WIDGET",
            }

        entities = plan.get("entities", {})
        source = str(entities.get("source") or self.adapter.get_active_source())
        today = datetime.now().strftime("%Y%m%d")
        date_filter = today if str(entities.get("date") or "").lower() == "today" else ""
        modality_filter = str(entities.get("modality") or "").upper()

        criteria: dict[str, Any] = {}
        if date_filter:
            criteria["date_from"] = date_filter
            criteria["date_to"] = date_filter
        if modality_filter:
            criteria["modality"] = modality_filter

        try:
            self.adapter.search(source=source, criteria=criteria)
        except Exception as exc:
            return {
                "ok": False,
                "action": "list_patients",
                "message": f"Search failed: {exc}",
                "data": None,
                "error_code": "SEARCH_FAILED",
            }

        rows = self.adapter.list_rows()
        filtered: list[dict[str, Any]] = []
        for row in rows:
            date_ok = True
            if date_filter:
                date_ok = self._to_yyyymmdd(str(row.get("date") or "")) == date_filter
            modality_ok = self._is_modality_match(str(row.get("modality") or ""), modality_filter) if modality_filter else True
            if date_ok and modality_ok:
                filtered.append(compact_patient_row(row))

        state["last_list"] = filtered
        return {
            "ok": True,
            "action": "list_patients",
            "message": f"Found {len(filtered)} patient(s) from {source} source.",
            "data": filtered,
            "error_code": None,
        }

    def _resolve_open_candidate(self, entities: dict[str, Any]) -> dict[str, Any]:
        candidate = entities.get("resolved_patient")
        if isinstance(candidate, dict):
            return {"status": "resolved", "matches": [compact_patient_row(candidate)]}

        code = str(entities.get("patient_code") or "").strip()
        if not code:
            return {"status": "missing_code", "matches": []}

        rows = self.adapter.list_rows()
        res = resolve_patient_by_code(rows, code)
        if res["status"] == "not_found":
            try:
                self.adapter.search(
                    source=self.adapter.get_active_source(),
                    criteria={"patient_id": code},
                )
            except Exception:
                pass
            rows = self.adapter.list_rows()
            res = resolve_patient_by_code(rows, code)
        return res

    def _resolve_download_candidate(self, entities: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        candidate = entities.get("resolved_patient")
        if isinstance(candidate, dict):
            return {"status": "resolved", "matches": [compact_patient_row(candidate)]}

        code = str(entities.get("patient_code") or "").strip()
        if code:
            res = resolve_patient_by_code(self.adapter.list_rows(), code)
            if res["status"] == "not_found":
                try:
                    self.adapter.search(
                        source=self.adapter.get_active_source(),
                        criteria={"patient_id": code},
                    )
                except Exception:
                    pass
                res = resolve_patient_by_code(self.adapter.list_rows(), code)
            return res

        last_row = state.get("last_patient")
        if isinstance(last_row, dict):
            return {"status": "resolved", "matches": [compact_patient_row(last_row)]}

        selected = self.adapter.get_selected_row()
        if isinstance(selected, dict):
            return {"status": "resolved", "matches": [compact_patient_row(selected)]}
        return {"status": "not_found", "matches": []}

    def _open_patient(self, plan: SecretaryActionPlan, state: dict[str, Any], confirmed: bool) -> SecretaryResult:
        if not self.adapter.is_available():
            return {
                "ok": False,
                "action": "open_patient",
                "message": "PACS home widget is not available.",
                "data": None,
                "error_code": "NO_HOME_WIDGET",
            }
        entities = plan.get("entities", {})
        resolved = self._resolve_open_candidate(entities)
        status = resolved.get("status")
        matches = resolved.get("matches", [])

        if status == "missing_code":
            return {
                "ok": False,
                "action": "open_patient",
                "message": "Patient code is required for opening a patient.",
                "data": None,
                "error_code": "MISSING_CODE",
            }
        if status == "not_found":
            return {
                "ok": False,
                "action": "open_patient",
                "message": "No patient found for that code.",
                "data": None,
                "error_code": "NOT_FOUND",
            }
        if status == "ambiguous":
            return {
                "ok": False,
                "action": "open_patient",
                "message": "Multiple patients matched this code.",
                "data": matches,
                "error_code": "AMBIGUOUS",
            }
        row = matches[0]
        if not confirmed:
            return {
                "ok": False,
                "action": "open_patient",
                "message": f"Confirm open patient {row.get('patient_id')} ({row.get('patient_name')}).",
                "data": {"candidate": row},
                "error_code": "CONFIRM_REQUIRED",
            }

        self.adapter.open_patient(
            patient_id=str(row.get("patient_id") or ""),
            patient_name=str(row.get("patient_name") or ""),
            study_uid=str(row.get("study_uid") or ""),
            report_status=str(row.get("report_status") or "pending"),
        )
        state["last_patient"] = deepcopy(row)
        return {
            "ok": True,
            "action": "open_patient",
            "message": f"Opened patient {row.get('patient_id')}.",
            "data": row,
            "error_code": None,
        }

    def _download_patient(self, plan: SecretaryActionPlan, state: dict[str, Any], confirmed: bool) -> SecretaryResult:
        if not self.adapter.is_available():
            return {
                "ok": False,
                "action": "download_patient",
                "message": "PACS home widget is not available.",
                "data": None,
                "error_code": "NO_HOME_WIDGET",
            }
        entities = plan.get("entities", {})
        resolved = self._resolve_download_candidate(entities, state)
        status = resolved.get("status")
        matches = resolved.get("matches", [])

        if status == "not_found":
            return {
                "ok": False,
                "action": "download_patient",
                "message": "No patient context found to download.",
                "data": None,
                "error_code": "NOT_FOUND",
            }
        if status == "ambiguous":
            return {
                "ok": False,
                "action": "download_patient",
                "message": "Multiple patients matched this request.",
                "data": matches,
                "error_code": "AMBIGUOUS",
            }
        row = matches[0]
        if not confirmed:
            return {
                "ok": False,
                "action": "download_patient",
                "message": f"Confirm download for patient {row.get('patient_id')} ({row.get('patient_name')}).",
                "data": {"candidate": row},
                "error_code": "CONFIRM_REQUIRED",
            }

        self.adapter.download_studies([row], set_current_tab=False)
        state["last_patient"] = deepcopy(row)
        return {
            "ok": True,
            "action": "download_patient",
            "message": f"Download queued for patient {row.get('patient_id')}.",
            "data": row,
            "error_code": None,
        }

    def execute(self, plan: SecretaryActionPlan, state: dict[str, Any], *, confirmed: bool = False) -> SecretaryResult:
        action = plan.get("action")
        if action == "list_patients":
            return self._list_patients(plan, state)
        if action == "open_patient":
            return self._open_patient(plan, state, confirmed=confirmed)
        if action == "download_patient":
            return self._download_patient(plan, state, confirmed=confirmed)
        return {
            "ok": False,
            "action": str(action or "unknown"),
            "message": "Unsupported action.",
            "data": None,
            "error_code": "UNSUPPORTED_ACTION",
        }
