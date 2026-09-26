"""Stage only the stdlib reference client into the shared Slicer UI payload."""
from pathlib import Path
import shutil

FILES = ('__init__.py', 'contracts.py', 'settings.py', 'client.py')
REPO = Path(__file__).resolve().parents[1]


def stage_client(payload):
    source = REPO / 'modules/ai_imaging/eagle_eye_remote'
    target = Path(payload) / 'python/modules/mpr/advanced_3d_slicer/slicer_modules/eagle_eye_remote'
    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        destination = target / name
        # Edition staging may use hardlinks; replace, never write through a link.
        temporary = destination.with_suffix('.staging')
        shutil.copyfile(source / name, temporary)
        temporary.replace(destination)
    return target
