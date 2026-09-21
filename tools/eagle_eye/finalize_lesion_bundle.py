"""Seal the prepared portable runtime; does not confer clinical/distribution approval."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def finalize(root):
    root = Path(root).resolve()
    shutil.copy2(Path(__file__).with_name('lesion_runner.py'), root / 'runner.py')
    shutil.copy2(Path(__file__).with_name('LESION_THIRD_PARTY_NOTICES.md'), root / 'NOTICE.md')
    shutil.copy2(Path(__file__).with_name('requirements-lesions.lock'), root / 'requirements-lock.txt')
    required = [root / f'data/model/UNet3D_MS_final_mdl{k}.pt' for k in 'ABC']
    required += [root / f'python/Lib/site-packages/brainles_hd_bet/model_weights/{i}.model' for i in range(5)]
    required += [root / 'python/Scripts/lst', root / 'python/python.exe',
                 root / 'data/atlas/sub-mni152_space-mni_t1.nii.gz']
    if any(not p.is_file() or p.stat().st_size == 0 for p in required):
        raise ValueError('Install all LST-AI/HD-BET weights and the portable runtime first.')
    paths = [p for directory in ('python', 'data') for p in (root / directory).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    paths += [root / name for name in ('runner.py', 'NOTICE.md', 'requirements-lock.txt')]
    hashes = {}
    for path in paths:
        with path.open('rb') as stream:
            hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'format_version': 1, 'version': '2.0.0rc1', 'clinical_qualification': False,
                'model_release': 'CompImg/LST-AI v2.0.0-data',
                'source': 'https://github.com/CompImg/LST-AI',
                'scientific_reference': 'https://doi.org/10.1016/j.nicl.2024.103611', 'sha256': hashes}
    temporary = root / 'manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(root / 'manifest.json')
    print(f'Sealed {len(hashes)} files; acceptance remains a separate requirement.')


if __name__ == '__main__':
    finalize(sys.argv[1])
