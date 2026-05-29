"""Plan-shaped wrapper around the existing HomeWidgetAdapter.

The legacy ``HomeWidgetAdapter`` exposes Python methods like ``search``,
``open_patient``, ``download_patient`` whose signatures predate the
Command Layer. This shim adapts those methods to the ``(plan, state) ->
CommandResult`` contract that ``AdapterRegistry`` expects.

No GUI code is touched here — we just route plan entities into the
existing adapter's args and wrap return values in ``CommandResult``.
"""

from __future__ import annotations

import logging
from typing import Any

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


class HomeCommandAdapter:
    """Plan-shaped façade over ``HomeWidgetAdapter``.

    Constructed once at HomeWidget startup. Register its methods in the
    project's AdapterRegistry like so::

        registry.register(
            name="home",
            adapter=HomeCommandAdapter(legacy_home_widget_adapter),
            actions={
                "list_patients":   "list_patients",
                "open_patient":    "open_patient",
                "download_patient":"download_patient",
            },
        )
    """

    # Action names that map to this adapter (matches catalog/modules/homepage.md
    # and download.md). Useful for tests + introspection.
    SUPPORTED_ACTIONS: tuple[str, ...] = (
        "list_patients",
        "open_patient",
        "download_patient",
    )

    def __init__(self, home_widget_adapter: Any):
        """``home_widget_adapter`` is the legacy ``HomeWidgetAdapter``."""
        self._home = home_widget_adapter

    # ── helpers ──────────────────────────────────────────────────────
    def _available(self, action: str) -> CommandResult | None:
        if not self._home or not getattr(self._home, "is_available", lambda: False)():
            return CommandResult(
                ok=False, action=action,
                message="PACS home widget is not available.",
                error_code="NO_HOME_WIDGET",
            )
        return None

    # ── action: list_patients ────────────────────────────────────────
    def list_patients(self, plan: CommandPlan, state: dict) -> CommandResult:
        guard = self._available("list_patients")
        if guard is not None:
            return guard
        ent = plan.entities or {}
        criteria: dict[str, Any] = {
            "patient_id":   str(ent.get("patient_id") or ""),
            "patient_name": str(ent.get("patient_name") or ""),
            "date_from":    str(ent.get("date_from") or ""),
            "date_to":      str(ent.get("date_to") or ""),
        }
        modality = ent.get("modality")
        if modality:
            criteria["modality"] = str(modality)
        source = str(ent.get("source") or "active_tab")
        try:
            self._home.search(source=source, criteria=criteria)
        except Exception as exc:
            return CommandResult(
                ok=False, action="list_patients",
                message=f"search failed: {exc}",
                error_code="HOME_SEARCH_FAILED",
            )
        # Try to surface the post-search row count if the adapter exposes it.
        rows: list = []
        for attr in ("read_patient_rows", "get_patient_rows", "patient_rows"):
            getter = getattr(self._home, attr, None)
            if callable(getter):
                try:
                    rows = list(getter() or [])
                    break
                except Exception:
                    rows = []
        return CommandResult(
            ok=True,
            action="list_patients",
            message=f"Listed {len(rows)} patients" if rows else "Search submitted",
            data={"rows": rows, "count": len(rows), "criteria": criteria},
        )

    # ── action: open_patient ─────────────────────────────────────────
    def open_patient(self, plan: CommandPlan, state: dict) -> CommandResult:
        guard = self._available("open_patient")
        if guard is not None:
            return guard
        ent = plan.entities or {}
        patient_id = str(ent.get("patient_id") or ent.get("id") or "")
        if not patient_id:
            return CommandResult(
                ok=False, action="open_patient",
                message="open_patient requires entities.patient_id",
                error_code="MISSING_PATIENT_ID",
            )
        # Delegate to the existing adapter. Some installs expose
        # open_patient_by_id; fall back to open_patient.
        method = (
            getattr(self._home, "open_patient_by_id", None)
            or getattr(self._home, "open_patient", None)
        )
        if not callable(method):
            return CommandResult(
                ok=False, action="open_patient",
                message="HomeWidgetAdapter exposes no open_patient method",
                error_code="ADAPTER_INCOMPLETE",
            )
        try:
            payload = method(patient_id) if method.__code__.co_argcount <= 2 else method(patient_id, ent)
        except Exception as exc:
            return CommandResult(
                ok=False, action="open_patient",
                message=f"open_patient failed: {exc}",
                error_code="HOME_OPEN_FAILED",
            )
        return CommandResult(
            ok=True, action="open_patient",
            message=f"Opened patient {patient_id}",
            data={"patient_id": patient_id, "payload": payload},
        )

    # ── action: download_patient ─────────────────────────────────────
    def download_patient(self, plan: CommandPlan, state: dict) -> CommandResult:
        guard = self._available("download_patient")
        if guard is not None:
            return guard
        ent = plan.entities or {}
        # Accept either a single patient_id or a list of patient_ids.
        ids = ent.get("patient_ids")
        if ids is None:
            single = ent.get("patient_id") or ent.get("id")
            ids = [single] if single else []
        ids = [str(x) for x in ids if x]
        if not ids:
            return CommandResult(
                ok=False, action="download_patient",
                message="download_patient requires patient_id(s) in entities",
                error_code="MISSING_PATIENT_ID",
            )
        method = (
            getattr(self._home, "download_patients", None)
            or getattr(self._home, "download_patient", None)
        )
        if not callable(method):
            return CommandResult(
                ok=False, action="download_patient",
                message="HomeWidgetAdapter exposes no download_patient method",
                error_code="ADAPTER_INCOMPLETE",
            )
        try:
            payload = method(ids) if len(ids) > 1 else method(ids[0])
        except Exception as exc:
            return CommandResult(
                ok=False, action="download_patient",
                message=f"download failed: {exc}",
                error_code="HOME_DOWNLOAD_FAILED",
            )
        return CommandResult(
            ok=True, action="download_patient",
            message=f"Enqueued {len(ids)} download(s)",
            data={"patient_ids": ids, "count": len(ids), "payload": payload},
        )


__all__ = ["HomeCommandAdapter"]
