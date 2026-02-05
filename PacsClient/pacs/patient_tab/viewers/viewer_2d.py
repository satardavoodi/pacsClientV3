from math import sqrt

import vtkmodules.all as vtk
from PySide6.QtCore import QTimer
from vtkmodules.util import numpy_support as vtknp
import enum
from PacsClient.pacs.patient_tab.utils import make_corner_actor, DicomTagsActors, read_segment_nifti, BoxManager
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider
from PySide6.QtCore import Qt
import time
from PacsClient.pacs.patient_tab.curved_mpr_module import CurvedMPRModule

# =====================================================
# ANTI-FLICKERING CONSTANTS
# =====================================================
_VIEWER_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_VIEWER_BATCH_DELAY_MS = 8  # Delay for batching multiple render requests


class ViewerType(enum.Enum):
    AXIAL = "Axial"
    SAGITTAL = "Sagittal"
    CORONAL = "Coronal"


class ImageReslice(vtk.vtkImageReslice):  # for set orientation and return image as 2D or 3D
    def __init__(self, vtk_image_data: vtk.vtkImageData, metadata):
        super().__init__()
        self.vtk_image_data = vtk_image_data
        self.metadata = metadata
        self.SetInputData(self.vtk_image_data)
        self.SetOutputDimensionality(3)  # output is 3d image
        # self.SetResliceAxesDirectionCosines(1, 0, 0, 0, -1, 0, 0, 0, 1)  # Roll 180 degrees (RAI)

        # self.apply_orientation()
        
        # ✅ BALANCED: Use CUBIC interpolation (good quality + reasonable speed)
        # Cubic is 3-5x faster than Sinc/Lanczos but maintains good visual quality
        self.SetInterpolationModeToCubic()  # Good balance between quality and speed
        
        # Speed optimizations
        self.OptimizationOn()  # Enable VTK optimizations
        self.SetAutoCropOutput(False)  # Disable auto-cropping for speed
        
        # ⚡ CRITICAL: Update is expensive, so ensure it's called only once
        self.Update()

    def apply_orientation(self):
        orientation = self.metadata['series']['orientation']
        # print('orientation:', orientation)
        pass


def flip_image_y(img):
    f = vtk.vtkImageFlip()
    f.SetInputData(img)
    f.SetFilteredAxis(1)  # 0=X, 1=Y, 2=Z
    f.Update()
    out = vtk.vtkImageData()
    out.DeepCopy(f.GetOutput())  # مستقل از فیلتر
    return out


def display_upsample_xy(vtk_img, factor=1.0):
    try:
        s = time.time()
        res = vtk.vtkImageResample()
        res.SetInputData(vtk_img)
        res.SetAxisMagnificationFactor(0, factor)  # X
        res.SetAxisMagnificationFactor(1, factor)  # Y
        res.SetAxisMagnificationFactor(2, 1.0)  # Z را دست نزن
        
        # ✅ BALANCED: Use Cubic interpolation (good quality + reasonable speed)
        res.SetInterpolationModeToCubic()
        res.Update()
        
        f = time.time()
        # print('end: ', f - s)
        return res.GetOutput()
    except:
        print('error')
        return vtk_img

def create_text_actor(world_position, text: str):
    text_source = vtk.vtkVectorText()
    text_source.SetText(text)

    # Extrude the text to make it 3D
    text_extrude = vtk.vtkLinearExtrusionFilter()
    text_extrude.SetInputConnection(text_source.GetOutputPort())
    text_extrude.SetExtrusionTypeToNormalExtrusion()
    text_extrude.SetVector(0, 0, 1)
    text_extrude.SetScaleFactor(1)

    # Mapper and actor
    text_mapper = vtk.vtkPolyDataMapper()
    text_mapper.SetInputConnection(text_extrude.GetOutputPort())

    text_actor = vtk.vtkFollower()
    text_actor.SetMapper(text_mapper)
    text_actor.SetScale(5, 5, 5)
    text_actor.SetPosition(world_position)
    text_actor.GetProperty().SetColor((1, 0, 0))
    return text_actor


