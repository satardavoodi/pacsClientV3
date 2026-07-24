"""
Two-Stage 3D Cursor — orchestration.

Sequences the workflow and owns its state machine. Deliberately the ONLY place
that knows about both stages, so `imaging_tab` needs just three call sites.

    3D Cursor clicked
        └─► begin()                      launch the lower-threshold pass NOW,
                                         so it overlaps the landmark picking
    guided picker runs (user picks nipples + pectoral line)
        └─► on_landmarks_ready(...)      Stage 1: compute + draw the region
    second pass returns (whenever)
        └─► _try_match()                 Stage 2: rank candidates, draw outcome

The two arms converge in `_try_match()`, which fires only when BOTH the region and
the second-pass CSV are available — in whichever order they arrive. The user is
never blocked waiting for the backend, and the backend result is never dropped for
arriving early.

FAILURE POSTURE
────────────────────────────────────────────────────────────────────────────────
Every failure degrades to "Stage 1 only": the geometric region stays on screen and
we say plainly that no reliable AI correspondence was found. We never invent a
match, never widen the bands to manufacture a hit, and never present an ambiguous
result as a confirmed one. A wrong "found it" moves the radiologist's eye away from
the real lesion — strictly worse than an honest "look here, I'm not sure".
"""

from __future__ import annotations

import ast
import logging
import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject

from . import region_render
from .candidate_matching import (
    AMBIGUOUS,
    MATCH,
    NO_MATCH,
    Candidate,
    MatchResult,
    rank_candidates,
)
from .search_region import SearchRegion, compute_search_region
from .second_pass import SecondPassController, second_pass_threshold
from .threshold_policy import LADDER_FLOOR, threshold_ladder
from .two_stage_session import save_session, session_from_result
from . import lesion_feature_store as _lfs
from . import contralateral_matcher as _cxl

# Diagnostics go through the LOGGER, not print(). print() writes to stdout, which
# a VS Code source run shows in the terminal and then loses — none of this
# feature's `[3D-Cursor]` lines ever reached user_data/logs/app.log, so the first
# live failure had to be diagnosed by reading CSVs by hand. Don't repeat that.
logger = logging.getLogger(__name__)


# Master flag. `=0` → the 3D Cursor behaves exactly as before this feature landed.
ENABLED = os.getenv("AIPACS_CURSOR3D_TWO_STAGE", "1").strip().lower() not in ("0", "false", "no", "off")

# Factor 3 (appearance/histogram similarity) in candidate scoring — AND the pattern
# descriptor captured into the lesion feature store. **Default ON (promoted
# 2026-07-15 per directive.)** It reads the source+target pixel arrays once per
# view-pair on the GUI thread (bounded: 2 decodes per finding at match-finalize, not
# per-candidate, and cached on the entry). KNOWN caveat kept as a tracked follow-up:
# move that read off-thread. `=0` restores the geometry-only legacy behaviour.
APPEARANCE_ENABLED = os.getenv("AIPACS_CURSOR3D_APPEARANCE", "0").strip().lower() in ("1", "true", "yes", "on")  # reverted to OFF 2026-07-20 (3D-Cursor close regression; re-enable to isolate)

# Dense three-factor visual heatmap overlay on the target viewport. **Default ON
# (promoted 2026-07-15 per directive.)** Render is wrapped (`_maybe_draw_heatmap`
# logs + never raises), so a VTK issue degrades to "no overlay", never a crash; the
# candidate scoring already uses the factors regardless. `=0` = no overlay (legacy).
HEATMAP_ENABLED = os.getenv("AIPACS_CURSOR3D_HEATMAP", "1").strip().lower() not in ("0", "false", "no", "off")  # RE-ENABLED default-ON 2026-07-21 after hardening the draw (drop non-finite cells + grid cap for off-image regions). `=0` = kill switch if it still closes the app.

# Persist every lesion's full descriptor (geometry + the appearance "pattern
# matrix") to the lesion feature store, so the SAME measurements can later drive
# contralateral R↔L comparison, not just today's CC↔MLO match. Storage only —
# non-clinical, atomic, never raises. GEOMETRY is always stored (cheap, no pixels);
# the APPEARANCE pattern is stored only when the pixel arrays were already decoded
# for factor 3 (no extra GUI-thread read). `=0` disables the store entirely.
FEATURE_STORE_ENABLED = os.getenv("AIPACS_CURSOR3D_FEATURE_STORE", "1").strip().lower() not in ("0", "false", "no", "off")

# UNIFY: process a PAIRED lesion (the AI already found it in BOTH views) through the
# SAME two-stage path (GM band + heatmap) instead of deferring it to the legacy
# correlation arc + "PAIRED" popup — so the 3D-cursor display is consistent whether or
# not the lesion was already paired. Default ON. `=0` = legacy arc for paired lesions.
UNIFY_PAIRED_ENABLED = os.getenv("AIPACS_CURSOR3D_UNIFY_PAIRED", "1").strip().lower() not in ("0", "false", "no", "off")

# Multiple-findings UX (2026-07-15): declutter when >1 corresponding lesion is
# found — draw only the SELECTED finding's full overlay (box + region + heatmap),
# others as small numbered markers, plus a click-to-review corner panel and a synced
# sidebar list. Default ON; `=0` restores the legacy "draw every finding at once".
FINDINGS_UX = os.getenv("AIPACS_CURSOR3D_FINDINGS_UX", "1").strip().lower() not in ("0", "false", "no", "off")

# The on-image corner panel is a Qt widget overlaid on the VTK viewport, which does
# NOT paint reliably over a VTK render window on many setups. Default OFF — the
# findings selector lives in the TOOLBAR (next to Ruler) and the sidebar list, both
# reliable. `=1` re-enables the experimental in-viewport overlay.
ONIMAGE_PANEL = os.getenv("AIPACS_CURSOR3D_ONIMAGE_PANEL", "0").strip().lower() in ("1", "true", "yes", "on")

DEFAULT_THRESHOLD = 0.45


# ─── UI state strings (single source of truth) ───────────────────────────────

