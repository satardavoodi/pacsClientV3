"""Keep recognizable API credentials out of Secretary planning and history."""
import re

_API_KEY = re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b')
_ASSIGNMENT = re.compile(r'\b(?:api[_ -]?key|access[_ -]?token|bearer)\s*[:=]\s*["\']?[A-Za-z0-9_-]{20,}', re.I)
LOCAL_ENTRY_MESSAGE = 'Enter API credentials in Settings > AI > EchoMind using the local password field. Do not include keys in Secretary commands.'


def contains_api_credential(text):
    return isinstance(text, str) and bool(_API_KEY.search(text) or _ASSIGNMENT.search(text))
