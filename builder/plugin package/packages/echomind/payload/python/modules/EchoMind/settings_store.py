from __future__ import annotations

import json
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
        "openai_report_model": "gpt-5.4",
        "openai_vision_model": "gpt-5.4",
        "openai_transcription_model": "gpt-4o-transcribe",
        "openai_secretary_model": "gpt-5-mini",
        "openai_reasoning_effort": "",
        "openai_temperature": 0.2,
        "openai_max_output_tokens": 4096,
        "openai_timeout_seconds": 60,
        "prompt_report_generation": "",
        "prompt_breast_assistant": "",
        "prompt_secretary_routing": "",
        "prompt_secretary_action": "",
        "prompt_transcript_cleanup": "",
        "prompt_image_artifact": "",
        "secretary_stt_provider": "native",  # native | v2t
        "secretary_stt_fallback": True,
    }


def load_settings() -> Dict[str, Any]:
    out = _defaults()
    fp = _config_path()
    try:
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if isinstance(data, dict):
                out.update(data)
    except Exception:
        pass
    return out


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = load_settings()
    cur.update(patch or {})
    fp = _config_path()
    tmp = fp.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    os.replace(tmp, fp)
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
        "report_model": _as_str("openai_report_model", "gpt-5.4") or "gpt-5.4",
        "vision_model": _as_str("openai_vision_model", "gpt-5.4") or "gpt-5.4",
        "transcription_model": _as_str("openai_transcription_model", "gpt-4o-transcribe") or "gpt-4o-transcribe",
        "secretary_model": _as_str("openai_secretary_model", "gpt-5-mini") or "gpt-5-mini",
        "reasoning_effort": _as_str("openai_reasoning_effort"),
        "temperature": _as_float("openai_temperature", 0.2),
        "max_output_tokens": max(1, _as_int("openai_max_output_tokens", 4096)),
        "timeout_seconds": max(5, _as_int("openai_timeout_seconds", 60)),
    }


def get_openai_model_for_feature(feature: str, default: str = "") -> str:
    cfg = get_openai_settings()
    normalized = str(feature or "").strip().lower()
    mapping = {
        "chat": "text_model",
        "text": "text_model",
        "assist": "text_model",
        "search": "text_model",
        "standardize": "text_model",
        "translation": "text_model",
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
        "openai_report_model": str((patch or {}).get("report_model") or "gpt-5.4").strip() or "gpt-5.4",
        "openai_vision_model": str((patch or {}).get("vision_model") or "gpt-5.4").strip() or "gpt-5.4",
        "openai_transcription_model": str((patch or {}).get("transcription_model") or "gpt-4o-transcribe").strip() or "gpt-4o-transcribe",
        "openai_secretary_model": str((patch or {}).get("secretary_model") or "gpt-5-mini").strip() or "gpt-5-mini",
        "openai_reasoning_effort": str((patch or {}).get("reasoning_effort") or "").strip(),
        "openai_temperature": float((patch or {}).get("temperature", 0.2) or 0.2),
        "openai_max_output_tokens": int((patch or {}).get("max_output_tokens", 4096) or 4096),
        "openai_timeout_seconds": int((patch or {}).get("timeout_seconds", 60) or 60),
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


def get_secretary_stt_route() -> str:
    route = str(load_settings().get("secretary_stt_provider") or "native").strip().lower()
    if route == "v2t":
        return "v2t"
    if route == "openai":
        return "openai"
    return "native"


def set_secretary_stt_route(route: str) -> Dict[str, Any]:
    route_value = str(route).strip().lower()
    if route_value == "v2t":
        normalized = "v2t"
    elif route_value == "openai":
        normalized = "openai"
    else:
        normalized = "native"
    return save_settings({"secretary_stt_provider": normalized})
