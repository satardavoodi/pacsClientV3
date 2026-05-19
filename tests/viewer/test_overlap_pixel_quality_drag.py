"""F1.2 — Drag-mode pixel quality gate (in-flight surrogate frames).

Companion to F1.1 ([test_overlap_pixel_quality.py](test_overlap_pixel_quality.py))
that validates rendering correctness during stack-drag in fast-interaction mode
— the regime where ``Lightweight2DPipeline`` is allowed to serve a "surrogate"
frame (the nearest cached neighbor) instead of decoding the requested slice.

Plan reference: F1.2.

Contract
--------
For each (filter_enabled × photometric) case:

1. **Drag through every slice** with
   ``fast_interaction=True, interaction_type='drag'``. For each frame, hash
   ``sha256(qimage.constBits())``. Some hashes will match the requested slice
   exactly (synchronous decode — first frame, or R1 staleness break forcing
   a real decode every 3rd consecutive surrogate). Others will be surrogates
   served from the nearest cached neighbor.
2. **Validity (100%)**: every drag-mode hash must appear in the
   *drag-reference* golden set — i.e. every served frame is the rendering
   of some slice from this series. Corrupted / dim / zero frames are caught.
3. **Surrogate proximity**: when a frame is a surrogate
   (``hash != drag_reference[idx]``), the matching reference index ``j`` must
   satisfy ``abs(j - idx) <= 10`` — the documented default surrogate distance
   (``_get_drag_surrogate_max_distance``) when no heavy download is active
   and velocity is below the boost threshold.
4. **Settle exactness (100%)**: after ``set_fast_interaction(False)``, a final
   ``get_rendered_frame(final_idx)`` must equal the SETTLED golden hash for
   that slice (the F1.1 contract re-asserted on the user-visible final frame
   after the drag is released).

The drag-reference follows the configured filter policy for the case.
With current FAST policy (R26), stack interaction keeps OpenCV filtering ON
when ``opencv_filter_enabled=True``, so ``filter_on_*`` drag runs validate
against ``overlap_pixel_filter_on_*`` references and ``filter_off_*`` runs
validate against ``overlap_pixel_filter_off_*`` references.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Reuse the Case matrix and synthetic-series factory from F1.1.
from tests.viewer.test_overlap_pixel_quality import (  # type: ignore
    CASES,
    Case,
    GOLDEN_DIR,
    N_SLICES,
    ROWS,
    COLS,
    _make_series,
    _qimage_sha256,
)

# Default surrogate distance from `_get_drag_surrogate_max_distance` when no
# heavy download is active and velocity is below the boost threshold. Tracked
# in [docs/plans/STACK_DRAG_PLAYBOOK_v2.3.6.md](docs/plans/STACK_DRAG_PLAYBOOK_v2.3.6.md).
_SURROGATE_MAX_DISTANCE = 10


def _load_drag_reference(case: Case) -> List[str]:
    """Return the per-slice drag-reference hashes for the case.

    Drag rendering uses the case's configured filter policy.
    """
    case_id = str(case.case_id)
    path = GOLDEN_DIR / f"overlap_pixel_{case_id}.json"
    if not path.exists():
        pytest.skip(
            f"Drag reference golden missing: {path}. "
            f"Run test_overlap_pixel_quality.py --capture-golden first."
        )
    return list(json.loads(path.read_text(encoding="utf-8"))["hashes"])


def _load_settled_reference(case: Case) -> List[str]:
    """Return the per-slice settled hashes for a case (F1.1 golden)."""
    if not case.golden_path.exists():
        pytest.skip(
            f"Settled golden missing for {case.case_id}. "
            f"Run test_overlap_pixel_quality.py --capture-golden first."
        )
    return list(json.loads(case.golden_path.read_text(encoding="utf-8"))["hashes"])


def _open_pipeline(series_dir: Path, case: Case):
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )

    cfg = PipelineConfig(
        pixel_cache_size=N_SLICES * 2,
        frame_cache_size=N_SLICES * 2,
        prefetch_radius=0,
        prefetch_workers=1,
        opencv_filter_enabled=case.filter_enabled,
    )
    p = Lightweight2DPipeline(config=cfg)
    p.open_series(str(series_dir))
    return p


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[c.case_id for c in CASES],
)
def test_overlap_pixel_quality_drag(case: Case, tmp_path: Path):
    """Drag-mode rendering must serve only valid neighbor frames; settle exact."""
    drag_ref = _load_drag_reference(case)
    drag_ref_set = set(drag_ref)
    drag_ref_index: Dict[str, List[int]] = {}
    for j, h in enumerate(drag_ref):
        drag_ref_index.setdefault(h, []).append(j)

    settled_ref = _load_settled_reference(case)
    assert len(drag_ref) == N_SLICES
    assert len(settled_ref) == N_SLICES

    series_dir = tmp_path / "series"
    _make_series(series_dir, case.photometric)

    pipeline = _open_pipeline(series_dir, case)
    try:
        # ── Drag through every slice in scan order ──────────────────────
        # The pipeline serves a mix of exact decodes and surrogates. The
        # contracts below validate both kinds without depending on which
        # specific indices end up as which.
        pipeline.set_fast_interaction(True, "drag")
        drag_hashes: List[str] = []
        for i in range(N_SLICES):
            f = pipeline.get_rendered_frame(i, interaction_type="drag")
            assert f is not None and f.qimage is not None
            assert f.width == COLS and f.height == ROWS, (
                f"{case.case_id}: drag QImage geometry wrong at idx={i}: "
                f"{f.width}x{f.height} (expected {COLS}x{ROWS})"
            )
            drag_hashes.append(_qimage_sha256(f.qimage))

        # ── Validity: every served frame is the rendering of *some* slice ─
        invalid = [
            (i, h[:12])
            for i, h in enumerate(drag_hashes)
            if h not in drag_ref_set
        ]
        assert not invalid, (
            f"{case.case_id}: {len(invalid)} drag frames are NOT a known slice "
            f"rendering - corruption or dim/zero QImage. First few: "
            f"{invalid[:5]}"
        )

        # ── Surrogate proximity: matching ref idx within +/- 10 of request ──
        far_surrogates: List[Dict[str, int]] = []
        for i, h in enumerate(drag_hashes):
            if h == drag_ref[i]:
                continue  # exact decode - perfect
            matches = drag_ref_index.get(h, [])
            if not matches:
                # Already caught by validity check above, but be defensive.
                far_surrogates.append({"idx": i, "matched_at": -1})
                continue
            nearest = min(matches, key=lambda j: abs(j - i))
            dist = abs(nearest - i)
            if dist > _SURROGATE_MAX_DISTANCE:
                far_surrogates.append(
                    {"idx": i, "matched_at": nearest, "distance": dist}
                )
        assert not far_surrogates, (
            f"{case.case_id}: surrogate served from beyond +/-"
            f"{_SURROGATE_MAX_DISTANCE} slices. Detail: {far_surrogates[:5]}"
        )

        # ── Settle exactness: end fast-interaction -> exact final hash ──
        # Mirrors the user-perceived "release-the-mouse" final frame.
        final_idx = N_SLICES - 1
        pipeline.set_fast_interaction(False)
        f_settled = pipeline.get_rendered_frame(final_idx)
        assert f_settled is not None and f_settled.qimage is not None
        actual_settled = _qimage_sha256(f_settled.qimage)
        assert actual_settled == settled_ref[final_idx], (
            f"{case.case_id}: settle frame hash drift at idx={final_idx}. "
            f"Expected {settled_ref[final_idx][:12]}, got "
            f"{actual_settled[:12]}. The user-perceived final frame after "
            f"releasing the drag has changed."
        )
    finally:
        try:
            pipeline.shutdown()
        except Exception:
            pass
