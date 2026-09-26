"""Owned same-job anatomical computation for downstream lesion assessments."""
from pathlib import Path
import shutil
import tempfile

from .contracts import BrainError


def compute_anatomy(t1_source, destination, *, cancel, progress):
    """Called inside the existing Brain lock; retain provenance outside scratch."""
    from .service import _run_analysis
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix='ee-anatomy-') as temporary:
        try:
            result = _run_analysis(t1_source, '', temporary, cancel=cancel, progress=progress)
            if cancel.is_set():
                raise BrainError('Anatomical assessment cancelled.')
            shutil.copytree(Path(result['artifact_directory']), destination)
        finally:
            # Retain private failure evidence before deleting owned scratch.
            # Logs are excluded from the server's derived-artifact allowlist.
            for name in ('process.log', 'process-diagnostics.jsonl'):
                for log in Path(temporary).glob('brain-*/' + name):
                    shutil.copyfile(log, destination.with_name(destination.name + '-' + name))
    return destination
