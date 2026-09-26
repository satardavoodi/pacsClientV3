"""Bind already decoded nonspatial frames on the owning VTK GUI thread."""

FRAME_KEY = '_advanced_presentation_frames'


def frames_for(viewer):
    return (getattr(viewer, 'metadata', None) or {}).get(FRAME_KEY) or ()


def apply_sync_point(viewer, point, adjust_slice):
    """Consume a logical frame token without moving the marker off native Z=0."""
    frames = frames_for(viewer)
    if not frames:
        return False
    index = int(round(point[2])) if adjust_slice else int(viewer.GetSlice())
    instances = viewer.metadata.get('instances') or []
    if (not 0 <= index < len(frames) or index >= len(instances)
            or instances[index].get('image_position_patient') is None
            or instances[index].get('image_orientation_patient') is None):
        viewer.hide_sync_point()
        return True
    if adjust_slice and index != viewer.GetSlice():
        viewer.set_slice(index)
    viewer._ensure_sync_point_actor()
    viewer._sync_point_source.SetCenter(float(point[0]), float(point[1]), 0.0)
    viewer._sync_point_actor.VisibilityOn()
    viewer._sync_point_visible = True
    viewer.Render()
    return True


def clear_overlay(viewer):
    actor = getattr(viewer, '_presentation_overlay_actor', None)
    if actor is not None:
        viewer.renderer.RemoveActor(actor)
        viewer._presentation_overlay_actor = None


def show_overlay(viewer, index):
    overlays = (getattr(viewer, 'metadata', None) or {}).get('_advanced_presentation_overlays') or ()
    image = overlays[index] if 0 <= index < len(overlays) else None
    actor = getattr(viewer, '_presentation_overlay_actor', None)
    if image is None:
        if actor is not None:
            actor.SetVisibility(False)
        return
    if actor is None:
        # Lightweight render prop belongs to this viewport, never to cached data.
        import vtk
        actor = viewer._presentation_overlay_actor = vtk.vtkImageActor()
        actor.PickableOff()
        actor.InterpolateOff()
        actor.SetPosition(0, 0, 0.01)
        viewer.renderer.AddActor(actor)
    actor.SetInputData(image)
    actor.SetVisibility(True)


def apply_frame_window(viewer, index):
    frames = frames_for(viewer)
    if not frames:
        return False
    image = frames[index]
    if image.GetNumberOfScalarComponents() == 3:
        viewer.color_mapper.SetWindow(255.0)
        viewer.color_mapper.SetLevel(127.5)
    elif not viewer.flag_set_custom_window_level:
        instance = viewer.metadata['instances'][index]
        viewer.color_mapper.SetWindow(instance['window_width'])
        viewer.color_mapper.SetLevel(instance['window_center'])
    elif getattr(viewer, '_presentation_monochrome_window', None) is not None:
        ww, wc = viewer._presentation_monochrome_window
        viewer.color_mapper.SetWindow(ww)
        viewer.color_mapper.SetLevel(wc)
    return True


def show_frame(viewer, index):
    """No filesystem/decode, resampling, pixel copying or VTK construction here."""
    frames = frames_for(viewer)
    index = max(0, min(int(index), len(frames) - 1))
    image = frames[index]
    old = viewer.vtk_image_data
    if old.GetNumberOfScalarComponents() == 1 and viewer.flag_set_custom_window_level:
        viewer._presentation_monochrome_window = viewer.get_window_level()
    camera = viewer.renderer.GetActiveCamera()
    same_shape = old.GetDimensions() == image.GetDimensions() and old.GetSpacing() == image.GetSpacing()
    saved = (camera.GetPosition(), camera.GetFocalPoint(), camera.GetViewUp(), camera.GetParallelScale())
    viewer._presentation_index = index
    viewer.vtk_image_data = image
    viewer.image_reslice.vtk_image_data = image
    viewer.image_reslice.SetInputData(image)
    viewer.image_reslice._configure_output_from_input()
    viewer.SetInputData(image)
    viewer.color_mapper.SetInputData(image)
    viewer.GetImageActor().GetMapper().SetInputConnection(viewer.color_mapper.GetOutputPort())
    viewer.UpdateDisplayExtent()
    apply_frame_window(viewer, index)
    viewer.orientation_markers.clear()
    show_overlay(viewer, index)
    # Consume vtkImageViewer2's first-render reset before restoring user zoom.
    viewer.Render()
    if same_shape:
        camera.SetPosition(saved[0])
        camera.SetFocalPoint(saved[1])
        camera.SetViewUp(saved[2])
        camera.SetParallelScale(saved[3])
    else:
        viewer.base_zoom_scale = viewer.zoom_to_fit(skip_render=True)
    viewer.update_corners_actors()
    viewer.Render()
