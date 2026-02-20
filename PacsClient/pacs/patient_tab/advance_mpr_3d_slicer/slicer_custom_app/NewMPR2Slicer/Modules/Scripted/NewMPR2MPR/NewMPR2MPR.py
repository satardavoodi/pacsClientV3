"""
NewMPR2MPR - Multi-Planar Reconstruction Module for NewMPR2Slicer

This scripted module provides MPR visualization controls integrated with
the NewMPR2 PACS viewer application. It is automatically activated when
NewMPR2Slicer is launched with --layout mpr.

Launch Contract Reference:
  See: docs/launch_contract.md
"""

import os
import logging
from typing import Optional

import slicer
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleWidget,
    ScriptedLoadableModuleLogic,
)
from slicer.util import VTKObservationMixin

try:
    import qt
    import ctk
    import vtk
except ImportError:
    pass  # Will be available when running inside Slicer


# =============================================================================
# Module Class
# =============================================================================

class NewMPR2MPR(ScriptedLoadableModule):
    """
    NewMPR2MPR Slicer Scripted Module
    
    Provides MPR visualization and controls for DICOM volumes loaded from
    the AI-PACS main application via the launch contract.
    """
    
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        
        # Module metadata - consistent with AI-PACS branding
        self.parent.title = "AI-PACS MPR Viewer"
        self.parent.categories = ["AI-PACS"]
        self.parent.dependencies = []
        self.parent.contributors = ["AI-PACS Development Team"]
        self.parent.helpText = """
        <h3>AI-PACS Multi-Planar Reconstruction Module</h3>
        <p>This module provides MPR visualization controls for DICOM volumes
        loaded from the AI-PACS PACS viewer.</p>
        <h4>Features:</h4>
        <ul>
            <li>Automatic volume loading from command line</li>
            <li>MPR layout configuration</li>
            <li>Window/Level controls</li>
            <li>Linked view navigation</li>
        </ul>
        <p>For more information, see the AI-PACS documentation.</p>
        """
        self.parent.acknowledgementText = """
        This module is part of the AI-PACS medical imaging platform.
        Developed by AI-PACS Development Team.
        """
        

# =============================================================================
# Widget Class
# =============================================================================

