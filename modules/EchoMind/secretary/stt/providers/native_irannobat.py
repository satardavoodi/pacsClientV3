from __future__ import annotations

from typing import Any, Optional


class NativeIrannobatProvider:
    """Secretary's "AI-PACS server" STT route.

    2026-07-13 — the endpoint is NO LONGER hard-coded here. This used to POST to
    ``modules.EchoMind.ai_chat_config.URL_GEN_TRANSCRIPT``, a module constant built
    at import time from ``AI_BASE`` — so the destination could only be changed by
    editing code, and it could silently disagree with the EchoMind chat.

    It now delegates to the shared :class:`VoiceTranscriptionService`, which reads
    **Settings ▸ EchoMind ▸ Voice to Text** on every call. Both EchoMind modules
    therefore upload to the same configured server, and switching servers in
    Settings takes effect immediately.

    The returned dict keeps its historical keys (``ok`` / ``provider`` /
    ``transcript`` / ``session_id`` / ``raw`` / ``files``) and additionally now
    carries ``quality_report`` — do not strip it: the chat's low-quality rejection
    handling and auto "noisy" retry depend on it.
    """

    name = "native"

    # 2026-08-10 — the default was a hard 360, and `VoiceTranscriptionService`
    # resolves its budget as `int(timeout or cfg["timeout_seconds"] or ...)`, so
    # that truthy default OVERRODE the user's Settings ▸ EchoMind ▸ Voice to Text
    # timeout on every Secretary transcription. `None` means "no opinion" and lets
    # the service fall through to the configured value — the same contract the
    # chat path already uses (`transcribe(..., timeout=None)`).
    def transcribe_files(
        self, paths: list[str], quality_mode: str = "clear", timeout: Optional[int] = None
    ) -> dict[str, Any]:
        if not paths:
            return {
                "ok": False,
                "provider": self.name,
                "error": "No files provided.",
                "transcript": "",
                "quality_report": [],
                "files": [],
            }

        # Lazy import keeps this leaf provider importable without the settings /
        # requests chain, and mirrors the service's own lazy provider imports.
        from modules.EchoMind.voice_transcription import VoiceTranscriptionService

        out = VoiceTranscriptionService().transcribe(
            paths, quality_mode=quality_mode, timeout=timeout
        )
        out.setdefault("provider", self.name)
        return out
