"""Bounded file upload preparation, called only from the request worker."""
from pathlib import Path
import base64

MAX_BYTES = 1024 * 1024
MAX_FILES = 6
EXTENSIONS = {'.txt', '.docx', '.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.gif'}


def encode_attachments(paths):
    if len(paths) > MAX_FILES:
        raise ValueError('Attach at most six files.')
    result, total = [], 0
    for path in paths:
        path = Path(path)
        if path.suffix.lower() not in EXTENSIONS:
            raise ValueError('Use TXT, DOCX, PDF or a standard image. Export DOC as DOCX first.')
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        total += len(data)
        if not data or total > MAX_BYTES:
            raise ValueError('Attachments must be nonempty and total at most 1 MiB.')
        result.append({'name': path.name, 'data': base64.b64encode(data).decode('ascii')})
    return result
