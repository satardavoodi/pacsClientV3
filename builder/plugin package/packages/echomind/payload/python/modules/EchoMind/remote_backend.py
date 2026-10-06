"""Registered-center text transport to the authenticated Eagle Eye server.

The Eagle Eye deployment settings own endpoint, TLS trust and client pairing.
Never forward provider keys or locally composed system prompts. STT retains its
existing shared VoiceTranscriptionService; no legacy PACS/provider fallback exists.
"""
from __future__ import annotations

import json
import requests
import sqlite3
from contextvars import ContextVar
from uuid import uuid4

_case_context = ContextVar('echomind_case_context', default=None)


def _history_directory():
    from PacsClient.utils.data_paths import ECHOMIND_DIR
    return ECHOMIND_DIR / 'remote_history'


def bind_history(work, study_uid, session_id):
    """Capture GUI case identity before scheduling; all I/O stays in the worker."""
    context = {key: value for key, value in
               (('study_uid', study_uid), ('session_id', session_id)) if value}
    def run():
        token = _case_context.set(context)
        try:
            return work()
        finally:
            _case_context.reset(token)
    return run

CENTER_CODE = 'RAZI_SERVER'
MAX_RESPONSE = 8 * 1024 * 1024


class RemoteError(RuntimeError):
    pass


def selected():
    from .api_manager import APIKeyManager
    from .settings_store import get_echomind_api_key
    from .credential_envelope import access_code_lookup
    from .api_manager import _KEY_TO_CENTER_CODE
    manager = APIKeyManager.instance()
    if manager.is_validated():
        return manager.get_current_center() == CENTER_CODE
    key = get_echomind_api_key()
    return bool(key and _KEY_TO_CENTER_CODE.get(access_code_lookup(key)) == CENTER_CODE)


def _login_credentials(code):
    """Resolve explicitly registered aliases; a prefix alone never grants access."""
    import hmac
    from .credential_envelope import open_provider_key, CredentialEnvelope, access_code_lookup
    from .center_registry import REMOTE_LOGIN_ENVELOPES
    try:
        lookup = access_code_lookup(code)
        envelope = next(item for item in REMOTE_LOGIN_ENVELOPES
                        if hmac.compare_digest(item['lookup_digest'], lookup))
        login = json.loads(open_provider_key(code, CredentialEnvelope(**envelope), 'RAZI_SERVER_LOGIN'))
        if not isinstance(login, dict) or set(login) != {'username', 'password'}:
            raise ValueError()
        if not all(isinstance(v, str) and v for v in login.values()):
            raise ValueError()
        return login
    except Exception:
        raise RemoteError('Re-enter the Razi Server test access code in EchoMind Settings.') from None


def _request(workflow, text, *, provider='company', **fields):
    if not selected():
        raise RemoteError('The Razi Server test center is no longer selected. Submit again.')
    if not isinstance(text, str) or not text.strip() or len(text) > 200000:
        raise RemoteError('Enter nonempty text of at most 200,000 characters.')
    payload = dict(text=text, provider=provider, workflow=workflow, response_format='json', **fields)
    context = _case_context.get()
    history = None
    if context is not None:
        from modules.ai_imaging.eagle_eye_remote.text_history import History
        history = History(_history_directory())
        rid = str(uuid4())
        payload.update(request_id=rid, case_context=context)
        try:
            history.begin(rid, 'local', context, payload)
        except (OSError, ValueError, sqlite3.Error):
            raise RemoteError('EchoMind local history is unavailable. No request was sent.') from None
    from modules.ai_imaging.eagle_eye_remote.client import Client, ServerHTTPError
    try:
        with Client().open('/v1/echomind/process', payload, timeout=360) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise RemoteError('EchoMind Server response is too large.')
        result = json.loads(body)
        if not isinstance(result, dict) or not result.get('content'):
            raise RemoteError('EchoMind Server returned no report content.')
        if history is not None:
            if result.get('request_id') != rid:
                raise RemoteError('EchoMind Server returned a different request identifier. Update the server before retrying.')
            try:
                history.finish(rid, 'local', result)
            except (OSError, sqlite3.Error):
                raise RemoteError('EchoMind returned a response but local history could not be saved. Do not resubmit automatically.') from None
        return result
    except ServerHTTPError as exc:
        messages = {401:'Eagle Eye authentication failed.', 403:'Eagle Eye client pairing was rejected.',
            422:'The server does not support this request or its fields.',
            429:'EchoMind Server is busy. Try again later.',
            502:'EchoMind Server could not complete the provider request.',
            503:'EchoMind is not configured on this Eagle Eye server.'}
        raise RemoteError(messages.get(exc.status, 'EchoMind Server request failed.')) from None
    except RemoteError:
        raise
    except (RuntimeError, OSError, ValueError, TypeError):
        raise RemoteError('Check the Eagle Eye connection and TLS pairing settings. No automatic retry was sent.') from None


