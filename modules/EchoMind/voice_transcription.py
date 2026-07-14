"""VoiceTranscriptionService — the ONE place a recorded voice file is sent.

WHY (2026-07-13)
----------------
Voice-to-text had two disconnected pipelines and no configuration:

* **EchoMind chat** (`viewer_chat/ai_chat_pages.py::_transcribe_now`) POSTed straight
  to ``URL_GEN_TRANSCRIPT`` = ``{AI_BASE}/generate_transcript`` with ``AI_BASE``
  hard-coded to the Windows server. It ignored the Settings provider entirely.
* **Secretary EchoMind** (`home_ui/secretary_button_widget.py`) went through
  ``SttRouter`` → ``NativeIrannobatProvider``, which posted to the SAME hard-coded
  constant (but with no auth header).

So the destination could not be changed without editing code, and the two modules
could silently disagree. This module is the single authority: both callers now ask
it where to send, and it reads **Settings ▸ EchoMind ▸ Voice to Text** on EVERY
call — so switching servers in Settings takes effect immediately, with no restart.

THE IMPORT-BY-VALUE TRAP (do not reintroduce)
---------------------------------------------
``URL_GEN_TRANSCRIPT`` is a module-level f-string built from ``AI_BASE`` at IMPORT
time, and callers did ``from .ai_chat_config import URL_GEN_TRANSCRIPT`` — binding
the string once. Reassigning ``AI_BASE`` later changes nothing. That is exactly why
the endpoint MUST be resolved inside a function (``resolve_endpoint()``), per call.
Never capture the resolved URL in a module-level constant again.

RESPONSE CONTRACT
-----------------
``transcribe()`` returns the server's RAW JSON body **merged with** normalized keys,
so both existing callers keep working unchanged:

* the chat reads ``transcript`` and ``quality_report`` (a low-quality voice comes
  back as **HTTP 200 with ``accepted: false``** — that drives its auto "noisy"
  retry, so ``quality_report`` MUST survive this layer);
* Secretary reads ``ok`` / ``transcript`` / ``error`` / ``route_used``;
* usage/session fields the chat logs are preserved because the raw body is merged
  in first.

Flag: ``AIPACS_ECHOMIND_STT_ENDPOINT`` (default ON). ``=0`` restores the legacy
hard-coded ``{AI_BASE}/generate_transcript`` destination byte-for-byte.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

from .settings_store import (
    STT_HTTP_PROVIDERS,
    STT_PROVIDER_AIPACS_1,
    STT_PROVIDER_AIPACS_2,
    STT_PROVIDER_CUSTOM,
    STT_PROVIDER_GOOGLE,
    STT_PROVIDER_OPENAI,
    get_stt_settings,
)

log = logging.getLogger(__name__)

# ── The two built-in AI-PACS transcription servers ───────────────────────────
# Shown in the UI ONLY as "AI-PACS Server 1" / "AI-PACS Server 2" — never as raw
# addresses (product requirement).
AIPACS_SERVER_1_BASE = "http://81.16.117.196:8082"   # A100 GPU
AIPACS_SERVER_2_BASE = "http://80.210.31.214:8085"   # Windows server

#: (provider_id, display label) — the Settings combo renders exactly this.
STT_PROVIDER_CHOICES = (
    (STT_PROVIDER_AIPACS_1, "AI-PACS Server 1"),
    (STT_PROVIDER_AIPACS_2, "AI-PACS Server 2"),
    (STT_PROVIDER_GOOGLE, "Google Speech"),
    (STT_PROVIDER_OPENAI, "OpenAI Transcription"),
    (STT_PROVIDER_CUSTOM, "Custom Server"),
)

DEFAULT_ENDPOINT_PATH = "/generate_transcript"
DEFAULT_TIMEOUT_S = 360

_ENV_FLAG = "AIPACS_ECHOMIND_STT_ENDPOINT"


def endpoint_config_enabled() -> bool:
    """Kill switch. ``0`` = legacy hard-coded endpoint (byte-identical)."""
    raw = os.environ.get(_ENV_FLAG)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def provider_label(provider: str) -> str:
    for pid, label in STT_PROVIDER_CHOICES:
        if pid == provider:
            return label
    return str(provider or "")


# ── Endpoint resolution (PURE — unit-testable, no network, no Qt) ────────────
def base_url_for(provider: str, custom_base_url: str = "", custom_port: int = 0) -> str:
    """Base URL for an HTTP provider. Returns "" for Google/OpenAI (no endpoint)."""
    if provider == STT_PROVIDER_AIPACS_1:
        return AIPACS_SERVER_1_BASE
    if provider == STT_PROVIDER_AIPACS_2:
        return AIPACS_SERVER_2_BASE
    if provider == STT_PROVIDER_CUSTOM:
        base = str(custom_base_url or "").strip().rstrip("/")
        if not base:
            return ""
        if "://" not in base:
            base = "http://" + base
        port = int(custom_port or 0)
        if port > 0:
            # Only append when the URL doesn't already carry a port.
            host_part = base.split("://", 1)[1]
            if ":" not in host_part.split("/", 1)[0]:
                base = f"{base}:{port}"
        return base
    return ""


def build_endpoint(base_url: str, endpoint_path: str = DEFAULT_ENDPOINT_PATH) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    path = str(endpoint_path or DEFAULT_ENDPOINT_PATH).strip() or DEFAULT_ENDPOINT_PATH
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def resolve_endpoint(cfg: Optional[Dict[str, Any]] = None) -> str:
    """The transcription URL to POST to, resolved from Settings AT CALL TIME.

    Returns "" for Google/OpenAI (they are not endpoint-based) and for a Custom
    provider with no URL entered yet.
    """
    if not endpoint_config_enabled():
        return _legacy_endpoint()
    cfg = cfg or get_stt_settings()
    base = base_url_for(
        cfg.get("provider", STT_PROVIDER_AIPACS_2),
        cfg.get("custom_base_url", ""),
        cfg.get("custom_port", 0),
    )
    return build_endpoint(base, cfg.get("endpoint_path", DEFAULT_ENDPOINT_PATH))


def _legacy_endpoint() -> str:
    """The pre-2026-07-13 hard-coded destination (flag-off path only)."""
    try:
        from .ai_chat_config import URL_GEN_TRANSCRIPT
        return str(URL_GEN_TRANSCRIPT)
    except Exception:
        return build_endpoint(AIPACS_SERVER_2_BASE, DEFAULT_ENDPOINT_PATH)


def resolve_auth_token(cfg: Optional[Dict[str, Any]] = None) -> str:
    """Bearer token for the AI-PACS server.

    The configured token wins. When empty we fall back to the GapGPT key the chat
    has always sent — so the chat's authenticated behaviour is preserved exactly,
    and Secretary (which used to send NO header to the same endpoint) now sends the
    same valid key instead of nothing.
    """
    cfg = cfg or get_stt_settings()
    token = str(cfg.get("auth_token") or "").strip()
    if token:
        return token
    try:  # best-effort; never raise into the audio path
        from modules.EchoMind.viewer_chat.api_manager import Manage
        m = Manage.instance()
        if m.is_validated():
            info = m.ensure_detected()
            return str(getattr(info, "gapgpt_key", "") or "").strip()
    except Exception:
        pass
    return ""


# ── The service ──────────────────────────────────────────────────────────────
class VoiceTranscriptionService:
    """Uploads an ALREADY-SAVED voice file and returns the transcription.

    Recording, the WAV file location and attachment handling are NOT this class's
    business — it only receives paths.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        # Not cached across calls on purpose: a Settings change must take effect
        # immediately. Pass `settings` only from tests / a single logical request.
        self._settings = settings

    def _cfg(self) -> Dict[str, Any]:
        return self._settings or get_stt_settings()

    # -- introspection (used by the Settings "Test Connection" button) --------
    def describe(self) -> Dict[str, Any]:
        cfg = self._cfg()
        return {
            "provider": cfg.get("provider"),
            "label": provider_label(cfg.get("provider", "")),
            "endpoint": resolve_endpoint(cfg),
            "timeout_seconds": cfg.get("timeout_seconds", DEFAULT_TIMEOUT_S),
            "has_auth": bool(resolve_auth_token(cfg)),
        }

    def test_connection(self) -> Dict[str, Any]:
        """Probe the configured server. Never raises."""
        cfg = self._cfg()
        provider = cfg.get("provider", STT_PROVIDER_AIPACS_2)
        if provider == STT_PROVIDER_GOOGLE:
            try:
                import speech_recognition  # noqa: F401
                return {"ok": True, "detail": "Google Speech library is available."}
            except Exception as exc:
                return {"ok": False, "detail": f"Google Speech library missing: {exc}"}
        if provider == STT_PROVIDER_OPENAI:
            from .settings_store import get_openai_settings
            key = str(get_openai_settings().get("api_key") or "").strip()
            return (
                {"ok": True, "detail": "OpenAI API key is configured."}
                if key
                else {"ok": False, "detail": "No OpenAI API key configured."}
            )

        endpoint = resolve_endpoint(cfg)
        if not endpoint:
            return {"ok": False, "detail": "No server URL configured."}
        base = endpoint.rsplit("/", 1)[0]
        token = resolve_auth_token(cfg)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        last: Any = "no response"
        for probe in (f"{base}/health", f"{base}/status", base):
            try:
                r = requests.get(probe, headers=headers, timeout=8)
                if r.status_code < 500:
                    return {
                        "ok": True,
                        "detail": f"Reachable (HTTP {r.status_code}).",
                        "endpoint": endpoint,
                    }
                last = f"HTTP {r.status_code}"
            except Exception as exc:
                last = exc
        return {"ok": False, "detail": f"Not reachable: {last}", "endpoint": endpoint}

    # -- the one upload path -------------------------------------------------
    def transcribe(
        self,
        paths: List[str],
        *,
        quality_mode: str = "clear",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        cfg = self._cfg()
        provider = cfg.get("provider", STT_PROVIDER_AIPACS_2)

        if provider == STT_PROVIDER_GOOGLE:
            return self._delegate("v2t", paths, quality_mode, timeout, cfg)
        if provider == STT_PROVIDER_OPENAI:
            return self._delegate("openai", paths, quality_mode, timeout, cfg)
        return self._post_audio(paths, quality_mode, timeout, cfg)

    # -- non-HTTP providers reuse the existing implementations ---------------
    def _delegate(self, kind, paths, quality_mode, timeout, cfg) -> Dict[str, Any]:
        # Lazy import: keeps this module free of the provider import chain (and
        # avoids a cycle, since NativeIrannobatProvider imports THIS module).
        try:
            if kind == "openai":
                from .secretary.stt.providers.openai_transcribe import OpenAITranscribeProvider
                provider_obj = OpenAITranscribeProvider()
            else:
                from .secretary.stt.providers.v2t_google import V2tGoogleProvider
                provider_obj = V2tGoogleProvider()
            out = provider_obj.transcribe_files(
                paths,
                quality_mode=quality_mode,
                timeout=int(timeout or cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_S),
            )
        except Exception as exc:
            return self._error(cfg, f"{kind} transcription failed: {exc}")
        out.setdefault("quality_report", [])   # chat reads this unconditionally
        out.setdefault("route_used", kind)
        out["endpoint"] = ""
        out["stt_provider"] = cfg.get("provider")
        return out

    def _post_audio(self, paths, quality_mode, timeout, cfg) -> Dict[str, Any]:
        endpoint = resolve_endpoint(cfg)
        if not endpoint:
            return self._error(
                cfg,
                "No transcription server configured. Set one in "
                "Settings ▸ EchoMind ▸ Voice to Text.",
            )

        files = []
        statuses: List[Dict[str, Any]] = []
        try:
            for p in paths or []:
                if not p or not os.path.exists(p):
                    statuses.append({"path": p, "ok": False, "error": "missing_file"})
                    continue
                files.append(("audio_files", open(p, "rb")))
                statuses.append({"path": p, "ok": True})
            if not files:
                return self._error(cfg, "No valid audio files to upload.", statuses)

            token = resolve_auth_token(cfg)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            request_timeout = int(timeout or cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_S)

            log.info(
                "[STT] upload provider=%s files=%d quality=%s",
                cfg.get("provider"), len(files), quality_mode,
            )
            r = requests.post(
                endpoint,
                files=files,
                data={"quality_mode": quality_mode},
                headers=headers,
                timeout=request_timeout,
            )
            r.raise_for_status()
            body = r.json()
        except Exception as exc:
            return self._error(cfg, str(exc), statuses)
        finally:
            for _, fh in files:
                try:
                    fh.close()
                except Exception:
                    pass

        # Merge the RAW body first so every server field the callers already read
        # (transcript, quality_report, session_id, usage, …) survives untouched.
        out: Dict[str, Any] = dict(body) if isinstance(body, dict) else {}
        transcript = str(out.get("transcript") or "").strip()
        out.update(
            {
                "ok": True,
                "provider": "native",          # SttRouter's provider name
                "stt_provider": cfg.get("provider"),
                "route_used": "native",
                "transcript": transcript,
                "quality_report": out.get("quality_report") or [],
                "raw": body,
                "files": statuses,
                "endpoint": endpoint,
            }
        )
        return out

    @staticmethod
    def _error(cfg, message: str, statuses=None) -> Dict[str, Any]:
        return {
            "ok": False,
            "provider": "native",
            "stt_provider": cfg.get("provider"),
            "route_used": "native",
            "error": message,
            "transcript": "",
            "quality_report": [],
            "files": statuses or [],
            "endpoint": resolve_endpoint(cfg),
        }


def transcribe_voice_files(
    paths: List[str],
    *,
    quality_mode: str = "clear",
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Module-level convenience wrapper — the entry point both modules call."""
    return VoiceTranscriptionService().transcribe(
        paths, quality_mode=quality_mode, timeout=timeout
    )
