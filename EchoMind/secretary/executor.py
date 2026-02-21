from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
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
    def _normalize_date_filter(raw: str) -> tuple[str, str]:
        """Return (date_from, date_to) in YYYYMMDD for supported tokens/ranges."""
        v = (raw or "").strip().lower()
        if not v:
            return "", ""

        now = datetime.now()
        if v == "today":
            d = now.strftime("%Y%m%d")
            return d, d
        if v == "yesterday":
            d = (now - timedelta(days=1)).strftime("%Y%m%d")
            return d, d

        # Handle "N days ago" / "N day ago" patterns (fallback if LLM returns relative)
        import re as _re
        _m = _re.match(r"(\d+)\s*days?\s*ago", v)
        if _m:
            d = (now - timedelta(days=int(_m.group(1)))).strftime("%Y%m%d")
            return d, d

        if ".." in v:
            left, right = v.split("..", 1)
            d1 = SecretaryExecutor._to_yyyymmdd(left)
            d2 = SecretaryExecutor._to_yyyymmdd(right)
            if d1 and d2:
                return (d1, d2) if d1 <= d2 else (d2, d1)
            return "", ""

        d = SecretaryExecutor._to_yyyymmdd(v)
        if d:
            return d, d
        return "", ""

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
        date_raw = str(entities.get("date") or "")
        date_from, date_to = self._normalize_date_filter(date_raw)
        modality_filter = str(entities.get("modality") or "").upper()

        criteria: dict[str, Any] = {}
        if date_from and date_to:
            criteria["date_from"] = date_from
            criteria["date_to"] = date_to
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
            if date_from and date_to:
                row_date = self._to_yyyymmdd(str(row.get("date") or ""))
                date_ok = bool(row_date) and date_from <= row_date <= date_to
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
        if action == "set_source_mode":
            return self._set_source_mode(plan, state)
        if action == "import_dicom":
            return self._import_dicom(plan, state)
        if action == "select_patient":
            return self._select_patient(plan, state)
        if action == "change_font_size":
            return self._change_font_size(plan, state)
        if action == "sort_patients":
            return self._sort_patients(plan, state)
        if action == "select_and_download":
            return self._select_and_download(plan, state, confirmed=confirmed)
        return {
            "ok": False,
            "action": str(action or "unknown"),
            "message": "Unsupported action.",
            "data": None,
            "error_code": "UNSUPPORTED_ACTION",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # New action handlers
    # ──────────────────────────────────────────────────────────────────────────

    def _set_source_mode(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        """Switch the active data-source tab."""
        if not self.adapter.is_available():
            return {"ok": False, "action": "set_source_mode", "message": "PACS home widget is not available.", "data": None, "error_code": "NO_HOME_WIDGET"}
        entities = plan.get("entities", {})
        mode = str(entities.get("mode") or entities.get("source") or "").lower().strip()
        if mode not in ("local", "server", "import"):
            return {"ok": False, "action": "set_source_mode", "message": f"Unknown source mode '{mode}'. Use local, server, or import.", "data": None, "error_code": "INVALID_MODE"}
        ok = self.adapter.set_source_mode(mode)
        return {"ok": ok, "action": "set_source_mode", "message": f"Source mode switched to '{mode}'." if ok else "Failed to switch mode.", "data": {"mode": mode}, "error_code": None if ok else "SWITCH_FAILED"}

    def _import_dicom(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        """Open the Import tab and trigger the folder-selection dialog."""
        if not self.adapter.is_available():
            return {"ok": False, "action": "import_dicom", "message": "PACS home widget is not available.", "data": None, "error_code": "NO_HOME_WIDGET"}
        ok = self.adapter.trigger_import_dicom()
        return {"ok": ok, "action": "import_dicom", "message": "Import panel opened. Please select the DICOM folder." if ok else "Failed to open import panel.", "data": None, "error_code": None if ok else "IMPORT_FAILED"}

    def _select_patient(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        """Select (check checkboxes) one or more patient rows."""
        if not self.adapter.is_available():
            return {"ok": False, "action": "select_patient", "message": "PACS home widget is not available.", "data": None, "error_code": "NO_HOME_WIDGET"}
        entities = plan.get("entities", {})
        code = str(entities.get("patient_code") or "").strip()
        limit = entities.get("limit")
        if code:
            count = self.adapter.select_rows_by_code(code)
            if count == 0:
                return {"ok": False, "action": "select_patient", "message": f"No patient found for code '{code}'.", "data": None, "error_code": "NOT_FOUND"}
            return {"ok": True, "action": "select_patient", "message": f"Selected {count} patient(s) matching '{code}'.", "data": {"selected_count": count}, "error_code": None}
        if limit is not None:
            try:
                n = int(limit)
            except (TypeError, ValueError):
                n = 1
            count = self.adapter.select_top_n_rows(n)
            return {"ok": True, "action": "select_patient", "message": f"Selected top {count} patient row(s).", "data": {"selected_count": count}, "error_code": None}
        return {"ok": False, "action": "select_patient", "message": "Provide patient_code or limit entity.", "data": None, "error_code": "MISSING_CRITERIA"}

    def _change_font_size(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        """Increase or decrease the patient list font size."""
        if not self.adapter.is_available():
            return {"ok": False, "action": "change_font_size", "message": "PACS home widget is not available.", "data": None, "error_code": "NO_HOME_WIDGET"}
        entities = plan.get("entities", {})
        direction = str(entities.get("direction") or "").lower().strip()
        if not direction:
            return {"ok": False, "action": "change_font_size", "message": "Provide direction: increase or decrease.", "data": None, "error_code": "MISSING_DIRECTION"}
        ok = self.adapter.change_font_size(direction)
        return {"ok": ok, "action": "change_font_size", "message": f"Font size {direction}d." if ok else f"Invalid direction '{direction}'.", "data": {"direction": direction}, "error_code": None if ok else "INVALID_DIRECTION"}

    def _sort_patients(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        """Sort the patient list table by a given column."""
        if not self.adapter.is_available():
            return {"ok": False, "action": "sort_patients", "message": "PACS home widget is not available.", "data": None, "error_code": "NO_HOME_WIDGET"}
        entities = plan.get("entities", {})
        column = str(entities.get("column") or "date").lower().strip()
        order = str(entities.get("order") or "desc").lower().strip()
        ok = self.adapter.sort_patients(column, order)
        if not ok:
            return {"ok": False, "action": "sort_patients", "message": f"Cannot sort by column '{column}'.", "data": None, "error_code": "INVALID_COLUMN"}
        return {"ok": True, "action": "sort_patients", "message": f"Sorted by '{column}' ({order}).", "data": {"column": column, "order": order}, "error_code": None}

    def _select_and_download(self, plan: SecretaryActionPlan, state: dict[str, Any], confirmed: bool = False) -> SecretaryResult:
        """Sort → select top-N → download in one step."""
        if not self.adapter.is_available():
            return {"ok": False, "action": "select_and_download", "message": "PACS home widget is not available.", "data": None, "error_code": "NO_HOME_WIDGET"}
        entities = plan.get("entities", {})
        sort_col = str(entities.get("sort_column") or entities.get("column") or "date").lower().strip()
        sort_order = str(entities.get("sort_order") or entities.get("order") or "desc").lower().strip()
        try:
            limit = int(entities.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10

        # Step 1 – sort (silently ignore if column unknown)
        self.adapter.sort_patients(sort_col, sort_order)

        # Step 2 – select top N
        selected = self.adapter.select_top_n_rows(limit)

        if selected == 0:
            return {"ok": False, "action": "select_and_download", "message": "No patient rows found to select.", "data": None, "error_code": "NO_ROWS"}

        if not confirmed:
            return {"ok": False, "action": "select_and_download",
                    "message": f"About to download top {selected} patient(s) sorted by {sort_col} {sort_order}. Confirm?",
                    "data": {"selected_count": selected, "sort_column": sort_col, "sort_order": sort_order},
                    "error_code": "CONFIRM_REQUIRED"}

        # Step 3 – download
        downloaded = self.adapter.trigger_download_selected()
        state["last_list"] = self.adapter.get_checked_studies()
        return {"ok": True, "action": "select_and_download",
                "message": f"Download queued for {downloaded} patient(s) (sorted by {sort_col} {sort_order}).",
                "data": {"downloaded_count": downloaded, "sort_column": sort_col, "sort_order": sort_order},
                "error_code": None}
