"""DownloadAdapter — plan-shaped wrapper over the Zeta DownloadManager widget.

Wraps the existing public surface:

* ``DownloadManagerWidget.add_downloads(studies, start_immediately)``
* ``...pause_study(study_uid)`` / ``resume_study`` / ``cancel_study``
* ``state_store.get(study_uid)`` / ``get_all_downloads()``
* ``state_store.get_statistics()``

No DM internals are touched — every method already exists on the widget
or its state store. This adapter just exposes them as CommandPlan
actions so tests + the agent SDK can call them through the bus.

Actions exposed
---------------
``download_patient`` (single patient by id — same key the HomeAdapter
uses, the registry overrides Home's binding when both are registered)
``cancel_download``  — by study_uid
``pause_download``   — by study_uid
``resume_download``  — by study_uid
``check_download_status`` — single study_uid → state dict
``list_downloads``   — all states; optional ``status_filter``
``download_statistics`` — counts + bytes per state
"""
from __future__ import annotations

import logging
from typing import Any

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


class DownloadCommandAdapter:
    """Plan-shaped façade over the DM widget."""

    SUPPORTED_ACTIONS: tuple[str, ...] = (
        "cancel_download",
        "pause_download",
        "resume_download",
        "check_download_status",
        "list_downloads",
        "download_statistics",
    )

    def __init__(self, dm_widget: Any = None, state_store: Any = None):
        """``dm_widget`` and ``state_store`` are typically the live
        instances. Tests pass mocks.
        """
        self._dm = dm_widget
        self._store = state_store or getattr(dm_widget, "state_store", None)

    # ── helpers ──────────────────────────────────────────────────────
    def _no_dm(self, action: str) -> CommandResult:
        return CommandResult(
            ok=False, action=action,
            message="DownloadManager widget is not available.",
            error_code="NO_DM_WIDGET",
        )

    def _no_store(self, action: str) -> CommandResult:
        return CommandResult(
            ok=False, action=action,
            message="DM state_store is not available.",
            error_code="NO_STATE_STORE",
        )

    def _require_uid(self, action: str, plan: CommandPlan) -> str | CommandResult:
        ent = plan.entities or {}
        uid = str(ent.get("study_uid") or ent.get("uid") or "").strip()
        if not uid:
            return CommandResult(
                ok=False, action=action,
                message=f"{action} requires entities.study_uid",
                error_code="MISSING_STUDY_UID",
            )
        return uid

    @staticmethod
    def _state_to_dict(state: Any) -> dict:
        """Render a DownloadState into a JSON-friendly dict.

        Defensive: read attributes by ``getattr`` so a state-store with
        different field names still produces something useful.
        """
        if state is None:
            return {}
        out: dict[str, Any] = {}
        for attr in ("study_uid", "status", "priority", "patient_id",
                     "patient_name", "modality", "study_date",
                     "study_description", "total_count",
                     "total_series_count", "downloaded_count",
                     "progress_percent", "bytes_downloaded",
                     "bytes_total", "elapsed_s", "error_message"):
            v = getattr(state, attr, None)
            if v is None:
                continue
            # Enum → string
            if hasattr(v, "value"):
                out[attr] = v.value
            elif hasattr(v, "name"):
                out[attr] = v.name
            else:
                out[attr] = v
        return out

    # ── action: cancel / pause / resume ──────────────────────────────
    def _act_on_study(self, action: str, method_name: str,
                      plan: CommandPlan) -> CommandResult:
        if self._dm is None:
            return self._no_dm(action)
        uid_or_err = self._require_uid(action, plan)
        if isinstance(uid_or_err, CommandResult):
            return uid_or_err
        uid = uid_or_err
        method = getattr(self._dm, method_name, None)
        if not callable(method):
            return CommandResult(
                ok=False, action=action,
                message=f"DM exposes no {method_name} method",
                error_code="DM_INCOMPLETE",
            )
        try:
            method(uid)
        except Exception as exc:
            return CommandResult(
                ok=False, action=action,
                message=f"{method_name}({uid[:24]}…) failed: {exc}",
                error_code="DM_ACTION_FAILED",
            )
        return CommandResult(
            ok=True, action=action,
            message=f"{action} → {uid[:24]}…",
            data={"study_uid": uid},
        )

    def cancel_download(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._act_on_study("cancel_download", "cancel_study", plan)

    def pause_download(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._act_on_study("pause_download", "pause_study", plan)

    def resume_download(self, plan: CommandPlan, state: dict) -> CommandResult:
        return self._act_on_study("resume_download", "resume_study", plan)

    # ── action: check_download_status ────────────────────────────────
    def check_download_status(self, plan: CommandPlan, state: dict) -> CommandResult:
        if self._store is None:
            return self._no_store("check_download_status")
        uid_or_err = self._require_uid("check_download_status", plan)
        if isinstance(uid_or_err, CommandResult):
            return uid_or_err
        uid = uid_or_err
        try:
            s = self._store.get(uid)
        except Exception as exc:
            return CommandResult(
                ok=False, action="check_download_status",
                message=f"state lookup failed: {exc}",
                error_code="STATE_READ_FAILED",
            )
        if s is None:
            return CommandResult(
                ok=False, action="check_download_status",
                message=f"no state for study {uid[:24]}…",
                error_code="UNKNOWN_STUDY",
            )
        return CommandResult(
            ok=True, action="check_download_status",
            message=f"state for {uid[:24]}…",
            data={"study_uid": uid, "state": self._state_to_dict(s)},
        )

    # ── action: list_downloads ───────────────────────────────────────
    def list_downloads(self, plan: CommandPlan, state: dict) -> CommandResult:
        if self._store is None:
            return self._no_store("list_downloads")
        ent = plan.entities or {}
        status_filter = (ent.get("status") or "").strip().lower()
        try:
            all_states = self._store.get_all() or []
        except Exception as exc:
            return CommandResult(
                ok=False, action="list_downloads",
                message=f"state list failed: {exc}",
                error_code="STATE_READ_FAILED",
            )
        rows = [self._state_to_dict(s) for s in all_states]
        if status_filter:
            rows = [r for r in rows
                    if (str(r.get("status") or "").lower() == status_filter)]
        return CommandResult(
            ok=True, action="list_downloads",
            message=f"{len(rows)} downloads (filter={status_filter or 'none'})",
            data={"rows": rows, "count": len(rows),
                  "status_filter": status_filter or None},
        )

    # ── action: download_statistics ──────────────────────────────────
    def download_statistics(self, plan: CommandPlan, state: dict) -> CommandResult:
        if self._store is None:
            return self._no_store("download_statistics")
        try:
            stats = self._store.get_statistics() or {}
        except Exception as exc:
            return CommandResult(
                ok=False, action="download_statistics",
                message=f"statistics failed: {exc}",
                error_code="STATE_READ_FAILED",
            )
        return CommandResult(
            ok=True, action="download_statistics",
            message=f"{stats.get('total', 0)} downloads tracked",
            data=stats if isinstance(stats, dict) else {"raw": stats},
        )


__all__ = ["DownloadCommandAdapter"]
