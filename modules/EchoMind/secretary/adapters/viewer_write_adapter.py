"""ViewerWriteCommandAdapter — TEST-MODE-ONLY viewer mutations.

Registered exclusively by ``test_server.maybe_start_test_server()`` (env
``AIPACS_TEST_SERVER=1``). It is **never** wired into the production bus by
``bus_factory`` — the production ViewerCommandAdapter stays read-only per
``docs/MULTI_STUDY_SINGLE_TAB_PLAN.md``.

Fidelity note (T1 tier, see TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04 §4.3):
``change_series`` invokes ``vtk_widget.method_change_series_on_viewer(...)`` with
the exact argument shape the real drop handler uses
(``_vw_dragdrop.dropEvent`` → ``QTimer.singleShot(0, _do_series_switch)``), so
every downstream path — async load, awaiting marker, progressive activation,
multi-study resolution, cross-patient guards — is the production path.
``close_patient_tab`` emits ``tabCloseRequested`` (the same signal the tab's X
button fires), so the real teardown handlers run.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


def _err(action: str, code: str, msg: str) -> CommandResult:
    return CommandResult(ok=False, action=action, error_code=code, message=msg)


class ViewerWriteCommandAdapter:
    """Write-side viewer commands for the high-pressure test framework."""

    def __init__(
        self,
        get_active_patient_tab: Optional[Callable[[], Any]] = None,
        get_main_tab_widget: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._get_tab = get_active_patient_tab or (lambda: None)
        self._get_tw = get_main_tab_widget or (lambda: None)

    # ── helpers ──────────────────────────────────────────────────────
    def _nodes(self):
        tab = self._get_tab()
        if tab is None:
            return None, []
        return tab, list(getattr(tab, "lst_nodes_viewer", None) or [])

    # ── change_series (DragSeries, T1) ───────────────────────────────
    def change_series(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        try:
            series_number = int(ent.get("series_number"))
        except (TypeError, ValueError):
            return _err(plan.action, "BAD_ARGS", "entities.series_number (int) is required")
        viewport = int(ent.get("viewport", 0) or 0)

        tab, nodes = self._nodes()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "no active patient tab")
        if not nodes:
            return _err(plan.action, "NO_VIEWPORTS", "active tab has no viewer nodes")
        if viewport < 0 or viewport >= len(nodes):
            return _err(plan.action, "BAD_VIEWPORT",
                        f"viewport {viewport} out of range (0..{len(nodes) - 1})")

        node = nodes[viewport]
        vtk_w = getattr(node, "vtk_widget", None)
        if vtk_w is None:
            return _err(plan.action, "NO_WIDGET", f"viewport {viewport} has no vtk_widget")
        method = getattr(vtk_w, "method_change_series_on_viewer", None)
        if method is None:
            return _err(plan.action, "NOT_READY",
                        "method_change_series_on_viewer is None (viewer not initialised)")

        # Mirror dropEvent's action-correlation stamp so KPI/log pipelines see
        # bus drops exactly like mouse drops (fidelity audit §4.3).
        try:
            import time as _time
            tab._pending_action_id = (
                f"drag_drop-{series_number}-{int(_time.time() * 1000)}"
                f"-viewer-{getattr(vtk_w, 'id_vtk_widget', 'na')}"
            )
            tab._pending_action_series = str(series_number)
        except Exception:
            pass

        # Mirror dropEvent's visual feedback so spinner/await semantics match
        # a real drop (optional, default on).
        if bool(ent.get("show_spinner", True)):
            try:
                vtk_w.viewport_spinner.show_loading("Switching series...")
            except Exception:
                pass

        slider = getattr(vtk_w, "slider", None) or getattr(node, "slider", None)
        try:
            method(
                series_index=series_number,
                flag_change_selected_widget=False,
                vtk_widget=vtk_w,
                slider=slider,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("viewer_write.change_series failed")
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(
            ok=True, action=plan.action,
            message=f"series {series_number} -> viewport {viewport} (async load dispatched)",
            data={"series_number": series_number, "viewport": viewport},
        )

    # ── query_viewport_state ─────────────────────────────────────────
    def query_viewport_state(self, plan: CommandPlan, state: dict) -> CommandResult:
        tab, nodes = self._nodes()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "no active patient tab")
        out = []
        for idx, node in enumerate(nodes):
            vtk_w = getattr(node, "vtk_widget", None)
            row: dict[str, Any] = {"viewport": idx, "alive": vtk_w is not None}
            if vtk_w is None:
                out.append(row)
                continue
            try:
                meta = getattr(getattr(vtk_w, "image_viewer", None), "metadata", {}) or {}
                row["series_number"] = str(
                    (meta.get("series") or {}).get("series_number", "") or ""
                )
                row["preview_only"] = bool(meta.get("preview_only", False))
            except Exception:
                row["series_number"] = None
            for attr, key in (
                ("_awaiting_series_number", "awaiting_series"),
                ("_progressive_mode", "progressive_mode"),
                ("_progressive_series_number", "progressive_series"),
            ):
                try:
                    row[key] = getattr(vtk_w, attr, None)
                except Exception:
                    row[key] = None
            try:
                row["slice_count"] = int(vtk_w.get_count_of_slices())
            except Exception:
                row["slice_count"] = None
            try:
                sp = getattr(vtk_w, "viewport_spinner", None)
                row["spinner_visible"] = bool(sp.isVisible()) if sp is not None else None
            except Exception:
                row["spinner_visible"] = None
            out.append(row)
        return CommandResult(
            ok=True, action=plan.action,
            message=f"{len(out)} viewport(s)",
            data={"study_uid": str(getattr(tab, "study_uid", "") or ""), "viewports": out},
        )

    # ── close_patient_tab (ClosePatient) ─────────────────────────────
    def close_patient_tab(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        tw = self._get_tw()
        if tw is None:
            return _err(plan.action, "NO_TAB_WIDGET", "main tab widget unavailable")
        index = ent.get("index")
        if index is None:
            # Default: the currently-active tab, but only if it's a patient tab.
            tab = self._get_tab()
            if tab is None:
                return _err(plan.action, "NO_ACTIVE_TAB",
                            "no index given and active tab is not a patient tab")
            index = tw.indexOf(tab)
        try:
            index = int(index)
            if index < 0 or index >= tw.count():
                return _err(plan.action, "BAD_INDEX", f"tab index {index} out of range")
            # Same signal the tab's X button fires → real teardown path.
            tw.tabCloseRequested.emit(index)
        except Exception as exc:  # noqa: BLE001
            logger.exception("viewer_write.close_patient_tab failed")
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(ok=True, action=plan.action,
                             message=f"tabCloseRequested emitted for index {index}",
                             data={"index": index})

    # ── switch_tab ───────────────────────────────────────────────────
    def switch_tab(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        tw = self._get_tw()
        if tw is None:
            return _err(plan.action, "NO_TAB_WIDGET", "main tab widget unavailable")
        try:
            index = int(ent.get("index", 0))
            if index < 0 or index >= tw.count():
                return _err(plan.action, "BAD_INDEX", f"tab index {index} out of range")
            tw.setCurrentIndex(index)
        except Exception as exc:  # noqa: BLE001
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(ok=True, action=plan.action,
                             message=f"switched to tab {index}", data={"index": index})

    # ── get_series_info (per-series discovery for DragSeries) ────────
    def get_series_info(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Per-series rows of the active tab from `_server_series_info`.

        Added 2026-06-04: `get_thumbnails_data` exposes study-level entries
        (`lst_thumbnails_data` has one row per study), so stress drivers had no
        series numbers to drop. Keys of `_server_series_info` are the sidebar's
        series numbers (offset keys for multi-study tabs — opaque but valid
        drop targets, exactly what a real drag payload would carry).
        """
        tab = self._get_tab()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "no active patient tab")
        info = getattr(tab, "_server_series_info", None) or {}
        rows = []
        for key, meta in list(info.items()):
            try:
                m = meta or {}
                inner = m.get("series") if isinstance(m.get("series"), dict) else {}
                rows.append({
                    "series_number": int(key),
                    "image_count": int(m.get("image_count")
                                       or inner.get("image_count") or 0),
                    "description": str(m.get("series_description")
                                       or inner.get("series_description") or "")[:48],
                })
            except Exception:
                continue
        rows.sort(key=lambda r: r["series_number"])
        return CommandResult(
            ok=True, action=plan.action, message=f"{len(rows)} series",
            data={"study_uid": str(getattr(tab, "study_uid", "") or ""),
                  "series": rows},
        )

    # ── change_layout (P1 stub — explicit, typed) ────────────────────
    def change_layout(self, plan: CommandPlan, state: dict) -> CommandResult:
        return _err(plan.action, "NOT_IMPLEMENTED",
                    "change_layout lands with the P1 toolbar-route work "
                    "(TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04 §6)")


TEST_WRITE_ACTIONS = {
    "change_series":        "change_series",
    "query_viewport_state": "query_viewport_state",
    "get_series_info":      "get_series_info",
    "close_patient_tab":    "close_patient_tab",
    "switch_tab":           "switch_tab",
    "change_layout":        "change_layout",
}

__all__ = ["ViewerWriteCommandAdapter", "TEST_WRITE_ACTIONS"]
