"""Worker-only launch contract identification for verified portable viewers.

The legacy one-file artifact has no product/version metadata. Match its verified
bytes rather than guessing a command protocol from an executable filename.
"""
import hashlib
from pathlib import Path

LEGACY_AIPACS_SHA256 = 'b8c806dbee628eba00afcab7c268af3fdeeb9f7956829b524b4b51e122224834'
IMPORT_FOLDER = 'aipacs_import_folder'
LEGACY_DICOMDIR = 'legacy_dicomdir'


def detect_viewer_launch_mode(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() == LEGACY_AIPACS_SHA256:
        return LEGACY_DICOMDIR
    # Preserve the existing contract for the current default and other artifacts.
    return IMPORT_FOLDER