class ImageViewer2D(vtk.vtkResliceImageViewer):
    def __init__(self, render_window, interactor, height, vtk_image_data: vtk.vtkImageData, metadata,
                 metadata_fixed, apply_default_filter, vtk_widget):
        super().__init__()
        self._overlays = []
        self.viewer_type = None
        self.apply_default_filter = apply_default_filter
        self.vtk_widget = vtk_widget
        self.viewer_height = height
        self.flag_set_custom_window_level = False
        # self.flag_flipped = False
        self.color_mapper = None
        self.skip_slices = 0  # this helper for CombineViewer

        # Curved MPR state
        self.curved_mpr_mode = False
        self.curved_mpr_points = []  # List of 3D points (x, y, z)
        self.curved_mpr_sphere_actors = []  # Visual spheres for points
        self.curved_mpr_line_actors = []  # Visual lines connecting points (legacy - individual segments)
        self.curved_mpr_observer_id = None  # Observer for click events
        
        # Curved MPR Module integration
        self.curved_mpr_module = CurvedMPRModule()
        self.curved_mpr_overlay_actor = None  # Text overlay for mode indication
        self.curved_mpr_centerline_actor = None  # Single polyline actor for the centerline

        self.dicom_tags_actors = DicomTagsActors()
        # self.last_index_slice_saved = None

        self.image_render_window: vtk.vtkRenderWindow = render_window
        self.image_interactor: vtk.vtkRenderWindowInteractor = interactor
        self.renderer: vtk.vtkRenderer = self.GetRenderer()

        self.vtk_image_data = vtk_image_data

        self.vtk_image_data = self._preprocess_vtk_image_data(self.vtk_image_data)
        # vtk_image_data = flip_image_y(vtk_image_data)
        # self.vtk_image_data = _display_upsample_xy(self.vtk_image_data)

        self.metadata = metadata
        self.metadata_fixed = metadata_fixed
        
        # Store image properties for curved MPR
        self.origin = self.vtk_image_data.GetOrigin()
        self.spacing = self.vtk_image_data.GetSpacing()

        # Performance optimization flags
        self._render_pending = False
        self._render_timer = None

        # self.run_test()
        self.SetRenderWindow(self.image_render_window)
        self.SetupInteractor(self.image_interactor)
        self.renderer.SetBackground(0, 0, 0)

        # Fast initialization without renders
        self.image_reslice = ImageReslice(self.vtk_image_data, self.metadata)
        self.SetInputData(self.image_reslice.GetOutput())  # without color map (window level)
        self.vtk_image_data = self.image_reslice.GetOutput()

        self.set_color_mapper()
        # self.apply_window_level()

        # Smooth zooming on the image actor
        self.GetImageActor().InterpolateOn()
        self.renderer.UseFXAAOn()

        self.UpdateDisplayExtent()
        self.Render()

        # self.last_index_slice_saved = self.get_count_of_slices() // 2

        '''
        AXIAL = "Axial"
        SAGITTAL = "Sagittal"
        CORONAL = "Coronal"
        '''
        # self.set_zoom_1to1()

        # self._baseline_scale = self.renderer.GetActiveCamera().GetParallelScale()
        # print('self.base_zoom_scale:', self.base_zoom_scale)

        self.base_zoom_scale = self.zoom_to_fit()

        self.load_top_right_actors()
        self.load_top_left_actors()
        self.load_bottom_left_actors()
        self.load_bottom_right_actors()

    def __get_factor_upsample(self, vtk_image_data: vtk.vtkImageData, viewer_height):
        # self.renderer.ResetCamera()
        camera = self.renderer.GetActiveCamera()

        # sure from image is 2d
        camera.ParallelProjectionOn()

        # get image size
        dims = vtk_image_data.GetDimensions()
        image_width, image_height = dims[0], dims[1]

        # get window size
        window_size = self.image_render_window.GetSize()
        window_width, window_height = window_size[0], window_size[1]

        # print(f"Image dimensions: {image_width}x{image_height}")
        # print(f"Window dimensions: {window_width}x{window_height}")

        spacing = vtk_image_data.GetSpacing()

        # calculate physical size image
        physical_width = image_width * spacing[0]
        physical_height = image_height * spacing[1]

        # calculate ratio physical size image
        image_aspect = physical_width / physical_height
        window_aspect = window_width / window_height

        # current_scale = camera.GetParallelScale()
        zoom_factor = 1.0  # lower: zoom in

        if image_aspect > window_aspect:
            # image is wider
            new_scale = (physical_width / 2.0) / (window_width / window_height) * zoom_factor
        else:
            # image is taller
            new_scale = (physical_height / 2.0) * zoom_factor

        # cam = self.renderer.GetActiveCamera()

        H = max(1, viewer_height)

        # print('H:"', H, 'c:', cam.GetParallelScale())
        # mm_per_screen_px = (2.0 * cam.GetParallelScale()) / H

        mm_per_screen_px = (2.0 * new_scale) / H
        spacing = vtk_image_data.GetSpacing()
        ppv_y = spacing[1] / mm_per_screen_px  # screen px per image px (تقریب محور Y)

        # print('ppv_y:', ppv_y)
        return ppv_y

    def _preprocess_vtk_image_data(self, vtk_image_data):
        # vtk_image_data = flip_image_y(vtk_image_data)

        if self.apply_default_filter:
            factor = self.__get_factor_upsample(vtk_image_data, self.viewer_height)
            if factor > 1:
                vtk_image_data = display_upsample_xy(vtk_image_data, factor=factor)

        return vtk_image_data

    def _sync_all_overlays_extent(self):
        """
        Keep every overlay actor aligned with the base image actor on the current slice.
        We simply copy the base actor's DisplayExtent to all overlay actors.
        """
        try:
            base_extent = self.GetImageActor().GetDisplayExtent()
        except Exception:
            return

        for (_vtk_image, _map_colors, _actor) in getattr(self, "_overlays", []):
            try:
                _actor.SetDisplayExtent(*base_extent)
            except Exception:
                pass


    # inside ImageViewer2D
    def clear_all_overlays(self):
        """Remove ALL overlay actors and reset overlay caches."""
        try:
            # multi-overlay list
            if hasattr(self, "_overlays") and self._overlays:
                for (_img, _map, actor) in self._overlays:
                    try:
                        self.GetRenderer().RemoveActor(actor)
                    except Exception:
                        pass
            self._overlays = []
        except Exception:
            pass

        # legacy single-overlay dict, if present
        try:
            if hasattr(self, "clear_overlay"):
                self.clear_overlay()
        except Exception:
            pass

    def clear_overlay(self):
        """حذف اوورلی از رندرر و آزادسازی مرجع‌ها"""
        if hasattr(self, "_overlay") and self._overlay:
            try:
                actor = self._overlay.get("actor")
                if actor:
                    self.GetRenderer().RemoveActor(actor)
            except Exception:
                pass
        self._overlay = {}

    def _update_overlay_extent(self):
        """DisplayExtent اوورلی را با توجه به اسلایس و اورینتیشن فعلی تنظیم می‌کند."""
        if not hasattr(self, "_overlay") or not self._overlay:
            return
        actor = self._overlay.get("actor")
        ov_img = self._overlay.get("reslice").GetOutput()
        base_img = self.vtk_image_data
        if not actor or not ov_img or not base_img:
            return

        # از ویوِر اصلی ابعاد و اسلایس فعلی را بگیر
        slice_idx = self.GetSlice()
        dims = base_img.GetDimensions()
        # slice_idx = dims[2] - (slice_idx + 2)

        extent = (0, dims[0] - 1, 0, dims[1] - 1, slice_idx, slice_idx)
        # extent = (0, dims[0], 0, dims[1], slice_idx, slice_idx)

        actor.SetDisplayExtent(*extent)

        self.image_reslice.Update()
        self.UpdateDisplayExtent()
        self.Render()

    # def _schedule_render(self, delay_ms=33):
    #     if getattr(self, "_render_pending", False):
    #         return
    #     self._render_pending = True
    #
    #     QTimer.singleShot(delay_ms, self._do_render)

    def _do_render(self):
        try:
            self.image_reslice.Update()
            self.UpdateDisplayExtent()
            self.Render()
            self.update_corners_actors()
            self.slider.setMaximum(self.get_count_of_slices())
        finally:
            self._render_pending = False

    def overlay(self, path: str, color=(1.0, 1.0, 0.0), opacity=0.4, is_label=True, pts_world_out: list = None,
                pts_ijk: list = None):
        """
        Add a new full-frame NIfTI overlay without removing previous overlays.
        - path: absolute path to the NIfTI mask (same geometry as the base image)
        - color/opacity: visual style for the overlay
        - is_label: if True, value 0 becomes fully transparent, others are colored
        """
        print(f'overlay path: {path}')

        # 1) Read NIfTI -> vtkImageData (your existing utility)
        vtk_image = read_segment_nifti(file=path)

        # 2) Build a simple LUT (transparent background for label images)
        import vtk
        lut = vtk.vtkLookupTable()
        table_size = 256
        lut.SetNumberOfTableValues(table_size)
        lut.Build()

        if is_label:
            # index 0 transparent, all other indices same RGBA
            lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
            for i in range(1, table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))
        else:
            for i in range(table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))

        map_colors = vtk.vtkImageMapToColors()
        map_colors.SetLookupTable(lut)
        map_colors.SetInputData(vtk_image)  # direct input; full-frame mask volume
        map_colors.Update()

        # 3) Create an image actor for the overlay and add it to the scene
        actor = vtk.vtkImageActor()
        actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
        actor.SetPickable(False)
        self.GetRenderer().AddActor(actor)

        # 4) Keep references to avoid GC removing VTK objects
        #    Structure: list of tuples (vtkImageData, vtkImageMapToColors, vtkImageActor)
        if not hasattr(self, "_overlays"):
            self._overlays = []
        self._overlays.append((vtk_image, map_colors, actor))

        if pts_world_out:
            self.create_overlay_box(pts_world_out, actor, pts_ijk)

        # 5) Align the overlay to the current slice and render
        self._sync_all_overlays_extent()
        self.Render()

    def create_overlay_box(self, pts_world_point, actor, pts_ijk):
        print('pts_world_point:', pts_world_point)

        # find top point to better show box_name
        text_actor_pos = pts_world_point[0]
        for i in range(1, len(pts_world_point)):
            if pts_world_point[i][1] > text_actor_pos[1]:  # compare height points
                text_actor_pos = pts_world_point[i]

        text_actor_pos[1] += 5

        box_name = f'Segmentation {len(self._overlays)}'
        text_actor = create_text_actor(text_actor_pos, box_name)
        self.renderer.AddActor(text_actor)

        corner_ijk = bbox_corners_ijk(pts_ijk)

        overlay_box_object = BoxManager(box_name=box_name, box_name_actor=text_actor, box_actor=actor,
                                        status_abnormal=False, ijk_points=corner_ijk)

        # update Box Details UI
        self.vtk_widget.update_boxes_details_ui(overlay_box_object)

    def _schedule_render(self, delay=50):
        """Schedule a render with delay to batch multiple updates"""
        if hasattr(self, '_render_timer') and self._render_timer:
            self._render_timer.stop()

        from PySide6.QtCore import QTimer
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._execute_render)
        self._render_timer.start(delay)

    def _execute_render(self):
        """Execute the actual render"""
        if self._render_pending:
            super().Render()
            self._render_pending = False

    def force_render_now(self):
        """Force immediate render without batching - for critical display moments"""
        try:
            # Ensure all VTK objects are updated
            self.image_reslice.Update()
            self.UpdateDisplayExtent()

            # Force camera reset and render
            self.GetRenderer().ResetCamera()
            self.GetRenderer().ResetCameraClippingRange()

            # Direct render call
            self.image_render_window.Render()

        except Exception as e:
            # Fallback to regular render
            try:
                super().Render()
            except:
                pass

    def grow_input_image_inplace_old(self, new_vtk_image_data, new_metadata=None):
        """
        بدون تعویض actor/mapper:
        - همان vtkImageData ورودیِ ImageReslice را بزرگ‌تر می‌کنیم
        - سپس Reslice و نمایش را Update می‌کنیم
        """
        old_input = self.image_reslice.vtk_image_data  # همان ورودیِ فعلی Reslice
        ox, oy, oz = old_input.GetDimensions()
        nx, ny, nz = new_vtk_image_data.GetDimensions()

        # print('ox, oy, oz:', ox, oy, oz)
        # print('nx, ny, nz:', nx, ny, nz)

        if (nx, ny, nz) <= (ox, oy, oz):
            # چیزی اضافه نشده؛ فقط Modified تا رندر نرم بماند
            # print('NOT CHANGED!!!!!!!!!!!')
            old_input.Modified()
            self.image_reslice.Modified()
            self.UpdateDisplayExtent()
            self.Render()
            return False

        # هم‌راستا بودن spacing/origin با سریِ فعلی (در عمل باید یکسان باشند)
        old_input.SetSpacing(new_vtk_image_data.GetSpacing())
        old_input.SetOrigin(new_vtk_image_data.GetOrigin())

        # extent/dimensions جدید
        old_input.SetDimensions(nx, ny, nz)
        old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

        # کپی محتوای اسکالرها (بدون تعویض actor/mapper)
        new_scalars = new_vtk_image_data.GetPointData().GetScalars()
        old_scalars = old_input.GetPointData().GetScalars()
        if old_scalars is None or old_scalars.GetNumberOfTuples() == 0:
            old_input.GetPointData().SetScalars(new_scalars)
        else:
            old_scalars.DeepCopy(new_scalars)

        # متادیتا (اختیاری) – برای سایز/WW/WL اسلایس‌های جدید
        if new_metadata is not None:
            self.metadata = new_metadata

        # رفرش نرم
        old_input.GetPointData().Modified()
        old_input.Modified()
        self.image_reslice.Modified()
        self.image_reslice.Update()
        self.UpdateDisplayExtent()
        self.update_corners_actors()  # متن گوشه‌ها (تعداد اسلایس و…)
        self.Render()
        return True

    def grow_input_image_inplace(self, new_vtk_image_data, new_metadata=None):
        """
        رشد درجا با کمترین هزینه:
        - بدون تعویض actor/mapper
        - بدون Render/Update فوری (caller اگر خواست throttle کند)
        - بهینه‌سازی شده برای سرعت بیشتر
        """
        old_input = self.image_reslice.vtk_image_data
        ox, oy, oz = old_input.GetDimensions()
        nx, ny, nz = new_vtk_image_data.GetDimensions()

        # 1) اگر چیزی اضافه نشده، فقط Modified سبک بده و برگرد
        if (nx <= ox and ny <= oy and nz <= oz):
            old_input.Modified()
            self.image_reslice.Modified()
            return False

        # 2) XY باید ثابت باشد؛ در غیر این صورت، از تخریب حافظه جلوگیری کن
        if (ox, oy) != (nx, ny):
            # اگر XY تغییر کرده، برای جلوگیری از کراش/مصرف سنگین، فعلاً رد کن
            # (در صورت نیاز می‌توان مسیر ایمن دیگری پیاده کرد)
            return False

        # 3) فقط در صورت تغییر، spacing/origin را به‌روز کن
        if old_input.GetSpacing() != new_vtk_image_data.GetSpacing():
            old_input.SetSpacing(new_vtk_image_data.GetSpacing())
        if old_input.GetOrigin() != new_vtk_image_data.GetOrigin():
            old_input.SetOrigin(new_vtk_image_data.GetOrigin())

        # 4) ابعاد/extent جدید
        old_input.SetDimensions(nx, ny, nz)
        old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

        # 5) کم‌هزینه‌ترین آپدیت اسکالرها: به‌جای DeepCopy، SetScalars (تعویض اشاره‌گر)
        new_scalars = new_vtk_image_data.GetPointData().GetScalars()
        old_input.GetPointData().SetScalars(new_scalars)

        # 6) متادیتا (در صورت نیاز) - بهینه‌سازی شده
        if new_metadata is not None:
            # فقط فیلدهای ضروری را جایگزین کن تا کپی‌های بزرگ اجتناب شود
            if 'series' in new_metadata:
                # Merge only essential fields to avoid deep copying
                for key in ['series_name', 'series_description', 'series_thk']:
                    if key in new_metadata['series']:
                        if 'series' not in self.metadata:
                            self.metadata['series'] = {}
                        self.metadata['series'][key] = new_metadata['series'][key]

            if 'instances' in new_metadata:
                # Direct assignment for instances to avoid copying
                self.metadata['instances'] = new_metadata['instances']

        # 7) علامت‌زدن تغییر؛ بدون Render/Update فوری
        old_input.GetPointData().Modified()
        old_input.Modified()
        self.image_reslice.Modified()

        # 8) Schedule render instead of immediate render
        if hasattr(self, '_schedule_render'):
            self._schedule_render(100)  # 100ms delay for batching
        else:
            # Fallback to immediate render if _schedule_render is not available
            self.Render()

        return True

    def set_color_mapper(self):
        # ✅ OPTIMIZATION: Reuse existing color_mapper instead of creating new one
        if hasattr(self, 'color_mapper') and self.color_mapper is not None:
            # Just reconnect to new input (much faster than creating new mapper)
            try:
                self.color_mapper.SetInputConnection(self.image_reslice.GetOutputPort())
                return  # Early return to avoid unnecessary GetImageActor call
            except:
                pass  # If failed, create new mapper below
        
        # Create new mapper only on first call or if reuse failed
        self.color_mapper = vtk.vtkImageMapToWindowLevelColors()
        self.color_mapper.SetInputConnection(self.image_reslice.GetOutputPort())
        self.GetImageActor().GetMapper().SetInputConnection(self.color_mapper.GetOutputPort())

    def update_corners_actors_pos(self, window_height):
        # all_actor_corners = self.dicom_tags_actors.all_actors()
        gap_base = 0.02
        height_base = 850
        gap = gap_base * (height_base / window_height)
        # _top_right

        # update top_right actors pos
        top = 0.98
        right = 0.94
        left = 0.02
        bottom = 0.02

        self.dicom_tags_actors.im_slice_actor.SetPosition(right, top)
        self.dicom_tags_actors.im_study_date_actor.SetPosition(right, top - (1 * gap))
        self.dicom_tags_actors.im_series_time_actor.SetPosition(right, top - (2 * gap))
        self.dicom_tags_actors.im_series_name_actor.SetPosition(right, top - (3 * gap))
        self.dicom_tags_actors.im_series_desc_actor.SetPosition(right, top - (4 * gap))

        # update top_left actors pos
        self.dicom_tags_actors.p_name_actor.SetPosition(left, top)
        self.dicom_tags_actors.p_id_actor.SetPosition(left, (top - 1 * gap))
        self.dicom_tags_actors.p_age_actor.SetPosition(left, (top - 2 * gap))
        self.dicom_tags_actors.p_sex_actor.SetPosition(left, (top - 3 * gap))

        # update bottom_left actors pos
        self.dicom_tags_actors.im_series_window_level.SetPosition(left, bottom)
        self.dicom_tags_actors.im_scale_zoom_actor.SetPosition(left, bottom + (1 * gap))
        self.dicom_tags_actors.im_series_size_actor.SetPosition(left, bottom + (2 * gap))
        self.dicom_tags_actors.im_series_thk_actor.SetPosition(left, bottom + (3 * gap))

        # update bottom_right actors pos
        self.dicom_tags_actors.im_hospital_name_actor.SetPosition(right, bottom)

    def update_corners_actors(self, update_just_zoom=False, window_height=None):
        if update_just_zoom:
            im_h = self.vtk_image_data.GetDimensions()[1]
            # win_h = self.image_render_window.GetSize()[1]
            win_h = window_height if window_height is not None else self.image_render_window.GetSize()[1]
            scale_zoom = win_h / im_h
            camera = self.renderer.GetActiveCamera()

            if camera.GetParallelScale() >= self.base_zoom_scale:  # zoom out
                changes_zoom = (camera.GetParallelScale() - self.base_zoom_scale) / self.base_zoom_scale
            else:  # zoom in
                changes = ((camera.GetParallelScale() * 2) - self.base_zoom_scale)
                changes_zoom = (changes - self.base_zoom_scale) / (camera.GetParallelScale() / 2)

            scale_zoom = scale_zoom - changes_zoom
            scale_zoom = f'{scale_zoom:.2f}'
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_scale_zoom_actor, f'Scale:{scale_zoom}')

        else:

            # update top-right actors
            current_slice = self.GetSlice()
            # meta = self.metadata['meta_changed'][current_slice]

            study_date = self.metadata_fixed['study_date']
            series_time = self.metadata_fixed['study_time']

            series_name = self.metadata['series']['series_name']
            series_desc = self.metadata['series']['series_description']

            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_slice_actor,
                                                     f'{current_slice + self.skip_slices + 1} / {self.get_count_of_slices()}')
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_study_date_actor, study_date)
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_time_actor, series_time)
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_name_actor, series_name)
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_desc_actor, series_desc)

            # update top-left actors -->
            '''we don't need to update actors on top-left because these actors are the same for all series'''

            # update bottom-left
            series_thk = self.metadata['series']['series_thk']

            rows = self.metadata['instances'][current_slice]['rows']
            columns = self.metadata['instances'][current_slice]['columns']
            series_size = f"{rows} * {columns}"

            window_width, window_center = int(self.get_window_level()[0]), int(self.get_window_level()[1])

            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_thk_actor, f'Thk:{series_thk} mm')
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_size_actor, f'Size:{series_size}')
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_window_level,
                                                     f'WW:{window_width} WL:{(window_center)}')

    def load_top_right_actors(self):
        """
            these actors belong to image information
        """
        top = 0.98
        right = 0.96
        gap = 0.02

        # changeable
        current_slice = self.GetSlice()
        study_date = self.metadata_fixed['study_date']
        series_time = self.metadata_fixed['study_time']

        series_name = self.metadata['series']['series_name']
        series_desc = self.metadata['series']['series_description']

        self.dicom_tags_actors.im_slice_actor = make_corner_actor(
            f'{current_slice + self.skip_slices} / {self.get_count_of_slices()}', right, top, 'right', 'top')
        self.dicom_tags_actors.im_study_date_actor = make_corner_actor(study_date, right, top - (1 * gap), 'right',
                                                                       'top')
        self.dicom_tags_actors.im_series_time_actor = make_corner_actor(series_time, right, top - (2 * gap), 'right',
                                                                        'top')
        self.dicom_tags_actors.im_series_name_actor = make_corner_actor(series_name, right, top - (3 * gap), 'right',
                                                                        'top')
        self.dicom_tags_actors.im_series_desc_actor = make_corner_actor(series_desc, right, top - (4 * gap), 'right',
                                                                        'top')

        self.renderer.AddViewProp(self.dicom_tags_actors.im_slice_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_study_date_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_time_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_name_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_desc_actor)
        self.Render()

    def load_top_right_actors_no_render(self):
        """Load top right actors without render call"""
        top = 0.98
        right = 0.96
        gap = 0.02

        # changeable
        current_slice = self.GetSlice()
        study_date = self.metadata_fixed.get('study_date', 'N/A')
        series_time = self.metadata_fixed.get('study_time', 'N/A')

        series_name = self.metadata['series']['series_name']
        series_desc = self.metadata['series']['series_description']

        self.dicom_tags_actors.im_slice_actor = make_corner_actor(
            f'{current_slice + self.skip_slices} / {self.get_count_of_slices()}', right, top, 'right', 'top')
        self.dicom_tags_actors.im_study_date_actor = make_corner_actor(study_date, right, top - (1 * gap), 'right',
                                                                       'top')
        self.dicom_tags_actors.im_series_time_actor = make_corner_actor(series_time, right, top - (2 * gap), 'right',
                                                                        'top')
        self.dicom_tags_actors.im_series_name_actor = make_corner_actor(series_name, right, top - (3 * gap), 'right',
                                                                        'top')
        self.dicom_tags_actors.im_series_desc_actor = make_corner_actor(series_desc, right, top - (4 * gap), 'right',
                                                                        'top')

        self.renderer.AddViewProp(self.dicom_tags_actors.im_slice_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_study_date_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_time_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_name_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_desc_actor)

    def load_top_left_actors(self):
        top = 0.98
        left = 0.02
        gap = 0.02

        # fixed
        p_name = self.metadata_fixed['patient_name']
        p_id = self.metadata_fixed['patient_id']
        p_sex = self.metadata_fixed['patient_sex']
        p_age = self.metadata_fixed['patient_age']

        self.dicom_tags_actors.p_name_actor = make_corner_actor(p_name, left, top, 'left', 'top')
        self.dicom_tags_actors.p_id_actor = make_corner_actor(f'PID:{p_id}', left, (top - 1 * gap), 'left', 'top')
        self.dicom_tags_actors.p_age_actor = make_corner_actor(f'Age:{p_age}', left, (top - 2 * gap), 'left', 'top')
        self.dicom_tags_actors.p_sex_actor = make_corner_actor(f'Sex:{p_sex}', left, (top - 3 * gap), 'left', 'top')

        self.renderer.AddViewProp(self.dicom_tags_actors.p_name_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_id_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_sex_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_age_actor)
        self.Render()

    def load_top_left_actors_no_render(self):
        """Load top left actors without render call"""
        top = 0.98
        left = 0.02
        gap = 0.02

        # fixed
        p_name = self.metadata_fixed.get('patient_name', 'N/A')
        p_id = self.metadata_fixed.get('patient_id', 'N/A')
        p_sex = self.metadata_fixed.get('patient_sex', 'N/A')
        p_age = self.metadata_fixed.get('patient_age', 'N/A')

        self.dicom_tags_actors.p_name_actor = make_corner_actor(p_name, left, top, 'left', 'top')
        self.dicom_tags_actors.p_id_actor = make_corner_actor(f'PID:{p_id}', left, (top - 1 * gap), 'left', 'top')
        self.dicom_tags_actors.p_age_actor = make_corner_actor(f'Age:{p_age}', left, (top - 2 * gap), 'left', 'top')
        self.dicom_tags_actors.p_sex_actor = make_corner_actor(f'Sex:{p_sex}', left, (top - 3 * gap), 'left', 'top')

        self.renderer.AddViewProp(self.dicom_tags_actors.p_name_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_id_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_sex_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_age_actor)

    def load_bottom_left_actors(self):
        bottom = 0.02
        left = 0.02
        gap = 0.02

        current_slice = self.GetSlice()
        series_thk = self.metadata['series']['series_thk']

        rows = self.metadata['instances'][current_slice]['rows']
        columns = self.metadata['instances'][current_slice]['columns']
        series_size = f"{rows} * {columns}"
        window_width, window_center = self.get_window_level()

        im_h = self.vtk_image_data.GetDimensions()[1]
        # im_h = float(series_size[0:series_size.find('x')])
        win_h = self.image_render_window.GetSize()[1]
        scale_zoom = win_h / im_h
        scale_zoom = f'{scale_zoom:.2f}'

        self.dicom_tags_actors.im_series_window_level = make_corner_actor(f'WW:{window_width} WL:{window_center}', left,
                                                                          bottom, 'left', 'bottom')
        self.dicom_tags_actors.im_scale_zoom_actor = make_corner_actor(f'Scale:{scale_zoom}', left, bottom + (1 * gap),
                                                                       'left', 'bottom')
        self.dicom_tags_actors.im_series_size_actor = make_corner_actor(series_size, left, bottom + (2 * gap), 'left',
                                                                        'bottom')
        self.dicom_tags_actors.im_series_thk_actor = make_corner_actor(series_thk, left, bottom + (3 * gap), 'left',
                                                                       'bottom')

        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_window_level)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_scale_zoom_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_size_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_thk_actor)
        self.Render()

    def load_bottom_left_actors_no_render(self):
        """Load bottom left actors without render call"""
        bottom = 0.02
        left = 0.02
        gap = 0.02

        current_slice = self.GetSlice()
        series_thk = self.metadata['series']['series_thk']

        rows = self.metadata['instances'][current_slice]['rows']
        columns = self.metadata['instances'][current_slice]['columns']
        series_size = f"{rows} * {columns}"
        window_width, window_center = self.get_window_level()

        im_h = self.vtk_image_data.GetDimensions()[1]
        win_h = self.image_render_window.GetSize()[1]
        scale_zoom = win_h / im_h
        scale_zoom = f'{scale_zoom:.2f}'

        self.dicom_tags_actors.im_series_window_level = make_corner_actor(f'WW:{window_width} WL:{window_center}', left,
                                                                          bottom, 'left', 'bottom')
        self.dicom_tags_actors.im_scale_zoom_actor = make_corner_actor(f'Scale:{scale_zoom}', left, bottom + (1 * gap),
                                                                       'left', 'bottom')
        self.dicom_tags_actors.im_series_size_actor = make_corner_actor(series_size, left, bottom + (2 * gap), 'left',
                                                                        'bottom')
        self.dicom_tags_actors.im_series_thk_actor = make_corner_actor(series_thk, left, bottom + (3 * gap), 'left',
                                                                       'bottom')

        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_window_level)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_scale_zoom_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_size_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_thk_actor)

    def load_bottom_right_actors(self):
        bottom = 0.02
        right = 0.96
        gap = 0.02

        hospital_name = self.metadata_fixed['institution_name']

        self.dicom_tags_actors.im_hospital_name_actor = make_corner_actor(hospital_name, right, bottom, 'right',
                                                                          'bottom')
        self.renderer.AddViewProp(self.dicom_tags_actors.im_hospital_name_actor)
        self.Render()

    def load_bottom_right_actors_no_render(self):
        """Load bottom right actors without render call"""
        bottom = 0.02
        right = 0.96
        gap = 0.02

        hospital_name = self.metadata_fixed.get('institution_name', 'N/A')

        self.dicom_tags_actors.im_hospital_name_actor = make_corner_actor(hospital_name, right, bottom, 'right',
                                                                          'bottom')
        self.renderer.AddViewProp(self.dicom_tags_actors.im_hospital_name_actor)

    def reset_image_viewer(self, vtk_image_data, metadata):
        import time
        _reset_start = time.time()
        
        _clear_start = time.time()
        self.clear_all_overlays()
        _clear_time = time.time() - _clear_start
        print(f"      • Clear overlays: {_clear_time:.3f}s")

        _preprocess_start = time.time()
        
        # ✅ OPTIMIZATION: Check if we can reuse existing reslice
        # If the vtk_image_data is the same (same series), skip reslice creation
        current_series_uid = metadata.get('series', {}).get('series_uid', None)
        cached_series_uid = getattr(self, '_cached_series_uid', None)
        
        can_reuse_reslice = (
            current_series_uid is not None and 
            current_series_uid == cached_series_uid and
            hasattr(self, 'image_reslice') and 
            self.image_reslice is not None
        )
        
        if can_reuse_reslice:
            print(f"      ✅ Reusing cached reslice")
        else:
            # Need to create new reslice
            if hasattr(self, 'image_reslice'):
                del self.image_reslice
            vtk_image_data = self._preprocess_vtk_image_data(vtk_image_data)
            self.image_reslice = ImageReslice(vtk_image_data, metadata)
            # Cache the series UID
            self._cached_series_uid = current_series_uid
            
        _preprocess_time = time.time() - _preprocess_start
        print(f"      • Preprocess + Reslice: {_preprocess_time:.3f}s")

        _setup_start = time.time()
        
        _set_input_start = time.time()
        # ✅ OPTIMIZATION: Disable automatic update during SetInputData
        old_global_warning = vtk.vtkObject.GetGlobalWarningDisplay()
        vtk.vtkObject.GlobalWarningDisplayOff()
        
        self.SetInputData(self.image_reslice.GetOutput())  # without color map (window level)
        self.vtk_image_data = self.image_reslice.GetOutput()  # <-- IMPORTANT: refresh cached image ref
        
        vtk.vtkObject.SetGlobalWarningDisplay(old_global_warning)
        _set_input_time = time.time() - _set_input_start
        print(f"         • SetInputData: {_set_input_time:.3f}s")

        # Update metadata
        _metadata_start = time.time()
        self.metadata = metadata
        _metadata_time = time.time() - _metadata_start
        print(f"         • Update metadata: {_metadata_time:.3f}s")

        _color_mapper_start = time.time()
        self.set_color_mapper()
        _color_mapper_time = time.time() - _color_mapper_start
        print(f"         • set_color_mapper: {_color_mapper_time:.3f}s")
        
        self.flag_set_custom_window_level = False
        
        _setup_time = time.time() - _setup_start
        print(f"      • Setup pipeline: {_setup_time:.3f}s")

        _render_start = time.time()
        
        _update_display_start = time.time()
        self.UpdateDisplayExtent()
        _update_display_time = time.time() - _update_display_start
        print(f"         • UpdateDisplayExtent: {_update_display_time:.3f}s")
        
        _render_call_start = time.time()
        self.Render()
        _render_call_time = time.time() - _render_call_start
        print(f"         • Render: {_render_call_time:.3f}s")
        
        _zoom_start = time.time()
        self.zoom_to_fit()
        _zoom_time = time.time() - _zoom_start
        print(f"         • zoom_to_fit: {_zoom_time:.3f}s")
        
        _render_time = time.time() - _render_start
        print(f"      • Render + zoom: {_render_time:.3f}s")
        
        _reset_total = time.time() - _reset_start
        print(f"      ⏱️  TOTAL reset_image_viewer: {_reset_total:.3f}s")

    def set_slice(self, slice_index):
        """
        Change the displayed slice and keep overlays in sync.
        Order matters:
          1) SetSlice so GetSlice() reflects the new index
          2) Apply default WL/WC (if user hasn't customized)
          3) Update corner text
          4) Sync all overlay actors to this slice
        """
        # 1) Move to the requested slice
        self.SetSlice(slice_index)

        # 2) Apply default window/level only if the user hasn't set a custom WL
        if not self.flag_set_custom_window_level:
            self.apply_default_window_level(slice_index)

        # 3) Update on-screen corner annotations
        self.update_corners_actors()

        # 4) Make overlays follow the current slice and render
        self._sync_all_overlays_extent()
        self.Render()

    def set_viewer_type(self, viewer_type):
        self.viewer_type = viewer_type

        if viewer_type == ViewerType.AXIAL.name.capitalize():
            self.SetSliceOrientationToXY()
        elif viewer_type == ViewerType.SAGITTAL.name.capitalize():
            self.SetSliceOrientationToYZ()
        elif viewer_type == ViewerType.CORONAL.name.capitalize():
            self.SetSliceOrientationToXZ()
        self.Render()

    def apply_default_window_level(self, slice_index):
        # get window width and window center from lst_windows_levels
        # belongs to the slice[index]
        # slice_index = 20
        # print('slice_index:', slice_index,'len:', len(self.metadata['windows_levels']) ,'self.metadata:', self.metadata['windows_levels'])

        # window_level = self.metadata['windows_levels'][slice_index]
        # # window_width = window_level['window_width'] * 1.25  # width
        # window_width = window_level['window_width']  # width
        # window_center = window_level['window_center']  # level

        instance_metadata = self.metadata['instances'][slice_index]
        window_width = instance_metadata['window_width']  # width
        window_center = instance_metadata['window_center']  # level

        # print(f'slice: {slice_index}\t width: {window_width}\t center: {window_center}')
        # window_width = window_width * (window_width / (window_center * 2))

        self.set_window_level(window_width, window_center, flag_default=True)

    def set_window_level(self, window_width, window_center, flag_default=False):

        # print(f'width: {window_width}\t center: {window_center}')

        # # create color mapper
        # color_mapper = vtk.vtkImageMapToWindowLevelColors()
        # color_mapper.SetInputConnection(self.image_reslice.GetOutputPort())
        #
        # color_mapper.SetWindow(window_width)
        # color_mapper.SetLevel(window_center)
        #
        # color_mapper.Update()
        # self.GetImageActor().GetMapper().SetInputConnection(color_mapper.GetOutputPort())

        # ###################################################################################
        # self.SetColorWindow(window_width)
        #
        # if flag_default is True:
        #     self.SetColorLevel(window_center / 2.0)
        # else:
        #     self.SetColorLevel(window_center)
        #     self.update_corners_actors()

        # self.SetColorWindow(window_width)
        # self.SetColorLevel(window_center)

        # if flag_default:
        #     # create color mapper
        #     # color_mapper = vtk.vtkImageMapToWindowLevelColors()
        #     # color_mapper.SetInputConnection(self.image_reslice.GetOutputPort())
        #
        #     self.color_mapper.SetWindow(window_width)
        #     self.color_mapper.SetLevel(window_center)
        #
        #     self.color_mapper.Update()
        #     # self.GetImageActor().GetMapper().SetInputConnection(color_mapper.GetOutputPort())
        #
        # else:
        #     self.color_mapper.SetWindow(window_width)
        #     self.color_mapper.SetLevel(window_center)
        #
        #
        #     self.color_mapper.Update()
        # is_rgb = self.metadata['meta_changed'][self.GetSlice()]['is_rgb']
        is_rgb = self.metadata['instances'][self.GetSlice()]['is_rgb']
        if is_rgb:
            return

        self.color_mapper.SetWindow(window_width)
        self.color_mapper.SetLevel(window_center)
        self.color_mapper.Update()
        self.update_corners_actors()

    def get_window_level(self):
        # window_width = self.GetColorWindow()
        # window_center = self.GetColorLevel()
        window_width = self.color_mapper.GetWindow()
        window_center = self.color_mapper.GetLevel()

        return window_width, window_center

    def get_count_of_slices(self):
        self.vtk_image_data: vtk.vtkImageData
        dims = self.vtk_image_data.GetDimensions()  # (dimX, dimY, dimZ)
        return dims[2]

    def set_zoom_1to1(self):
        """ set image to pixel to pixel"""
        self.renderer.ResetCamera()

        spacing = self.vtk_image_data.GetSpacing()  # (spacing_x, spacing_y, spacing_z)
        window_height = self.image_render_window.GetSize()[1]  # window height to pixel

        parallel_scale = (window_height * spacing[1])
        # print('parallel_scale::', parallel_scale)

        camera = self.renderer.GetActiveCamera()
        camera.SetParallelScale(parallel_scale)
        self.Render()
        return parallel_scale

    def zoom_to_fit(self):
        try:
            self.renderer.ResetCamera()
            camera = self.renderer.GetActiveCamera()

            # sure from image is 2d
            camera.ParallelProjectionOn()

            # get image size
            dims = self.vtk_image_data.GetDimensions()
            image_width, image_height = dims[0], dims[1]

            # get window size
            window_size = self.image_render_window.GetSize()
            window_width, window_height = window_size[0], window_size[1]

            # print(f"Image dimensions: {image_width}x{image_height}")
            # print(f"Window dimensions: {window_width}x{window_height}")

            spacing = self.vtk_image_data.GetSpacing()

            # calculate physical size image
            physical_width = image_width * spacing[0]
            physical_height = image_height * spacing[1]

            # calculate ratio physical size image
            image_aspect = physical_width / physical_height
            window_aspect = window_width / window_height

            # current_scale = camera.GetParallelScale()
            zoom_factor = 1.0  # lower: zoom in

            if image_aspect > window_aspect:
                # image is wider
                new_scale = (physical_width / 2.0) / (window_width / window_height) * zoom_factor
            else:
                # image is taller
                new_scale = (physical_height / 2.0) * zoom_factor

            # print(f"Physical dimensions: {physical_width}x{physical_height}")
            # print(f"New scale: {new_scale}")
            # print(f"Aspect ratios - Image: {image_aspect}, Window: {window_aspect}")

            camera.SetParallelScale(new_scale)
            self.Render()

            return new_scale
            # zoom = self.base_zoom_scale / camera.GetParallelScale()
            # print('zooooom:', zoom)
            # print("Zoom to fit applied successfully")
            # return True
        except Exception as e:
            print(f"Error in zoom_to_fit: {e}")
            return False

    def enable_curved_mpr_mode(self, enabled=True):
        """Enable/disable curved MPR point picking mode"""
        self.curved_mpr_mode = enabled
        
        if enabled:
            print(f"[CURVED MPR] Mode ENABLED on viewer")
            
            # Start the curved MPR module with the current volume
            self.curved_mpr_module.start_curved_mpr(self.vtk_image_data)
            
            # Clear previous points (legacy)
            self.curved_mpr_points = []
            self._clear_curved_mpr_visuals()
            
            # Show text overlay
            self._show_curved_mpr_overlay()
            
            # Add observer for left click
            if self.curved_mpr_observer_id is None:
                self.curved_mpr_observer_id = self.image_interactor.AddObserver(
                    'LeftButtonPressEvent',
                    self._on_curved_mpr_click
                )
        else:
            print(f"[CURVED MPR] Mode DISABLED on viewer")
            
            # Reset the module
            self.curved_mpr_module.reset()
            
            # Hide text overlay
            self._hide_curved_mpr_overlay()
            
            # Remove observer
            if self.curved_mpr_observer_id is not None:
                self.image_interactor.RemoveObserver(self.curved_mpr_observer_id)
                self.curved_mpr_observer_id = None
    
    def _on_curved_mpr_click(self, obj, event):
        """
        Handle click event for curved MPR point selection.
        
        CRITICAL: This must convert 2D click coordinates to proper 3D DICOM world coordinates,
        accounting for the current reslice orientation (axial/sagittal/coronal/oblique).
        """
        if not self.curved_mpr_mode:
            return
        
        try:
            import numpy as np
            
            # Get click position in screen coordinates
            click_pos = self.image_interactor.GetEventPosition()
            
            # METHOD 1: Try vtkWorldPointPicker first (most accurate for image planes)
            world_picker = vtk.vtkWorldPointPicker()
            if world_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer):
                picked_pos = world_picker.GetPickPosition()
                if picked_pos != (0.0, 0.0, 0.0):
                    point_3d = list(picked_pos)
                    print(f"[CURVED MPR] ✓ WorldPointPicker: ({point_3d[0]:.1f}, {point_3d[1]:.1f}, {point_3d[2]:.1f})")
                    self._add_curved_mpr_point(point_3d)
                    return
            
            # METHOD 2: Manual calculation using slice orientation and position
            # Get current slice and orientation
            current_slice = self.GetSlice()
            orientation = self.GetSliceOrientation()  # 0=YZ (sagittal), 1=XZ (coronal), 2=XY (axial)
            
            # Get image properties
            origin = np.array(self.origin)
            spacing = np.array(self.spacing)
            
            # Get the renderer and camera
            renderer = self.renderer
            camera = renderer.GetActiveCamera()
            
            # Convert display coordinates to world using coordinate converter
            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToDisplay()
            coord.SetValue(click_pos[0], click_pos[1], 0)
            world_2d = np.array(coord.GetComputedWorldValue(renderer))
            
            # Calculate 3D point based on orientation
            # The picked 2D point is in the viewing plane, we need to add the depth
            
            if orientation == 2:  # Axial (XY plane)
                # Z is determined by slice
                point_3d = [
                    world_2d[0],  # X from picked position
                    world_2d[1],  # Y from picked position
                    origin[2] + current_slice * spacing[2]  # Z from slice index
                ]
            elif orientation == 1:  # Coronal (XZ plane)
                # Y is determined by slice
                point_3d = [
                    world_2d[0],  # X from picked position
                    origin[1] + current_slice * spacing[1],  # Y from slice index
                    world_2d[1]   # Z from picked position (displayed as Y on screen)
                ]
            elif orientation == 0:  # Sagittal (YZ plane)
                # X is determined by slice
                point_3d = [
                    origin[0] + current_slice * spacing[0],  # X from slice index
                    world_2d[0],  # Y from picked position
                    world_2d[1]   # Z from picked position (displayed as Y on screen)
                ]
            else:
                # Fallback for unknown orientation - use PropPicker
                print(f"[CURVED MPR] Warning: Unknown orientation {orientation}, using PropPicker")
                prop_picker = vtk.vtkPropPicker()
                if prop_picker.Pick(click_pos[0], click_pos[1], 0, renderer):
                    point_3d = list(prop_picker.GetPickPosition())
                else:
                    print("[CURVED MPR] Failed to pick point")
                    return
            
            orientation_names = {0: 'Sagittal', 1: 'Coronal', 2: 'Axial'}
            print(f"[CURVED MPR] Click at screen ({click_pos[0]}, {click_pos[1]})")
            print(f"[CURVED MPR] ✓ 3D position: ({point_3d[0]:.1f}, {point_3d[1]:.1f}, {point_3d[2]:.1f})")
            print(f"[CURVED MPR] Orientation: {orientation_names.get(orientation, 'Unknown')}, Slice: {current_slice}")
            
            # Add point to module
            self.curved_mpr_module.add_point_world(tuple(point_3d))
            
            # Update centerline visualization
            self._update_curved_mpr_centerline()
            
            # Add point for visualization (legacy - spheres and labels)
            self._add_curved_mpr_point(point_3d)
            
        except Exception as e:
            print(f"[CURVED MPR] Error in click handler: {e}")
            import traceback
            traceback.print_exc()
    
    def _add_curved_mpr_point(self, point_3d):
        """Add a point to curved MPR path and visualize it with number label"""
        self.curved_mpr_points.append(point_3d)
        point_num = len(self.curved_mpr_points)
        
        # Colors for better visibility
        if point_num == 1:
            sphere_color = (0.0, 1.0, 0.0)  # Green for first point
        else:
            sphere_color = (1.0, 0.9, 0.0)  # Yellow for others
        
        # Create sphere at point - larger and more visible
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(point_3d)
        sphere.SetRadius(4.0)  # 4mm radius - larger for visibility
        sphere.SetPhiResolution(16)
        sphere.SetThetaResolution(16)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*sphere_color)
        actor.GetProperty().SetOpacity(0.9)
        actor.GetProperty().SetAmbient(0.3)
        actor.GetProperty().SetDiffuse(0.7)
        
        self.renderer.AddActor(actor)
        self.curved_mpr_sphere_actors.append(actor)
        
        # Create text label with point number
        text_source = vtk.vtkVectorText()
        text_source.SetText(str(point_num))
        
        text_mapper = vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_source.GetOutputPort())
        
        text_actor = vtk.vtkFollower()
        text_actor.SetMapper(text_mapper)
        text_actor.SetScale(5, 5, 5)  # Scale for visibility
        text_actor.SetPosition(point_3d[0] + 5, point_3d[1] + 5, point_3d[2])
        text_actor.GetProperty().SetColor(1.0, 1.0, 1.0)  # White text
        text_actor.SetCamera(self.renderer.GetActiveCamera())
        
        self.renderer.AddActor(text_actor)
        self.curved_mpr_sphere_actors.append(text_actor)  # Store with spheres for cleanup
        
        # Note: Individual line segments are now replaced by a single polyline
        # drawn via _update_curved_mpr_centerline() for better performance
        
        # Render
        self.Render()
        
        print(f"[CURVED MPR] Point {point_num} added at ({point_3d[0]:.1f}, {point_3d[1]:.1f}, {point_3d[2]:.1f})")
    
    def _update_curved_mpr_centerline(self):
        """
        Update the centerline polyline visualization.
        
        This creates/updates a single lightweight polyline connecting all picked points.
        Much more efficient than individual line segments.
        """
        # Remove old centerline actor if exists
        if self.curved_mpr_centerline_actor is not None:
            self.renderer.RemoveActor(self.curved_mpr_centerline_actor)
            self.curved_mpr_centerline_actor = None
        
        # Get polydata from module
        polydata = self.curved_mpr_module.get_centerline_polydata()
        
        if polydata is None:
            # Less than 2 points, no line to draw
            self.Render()
            return
        
        # Create mapper
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        
        # Create actor with visual properties
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        
        # Styling: thin yellow/green line
        actor.GetProperty().SetColor(1.0, 0.9, 0.0)  # Yellow (highly visible)
        actor.GetProperty().SetLineWidth(3.0)  # Thin but visible
        actor.GetProperty().SetOpacity(0.9)
        actor.GetProperty().SetAmbient(0.5)
        actor.GetProperty().SetDiffuse(0.7)
        
        # Add to renderer
        self.renderer.AddActor(actor)
        self.curved_mpr_centerline_actor = actor
        
        # Render
        self.Render()
        
        point_count = self.curved_mpr_module.get_point_count()
        print(f"[CURVED MPR] Centerline updated with {point_count} points")
    
    def _clear_curved_mpr_visuals(self):
        """Clear curved MPR visual elements"""
        # Remove spheres
        for actor in self.curved_mpr_sphere_actors:
            self.renderer.RemoveActor(actor)
        self.curved_mpr_sphere_actors = []
        
        # Remove legacy lines (if any)
        for actor in self.curved_mpr_line_actors:
            self.renderer.RemoveActor(actor)
        self.curved_mpr_line_actors = []
        
        # Remove centerline polyline
        if self.curved_mpr_centerline_actor is not None:
            self.renderer.RemoveActor(self.curved_mpr_centerline_actor)
            self.curved_mpr_centerline_actor = None
        
        # Render
        self.Render()
    
    def _show_curved_mpr_overlay(self):
        """Show text overlay indicating Curved MPR mode is active"""
        # Remove previous overlay if exists
        self._hide_curved_mpr_overlay()
        
        # Create 2D text actor for overlay
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput("Curved MPR Mode: Click to add points")
        
        # Position at top center of the viewport
        text_property = text_actor.GetTextProperty()
        text_property.SetFontSize(18)
        text_property.SetColor(0.0, 1.0, 0.0)  # Green color
        text_property.SetBold(True)
        text_property.SetJustificationToCentered()
        text_property.SetVerticalJustificationToTop()
        
        # Set position (normalized coordinates)
        coord = text_actor.GetPositionCoordinate()
        coord.SetCoordinateSystemToNormalizedViewport()
        coord.SetValue(0.5, 0.98)  # Top center
        
        # Add to renderer
        self.renderer.AddViewProp(text_actor)
        self.curved_mpr_overlay_actor = text_actor
        
        # Render
        self.Render()
        print("[CURVED MPR] Overlay text displayed")
    
    def _hide_curved_mpr_overlay(self):
        """Hide the Curved MPR mode overlay text"""
        if self.curved_mpr_overlay_actor is not None:
            self.renderer.RemoveActor2D(self.curved_mpr_overlay_actor)
            self.curved_mpr_overlay_actor = None
            self.Render()
            print("[CURVED MPR] Overlay text hidden")
    
    def get_curved_mpr_points(self):
        """Get all curved MPR points"""
        return self.curved_mpr_points.copy()
    
    def generate_and_show_curved_mpr(self, num_samples=200, slice_width=100, slice_height=100):
        """
        Generate and display the curved MPR image in a new window.
        
        This is a convenience method that:
        1. Generates the curved MPR using the module
        2. Opens a new window to display it
        
        Args:
            num_samples: Number of slices along the path
            slice_width: Width of each slice
            slice_height: Height of each slice
        
        Returns:
            The CurvedMPRView window, or None if generation failed
        """
        if not self.curved_mpr_module.is_active():
            print("[Viewer] Curved MPR mode is not active")
            return None
        
        point_count = self.curved_mpr_module.get_point_count()
        if point_count < 2:
            print(f"[Viewer] Need at least 2 points, only {point_count} picked")
            return None
        
        print(f"[Viewer] Generating curved MPR with {point_count} points...")
        
        # Generate the curved MPR image
        curved_mpr_image = self.curved_mpr_module.generate_curved_mpr(
            num_samples=num_samples,
            slice_width=slice_width,
            slice_height=slice_height
        )
        
        if curved_mpr_image is None:
            print("[Viewer] Failed to generate curved MPR")
            return None
        
        # Import and show the view
        from PacsClient.pacs.patient_tab.curved_mpr_view import CurvedMPRView
        
        print("[Viewer] Opening curved MPR view window...")
        view_window = CurvedMPRView(curved_mpr_image)
        view_window.show()
        
        return view_window
    
    def cleanup(self):
        """آزاد کردن منابع VTK برای جلوگیری از leak حافظه."""
        try:
            # Clean up curved MPR
            if self.curved_mpr_observer_id is not None:
                self.image_interactor.RemoveObserver(self.curved_mpr_observer_id)
                self.curved_mpr_observer_id = None
            self._clear_curved_mpr_visuals()
            # حذف actorها از renderer
            if self.renderer:
                actors = self.renderer.GetActors()
                actors.InitTraversal()
                actor = actors.GetNextItem()
                while actor:
                    self.renderer.RemoveActor(actor)
                    actor = actors.GetNextItem()

                actors2d = self.renderer.GetActors2D()
                actors2d.InitTraversal()
                actor2d = actors2d.GetNextItem()
                while actor2d:
                    self.renderer.RemoveActor2D(actor2d)
                    actor2d = actors2d.GetNextItem()

            # آزاد کردن mapperها و color_mapper
            if self.color_mapper:
                self.color_mapper.SetInputConnection(None)
                # self.color_mapper.Delete()
                # del self.color_mapper
                self.color_mapper = None

            if self.GetImageActor() and self.GetImageActor().GetMapper():
                self.GetImageActor().GetMapper().SetInputConnection(None)
                # self.GetImageActor().GetMapper().Delete()
                # mapper = self.GetImageActor().GetMapper()
                # del mapper

            # آزاد کردن image_reslice و vtk_image_data
            if self.image_reslice:
                self.image_reslice.SetInputData(None)
                # self.image_reslice.Delete()
                # del self.image_reslice
                self.image_reslice = None

            if self.vtk_image_data:
                if self.vtk_image_data.GetPointData() and self.vtk_image_data.GetPointData().GetScalars():
                    self.vtk_image_data.GetPointData().SetScalars(None)  # آزاد کردن scalars بزرگ
                # self.vtk_image_data.Delete()
                # del self.vtk_image_data
                self.vtk_image_data = None

            # آزاد کردن dicom_tags_actors (اگر actorهای متنی دارید)
            # if self.dicom_tags_actors:
            #     for actor in vars(self.dicom_tags_actors).values():
            #         if isinstance(actor, vtk.vtkActor2D):
            #             # actor.Delete()
            #             del actor
            #     self.dicom_tags_actors = None

            # ریست renderer
            if self.renderer:
                self.renderer.ResetCamera()
                # self.renderer.Delete()
                # del self.renderer
                self.renderer = None

            # تنظیم به None برای کمک به GC
            self.metadata = None
            self.metadata_fixed = None

        except Exception as e:
            print(f"Error in cleanup: {e}")

    def clear_boxes(self):
        """تمام باکس‌های رسم‌شده را از رندرر حذف می‌کند."""
        if hasattr(self, "_box_actors") and self._box_actors:
            for a in self._box_actors:
                try:
                    self.renderer.RemoveActor(a)
                except Exception:
                    pass
        self._box_actors = []

    def ijk_to_world(self, i: float, j: float, k: float | None = None, *, y_flip: bool = True):
        """
        تبدیل (i, j, k) در IJK به مختصات World.
        اگر k=None باشد، z بر اساس اسلایس فعلی تنظیم می‌شود.
        y_flip=True یعنی j' = (ny - 1) - j مثل منطق فعلی شما.
        """
        img = self.vtk_image_data
        ox, oy, oz = img.GetOrigin()
        sx, sy, sz = img.GetSpacing()
        nx, ny, nz = img.GetDimensions()

        jj = (ny - 1) - j if y_flip else j

        xw = ox + float(i) * sx
        yw = oy + float(jj) * sy

        if k is None:
            zw = oz + sz * float(self.GetSlice())
        else:
            zw = oz + sz * float(k)

        return xw, yw, zw

    def draw_boxes_ijk(self, boxes_scores: list, color=(0.0, 1.0, 0.0), line_width=2.0):
        """
        boxes_ijk_xyxy: لیستِ باکس‌ها به صورت [[x_min, y_min, x_max, y_max], ...] در دستگاه IJK.
        توجه: چون تصویر روی محور Y فلیپ شده، j' = (ny - 1 - j) اعمال می‌شود.
        هر باکس روی اسلایس فعلی رسم می‌گردد.
        """
        lst_boxes_object = []
        # پاک‌سازی باکس‌های قبلی
        self.clear_boxes()
        self._box_actors = []

        def _actor_for_rect(p0, p1, p2, p3):
            pts = vtk.vtkPoints()
            pts.SetNumberOfPoints(5)
            pts.SetPoint(0, *p0);
            pts.SetPoint(1, *p1);
            pts.SetPoint(2, *p2);
            pts.SetPoint(3, *p3);
            pts.SetPoint(4, *p0)
            lines = vtk.vtkCellArray();
            lines.InsertNextCell(5)
            for i in range(5): lines.InsertCellPoint(i)
            poly = vtk.vtkPolyData();
            poly.SetPoints(pts);
            poly.SetLines(lines)
            mapper = vtk.vtkPolyDataMapper();
            mapper.SetInputData(poly)
            actor = vtk.vtkActor();
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
            prop.SetLineWidth(float(line_width))
            prop.SetOpacity(1.0);
            prop.SetRepresentationToWireframe()
            return actor

        # for box in boxes_ijk_xyxy:
        for box_score in boxes_scores:
            box = box_score['box']
            score = box_score['score']
            classification_label = box_score.get('classification', '')

            if not (isinstance(box, (list, tuple)) and len(box) == 4):
                continue  # رد باکس نامعتبر

            x0_i, y0_j, x1_i, y1_j = map(float, box)

            p0 = self.ijk_to_world(x0_i, y0_j, None, y_flip=True)  # پایین-چپ
            p1 = self.ijk_to_world(x1_i, y0_j, None, y_flip=True)  # پایین-راست
            p2 = self.ijk_to_world(x1_i, y1_j, None, y_flip=True)  # بالا-راست
            p3 = self.ijk_to_world(x0_i, y1_j, None, y_flip=True)  # بالا-چپ

            corner_ijk_points = bbox_corners_ijk([(x0_i, y0_j, 0), (x1_i, y0_j, 0), (x1_i, y1_j, 0), (x0_i, y1_j, 0)])
            print('corner_ijk_points:', corner_ijk_points)

            actor = _actor_for_rect(p0, p1, p2, p3)
            self.renderer.AddActor(actor)
            self._box_actors.append(actor)

            # add text up of box
            box_name = f'Box{len(lst_boxes_object) + 1}, \t\tscore: {score}'
            text_actor = create_text_actor(world_position=((p1[0] + p0[0]) / 2, p1[1] + 2, p1[2]), text=box_name)

            # create box object for manage
            box_object = BoxManager(box_name=box_name, box_name_actor=text_actor, box_actor=actor, status_abnormal=True,
                                    ijk_points=corner_ijk_points, classification_label=classification_label)
            lst_boxes_object.append(box_object)

            self.renderer.AddActor(text_actor)

        # هم‌ترازسازی و رندر
        if hasattr(self, "_sync_all_overlays_extent"):
            self._sync_all_overlays_extent()
        self.renderer.ResetCameraClippingRange()
        self.Render()

        # update ui
        self.vtk_widget.update_boxes_details_ui(lst_boxes_object)
        return lst_boxes_object

    def world_to_ijk(self,
                     xw: float, yw: float, zw: float,
                     *,
                     y_flip: bool = True,
                     clamp: bool = True,
                     as_int: bool = False) -> tuple[float, float, float]:
        """
        World → IJK برای vtkImageData همین ویور.
        - y_flip: اگر True باشد، مثل نمایش تو j' = (ny-1) - j اعمال می‌شود.
        - clamp: به محدوده‌ی تصویر (0..nx-1, 0..ny-1, 0..nz-1) می‌چیند.
        - as_int: اگر True باشد، خروجی را گرد کرده‌ی عدد صحیح برمی‌گرداند.
        """
        img = self.vtk_image_data
        ox, oy, oz = img.GetOrigin()
        sx, sy, sz = img.GetSpacing()
        nx, ny, nz = img.GetDimensions()

        # تبدیل مستقیم
        i = (xw - ox) / sx
        j = (yw - oy) / sy
        k = (zw - oz) / sz

        # فلیپ محور Y (مطابق رسم تو)
        if y_flip:
            j = (ny - 1) - j

        if clamp:
            i = max(0.0, min(i, nx - 1))
            j = max(0.0, min(j, ny - 1))
            k = max(0.0, min(k, nz - 1))

        if as_int:
            return (int(round(i)), int(round(j)), int(round(k)))
        return (float(i), float(j), float(k))

    def get_actor_points_world(self, actor: vtk.vtkActor) -> list[tuple[float, float, float]]:
        """
        نقاط هندسه‌ای که به mapper/actor داده شده‌اند را (در فضای actor) برمی‌گرداند.
        اگر actor ترنسفورم داشته باشد، آن را به World اعمال می‌کنیم.
        """
        mapper = actor.GetMapper()
        poly = mapper.GetInput()  # vtkPolyData
        pts = poly.GetPoints()
        n = pts.GetNumberOfPoints()
        if n <= 0:
            return []

        # نقاط در فضای 'model' هستند؛ اگر actor ترنسفورم داشته باشد، به World ضرب می‌کنیم:
        m = vtk.vtkMatrix4x4()
        actor.GetMatrix(m)  # model→world
        M = np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)], dtype=float)

        out = []
        for i in range(n):
            x, y, z = pts.GetPoint(i)
            v = np.array([x, y, z, 1.0])
            X = M @ v
            out.append((float(X[0]), float(X[1]), float(X[2])))
        return out


