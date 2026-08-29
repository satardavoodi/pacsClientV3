from __future__ import annotations

import base64
import os
from typing import Any, Optional

from modules.EchoMind.llm_client import chat_completion
from modules.EchoMind.settings_store import get_openai_model_for_feature, get_openai_settings, get_prompt_settings

# ── 2026-08-01: BACKEND PROMPT PARITY ────────────────────────────────────────
# This module is the AI feature set for `llm_backend == "openai"`. Before this
# date it was a DIFFERENT PRODUCT from the company path:
#
#   * `reporter()` sent a ~1,100-character generic prompt whose entire modality
#     handling was `prompt += f"\nModality: {modality}."` — no BI-RADS rules, no
#     Persian/Finglish term maps, no per-region normal templates, no
#     projection/never-presume rules, no temperature clamp, no output
#     validation. Flipping ONE setting silently changed CLINICAL CONTENT.
#   * `correction()` hard-coded *"Return ONLY valid JSON with keys Report Title,
#     Pathological Findings, Normal Findings, Impression, Recommendations"* —
#     the fixed 5-key schema that DELETES a mammogram's BI-RADS category, breast
#     composition and axillary evaluation (and invents an empty Impression) the
#     moment a physician corrects a typo. Removing that from the company path
#     was the whole point of the KEY-SET MIRROR rule; this copy still had it.
#
# Both now call the ONE authority in `openai_reporter`. Do not re-fork them: a
# prompt improvement must reach every backend, and a radiologist reviewing the
# wording must only have to review it once.
#
# `openai_reporter` does NOT import this module, so there is no cycle.
from modules.EchoMind.viewer_chat.openai_reporter import (  # noqa: E402
    _report_validation_enabled,
    _validate_report_json,
    build_correction_system_prompt,
    build_correction_user_content,
    build_report_system_prompt,
    report_sampling_params,
)

_ENV_PROMPT_PARITY = "AIPACS_ECHOMIND_BACKEND_PROMPT_PARITY"


def _prompt_parity_enabled() -> bool:
    """Kill switch for the shared report prompt (default ON).

    `=0` restores the legacy generic prompt below — byte-identical to what this
    backend sent before 2026-08-01, including its lack of a temperature clamp
    and of output validation. It exists so a live regression (token budget,
    fence/sentinel handling on an unusual provider) can be reverted in the
    field without a rebuild. It does NOT gate the correction fix: the fixed
    5-key schema deletes clinical content, and there is no valid use for it.
    """
    raw = os.environ.get(_ENV_PROMPT_PARITY)
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _feature_prompt(name: str) -> str:
    try:
        return str(get_prompt_settings().get(name) or "").strip()
    except Exception:
        return ""


def _compose_prompt(base_prompt: str, feature_name: str = "") -> str:
    """Attach the user's custom prompt AFTER the EchoMind header/workflow, fenced.

    2026-08-02 (owner decision Q3): composition order is
        SHARED HEADER + WORKFLOW  →  fenced USER layer
    The user layer is ADDITIVE — it may shape wording but the EchoMind output
    contract above always wins. It used to be PREPENDED (before the header),
    which gave user text priority over the parsing contract. An empty user
    prompt returns the base prompt byte-identical (backend parity preserved).
    """
    extra = _feature_prompt(feature_name) if feature_name else ""
    if not extra:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        "===== USER CUSTOM INSTRUCTIONS (additive) =====\n"
        "The physician-user added the custom instructions below. Apply them ONLY where\n"
        "they do not conflict with the EchoMind rules and output contract above — on\n"
        "any conflict, the rules above win.\n"
        f"{extra}\n"
        "===== END USER CUSTOM INSTRUCTIONS ====="
    )


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
    """Report generation on the OpenAI backend — SAME prompt as the company path.

    The system prompt, the temperature clamp for structure-validated modalities
    and the post-response JSON validation all come from `openai_reporter`, so a
    radiologist gets the same report whichever backend Settings is on.

    ONE deliberate difference: `max_tokens` stays at the user's configured
    `max_output_tokens` rather than the company path's hard-coded 2500. On this
    backend the budget also has to cover REASONING tokens (gpt-5* with
    `reasoning_effort`), so imposing 2500 here could truncate a report the
    company path renders fine — a downgrade, not parity. The clamp that matters
    clinically is the temperature.
    """
    modality = str(modality or "")
    normal_template = str(normal_template or "")

    if _prompt_parity_enabled():
        system_prompt = build_report_system_prompt(modality, normal_template)
        temperature = report_sampling_params(modality).get("temperature")
        result = _call(
            feature_name="report",
            system_prompt=_compose_prompt(system_prompt, "report_generation"),
            user_content=user_msg,
            user_msg=user_msg,
            model=model,
            api_key_override=(CENTER_Key or None),
            temperature=temperature,
        )
        content = result.get("content", "")
        if modality and _report_validation_enabled():
            # Same contract as the company path: an incomplete report FAILS
            # LOUDLY instead of rendering partially. `_validate_report_json`
            # no-ops for anything outside `_VALIDATED_MODALITIES`.
            content = _validate_report_json(content, modality.lower())
        return {"content": content, "usage": result.get("usage", {})}

    return _legacy_reporter(
        user_msg=user_msg,
        modality=modality,
        normal_template=normal_template,
        CENTER_Key=CENTER_Key,
        model=model,
    )


