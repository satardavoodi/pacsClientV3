from enum import Enum


class SyncMode(str, Enum):
    """Supported synchronization modes."""

    DISABLED = "disabled"
    CURSOR = "cursor"  # live cursor/point sync
    SLICE = "slice"    # slice-only sync
    FULL = "full"      # cursor + slice + WL (future)


class SyncTarget(str, Enum):
    """Types of viewer targets that can be synchronized."""

    VIEWER_2D = "viewer_2d"
    MPR = "mpr"
    UNKNOWN = "unknown"