class CustomCombineImageViewers(ImageViewer2D):
    def __init__(self, render_window, interactor, height, vtk_image_data1: vtk.vtkImageData, metadata1: dict,
                 vtk_image_data2: vtk.vtkImageData, metadata2: dict, metadata_fixed, apply_default_filter, vtk_widget):

        # vtk_image_data1 = flip_image_y(vtk_image_data1)
        # vtk_image_data2 = flip_image_y(vtk_image_data2)

        self.vtk_image_data1 = vtk_image_data1
        self.metadata1 = metadata1

        # self.vtk_image_data2 = self._preprocess_vtk_image_data(vtk_image_data2)
        # print('vtk_image_data2:", ', vtk_image_data2)
        self.vtk_image_data2 = vtk_image_data2
        # self.vtk_image_data2 = self._preprocess_vtk_image_data(vtk_image_data2)

        self.metadata2 = metadata2

        self.series_showed = None
        super().__init__(render_window, interactor, height, vtk_image_data1, metadata1, metadata_fixed,
                         apply_default_filter, vtk_widget=vtk_widget)

        self.vtk_image_data1 = self.vtk_image_data
        self.metadata1 = self.metadata

        self.vtk_image_data2 = self._preprocess_vtk_image_data(vtk_image_data2)

        self.image_reslice_1 = ImageReslice(self.vtk_image_data1, self.metadata1)
        self.image_reslice_2 = ImageReslice(self.vtk_image_data2, self.metadata2)

    def get_count_of_slices(self):
        count_slices = self.get_count_of_slice_image_1() + self.get_count_of_slice_image_2()
        return count_slices

    def get_count_of_slice_image_1(self):
        return self.vtk_image_data1.GetDimensions()[2]

    def get_count_of_slice_image_2(self):
        return self.vtk_image_data2.GetDimensions()[2]

    def set_slice(self, slice_index):
        # print('slice index:', slice_index, 'skip slics helper:', self.skip_slices)

        if 0 <= slice_index < self.get_count_of_slice_image_1():
            self.skip_slices = 0
            if self.series_showed == 'series_1':
                pass
            else:
                self.change_local_series('series_1')
                self.series_showed = 'series_1'

        else:

            self.skip_slices = self.get_count_of_slice_image_1()
            if self.series_showed == 'series_2':
                pass
            else:
                self.change_local_series('series_2')
                self.series_showed = 'series_2'

        slice_index = slice_index - self.skip_slices
        if not self.flag_set_custom_window_level:
            self.apply_default_window_level(slice_index)
        self.SetSlice(slice_index)
        self.update_corners_actors()
        self.Render()

    def change_local_series(self, series_number):

        if series_number == 'series_1':
            self.image_reslice = self.image_reslice_1

        elif series_number == 'series_2':
            self.image_reslice = self.image_reslice_2

        self.SetInputData(self.image_reslice.GetOutput())  # without color map (window level)
        self.vtk_image_data = self.image_reslice.GetOutput()
        self.metadata = self.image_reslice.metadata
        self.set_color_mapper()

        self.flag_set_custom_window_level = False
        self.zoom_to_fit()

    def reset_image_viewer(self, vtk_image_data, metadata):
        self.series_showed = None
        super().reset_image_viewer(vtk_image_data, metadata)



def bbox_corners_ijk(ijk_list_3d):
    """
    ijk_list_3d: لیستی از نقاط به شکل [i, j, k]
    خروجی: (bottom_left, top_right) در مختصات IJK
    فرض: محور j رو به پایین زیاد می‌شود.
    """
    if not ijk_list_3d:
        raise ValueError("ijk_list_3d is empty")

    is_, js, ks = zip(*ijk_list_3d)
    i_min, i_max = min(is_), max(is_)
    j_min, j_max = min(js), max(js)
    # k = ks[0]  # فرض: همه روی یک اسلایس‌اند

    # bottom_left = (i_min, j_min, k)
    # top_right = (i_max, j_max, k)
    # bottom_left = (i_min, j_min)
    # top_right = (i_max, j_max)
    # return bottom_left, top_right

    return [i_min, j_min, i_max, j_max]