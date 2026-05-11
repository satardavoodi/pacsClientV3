"""Shared visual constants for measurement / annotation tools.

Single source of truth — QPainterToolRenderer reads from here at render time.
Values extracted from VTK interactor style source code so FAST and Advanced
modes produce visually identical annotations.

Pure Python — zero Qt / VTK imports.  Use ``QColor(*RULER_COLOR)`` at the
rendering call site.
"""

# ── Tool Colors (RGB tuples matching VTK interactor styles exactly) ──────

RULER_COLOR = (0, 230, 0)               # bright green
ANGLE_COLOR = (0, 230, 0)               # bright green (same as ruler)
TWO_LINE_ANGLE_COLOR = (0, 230, 230)    # cyan (different from 3-pt angle!)
ARROW_COLOR = (0, 230, 0)               # bright green
TEXT_COLOR = (178, 77, 77)              # dark rose
ROI_COLOR = (240, 230, 140)             # khaki
CIRCLE_ROI_COLOR = (240, 230, 140)      # khaki (same as polygon ROI)
ERASER_HOVER_COLOR = (255, 0, 0)        # bright red

# ── Line Widths (pixels) ────────────────────────────────────────────────

RULER_LINE_WIDTH = 1
ANGLE_LINE_WIDTH = 1
TWO_LINE_ANGLE_LINE_WIDTH = 3
ARROW_LINE_WIDTH = 4
ROI_LINE_WIDTH = 2
CIRCLE_ROI_LINE_WIDTH = 2

# ── Endpoint / Handle Sizes (pixels) ────────────────────────────────────

RULER_ENDPOINT_SIZE = 7
RULER_HANDLE_SIZE = 10
ANGLE_POINT_SIZE = 5
ANGLE_HANDLE_SIZE = 10
CIRCLE_ROI_HANDLE_SIZE = 10
ROI_RECT_HANDLE_SIZE = 9
ROI_RECT_CENTER_HANDLE_SIZE = 10
ARROW_ENDPOINT_SIZE = 9
ARROW_HEAD_HEIGHT = 42
ARROW_HEAD_WIDTH_RATIO = 0.45

# ── Font ────────────────────────────────────────────────────────────────

LABEL_FONT_FAMILY = "Arial"
LABEL_FONT_SIZE = 24               # ruler, two-line angle
LABEL_FONT_BOLD = True             # two-line angle label
TEXT_TOOL_FONT_SIZE = 16           # text annotation tool
LABEL_FORMAT_DISTANCE = "{:.1f} mm"
LABEL_FORMAT_ANGLE = "{:.1f}\u00b0"

# ── Selection / Interaction ─────────────────────────────────────────────

SELECTION_HIGHLIGHT_WIDTH = 2      # extra pixels on selected annotation
ERASER_HIT_TOLERANCE = 15         # pixels (generous for touch/imprecise click)
SELECTION_HIT_TOLERANCE = 12      # pixels (annotation click-to-select)

HANDLE_FILL_COLOR = (18, 24, 32)
HANDLE_OUTLINE_COLOR = (235, 235, 235)
HANDLE_HOVER_FILL_COLOR = (255, 255, 255)
HANDLE_HOVER_OUTLINE_COLOR = (0, 230, 0)
