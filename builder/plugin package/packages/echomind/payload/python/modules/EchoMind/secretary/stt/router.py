from __future__ import annotations

from typing import Any, Optional

from .providers.native_irannobat import NativeIrannobatProvider
from .providers.openai_transcribe import OpenAITranscribeProvider
from .providers.v2t_google import V2tGoogleProvider


class SttRouter:
    def __init__(self):
        self.native = NativeIrannobatProvider()
        self.openai = OpenAITranscribeProvider()
        self.v2t = V2tGoogleProvider()

    def _get_provider(self, route: str):
        if (route or "").lower() == "openai":
            return self.openai
        if (route or "").lower() == "v2t":
            return self.v2t
        return self.native

    def transcribe_files(
        self,
        paths: list[str],
        route: str = "native",
        fallback: bool = True,
        quality_mode: str = "clear",
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        # The shared service owns provider selection and fallback for every EchoMind.
        from modules.EchoMind.voice_transcription import VoiceTranscriptionService
        return VoiceTranscriptionService().transcribe(
            paths, quality_mode=quality_mode, timeout=timeout,
        )
