from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

from aipacs_runtime import roaming_config_root


def _config_path() -> Path:
    cfg_dir = roaming_config_root()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "echomind_settings.json"


def _defaults() -> Dict[str, Any]:
    return {
        "api_key": "",
        "llm_backend": "company",  # company | openai
        "openai_api_key": "",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_org_id": "",
        "openai_project_id": "",
        "openai_text_model": "gpt-5-mini",
        "openai_report_model": "gpt-5.6-terra",
        "openai_vision_model": "gpt-5.4",
        "openai_transcription_model": "gpt-4o-transcribe",
        "openai_secretary_model": "gpt-5-mini",
        "openai_reasoning_effort": "",
        "openai_temperature": 0.2,
        "openai_max_output_tokens": 4096,
        # F6 (2026-07-28): was 60. The company/GapGPT path has always used a
        # 180 s READ budget (`echomind_http.DEFAULT_READ_TIMEOUT_S`, formerly
        # `openai_reporter._DEFAULT_READ_TIMEOUT_S`), so the SAME report-
        # generation request had a 180 s ceiling on one backend and 60 s on the
        # other — long reports failed on OpenAI with a bogus "network error"
        # while succeeding on GapGPT. Both backends now default to the same
        # budget. An explicitly saved value still wins; an install that already
        # persisted 60 keeps it and can raise it in Settings ▸ EchoMind.
        "openai_timeout_seconds": 180,
        "prompt_report_generation": "",
        "prompt_breast_assistant": "",
        "prompt_secretary_routing": "",
        "prompt_secretary_action": "",
        "prompt_transcript_cleanup": "",
        "prompt_image_artifact": "",
        "secretary_stt_provider": "native",  # LEGACY route: native | v2t | openai
        # INERT, and it must stay that way (checked 2026-08-10). The only fallback
        # `SttRouter` can reach is Google Web Speech — free, unauthenticated, and
        # off-premises. This key defaults to True, so wiring it to the router's
        # `fallback` argument would ship raw patient dictation to Google on the
        # commonest failure (an empty transcript). The one caller (Secretary) passes
        # a literal False on purpose; do not connect them without a PHI review.
        "secretary_stt_fallback": True,
        # ── Voice-to-Text (SHARED by EchoMind chat + Secretary EchoMind) ──────
        # Single source of truth for where a recorded voice file is sent.
        #   stt_provider : aipacs_1 | aipacs_2 | v2t | openai | custom
        #                  "" (default) = derive from the legacy
        #                  secretary_stt_provider, so an existing install keeps
        #                  its exact current behaviour.
        "stt_provider": "",
        "stt_custom_base_url": "",      # custom only, e.g. http://10.0.0.5
        "stt_custom_port": 0,           # custom only, 0 = port is part of the URL
        "stt_endpoint_path": "/generate_transcript",
        "stt_timeout_seconds": 360,
        "stt_auth_token": "",           # optional; falls back to the GapGPT key
        "connection_type": "direct",  # direct | socks5
        "proxy_port": 2080,
    }


# ── F11 (2026-07-28): stop re-parsing the settings file 6× per LLM request ───
# `load_settings()` opened and JSON-parsed the file on EVERY call, and nothing
# cached it. A single `openai_parallel_backend._call` triggered roughly six
# reads: get_prompt_settings → get_openai_model_for_feature → get_openai_settings
# → get_openai_settings again → then inside chat_completion: get_llm_backend,
# get_openai_settings, get_proxy_settings.
#
# THE CONSTRAINT THIS MUST NOT BREAK: settings are resolved PER CALL on purpose
# (see the module docstring of voice_transcription.py — a Settings change has to
# take effect with no restart, and the import-by-value trap is why). So this is
# NOT a TTL cache: it is keyed on the file's identity (mtime_ns + size), so any
# write — ours or an external editor's — invalidates it on the very next read.
# `save_settings` additionally clears it outright, so our own writes can never
# be served stale even within one filesystem timestamp tick.
_CACHE_LOCK = threading.Lock()
_cache_key: Any = None
_cache_value: Dict[str, Any] | None = None


def _invalidate_settings_cache() -> None:
    """Drop the cached settings (called after every write; safe to call anytime)."""
    global _cache_key, _cache_value
    with _CACHE_LOCK:
        _cache_key = None
        _cache_value = None


def _file_identity(fp: Path):
    try:
        st = fp.stat()
        return (st.st_mtime_ns, st.st_size)
    except Exception:
        return None


