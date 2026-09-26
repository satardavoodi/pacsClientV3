"""Prepare the optional 2D research engine without changing sealed LST dependencies.

Not a release installer: model redistribution terms are not declared on the
upstream Hugging Face model card. Resolve that before customer redistribution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

WHEELS = {
    'mindglide-1.3.0-py3-none-any.whl': '6031f365773a37303f2608cb31455bbc9d6f31bfe24ff806dc940891ec397fc5',
    'monai-1.5.0-py3-none-any.whl': '93259cfa8b68fbf006dea7c78376a46ce38f369bf8b20b36f74ab1d3f484d37b',
}
MODEL_SHA256 = '881e30efd9444a25ee70c01d795dd9fb21ac750a48f1ba8070fcd79fb75e76ca'
MODEL_URL = ('https://huggingface.co/MS-PINPOINT/mindglide/resolve/'
             'a1969821c0a4a37ae54f649a9a0c6fd1b8a48e26/_20240404_conjurer_trained_dice_7733.pt')


def shared_runtime_hashes(bundle):
    """Use the existing sealed hashes; omit unused LST models, headers and tests."""
    sealed = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))['sha256']
    packages = {'torch', 'numpy', 'numpy.libs', 'scipy', 'scipy.libs', 'nibabel', 'skimage',
                'pandas', 'pandas.libs', 'tqdm', 'packaging', 'filelock', 'networkx',
                'fsspec', 'sympy', 'mpmath', 'typing_extensions.py', 'six.py', 'dateutil',
                'pytz', 'tzdata', 'PIL', 'lazy_loader', 'imageio', 'tifffile', 'psutil',
                'importlib_resources', 'zipp', 'yaml', 'pkg_resources'}
    chosen = {}
    for name, value in sealed.items():
        parts = Path(name).parts
        if parts[0] != 'python':
            continue
        if len(parts) == 2 or (len(parts) >= 4 and parts[1:3] == ('Lib', 'site-packages')
                              and parts[3] in packages and not {'include', 'test', 'tests', '__pycache__'} & set(parts[4:])):
            chosen[name] = value
    if not {'python/python.exe', 'python/python310.dll', 'python/python310.zip',
            'python/Lib/site-packages/torch/__init__.py', 'python/Lib/site-packages/numpy/__init__.py'} <= chosen.keys():
        raise ValueError('Shared runtime inventory is incomplete.')
    return chosen


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def prepare(bundle, downloads):
    bundle, downloads = Path(bundle).resolve(), Path(downloads).resolve()
    root = bundle / 'mindglide'
    root.mkdir(exist_ok=True)
    # Build into a new directory to avoid retaining stale MONAI package files.
    target = root / 'site-packages-v1'
    if target.exists():
        raise ValueError('Preparation target already exists. Use a fresh staging bundle.')
    for name, expected in WHEELS.items():
        if digest(downloads / name) != expected:
            raise ValueError('Pinned wheel digest mismatch: ' + name)
    target.mkdir()
    for name in WHEELS:
        with zipfile.ZipFile(downloads / name) as wheel:
            for member in wheel.namelist():
                if not (target / member).resolve().is_relative_to(target):
                    raise ValueError('Unsafe wheel member.')
            wheel.extractall(target)
    model = root / 'model.pt'
    if not model.exists():
        urllib.request.urlretrieve(MODEL_URL, model)
    if digest(model) != MODEL_SHA256:
        raise ValueError('Pinned MindGlide model digest mismatch.')
    shutil.copyfile(Path(__file__).with_name('mindglide_runner.py'), root / 'runner.py')
    files = [model, root / 'runner.py', *[p for p in target.rglob('*') if p.is_file()]]
    manifest = dict(format_version=1, version='1.3.0', model_sha256=MODEL_SHA256,
                    model_url=MODEL_URL, redistribution_qualified=False, clinical_qualification=False,
                    python_sha256=digest(bundle / 'python/python.exe'),
                    shared_sha256=shared_runtime_hashes(bundle),
                    sha256={p.relative_to(root).as_posix(): digest(p) for p in files})
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--downloads', required=True)
    args = parser.parse_args()
    prepare(args.bundle, args.downloads)
