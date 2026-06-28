"""
View creation, toolbar, window/level callbacks, and auto-rotation for
StandardMPRViewer.

Contains ``_setup_ui``, the four ``_create_*_view`` methods, toolbar
creation, W/L and 3D preset callbacks, and auto-rotation timer.

CT-specific camera corrections (Roll/Azimuth) are applied inside the
individual ``_create_*_view`` methods — do NOT remove them.
"""

import logging
import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QComboBox, QHBoxLayout, QVBoxLayout,
    QFrame, QPushButton, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PacsClient.utils.structured_logging import emit_viewer_event

from ..mpr_diagnostic_validator import MPRDiagnosticValidator, DIAG_ENABLED
from ._interactor_styles import VRTInteractorStyle

logger = logging.getLogger(__name__)

import os as _os
# L1 MPR-open optimization (2026-06-28): defer the expensive 3D VRT view (the
# GPU volume upload + first ray-cast — the single biggest cost of opening MPR)
# to an idle callback so the three diagnostic 2D planes (axial/sagittal/coronal)
# paint FIRST. This changes only the *timing* of the 3D pane's construction, not
# any geometry: each view's camera/reslice is computed per-view (independent of
# creation order), and the all-views post-passes (_apply_native_plane_interpolation,
# _capture_baseline_camera_state, _apply_window_level) are 2D-only by design.
# Default ON (2026-06-28: flipped to address the MPR-open freeze) — the 3 diagnostic
# 2D planes appear first and the heavy 3D VRT fills in a moment later. Kill switch
# AIPACS_MPR_DEFER_3D=0 = byte-identical synchronous 4-panel build. Flag AIPACS_MPR_DEFER_3D.
_MPR_DEFER_3D = (_os.getenv("AIPACS_MPR_DEFER_3D", "1") or "1").strip().lower() not in ("0", "false", "no", "off")

