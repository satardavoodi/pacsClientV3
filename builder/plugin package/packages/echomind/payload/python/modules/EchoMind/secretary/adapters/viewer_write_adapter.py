"""ViewerWriteCommandAdapter — controlled viewer mutations.

Registered by ``bus_factory`` for the safe voice/assistant subset
(``change_series``, ``scroll_slices``, ``switch_tab`` and read probes), and by
``test_server.maybe_start_test_server()`` for the fuller QA surface
(``close_patient_tab`` included). Keep destructive actions out of the
production bus.

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

from dataclasses import asdict, is_dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
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

    def _viewport(
        self,
        viewport: int,
        action: str,
    ) -> tuple[Any | None, Any | None, Any | None, CommandResult | None]:
        tab, nodes = self._nodes()
        if tab is None:
            return None, None, None, _err(action, "NO_ACTIVE_TAB", "no active patient tab")
        if not nodes:
            return tab, None, None, _err(action, "NO_VIEWPORTS", "active tab has no viewer nodes")
        if viewport < 0 or viewport >= len(nodes):
            return tab, None, None, _err(
                action, "BAD_VIEWPORT",
                f"viewport {viewport} out of range (0..{len(nodes) - 1})",
            )
        node = nodes[viewport]
        vtk_w = getattr(node, "vtk_widget", None)
        if vtk_w is None:
            return tab, node, None, _err(action, "NO_WIDGET", f"viewport {viewport} has no vtk_widget")
        return tab, node, vtk_w, None

    @staticmethod
    def _qt_viewer(vtk_w: Any) -> Any:
        return (
            getattr(vtk_w, "_qt_viewer_widget", None)
            or getattr(vtk_w, "qt_viewer", None)
            or getattr(vtk_w, "qt_slice_viewer", None)
        )

    @staticmethod
    def _pipeline(qv: Any) -> Any:
        return getattr(qv, "_coord_backend", None) or getattr(qv, "pipeline", None)

    @staticmethod
    def _current_slice(node: Any, vtk_w: Any, qv: Any = None) -> int:
        if qv is not None and getattr(qv, "_current_slice_index", None) is not None:
            try:
                return int(getattr(qv, "_current_slice_index"))
            except Exception:
                pass
        slider = getattr(vtk_w, "slider", None) or getattr(node, "slider", None)
        if slider is not None:
            try:
                return int(slider.value())
            except Exception:
                pass
        return 0

    @staticmethod
    def _slice_count(vtk_w: Any) -> int:
        try:
            return int(vtk_w.get_count_of_slices())
        except Exception:
            return 0

    @staticmethod
    def _safe_json_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (list, tuple)):
            return [ViewerWriteCommandAdapter._safe_json_value(v) for v in value]
        if isinstance(value, dict):
            return {str(k): ViewerWriteCommandAdapter._safe_json_value(v) for k, v in value.items()}
        if is_dataclass(value):
            return ViewerWriteCommandAdapter._safe_json_value(asdict(value))
        return str(value)

    @staticmethod
    def _public_attrs(obj: Any) -> dict[str, Any]:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return ViewerWriteCommandAdapter._safe_json_value(obj)
        if is_dataclass(obj):
            return ViewerWriteCommandAdapter._safe_json_value(asdict(obj))
        out: dict[str, Any] = {}
        for name in dir(obj):
            if name.startswith("_"):
                continue
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            if callable(value):
                continue
            out[name] = ViewerWriteCommandAdapter._safe_json_value(value)
        return out

    @staticmethod
    def _point_obj(pt: Any) -> dict[str, float]:
        return {"x": float(pt[0]), "y": float(pt[1])}

    @staticmethod
    def _tool_model_to_dict(model: Any, index: int | None = None) -> dict[str, Any]:
        tool_type = getattr(model, "tool_type", "")
        tool_name = getattr(tool_type, "name", str(tool_type)).lower()
        row: dict[str, Any] = {
            "index": index,
            "type": tool_name,
            "slice_index": int(getattr(model, "slice_index", 0) or 0),
            "points_image": [
                ViewerWriteCommandAdapter._point_obj(p)
                for p in (getattr(model, "points_image", None) or [])
            ],
            "is_complete": bool(getattr(model, "is_complete", False)),
            "is_selected": bool(getattr(model, "is_selected", False)),
        }
        for attr in (
            "distance_mm", "angle_degrees", "radius_image_px", "label_text",
            "text", "head_size_px", "font_size", "created_at",
        ):
            if hasattr(model, attr):
                row[attr] = ViewerWriteCommandAdapter._safe_json_value(getattr(model, attr))
        stats = getattr(model, "stats", None)
        if stats is not None:
            row["stats"] = ViewerWriteCommandAdapter._safe_json_value(stats)
        return row

    @staticmethod
    def _agent_artifacts_dir() -> Path:
        try:
            from PacsClient.utils.data_paths import ECHOMIND_DIR
            root = Path(ECHOMIND_DIR)
        except Exception:
            root = Path.cwd() / "user_data" / "echomind"
        out = root / "agent_artifacts"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    @staticmethod
    def _series_rows(tab: Any) -> list[dict[str, Any]]:
        """Return drop-valid series rows sorted by the sidebar display key.

        Keys of ``_server_series_info`` are the exact opaque display keys the
        real drag payload carries. In multi-study tabs those keys may be offset
        values, so callers must pass the key through unchanged rather than
        deriving a path or original series number from it.
        """
        info = getattr(tab, "_server_series_info", None) or {}
        rows: list[dict[str, Any]] = []
        for key, meta in list(info.items()):
            try:
                m = meta or {}
                inner = m.get("series") if isinstance(m.get("series"), dict) else {}
                rows.append({
                    "series_number": int(key),
                    "series_uid": str(
                        m.get("series_uid")
                        or m.get("series_instance_uid")
                        or inner.get("series_uid")
                        or inner.get("series_instance_uid")
                        or ""
                    ),
                    "image_count": int(m.get("image_count")
                                       or inner.get("image_count") or 0),
                    "description": str(m.get("series_description")
                                       or inner.get("series_description") or "")[:48],
                })
            except Exception:
                continue
        rows.sort(key=lambda r: r["series_number"])
        return rows

    def _resolve_series_number(
        self,
        ent: dict[str, Any],
        tab: Any,
        action: str,
    ) -> tuple[int | None, CommandResult | None]:
        if ent.get("series_number") is not None:
            try:
                return int(ent.get("series_number")), None
            except (TypeError, ValueError):
                return None, _err(action, "BAD_ARGS",
                                  "entities.series_number must be an int")

        rows = self._series_rows(tab)

        uid = str(ent.get("series_uid") or "").strip()
        if uid:
            for row in rows:
                if str(row.get("series_uid") or "") == uid:
                    return int(row["series_number"]), None
            return None, _err(action, "SERIES_NOT_FOUND",
                              f"series_uid {uid!r} is not present in this tab")

        if ent.get("series_index") is not None:
            try:
                idx = int(ent.get("series_index"))
            except (TypeError, ValueError):
                return None, _err(action, "BAD_ARGS",
                                  "entities.series_index must be a 0-based int")
            if not rows:
                return None, _err(action, "NO_SERIES_INFO",
                                  "series_index requires active tab series metadata")
            if idx < 0 or idx >= len(rows):
                return None, _err(action, "BAD_SERIES_INDEX",
                                  f"series_index {idx} out of range (0..{len(rows) - 1})")
            return int(rows[idx]["series_number"]), None

        return None, _err(action, "BAD_ARGS",
                          "entities.series_number, series_index, or series_uid is required")

    # ── change_series (DragSeries, T1) ───────────────────────────────
    def change_series(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        viewport = int(ent.get("viewport", 0) or 0)

        tab, nodes = self._nodes()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "no active patient tab")
        series_number, series_err = self._resolve_series_number(ent, tab, plan.action)
        if series_err is not None:
            return series_err
        assert series_number is not None
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

        # OPT-23 (2026-07-08): defer the actual viewport switch to the NEXT event-loop
        # turn, matching the real drop handler (`_vw_dragdrop.dropEvent` ->
        # `QTimer.singleShot(0, _do_series_switch)`; see this file's docstring fidelity
        # note). EchoMind dispatch runs INLINE on the UI thread, so calling `method(...)`
        # synchronously here (a) never let the loading spinner shown above PAINT before
        # the heavy switch (the user saw a dead freeze instead of "loading"), and (b)
        # blocked the command-bus / IPC drain for the whole switch (incl. the Advanced/VTK
        # render). Deferring to singleShot(0) yields control back so the spinner paints and
        # the drain returns immediately; the switch itself is unchanged (async for a
        # cache-miss; the Advanced/VTK render stays GUI-thread but is now visibly
        # "loading"). Flag AIPACS_ECHOMIND_DEFER_SWITCH (default on; =0 = legacy inline).
        # Result semantics unchanged: this already reported "async load dispatched" and
        # never waited for the load to finish.
        def _do_switch() -> None:
            try:
                method(
                    series_index=series_number,
                    flag_change_selected_widget=False,
                    vtk_widget=vtk_w,
                    slider=slider,
                )
            except Exception:  # noqa: BLE001
                logger.exception("viewer_write.change_series deferred switch failed")

        _defer = (os.getenv("AIPACS_ECHOMIND_DEFER_SWITCH", "1") or "1").strip() != "0"
        if _defer:
            try:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, _do_switch)
            except Exception:  # noqa: BLE001 — no Qt loop (e.g. tests) -> run inline
                try:
                    _do_switch()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("viewer_write.change_series failed")
                    return _err(plan.action, "DISPATCH_FAILED", str(exc))
        else:
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

    # ── get_viewport_context ────────────────────────────────────────
    def get_viewport_context(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        viewport = int(ent.get("viewport", 0) or 0)
        tab, node, vtk_w, err = self._viewport(viewport, plan.action)
        if err is not None:
            return err
        assert tab is not None and node is not None and vtk_w is not None

        qv = self._qt_viewer(vtk_w)
        pipeline = self._pipeline(qv) if qv is not None else None
        slice_index = self._current_slice(node, vtk_w, qv)
        slice_count = self._slice_count(vtk_w)

        image_viewer = getattr(vtk_w, "image_viewer", None)
        metadata = self._safe_json_value(getattr(image_viewer, "metadata", {}) or {})
        metadata_fixed = self._safe_json_value(getattr(image_viewer, "metadata_fixed", {}) or {})

        viewport_state: dict[str, Any] = {
            "viewport": viewport,
            "backend": "fast_qt" if qv is not None else "vtk_or_unknown",
            "slice_index": slice_index,
            "slice_count": slice_count,
            "series_number": None,
            "image": {},
            "widget": {},
            "view_transform": {},
        }
        try:
            series = (metadata or {}).get("series") or {}
            viewport_state["series_number"] = str(series.get("series_number", "") or "")
        except Exception:
            pass

        if qv is not None:
            try:
                viewport_state["widget"] = {
                    "width": int(qv.width()),
                    "height": int(qv.height()),
                }
            except Exception:
                pass
            viewport_state["image"] = {
                "width": self._safe_json_value(getattr(qv, "_image_width", None)),
                "height": self._safe_json_value(getattr(qv, "_image_height", None)),
            }
            pan = getattr(qv, "_pan_offset", None)
            viewport_state["view_transform"] = {
                "zoom": self._safe_json_value(getattr(qv, "_zoom", None)),
                "pan": {
                    "x": self._safe_json_value(pan.x() if pan is not None else None),
                    "y": self._safe_json_value(pan.y() if pan is not None else None),
                },
                "rotation_degrees": self._safe_json_value(getattr(qv, "_rotation_angle", None)),
                "flip_horizontal": self._safe_json_value(getattr(qv, "_flip_h", None)),
                "flip_vertical": self._safe_json_value(getattr(qv, "_flip_v", None)),
                "display_scale": {
                    "x": self._safe_json_value(getattr(qv, "_display_scale_x", 1.0)),
                    "y": self._safe_json_value(getattr(qv, "_display_scale_y", 1.0)),
                },
            }

        slice_meta = {}
        if pipeline is not None and bool(ent.get("include_slice_meta", True)):
            getter = getattr(pipeline, "get_slice_meta", None) or getattr(pipeline, "get_geometry", None)
            if callable(getter):
                try:
                    raw = getter(slice_index)
                    slice_meta = self._public_attrs(raw)
                    if not bool(ent.get("include_local_paths", False)):
                        for key in ("path", "file_path", "dicom_path", "filename"):
                            if key in slice_meta:
                                slice_meta[key] = Path(str(slice_meta[key])).name
                except Exception as exc:
                    slice_meta = {"error": str(exc)}

        geometry = {}
        if pipeline is not None and callable(getattr(pipeline, "image_xy_to_patient_xyz", None)):
            try:
                w = viewport_state.get("image", {}).get("width") or slice_meta.get("cols")
                h = viewport_state.get("image", {}).get("height") or slice_meta.get("rows")
                if w and h:
                    corners = {
                        "top_left": (0.0, 0.0),
                        "top_right": (float(w) - 1.0, 0.0),
                        "bottom_left": (0.0, float(h) - 1.0),
                        "bottom_right": (float(w) - 1.0, float(h) - 1.0),
                    }
                    geometry["patient_corners_lps_mm"] = {
                        name: self._safe_json_value(
                            pipeline.image_xy_to_patient_xyz(x, y, slice_index)
                        )
                        for name, (x, y) in corners.items()
                    }
            except Exception as exc:
                geometry["error"] = str(exc)

        capabilities = {
            "capture_viewport": True,
            "dicom_context": pipeline is not None,
            "image_to_patient_geometry": (
                pipeline is not None
                and callable(getattr(pipeline, "image_xy_to_patient_xyz", None))
            ),
            "distance_measurement": (
                qv is not None
                and getattr(qv, "tool_controller", None) is not None
            ),
            "measurement_readback": (
                qv is not None
                and getattr(qv, "tool_controller", None) is not None
            ),
        }

        return CommandResult(
            ok=True,
            action=plan.action,
            message=f"viewport {viewport} context",
            data={
                "study_uid": str(getattr(tab, "study_uid", "") or ""),
                "viewport": viewport_state,
                "metadata": metadata,
                "metadata_fixed": metadata_fixed,
                "slice_meta": slice_meta,
                "geometry": geometry,
                "capabilities": capabilities,
            },
        )

    # ── capture_viewport ────────────────────────────────────────────
    def capture_viewport(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        viewport = int(ent.get("viewport", 0) or 0)
        scope = str(ent.get("scope") or "viewport").strip().lower()
        tab, node, vtk_w, err = self._viewport(viewport, plan.action)
        if err is not None:
            return err
        assert tab is not None and node is not None and vtk_w is not None

        if scope not in ("viewport", "tab"):
            return _err(plan.action, "BAD_ARGS", "entities.scope must be 'viewport' or 'tab'")

        target = tab if scope == "tab" else (self._qt_viewer(vtk_w) or vtk_w)
        prefix = str(ent.get("filename_prefix") or f"viewport_{viewport}_{scope}").strip()
        safe_prefix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in prefix)[:80]
        path = self._agent_artifacts_dir() / f"{self._timestamp()}_{safe_prefix}.png"

        try:
            if scope == "viewport":
                try:
                    from modules.viewer.viewport_capture import grab_widget_pixmap
                    pixmap = grab_widget_pixmap(target)
                except Exception:
                    pixmap = target.grab()
            else:
                pixmap = target.grab()
            ok = bool(pixmap.save(str(path), "PNG"))
        except Exception as exc:  # noqa: BLE001
            logger.exception("viewer_write.capture_viewport failed")
            return _err(plan.action, "CAPTURE_FAILED", str(exc))
        if not ok:
            return _err(plan.action, "CAPTURE_FAILED", "QPixmap.save returned false")

        return CommandResult(
            ok=True,
            action=plan.action,
            message=f"saved {scope} capture for viewport {viewport}",
            data={
                "viewport": viewport,
                "scope": scope,
                "path": str(path),
                "study_uid": str(getattr(tab, "study_uid", "") or ""),
            },
        )

    # ── activate_tool ───────────────────────────────────────────────
    def activate_tool(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        viewport = int(ent.get("viewport", 0) or 0)
        tool = str(ent.get("tool") or "").strip().lower().replace("-", "_")
        _tab, _node, vtk_w, err = self._viewport(viewport, plan.action)
        if err is not None:
            return err
        assert vtk_w is not None
        qv = self._qt_viewer(vtk_w)
        ctrl = getattr(qv, "tool_controller", None) if qv is not None else None
        if ctrl is None:
            return _err(plan.action, "NOT_IMPLEMENTED",
                        "tool activation is currently implemented for FAST Qt viewports only")
        try:
            from modules.viewer.tools.enums import ToolType
            mapping = {
                "distance": ToolType.RULER,
                "ruler": ToolType.RULER,
                "angle": ToolType.ANGLE,
                "two_line_angle": ToolType.TWO_LINE_ANGLE,
                "roi_rect": ToolType.ROI_RECT,
                "roi_rectangle": ToolType.ROI_RECT,
                "roi_circle": ToolType.ROI_CIRCLE,
                "circle_roi": ToolType.ROI_CIRCLE,
                "arrow": ToolType.ARROW,
                "annotation": ToolType.ARROW,
                "text": ToolType.TEXT,
                "eraser": ToolType.ERASER,
                "select": None,
                "none": None,
            }
            if tool not in mapping:
                return _err(plan.action, "BAD_ARGS",
                            "tool must be one of distance/ruler, angle, two_line_angle, "
                            "roi_rect, roi_circle, arrow, text, eraser, select")
            if mapping[tool] is None:
                ctrl.deactivate()
            else:
                ctrl.activate(mapping[tool])
            try:
                qv.update()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(ok=True, action=plan.action,
                             message=f"tool {tool or 'none'} activated",
                             data={"viewport": viewport, "tool": tool or "none"})

    # ── measure_distance ────────────────────────────────────────────
    def measure_distance(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        viewport = int(ent.get("viewport", 0) or 0)
        tab, node, vtk_w, err = self._viewport(viewport, plan.action)
        if err is not None:
            return err
        assert tab is not None and node is not None and vtk_w is not None

        qv = self._qt_viewer(vtk_w)
        ctrl = getattr(qv, "tool_controller", None) if qv is not None else None
        if ctrl is None:
            return _err(plan.action, "NOT_IMPLEMENTED",
                        "distance measurement is currently implemented for FAST Qt viewports only")

        current_slice = self._current_slice(node, vtk_w, qv)
        if ent.get("slice_index") is not None:
            try:
                requested_slice = int(ent.get("slice_index"))
            except (TypeError, ValueError):
                return _err(plan.action, "BAD_ARGS", "entities.slice_index must be an int")
            if requested_slice != current_slice:
                return _err(
                    plan.action,
                    "CONTEXT_MISMATCH",
                    f"requested slice {requested_slice} but current viewport slice is {current_slice}",
                )
        slice_index = current_slice

        try:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            from modules.viewer.tools.enums import ToolType
            resolver = CoordinateResolver(qv, self._pipeline(qv))
        except Exception as exc:
            return _err(plan.action, "NOT_READY", f"coordinate resolver unavailable: {exc}")

        points = ent.get("points_image") or ent.get("image_points")
        if not points and ent.get("points_widget"):
            try:
                points = [
                    resolver.widget_to_image(float(p[0]), float(p[1]))
                    for p in ent.get("points_widget")
                ]
            except Exception as exc:
                return _err(plan.action, "BAD_ARGS", f"points_widget could not be converted: {exc}")
        if not isinstance(points, (list, tuple)) or len(points) != 2:
            return _err(plan.action, "BAD_ARGS",
                        "entities.points_image must contain exactly two [x, y] points")
        try:
            p1 = (float(points[0][0]), float(points[0][1]))
            p2 = (float(points[1][0]), float(points[1][1]))
        except Exception:
            return _err(plan.action, "BAD_ARGS",
                        "entities.points_image must contain numeric [x, y] points")

        width = float(getattr(qv, "_image_width", 0) or 0)
        height = float(getattr(qv, "_image_height", 0) or 0)
        if width <= 0 or height <= 0:
            return _err(plan.action, "NOT_READY", "viewport image dimensions are unavailable")
        for x, y in (p1, p2):
            if x < 0 or y < 0 or x >= width or y >= height:
                return _err(plan.action, "POINT_OUT_OF_BOUNDS",
                            f"point ({x:.1f}, {y:.1f}) outside image bounds {width:.0f}x{height:.0f}")

        try:
            before = len(ctrl.store.get_for_slice(slice_index))
            ctrl.activate(ToolType.RULER)
            ctrl.on_mouse_press(p1[0], p1[1], slice_index, resolver)
            ctrl.on_mouse_press(p2[0], p2[1], slice_index, resolver)
            ctrl.deactivate()
            after = ctrl.store.get_for_slice(slice_index)
            if len(after) <= before:
                return _err(plan.action, "MEASUREMENT_FAILED", "ruler was not added to the tool store")
            model = after[-1]
            label = str(ent.get("label") or "").strip()
            if label:
                try:
                    model.label_text = label
                except Exception:
                    pass
            try:
                qv.update()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            logger.exception("viewer_write.measure_distance failed")
            return _err(plan.action, "DISPATCH_FAILED", str(exc))

        return CommandResult(
            ok=True,
            action=plan.action,
            message=f"distance measured on viewport {viewport}, slice {slice_index}",
            data={
                "viewport": viewport,
                "slice_index": slice_index,
                "study_uid": str(getattr(tab, "study_uid", "") or ""),
                "measurement": self._tool_model_to_dict(model, len(after) - 1),
            },
        )

    # ── get_measurements ────────────────────────────────────────────
    def get_measurements(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        viewport = int(ent.get("viewport", 0) or 0)
        _tab, node, vtk_w, err = self._viewport(viewport, plan.action)
        if err is not None:
            return err
        assert node is not None and vtk_w is not None
        qv = self._qt_viewer(vtk_w)
        ctrl = getattr(qv, "tool_controller", None) if qv is not None else None
        if ctrl is None:
            return _err(plan.action, "NOT_IMPLEMENTED",
                        "measurement readback is currently implemented for FAST Qt viewports only")

        current_slice = self._current_slice(node, vtk_w, qv)
        all_slices = bool(ent.get("all_slices", False))
        rows: list[dict[str, Any]] = []
        try:
            if all_slices:
                annotations = getattr(ctrl.store, "_annotations", {}) or {}
                for slice_idx in sorted(annotations):
                    for i, model in enumerate(ctrl.store.get_for_slice(slice_idx)):
                        rows.append(self._tool_model_to_dict(model, i))
            else:
                slice_index = current_slice
                if ent.get("slice_index") is not None:
                    slice_index = int(ent.get("slice_index"))
                for i, model in enumerate(ctrl.store.get_for_slice(slice_index)):
                    rows.append(self._tool_model_to_dict(model, i))
        except Exception as exc:  # noqa: BLE001
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(
            ok=True,
            action=plan.action,
            message=f"{len(rows)} measurement(s)",
            data={
                "viewport": viewport,
                "slice_index": None if all_slices else (
                    int(ent.get("slice_index")) if ent.get("slice_index") is not None else current_slice
                ),
                "all_slices": all_slices,
                "measurements": rows,
            },
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
        rows = self._series_rows(tab)
        return CommandResult(
            ok=True, action=plan.action, message=f"{len(rows)} series",
            data={"study_uid": str(getattr(tab, "study_uid", "") or ""),
                  "series": rows},
        )

    # ── scroll_slices (2026-06-06 bridge: per-slice stack navigation) ─
    def scroll_slices(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Move through the active viewport's slice stack via the SAME
        ``set_slice`` the wheel/slider path uses.

        Entities (one of):
          index      — absolute slice index (0-based)
          delta      — signed step (e.g. +1 / -5)
          direction  — "next" | "previous" | "first" | "last"
        Default with no entities: next slice. Result reports the clamped
        target so callers can chain ("scroll 10 forward" → lands on last).
        """
        ent = plan.entities or {}
        tab, nodes = self._nodes()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "no active patient tab")
        if not nodes:
            return _err(plan.action, "NO_VIEWPORTS", "active tab has no viewer nodes")
        viewport = int(ent.get("viewport", 0) or 0)
        if viewport < 0 or viewport >= len(nodes):
            return _err(plan.action, "BAD_VIEWPORT",
                        f"viewport {viewport} out of range (0..{len(nodes) - 1})")
        vtk_w = getattr(nodes[viewport], "vtk_widget", None)
        if vtk_w is None:
            return _err(plan.action, "NO_WIDGET", f"viewport {viewport} has no vtk_widget")
        set_slice = getattr(vtk_w, "set_slice", None)
        if not callable(set_slice):
            return _err(plan.action, "NOT_READY", "viewer has no set_slice (not initialised)")
        try:
            count = int(vtk_w.get_count_of_slices())
        except Exception:
            count = 0
        if count <= 0:
            return _err(plan.action, "NO_SLICES", "active viewport has no loaded slices")

        slider = getattr(vtk_w, "slider", None) or getattr(nodes[viewport], "slider", None)
        try:
            current = int(slider.value()) if slider is not None else 0
        except Exception:
            current = 0

        direction = str(ent.get("direction") or "").strip().lower()
        if ent.get("index") is not None:
            try:
                target = int(ent.get("index"))
            except (TypeError, ValueError):
                return _err(plan.action, "BAD_ARGS", "entities.index must be an int")
        elif ent.get("delta") is not None:
            try:
                target = current + int(ent.get("delta"))
            except (TypeError, ValueError):
                return _err(plan.action, "BAD_ARGS", "entities.delta must be an int")
        elif direction in ("first", "start"):
            target = 0
        elif direction in ("last", "end"):
            target = count - 1
        elif direction in ("previous", "prev", "back", "up"):
            target = current - 1
        else:  # "next" / default
            target = current + 1

        target = max(0, min(count - 1, target))
        try:
            set_slice(target)
        except Exception as exc:  # noqa: BLE001
            logger.exception("viewer_write.scroll_slices failed")
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(
            ok=True, action=plan.action,
            message=f"slice {target + 1}/{count} (viewport {viewport})",
            data={"viewport": viewport, "slice_index": target,
                  "slice_count": count, "previous_index": current},
        )

    # ── change_layout (P1 stub — explicit, typed) ────────────────────
    def change_layout(self, plan: CommandPlan, state: dict) -> CommandResult:
        return _err(plan.action, "NOT_IMPLEMENTED",
                    "change_layout lands with the P1 toolbar-route work "
                    "(TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04 §6)")


TEST_WRITE_ACTIONS = {
    "change_series":        "change_series",
    "query_viewport_state": "query_viewport_state",
    "get_viewport_context": "get_viewport_context",
    "capture_viewport":     "capture_viewport",
    "activate_tool":        "activate_tool",
    "measure_distance":     "measure_distance",
    "get_measurements":     "get_measurements",
    "get_series_info":      "get_series_info",
    "close_patient_tab":    "close_patient_tab",
    "switch_tab":           "switch_tab",
    "change_layout":        "change_layout",
    "scroll_slices":        "scroll_slices",
}

__all__ = ["ViewerWriteCommandAdapter", "TEST_WRITE_ACTIONS"]
