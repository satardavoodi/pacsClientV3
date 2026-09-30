"""Two private MRML workspaces with one stateless processing implementation."""
import queue
import threading
import time
from pathlib import Path

import numpy as np
import qt
import ctk
import slicer
import vtk
from slicer.ScriptedLoadableModule import ScriptedLoadableModuleWidget

from .geometry import path_frames, diameter_stenosis, segment_snapshot
from .seed_presets import PRESETS, ensure_seed_segments, lumen_segment_id
from .lighting import FlyThroughLight, configure_lumen_display


class LumenWorkspace(ScriptedLoadableModuleWidget):
    mode = "vascular"

    def section(self, title):
        panel = ctk.ctkCollapsibleButton()
        panel.text = title
        panel.setObjectName("lumenStep")
        panel.setStyleSheet("ctkCollapsibleButton#lumenStep { color: #a5dfec; background: #1b3347; border: 0; padding: 5px; font-weight: 600; }")
        self.layout.addWidget(panel)
        return panel

    @staticmethod
    def actionRow(*buttons):
        container = qt.QWidget()
        row = qt.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for button in buttons:
            button.setSizePolicy(qt.QSizePolicy.Maximum, qt.QSizePolicy.Fixed)
            button.setStyleSheet("QPushButton { padding: 4px 10px; min-height: 20px; }")
            row.addWidget(button)
        row.addStretch(1)
        return container

    def setup(self):
        super().setup()
        self.parameter = None
        self.result = None
        self.cancel = threading.Event()
        self.results = queue.Queue()
        self.worker = None
        self.generation = 0
        self.observers = []
        self.playing = False
        self.camera_backup = None
        self.flyLight = None
        self.publishing = False
        self.pollTimer = qt.QTimer()
        self.pollTimer.setInterval(40)
        self.pollTimer.connect("timeout()", self.poll)
        self.playTimer = qt.QTimer()
        self.playTimer.setInterval(33)
        self.playTimer.connect("timeout()", self.tick)
        self.source = slicer.qMRMLNodeComboBox()
        self.source.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self.source.noneEnabled = True
        self.source.addEnabled = False
        self.source.removeEnabled = False
        self.source.setMRMLScene(slicer.mrmlScene)
        sourcePanel = self.section("1. Source image")
        sourceLayout = qt.QVBoxLayout(sourcePanel)
        sourceLayout.addWidget(self.source)
        self.source.connect("currentNodeChanged(vtkMRMLNode*)", self.setSource)

        segmentation = self.section("2. Segment and review the lumen")
        self.segmentPanel = segmentation
        segmentationLayout = qt.QVBoxLayout(segmentation)
        self.editor = slicer.qMRMLSegmentEditorWidget()
        self.editor.setMRMLScene(slicer.mrmlScene)
        self.editor.setSegmentationNodeSelectorVisible(False)
        self.editor.setSourceVolumeNodeSelectorVisible(False)
        self.editor.setMaximumNumberOfUndoStates(5)
        self.editor.setUndoEnabled(True)
        segmentationLayout.addWidget(self.editor)

        route = self.section("3. Select a route")
        form = qt.QFormLayout(route)
        self.place = qt.QPushButton("Place start and destination")
        self.place.connect("clicked()", self.placeEndpoints)
        form.addRow(self.actionRow(self.place))
        self.routeStatus = qt.QLabel("Route endpoints: 0 / 2. Use Place start and destination.")
        self.routeStatus.wordWrap = True
        form.addRow(self.routeStatus)
        self.manual = slicer.qMRMLNodeComboBox()
        self.manual.nodeTypes = ["vtkMRMLMarkupsCurveNode"]
        self.manual.noneEnabled = True
        self.manual.selectNodeUponCreation = False
        self.manual.addEnabled = False
        self.manual.removeEnabled = False
        self.manual.setMRMLScene(slicer.mrmlScene)
        self.manual.setToolTip("Optional reviewed curve for this source. Leave empty to compute a VMTK centerline.")
        form.addRow("Manual route (optional)", self.manual)
        self.manual.connect("currentNodeChanged(vtkMRMLNode*)", self.inputsChanged)
        self.compute = qt.QPushButton("Compute route")
        self.compute.setToolTip("Compute centerline and cross-sectional measurements.")
        self.compute.connect("clicked()", self.run)
        self.computeStatus = qt.QLabel("")
        self.computeStatus.wordWrap = True
        self.cancelButton = qt.QPushButton("Cancel")
        self.cancelButton.enabled = False
        self.cancelButton.connect("clicked()", self.cancelJob)
        form.addRow(self.actionRow(self.compute, self.cancelButton))
        form.addRow(self.computeStatus)

        review = self.section("4. Navigate and measure" if self.mode == "vascular" else "4. Fly through the selected branch")
        form = qt.QFormLayout(review)
        self.position = qt.QSlider(qt.Qt.Horizontal)
        self.position.setRange(0, 0)
        self.position.connect("valueChanged(int)", self.navigate)
        form.addRow("Position", self.position)
        self.measurement = qt.QLabel("No route computed")
        self.measurement.wordWrap = True
        form.addRow(self.measurement)
        if self.mode == "vascular":
            self.reference = qt.QPushButton("Set reference")
            self.reference.setToolTip("Use the current section as the diameter reference.")
            self.reference.connect("clicked()", self.setReference)
            form.addRow(self.actionRow(self.reference))
            self.stenosis = qt.QLabel("Reference not selected")
            self.stenosis.wordWrap = True
            form.addRow(self.stenosis)
        else:
            self.playButton = qt.QPushButton("Play / Pause")
            self.playButton.connect("clicked()", self.togglePlay)
            form.addRow(self.actionRow(self.playButton))
            self.speed = qt.QDoubleSpinBox()
            self.speed.setRange(0.5, 50)
            self.speed.setValue(5)
            self.speed.setSuffix(" mm/s")
            form.addRow("Speed", self.speed)
            self.reverse = qt.QCheckBox("Reverse travel")
            form.addRow(self.reverse)
            self.angle = qt.QDoubleSpinBox()
            self.angle.setRange(30, 120)
            self.angle.setValue(90)
            self.angle.connect("valueChanged(double)", lambda value: self.navigate(self.position.value))
            form.addRow("Field of view (degrees)", self.angle)
            self.wallBrightness = qt.QSpinBox()
            self.wallBrightness.setRange(20, 80)
            self.wallBrightness.setValue(55)
            self.wallBrightness.setSuffix(" %")
            self.wallBrightness.setToolTip("Adjust wall illumination while retaining directional shading. This is a segmented surface, not optical tissue color.")
            self.wallBrightness.connect("valueChanged(int)", self.updateWallBrightness)
            form.addRow("Wall brightness", self.wallBrightness)
        self.overview = qt.QPushButton("Restore overview")
        self.overview.connect("clicked()", self.restoreOverview)
        save = qt.QPushButton("Save scene")
        save.setToolTip("Save the scene, segmentation, route and measurements.")
        save.connect("clicked()", slicer.util.openSaveDataDialog)
        form.addRow(self.actionRow(self.overview, save))
        self.status = qt.QLabel("Select a source image to begin.")
        self.status.wordWrap = True
        self.layout.addWidget(self.status)
        self.layout.addStretch(1)
        self.closeObserver = slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.StartCloseEvent, self.sceneClosing)

    def setSource(self, volume):
        if self.parameter and self.parameter.GetNodeReference("source") == volume:
            return
        self.invalidate()
        self.clearObservers()
        self.parameter = None
        self.editor.setSegmentationNode(None)
        self.editor.setSourceVolumeNode(None)
        self.editor.setMRMLSegmentEditorNode(None)
        if volume is None:
            return
        if volume.GetParentTransformNode():
            self.status.text = "Harden the source transform before lumen analysis."
            return
        blocked = self.source.blockSignals(True)
        self.source.setCurrentNode(volume)
        self.source.blockSignals(blocked)
        for node in slicer.util.getNodesByClass("vtkMRMLScriptedModuleNode"):
            if node.GetAttribute("AIPacsLumenMode") == self.mode and node.GetNodeReference("source") == volume:
                self.parameter = node
                break
        if self.parameter is None:
            self.parameter = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScriptedModuleNode", self.mode + " session")
            self.parameter.SetAttribute("AIPacsLumenMode", self.mode)
            self.parameter.SetNodeReferenceID("source", volume.GetID())
        segment = self.node("segmentation", "vtkMRMLSegmentationNode", "Lumen")
        segment.CreateDefaultDisplayNodes()
        segment.SetReferenceImageGeometryParameterFromVolumeNode(volume)
        classes, created = ensure_seed_segments(segment.GetSegmentation(), self.mode)
        for role, name, color, enabled, guidance in PRESETS[self.mode]:
            if role in created:
                segment.GetDisplayNode().SetSegmentVisibility(classes[role], enabled)
        editorNode = self.node("editor", "vtkMRMLSegmentEditorNode", "Lumen editor")
        self.editor.setMRMLSegmentEditorNode(editorNode)
        self.editor.setSegmentationNode(segment)
        self.editor.setSourceVolumeNode(volume)
        self.editor.setCurrentSegmentID(classes["lumen"])
        seeds = self.node("seeds", "vtkMRMLMarkupsLineNode", "Route endpoints")
        for obj in (segment.GetSegmentation(), volume, seeds):
            event = slicer.vtkSegmentation.SegmentModified if obj == segment.GetSegmentation() else vtk.vtkCommand.ModifiedEvent
            self.observers.append((obj, obj.AddObserver(event, self.inputsChanged)))
        for event in (slicer.vtkMRMLMarkupsNode.PointModifiedEvent,
                      slicer.vtkMRMLMarkupsNode.PointRemovedEvent,
                      slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent,
                      slicer.vtkMRMLMarkupsNode.PointPositionUndefinedEvent):
            self.observers.append((seeds, seeds.AddObserver(event, self.inputsChanged)))
        self.observers.append((segment.GetSegmentation(), segment.GetSegmentation().AddObserver(
            slicer.vtkSegmentation.SegmentRemoved, self.inputsChanged)))
        for obj in (segment, volume):
            self.observers.append((obj, obj.AddObserver(
                slicer.vtkMRMLTransformableNode.TransformModifiedEvent, self.inputsChanged)))
        self.status.text = "Review the lumen segment, place two endpoints, then compute."
        self.restoreResult()
        self.updateRouteStatus()

    def selectSeedClass(self, role):
        if not self.parameter or (self.worker and self.worker.is_alive()):
            return
        segment = self.parameter.GetNodeReference("segmentation")
        classes, created = ensure_seed_segments(segment.GetSegmentation(), self.mode)
        for key, name, color, enabled, guidance in PRESETS[self.mode]:
            if key in created:
                segment.GetDisplayNode().SetSegmentVisibility(classes[key], enabled)
            if key == role:
                self.status.text = guidance
        segment.GetDisplayNode().SetSegmentVisibility(classes[role], True)
        self.editor.setCurrentSegmentID(classes[role])
        self.editor.setActiveEffectByName("Paint")

    def startSeedGrow(self):
        if not self.parameter or (self.worker and self.worker.is_alive()):
            return
        self.editor.setActiveEffectByName("Grow from seeds")
        self.status.text = "Paint every visible seed class first (at least two). Hide unused classes with the eye icon. Initialize the preview, correct seeds, then Apply. After erasing seeds, Cancel and initialize again. No result is applied automatically."

    def node(self, role, kind, name):
        node = self.parameter.GetNodeReference(role)
        if node is None:
            node = slicer.mrmlScene.AddNewNodeByClass(kind, name)
            self.parameter.SetNodeReferenceID(role, node.GetID())
        return node

    def clearObservers(self):
        for obj, tag in self.observers:
            obj.RemoveObserver(tag)
        self.observers = []

    def inputsChanged(self, caller=None, event=None):
        if self.publishing:
            return
        self.invalidate()
        if self.parameter:
            self.parameter.SetParameter("resultValid", "false")
        self.status.text = "Input changed. Recompute the route before navigating."
        self.updateRouteStatus()

    def updateRouteStatus(self):
        seeds = self.parameter.GetNodeReference("seeds") if self.parameter else None
        count = seeds.GetNumberOfDefinedControlPoints() if seeds else 0
        self.routeStatus.text = (f"Route endpoints: {count} / 2. "
                                 + ("Ready to compute." if count == 2 else
                                    "Use Place start and destination; general fiducials are not route endpoints."))

    def invalidate(self):
        self.cancel.set()
        self.generation += 1
        self.restoreOverview()
        self.result = None
        if self.parameter:
            for role in ("surface", "path"):
                node = self.parameter.GetNodeReference(role)
                if node and node.GetDisplayNode():
                    node.GetDisplayNode().SetVisibility(False)
        if hasattr(self, "position"):
            self.position.setRange(0, 0)
            self.measurement.text = "No current route"

    def placeEndpoints(self):
        if not self.parameter:
            return
        seeds = self.parameter.GetNodeReference("seeds")
        self.editor.setActiveEffectByName("")
        seeds.RemoveAllControlPoints()
        seeds.CreateDefaultDisplayNodes()
        slicer.modules.markups.logic().SetActiveListID(seeds)
        # StartPlaceMode forcibly selects FiducialNode, losing the owned line.
        application = slicer.app.applicationLogic()
        selection = application.GetSelectionNode()
        selection.SetReferenceActivePlaceNodeClassName(seeds.GetClassName())
        selection.SetActivePlaceNodeID(seeds.GetID())
        interaction = application.GetInteractionNode()
        interaction.SetPlaceModePersistence(1)
        interaction.SetCurrentInteractionMode(interaction.Place)
        self.updateRouteStatus()
        self.status.text = "Place start first, then destination, within the ends of the chosen lumen."

    def run(self):
        if self.worker and self.worker.is_alive():
            self.status.text = "Wait for the cancelled computation to finish before starting another."
            return
        if not self.parameter:
            return
        try:
            segment = self.editor.segmentationNode()
            segmentID = lumen_segment_id(segment.GetSegmentation(), self.mode) if segment else None
            if segment is None or segment != self.parameter.GetNodeReference("segmentation") or not segmentID:
                raise ValueError("Use this workspace's lumen segment")
            if segment.GetParentTransformNode():
                raise ValueError("Harden the segmentation transform first")
            representation = segment.GetSegmentation().GetSegment(segmentID).GetRepresentation("Binary labelmap")
            if representation is None:
                raise ValueError("Create a binary lumen segment before computing")
            # A detached snapshot is the only object transferred out of the scene.
            internal = slicer.util.arrayFromSegmentInternalBinaryLabelmap(segment, segmentID)
            # Shared labelmaps may contain several segments with distinct labels.
            label = segment.GetSegmentation().GetSegment(segmentID).GetLabelValue()
            matrix = vtk.vtkMatrix4x4()
            representation.GetImageToWorldMatrix(matrix)
            mask, affine = segment_snapshot(internal, label, slicer.util.arrayFromVTKMatrix(matrix), representation.GetExtent())
            curve = self.manual.currentNode()
            manual = None
            if curve:
                if curve.GetParentTransformNode():
                    raise ValueError("Harden the manual route transform first")
                manual = np.array(slicer.util.arrayFromMarkupsCurvePoints(curve, world=True), copy=True)
                self.observers.append((curve, curve.AddObserver(
                    slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.inputsChanged)))
            seeds = self.parameter.GetNodeReference("seeds")
            endpoints = np.array(slicer.util.arrayFromMarkupsControlPoints(seeds, world=True), copy=True)
            if manual is None and (len(endpoints) != 2 or seeds.GetNumberOfDefinedControlPoints() != 2):
                raise ValueError("Place exactly two endpoints, or select a reviewed manual curve")
            self.invalidate()
            self.parameter.SetParameter("resultValid", "false")
            self.parameter.SetParameter("segmentID", segmentID)
            self.cancel = threading.Event()
            generation = self.generation
            cancel = self.cancel
            results = self.results
            self.compute.enabled = False
            self.source.enabled = False
            self.editor.enabled = False
            self.place.enabled = False
            self.manual.enabled = False
            self.cancelButton.enabled = True
            self.status.text = "Computing a detached lumen snapshot. You can cancel this job."
            self.computeStatus.text = self.status.text
            python = Path(slicer.app.slicerHome) / "python-install/bin/python.exe"
            if not python.is_file():
                raise RuntimeError("The Advanced Analysis Python worker is missing")
            def execute():
                try:
                    from .process import run_isolated
                    result = run_isolated(python, mask, affine, endpoints, manual, cancel)
                    results.put((generation, result, None))
                except Exception as exc:
                    results.put((generation, None, str(exc)))
            self.worker = threading.Thread(target=execute, name="Lumen-" + self.mode, daemon=True)
            self.worker.start()
            self.pollTimer.start()
        except Exception as exc:
            self.compute.enabled = True
            self.source.enabled = True
            self.editor.enabled = True
            self.place.enabled = True
            self.manual.enabled = True
            self.cancelButton.enabled = False
            self.status.text = str(exc)
            self.computeStatus.text = self.status.text

    def cancelJob(self):
        self.cancel.set()
        self.generation += 1
        self.status.text = "Cancelling; the current native step may need to finish."

    def poll(self):
        try:
            generation, result, error = self.results.get_nowait()
        except queue.Empty:
            return
        self.pollTimer.stop()
        self.compute.enabled = True
        self.source.enabled = True
        self.editor.enabled = True
        self.place.enabled = True
        self.manual.enabled = True
        self.cancelButton.enabled = False
        if generation != self.generation or self.cancel.is_set() or not self.parameter:
            self.status.text = "Computation discarded; no result was applied."
            self.computeStatus.text = self.status.text
            return
        if error:
            self.status.text = error
            self.computeStatus.text = self.status.text
            return
        try:
            self.publishing = True
            self.publish(result)
            self.computeStatus.text = "Route ready. Move Position or press Play to enter the airway." if self.mode == "bronchoscopy" else "Route ready. Move Position to review sections."
        except Exception as exc:
            self.invalidate()
            self.parameter.SetParameter("resultValid", "false")
            self.status.text = "Could not display result: " + str(exc)
            self.computeStatus.text = self.status.text
        finally:
            self.publishing = False

    def publish(self, result):
        self.result = result
        model = self.node("surface", "vtkMRMLModelNode", "Reviewed lumen surface")
        model.SetAndObservePolyData(result["surface"])
        model.CreateDefaultDisplayNodes()
        model.GetDisplayNode().SetBackfaceCulling(False)
        model.GetDisplayNode().SetFrontfaceCulling(False)
        model.GetDisplayNode().SetColor(0.9, 0.68, 0.55)
        model.GetDisplayNode().SetAmbient(0.3)
        model.GetDisplayNode().SetDiffuse(0.7)
        model.GetDisplayNode().SetSpecular(0.15)
        model.GetDisplayNode().SetPower(20)
        if self.mode == "bronchoscopy":
            configure_lumen_display(model.GetDisplayNode(), self.wallBrightness.value)
        model.GetDisplayNode().SetVisibility(True)
        path = self.node("path", "vtkMRMLMarkupsCurveNode", "Reviewed lumen route")
        path.SetCurveTypeToLinear()
        path.SetLocked(True)
        slicer.util.updateMarkupsControlPointsFromArray(path, result["points"])
        path.GetDisplayNode().SetVisibility(True)
        table = self.node("measurements", "vtkMRMLTableNode", "Lumen sections")
        table.RemoveAllColumns()
        for name, data in [("Distance_mm", result["distance"]), ("Area_mm2", result["area"]),
                           ("EquivalentDiameter_mm", result["diameter"])]:
            column = vtk.vtkDoubleArray()
            column.SetName(name)
            for value in data:
                column.InsertNextValue(float(value))
            table.AddColumn(column)
        self.parameter.SetParameter("resultValid", "true")
        self.parameter.SetParameter("referenceIndex", "")
        self.position.setRange(0, len(result["points"]) - 1)
        self.parameter.GetNodeReference("segmentation").GetDisplayNode().SetVisibility3D(False)
        layout = slicer.vtkMRMLLayoutNode.SlicerLayoutDual3DView if self.mode == "bronchoscopy" else slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView
        slicer.app.layoutManager().setLayout(layout)
        slicer.util.setSliceViewerLayers(background=self.parameter.GetNodeReference("source"))
        slicer.util.resetThreeDViews()
        if self.mode == "bronchoscopy":
            view = slicer.app.layoutManager().threeDWidget(1).mrmlViewNode()
            path.GetDisplayNode().RemoveAllViewNodeIDs()
            path.GetDisplayNode().AddViewNodeID(view.GetID())
        self.navigate(0)
        self.segmentPanel.collapsed = True
        self.status.text = "Route ready. Invalid/open sections are reported as unavailable. Save the scene to retain results."

    def restoreResult(self):
        if self.parameter.GetParameter("resultValid") != "true":
            return
        path = self.parameter.GetNodeReference("path")
        table = self.parameter.GetNodeReference("measurements")
        model = self.parameter.GetNodeReference("surface")
        if not path or not table or not model:
            return
        points = np.array(slicer.util.arrayFromMarkupsControlPoints(path, world=True), copy=True)
        if len(points) < 2 or table.GetNumberOfRows() != len(points):
            return
        tangents, ups = path_frames(points)
        data = {"points": points, "surface": model.GetPolyData(), "tangents": tangents, "ups": ups}
        for key, column in (("distance", "Distance_mm"), ("area", "Area_mm2"), ("diameter", "EquivalentDiameter_mm")):
            data[key] = np.array(slicer.util.arrayFromTableColumn(table, column), copy=True)
        if self.mode == "bronchoscopy":
            configure_lumen_display(model.GetDisplayNode(), self.wallBrightness.value)
        self.result = data
        self.position.setRange(0, len(points) - 1)

    def updateWallBrightness(self, value):
        if self.parameter and self.result is not None:
            model = self.parameter.GetNodeReference("surface")
            if model and model.GetDisplayNode():
                configure_lumen_display(model.GetDisplayNode(), value)
                lm = slicer.app.layoutManager()
                for index in range(lm.threeDViewCount):
                    lm.threeDWidget(index).threeDView().scheduleRender()

    def navigate(self, index):
        if self.result is None:
            return
        index = int(index)
        result = self.result
        point, tangent, up = result["points"][index], result["tangents"][index], result["ups"][index]
        area, diameter = result["area"][index], result["diameter"][index]
        station = result["distance"][index]
        self.measurement.text = (f"Position: {station:.1f} / {result['distance'][-1]:.1f} mm\n"
                                 + (f"Area: {area:.2f} mm2 | Equivalent diameter: {diameter:.2f} mm" if np.isfinite(area) else "Section unavailable: review the path and lumen"))
        lm = slicer.app.layoutManager()
        for name in lm.sliceViewNames():
            node = lm.sliceWidget(name).mrmlSliceNode()
            if self.mode == "vascular" and name == "Red":
                node.SetSliceToRASByNTP(*tangent, *np.cross(up, tangent), *point, 0)
            else:
                node.JumpSliceByCentering(*point)
        if self.mode == "bronchoscopy" and lm.threeDViewCount:
            cameraNode = slicer.modules.cameras.logic().GetViewActiveCameraNode(lm.threeDWidget(0).mrmlViewNode())
            camera = cameraNode.GetCamera()
            renderers = lm.threeDWidget(0).threeDView().renderWindow().GetRenderers()
            renderer = next((renderers.GetItemAsObject(i) for i in range(renderers.GetNumberOfItems())
                             if renderers.GetItemAsObject(i).GetActiveCamera() == camera), None)
            if renderer is None:
                self.computeStatus.text = "The fly-through camera is not attached to a visible renderer. Restore the analysis layout."
                return
            if self.flyLight is not None and self.flyLight.renderer != renderer:
                self.flyLight.restore()
                self.flyLight = None
            if self.flyLight is None:
                self.flyLight = FlyThroughLight(renderer)
            if self.camera_backup is None:
                saved = vtk.vtkCamera()
                saved.DeepCopy(camera)
                self.camera_backup = (cameraNode.GetID(), saved)
            direction = -tangent if self.reverse.checked else tangent
            camera.SetPosition(point)
            camera.SetFocalPoint(point + direction * 5)
            camera.SetViewUp(up)
            camera.SetParallelProjection(False)
            camera.SetViewAngle(self.angle.value)
            camera.SetClippingRange(0.05, 1000)
            lm.threeDWidget(0).threeDView().scheduleRender()
        if self.mode == "vascular":
            reference = self.parameter.GetParameter("referenceIndex")
            if reference:
                ref = result["diameter"][int(reference)]
                self.stenosis.text = (f"Equivalent-diameter reduction vs reference: {diameter_stenosis(diameter, ref):.1f}%\nUser-selected reference; not an automatic NASCET assessment."
                                      if np.isfinite(diameter) and ref > 0 else "Measurement unavailable at this section")

    def setReference(self):
        if self.result is not None:
            index = int(self.position.value)
            diameter = self.result["diameter"][index]
            if not np.isfinite(diameter) or diameter <= 0:
                self.status.text = "Select a valid reference section."
                return
            self.parameter.SetParameter("referenceIndex", str(index))
            self.navigate(index)

    def togglePlay(self):
        if self.result is None:
            return
        self.playing = not self.playing
        if self.playing:
            self.lastTick = time.monotonic()
            self.travel = float(self.result["distance"][int(self.position.value)])
            self.playTimer.start()
        else:
            self.playTimer.stop()

    def tick(self):
        if self.result is None or not self.playing:
            self.playTimer.stop()
            return
        now = time.monotonic()
        self.travel += (now - self.lastTick) * self.speed.value * (-1 if self.reverse.checked else 1)
        self.lastTick = now
        distances = self.result["distance"]
        index = int(np.argmin(abs(distances - self.travel)))
        self.position.setValue(index)
        if self.travel <= 0 or self.travel >= distances[-1]:
            self.playing = False
            self.playTimer.stop()

    def restoreOverview(self):
        self.playing = False
        if self.flyLight is not None:
            self.flyLight.restore()
            self.flyLight = None
        if hasattr(self, "playTimer"):
            self.playTimer.stop()
        if self.camera_backup:
            node = slicer.mrmlScene.GetNodeByID(self.camera_backup[0])
            if node:
                node.GetCamera().DeepCopy(self.camera_backup[1])
            self.camera_backup = None

    def enter(self):
        if self.parameter and self.parameter.GetScene():
            self.restoreResult()
            if self.result is not None:
                for role in ("surface", "path"):
                    node = self.parameter.GetNodeReference(role)
                    if node and node.GetDisplayNode():
                        node.GetDisplayNode().SetVisibility(True)

    def exit(self):
        self.restoreOverview()
        if self.worker and self.worker.is_alive():
            self.cancelJob()

    def sceneClosing(self, caller=None, event=None):
        self.invalidate()
        self.clearObservers()
        self.parameter = None
        self.editor.setMRMLSegmentEditorNode(None)

    def cleanup(self):
        self.invalidate()
        self.pollTimer.stop()
        self.clearObservers()
        slicer.mrmlScene.RemoveObserver(self.closeObserver)
