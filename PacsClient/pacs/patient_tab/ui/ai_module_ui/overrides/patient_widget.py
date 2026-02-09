import asyncio
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QWidget, QGroupBox, QVBoxLayout, QButtonGroup, QFrame

from PacsClient.pacs.patient_tab.ui import PatientWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer, TYPES_VIEWER, VerticalButton, has_subfolders
from PacsClient.pacs.patient_tab.ui.ai_module_ui.toolbar import ToolBarManager
from .vtk_widget import AIVTKWidget
from PacsClient.utils import CallerTypes
from PacsClient.utils.config import SOURCE_PATH


class AIPatientWidget(PatientWidget):
    """
    AI Module Patient Widget - extends base PatientWidget with AI-specific functionality
    Removes all duplicated code and properly inherits from base class
    """
    
    def __init__(self, parent=None, study_uid: str = None, imaging_tab_ui=None):
        # Set up AI-specific properties
        self.type_viewer = None
        self.imaging_tab_ui = imaging_tab_ui
        
        # Determine import folder path based on study_uid
        sample_study = Path.cwd() / r'sample_files\sample dicom/2.16.840.1.113669.632.20.20250825.152409026.1.1'
        import_folder_path = sample_study

        print('study_uid:', study_uid)

        try:
            if study_uid:
                study_path = SOURCE_PATH / study_uid  # source path
                if study_path.exists() and has_subfolders(study_path):  # really study existed
                    import_folder_path = study_path  # load a selected study
        except Exception as e:
            print('error in override patient widget', e)
            import_folder_path = sample_study

        # Initialize parent class
        super().__init__(parent, str(import_folder_path), size_init_viewers=(1, 1), caller=CallerTypes.IMPORT)
        self.ordering_by_instances_number = False

    def header_layout_ui(self):
        """Override to use AI-specific toolbar manager"""
        self.toolbar_manager = ToolBarManager(self)

    def get_optimal_layout_for_series(self, metadata: dict) -> tuple:
        """
        Override to return optimal layout for AI module analysis view
        AI module only needs single viewport (1,1) for detailed analysis
        """
        return (1, 1)

    def creator_vtk_widget(self):
        """Override to create AI-specific VTK widget"""
        height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
        return AIVTKWidget(height_viewer=height, patient_widget=self, type_viewer=self.type_viewer)

    def update_sidebar_ui(self, lst_boxes_object):
        """AI-specific method to update sidebar with box objects"""
        for box_object in lst_boxes_object:
            print('box :', box_object)
            if self.imaging_tab_ui:
                self.imaging_tab_ui.sidebar_upsert_item(
                    key=box_object.box_name, 
                    status=box_object.status_abnormal,
                    box_object=box_object, 
                    classification=box_object.classification_label
                )

    def sidebar_clear(self):
        """AI-specific method to clear sidebar"""
        if self.imaging_tab_ui:
            self.imaging_tab_ui.sidebar_clear()

    def create_some_viewers(self, count):
        """AI-specific method to create viewers with custom names"""
        index_series_show = 0  # create viewers that all of them show first series of thumbnails
        lst_names_viewer = [TYPES_VIEWER.your_viewer, TYPES_VIEWER.fixed_viewer]
        for i in range(count):
            self.type_viewer = lst_names_viewer[i]
            new_node: NodeViewer = self.new_viewer(index_series_show)

            # replace default widget with groupbox widget (for add name viewer)
            main_layout = new_node.widget.layout()
            if main_layout:
                main_layout.setContentsMargins(0, 10, 0, 10)

                temp_groupbox = QGroupBox(lst_names_viewer[i])
                temp_groupbox.setLayout(main_layout)
                new_node.change_main_widget(temp_groupbox)

    def manage_reference_line(self):
        """Override to disable reference lines for AI module"""
        pass  # turn off reference lines for AI
