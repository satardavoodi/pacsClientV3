from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.utils.config import ATTACHMENT_PATH
from pathlib import Path, PureWindowsPath
from PacsClient.pacs.patient_tab.utils import BoxManager, TYPES_VIEWER
from PacsClient.utils.utils import load_mg_ai_manifest
from modules.ai_imaging.ai_module_ui.csv_table import concat_tables, read_csv_table
import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Signal


class AIVTKWidget(VTKWidget):
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
        except Exception:
            series_uid = None
        if not series_uid:
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
            except Exception:
                current_uid = None
            if current_uid != series_uid:
                return
            if not self._is_series_ready_for_boxes(series_uid):
                attempts["count"] += 1
                if attempts["count"] <= 25:
                    QTimer.singleShot(80, _run_if_current)
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
                executor.submit(self._compute_boxes_scores_for_metadata, df_det, df_cls, metadata, cache_key)

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
            return df[df["dicom_full_path"].isin(matches)]
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

    def _compute_boxes_scores_for_metadata(self, df_det, df_cls, metadata, cache_key=None):
        series_uid = metadata.get('series', {}).get('series_uid') if isinstance(metadata, dict) else None
        if not series_uid:
            return

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

        if new_boxes:
            boxes += new_boxes
            scores += [None] * len(new_boxes)

        for i in range(len(boxes)):
            if boxes[i] in removed_boxes:
                continue
            score = float(f'{scores[i]:.2f}') if scores[i] is not None else 'Custom'
            classification_label = None
            if df_cls is not None:
                classification_label = self._extract_classification_label_for_metadata(
                    df_cls,
                    boxes[i],
                    series_uid,
                    instance_names,
                    instance_tokens,
                    instance_numbers,
                )
            if classification_label is not None:
                boxes_scores.append({'box': boxes[i], 'score': score, 'classification': classification_label})
            else:
                boxes_scores.append({'box': boxes[i], 'score': score})

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
                if attempts["count"] <= 20:
                    QTimer.singleShot(80, _apply)
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
        spinner = getattr(self, 'viewport_spinner', None)
        if spinner and getattr(spinner, 'spinner', None) is not None:
            try:
                if spinner.spinner.isVisible():
                    return False
            except Exception:
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
                print(f'in if')
                self.patient_widget.toolbar_manager.check_and_deactivate_tools()
                print(f'after check and deactive tools')
                self._lock_camera_scale(duration_ms=800)
                self._notify_processing_status("Processing: Drawing boxes...", True)
                lst_boxes_object = self.image_viewer.draw_boxes_ijk(boxes_scores, color=(0.0, 1.0, 0.0), line_width=3.0)
                print(f'after draw boxes object')

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

    def check_equal_lists(self, lst1, lst2):
        round_n = 1
        equal = [round(x, round_n) for x in lst1] == [round(x, round_n) for x in lst2]
        return equal

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