class State:
    CALCULATING_REGION = "Calculating corresponding region…"
    RUNNING_ANALYSIS = "Running lower-threshold analysis…"
    WAITING_BACKEND = "Waiting for AI result…"
    EVALUATING = "Evaluating candidate lesions…"
    FOUND = "Corresponding lesion found"
    AMBIGUOUS_STATE = "Multiple possible matches — review alternatives"
    NOT_FOUND = "No reliable corresponding lesion found"
    REGION_ONLY = "Predicted region shown (no AI candidates)"

    @staticmethod
    def retrying(threshold: float) -> str:
        return f"Nothing in the region — retrying at threshold {threshold:.2f}…"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_boxes(cell) -> List[List[float]]:
    """
    Parse a CSV `box` / `new_box` cell into [[x1,y1,x2,y2], ...].

    Reimplemented here rather than imported from `imaging_tab`, because
    `imaging_tab` imports this package — importing back would be circular.
    Kept semantically identical to `imaging_tab._parse_box_cell`.
    """
    if cell is None:
        return []
    if isinstance(cell, (list, tuple)):
        raw = list(cell)
    else:
        text = str(cell).strip()
        if not text or text.lower() in ("nan", "none", "[]"):
            return []
        try:
            raw = ast.literal_eval(text)
        except Exception:
            return []
    if not isinstance(raw, (list, tuple)) or not raw:
        return []
    # A bare [x1,y1,x2,y2] is one box; a list of lists is many.
    if all(isinstance(v, (int, float)) for v in raw):
        return [[float(v) for v in raw]] if len(raw) == 4 else []
    out: List[List[float]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 4:
            try:
                out.append([float(v) for v in item])
            except Exception:
                continue
    return out


def _parse_scores(cell) -> List[float]:
    if cell is None:
        return []
    if isinstance(cell, (list, tuple)):
        raw = list(cell)
    else:
        text = str(cell).strip()
        if not text or text.lower() in ("nan", "none", "[]"):
            return []
        try:
            raw = ast.literal_eval(text)
        except Exception:
            try:
                return [float(text)]
            except Exception:
                return []
    if isinstance(raw, (int, float)):
        return [float(raw)]
    out: List[float] = []
    for v in raw if isinstance(raw, (list, tuple)) else []:
        try:
            out.append(float(v))
        except Exception:
            out.append(0.5)
    return out


def current_threshold(study_uid: str, attachments_path: str) -> float:
    """
    The threshold of the run currently displayed. Falls back to the routine
    default (0.45) — never guesses low, because guessing low would make the
    second pass a no-op (or, worse, a duplicate of the active run).
    """
    try:
        from PacsClient.utils.utils import load_mg_ai_runs
        data = load_mg_ai_runs(study_uid, attachments_path) or {}
        active = data.get("active") or {}
        active_det = active.get("detection")
        for run in data.get("available", []) or []:
            if run.get("detection") == active_det and run.get("threshold") is not None:
                return float(run["threshold"])
        # No active marker — take the highest threshold we know about.
        thresholds = [
            float(r["threshold"]) for r in (data.get("available") or [])
            if r.get("threshold") is not None
        ]
        if thresholds:
            return max(thresholds)
    except Exception:
        pass
    return DEFAULT_THRESHOLD


# ─── Controller ──────────────────────────────────────────────────────────────

class TwoStageCursorController(QObject):
    """One instance per ImagingToolsTab. Reused across 3D Cursor invocations."""

    def __init__(self, tab):
        super().__init__(tab)
        self._tab = tab
        self._second = SecondPassController(self)
        self._second.started.connect(self._on_pass_started)
        self._second.reused.connect(self._on_pass_reused)
        self._second.finished.connect(self._on_pass_finished)
        self._second.failed.connect(self._on_pass_failed)

        self._reset()

    def _reset(self) -> None:
        self._original_threshold: float = DEFAULT_THRESHOLD
        self._study_uid: str = ""
        self._attachments_path: str = ""
        self._ladder: List[float] = []
        self._rung: int = 0
        self._second_csv: Optional[str] = None
        self._second_cls_csv: Optional[str] = None
        self._second_threshold: Optional[float] = None
        self._second_failed: bool = False
        self._second_error: Optional[str] = None

        # Stage-1 output: one entry per unpaired source lesion.
        self._pending: List[dict] = []
        self._region_ready: bool = False
        self._matched: bool = False

        # Multiple-findings UX: ordered findings + the currently reviewed one.
        self._clear_findings_panels()
        self._findings: List[dict] = []
        self._selected_finding: int = 0

    # ── status plumbing ──────────────────────────────────────────────────────

    def _status(self, text: str, active: bool = True) -> None:
        try:
            self._tab.set_processing_status(text, active=active)
        except Exception:
            pass

    def _report(self, text: str) -> None:
        try:
            self._tab.feature_view.setPlainText(text)
        except Exception:
            pass

    # ── Stage 2a: launch the background pass ─────────────────────────────────

    def begin(self, study_uid: str, attachments_path: str) -> None:
        """Called the instant the 3D Cursor button is pressed."""
        if not ENABLED:
            return
        self._reset()
        self._study_uid = str(study_uid)
        self._attachments_path = str(attachments_path)
        self._original_threshold = current_threshold(study_uid, attachments_path)

        self._ladder = threshold_ladder(self._original_threshold)
        self._rung = 0
        if not self._ladder:
            logger.info(
                f"[3D-Cursor][2-STAGE] original threshold {self._original_threshold:.2f} "
                f"is already at/below the floor {LADDER_FLOOR:.2f} — no second pass"
            )
            return

        logger.info(
            f"[3D-Cursor][2-STAGE] begin: original={self._original_threshold:.2f} "
            f"ladder={[f'{t:.2f}' for t in self._ladder]}"
        )
        self._start_rung()

    def _start_rung(self) -> bool:
        """Launch the next rung of the escalation ladder. False if exhausted."""
        if self._rung >= len(self._ladder):
            return False
        target = self._ladder[self._rung]
        self._rung += 1
        self._second_csv = None
        self._second_cls_csv = None
        self._second_failed = False
        self._second_error = None
        return self._second.start(
            study_uid=self._study_uid,
            attachments_path=self._attachments_path,
            original_threshold=self._original_threshold,
            threshold=target,
        )

    @property
    def _has_next_rung(self) -> bool:
        return self._rung < len(self._ladder)

    @property
    def _lowest_tried(self) -> Optional[float]:
        if not self._ladder or self._rung == 0:
            return None
        return self._ladder[self._rung - 1]

    # ── Stage 1: the region (called after landmarks + legacy correlation) ────

    def on_landmarks_ready(
        self,
        *,
        result,                      # correlator.Cursor3DResult
        views_by_key: Dict[str, object],
        geoms_by_key: Dict[str, object],
        contours_by_key: Optional[Dict[str, object]] = None,
        study_uid: str = "",
        attachments_path: str = "",
        pectoral_angle_deg: Optional[float] = None,
    ) -> bool:
        """
        Compute and draw the search region for every lesion that the correlator
        could NOT pair — i.e. exactly the lesions seen in one view but not the
        other, which is the clinical case this whole workflow exists for.

        Returns True if this controller has taken ownership of the overlay and the
        status strip. False means there was nothing for it to do (every lesion was
        already paired, or no region was computable) — the caller must then fall
        back to the legacy summary so the user is not left with a silent viewer.
        """
        if not ENABLED:
            return False

        self._status(State.CALCULATING_REGION)
        contours_by_key = contours_by_key or {}
        self._pending = []
        cleared: set = set()

        for laterality, lat_result in result.lateralities.items():
            for m in lat_result.cursor_matches:
                # A PAIRED lesion was found by the AI in BOTH views. Legacy behaviour
                # skipped it here (nothing to SEARCH cross-view) so it fell back to the
                # correlation arc + popup. UNIFY: process it through the SAME two-stage
                # path so it gets the GM band + heatmap like every other lesion — the
                # region is built in the target view and the shared second-pass confirms
                # the already-detected lesion (match → heatmap on it). `=0` = legacy arc.
                if m.match_type == "paired" and not UNIFY_PAIRED_ENABLED:
                    continue

                src_key = f"{laterality}_{m.source_view}"
                tgt_key = f"{laterality}_{m.target_view}"
                src_geom = geoms_by_key.get(src_key)
                tgt_geom = geoms_by_key.get(tgt_key)
                tgt_view = views_by_key.get(tgt_key)
                if src_geom is None or tgt_geom is None or tgt_view is None:
                    continue

                region = compute_search_region(
                    m.source_lesion, src_geom, tgt_geom,
                    breast_contour=contours_by_key.get(tgt_key),
                )
                if not region.ok:
                    logger.warning(
                        f"[3D-Cursor][2-STAGE] region unusable for {src_key}: {region.message}"
                    )
                    continue

                # PNL cross-view depth-normalisation diagnostic — logged for EVERY
                # region whether or not the normaliser is applied, so 50513/50258 can
                # be validated live from the log (legacy vs normalised depth + the two
                # pectoral distances + correction ratio).
                _pnl = getattr(region, "pnl", None)
                _pnl_log = None
                if _pnl is not None:
                    try:
                        _pnl_log = _pnl.as_log_dict()
                        logger.info(
                            f"[3D-Cursor][PNL] {m.source_view}->{m.target_view} "
                            f"({laterality}) {_pnl_log}"
                        )
                    except Exception:
                        _pnl_log = None

                self._pending.append({
                    "laterality": laterality,
                    "source_view": m.source_view,
                    "target_view": m.target_view,
                    "source_lesion": m.source_lesion,
                    "source_geom": src_geom,
                    "target_geom": tgt_geom,
                    "target_view_data": tgt_view,
                    "source_view_data": views_by_key.get(src_key),  # for factor-3 pixels
                    "region": region,
                    "match": None,
                    "pnl": _pnl_log,          # PNL depth-normalisation diagnostic
                    "_appearance_fn": None,   # cached lazily (factor 3)
                    # PAIRED lesion: the AI already located it in the TARGET view, so its
                    # known box anchors the heatmap core at the EXACT vertical position —
                    # better than the weak geometric height prior. None for unpaired.
                    "paired_target_box_px": (
                        list(m.target_lesion.to_pixel_box())
                        if (m.match_type == "paired" and m.target_lesion is not None)
                        else None
                    ),
                })

                vtk_w = getattr(tgt_view, "vtk_widget", None)
                if vtk_w is not None:
                    # Clear each target viewer exactly once, on its first region.
                    # Subsequent regions on the same viewer (a breast with several
                    # unpaired lesions) must ADD, not wipe the previous one.
                    first = id(vtk_w) not in cleared
                    cleared.add(id(vtk_w))
                    region_render.draw_search_region(vtk_w, region, clear_first=first)

        self._region_ready = True
        self._study_uid = study_uid
        self._attachments_path = attachments_path
        self._pectoral_angle_deg = pectoral_angle_deg

        if not self._pending:
            # Nothing unpaired => nothing for this workflow to do. Hand back to the
            # legacy summary rather than leaving the user with a silent viewer.
            logger.info("[3D-Cursor][2-STAGE] no unpaired lesions — deferring to legacy summary")
            self._second.cancel()
            return False

        self._try_match()
        return True

    # ── second-pass callbacks ────────────────────────────────────────────────

    def _on_pass_started(self, threshold: float) -> None:
        self._status(f"{State.RUNNING_ANALYSIS} (threshold {threshold:.2f})")

    def _on_pass_reused(self, det_csv: str, threshold: float) -> None:
        self._second_csv = det_csv
        self._second_threshold = threshold
        self._safe_try_match()

    def _on_pass_finished(self, det_csv: str, cls_csv: str, threshold: float) -> None:
        self._second_csv = det_csv
        self._second_cls_csv = cls_csv or None
        self._second_threshold = threshold
        self._safe_try_match()

    def _on_pass_failed(self, message: str) -> None:
        self._second_failed = True
        self._second_error = message
        self._safe_try_match()

    def _safe_try_match(self) -> None:
        """Run `_try_match` from a Qt signal handler without ever letting an exception
        reach `main.py::notify` — which re-raises and CLOSES the app. Any failure is
        logged with a traceback (so it lands in app.log) and the status degrades
        honestly, but the app stays alive. This is the crash safety net for the
        second-pass convergence path."""
        try:
            self._try_match()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[3D-Cursor][2-STAGE] _try_match crashed (contained — app kept alive): %s",
                exc, exc_info=True,
            )
            try:
                self._status(State.NOT_FOUND, active=False)
            except Exception:
                pass

    # ── convergence ──────────────────────────────────────────────────────────

    def _try_match(self) -> None:
        """
        Fires when BOTH arms are in. Order-independent by construction.

        If this rung produced NO detection inside the predicted region, escalate to
        the next (lower) rung rather than declaring failure — see the ladder note in
        threshold_policy.py. Escalating is safe precisely because the region gates
        what we show: we look deeper, but we still only surface detections that land
        in the geometrically-plausible band.
        """
        if not ENABLED or self._matched:
            return
        if not self._region_ready or not self._pending:
            return

        if self._second_failed:
            # A backend failure is not a reason to keep hammering it.
            self._finish_region_only(
                f"Lower-threshold analysis failed ({self._second_error}). "
                f"The predicted region is shown — review it manually."
            )
            return

        if not self._second_csv:
            self._status(State.WAITING_BACKEND)
            return

        self._status(State.EVALUATING)

        # Score this rung's detections against every pending region.
        scored: List[Tuple[dict, MatchResult]] = []
        any_in_region = False
        total_target_candidates = 0

        for entry in self._pending:
            vtk_w = getattr(entry["target_view_data"], "vtk_widget", None)
            candidates = self._load_candidates(vtk_w)
            total_target_candidates += len(candidates)

            match = rank_candidates(
                candidates,
                entry["region"],
                entry["source_lesion"],
                entry["source_geom"],
                entry["target_geom"],
                appearance_score_fn=self._appearance_fn_for(entry),  # factor 3 (flag-gated)
            )
            if any(s.in_outer_band for s in match.ranked):
                any_in_region = True
            scored.append((entry, match))

        thr = self._second_threshold if self._second_threshold is not None else -1.0
        logger.info(
            f"[3D-Cursor][2-STAGE] rung threshold={thr:.2f}: "
            f"{total_target_candidates} detection(s) in the target view, "
            f"in_region={any_in_region} "
            f"({self._csv_view_summary()})"
        )

        # ── Escalate: nothing landed in the region, and we have rungs left. ──
        if not any_in_region and self._has_next_rung:
            nxt = self._ladder[self._rung]
            logger.info(
                f"[3D-Cursor][2-STAGE] nothing in region at {thr:.2f} — escalating to {nxt:.2f}"
            )
            self._status(State.retrying(nxt))
            if self._start_rung():
                return
            # Could not launch the next rung — fall through and finalize honestly.
            logger.warning("[3D-Cursor][2-STAGE] could not launch next rung — finalizing")

        # ── Finalize. ──
        self._matched = True
        lines: List[str] = []
        any_match = False
        any_ambiguous = False

        for entry, match in scored:
            entry["match"] = match
            if match.status == MATCH:
                any_match = True
            elif match.status == AMBIGUOUS:
                any_ambiguous = True
            lines.append(self._describe(entry, match))
            self._persist(entry, match)

        # Contralateral (R↔L) symmetry pass — runs AFTER every lesion of this run is
        # persisted, so the store has both breasts to compare. Gated + never raises;
        # sets self._symmetry_note, surfaced in the findings panel below.
        self._run_contralateral_analysis(scored)

        if FINDINGS_UX:
            # Declutter: build the ordered findings and draw ONLY the top one's full
            # overlay (box + region + heatmap); the rest are small numbered markers,
            # reviewable one at a time via the toolbar dropdown + the synced sidebar.
            #
            # HARD GUARD: this runs from the second-pass Qt signal, where an
            # unhandled exception is re-raised by main.py::notify and CLOSES the app.
            # Any failure here must degrade to the legacy draw-all, never crash. The
            # traceback is logged (exc_info) so the cause lands in app.log.
            try:
                self._build_findings(scored)
                self._selected_finding = 0
                self._render_findings()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[3D-Cursor][FINDINGS] render failed — falling back to legacy "
                    "draw-all (this prevented an app crash): %s", exc, exc_info=True,
                )
                for entry, match in scored:
                    vtk_w = getattr(entry["target_view_data"], "vtk_widget", None)
                    if vtk_w is not None:
                        try:
                            self._maybe_draw_heatmap(entry, match)
                            region_render.draw_candidates(vtk_w, match)
                        except Exception:
                            pass
                try:
                    self._report("\n\n".join(lines))
                except Exception:
                    pass
        else:
            # Legacy: draw every finding at once (the pre-2026-07-15 cluttered view).
            from .candidate_matching import focused_indices
            for entry, match in scored:
                vtk_w = getattr(entry["target_view_data"], "vtk_widget", None)
                if vtk_w is not None:
                    self._maybe_draw_heatmap(entry, match)
                    region_render.draw_candidates(vtk_w, match)
            foci = focused_indices([m for _, m in scored])
            if foci:
                header: List[str] = []
                for rank, idx in enumerate(foci, start=1):
                    f_entry, f_match = scored[idx]
                    f_best = f_match.best
                    tag = ("★ FOCUSED corresponding lesion" if len(foci) == 1
                           else f"★ Corresponding lesion {rank} of {len(foci)}")
                    header.append(
                        f"{tag}: {f_entry['laterality']} "
                        f"{f_entry['source_view']}->{f_entry['target_view']} · "
                        f"score {f_best.total:.2f} · {f_best.deviation_mm:.1f} mm from the locus"
                    )
                lines.insert(0, "\n".join(header) + "\n")
            _note = getattr(self, "_symmetry_note", "")
            if _note:
                lines.append(_note)
            self._report("\n\n".join(lines))

        if any_match:
            self._status(State.FOUND, active=False)
        elif any_ambiguous:
            self._status(State.AMBIGUOUS_STATE, active=False)
        else:
            self._status(State.NOT_FOUND, active=False)

    @staticmethod
    def _dominant_focus(scored):
        """
        The single strongest CONFIDENT correspondence across all scored entries, or
        None. Delegates the selection rule to the pure, unit-tested
        `candidate_matching.dominant_index`. Returns (entry, ScoredCandidate).
        """
        from .candidate_matching import dominant_index
        idx = dominant_index([m for _, m in scored])
        if idx is None:
            return None
        entry, match = scored[idx]
        return (entry, match.best)

    # ── Multiple-findings UX: declutter + review one at a time ────────────────

    def _build_findings(self, scored) -> None:
        """Order the scored entries into reviewable findings (strongest first)."""
        findings: List[dict] = []
        for (entry, match) in scored:
            best = match.best
            findings.append({
                "entry": entry, "match": match, "best": best,
                "score": float(best.total) if best is not None else -1.0,
                "box": list(best.candidate.box_px) if best is not None else None,
                "status": match.status,
                "vtk_w": getattr(entry["target_view_data"], "vtk_widget", None),
                "region": entry["region"],
            })
        order = sorted(range(len(findings)), key=lambda k: findings[k]["score"], reverse=True)
        self._findings = [findings[k] for k in order]
        for i, f in enumerate(self._findings):
            f["number"] = i + 1

    def _finding_anchor_box(self, f: dict):
        """The box to draw for a finding: the matched candidate, else a small box at
        the predicted region's nominal point (so a no-match finding still has a
        reviewable marker)."""
        if f.get("box"):
            return f["box"]
        region = f.get("region")
        nom = getattr(region, "nominal_point_px", None) if region is not None else None
        if nom:
            x, y = float(nom[0]), float(nom[1])
            return [x - 22, y - 22, x + 22, y + 22]
        return None

    def _render_findings(self) -> None:
        """Draw ONLY the selected finding's full overlay; others as small markers."""
        if not self._findings:
            return
        sel = max(0, min(self._selected_finding, len(self._findings) - 1))
        self._selected_finding = sel

        by_view: Dict[int, list] = {}
        for idx, f in enumerate(self._findings):
            vw = f.get("vtk_w")
            if vw is None:
                continue
            by_view.setdefault(id(vw), [vw, []])[1].append((idx, f))

        for _vid, (vw, flist) in by_view.items():
            try:
                region_render.clear_region_actors(vw)
            except Exception:
                pass
            sel_f = next((f for idx, f in flist if idx == sel), None)
            # 1) selected finding's region band + heatmap UNDER everything.
            if sel_f is not None:
                try:
                    region_render.draw_search_region(vw, sel_f["region"], clear_first=False)
                except Exception:
                    pass
                if HEATMAP_ENABLED:
                    try:
                        self._maybe_draw_heatmap(sel_f["entry"], sel_f["match"])
                    except Exception:
                        pass
            # 2) small markers for every OTHER finding on this viewport.
            for idx, f in flist:
                if idx == sel:
                    continue
                box = self._finding_anchor_box(f)
                if box is not None:
                    try:
                        region_render.draw_finding(vw, box, f["number"], selected=False)
                    except Exception:
                        pass
            # 3) selected finding's box + leader-lined label ON TOP.
            if sel_f is not None:
                box = self._finding_anchor_box(sel_f)
                if box is not None:
                    try:
                        region_render.draw_finding(
                            vw, box, sel_f["number"], selected=True,
                            score=(sel_f["score"] if sel_f["score"] >= 0 else None),
                        )
                    except Exception:
                        pass

        self._update_findings_panel()
        self._report(self._findings_report_text())
        logger.info(
            "[3D-Cursor][FINDINGS] %d finding(s), reviewing #%d",
            len(self._findings), self._findings[sel]["number"],
        )

    def _select_finding(self, i: int) -> None:
        """Review finding `i` (0-based): redraw it full, others as markers."""
        if not self._findings:
            return
        self._selected_finding = max(0, min(int(i), len(self._findings) - 1))
        self._render_findings()

    def _findings_items(self):
        """(global_index, number, score_or_None, subtitle) for the panels."""
        out = []
        for idx, f in enumerate(self._findings):
            e = f["entry"]
            sub = f"{e['laterality']} {e['source_view']}->{e['target_view']}"
            out.append((idx, f["number"], (f["score"] if f["score"] >= 0 else None), sub))
        return out

    def _update_findings_panel(self) -> None:
        """Show/refresh the on-image corner panel + the synced sidebar list."""
        items = self._findings_items()
        # Toolbar combo + sidebar list (reliable, outside the VTK viewport).
        try:
            fn = getattr(self._tab, "cursor3d_set_findings", None)
            if callable(fn):
                fn(items, self._selected_finding, self._select_finding)
        except Exception:
            pass

        # The on-image VTK-overlaid panel is OFF by default (does not paint over VTK
        # on many setups). The toolbar/sidebar above are the selectors.
        if not ONIMAGE_PANEL:
            self._clear_findings_panels()
            return

        panels = getattr(self, "_findings_panels", None)
        if panels is None:
            panels = {}
            self._findings_panels = panels

        if len(self._findings) <= 1:
            self._clear_findings_panels()      # nothing to disambiguate
            return

        host = self._findings[0].get("vtk_w")
        if host is None:
            return
        try:
            from .findings_panel import FindingsOverlayPanel
        except Exception:
            return
        panel = panels.get("main")
        try:
            if panel is None:
                panel = FindingsOverlayPanel(host)
                panel.selected.connect(self._select_finding)
                panels["main"] = panel
            panel.set_findings(items, selected=self._selected_finding)
        except Exception as exc:  # never let the overlay break the workflow
            logger.warning(f"[3D-Cursor][FINDINGS] corner panel unavailable: {exc}")

    def _clear_findings_panels(self) -> None:
        panels = getattr(self, "_findings_panels", None)
        if panels:
            for p in list(panels.values()):
                try:
                    p.hide()
                    p.setParent(None)
                    p.deleteLater()
                except Exception:
                    pass
        self._findings_panels = {}

    def _findings_report_text(self) -> str:
        if not self._findings:
            return ""
        sel = self._selected_finding
        lines: List[str] = []
        n = len(self._findings)
        if n > 1:
            lines.append(f"{n} findings — reviewing #{self._findings[sel]['number']} "
                         f"(click a row, on the image or here, to switch):")
            for idx, f in enumerate(self._findings):
                mark = "▸" if idx == sel else "  "
                sc = f"{f['score']:.2f}" if f["score"] >= 0 else f["status"]
                e = f["entry"]
                lines.append(f"{mark} #{f['number']}  score {sc}  ·  "
                             f"{e['laterality']} {e['source_view']}->{e['target_view']}")
            lines.append("")
        f = self._findings[sel]
        lines.append(self._describe(f["entry"], f["match"]))
        note = getattr(self, "_symmetry_note", "")
        if note:
            lines.append("")
            lines.append(note)
        return "\n".join(lines)

    # ── factor 3: appearance / histogram similarity ──────────────────────────

    def _appearance_fn_for(self, entry: dict):
        """
        Build (and cache) the factor-3 appearance-similarity callable for one entry,
        or None when disabled / pixels unavailable.

        Reads the source + target DICOM pixel arrays ONCE and closes over them. This
        currently runs on the GUI thread (default OFF via AIPACS_CURSOR3D_APPEARANCE);
        production must move the pixel read off-thread before enabling by default.
        """
        if not APPEARANCE_ENABLED:
            return None
        if entry.get("_appearance_fn") is not None:
            return entry["_appearance_fn"]
        try:
            from . import appearance_similarity as _app

            def _pixels(view_data):
                path = str(getattr(view_data, "dicom_path", "") or "")
                if not path or not os.path.isfile(path):
                    return None
                import pydicom
                return pydicom.dcmread(path, force=True).pixel_array

            src_px = _pixels(entry.get("source_view_data"))
            tgt_px = _pixels(entry.get("target_view_data"))
            if src_px is None or tgt_px is None:
                return None
            # Reuse these already-decoded arrays for the feature store (so the
            # appearance pattern is captured with NO extra pixel read).
            entry["_source_pixels"] = src_px
            entry["_target_pixels"] = tgt_px
            src_box = entry["source_lesion"].to_pixel_box()
            sfeat = _app.source_features(src_px, src_box)
            if not sfeat.ok:
                return None

            def _score(cand_box):
                return _app.candidate_appearance_score(sfeat, tgt_px, cand_box)

            entry["_appearance_fn"] = _score
            logger.info("[3D-Cursor][3-FACTOR] appearance similarity enabled for this view")
            return _score
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[3D-Cursor][3-FACTOR] appearance unavailable: {exc}")
            return None

    def _maybe_draw_heatmap(self, entry: dict, match) -> None:
        """Render the dense three-factor heatmap on the target viewport (flag-gated)."""
        if not HEATMAP_ENABLED:
            return
        try:
            from . import cross_view_heatmap as _hm
            vtk_w = getattr(entry["target_view_data"], "vtk_widget", None)
            if vtk_w is None:
                return
            # Pull the hot core onto the KNOWN lesion — the geometric height along the
            # band is only a weak prior. Precedence:
            #   1. a PAIRED lesion's own AI-located target box (exact vertical position);
            #   2. the second-pass matched candidate;
            #   3. else no emphasis → the core stays at the geometric nominal.
            emphasis = None
            _pt = entry.get("paired_target_box_px")
            if _pt is not None:
                try:
                    b = [float(v) for v in _pt]
                    emphasis = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
                except Exception:
                    emphasis = None
            if emphasis is None:
                best = getattr(match, "best", None) if match is not None else None
                if best is not None:
                    try:
                        b = [float(v) for v in best.candidate.box_px]
                        emphasis = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
                    except Exception:
                        emphasis = None
            field = _hm.build_heatmap_field(entry["region"], emphasis_px=emphasis)
            if field is not None:
                region_render.draw_heatmap_field(vtk_w, field)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[3D-Cursor][3-FACTOR] heatmap render failed (non-fatal): {exc}")

    # ── diagnostics ──────────────────────────────────────────────────────────

    def _csv_view_summary(self) -> str:
        """
        Per-image box counts for the current second-pass CSV.

        This one line is what was missing when the first live failure had to be
        diagnosed by hand: it says immediately whether the pass found nothing at
        all, or found things in the WRONG views. On study 50016 it would have read
        `IMG-68304=1 IMG-68306=2 IMG-68308=1 IMG-68310=0` — instantly showing the
        target view (L-MLO / IMG-68310) was empty while other views had detections.
        """
        if not self._second_csv or not os.path.isfile(str(self._second_csv)):
            return "no csv"
        try:
            from modules.ai_imaging.ai_module_ui.csv_table import read_csv_table
            df = read_csv_table(str(self._second_csv))
            parts = []
            for row in getattr(df, "rows", []) or []:
                path = str(row.get("dicom_full_path", "") or "")
                name = os.path.basename(path) or "?"
                n = len(_parse_boxes(row.get("box", "")))
                parts.append(f"{name}={n}")
            return " ".join(parts) if parts else "empty csv"
        except Exception as exc:  # noqa: BLE001
            return f"summary failed: {exc}"

    def _finish_region_only(self, message: str) -> None:
        self._matched = True
        lines = [
            self._describe(e, None) + f"\n  {message}"
            for e in self._pending
        ]
        self._report("\n\n".join(lines))
        self._status(State.REGION_ONLY, active=False)
        for e in self._pending:
            self._persist(e, None)

    # ── candidate loading ────────────────────────────────────────────────────

    def _load_candidates(self, vtk_widget) -> List[Candidate]:
        """
        Read the second-pass detections that belong to the TARGET viewer's series.

        Reuses the widget's own row-matching (`get_series_ai_data_from_df`) rather
        than re-deriving which CSV rows belong to which series — that matcher has a
        four-way fallback chain (series dir, filename, numeric token, instance
        number) which we must not fork.
        """
        out: List[Candidate] = []
        if vtk_widget is None or not self._second_csv:
            return out

        try:
            from modules.ai_imaging.ai_module_ui.csv_table import read_csv_table
            df = read_csv_table(str(self._second_csv))
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[3D-Cursor][2-STAGE] cannot read second-pass CSV: {exc}")
            return out

        rows = []
        try:
            getter = getattr(vtk_widget, "get_series_ai_data_from_df", None)
            if callable(getter):
                data = getter(df, check_all_rows=True)
                if isinstance(data, list):
                    for tbl in data:
                        rows.extend(getattr(tbl, "rows", []) or [])
                elif data is not None:
                    rows = list(getattr(data, "rows", []) or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[3D-Cursor][2-STAGE] series row match failed: {exc}")
            return out

        classes = self._load_classifications()

        idx = 0
        for row in rows:
            boxes = _parse_boxes(row.get("box", ""))
            scores = _parse_scores(row.get("scores", ""))
            removed = set()
            for rb in _parse_boxes(row.get("removed", "")):
                removed.add(tuple(round(v, 2) for v in rb))

            for i, box in enumerate(boxes):
                if tuple(round(v, 2) for v in box) in removed:
                    continue  # the user already rejected this box
                score = scores[i] if i < len(scores) else 0.5
                out.append(Candidate(
                    index=idx,
                    box_px=box,
                    score=score,
                    classification=self._lookup_class(classes, box),
                ))
                idx += 1

        print(f"[3D-Cursor][2-STAGE] loaded {len(out)} second-pass candidates for target view")
        return out

    def _load_classifications(self) -> List[Tuple[List[float], str]]:
        """[( [xmin,ymin,xmax,ymax], label ), ...] from the second-pass cls CSV."""
        out: List[Tuple[List[float], str]] = []
        if not self._second_cls_csv or not os.path.isfile(str(self._second_cls_csv)):
            return out
        try:
            from modules.ai_imaging.ai_module_ui.csv_table import read_csv_table
            df = read_csv_table(str(self._second_cls_csv))
            for row in getattr(df, "rows", []) or []:
                try:
                    box = [
                        float(row.get("xmin")), float(row.get("ymin")),
                        float(row.get("xmax")), float(row.get("ymax")),
                    ]
                except Exception:
                    continue
                label = str(row.get("labels_pred") or "").strip()
                if label:
                    out.append((box, label))
        except Exception:
            pass
        return out

    @staticmethod
    def _lookup_class(classes, box: List[float], tol: float = 2.0) -> Optional[str]:
        """
        Tolerant box join.

        The existing classification join uses EXACT float equality on the four
        corners, which fails whenever the two CSVs round differently. A 2-pixel
        tolerance is still unambiguous at mammographic resolution (detections are
        tens of pixels apart at minimum) and recovers labels the strict join drops.
        """
        for cbox, label in classes:
            if all(abs(cbox[i] - box[i]) <= tol for i in range(4)):
                return label
        return None

    # ── reporting / persistence ──────────────────────────────────────────────

    def _describe(self, entry: dict, match: Optional[MatchResult]) -> str:
        r: SearchRegion = entry["region"]
        head = (
            f"{entry['laterality']} · {entry['source_view']} → {entry['target_view']}\n"
            f"  Region: {r.method.upper()} at {r.distance_mm:.1f} mm "
            f"({r.distance_kind}), band ±{r.inner_band_mm:.0f}/±{r.outer_band_mm:.0f} mm"
        )
        if match is None:
            return head

        if match.status == MATCH and match.best is not None:
            b = match.best
            head += (
                f"\n  ✓ MATCH — score {b.total:.2f}, "
                f"{b.deviation_mm:.1f} mm from the locus, "
                f"AI confidence {b.candidate.score:.2f}"
                f"\n    {self._components_line(b)}"
            )
        elif match.status == AMBIGUOUS:
            head += f"\n  ? AMBIGUOUS — {len(match.alternatives)} candidates within {match.margin:.2f}:"
            for i, s in enumerate(match.alternatives, start=1):
                head += f"\n    ALT {i}: score {s.total:.2f}, {s.deviation_mm:.1f} mm from locus"
        else:
            head += f"\n  ✗ {match.message}"
            # Say HOW HARD we looked. "No match" is only meaningful with the depth
            # of the search attached — otherwise the user cannot tell a working
            # feature from a broken one (which is exactly what happened on 50016).
            low = self._lowest_tried
            if low is not None:
                tried = ", ".join(f"{t:.2f}" for t in self._ladder[: self._rung])
                head += (
                    f"\n    The AI was re-run down to threshold {low:.2f} "
                    f"(tried: {tried}) and still detected nothing inside the "
                    f"predicted region in the {entry['target_view']} view."
                    f"\n    The region above remains valid — review it manually."
                )
        return head

    @staticmethod
    def _components_line(sc) -> str:
        return "  ".join(f"{k}={v:.2f}" for k, v in sc.components.items())

    def _persist(self, entry: dict, match: Optional[MatchResult]) -> None:
        try:
            sess = session_from_result(
                study_uid=getattr(self, "_study_uid", "") or "",
                laterality=entry["laterality"],
                source_view=entry["source_view"],
                target_view=entry["target_view"],
                source_lesion=entry["source_lesion"],
                region=entry["region"],
                match_result=match,
                original_threshold=self._original_threshold,
                second_pass_threshold=self._second_threshold,
                second_pass_detection_csv=self._second_csv,
                second_pass_run_id=self._second.run_id,
                second_pass_status=(
                    "failed" if self._second_failed
                    else ("done" if self._second_csv else "not_started")
                ),
                second_pass_error=self._second_error,
                target_nipple_px=(
                    entry["target_geom"].nipple.x_px,
                    entry["target_geom"].nipple.y_px,
                ),
                source_nipple_px=(
                    entry["source_geom"].nipple.x_px,
                    entry["source_geom"].nipple.y_px,
                ),
                pectoral_angle_deg=getattr(self, "_pectoral_angle_deg", None),
                pnl=entry.get("pnl"),
            )
            save_session(sess, getattr(self, "_attachments_path", "") or "")
        except Exception as exc:  # noqa: BLE001
            print(f"[3D-Cursor][2-STAGE] session persist failed (non-fatal): {exc}")
        # Independent of the session audit record: store the reusable per-lesion
        # descriptors (geometry + appearance pattern) for future contralateral use.
        self._store_lesion_features(entry, match)

    def _store_lesion_features(self, entry: dict, match: Optional[MatchResult]) -> None:
        """
        Persist per-lesion GEOMETRY (always) and the APPEARANCE pattern descriptor
        (when the pixels were already decoded for factor 3) to the lesion feature
        store — so the SAME measurements can later drive contralateral R↔L matching,
        not only today's CC↔MLO correspondence. Storage only; never raises.
        """
        if not FEATURE_STORE_ENABLED:
            return
        try:
            attach = getattr(self, "_attachments_path", "") or ""
            if not attach:
                return
            study_uid = getattr(self, "_study_uid", "") or ""
            src_view_data = entry.get("source_view_data")
            tgt_view_data = entry.get("target_view_data")
            patient_id = str(
                getattr(src_view_data, "patient_id", "")
                or getattr(self, "_patient_id", "")
                or ""
            )

            def _opt_float(v):
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            def _geom_features(geom, lesion, view_data=None):
                sp = geom.image.pixel_spacing
                axial = float(geom.compute_lesion_depth_mm(lesion))
                pnl = geom.pectoral_reference_distance_mm()
                frac = (axial / pnl) if (pnl and pnl > 1e-6) else None
                return _lfs.LesionGeometryFeatures(
                    center_px=tuple(float(v) for v in lesion.center_px),
                    nipple_px=(float(geom.nipple.x_px), float(geom.nipple.y_px)),
                    pixel_spacing_mm=(float(sp.x), float(sp.y)),
                    radial_distance_mm=round(float(geom.compute_lesion_radial_distance_mm(lesion)), 3),
                    axial_depth_mm=round(axial, 3),
                    height_mm=round(float(geom.compute_lesion_height_mm(lesion)), 3),
                    pnl_length_mm=round(float(pnl), 3) if pnl else None,
                    pnl_fractional_depth=round(float(frac), 4) if frac is not None else None,
                    pectoral_angle_deg=(
                        float(geom.pectoral_angle_deg)
                        if geom.pectoral_angle_deg is not None else None
                    ),
                    physical_size_mm2=round(float(lesion.width_mm * lesion.height_mm), 3),
                    box_shape_aspect=(
                        round(float(lesion.width_mm / lesion.height_mm), 4)
                        if lesion.height_mm > 1e-6 else None
                    ),
                    positioner_primary_angle_deg=_opt_float(
                        getattr(view_data, "positioner_primary_angle_deg", None)),
                    body_part_thickness_mm=_opt_float(
                        getattr(view_data, "body_part_thickness_mm", None)),
                )

            def _describe(px, box, sp):
                if px is None:
                    return None
                try:
                    from .appearance_similarity import describe_region
                    return describe_region(px, box, spacing_mm=(float(sp.x), float(sp.y)))
                except Exception:
                    return None

            # ── source lesion (geometry always; appearance if pixels present) ──
            src_geom = entry["source_geom"]
            src_lesion = entry["source_lesion"]
            src_box = [float(v) for v in src_lesion.to_pixel_box()]
            src_appearance = _describe(
                entry.get("_source_pixels"), src_box, src_geom.image.pixel_spacing
            )
            src_rec = _lfs.LesionFeatureRecord(
                lesion_uid=_lfs.LesionFeatureRecord.new_uid(),
                patient_id=patient_id,
                study_uid=str(study_uid),
                laterality=str(entry["laterality"]),
                view_position=str(entry["source_view"]),
                box_px=src_box,
                origin="picked",
                score=float(getattr(src_lesion, "score", 0.5)),
                series_uid=(str(getattr(src_view_data, "series_uid", "") or "") or None),
                geometry=_geom_features(src_geom, src_lesion, src_view_data),
                appearance=src_appearance,
            )
            _lfs.save_lesion_feature(src_rec, attach)

            # ── the corresponding candidate, only on a CONFIDENT match ──
            best = getattr(match, "best", None) if match is not None else None
            if best is not None:
                from .geometry import LesionLocation
                tgt_geom = entry["target_geom"]
                tsp = tgt_geom.image.pixel_spacing
                cand_box = [float(v) for v in best.candidate.box_px]
                cand_lesion = LesionLocation.from_pixel_box(
                    list(cand_box), tsp, score=float(best.candidate.score)
                )
                tgt_rec = _lfs.LesionFeatureRecord(
                    lesion_uid=_lfs.LesionFeatureRecord.new_uid(),
                    patient_id=patient_id,
                    study_uid=str(study_uid),
                    laterality=str(entry["laterality"]),
                    view_position=str(entry["target_view"]),
                    box_px=cand_box,
                    origin="candidate",
                    score=float(best.candidate.score),
                    classification=getattr(best.candidate, "classification", None),
                    series_uid=(str(getattr(tgt_view_data, "series_uid", "") or "") or None),
                    geometry=_geom_features(tgt_geom, cand_lesion, tgt_view_data),
                    appearance=_describe(entry.get("_target_pixels"), cand_box, tsp),
                )
                _lfs.save_lesion_feature(tgt_rec, attach)

            logger.info(
                "[3D-Cursor][FEATURES] stored lesion descriptors "
                f"({entry['laterality']} {entry['source_view']}->{entry['target_view']}, "
                f"appearance={'yes' if (src_appearance and src_appearance.get('ok')) else 'geometry-only'})"
            )
        except Exception as exc:  # noqa: BLE001 — storage must never be fatal
            logger.warning(f"[3D-Cursor][FEATURES] store failed (non-fatal): {exc}")

    def _run_contralateral_analysis(self, scored) -> None:
        """
        Store-based Right↔Left symmetry pass. For every stored lesion of this patient
        it asks whether the OTHER breast has a matching finding at the mirror location
        (same view); a finding with NO counterpart is flagged as a possible asymmetry.

        Gated by AIPACS_CURSOR3D_CONTRALATERAL (default OFF — surfacing an asymmetry
        call is a clinical action to enable deliberately). Decision support only;
        never raises. Result is stashed in `self._symmetry_note` and rendered in the
        findings panel by `_findings_report_text` / the legacy report.
        """
        self._symmetry_note = ""
        try:
            if not _cxl.contralateral_enabled():
                return
            attach = getattr(self, "_attachments_path", "") or ""
            if not attach:
                return
            patient_id = ""
            for entry, _ in (scored or []):
                pid = str(getattr(entry.get("source_view_data"), "patient_id", "") or "")
                if pid:
                    patient_id = pid
                    break
            if not patient_id:
                patient_id = str(getattr(self, "_patient_id", "") or "")
            if not patient_id:
                logger.info("[3D-Cursor][SYMMETRY] no patient id — contralateral pass skipped")
                return

            results = _cxl.analyze_patient_symmetry_from_store(patient_id, attach)
            if not results:
                return

            for r in results:
                g = r.query
                logger.info(
                    "[3D-Cursor][SYMMETRY] %s %s uid=%s -> %s (best=%.2f)",
                    g.get("laterality"), g.get("view_position"), g.get("lesion_uid"),
                    r.status, (r.best.total if r.best else 0.0),
                )

            asy = [r for r in results if r.asymmetry_flag]
            sym = [r for r in results if r.status == _cxl.SYMMETRIC]
            if asy:
                note = ["⚠ ASYMMETRY REVIEW — finding(s) whose counterpart in the other breast does not match:"]
                for r in asy:
                    g = r.query
                    best = f"{r.best.total:.2f}" if r.best else "—"
                    note.append(
                        f"  • {g.get('laterality')} {g.get('view_position')} "
                        f"(best mirror {best}) — {r.message}"
                    )
                note.append("  (Decision support, not a diagnosis — review for a developing asymmetry.)")
                self._symmetry_note = "\n".join(note)
            elif sym:
                self._symmetry_note = (
                    "Contralateral symmetry: every comparable finding has a mirror "
                    "counterpart in the other breast (lower concern)."
                )
            else:
                # Only insufficient-data results — be honest that no comparison was
                # possible; do NOT imply symmetry or asymmetry.
                self._symmetry_note = (
                    "Contralateral symmetry: the other breast has no analysed finding "
                    "in this view, so no R↔L comparison was possible (not an asymmetry)."
                )
        except Exception as exc:  # noqa: BLE001 — decision support must never be fatal
            logger.warning(f"[3D-Cursor][SYMMETRY] analysis failed (non-fatal): {exc}")
            self._symmetry_note = ""
