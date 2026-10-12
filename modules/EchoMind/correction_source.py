"""Opaque report-source selection envelopes; parsing belongs to EchoMind Server."""
import base64
import json

MARKER = '_echomind_correction_source_v1'


def pack(name, data):
    if not data or len(data) > 1024 * 1024:
        raise ValueError('Correction source must be nonempty and at most 1 MiB.')
    return json.dumps({MARKER: {'name': name, 'data': base64.b64encode(data).decode('ascii')}})


def unpack(value):
    try:
        obj = json.loads(value)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or MARKER not in obj:
        return None
    if set(obj) != {MARKER} or not isinstance(obj[MARKER], dict) or set(obj[MARKER]) != {'name', 'data'}:
        raise ValueError('Invalid saved correction source.')
    return obj[MARKER]
