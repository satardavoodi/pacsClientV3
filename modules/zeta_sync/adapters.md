# Adapter Notes

Integrations should provide two adapter callbacks:

- `apply_cursor(viewer_id, world_pos)`
- `apply_slice(viewer_id, slice_index)`

These callbacks live near the viewer widgets and translate between the viewer's
coordinate system and world coordinates as required.
