# Viewport Vision, DICOM Context, and Measurement Capability

Date: 2026-07-06

This document is the continuation handoff for the Secretary EchoMind agentic
app-control work. It keeps the single architecture rule:

`Secretary EchoMind -> external GPT/GapGPT brain -> CommandPlan -> CommandBus -> MCP/action layer -> AI-PACS UI`

Do not create a second parallel agent. The MCP server is an execution transport
over the same CommandBus actions that Secretary EchoMind uses.

## Current Implementation

The first production-facing action slice is implemented in:

- `modules/EchoMind/secretary/adapters/viewer_write_adapter.py`
- `modules/EchoMind/secretary/bus_factory.py`
- `modules/EchoMind/secretary/permissions.py`
- `tools/testing/aipacs_control_mcp/server.py`

New CommandBus actions:

- `get_viewport_context`
- `capture_viewport`
- `activate_tool`
- `measure_distance`
- `get_measurements`

New MCP wrappers:

- `get_viewport_context(viewport, include_slice_meta, include_local_paths)`
- `capture_viewport(viewport, scope, filename_prefix)`
- `activate_tool(tool, viewport)`
- `measure_distance(points_image_json, viewport, slice_index, label)`
- `get_measurements(viewport, slice_index, all_slices)`

`get_viewport_context` and `get_measurements` are read-only. `capture_viewport`,
`activate_tool`, and `measure_distance` are local writes because they save local
artifacts or change viewer overlays.

## Viewport Capture Plan

Use `capture_viewport`, not desktop screenshots, for normal agent runs. It saves
PNG files under:

`user_data/echomind/agent_artifacts`

Supported scopes:

- `viewport`: active viewport widget, using `modules.viewer.viewport_capture.grab_widget_pixmap`
- `tab`: full active patient tab

The external GPT brain should receive the saved image path or encoded image from
the Secretary EchoMind orchestration layer, along with the structured viewport
context from `get_viewport_context`.

## DICOM Context Plan

`get_viewport_context` currently returns:

- active study UID
- viewport index
- backend type
- current slice index and slice count
- series number when available
- widget size
- image size
- zoom, pan, rotation, flip, display scale
- viewer metadata and fixed metadata
- current slice metadata from the FAST pipeline when available
- patient-space coordinates for image corners when the pipeline supports
  `image_xy_to_patient_xyz`
- capability flags

The FAST viewer already has DICOM geometry code in:

- `modules/viewer/fast/lightweight_2d_pipeline.py`
- `modules/viewer/fast/dicom_sync_geometry.py`
- `modules/viewer/fast/dicom_header_scan.py`
- `modules/viewer/tools/coord_resolver.py`

The next slice should normalize context into a stable `ViewportContext` model
inside the Secretary module so GPT prompts do not depend on raw GUI object names.

## GPT Request Shape

Secretary EchoMind should send the external GPT/GapGPT brain a compact package:

```json
{
  "user_command": "measure orbital distance on the current CT slice",
  "workflow_state": {
    "active_step": "measurement",
    "patient_confirmed": true,
    "study_confirmed": true
  },
  "viewport_context": {
    "viewport": 0,
    "slice_index": 55,
    "slice_count": 110,
    "modality": "CT",
    "pixel_spacing": [0.5, 0.5],
    "orientation": [1, 0, 0, 0, 1, 0]
  },
  "viewport_capture_path": "user_data/echomind/agent_artifacts/...",
  "ocr_text": "optional OCR result"
}
```

GPT should respond with a structured decision, not free text:

```json
{
  "intent": "measure_distance",
  "confidence": 0.88,
  "requires_confirmation": false,
  "action": {
    "name": "measure_distance",
    "entities": {
      "viewport": 0,
      "slice_index": 55,
      "points_image": [[120.0, 210.0], [220.0, 211.5]],
      "label": "orbital distance"
    }
  },
  "validation": {
    "expected_result": "distance_mm present and measurement visible"
  }
}
```

If GPT is not confident about anatomy, plane, side, or target points, it must
return `requires_confirmation: true` or ask for another capture/slice.

## Coordinate Mapping

Preferred coordinate path:

1. GPT identifies target points in image-pixel coordinates from the viewport
   capture plus context.
2. Local orchestrator calls `measure_distance(points_image=...)`.
3. `measure_distance` validates the slice and image bounds.
4. `CoordinateResolver` maps image points to DICOM patient space through the
   active FAST pipeline.
5. `ToolController` creates a real `RulerModel` in the viewer tool store.
6. `get_measurements` reads the completed model and returns `distance_mm`.

Avoid raw screen coordinates for clinical measurement. If screen coordinates are
unavoidable, first convert:

`screen -> widget -> image -> DICOM patient space`

The active transform must include zoom, pan, rotation, flip, display scale,
pixel spacing, image orientation patient, image position patient, and slice
index.

## Measurement Workflow

Recommended Secretary EchoMind loop:

1. Receive voice/chat command through the existing transcription/AI structure.
2. Capture viewport with `capture_viewport`.
3. Read structured context with `get_viewport_context`.
4. Send screenshot, OCR text if available, and context to GapGPT.
5. If GPT returns uncertainty, ask the user for confirmation or a more specific
   target.
6. Execute `measure_distance` using image-space points.
7. Execute `get_measurements` for validation.
8. Capture the viewport again for the report artifact.
9. Store conversation, decision, command result, screenshots, and final report
   under EchoMind user data.

## Safety Rules

- Never measure if patient, study, series, viewport, or slice context changed
  between GPT decision and execution.
- Reject a requested `slice_index` that does not match the current displayed
  slice.
- Reject points outside image bounds.
- Prefer local tool-store measurement over GUI drag automation.
- Ask for confirmation when anatomy, plane, or target points are ambiguous.
- Save screenshots and GPT decisions in EchoMind user data for auditability.
- Do not silently send PHI or reports outside the existing Secretary EchoMind
  LLM/GapGPT path.

## Tests

Implemented tests:

- `modules/EchoMind/secretary/tests/test_viewer_write_adapter.py`
  - viewport context includes DICOM geometry and capabilities
  - distance measurement writes to the FAST tool store
  - measurement readback returns the completed ruler
  - slice mismatch is rejected
- `tests/code/echomind/test_mcp_server_inventory.py`
  - MCP exposes the viewport vision and measurement tools

Recommended next tests:

- live app test: capture viewport -> context -> GPT mock decision -> distance
  measurement -> readback -> after screenshot
- coordinate round-trip tests for rotated/flipped/zoomed FAST viewports
- ROI rectangle/circle measurement tests with CT density statistics
- VTK or MPR backend support tests, returning `NOT_IMPLEMENTED` until real
  mapping is available

## Next Development Slice

1. Add a stable `ViewportContext` dataclass in Secretary EchoMind and adapt
   `get_viewport_context` to return that schema.
2. Add `measure_angle`, `measure_roi_rect`, `measure_roi_circle`, and
   `place_annotation` actions using the same FAST `ToolController`.
3. Add OCR fallback configuration for the clinical validation runner. The
   current environment has `pytesseract` but no Tesseract binary.
4. Add GapGPT decision logging to the normal Secretary EchoMind runtime, not
   only the validation harness.
5. Extend live clinical validation to call `get_viewport_context`,
   `capture_viewport`, `measure_distance`, and `get_measurements`.
