# Phase 2 Preparation: Backend-Independent Tools

## Goal
Decouple tool interaction/rendering from VTK so tool behavior is identical across:
- `VTK / SimpleITK`
- `PyDK (PyDicom 2D)`

## Existing Phase 1 Foundations
- Shared backend contract: `IViewer2DBackend`.
- Deterministic backend resolver: `resolve_viewer_backend(...)`.
- Geometry-driven metadata path for lazy backend.
- Generation-safe lazy frame readiness handling.

## Implementation Steps
1. Introduce a shared `ToolOverlayLayer` in Qt (QGraphicsScene or paint overlay).
2. Move tool state machine into a backend-independent `ToolManager`.
3. Route all mouse/keyboard gestures through `ToolManager`.
4. Use backend transforms (`image<->patient`) for measurements/reference lines.
5. Keep sync bus and reference lines geometry-only (no VTK-only assumptions).
6. Validate tool parity against current VTK behavior (gesture and numeric parity).

## Non-Goals in Phase 2 Prep
- No UI/gesture behavior changes.
- No backend-specific tool code in overlays.

## Entry Points
- Viewport backend bind and lifecycle:
  - `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget.py`
- Backend contracts:
  - `PacsClient/pacs/patient_tab/viewers/backends/contracts.py`
