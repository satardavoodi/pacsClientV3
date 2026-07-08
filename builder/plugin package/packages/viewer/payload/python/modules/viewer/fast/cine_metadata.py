"""Pure (Qt-free) helpers for cine / multi-frame playback metadata.

Resolves a playback frame rate from the DICOM cine-timing tags following the
standard precedence, and classifies whether a series is a cine loop. Kept
dependency-free (stdlib only) so it is unit-testable headless and can be reused
by the FAST pipeline and the cine player without importing either.

DICOM references:
- RecommendedDisplayFrameRate (0008,2144) — explicit display fps (US/XA/echo).
- CineRate (0018,0040) — acquisition frames per second.
- FrameTime (0018,1063) — ms per frame; fps = 1000 / FrameTime.
- FrameTimeVector (0018,1065) — per-frame durations (variable-rate; use mean).
Multi-frame cine objects: Ultrasound Multi-frame (A.7), X-Ray Angiographic (A.14),
Enhanced MR (A.36), Ophthalmic Photography (A.41).
"""
from __future__ import annotations

from typing import Optional, Sequence

# Clamp resolved rates to a sane, safe display range. Sub-1 fps is treated as a
# still/very-slow loop; nothing plays faster than 60 fps in the viewer.
MIN_CINE_FPS = 1.0
MAX_CINE_FPS = 60.0
# Fallback when a multi-frame object carries NO timing tag at all. A neutral,
# conservative default (many US/echo cines are 15-30 fps; XA often ~15).
DEFAULT_CINE_FPS = 15.0


def _pos_float(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0.0:  # NaN or non-positive
        return None
    return f


def clamp_fps(fps: Optional[float]) -> Optional[float]:
    """Clamp a frame rate into [MIN_CINE_FPS, MAX_CINE_FPS]; None passes through."""
    f = _pos_float(fps)
    if f is None:
        return None
    return max(MIN_CINE_FPS, min(MAX_CINE_FPS, f))


def resolve_frame_rate(
    *,
    recommended_display_frame_rate: Optional[float] = None,
    cine_rate: Optional[float] = None,
    frame_time_ms: Optional[float] = None,
    frame_time_vector: Optional[Sequence[float]] = None,
    default: Optional[float] = None,
) -> Optional[float]:
    """Resolve a playback fps from cine-timing tags, by DICOM precedence.

    Order: RecommendedDisplayFrameRate → CineRate → 1000/FrameTime →
    1000/mean(FrameTimeVector) → *default*. Returns a clamped fps, or *default*
    (clamped) if no tag is usable, or None if there is nothing at all.
    """
    rec = _pos_float(recommended_display_frame_rate)
    if rec is not None:
        return clamp_fps(rec)
    cr = _pos_float(cine_rate)
    if cr is not None:
        return clamp_fps(cr)
    ft = _pos_float(frame_time_ms)
    if ft is not None:
        return clamp_fps(1000.0 / ft)
    if frame_time_vector:
        vals = [v for v in (_pos_float(x) for x in frame_time_vector) if v is not None]
        if vals:
            mean_ms = sum(vals) / len(vals)
            if mean_ms > 0:
                return clamp_fps(1000.0 / mean_ms)
    return clamp_fps(default)


def is_cine(num_frames: Optional[int]) -> bool:
    """True when the object holds more than one frame (a playable loop)."""
    try:
        return int(num_frames or 1) > 1
    except (TypeError, ValueError):
        return False


def playback_fps(
    num_frames: Optional[int],
    *,
    recommended_display_frame_rate: Optional[float] = None,
    cine_rate: Optional[float] = None,
    frame_time_ms: Optional[float] = None,
    frame_time_vector: Optional[Sequence[float]] = None,
) -> Optional[float]:
    """Convenience: resolved fps for a cine object, else None for a still image.

    Falls back to DEFAULT_CINE_FPS only when the object IS multi-frame but carries
    no usable timing tag — so a still image never gets a spurious rate."""
    if not is_cine(num_frames):
        return None
    return resolve_frame_rate(
        recommended_display_frame_rate=recommended_display_frame_rate,
        cine_rate=cine_rate,
        frame_time_ms=frame_time_ms,
        frame_time_vector=frame_time_vector,
        default=DEFAULT_CINE_FPS,
    )
