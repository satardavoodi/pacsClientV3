"""
Camera state mixin for VTKWidget.
capture, restore, schedule_camera_restore, save_status_camera.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class _VWCameraMixin:
    """Camera state: capture, restore, schedule_camera_restore."""

    def _capture_camera_state(self):
        try:
            if self.image_viewer is None:
                return None
            camera = self.image_viewer.renderer.GetActiveCamera()
            if not camera:
                return None
            state = {
                'parallel_scale': camera.GetParallelScale(),
                'position': camera.GetPosition(),
                'focal_point': camera.GetFocalPoint(),
                'view_up': camera.GetViewUp(),
                'clipping_range': camera.GetClippingRange(),
            }
            # ├ت┼ôظخ Update protected scale when capturing state
            self._protected_parallel_scale = state['parallel_scale']
            logger.debug(f"[_capture_camera_state] Protected scale saved: {self._protected_parallel_scale}")
            return state
        except Exception:
            return None

    def _restore_camera_state(self, state):
        if not state or self.image_viewer is None:
            return
        try:
            camera = self.image_viewer.renderer.GetActiveCamera()
            if camera:
                camera.SetParallelScale(state['parallel_scale'])
                camera.SetPosition(state['position'])
                # ├ت┼ôظخ Update protected scale when restoring state
                self._protected_parallel_scale = state['parallel_scale']
                logger.debug(f"[_restore_camera_state] Protected scale restored: {self._protected_parallel_scale}")
                camera.SetFocalPoint(state['focal_point'])
                camera.SetViewUp(state['view_up'])
                camera.SetClippingRange(state['clipping_range'])
                self.image_viewer.renderer.ResetCameraClippingRange()
        except Exception:
            pass

    def _schedule_camera_restore(self, state):
        if not state or self.image_viewer is None:
            return

        gen = getattr(self, '_camera_restore_generation', 0)

        def _restore():
            if getattr(self, '_camera_restore_generation', 0) != gen:
                logger.debug(
                    f"[_schedule_camera_restore] Skipping stale restore (gen={gen} current={self._camera_restore_generation})"
                )
                return
            self._restore_camera_state(state)
            try:
                self.image_viewer.Render()
            except Exception:
                pass

        try:
            QTimer.singleShot(0, _restore)
            QTimer.singleShot(50, _restore)
        except Exception:
            pass

    def save_status_camera(self, image_viewer):
        if self._qt_bridge_active:
            # Qt bridge has a mock camera; just store a neutral view-up
            self.initial_view_up_camera = (0, -1, 0)
            return
        camera = image_viewer.renderer.GetActiveCamera()
        self.initial_view_up_camera = camera.GetViewUp()
