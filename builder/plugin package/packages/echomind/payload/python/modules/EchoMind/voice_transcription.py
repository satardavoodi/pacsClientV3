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

import requests  # noqa: F401  (kept: callers/tests reference the module symbol)

from . import echomind_http
from .settings_store import (
    STT_HTTP_PROVIDERS,
    STT_PROVIDER_AIPACS_1,
    STT_PROVIDER_AIPACS_2,
    STT_PROVIDER_AIPACS_3,
    STT_PROVIDER_CUSTOM,
    STT_PROVIDER_GOOGLE,
    STT_PROVIDER_OPENAI,
    get_stt_settings,
)

log = logging.getLogger(__name__)

# ── Built-in Company transcription servers 1/2 ───────────────────────────
# Shown in the UI ONLY as "Company Server 1" / "Company Server 2" — never as raw
# addresses (product requirement).
AIPACS_SERVER_1_BASE = "http://81.16.117.196:8082"   # A100 GPU
AIPACS_SERVER_2_BASE = "http://80.210.31.214:8085"   # Windows server

# ── Company Server 3 — an OpenAI-COMPATIBLE Whisper endpoint (GapGPT) ─────────
# Unlike Servers 1/2 (multipart ``audio_files`` + ``quality_mode`` at
# ``/generate_transcript``), Server 3 speaks the OpenAI transcription REST API:
# ``POST {base}/audio/transcriptions`` with ``model`` + ``file`` and a Bearer
# key. Shown in the UI ONLY as "Company Server 3"; the base URL / model are not
# surfaced (same product rule as Servers 1/2). Its Bearer credential is opened
# from the validated EchoMind center envelope and is never stored independently.
AIPACS_SERVER_3_BASE = "https://api.gapgpt.app/v1"
AIPACS_SERVER_3_MODEL = "gapgpt/whisper-1"

