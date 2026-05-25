from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.utils.config import ATTACHMENT_PATH
from pathlib import Path, PureWindowsPath
from PacsClient.pacs.patient_tab.utils import BoxManager, TYPES_VIEWER
from PacsClient.utils.utils import load_mg_ai_manifest
from modules.ai_imaging.ai_module_ui.csv_table import concat_tables, read_csv_table
import asyncio
import os
import math
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Signal


_AI_MG_LOGGER = logging.getLogger(__name__)


class AIVTKWidget(VTKWidget):
    # Current canonical CSV coordinate space expected by Advanced VTK draw path.
    CSV_COORD_SPACE_CURRENT = "vtk_raw_ijk_v2"
    # Compatibility spaces for older server CSV generations.
    CSV_COORD_SPACE_LEGACY_BOTTOM_LEFT = "legacy_bottom_left_ijk"
    CSV_COORD_SPACE_NORMALIZED = "normalized_xyxy"
    CSV_COORD_SPACE_WORLD_MM = "world_mm_xyxy"

    processing_status_changed = Signal(str, bool)
    segmentation_ready = Signal(object, object, object, object)
    manager_ai_requested = Signal(int, object)
    apply_boxes_requested = Signal(object, object, object)
    def __init__(self, parent=None, height_viewer=480, patient_widget=None, type_viewer=None):
        super().__init__(parent, height_viewer, patient_widget=patient_widget)
        self.apply_default_filter = False
        self.patient_widget = patient_widget
        self.type_viewer = type_viewer
        self.csv_details_path = None
        self.csv_classification = None
        self._csv_cache = {}
        self._series_ai_cache = {}
        self._ai_boxes_cache = {}
        self._ai_last_run_series_uid = None
        self._ai_last_run_ts = 0.0
        self._ai_busy = False
        self._ai_pending_token = 0
        self._ai_pending_series_uid = None
        self._ai_apply_delay_ms = 300
        self._ai_prefetch_started = False
        self._ai_prefetch_max_workers = max(2, min(4, (os.cpu_count() or 2) // 2))
        self._ai_cache_lock = threading.Lock()
        self._ai_inflight = set()
        self._seg_pending = 0
        self._seg_executor = ThreadPoolExecutor(max_workers=2)
        self._seg_request_token = 0
        self._seg_helper = None
        self._seg_helper_series_uid = None

        if self.patient_widget is not None:
            if not hasattr(self.patient_widget, "_ai_boxes_cache"):
                self.patient_widget._ai_boxes_cache = {}
            if not hasattr(self.patient_widget, "_ai_boxes_cache_lock"):
                self.patient_widget._ai_boxes_cache_lock = threading.Lock()
            if not hasattr(self.patient_widget, "_ai_boxes_inflight"):
                self.patient_widget._ai_boxes_inflight = set()
            if not hasattr(self.patient_widget, "_ai_prefetch_started"):
                self.patient_widget._ai_prefetch_started = False
            if not hasattr(self.patient_widget, "_ai_prefetch_executor"):
                self.patient_widget._ai_prefetch_executor = None

            self._ai_boxes_cache = self.patient_widget._ai_boxes_cache
            self._ai_cache_lock = self.patient_widget._ai_boxes_cache_lock
            self._ai_inflight = self.patient_widget._ai_boxes_inflight
            self._ai_prefetch_started = self.patient_widget._ai_prefetch_started

        self.processing_status_changed.connect(self._on_processing_status_changed)
        self.segmentation_ready.connect(self._on_segmentation_ready)
        self.manager_ai_requested.connect(self._on_manager_ai_requested)
        self.apply_boxes_requested.connect(self._on_apply_boxes_requested)

        # --- Eagle Eye on-viewer "Show/Hide Boxes" toggle ---
        self._ai_boxes_visible = True
        self._boxes_toggle_btn = None
        try:
            if self.type_viewer != TYPES_VIEWER.fixed_viewer:
                self._create_boxes_toggle_button()
        except Exception:
            pass

    def _on_processing_status_changed(self, text: str, active: bool):
        imaging_tab = getattr(self.patient_widget, "imaging_tab_ui", None)
        if imaging_tab is None:
            return
        imaging_tab.set_processing_status(text, active)

    def _on_segmentation_ready(self, out_path, pts_world_out, ijk_list_3d, series_uid):
        try:
            current_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
        except Exception:
            current_uid = None

        if series_uid and current_uid != series_uid:
            self._seg_pending = max(0, self._seg_pending - 1)
            if self._seg_pending == 0:
                self._notify_processing_status("Processing: Ready", False)
            return

        if out_path:
            try:
                self._lock_camera_scale(duration_ms=800)
                pts_world = [list(p) for p in (pts_world_out or [])]
                pts_ijk = [list(p) for p in (ijk_list_3d or [])]
                self.image_viewer.overlay(out_path, pts_world_out=pts_world, pts_ijk=pts_ijk)
            except Exception as e:
                print(f"[AI][SEG] Overlay failed: {e}")

        self._seg_pending = max(0, self._seg_pending - 1)
        if self._seg_pending == 0:
            self._notify_processing_status("Processing: Ready", False)

    def _on_manager_ai_requested(self, delay_ms: int, reason=None):
        self._schedule_manager_ai(delay_ms=delay_ms, reason=reason)

    def _on_apply_boxes_requested(self, series_uid, boxes_scores, delay_ms):
        self._schedule_apply_boxes(series_uid, boxes_scores, delay_ms=delay_ms)

    def _schedule_manager_ai_safe(self, delay_ms=200, reason=None):
        try:
            from PySide6.QtCore import QThread
            if QThread.currentThread() != self.thread():
                self.manager_ai_requested.emit(int(delay_ms), reason)
                return
        except Exception:
            pass
        self._schedule_manager_ai(delay_ms=delay_ms, reason=reason)

    def _get_segmentation_helper(self):
        try:
            series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
        except Exception:
            series_uid = None

        if self._seg_helper is None or self._seg_helper_series_uid != series_uid:
            from modules.viewer.interactor_styles.segmentation_styles.polygon_interactorstyle import (
                PolygonSegmentationInteractorStyle,
            )
            helper = PolygonSegmentationInteractorStyle(self.image_viewer)
            try:
                helper.Off()
            except Exception:
                pass
            self._seg_helper = helper
            self._seg_helper_series_uid = series_uid

        return self._seg_helper

    def _schedule_apply_boxes_safe(self, series_uid, boxes_scores, delay_ms=None):
        try:
            from PySide6.QtCore import QThread
            if QThread.currentThread() != self.thread():
                self.apply_boxes_requested.emit(series_uid, boxes_scores, delay_ms)
                return
        except Exception:
            pass
        self._schedule_apply_boxes(series_uid, boxes_scores, delay_ms=delay_ms)

    def _notify_processing_status(self, text: str, active: bool = True):
        self.processing_status_changed.emit(text, active)

    def _lock_camera_scale(self, duration_ms: int = 600):
        state = None
        try:
            if hasattr(self, "_capture_camera_state"):
                state = self._capture_camera_state()
        except Exception:
            state = None
        if state is None:
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    state = {
                        "parallel_scale": camera.GetParallelScale(),
                        "position": camera.GetPosition(),
                        "focal_point": camera.GetFocalPoint(),
                        "view_up": camera.GetViewUp(),
                        "clipping_range": camera.GetClippingRange(),
                    }
            except Exception:
                state = None
        try:
            if state and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(state, duration_ms=duration_ms)
        except Exception:
            pass

    def _schedule_manager_ai(self, delay_ms=200, reason=None):
        try:
            series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
            series_num = self.image_viewer.metadata.get('series', {}).get('series_number')
        except Exception:
            series_uid = None
            series_num = None
        if series_uid is None and series_num is None:
            return

        self._ai_pending_token += 1
        token = self._ai_pending_token
        self._ai_pending_series_uid = series_uid
        attempts = {"count": 0}

        def _run_if_current():
            if token != self._ai_pending_token:
                return
            try:
                current_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
                current_num = self.image_viewer.metadata.get('series', {}).get('series_number')
            except Exception:
                current_uid = None
                current_num = None
            if series_uid is not None and current_uid != series_uid:
                return
            if series_uid is None and series_num is not None and current_num != series_num:
                return
            if not self._is_series_ready_for_boxes(series_uid):
                attempts["count"] += 1
                if attempts["count"] <= 100:
                    QTimer.singleShot(80, _run_if_current)
                else:
                    print(
                        f"[MG][MANAGER_AI] Dropped after readiness retries "
                        f"series_uid={series_uid} reason={reason}"
                    )
                return
            if self._ai_busy:
                QTimer.singleShot(120, _run_if_current)
                return
            self.manager_ai(expected_series_uid=series_uid)

        from PySide6.QtCore import QTimer
        QTimer.singleShot(int(delay_ms), _run_if_current)

    def _ensure_ai_prefetch_for_all_series(self):
        if self.patient_widget is None:
            return
        if getattr(self.patient_widget, "_ai_prefetch_started", False):
            return

        try:
            modality = self.image_viewer.metadata.get('series', {}).get('modality', '').upper()
        except Exception:
            modality = ''
        if modality != 'MG':
            return

        self.patient_widget._ai_prefetch_started = True

        def _prefetch_worker():
            df_det = self._load_csv_cached(self.csv_details_path)
            if df_det is None:
                return
            df_cls = self._load_csv_cached(self.csv_classification)

            det_stamp = self._get_csv_stamp(self.csv_details_path)
            cls_stamp = self._get_csv_stamp(self.csv_classification)

            series_items = getattr(self.patient_widget, 'lst_thumbnails_data', []) or []
            if not series_items:
                return

            executor = self.patient_widget._ai_prefetch_executor
            if executor is None:
                executor = ThreadPoolExecutor(max_workers=self._ai_prefetch_max_workers)
                self.patient_widget._ai_prefetch_executor = executor

            for item in series_items:
                metadata = item.get('metadata') if isinstance(item, dict) else None
                if not metadata:
                    continue
                series_modality = str(metadata.get('series', {}).get('modality', '')).upper()
                if series_modality and series_modality != 'MG':
                    continue
                series_uid = metadata.get('series', {}).get('series_uid')
                if not series_uid:
                    continue
                cache_key = (series_uid, det_stamp, cls_stamp)
                with self._ai_cache_lock:
                    if cache_key in self._ai_boxes_cache or cache_key in self._ai_inflight:
                        continue
                    self._ai_inflight.add(cache_key)
                future = executor.submit(self._compute_boxes_scores_for_metadata, df_det, df_cls, metadata, cache_key)

                def _on_prefetch_done(f, _key=cache_key, _uid=series_uid):
                    exc = f.exception()
                    if exc is not None:
                        import traceback as _tb
                        _AI_MG_LOGGER.warning(
                            "[MG][PREFETCH_WORKER_ERROR] series_uid=%s err=%r tb=%s",
                            _uid,
                            exc,
                            _tb.format_exception(type(exc), exc, exc.__traceback__),
                            extra={"component": "viewer"},
                        )
                        with self._ai_cache_lock:
                            self._ai_inflight.discard(_key)

                future.add_done_callback(_on_prefetch_done)

        threading.Thread(target=_prefetch_worker, daemon=True, name="AIBoxPrefetch").start()

    def _match_rows_for_series(self, df, series_uid, instance_names, instance_tokens, instance_numbers, check_all=False):
        matches = []
        for dicom_path_str in df["dicom_full_path"]:
            s = str(dicom_path_str).strip().strip('"').strip("'")
            p = PureWindowsPath(s) if ('\\' in s and '/' not in s) else Path(s)
            parent_dir = p.parent
            dicom_series_uid = parent_dir.name
            dicom_name = p.name
            dicom_token = self._extract_filename_token(dicom_name)

            dicom_num = None
            if dicom_token:
                try:
                    dicom_num = int(dicom_token)
                except Exception:
                    dicom_num = None

            if (
                dicom_series_uid == series_uid
                or (instance_names and dicom_name in instance_names)
                or (instance_tokens and dicom_token in instance_tokens)
                or (instance_numbers and dicom_num in instance_numbers)
            ):
                matches.append(dicom_path_str)
                if not check_all:
                    break

        if not matches:
            return None
        if check_all:
            # NOTE: df is the AI module's custom CsvTable, whose columns are
            # CsvColumn objects — they do NOT implement pandas' .isin().
            # Use an explicit boolean mask (CsvTable.__getitem__ accepts a
            # list of bools). The previous .isin() call raised AttributeError,
            # which the caller swallowed — silently dropping every per-box
            # classification label.
            match_set = set(matches)
            mask = [str(v) in match_set for v in df["dicom_full_path"]]
            return df[mask]
        return df[df["dicom_full_path"] == matches[0]]

    def _safe_eval_list(self, value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        try:
            return eval(value)
        except Exception:
            return []

    def _extract_value_field_for_metadata(self, df, field, series_uid, instance_names, instance_tokens, instance_numbers):
        try:
            series_ai_data = self._match_rows_for_series(
                df,
                series_uid,
                instance_names,
                instance_tokens,
                instance_numbers,
                check_all=False,
            )
            if series_ai_data is None:
                return []
            return self._safe_eval_list(series_ai_data[field].iloc[0])
        except Exception:
            return []

    def _extract_classification_label_for_metadata(self, df_classification, box_selected,
                                                    series_uid, instance_names, instance_tokens, instance_numbers):
        series_ai_data = self._match_rows_for_series(
            df_classification,
            series_uid,
            instance_names,
            instance_tokens,
            instance_numbers,
            check_all=True,
        )
        if series_ai_data is None:
            return None

        try:
            lst_ai_data = series_ai_data.to_dict()
        except Exception:
            return None

        xmins = lst_ai_data.get('xmin', {})
        ymins = lst_ai_data.get('ymin', {})
        xmaxs = lst_ai_data.get('xmax', {})
        ymaxs = lst_ai_data.get('ymax', {})
        labels = lst_ai_data.get('labels_pred', {})

        for k in xmins.keys():
            try:
                box = [xmins[k], ymins[k], xmaxs[k], ymaxs[k]]
            except Exception:
                continue
            if self.check_equal_lists(box_selected, box):
                try:
                    return eval(labels[k])
                except Exception:
                    return labels.get(k)
        return None

    def _resolve_coord_space_for_series(self, df, series_uid, instance_names, instance_tokens, instance_numbers):
        """Resolve declared coordinate space for matched CSV rows.

        The conversion contract is CSV-driven. If no coordinate-space metadata exists,
        we keep the current behavior (assume current VTK IJK pixel space) to avoid
        regressing already-correct studies.
        """
        try:
            matched = self._match_rows_for_series(
                df,
                series_uid,
                instance_names,
                instance_tokens,
                instance_numbers,
                check_all=True,
            )
            if matched is None:
                return self.CSV_COORD_SPACE_CURRENT

            for key in ("coord_space", "geometry_version", "coord_system"):
                if key not in matched.columns:
                    continue
                values = [str(v).strip().lower() for v in matched[key].iloc if str(v).strip()]
                if values:
                    # Prefer the first non-empty declaration for the matched slice rows.
                    return values[0]
        except Exception:
            pass
        return self.CSV_COORD_SPACE_CURRENT

    def _get_series_pixel_geometry(self, metadata):
        cols = None
        rows = None
        sx = None
        sy = None
        try:
            instances = metadata.get("instances", []) if isinstance(metadata, dict) else []
            if instances:
                first = instances[0] or {}
                col_val = first.get("columns")
                row_val = first.get("rows")
                try:
                    cols = int(col_val) if col_val is not None and str(col_val) != "" else None
                except Exception:
                    cols = None
                try:
                    rows = int(row_val) if row_val is not None and str(row_val) != "" else None
                except Exception:
                    rows = None
                spacing = first.get("pixel_spacing")
                if isinstance(spacing, (list, tuple)) and len(spacing) >= 2:
                    sy = float(spacing[0]) if spacing[0] not in (None, "") else None
                    sx = float(spacing[1]) if spacing[1] not in (None, "") else None
        except Exception:
            pass

        if (not cols or not rows) and getattr(self, "image_viewer", None) is not None:
            try:
                dims = self.image_viewer.vtk_image_data.GetDimensions()
                cols = cols or int(dims[0])
                rows = rows or int(dims[1])
            except Exception:
                pass

        return cols, rows, sx, sy

    def _normalize_and_clamp_box(self, box, cols, rows):
        try:
            x0, y0, x1, y1 = [float(v) for v in box]
        except Exception:
            return None

        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
            return None

        left = min(x0, x1)
        right = max(x0, x1)
        top = min(y0, y1)
        bottom = max(y0, y1)

        if cols is not None and cols > 0:
            left = max(0.0, min(left, cols - 1))
            right = max(0.0, min(right, cols - 1))
        if rows is not None and rows > 0:
            top = max(0.0, min(top, rows - 1))
            bottom = max(0.0, min(bottom, rows - 1))

        return [left, top, right, bottom]

    def _convert_boxes_to_current_geometry(self, boxes, *, coord_space, cols, rows, sx, sy):
        """Convert CSV boxes to the current VTK raw-IJK box convention.

        Supported coordinate spaces:
        - vtk_raw_ijk_v2 (pass-through)
        - legacy_bottom_left_ijk (Y-origin inversion)
        - normalized_xyxy (0..1 to pixel)
        - world_mm_xyxy (physical mm to pixel via spacing)
        """
        converted = []
        src = (coord_space or "").strip().lower()

        for box in boxes or []:
            try:
                x0, y0, x1, y1 = [float(v) for v in box]
            except Exception:
                continue

            if src in (self.CSV_COORD_SPACE_NORMALIZED, "normalized", "norm_xyxy"):
                if cols and rows:
                    x0, x1 = x0 * (cols - 1), x1 * (cols - 1)
                    y0, y1 = y0 * (rows - 1), y1 * (rows - 1)
            elif src in (self.CSV_COORD_SPACE_WORLD_MM, "world_mm", "physical_mm_xyxy"):
                if sx and sy and sx > 0 and sy > 0:
                    x0, x1 = x0 / sx, x1 / sx
                    y0, y1 = y0 / sy, y1 / sy
            elif src in (self.CSV_COORD_SPACE_LEGACY_BOTTOM_LEFT, "legacy_display_ijk", "bottom_left"):
                if rows and rows > 0:
                    y0, y1 = (rows - 1) - y0, (rows - 1) - y1

            normalized = self._normalize_and_clamp_box([x0, y0, x1, y1], cols, rows)
            if normalized is not None:
                converted.append(normalized)

        return converted

    def _compute_boxes_scores_for_metadata(self, df_det, df_cls, metadata, cache_key=None):
        series_uid = metadata.get('series', {}).get('series_uid') if isinstance(metadata, dict) else None

        instances = metadata.get('instances', []) if isinstance(metadata, dict) else []
        instance_names = set()
        instance_tokens = set()
        instance_numbers = set()
        for inst in instances or []:
            inst_path = inst.get('instance_path')
            if inst_path:
                name = Path(inst_path).name
                instance_names.add(name)
                token = self._extract_filename_token(name)
                if token:
                    instance_tokens.add(token)
            inst_num = inst.get('instance_number')
            if inst_num is not None:
                try:
                    instance_numbers.add(int(inst_num))
                except Exception:
                    pass

        cols, rows, sx, sy = self._get_series_pixel_geometry(metadata)
        coord_space = self._resolve_coord_space_for_series(
            df_det,
            series_uid,
            instance_names,
            instance_tokens,
            instance_numbers,
        )

        boxes_scores = []
        boxes = self._extract_value_field_for_metadata(
            df_det, 'box', series_uid, instance_names, instance_tokens, instance_numbers
        )
        scores = self._extract_value_field_for_metadata(
            df_det, 'scores', series_uid, instance_names, instance_tokens, instance_numbers
        )
        new_boxes = self._extract_value_field_for_metadata(
            df_det, 'new_box', series_uid, instance_names, instance_tokens, instance_numbers
        )
        removed_boxes = self._extract_value_field_for_metadata(
            df_det, 'removed', series_uid, instance_names, instance_tokens, instance_numbers
        )

        # Defensive normalization: extraction may return None for sparse CSV fields.
        boxes = list(boxes or [])
        scores = list(scores or [])
        new_boxes = list(new_boxes or [])
        removed_boxes = list(removed_boxes or [])

        boxes = self._convert_boxes_to_current_geometry(
            boxes,
            coord_space=coord_space,
            cols=cols,
            rows=rows,
            sx=sx,
            sy=sy,
        )
        new_boxes = self._convert_boxes_to_current_geometry(
            new_boxes,
            coord_space=coord_space,
            cols=cols,
            rows=rows,
            sx=sx,
            sy=sy,
        )
        removed_boxes = self._convert_boxes_to_current_geometry(
            removed_boxes,
            coord_space=coord_space,
            cols=cols,
            rows=rows,
            sx=sx,
            sy=sy,
        )

        _AI_MG_LOGGER.warning(
            "[MG][GEOM_CONVERT] series_uid=%s coord_space=%s dims=(%s,%s) spacing=(%s,%s) boxes=%d new=%d removed=%d",
            series_uid,
            coord_space,
            str(cols),
            str(rows),
            str(sx),
            str(sy),
            len(boxes),
            len(new_boxes),
            len(removed_boxes),
            extra={"component": "viewer"},
        )

        if new_boxes:
            boxes += new_boxes
            scores += [None] * len(new_boxes)

        if len(scores) < len(boxes):
            _AI_MG_LOGGER.warning(
                "[MG][SCORE_LENGTH_MISMATCH] series_uid=%s boxes=%d scores=%d",
                series_uid,
                len(boxes),
                len(scores),
                extra={"component": "viewer"},
            )

        _AI_MG_LOGGER.warning(
            "[MG][COMPUTE_STEP] step=before_for_loop series_uid=%s boxes=%d scores=%d removed=%d",
            series_uid, len(boxes), len(scores), len(removed_boxes),
            extra={"component": "viewer"},
        )

        for i in range(len(boxes)):
            if boxes[i] in removed_boxes:
                continue
            score_value = scores[i] if i < len(scores) else None
            try:
                score = float(f'{score_value:.2f}') if score_value is not None else 'Custom'
            except (TypeError, ValueError):
                try:
                    score = round(float(score_value), 2)
                except Exception:
                    score = 'Custom'
            classification_label = None
            if df_cls is not None:
                try:
                    classification_label = self._extract_classification_label_for_metadata(
                        df_cls,
                        boxes[i],
                        series_uid,
                        instance_names,
                        instance_tokens,
                        instance_numbers,
                    )
                except Exception as exc:
                    _AI_MG_LOGGER.warning(
                        "[MG][CLASSIFY_EXTRACT_ERROR] series_uid=%s idx=%d err=%s",
                        series_uid,
                        i,
                        str(exc),
                        extra={"component": "viewer"},
                    )
            if classification_label is not None:
                boxes_scores.append({'box': boxes[i], 'score': score, 'classification': classification_label})
            else:
                boxes_scores.append({'box': boxes[i], 'score': score})

        _AI_MG_LOGGER.warning(
            "[MG][COMPUTE_STEP] step=after_for_loop series_uid=%s boxes_scores=%d",
            series_uid, len(boxes_scores),
            extra={"component": "viewer"},
        )

        stats = {
            "total": len(boxes),
            "new": len(new_boxes),
            "removed": len(removed_boxes),
            "final": len(boxes_scores),
        }

        if cache_key is None:
            det_stamp = self._get_csv_stamp(self.csv_details_path)
            cls_stamp = self._get_csv_stamp(self.csv_classification)
            cache_key = (series_uid, det_stamp, cls_stamp)

        with self._ai_cache_lock:
            self._ai_boxes_cache[cache_key] = {
                "boxes_scores": boxes_scores,
                "stats": stats,
            }
            self._ai_inflight.discard(cache_key)

        _AI_MG_LOGGER.warning(
            "[MG][COMPUTE_STEP] step=cache_stored series_uid=%s boxes_scores=%d",
            series_uid, len(boxes_scores),
            extra={"component": "viewer"},
        )

        _AI_MG_LOGGER.warning(
            "[MG][AUTO_APPLY_FROM_PREFETCH] series_uid=%s boxes=%d",
            series_uid,
            len(boxes_scores),
            extra={"component": "viewer"},
        )
        self._schedule_apply_boxes_safe(series_uid, boxes_scores)

        return boxes_scores, stats

    def _schedule_apply_boxes(self, series_uid, boxes_scores, delay_ms=None):
        if delay_ms is None:
            delay_ms = self._ai_apply_delay_ms

        from PySide6.QtCore import QTimer

        attempts = {"count": 0}

        def _apply():
            try:
                current_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
            except Exception:
                current_uid = None
            if current_uid != series_uid:
                return
            if not self._is_series_ready_for_boxes(series_uid):
                attempts["count"] += 1
                if attempts["count"] <= 100:
                    QTimer.singleShot(80, _apply)
                else:
                    print(
                        f"[MG][BOXES] Dropped apply after readiness retries "
                        f"series_uid={series_uid} boxes={len(boxes_scores) if boxes_scores else 0}"
                    )
                return
            if not boxes_scores:
                try:
                    self.image_viewer.clear_boxes()
                except Exception:
                    pass
                try:
                    self.image_viewer.clear_overlay()
                except Exception:
                    pass
                self._notify_processing_status("Processing: Ready", False)
                return
            self.add_ai_boxes2viewer(boxes_scores)

        QTimer.singleShot(int(delay_ms), _apply)

    def _is_series_ready_for_boxes(self, series_uid):
        try:
            current_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
        except Exception:
            current_uid = None
        if current_uid != series_uid:
            return False
        if self.image_viewer is None:
            return False
        return True

    def _get_csv_stamp(self, csv_path):
        if csv_path is None:
            return None
        try:
            path = Path(csv_path)
            if not path.exists():
                return (str(path), None)
            return (str(path), path.stat().st_mtime)
        except Exception:
            return (str(csv_path), None)

    def _load_csv_cached(self, csv_path):
        if csv_path is None:
            return None

        try:
            path = Path(csv_path)
        except Exception:
            return None

        if not path.exists():
            print(f"[MG][CSV] file not found: {path}")
            return None

        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = None

        cached = self._csv_cache.get(key)
        if cached and cached.get("mtime") == mtime:
            return cached.get("df")

        df = read_csv_table(path)
        self._csv_cache[key] = {"mtime": mtime, "df": df}
        return df

    def _get_series_ai_cached(self, df, check_all_rows=False):
        try:
            series_uid = self.image_viewer.metadata['series'].get('series_uid')
        except Exception:
            series_uid = None
        cache_key = (id(df), series_uid, bool(check_all_rows))
        cached = self._series_ai_cache.get(cache_key)
        if cached is not None:
            return cached
        result = self.get_series_ai_data_from_df(df, check_all_rows=check_all_rows)
        self._series_ai_cache[cache_key] = result
        return result

    def start_process_series(self, vtk_image_data, metadata, series_index, id_vtk_widget, metadata_fixed):
        print(f"[MG][VTK] start_process_series called for series={series_index} modality={metadata.get('series', {}).get('modality', 'N/A')}")
        super().start_process_series(vtk_image_data, metadata, series_index, id_vtk_widget, metadata_fixed)

        study_uid = self.image_viewer.metadata_fixed['study_uid']

        # ---- MG: load CSV paths from manifest (via utils)
        if self.image_viewer.metadata['series']['modality'].upper() == 'MG':
            det_csv, cls_csv = load_mg_ai_manifest(
                study_uid=study_uid,
                attachments_path=ATTACHMENT_PATH
            )

            if det_csv and cls_csv:
                self.csv_details_path = det_csv
                self.csv_classification = cls_csv
                print("[MG] CSV paths loaded from manifest")
            else:
                det_csv, cls_csv = self._fallback_mg_csv_paths(study_uid)
                if det_csv and cls_csv:
                    self.csv_details_path = det_csv
                    self.csv_classification = cls_csv
                    print("[MG] CSV paths loaded from fallback")
                else:
                    # fallback (backward compatible)
                    self.csv_details_path = ATTACHMENT_PATH / study_uid / 'updated_csv_with_boxes.csv'
                    self.csv_classification = ATTACHMENT_PATH / study_uid / 'classification.csv'
                    print("[MG] CSV paths loaded from default")

        # connect apply button
        try:
            self.patient_widget.imaging_tab_ui.apply_btn.clicked.disconnect(self.on_apply)
        except Exception:
            pass

        self.patient_widget.imaging_tab_ui.apply_btn.clicked.connect(self.on_apply)

        try:
            self._ensure_ai_prefetch_for_all_series()
        except Exception:
            pass

        print(f"[MG][VTK] Scheduling manager_ai() for series={series_index}")
        self._schedule_manager_ai_safe(reason="start_process_series")

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None):
        print(f"[MG][VTK] switch_series called for series={series_index} modality={metadata.get('series', {}).get('modality', 'N/A')}")
        
        # Load CSV paths if not already loaded (happens when viewer is created as placeholder)
        if self.csv_details_path is None and metadata.get('series', {}).get('modality', '').upper() == 'MG':
            print(f"[MG][VTK] CSV paths not loaded, initializing now...")
            study_uid = metadata_fixed.get('study_uid') if metadata_fixed else None
            if study_uid:
                det_csv, cls_csv = load_mg_ai_manifest(
                    study_uid=study_uid,
                    attachments_path=ATTACHMENT_PATH
                )

                if det_csv and cls_csv:
                    self.csv_details_path = det_csv
                    self.csv_classification = cls_csv
                    print("[MG][VTK] CSV paths loaded from manifest")
                else:
                    det_csv, cls_csv = self._fallback_mg_csv_paths(study_uid)
                    if det_csv and cls_csv:
                        self.csv_details_path = det_csv
                        self.csv_classification = cls_csv
                        print("[MG][VTK] CSV paths loaded from fallback")
                    else:
                        # fallback (backward compatible)
                        self.csv_details_path = ATTACHMENT_PATH / study_uid / 'updated_csv_with_boxes.csv'
                        self.csv_classification = ATTACHMENT_PATH / study_uid / 'classification.csv'
                        print("[MG][VTK] CSV paths loaded from default")
        
        # ✅ CRITICAL FIX: Use super().switch_series() not switch_series_backup()
        result = super().switch_series(vtk_image_data, metadata, series_index, vtk_image_data_2, metadata_2,
                                       metadata_fixed)
        if result:
            self._seg_request_token += 1
            self._seg_helper_series_uid = None
            try:
                self._ensure_ai_prefetch_for_all_series()
            except Exception:
                pass
            print(f"[MG][VTK] Scheduling manager_ai() after switch for series={series_index}")
            self._schedule_manager_ai_safe(reason="switch_series")
        else:
            print(f"[MG][VTK] switch_series returned False for series={series_index}")
        return result

    def load_csv(self, csv_path=None):
        if csv_path is None:
            csv_path = self.csv_details_path

        print(f"[MG][CSV] csv_path={csv_path}")
        if csv_path is None:
            print("[MG][CSV] csv_path is None")
            return None

        df = self._load_csv_cached(csv_path)
        if df is None:
            return None

        print(f"[MG][CSV] loaded rows={len(df)} cols={list(df.columns)}")
        return df

    def _fallback_mg_csv_paths(self, study_uid):
        """Pick the most recent MG CSV pair if manifest is missing/invalid."""
        try:
            base_dir = ATTACHMENT_PATH / study_uid
            if not base_dir.exists():
                return None, None

            det_files = sorted(base_dir.glob('updated_csv_with_boxes_*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
            if not det_files:
                return None, None

            det = det_files[0]
            suffix = det.name.replace('updated_csv_with_boxes_', '')
            cls = base_dir / f'classification_{suffix}'
            if cls.exists():
                return det, cls

            # fallback to any classification CSV if paired file not found
            cls_files = sorted(base_dir.glob('classification_*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)
            return det, (cls_files[0] if cls_files else None)

        except Exception:
            return None, None

    def get_series_ai_data_from_df(self, df, check_all_rows=False):
        series_uid = self.image_viewer.metadata['series'].get('series_uid')
        series_num = self.image_viewer.metadata['series'].get('series_number', 'N/A')
        lst_dicom_path = df["dicom_full_path"]
        lst_ai_data = []

        instance_names = set()
        instance_tokens = set()
        instance_numbers = set()
        try:
            instances = self.image_viewer.metadata.get('instances', [])
            for inst in instances:
                inst_path = inst.get('instance_path')
                if inst_path:
                    name = Path(inst_path).name
                    instance_names.add(name)
                    token = self._extract_filename_token(name)
                    if token:
                        instance_tokens.add(token)
                inst_num = inst.get('instance_number')
                if inst_num is not None:
                    try:
                        instance_numbers.add(int(inst_num))
                    except Exception:
                        pass
        except Exception:
            instance_names = set()
            instance_tokens = set()
            instance_numbers = set()
        
        print(
            f"[MG][MATCH] Searching series={series_num} uid={series_uid} "
            f"names={len(instance_names)} tokens={len(instance_tokens)} numbers={len(instance_numbers)}"
        )
        print(f"[MG][MATCH] CSV has {len(lst_dicom_path)} rows total")

        if check_all_rows:  # return list of series_ai_data
            for dicom_path_str in lst_dicom_path:
                s = str(dicom_path_str).strip().strip('"').strip("'")  # پاکسازی احتمالی

                # اگر بک‌اسلش داریم (مسیر ویندوزی)، از PureWindowsPath استفاده کن
                p = PureWindowsPath(s) if ('\\' in s and '/' not in s) else Path(s)

                parent_dir = p.parent
                dicom_series_uid = parent_dir.name
                dicom_name = p.name
                dicom_token = self._extract_filename_token(dicom_name)

                dicom_num = None
                if dicom_token:
                    try:
                        dicom_num = int(dicom_token)
                    except Exception:
                        dicom_num = None

                if (
                    dicom_series_uid == series_uid
                    or (instance_names and dicom_name in instance_names)
                    or (instance_tokens and dicom_token in instance_tokens)
                    or (instance_numbers and dicom_num in instance_numbers)
                ):
                    series_ai_data = df[df["dicom_full_path"] == dicom_path_str]
                    lst_ai_data.append(series_ai_data)
            if len(lst_ai_data) == 0:
                print(
                    "[MG][MATCH] no rows matched by series_uid/instance name/token/number "
                    f"series_uid={series_uid}"
                )
                print(
                    "[MG][MATCH] instance_names=%d instance_tokens=%d instance_numbers=%d"
                    % (len(instance_names), len(instance_tokens), len(instance_numbers))
                )
            return lst_ai_data if len(lst_ai_data) > 0 else None

        else:  # get first rows if series_ai_data exist
            for dicom_path_str in lst_dicom_path:
                s = str(dicom_path_str).strip().strip('"').strip("'")  # پاکسازی احتمالی

                # اگر بک‌اسلش داریم (مسیر ویندوزی)، از PureWindowsPath استفاده کن
                p = PureWindowsPath(s) if ('\\' in s and '/' not in s) else Path(s)

                parent_dir = p.parent
                dicom_series_uid = parent_dir.name
                dicom_name = p.name
                dicom_token = self._extract_filename_token(dicom_name)

                dicom_num = None
                if dicom_token:
                    try:
                        dicom_num = int(dicom_token)
                    except Exception:
                        dicom_num = None

                if (
                    dicom_series_uid == series_uid
                    or (instance_names and dicom_name in instance_names)
                    or (instance_tokens and dicom_token in instance_tokens)
                    or (instance_numbers and dicom_num in instance_numbers)
                ):
                    print(
                        f"[MG][MATCH] ✓ Matched CSV row: series_uid={dicom_series_uid} "
                        f"name={dicom_name} token={dicom_token} num={dicom_num}"
                    )
                    series_ai_data = df[df["dicom_full_path"] == dicom_path_str]
                    return series_ai_data
            print(
                "[MG][MATCH] ✗ NO rows matched by series_uid/instance name/token/number "
                f"series={series_num} uid={series_uid}"
            )
            print(
                "[MG][MATCH] Available: instance_names=%d instance_tokens=%d instance_numbers=%d"
                % (len(instance_names), len(instance_tokens), len(instance_numbers))
            )
            if instance_names:
                print(f"[MG][MATCH] Sample instance_names: {list(instance_names)[:3]}")
            if instance_tokens:
                print(f"[MG][MATCH] Sample instance_tokens: {list(instance_tokens)[:3]}")
            if instance_numbers:
                print(f"[MG][MATCH] Sample instance_numbers: {list(instance_numbers)[:3]}")
        return None

    def _extract_filename_token(self, filename: str) -> str | None:
        try:
            import re
            matches = re.findall(r"(\d+)", str(filename))
            return matches[-1] if matches else None
        except Exception:
            return None

    def extract_value_field(self, df, field='box') -> list:
        try:
            series_ai_data = self._get_series_ai_cached(df, check_all_rows=False)
            if series_ai_data is not None:
                return eval(series_ai_data[field].iloc[0])  # field=box :: extract only box
            return []
        except Exception as e:
            # print('error:', e)
            pass
            return []

    def add_ai_boxes2viewer(self, boxes_scores):
        """
        Synchronous method to add AI boxes to the viewer.
        Changed from async to sync to avoid task conflicts.
        """
        if not boxes_scores:
            self._notify_processing_status("Processing: Ready", False)
            return
        try:
            print(f'[MG][ADD_BOXES] Called with {len(boxes_scores) if boxes_scores else 0} boxes')
            print(f'[MG][ADD_BOXES] boxes_scores: {boxes_scores}\n')
            if boxes_scores:
                # Keep sidebar populated from CSV even when actor drawing fails or is off-view.
                self._seed_sidebar_from_boxes_scores(boxes_scores)
                print(f'in if')
                self.patient_widget.toolbar_manager.check_and_deactivate_tools()
                print(f'after check and deactive tools')
                self._lock_camera_scale(duration_ms=800)
                self._notify_processing_status("Processing: Drawing boxes...", True)
                lst_boxes_object = self.image_viewer.draw_boxes_ijk(boxes_scores, color=(0.0, 1.0, 0.0), line_width=3.0)
                print(f'after draw boxes object')
                if lst_boxes_object:
                    self.update_boxes_details_ui(lst_boxes_object)
                    self._log_csv_vs_draw_probe(boxes_scores, lst_boxes_object)

                series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
                self._seg_pending = 0
                self._seg_request_token += 1
                seg_token = self._seg_request_token

                def _start_segmentation():
                    if seg_token != self._seg_request_token:
                        return
                    try:
                        current_uid = self.image_viewer.metadata.get('series', {}).get('series_uid')
                    except Exception:
                        current_uid = None
                    if current_uid != series_uid:
                        return
                    if not lst_boxes_object:
                        self._notify_processing_status("Processing: Ready", False)
                        return

                    self._notify_processing_status("Processing: Segmenting...", True)

                    for box_object in lst_boxes_object:
                        print(f'in for')
                        box_object: BoxManager
                        pts = self.image_viewer.get_actor_points_world(box_object.box_actor)
                        print('pts:', pts, '\n')

                        try:
                            ijk_list_3d = [
                                self.image_viewer.world_to_ijk(xw=w_pt[0], yw=w_pt[1], zw=w_pt[2], y_flip=True)
                                for w_pt in pts
                            ]
                        except Exception as e:
                            print(f"[AI][SEG] world_to_ijk failed: {e}")
                            continue

                        interactor = self._get_segmentation_helper()
                        if interactor is None or not hasattr(interactor, "request_segmentation_for_ijk"):
                            print("[AI][SEG] Polygon interactor not available; skipping segmentation.")
                            continue

                        self._seg_pending += 1

                        def _seg_worker(ijk_points, pts_world, uid):
                            try:
                                out_path, _payload = interactor.request_segmentation_for_ijk(ijk_points)
                            except Exception as e:
                                print(f"[AI][SEG] request failed: {e}")
                                out_path = None
                            self.segmentation_ready.emit(out_path, pts_world, ijk_points, uid)

                        self._seg_executor.submit(_seg_worker, ijk_list_3d, pts, series_uid)

                    if self._seg_pending == 0:
                        self._notify_processing_status("Processing: Ready", False)

                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, _start_segmentation)

        except Exception as e:
            print('error in add_ai_boxes2viewer:', e)
        finally:
            if self._seg_pending == 0:
                self._notify_processing_status("Processing: Ready", False)

    def _seed_sidebar_from_boxes_scores(self, boxes_scores):
        imaging_tab = getattr(self.patient_widget, 'imaging_tab_ui', None)
        if imaging_tab is None:
            return

        try:
            series_num = self.image_viewer.metadata.get('series', {}).get('series_number', 'N/A')
            series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid', 'N/A')
        except Exception:
            series_num = 'N/A'
            series_uid = 'N/A'

        seeded = 0

        for i, item in enumerate(boxes_scores or []):
            if not isinstance(item, dict):
                continue
            box = item.get('box')
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            classification = item.get('classification', [])
            imaging_tab.sidebar_upsert_item(
                key=f"Box {i + 1}",
                status=1,
                box_object=None,
                csv_box=[float(v) for v in box],
                classification=classification if classification is not None else [],
                select=False,
            )
            seeded += 1

        _AI_MG_LOGGER.warning(
            "[MG][SIDEBAR_SEED] series=%s uid=%s seeded=%d total_input=%d",
            series_num,
            series_uid,
            seeded,
            len(boxes_scores or []),
            extra={"component": "viewer"},
        )

    def _box_from_actor_ijk(self, box_object):
        try:
            pts = self.image_viewer.get_actor_points_world(box_object.box_actor)
            if not pts:
                return None
            ijk_pts = [
                self.image_viewer.world_to_ijk(xw=p[0], yw=p[1], zw=p[2], y_flip=True)
                for p in pts
            ]
            xs = [float(p[0]) for p in ijk_pts]
            ys = [float(p[1]) for p in ijk_pts]
            return [min(xs), min(ys), max(xs), max(ys)]
        except Exception:
            return None

    def _log_csv_vs_draw_probe(self, boxes_scores, lst_boxes_object):
        try:
            series_num = self.image_viewer.metadata.get('series', {}).get('series_number', 'N/A')
            series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid', 'N/A')
        except Exception:
            series_num = 'N/A'
            series_uid = 'N/A'

        csv_boxes = []
        for item in boxes_scores or []:
            if isinstance(item, dict):
                box = item.get('box')
                if isinstance(box, (list, tuple)) and len(box) == 4:
                    csv_boxes.append([float(v) for v in box])

        actor_boxes = []
        for box_object in lst_boxes_object or []:
            b = self._box_from_actor_ijk(box_object)
            if b is not None:
                actor_boxes.append(b)

        _AI_MG_LOGGER.warning(
            "[MG][BOX_DIAG] series=%s uid=%s csv_count=%d actor_count=%d",
            series_num,
            series_uid,
            len(csv_boxes),
            len(actor_boxes),
            extra={"component": "viewer"},
        )

        n = min(len(csv_boxes), len(actor_boxes), 3)
        for i in range(n):
            c = csv_boxes[i]
            a = actor_boxes[i]
            d = [round(a[j] - c[j], 3) for j in range(4)]
            _AI_MG_LOGGER.warning(
                "[MG][BOX_DIAG] idx=%d csv=%s actor=%s delta_actor_minus_csv=%s",
                i + 1,
                c,
                a,
                d,
                extra={"component": "viewer"},
            )

    def update_boxes_details_ui(self, lst_boxes_object):  # correct input : [BoxManager, BoxManager, ...]
        if not isinstance(lst_boxes_object, list):  # check list if BoxesManager.
            lst_boxes_object = [lst_boxes_object]
        self.patient_widget.update_sidebar_ui(lst_boxes_object)

    def manager_ai(self, expected_series_uid=None):
        series_num = self.image_viewer.metadata.get('series', {}).get('series_number', 'N/A')
        series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid', 'N/A')
        print(f"[MG][MANAGER_AI] START series={series_num} uid={series_uid}")
        if expected_series_uid and expected_series_uid != series_uid:
            print(f"[MG][MANAGER_AI] Skipping - stale series (expected={expected_series_uid})")
            return
        if self._ai_busy:
            print("[MG][MANAGER_AI] Skipping - already running")
            self._notify_processing_status("Processing: Busy...", True)
            return
        if self._ai_last_run_series_uid == series_uid and (time.time() - self._ai_last_run_ts) < 0.2:
            print("[MG][MANAGER_AI] Skipping - debounced")
            return
        if self.type_viewer == TYPES_VIEWER.fixed_viewer:
            print(f"[MG][MANAGER_AI] Skipping fixed_viewer")
            self._notify_processing_status("Processing: Ready", False)
            return
        self.patient_widget.sidebar_clear()
        if self.image_viewer.metadata['series']['modality'].upper() == 'MG':
            self._notify_processing_status("Processing: Reading AI results...", True)
            print(f"[MG][MANAGER_AI] MG modality detected, loading boxes...")
            df = self.load_csv()
            if df is not None:
                self._ai_busy = True
                try:
                    det_stamp = self._get_csv_stamp(self.csv_details_path)
                    cls_stamp = self._get_csv_stamp(self.csv_classification)
                    cache_key = (series_uid, det_stamp, cls_stamp)

                    with self._ai_cache_lock:
                        cache_entry = self._ai_boxes_cache.get(cache_key)

                    if cache_entry is None:
                        if cache_key in self._ai_inflight:
                            print("[MG][BOXES] In-flight - waiting on background compute")
                        else:
                            with self._ai_cache_lock:
                                self._ai_inflight.add(cache_key)

                            df_classification = self.load_csv(self.csv_classification)
                            metadata = self.image_viewer.metadata

                            def _worker():
                                try:
                                    result = self._compute_boxes_scores_for_metadata(df, df_classification, metadata, cache_key)
                                    if result:
                                        boxes_scores, _stats = result
                                        self._schedule_apply_boxes_safe(series_uid, boxes_scores)
                                except Exception as exc:
                                    _AI_MG_LOGGER.warning(
                                        "[MG][COMPUTE_WORKER_ERROR] series_uid=%s err=%s",
                                        series_uid,
                                        str(exc),
                                        extra={"component": "viewer"},
                                    )
                                finally:
                                    pass

                            threading.Thread(target=_worker, daemon=True, name=f"AIBoxCompute-{series_uid}").start()
                        print("[MG][BOXES] Deferring apply until cache is ready")
                    else:
                        boxes_scores = cache_entry.get("boxes_scores", [])
                        stats = cache_entry.get("stats", {"total": 0, "new": 0, "removed": 0, "final": len(boxes_scores)})

                        print(
                            "[MG][BOXES] total=%d new=%d removed=%d final=%d"
                            % (stats.get("total", 0), stats.get("new", 0), stats.get("removed", 0), stats.get("final", 0))
                        )
                        print(f"[MG][BOXES] boxes_scores={boxes_scores}")

                        self._schedule_apply_boxes_safe(series_uid, boxes_scores)
                finally:
                    self._ai_last_run_series_uid = series_uid
                    self._ai_last_run_ts = time.time()
                    self._ai_busy = False
            else:
                self._notify_processing_status("Processing: Ready", False)
        else:
            print(f"[MG][MANAGER_AI] Modality is not MG, skipping boxes")
            self._notify_processing_status("Processing: Ready", False)
        print(f"[MG][MANAGER_AI] END series={series_num}")

    def extract_classification_label(self, df_classification, box_selected):
        lst_ai_data = self._get_series_ai_cached(df_classification, check_all_rows=True)

        if lst_ai_data is not None:
            # get_series_ai_data_from_df returns a list of DataFrames when check_all_rows=True
            if isinstance(lst_ai_data, list):
                if len(lst_ai_data) == 0:
                    return None
                # Concatenate the matching CSV rows without pulling pandas into the core.
                lst_ai_data = concat_tables(lst_ai_data)
            
            lst_ai_data = lst_ai_data.to_dict()
            print('lst_ai_data:lst_ai_data:', lst_ai_data)
            print('box_selected:', box_selected)

            xmins = lst_ai_data['xmin']
            ymins = lst_ai_data['ymin']
            xmaxs = lst_ai_data['xmax']
            ymaxs = lst_ai_data['ymax']
            labels = lst_ai_data['labels_pred']

            for k in xmins.keys():  # it is the sample. we can use any lst
                box = [xmins[k], ymins[k], xmaxs[k], ymaxs[k]]
                print('box in lst:', box)
                print('box_selected == box:', box_selected == box)
                print('eqq::', self.check_equal_lists(box_selected, box))

                if self.check_equal_lists(box_selected, box):
                    print('wwww:', type(labels[k]))
                    print('wwww:', eval(labels[k]))
                    return eval(labels[k])

    def _bind_backend_from_metadata(self, metadata, force_vtk=False, source="bind"):
        """Eagle Eye always renders through the VTK / Advanced pipeline.

        AI detection boxes, overlays and segmentation require the VTK render
        window, so force the VTK backend for every series bind regardless of
        the global FAST/Advanced viewer setting.
        """
        return super()._bind_backend_from_metadata(metadata, force_vtk=True, source=source)

    def _update_backend_badge(self):
        """Eagle Eye is always Advanced/VTK — the badge must never show FAST."""
        try:
            badge = getattr(self, "_backend_badge", None)
            if badge is not None:
                badge.setText("advance")
                badge.adjustSize()
                x = max(0, (self.width() - badge.width()) // 2)
                badge.move(x, 8)
                badge.raise_()
        except Exception:
            pass
        # Keep the Show/Hide Boxes toggle aligned next to the badge.
        try:
            self._position_boxes_toggle_button()
        except Exception:
            pass

    def _create_boxes_toggle_button(self):
        """Create the on-viewer Show/Hide Boxes toggle (Eagle Eye only)."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton
        btn = QPushButton("Hide Boxes", self)
        btn.setObjectName("AIBoxesToggle")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip("Show or hide the AI detection boxes")
        btn.setStyleSheet(
            "QPushButton#AIBoxesToggle {"
            " background: rgba(20, 28, 40, 210); color: #d6e2f0;"
            " border: 1px solid #3a4a5e; border-radius: 6px;"
            " padding: 2px 10px; font-size: 11px; }"
            " QPushButton#AIBoxesToggle:hover {"
            " background: rgba(42, 58, 80, 235); }"
        )
        btn.clicked.connect(self._toggle_ai_boxes)
        btn.adjustSize()
        btn.show()
        btn.raise_()
        self._boxes_toggle_btn = btn
        self._position_boxes_toggle_button()

    def _position_boxes_toggle_button(self):
        """Place the toggle button just to the right of the backend badge."""
        btn = getattr(self, "_boxes_toggle_btn", None)
        if btn is None:
            return
        btn.adjustSize()
        badge = getattr(self, "_backend_badge", None)
        if badge is not None:
            x = badge.x() + badge.width() + 8
            y = badge.y()
        else:
            x = max(0, self.width() - btn.width() - 8)
            y = 8
        x = min(x, max(0, self.width() - btn.width() - 4))
        btn.move(x, y)
        btn.raise_()

    def _toggle_ai_boxes(self):
        """Flip AI detection-box visibility (on-viewer toggle handler)."""
        self._ai_boxes_visible = not getattr(self, "_ai_boxes_visible", True)
        self._apply_ai_boxes_visibility()
        btn = getattr(self, "_boxes_toggle_btn", None)
        if btn is not None:
            btn.setText("Hide Boxes" if self._ai_boxes_visible else "Show Boxes")
            self._position_boxes_toggle_button()

    def _apply_ai_boxes_visibility(self):
        """Apply the _ai_boxes_visible flag to every AI annotation on the viewer.

        Hides/shows the detection-box rectangles and their score/label text,
        AND the segmentation overlay (the yellow highlighted area) and any
        legacy overlay actor — so that hiding leaves only the raw underlying
        image visible.
        """
        try:
            viewer = getattr(self, "image_viewer", None)
            if viewer is None:
                return
            vis = 1 if getattr(self, "_ai_boxes_visible", True) else 0

            # Detection boxes: green rectangles + red score/label text.
            for attr in ("_box_actors", "_box_text_actors"):
                for actor in (getattr(viewer, attr, None) or []):
                    try:
                        actor.SetVisibility(vis)
                    except Exception:
                        pass

            # Segmentation overlays — the yellow highlighted areas.
            # Each _overlays entry is a (vtk_image, map_colors, actor) tuple.
            for entry in (getattr(viewer, "_overlays", None) or []):
                try:
                    ov_actor = entry[2]
                    if ov_actor is not None:
                        ov_actor.SetVisibility(vis)
                except Exception:
                    pass

            # Legacy single-overlay dict, if present.
            try:
                legacy = getattr(viewer, "_overlay", None)
                if isinstance(legacy, dict):
                    ov_actor = legacy.get("actor")
                    if ov_actor is not None:
                        ov_actor.SetVisibility(vis)
            except Exception:
                pass

            rw = getattr(viewer, "render_window", None) or getattr(self, "render_window", None)
            if rw is not None:
                rw.Render()
        except Exception as e:
            _AI_MG_LOGGER.warning("[MG] toggle AI annotations visibility failed: %s", e)


    def check_equal_lists(self, lst1, lst2):
        round_n = 1
        try:
            # Coerce every element to float so string/int box coordinates
            # compare correctly.
            l1 = [round(float(x), round_n) for x in lst1]
            l2 = [round(float(x), round_n) for x in lst2]
            return l1 == l2
        except (ValueError, TypeError):
            # Non-numeric values (e.g. a label like "Custom"): fall back to
            # direct equality rather than raising.
            return lst1 == lst2

    def set_new_interactorstyle(self, style):
        if self.type_viewer == TYPES_VIEWER.fixed_viewer:
            return
        super().set_new_interactorstyle(style)

    def on_apply(self):
        if self.type_viewer == TYPES_VIEWER.fixed_viewer:
            return None

        if self.image_viewer.metadata['series']['modality'].upper() == 'MG':
            df = self.load_csv()
            if df is not None:
                series_ai_data = self.get_series_ai_data_from_df(df)
                print('series_ai_data:', series_ai_data)

                self.patient_widget.imaging_tab_ui.update_csv(csv_path=self.csv_details_path, row=series_ai_data)
