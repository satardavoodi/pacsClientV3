"""Phase-1 object/blob cache boundary for FAST stack interaction.

The first implementation is intentionally local/no-op.  It gives the FAST
viewer a stable interface for future slice-level DICOM object retrieval without
forcing download manager or server protocol changes in the protected-lane pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ObjectCache(Protocol):
    def has_object(self, series_uid: str, slice_index: int) -> bool:
        ...

    def request_object(self, priority: int, series_uid: str, slice_index: int) -> bool:
        ...


@dataclass
class NoopObjectCache:
    """Default boundary until slice-level retrieval is connected."""

    def has_object(self, series_uid: str, slice_index: int) -> bool:
        return False

    def request_object(self, priority: int, series_uid: str, slice_index: int) -> bool:
        return False


_instance: ObjectCache = NoopObjectCache()


def get_object_cache() -> ObjectCache:
    return _instance


def set_object_cache(cache: ObjectCache) -> None:
    global _instance
    _instance = cache


def is_noop_object_cache() -> bool:
    """Fast probe: True when no real ObjectCache has been wired yet.

    FAST-mode stack-drag hot paths can use this to skip the per-target
    ``has_object``/``request_object`` submission loop when the default
    Noop cache is still in place. Saves one ``hasattr`` + one method
    dispatch + one global lookup + one try/except per item per accepted
    drag target. Small per-call but measurable on multi-second drags
    that accept 40-60 targets with 3-5 work items each.
    """
    return isinstance(_instance, NoopObjectCache)


__all__ = [
    "ObjectCache",
    "NoopObjectCache",
    "get_object_cache",
    "set_object_cache",
    "is_noop_object_cache",
]