# Pre-warm the 2D reslice/render path after MPR open (2026-06-28) so the FIRST
# crosshair drag does not pay a first-touch GPU reslice/shader cost (the reported
# "small lag on the first crossline move, then smooth"). It forces ONE extra
# re-reslice render of each 2D pane at the CURRENT position — identical image, no
# geometry change — deferred to idle so it never adds to the open time. Kill switch
# AIPACS_MPR_PREWARM=0.
_MPR_PREWARM = (_os.getenv("AIPACS_MPR_PREWARM", "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def _emit_geometry_contract_missing_guard(*, feature: str) -> None:
    logger.warning(
        "[GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH] feature=%s reason=local_mpr_view_creation_without_advanced_contract_adapter "
        "fallback_behavior=continue_legacy_mpr_geometry_path action=warn_only",
        feature,
    )

# WL_PRESETS — window/level presets for CT viewing (originally in standard_mpr_viewer.py)
WL_PRESETS = {
    'Auto': None,
    'Brain': {'window': 80, 'level': 40},
    'Subdural': {'window': 200, 'level': 75},
    'Bone': {'window': 2000, 'level': 300},
    'Lung': {'window': 1500, 'level': -600},
    'Abdomen': {'window': 350, 'level': 50},
    'Liver': {'window': 150, 'level': 80},
    'Soft Tissue': {'window': 400, 'level': 50},
}


class _MprViewsMixin:
    """Mixin: UI setup, view creation, toolbar, W/L, auto-rotation."""

    # ------------------------------------------------------------------
    # UI orchestration
    # ------------------------------------------------------------------

    def _setup_ui(self):
        """Setup clean, professional UI inspired by RadiAnt/Horos"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                background-color: #1a1a1a;
            }
        """)

        content_container = QWidget()
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        views_container = QWidget()
        views_container.setStyleSheet("background-color: #000000;")
        views_layout = QGridLayout(views_container)
        views_layout.setContentsMargins(2, 2, 2, 2)
        views_layout.setSpacing(2)
        self._views_layout = views_layout

        layout_views = getattr(self, '_layout_views', None)
        if layout_views:
            # Projection / subset mode (MIP / MinIP / Thick Slab from the dropdown): build ONLY the
            # requested 1–3 view(s) in a single row — no 3D pane, never the full 4-panel.
            _creators = {
                'axial': self._create_axial_view,
                'sagittal': self._create_sagittal_view,
                'coronal': self._create_coronal_view,
            }
            for _col, _vname in enumerate(layout_views):
                _creator = _creators.get(_vname)
                if _creator is not None:
                    _creator(views_layout, 0, _col)
            logger.info("[ZETA_MPR] subset layout built: %s (slab=%s)", layout_views,
                        getattr(self, '_slab_mode', None))
        elif _MPR_DEFER_3D:
            # L1 (AIPACS_MPR_DEFER_3D): build the three diagnostic 2D planes now and
            # defer the expensive 3D VRT (GPU upload + first ray-cast) to an idle
            # callback so the planes are shown first. The 3D cell is held by a
            # lightweight placeholder so the 2x2 grid does not jump when the real
            # 3D pane lands. Geometry is unaffected — see the module-level note.
            self._create_axial_view(views_layout, 0, 0)
            self._create_sagittal_view(views_layout, 1, 0)
            self._create_coronal_view(views_layout, 1, 1)
            self._install_deferred_3d_placeholder(views_layout, 0, 1)
            self._deferred_3d_pending = True
            QTimer.singleShot(0, self._build_deferred_3d_view)
        else:
            self._create_axial_view(views_layout, 0, 0)
            self._create_3d_view(views_layout, 0, 1)
            self._create_sagittal_view(views_layout, 1, 0)
            self._create_coronal_view(views_layout, 1, 1)

        # The NATIVE-plane pane (the one looking down the acquired-slice axis) must show the
        # ORIGINAL acquired slices (nearest-neighbour, no blending); the other two panes are MPR
        # reconstructions (linear). Hardcoding interpolation per pane name made a routed
        # sagittal/coronal-native series interpolate its native plane — this re-assigns by role.
        # Runs AFTER all cameras/routing are set so _view_axes() is populated for every view.
        self._apply_native_plane_interpolation()

        # Projection mode: apply the requested slab (max=MIP / min=MinIP / mean=Thick Slab) to the
        # built view(s). Reuses the existing _apply_slab_projection (sets vtkImageResliceMapper
        # SetSlabThickness + SetSlabTypeToMax/Min/Mean); it iterates only views present in
        # self.viewers, so in subset mode it touches exactly the requested pane(s). No-op when
        # slab_mode is None (full 4-panel MPR unchanged).
        _slab_mode = getattr(self, '_slab_mode', None)
        if _slab_mode and hasattr(self, '_apply_slab_projection'):
            try:
                _thk = getattr(self, '_slab_thickness_mm', None)
                if not _thk or _thk <= 0:
                    _thk = 10.0
                self._apply_slab_projection(_slab_mode, float(_thk))
            except Exception as exc:
                logger.warning("[ZETA_MPR] slab projection apply failed: %r", exc)

        content_layout.addWidget(views_container, stretch=1)
        main_layout.addWidget(content_container)
        self.setLayout(main_layout)

        # Capture baseline camera state AFTER all views created + CT corrections applied
        self._capture_baseline_camera_state()

        # Diagnostic Validator (activate with ZETA_MPR_DIAG=1)
        self._diag = MPRDiagnosticValidator(self, auto_validate=True)
        self._diag.capture_baseline()
        if DIAG_ENABLED:
            self._diag.install_corner_markers()
            self._diag.install_diag_overlays()

        # Pre-warm the 2D reslice/render path once the UI is idle, so the FIRST
        # crosshair drag is smooth (issue 2). Deferred → no added open time.
        if _MPR_PREWARM:
            QTimer.singleShot(0, self._prewarm_mpr_reslice)

    def _prewarm_mpr_reslice(self):
        """Force one re-reslice render of each 2D pane at the CURRENT position.

        Warms VTK's reslice/GPU path so the user's first crosshair drag does not
        pay a first-touch cost. Identical image (no camera/geometry change),
        idempotent, and teardown-safe (a close mid-defer is swallowed)."""
        if not _MPR_PREWARM:
            return
        try:
            for vn in ('axial', 'sagittal', 'coronal'):
                view = (getattr(self, 'viewers', None) or {}).get(vn)
                if not view:
                    continue
                mapper = view.get('mapper')
                if mapper is not None:
                    try:
                        mapper.Modified()   # mark dirty → next render re-reslices (warms the path)
                    except Exception:
                        pass
                try:
                    view['widget'].GetRenderWindow().Render()
                except Exception:
                    pass
        except RuntimeError:
            return  # MPR closed before the idle pre-warm fired — benign
        except Exception as exc:
            logger.debug("[ZETA_MPR] reslice pre-warm skipped: %r", exc)

    def _create_toolbar(self):
        """Create clean, minimal toolbar like professional DICOM viewers"""
        logger.info("Creating professional toolbar...")

        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("""
            QWidget {
                background-color: #252525;
                border-bottom: 1px solid #3a3a3a;
            }
        """)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        # Window/Level
        wl_label = QLabel("W/L:")
        wl_label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(wl_label)

        self.wl_combo = QComboBox()
        self.wl_combo.addItems(list(WL_PRESETS.keys()))
        self.wl_combo.setCurrentText('Auto')
        self.wl_combo.currentTextChanged.connect(self._on_wl_changed)
        self.wl_combo.setStyleSheet("""
            QComboBox {
                background: #333; color: #fff; border: 1px solid #444;
                border-radius: 3px; padding: 4px 24px 4px 8px;
                min-width: 90px; font-size: 12px;
            }
            QComboBox:hover { border-color: #666; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox::down-arrow {
                image: none; border-left: 4px solid transparent;
                border-right: 4px solid transparent; border-top: 5px solid #888;
            }
            QComboBox QAbstractItemView {
                background: #333; color: #fff; border: 1px solid #444;
                selection-background-color: #0066cc;
            }
        """)
        layout.addWidget(self.wl_combo)

        layout.addWidget(self._create_separator())

        # 3D Preset
        vol_label = QLabel("3D:")
        vol_label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(vol_label)

        self.vol_combo = QComboBox()
        all_presets = self.preset_manager.get_all_preset_names()
        self.vol_combo.addItems(all_presets)
        best_preset = self._get_best_3d_preset()
        if best_preset in all_presets:
            self.vol_combo.setCurrentText(best_preset)
        self.vol_combo.currentTextChanged.connect(self._on_volume_preset_changed)
        self.vol_combo.setStyleSheet(self.wl_combo.styleSheet())
        layout.addWidget(self.vol_combo)

        layout.addStretch()

        # Crosshairs button
        self.crosshair_btn = QPushButton("Crosshairs")
        self.crosshair_btn.setCheckable(True)
        self.crosshair_btn.setChecked(True)
        self.crosshair_btn.clicked.connect(self._toggle_crosshairs)
        self.crosshair_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.crosshair_btn.customContextMenuRequested.connect(self._show_crosshair_settings_menu)
        self.crosshair_btn.setCursor(Qt.PointingHandCursor)
        self.crosshair_btn.setMinimumWidth(120)
        self.crosshair_btn.setStyleSheet("""
            QPushButton {
                background: #333; color: #ccc; border: 1px solid #444;
                border-radius: 3px; padding: 5px 20px; font-size: 12px;
            }
            QPushButton:hover { background: #3a3a3a; border-color: #555; }
            QPushButton:checked { background: #0066cc; color: #fff; border-color: #0077ee; }
            QPushButton:checked:hover { background: #0077dd; }
        """)
        layout.addWidget(self.crosshair_btn)

        # Reset button
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset_rendering)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background: #333; color: #ccc; border: 1px solid #444;
                border-radius: 3px; padding: 5px 14px; font-size: 12px;
            }
            QPushButton:hover { background: #3a3a3a; border-color: #555; }
        """)
        layout.addWidget(self.reset_btn)

        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._close_mpr)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: #8b0000; color: #fff; border: 1px solid #a00;
                border-radius: 3px; padding: 5px 14px; font-size: 12px;
            }
            QPushButton:hover { background: #a00000; }
        """)
        layout.addWidget(self.close_btn)

        return toolbar

    def _create_separator(self):
        """Create a vertical separator line"""
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #3a3a3a;")
        return sep

    # ------------------------------------------------------------------
    # View creation
    # ------------------------------------------------------------------

    def _apply_native_plane_interpolation(self):
        """Set each 2D pane's image interpolation by ROLE (native vs reconstructed), not pane name.

        The NATIVE plane is the pane whose through-plane (look) axis is the volume's acquired-slice
        axis — world axis 2 (= A's ``slice_axis_lps``; for a legacy axial-native volume this is the
        axial stacking axis). That pane shows the ORIGINAL acquired slices, so it uses NEAREST
        interpolation (no blending across acquired slices). The other two panes are MPR
        reconstructions and use LINEAR (smooth reslice). For axial-native input this reproduces the
        original per-pane setup (axial=nearest, sagittal/coronal=linear) → no change; for a routed
        sagittal/coronal-native series it moves NEAREST onto the ACTUAL native pane so its native
        plane is no longer interpolated, and makes the (now reconstructed) axial pane linear.
        """
        NATIVE_SLICE_AXIS = 2  # vtkImageData 3rd dim / A[:,2] = acquired-slice direction
        for view in ('axial', 'sagittal', 'coronal'):
            info = self.viewers.get(view)
            if not info:
                continue
            actor = info.get('actor')
            if actor is None:
                continue
            try:
                look_axis = int(self._view_axes(view)[0])
                prop = actor.GetProperty()
                mapper = info.get('mapper')
                if look_axis == NATIVE_SLICE_AXIS:
                    # Native plane: original acquired slices — nearest + native-resolution sampling
                    # (matches how the axial pane was treated when axial was always native).
                    prop.SetInterpolationTypeToNearest()
                    if mapper is not None and hasattr(mapper, 'SetResampleToScreenPixels'):
                        mapper.SetResampleToScreenPixels(False)
                    role = "native(nearest)"
                else:
                    # Reconstructed plane: smooth MPR — linear + screen-pixel resample (the
                    # original sagittal/coronal default).
                    prop.SetInterpolationTypeToLinear()
                    if mapper is not None and hasattr(mapper, 'SetResampleToScreenPixels'):
                        mapper.SetResampleToScreenPixels(True)
                    role = "reconstructed(linear)"
                logger.info("[ZETA_MPR] %s pane interpolation -> %s (look_axis=%d)", view, role, look_axis)
            except Exception as exc:
                logger.debug("[ZETA_MPR] native-plane interpolation set failed for %s: %r", view, exc)

    def _create_axial_view(self, layout, row, col):
        """Create axial view (XY plane) - Original slices, NO interpolation between slices"""
        emit_viewer_event(
            logger,
            "ZETA_NPR_VIEWPORT_ASSIGNMENT",
            stage="create_view",
            view_name="axial",
            grid_row=row,
            grid_col=col,
            source_role="input_volume_primary",
            interpolation="nearest",
            used_default_axial=True,
            fallback_reason="fixed_layout_primary_source_view",
        )
        _emit_geometry_contract_missing_guard(feature="zeta_mpr_create_axial_view")
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("border: none; background: black;")
        container_layout.addWidget(vtk_widget)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)

        slice_mapper = vtk.vtkImageResliceMapper()
        slice_mapper.SetInputData(self.image_data)
        slice_mapper.SliceFacesCameraOn()
        slice_mapper.SliceAtFocalPointOn()
        slice_mapper.SetResampleToScreenPixels(False)

        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(slice_mapper)

        window, level = self._get_initial_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        image_slice.GetProperty().SetInterpolationTypeToNearest()

        renderer.AddViewProp(image_slice)

        camera = renderer.GetActiveCamera()
        camera_pos, focal_point, view_up = self._get_camera_vectors_for_view('axial')
        camera.SetPosition(camera_pos)
        camera.SetFocalPoint(focal_point)
        camera.SetViewUp(view_up)
        camera.ParallelProjectionOn()
        renderer.ResetCamera()
        camera.Zoom(1.2)

        vtk_widget.Initialize()
        vtk_widget.Start()

        self._add_click_handler(vtk_widget, renderer, 'axial')

        self.viewers['axial'] = {
            'widget': vtk_widget, 'renderer': renderer,
            'actor': image_slice, 'mapper': slice_mapper
        }
        self._register_view('axial', container, vtk_widget, row, col)
        self._create_crosshairs(renderer, 'axial')
        self._create_slice_info_text(renderer, 'axial')
        layout.addWidget(container, row, col)

    def _create_sagittal_view(self, layout, row, col):
        """Create sagittal view (YZ plane) - MPR reconstructed with interpolation"""
        emit_viewer_event(
            logger,
            "ZETA_NPR_VIEWPORT_ASSIGNMENT",
            stage="create_view",
            view_name="sagittal",
            grid_row=row,
            grid_col=col,
            source_role="mpr_reconstructed",
            interpolation="linear",
            used_default_axial=False,
            fallback_reason="none",
        )
        _emit_geometry_contract_missing_guard(feature="zeta_mpr_create_sagittal_view")
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor { border: none; background: black; }
        """)
        vtk_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        vtk_widget.customContextMenuRequested.connect(
            lambda pos, w=vtk_widget: self._show_vrt_preset_menu(w, pos)
        )
        container_layout.addWidget(vtk_widget)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)

        slice_mapper = vtk.vtkImageResliceMapper()
        slice_mapper.SetInputData(self.image_data)
        slice_mapper.SliceFacesCameraOn()
        slice_mapper.SliceAtFocalPointOn()

        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(slice_mapper)

        window, level = self._get_initial_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        image_slice.GetProperty().SetInterpolationTypeToLinear()

        renderer.AddViewProp(image_slice)

        camera = renderer.GetActiveCamera()
        camera_pos, focal_point, view_up = self._get_camera_vectors_for_view('sagittal')
        camera.SetPosition(camera_pos)
        camera.SetFocalPoint(focal_point)
        camera.SetViewUp(view_up)
        camera.ParallelProjectionOn()

        # CT-specific camera correction
        if self._needs_radiological_correction():
            camera.Roll(180)

        renderer.ResetCamera()
        camera.Zoom(1.2)

        vtk_widget.Initialize()
        vtk_widget.Start()

        self._add_click_handler(vtk_widget, renderer, 'sagittal')

        self.viewers['sagittal'] = {
            'widget': vtk_widget, 'renderer': renderer,
            'actor': image_slice, 'mapper': slice_mapper
        }
        self._register_view('sagittal', container, vtk_widget, row, col)
        self._create_crosshairs(renderer, 'sagittal')
        self._create_slice_info_text(renderer, 'sagittal')
        layout.addWidget(container, row, col)

    def _create_coronal_view(self, layout, row, col):
        """Create coronal view (XZ plane) - MPR reconstructed with interpolation"""
        emit_viewer_event(
            logger,
            "ZETA_NPR_VIEWPORT_ASSIGNMENT",
            stage="create_view",
            view_name="coronal",
            grid_row=row,
            grid_col=col,
            source_role="mpr_reconstructed",
            interpolation="linear",
            used_default_axial=False,
            fallback_reason="none",
        )
        _emit_geometry_contract_missing_guard(feature="zeta_mpr_create_coronal_view")
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor { border: none; background: black; }
        """)
        container_layout.addWidget(vtk_widget)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)

        slice_mapper = vtk.vtkImageResliceMapper()
        slice_mapper.SetInputData(self.image_data)
        slice_mapper.SliceFacesCameraOn()
        slice_mapper.SliceAtFocalPointOn()

        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(slice_mapper)

        window, level = self._get_initial_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        image_slice.GetProperty().SetInterpolationTypeToLinear()

        renderer.AddViewProp(image_slice)

        camera = renderer.GetActiveCamera()
        camera_pos, focal_point, view_up = self._get_camera_vectors_for_view('coronal')
        camera.SetPosition(camera_pos)
        camera.SetFocalPoint(focal_point)
        camera.SetViewUp(view_up)
        camera.ParallelProjectionOn()

        # CT-specific camera corrections
        if self._needs_radiological_correction():
            camera.Azimuth(180)
            camera.Roll(180)

        renderer.ResetCamera()
        camera.Zoom(1.2)

        vtk_widget.Initialize()
        vtk_widget.Start()

        self._add_click_handler(vtk_widget, renderer, 'coronal')

        self.viewers['coronal'] = {
            'widget': vtk_widget, 'renderer': renderer,
            'actor': image_slice, 'mapper': slice_mapper
        }
        self._register_view('coronal', container, vtk_widget, row, col)
        self._create_crosshairs(renderer, 'coronal')
        self._create_slice_info_text(renderer, 'coronal')
        layout.addWidget(container, row, col)

    def _create_3d_view(self, layout, row, col):
        """Create advanced 3D volume view with best quality"""
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor { border: none; background: black; }
        """)
        vtk_widget.setContextMenuPolicy(Qt.PreventContextMenu)
        container_layout.addWidget(vtk_widget)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0.1, 0.1, 0.1)
        renderer.SetBackground2(0.0, 0.0, 0.0)
        renderer.GradientBackgroundOn()
        vtk_widget.GetRenderWindow().AddRenderer(renderer)

        vtk_widget.GetRenderWindow().SetMultiSamples(4)

        volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        volume_mapper.SetInputData(self.image_data)
        # Interactive VRT quality (2026-06-14). On a large volume (e.g. 46293 = 512x512x198)
        # the previous fixed config — AutoAdjustSampleDistances OFF + a fine fixed SampleDistance
        # — ray-cast at FULL quality on every rotation frame, so rotation could never go coarse and
        # felt slow. The trackball style already raises the render window's desired update rate
        # during a drag; enabling auto-adjust lets the GPU mapper honor it: COARSE while rotating
        # (smooth), FULL quality the instant the camera settles (no still-image regression). The
        # fixed SampleDistance(0.5) stays as the at-rest target. Reversible: set
        # AIPACS_ZETA_MPR_VRT_ADAPTIVE=0 to restore the legacy fixed-quality-every-frame behavior.
        import os as _os
        _vrt_adaptive = _os.environ.get("AIPACS_ZETA_MPR_VRT_ADAPTIVE", "1").strip().lower() \
            not in ("0", "false", "no", "off")
        volume_mapper.SetAutoAdjustSampleDistances(1 if _vrt_adaptive else 0)
        volume_mapper.SetSampleDistance(0.5)
        volume_mapper.SetImageSampleDistance(1.0)
        volume_mapper.SetMaxMemoryInBytes(1024 * 1024 * 512)
        volume_mapper.SetBlendModeToComposite()

        volume_property = vtk.vtkVolumeProperty()
        volume_property.SetInterpolationTypeToLinear()
        volume_property.ShadeOn()
        volume_property.SetAmbient(0.2)
        volume_property.SetDiffuse(0.7)
        volume_property.SetSpecular(0.3)
        volume_property.SetSpecularPower(20)
        volume_property.SetDisableGradientOpacity(0)

        self.volume_property = volume_property

        best_preset = self._get_best_3d_preset()
        self.current_3d_preset = best_preset
        self.preset_manager.apply_preset(volume_property, best_preset, self.scalar_range)

        volume = vtk.vtkVolume()
        volume.SetMapper(volume_mapper)
        volume.SetProperty(volume_property)
        renderer.AddVolume(volume)

        camera = renderer.GetActiveCamera()
        renderer.ResetCamera()
        camera.SetViewUp(0, 0, 1)

        bounds = self.image_data.GetBounds()
        distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.0

        camera.SetPosition(
            self.center[0] + distance * 0.7,
            self.center[1] + distance * 1.2,
            self.center[2] + distance * 0.4
        )
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])

        if self._needs_radiological_correction():
            camera.Elevation(15)
            camera.Roll(180)
            camera.Zoom(1.3)
        else:
            camera.Zoom(1.2)

        light1 = vtk.vtkLight()
        light1.SetPosition(self.center[0] + 500, self.center[1] + 500, self.center[2] + 500)
        light1.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        light1.SetColor(1.0, 1.0, 1.0)
        light1.SetIntensity(0.8)
        renderer.AddLight(light1)

        light2 = vtk.vtkLight()
        light2.SetPosition(self.center[0] - 500, self.center[1] - 500, self.center[2])
        light2.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        light2.SetColor(0.8, 0.8, 1.0)
        light2.SetIntensity(0.4)
        renderer.AddLight(light2)

        interactor = vtk_widget.GetRenderWindow().GetInteractor()
        style = VRTInteractorStyle(self, vtk_widget)
        interactor.SetInteractorStyle(style)

        if _vrt_adaptive:
            # Target ~15 fps while interacting (mapper goes coarse), refine at rest. Pairs with
            # AutoAdjustSampleDistances above. Guarded so a VTK build without these setters can't
            # break viewer creation.
            try:
                interactor.SetDesiredUpdateRate(15.0)
                interactor.SetStillUpdateRate(0.001)
            except Exception:
                pass

        vtk_widget.Initialize()
        vtk_widget.Start()

        self.viewers['3d'] = {
            'widget': vtk_widget, 'renderer': renderer,
            'volume': volume, 'property': volume_property,
            'mapper': volume_mapper, 'camera': camera, 'style': style
        }
        self._register_view('3d', container, vtk_widget, row, col)
        self.setup_auto_rotation()
        layout.addWidget(container, row, col)

    # ------------------------------------------------------------------
    # Deferred 3D VRT (L1 — AIPACS_MPR_DEFER_3D). Only the *timing* of the 3D
    # view's construction changes; the placeholder holds its grid cell so the
    # 2D planes do not reflow, and the build is teardown-safe (a close during
    # the defer must never touch a deleted VTK/Qt object).
    # ------------------------------------------------------------------

    def _install_deferred_3d_placeholder(self, layout, row, col):
        """Occupy the 3D grid cell with a lightweight 'Rendering 3D…' frame so the
        2x2 layout is stable until the deferred VRT pane replaces it."""
        try:
            placeholder = QFrame()
            placeholder.setStyleSheet("background: #000; border: 1px solid #333;")
            # Fill the 3D cell exactly like the final VTK pane (Expanding) so the
            # 2x2 grid does NOT reflow/jump when the real 3D widget replaces it.
            from PySide6.QtWidgets import QSizePolicy
            placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            ph_layout = QVBoxLayout(placeholder)
            ph_layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel("Rendering 3D…")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "color: #6b7785; font-size: 12px; background: transparent; border: none;"
            )
            ph_layout.addWidget(label)
            layout.addWidget(placeholder, row, col)
            self._deferred_3d_placeholder = placeholder
        except Exception as exc:
            self._deferred_3d_placeholder = None
            logger.debug("[ZETA_MPR] 3D placeholder install failed (non-fatal): %r", exc)

    def _build_deferred_3d_view(self):
        """Idle callback: build the deferred 3D VRT after the 2D planes are shown.

        Teardown-safe: bails if MPR was cleaned up before this fires (the pending
        flag is cleared in ``cleanup``) or if the underlying C++ widget has been
        deleted (closing MPR during the brief defer → benign RuntimeError, swallowed
        like the project's other VTK teardown races)."""
        if not getattr(self, '_deferred_3d_pending', False):
            return
        self._deferred_3d_pending = False
        try:
            layout = getattr(self, '_views_layout', None)
            if layout is None:
                return
            # Drop the placeholder, then build the real 3D into the same cell (0,1).
            placeholder = getattr(self, '_deferred_3d_placeholder', None)
            if placeholder is not None:
                try:
                    layout.removeWidget(placeholder)
                    placeholder.setParent(None)
                    placeholder.deleteLater()
                except RuntimeError:
                    pass
                self._deferred_3d_placeholder = None
            self._create_3d_view(layout, 0, 1)
            logger.info("[ZETA_MPR] deferred 3D VRT view built (L1)")
        except RuntimeError as exc:
            # Deleted C++ object mid-build (MPR closed during the defer) — benign.
            logger.debug("[ZETA_MPR] deferred 3D build skipped (teardown race): %r", exc)
        except Exception as exc:
            logger.warning("[ZETA_MPR] deferred 3D build failed: %r", exc)

    # ------------------------------------------------------------------
    # Volume / WL preset callbacks
    # ------------------------------------------------------------------

    def _apply_volume_preset(self, volume_property, preset_name):
        """Apply a volume preset to volume property using preset manager"""
        success = self.preset_manager.apply_preset(volume_property, preset_name, self.scalar_range)
        if not success:
            logger.warning(f"Failed to apply preset {preset_name}")
        else:
            self.current_3d_preset = preset_name
            logger.debug(f"Applied volume preset: {preset_name}")

    def _on_wl_changed(self, preset_name):
        """Handle window/level preset change - applies globally"""
        preset = WL_PRESETS[preset_name]

        if preset is None:
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
        else:
            window = preset['window']
            level = preset['level']

        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name in self.viewers:
                actor = self.viewers[view_name]['actor']
                actor.GetProperty().SetColorWindow(window)
                actor.GetProperty().SetColorLevel(level)
                renderer = self.viewers[view_name]['renderer']
                renderer.GetRenderWindow().Render()

        try:
            parent = self.parentWidget()
            if parent:
                parent_layout = parent.layout()
                if parent_layout:
                    for i in range(parent_layout.count()):
                        item = parent_layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            if hasattr(widget, 'set_window_level') and widget != self:
                                widget.set_window_level(window, level)
        except Exception as e:
            logger.debug(f"Could not update original viewer W/L: {e}")

        logger.info(f"Applied W/L preset: {preset_name} (W={window}, L={level})")

    def _on_volume_preset_changed(self, preset_name):
        """Handle 3D volume preset change"""
        if '3d' not in self.viewers:
            return
        volume_property = self.viewers['3d']['property']
        self._apply_volume_preset(volume_property, preset_name)
        renderer = self.viewers['3d']['renderer']
        renderer.GetRenderWindow().Render()
        logger.info(f"Applied 3D preset: {preset_name}")

    # ------------------------------------------------------------------
    # Auto-rotation
    # ------------------------------------------------------------------

    def setup_auto_rotation(self):
        """Setup auto-rotation for the 3D view.

        Auto-rotation is **OFF by default** (performance + stability). When on, a 30 ms QTimer
        (~33 fps) continuously volume-renders the 3D pane until the first user interaction —
        that drains CPU/GPU at idle, makes the 2D panes choppy while it spins, and widens the
        teardown race (a rotation tick can fire into a finalizing VTK render window → the
        0x8001010d crash family). Opt back in with env ``AIPACS_ZETA_MPR_AUTOROTATE=1``.

        The timer object is still created (so ``stop_auto_rotation`` / ``cleanup`` and any future
        UI toggle stay valid); it is only **started** when explicitly enabled.
        """
        if '3d' not in self.viewers:
            return
        self.auto_rotation_timer = QTimer(self)
        self.auto_rotation_timer.timeout.connect(self.auto_rotate_step)
        self.auto_rotation_timer.setInterval(30)
        import os as _os
        enabled = _os.environ.get("AIPACS_ZETA_MPR_AUTOROTATE", "0") == "1"
        self.auto_rotation_active = enabled
        if enabled:
            self.auto_rotation_timer.start()
            logger.info("Auto-rotation enabled for 3D view (AIPACS_ZETA_MPR_AUTOROTATE=1) - stops on user interaction")
        else:
            logger.info("Auto-rotation disabled by default (set AIPACS_ZETA_MPR_AUTOROTATE=1 to enable)")

    def auto_rotate_step(self):
        """Perform one step of automatic rotation"""
        if not self.auto_rotation_active or '3d' not in self.viewers:
            return
        try:
            camera = self.viewers['3d']['camera']
            camera.Azimuth(0.5)
            renderer = self.viewers['3d']['renderer']
            renderer.GetRenderWindow().Render()
        except Exception as e:
            logger.debug(f"Auto-rotation step error: {e}")

    def stop_auto_rotation(self):
        """Stop the automatic rotation"""
        if self.auto_rotation_timer and self.auto_rotation_active:
            self.auto_rotation_active = False
            self.auto_rotation_timer.stop()
            logger.info("Auto-rotation stopped due to user interaction")
