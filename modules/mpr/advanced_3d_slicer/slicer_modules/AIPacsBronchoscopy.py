"""AI-PACS virtual bronchoscopy workspace using the shared Slicer runtime."""
from slicer.ScriptedLoadableModule import ScriptedLoadableModule
from aipacs_lumen.workspace import LumenWorkspace


class AIPacsBronchoscopy(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = "Virtual Bronchoscopy"
        parent.categories = ["AI-PACS"]
        parent.dependencies = ["Segmentations", "Markups", "SegmentEditor"]
        parent.helpText = "Review the airway segment, choose a branch and navigate its interior alongside CT."


class AIPacsBronchoscopyWidget(LumenWorkspace):
    mode = "bronchoscopy"
