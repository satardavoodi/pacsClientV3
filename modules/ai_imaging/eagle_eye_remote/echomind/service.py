"""Remote workflows built around the copied EchoMind reporting and STT core."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .reference_report import ReferenceContext
from .attachments import Attachment, content_parts
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
    workflow: Literal["report", "turbo", "chat", "assistant", "search", "web_search", "standardize", "standardize_assist", "translate_report", "translate_text", "correction", "breast", "organize_template", "template_languages", "add_reference"] = "report"
    modality: Literal["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND", "RADIOLOGY", "MAMOGRAPHY", "ECHOCARDIOGRAPHY", ""] = ""
    correction_source: Attachment | None = None
    attachments: list[Attachment] = Field(default_factory=list, max_length=6)
    reference_context: ReferenceContext | None = None
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


class ReportUnavailable(WorkflowError):
    pass


class AttachmentFallbackUnavailable(ReportUnavailable):
    pass


def _overrides(request, openai_key, center_code):
    if request.workflow == 'web_search' and (request.provider != 'company' or request.model or request.translate):
        raise WorkflowError('Web Search requires the company provider and server-selected model; translation is not supported')
    if request.turbo_correction and (request.workflow != 'correction' or request.provider != 'company' or request.model):
        raise WorkflowError('Turbo correction requires company correction and its server-selected model')
    if request.workflow == "turbo" and request.provider != "company":
        raise WorkflowError("Turbo requires the company provider")
    values = {"llm_backend": "openai" if request.provider == "openai" else "company", "brain_workflow": request.workflow, "brain_modality": request.modality}
    if openai_key:
        # User keys are sent only to OpenAI, never to a server-configured alternate host.
        values.update(openai_api_key=openai_key, openai_base_url="https://api.openai.com/v1",
                      openai_org_id="", openai_project_id="")
    if center_code:
        raise WorkflowError('Company credentials are owned by Eagle AI Brain in AI > Connection.')
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
    from ..usage import record_tokens
    record_tokens(body.get("usage") if isinstance(body, dict) else None, "company-service")
    return {"content": content, "usage": body.get("usage", {}) if isinstance(body, dict) else {}}


def _report_content(result):
    if not isinstance(result, dict):
        return False
    value = result.get('content')
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, dict) and bool(value) and not value.get('error') and any(
        isinstance(item, str) and item.strip() for item in value.values())


def _report_with_fallback(request, options):
    if request.model:
        raise WorkflowError('Reporting uses the server-selected model')
    prompt = build_turbo_system_prompt(request.modality, request.normal_template,
        profile=request.study_profile.model_dump() if request.study_profile else None)
    try:
        result = company.reporter(request.text, request.modality, request.normal_template,
                                  **options, system_prompt_override=prompt)
        if _report_content(result):
            return {**result, 'route_used': 'turbo', 'fallback_used': False}
    except Exception:
        # Provider details may contain credentials or clinical text. Do not log.
        pass
    if request.attachments:
        raise AttachmentFallbackUnavailable('Turbo is unavailable; company fallback cannot process report attachments')
    if current_settings().get('brain_server', 'server_1') != 'server_1':
        raise ReportUnavailable('The selected Brain route failed. No company fallback was sent.')
    result = _native(request.model_copy(update={'provider': 'aipacs', 'workflow': 'report'}))
    if not _report_content(result):
        raise ReportUnavailable('Report providers returned no usable content')
    return {**result, 'route_used': 'company_service', 'fallback_used': True}


def _custom_report(request, attachment_parts):
    from .core.ai_chat_config import GAPGPT_API_URL
    fields = ('text',) if request.workflow == 'chat' else (
        'text', 'modality', 'normal_template', 'correction_note', 'target_section')
    data = {key: getattr(request, key) for key in fields}
    if request.study_profile:
        data['study_profile'] = request.study_profile.model_dump()
    content = json.dumps(data, ensure_ascii=True)
    if attachment_parts:
        content = [{'type': 'text', 'text': content}] + attachment_parts
    from ..brain_connection import source
    with source('echomind'):
        response = echomind_http.post(GAPGPT_API_URL, json={
            'messages': [{'role': 'user', 'content': content}]})
    response.raise_for_status()
    body = response.json()
    text = body['choices'][0]['message']['content']
    if not isinstance(text, str) or not text.strip():
        raise WorkflowError('Custom provider returned an empty report.')
    from ..usage import record_tokens
    model_key = 'openai_text_model' if request.workflow == 'chat' else 'openai_report_model'
    record_tokens(body.get('usage'), current_settings().get(model_key, 'unspecified'))
    return {'content': text, 'usage': body.get('usage', {})}


def _process(request):
    if (current_settings().get('brain_server', 'server_1') == 'custom'
            and request.workflow in ('assistant', 'search', 'web_search')):
        raise WorkflowError('Assist and Search are unavailable with Custom Brain.')
    imported_source = request.correction_source is not None
    if imported_source:
        if request.workflow != 'correction' or request.provider != 'company' or not request.correction_note.strip():
            raise WorkflowError('Saved sources require company Correction and a correction note.')
        from .correction_source import normalize
        try:
            request = request.model_copy(update={'text': normalize(request.correction_source)})
        except Exception:
            raise WorkflowError('Cannot read the saved report. Use JSON, HTML, UTF-8 text, DOCX or a readable text PDF; limit 1 MiB.') from None
    attachment_parts = None
    if request.attachments:
        if request.provider != "company" or request.workflow not in ("report", "turbo"):
            raise WorkflowError("Attachments require company Report or Turbo.")
        try:
            attachment_parts = content_parts(request.attachments)
        except Exception:
            raise WorkflowError("Cannot read attachments. Use UTF-8 TXT, DOCX, text PDF (up to 30 pages) or images; total limit 1 MiB.") from None
    if (current_settings().get('brain_server') == 'custom'
            and request.provider in ('company', 'aipacs')
            and request.workflow in ('report', 'turbo', 'correction', 'chat')):
        if request.workflow == 'correction' and not request.correction_note.strip():
            raise WorkflowError('A correction note is required')
        return _custom_report(request, attachment_parts)
    if request.workflow == "add_reference":
        if request.provider != "company" or request.model or request.translate:
            raise WorkflowError("Reference comparison requires the company server workflow")
        from .reference_report import add_reference
        return add_reference(request.text, request.modality, request.reference_context or ReferenceContext())
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
    if request.workflow in ('report', 'turbo') and request.provider in ('company', 'aipacs'):
        options = {'attachment_parts': attachment_parts} if attachment_parts else {}
        return _report_with_fallback(request, options)
    if request.provider == "aipacs" and request.workflow != "chat":
        return _native(request)
    backend = openai if request.provider == "openai" else company
    options = {"model": request.model} if request.model else {}
    if attachment_parts:
        options["attachment_parts"] = attachment_parts
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
        if imported_source:
            from .correction_source import INSTRUCTIONS
            options['system_prompt_prefix'] = INSTRUCTIONS + options.get('system_prompt_prefix', '')
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
        return {**{key: result[key] for key in ("route_used", "fallback_used") if key in result},
                "content": content, "usage": result.get("usage", {}), "transcript": transcript,
                "translation": translated, "provider": request.provider, "workflow": request.workflow}


def transcribe(paths, *, provider=None, openai_key="", center_code="", quality_mode="clear", base=None):
    request = ProcessRequest(text="audio", stt_provider=provider, provider="openai" if provider == "openai" else "company")
    with request_context(_overrides(request, openai_key, center_code), base=base):
        result = VoiceTranscriptionService().transcribe(paths, quality_mode=quality_mode)
        if not result.get("ok") or not result.get("transcript") or any(not f.get("ok") for f in result.get("files", [])):
            raise WorkflowError("Transcription failed or returned no speech")
        return {"transcript": result["transcript"], "provider": result.get("stt_provider"),
                "quality_report": result.get("quality_report", [])}
