"""Patient and appointment read tools.

The CRM *operations* for these existed in ``config/operations.json`` but were
never registered as core tools — so no client could reach them through
``dispatch()``. These two close that gap (docs/RECEPTION_CRM_INTEGRATION.md §7.2).

Patient search deliberately uses the reception/PACS patient endpoint (the same
one the Android worklist already reads) rather than ``Patient/autoCheckNID``:
it supports name *and* national-code search and needs no clinic/center ids.

PHI: these tools return patient identifiers by design — that is what they are
for. They return the *minimum necessary* fields, never the full CRM record, and
the audit layer hashes the inputs.
"""

from __future__ import annotations

from typing import Any

from ...ino_api import InoClient
from ..registry import ToolRegistry
from ..types import ToolDefinition

MAX_LIMIT = 50


def register_patient_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="patients.search",
            kind="skill",
            handler=_patient_search,
            description=(
                "Find a patient by name or national code. Returns identifiers and the most recent "
                "reception. Use this before any patient-scoped action — never guess a patient id."
            ),
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "patientName": {"type": "string"},
                    "nationalCode": {"type": "string"},
                    "receptionId": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        )
    )
    registry.register(
        ToolDefinition(
            name="appointments.list",
            kind="skill",
            handler=_appointments_list,
            description="List patients waiting for an appointment (the scheduling queue).",
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "required": [],
                "properties": {
                    "modality": {"type": "string"},
                    "page": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        )
    )


def _client() -> InoClient:
    client = InoClient.from_env()
    client.login()
    return client


def _patient_search(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("patientName") or "").strip()
    national_code = str(args.get("nationalCode") or "").strip()
    reception_id = str(args.get("receptionId") or "").strip()
    if not (name or national_code or reception_id):
        raise ValueError("Provide patientName, nationalCode, or receptionId.")

    limit = max(1, min(int(args.get("limit") or 10), MAX_LIMIT))
    # Annotated because the literal makes it `dict[str, int]` and every filter
    # added below is a string. Harmless at run time, but it left three honest
    # lines flagged as type errors, and a checker whose findings are mostly
    # false is one nobody reads.
    params: dict[str, Any] = {"page": 1, "limit": limit}
    if name:
        params["patientName"] = name
    if national_code:
        params["nationalCode"] = national_code
    if reception_id:
        params["receptionId"] = reception_id

    raw = _client().get_json("/api/pacs/patients", params)
    rows = raw.get("data") if isinstance(raw, dict) else raw
    rows = rows if isinstance(rows, list) else []
    return {
        "skill": "patients.search",
        "query": {k: v for k, v in params.items() if k not in {"page", "limit"}},
        "count": len(rows),
        "matches": [_patient_row(row) for row in rows[:limit]],
        "note": (
            "A patient obtained from a spoken command must be confirmed on screen by name and "
            "national code before any write. Voice may search; voice may not identify."
        ),
    }


def _nested(row: dict[str, Any], key: str) -> dict[str, Any]:
    """The nested object at `key`, or an empty one.

    The reception API returns `patient` and `modality` as either an embedded
    object or a bare id depending on the endpoint, so every read of them needs
    the isinstance guard. Written inline it called `row.get(key)` twice and left
    the result typed `Any | dict | None`, which made four honest field reads
    look like possible `None.get` crashes.
    """
    value = row.get(key)
    return value if isinstance(value, dict) else {}


def _patient_row(row: dict[str, Any]) -> dict[str, Any]:
    patient = _nested(row, "patient")
    modality = _nested(row, "modality")
    return {
        "reception_id": row.get("receptionID") or row.get("receptionId") or row.get("_id"),
        "workflow_id": row.get("receptionId"),
        "patient_name": patient.get("Name") or patient.get("name") or row.get("patientName"),
        "national_code": patient.get("NationalID") or patient.get("nationalCode") or row.get("nationalCode"),
        "age": patient.get("Age"),
        "modality": modality.get("name") or modality.get("Modality") or row.get("modality"),
        "date": row.get("date"),
        "workflow_status": row.get("workflowStatus"),
    }


def _appointments_list(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "page": int(args.get("page") or 1),
        "limit": max(1, min(int(args.get("limit") or 20), 100)),
    }
    if args.get("modality"):
        params["modality"] = str(args["modality"])

    raw = _client().get_json("/api/imagingWorkflow/workflow/waiting-appointment", params)
    rows = raw.get("data") if isinstance(raw, dict) else raw
    rows = rows if isinstance(rows, list) else []
    return {
        "skill": "appointments.list",
        "count": len(rows),
        "rows": [_patient_row(row) for row in rows],
        "pagination": raw.get("pagination") if isinstance(raw, dict) else None,
    }