def _legacy_reporter(
    user_msg: str,
    modality: Optional[str] = "",
    normal_template: Optional[str] = "",
    CENTER_Key: Optional[str] = None,
    model: str | None = None,
) -> dict[str, Any]:
    """PRE-2026-08-01 generic prompt. Reachable only via the kill switch.

    Kept byte-identical on purpose — a kill switch that "restores" something
    slightly different is not a kill switch. Do not extend it; extend the
    shared authority in `openai_reporter` instead.
    """
    prompt = (
        "You are EchoMind report generation. Produce a structured radiology report in English. "
        "Return only valid JSON with keys Report Title, Pathological Findings, Normal Findings. "
        "PHYSICIAN-PROVIDED CONTENT PRESERVATION (highest priority): Do NOT independently generate, "
        "invent, or infer any new impression, conclusion, suggestion, follow-up advice, "
        "clinical/laboratory/pathologic correlation, biopsy, further-imaging, or management "
        "recommendation the physician did not provide. However, ANY impression, recommendation, "
        "suggestion, or correlation the physician EXPLICITLY dictated in the input MUST be preserved "
        "(meaning intact) in the report and MUST NOT be deleted, omitted, weakened, or softened — "
        "e.g. 'findings are suggestive of ...', 'clinical correlation is recommended', 'biopsy is "
        "recommended', 'further evaluation is recommended'. "
        "Include the Impression and Recommendations keys whenever the physician provided such content; "
        "omit them only when the physician provided none. "
        "SEX-SPECIFIC ANATOMY: Do NOT infer or assume the patient's sex. Include a sex-specific organ "
        "(prostate, uterus, ovaries, seminal vesicles, cervix, testes) ONLY IF the physician explicitly "
        "mentioned that organ; if no information was given about it, OMIT it entirely and do NOT emit a "
        "normal/'unremarkable' statement for it. NEVER include both male and female organs in the same report."
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
        data_url = f"data:image/jpeg;base64,{encoded}"
        user_content.append({"type": "image_url", "image_url": {"url": data_url}})
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


def EagleEyeImageAnalysis(
    system_prompt: str,
    header: str = "",
    items: Optional[list] = None,
    CENTER_Key: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """One request carrying a whole Eagle Eye capture session.

    The OpenAI-direct twin of `openai_reporter.EagleEyeImageAnalysis`. Both
    build their content with the SHARED helper so the two backends cannot drift
    in image ordering, MIME type or detail level - the same rule the report
    prompts already follow.
    """
    from modules.EchoMind.viewer_chat.openai_reporter import (
        build_eagle_eye_user_content, EAGLE_EYE_MAX_TOKENS,
    )
    user_content = build_eagle_eye_user_content(header, items or [])
    return _call(
        feature_name="eagle_eye",
        system_prompt=system_prompt,
        user_content=user_content,
        user_msg=header,
        model=model,
        api_key_override=(CENTER_Key or None),
        temperature=(0.2 if temperature is None else temperature),
        max_tokens=int(max_tokens or EAGLE_EYE_MAX_TOKENS),
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
    target_section: str = "",
    system_prompt_prefix: str = "",
) -> dict[str, Any]:
    # ── 2026-08-01: the SHARED correction authority ──────────────────────────
    # The prompt this used to build hard-coded "EXACTLY these 5 keys", so on
    # this backend a physician correcting a typo on a mammogram got the report
    # back WITHOUT its BI-RADS category, breast composition and axillary
    # evaluation — with an empty Impression and Recommendations invented in
    # their place, because the schema said they had to be there. An obstetric
    # report (eleven keys) lost eight sections.
    #
    # No kill switch, deliberately: the legacy prompt deletes clinical content,
    # so "revert to it" is never the right answer. The response handler in
    # `ai_chat_pages` already cleans a ```json fence AND a <|end|> sentinel
    # unconditionally, so the shared prompt's stricter output format is safe
    # here (it was NOT before that fix — the fence strip was gated on the
    # sentinel, which this backend never asked for).
    system_prompt = build_correction_system_prompt()
    payload = build_correction_user_content(user_report, correction_note, target_section)
    return _call(
        feature_name="correction",
        # A PREFIX, never an override: everything the shared correction prompt
        # says - including the output contract that gets parsed - still follows.
        system_prompt=((str(system_prompt_prefix).strip() + "\n\n" + system_prompt)
                       if str(system_prompt_prefix or "").strip() else system_prompt),
        user_content=payload,
        user_msg=correction_note,
        model=model,
        api_key_override=(CENTER_Key or None),
        temperature=0,
    )
