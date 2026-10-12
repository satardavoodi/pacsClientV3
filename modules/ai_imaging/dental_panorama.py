"""Developer panoramic candidate: server-owned inference and explicit source binding."""
import base64
import csv
import html
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

FINDINGS = ('MISSING', 'IMPLANT', 'RESIDUAL_ROOT', 'CROWN_BRIDGE',
            'ROOT_CANAL_FILLING', 'FILLING', 'CARIES', 'PERIAPICAL_RADIOLUCENCY')
IMAGE_DIGEST = 'sha256:74a722b3fb62f5b3f7f08820bfac9a21c1ffbe357311f22f9e1e187129204147'
LIMITATION = ('Experimental panoramic candidate; physician review required. Scores are not '
              'calibrated probabilities. No assessment of pulp involvement, periodontal bone '
              'loss, root canal adequacy, or implant health is provided.')


def validate_rows(rows):
    expected = {(str(q * 10 + n), f) for q in range(1, 5) for n in range(1, 9) for f in FINDINGS}
    if not isinstance(rows, list) or len(rows) != 256:
        raise ValueError('Incomplete dental model output.')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'fdi', 'finding', 'score'}:
            raise ValueError('Unsupported dental result schema.')
        pair = (row['fdi'], row['finding'])
        score = row['score']
        if pair not in expected or pair in seen or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid or duplicate dental model score.')
        seen.add(pair)
    return rows


def load_image(path, study_uid, series_uid=None):
    """Read on a worker; reject mixed identity, multi-frame and non-radiographs."""
    import pydicom
    import numpy as np
    from pydicom.pixel_data_handlers.util import apply_modality_lut
    ds = pydicom.dcmread(path)
    if (str(ds.get('StudyInstanceUID', '')) != study_uid or not study_uid
            or series_uid and str(ds.get('SeriesInstanceUID', '')) != series_uid):
        raise ValueError('The selected image belongs to another study or series.')
    if str(ds.get('Modality', '')).upper() not in ('DX', 'CR', 'PX', 'IO'):
        raise ValueError('Select a panoramic dental radiograph.')
    if int(ds.get('NumberOfFrames', 1)) != 1 or int(ds.get('SamplesPerPixel', 1)) != 1:
        raise ValueError('One monochrome panoramic image is required.')
    if not 0 < int(ds.Rows) * int(ds.Columns) <= 24_000_000:
        raise ValueError('Panoramic image dimensions exceed the supported limit.')
    raw = ds.pixel_array
    pixels = np.asarray(apply_modality_lut(raw, ds), dtype=np.float32)
    valid = np.isfinite(pixels)
    if 'PixelPaddingValue' in ds:
        low = float(ds.PixelPaddingValue)
        high = float(ds.get('PixelPaddingRangeLimit', low))
        valid &= ~((raw >= min(low, high)) & (raw <= max(low, high)))
    if pixels.ndim != 2 or not valid.any():
        raise ValueError('No usable panoramic pixels.')
    low, high = float(pixels[valid].min()), float(pixels[valid].max())
    if high <= low:
        raise ValueError('No usable panoramic contrast.')
    pixels = np.clip((pixels - low) * 255 / (high - low), 0, 255)
    if ds.PhotometricInterpretation == 'MONOCHROME1':
        pixels = 255 - pixels
    elif ds.PhotometricInterpretation != 'MONOCHROME2':
        raise ValueError('Unsupported panoramic photometric interpretation.')
    pixels[~valid] = 0
    identity = {'study_uid': study_uid, 'series_uid': str(ds.get('SeriesInstanceUID', '')),
                'sop_uid': str(ds.get('SOPInstanceUID', ''))}
    from .eagle_eye_remote.contracts import uid
    for value in identity.values():
        uid(value)
    return {'pixels': pixels.astype(np.uint8), 'identity': identity}


def study_images(study_uid):
    from PacsClient.utils.db_manager import get_series_by_study_uid
    import pydicom
    result = []
    for series in get_series_by_study_uid(study_uid):
        if str(series.get('modality', '')).upper() not in ('DX', 'CR', 'PX', 'IO') or not series.get('series_path'):
            continue
        folder = Path(series['series_path'])
        if not folder.is_dir():
            continue
        for index, path in enumerate(folder.iterdir()):
            if index >= 1000:
                raise ValueError('Select a single panoramic DICOM image.')
            if not path.is_file() or path.suffix.lower() not in ('', '.dcm', '.dicom'):
                continue
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            if str(ds.get('StudyInstanceUID', '')) == study_uid and str(ds.get('SeriesInstanceUID', '')) == series.get('series_uid'):
                result.append({'path': str(path), 'series_uid': str(ds.SeriesInstanceUID),
                               'label': f"Series {series.get('series_number', '')} | Image {ds.get('InstanceNumber', '')}"})
    return result


