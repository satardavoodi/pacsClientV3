# Standard library imports
import os
import asyncio
from pathlib import Path

# PySide6 imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QLabel, QSlider, QToolBar, QPushButton, QButtonGroup,
    QStackedWidget, QSizePolicy, QToolButton, QFrame, QGroupBox,
    QApplication
)

# Project imports
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
from PacsClient.pacs.patient_tab.utils import (
    ThumbnailManager, create_attachment_folder, open_folder,
    check_and_get_thumbnails, get_name_file_from_path,
    load_images, save_image_as_png, delete_widgets_in_layout, NodeViewer
)
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager


class VerticalButton(QPushButton):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.save()
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(0, 0, self.height(), self.width(),
                         Qt.AlignmentFlag.AlignCenter, self.text())
        painter.restore()


class PatientWidget(QWidget):
    """Main patient widget for displaying DICOM images and thumbnails"""

    def __init__(self, parent=None, import_folder_path: str = None, size_init_viewers=(2, 1),
                 caller: CallerTypes = None):
        """Initialize PatientWidget with default 2x1 layout for CT and MR"""
        super().__init__(parent)

        # Initialize core attributes
        self._init_attributes(import_folder_path)

        # Setup UI layout
        self._setup_main_layout()

        # Initialize components
        self._init_components()

        # Start data pipeline if folder path provided
        if self.import_folder_path:
            self.pipeline_manager(caller=caller, size_init_viewers=size_init_viewers)

    def _init_attributes(self, import_folder_path: str):
        """Initialize widget attributes"""
        # Data attributes
        self.import_folder_path = import_folder_path
        self.lst_thumbnails_data = []
        self.lst_nodes_viewer = []
        self.selected_widget: VTKWidget = None
        self.lst_series_name = set()
        self.metadata_fixed = {}
        self._series_index = {}  # map: series_key -> index in lst_thumbnails_data
        self.unique_elements_index = 0

        # Patient information for tab
        self.patient_name = "Loading..."
        self.patient_id = "N/A"
        self.first_thumbnail_path = None
        self.tab_manager = None

    def _setup_main_layout(self):
        """Setup main layout structure"""
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        self.header_layout_ui()

        # Body container
        self.container_layout = QHBoxLayout()
        self.container_layout.setSpacing(0)
        self.main_layout.addLayout(self.container_layout)

    def _init_components(self):
        """Initialize UI components in proper order: tabs (left) → series (center) → viewer (right)"""
        # Left sidebar with tabs (Series, Reception, AI Chat)
        self.sidebar = self.sidebar_layout_ui()
        self.container_layout.addWidget(self.sidebar)

        # Center panel with thumbnails/series (fixed width)
        self._setup_thumbnails_panel()
        self.container_layout.addWidget(self.thumbnails_panel)

        # Right viewer area (main content - should expand)
        self.viewer_widget = self.viewer_layout_ui()
        self.container_layout.addWidget(self.viewer_widget, 1)  # stretch factor 1

    def _setup_thumbnails_panel(self):
        """Setup center panel with thumbnails and reception info"""
        self.thumbnails_panel = QStackedWidget()
        self.thumbnails_panel.setFixedWidth(250)  # Width for thumbnails in center
        self.thumbnails_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        # Create panels
        self.thumb_panel = self.thumbnail_layout_ui()
        self.reception_panel = self.reception_layout_ui()
        self.thumbnail_manager = ThumbnailManager(self.change_series_on_viewer)

        # Add panels to stack
        self.thumbnails_panel.addWidget(self.thumb_panel)  # index 0
        self.thumbnails_panel.addWidget(self.reception_panel)  # index 1

    def _clear_data(self):
        """Clear all data structures"""
        self.lst_thumbnails_data = []
        self.lst_nodes_viewer = []
        self.selected_widget = None
        self.lst_series_name = set()
        self._series_index = {}
        self.unique_elements_index = 0

    def _init_metadata_for_sync(self):
        """Initialize metadata for synchronous loading"""
        self.metadata_fixed = {'caller': CallerTypes.SERVER}

        if self.import_folder_path:
            study_uid = Path(self.import_folder_path).name
            self.metadata_fixed.update({
                'study_uid': study_uid,
                'study_date': 'N/A',
                'study_time': 'N/A',
                'patient_name': getattr(self, 'patient_name', 'N/A'),
                'patient_id': getattr(self, 'patient_id', 'N/A'),
                'patient_sex': 'N/A',
                'patient_age': 'N/A',
                'institution_name': 'N/A'
            })

    def _load_series_from_folder(self):
        """Load series data from folder structure"""
        if not self.import_folder_path or not os.path.exists(self.import_folder_path):
            print(f"⚠️ Folder path not found: {self.import_folder_path}")
            return

        # Get series data from folder structure
        series_data = self.get_series_from_folder_simple(self.import_folder_path)

        if series_data:
            # Process series data
            for series_info in series_data:
                self.lst_thumbnails_data.append(series_info)
                if 'series_number' in series_info:
                    self.lst_series_name.add(str(series_info['series_number']))

            # Update UI using simple method
            self.display_series_simple(series_data)
            print(f"✅ Loaded {len(series_data)} series synchronously")
        else:
            print("⚠️ No series data found in folder")

    def pipeline_manager(self, caller, size_init_viewers=(2, 1)):
        """Manage data loading pipeline based on caller type"""
        try:
            # Check if we have a running event loop
            loop = asyncio.get_running_loop()

            if caller == CallerTypes.IMPORT:
                asyncio.create_task(self.pipeline_manager_import(caller=caller, size_init_viewers=size_init_viewers))
            elif caller == CallerTypes.SERVER:
                asyncio.create_task(self.pipeline_manager_server(caller=caller, size_init_viewers=size_init_viewers))

        except RuntimeError:
            # No running event loop - run synchronously
            print("🔄 No event loop found, running pipeline synchronously...")

            if caller == CallerTypes.SERVER:
                self.load_thumbnails_sync()
            else:
                print("⚠️ Import caller needs async support - skipping for now")

    def load_thumbnails_sync(self):
        """Load thumbnails synchronously when no event loop is available"""
        try:
            print("🖼️ Loading thumbnails synchronously...")

            # Clear existing data and initialize metadata
            self._clear_data()
            self._init_metadata_for_sync()

            # Load thumbnails from folder
            self._load_series_from_folder()

        except Exception as e:
            print(f"❌ Error loading thumbnails synchronously: {e}")
            import traceback
            traceback.print_exc()

    def display_series_simple(self, series_data):
        """Simple method to display series without complex processing"""
        try:
            print(f"🖼️ Displaying {len(series_data)} series...")

            # Just log the series data for now
            for series_info in series_data:
                print(f"📁 Series {series_info.get('series_number', 'Unknown')}: {series_info.get('file_count', 0)} files")

            # For now, just show a simple message that data is loaded
            print("✅ Series data loaded successfully - ready for viewing")

        except Exception as e:
            print(f"❌ Error in display_series_simple: {e}")
            import traceback
            traceback.print_exc()

    def get_series_from_folder_simple(self, folder_path):
        """Simple method to get series data from folder structure"""
        try:
            import os
            import glob
            import time

            print(f"🔍 DEBUG: Checking folder: {folder_path}")
            print(f"🔍 DEBUG: Folder exists: {os.path.exists(folder_path)}")

            if not os.path.exists(folder_path):
                print(f"❌ Folder does not exist: {folder_path}")
                return []

            # List all items in folder for debugging
            try:
                all_items = os.listdir(folder_path)
                print(f"🔍 DEBUG: All items in folder: {all_items}")
            except Exception as list_error:
                print(f"❌ Error listing folder contents: {list_error}")
                return []

            series_data = []

            # Look for series folders (numeric folders)
            for item in all_items:
                item_path = os.path.join(folder_path, item)
                print(f"🔍 DEBUG: Checking item: {item} -> {item_path}")
                print(f"🔍 DEBUG: Is directory: {os.path.isdir(item_path)}")
                print(f"🔍 DEBUG: Is digit: {item.isdigit()}")

                if os.path.isdir(item_path) and item.isdigit():
                    series_number = item
                    print(f"📁 Processing series folder: {series_number}")

                    # Count DICOM files in this series
                    dcm_files = glob.glob(os.path.join(item_path, "*.dcm"))
                    print(f"🔍 DEBUG: DCM files in {series_number}: {len(dcm_files)}")

                    if dcm_files:
                        # Create series info
                        series_info = {
                            'series_number': int(series_number),
                            'series_path': item_path,
                            'file_count': len(dcm_files),
                            'first_file': dcm_files[0] if dcm_files else None
                        }
                        series_data.append(series_info)
                        print(f"📁 Found series {series_number} with {len(dcm_files)} files")
                    else:
                        print(f"⚠️ No DCM files found in series {series_number}")

            # Sort by series number
            series_data.sort(key=lambda x: x['series_number'])
            print(f"✅ Found {len(series_data)} series in folder")

            # If no series found, wait for files to be written (multiple retries)
            if len(series_data) == 0:
                print("⏳ No series with files found, waiting for DICOM files to be written...")

                # Try multiple times with increasing delays
                for retry_count in range(5):  # Try 5 times
                    wait_time = 1 + retry_count  # 1, 2, 3, 4, 5 seconds
                    print(f"🔄 Retry {retry_count + 1}/5: Waiting {wait_time} seconds...")
                    time.sleep(wait_time)

                    # Check again
                    all_items = os.listdir(folder_path)
                    print(f"🔍 DEBUG: Items after {wait_time}s wait: {all_items}")

                    temp_series_data = []
                    for item in all_items:
                        item_path = os.path.join(folder_path, item)
                        if os.path.isdir(item_path) and item.isdigit():
                            dcm_files = glob.glob(os.path.join(item_path, "*.dcm"))
                            print(f"🔍 DEBUG: [Retry {retry_count + 1}] DCM files in {item}: {len(dcm_files)}")

                            if dcm_files:
                                series_info = {
                                    'series_number': int(item),
                                    'series_path': item_path,
                                    'file_count': len(dcm_files),
                                    'first_file': dcm_files[0]
                                }
                                temp_series_data.append(series_info)
                                print(f"📁 [Retry {retry_count + 1}] Found series {item} with {len(dcm_files)} files")

                    if temp_series_data:
                        series_data = temp_series_data
                        series_data.sort(key=lambda x: x['series_number'])
                        print(f"✅ [Retry {retry_count + 1}] Found {len(series_data)} series in folder")
                        break
                    else:
                        print(f"⏳ [Retry {retry_count + 1}] Still no files found, continuing...")

                if not series_data:
                    print("❌ No DICOM files found after all retries")

            return series_data

        except Exception as e:
            print(f"❌ Error reading series from folder: {e}")
            import traceback
            traceback.print_exc()
            return []

    def display_series_without_clearing(self, series_data):
        """
        Display series data without clearing existing thumbnails
        نمایش داده‌های سری بدون پاک کردن thumbnails موجود
        """
        try:
            print(f"🖼️ Displaying {len(series_data)} series without clearing existing thumbnails...")

            if not series_data:
                print("⚠️ No series data to display")
                return

            # Process each series and add to existing data
            for series_info in series_data:
                # Create thumbnail data in expected format
                thumbnail_data = {
                    'series_number': series_info.get('series_number', 0),
                    'series_path': series_info.get('series_path', ''),
                    'file_count': series_info.get('file_count', 0),
                    'first_file': series_info.get('first_file', ''),
                    'metadata': {
                        'series_number': series_info.get('series_number', 0),
                        'file_count': series_info.get('file_count', 0)
                    }
                }

                # Add to existing data if not already present
                series_exists = False
                for existing_data in self.lst_thumbnails_data:
                    if existing_data.get('series_number') == thumbnail_data['series_number']:
                        series_exists = True
                        break

                if not series_exists:
                    self.lst_thumbnails_data.append(thumbnail_data)
                    print(f"📁 Added series {thumbnail_data['series_number']} to display")
                else:
                    print(f"📁 Series {thumbnail_data['series_number']} already exists, skipping")

            # Trigger UI update without clearing
            if hasattr(self, 'update_thumbnails_display'):
                self.update_thumbnails_display()
            else:
                print("⚠️ update_thumbnails_display method not found")

        except Exception as e:
            print(f"❌ Error in display_series_without_clearing: {e}")
            import traceback
            traceback.print_exc()

    async def pipeline_manager_server(self, caller, size_init_viewers):
        # Check if import_folder_path is available
        if not self.import_folder_path:
            # Wait for folder path to be set
            max_wait_time = 30  # Maximum 30 seconds
            wait_count = 0
            while not self.import_folder_path and wait_count < max_wait_time:
                await asyncio.sleep(1.0)
                wait_count += 1

        # Ensure metadata_fixed is properly set with study_uid
        if not hasattr(self, 'metadata_fixed'):
            self.metadata_fixed = {}
        self.metadata_fixed['caller'] = CallerTypes.SERVER

        # Add study_uid and other required fields to metadata_fixed
        if self.import_folder_path:
            study_uid = Path(self.import_folder_path).name
            self.metadata_fixed['study_uid'] = study_uid
            self.metadata_fixed['study_date'] = 'N/A'  # Default value
            self.metadata_fixed['study_time'] = 'N/A'  # Default value
            self.metadata_fixed['patient_name'] = getattr(self, 'patient_name', 'N/A')
            self.metadata_fixed['patient_id'] = getattr(self, 'patient_id', 'N/A')
            self.metadata_fixed['patient_sex'] = 'N/A'  # Default value
            self.metadata_fixed['patient_age'] = 'N/A'  # Default value

        # 1) بررسی وجود تامب‌نیل‌ها و شروع دانلود خودکار در صورت نیاز
        thumb_index = 0
        thumbnails = check_and_get_thumbnails(self.import_folder_path)
        print(f"🔍 DEBUG: Found {len(thumbnails) if thumbnails else 0} cached thumbnails")

        if thumbnails:
            # تامب‌نیل‌ها وجود دارند - نمایش آنها
            for thumbnail_file in thumbnails:
                print(f"🔍 DEBUG: Loading cached thumbnail: {thumbnail_file}")
                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index, file_path_thumbnail=thumbnail_file)
        else:
            # تامب‌نیل‌ها وجود ندارند - شروع دانلود خودکار
            print("🚀 No thumbnails found - starting auto-download...")
            await self.start_auto_thumbnail_download()

        await asyncio.sleep(0.1)  # فرصت به UI

        load_viewer = True
        poll_interval = 0.2  # کاهش بیشتر فاصله پولینگ برای سرعت بیشتر
        max_attempts = 50  # Maximum 10 seconds (50 * 0.2)
        attempt_count = 0
        consecutive_empty_results = 0  # Track consecutive empty results
        max_empty_results = 3  # Stop after 3 consecutive empty results
        images_loaded = False  # Track if any images were loaded

        while attempt_count < max_attempts:
            attempt_count += 1
            try:
                # Check again if folder path is available
                if not self.import_folder_path:
                    await asyncio.sleep(poll_interval)
                    continue


                # Check if folder exists and has files
                import os
                if not os.path.exists(self.import_folder_path):
                    await asyncio.sleep(poll_interval)
                    continue

                # Check if folder has any files
                try:
                    files = os.listdir(self.import_folder_path)
                    if not files:
                        await asyncio.sleep(poll_interval)
                        continue
                except Exception as e:
                    print(f"❌ Error checking folder: {e}")
                    await asyncio.sleep(poll_interval)
                    continue

                try:
                    # Priority loading: process first series immediately, others in background
                    if load_viewer:
                        # For first viewer, process series one by one for immediate display
                        results = []
                        try:
                            series_generator = load_images(
                                self.import_folder_path,
                                patient_pk=self.metadata_fixed.get('patient_pk', None),
                                study_pk=self.metadata_fixed.get('study_pk', None),
                            )

                            # Process first series immediately
                            try:
                                first_result = await asyncio.to_thread(lambda: next(series_generator))
                                results.append(first_result)
                            except StopIteration:
                                results = []

                            # Schedule remaining series for background processing
                            if results:  # If we got the first series
                                asyncio.create_task(self._process_remaining_series_background(series_generator))
                        except Exception as load_error:
                            print(f"❌ Error loading images: {load_error}")
                            import traceback
                            traceback.print_exc()
                            results = []
                    else:
                        # Normal batch processing for subsequent loads
                        try:
                            results = await asyncio.to_thread(
                                lambda: list(load_images(
                                    self.import_folder_path,
                                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                                    study_pk=self.metadata_fixed.get('study_pk', None),
                                ))
                            )
                        except Exception as load_error:
                            print(f"❌ Error loading images in batch: {load_error}")
                            import traceback
                            traceback.print_exc()
                            results = []


                    # Track consecutive empty results
                    if not results or len(results) == 0:
                        consecutive_empty_results += 1
                        if consecutive_empty_results >= max_empty_results:
                            break
                    else:
                        consecutive_empty_results = 0  # Reset counter on successful load
                        images_loaded = True  # Mark that we've loaded some images

                except Exception as load_error:
                    print(f"❌ Error loading images: {load_error}")
                    consecutive_empty_results += 1
                    if consecutive_empty_results >= max_empty_results:
                        break
                    # Wait a bit before retrying
                    await asyncio.sleep(poll_interval)
                    continue
                    
                for vtk_image_data, metadata, patient_info in results:
                    self.check_and_add_meta_fixed(patient_info)

                    series_key = metadata['series']['series_name']
                    grown = None

                    # if len(metadata['instances']) != 1:  # else: go to create new element of lst_thumbnails
                    # if (len(metadata['instances']) != 1) or (int(metadata['instances'][0]['is_rgb']) == 0):
                    # print('series_key:', series_key)

                    if (series_key, metadata['instances'][-1]['is_rgb']) in self._series_index:
                        idx = self._series_index[(series_key, metadata['instances'][-1]['is_rgb'])]

                        # Safety check for selected_widget and image_viewer
                        if (self.selected_widget and
                            hasattr(self.selected_widget, 'image_viewer') and
                            self.selected_widget.image_viewer and
                            hasattr(self.selected_widget.image_viewer, 'metadata')):

                            flag_same_color_channel = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                            if flag_same_color_channel and (metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series']['series_number']):
                                grown = self.selected_widget.grow_current_series_inplace(vtk_image_data, metadata)

                        else:
                            flag_same_color_channel = self.check_metadata_belong_together(self.lst_thumbnails_data[idx]['metadata'], metadata)
                            if flag_same_color_channel:
                                old_vtk = self.lst_thumbnails_data[idx]['vtk_image_data']
                                grown = grow_vtk_inplace(old_vtk, vtk_image_data)

                        if flag_same_color_channel:
                            if grown:
                                self.lst_thumbnails_data[idx]['metadata'] = metadata
                            await asyncio.sleep(0)  # فرصت به UI
                            continue

                    # Use fast thumbnail generation for first series
                    from PacsClient.pacs.patient_tab.utils.utils import save_image_as_png_fast_first

                    # Check if this is the first series being processed
                    is_first_series = len(self.lst_thumbnails_data) == 0

                    if is_first_series:
                        file_path = save_image_as_png_fast_first(
                            vtk_image_data=vtk_image_data, metadata=metadata,
                            metadata_fixed=self.metadata_fixed,
                            file=metadata['series']['series_path']
                        )
                    else:
                        file_path = save_image_as_png(
                            vtk_image_data=vtk_image_data, metadata=metadata,
                            metadata_fixed=self.metadata_fixed,
                            file=metadata['series']['series_path']
                        )
                    thumb_index = self.add_thumbnail_to_thumbnail_layout(
                        thumb_index=thumb_index, file_path_thumbnail=file_path, metadata=metadata)

                    # self.lst_thumbnails_data.append(
                    #     {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                    # )
                    new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                    self.add_new_data_to_lst_thumbnails_data(new_data)

                    self._series_index[(series_key, metadata['instances'][-1]['is_rgb'])] = len(self.lst_thumbnails_data) - 1

                    if load_viewer:
                        # Initialize viewers for the first time
                        self.init_matrix_viewers(size_init_viewers)

                        # Now that we have data, create a real viewer for the first series
                        if self.lst_thumbnails_data and len(self.lst_thumbnails_data) > 0:
                            try:
                                # Clear placeholder viewers
                                self.clear_viewers()

                                # Create the first real viewer
                                real_viewer = self.new_viewer(0)

                                # Apply layout
                                self.apply_multi_viewer(size_init_viewers)

                                # Set as selected and render immediately
                                if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                                    self.selected_widget = self.lst_nodes_viewer[0]

                                # Force immediate render and apply reset like toolbar
                                try:
                                    vtk_widget = self.selected_widget.vtk_widget
                                    if (vtk_widget and hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer):
                                        vtk_widget.image_viewer.force_render_now()

                                        # Apply reset like toolbar reset button with delay
                                        # Use QTimer to apply reset after viewer is fully loaded
                                        from PySide6.QtCore import QTimer
                                        QTimer.singleShot(100, lambda: self._apply_reset_to_viewer(self.selected_widget))
                                except:
                                    pass

                                # Set load_viewer to False to prevent waiting for more series
                                load_viewer = False

                            except Exception as e:
                                print(f"Error creating first real viewer: {e}")

                        continue  # Skip the general display logic for the first series

                    # Only try to display the first few series to avoid overwhelming the viewer
                    # The user can switch between series using thumbnails
                    pass  # Series added to thumbnails

                    if self.selected_widget:
                        # Safety check for selected_widget and image_viewer
                        if (hasattr(self.selected_widget, 'image_viewer') and
                            self.selected_widget.image_viewer and
                            hasattr(self.selected_widget.image_viewer, 'metadata')):

                            flag_same_color_channel = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                            if (not flag_same_color_channel) and (metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series']['series_number']):
                                self.init_matrix_viewers(size_init_viewers)

                # Check if we have loaded all instances
                if caller == CallerTypes.SERVER and 'number_of_instances' in self.metadata_fixed:
                    number_of_instances_on_db = self.metadata_fixed['number_of_instances']
                    count_of_instances = 0

                    for i in range(len(self.lst_thumbnails_data)):
                        count_of_instances += len(self.lst_thumbnails_data[i]['metadata']['instances'])

                    if count_of_instances >= number_of_instances_on_db:
                        break

                # If we have results and they seem complete, break the loop
                if results and len(results) > 0:
                    # Check if we have a reasonable number of series loaded
                    if len(self.lst_thumbnails_data) >= len(results):
                        break

                # Early exit if we have loaded images and no new results for a while
                if images_loaded and consecutive_empty_results >= 2:
                    break

                # Check timeout
                if attempt_count >= max_attempts:
                    break

                await asyncio.sleep(poll_interval)

            except Exception as e:
                print('error in pipeline-manager:', e)
                # Don't continue indefinitely on errors
                if attempt_count > 10:  # After 10 failed attempts, break
                    print('❌ Too many errors, stopping pipeline')
                    break

            # Only print loading if we're still within reasonable attempts
            await asyncio.sleep(poll_interval)

    def check_metadata_belong_together(self, metadata1: dict, metadata2: dict):
        color_channel_1 = metadata1['instances'][-1]['is_rgb']
        color_channel_2 = metadata2['instances'][-1]['is_rgb']
        return color_channel_1 == color_channel_2

    async def pipeline_manager_import(self, caller, size_init_viewers):
        """
            Manage pipeline base on caller
            caller: server, import, local(db)
        """
        thumb_index = 0
        thumbnails = check_and_get_thumbnails(self.import_folder_path)
        print(f"🔍 DEBUG: Found {len(thumbnails) if thumbnails else 0} cached thumbnails in display_thumbnails_immediately")
        if thumbnails:
            for thumbnail_file in thumbnails:
                print(f"🔍 DEBUG: Loading cached thumbnail in display_thumbnails_immediately: {thumbnail_file}")
                thumb_index = self.add_thumbnail_to_thumbnail_layout(thumb_index=thumb_index,
                                                                     file_path_thumbnail=thumbnail_file)

        # QApplication.processEvents()  # به Qt فرصت repaint بده
        await asyncio.sleep(0.1)  # به حلقۀ asyncio هم فرصت بده

        load_viewer = True
        # while True:
        for vtk_image_data, metadata, patient_info in load_images(self.import_folder_path,
                                                                  patient_pk=self.metadata_fixed.get('patient_pk',
                                                                                                     None),
                                                                  study_pk=self.metadata_fixed.get('study_pk', None)):
            self.check_and_add_meta_fixed(patient_info)

            file_path = metadata['series']['series_path']
            file_path = save_image_as_png(vtk_image_data=vtk_image_data, metadata=metadata,
                                          metadata_fixed=self.metadata_fixed, file=file_path)

            thumb_index = self.add_thumbnail_to_thumbnail_layout(
                thumb_index=thumb_index, file_path_thumbnail=file_path, metadata=metadata)

            new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
            self.add_new_data_to_lst_thumbnails_data(new_data)

            # self.lst_thumbnails_data.append(
            #     {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path})

            # self.add_series_name_to_lst_series_names(metadata['meta_fixed']['series_name'])

            if load_viewer:
                # self.init_matrix_viewers((1, 1))
                self.init_matrix_viewers(size_init_viewers)
                load_viewer = False

            if self.selected_widget:  # reload again if series is rgb and grayscale together
                flag_same_color_channel = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                if (not flag_same_color_channel) and (metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series']['series_number']):
                    self.init_matrix_viewers(size_init_viewers)

            QApplication.processEvents()  # به Qt فرصت repaint بده
            await asyncio.sleep(0)  # به حلقۀ asyncio هم فرصت بده

    def clear_viewers(self):
        """Clear existing viewers and clean up resources"""
        try:
            # Clear the layout
            while self.vtk_layout.count():
                child = self.vtk_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            # Clear the list
            self.lst_nodes_viewer.clear()
            self.selected_widget = None

        except Exception as e:
            import traceback
            traceback.print_exc()

    def init_matrix_viewers(self, size_init_viewers):
        """Initialize matrix of viewers with specified size"""
        try:
            # Clear existing viewers
            self.clear_viewers()

            # Check if we have thumbnail data to create viewers
            if not self.lst_thumbnails_data or len(self.lst_thumbnails_data) == 0:
                # Create placeholder viewers without data
                rows, cols = size_init_viewers
                for row in range(rows):
                    for col in range(cols):
                        # Create a simple placeholder NodeViewer
                        placeholder_viewer = self.create_placeholder_viewer()
                        self.lst_nodes_viewer.append(placeholder_viewer)

                # Apply the layout
                self.apply_multi_viewer(size_init_viewers)

                # Set the first viewer as selected by default
                if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                    self.selected_widget = self.lst_nodes_viewer[0]
                return

            # Create new viewers using the proper new_viewer method
            rows, cols = size_init_viewers
            for row in range(rows):
                for col in range(cols):
                    try:
                        # Use the existing new_viewer method to create a proper viewer
                        viewer = self.new_viewer(0)  # Use default thumbnail index
                        # Note: new_viewer already appends to lst_nodes_viewer
                    except Exception as viewer_error:
                        print(f"Error creating viewer {row},{col}: {viewer_error}")
                        # Continue with other viewers instead of crashing
                        continue

            # Apply the layout
            self.apply_multi_viewer(size_init_viewers)

            # Set the first viewer as selected by default
            if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                self.selected_widget = self.lst_nodes_viewer[0]

        except Exception as e:
            print(f"Error initializing matrix viewers: {e}")
            import traceback
            traceback.print_exc()

    def create_placeholder_viewer(self):
        """Create a placeholder NodeViewer without data"""
        try:
            from PySide6.QtWidgets import QWidget, QGridLayout, QSlider, QLabel
            from PySide6.QtCore import Qt

            # Create a simple container with a label
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Create a placeholder label
            placeholder_label = QLabel("Loading...")
            placeholder_label.setAlignment(Qt.AlignCenter)
            placeholder_label.setStyleSheet("""
                QLabel {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    border: 1px solid #90caf9;
                    border-radius: 5px;
                    font-size: 14px;
                    padding: 20px;
                }
            """)

            layout.addWidget(placeholder_label, 0, 0)

            container = QWidget()
            container.setLayout(layout)
            container.setStyleSheet("""
                border: 2px solid #90caf9;
                border-radius: 5px;
                margin: 0px;
                padding: 0px;
            """)

            # Create a placeholder NodeViewer with None vtk_widget
            placeholder_viewer = NodeViewer(container, None, None)
            return placeholder_viewer

        except Exception as e:
            print(f"Error creating placeholder viewer: {e}")
            return None

    def add_series_name_to_lst_series_names(self, series_name):
        self.lst_series_name.add(series_name)

    def add_new_data_to_lst_thumbnails_data(self, new_data):
        add_by_head = True
        metadata = new_data['metadata']

        for i in range(len(self.lst_thumbnails_data)):
            # we assume lst is such as left and right (front , back) queue without remove element
            if self.lst_thumbnails_data[i]['metadata']['series']['series_name'] == metadata['series']['series_name']:
                self.lst_thumbnails_data.append(new_data)
                add_by_head = False
                break  # this series is continued another series. so we added at last index lst

        if add_by_head:
            self.lst_thumbnails_data.insert(self.unique_elements_index, new_data)
            self.unique_elements_index += 1

    def check_and_add_meta_fixed(self, patient_info):
        if len(self.metadata_fixed) != 0:
            return

        patient_pk = patient_info[0]
        # study_pk = patient_info[1]

        patient_data = get_patient_by_patient_pk(patient_pk)
        study_data = get_studies_by_patient_pk(patient_pk)

        self.metadata_fixed.update(patient_data)
        self.metadata_fixed.update(study_data)

        # Update tab information when metadata is loaded
        self.update_tab_info()

    def header_layout_ui(self):
        # ===== Header Layout =====
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(0)

        toolbar = QToolBar()
        toolbar.setStyleSheet('''
            QToolBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
                border: 1px solid #374151;
                border-radius: 12px;
                padding: 2px;
                spacing: 2px;
            }
            QToolBar::separator:horizontal {
                width: 1px;
                background-color: #4b5563;
                margin: 1px 4px;
            }
        ''')
        self.toolbar_manager = ToolbarManager(self)

        # Call the add_toolbar_actions method from ToolbarManager to add actions
        self.toolbar_manager.add_toolbar_actions(toolbar)

        # toolbar.setLayoutDirection(Qt.RightToLeft)
        toolbar.setContentsMargins(8, 4, 8, 4)
        header_layout.addWidget(toolbar)
        # header_layout.addWidget(toolbar, alignment=Qt.AlignmentFlag.AlignCenter)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # header_layout.addStretch()  # set space from right

        self.main_layout.addLayout(header_layout)
        return header_layout

    ##############################################################################################
    def sidebar_layout_ui(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(40)
        sidebar.setStyleSheet("""
            background-color: #171b1e;
            border-top-left-radius: 12px;
            border-bottom-left-radius: 12px;
            margin: 0px;
            padding: 0px;
        """)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Sidebar buttons
        self.btn_series = VerticalButton("Series")
        self.btn_series.setFixedHeight(100)
        self.btn_series.setCheckable(True)
        self.btn_series.setChecked(True)
        self.btn_series.setStyleSheet(self.sidebar_btn_style(True))

        self.btn_reception = VerticalButton("Reception Data")
        self.btn_reception.setFixedHeight(100)
        self.btn_reception.setCheckable(True)
        self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))

        # AI Chat button
        self.btn_ai_chat = VerticalButton("AI Chat")
        self.btn_ai_chat.setFixedHeight(100)
        self.btn_ai_chat.setCheckable(True)
        self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))

        # group for exclusive selection
        self.sidebar_btn_group = QButtonGroup(sidebar)
        self.sidebar_btn_group.setExclusive(True)
        self.sidebar_btn_group.addButton(self.btn_series)
        self.sidebar_btn_group.addButton(self.btn_reception)
        self.sidebar_btn_group.addButton(self.btn_ai_chat)

        layout.addWidget(self.btn_series)
        layout.addWidget(self.btn_reception)
        layout.addWidget(self.btn_ai_chat)
        layout.addStretch()

        # Connect button signals
        self.btn_series.clicked.connect(lambda: self.switch_thumbnails_panel("series"))
        self.btn_reception.clicked.connect(lambda: self.switch_thumbnails_panel("reception"))
        self.btn_ai_chat.clicked.connect(lambda: self.switch_thumbnails_panel("ai_chat"))

        return sidebar

    def sidebar_btn_style(self, checked):
        if checked:
            return """
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 0;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: #222;
                    color: #aaa;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 0;
                }
            """

    def switch_thumbnails_panel(self, option):
        """Switch between different panels in the center thumbnails area"""
        if option == "series":
            self.thumbnails_panel.setCurrentIndex(0)
            self.btn_series.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
        elif option == "reception":
            self.thumbnails_panel.setCurrentIndex(1)
            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
        elif option == "ai_chat":
            # Create AI Chat widget if it doesn't exist
            if not hasattr(self, 'ai_chat_widget'):
                try:
                    from PacsClient.pacs.patient_tab.viewers.ai_chat_viewer import AIChatViewer
                    self.ai_chat_widget = AIChatViewer()
                    self.thumbnails_panel.addWidget(self.ai_chat_widget)
                except Exception as e:
                    print(f"Error creating AI Chat widget: {e}")
                    return

            # Switch to AI Chat panel
            try:
                self.thumbnails_panel.setCurrentWidget(self.ai_chat_widget)
            except Exception as e:
                print(f"Error switching to AI Chat widget: {e}")
                return

            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(True))

    ########################################################
    def thumbnail_layout_ui(self):
        """Thumbnail panel for center area - series thumbnails display"""
        # Main panel
        thumbnail_panel = QWidget()
        thumbnail_panel.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: 1px solid #374151;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)

        thumbnail_panel.setFixedWidth(250)  # Slightly wider for better thumbnail display
        thumbnail_layout = QVBoxLayout(thumbnail_panel)
        thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        thumbnail_layout.setSpacing(6)

        # Enhanced header matching right panel
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title_label = QLabel("Series Thumbnails")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)

        # Count indicator
        self.thumb_count_label = QLabel("0 series")
        self.thumb_count_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
        """)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.thumb_count_label)
        thumbnail_layout.addWidget(header_widget)

        # Scroll area with right panel styling
        thumb_scroll = QScrollArea()
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        thumb_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                border-radius: 8px;
                background: #0f1419;
            }
            QScrollBar:vertical {
                border: none;
                background: #0f1419;
                width: 14px;
                border-radius: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a5568, stop:1 #718096);
                border-radius: 8px;
                min-height: 30px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #718096, stop:1 #a0aec0);
            }
        """)

        # Content container
        thumb_container = QWidget()
        thumb_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)

        self.thumb_grid = QGridLayout(thumb_container)
        # Move thumbnail to the left side with minimal margins
        # Small left margin, larger right margin to push thumbnail left
        self.thumb_grid.setContentsMargins(8, 6, 14, 6)  # Left-aligned with proper spacing
        self.thumb_grid.setHorizontalSpacing(6)  # Reduced spacing for better fit
        self.thumb_grid.setVerticalSpacing(6)   # Reduced spacing for better fit
        self.thumb_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # Align thumbnails to the left
        thumb_scroll.setWidget(thumb_container)
        thumbnail_layout.addWidget(thumb_scroll)

        return thumbnail_panel

    def add_thumbnail_to_thumbnail_layout(self, thumb_index, file_path_thumbnail, metadata=None):
        """Add thumbnail to layout with series info"""
        if metadata:  # it means that we loaded vtk_image_data, metadata
            # add new thumbnails
            if not metadata['series']['main_thumbnail']:
                return thumb_index  # we don't add new thumbnail

            series_name = str(metadata['series']['series_number'])

        else:
            series_name = get_name_file_from_path(file_path_thumbnail)

        if series_name in self.thumbnail_manager.lst_buttons_name:
            return thumb_index  # we don't add new thumbnail

        pixmap = QPixmap(file_path_thumbnail)

        # Extract series info from metadata or database
        series_info = None
        if metadata:
            series_info = {
                'series_number': metadata['series'].get('series_number', series_name),
                'modality': metadata['series'].get('modality', 'Unknown'),
                'series_description': metadata['series'].get('series_description', ''),
                'image_count': len(metadata.get('instances', [])),
                'protocol_name': metadata['series'].get('protocol_name', ''),
                'body_part_examined': metadata['series'].get('body_part_examined', '')
            }
        else:
            # For cached thumbnails, try to get series info from database
            print(f"🔍 DEBUG: Processing cached thumbnail for series {series_name}")
            try:
                series_info = self.get_cached_series_metadata(series_name)
                print(f"🔍 DEBUG: Got series_info from database: {series_info}")
                if not series_info:  # If database lookup fails, create basic info
                    print(f"🔍 DEBUG: Database lookup failed, creating fallback info")
                    series_info = {
                        'series_number': series_name,
                        'modality': 'Unknown',
                        'series_description': f'Series {series_name}',
                        'image_count': 0,
                        'protocol_name': '',
                        'body_part_examined': ''
                    }
            except Exception as e:
                print(f"Error getting cached series info: {str(e)}")
                # Fallback to basic info
                series_info = {
                    'series_number': series_name,
                    'modality': 'Unknown',
                    'series_description': f'Series {series_name}',
                    'image_count': 0,
                    'protocol_name': '',
                    'body_part_examined': ''
                }

        # Determine if this is a new download (show progress) or existing (no progress)
        show_progress = metadata is not None and metadata.get('is_downloading', False)

        thumb_widget = self.thumbnail_manager.create_thumbnail_widget(
            pixmap=pixmap,
            label_text=series_name,
            sop_instance_uid='test uid',
            thumbnail_index=thumb_index,
            series_info=series_info,
            show_progress=show_progress
        )

        # Add to grid in single column layout
        self.thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 1)

        # Update count label
        if hasattr(self, 'thumb_count_label'):
            self.thumb_count_label.setText(f"{thumb_index + 1} series")

        # Set first thumbnail for tab if this is the first one
        if thumb_index == 0 and not self.first_thumbnail_path:
            self.first_thumbnail_path = file_path_thumbnail
            print(f"🔍 DEBUG: Setting first_thumbnail_path = {file_path_thumbnail}")
            self.on_thumbnail_added(file_path_thumbnail)

        return thumb_index + 1

    def reception_layout_ui(self):
        # reception_panel = QWidget()
        # reception_panel.setFixedWidth(250)
        #
        # reception_panel.setStyleSheet('''
        #     background-color: #21272a;
        #     border: 0.5px solid;
        #     border-radius: 10px;
        #     padding: 0px;
        #
        # ''')

        def create_line():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            line.setStyleSheet("color: white; margin: 0px;")
            return line

        reception_group = QGroupBox()
        reception_group.setStyleSheet('padding: 0px; margin: 0px;')

        reception_layout = QVBoxLayout()
        reception_layout.setSpacing(4)  # Reduce spacing
        reception_layout.setContentsMargins(6, 6, 6, 6)  # Reduce margins
        reception_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # self.label_p_name = QLabel(f'  Patient Name:  {p_name}')
        # self.label_p_id = QLabel(f'  Patient Id:  {p_id}')
        # self.label_h_name = QLabel(f'  Hospital Name:  {h_name}')

        self.label_p_name = QLabel(f'  Patient Name: ')
        self.label_p_id = QLabel(f'  Patient Id: ')
        self.label_h_name = QLabel(f'  Hospital Name: ')

        reception_layout.addWidget(self.label_p_name)
        reception_layout.addWidget(create_line())

        reception_layout.addWidget(self.label_p_id)
        reception_layout.addWidget(create_line())

        reception_layout.addWidget(self.label_h_name)
        reception_layout.addWidget(create_line())

        self.btn_open_folder_attachments = QPushButton('Open Attachments')
        self.btn_open_folder_attachments.setFixedHeight(50)
        reception_layout.addWidget(self.btn_open_folder_attachments)

        reception_group.setLayout(reception_layout)
        return reception_group

    def add_data_to_reception_layout(self):
        # metadata = self.lst_thumbnails_data[0]['metadata']['meta_fixed']
        # file_path = self.lst_thumbnails_data[0]['metadata']['path']

        metadata = self.lst_thumbnails_data[0]['metadata']
        file_path = self.lst_thumbnails_data[0]['metadata']['series']['series_path']

        create_attachment_folder(file_path)

        # p_name = metadata['patient_name']
        # p_id = metadata['patient_id']
        # h_name = metadata['hospital_name']

        p_name = self.metadata_fixed['patient_name']
        p_id = self.metadata_fixed['patient_id']
        h_name = self.metadata_fixed['institution_name']

        self.label_p_name.setText(f'  Patient Name:  {p_name}')
        self.label_p_id.setText(f'  Patient Id:  {p_id}')
        self.label_h_name.setText(f'  Hospital Name:  {h_name}')

        self.btn_open_folder_attachments.clicked.connect(lambda: open_folder(file_path))

    ##############################################################################################

    def viewer_layout_ui(self):
        """Create viewer area with grid layout for multiple viewers (right side)"""
        viewer_widget = QWidget()
        viewer_widget.setStyleSheet('''
            QWidget {
                background-color: #21272a;
                border: 1px solid #374151;
                border-radius: 10px;
                margin: 0px;
                padding: 0px;
            }
        ''')

        # Use grid layout for 2x1 default layout (2 columns, 1 row)
        self.vtk_layout = QGridLayout(viewer_widget)
        self.vtk_layout.setContentsMargins(2, 2, 2, 2)  # Small margins for visual separation
        self.vtk_layout.setSpacing(2)  # Small spacing between viewers

        # Set stretch factors to make viewers expand equally
        self.vtk_layout.setColumnStretch(0, 1)
        self.vtk_layout.setColumnStretch(1, 1)
        self.vtk_layout.setRowStretch(0, 1)

        return viewer_widget

    def new_viewer(self, default_thumb_index=0):
        """Create a new VTK viewer with slider controls"""
        # Create VTK widget and slider
        vtk_widget = self.create_new_vtk_widget(default_thumb_index)
        slider = self._create_viewer_slider(vtk_widget)

        # Create container layout
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Add widgets to layout
        layout.addWidget(vtk_widget, 0, 0)
        layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight)

        # Create container widget
        container = self._create_viewer_container(layout)

        # Create and configure NodeViewer
        new_node = self._setup_node_viewer(container, vtk_widget, slider)

        return new_node

    def _create_viewer_slider(self, vtk_widget):
        """Create and configure slider for VTK viewer"""
        slider = QSlider(Qt.Vertical, vtk_widget)
        slider.setInvertedAppearance(True)

        slider.setStyleSheet("""
            QSlider {
                background: rgba(0, 0, 0, 1);
                border-radius: 0px;
                border: none;
                padding-top: 50px;
                padding-bottom: 50px;
            }
            QSlider::groove:vertical {
                background: #90caf9;
                width: 6px;
                border-radius: 3px;
            }
            QSlider::handle:vertical {
                background: #90caf9;
                border: none;
                width: 0;
                height: 0;
                border-radius: 0;  /* نصف عرض و ارتفاع */
                margin: 0;
            }
            QSlider::handle:vertical:hover {
                background: #5d99c6;
            }
            QSlider::sub-page:vertical {
                background: #90caf9;
                border-radius: 3px;
            }
            QSlider::add-page:vertical {
                background: rgba(0,0,0,0.5);
                border-radius: 3px;
            }
        """)

        return slider

    def _create_viewer_container(self, layout):
        """Create container widget for viewer"""
        container = QWidget()
        container.setLayout(layout)
        # Set default border style for viewport
        container.setStyleSheet("""
            QWidget {
                border: 2px solid #4a5568;
                border-radius: 5px;
                margin: 1px;
                padding: 0px;
                background: rgba(26, 32, 44, 0.3);
            }
        """)
        return container

    def _setup_node_viewer(self, container, vtk_widget, slider):
        """Setup NodeViewer with container, vtk_widget, and slider"""
        new_node = NodeViewer(container, vtk_widget, slider)
        self.lst_nodes_viewer.append(new_node)
        
        vtk_widget.set_slider(slider)
        count_slices = vtk_widget.get_count_of_slices()
        # mid_slices = count_slices // 2
        mid_slices = 0
        last_slices = count_slices - 1

        slider.setMinimum(0)
        slider.setMaximum(last_slices)

        slider.setValue(mid_slices)

        self.on_slider_value_changed(vtk_widget, mid_slices)  # set middle slice to show
        slider.valueChanged.connect(lambda: self.on_slider_value_changed(vtk_widget, slider.value()))

        vtk_widget.set_method_change_series_on_drop(self.change_series_on_viewer)
        vtk_widget.set_method_change_container_border(self.change_container_border)

        # Set first viewport as selected by default
        if len(self.lst_nodes_viewer) == 1:
            self.change_container_border(0)

        return new_node

    def on_slider_value_changed(self, vtk_widget, value):
        vtk_widget.set_slice(value)

    def apply_multi_viewer(self, numbers):

        def set_viewers_1x1():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            # self.set_viewer_to_main_viewer(self.lst_nodes_viewer[0])
            self.change_container_border(0)

        def set_viewers_2x1():
            """2 columns, 1 row layout (default for CT/MR)"""
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.change_container_border(0)

        def set_viewers1x3():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.change_container_border(0)

        def set_viewers1x4():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 0, 3)
            self.change_container_border(0)

        def set_viewers_1x2():
            """1 column, 2 rows layout"""
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
            self.change_container_border(0)

        def set_viewers3x1():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 2, 0)
            self.change_container_border(0)

        def set_viewers4x1():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 3, 0)
            self.change_container_border(0)

        def set_viewers2x2():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 1)
            # self.set_viewer_to_main_viewer(self.lst_nodes_viewer[0])
            self.change_container_border(0)

        def set_viewers2x3():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 1, 2)
            self.change_container_border(0)

        def set_viewers2x4():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 0, 3)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[6].widget, 1, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[7].widget, 1, 3)
            self.change_container_border(0)

        ########
        def set_viewers3x2():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 2, 1)
            self.change_container_border(0)

        def set_viewers3x3():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 1, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[6].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[7].widget, 2, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[8].widget, 2, 2)
            self.change_container_border(0)

        def set_viewers3x4():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 0, 3)

            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[6].widget, 1, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[7].widget, 1, 3)

            self.vtk_layout.addWidget(self.lst_nodes_viewer[8].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[9].widget, 2, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[10].widget, 2, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[11].widget, 2, 3)
            self.change_container_border(0)

        def set_viewers4x2():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 2, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[6].widget, 3, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[7].widget, 3, 1)
            self.change_container_border(0)

        def set_viewers4x3():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 1, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[6].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[7].widget, 2, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[8].widget, 2, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[9].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[10].widget, 2, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[11].widget, 2, 2)
            self.change_container_border(0)

        def set_viewers4x4():
            self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 0, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 0, 3)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[4].widget, 1, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[5].widget, 1, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[6].widget, 1, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[7].widget, 1, 3)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[8].widget, 2, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[9].widget, 2, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[10].widget, 2, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[11].widget, 2, 3)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[12].widget, 3, 0)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[13].widget, 3, 1)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[14].widget, 3, 2)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[15].widget, 3, 3)
            self.change_container_border(0)

        def manage_parameters_create_viewer(row, column):
            matrix_view = (row, column)
            self._clear_layout(self.vtk_layout)
            self.lst_nodes_viewer.clear()

            self.create_some_viewers(number_of_row * number_of_column)

            if matrix_view == (1, 1):
                set_viewers_1x1()

            elif matrix_view == (1, 2):
                set_viewers_1x2()

            elif matrix_view == (1, 3):
                set_viewers1x3()

            elif matrix_view == (1, 4):
                set_viewers1x4()

            #######
            elif matrix_view == (2, 1):
                set_viewers_2x1()  # This is our default 2x1 layout

            elif matrix_view == (3, 1):
                set_viewers3x1()

            elif matrix_view == (4, 1):
                set_viewers4x1()

            ##########

            elif matrix_view == (2, 2):
                set_viewers2x2()

            elif matrix_view == (2, 3):
                set_viewers2x3()

            elif matrix_view == (2, 4):
                set_viewers2x4()

            ##########

            elif matrix_view == (3, 2):
                set_viewers3x2()

            elif matrix_view == (3, 3):
                set_viewers3x3()

            elif matrix_view == (3, 4):
                set_viewers3x4()

            #####################
            elif matrix_view == (4, 2):
                set_viewers4x2()

            elif matrix_view == (4, 3):
                set_viewers4x3()

            elif matrix_view == (4, 4):
                set_viewers4x4()

        # numbers = self.line_edit_size_viewer.text()
        number_of_row, number_of_column = int(numbers[0]), int(numbers[1])
        lst_row_column_valid = [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (3, 1), (4, 1), (2, 2), (2, 3), (2, 4),
                                (3, 2), (3, 3), (3, 4), (4, 2), (4, 3), (4, 4)]

        if (number_of_row, number_of_column) in lst_row_column_valid:
            manage_parameters_create_viewer(number_of_row, number_of_column)

        else:
            print(f'numbers {number_of_row}, {number_of_column} are not valid.')

    def _clear_layout(self, layout):
        """Clear all items from a layout"""
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def create_some_viewers(self, count):
        last_viewer_index = 0
        for i in range(count):
            try:
                # it's means we have series at enough
                self.new_viewer(i)
                last_viewer_index = i
            except:
                # we don't have series at enough. so we create from last series until row * col
                self.new_viewer(last_viewer_index)

    # ===== Custom Tab Management Methods =====

    def set_tab_manager(self, tab_manager):
        """Set the tab manager for this patient widget"""
        self.tab_manager = tab_manager

    def update_tab_info(self):
        """Update the tab with current patient information"""
        print(f"🔍 DEBUG: update_tab_info called")
        print(f"🔍 DEBUG: Has tab_manager: {hasattr(self, 'tab_manager') and self.tab_manager is not None}")
        print(f"🔍 DEBUG: Has metadata_fixed: {hasattr(self, 'metadata_fixed') and bool(self.metadata_fixed)}")
        print(f"🔍 DEBUG: first_thumbnail_path: {self.first_thumbnail_path}")
        print(f"🔍 DEBUG: patient_name: {self.patient_name}")
        print(f"🔍 DEBUG: patient_id: {self.patient_id}")

        if self.tab_manager:
            # Use current patient info or extract from metadata_fixed if available
            patient_name = self.patient_name
            patient_id = self.patient_id

            if hasattr(self, 'metadata_fixed') and self.metadata_fixed:
                # Extract patient information from metadata
                patient_name = self.metadata_fixed.get('patient_name', patient_name)
                patient_id = self.metadata_fixed.get('patient_id', patient_id)

                # Update local patient info
                self.patient_name = patient_name
                self.patient_id = patient_id

                # Find first thumbnail path from lst_thumbnails_data if not already set
                if not self.first_thumbnail_path and self.lst_thumbnails_data:
                    first_thumbnail = self.lst_thumbnails_data[0]
                    if 'file_path' in first_thumbnail:
                        self.first_thumbnail_path = first_thumbnail['file_path']

            # Update tab
            print(f"🔍 DEBUG: Updating tab with patient_name={patient_name}, patient_id={patient_id}, thumbnail_path={self.first_thumbnail_path}")
            current_index = self.tab_manager.tab_widget.currentIndex()
            self.tab_manager.update_patient_tab(
                current_index,
                patient_name=patient_name,
                patient_id=patient_id,
                thumbnail_path=self.first_thumbnail_path
            )
            print(f"🔍 DEBUG: Tab update completed")

    def get_patient_info(self):
        """Get current patient information"""
        return {
            'patient_name': self.patient_name,
            'patient_id': self.patient_id,
            'thumbnail_path': self.first_thumbnail_path
        }

    def on_thumbnail_added(self, thumbnail_path):
        """Called when a new thumbnail is added"""
        print(f"🔍 DEBUG: on_thumbnail_added called with path: {thumbnail_path}")
        print(f"🔍 DEBUG: Current first_thumbnail_path: {self.first_thumbnail_path}")
        print(f"🔍 DEBUG: Has tab_manager: {hasattr(self, 'tab_manager') and self.tab_manager is not None}")

        # Always update tab info if we have a tab manager and thumbnail path
        if self.tab_manager and thumbnail_path:
            print(f"🔍 DEBUG: Calling update_tab_info with thumbnail: {thumbnail_path}")
            self.update_tab_info()

    def load_patient_info_immediately(self, patient_pk=None):
        """Load patient information immediately from database"""
        try:
            if patient_pk is None and hasattr(self, 'patient_pk'):
                patient_pk = self.patient_pk

            if patient_pk:
                print(f"🔍 Loading patient info immediately for patient_pk: {patient_pk}")

                # Import database functions from correct module
                from PacsClient.utils.db_manager import get_patient_by_patient_pk, get_studies_by_patient_pk

                # Get patient data
                patient_data = get_patient_by_patient_pk(patient_pk)
                if patient_data:
                    patient_name = patient_data.get('patient_name', 'Unknown')
                    patient_id = patient_data.get('patient_id', 'N/A')

                    print(f"✅ Found patient data: {patient_name} ({patient_id})")

                    # Update local patient info
                    self.patient_name = patient_name
                    self.patient_id = patient_id

                    # Update tab immediately
                    if self.tab_manager:
                        current_index = self.tab_manager.tab_widget.currentIndex()
                        print(f"📋 Updating tab at index {current_index}")
                        self.tab_manager.update_patient_tab(
                            current_index,
                            patient_name=self.patient_name,
                            patient_id=self.patient_id,
                            thumbnail_path=self.first_thumbnail_path
                        )
                        print(f"✅ Tab updated successfully")
                    else:
                        print(f"⚠️ No tab manager available")

                    print(f"✅ Patient info loaded immediately: {patient_name} ({patient_id})")
                else:
                    print(f"❌ No patient data found for patient_pk: {patient_pk}")
            else:
                print(f"❌ No patient_pk provided")

        except Exception as e:
            print(f"❌ Error loading patient info immediately: {e}")
            import traceback
            traceback.print_exc()

    def set_patient_pk(self, patient_pk):
        """Set patient PK and load info immediately"""
        self.patient_pk = patient_pk
        self.load_patient_info_immediately(patient_pk)

        # Also set up a fallback timer to ensure tab gets updated
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.load_patient_info_immediately(patient_pk))
        timer.start(1000)  # Try again after 1 second

    def update_folder_path(self, folder_path):
        """Update the folder path and reload the study"""
        try:
            print(f"🔄 Updating folder path to: {folder_path}")

            # Clear cache to ensure fresh data loading
            from PacsClient.pacs.patient_tab.utils.utils import clear_study_cache
            study_uid = Path(folder_path).name
            clear_study_cache(study_uid)

            self.import_folder_path = folder_path

            # Set caller type for server downloads
            if not hasattr(self, 'metadata_fixed'):
                self.metadata_fixed = {}
            self.metadata_fixed['caller'] = CallerTypes.SERVER

            # Add study_uid and other required fields to metadata_fixed
            study_uid = Path(folder_path).name
            self.metadata_fixed['study_uid'] = study_uid
            self.metadata_fixed['study_date'] = 'N/A'  # Default value
            self.metadata_fixed['study_time'] = 'N/A'  # Default value
            self.metadata_fixed['patient_name'] = getattr(self, 'patient_name', 'N/A')
            self.metadata_fixed['patient_id'] = getattr(self, 'patient_id', 'N/A')
            self.metadata_fixed['patient_sex'] = 'N/A'  # Default value
            self.metadata_fixed['patient_age'] = 'N/A'  # Default value

            # Clear existing data to force fresh load
            self.lst_thumbnails_data = []
            self.lst_nodes_viewer = []
            self.selected_widget = None
            self.lst_series_name = set()
            self._series_index = {}
            self.unique_elements_index = 0

            # Use synchronous loading instead of async pipeline to avoid crashes
            print(f"🚀 Starting synchronous loading with folder path")
            self.load_thumbnails_sync()

        except Exception as e:
            print(f"❌ Error updating folder path: {str(e)}")
            import traceback
            traceback.print_exc()

    def load_study_from_folder(self, folder_path):
        """Load study from a specific folder path"""
        try:

            # Clear existing data
            self.lst_thumbnails_data = []
            self.lst_nodes_viewer = []
            self.selected_widget = None
            self.lst_series_name = set()
            self.metadata_fixed = {'caller': CallerTypes.SERVER}
            self._series_index = {}
            self.unique_elements_index = 0

            # Update folder path (this will trigger the pipeline)
            self.update_folder_path(folder_path)


        except Exception as e:
            print(f"Error loading study from folder: {str(e)}")
            import traceback
            traceback.print_exc()

    def show_loading_indicator(self, message="Loading..."):
        """Show loading indicator in the widget"""
        try:
            self._loading_message = message

        except Exception as e:
            print(f"Error showing loading indicator: {str(e)}")

    def hide_loading_indicator(self):
        """Hide loading indicator"""
        try:
            print("Loading completed")
            if hasattr(self, '_loading_message'):
                del self._loading_message

        except Exception as e:
            print(f"Error hiding loading indicator: {str(e)}")

    def refresh_ui_after_download(self):
        """Refresh UI after download completion to show new data"""
        try:
            print("🔄 Refreshing UI after download...")

            # Clear existing data to force reload
            self.lst_thumbnails_data = []
            self.lst_nodes_viewer = []
            self.selected_widget = None
            self.lst_series_name = set()
            self._series_index = {}
            self.unique_elements_index = 0

            # Clear thumbnail layout
            if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                # Clear thumbnails manually since clear_all_thumbnails method was removed
                for btn in self.thumbnail_manager.buttons:
                    if btn.parentWidget():
                        btn.parentWidget().setParent(None)
                        btn.parentWidget().deleteLater()
                self.thumbnail_manager.buttons.clear()
                self.thumbnail_manager.lst_buttons_name.clear()

            # Clear viewer layout
            if hasattr(self, 'sidebar') and hasattr(self.sidebar, 'layout'):
                # Clear existing viewers
                for i in reversed(range(self.sidebar.layout().count())):
                    child = self.sidebar.layout().itemAt(i).widget()
                    if child:
                        child.setParent(None)
                        child.deleteLater()

            # Force pipeline manager to restart with fresh data
            if self.import_folder_path:
                print("🚀 Restarting pipeline manager with fresh data...")
                self.pipeline_manager(caller=CallerTypes.SERVER, size_init_viewers=(1, 1))

            print("✅ UI refresh completed")

        except Exception as e:
            print(f"❌ Error refreshing UI after download: {str(e)}")
            import traceback
            traceback.print_exc()

    async def _process_remaining_series_background(self, series_generator):
        """Process remaining series in background after first series is displayed"""
        try:

            # Process remaining series one by one in background
            series_count = 0
            async for result in self._async_generator_wrapper(series_generator):
                if result:
                    vtk_image_data, metadata, patient_info = result
                    series_count += 1

                    # Process this series in the main thread
                    await self._process_single_series_result(vtk_image_data, metadata, patient_info)

                    # Apply reset to current viewer if this series was loaded to it
                    if (self.selected_widget and
                        hasattr(self.selected_widget, 'last_series_show') and
                        self.selected_widget.last_series_show == len(self.lst_thumbnails_data) - 1):

                        # Find the node viewer for the selected widget
                        for node in self.lst_nodes_viewer:
                            if node.vtk_widget == self.selected_widget:
                                self._apply_reset_to_viewer(node)
                                break

                    # Small delay to not overwhelm the UI
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"❌ Error in background series processing: {e}")

    async def _async_generator_wrapper(self, generator):
        """Wrapper to make synchronous generator async"""
        try:
            while True:
                try:
                    result = await asyncio.to_thread(lambda: next(generator))
                    yield result
                except StopIteration:
                    break
        except Exception as e:
            print(f"❌ Error in async generator wrapper: {e}")

    async def _process_single_series_result(self, vtk_image_data, metadata, patient_info):
        """Process a single series result (extracted from main loop)"""
        try:
            self.check_and_add_meta_fixed(patient_info)

            series_key = metadata['series']['series_name']
            grown = None

            if (series_key, metadata['instances'][-1]['is_rgb']) in self._series_index:
                idx = self._series_index[(series_key, metadata['instances'][-1]['is_rgb'])]

                # Safety check for selected_widget and image_viewer
                if (self.selected_widget and
                    hasattr(self.selected_widget, 'image_viewer') and
                    self.selected_widget.image_viewer and
                    hasattr(self.selected_widget.image_viewer, 'metadata')):

                    flag_same_color_channel = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                    if flag_same_color_channel and (metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series']['series_number']):
                        grown = self.selected_widget.grow_current_series_inplace(vtk_image_data, metadata)

                else:
                    flag_same_color_channel = self.check_metadata_belong_together(self.lst_thumbnails_data[idx]['metadata'], metadata)
                    if flag_same_color_channel:
                        old_vtk = self.lst_thumbnails_data[idx]['vtk_image_data']
                        grown = grow_vtk_inplace(old_vtk, vtk_image_data)

                if flag_same_color_channel:
                    if grown:
                        self.lst_thumbnails_data[idx]['metadata'] = metadata
                    return  # Early return for grown series

            # Add new series - use fast thumbnail generation for first series
            from PacsClient.pacs.patient_tab.utils.utils import save_image_as_png_fast_first

            # Check if this is likely the first series (simple heuristic)
            is_first_series = len(self.lst_thumbnails_data) == 0

            if is_first_series:
                file_path = save_image_as_png_fast_first(
                    vtk_image_data=vtk_image_data, metadata=metadata,
                    metadata_fixed=self.metadata_fixed,
                    file=metadata['series']['series_path']
                )
            else:
                file_path = save_image_as_png(
                    vtk_image_data=vtk_image_data, metadata=metadata,
                    metadata_fixed=self.metadata_fixed,
                    file=metadata['series']['series_path']
                )

            # Add thumbnail in main thread
            thumb_index = len(self.lst_thumbnails_data)  # Simple index calculation
            self.add_thumbnail_to_thumbnail_layout(
                thumb_index=thumb_index, file_path_thumbnail=file_path, metadata=metadata)

            new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
            self.add_new_data_to_lst_thumbnails_data(new_data)

            self._series_index[(series_key, metadata['instances'][-1]['is_rgb'])] = len(self.lst_thumbnails_data) - 1

        except Exception as e:
            print(f"Error processing single series result: {e}")

    def _apply_reset_to_viewer(self, node_viewer):
        """Apply reset to viewer like toolbar reset button - exact same logic"""
        try:
            if not node_viewer or not node_viewer.vtk_widget:
                return

            selected_widget = node_viewer.vtk_widget

            # Get the current series data
            series_index = selected_widget.last_series_show
            if series_index is None or series_index >= len(self.lst_thumbnails_data):
                return

            vtk_image_data = self.lst_thumbnails_data[series_index]['vtk_image_data']
            metadata = self.lst_thumbnails_data[series_index]['metadata']


            # Exact same logic as toolbar reset (toggle_reset_selected_widget)

            # 1. Reset the image (like toolbar reset)
            selected_widget.reset_image(vtk_image_data, metadata)

            # 2. Create an eraser instance for delete widgets from image viewer (like toolbar)
            from PacsClient.pacs.patient_tab.interactor_styles import EraserInteractorStyle
            selected_widget.set_new_interactorstyle(EraserInteractorStyle)
            selected_widget.current_style.delete_all_widgets()

            # 3. Restore default interactor style (like toolbar reset)
            selected_widget.restore_default_interactorstyle()


        except Exception as e:
            print(f"Error applying reset to viewer: {e}")
            import traceback
            traceback.print_exc()

    def _apply_reset_to_all_viewers(self):
        """Apply reset to all viewers like toolbar reset all"""
        try:

            for node in self.lst_nodes_viewer:
                self._apply_reset_to_viewer(node)


        except Exception as e:
            print(f"Error applying reset to all viewers: {e}")

    # ==================== PRIORITY THUMBNAIL DISPLAY METHODS ====================
    # These methods support immediate thumbnail display before DICOM download

    def set_patient_info(self, patient_id, patient_name, study_uid):
        """Set patient information for thumbnail fetching"""
        self.patient_id = patient_id
        self.patient_name = patient_name
        self.study_uid = study_uid

    def display_thumbnails_immediately(self, thumbnails_data):
        """
        Display thumbnails immediately from server response - one by one with loading
        اولین اولویت: نمایش فوری تامب‌نیل‌ها تک تک با loading
        """
        try:

            # Clear existing thumbnails
            self.clear_thumbnails()

            # Show loading state (if available)
            if hasattr(self, 'show_thumbnail_loading'):
                self.show_thumbnail_loading(len(thumbnails_data))

            # Start progressive display with minimal delay for better UX
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, lambda: self.display_thumbnails_progressively(thumbnails_data))

        except Exception as e:
            print(f"Error in display_thumbnails_immediately: {str(e)}")

    def display_thumbnails_progressively(self, thumbnails_data):
        """Display thumbnails one by one with a small delay for better UX"""
        try:
            from PySide6.QtCore import QTimer

            # توقف timer قبلی اگر وجود دارد
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()

            self.current_thumbnail_index = 0
            self.thumbnails_to_display = thumbnails_data

            # Update thumbnail count if available
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"Loading 0/{len(thumbnails_data)} series...")

            # Create a timer to display thumbnails progressively
            self.thumbnail_timer = QTimer()
            self.thumbnail_timer.timeout.connect(self.display_next_thumbnail_patient)
            self.thumbnail_timer.start(100)  # 100ms delay between each thumbnail to prevent overlapping

        except Exception as e:
            print(f"Error in display_thumbnails_progressively: {str(e)}")

    def display_next_thumbnail_patient(self):
        """Display the next thumbnail in the patient tab queue"""
        try:
            # بررسی وجود timer و داده‌ها
            if not hasattr(self, 'thumbnail_timer') or not self.thumbnail_timer:
                return

            if not hasattr(self, 'thumbnails_to_display') or not self.thumbnails_to_display:
                return

            if self.current_thumbnail_index >= len(self.thumbnails_to_display):
                # All thumbnails displayed, stop the timer
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None

                # Update final count
                if hasattr(self, 'thumb_count_label'):
                    self.thumb_count_label.setText(f"{len(self.thumbnails_to_display)} series")
                return

            thumb_data = self.thumbnails_to_display[self.current_thumbnail_index]

            try:
                file_path = thumb_data.get('file_path')
                if file_path and os.path.exists(file_path):
                    # بررسی اینکه آیا این تامب‌نیل قبلاً اضافه شده یا نه
                    if not self.is_thumbnail_already_added(file_path):
                        # Create standardized metadata for immediate display
                        from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
                        metadata = ThumbnailManager.create_standard_metadata(
                            series_number=thumb_data.get('series_number', f'Series {self.current_thumbnail_index + 1}'),
                            modality=thumb_data.get('modality', 'Unknown'),
                            series_description=thumb_data.get('series_description', ''),
                            image_count=thumb_data.get('image_count', 1),
                            protocol_name=thumb_data.get('protocol_name', ''),
                            body_part_examined=thumb_data.get('body_part_examined', ''),
                            is_downloading=False  # Mark as completed download
                        )

                        # Add thumbnail to layout
                        thumb_index = self.add_thumbnail_to_thumbnail_layout(
                            thumb_index=self.current_thumbnail_index,
                            file_path_thumbnail=file_path,
                            metadata=metadata
                        )

                        print(f"✅ Added thumbnail {self.current_thumbnail_index + 1}/{len(self.thumbnails_to_display)}")

            except Exception as e:
                print(f"Error processing thumbnail {self.current_thumbnail_index}: {str(e)}")

            self.current_thumbnail_index += 1

            # Update progress count
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"{self.current_thumbnail_index}/{len(self.thumbnails_to_display)} series")

        except Exception as e:
            print(f"Error in display_next_thumbnail_patient: {str(e)}")
            # Stop timer on error
            if hasattr(self, 'thumbnail_timer'):
                self.thumbnail_timer.stop()

    def is_thumbnail_already_added(self, file_path):
        """
        بررسی اینکه آیا تامب‌نیل قبلاً اضافه شده یا نه
        """
        try:
            if not hasattr(self, 'thumbnail_manager') or not self.thumbnail_manager:
                return False

            # بررسی در لیست دکمه‌های موجود
            for btn in self.thumbnail_manager.buttons:
                if hasattr(btn, 'file_path') and btn.file_path == file_path:
                    return True
                # بررسی در parent widget
                parent = btn.parentWidget()
                if parent and hasattr(parent, 'file_path') and parent.file_path == file_path:
                    return True

            return False

        except Exception as e:
            print(f"❌ Error checking thumbnail existence: {e}")
            return False

    def cleanup_timers(self):
        """
        پاکسازی همه timerها
        """
        try:
            # توقف و پاک کردن thumbnail timer
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None

            # توقف و پاک کردن cached thumbnail timer
            if hasattr(self, 'cached_thumbnail_timer') and self.cached_thumbnail_timer:
                self.cached_thumbnail_timer.stop()
                self.cached_thumbnail_timer.deleteLater()
                self.cached_thumbnail_timer = None

            print("✅ All timers cleaned up")

        except Exception as e:
            print(f"❌ Error cleaning up timers: {e}")

    def __del__(self):
        """
        Destructor - پاکسازی منابع هنگام حذف widget
        """
        try:
            self.cleanup_timers()
        except:
            pass

    def load_thumbnails_from_cache(self, thumbnail_dir):
        """
        Load thumbnails from cached directory
        بارگذاری تامب‌نیل‌ها از کش
        """
        try:

            from pathlib import Path
            cache_path = Path(thumbnail_dir)

            if not cache_path.exists():
                print(f"Cache directory does not exist: {thumbnail_dir}")
                return

            # Find all image files in cache
            image_files = []
            for ext in ['.png', '.jpg', '.jpeg']:
                image_files.extend(cache_path.glob(f'*{ext}'))

            if not image_files:
                print(f"No thumbnail images found in cache: {thumbnail_dir}")
                return

            # Clear existing thumbnails
            self.clear_thumbnails()

            # Sort files by name for consistent ordering
            image_files.sort(key=lambda x: x.name)

            # Prepare cached thumbnails data for progressive display with database metadata
            cached_thumbnails_data = []
            for image_file in image_files:
                # Extract series info from filename if possible
                series_name = image_file.stem

                # Try to get metadata from database
                series_metadata = self.get_cached_series_metadata(series_name)

                cached_thumbnails_data.append({
                    'file_path': str(image_file),
                    'series_number': series_metadata.get('series_number', series_name),
                    'modality': series_metadata.get('modality', 'Unknown'),
                    'series_description': series_metadata.get('series_description', f'Series {series_name}'),
                    'image_count': series_metadata.get('image_count', 0),
                    'protocol_name': series_metadata.get('protocol_name', ''),
                    'body_part_examined': series_metadata.get('body_part_examined', ''),
                    'is_cached': True
                })

            # Display cached thumbnails progressively
            self.display_cached_thumbnails_progressively(cached_thumbnails_data)

        except Exception as e:
            print(f"Error in load_thumbnails_from_cache: {str(e)}")

    def get_cached_series_metadata(self, series_number):
        """Get series metadata from database for cached thumbnails"""
        try:
            # Get study_uid from patient widget or extract from import_folder_path
            study_uid = None

            # First try to get from self.study_uid
            if hasattr(self, 'study_uid') and self.study_uid:
                study_uid = self.study_uid
                print(f"🔍 DEBUG: Using self.study_uid = {study_uid}")
            # If not available, extract from import_folder_path
            elif hasattr(self, 'import_folder_path') and self.import_folder_path:
                from pathlib import Path
                study_uid = Path(self.import_folder_path).name
                print(f"🔍 DEBUG: Extracted study_uid from path = {study_uid}")

            if not study_uid:
                print(f"🔍 DEBUG: No study_uid available, returning empty dict")
                return {}

            # Import database functions
            from PacsClient.utils.db_manager import get_series_by_study_and_number

            # Get series metadata from database
            print(f"🔍 DEBUG: Querying database for study_uid={study_uid}, series_number={series_number}")
            series_data = get_series_by_study_and_number(study_uid, series_number)
            print(f"🔍 DEBUG: Database returned: {series_data}")

            if series_data:
                return {
                    'series_number': series_data.get('series_number', series_number),
                    'modality': series_data.get('modality', 'Unknown'),
                    'series_description': series_data.get('series_description', ''),
                    'image_count': series_data.get('image_count', 0),
                    'protocol_name': series_data.get('protocol_name', ''),
                    'body_part_examined': series_data.get('body_part_examined', ''),
                    'manufacturer': series_data.get('manufacturer', ''),
                    'institution_name': series_data.get('institution_name', '')
                }
            else:
                # Fallback if no database data found
                return {
                    'series_number': series_number,
                    'modality': 'Unknown',
                    'series_description': f'Series {series_number}',
                    'image_count': 0
                }

        except Exception as e:
            print(f"Error getting cached series metadata: {str(e)}")
            # Return fallback metadata
            return {
                'series_number': series_number,
                'modality': 'Unknown',
                'series_description': f'Series {series_number}',
                'image_count': 0
            }

    def display_cached_thumbnails_progressively(self, cached_thumbnails_data):
        """Display cached thumbnails one by one with a small delay for better UX"""
        try:
            from PySide6.QtCore import QTimer


            self.current_cached_index = 0
            self.cached_thumbnails_to_display = cached_thumbnails_data

            # Update thumbnail count if available
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"Loading 0/{len(cached_thumbnails_data)} cached series...")

            # Create a timer to display cached thumbnails progressively
            self.cached_thumbnail_timer = QTimer()
            self.cached_thumbnail_timer.timeout.connect(self.display_next_cached_thumbnail)
            self.cached_thumbnail_timer.start(80)  # 80ms delay between each cached thumbnail to prevent overlapping

        except Exception as e:
            print(f"Error in display_cached_thumbnails_progressively: {str(e)}")

    def display_next_cached_thumbnail(self):
        """Display the next cached thumbnail in the queue"""
        try:
            if self.current_cached_index >= len(self.cached_thumbnails_to_display):
                # All cached thumbnails displayed, stop the timer
                self.cached_thumbnail_timer.stop()
                # Update final count
                if hasattr(self, 'thumb_count_label'):
                    self.thumb_count_label.setText(f"{len(self.cached_thumbnails_to_display)} cached series")
                return

            thumb_data = self.cached_thumbnails_to_display[self.current_cached_index]

            try:
                file_path = thumb_data.get('file_path')
                if file_path and os.path.exists(file_path):
                    # Create standardized metadata for cached images
                    from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
                    metadata = ThumbnailManager.create_standard_metadata(
                        series_number=thumb_data.get('series_number', f'Series {self.current_cached_index + 1}'),
                        modality=thumb_data.get('modality', 'Cached'),
                        series_description=thumb_data.get('series_description', ''),
                        image_count=thumb_data.get('image_count', 1),
                        is_downloading=False  # Mark as existing/cached - no progress
                    )

                    # Add to layout
                    thumb_index = self.add_thumbnail_to_thumbnail_layout(
                        thumb_index=self.current_cached_index,
                        file_path_thumbnail=file_path,
                        metadata=metadata
                    )

                    # Force layout update to prevent overlapping
                    if hasattr(self, 'thumb_grid') and self.thumb_grid:
                        self.thumb_grid.update()


            except Exception as e:
                print(f"Error processing cached thumbnail {self.current_cached_index}: {str(e)}")

            self.current_cached_index += 1

            # Update progress count
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"{self.current_cached_index}/{len(self.cached_thumbnails_to_display)} cached series")

        except Exception as e:
            print(f"Error in display_next_cached_thumbnail: {str(e)}")
            # Stop timer on error
            if hasattr(self, 'cached_thumbnail_timer'):
                self.cached_thumbnail_timer.stop()

    def clear_thumbnails(self):
        """Clear existing thumbnails from the layout"""
        try:
            # توقف timerها
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None

            if hasattr(self, 'cached_thumbnail_timer') and self.cached_thumbnail_timer:
                self.cached_thumbnail_timer.stop()
                self.cached_thumbnail_timer.deleteLater()
                self.cached_thumbnail_timer = None

            # پاک کردن grid layout
            if hasattr(self, 'thumb_grid') and self.thumb_grid:
                # Clear grid layout
                for i in reversed(range(self.thumb_grid.count())):
                    child = self.thumb_grid.itemAt(i)
                    if child and child.widget():
                        widget = child.widget()
                        widget.setParent(None)
                        widget.deleteLater()

                # Clear thumbnail manager
                if hasattr(self, 'thumbnail_manager'):
                    # پاک کردن دکمه‌ها
                    for btn in self.thumbnail_manager.buttons[:]:
                        if btn.parent():
                            btn.setParent(None)
                            btn.deleteLater()
                    self.thumbnail_manager.buttons.clear()
                    self.thumbnail_manager.lst_buttons_name.clear()

                print("✅ Thumbnails cleared successfully")

        except Exception as e:
            print(f"⚠️ Error clearing thumbnails: {e}")

    def show_loading_indicator(self, message="Loading..."):
        """Show loading indicator with message"""
        try:
            # Update header status if available
            if hasattr(self, 'status_label'):
                self.status_label.setText(message)
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #f59e0b;
                        font-size: 12px;
                        padding: 2px 6px;
                        background: rgba(245, 158, 11, 0.1);
                        border: 1px solid rgba(245, 158, 11, 0.3);
                        border-radius: 4px;
                    }
                """)

            print(f"⏳ Loading: {message}")

        except Exception as e:
            print(f"Error showing loading indicator: {e}")

    def hide_loading_indicator(self):
        """Hide loading indicator"""
        try:
            # Clear status if available
            if hasattr(self, 'status_label'):
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #10b981;
                        font-size: 12px;
                        padding: 2px 6px;
                        background: rgba(16, 185, 129, 0.1);
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        border-radius: 4px;
                    }
                """)

            print("✅ Loading complete")

        except Exception as e:
            print(f"Error hiding loading indicator: {e}")

    async def start_auto_thumbnail_download(self):
        """
        شروع دانلود خودکار تامب‌نیل‌ها از سرور با مدیریت خطا و fallback
        """
        try:
            print("🚀 Starting auto thumbnail download...")

            # نمایش پیام بارگذاری
            if hasattr(self, 'show_loading_indicator'):
                self.show_loading_indicator("Downloading thumbnails...")

            # نمایش پیشرفت دانلود
            if hasattr(self, 'thumbnail_manager'):
                self.thumbnail_manager.show_auto_download_progress("", 0)

            # دریافت اطلاعات سرور
            server = self.get_server_configuration()
            if not server:
                print("❌ No server configuration available for auto-download")
                await self.handle_download_failure("No server configuration")
                return

            # دریافت study_uid
            study_uid = self.get_study_uid()
            if not study_uid:
                await self.handle_download_failure("No study UID")
                return

            # دریافت patient_id
            patient_id = getattr(self, 'patient_id', None) or study_uid.split('.')[-1]

            print(f"📡 Connecting to server: {server['host']}:{server.get('port', 50051)}")
            print(f"📋 Study UID: {study_uid}")
            print(f"👤 Patient ID: {patient_id}")

            # تلاش برای اتصال به سرور
            grpc_client = None
            try:
                from PacsClient.components.grpc_client import DicomGrpcClient
                grpc_client = DicomGrpcClient(host=server['host'], port=server.get('port', 50051))

                # تست اتصال
                if not grpc_client._connect():
                    raise Exception("Failed to connect to gRPC server")

                print("✅ Connected to server successfully")

                # دریافت تامب‌نیل‌ها از سرور
                thumbnails_data = grpc_client.get_thumbnails(patient_id, study_uid)

                if thumbnails_data and 'thumbnails' in thumbnails_data:
                    total_series = len(thumbnails_data['thumbnails'])
                    print(f"✅ Received {total_series} thumbnails from server")

                    # به‌روزرسانی پیشرفت
                    if hasattr(self, 'thumbnail_manager'):
                        self.thumbnail_manager.update_auto_download_progress(0, total_series, "Processing thumbnails...")

                    # ذخیره تامب‌نیل‌ها محلی
                    saved_thumbnails = self.save_thumbnails_locally(thumbnails_data, study_uid)

                    if saved_thumbnails:
                        # ذخیره اطلاعات سری در دیتابیس
                        self.save_series_info_to_database(study_uid, thumbnails_data['thumbnails'])

                        # پاک کردن کش برای اطمینان از داده‌های تازه
                        from PacsClient.pacs.patient_tab.utils.utils import clear_study_cache
                        clear_study_cache(study_uid)

                        # نمایش فوری تامب‌نیل‌ها
                        await self.display_downloaded_thumbnails(saved_thumbnails)

                        # تکمیل پیشرفت
                        if hasattr(self, 'thumbnail_manager'):
                            self.thumbnail_manager.update_auto_download_progress(total_series, total_series, "✅ Complete")

                        print("✅ Auto thumbnail download completed successfully")
                    else:
                        print("❌ Failed to save thumbnails locally")
                        await self.handle_download_failure("Failed to save thumbnails")
                else:
                    print("⚠️ No thumbnail data received from server")
                    await self.handle_download_failure("No thumbnail data from server")

            except Exception as grpc_error:
                print(f"❌ gRPC error: {str(grpc_error)}")
                await self.handle_download_failure(f"Server error: {str(grpc_error)}")

            finally:
                if grpc_client:
                    try:
                        grpc_client.close()
                    except:
                        pass

        except Exception as e:
            print(f"❌ Error in auto thumbnail download: {str(e)}")
            await self.handle_download_failure(f"Unexpected error: {str(e)}")
            import traceback
            traceback.print_exc()

    async def handle_download_failure(self, error_message):
        """
        مدیریت خطاهای دانلود و نمایش پیام مناسب
        """
        try:
            print(f"⚠️ Handling download failure: {error_message}")

            # مخفی کردن پیشرفت دانلود
            if hasattr(self, 'thumbnail_manager'):
                self.thumbnail_manager.hide_auto_download_widget()

            # نمایش پیام خطا
            if hasattr(self, 'show_loading_indicator'):
                self.show_loading_indicator(f"Download failed: {error_message}")

            # ایجاد ویجت خطا
            self.create_error_widget(error_message)

            # تلاش برای fallback
            await self.try_fallback_download()

        except Exception as e:
            print(f"❌ Error in handle_download_failure: {e}")

    def create_error_widget(self, error_message):
        """
        ایجاد ویجت نمایش خطا
        """
        try:
            from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
            from PySide6.QtCore import Qt

            # ایجاد ویجت خطا
            error_widget = QWidget()
            error_widget.setFixedSize(180, 100)
            error_widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 2px solid #ef4444;
                    border-radius: 8px;
                    margin: 2px;
                }
            """)

            # ایجاد layout
            layout = QVBoxLayout(error_widget)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(4)

            # عنوان خطا
            error_title = QLabel("Download Failed")
            error_title.setAlignment(Qt.AlignCenter)
            error_title.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    font-weight: bold;
                    color: #ef4444;
                    background: transparent;
                    border: none;
                }
            """)
            layout.addWidget(error_title)

            # پیام خطا
            error_label = QLabel(error_message[:50] + "..." if len(error_message) > 50 else error_message)
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setWordWrap(True)
            error_label.setStyleSheet("""
                QLabel {
                    font-size: 9px;
                    color: #cbd5e0;
                    background: transparent;
                    border: none;
                }
            """)
            layout.addWidget(error_label)

            # دکمه تلاش مجدد
            retry_button = QPushButton("Retry")
            retry_button.setFixedHeight(20)
            retry_button.setStyleSheet("""
                QPushButton {
                    background: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #dc2626;
                }
            """)
            retry_button.clicked.connect(lambda: self.retry_download())
            layout.addWidget(retry_button)

            # اضافه کردن به layout تامب‌نیل‌ها
            if hasattr(self, 'thumb_panel') and hasattr(self.thumb_panel, 'layout'):
                self.thumb_panel.layout().addWidget(error_widget)

            print("✅ Error widget created")

        except Exception as e:
            print(f"❌ Error creating error widget: {e}")

    async def try_fallback_download(self):
        """
        تلاش برای دانلود fallback
        """
        try:
            print("🔄 Trying fallback download...")

            # بررسی وجود فایل‌های DICOM محلی
            if self.import_folder_path and os.path.exists(self.import_folder_path):
                files = os.listdir(self.import_folder_path)
                if files:
                    print("📁 Found local DICOM files, attempting to generate thumbnails...")
                    await self.generate_thumbnails_from_local_files()
                    return

            # تلاش برای دانلود از سرور جایگزین
            await self.try_alternative_server()

        except Exception as e:
            print(f"❌ Error in fallback download: {e}")

    async def generate_thumbnails_from_local_files(self):
        """
        تولید تامب‌نیل‌ها از فایل‌های محلی
        """
        try:
            print("🖼️ Generating thumbnails from local files...")

            # این بخش نیاز به پیاده‌سازی دارد
            # می‌تواند از image_io.py استفاده کند
            print("⚠️ Local thumbnail generation not implemented yet")

        except Exception as e:
            print(f"❌ Error generating thumbnails from local files: {e}")

    async def try_alternative_server(self):
        """
        تلاش برای اتصال به سرور جایگزین
        """
        try:
            print("🔄 Trying alternative server...")

            # این بخش نیاز به پیاده‌سازی دارد
            # می‌تواند لیست سرورهای جایگزین را بررسی کند
            print("⚠️ Alternative server fallback not implemented yet")

        except Exception as e:
            print(f"❌ Error trying alternative server: {e}")

    def retry_download(self):
        """
        تلاش مجدد برای دانلود
        """
        try:
            print("🔄 Retrying download...")

            # پاک کردن ویجت خطا
            self.clear_error_widgets()

            # شروع مجدد دانلود
            import asyncio
            asyncio.create_task(self.start_auto_thumbnail_download())

        except Exception as e:
            print(f"❌ Error in retry download: {e}")

    def clear_error_widgets(self):
        """
        پاک کردن ویجت‌های خطا
        """
        try:
            if hasattr(self, 'thumb_panel') and hasattr(self.thumb_panel, 'layout'):
                layout = self.thumb_panel.layout()
                for i in reversed(range(layout.count())):
                    widget = layout.itemAt(i).widget()
                    if widget and hasattr(widget, 'styleSheet') and 'border: 2px solid #ef4444' in widget.styleSheet():
                        widget.deleteLater()

            print("✅ Error widgets cleared")

        except Exception as e:
            print(f"❌ Error clearing error widgets: {e}")

    def get_server_configuration(self):
        """
        دریافت تنظیمات سرور از parent widget
        """
        try:
            # تلاش برای دریافت از parent widget
            if hasattr(self, 'parent') and self.parent:
                if hasattr(self.parent, 'data_access_panel_widget'):
                    return self.parent.data_access_panel_widget.get_server_selected()
                elif hasattr(self.parent, 'get_server_selected'):
                    return self.parent.get_server_selected()

            # تلاش برای دریافت از tab manager
            if hasattr(self, 'tab_manager') and self.tab_manager:
                if hasattr(self.tab_manager, 'parent') and self.tab_manager.parent:
                    if hasattr(self.tab_manager.parent, 'data_access_panel_widget'):
                        return self.tab_manager.parent.data_access_panel_widget.get_server_selected()

            return None
        except Exception as e:
            print(f"❌ Error getting server configuration: {e}")
            return None

    def get_study_uid(self):
        """
        دریافت study_uid از مسیر یا متغیرهای موجود
        """
        try:
            # از import_folder_path
            if self.import_folder_path:
                from pathlib import Path
                return Path(self.import_folder_path).name

            # از متغیرهای موجود
            if hasattr(self, 'study_uid') and self.study_uid:
                return self.study_uid

            return None
        except Exception as e:
            print(f"❌ Error getting study_uid: {e}")
            return None

    def save_thumbnails_locally(self, thumbnails_data, study_uid):
        """
        ذخیره تامب‌نیل‌ها در سیستم محلی
        """
        try:
            from PacsClient.pacs.patient_tab.utils.utils import save_thumbnail_with_bytes, THUMBNAIL_PATH

            saved_thumbnails = []
            thumbnails_dir = THUMBNAIL_PATH / study_uid
            thumbnails_dir.mkdir(parents=True, exist_ok=True)

            for thumbnail_info in thumbnails_data.get('thumbnails', []):
                try:
                    # دریافت داده‌های تامب‌نیل
                    thumbnail_bytes = thumbnail_info.get('thumbnail_bytes')
                    series_number = thumbnail_info.get('series_number', 'unknown')

                    if thumbnail_bytes:
                        # ذخیره فایل تامب‌نیل
                        file_path = save_thumbnail_with_bytes(study_uid, series_number, thumbnail_bytes)
                        if file_path:
                            saved_thumbnails.append({
                                'file_path': file_path,
                                'series_number': series_number,
                                'modality': thumbnail_info.get('modality', 'Unknown'),
                                'series_description': thumbnail_info.get('series_description', ''),
                                'image_count': thumbnail_info.get('image_count', 0),
                                'protocol_name': thumbnail_info.get('protocol_name', ''),
                                'body_part_examined': thumbnail_info.get('body_part_examined', '')
                            })
                            print(f"✅ Saved thumbnail for series {series_number}")
                        else:
                            print(f"❌ Failed to save thumbnail for series {series_number}")
                    else:
                        print(f"⚠️ No thumbnail bytes for series {series_number}")

                except Exception as e:
                    print(f"❌ Error saving thumbnail for series {series_number}: {e}")
                    continue

            print(f"✅ Successfully saved {len(saved_thumbnails)} thumbnails")
            return saved_thumbnails

        except Exception as e:
            print(f"❌ Error in save_thumbnails_locally: {e}")
            return []

    def save_series_info_to_database(self, study_uid, series_thumbnails):
        """
        ذخیره اطلاعات سری در دیتابیس
        """
        try:
            from PacsClient.utils.db_manager import insert_series

            for series_info in series_thumbnails:
                try:
                    # ذخیره اطلاعات سری در دیتابیس
                    series_data = {
                        'study_uid': study_uid,
                        'series_number': series_info.get('series_number'),
                        'modality': series_info.get('modality', 'Unknown'),
                        'series_description': series_info.get('series_description', ''),
                        'image_count': series_info.get('image_count', 0),
                        'protocol_name': series_info.get('protocol_name', ''),
                        'body_part_examined': series_info.get('body_part_examined', '')
                    }

                    insert_series(**series_data)
                    print(f"✅ Saved series info for {series_data['series_number']}")

                except Exception as e:
                    print(f"❌ Error saving series info: {e}")
                    continue

        except Exception as e:
            print(f"❌ Error in save_series_info_to_database: {e}")

    async def display_downloaded_thumbnails(self, thumbnails_data):
        """
        نمایش تامب‌نیل‌های دانلود شده
        """
        try:
            print(f"🖼️ Displaying {len(thumbnails_data)} downloaded thumbnails...")

            # توقف timer قبلی اگر وجود دارد
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None

            # پاک کردن تامب‌نیل‌های موجود
            self.clear_thumbnails()

            # نمایش تامب‌نیل‌ها به صورت پیشرونده
            if hasattr(self, 'display_thumbnails_progressively'):
                self.display_thumbnails_progressively(thumbnails_data)
            else:
                # نمایش مستقیم
                for i, thumb_data in enumerate(thumbnails_data):
                    try:
                        file_path = thumb_data.get('file_path')
                        if file_path and os.path.exists(file_path):
                            # بررسی تکراری نبودن
                            if not self.is_thumbnail_already_added(file_path):
                                self.add_thumbnail_to_thumbnail_layout(
                                    thumb_index=i,
                                    file_path_thumbnail=file_path
                                )
                    except Exception as e:
                        print(f"❌ Error displaying thumbnail {i}: {e}")
                        continue

            print("✅ Downloaded thumbnails displayed successfully")

        except Exception as e:
            print(f"❌ Error in display_downloaded_thumbnails: {e}")

    def optimize_memory_usage(self):
        """
        بهینه‌سازی استفاده از حافظه
        """
        try:
            import gc

            print("🧹 Optimizing memory usage...")

            # پاکسازی کش‌های قدیمی
            from PacsClient.pacs.patient_tab.utils.utils import cleanup_old_cache_entries, get_cache_stats
            cleanup_old_cache_entries()

            # نمایش آمار کش
            cache_stats = get_cache_stats()
            print(f"📊 Cache stats: {cache_stats['valid_entries']}/{cache_stats['total_entries']} valid entries, {cache_stats['cache_size_mb']:.2f} MB")

            # پاکسازی حافظه Python
            gc.collect()

            # بهینه‌سازی ویجت‌های UI
            self.optimize_ui_widgets()

            print("✅ Memory optimization completed")

        except Exception as e:
            print(f"❌ Error in memory optimization: {e}")

    def optimize_ui_widgets(self):
        """
        بهینه‌سازی ویجت‌های UI
        """
        try:
            # پاکسازی ویجت‌های غیرضروری
            if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                # پاکسازی دکمه‌های قدیمی
                old_buttons = []
                for btn in self.thumbnail_manager.buttons:
                    if not btn.isVisible() or btn.parent() is None:
                        old_buttons.append(btn)

                for btn in old_buttons:
                    self.thumbnail_manager.buttons.remove(btn)
                    if hasattr(btn, 'deleteLater'):
                        btn.deleteLater()

                print(f"🗑️ Cleaned up {len(old_buttons)} old thumbnail buttons")

            # بهینه‌سازی layout
            if hasattr(self, 'thumb_panel') and hasattr(self.thumb_panel, 'layout'):
                layout = self.thumb_panel.layout()
                if layout:
                    # حذف spacing اضافی
                    layout.setSpacing(2)
                    layout.setContentsMargins(4, 4, 4, 4)

        except Exception as e:
            print(f"❌ Error optimizing UI widgets: {e}")

    def get_memory_usage_stats(self):
        """
        دریافت آمار استفاده از حافظه
        """
        try:
            import psutil
            import os

            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()

            # آمار کش
            from PacsClient.pacs.patient_tab.utils.utils import get_cache_stats
            cache_stats = get_cache_stats()

            return {
                'process_memory_mb': memory_info.rss / (1024 * 1024),
                'process_memory_percent': process.memory_percent(),
                'cache_entries': cache_stats['total_entries'],
                'cache_size_mb': cache_stats['cache_size_mb'],
                'thumbnail_buttons': len(self.thumbnail_manager.buttons) if hasattr(self, 'thumbnail_manager') else 0,
                'thumbnails_data': len(self.lst_thumbnails_data) if hasattr(self, 'lst_thumbnails_data') else 0
            }

        except Exception as e:
            print(f"❌ Error getting memory stats: {e}")
            return {}

    def log_memory_usage(self):
        """
        ثبت آمار استفاده از حافظه
        """
        try:
            stats = self.get_memory_usage_stats()
            if stats:
                print(f"📊 Memory Usage Stats:")
                print(f"   - Process Memory: {stats.get('process_memory_mb', 0):.2f} MB ({stats.get('process_memory_percent', 0):.1f}%)")
                print(f"   - Cache Entries: {stats.get('cache_entries', 0)}")
                print(f"   - Cache Size: {stats.get('cache_size_mb', 0):.2f} MB")
                print(f"   - Thumbnail Buttons: {stats.get('thumbnail_buttons', 0)}")
                print(f"   - Thumbnails Data: {stats.get('thumbnails_data', 0)}")
        except Exception as e:
            print(f"❌ Error logging memory usage: {e}")

    def initialize_viewer_components(self):
        """Initialize all viewer components properly"""
        try:
            print("🔧 Initializing viewer components...")

            # Initialize lst_nodes_viewer if not exists
            if not hasattr(self, 'lst_nodes_viewer'):
                self.lst_nodes_viewer = []

            # Initialize vtk_layout if not exists
            if not hasattr(self, 'vtk_layout'):
                # Create a simple grid layout for viewers
                from PySide6.QtWidgets import QGridLayout
                self.vtk_layout = QGridLayout()
                # Add to sidebar if it has a layout
                if hasattr(self, 'sidebar') and hasattr(self.sidebar, 'layout'):
                    # Add the vtk_layout to sidebar
                    pass

            # Initialize metadata_fixed if not exists
            if not hasattr(self, 'metadata_fixed'):
                self.metadata_fixed = {'caller': CallerTypes.SERVER}

            print("✅ Viewer components initialized")

        except Exception as e:
            print(f"❌ Error initializing viewer components: {e}")
            import traceback
            traceback.print_exc()

    def load_first_series_only(self, folder_path, series_number):
        """Load only the first series without clearing existing data"""
        try:
            print(f"🎯 First series {series_number} completed! Loading into viewer...")

            # Set the folder path
            self.import_folder_path = folder_path

            # Initialize metadata_fixed
            if not hasattr(self, 'metadata_fixed'):
                self.metadata_fixed = {}
            self.metadata_fixed['caller'] = CallerTypes.SERVER

            study_uid = Path(folder_path).name
            self.metadata_fixed['study_uid'] = study_uid
            self.metadata_fixed['study_date'] = 'N/A'
            self.metadata_fixed['study_time'] = 'N/A'
            self.metadata_fixed['patient_name'] = getattr(self, 'patient_name', 'N/A')
            self.metadata_fixed['patient_id'] = getattr(self, 'patient_id', 'N/A')
            self.metadata_fixed['patient_sex'] = 'N/A'
            self.metadata_fixed['patient_age'] = 'N/A'
            self.metadata_fixed['institution_name'] = 'N/A'

            # Simple approach: just trigger the existing sync loading mechanism
            print("🔄 Using sync loading mechanism...")
            try:
                self.load_thumbnails_sync()
                print("✅ First series loaded using sync mechanism")
            except Exception as sync_error:
                print(f"❌ Error in sync loading: {sync_error}")
                import traceback
                traceback.print_exc()

                # Final fallback to pipeline manager
                print("🔄 Final fallback to pipeline manager...")
                try:
                    self.pipeline_manager(caller=CallerTypes.SERVER, size_init_viewers=(1, 1))
                    print("✅ Final fallback succeeded")
                except Exception as pipeline_error:
                    print(f"❌ All loading methods failed: {pipeline_error}")
                    import traceback
                    traceback.print_exc()

        except Exception as e:
            print(f"❌ Error loading first series: {e}")
            import traceback
            traceback.print_exc()

    def load_first_series_direct(self, folder_path, series_number):
        """Load first series directly without async pipeline"""
        try:
            print(f"🚀 Direct loading of first series {series_number} from {folder_path}")

            # Get the specific series path using the same method as dicom_downloader
            from PacsClient.pacs.patient_tab.utils.utils import check_series_study_exist
            study_uid = Path(folder_path).name
            series_path = check_series_study_exist(study_uid, str(series_number))

            print(f"📁 Series path: {series_path}")

            # Check if series path exists and has DICOM files
            import os
            if not os.path.exists(series_path):
                raise Exception(f"Series path does not exist: {series_path}")

            dcm_files = [f for f in os.listdir(series_path) if f.endswith('.dcm')]
            if not dcm_files:
                raise Exception(f"No DICOM files found in series path: {series_path}")

            print(f"📂 Found {len(dcm_files)} DICOM files in series {series_number}")

            # Load the series using load_images
            from PacsClient.pacs.patient_tab.utils.image_io import load_images
            from PacsClient.pacs.patient_tab.utils import utils

            # Process only the specific series folder
            # Since load_images expects a study folder structure, we need to handle single series differently
            try:
                # First try with load_images (in case it works with single series folder)
                series_results = list(load_images(series_path))
            except Exception as load_error:
                print(f"⚠️ load_images failed: {load_error}, trying direct DICOM loading...")

                # Fallback: Load DICOM files directly
                series_results = self.load_dicom_series_direct(series_path, series_number)

            if not series_results:
                raise Exception(f"No series data loaded from {series_path}")

            # Get the first (and should be only) result
            vtk_image_data, metadata, (patient_pk, study_pk) = series_results[0]
            print(f"✅ Successfully loaded series data: {len(series_results)} series")

            # Add to thumbnails data FIRST (required for init_matrix_viewers)
            series_key = f"series_{series_number}"
            thumbnail_data = {
                'vtk_image_data': vtk_image_data,
                'metadata': metadata,
                'series_key': series_key,
                'patient_pk': patient_pk,
                'study_pk': study_pk,
                'is_first_series': True
            }

            # Clear existing data and add new - MUST be done before init_matrix_viewers
            self.lst_thumbnails_data = [thumbnail_data]
            self._series_index = {(series_key, metadata['instances'][-1]['is_rgb']): 0}
            print(f"✅ Added thumbnail data to lst_thumbnails_data (length: {len(self.lst_thumbnails_data)})")

            # Initialize viewers if not already done
            if not hasattr(self, 'lst_nodes_viewer') or not self.lst_nodes_viewer:
                print("🔧 Initializing viewers for first series...")
                try:
                    self.init_matrix_viewers((1, 1))
                    print(f"✅ Viewers initialized successfully (count: {len(self.lst_nodes_viewer) if hasattr(self, 'lst_nodes_viewer') else 0})")
                except Exception as init_error:
                    print(f"❌ Error initializing viewers: {init_error}")
                    # Try manual viewer creation
                    self.create_manual_viewer_for_first_series(vtk_image_data, metadata)
                    return

            # Create viewer for the first series
            if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                print("🖼️ Creating viewer for first series...")

                # Get the first viewer widget
                vtk_widget = self.lst_nodes_viewer[0]

                # Start processing the series
                vtk_widget.start_process_series(
                    vtk_image_data=vtk_image_data,
                    metadata=metadata,
                    series_index=0,
                    id_vtk_widget=0,
                    metadata_fixed=self.metadata_fixed
                )

                # Set as selected widget
                self.selected_widget = vtk_widget

                print("✅ First series viewer created successfully")
            else:
                raise Exception("No VTK widgets available for display")

        except Exception as e:
            print(f"❌ Error in direct first series loading: {e}")
            import traceback
            traceback.print_exc()
            raise

    def load_dicom_series_direct(self, series_path, series_number):
        """Load DICOM series directly without using load_images pipeline"""
        try:
            print(f"🔧 Direct DICOM loading from {series_path}")

            import os
            from pathlib import Path
            from PacsClient.pacs.patient_tab.utils.image_io import get_itk_image_fast_first
            from PacsClient.pacs.patient_tab.utils import utils
            from natsort import natsorted

            # Get all DICOM files
            dcm_files = [os.path.join(series_path, f) for f in os.listdir(series_path) if f.endswith('.dcm')]
            dcm_files = natsorted(dcm_files)

            if not dcm_files:
                raise Exception(f"No DICOM files found in {series_path}")

            print(f"📂 Processing {len(dcm_files)} DICOM files...")

            # Create ITK image from DICOM files
            itk_image = get_itk_image_fast_first(dcm_files)
            print("✅ ITK image created successfully")

            # Convert ITK to VTK
            vtk_image_data = utils.convert_itk2vtk_fast_first(itk_image)
            if vtk_image_data is None:
                # Fallback to regular conversion
                vtk_image_data = utils.convert_itk2vtk(itk_image)
            print("✅ VTK image data created successfully")

            # Create basic metadata
            import pydicom
            first_dcm = pydicom.dcmread(dcm_files[0], force=True)

            metadata = {
                'series': {
                    'series_number': series_number,
                    'modality': getattr(first_dcm, 'Modality', 'Unknown'),
                    'series_description': getattr(first_dcm, 'SeriesDescription', ''),
                    'protocol_name': getattr(first_dcm, 'ProtocolName', ''),
                    'body_part_examined': getattr(first_dcm, 'BodyPartExamined', ''),
                    'main_thumbnail': True
                },
                'instances': []
            }

            # Add instance metadata
            for i, dcm_file in enumerate(dcm_files):
                try:
                    ds = pydicom.dcmread(dcm_file, force=True, stop_before_pixels=True)
                    instance_meta = {
                        'instance_number': getattr(ds, 'InstanceNumber', i + 1),
                        'sop_instance_uid': getattr(ds, 'SOPInstanceUID', f'generated_{i}'),
                        'is_rgb': len(getattr(ds, 'PhotometricInterpretation', '')) > 0 and 'RGB' in str(ds.PhotometricInterpretation),
                        'file_path': dcm_file
                    }
                    metadata['instances'].append(instance_meta)
                except Exception as meta_error:
                    print(f"⚠️ Error reading metadata from {dcm_file}: {meta_error}")
                    # Add basic instance info
                    metadata['instances'].append({
                        'instance_number': i + 1,
                        'sop_instance_uid': f'generated_{i}',
                        'is_rgb': False,
                        'file_path': dcm_file
                    })

            print(f"✅ Created metadata for {len(metadata['instances'])} instances")

            # Return in the same format as load_images
            return [(vtk_image_data, metadata, (None, None))]

        except Exception as e:
            print(f"❌ Error in direct DICOM loading: {e}")
            import traceback
            traceback.print_exc()
            raise

    def create_manual_viewer_for_first_series(self, vtk_image_data, metadata):
        """Create viewer manually when init_matrix_viewers fails"""
        try:
            print("🔧 Creating manual viewer for first series...")

            # Import required classes
            from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget
            from PacsClient.pacs.patient_tab.utils.node_viewer import NodeViewer

            # Initialize lists if they don't exist
            if not hasattr(self, 'lst_nodes_viewer'):
                self.lst_nodes_viewer = []
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            # Create VTK widget manually
            vtk_widget = VTKWidget()
            vtk_widget.setMinimumSize(400, 400)

            # Create node viewer
            node_viewer = NodeViewer(vtk_widget, 0)
            self.lst_nodes_viewer = [node_viewer]

            # Add to center layout
            if hasattr(self, 'center_layout') and self.center_layout:
                # Clear existing widgets
                while self.center_layout.count():
                    child = self.center_layout.takeAt(0)
                    if child.widget():
                        child.widget().setParent(None)

                # Add new widget
                self.center_layout.addWidget(vtk_widget, 0, 0)

            # Start processing the series
            vtk_widget.start_process_series(
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                series_index=0,
                id_vtk_widget=0,
                metadata_fixed=self.metadata_fixed
            )

            # Set as selected widget
            self.selected_widget = vtk_widget

            print("✅ Manual viewer created successfully")

        except Exception as e:
            print(f"❌ Error creating manual viewer: {e}")
            import traceback
            traceback.print_exc()
            raise

    def create_simple_viewer_now(self, vtk_image_data, metadata, series_number):
        """Create a simple viewer immediately without complex initialization"""
        try:
            print(f"🎯 Creating simple viewer for series {series_number}")

            # Import required classes
            from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget

            # Check if we already have viewers
            if hasattr(self, 'lst_nodes_viewer') and self.lst_nodes_viewer:
                print("✅ Using existing viewer")
                vtk_widget = self.lst_nodes_viewer[0].vtk_widget
            else:
                print("🔧 Creating new VTK widget")
                # Create a simple VTK widget
                vtk_widget = VTKWidget()
                vtk_widget.setMinimumSize(400, 400)

                # Add to center layout if available
                if hasattr(self, 'center_layout') and self.center_layout:
                    # Clear existing widgets
                    while self.center_layout.count():
                        child = self.center_layout.takeAt(0)
                        if child.widget():
                            child.widget().setParent(None)

                    # Add new widget
                    self.center_layout.addWidget(vtk_widget, 0, 0)
                    print("✅ Added VTK widget to center layout")

                # Initialize viewer lists
                if not hasattr(self, 'lst_nodes_viewer'):
                    self.lst_nodes_viewer = []

                from PacsClient.pacs.patient_tab.utils.node_viewer import NodeViewer
                node_viewer = NodeViewer(vtk_widget, 0)
                self.lst_nodes_viewer = [node_viewer]

            # Start processing the series
            print("🖼️ Starting series processing...")
            vtk_widget.start_process_series(
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                series_index=0,
                id_vtk_widget=0,
                metadata_fixed=self.metadata_fixed
            )

            # Set as selected widget
            self.selected_widget = vtk_widget

            print("✅ Simple viewer created and series loaded successfully!")

        except Exception as e:
            print(f"❌ Error creating simple viewer: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise - just log the error

    def display_series_simple(self, series_data):
        """Simple method to display series without complex processing"""
        try:
            print(f"🖼️ Displaying {len(series_data)} series...")

            # Check if we have series data to display
            if not series_data:
                print("⚠️ No series data to display")
                return

            # Log the series data
            for series_info in series_data:
                print(f"📁 Series {series_info.get('series_number', 'Unknown')}: {series_info.get('file_count', 0)} files")
                print(f"📁 Path: {series_info.get('file_path', 'N/A')}")

            # Now try to create a real viewer
            if series_data:
                first_series = series_data[0]
                series_number = first_series.get('series_number', 1)

                # Get series path using the same method as dicom_downloader
                try:
                    from PacsClient.pacs.patient_tab.utils.utils import check_series_study_exist

                    # Get study_uid from metadata_fixed or import_folder_path
                    study_uid = None
                    if hasattr(self, 'metadata_fixed') and 'study_uid' in self.metadata_fixed:
                        study_uid = self.metadata_fixed['study_uid']
                    elif hasattr(self, 'import_folder_path') and self.import_folder_path:
                        study_uid = os.path.basename(self.import_folder_path)

                    if study_uid:
                        # Use the same method as dicom_downloader
                        series_path = check_series_study_exist(study_uid, str(series_number))
                        print(f"📁 Series path from check_series_study_exist: {series_path}")
                    else:
                        print("⚠️ No study_uid available")
                        return

                    if series_path and os.path.exists(series_path):
                        print(f"🎯 Creating viewer for series: {series_path}")

                        # Create a real viewer for the first series
                        print("✅ First series is ready for viewing")
                        print(f"📁 Series path: {series_path}")

                        try:
                            # Use the direct DICOM loading method we created
                            series_results = self.load_dicom_series_direct(series_path, series_number)

                            if series_results:
                                vtk_image_data, metadata, (patient_pk, study_pk) = series_results[0]
                                print("✅ Series data loaded successfully")

                                # Try to create a simple viewer
                                self.create_simple_viewer_now(vtk_image_data, metadata, series_number)

                            else:
                                print("❌ No series data found")
                                return

                        except Exception as viewer_error:
                            print(f"❌ Error creating viewer: {viewer_error}")
                            import traceback
                            traceback.print_exc()
                            print("🎯 User can click on thumbnail to view the series")
                    else:
                        print(f"⚠️ Series path not found: {series_path}")

                except Exception as db_error:
                    print(f"❌ Error reading from database: {db_error}")
                    import traceback
                    traceback.print_exc()

            print("✅ Series display completed")

        except Exception as e:
            print(f"❌ Error in display_series_simple: {e}")
            import traceback
            traceback.print_exc()

    def create_simple_viewer_for_series(self, series_path):
        """Create a simple viewer for a specific series without requiring thumbnail data"""
        try:
            print(f"🎯 Creating simple viewer for: {series_path}")

            # For now, just show that the series is ready without creating complex viewer
            # This prevents hanging issues
            print("✅ First series is ready for viewing")
            print("📁 Series path:", series_path)

            # Count DICOM files
            import os
            if os.path.exists(series_path):
                dcm_files = [f for f in os.listdir(series_path) if f.endswith('.dcm')]
                print(f"📊 Found {len(dcm_files)} DICOM files in series")

                if dcm_files:
                    print(f"📂 First DICOM file: {dcm_files[0]}")
                    print("🎯 Series is ready - viewer will be created when user clicks on thumbnail")
                else:
                    print("⚠️ No DICOM files found in series path")
            else:
                print("⚠️ Series path does not exist")

            print("✅ Simple viewer preparation completed")

        except Exception as e:
            print(f"❌ Error preparing simple viewer: {e}")
            import traceback
            traceback.print_exc()

    def create_proper_viewer_for_first_series(self, series_path, series_number):
        """Create a proper viewer for the first series with proper initialization"""
        try:
            print(f"🎯 Creating proper viewer for series {series_number}")

            # Load the DICOM files from the series
            import os
            dcm_files = [f for f in os.listdir(series_path) if f.endswith('.dcm')]

            if not dcm_files:
                print("⚠️ No DICOM files found in series")
                return

            # Take the first DICOM file
            first_dcm = os.path.join(series_path, dcm_files[0])
            print(f"📂 Loading first DICOM file: {first_dcm}")

            # Load the DICOM file and create VTK data
            try:
                from PacsClient.pacs.patient_tab.utils.image_io import load_images

                # Create a generator for the series
                series_generator = load_images(series_path)

                # Get the first result
                first_result = next(series_generator)

                if first_result:
                    # Extract VTK data and metadata from tuple
                    # load_images returns: (vtk_image_data, metadata, (patient_pk, study_pk))
                    vtk_image_data, metadata, (patient_pk, study_pk) = first_result

                    if vtk_image_data and metadata:
                        print("✅ VTK data and metadata loaded successfully")

                        # For now, just log the success without creating VTK widget to avoid hanging
                        print(f"📊 VTK Image Data: {type(vtk_image_data)}")
                        print(f"📊 Metadata: {type(metadata)}")
                        print(f"📊 Patient PK: {patient_pk}, Study PK: {study_pk}")

                        # Log metadata details
                        if isinstance(metadata, dict):
                            print(f"📊 Series info: {metadata.get('series', {}).get('series_name', 'Unknown')}")
                            print(f"📊 Study info: {metadata.get('study', {}).get('study_uid', 'Unknown')}")

                        print("✅ First series data is ready - viewer will be created when user clicks on thumbnail")

                        # Store the data for later use
                        if not hasattr(self, 'first_series_data'):
                            self.first_series_data = {
                                'vtk_image_data': vtk_image_data,
                                'metadata': metadata,
                                'patient_pk': patient_pk,
                                'study_pk': study_pk
                            }
                            print("✅ First series data stored for later use")
                    else:
                        print("⚠️ Failed to extract VTK data or metadata")
                else:
                    print("⚠️ No result from series generator")

            except Exception as load_error:
                print(f"❌ Error loading DICOM data: {load_error}")
                import traceback
                traceback.print_exc()

        except Exception as e:
            print(f"❌ Error creating proper viewer: {e}")
            import traceback
            traceback.print_exc()