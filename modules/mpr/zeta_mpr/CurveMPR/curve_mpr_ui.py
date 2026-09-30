import vtkmodules.all as vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QDoubleSpinBox, QStackedWidget
from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, Slot, QTimer, QEvent
import threading
import logging
import numpy as np
from .curve_mpr_core import CurveMPRCore


class _ResultSignals(QObject):
    finished = Signal(int, object, object)


class _Reconstruction(QRunnable):
    """Own filters on a worker; never access a QWidget or renderer here."""
    def __init__(self, revision, volume, points, straighten=False, physical_width=40.0, reference_normal=None,
                 angle_degrees=0, rebuild_volume=True, include_mip=True):
        super().__init__()
        self.revision, self.volume, self.points = revision, volume, points
        self.straighten, self.physical_width = straighten, physical_width
        self.reference_normal = reference_normal
        self.angle_degrees = float(angle_degrees) % 360
        self.rebuild_volume = rebuild_volume
        self.include_mip = include_mip
        self.cancelled = threading.Event()
        self.signals = _ResultSignals()

    def run(self):
        result, error = None, None
        try:
            volume = vtk.vtkImageData()
            volume.ShallowCopy(self.volume)
            core = CurveMPRCore(volume, reference_normal=self.reference_normal)
            core.control_points = self.points
            core._update_spline()
            if not self.cancelled.is_set():
                curved = core.generate_curved_image(physical_width=self.physical_width, angle_degrees=self.angle_degrees)
                if not self.cancelled.is_set():
                    ortho = core.generate_curved_image(physical_width=self.physical_width, angle_degrees=(self.angle_degrees+90)%360)
                    mip = (core.generate_mip_image(physical_width=self.physical_width, cancelled=self.cancelled,
                                                   angle_degrees=self.angle_degrees) if self.include_mip else None)
                    straightened = (core.generate_straightened_volume(
                        physical_width=self.physical_width, cancelled=self.cancelled)
                        if self.rebuild_volume and self.straighten and not self.cancelled.is_set() else None)
                    local = (core.generate_path_volume(self.physical_width, self.cancelled)
                             if self.rebuild_volume and not self.straighten else None)
                    result = (curved, ortho, mip, straightened, local, core.tube_mask)
        except Exception as exc:
            # Do not expose volume metadata or exception payloads to the UI/log.
            error = type(exc).__name__
        finally:
            self.signals.finished.emit(self.revision, result, error)

