"""Hard request budgets for locally derived model-facing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class EvidenceUsage:
    image_count: int
    pixel_count: int
    byte_count: int


@dataclass(frozen=True)
class EvidenceBudget:
    """Bound model-facing evidence before any provider request is assembled."""

    max_images: int = 8
    max_focuses: int = 4
    max_pixels: int = 12_000_000
    max_bytes: int = 12 * 1024 * 1024

    def measure(self, qualities: Iterable[object], paths: Iterable[str | Path]) -> EvidenceUsage:
        quality_items = tuple(qualities)
        path_items = tuple(Path(path) for path in paths)
        return EvidenceUsage(
            image_count=len(path_items),
            pixel_count=sum(int(getattr(item, "pixel_count", 0)) for item in quality_items),
            byte_count=sum(path.stat().st_size for path in path_items),
        )

    def validate(self, usage: EvidenceUsage, focus_count: int) -> None:
        if int(focus_count) > self.max_focuses:
            raise ValueError("The focused evidence plan exceeds the focus limit.")
        if usage.image_count > self.max_images:
            raise ValueError("The focused evidence package exceeds the image limit.")
        if usage.pixel_count > self.max_pixels:
            raise ValueError("The focused evidence package exceeds the pixel limit.")
        if usage.byte_count > self.max_bytes:
            raise ValueError("The focused evidence package exceeds the byte limit.")