def load_settings() -> Dict[str, Any]:
    global _cache_key, _cache_value
    fp = _config_path()
    identity = _file_identity(fp)

    if identity is not None:
        with _CACHE_LOCK:
            if _cache_key == identity and _cache_value is not None:
                # Copy: callers mutate the result (e.g. save_settings does
                # `cur.update(patch)`), and the cache must not be poisoned.
                return dict(_cache_value)

    out = _defaults()
    try:
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if isinstance(data, dict):
                out.update(data)
    except Exception:
        return out  # unreadable/corrupt → defaults, and do NOT cache that

    if identity is not None:
        with _CACHE_LOCK:
            _cache_key = identity
            _cache_value = dict(out)
    return out


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = load_settings()
    cur.update(patch or {})
    fp = _config_path()
    tmp = fp.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    os.replace(tmp, fp)
    # Never serve the pre-write value, even if mtime granularity hides the change.
    _invalidate_settings_cache()
    return cur


def get_echomind_api_key() -> str:
    return str(load_settings().get("api_key") or "").strip()


def set_echomind_api_key(api_key: str) -> Dict[str, Any]:
    return save_settings({"api_key": (api_key or "").strip()})


def get_llm_backend() -> str:
    backend = str(load_settings().get("llm_backend") or "company").strip().lower()
    return "openai" if backend == "openai" else "company"


def set_llm_backend(backend: str) -> Dict[str, Any]:
    normalized = "openai" if str(backend).strip().lower() == "openai" else "company"
    return save_settings({"llm_backend": normalized})


def get_openai_settings() -> Dict[str, Any]:
    settings = load_settings()

    def _as_str(name: str, default: str = "") -> str:
        return str(settings.get(name) or default).strip()

    def _as_int(name: str, default: int) -> int:
        try:
            return int(settings.get(name, default))
        except Exception:
            return default

    def _as_float(name: str, default: float) -> float:
        try:
            return float(settings.get(name, default))
        except Exception:
            return default

    return {
        "api_key": _as_str("openai_api_key"),
        "base_url": _as_str("openai_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1",
        "organization": _as_str("openai_org_id"),
        "project": _as_str("openai_project_id"),
        "text_model": _as_str("openai_text_model", "gpt-5-mini") or "gpt-5-mini",
        "report_model": _as_str("openai_report_model", "gpt-5.6-terra") or "gpt-5.6-terra",
        "vision_model": _as_str("openai_vision_model", "gpt-5.4") or "gpt-5.4",
        "transcription_model": _as_str("openai_transcription_model", "gpt-4o-transcribe") or "gpt-4o-transcribe",
        "secretary_model": _as_str("openai_secretary_model", "gpt-5-mini") or "gpt-5-mini",
        "reasoning_effort": _as_str("openai_reasoning_effort"),
        "temperature": _as_float("openai_temperature", 0.2),
        "max_output_tokens": max(1, _as_int("openai_max_output_tokens", 4096)),
        "timeout_seconds": max(5, _as_int("openai_timeout_seconds", 180)),
    }


def get_openai_model_for_feature(feature: str, default: str = "") -> str:
    cfg = get_openai_settings()
    normalized = str(feature or "").strip().lower()
    mapping = {
        "chat": "text_model",
        "text": "text_model",
        "assist": "text_model",
        "search": "text_model",
        "standardize": "report_model",
        "translation": "report_model",
        "report": "report_model",
        "reporter": "report_model",
        "correction": "report_model",
        "report_translation": "report_model",
        "vision": "vision_model",
        "image": "vision_model",
        "image_artifact": "vision_model",
        "breast": "report_model",
        "secretary": "secretary_model",
        "transcription": "transcription_model",
    }
    key = mapping.get(normalized, "text_model")
    fallback = str(default or cfg.get("text_model") or "gpt-5-mini").strip() or "gpt-5-mini"
    return str(cfg.get(key) or fallback).strip() or fallback


def save_openai_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "openai_api_key": str((patch or {}).get("api_key") or "").strip(),
        "openai_base_url": str((patch or {}).get("base_url") or "https://api.openai.com/v1").strip() or "https://api.openai.com/v1",
        "openai_org_id": str((patch or {}).get("organization") or "").strip(),
        "openai_project_id": str((patch or {}).get("project") or "").strip(),
        "openai_text_model": str((patch or {}).get("text_model") or "gpt-5-mini").strip() or "gpt-5-mini",
        "openai_report_model": str((patch or {}).get("report_model") or "gpt-5.6-terra").strip() or "gpt-5.6-terra",
        "openai_vision_model": str((patch or {}).get("vision_model") or "gpt-5.4").strip() or "gpt-5.4",
        "openai_transcription_model": str((patch or {}).get("transcription_model") or "gpt-4o-transcribe").strip() or "gpt-4o-transcribe",
        "openai_secretary_model": str((patch or {}).get("secretary_model") or "gpt-5-mini").strip() or "gpt-5-mini",
        "openai_reasoning_effort": str((patch or {}).get("reasoning_effort") or "").strip(),
        "openai_temperature": float((patch or {}).get("temperature", 0.2) or 0.2),
        "openai_max_output_tokens": int((patch or {}).get("max_output_tokens", 4096) or 4096),
        "openai_timeout_seconds": int((patch or {}).get("timeout_seconds", 180) or 180),
    }
    return save_settings(normalized)


