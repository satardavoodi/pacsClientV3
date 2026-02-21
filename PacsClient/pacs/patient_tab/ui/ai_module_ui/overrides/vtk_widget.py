from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget
import pandas as pd
from PacsClient.utils.config import ATTACHMENT_PATH
from pathlib import Path, PureWindowsPath
from PacsClient.pacs.patient_tab.utils import BoxManager, TYPES_VIEWER
from PacsClient.utils.utils import load_mg_ai_manifest
import asyncio
import time


class AIVTKWidget(VTKWidget):
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

        df = pd.read_csv(path)
        self._csv_cache[key] = {"mtime": mtime, "df": df}
        return df

    def _get_series_ai_cached(self, df: pd.DataFrame, check_all_rows=False):
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

        print(f"[MG][VTK] About to call manager_ai() for series={series_index}")
        self.manager_ai()
        print(f"[MG][VTK] manager_ai() completed for series={series_index}")

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
            print(f"[MG][VTK] About to call manager_ai() after switch for series={series_index}")
            self.manager_ai()
            print(f"[MG][VTK] manager_ai() completed after switch for series={series_index}")
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

    def get_series_ai_data_from_df(self, df: pd.DataFrame, check_all_rows=False):
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

    def extract_value_field(self, df: pd.DataFrame, field='box') -> list:
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
        try:
            print(f'[MG][ADD_BOXES] Called with {len(boxes_scores) if boxes_scores else 0} boxes')
            print(f'[MG][ADD_BOXES] boxes_scores: {boxes_scores}\n')
            if not boxes_scores:
                return
            if boxes_scores:
                print(f'in if')
                self.patient_widget.toolbar_manager.check_and_deactivate_tools()
                print(f'after check and deactive tools')

                self.patient_widget.toolbar_manager.toggle_polygon_segment(self)  # active polygon interactorstyle
                print(f'after toggle polygon segment')
                lst_boxes_object = self.image_viewer.draw_boxes_ijk(boxes_scores, color=(0.0, 1.0, 0.0), line_width=3.0)
                print(f'after draw boxes object')

                for box_object in lst_boxes_object:
                    print(f'in for')
                    box_object: BoxManager
                    pts = self.image_viewer.get_actor_points_world(box_object.box_actor)
                    print('pts:', pts, '\n')

                    try:
                        # send boxes to PolygonInteractorStyle for draw segmentation on the viewer
                        print(f'in try, current style: {self.current_style}\n')
                        self.current_style.draw_segmentation_with_ijk_point(pts)
                    except:
                        print('This series is not existed on the server.')

                self.patient_widget.toolbar_manager.toggle_polygon_segment(self)  # deactivate polygon interactorstyle
        except Exception as e:
            print('error in add_ai_boxes2viewer:', e)

    def update_boxes_details_ui(self, lst_boxes_object):  # correct input : [BoxManager, BoxManager, ...]
        if not isinstance(lst_boxes_object, list):  # check list if BoxesManager.
            lst_boxes_object = [lst_boxes_object]
        self.patient_widget.update_sidebar_ui(lst_boxes_object)

    def manager_ai(self):
        series_num = self.image_viewer.metadata.get('series', {}).get('series_number', 'N/A')
        series_uid = self.image_viewer.metadata.get('series', {}).get('series_uid', 'N/A')
        print(f"[MG][MANAGER_AI] START series={series_num} uid={series_uid}")
        if self._ai_busy:
            print("[MG][MANAGER_AI] Skipping - already running")
            return
        if self._ai_last_run_series_uid == series_uid and (time.time() - self._ai_last_run_ts) < 0.2:
            print("[MG][MANAGER_AI] Skipping - debounced")
            return
        if self.type_viewer == TYPES_VIEWER.fixed_viewer:
            print(f"[MG][MANAGER_AI] Skipping fixed_viewer")
            return
        self.patient_widget.sidebar_clear()
        if self.image_viewer.metadata['series']['modality'].upper() == 'MG':
            print(f"[MG][MANAGER_AI] MG modality detected, loading boxes...")
            df = self.load_csv()
            if df is not None:
                self._ai_busy = True
                try:
                    det_stamp = self._get_csv_stamp(self.csv_details_path)
                    cls_stamp = self._get_csv_stamp(self.csv_classification)
                    cache_key = (series_uid, det_stamp, cls_stamp)

                    cache_entry = self._ai_boxes_cache.get(cache_key)
                    if cache_entry is None:
                        boxes_scores = []

                        boxes = self.extract_value_field(df, field='box')
                        scores = self.extract_value_field(df, field='scores')

                        new_boxes = self.extract_value_field(df, field='new_box')
                        boxes += new_boxes

                        # sync scores base on boxes
                        non_scores = [None] * len(new_boxes)
                        scores += non_scores

                        removed_boxes = self.extract_value_field(df, field='removed')

                        df_classification = self.load_csv(self.csv_classification)
                        if df_classification is None:
                            for i in range(len(boxes)):
                                if boxes[i] not in removed_boxes:
                                    box = boxes[i]
                                    score = float(f'{scores[i]:.2f}') if scores[i] is not None else 'Custom'
                                    boxes_scores.append({'box': box, 'score': score})
                        else:
                            for i in range(len(boxes)):
                                if boxes[i] not in removed_boxes:
                                    box = boxes[i]
                                    score = float(f'{scores[i]:.2f}') if scores[i] is not None else 'Custom'
                                    classification_label = self.extract_classification_label(df_classification, box)
                                    boxes_scores.append({'box': box, 'score': score, 'classification': classification_label})

                        stats = {
                            "total": len(boxes),
                            "new": len(new_boxes),
                            "removed": len(removed_boxes),
                            "final": len(boxes_scores),
                        }
                        self._ai_boxes_cache[cache_key] = {
                            "boxes_scores": boxes_scores,
                            "stats": stats,
                        }
                    else:
                        boxes_scores = cache_entry.get("boxes_scores", [])
                        stats = cache_entry.get("stats", {"total": 0, "new": 0, "removed": 0, "final": len(boxes_scores)})

                    print(
                        "[MG][BOXES] total=%d new=%d removed=%d final=%d"
                        % (stats.get("total", 0), stats.get("new", 0), stats.get("removed", 0), stats.get("final", 0))
                    )
                    print(f"[MG][BOXES] boxes_scores={boxes_scores}")

                    from PySide6.QtCore import QTimer
                    if not boxes_scores:
                        print("[MG][BOXES] no boxes to render for this series")
                        try:
                            self.image_viewer.clear_boxes()
                        except Exception:
                            pass
                    else:
                        print(f"[MG][BOXES] Scheduling render of {len(boxes_scores)} boxes in 100ms")
                        QTimer.singleShot(100, lambda: self.add_ai_boxes2viewer(boxes_scores))
                finally:
                    self._ai_last_run_series_uid = series_uid
                    self._ai_last_run_ts = time.time()
                    self._ai_busy = False
        else:
            print(f"[MG][MANAGER_AI] Modality is not MG, skipping boxes")
        print(f"[MG][MANAGER_AI] END series={series_num}")

    def extract_classification_label(self, df_classification, box_selected):
        lst_ai_data = self._get_series_ai_cached(df_classification, check_all_rows=True)

        if lst_ai_data is not None:
            # get_series_ai_data_from_df returns a list of DataFrames when check_all_rows=True
            if isinstance(lst_ai_data, list):
                if len(lst_ai_data) == 0:
                    return None
                # Concatenate all DataFrames in the list
                lst_ai_data = pd.concat(lst_ai_data, ignore_index=True)
            
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
