"""Stage and seal owner-supplied models into isolated development engine bundles.

Requires separately provisioned runtime/Scripts/python.exe. Does not access patient
files, install a service, change endpoints, or turn a venv into a release runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[2]
MODEL_FILES = ['calibrators_per_label.joblib', 'stackers_per_label.joblib',
               'stack_imputer.joblib', 'stack_used_kinds.joblib', 'thresholds_STACKED.npy',
               'label_order.txt', *[f'feature_list_{k}.txt' for k in ('BL', 'BOTH', 'MV', 'SINGLE')],
               *[f'xgb_ovr_{k}.joblib' for k in ('BL', 'BOTH', 'MV', 'SINGLE')]]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def normalize_runtime_home(runtime):
    """Record the physical base path, not an MSIX-virtualized user-profile alias."""
    cfg = Path(runtime) / 'pyvenv.cfg'
    if not cfg.is_file():
        return  # A self-contained packaged interpreter need not use a venv.
    lines = cfg.read_text(encoding='utf-8').splitlines()
    for index, line in enumerate(lines):
        key, separator, value = line.partition('=')
        if separator and key.strip() == 'home':
            base = Path(value.strip()).resolve()
            if not (base / 'python.exe').is_file():
                raise ValueError('The development runtime base interpreter is unavailable.')
            lines[index] = f'home = {base}'
            cfg.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            return
    raise ValueError('The development runtime has no base interpreter home.')


def prepare(snapshot, engine):
    root = REPO / 'generated-files/eagle-eye' / engine
    source = REPO / 'modules/ai_imaging/eagle_eye_engines'
    if not (root / 'runtime/Scripts/python.exe').is_file():
        raise ValueError('Provision the isolated runtime first.')
    normalize_runtime_home(root / 'runtime')
    (root / 'weights').mkdir(parents=True, exist_ok=True)
    names = {'final_model.pth': 'final_model.pth'} if engine == 'bone-age' else {
        'best_fcos_csv_delivery.pth': 'best_fcos_csv_delivery.pth',
        **{f'XGBoost_AR/models_stacked/{n}': f'models_stacked/{n}' for n in MODEL_FILES}}
    for original, target in names.items():
        dest = root / 'weights' / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot / engine / original, dest)
    (root / 'source').mkdir(exist_ok=True)
    shutil.copy2(source / 'worker.py', root / 'source/worker.py')
    for path in (source / 'vendor' / engine.replace('-', '_')).glob('*.py'):
        shutil.copy2(path, root / 'source' / path.name)
    (root / 'runner.py').write_text(
        'import sys\nfrom pathlib import Path\n'
        'root, job = map(Path, sys.argv[1:])\n'
        'sys.path.insert(0, str(root / "source"))\n'
        'from worker import main\n'
        'main(root, job)\n', encoding='utf-8')
    files = [root / 'runner.py']
    for directory in ('runtime', 'source', 'weights'):
        files.extend(p for p in (root / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in sorted(files)}
    revision = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(dict(format_version=1, engine=engine,
        revision=revision, device='cpu', deployment='development-venv', sha256=hashes), indent=2), encoding='utf-8')
    print(f'{engine}: sealed {len(hashes)} files; development bundle, not a portable installer.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('engine', choices=('breast', 'bone-age'))
    args = parser.parse_args()
    prepare(args.snapshot, args.engine)