class NewMPR2MPRWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """
    NewMPR2MPR Widget
    
    Provides the user interface for the NewMPR2 MPR module.
    UI styling is inherited from the global QSS stylesheet.
    """
    
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        
        self.logic: Optional['NewMPR2MPRLogic'] = None
        self._volumeNode = None
        self._patientId = None
        self._studyId = None
    
    def setup(self):
        """Initialize the widget UI."""
        ScriptedLoadableModuleWidget.setup(self)
        
        # Create logic instance
        self.logic = NewMPR2MPRLogic()
        
        # Load UI from .ui file or create programmatically
        self._setupUI()
        
        # Connect to scene events for volume updates
        self._setupConnections()
        
        # Initial update
        self._updateVolumeInfo()
    
    def _setupUI(self):
        """
        Create the module UI programmatically.
        """
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)
        
        headerFrame = qt.QFrame()
        headerFrame.setObjectName("mprHeader")
        headerFrame.setMinimumHeight(50)
        headerFrame.setMaximumHeight(56)
        
        headerLayout = qt.QHBoxLayout(headerFrame)
        headerLayout.setContentsMargins(12, 8, 12, 8)
        headerLayout.setSpacing(8)
        
        titleLabel = qt.QLabel("MPR - AI-PACS Advanced Viewer")
        titleLabel.setObjectName("mprTitle")
        headerLayout.addWidget(titleLabel)
        
        subtitleLabel = qt.QLabel("Multi-Planar Reconstruction")
        subtitleLabel.setObjectName("mprSubtitle")
        headerLayout.addWidget(subtitleLabel)
        
        headerLayout.addStretch()
        self.layout.addWidget(headerFrame)
        
        bodyFrame = qt.QFrame()
        bodyFrame.setObjectName("mprBodyPanel")
        bodyLayout = qt.QVBoxLayout(bodyFrame)
        bodyLayout.setContentsMargins(8, 8, 8, 8)
        bodyLayout.setSpacing(8)

        infoSection = qt.QFrame()
        infoSection.setObjectName("mprControlPanel")
        infoLayout = qt.QVBoxLayout(infoSection)
        infoLayout.setContentsMargins(10, 10, 10, 10)
        infoLayout.setSpacing(4)

        infoTitle = qt.QLabel("📊 Volume Information")
        infoTitle.setObjectName("sectionTitle")
        infoLayout.addWidget(infoTitle)

        patNameRow = qt.QHBoxLayout()
        patNameLabel = qt.QLabel("Patient:")
        patNameLabel.setFixedWidth(70)
        patNameLabel.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.patientNameLabel = qt.QLabel("—")
        self.patientNameLabel.setObjectName("mprValueLabel")
        self.patientNameLabel.setStyleSheet("color: #e5e7eb; font-size: 11px; font-weight: 500;")
        patNameRow.addWidget(patNameLabel)
        patNameRow.addWidget(self.patientNameLabel, 1)
        infoLayout.addLayout(patNameRow)

        modalityRow = qt.QHBoxLayout()
        modalityLabel = qt.QLabel("Modality:")
        modalityLabel.setFixedWidth(70)
        modalityLabel.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.modalityLabel = qt.QLabel("—")
        self.modalityLabel.setObjectName("mprValueLabel")
        self.modalityLabel.setStyleSheet("color: #e5e7eb; font-size: 11px;")
        modalityRow.addWidget(modalityLabel)
        modalityRow.addWidget(self.modalityLabel, 1)
        infoLayout.addLayout(modalityRow)

        seqRow = qt.QHBoxLayout()
        seqLabel = qt.QLabel("Sequence:")
        seqLabel.setFixedWidth(70)
        seqLabel.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.sequenceLabel = qt.QLabel("—")
        self.sequenceLabel.setObjectName("mprValueLabel")
        self.sequenceLabel.setStyleSheet("color: #e5e7eb; font-size: 11px;")
        self.sequenceLabel.setWordWrap(True)
        seqRow.addWidget(seqLabel)
        seqRow.addWidget(self.sequenceLabel, 1)
        infoLayout.addLayout(seqRow)

        dimRow = qt.QHBoxLayout()
        dimLabel = qt.QLabel("Size:")
        dimLabel.setFixedWidth(70)
        dimLabel.setStyleSheet("color: #9ca3af; font-size: 11px;")
        self.dimensionsLabel = qt.QLabel("—")
        self.dimensionsLabel.setObjectName("mprValueLabel")
        self.dimensionsLabel.setStyleSheet("color: #e5e7eb; font-size: 11px;")
        dimRow.addWidget(dimLabel)
        dimRow.addWidget(self.dimensionsLabel, 1)
        infoLayout.addLayout(dimRow)

        bodyLayout.addWidget(infoSection)
        bodyLayout.addStretch(1)
        self.layout.addWidget(bodyFrame)

        infoBarFrame = qt.QFrame()
        infoBarFrame.setObjectName("mprInfoBar")
        infoBarFrame.setMinimumHeight(36)
        infoBarFrame.setMaximumHeight(44)

        infoBarLayout = qt.QHBoxLayout(infoBarFrame)
        infoBarLayout.setContentsMargins(10, 6, 10, 6)
        infoBarLayout.setSpacing(8)

        self.dicomPathLabel = qt.QLabel("📂 DICOM: (not loaded)")
        self.dicomPathLabel.setObjectName("infoPath")
        infoBarLayout.addWidget(self.dicomPathLabel, 1)

        self.statusLabel = qt.QLabel("● Ready")
        self.statusLabel.setStyleSheet("color: #10b981;")
        infoBarLayout.addWidget(self.statusLabel)

        self.layout.addWidget(infoBarFrame)
    
    def _setupConnections(self):
        self.addObserver(
            slicer.mrmlScene,
            slicer.mrmlScene.EndCloseEvent,
            self._onSceneClose
        )
        self.addObserver(
            slicer.mrmlScene,
            slicer.mrmlScene.NodeAddedEvent,
            self._onNodeAdded
        )

    def cleanup(self):
        self.removeObservers()

    def _onSceneClose(self, caller, event):
        self._volumeNode = None
        self._updateVolumeInfo()

    def _onNodeAdded(self, caller, event):
        qt.QTimer.singleShot(500, self._updateVolumeInfo)

    def _updateVolumeInfo(self):
        volumeNode = self._getActiveVolumeNode()

        if volumeNode:
            self._volumeNode = volumeNode
            dims = volumeNode.GetImageData().GetDimensions() if volumeNode.GetImageData() else (0, 0, 0)
            spacing = volumeNode.GetSpacing()
            self.dimensionsLabel.setText(f"{dims[0]}×{dims[1]}×{dims[2]} ({spacing[0]:.1f}mm)")
            self._updatePatientInfo(volumeNode)
            self.statusLabel.setText("● Volume Loaded")
            self.statusLabel.setStyleSheet("color: #10b981;")
        else:
            self.patientNameLabel.setText("—")
            self.modalityLabel.setText("—")
            self.sequenceLabel.setText("—")
            self.dimensionsLabel.setText("—")
            self.statusLabel.setText("○ No Data")
            self.statusLabel.setStyleSheet("color: #6b7280;")

    def _updatePatientInfo(self, volumeNode):
        patientName = volumeNode.GetName() if volumeNode else "—"
        modality = "—"
        seriesDesc = "—"

        try:
            if hasattr(slicer, 'dicomDatabase') and slicer.dicomDatabase and slicer.dicomDatabase.isOpen:
                uids = volumeNode.GetAttribute("DICOM.instanceUIDs")
                if uids:
                    uid = uids.split()[0]
                    patientName = slicer.dicomDatabase.instanceValue(uid, "0010,0010") or patientName
                    modality = slicer.dicomDatabase.instanceValue(uid, "0008,0060") or modality
                    seriesDesc = slicer.dicomDatabase.instanceValue(uid, "0008,103E") or seriesDesc
        except Exception as e:
            logging.debug(f"Could not get DICOM info: {e}")

        if "^" in patientName:
            parts = patientName.split("^")
            patientName = f"{parts[1]} {parts[0]}" if len(parts) > 1 else parts[0]

        self.patientNameLabel.setText(patientName[:25] + "..." if len(patientName) > 25 else patientName)
        self.modalityLabel.setText(modality)
        self.sequenceLabel.setText(seriesDesc[:30] + "..." if len(seriesDesc) > 30 else seriesDesc)

    def _getActiveVolumeNode(self):
        compositeNodes = slicer.util.getNodesByClass("vtkMRMLSliceCompositeNode")
        for compositeNode in compositeNodes:
            bgVolumeId = compositeNode.GetBackgroundVolumeID()
            if bgVolumeId:
                volumeNode = slicer.mrmlScene.GetNodeByID(bgVolumeId)
                if volumeNode:
                    return volumeNode

        volumeNodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        return volumeNodes[0] if volumeNodes else None


