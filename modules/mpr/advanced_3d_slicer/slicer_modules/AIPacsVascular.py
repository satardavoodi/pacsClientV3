"""AI-PACS vascular workspace, hosted by the existing Slicer runtime."""
from slicer.ScriptedLoadableModule import ScriptedLoadableModule
from aipacs_lumen.workspace import LumenWorkspace


class AIPacsVascular(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = "Vascular Analysis"
        parent.categories = ["AI-PACS"]
        parent.dependencies = ["Segmentations", "Markups", "SegmentEditor"]
        parent.helpText = "Review a lumen segment, trace one vessel and measure perpendicular cross-sections."


class AIPacsVascularWidget(LumenWorkspace):
    mode = "vascular"
