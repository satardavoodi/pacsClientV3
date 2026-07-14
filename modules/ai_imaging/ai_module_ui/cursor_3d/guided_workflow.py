"""
3D Cursor — guided, step-by-step workflow (UI/UX layer).

WHY THIS EXISTS
---------------
The original flow ran two separate pop-ups back to back (nipple picker, then
pectoral picker), each labelled only "viewer 1 / viewer 2". The user could not
tell, at any moment: which step they were on, which VIEW to click, which tool was
active, what was already done, or what came next. It also asked for a pectoral
line **on BOTH views** — but the correlation math only ever consumes the **MLO**
pectoral angle:

    correlator._correlate_laterality():
        pectoral_angle_deg = mlo_view.manual_pectoral_angle_deg   (preferred)
    correlator._build_geometry():
        pectoral_angle_deg = angle if view.view_position == 'MLO' else None

so the CC pectoral line was discarded (it is also anatomically meaningless — the
pectoral muscle is not imaged in a CC view). The guided flow therefore asks for
exactly what the calculation uses, in the order it is used:

    1. Nipple  — MLO   (1 click)   → origin for Kopans depth d = |lesion - nipple|
    2. Nipple  — CC    (1 click)   → same origin in the other view
    3. Pectoral line — MLO (2 clicks: superior → inferior) → arc angle θ_pec

This module keeps the DECISION LOGIC pure (`plan_cursor3d_steps`, `Cursor3DFlow`)
so it is unit-testable without Qt/VTK; the Qt shell (`Cursor3DGuidedPicker`,
`Cursor3DWizardPanel`) is a thin layer on top.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Flag
# ─────────────────────────────────────────────────────────────────────────────

def guided_flow_enabled() -> bool:
    """AIPACS_CURSOR3D_GUIDED (default ON; =0 → legacy two-dialog flow)."""
    raw = os.environ.get("AIPACS_CURSOR3D_GUIDED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


# ─────────────────────────────────────────────────────────────────────────────
# Pure model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ViewSlot:
    """One loaded viewer: where it sits and what it shows."""
    viewer_index: int              # position in the viewer list (0 = first/left)
    laterality: str = ""           # 'R' / 'L' / ''
    view_position: str = ""        # 'CC' / 'MLO' / ''

    @property
    def label(self) -> str:
        if self.laterality and self.view_position:
            return f"{self.laterality}-{self.view_position}"
        if self.view_position:
            return self.view_position
        return f"Viewer {self.viewer_index + 1}"

    @property
    def side(self) -> str:
        return "left" if self.viewer_index == 0 else "right"


@dataclass(frozen=True)
class Cursor3DStep:
    """One instruction the user must complete."""
    key: str            # 'nipple_mlo' | 'nipple_cc' | 'pectoral_mlo'
    kind: str           # 'point' (1 click) | 'line' (2 clicks)
    view_position: str  # 'MLO' | 'CC'
    view_label: str     # 'R-MLO'
    viewer_index: int   # which viewer must be clicked
    title: str          # short checklist title
    tool: str           # which tool is active
    instruction: str    # what to do, in plain words
    clicks: int         # clicks required
    why: str = ""       # what the value is used for (shown as a hint)


def plan_cursor3d_steps(slots: List[ViewSlot]) -> Optional[List[Cursor3DStep]]:
    """Build the ordered step list from the loaded views.

    Returns None when the views cannot be identified (missing/duplicate
    view_position) — the caller then falls back to the legacy generic flow rather
    than guessing, because clicking the nipple in the wrong view silently corrupts
    the correlation.
    """
    if not slots or len(slots) < 2:
        return None

    by_view: Dict[str, ViewSlot] = {}
    for s in slots:
        vp = (s.view_position or "").upper()
        if vp not in ("CC", "MLO"):
            return None
        if vp in by_view:
            return None  # two CCs (or two MLOs) — cannot plan
        by_view[vp] = s

    mlo = by_view.get("MLO")
    cc = by_view.get("CC")
    if mlo is None or cc is None:
        return None

    return [
        Cursor3DStep(
            key="nipple_mlo",
            kind="point",
            view_position="MLO",
            view_label=mlo.label,
            viewer_index=mlo.viewer_index,
            title=f"Nipple — MLO ({mlo.label})",
            tool="Nipple marker · 1 click",
            instruction=f"Click the <b>nipple</b> in the <b>{mlo.label}</b> view ({mlo.side} viewer).",
            clicks=1,
            why="Origin for the depth measurement (Kopans' rule: distance from the nipple is preserved between views).",
        ),
        Cursor3DStep(
            key="nipple_cc",
            kind="point",
            view_position="CC",
            view_label=cc.label,
            viewer_index=cc.viewer_index,
            title=f"Nipple — CC ({cc.label})",
            tool="Nipple marker · 1 click",
            instruction=f"Click the <b>nipple</b> in the <b>{cc.label}</b> view ({cc.side} viewer).",
            clicks=1,
            why="The same origin in the second view — the correspondence arc is centred on it.",
        ),
        Cursor3DStep(
            key="pectoral_mlo",
            kind="line",
            view_position="MLO",
            view_label=mlo.label,
            viewer_index=mlo.viewer_index,
            title=f"Pectoral line — MLO ({mlo.label})",
            tool="Pectoral line · 2 clicks (superior → inferior)",
            instruction=(
                f"Draw the <b>pectoral muscle line</b> in the <b>{mlo.label}</b> view: "
                f"click its <b>upper (superior)</b> end, then its <b>lower (inferior)</b> end."
            ),
            clicks=2,
            why="Gives the pectoral angle θ used to project the lesion (H = Y·sinθ + Z·cosθ). Only the MLO view images the pectoral muscle — no CC line is needed.",
        ),
    ]


@dataclass
class Cursor3DFlow:
    """Pure state machine driving the guided workflow (no Qt, no VTK)."""

    steps: List[Cursor3DStep]
    current_index: int = 0
    # step key -> list of (x_px, y_px) image-pixel clicks
    clicks: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)

    # ---- queries -----------------------------------------------------------
    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        return self.current_index >= len(self.steps)

    @property
    def current_step(self) -> Optional[Cursor3DStep]:
        if self.is_complete:
            return None
        return self.steps[self.current_index]

    def progress_text(self) -> str:
        if self.is_complete:
            return f"All {self.total_steps} steps complete"
        return f"Step {self.current_index + 1} of {self.total_steps}"

    def step_state(self, index: int) -> str:
        """'done' | 'current' | 'pending' — drives the checklist rendering."""
        if index < self.current_index:
            return "done"
        if index == self.current_index and not self.is_complete:
            return "current"
        return "pending"

    def points_for(self, key: str) -> List[Tuple[float, float]]:
        return list(self.clicks.get(key, []))

    def clicks_remaining(self) -> int:
        step = self.current_step
        if step is None:
            return 0
        return max(0, step.clicks - len(self.clicks.get(step.key, [])))

    # ---- transitions -------------------------------------------------------
    def click(self, viewer_index: int, x_px: float, y_px: float) -> dict:
        """Record a click. Returns a small event dict for the UI shell.

        status: 'wrong_view' | 'need_more_clicks' | 'step_done' | 'flow_done' | 'ignored'
        """
        step = self.current_step
        if step is None:
            return {"status": "ignored"}

        if viewer_index != step.viewer_index:
            return {
                "status": "wrong_view",
                "expected_view": step.view_label,
                "expected_viewer_index": step.viewer_index,
                "step": step,
            }

        pts = self.clicks.setdefault(step.key, [])
        pts.append((float(x_px), float(y_px)))

        if len(pts) < step.clicks:
            return {"status": "need_more_clicks", "step": step, "points": list(pts)}

        self.current_index += 1
        if self.is_complete:
            return {"status": "flow_done", "step": step, "points": list(pts)}
        return {"status": "step_done", "step": step, "points": list(pts),
                "next_step": self.current_step}

    def back(self) -> Optional[Cursor3DStep]:
        """Undo: drop the clicks of the step in progress, else re-open the previous
        step. Returns the step whose overlay must be erased (None if nothing to undo)."""
        step = self.current_step
        if step is not None and self.clicks.get(step.key):
            self.clicks[step.key] = []
            return step
        if self.current_index == 0:
            return None
        self.current_index -= 1
        prev = self.steps[self.current_index]
        self.clicks[prev.key] = []
        return prev

    def reset(self) -> None:
        self.current_index = 0
        self.clicks = {}
