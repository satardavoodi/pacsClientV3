"""
Home Panel Widget - backward-compatible shim.

Original 5,410-line file split into focused mixins in home_panel/ subfolder.
See home_panel/README.md for the file map.

All public names re-exported for backward compatibility:
    from PacsClient.pacs.workstation_ui.home_ui.home_ui import HomePanelWidget
    from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
    from PacsClient.pacs.workstation_ui.home_ui.home_ui import SourceOfPatientLoad
"""
from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import (
    HomePanelWidget,
    SourceOfPatientLoad,
    get_home_widget,
    _ensure_patient_widget,
    _ensure_ai_main_window,
    PRIORITY_MANAGER_AVAILABLE,
    _home_widget_instance,
)

__all__ = [
    "HomePanelWidget",
    "SourceOfPatientLoad",
    "get_home_widget",
]
