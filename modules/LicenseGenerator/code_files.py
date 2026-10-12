"""Bounded license/request file helpers; called only by owned UI workers."""
from pathlib import Path
from .signed_license import LicenseError, MAX_CODE


def read_code(path):
    with Path(path).open('r', encoding='utf-8-sig') as source:
        code = source.read(MAX_CODE + 1)
    if len(code) > MAX_CODE:
        raise LicenseError('The license file is too large.')
    return code


def save_request(path, request):
    Path(path).write_text(request, encoding='utf-8')
    return None