#: (provider_id, display label) — the Settings combo renders exactly this.
STT_PROVIDER_CHOICES = (
    (STT_PROVIDER_AIPACS_1, "Company Server 1"),
    (STT_PROVIDER_AIPACS_2, "Company Server 2"),
    (STT_PROVIDER_AIPACS_3, "Company Server 3"),
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

    Custom and native servers may use their configured token. Company Server 3
    always uses the provider credential opened by the validated EchoMind center
    access code, so it cannot bypass the company entitlement boundary.
    """
    cfg = cfg or get_stt_settings()
    provider = str(cfg.get("provider") or "").strip().lower()
    token = str(cfg.get("auth_token") or "").strip()
    if token and provider != STT_PROVIDER_AIPACS_3:
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
        if provider == STT_PROVIDER_AIPACS_3:
            # OpenAI-compatible server: probe the base without exposing its
            # address in the (user-visible) detail string.
            key = resolve_auth_token(cfg)
            if not key:
                return {
                    "ok": False,
                    "detail": "Authenticate EchoMind before testing Company Server 3.",
                }
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            try:
                r = echomind_http.get(f"{AIPACS_SERVER_3_BASE}/models", headers=headers, timeout=8)
                if r.status_code < 500:
                    return {"ok": True, "detail": f"Company Server 3 reachable (HTTP {r.status_code})."}
                return {"ok": False, "detail": f"Company Server 3 error (HTTP {r.status_code})."}
            except Exception as exc:
                return {"ok": False, "detail": f"Company Server 3 not reachable: {exc}"}

        endpoint = resolve_endpoint(cfg)
        if not endpoint:
            return {"ok": False, "detail": "No server URL configured."}
        base = endpoint.rsplit("/", 1)[0]
        token = resolve_auth_token(cfg)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # The three probes run CONCURRENTLY (F4, 2026-07-28). They used to run
        # in sequence at 8 s each, so an unreachable server took 24 s to say so —
        # and this ran inline in the Settings button's Qt slot, freezing the GUI
        # for that whole time. Results are still consulted in the SAME priority
        # order, so the reported outcome is unchanged; only the wall clock is
        # now bounded by the slowest single probe instead of their sum.
        probes = (f"{base}/health", f"{base}/status", base)

        def _probe(url: str) -> Any:
            return echomind_http.get(url, headers=headers, timeout=8)

        results: List[Any] = [None] * len(probes)
        try:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=len(probes)) as pool:
                futures = [pool.submit(_probe, url) for url in probes]
                for i, fut in enumerate(futures):
                    try:
                        results[i] = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        results[i] = exc
        except Exception:
            # Executor unavailable for any reason — fall back to sequential.
            for i, url in enumerate(probes):
                try:
                    results[i] = _probe(url)
                except Exception as exc:  # noqa: BLE001
                    results[i] = exc

        last: Any = "no response"
        for outcome in results:
            if outcome is None:
                continue
            if isinstance(outcome, Exception):
                last = outcome
                continue
            if getattr(outcome, "status_code", 599) < 500:
                return {
                    "ok": True,
                    "detail": f"Reachable (HTTP {outcome.status_code}).",
                    "endpoint": endpoint,
                }
            last = f"HTTP {outcome.status_code}"
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
        if provider == STT_PROVIDER_AIPACS_3:
            return self._post_openai_compatible(paths, timeout, cfg)
        return self._post_audio(paths, quality_mode, timeout, cfg)

    # -- non-HTTP providers reuse the existing implementations ---------------
    def _delegate(self, kind, paths, quality_mode, timeout, cfg) -> Dict[str, Any]:
        # 2026-08-09: this route logs, like the HTTP ones already do. It used to be
        # completely silent. `_post_audio` emits "[STT] upload provider=..." and
        # echomind_http logs the response, so a Server 1/2/3 transcription leaves two
        # lines in app.log -- Google and OpenAI left none. After switching the provider
        # to Google we could not tell from the log whether a run had happened at all,
        # let alone whether it succeeded. A route that cannot be observed cannot be
        # verified, so it gets the same two lines.
        log.info(
            "[STT] upload provider=%s route=%s files=%d quality=%s",
            cfg.get("provider"), kind, len(paths or []), quality_mode,
        )
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
            log.warning("[STT] route=%s raised: %s", kind, exc)
            return self._error(cfg, f"{kind} transcription failed: {exc}")
        out.setdefault("quality_report", [])   # chat reads this unconditionally
        out.setdefault("route_used", kind)
        out["endpoint"] = ""
        out["stt_provider"] = cfg.get("provider")
        # Length, not content: the transcript is patient dictation and must never
        # reach app.log. `chars=0 ok=False` is enough to tell "no speech recognised"
        # apart from "the provider refused" apart from "it never ran".
        log.info(
            "[STT] result route=%s ok=%s chars=%d error=%s",
            kind, bool(out.get("ok")),
            len(str(out.get("transcript") or "")),
            out.get("error") or "-",
        )
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
            # Routed through the ONE transport authority (F3): before this, a
            # voice upload passed no `proxies=`, so the Settings connection type
            # (direct / SOCKS5) was silently ignored for every transcription
            # while it WAS honoured for the GapGPT/OpenAI chat calls.
            r = echomind_http.post(
                endpoint,
                files=files,
                data={"quality_mode": quality_mode},
                headers=headers,
                # `request_timeout` is the user's configured stt_timeout_seconds,
                # whose default is already UPLOAD_READ_TIMEOUT_S. Passing
                # `read_timeout` as well was dead weight: an explicit timeout
                # wins over it by design, so it could never take effect.
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

    # -- AI-PACS Server 3: OpenAI-compatible Whisper (GapGPT) -----------------
    def _post_openai_compatible(self, paths, timeout, cfg) -> Dict[str, Any]:
        """Transcribe via the OpenAI ``/audio/transcriptions`` REST API.

        One file per request (the OpenAI endpoint takes a single ``file``), so
        multiple recordings are transcribed in turn and joined — mirroring the
        existing OpenAI provider. Returns the SAME response contract as the AI-PACS
        native path so both callers (chat + Secretary) work unchanged: there is no
        ``quality_mode`` / ``accepted`` here, so ``quality_report`` is always ``[]``
        (a Whisper endpoint has no low-quality "noisy" retry signal).
        """
        key = resolve_auth_token(cfg)
        if not key:
            return self._error(
                cfg,
                "Authenticate EchoMind before using Company Server 3.",
            )
        endpoint = build_endpoint(AIPACS_SERVER_3_BASE, "/audio/transcriptions")
        request_timeout = int(timeout or cfg.get("timeout_seconds") or DEFAULT_TIMEOUT_S)
        headers = {"Authorization": f"Bearer {key}"} if key else {}

        statuses: List[Dict[str, Any]] = []
        chunks: List[str] = []
        for p in paths or []:
            if not p or not os.path.exists(p):
                statuses.append({"path": p, "ok": False, "error": "missing_file"})
                continue
            try:
                with open(p, "rb") as fh:
                    r = echomind_http.post(
                        endpoint,
                        headers=headers,
                        files={"file": (os.path.basename(p), fh, "audio/wav")},
                        data={"model": AIPACS_SERVER_3_MODEL},
                        # see the note on the sibling upload above.
                        timeout=request_timeout,
                    )
                r.raise_for_status()
                body = r.json()
                text = str((body or {}).get("text") or "").strip()
                statuses.append({"path": p, "ok": True, "text": text})
                if text:
                    chunks.append(text)
            except Exception as exc:  # noqa: BLE001 — never raise into the audio path
                statuses.append({"path": p, "ok": False, "error": str(exc)})

        if not any(s.get("ok") for s in statuses):
            first_err = next((s.get("error") for s in statuses if s.get("error")), "upload failed")
            return self._error(cfg, f"Company Server 3 transcription failed: {first_err}", statuses)

        transcript = "\n".join(c for c in chunks if c).strip()
        return {
            "ok": True,
            "provider": "native",          # SttRouter's provider name
            "stt_provider": cfg.get("provider"),
            "route_used": "native",
            "transcript": transcript,
            "quality_report": [],
            "files": statuses,
            "endpoint": "",                # never surface Server 3's address
        }

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


def quality_mode_supported(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Does the ACTIVE provider act on ``quality_mode``?

    Servers 1 and 2 send it with the upload (``data={"quality_mode": ...}``) and
    the server changes its acceptance thresholds, so a "noisy" resend is a
    genuinely different request. Server 3 and the OpenAI Whisper provider take a
    file and a model name and nothing else — resending "in noisy mode" there is
    the SAME request twice, which buys a duplicate failure and a wasted second.

    Defaults to True on any error: an unknown provider keeps the old behaviour
    rather than silently losing a retry that might have worked.
    """
    try:
        provider = str((cfg if cfg is not None
                        else VoiceTranscriptionService()._cfg()).get("provider") or "")
    except Exception:                             # pragma: no cover - defensive
        return True
    # v2t joins them 2026-08-09: V2tGoogleProvider.transcribe_files opens with
    # del quality_mode, timeout - it accepts the argument and ignores it, so a
    # "noisy" resend on this route is the same request twice, exactly as on Server 3.
    return provider not in (STT_PROVIDER_AIPACS_3, STT_PROVIDER_OPENAI,
                            STT_PROVIDER_GOOGLE)


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
