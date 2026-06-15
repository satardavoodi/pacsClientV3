"""ViewerCommandAdapter — STRICTLY READ-ONLY surface over the patient
viewer tabs.

Designed to be *structurally incapable* of breaking the multi-study
guardrails listed in ``docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`` §"Regression
guardrails": every method on this adapter reads attributes and returns
data; none touch `change_series_on_viewer`, `_rebuild_multistudy_series_index`,
or any state-mutating path.

Write-side actions (change layout, change series on a viewport, scroll,
toggle sync, set window/level) will land in a separate adapter once the
write-path multi-study invariants have their own dedicated tests. Until
then, callers wanting to mutate viewer state continue using the existing
GUI paths.

Read actions exposed
---------------------
``viewer.get_active_tab`` — study/patient currently in front, plus the
viewport layout dimensions
``viewer.list_open_tabs`` — what's open in the tab widget
``viewer.get_thumbnails_data`` — read-only list of series metadata for
the active patient
``viewer.get_active_series`` — series UID + number on the focused
viewport
``viewer.get_multistudy_info`` — for the active patient: list of
``{study_uid, series_count, is_primary}`` rows
"""
from __future__ import annotations

import logging
from typing import Any

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


class ViewerCommandAdapter:
    """Read-only viewer-state probe.

    Constructed once at app startup with a callable that returns the
    currently-active patient tab widget (or None when no patient is
    open). The adapter dereferences the widget on each call so it sees
    the LIVE active tab, not a stale one.
    """

    SUPPORTED_ACTIONS: tuple[str, ...] = (
        "get_active_tab",
        "list_open_tabs",
        "get_thumbnails_data",
        "get_active_series",
        "get_multistudy_info",
    )

    def __init__(self, get_active_patient_tab=None, get_main_tab_widget=None):
        """``get_active_patient_tab()`` returns the currently-active
        ``PatientWidget`` instance, or None. ``get_main_tab_widget()``
        returns the QTabWidget hosting all open tabs (for ``list_open_tabs``).
        """
        self._get_active = get_active_patient_tab or (lambda: None)
        self._get_main_tabs = get_main_tab_widget or (lambda: None)

    # ── helpers ──────────────────────────────────────────────────────
    def _no_active(self, action: str) -> CommandResult:
        return CommandResult(
            ok=False, action=action,
            message="No active patient tab.",
            error_code="NO_ACTIVE_TAB",
        )

    @staticmethod
    def _read_attr(obj: Any, name: str, default: Any = None) -> Any:
        return getattr(obj, name, default)

    @staticmethod
    def _is_multistudy(tab: Any) -> bool:
        """The MULTI_STUDY plan gates everything on
        ``len(self._studies_series) > 1`` (or _is_multistudy_hint).
        """
        try:
            ss = ViewerCommandAdapter._read_attr(tab, "_studies_series", None)
            if isinstance(ss, dict) and len(ss) > 1:
                return True
            return bool(ViewerCommandAdapter._read_attr(tab, "_is_multistudy_hint", False))
        except Exception:
            return False

    # ── action: get_active_tab ───────────────────────────────────────
    def get_active_tab(self, plan: CommandPlan, state: dict) -> CommandResult:
        tab = self._get_active()
        if tab is None:
            return self._no_active("get_active_tab")
        try:
            nodes = self._read_attr(tab, "lst_nodes_viewer", []) or []
            # The MULTI_STUDY doc warns the offset-key encoding is opaque;
            # we treat study_uid as a string label, never derive paths.
            return CommandResult(
                ok=True, action="get_active_tab",
                message="active patient tab snapshot",
                data={
                    "study_uid": str(self._read_attr(tab, "study_uid", "")),
                    "patient_id": str(self._read_attr(tab, "patient_id", "")),
                    "is_multistudy": self._is_multistudy(tab),
                    "viewport_count": len(nodes),
                    "layout_hint": (
                        getattr(tab, "_current_layout_dims", None)
                        or getattr(tab, "_layout_dims", None)
                    ),
                },
            )
        except Exception as exc:
            return CommandResult(
                ok=False, action="get_active_tab",
                message=f"read failed: {exc}",
                error_code="VIEWER_READ_ERROR",
            )

    # ── action: list_open_tabs ───────────────────────────────────────
    def list_open_tabs(self, plan: CommandPlan, state: dict) -> CommandResult:
        tabs = self._get_main_tabs()
        if tabs is None:
            return CommandResult(
                ok=False, action="list_open_tabs",
                message="No main tab widget bound.",
                error_code="NO_TAB_WIDGET",
            )
        try:
            n = tabs.count() if hasattr(tabs, "count") else 0
            titles = []
            current_idx = tabs.currentIndex() if hasattr(tabs, "currentIndex") else -1
            for i in range(n):
                title = tabs.tabText(i) if hasattr(tabs, "tabText") else ""
                titles.append({"index": i, "title": str(title)})
            return CommandResult(
                ok=True, action="list_open_tabs",
                message=f"{n} tab(s) open",
                data={"tabs": titles, "current_index": current_idx,
                      "count": n},
            )
        except Exception as exc:
            return CommandResult(
                ok=False, action="list_open_tabs",
                message=f"read failed: {exc}",
                error_code="VIEWER_READ_ERROR",
            )

    # ── action: get_thumbnails_data ──────────────────────────────────
    def get_thumbnails_data(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Return the series-info list for the active patient.

        For multi-study patients, returns the GROUPED list. We surface the
        opaque offset key when present, plus _orig_series_number /
        study_uid so consumers can render labels without violating the
        "offset keys are opaque" rule.
        """
        tab = self._get_active()
        if tab is None:
            return self._no_active("get_thumbnails_data")
        try:
            lst = self._read_attr(tab, "lst_thumbnails_data", []) or []
            rows = []
            for item in list(lst):
                if not isinstance(item, dict):
                    continue
                meta = item.get("metadata") or {}
                series = meta.get("series") if isinstance(meta, dict) else {}
                rows.append({
                    "series_number": str(item.get("series_number", "")),
                    "series_uid": str((series or {}).get("series_uid", "")),
                    "modality": str(item.get("modality", "")),
                    "image_count": int(item.get("image_count", 0) or 0),
                    "study_uid": str((series or {}).get("study_uid", "")),
                    "orig_series_number": str(
                        (series or {}).get("_orig_series_number", "")
                    ),
                })
            return CommandResult(
                ok=True, action="get_thumbnails_data",
                message=f"{len(rows)} series visible",
                data={"rows": rows, "count": len(rows),
                      "is_multistudy": self._is_multistudy(tab)},
            )
        except Exception as exc:
            return CommandResult(
                ok=False, action="get_thumbnails_data",
                message=f"read failed: {exc}",
                error_code="VIEWER_READ_ERROR",
            )

    # ── action: get_active_series ────────────────────────────────────
    def get_active_series(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Return series_uid / series_number for the focused viewport."""
        tab = self._get_active()
        if tab is None:
            return self._no_active("get_active_series")
        try:
            target = (
                self._read_attr(tab, "selected_widget", None)
                or (self._read_attr(tab, "lst_nodes_viewer", []) or [None])[0]
            )
            if target is None:
                return CommandResult(
                    ok=False, action="get_active_series",
                    message="No focused viewport.",
                    error_code="NO_VIEWPORT",
                )
            # In a node, ``vtk_widget`` is the per-viewport widget.
            vtk_widget = (self._read_attr(target, "vtk_widget", None)
                          or target)
            iv = self._read_attr(vtk_widget, "image_viewer", None)
            if iv is None:
                return CommandResult(
                    ok=True, action="get_active_series",
                    message="(viewport has no image_viewer yet)",
                    data={"series_uid": "", "series_number": ""},
                )
            metadata = self._read_attr(iv, "metadata", {}) or {}
            series = (metadata.get("series") if isinstance(metadata, dict) else {}) or {}
            return CommandResult(
                ok=True, action="get_active_series",
                message="active series",
                data={
                    "series_uid": str(series.get("series_uid", "")),
                    "series_number": str(series.get("series_number", "")),
                    # Multi-study: expose the original number so labels
                    # never use the opaque offset key.
                    "orig_series_number": str(series.get("_orig_series_number", "")),
                    "modality": str(series.get("modality", "")),
                    "study_uid": str(series.get("study_uid", "")),
                },
            )
        except Exception as exc:
            return CommandResult(
                ok=False, action="get_active_series",
                message=f"read failed: {exc}",
                error_code="VIEWER_READ_ERROR",
            )

    # ── action: get_multistudy_info ──────────────────────────────────
    def get_multistudy_info(self, plan: CommandPlan, state: dict) -> CommandResult:
        """List the studies grouped under the active patient tab.

        Single-study patients return one row with is_primary=True. For
        multi-study patients, the row tagged is_primary matches the
        widget's `study_uid` (the primary study whose keys are unchanged
        per MULTI_STUDY plan §Core idea — collision-free offset keys).
        """
        tab = self._get_active()
        if tab is None:
            return self._no_active("get_multistudy_info")
        try:
            primary = str(self._read_attr(tab, "study_uid", ""))
            ss = self._read_attr(tab, "_studies_series", None) or {}
            studies = []
            if isinstance(ss, dict) and ss:
                for uid, series_list in ss.items():
                    studies.append({
                        "study_uid": str(uid),
                        "series_count": (len(series_list)
                                         if hasattr(series_list, "__len__") else 0),
                        "is_primary": (str(uid) == primary),
                    })
            else:
                # Single-study fallback
                studies.append({
                    "study_uid": primary,
                    "series_count": len(self._read_attr(tab, "lst_thumbnails_data", []) or []),
                    "is_primary": True,
                })
            return CommandResult(
                ok=True, action="get_multistudy_info",
                message=f"{len(studies)} study(ies)",
                data={"studies": studies,
                      "is_multistudy": self._is_multistudy(tab),
                      "primary_study_uid": primary},
            )
        except Exception as exc:
            return CommandResult(
                ok=False, action="get_multistudy_info",
                message=f"read failed: {exc}",
                error_code="VIEWER_READ_ERROR",
            )


__all__ = ["ViewerCommandAdapter"]
