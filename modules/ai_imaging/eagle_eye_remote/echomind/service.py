"""Remote workflows built around the copied EchoMind reporting and STT core."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .runtime import request_context, current_settings
from .core import ai_chat_config as endpoints, echomind_http
from .core.viewer_chat import openai_reporter as company, openai_parallel_backend as openai
from .core.viewer_chat.turbo_prompt import build_turbo_system_prompt, build_turbo_correction_prefix
from .core.voice_transcription import VoiceTranscriptionService


class StudyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regions: list[str] = Field(default_factory=list, max_length=30)
    contrast: str = Field(default="", max_length=100)
    procedure: str = Field(default="", max_length=200)
    subtype: list[str] = Field(default_factory=list, max_length=20)
    patient: str = Field(default="", max_length=500)
    service: str = Field(default="", max_length=500)
    protocol: str = Field(default="", max_length=500)
    notes: list[str] = Field(default_factory=list, max_length=20)


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=200000)
    provider: Literal["aipacs", "company", "openai"] = "company"
    workflow: Literal["report", "turbo", "chat", "assistant", "search", "web_search", "standardize", "standardize_assist", "translate_report", "translate_text", "correction", "breast", "organize_template", "template_languages"] = "report"
    modality: Literal["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND", "RADIOLOGY", "MAMOGRAPHY", ""] = ""
    normal_template: str = Field(default="", max_length=100000)
    correction_note: str = Field(default="", max_length=20000)
    target_section: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=100)
    response_format: Literal["html", "json"] = "html"
    stt_provider: Literal["aipacs_1", "aipacs_2", "aipacs_3", "openai", "v2t", "custom"] | None = None
    quality_mode: Literal["clear", "noisy"] = "clear"
    translate: bool = False
    turbo_correction: bool = False
    study_profile: StudyProfile | None = None


class WorkflowError(Exception):
    pass


def _overrides(request, openai_key, center_code):
    if request.workflow == 'web_search' and (request.provider != 'company' or request.model or request.translate):
        raise WorkflowError('Web Search requires the company provider and server-selected model; translation is not supported')
    if request.turbo_correction and (request.workflow != 'correction' or request.provider != 'company' or request.model):
        raise WorkflowError('Turbo correction requires company correction and its server-selected model')
    if request.workflow == "turbo" and request.provider != "company":
        raise WorkflowError("Turbo requires the company provider")
    values = {"llm_backend": "openai" if request.provider == "openai" else "company"}
    if openai_key:
        # User keys are sent only to OpenAI, never to a server-configured alternate host.
        values.update(openai_api_key=openai_key, openai_base_url="https://api.openai.com/v1",
                      openai_org_id="", openai_project_id="")
    if center_code:
        values["api_key"] = center_code
    if request.stt_provider:
        values["stt_provider"] = request.stt_provider
    return values


def _native(request):
    routes = {"report": endpoints.URL_GEN_REPORT, "chat": endpoints.URL_CHAT,
              "assistant": endpoints.URL_GEN_ASSISTANT, "search": endpoints.URL_SEARCH}
    if request.workflow not in routes:
        raise WorkflowError("This workflow requires company or OpenAI provider")
    payload = {"chat": {"user_message": request.text}, "search": {"user_query": request.text}}.get(request.workflow, {"text": request.text})
    if request.workflow == "report":
        payload.update(modality=request.modality, normal_template=request.normal_template)
    response = echomind_http.post(routes[request.workflow], json=payload)
    response.raise_for_status()
    body = response.json()
    keys = {"report": ("report", "report_output", "data"), "chat": ("response",),
            "assistant": ("assistant_output", "assistant", "data"), "search": ("search_results", "results", "response", "data")}
    content = next((body[k] for k in keys[request.workflow] if isinstance(body, dict) and body.get(k)), body)
    for _ in range(6):
        if not isinstance(content, dict):
            break
        for key in ("content", "report", "response", "message", "result", "output", "data"):
            if key in content and content[key] is not None:
                content = content[key]
                break
        else:
            break
    return {"content": content, "usage": body.get("usage", {}) if isinstance(body, dict) else {}}


def _process(request):
    if request.workflow in ('organize_template', 'template_languages'):
        if request.provider != 'company':
            raise WorkflowError('Template workflows require the company provider')
        from .core import reception_templates
        if request.workflow == 'organize_template':
            payload = json.loads(request.text)
            if not isinstance(payload, dict) or set(payload) != {'name', 'modality', 'blocks'}:
                raise WorkflowError('Invalid template organization source')
            blocks = payload['blocks']
            if (not isinstance(payload['name'], str) or len(payload['name']) > 500
                    or not isinstance(payload['modality'], str) or len(payload['modality']) > 100
                    or not isinstance(blocks, list) or not 1 <= len(blocks) <= 600
                    or any(not isinstance(b, dict) or set(b) != {'id', 'text'}
                           or b['id'] != f'L{i:04d}' or not isinstance(b['text'], str)
                           or not b['text'].strip() for i, b in enumerate(blocks))
                    or sum(len(b['text']) for b in blocks) > 80000):
                raise WorkflowError('Invalid template organization source')
            content = reception_templates._organizer_completion(payload)
        else:
            content = reception_templates.prepare_template_languages(request.text)
        return {'content': content, 'usage': {}}
    if request.workflow == 'web_search':
        from .web_search import search
        return search(request.text)
    if request.provider == "aipacs":
        return _native(request)
    backend = openai if request.provider == "openai" else company
    options = {"model": request.model} if request.model else {}
    if request.workflow == "turbo":
        if request.model:
            raise WorkflowError("Turbo uses the company-selected model")
        return company.reporter(request.text, request.modality, request.normal_template,
                                system_prompt_override=build_turbo_system_prompt(request.modality, request.normal_template,
                                    profile=request.study_profile.model_dump() if request.study_profile else None))
    if request.workflow == "report":
        return backend.reporter(request.text, request.modality, request.normal_template, **options)
    if request.workflow == "correction":
        if not request.correction_note.strip():
            raise WorkflowError("A correction note is required")
        if request.turbo_correction:
            profile = request.study_profile.model_dump() if request.study_profile else {}
            if request.modality:
                profile['modality'] = request.modality
            options['system_prompt_prefix'] = build_turbo_correction_prefix(
                profile or None) or ''
        return backend.correction(request.text, request.correction_note, target_section=request.target_section, **options)
    function = {"chat": backend.chat, "assistant": backend.BreastExpertAssistant,
                "breast": backend.BreastExpertAssistant, "search": backend.standard_assist_search,
                "standardize": backend.standardize, "standardize_assist": backend.standard_assist_search, "translate_report": backend.translate_report,
                "translate_text": backend.translate_text_to_persian}[request.workflow]
    # AI-PACS owns the native general Assistant/Search workflows. Company/OpenAI search
    # standardizes a query, and breast is the workstation's dedicated breast assistant.
    if request.workflow in ("assistant", "search"):
        raise WorkflowError("Use aipacs for Assistant/Search; use breast for the breast assistant")
    return function(request.text, **options)


def process(request, *, openai_key="", center_code="", audio_paths=None, base=None):
    with request_context(_overrides(request, openai_key, center_code), base=base):
        transcript = None
        if audio_paths:
            from .core.settings_store import get_stt_provider
            stt_backend = "openai" if get_stt_provider() == "openai" else current_settings()["llm_backend"]
            with request_context({"llm_backend": stt_backend}, base=current_settings()):
                stt = VoiceTranscriptionService().transcribe(audio_paths, quality_mode=request.quality_mode)
            if not stt.get("ok") or not str(stt.get("transcript") or "").strip():
                raise WorkflowError("Transcription failed or returned no speech")
            if any(not item.get("ok") for item in stt.get("files", [])):
                raise WorkflowError("At least one audio file could not be transcribed")
            transcript = str(stt["transcript"])
            request = request.model_copy(update={"text": transcript})
        if request.normal_template and request.workflow in ("correction", "translate_report"):
            from .core.normal_templates import remember_report_template
            remember_report_template(request.text, request.normal_template)
        result = _process(request)
        content = result.get("content")
        if not content:
            raise WorkflowError("Provider returned an empty result")
        translated = None
        if request.translate:
            backend = openai if request.provider == "openai" else company
            raw = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            translated = backend.translate_report(raw) if request.workflow in ("report", "turbo", "correction") else backend.translate_text_to_persian(raw)
        return {"content": content, "usage": result.get("usage", {}), "transcript": transcript,
                "translation": translated, "provider": request.provider, "workflow": request.workflow}


def transcribe(paths, *, provider=None, openai_key="", center_code="", quality_mode="clear", base=None):
    request = ProcessRequest(text="audio", stt_provider=provider, provider="openai" if provider == "openai" else "company")
    with request_context(_overrides(request, openai_key, center_code), base=base):
        result = VoiceTranscriptionService().transcribe(paths, quality_mode=quality_mode)
        if not result.get("ok") or not result.get("transcript") or any(not f.get("ok") for f in result.get("files", [])):
            raise WorkflowError("Transcription failed or returned no speech")
        return {"transcript": result["transcript"], "provider": result.get("stt_provider"),
                "quality_report": result.get("quality_report", [])}
