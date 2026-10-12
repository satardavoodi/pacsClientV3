"""Server-owned Breast branches; partial analysis is explicit, never normal."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from .service import run as run_tissue, bundle_root, validate_sources, digest


def validate_calcium(data, records, study):
    if (data.get('status') != 'success' or data.get('study_id') != study
            or data.get('coordinate_space') != 'native_source_pixels_xy'):
        raise ValueError('Invalid calcium result identity.')
    expected = {(r['series_uid'], r['sop_uid'], r['sha256']) for r in records}
    files = data.get('files', [])
    actual = [(r.get('series_uid'), r.get('sop_uid'), r.get('source_sha256')) for r in files]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError('Calcium source binding mismatch.')
    for r in files:
        shape = r.get('shape_hw', [])
        points, scores = r.get('points_xy'), r.get('scores')
        if (len(shape) != 2 or any(type(v) is not int or v <= 0 for v in shape)
                or not isinstance(points, list) or not isinstance(scores, list)
                or len(points) != len(scores) or len(points) > 200000):
            raise ValueError('Invalid calcium geometry.')
        for xy, score in zip(points, scores):
            if (len(xy) != 2 or not all(math.isfinite(float(v)) for v in [*xy, score])
                    or not 0 <= xy[0] < shape[1] or not 0 <= xy[1] < shape[0]
                    or not 0 <= score <= 1):
                raise ValueError('Invalid calcium point.')
    return data


def run_calcium(files, study, output, *, cancelled=lambda: False, timeout=1200):
    tissue = bundle_root('breast')
    root = Path(tissue).parent / 'calcium-b95' if tissue else Path('__missing_calcium__')
    if not (root / 'manifest.json').is_file():
        return dict(status='unavailable', reason='calcium_bundle_not_installed')
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'breast_calcium_v1':
        raise ValueError('Unsupported calcium bundle.')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    if actual != set(manifest['sha256']):
        raise ValueError('Calcium bundle inventory mismatch.')
    for name, expected in manifest['sha256'].items():
        if cancelled():
            raise RuntimeError('Analysis cancelled.')
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != expected:
            raise ValueError('Calcium bundle integrity mismatch.')
    if 'runner.py' not in manifest['sha256']:
        raise ValueError('Calcium runner is not sealed.')
    threads = manifest.get('threads', 2)
    if type(threads) is not int or not 1 <= threads <= 4:
        raise ValueError('Unsupported calcium thread budget.')
    records, _ = validate_sources(files, study, 'breast')
    job = Path(output) / ('calcium-' + uuid.uuid4().hex)
    job.mkdir(parents=True)
    request = dict(study_uid=study, files=records)
    (job / 'request.json').write_text(json.dumps(request), encoding='utf-8')
    python = Path(tissue) / 'runtime/Scripts/python.exe'
    if not python.is_file():
        python = Path(tissue) / 'runtime/python.exe'
    command = [str(python), '-s', '-B', str(root / 'runner.py'), '--request', str(job / 'request.json'),
               '--job', str(job), '--assets', str(root / 'assets'), '--deps', str(root / 'deps'), '--threads', str(threads)]
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','QT_'))}
    env.update(CUDA_VISIBLE_DEVICES='-1', OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads),
               PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', NO_ALBUMENTATIONS_UPDATE='1')
    from modules.mpr.advanced_3d_slicer.owned_process import ProcessJob
    owner, process = ProcessJob(), None
    try:
        with (job / 'private.log').open('wb') as log:
            if cancelled():
                raise RuntimeError('Analysis cancelled.')
            process = subprocess.Popen(command, cwd=job, env=env, stdout=log, stderr=log,
                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            owner.assign(process)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancelled():
                    raise RuntimeError('Analysis cancelled.')
                if time.monotonic() > deadline:
                    raise RuntimeError('Calcium inference timed out.')
                time.sleep(.1)
            if process.returncode:
                raise RuntimeError('Calcium inference failed; inspect private server diagnostics.')
        data = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        for record in records:
            if digest(record['path']) != record['sha256']:
                raise ValueError('Calcium source changed.')
        validate_calcium(data, records, study)
        data['engine_revision'] = manifest['revision']
        return data
    finally:
        owner.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)


def run(files, study, output, *, threshold=.45, cancelled=lambda:False):
    """Run on the server worker, never the GUI thread or a client fallback."""
    stop = threading.Event()
    check = lambda: stop.is_set() or cancelled()
    if check():
        raise RuntimeError('Analysis cancelled.')
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='BreastBranches') as pool:
        calcium = pool.submit(run_calcium, files, study, output, cancelled=check)
        try:
            result = run_tissue('breast', files, study, output, threshold=threshold, cancelled=check)
        except BaseException:
            stop.set()
            raise
        try:
            data = calcium.result()
        except Exception:
            data = dict(status='unavailable', reason='calcium_execution_failed')
        if check():
            raise RuntimeError('Analysis cancelled.')
    result['calcium'] = data
    result['breast_status'] = ('completed' if data.get('status') == 'success'
        and result.get('classification_status') in ('completed','no_detections') else 'incomplete')
    return result