class CurveMPRWidget(QWidget):
    def __init__(self, vtk_image_data: vtk.vtkImageData, main_viewer=None, parent=None):
        super().__init__(parent)
        self.vtk_image_data = vtk_image_data
        self.main_viewer = main_viewer
        self.core = CurveMPRCore(vtk_image_data)
        self._revision = 0
        self._job = None
        self._pending = False
        self._closed = False
        self._source_view = 'axial'
        self._source_helpers = []
        self._image_rotations = {'curved': 0, 'ortho': 0}
        self._orbit_angle = 0.0
        self._pane_titles = {}
        self._volume_mode = 'Path VRT'
        self._straightened_volume = None
        self._path_volume = None
        self._volume_mask = None
        
        # Visuals for main viewer
        self.points_actor = vtk.vtkActor()
        self.spline_actor = vtk.vtkActor()
        self._setup_main_viewer_visuals()
        
        self._setup_ui()
        self._setup_vtk()
        if hasattr(self, 'volume_mode'):
            self.volume_mode.currentTextChanged.connect(self._set_volume_mode)
            self.volume_preset.currentIndexChanged.connect(self._apply_volume_preset)
            self.volume_width.valueChanged.connect(self._volume_width_changed)
            self._apply_volume_preset()
            self._show_volume()
            self.source_plane.currentTextChanged.connect(self._set_source_view)
            self.orbit_angle.valueChanged.connect(self._set_orbit_angle)
            self.vtkWidget_curved.installEventFilter(self)
            self.vtkWidget_ortho.installEventFilter(self)
        
    def _setup_main_viewer_visuals(self):
        if not self.main_viewer:
            return
            
        # Points
        self.points_polydata = vtk.vtkPolyData()
        self.points_mapper = vtk.vtkPolyDataMapper()
        self.points_mapper.SetInputData(self.points_polydata)
        self.points_actor.SetMapper(self.points_mapper)
        self.points_actor.GetProperty().SetColor(1.0, 0.0, 0.0)
        self.points_actor.GetProperty().SetPointSize(5)
        
        # Spline
        self.spline_polydata = vtk.vtkPolyData()
        self.spline_mapper = vtk.vtkPolyDataMapper()
        self.spline_mapper.SetInputData(self.spline_polydata)
        self.spline_actor.SetMapper(self.spline_mapper)
        self.spline_actor.GetProperty().SetColor(0.0, 1.0, 0.0)
        self.spline_actor.GetProperty().SetLineWidth(2)
        
        # Add to the selected source renderer
        if hasattr(self.main_viewer, 'viewers') and self._source_view in self.main_viewer.viewers:
            self.main_viewer.viewers[self._source_view]['renderer'].AddActor(self.points_actor)
            self.main_viewer.viewers[self._source_view]['renderer'].AddActor(self.spline_actor)
            
    def _update_main_viewer_visuals(self):
        if not self.main_viewer:
            return
            
        # Update points
        points = vtk.vtkPoints()
        vertices = vtk.vtkCellArray()
        for p in self.core.control_points:
            id = points.InsertNextPoint(p[0], p[1], p[2])
            vertices.InsertNextCell(1)
            vertices.InsertCellPoint(id)
            
        self.points_polydata.SetPoints(points)
        self.points_polydata.SetVerts(vertices)
        
        # Update spline
        spline_points = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        if len(self.core.spline_points) > 1:
            lines.InsertNextCell(len(self.core.spline_points))
            for p in self.core.spline_points:
                id = spline_points.InsertNextPoint(p[0], p[1], p[2])
                lines.InsertCellPoint(id)
                
        self.spline_polydata.SetPoints(spline_points)
        self.spline_polydata.SetLines(lines)
        
        if hasattr(self.main_viewer, 'viewers') and self._source_view in self.main_viewer.viewers:
            self.main_viewer.viewers[self._source_view]['widget'].GetRenderWindow().Render()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Top controls
        controls_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Points")
        self.btn_clear.clicked.connect(self.clear_points)
        controls_layout.addWidget(self.btn_clear)
        
        self.lbl_info = QLabel("Click points in Axial view to define curve.")
        controls_layout.addWidget(self.lbl_info)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)

        self.volume_controls = QWidget(self)
        volume_container = QVBoxLayout(self.volume_controls)
        volume_container.setContentsMargins(0, 0, 0, 0)
        volume_layout = QHBoxLayout()
        volume_container.addLayout(volume_layout)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.addWidget(QLabel('Draw on:'))
        self.source_plane = QComboBox()
        self.source_plane.addItems(['Axial', 'Sagittal', 'Coronal'])
        self.source_plane.setToolTip('Changing the drawing plane clears the current path.')
        volume_layout.addWidget(self.source_plane)
        volume_layout.addWidget(QLabel('3D / projection:'))
        self.volume_mode = QComboBox()
        self.volume_mode.addItems(['Path VRT', 'Straightened VRT', 'Curved MIP'])
        volume_layout.addWidget(self.volume_mode)
        self.volume_preset = QComboBox()
        for label, preset in [('Vessels', 'CT-Vessels-Red'), ('Coronary', 'CT-Coronary'),
                              ('Bone', 'CT-Bone'), ('Soft tissue', 'CT-Soft-Tissue'),
                              ('Airway', 'CT-Lung-Airways'),
                              ('MR Angiography', 'MRI-MRA')]:
            self.volume_preset.addItem(label, preset)
        self.volume_preset.setToolTip('Rendering appearance; does not segment or isolate vessels.')
        volume_layout.addWidget(self.volume_preset)
        volume_layout = QHBoxLayout()
        volume_container.addLayout(volume_layout)
        volume_layout.addWidget(QLabel('Tube diameter:'))
        self.volume_width = QDoubleSpinBox()
        self.volume_width.setRange(5, 100)
        self.volume_width.setValue(40)
        self.volume_width.setSuffix(' mm')
        self.volume_width.setKeyboardTracking(False)
        self.volume_width.setEnabled(False)
        volume_layout.addWidget(self.volume_width)
        volume_layout.addWidget(QLabel('Around path:'))
        self.orbit_angle = QDoubleSpinBox()
        self.orbit_angle.setRange(0, 359.9)
        self.orbit_angle.setWrapping(True)
        self.orbit_angle.setSingleStep(5)
        self.orbit_angle.setSuffix(' deg')
        self.orbit_angle.setKeyboardTracking(False)
        self.orbit_angle.setToolTip('Scroll either CPR image to rotate both sampling planes around the path.')
        volume_layout.addWidget(self.orbit_angle)
        self.volume_note = QLabel('Draw a path to reconstruct')
        volume_layout.addWidget(self.volume_note)
        volume_layout.addStretch()
        layout.addWidget(self.volume_controls)
        
        # Viewers
        viewers_layout = QHBoxLayout()
        
        # Curved MPR Viewer
        self.vtkWidget_curved = QVTKRenderWindowInteractor(self)
        self.pane_curved = self._image_pane('curved', 'CPR 0 degrees', self.vtkWidget_curved)
        viewers_layout.addWidget(self.pane_curved, stretch=2)
        
        # Orthogonal Viewer
        self.vtkWidget_ortho = QVTKRenderWindowInteractor(self)
        self.pane_ortho = self._image_pane('ortho', 'CPR 90 degrees', self.vtkWidget_ortho)
        viewers_layout.addWidget(self.pane_ortho, stretch=1)
        
        # MIP Viewer
        self.vtkWidget_mip = QVTKRenderWindowInteractor(self)
        viewers_layout.addWidget(self.vtkWidget_mip, stretch=1)
        
        layout.addLayout(viewers_layout)

    def _image_pane(self, name, title, widget):
        pane = QWidget(self)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        label = QLabel(title)
        self._pane_titles[name] = label
        row.addWidget(label)
        row.addStretch()
        row.addWidget(QLabel('Image roll:'))
        spin = QDoubleSpinBox()
        spin.setRange(-180, 180)
        spin.setSingleStep(90)
        spin.setSuffix(' deg')
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(lambda angle: self._rotate_image(name, angle))
        row.addWidget(spin)
        layout.addLayout(row)
        layout.addWidget(widget)
        return pane

    def _rotate_image(self, name, angle):
        self._image_rotations[name] = angle
        if not self._closed:
            self._fit_image(name)

    def _fit_image(self, name):
        actor = getattr(self, 'image_actor_' + name)
        renderer = getattr(self, 'ren_' + name)
        # Headless controller doubles do not own cameras.
        if hasattr(actor, 'GetInput') and actor.GetInput() is not None:
            camera = renderer.GetActiveCamera()
            center = actor.GetInput().GetCenter()
            camera.SetFocalPoint(center)
            camera.SetPosition(center[0], center[1], center[2] + 1000)
            camera.SetViewUp(-1, 0, 0)  # Arc length runs top-to-bottom by default.
            camera.ParallelProjectionOn()
            camera.Roll(self._image_rotations.get(name, 0))
        renderer.ResetCamera()
        getattr(self, 'vtkWidget_' + name).GetRenderWindow().Render()

    def install_source_views(self):
        """Reuse Standard MPR's canonical panes; only the selected one is visible."""
        from .curve_mpr_interactor import CurveMPRInteractorStyle
        self.source_stack = QStackedWidget(self.main_viewer)
        for name in ('axial', 'sagittal', 'coronal'):
            container = self.main_viewer._view_containers[name]
            self.main_viewer._views_layout.removeWidget(container)
            self.source_stack.addWidget(container)
            self.main_viewer.viewers[name]['widget'].installEventFilter(self)
            helper = CurveMPRInteractorStyle(self.main_viewer, self, view_name=name)
            helper.attach(self.main_viewer.viewers[name]['widget'].GetInteractorStyle())
            self._source_helpers.append(helper)
        self.main_viewer._views_layout.addWidget(self.source_stack, 0, 0)
        self._set_source_view('Axial')

    def eventFilter(self, obj, event):
        if obj is getattr(self, 'vtkWidget_mip', None) and self._volume_mode != 'Curved MIP':
            if self._volume_mouse_event(event):
                return True
        if event.type() == QEvent.Wheel and (obj is getattr(self, 'vtkWidget_curved', None)
                                            or obj is getattr(self, 'vtkWidget_ortho', None)):
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self._set_orbit_angle(self._orbit_angle + (5 if delta > 0 else -5))
            return True  # Do not also invoke VTK's wheel zoom.
        # Standard MPR's expand handler assumes its original grid. A CPR source
        # pane belongs to a stack; double-click must not reparent it out of that stack.
        if event.type() == QEvent.MouseButtonDblClick:
            return True
        return super().eventFilter(obj, event)

    def _volume_mouse_event(self, event):
        """Route Qt events explicitly to the same Python style as Standard MPR."""
        kind = event.type()
        if self._closed:
            return True
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                        QEvent.MouseMove, QEvent.Wheel):
            return False
        style = self.volume_style
        interactor = self.vtkWidget_mip.GetRenderWindow().GetInteractor()
        point = event.position()
        interactor.SetEventInformation(int(point.x()), self.vtkWidget_mip.height()-1-int(point.y()),
                                      int(bool(event.modifiers() & Qt.ControlModifier)),
                                      int(bool(event.modifiers() & Qt.ShiftModifier)))
        style.SetCurrentRenderer(self.ren_mip)
        if kind == QEvent.MouseMove:
            style.OnMouseMove()
        elif kind == QEvent.Wheel:
            # Parallel cameras zoom by scale; Dolly alone changes only distance.
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                camera = self.ren_mip.GetActiveCamera()
                camera.Zoom(1.1 if delta > 0 else 1/1.1)
                self.ren_mip.ResetCameraClippingRange()
                self._volume_quality()
        else:
            button = {Qt.LeftButton: 'Left', Qt.RightButton: 'Right', Qt.MiddleButton: 'Middle'}.get(event.button())
            if button is None:
                return False
            down = kind == QEvent.MouseButtonPress
            if down:
                self._volume_quality(True)
            getattr(style, 'On' + button + 'Button' + ('Down' if down else 'Up'))()
            if not down:
                self._volume_quality(False)
        return True

    def _set_active_view(self, _name):
        # Required by Standard MPR's style; this widget owns only one VRT pane.
        pass

    def _capture_vrt_baseline(self):
        from ..mpr_viewer._mpr_vrt import _MprVrtMixin
        _MprVrtMixin._capture_vrt_baseline(self._vrt_controls)

    def _apply_vrt_appearance_delta(self, dx, dy):
        from ..mpr_viewer._mpr_vrt import _MprVrtMixin
        _MprVrtMixin._apply_vrt_appearance_delta(self._vrt_controls, dx, dy)

    def _reset_vrt_rmb_state(self):
        self._vrt_controls._vrt_mouse_state.clear()

    def _show_vrt_preset_menu_from_interactor(self, _widget):
        self.volume_preset.showPopup()

    def _set_orbit_angle(self, angle):
        if self._closed:
            return
        self._orbit_angle = float(angle) % 360
        if hasattr(self, 'orbit_angle'):
            self.orbit_angle.blockSignals(True)
            self.orbit_angle.setValue(self._orbit_angle)
            self.orbit_angle.blockSignals(False)
        self.update_views(orbit_only=True)

    def _set_source_view(self, name):
        if self._closed or not hasattr(self, 'source_stack'):
            return
        name = name.lower()
        old = self.main_viewer.viewers[self._source_view]['renderer']
        for actor in (self.points_actor, self.spline_actor):
            old.RemoveActor(actor)
        self._source_view = name
        self.source_stack.setCurrentIndex(('axial', 'sagittal', 'coronal').index(name))
        target = self.main_viewer.viewers[name]['renderer']
        for actor in (self.points_actor, self.spline_actor):
            target.AddActor(actor)
        self.clear_points()

    def _reference_normal(self):
        if self.main_viewer is not None:
            return tuple(self.main_viewer.viewers[self._source_view]['renderer'].GetActiveCamera().GetViewPlaneNormal())
        return {'axial': (0,0,1), 'sagittal': (1,0,0), 'coronal': (0,1,0)}[self._source_view]
        
    def _setup_vtk(self):
        # Curved MPR Renderer
        self.ren_curved = vtk.vtkRenderer()
        self.ren_curved.SetBackground(0.1, 0.1, 0.1)
        self.vtkWidget_curved.GetRenderWindow().AddRenderer(self.ren_curved)
        
        self.image_actor_curved = vtk.vtkImageActor()
        self.image_actor_curved.VisibilityOff()
        self.image_actor_curved.GetProperty().SetColorWindow(2000)
        self.image_actor_curved.GetProperty().SetColorLevel(500)
        self.ren_curved.AddActor(self.image_actor_curved)
        
        self.interactor_style_curved = vtk.vtkInteractorStyleImage()
        self.vtkWidget_curved.SetInteractorStyle(self.interactor_style_curved)
        
        # Orthogonal Renderer
        self.ren_ortho = vtk.vtkRenderer()
        self.ren_ortho.SetBackground(0.1, 0.1, 0.1)
        self.vtkWidget_ortho.GetRenderWindow().AddRenderer(self.ren_ortho)
        
        self.image_actor_ortho = vtk.vtkImageActor()
        self.image_actor_ortho.VisibilityOff()
        self.image_actor_ortho.GetProperty().SetColorWindow(2000)
        self.image_actor_ortho.GetProperty().SetColorLevel(500)
        self.ren_ortho.AddActor(self.image_actor_ortho)
        
        self.interactor_style_ortho = vtk.vtkInteractorStyleImage()
        self.vtkWidget_ortho.SetInteractorStyle(self.interactor_style_ortho)
        
        # MIP Renderer
        self.ren_mip = vtk.vtkRenderer()
        self.ren_mip.SetBackground(0.1, 0.1, 0.1)
        self.vtkWidget_mip.GetRenderWindow().AddRenderer(self.ren_mip)
        
        self.image_actor_mip = vtk.vtkImageActor()
        self.image_actor_mip.VisibilityOff()
        self.image_actor_mip.GetProperty().SetColorWindow(2000)
        self.image_actor_mip.GetProperty().SetColorLevel(500)
        self.ren_mip.AddActor(self.image_actor_mip)
        
        self.interactor_style_mip = vtk.vtkInteractorStyleImage()
        self.vtkWidget_mip.SetInteractorStyle(self.interactor_style_mip)
        
        self.vtkWidget_curved.Initialize()
        self.vtkWidget_ortho.Initialize()
        self.vtkWidget_mip.Initialize()

        # The fourth pane can display its existing MIP or a real 3D volume.
        self.volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        self.volume_mapper.SetBlendModeToComposite()
        self.volume_mapper.SetAutoAdjustSampleDistances(1)
        self.volume_mapper.SetImageSampleDistance(1)
        self.volume_mapper.SetMaxMemoryInBytes(max(512 * 1024**2,
                                                   int(self.vtk_image_data.GetActualMemorySize() * 1024 * 1.6)))
        self.volume_property = vtk.vtkVolumeProperty()
        self.volume_actor = vtk.vtkVolume()
        self.volume_actor.SetMapper(self.volume_mapper)
        self.volume_actor.SetProperty(self.volume_property)
        self.ren_mip.AddVolume(self.volume_actor)
        from types import SimpleNamespace
        from ..mpr_viewer._interactor_styles import VRTInteractorStyle
        self._vrt_controls = SimpleNamespace(
            viewers={'3d': {'property': self.volume_property, 'renderer': self.ren_mip}},
            _vrt_mouse_state={}, _capture_vrt_baseline=self._capture_vrt_baseline)
        self.volume_style = VRTInteractorStyle(self, self.vtkWidget_mip)
        self.volume_style.SetDefaultRenderer(self.ren_mip)
        self.volume_style.SetCurrentRenderer(self.ren_mip)
        self.vtkWidget_mip.installEventFilter(self)
        self.vtkWidget_mip.setToolTip('Left drag: rotate; right drag: appearance; middle drag / wheel: zoom; left + right: pan; right click: presets.')
        self.volume_style.AddObserver('StartInteractionEvent', lambda *_: self._volume_quality(True))
        self.volume_style.AddObserver('EndInteractionEvent', lambda *_: self._volume_quality(False))
        self._vrt_render_timer = QTimer(self)
        self._vrt_render_timer.setSingleShot(True)
        self._vrt_render_timer.timeout.connect(self._render_volume)

    def _render_volume(self):
        if not self._closed and not getattr(self.main_viewer, '_mpr_closed', False):
            self.vtkWidget_mip.GetRenderWindow().Render()

    def _volume_quality(self, interacting=False):
        if self._closed:
            return
        from ..mpr_viewer._mpr_vrt import configure_vrt_quality, DEFAULT_VRT_QUALITY
        image = self.volume_mapper.GetInput()
        if image is not None:
            configure_vrt_quality(self.volume_mapper, self.volume_property, image.GetSpacing(),
                                  DEFAULT_VRT_QUALITY, interacting,
                                  image.GetActualMemorySize() > 512 * 1024)
            self._vrt_render_timer.start(0)

    def _apply_volume_preset(self, *_):
        if self._closed:
            return
        from modules.viewer.advanced.vtk_3d_presets import apply_preset_to_volume_property
        from ..mpr_viewer._mpr_vrt import refine_vrt_property
        preset = self.volume_preset.currentData()
        apply_preset_to_volume_property(self.volume_property, preset)
        refine_vrt_property(self.volume_property, preset)
        self._volume_quality()

    def _show_volume(self):
        if not hasattr(self, 'volume_mapper') or self._closed:
            return
        is_mip = self._volume_mode == 'Curved MIP'
        image = self._path_volume if self._volume_mode == 'Path VRT' else self._straightened_volume
        previous = self.volume_mapper.GetInput()
        self.volume_mapper.SetMaskTypeToBinary()
        self.volume_mapper.SetMaskInput(self._volume_mask if image is not None else None)
        self.image_actor_mip.SetVisibility(is_mip and self.image_actor_mip.GetInput() is not None)
        self.volume_actor.SetVisibility(not is_mip and image is not None)
        self.vtkWidget_mip.SetInteractorStyle(self.interactor_style_mip if is_mip else self.volume_style)
        self.volume_preset.setEnabled(not is_mip)
        self.volume_width.setEnabled(True)
        if not is_mip:
            if image is None:
                self.volume_mapper.RemoveAllInputConnections(0)
            else:
                self.volume_mapper.SetInputData(image)
            if image is not None and image is not previous:
                self._orient_volume_view(image)
            self.volume_note.setText(('Tube around path' if self._volume_mode == 'Path VRT' else
                                      'Straightened tube') if image is not None else 'Draw a path to reconstruct')
            self._volume_quality()
        else:
            self.volume_note.setText('Curved maximum intensity projection')
            self.ren_mip.ResetCamera()
        self._vrt_render_timer.start(0)

    def _orient_volume_view(self, image):
        camera = self.ren_mip.GetActiveCamera()
        center = np.asarray(image.GetCenter())
        up, normal = np.array([-1.,0,0]), np.array([0.,0,1])
        if self._volume_mode == 'Path VRT' and len(self.core.control_points) > 1:
            up = self.core.control_points[0] - self.core.control_points[-1]
            if np.linalg.norm(up) < 1e-8:
                up = self.core.control_points[0] - self.core.control_points[1]
            up = up / max(np.linalg.norm(up), 1e-8)
            normal = np.asarray(self._reference_normal(), dtype=float)
            normal -= np.dot(normal, up) * up
            if np.linalg.norm(normal) < 1e-8:
                normal = np.cross(up, np.eye(3)[np.argmin(np.abs(up))])
            normal /= np.linalg.norm(normal)
        camera.SetFocalPoint(center)
        camera.SetPosition(center + 1000 * normal)
        camera.SetViewUp(up)
        camera.ParallelProjectionOn()
        self.ren_mip.ResetCamera()

    def _set_volume_mode(self, mode):
        if self._closed:
            return
        self._volume_mode = mode
        self._show_volume()
        # Revisions also protect mode changes during in-flight straightening.
        self.update_views()

    def _volume_width_changed(self, _value):
        if self._closed:
            return
        self._straightened_volume = None
        self._path_volume = None
        self._volume_mask = None
        self._show_volume()
        self.update_views()
        
    def add_point(self, point):
        if self._closed or getattr(self.main_viewer, '_mpr_closed', False):
            return
        if self.core.control_points and all(
                abs(a - b) < 1e-6 for a, b in zip(point, self.core.control_points[-1])):
            return
        self.core.add_control_point(point)
        self._straightened_volume = None
        self._path_volume = None
        self._volume_mask = None
        self._show_volume()
        self._update_main_viewer_visuals()
        self.update_views()
        
    def clear_points(self):
        self._revision += 1
        self._pending = False
        if self._job is not None:
            self._job.cancelled.set()
        self.core.clear_points()
        self._straightened_volume = None
        self._path_volume = None
        self._volume_mask = None
        self._show_volume()
        self._update_main_viewer_visuals()
        for name in ('curved', 'ortho', 'mip'):
            getattr(self, 'image_actor_' + name).SetVisibility(False)
        self.image_actor_curved.SetInputData(None)
        self.image_actor_ortho.SetInputData(None)
        self.image_actor_mip.SetInputData(None)
        self.vtkWidget_curved.GetRenderWindow().Render()
        self.vtkWidget_ortho.GetRenderWindow().Render()
        self.vtkWidget_mip.GetRenderWindow().Render()
        self.lbl_info.setText(f"Click points in {self._source_view.title()} view to define curve.")
        
    def update_views(self, orbit_only=False):
        if self._closed or len(self.core.control_points) < 2:
            return
        if not orbit_only:
            self._revision += 1
        self._pending = True
        self.lbl_info.setText("Reconstructing curve...")
        if self._job is not None:
            if not orbit_only:
                self._job.cancelled.set()
            return
        self._start_reconstruction()

    def _start_reconstruction(self):
        self._pending = False
        job = _Reconstruction(self._revision, self.vtk_image_data,
                              [p.copy() for p in self.core.control_points],
                              straighten=self._volume_mode == 'Straightened VRT',
                              physical_width=self.volume_width.value() if hasattr(self, 'volume_width') else 40,
                              reference_normal=self._reference_normal(), angle_degrees=self._orbit_angle,
                              include_mip=self._volume_mode == 'Curved MIP',
                              rebuild_volume=(self._straightened_volume is None if self._volume_mode == 'Straightened VRT'
                                              else self._path_volume is None))
        self._job = job
        job.signals.finished.connect(self._reconstruction_finished, Qt.QueuedConnection)
        # QObject destruction must cancel without retaining or touching the widget.
        self.destroyed.connect(job.cancelled.set)
        QThreadPool.globalInstance().start(job)

    @Slot(int, object, object)
    def _reconstruction_finished(self, revision, images, error):
        job, self._job = self._job, None
        if job is not None:
            self.destroyed.disconnect(job.cancelled.set)
        if self._closed or getattr(self.main_viewer, '_mpr_closed', False):
            return
        if revision == self._revision:
            if error:
                logging.getLogger(__name__).warning("[CURVE-MPR] reconstruction failed: %s", error)
                self.lbl_info.setText("Reconstruction failed. Clear points and try again.")
            elif images is not None:
                for name, image in zip(('curved', 'ortho', 'mip'), images):
                    if image is not None:
                        getattr(self, 'image_actor_' + name).SetInputData(image)
                        getattr(self, 'image_actor_' + name).SetVisibility(True)
                        if self.main_viewer is not None:
                            source_property = self.main_viewer.viewers[self._source_view]['actor'].GetProperty()
                            prop = getattr(self, 'image_actor_' + name).GetProperty()
                            prop.SetColorWindow(source_property.GetColorWindow())
                            prop.SetColorLevel(source_property.GetColorLevel())
                        if name != 'mip' or self._volume_mode == 'Curved MIP':
                            self._fit_image(name)
                if job is None or job.rebuild_volume:
                    self._straightened_volume = images[3] if len(images) > 3 else None
                    self._path_volume = images[4] if len(images) > 4 else None
                    self._volume_mask = images[5] if len(images) > 5 else None
                for name, offset in (('curved', 0), ('ortho', 90)):
                    if name in self._pane_titles:
                        angle = job.angle_degrees if job is not None else self._orbit_angle
                        self._pane_titles[name].setText(f'CPR {(angle+offset)%360:g} degrees')
                if job is None or job.rebuild_volume:
                    self._show_volume()
                self.lbl_info.setText("Curve reconstructed. Add points or clear to start again.")
        if self._pending:
            self._start_reconstruction()

    def cleanup(self):
        if self._closed:
            return
        self._closed = True
        self._pending = False
        self._revision += 1
        if self._job is not None:
            self._job.cancelled.set()
        if hasattr(self, '_vrt_render_timer'):
            self._vrt_render_timer.stop()
            self.volume_style.RemoveAllObservers()
            try:
                self.volume_actor.ReleaseGraphicsResources(self.vtkWidget_mip.GetRenderWindow())
            except RuntimeError:
                pass
            self.volume_mapper.RemoveAllInputConnections(0)
            self.volume_mapper.SetMaskInput(None)
        self._straightened_volume = None
        self._path_volume = None
        self._volume_mask = None
        helper = getattr(self, '_interactor_helper', None)
        if helper is not None and hasattr(helper, 'observer_id'):
            helper.interactor_style.RemoveObserver(helper.observer_id)
        self._interactor_helper = None
        for helper in self._source_helpers:
            helper.detach()
        self._source_helpers.clear()
        self.vtk_image_data = None
        self.core.vtk_image_data = None
        self.main_viewer = None
        for name in ('curved', 'ortho', 'mip'):
            widget = getattr(self, 'vtkWidget_' + name)
            if hasattr(widget, 'Finalize'):
                try:
                    widget.Finalize()
                except RuntimeError:
                    # Qt may already have deleted a reparented child.
                    pass

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
