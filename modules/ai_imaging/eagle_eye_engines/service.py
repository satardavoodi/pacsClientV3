"""Import-light engine execution; all disk/process work belongs off the GUI thread."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ENGINES = ('breast', 'bone-age')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bundle_root(engine):
    if engine not in ENGINES:
        raise ValueError('Unknown Eagle Eye engine.')
    from modules.ai_imaging.eagle_eye.assets import installed_feature_roots
    if getattr(sys, 'frozen', False):
        from aipacs_runtime import load_installation_profile
        if load_installation_profile().get('distribution_edition') != 'eagle-eye':
            return None
    roots = installed_feature_roots(engine.replace('-', '_'))
    if not getattr(sys, 'frozen', False):
        roots.insert(0, Path(__file__).resolve().parents[3] / 'generated-files/eagle-eye' / engine)
    return next((p for p in roots if (p / 'manifest.json').is_file()), None)


def available(engine):
    root = bundle_root(engine)
    if root is None:
        return False
    try:
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        qualified = json.loads((root / 'qualification.json').read_text(encoding='utf-8'))
        return (qualified.get('revision') == manifest['revision']
                and qualified.get('synthetic_smoke') == 'passed')
    except (OSError, ValueError, KeyError):
        return False


def validate_bundle(root, engine, cancelled=lambda: False):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('engine') != engine or manifest.get('format_version') != 1:
        raise ValueError('Incorrect engine package.')
    required = {'runner.py', 'runtime/Scripts/python.exe', 'source/worker.py'}
    required.add('weights/final_model.pth' if engine == 'bone-age' else 'weights/best_fcos_csv_delivery.pth')
    if not required.issubset(manifest['sha256']):
        raise ValueError('Incomplete engine package.')
    for name, expected in manifest['sha256'].items():
        if cancelled():
            raise RuntimeError('Analysis cancelled.')
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or digest(path) != expected:
            raise ValueError('The engine package is missing or changed. Prepare it again.')
    return manifest


def validate_sources(files, study_uid, engine, sex=None):
    """Reject mixed identity, partial/multiframe inputs and guessed sex before decode."""
    import pydicom
    from pydicom.uid import UID
    if not study_uid or not UID(study_uid).is_valid:
        raise ValueError('A valid study identity is required.')
    if not 1 <= len(files) <= 64:
        raise ValueError('Select between one and 64 source images.')
    records, seen, sexes = [], set(), set()
    for source in files:
        path = Path(source).resolve()
        if not path.is_file() or not 0 < path.stat().st_size <= 512 * 1024**2:
            raise ValueError('A source image is unavailable or exceeds the size limit.')
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        if str(ds.get('StudyInstanceUID', '')) != study_uid:
            raise ValueError('A source image belongs to another study.')
        sop, series = str(ds.get('SOPInstanceUID', '')), str(ds.get('SeriesInstanceUID', ''))
        if not sop or not series or sop in seen:
            raise ValueError('Source identity is incomplete or duplicated.')
        seen.add(sop)
        expected = ('MG',) if engine == 'breast' else ('DX', 'CR')
        if str(ds.get('Modality', '')).upper() not in expected:
            raise ValueError('The selected modality is not supported by this engine.')
        if int(ds.get('NumberOfFrames', 1)) != 1 or int(ds.get('SamplesPerPixel', 1)) != 1:
            raise ValueError('Select monochrome single-frame images.')
        if ds.get('PhotometricInterpretation') not in ('MONOCHROME1', 'MONOCHROME2'):
            raise ValueError('Unsupported photometric interpretation.')
        if not 0 < int(ds.Rows) * int(ds.Columns) <= 80_000_000:
            raise ValueError('Source dimensions exceed the limit.')
        if 'DERIVED' in str(ds.get('ImageType', '')).upper():
            raise ValueError('Select original acquisition images, not derived AI outputs.')
        if engine == 'bone-age':
            value = str(ds.get('PatientSex', '')).upper()
            if value in ('M', 'F'):
                sexes.add(value)
            if str(ds.get('BodyPartExamined', '')).upper() not in ('HAND',):
                raise ValueError('Bone Age requires an explicitly identified full-hand image.')
        records.append(dict(path=str(path), sha256=digest(path), sop_uid=sop, series_uid=series,
                            laterality=str(ds.get('ImageLaterality', '') or ds.get('Laterality', '')),
                            view_position=str(ds.get('ViewPosition', '')),
                            rows=int(ds.Rows), columns=int(ds.Columns)))
    normalized = {'m': 'M', 'male': 'M', 'f': 'F', 'female': 'F'}.get(str(sex or '').lower())
    if engine == 'bone-age':
        if len(sexes) != 1 or (normalized and normalized not in sexes):
            raise ValueError('Bone Age requires consistent verified DICOM sex.')
        normalized = next(iter(sexes))
    return records, normalized


def run(engine, files, study_uid, output_parent, *, sex=None, threshold=0.45,
        cancelled=lambda: False, root=None, timeout=1200, smoke=False):
    """Run one process-owned job. Partial or cancelled jobs are never returned."""
    if engine not in ENGINES or not 0.05 <= float(threshold) <= 0.95:
        raise ValueError('Invalid engine or threshold.')
    root = Path(root or bundle_root(engine) or '').resolve()
    manifest = validate_bundle(root, engine, cancelled)
    records, verified_sex = ([], None) if smoke else validate_sources(files, study_uid, engine, sex)
    parent = Path(output_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    job = parent / ('engine-' + uuid.uuid4().hex)
    job.mkdir()
    request = dict(engine=engine, study_uid=study_uid, files=records, sex=verified_sex,
                   threshold=float(threshold), smoke=smoke)
    (job / 'request.json').write_text(json.dumps(request), encoding='utf-8')
    from modules.mpr.advanced_3d_slicer.owned_process import ProcessJob
    owner, process, success = ProcessJob(), None, False
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_'))}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='-1',
               HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', NO_ALBUMENTATIONS_UPDATE='1',
               OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', PYTHONUTF8='1')
    try:
        if cancelled():
            raise RuntimeError('Analysis cancelled.')
        process = subprocess.Popen([str(root / 'runtime/Scripts/python.exe'), '-s', '-B',
                                    str(root / 'runner.py'), str(root), str(job)],
                                   cwd=job, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        owner.assign(process)
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancelled():
                raise RuntimeError('Analysis cancelled.')
            if time.monotonic() > deadline:
                raise RuntimeError('Engine execution timed out.')
            time.sleep(0.1)
        if cancelled():
            raise RuntimeError('Analysis cancelled.')
        if process.returncode:
            raise RuntimeError('Local engine failed. No completed result was published.')
        result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        if result.get('study_id') != study_uid or result.get('status') != 'success':
            raise RuntimeError('Invalid engine result identity.')
        for record in records:
            if digest(record['path']) != record['sha256']:
                raise RuntimeError('Source changed during inference; discard this result.')
        result['input_sha256'] = {r['sop_uid']: r['sha256'] for r in records}
        result['engine_revision'] = manifest['revision']
        result['job_directory'] = str(job)
        receipt = job / 'receipt.partial'
        receipt.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
        receipt.replace(job / 'result.json')
        if smoke:
            qualification = root / ('qualification-' + job.name + '.partial')
            qualification.write_text(json.dumps({'revision': manifest['revision'],
                'synthetic_smoke': 'passed'}), encoding='utf-8')
            qualification.replace(root / 'qualification.json')
        success = True
        return result
    finally:
        owner.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)
        if not success:
            if not job.resolve().is_relative_to(parent):
                raise RuntimeError('Unsafe temporary job cleanup path.')
            shutil.rmtree(job)


def run_study(engine, study_uid, *, sex=None, threshold=0.45, cancelled=lambda: False):
    """UI worker adapter: use the completed local source inventory only."""
    from PacsClient.utils.db_manager import get_series_by_study_uid
    from PacsClient.utils.data_paths import ATTACHMENTS_DIR
    import pydicom
    files = []
    for row in get_series_by_study_uid(study_uid):
        if str(row.get('modality', '')).upper() not in (('MG',) if engine == 'breast' else ('DX', 'CR')):
            continue
        folder = Path(row.get('series_path') or '')
        if not row.get('series_path') or not folder.is_dir():
            raise ValueError('Download the complete selected study before local analysis.')
        initial_count = len(files)
        for index, path in enumerate(folder.iterdir()):
            if index >= 1000:
                raise ValueError('Source inventory exceeds the limit.')
            if not path.is_file() or path.suffix.lower() not in ('', '.dcm', '.dicom'):
                continue
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            if str(ds.get('StudyInstanceUID', '')) != study_uid or str(ds.get('SeriesInstanceUID', '')) != str(row.get('series_uid', '')):
                raise ValueError('Local source identity does not match the selected study.')
            files.append(str(path))
        expected = int(row.get('expected_instance_count') or row.get('image_count') or 0)
        if expected <= 0 or len(files) - initial_count != expected:
            raise ValueError('A complete, counted source series is required for local analysis.')
    result = run(engine, files, study_uid, ATTACHMENTS_DIR / study_uid, sex=sex,
                 threshold=threshold, cancelled=cancelled)
    if engine == 'breast':
        # Existing MG manifests store filenames relative to the attachment root.
        for key in ('csv', 'csv_classification'):
            if result.get(key):
                source = Path(result[key])
                dest = source.parent.parent / f'{source.stem}_{threshold:.2f}_{source.parent.name}.csv'
                temporary = dest.with_suffix('.partial')
                shutil.copy2(source, temporary)
                temporary.replace(dest)
                result[key] = str(dest)
    return result
