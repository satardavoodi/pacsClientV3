"""
Coordinate Utilities — Accurate widget-to-image coordinate conversion.

This module provides the canonical coordinate conversion pipeline for the
3D Cursor system. It replaces the per-picker inline conversion with a
single shared, high-accuracy implementation.

The conversion uses VTK's renderer DisplayToWorld projection (which uses
the camera's focal plane) instead of vtkWorldPointPicker (which can have
depth-related offsets on 2D image views).

Accuracy is critical: all downstream calculations (nipple distance,
arc computation, view correspondence) depend on these coordinates.
"""

from __future__ import annotations

from typing import Tuple, Optional


def widget_to_image_coords(vtk_widget, wx: float, wy: float) -> Tuple[float, float]:
    """
    Convert widget (screen) coordinates to DICOM image pixel coordinates.

    Uses the renderer's DisplayToWorld conversion which projects from the
    display point through the camera's focal plane onto the image. This is
    more accurate than vtkWorldPointPicker for 2D image viewers because it
    avoids Z-depth picking ambiguity.

    Args:
        vtk_widget: The VTK widget (has .image_viewer with .renderer, .world_to_ijk)
        wx: Widget X coordinate (from mouse event)
        wy: Widget Y coordinate (from mouse event)

    Returns:
        (img_x, img_y) in DICOM pixel coordinates.
    """
    # Method 1: Renderer DisplayToWorld (most accurate for 2D viewers)
    result = _convert_via_display_to_world(vtk_widget, wx, wy)
    if result is not None:
        return result

    # Method 2: vtkWorldPointPicker fallback
    result = _convert_via_world_picker(vtk_widget, wx, wy)
    if result is not None:
        return result

    # Method 3: Proportional mapping fallback
    result = _convert_proportional(vtk_widget, wx, wy)
    if result is not None:
        return result

    # Last resort: raw widget coords
    return (float(wx), float(wy))


def _convert_via_display_to_world(vtk_widget, wx: float, wy: float) -> Optional[Tuple[float, float]]:
    """
    Use renderer.DisplayToWorld for accurate 2D image coordinate conversion.

    This method:
    1. Sets the display point to (wx, widget_h - wy, 0) — VTK uses bottom-left origin.
    2. Converts display → world using the camera's projection.
    3. Converts world → ijk using the image viewer's transform.

    This avoids vtkWorldPointPicker's depth-picking issues on 2D mammogram views.
    """
    try:
        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return None

        renderer = getattr(iv, 'renderer', None)
        world_to_ijk = getattr(iv, 'world_to_ijk', None)
        if renderer is None or not callable(world_to_ijk):
            return None

        widget_h = float(max(1, vtk_widget.height()))
        widget_w = float(max(1, vtk_widget.width()))

        # VTK display coordinates have origin at bottom-left
        display_x = float(wx)
        display_y = float(widget_h - wy)

        # Use the renderer's coordinate system to convert display → world.
        # SetDisplayPoint + DisplayToWorld uses the camera's focal plane depth.
        coordinate = renderer.GetRenderWindow().GetInteractor()
        if coordinate is None:
            # Fallback: use renderer directly
            renderer.SetDisplayPoint(display_x, display_y, 0.0)
            renderer.DisplayToWorld()
            world_pt = renderer.GetWorldPoint()
            # world_pt is (x, y, z, w) — homogeneous coordinates
            if world_pt[3] != 0.0:
                wx_world = world_pt[0] / world_pt[3]
                wy_world = world_pt[1] / world_pt[3]
                wz_world = world_pt[2] / world_pt[3]
            else:
                return None
        else:
            # Use renderer's coordinate conversion directly
            renderer.SetDisplayPoint(display_x, display_y, 0.0)
            renderer.DisplayToWorld()
            world_pt = renderer.GetWorldPoint()
            if world_pt[3] != 0.0:
                wx_world = world_pt[0] / world_pt[3]
                wy_world = world_pt[1] / world_pt[3]
                wz_world = world_pt[2] / world_pt[3]
            else:
                return None

        # World → IJK
        i, j, _k = world_to_ijk(xw=wx_world, yw=wy_world, zw=wz_world, y_flip=True)

        # Clamp to image bounds
        img_x, img_y = _clamp_to_image(iv, float(i), float(j))
        return (img_x, img_y)

    except Exception as e:
        print(f"[3D-Cursor][COORD] DisplayToWorld conversion failed: {e}")
        return None


