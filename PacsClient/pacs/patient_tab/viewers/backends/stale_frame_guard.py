from __future__ import annotations

from typing import Optional


def should_render_ready_slice(
    ready_slice: int,
    requested_slice: Optional[int],
    current_slice: Optional[int],
    ready_generation: int,
    current_generation: int,
) -> bool:
    """Return True only for the latest in-generation slice request."""
    if requested_slice is None or current_slice is None:
        return False
    if int(ready_generation) != int(current_generation):
        return False
    ready = int(ready_slice)
    return ready == int(requested_slice) and ready == int(current_slice)
