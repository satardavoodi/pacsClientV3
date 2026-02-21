import vtkmodules.all as vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt
from .curve_mpr_core import CurveMPRCore

class CurveMPRWidget(QWidget):
    def __init__(self, vtk_image_data: vtk.vtkImageData, main_viewer=None, parent=None):
        super().__init__(parent)
        self.vtk_image_data = vtk_image_data
        self.main_viewer = main_viewer
        self.core = CurveMPRCore(vtk_image_data)
        
        # Visuals for main viewer
        self.points_actor = vtk.vtkActor()
        self.spline_actor = vtk.vtkActor()
        self._setup_main_viewer_visuals()
        
        self._setup_ui()
        self._setup_vtk()
        
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
        
        # Add to axial renderer
        if hasattr(self.main_viewer, 'viewers') and 'axial' in self.main_viewer.viewers:
            self.main_viewer.viewers['axial']['renderer'].AddActor(self.points_actor)
            self.main_viewer.viewers['axial']['renderer'].AddActor(self.spline_actor)
            
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
        
        if hasattr(self.main_viewer, 'viewers') and 'axial' in self.main_viewer.viewers:
            self.main_viewer.viewers['axial']['widget'].GetRenderWindow().Render()
        
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
        
        # Viewers
        viewers_layout = QHBoxLayout()
        
        # Curved MPR Viewer
        self.vtkWidget_curved = QVTKRenderWindowInteractor(self)
        viewers_layout.addWidget(self.vtkWidget_curved, stretch=2)
        
        # Orthogonal Viewer
        self.vtkWidget_ortho = QVTKRenderWindowInteractor(self)
        viewers_layout.addWidget(self.vtkWidget_ortho, stretch=1)
        
        # MIP Viewer
        self.vtkWidget_mip = QVTKRenderWindowInteractor(self)
        viewers_layout.addWidget(self.vtkWidget_mip, stretch=1)
        
        layout.addLayout(viewers_layout)
        
    def _setup_vtk(self):
        # Curved MPR Renderer
        self.ren_curved = vtk.vtkRenderer()
        self.ren_curved.SetBackground(0.1, 0.1, 0.1)
        self.vtkWidget_curved.GetRenderWindow().AddRenderer(self.ren_curved)
        
        self.image_actor_curved = vtk.vtkImageActor()
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
        self.image_actor_mip.GetProperty().SetColorWindow(2000)
        self.image_actor_mip.GetProperty().SetColorLevel(500)
        self.ren_mip.AddActor(self.image_actor_mip)
        
        self.interactor_style_mip = vtk.vtkInteractorStyleImage()
        self.vtkWidget_mip.SetInteractorStyle(self.interactor_style_mip)
        
        self.vtkWidget_curved.Initialize()
        self.vtkWidget_ortho.Initialize()
        self.vtkWidget_mip.Initialize()
        
    def add_point(self, point):
        self.core.add_control_point(point)
        self._update_main_viewer_visuals()
        self.update_views()
        
    def clear_points(self):
        self.core.clear_points()
        self._update_main_viewer_visuals()
        self.image_actor_curved.SetInputData(None)
        self.image_actor_ortho.SetInputData(None)
        self.image_actor_mip.SetInputData(None)
        self.vtkWidget_curved.GetRenderWindow().Render()
        self.vtkWidget_ortho.GetRenderWindow().Render()
        self.vtkWidget_mip.GetRenderWindow().Render()
        
    def update_views(self):
        if len(self.core.control_points) < 2:
            return
            
        # Generate curved image
        curved_img = self.core.generate_curved_image()
        if curved_img:
            self.image_actor_curved.SetInputData(curved_img)
            self.ren_curved.ResetCamera()
            self.vtkWidget_curved.GetRenderWindow().Render()
            
        # Generate orthogonal slice at the middle of the curve
        ortho_img = self.core.generate_orthogonal_slice(self.core.total_length / 2.0)
        if ortho_img:
            self.image_actor_ortho.SetInputData(ortho_img)
            self.ren_ortho.ResetCamera()
            self.vtkWidget_ortho.GetRenderWindow().Render()
            
        # Generate MIP image
        mip_img = self.core.generate_mip_image()
        if mip_img:
            self.image_actor_mip.SetInputData(mip_img)
            self.ren_mip.ResetCamera()
            self.vtkWidget_mip.GetRenderWindow().Render()