def get_prompt_settings() -> Dict[str, str]:
    settings = load_settings()
    return {
        "report_generation": str(settings.get("prompt_report_generation") or "").strip(),
        "breast_assistant": str(settings.get("prompt_breast_assistant") or "").strip(),
        "secretary_routing": str(settings.get("prompt_secretary_routing") or "").strip(),
        "secretary_action": str(settings.get("prompt_secretary_action") or "").strip(),
        "transcript_cleanup": str(settings.get("prompt_transcript_cleanup") or "").strip(),
        "image_artifact": str(settings.get("prompt_image_artifact") or "").strip(),
    }


def save_prompt_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "prompt_report_generation": str((patch or {}).get("report_generation") or "").strip(),
        "prompt_breast_assistant": str((patch or {}).get("breast_assistant") or "").strip(),
        "prompt_secretary_routing": str((patch or {}).get("secretary_routing") or "").strip(),
        "prompt_secretary_action": str((patch or {}).get("secretary_action") or "").strip(),
        "prompt_transcript_cleanup": str((patch or {}).get("transcript_cleanup") or "").strip(),
        "prompt_image_artifact": str((patch or {}).get("image_artifact") or "").strip(),
    }
    return save_settings(normalized)


# ── Voice-to-Text: the ONE provider selection, shared by both modules ────────
#
# Settings ▸ EchoMind ▸ Voice to Text is the single source of truth for where a
# recorded voice file is sent. Before this, the EchoMind chat POSTed to a
# hard-coded ``{AI_BASE}/generate_transcript`` and ignored this setting entirely,
# while Secretary read it but only as a 3-way provider route with no endpoint.
STT_PROVIDER_AIPACS_1 = "aipacs_1"   # AI-PACS Server 1 (A100 GPU)
STT_PROVIDER_AIPACS_2 = "aipacs_2"   # AI-PACS Server 2 (Windows)
STT_PROVIDER_AIPACS_3 = "aipacs_3"   # AI-PACS Server 3 (OpenAI-compatible Whisper)
STT_PROVIDER_GOOGLE = "v2t"          # Google Speech (local library, no endpoint)
STT_PROVIDER_OPENAI = "openai"       # OpenAI transcription (own base_url)
STT_PROVIDER_CUSTOM = "custom"       # user-entered server

STT_PROVIDERS = (
    STT_PROVIDER_AIPACS_1,
    STT_PROVIDER_AIPACS_2,
    STT_PROVIDER_AIPACS_3,
    STT_PROVIDER_GOOGLE,
    STT_PROVIDER_OPENAI,
    STT_PROVIDER_CUSTOM,
)

#: Providers whose voice file is uploaded to an AI-PACS/Whisper HTTP endpoint.
STT_HTTP_PROVIDERS = (STT_PROVIDER_AIPACS_1, STT_PROVIDER_AIPACS_2, STT_PROVIDER_CUSTOM)

#: Legacy ``secretary_stt_provider`` -> unified ``stt_provider``.
#: "native" meant the hard-coded ``AI_BASE`` = the WINDOWS server, i.e. Server 2 —
#: so an install that never touches the new setting behaves EXACTLY as before.
_LEGACY_ROUTE_TO_PROVIDER = {
    "native": STT_PROVIDER_AIPACS_2,
    "v2t": STT_PROVIDER_GOOGLE,
    "openai": STT_PROVIDER_OPENAI,
}


