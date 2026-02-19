from PySide6.QtWidgets import QSlider, QWidget, QGroupBox, QVBoxLayout
import os
from pathlib import Path
from PacsClient.pacs.patient_tab.ui import PatientWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer


class AiPatientWidget(PatientWidget):
    def __init__(self, parent=None, import_folder_path: str = None):
        if import_folder_path is None:
            # Prefer environment override for local testing:
            #   AIPACS_SAMPLE_IMPORT_DIR=/path/to/study
            import_folder_path = os.getenv("AIPACS_SAMPLE_IMPORT_DIR")

            if not import_folder_path:
                project_root = Path(__file__).resolve().parents[6]
                sample_dir = project_root / "sample_files" / "sample dicom"
                if sample_dir.exists():
                    import_folder_path = str(sample_dir)

            # If still None, PatientWidget will initialize without auto-import path.
        super().__init__(parent, import_folder_path, size_init_viewers=(1, 2))

    def header_layout_ui(self):
        # we don't need header toolbar
        pass

    def init_matrix_viewers(self, numbers):
        self.apply_multi_viewer(numbers)
        # we don't have header toolbar. so we don't connect selected_widget to any toolbar

    def create_some_viewers(self, count):
        index_series_show = 0  # create viewers that all of them show first series of thumbnails
        lst_names_viewer = ['Main Viewer', 'Before Change Viewer']
        for i in range(count):
            new_node: NodeViewer = self.new_viewer(index_series_show)

            # replace default widget with groupbox widget (for add name viewer)
            main_layout = new_node.widget.layout()
            temp_groupbox = QGroupBox(lst_names_viewer[i])
            temp_groupbox.setLayout(main_layout)
            new_node.change_main_widget(temp_groupbox)

    def change_series_on_viewer(self, series_index, *args, **kwargs):

        vtk_image_data = self.lst_thumbnails_data[series_index]['vtk_image_data']
        metadata = self.lst_thumbnails_data[series_index]['metadata']

        main_viewer: NodeViewer = self.lst_nodes_viewer[0]  # we contracted that left viewer is after viewer
        vtk_widget = main_viewer.vtk_widget
        slider = main_viewer.slider

        flag_switch = vtk_widget.switch_series(vtk_image_data, metadata, series_index)
        if flag_switch is True:
            self.reset_slider(vtk_widget, slider)

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        if self.selected_widget == node_viewer.vtk_widget:
            # print('we clicked on the main viewer')
            return False

        # set new vtk_widget to main vtk_widget
        self.selected_widget = node_viewer.vtk_widget
        self.slider = node_viewer.slider