def _convert_via_world_picker(vtk_widget, wx: float, wy: float) -> Optional[Tuple[float, float]]:
    """
    Fallback: use vtkWorldPointPicker (less accurate but widely supported).

    Uses a vtkCellPicker with tolerance=0 for better accuracy on the image plane.
    """
    try:
        import vtk as _vtk

        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return None

        renderer = getattr(iv, 'renderer', None)
        world_to_ijk = getattr(iv, 'world_to_ijk', None)
        if renderer is None or not callable(world_to_ijk):
            return None

        widget_h = float(max(1, vtk_widget.height()))

        # Use vtkCellPicker (more precise than vtkWorldPointPicker for image data)
        picker = _vtk.vtkCellPicker()
        picker.SetTolerance(0.001)
        ok = picker.Pick(float(wx), float(widget_h - wy), 0.0, renderer)

        if ok:
            w_pt = picker.GetPickPosition()
        else:
            # Fall back to vtkWorldPointPicker (always returns a position)
            wpicker = _vtk.vtkWorldPointPicker()
            wpicker.Pick(float(wx), float(widget_h - wy), 0.0, renderer)
            w_pt = wpicker.GetPickPosition()

        i, j, _k = world_to_ijk(xw=w_pt[0], yw=w_pt[1], zw=w_pt[2], y_flip=True)

        # Clamp to image bounds
        img_x, img_y = _clamp_to_image(iv, float(i), float(j))
        return (img_x, img_y)

    except Exception as e:
        print(f"[3D-Cursor][COORD] WorldPicker conversion failed: {e}")
        return None


def _convert_proportional(vtk_widget, wx: float, wy: float) -> Optional[Tuple[float, float]]:
    """
    Fallback: proportional mapping based on widget/image dimensions.

    This is a rough approximation that ignores zoom/pan but is better than
    returning raw widget coords.
    """
    try:
        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return None

        meta = getattr(iv, 'metadata', {}) or {}
        instances = meta.get('instances', [])
        inst = instances[0] if isinstance(instances, list) and instances else {}
        img_w = int(inst.get('columns', 0) or 0)
        img_h = int(inst.get('rows', 0) or 0)

        if img_w > 0 and img_h > 0:
            widget_w = float(max(1, vtk_widget.width()))
            widget_h = float(max(1, vtk_widget.height()))
            img_x = (wx / widget_w) * img_w
            img_y = (wy / widget_h) * img_h
            return (
                max(0.0, min(img_x, float(img_w - 1))),
                max(0.0, min(img_y, float(img_h - 1))),
            )
    except Exception:
        pass
    return None


def _clamp_to_image(image_viewer, img_x: float, img_y: float) -> Tuple[float, float]:
    """Clamp pixel coordinates to the image bounds."""
    try:
        meta = getattr(image_viewer, 'metadata', {}) or {}
        instances = meta.get('instances', [])
        inst = instances[0] if isinstance(instances, list) and instances else {}
        rows = int(inst.get('rows', 0) or 0)
        cols = int(inst.get('columns', 0) or 0)

        if cols > 0:
            img_x = max(0.0, min(img_x, float(cols - 1)))
        if rows > 0:
            img_y = max(0.0, min(img_y, float(rows - 1)))
    except Exception:
        pass
    return (img_x, img_y)


def get_pixel_array_from_viewer(vtk_widget) -> Optional["numpy.ndarray"]:
    """
    Extract the current displayed image as a numpy array from a VTK widget.

    Returns:
        2D numpy array (rows x cols) of pixel intensities, or None.
    """
    try:
        import numpy as np

        iv = getattr(vtk_widget, 'image_viewer', None)
        if iv is None:
            return None

        vtk_image = getattr(iv, 'vtk_image_data', None)
        if vtk_image is None:
            # Try alternative attribute names
            vtk_image = getattr(iv, 'GetInput', lambda: None)()

        if vtk_image is None:
            return None

        dims = vtk_image.GetDimensions()  # (cols, rows, slices)
        cols, rows = dims[0], dims[1]

        if cols <= 0 or rows <= 0:
            return None

        scalars = vtk_image.GetPointData().GetScalars()
        if scalars is None:
            return None

        # Convert VTK array to numpy
        from vtk.util.numpy_support import vtk_to_numpy
        arr = vtk_to_numpy(scalars)

        # Handle multi-component (RGB) images
        n_comp = scalars.GetNumberOfComponents()
        if n_comp == 1:
            arr = arr.reshape(rows, cols)
        elif n_comp >= 3:
            arr = arr.reshape(rows, cols, n_comp)
            # Convert to grayscale for analysis
            arr = np.mean(arr[:, :, :3], axis=2).astype(arr.dtype)
        else:
            arr = arr.reshape(rows, cols)

        return arr

    except Exception as e:
        print(f"[3D-Cursor][COORD] Failed to extract pixel array: {e}")
        return None
