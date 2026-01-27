import asyncio

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QWidget, QGroupBox, QVBoxLayout, QLabel, QGridLayout, QButtonGroup
from PacsClient.pacs.patient_tab.ui import PatientWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer
from PacsClient.pacs.patient_tab.ui.ai_module_ui.toolbar import ToolBarManager
from pathlib import Path
from PacsClient.utils import CallerTypes
from .vtk_widget import AIVTKWidget
from PacsClient.pacs.patient_tab.utils import BoxManager, TYPES_VIEWER, VerticalButton, has_subfolders
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget
from PacsClient.utils.config import SOURCE_PATH


class AIPatientWidget(PatientWidget):
    # def __init__(self, parent=None, import_folder_path: str = None, imaging_tab_ui=None):
    def __init__(self, parent=None, study_uid: str = None, imaging_tab_ui=None):
        self.type_viewer = None

        sample_study = Path.cwd() / r'sample_files\sample dicom/2.16.840.1.113669.632.20.20250825.152409026.1.1'
        import_folder_path = sample_study

        print('study_uid:', study_uid)

        try:
            if study_uid:
                study_path = SOURCE_PATH / study_uid  # source path
                if study_path.exists():
                    if has_subfolders(study_path):  # really study existed
                        import_folder_path = study_path  # load a selected study

        except Exception as e:
            print('error in override patient widget', e)

            # if import_folder_path is None:
            #     # import_folder_path = r'sample_files/sample dicom/1.3.46.670589.11.63286.5.0.15220.2024082210022481008/1.3.12.2.1107.5.2.30.27105.2024090807314525073321420.0.0.0'
            #     # import_folder_path = r'/Users/mac/Downloads/PacsClient/sample_files/sample dicom/1.3.46.670589.11.63286.5.0.15220.2024082210022481008/1.3.12.2.1107.5.2.30.27105.2024090807314525073321420.0.0.0'
            #     # import_folder_path = Path.cwd() / 'sample_files\sample dicom/1.3.46.670589.11.63286.5.0.15220.2024082210022481008/1.3.12.2.1107.5.2.30.27105.2024090807314525073321420.0.0.0'
            #     # import_folder_path = r'M:\mostafa\codes\PacsClient\sample_files\sample dicom\1.3.46.670589.11.63286.5.0.15220.2024082210022481008\1.3.12.2.1107.5.2.30.27105.2024090807314525073321420.0.0.0'
            #     # import_folder_path = r'/Users/euleday/Desktop/SR03'
            #     # import_folder_path = r'C:\Users\Salari\Desktop\copy\m\sample_1\2.16.840.1.113669.632.20.20250825.152409026.1.1'
            #
            #     import_folder_path = Path.cwd() / 'sample_files\sample dicom/2.16.840.1.113669.632.20.20250825.152409026.1.1'
            # import_folder_path = r'C:\Users\Salari\Downloads\Telegram Desktop\SR03\SR03'
            # import_folder_path = r'/USERS/mac/2.16.840.1.113669.632.20.20250825.152409026.1.1'

        super().__init__(parent, str(import_folder_path), size_init_viewers=(1, 2), caller=CallerTypes.IMPORT)
        self.ordering_by_instances_number = False

        self.imaging_tab_ui = imaging_tab_ui

    def header_layout_ui(self):
        self.toolbar_manager = ToolBarManager(self)

    def init_matrix_viewers(self, numbers=None):
        self.apply_multi_viewer(numbers)
        # we don't have header toolbar. so we don't connect selected_widget to any toolbar
        if len(self.lst_nodes_viewer) > 0:
            self.selected_widget = self.lst_nodes_viewer[0].vtk_widget

    def update_sidebar_ui(self, lst_boxes_object):
        for box_object in lst_boxes_object:
            box_object: BoxManager
            print('box :', box_object)
            self.imaging_tab_ui.sidebar_upsert_item(key=box_object.box_name, status=box_object.status_abnormal,
                                                    box_object=box_object, classification=box_object.classification_label)

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
        layout.setSpacing(0)

        # دکمه‌ها (بدون setFixedHeight)
        self.btn_series = VerticalButton("Series")
        self.btn_series.setCheckable(True)
        self.btn_series.setChecked(True)
        self.btn_series.setStyleSheet(self.sidebar_btn_style(True))

        self.btn_reception = VerticalButton("Reception Data")
        self.btn_reception.setCheckable(True)
        self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))

        self.btn_ai_chat = VerticalButton("ECHO MIND")
        self.btn_ai_chat.setCheckable(True)
        self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))

        # گروه انحصاری
        self.sidebar_btn_group = QButtonGroup(sidebar)
        self.sidebar_btn_group.setExclusive(True)
        self.sidebar_btn_group.addButton(self.btn_series)
        self.sidebar_btn_group.addButton(self.btn_reception)
        self.sidebar_btn_group.addButton(self.btn_ai_chat)

        # اضافه به لایه + stretch برابر تا فضا را به صورت تطبیقی تقسیم کنند
        layout.addWidget(self.btn_series, 1)
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_reception, 1)
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_ai_chat, 1)
        layout.addStretch(0)

        # اتصال‌ها
        self.btn_series.clicked.connect(lambda: self.switch_right_panel("series"))
        self.btn_reception.clicked.connect(lambda: self.switch_right_panel("reception"))
        self.btn_ai_chat.clicked.connect(lambda: self.switch_right_panel("ai_chat"))

        return sidebar

    def sidebar_clear(self):
        self.imaging_tab_ui.sidebar_clear()

    def creator_vtk_widget(self):
        height = self.sidebar.height()
        return AIVTKWidget(height_viewer=height, patient_widget=self, type_viewer=self.type_viewer)

    # def _distribute_mg_images(self, vtk_image_data, metadata):
    #     pass
    #
    # def _distribute_mg_images_from_series_list(self, mg_series_data, combined_metadata):
    #     pass

    def get_optimal_layout_for_series(self, metadata: dict) -> tuple:
        """
        Return optimal layout for AI module analysis view
        AI module only needs single viewport (1,1) for detailed analysis
        """
        # AI module: single viewport for focused analysis
        return (1, 1)

    def create_some_viewers(self, count):
        index_series_show = 0  # create viewers that all of them show first series of thumbnails
        lst_names_viewer = [TYPES_VIEWER.your_viewer, TYPES_VIEWER.fixed_viewer]
        for i in range(count):
            self.type_viewer = lst_names_viewer[i]
            new_node: NodeViewer = self.new_viewer(index_series_show)

            # replace default widget with groupbox widget (for add name viewer)
            main_layout: QGridLayout = new_node.widget.layout()
            main_layout.setContentsMargins(0, 10, 0, 10)

            temp_groupbox = QGroupBox(lst_names_viewer[i])
            temp_groupbox.setLayout(main_layout)
            new_node.change_main_widget(temp_groupbox)

    def _display_loaded_series(self, series_number, vtk_image_data, metadata,
                               flag_change_selected_widget, vtk_widget, slider):
        """
        نمایش سری که قبلاً لود شده است
        این تابع فقط قسمت visualization را انجام می‌دهد
        """
        try:
            # Check if we have a selected_widget set
            if flag_change_selected_widget and self.selected_widget is None:
                print(f"⚠️ [DISPLAY] selected_widget is None, trying to set from lst_nodes_viewer")
                if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                    self.selected_widget = self.lst_nodes_viewer[0].vtk_widget
                    self.slider = self.lst_nodes_viewer[0].slider
                    print(f"   ✅ Set selected_widget from first viewer")
                else:
                    print(f"   ❌ No viewers available!")
                    return

            # ادامه کد change_series_on_viewer از اینجا
            vtk_widget_data_2 = None
            metadata_2 = None

            for i in range(len(self.lst_thumbnails_data)):
                series_number_2 = self.lst_thumbnails_data[i]['metadata']['series']['series_number']
                if (series_number_2 == series_number) and id(self.lst_thumbnails_data[i]['vtk_image_data']) != id(
                        vtk_image_data):
                    vtk_widget_data_2 = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata_2 = self.lst_thumbnails_data[i]['metadata']
                    break

            for node_viewer in self.lst_nodes_viewer:
                node_viewer: NodeViewer

                vtk_widget = node_viewer.vtk_widget
                slider = node_viewer.slider
                flag_switch = vtk_widget.switch_series(vtk_image_data, metadata, series_number, vtk_widget_data_2,
                                                       metadata_2, self.metadata_fixed)
                if flag_switch is True:
                    self.reset_slider(vtk_widget, slider)
                    # vtk_widget.resizeEvent(None)
                    # vtk_widget.image_viewer.update_corners_actors()

        except Exception as e:
            print('error on display loaded series:', e)
            import traceback
            traceback.print_exc()

    def new_viewer(self, default_thumb_index=0):
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        layout.setSpacing(0)  # Remove spacing

        # Check if we have thumbnail data
        if not self.lst_thumbnails_data or len(self.lst_thumbnails_data) == 0:
            # Create a placeholder viewer when no data is available
            vtk_widget = self.create_dummy_vtk_widget()
        else:
            vtk_widget = self.create_new_vtk_widget(default_thumb_index)

        slider = QSlider(Qt.Vertical, vtk_widget)
        slider.setInvertedAppearance(True)

        # slider.setStyleSheet("""
        #     QSlider {
        #         background: rgba(0, 0, 0, 1);
        #         border-radius: 0px;
        #         border: none;
        #         padding-top: 50px;   /* فاصله داخل اسلایدر از بالا */
        #         padding-bottom: 50px;  /* فاصله داخل اسلایدر از پایین */
        #     }
        # """)
        pass

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

        layout.addWidget(vtk_widget, 0, 0)
        # layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight)

        container = QWidget()
        container.setLayout(layout)
        container.setStyleSheet("""
            QWidget {
                border: 2px solid #4a5568;
                border-radius: 5px;
                margin: 1px;
                padding: 0px;
                background: rgba(26, 32, 44, 0.3);
            }
        """)

        ##############################################################
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
        return new_node
        # return widget

    def change_container_border(self, id_vtk_widget):
        # TODO: at first we must check last viewer selected. if the last viewed selected and id_vtk_widget are the
        #  same, skip the for (return)
        node_viewer_selected = self.lst_nodes_viewer[id_vtk_widget]
        for node_viewer in self.lst_nodes_viewer:
            node_viewer: NodeViewer

            if node_viewer_selected.widget == node_viewer.widget:
                node_viewer_selected.widget.setStyleSheet("""
                    QWidget {
                        border: 3px solid #3182ce;
                        border-radius: 5px;
                        margin: 1px;
                        padding: 0px;
                        background: rgba(49, 130, 206, 0.1);
                    }
                """)
                self.set_viewer_to_main_viewer(node_viewer_selected)

            else:
                node_viewer.widget.setStyleSheet("""
                    QWidget {
                        border: 2px solid #4a5568;
                        border-radius: 5px;
                        margin: 1px;
                        padding: 0px;
                        background: rgba(26, 32, 44, 0.3);
                    }
                """)

        # self.manage_reference_line()

    def manage_reference_line(self):
        pass  # turn off reference lines for AI
