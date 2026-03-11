from __future__ import annotations

from typing import Any

from .providers.native_irannobat import NativeIrannobatProvider
from .providers.v2t_google import V2tGoogleProvider


class SttRouter:
    def __init__(self):
        self.native = NativeIrannobatProvider()
        self.v2t = V2tGoogleProvider()

    def _get_provider(self, route: str):
        if (route or "").lower() == "v2t":
            return self.v2t
        return self.native

    def transcribe_files(
        self,
        paths: list[str],
        route: str = "native",
        fallback: bool = True,
        quality_mode: str = "clear",
    ) -> dict[str, Any]:
        primary_route = (route or "native").lower()
        primary = self._get_provider(primary_route)
        first = primary.transcribe_files(paths, quality_mode=quality_mode)
        if first.get("ok") and str(first.get("transcript") or "").strip():
            first["route_requested"] = primary_route
            first["route_used"] = primary.name
            return first

        if not fallback:
            first["route_requested"] = primary_route
            first["route_used"] = primary.name
            return first

        secondary_route = "v2t" if primary_route != "v2t" else "native"
        secondary = self._get_provider(secondary_route)
        second = secondary.transcribe_files(paths, quality_mode=quality_mode)
        second["route_requested"] = primary_route
        second["route_used"] = secondary.name
        if not second.get("ok") and first.get("error"):
            second["first_error"] = first.get("error")
        return second

