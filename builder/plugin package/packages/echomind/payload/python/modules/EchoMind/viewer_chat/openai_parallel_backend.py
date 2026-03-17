from __future__ import annotations

import base64
from typing import Any, Optional

from modules.EchoMind.llm_client import chat_completion
from modules.EchoMind.settings_store import get_openai_model_for_feature, get_openai_settings, get_prompt_settings


def _feature_prompt(name: str) -> str:
    try:
        return str(get_prompt_settings().get(name) or "").strip()
    except Exception:
        return ""


def _compose_prompt(base_prompt: str, feature_name: str = "") -> str:
    extra = _feature_prompt(feature_name) if feature_name else ""
    if not extra:
        return base_prompt
    return f"{extra}\n\n{base_prompt}"


def _resolve_feature_model(feature_name: str, model: str | None = None) -> str:
    override = str(model or "").strip()
    if override:
        return override
    return get_openai_model_for_feature(feature_name, "gpt-5-mini")


def _call(
    *,
    feature_name: str,
    system_prompt: str,
    user_content: Any,
    user_msg: str,
    model: str | None,
    api_key_override: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    cfg = get_openai_settings()
    resolved_model = _resolve_feature_model(feature_name, model)
    result = chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        model=resolved_model,
        temperature=float(cfg.get("temperature", 0.2) if temperature is None else temperature),
        max_tokens=int(max_tokens or cfg.get("max_output_tokens") or 4096),
        timeout=int(cfg.get("timeout_seconds") or 60),
        api_key_override=api_key_override,
        reasoning_effort=str(cfg.get("reasoning_effort") or "").strip() or None,
    )
    return {
        "content": result.get("content", ""),
        "usage": result.get("usage", {}),
    }


def chat(
    user_msg: str,
    CENTER_Key: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    return _call(
        feature_name="text",
        system_prompt="You are EchoMind medical chat. Respond concisely and clinically.",
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
    )


def reporter(
    user_msg: str,
    modality: Optional[str] = "",
    normal_template: Optional[str] = "",
    CENTER_Key: Optional[str] = None,
    model: str | None = None,
) -> dict[str, Any]:
    prompt = (
        "You are EchoMind report generation. Produce a structured radiology report in English. "
        "Return only valid JSON with keys Report Title, Pathological Findings, Normal Findings. "
        "Include Impression and Recommendations only if they are explicitly supported by the input."
    )
    if modality:
        prompt += f"\nModality: {modality}."
    if normal_template:
        prompt += (
            "\nA normal template is provided below. Use it as the basis for Normal Findings and only adjust "
            "the sections directly affected by dictated pathology.\n\n"
            f"Normal template:\n{normal_template}"
        )
    return _call(
        feature_name="report",
        system_prompt=_compose_prompt(prompt, "report_generation"),
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
    )


def ImageQualityAnalyzer(
    user_msg: str = "",
    CENTER_Key: str = "",
    model: str | None = None,
    image_path: Optional[str] = None,
) -> dict[str, Any]:
    user_content: list[dict[str, Any]] = []
    if user_msg:
        user_content.append({"type": "text", "text": user_msg})
    if image_path:
        with open(image_path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("utf-8")
        user_content.append({"type": "image", "image": encoded})
    prompt = (
        "You are EchoMind Image Quality Analyzer. Inspect the radiology image, identify artifacts, "
        "estimate likely causes, state certainty, and propose practical corrective actions."
    )
    return _call(
        feature_name="vision",
        system_prompt=_compose_prompt(prompt, "image_artifact"),
        user_content=user_content or user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
        temperature=0.2,
        max_tokens=2000,
    )


def BreastExpertAssistant(
    user_msg: str = "",
    CENTER_Key: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    prompt = (
        "You are EchoMind Breast Expert Assistant. Prioritize fellowship-level breast radiology reasoning, "
        "then add concise technical imaging advice and downstream management guidance."
    )
    return _call(
        feature_name="report",
        system_prompt=_compose_prompt(prompt, "breast_assistant"),
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
        temperature=0.2,
        max_tokens=2000,
    )


def translate_text_to_persian(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _call(
        feature_name="text",
        system_prompt=(
            "Translate the user's medical text from English to Persian. "
            "Preserve structure and return plain text only."
        ),
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
        temperature=0.2,
        max_tokens=2000,
    )


def translate_report(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _call(
        feature_name="report",
        system_prompt=(
            "Translate the radiology report from English to Persian and return only valid JSON with the same keys "
            "and the same structure as the input report."
        ),
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
    )


def standard_assist_search(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _call(
        feature_name="text",
        system_prompt=(
            "Standardize the physician's assistant or search request. "
            "Return concise structured JSON with cleaned English and Persian outputs when possible."
        ),
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
    )


def standardize(
    user_msg: str,
    CENTER_Key: Optional[str] = None,
    model: str | None = None,
) -> dict[str, Any]:
    return _call(
        feature_name="text",
        system_prompt=(
            "Standardize the dictated medical content. Return JSON with cleaned Persian and English sentences, "
            "plus impression and recommendation arrays only when explicitly present."
        ),
        user_content=user_msg,
        user_msg=user_msg,
        model=model,
        api_key_override=(CENTER_Key or None),
    )


def correction(
    user_report: str,
    correction_note: str,
    CENTER_Key: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    payload = (
        "ORIGINAL_REPORT:\n"
        f"{user_report}\n\n"
        "CORRECTION_NOTE:\n"
        f"{correction_note}\n"
    )
    return _call(
        feature_name="report",
        system_prompt=(
            "You are a medical report editor. Apply only the requested corrections and return only valid JSON with "
            "keys Report Title, Pathological Findings, Normal Findings, Impression, Recommendations."
        ),
        user_content=payload,
        user_msg=correction_note,
        model=model,
        api_key_override=(CENTER_Key or None),
    )
