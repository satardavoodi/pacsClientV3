"""Hosted CRM narrative policy; machine results and authority are unchanged."""
from __future__ import annotations

import re
from typing import Any

from ..response_language import current_reply_language, request_language, response_language_instruction


_ERRORS = {
    'VALIDATION': 'Enter a request.',
    'LLM_NOT_CONFIGURED': 'The AI service is not configured.',
    'PERMISSION_DENIED': 'You do not have permission to perform this operation.',
    'INTERPRETATION_FAILED': 'The request could not be understood. Please clarify it.',
    'LLM_ERROR': 'The AI service could not process this request.',
    'TOOL_NOT_FOUND': 'This operation is not supported.',
    'CONFIRMATION_REQUIRED': 'Human approval is required.',
    'CONFIRMATION_INVALID': 'This approval is invalid or has expired.',
    'IDEMPOTENCY_CONFLICT': 'This request was already submitted with different information.',
    'MODE_READ_ONLY': 'This mode permits read-only operations.',
    'MODE_PROPOSE_ONLY': 'This mode can propose an operation but cannot execute it.',
}


def run_command(run, request, context, *, registry=None, chat=None, confirmations=None):
    """Resolve once from original input, before attachment/data/history processing."""
    preference = request.language_preference
    if preference not in ('en', 'fa'):
        raise ValueError('language_preference must be fa or en.')
    from reception_crm.llm import client
    upstream = chat or client.chat_completion
    with request_language(request.text, preference):
        instruction = response_language_instruction()
        def localized_chat(messages, **options):
            # Append to the system policy, preserving provider role ordering.
            # A copy prevents caller history/schema/data mutation.
            policy = instruction + (
                '\nLegacy JSON field names ending in _fa remain unchanged. Their '
                'human-readable narrative values must follow this request language. '
                'Never translate tool names, arguments, identifiers, schema keys or data literals.'
            )
            localized = list(messages)
            for index in range(len(localized) - 1, -1, -1):
                item = localized[index]
                if item.get('role') == 'system' and isinstance(item.get('content'), str):
                    localized[index] = dict(item, content=item['content'] + '\n\n' + policy)
                    break
            else:
                localized.insert(0, {'role': 'system', 'content': policy})
            return upstream(localized, **options)
        result = run(request, context, registry=registry, chat=localized_chat,
                     confirmations=confirmations)
        if current_reply_language() != 'en':
            return result
        # Deterministic failures have no model call to obey the instruction.
        error = result.get('error')
        if error:
            result = dict(result)
            message = _ERRORS.get(error.get('code'), 'The request could not be completed.')
            result['message'] = message
            result['error'] = dict(error, message=message)
            if error.get('code') == 'CONFIRMATION_REQUIRED' and result.get('userAction'):
                action = dict(result['userAction'])
                tools = ', '.join(str(step.get('tool', '')) for step in action.get('steps', []))
                action['summaryFa'] = f'Review and approve the proposed operations: {tools}.'
                action['effects'] = ['Review each operation and its arguments before approval.']
                result['userAction'] = action
        elif (not result.get('success') and result.get('requiresUserAction')
              and not result.get('message')):
            result = dict(result, message='Please clarify your request.')
        return result


def render_english_fallback(data: Any, *, inherited_day=None, snapshot=None) -> str:
    """Bounded numeric evidence, never a guessed translation of record text."""
    lines = ['## Result']
    if inherited_day:
        lines.append(f'Date: {inherited_day}')
    if snapshot:
        lines.append(f'This result uses the saved snapshot from {snapshot}; it is not a fresh read.')
    def visit(value, path='', depth=0):
        if len(lines) >= 45 or depth > 5:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                # Paths, tokens and arbitrary narrative never become display text.
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', str(key)):
                    continue
                if any(word in str(key).lower() for word in ('token', 'secret', 'password', 'path')):
                    continue
                label = re.sub(r'([a-z])([A-Z])', r'\1 \2', str(key)).replace('_', ' ')
                visit(child, f'{path} / {label}' if path else label, depth + 1)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f'- {path}: {value}')
        elif isinstance(value, str) and re.fullmatch(r'\d{4}[/\-]\d{2}[/\-]\d{2}', value):
            lines.append(f'- {path}: {value}')
    visit(data)
    if len(lines) == 1:
        lines.append('The result is available in the structured details.')
    return '\n\n'.join(lines)
