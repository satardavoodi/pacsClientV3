"""Prepare a local portable Brain candidate; this does not approve distribution."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from modules.ai_imaging.eagle_eye_brain.runtime import validate_bundle, sha256, SYNTHSEG_REVISION
from modules.ai_imaging.eagle_eye_brain.volbrain_reference import data_root, HASHES


COMPILE_ONLY_RUNTIME_DIRS = ('Lib/site-packages/tensorflow/include',)


def remove_compile_only_runtime_files(python_home):
    """Remove headers that TensorFlow inference never loads at runtime."""
    python_home = Path(python_home).resolve()
    removed = []
    for relative in COMPILE_ONLY_RUNTIME_DIRS:
        target = (python_home / relative).resolve()
        if not target.is_relative_to(python_home):
            raise ValueError('Compile-only runtime exclusion escaped the portable Python root')
        if target.exists():
            shutil.rmtree(target)
            removed.append(relative)
    return tuple(removed)


def prepare(source, destination, python_home=None):
    if python_home is None:
        raise ValueError('Supply a prepared standalone Windows Python; the old virtual environment is retired')
    source, destination = Path(source).resolve(), Path(destination).resolve()
    reuse_python = python_home is not None and Path(python_home).resolve() == destination / 'model/python'
    if ((destination.exists() and not reuse_python) or destination.is_relative_to(source)
            or source.is_relative_to(destination)):
        raise ValueError('Choose a new output directory separate from the source bundle')
    if reuse_python and any((destination / name).exists() for name in
                            ('model/manifest.json', 'model/SynthSeg', 'references')):
        raise ValueError('In-place finalization requires a fresh Python-only candidate')
    original = validate_bundle(source)
    base = Path(python_home).resolve()
    if not (base / 'python.exe').is_file():
        raise ValueError('A complete local Windows Python base is required')
    model = destination / 'model'
    # Copy real Python, not a venv launcher with an absolute base-interpreter path.
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    if not reuse_python:
        shutil.copytree(base, model / 'python', ignore=ignore)
    # Keep the redistributable runtime DLL beside the interpreter when the
    # embedded Python archive omits it; do not depend on a developer PATH entry.
    vc_runtime = source / 'python-base/vcruntime140_1.dll'
    if vc_runtime.is_file() and not (model / 'python/vcruntime140_1.dll').exists():
        shutil.copy2(vc_runtime, model / 'python/vcruntime140_1.dll')
    remove_compile_only_runtime_files(model / 'python')
    with (model / 'dependencies.json').open('w', encoding='utf-8') as inventory:
        subprocess.run([str(model / 'python/python.exe'), '-I', '-B', '-c',
            'import json,importlib.metadata as m; print(json.dumps(sorted((d.metadata["Name"],d.version) for d in m.distributions())))'],
            stdout=inventory, check=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for name in original['sha256']:
        if name.startswith('SynthSeg/'):
            target = model / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
    for name in ('LICENSE.txt', 'bibtex.bib', 'README.md'):
        shutil.copy2(source / 'SynthSeg' / name, model / 'SynthSeg' / name)
    manifest = dict(format_version=2, revision=SYNTHSEG_REVISION, platform='windows-x64',
                    sha256={p.relative_to(model).as_posix(): sha256(p)
                            for p in sorted(model.rglob('*')) if p.is_file()
                            and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')})
    (model / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    validate_bundle(model)
    reference = destination / 'references/volbrain'
    reference.mkdir(parents=True)
    for sex, digest in HASHES.items():
        name = 'bounds_' + ('general' if sex == 'unknown' else sex) + '.csv'
        if sha256(data_root() / name) != digest:
            raise ValueError('Reference data failed integrity verification')
        shutil.copy2(data_root() / name, reference / name)
    for name in ('README.md', 'license.txt'):
        shutil.copy2(data_root() / name, reference / name)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('PYTHON', 'QT_'))}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='-1')
    # Different cwd and no inherited Python path; both imports and the actual CLI load.
    code = ('import sys,pathlib,tensorflow,numpy,scipy,nibabel,h5py; '
            'r=pathlib.Path(sys.executable).resolve().parent; '
            'assert pathlib.Path(sys.prefix).resolve()==r; '
            'assert all(pathlib.Path(m.__file__).resolve().is_relative_to(r) '
            'for m in (tensorflow,numpy,scipy,nibabel,h5py))')
    # Python 3.8 lacks Path.is_relative_to.
    code = code.replace('pathlib.Path(m.__file__).resolve().is_relative_to(r)',
                        'r in pathlib.Path(m.__file__).resolve().parents')
    commands = [[model / 'python/python.exe', '-I', '-B', '-c', code],
                [model / 'python/python.exe', '-I', '-B',
                 model / 'SynthSeg/scripts/commands/SynthSeg_predict.py', '--help']]
    with (destination / 'runtime-probe.log').open('w', encoding='utf-8') as log:
        for command in commands:
            subprocess.run([str(p) for p in command], cwd=destination, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    (destination / 'runtime-probe.json').write_text(json.dumps(dict(
        status='passed', model_manifest_sha256=sha256(model / 'manifest.json'),
        scope='Relocated Windows interpreter, dependency imports and SynthSeg CLI only; no clinical acceptance.'
    ), indent=2), encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=REPO / 'generated-files/brain-volumetry')
    parser.add_argument('--output', type=Path, default=REPO / 'generated-files/eagle-eye/brain-tf212-py310')
    parser.add_argument('--python-home', type=Path, required=True, help='Prepared standalone Windows Python with dependencies; never a venv')
    args = parser.parse_args()
    prepare(args.source, args.output, args.python_home)
    print('Portable Brain candidate prepared. Distribution approval is not granted by this operation.')