def reporter(user_msg, modality='', normal_template=None, CENTER_Key=None, model=None,
             system_prompt_override=None, *, workflow='report', study_profile=None):
    if system_prompt_override:
        raise RemoteError('Custom local prompts are not supported by the server route.')
    if workflow not in ('report', 'turbo'):
        raise RemoteError('Unsupported reporting workflow.')
    fields = {'modality': modality or '', 'normal_template': normal_template or ''}
    if study_profile is not None:
        fields['study_profile'] = _profile(study_profile)
    result = _request(workflow, user_msg, **fields)
    from .normal_templates import remember_report_template
    content = result['content']
    remember_report_template(content if isinstance(content, str) else json.dumps(content), normal_template or '')
    return result


def _template_for(report):
    from .normal_templates import report_template_reference, PERSIAN_REFERENCE_MARKER
    reference = report_template_reference(report)
    return reference['en'] + PERSIAN_REFERENCE_MARKER + reference['fa'] if reference else ''


def _profile(profile):
    """Adapt desktop string subtype to the server's list schema; reject extra fields."""
    allowed = {'regions', 'contrast', 'procedure', 'subtype', 'patient', 'service', 'protocol', 'notes', 'modality'}
    if not isinstance(profile, dict) or set(profile) - allowed:
        raise RemoteError('Invalid reporting context.')
    result = dict(profile)
    result.pop('modality', None)  # Modality is a request field, not a study-profile field.
    for key in ('regions', 'subtype', 'notes'):
        if key in result and isinstance(result[key], str):
            result[key] = [result[key]] if result[key].strip() else []
    return result


def correction(user_report, correction_note, CENTER_Key=None, model=None,
               target_section='', system_prompt_prefix='', *, turbo=False, study_profile=None):
    if system_prompt_prefix:
        raise RemoteError('Local correction prompts must not be sent to EchoMind Server.')
    fields = dict(correction_note=correction_note, target_section=target_section,
                  normal_template=_template_for(user_report))
    if turbo:
        fields['turbo_correction'] = True
        fields['study_profile'] = _profile(study_profile) if study_profile is not None else None
        fields['modality'] = study_profile.get('modality', '') if isinstance(study_profile, dict) else ''
    result = _request('correction', user_report, **fields)
    from .normal_templates import inherit_report_template
    return inherit_report_template(user_report, result)


def translate_report(user_msg, CENTER_Key=None, model=None):
    return _request('translate_report', user_msg, normal_template=_template_for(user_msg))


def standardize(user_msg, CENTER_Key=None, model=None):
    return _request('standardize', user_msg)


def translate_text_to_persian(user_msg, CENTER_Key=None, model=None):
    return _request('translate_text', user_msg)


def chat(user_msg, CENTER_Key=None, model=None):
    return _request('chat', user_msg)


def assistant(user_msg):
    """Use the central server's native reference assistant, not the breast model."""
    return _request('assistant', user_msg, provider='aipacs')


def search(user_msg):
    """Send reference searches through the same authenticated central server."""
    return _request('search', user_msg, provider='aipacs')


def web_search(user_msg):
    """The server owns the Radiology Expert prompt, search tool and model."""
    return _request('web_search', user_msg)


def render_web_search(content):
    import html
    from urllib.parse import urlsplit
    if not isinstance(content, dict) or not isinstance(content.get('Answer'), str):
        raise RemoteError('Invalid Web Search response.')
    links = []
    for source in content.get('Sources', []):
        if not isinstance(source, dict):
            continue
        url = source.get('url', '')
        try:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                continue
        except (ValueError, TypeError):
            continue
        links.append('<li><a href="' + html.escape(url, quote=True) + '">' + html.escape(str(source.get('title') or url)) + '</a></li>')
    if not links:
        raise RemoteError('Web Search returned no source links.')
    return '<h3>Radiology Expert - Web Search</h3><p>' + html.escape(content['Answer']).replace('\n', '<br>') + '</p><h4>Sources</h4><ol>' + ''.join(links) + '</ol>'


def BreastExpertAssistant(user_msg, CENTER_Key=None, model=None):
    return _request('breast', user_msg)


def standard_assist_search(user_msg, CENTER_Key=None, model=None):
    return _request('standardize_assist', user_msg)


def organize_template_blocks(payload):
    return _request('organize_template', json.dumps(payload, ensure_ascii=False))['content']


def prepare_template_languages(text):
    return _request('template_languages', text)['content']


def ImageQualityAnalyzer(*args, **kwargs):
    raise RemoteError('Image uploads are not supported by the text-only reporting pilot.')
