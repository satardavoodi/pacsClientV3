from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from .adapters.home_widget_adapter import HomeWidgetAdapter
from .contracts import SecretaryActionPlan, SecretaryResult
from .resolver import compact_patient_row, resolve_patient_by_code
from .workflow import ExecutionCall, drive_steps, drive_steps_async


def _bus_bridge_enabled() -> bool:
    """CommandBus routing for non-home actions is ON by default.

    Escape hatch: ``AIPACS_SECRETARY_BUS=0`` restores the pre-2026-06-06
    behavior (every non-home action returns UNSUPPORTED_ACTION)."""
    return os.environ.get("AIPACS_SECRETARY_BUS", "").strip().lower() not in (
        "0", "false", "off",
    )


def _assistant_bus_mode() -> str:
    """Company command execution always uses the local assistant policy."""
    return "assistant"


class SecretaryExecutor:
    def __init__(
        self,
        adapter: HomeWidgetAdapter,
        command_bus_getter: Optional[Callable[[], Any]] = None,
    ):
        self.adapter = adapter
        # Resolved lazily on every non-home action so construction order
        # doesn't matter (the home panel builds its CommandBus during
        # startup; the orchestrator may be constructed before or after).
        self._command_bus_getter = command_bus_getter

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
        return drive_steps(self._list_patients_steps(plan, state))

    def _list_patients_steps(self, plan: SecretaryActionPlan, state: dict[str, Any]) -> SecretaryResult:
        # A failed replacement search must not leave an older ordinal target.
        state.pop("last_list_source", None)
        if not self.adapter.is_available():
            return {
                "ok": False,
                "action": "list_patients",
                "message": "PACS home widget is not available.",
                "data": None,
                "error_code": "NO_HOME_WIDGET",
            }

        entities = plan.get("entities", {})
        source = str(entities.get("source") or "").strip().lower()
        if not source or source in {"active_tab", "active", "current"}:
            source = self.adapter.get_active_source()
        date_raw = str(entities.get("date") or "")
        date_from, date_to = self._normalize_date_filter(date_raw)
        if entities.get("date_from") or entities.get("date_to"):
            date_from = self._to_yyyymmdd(str(entities.get("date_from") or ""))
            date_to = self._to_yyyymmdd(str(entities.get("date_to") or ""))
            try:
                datetime.strptime(date_from, "%Y%m%d")
                datetime.strptime(date_to, "%Y%m%d")
                if date_from > date_to:
                    raise ValueError("reversed range")
            except ValueError:
                return {"ok": False, "action": "list_patients", "message": "Invalid search date range; no search was started.", "data": None, "error_code": "INVALID_DATE_RANGE"}
        modality_filter = str(entities.get("modality") or "").upper()

        criteria: dict[str, Any] = {}
        if date_from and date_to:
            criteria["date_from"] = date_from
            criteria["date_to"] = date_to
        if modality_filter:
            criteria["modality"] = modality_filter

        try:
            (yield ExecutionCall(self.adapter.search, getattr(self.adapter, "search_async", self.adapter.search), kwargs={"source": source, "criteria": criteria}))
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

        state["last_list"] = deepcopy(filtered)
        state["last_list_source"] = source
        return {
            "ok": True,
            "action": "list_patients",
            "message": f"Found {len(filtered)} patient(s) from {source} source.",
            "data": filtered,
            "error_code": None,
        }

    def _resolve_open_candidate(self, entities: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        return drive_steps(self._resolve_open_candidate_steps(entities, state))

    def _resolve_open_candidate_steps(self, entities: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        if "row_index" in entities:
            index = entities["row_index"]
            source = state.get("last_list_source")
            requested_source = entities.get("source", "active_tab")
            rows = state.get("last_list")
            if (type(index) is not int or not 1 <= index <= 10000
                    or "patient_code" in entities or "resolved_patient" in entities
                    or not source or source != self.adapter.get_active_source()
                    or requested_source not in (source, "active_tab", "active", "current", "")
                    or not isinstance(rows, list) or index > len(rows)):
                return {"status": "invalid_list_context", "matches": []}
            row = compact_patient_row(rows[index - 1])
            # Resolve by immutable study identity, never by a potentially re-sorted index.
            if not row["patient_id"] or not row["study_uid"]:
                return {"status": "invalid_list_context", "matches": []}
            matches = [compact_patient_row(current) for current in self.adapter.list_rows()
                       if str(current.get("patient_id") or "").strip() == row["patient_id"]
                       and str(current.get("study_uid") or "").strip() == row["study_uid"]]
            if len(matches) != 1:
                return {"status": "invalid_list_context", "matches": []}
            return {"status": "resolved", "matches": matches}

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
                (yield ExecutionCall(self.adapter.search, getattr(self.adapter, "search_async", self.adapter.search), kwargs={"source": self.adapter.get_active_source(), "criteria": {"patient_id": code}}))
            except Exception:
                return {"status": "not_found", "matches": []}
            rows = self.adapter.list_rows()
            res = resolve_patient_by_code(rows, code)
        return res

    def _resolve_download_candidate(self, entities: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        return drive_steps(self._resolve_download_candidate_steps(entities, state))

    def _resolve_download_candidate_steps(self, entities: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        candidate = entities.get("resolved_patient")
        if isinstance(candidate, dict):
            return {"status": "resolved", "matches": [compact_patient_row(candidate)]}

        code = str(entities.get("patient_code") or "").strip()
        if code:
            res = resolve_patient_by_code(self.adapter.list_rows(), code)
            if res["status"] == "not_found":
                try:
                    (yield ExecutionCall(self.adapter.search, getattr(self.adapter, "search_async", self.adapter.search), kwargs={"source": self.adapter.get_active_source(), "criteria": {"patient_id": code}}))
                except Exception:
                    return {"status": "not_found", "matches": []}
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
        return drive_steps(self._open_patient_steps(plan, state, confirmed))

    def _open_patient_steps(self, plan: SecretaryActionPlan, state: dict[str, Any], confirmed: bool) -> SecretaryResult:
        if not self.adapter.is_available():
            return {
                "ok": False,
                "action": "open_patient",
                "message": "PACS home widget is not available.",
                "data": None,
                "error_code": "NO_HOME_WIDGET",
            }
        entities = plan.get("entities", {})
        if entities.get('list_id'):
            result = self._try_command_bus(plan, state, confirmed=confirmed)
            return result or {'ok': False, 'action': 'open_patient', 'data': None,
                'error_code': 'CONTROL_UNAVAILABLE', 'message': 'The patient-opening control is unavailable.'}
        resolved = (yield from self._resolve_open_candidate_steps(entities, state))
        status = resolved.get("status")
        matches = resolved.get("matches", [])

        if status == "invalid_list_context":
            return {"ok": False, "action": "open_patient", "data": None,
                    "message": "List context is missing or changed. Refresh the patient list before opening a row.",
                    "error_code": "INVALID_LIST_CONTEXT"}
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
        return drive_steps(self._download_patient_steps(plan, state, confirmed))

    def _download_patient_steps(self, plan: SecretaryActionPlan, state: dict[str, Any], confirmed: bool) -> SecretaryResult:
        if not self.adapter.is_available():
            return {
                "ok": False,
                "action": "download_patient",
                "message": "PACS home widget is not available.",
                "data": None,
                "error_code": "NO_HOME_WIDGET",
            }
        entities = plan.get("entities", {})
        resolved = (yield from self._resolve_download_candidate_steps(entities, state))
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
        return drive_steps(self.execute_steps(plan, state, confirmed=confirmed))

    async def execute_async(self, plan, state, *, confirmed=False):
        return await drive_steps_async(self.execute_steps(plan, state, confirmed=confirmed))

    def execute_steps(self, plan: SecretaryActionPlan, state: dict[str, Any], *, confirmed: bool = False) -> SecretaryResult:
        action = plan.get("action")
        if action == "list_patients":
            return (yield from self._list_patients_steps(plan, state))
        if action == "open_patient":
            return (yield from self._open_patient_steps(plan, state, confirmed=confirmed))
        if action == "download_patient":
            return (yield from self._download_patient_steps(plan, state, confirmed=confirmed))
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

        # ── CommandBus bridge (2026-06-06) ───────────────────────────────
        # Non-home actions (module launch, viewer navigation, download
        # control, reporting workflow) route to the app's CommandBus, which
        # already implements them in-process on live widgets. Previously
        # every such action returned UNSUPPORTED_ACTION here, capping the
        # voice assistant at the home-panel set. The 9 home actions above
        # are untouched.
        bus_result = self._try_command_bus(plan, state, confirmed=confirmed)
        if bus_result is not None:
            return bus_result

        return {
            "ok": False,
            "action": str(action or "unknown"),
            "message": "Unsupported action.",
            "data": None,
            "error_code": "UNSUPPORTED_ACTION",
        }

    # ──────────────────────────────────────────────────────────────────────
    # CommandBus routing for non-home actions
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_bus(self) -> Any:
        getter = self._command_bus_getter
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def _try_command_bus(
        self,
        plan: SecretaryActionPlan,
        state: dict[str, Any],
        confirmed: bool = False,
    ) -> SecretaryResult | None:
        """Route an action the home executor doesn't own to the CommandBus.

        Returns None when the bridge is disabled, no bus is available, or the
        bus doesn't register the action — the caller then falls through to
        the legacy UNSUPPORTED_ACTION result. Never raises.
        """
        action = str(plan.get("action") or "").strip()
        if not action or not _bus_bridge_enabled():
            return None
        bus = self._resolve_bus()
        if bus is None:
            return None
        # Confirmation gate for sensitive bus actions (e.g. PACS send): reuse
        # the Secretary's existing confirm turn — _run_plan stores the pending
        # plan on CONFIRM_REQUIRED and re-executes it with confirmed=True
        # after the user replies "yes".
        from .validator import _BUS_CONFIRM_REQUIRED_ACTIONS
        if action in _BUS_CONFIRM_REQUIRED_ACTIONS and not confirmed:
            return {
                "ok": False,
                "action": action,
                "message": (
                    f"Confirm '{action.replace('_', ' ')}' for the current "
                    "patient? Reply yes to continue or no to cancel."
                ),
                "data": None,
                "error_code": "CONFIRM_REQUIRED",
            }
        try:
            registry = getattr(bus, "registry", None)
            if registry is None or not registry.has_action(action):
                return None
            from .command_envelope import CommandPlan

            cmd_plan = CommandPlan(
                action=action,
                entities=dict(plan.get("entities") or {}),
                confidence=float(plan.get("confidence") or 1.0),
                needs_confirmation=bool(plan.get("needs_confirmation")),
                reason=str(plan.get("reason") or "secretary bus bridge"),
            )
            # Local assistant policy is authoritative; a proposal/session cannot
            # promote itself to QA or unrestricted. Keep transient flags local.
            bus_state = dict(state or {})
            bus_state["confirmed"] = bool(confirmed)
            bus_state["agent_mode"] = _assistant_bus_mode()
            result = bus.execute(cmd_plan, bus_state)
        except Exception as exc:  # noqa: BLE001 — degrade to a typed error
            return {
                "ok": False,
                "action": action,
                "message": f"Command bus execution failed: {exc}",
                "data": None,
                "error_code": "BUS_EXECUTION_FAILED",
            }
        try:
            data = result.data
            if data is not None and not isinstance(data, (dict, list)):
                data = {"value": data}
            return {
                "ok": bool(result.ok),
                "action": str(result.action or action),
                "message": str(result.message or ""),
                "data": data,
                "error_code": result.error_code,
            }
        except Exception:
            return {
                "ok": False,
                "action": action,
                "message": "Command bus returned an unreadable result.",
                "data": None,
                "error_code": "BUS_BAD_RESULT",
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
            if count <= 0:
                return {"ok": False, "action": "select_patient", "message": "No patient rows were selected.", "data": {"selected_count": 0}, "error_code": "NOT_FOUND"}
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
