from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget
import pandas as pd
from PacsClient.utils.config import ATTACHMENT_PATH
from pathlib import Path, PureWindowsPath
from PacsClient.pacs.patient_tab.utils import BoxManager, TYPES_VIEWER
from PacsClient.utils.utils import load_mg_ai_manifest
import asyncio


class AIVTKWidget(VTKWidget):
    def __init__(self, parent=None, height_viewer=480, patient_widget=None, type_viewer=None):
        super().__init__(parent, height_viewer)
        self.apply_default_filter = False
        self.patient_widget = patient_widget
        self.type_viewer = type_viewer
        self.csv_details_path = None
        self.csv_classification = None

    def start_process_series(self, vtk_image_data, metadata, series_index, id_vtk_widget, metadata_fixed):
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

        self.manager_ai()

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None):
        if super().switch_series_backup(vtk_image_data, metadata, series_index, vtk_image_data_2, metadata_2,
                                        metadata_fixed):
            self.manager_ai()
            return True
        return False

    def load_csv(self, csv_path=None):
        if csv_path is None:
            csv_path = self.csv_details_path

        print('csv_path', csv_path)
        if csv_path is None:
            print('csv or attachments are not exist')
            return None

        if not csv_path.exists():
            print('csv or attachments are not exist')
            return None

        df = pd.read_csv(csv_path)
        return df

    def get_series_ai_data_from_df(self, df: pd.DataFrame, check_all_rows=False):
        series_uid = self.image_viewer.metadata['series']['series_uid']
        lst_dicom_path = df["dicom_full_path"]
        lst_ai_data = []
        check_all_rows = False

        if check_all_rows:  # return list of series_ai_data
            for dicom_path_str in lst_dicom_path:
                s = str(dicom_path_str).strip().strip('"').strip("'")  # پاکسازی احتمالی

                # اگر بک‌اسلش داریم (مسیر ویندوزی)، از PureWindowsPath استفاده کن
                p = PureWindowsPath(s) if ('\\' in s and '/' not in s) else Path(s)

                parent_dir = p.parent
                dicom_series_uid = parent_dir.name

                if dicom_series_uid == series_uid:
                    series_ai_data = df[df["dicom_full_path"] == dicom_path_str]
                    lst_ai_data.append(series_ai_data)
            return lst_ai_data if len(lst_ai_data) > 0 else None

        else:  # get first rows if series_ai_data exist
            for dicom_path_str in lst_dicom_path:
                s = str(dicom_path_str).strip().strip('"').strip("'")  # پاکسازی احتمالی

                # اگر بک‌اسلش داریم (مسیر ویندوزی)، از PureWindowsPath استفاده کن
                p = PureWindowsPath(s) if ('\\' in s and '/' not in s) else Path(s)

                parent_dir = p.parent
                dicom_series_uid = parent_dir.name

                if dicom_series_uid == series_uid:
                    series_ai_data = df[df["dicom_full_path"] == dicom_path_str]
                    return series_ai_data
        return None

    def extract_value_field(self, df: pd.DataFrame, field='box') -> list:
        try:
            series_ai_data = self.get_series_ai_data_from_df(df)
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
            print(f'boxes_scores: {boxes_scores}\n')
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
        print('manage AI')
        if self.type_viewer == TYPES_VIEWER.fixed_viewer:
            return
        self.patient_widget.sidebar_clear()
        if self.image_viewer.metadata['series']['modality'].upper() == 'MG':
            df = self.load_csv()
            if df is not None:
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

                print('boxes_scores:', boxes_scores)

                # boxes = [box for box in boxes if box not in removed_boxes]
                # Use QTimer.singleShot for deferred execution to avoid async task conflicts
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, lambda: self.add_ai_boxes2viewer(boxes_scores))

    def extract_classification_label(self, df_classification, box_selected):
        lst_ai_data: pd.DataFrame = self.get_series_ai_data_from_df(df_classification, check_all_rows=True)

        if lst_ai_data is not None:
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