def analyze(image, cancel):
    """Client sends DICOM references only, never pixels or worker credentials."""
    from .eagle_eye_remote.client import Client
    from PacsClient.utils.data_paths import AI_DIR
    identity = image['identity']
    client = Client()
    if 'dental-panorama' not in client.json('/v1/capabilities').get('modules', []):
        raise ValueError('The selected Eagle Eye Server needs the panoramic Developer update.')
    result = client.analyze('dental-panorama', identity['study_uid'],
        {'primary': {'series_uid': identity['series_uid'], 'sop_uid': identity['sop_uid'], 'expected_count': 1}},
        {'panoramic_confirmed': True}, Path(AI_DIR) / 'eagle_eye', cancel=cancel)
    bindings = result.get('source_binding', [])
    if len(bindings) != 1 or any(bindings[0].get(k) != identity[k] for k in identity):
        raise ValueError('Dental result does not match the selected source image.')
    validate_rows(result.get('dental_scores'))
    return result


def load_saved(result, study_uid):
    """Validate retained results and decode their owned preview off the GUI thread."""
    from PIL import Image
    import numpy as np
    if result.get('analysis_study_uid', result.get('study_uid')) != study_uid:
        raise ValueError('Dental result belongs to another study.')
    bindings = result.get('source_binding', [])
    if len(bindings) != 1 or bindings[0].get('study_uid') != study_uid:
        raise ValueError('Dental result source binding is incomplete.')
    if result.get('model_digest') != IMAGE_DIGEST:
        raise ValueError('Unsupported dental model revision.')
    validate_rows(result.get('dental_scores'))
    root = Path(result['artifact_directory']).resolve()
    preview = (root / 'preview.png').resolve()
    if preview.parent != root:
        raise ValueError('Saved dental preview escaped its directory.')
    with Image.open(preview) as image:
        if image.width * image.height > 24_000_000:
            raise ValueError('Unsupported preview dimensions.')
        pixels = np.asarray(image.convert('L')).copy()
    return {'result': result, 'pixels': pixels}


def execute(request, records, output, cancel):
    """Only the Eagle Eye Server may call the private fixed-command Linux worker."""
    from PIL import Image
    if len(records) != 1 or request['parameters'].get('panoramic_confirmed') is not True:
        raise ValueError('Confirm and select exactly one panoramic source.')
    ref = request['series']['primary']
    if records[0]['sop_uid'] != ref['sop_uid']:
        raise ValueError('Panoramic source identity changed.')
    image = load_image(records[0]['path'], request['study_uid'], ref['series_uid'])
    if image['identity']['sop_uid'] != ref['sop_uid']:
        raise ValueError('Panoramic source instance changed.')
    cfg_path = Path(os.environ.get('AIPACS_DENTAL_WORKER_CONFIG', 'D:/Eagle Eye Server/config/dental-worker.json'))
    cfg = json.loads(cfg_path.read_text(encoding='utf-8-sig'))
    buffer = io.BytesIO()
    Image.fromarray(image['pixels']).save(buffer, format='PNG')
    payload = json.dumps({'protocol': 1, 'image_png': base64.b64encode(buffer.getvalue()).decode()}).encode()
    if len(payload) > 32 * 1024**2:
        raise ValueError('Panoramic payload exceeds the worker limit.')
    command = [cfg['ssh_executable'], '-F', cfg.get('ssh_config', '/dev/null'),
               '-o', 'BatchMode=yes', '-o', 'ClearAllForwardings=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=10', '-o', 'UserKnownHostsFile="' + cfg['known_hosts'] + '"',
               '-i', cfg['private_key'], cfg['destination'], 'dental-panorama-v1']
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Files avoid pipe deadlock; no source pixels or identifiers enter logs.
    with tempfile.TemporaryDirectory(prefix='dental-', dir=output) as scratch, \
            (Path(scratch) / 'input').open('w+b') as inp, (Path(scratch) / 'output').open('w+b') as out:
        inp.write(payload); inp.seek(0)
        process = subprocess.Popen(command, stdin=inp, stdout=out, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancel.is_set() or time.monotonic() - started > 240:
                    process.kill()
                    raise RuntimeError('Dental analysis cancelled or timed out.')
                time.sleep(.1)
            if process.returncode:
                raise RuntimeError('Dental model worker unavailable; no diagnostic result was generated.')
            out.seek(0)
            data = out.read(2 * 1024**2 + 1)
            if len(data) > 2 * 1024**2:
                raise ValueError('Dental worker output exceeds the limit.')
            result = json.loads(data)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
    if result.get('model_digest') != IMAGE_DIGEST:
        raise ValueError('Unexpected dental model revision.')
    rows = validate_rows(result.get('rows'))
    with (output / 'dental.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['fdi', 'finding', 'score'])
        writer.writeheader(); writer.writerows(rows)
    Image.fromarray(image['pixels']).save(output / 'preview.png')
    table = ''.join(f"<tr><td>{r['fdi']}</td><td>{r['finding']}</td><td>{r['score']:.4f}</td></tr>" for r in rows)
    (output / 'report.html').write_text('<html><body><h2>Panoramic AI: Research Draft</h2><p>'
        + html.escape(LIMITATION) + '</p><table><tr><th>FDI</th><th>Finding</th><th>Score</th></tr>'
        + table + '</table></body></html>', encoding='utf-8')
    return {'artifact_directory': str(output), 'dental_scores': rows, 'model_digest': IMAGE_DIGEST,
            'report_status': 'unreviewed_research_draft', 'limitations': LIMITATION,
            'preprocessing': 'native modality LUT, valid-pixel min/max, MONOCHROME inversion, no resizing',
            'elapsed_seconds': round(time.monotonic() - started, 3)}