# =============================================================================
# Logic Class
# =============================================================================

class NewMPR2MPRLogic(ScriptedLoadableModuleLogic):
    """Business logic for NewMPR2MPR module."""

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)

    def setDefaultParameters(self, parameterNode):
        if not parameterNode.GetParameter("SlabThickness"):
            parameterNode.SetParameter("SlabThickness", "0.0")
        if not parameterNode.GetParameter("LinkViews"):
            parameterNode.SetParameter("LinkViews", "true")
        if not parameterNode.GetParameter("ShowCrosshair"):
            parameterNode.SetParameter("ShowCrosshair", "true")

    @staticmethod
    def storePatientInfo(patientId: str, studyId: str):
        parameterNode = None
        nodes = slicer.util.getNodesByClass("vtkMRMLScriptedModuleNode")
        for node in nodes:
            if node.GetAttribute("ModuleName") == "NewMPR2MPR":
                parameterNode = node
                break

        if not parameterNode:
            parameterNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode")
            parameterNode.SetAttribute("ModuleName", "NewMPR2MPR")
            parameterNode.SetName("NewMPR2MPRParameters")

        if patientId:
            parameterNode.SetParameter("PatientID", patientId)
        if studyId:
            parameterNode.SetParameter("StudyID", studyId)

        return parameterNode
