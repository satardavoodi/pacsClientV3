"""Prepare a standalone Windows Breast or Bone Age engine from verified local inputs.

This creates an immutable build input, not redistribution or clinical approval.
The destination must be new. No patient data or inference outputs are copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from modules.ai_imaging.eagle_eye_engines.service import validate_bundle

PYTHON_MINOR = {'breast': (3, 10), 'bone-age': (3, 12)}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _base_ignores(directory: str, names: list[str]) -> set[str]:
    excluded = {'__pycache__', 'include', 'libs', 'Scripts'} if Path(directory).name.startswith('cpython-') else {'__pycache__'}
    return set(names) & excluded


def _package_ignores(directory: str, names: list[str]) -> set[str]:
    excluded = {'__pycache__'}
    if Path(directory).name == 'torch':
        # C/C++ headers are not loaded during inference and exceed Inno source-path limits.
        excluded.add('include')
    return set(names) & excluded


def _probe_runtime(runtime: Path, engine: str) -> dict:
    modules = ('torch', 'torchvision', 'pydicom', 'numpy', 'pandas') if engine == 'breast' else (
        'torch', 'timm', 'pydicom', 'numpy')
    code = (
        'import importlib,json,pathlib,sys; '
        'root=pathlib.Path(sys.prefix).resolve(); '
        'names=' + repr(modules) + '; '
        'mods=[importlib.import_module(name) for name in names]; '
        'assert root==pathlib.Path(sys.executable).resolve().parent; '
        'assert all(pathlib.Path(mod.__file__).resolve().is_relative_to(root) for mod in mods); '
        'print(json.dumps({"version":list(sys.version_info[:3]),"modules":names}))'
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith(('PYTHON', 'QT_'))}
    result = subprocess.run([str(runtime / 'python.exe'), '-I', '-B', '-c', code],
                            cwd=runtime.parent, env=env, capture_output=True, text=True,
                            check=True, timeout=120,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    probe = json.loads(result.stdout)
    if tuple(probe['version'][:2]) != PYTHON_MINOR[engine]:
        raise ValueError(f'{engine} requires Python {PYTHON_MINOR[engine]}, found {probe["version"]}.')
    return probe


def prepare(engine: str, development_bundle: Path, python_home: Path, output: Path) -> Path:
    if engine not in PYTHON_MINOR:
        raise ValueError('Unknown Eagle Eye engine.')
    development_bundle = development_bundle.resolve()
    python_home = python_home.resolve()
    output = output.resolve()
    if (output.exists() or output.is_relative_to(development_bundle)
            or output.is_relative_to(python_home)):
        raise ValueError('Choose a new destination outside both inputs.')
    if not (python_home / 'python.exe').is_file():
        raise ValueError('A complete standalone Python base is required.')
    if not (development_bundle / 'runtime/Lib/site-packages').is_dir():
        raise ValueError('The verified development dependency tree is missing.')
    original = validate_bundle(development_bundle, engine)
    if original.get('deployment') != 'development-venv':
        raise ValueError('Expected the explicitly verified development engine input.')
    runtime = output / 'runtime'
    shutil.copytree(python_home, runtime, ignore=_base_ignores)
    shutil.copytree(development_bundle / 'runtime/Lib/site-packages',
                    runtime / 'Lib/site-packages', dirs_exist_ok=True, ignore=_package_ignores)
    for name in ('source', 'weights'):
        shutil.copytree(development_bundle / name, output / name,
                        ignore=lambda _directory, names: set(names) & {'__pycache__'})
    shutil.copy2(development_bundle / 'runner.py', output / 'runner.py')
    if (runtime / 'pyvenv.cfg').exists() or (runtime / 'Scripts/python.exe').exists():
        raise ValueError('A standalone engine must not carry a virtual-environment launcher.')
    probe = _probe_runtime(runtime, engine)
    dependencies = subprocess.run(
        [str(runtime / 'python.exe'), '-I', '-B', '-c',
         'import importlib.metadata as m,json; print(json.dumps(sorted((d.metadata["Name"],d.version) for d in m.distributions())))'],
        cwd=output, capture_output=True, text=True, check=True, timeout=60,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (output / 'dependencies.json').write_text(dependencies.stdout, encoding='utf-8')
    names = [p for p in output.rglob('*') if p.is_file() and '__pycache__' not in p.parts
             and p.suffix not in ('.pyc', '.pyo')]
    hashes = {path.relative_to(output).as_posix(): digest(path) for path in sorted(names)}
    revision = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    manifest = dict(format_version=2, engine=engine, revision=revision,
                    deployment='standalone-python', device='cpu',
                    python_version=probe['version'],
                    source_manifest_sha256=digest(development_bundle / 'manifest.json'),
                    sha256=hashes)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'runtime-probe.json').write_text(json.dumps(dict(
        status='passed', manifest_sha256=digest(output / 'manifest.json'),
        python_version=probe['version'], modules=probe['modules'],
        scope='Relocated, isolated interpreter and required module imports only; no clinical acceptance.'
    ), indent=2), encoding='utf-8')
    validate_bundle(output, engine)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=tuple(PYTHON_MINOR))
    parser.add_argument('--development-bundle', type=Path, required=True)
    parser.add_argument('--python-home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(f'Prepared {prepare(args.engine, args.development_bundle, args.python_home, args.output)}')
