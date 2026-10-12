"""Adapt reception prompts to the existing server-owned AI provider gateway."""
import os
from pathlib import Path
from ..echomind import runtime
from ..echomind.core import llm_client


def completion(messages, **options):
    directory = Path(os.environ['CRM_EAGLE_CONFIG'])
    from ..brain_connection import source
    with source('crm'), runtime.configuration(directory), runtime.request_context({'llm_backend': 'company'}):
        settings = runtime.current_settings()
        model = settings.get('crm_model') or 'gpt-5.6-terra'
        reply = llm_client.chat_completion(messages=messages, model=model,
            max_tokens=options.get('max_tokens') or 2400,
            temperature=options.get('temperature') if options.get('temperature') is not None else 0.0,
            timeout=options.get('timeout') or 60)
        return {key: value for key, value in dict(reply, provider='eagle_eye',
                display_name='Eagle Eye Server').items() if key != 'raw'}
