"""Per-slice annotation storage.

No Qt / VTK imports — pure dict-based container.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import ToolModel


class ToolStore:
    """Stores annotations keyed by slice index."""

    def __init__(self) -> None:
        self._annotations: Dict[int, List[ToolModel]] = {}

    # ── Mutators ────────────────────────────────────────────────────

    def add(self, model: ToolModel) -> None:
        bucket = self._annotations.setdefault(model.slice_index, [])
        bucket.append(model)

    def remove(self, model: ToolModel) -> bool:
        """Remove *model* from its slice bucket.  Returns True if found."""
        bucket = self._annotations.get(model.slice_index)
        if bucket is None:
            return False
        try:
            bucket.remove(model)
            if not bucket:
                del self._annotations[model.slice_index]
            return True
        except ValueError:
            return False

    def clear_slice(self, slice_index: int) -> None:
        self._annotations.pop(slice_index, None)

    def clear_all(self) -> None:
        self._annotations.clear()

    # ── Queries ─────────────────────────────────────────────────────

    def get_for_slice(self, slice_index: int) -> List[ToolModel]:
        return list(self._annotations.get(slice_index, []))

    def count(self) -> int:
        return sum(len(v) for v in self._annotations.values())

    def find_selected(self, slice_index: int) -> Optional[ToolModel]:
        for m in self._annotations.get(slice_index, []):
            if m.is_selected:
                return m
        return None

    def deselect_all(self) -> None:
        for bucket in self._annotations.values():
            for m in bucket:
                m.is_selected = False
