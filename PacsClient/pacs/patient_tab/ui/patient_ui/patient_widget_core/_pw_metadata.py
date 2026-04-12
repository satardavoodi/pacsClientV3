"""
Series metadata, caching, grid config, patient data.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import asyncio
import copy
import json
import time
import traceback
import vtk
from PySide6.QtCore import QTimer
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk


class _PWMetadataMixin:
    """Series metadata, caching, grid config, patient data."""

    def check_logo_patient(self, file_path):
        # ✅ FULLY SYNCHRONOUS: No async at all to avoid task conflicts
        if self.logo_patient is None:
            self.logo_patient = file_path
            # Use QTimer.singleShot to safely update UI
            QTimer.singleShot(0, self.update_tab_manager)

    def is_single_frame_modality(self, metadata: dict) -> bool:
        """
        تشخیص اینکه modality تک‌فریم است یا نه (مثل DX، CR، US)
        برای این modality ها layout باید 1x1 باشد
        توجه: MG باید 2x2 باشد نه 1x1
        """
        modality = metadata.get('series', {}).get('modality', '').upper()
        num_instances = len(metadata.get('instances', []))

        # لیست modality های تک‌فریم یا تصاویر ثابت (بدون MG)
        single_frame_modalities = ['DX', 'CR', 'US', 'RF', 'XA', 'PX', 'IO']

        # اگر modality تک‌فریم است یا تعداد instance ها کم است (<=3)
        if modality in single_frame_modalities or (num_instances <= 3 and modality != 'MG'):
            return True

        return False

    def get_optimal_layout_for_series(self, metadata: dict) -> tuple[int, int]:
        """
        Get layout based on series modality from modality_grid.json (fallback to default or 1x2).
        """
        # استخراج مودالیتی از metadata
        modality = None
        try:
            if 'series' in metadata and 'modality' in metadata['series']:
                modality = metadata['series']['modality']
            elif 'instances' in metadata and len(metadata['instances']) > 0:
                modality = metadata['instances'][0].get('modality')
        except Exception as e:
            print(f"⚠️ Error extracting modality from metadata: {e}")
        
        return self._get_default_layout_from_config(modality=modality)

    def apply_modality_grid_config(self):
        """Re-apply viewer layout based on the current modality grid config."""
        try:
            if not getattr(self, "viewer_controller", None):
                return
            if not hasattr(self, "vtk_layout"):
                return

            metadata = None
            selected_widget = self.selected_widget
            if selected_widget and getattr(selected_widget, "image_viewer", None):
                metadata = getattr(selected_widget.image_viewer, "metadata", None)

            if metadata is None and selected_widget is not None:
                idx = getattr(selected_widget, "last_series_show", None)
                if isinstance(idx, int) and 0 <= idx < len(self.lst_thumbnails_data):
                    metadata = self.lst_thumbnails_data[idx].get("metadata")

            if metadata is None and self.lst_thumbnails_data:
                metadata = self.lst_thumbnails_data[0].get("metadata")

            if metadata:
                layout = self.get_optimal_layout_for_series(metadata)
            else:
                layout = self._get_default_layout_from_config()

            if layout == self.viewer_controller._current_layout:
                return

            self.viewer_controller.apply_multi_viewer(layout, modify_by_user=True)
        except Exception as e:
            print(f"⚠️ Error applying modality grid config: {e}")

    def apply_viewer_backend_config(self):
        """Apply backend setting updates to already-open viewers."""
        try:
            if not getattr(self, "viewer_controller", None):
                return
            self.viewer_controller.apply_backend_setting_to_open_viewers()
        except Exception as e:
            print(f"Error applying viewer backend config: {e}")

    def init_grid_config():
        """فایل config اولیه را ایجاد می‌کند اگر وجود نداشته باشد"""
        if not GRID_CONFIG_PATH.exists():
            default_config = {
                "default": {"rows": 1, "cols": 2},
                "CT": {"rows": 1, "cols": 2},
                "MR": {"rows": 1, "cols": 2},
                "MG": {"rows": 2, "cols": 2},
                "CR": {"rows": 1, "cols": 2},
                "DX": {"rows": 1, "cols": 2},
                "US": {"rows": 1, "cols": 2},
                "XA": {"rows": 1, "cols": 2},
                "RF": {"rows": 1, "cols": 2},
                "NM": {"rows": 1, "cols": 2},
                "PT": {"rows": 1, "cols": 2},
                "OT": {"rows": 1, "cols": 2}
            }
            
            try:
                GRID_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(GRID_CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                print(f"فایل config در {GRID_CONFIG_PATH} ایجاد شد.")
            except Exception as e:
                print(f"خطا در ایجاد فایل config: {e}")

    def check_metadata_belong_together(self, metadata1: dict, metadata2: dict):
        color_channel_1 = metadata1['instances'][-1]['is_rgb']
        color_channel_2 = metadata2['instances'][-1]['is_rgb']
        return color_channel_1 == color_channel_2

    def _combine_mg_metadata(self, mg_series_data):
        """
        ترکیب metadataهای چند series MG به یک metadata واحد
        """
        if not mg_series_data:
            return None

        # از اولین series به عنوان base استفاده کن
        first_vtk, first_metadata = mg_series_data[0]

        combined_metadata = {
            'series': first_metadata['series'].copy(),
            'instances': []
        }

        # instanceهای همه seriesها را جمع کن
        for vtk_data, metadata in mg_series_data:
            combined_metadata['instances'].extend(metadata.get('instances', []))

        return combined_metadata

    def add_series_name_to_lst_series_names(self, series_name):
        self.lst_series_name.add(series_name)

    def add_new_data_to_lst_thumbnails_data(self, new_data):
        """Add new data and update caches for optimal lookup performance"""
        series_number = str(new_data['metadata']['series']['series_number'])
        series_name = str(new_data['metadata']['series']['series_name'])
        # Ensure required attributes exist
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []
        if not hasattr(self, 'unique_elements_index'):
            self.unique_elements_index = 0
        
        add_by_head = True
        inserted_index = None
        metadata = new_data['metadata']
        incoming_is_preview = bool(metadata.get('preview_only', False))

        for i in range(len(self.lst_thumbnails_data)):
            existing_series = self.lst_thumbnails_data[i].get('metadata', {}).get('series', {})
            existing_series_number = str(existing_series.get('series_number'))
            existing_series_name = str(existing_series.get('series_name'))

            # If same series_number already exists, avoid duplicate insert.
            if existing_series_number == series_number:
                existing_metadata = self.lst_thumbnails_data[i].get('metadata', {})
                existing_is_preview = bool(existing_metadata.get('preview_only', False))
                if incoming_is_preview and (not existing_is_preview):
                    return False

                incoming_len = len(metadata.get('instances', []) or [])
                existing_len = len(existing_metadata.get('instances', []) or [])
                if incoming_len == existing_len and incoming_is_preview == existing_is_preview:
                    return False
                self.lst_thumbnails_data[i] = new_data
                inserted_index = i
                add_by_head = False
                break

            # We assume lst is such as left and right (front , back) queue without remove element
            # Only treat series_name as a pairing key when it is present.
            if existing_series_name and existing_series_name == metadata['series']['series_name']:
                # this series has been created before
                if len(metadata['instances']) == len(self.lst_thumbnails_data[i]['metadata']['instances']):
                    return False

                self.lst_thumbnails_data.append(new_data)
                inserted_index = len(self.lst_thumbnails_data) - 1
                add_by_head = False
                break  # this series is continued another series. so we added at last index lst

        if add_by_head:
            inserted_index = self.unique_elements_index
            self.lst_thumbnails_data.insert(self.unique_elements_index, new_data)
            self.unique_elements_index += 1

        # Update series cache only after list insertion/append so index is always correct.
        if inserted_index is None:
            for i, item in enumerate(self.lst_thumbnails_data):
                if str(item.get('metadata', {}).get('series', {}).get('series_number')) == series_number:
                    inserted_index = i
                    break
        if inserted_index is None:
            inserted_index = -1

        self.viewer_controller._series_cache[series_number] = (
            new_data['vtk_image_data'],
            new_data['metadata'],
            inserted_index
        )
        self.viewer_controller._series_name_cache[series_number] = series_name

        # ... بعد از منطق insert/append
        try:
            series_no = str(metadata['series']['series_number'])
            # حالا این سری آماده است
            if incoming_is_preview:
                self.thumbnail_manager.set_series_pending(series_no)
            else:
                self.thumbnail_manager.set_series_ready(series_no)

            # Update thumbnail image count from actual loaded instances
            try:
                actual_count = len(metadata.get('instances', []) or [])
            except Exception:
                actual_count = 0
            if (not incoming_is_preview) and actual_count > 0:
                if hasattr(self, '_server_series_info') and series_no in self._server_series_info:
                    self._server_series_info[series_no]['image_count'] = actual_count
                self.thumbnail_manager.update_series_image_count(series_no, actual_count)
            
            # ⚡ OPTIMIZATION: Rebuild indices after data change for fast lookups
            # This is a O(n) one-time cost when new series is added
            self.viewer_controller._rebuild_series_index()
        except Exception as e:
            print("set ready border failed:", e)

    def replace_series_data(self, series_number, vtk_image_data, metadata, file_path='', allow_append_if_missing: bool = True) -> int:
        """Replace existing series data (preview -> full) with optional append policy.

        Args:
            series_number: Target series number.
            vtk_image_data: VTK payload.
            metadata: Series metadata.
            file_path: Thumbnail path.
            allow_append_if_missing: When False, skip append-on-miss and return -1.

        Returns:
            Index of replaced/appended item, or -1 when not found (and append disallowed).
        """
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []

        series_number_str = str(series_number)
        incoming_is_preview = bool((metadata or {}).get('preview_only', False))
        new_data = {
            'vtk_image_data': vtk_image_data,
            'metadata': metadata,
            'file_path': file_path
        }
        
        print(f"[REPLACE_SERIES_DATA] series={series_number_str} vtk={vtk_image_data is not None} meta={metadata is not None} list_len={len(self.lst_thumbnails_data)}")

        for idx, item in enumerate(self.lst_thumbnails_data):
            try:
                item_series_str = str(item.get('metadata', {}).get('series', {}).get('series_number'))
                if item_series_str == series_number_str:
                    existing_meta = item.get('metadata', {}) or {}
                    existing_is_preview = bool(existing_meta.get('preview_only', False))
                    if incoming_is_preview and (not existing_is_preview):
                        print(f"[REPLACE_SERIES_DATA] Ignoring preview payload for full series={series_number_str}")
                        return idx

                    print(f"[REPLACE_SERIES_DATA] Found existing at idx={idx}, replacing")
                    self.lst_thumbnails_data[idx] = new_data
                    series_name = str(metadata.get('series', {}).get('series_name'))
                    self.viewer_controller._series_cache[series_number_str] = (vtk_image_data, metadata, idx)
                    self.viewer_controller._hot_series_cache[series_number_str] = (vtk_image_data, metadata, idx)
                    self.viewer_controller._series_name_cache[series_number_str] = series_name
                    try:
                        if incoming_is_preview:
                            self.thumbnail_manager.set_series_pending(series_number_str)
                        else:
                            self.thumbnail_manager.set_series_ready(series_number_str)
                        try:
                            actual_count = len(metadata.get('instances', []) or [])
                        except Exception:
                            actual_count = 0
                        if (not incoming_is_preview) and actual_count > 0:
                            if hasattr(self, '_server_series_info') and series_number_str in self._server_series_info:
                                self._server_series_info[series_number_str]['image_count'] = actual_count
                            self.thumbnail_manager.update_series_image_count(series_number_str, actual_count)
                    except Exception:
                        pass
                    self.viewer_controller._rebuild_series_index()
                    print(f"[REPLACE_SERIES_DATA] Successfully replaced and returning idx={idx}")
                    return idx
            except Exception as e:
                print(f"[REPLACE_SERIES_DATA] Error checking item {idx}: {e}")
                continue

        if not bool(allow_append_if_missing):
            print(
                f"[REPLACE_SERIES_DATA] series={series_number_str} not found and append disallowed, returning -1"
            )
            return -1

        print(f"[REPLACE_SERIES_DATA] Not found in list, calling add_new_data_to_lst_thumbnails_data")
        try:
            self.add_new_data_to_lst_thumbnails_data(new_data)
        except Exception as e:
            print(f"[REPLACE_SERIES_DATA] add_new_data_to_lst_thumbnails_data FAILED: {e}")
            import traceback
            traceback.print_exc()

        print(f"[REPLACE_SERIES_DATA] Searching for series={series_number_str} after add_new_data")
        for idx, item in enumerate(self.lst_thumbnails_data):
            try:
                item_series_str = str(item.get('metadata', {}).get('series', {}).get('series_number'))
                if item_series_str == series_number_str:
                    print(f"[REPLACE_SERIES_DATA] Found at idx={idx} after add_new_data")
                    return idx
            except Exception as e:
                print(f"[REPLACE_SERIES_DATA] Error checking item {idx} after add: {e}")
                continue

        print(f"[REPLACE_SERIES_DATA] FAILED: series={series_number_str} not found after add_new_data, returning -1")
        return -1

    def check_and_add_meta_fixed(self, patient_info):
        if len(self.metadata_fixed) != 0:
            return
        if not patient_info or len(patient_info) < 1:
            return

        patient_pk = patient_info[0]
        if patient_pk is None:
            return
        # study_pk = patient_info[1]

        print('patient_pk::', patient_pk)

        patient_data = get_patient_by_patient_pk(patient_pk)
        study_data = get_studies_by_patient_pk(patient_pk)

        print('patient_data:', patient_data)
        print('study_data:', study_data)

        if patient_data:
            self.metadata_fixed.update(patient_data)
        if study_data:
            self.metadata_fixed.update(study_data)

        if self.study_uid is None and study_data:
            self.study_uid = study_data.get('study_uid')

        self.update_tab_manager()
        try:
            if self.metadata_fixed.get('study_uid'):
                self.add_data_to_reception_layout()
        except Exception:
            pass

    def update_tab_manager(self, patient_name=None, patient_id=None):
        if self.tab_manager:
            current_index = self.tab_manager.tab_widget.currentIndex()

            patient_name = patient_name if patient_name else 'N/A'
            patient_id = patient_id if patient_id else 'N/A'

            self.tab_manager.update_patient_tab(
                current_index,
                patient_name=self.metadata_fixed.get('patient_name', patient_name),
                patient_id=self.metadata_fixed.get('patient_id', patient_id),
                thumbnail_path=self.logo_patient
            )

    def close_and_remove_patient_tab(self):
        if self.tab_manager:
            current_index = self.tab_manager.tab_widget.currentIndex()
            self.tab_manager.close_patient_tab(current_index)

    async def open_report_in_echo_mind(self, file_path):
        echo_mind_window = self.ai_chat_layout_ui()  # open ECHO MIND window

        await asyncio.sleep(0.1)
        echo_mind_window._open_mode_page('report')  # open report page

        # print('path audio:', self._file_path)
        echo_mind_window._page.composer._choose_file(file_path)  # send audio to report page