def normalize_stt_provider(value: Any) -> str:
    v = str(value or "").strip().lower()
    if v in STT_PROVIDERS:
        return v
    return _LEGACY_ROUTE_TO_PROVIDER.get(v, STT_PROVIDER_AIPACS_2)


def get_stt_provider() -> str:
    """The selected Voice-to-Text provider (unified, 5-way)."""
    settings = load_settings()
    explicit = str(settings.get("stt_provider") or "").strip().lower()
    if explicit:
        return normalize_stt_provider(explicit)
    # Not configured yet -> derive from the legacy route (back-compat).
    return normalize_stt_provider(settings.get("secretary_stt_provider"))


def get_stt_settings() -> Dict[str, Any]:
    """Everything the shared VoiceTranscriptionService needs. Never raises."""
    settings = load_settings()

    def _as_int(name: str, default: int) -> int:
        try:
            return int(settings.get(name, default) or default)
        except Exception:
            return default

    return {
        "provider": get_stt_provider(),
        "custom_base_url": str(settings.get("stt_custom_base_url") or "").strip(),
        "custom_port": max(0, _as_int("stt_custom_port", 0)),
        "endpoint_path": (
            str(settings.get("stt_endpoint_path") or "").strip() or "/generate_transcript"
        ),
        "timeout_seconds": max(5, _as_int("stt_timeout_seconds", 360)),
        "auth_token": str(settings.get("stt_auth_token") or "").strip(),
    }


def save_stt_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    patch = patch or {}
    provider = normalize_stt_provider(patch.get("provider"))
    try:
        port = max(0, int(patch.get("custom_port", 0) or 0))
    except Exception:
        port = 0
    try:
        timeout = max(5, int(patch.get("timeout_seconds", 360) or 360))
    except Exception:
        timeout = 360
    normalized = {
        "stt_provider": provider,
        "stt_custom_base_url": str(patch.get("custom_base_url") or "").strip(),
        "stt_custom_port": port,
        "stt_endpoint_path": (
            str(patch.get("endpoint_path") or "").strip() or "/generate_transcript"
        ),
        "stt_timeout_seconds": timeout,
        "stt_auth_token": str(patch.get("auth_token") or "").strip(),
        # Keep the LEGACY key in lock-step so any code still reading
        # secretary_stt_provider (and SttRouter, which is 3-way) stays correct.
        "secretary_stt_provider": stt_provider_to_legacy_route(provider),
    }
    return save_settings(normalized)


def stt_provider_to_legacy_route(provider: str) -> str:
    """Map the 5-way provider onto the 3-way ``SttRouter`` route.

    Every HTTP provider (both AI-PACS servers and a custom server) is the
    "native" route — the router picks NativeIrannobatProvider, which now resolves
    its endpoint from these settings instead of a hard-coded URL.
    """
    p = normalize_stt_provider(provider)
    if p == STT_PROVIDER_GOOGLE:
        return "v2t"
    if p == STT_PROVIDER_OPENAI:
        return "openai"
    return "native"


def get_secretary_stt_route() -> str:
    """The 3-way route for ``SttRouter`` — derived from the unified provider."""
    return stt_provider_to_legacy_route(get_stt_provider())


def set_secretary_stt_route(route: str) -> Dict[str, Any]:
    route_value = str(route).strip().lower()
    if route_value == "v2t":
        normalized = "v2t"
    elif route_value == "openai":
        normalized = "openai"
    else:
        normalized = "native"
    return save_settings({"secretary_stt_provider": normalized})


def get_proxy_settings() -> Dict[str, Any]:
    settings = load_settings()
    conn_type = str(settings.get("connection_type") or "direct").strip().lower()
    if conn_type not in ("direct", "socks5"):
        conn_type = "direct"
    port = int(settings.get("proxy_port") or 2080)
    if port not in (2080, 2081, 2082):
        port = 2080
    return {
        "connection_type": conn_type,
        "proxy_host": "127.0.0.1",
        "proxy_port": port,
    }


def save_proxy_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    conn_type = str((patch or {}).get("connection_type") or "direct").strip().lower()
    if conn_type not in ("direct", "socks5"):
        conn_type = "direct"
    port = int((patch or {}).get("proxy_port") or 2080)
    if port not in (2080, 2081, 2082):
        port = 2080
    return save_settings({
        "connection_type": conn_type,
        "proxy_port": port,
    })
