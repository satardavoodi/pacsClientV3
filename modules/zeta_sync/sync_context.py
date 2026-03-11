from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .sync_types import SyncTarget


@dataclass
class SyncContext:
    """
    Describes a viewer participating in sync.

    Keep this lightweight; viewer-specific data should be queried lazily by
    the sync manager to avoid tight coupling.
    """

    viewer_id: str
    target_type: SyncTarget
    series_uid: Optional[str] = None
    study_uid: Optional[str] = None
    frame_of_reference_uid: Optional[str] = None
    orientation: Optional[Tuple[float, ...]] = None
