"""Publish allowlisted results and derived editing references, never DICOM/models."""
import csv
import io
import json
from pathlib import Path, PureWindowsPath
import zipfile

from .contracts import digest

MASKS = {'labels.npy', 'labels.nii.gz', 'space-flair_seg-lst.nii.gz', 'spine-mask.npy'}
TABLES = {'volumes.csv', 'posterior.csv', 'qc.csv', 'classification.csv', 'updated_csv_with_boxes.csv'}


def prepare_breast_tables(result, records):
    """Bind portable review rows to verified series/SOP identities, never disk names."""
    directory = Path(result['artifact_directory']).resolve()
    bindings = {}
    for record in records:
        reference = f"{record['series_uid']}/{record['sop_uid']}.dcm"
        bindings[record['path']] = bindings[reference] = (record, reference)
    for key in ('csv', 'csv_classification'):
        if not result.get(key):
            continue
        path = Path(result[key]).resolve()
        if not path.is_relative_to(directory) or path.name not in TABLES:
            raise ValueError('Breast review table escaped the result directory.')
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
        for row in rows:
            binding = bindings.get(row.get('dicom_full_path') or row.get('full_image_path'))
            if binding is None:
                raise ValueError('Breast review row does not match a verified source.')
            record, reference = binding
            row.update(dicom_full_path=reference, full_image_path=reference,
                       study_instance_uid=record['study_uid'], series_instance_uid=record['series_uid'],
                       sop_instance_uid=record['sop_uid'])
        if rows:
            buffer = io.StringIO(newline='')
            writer = csv.DictWriter(buffer, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
            writer.writeheader()
            writer.writerows(rows)
            temporary = path.with_suffix('.portable.partial')
            temporary.write_text(buffer.getvalue(), encoding='utf-8')
            temporary.replace(path)


def publish(job, request, records, result):
    directory = Path(result.get('artifact_directory') or job / 'work').resolve()
    if not directory.is_relative_to(job.resolve()):
        raise ValueError('Analysis outputs escaped the job directory.')
    if result.get('acquisition_mode') == '2d':
        from ..eagle_eye_brain.lesions_2d import filesystem_path
        directory = filesystem_path(directory)
        result = dict(result, artifact_directory=str(directory),
                      mask_path=str(filesystem_path(result['mask_path'])))
        for key in ('raw_mask_path', 'band_mask_path'):
            if result.get(key):
                result[key] = str(filesystem_path(result[key]))
        if result.get('review_assets'):
            result['review_assets'] = {key: str(filesystem_path(path))
                                       for key, path in result['review_assets'].items()}
    if request['module'] == 'breast':
        prepare_breast_tables(result, records)
    exports = {}
    review_paths = set()
    if request['module'] in ('brain', 'brain-lesions') and (result.get('review_assets')
            or result.get('mask_path') or (directory / 'labels.nii.gz').is_file()):
        from .segmentation_review import assets
        selected = assets(result)
        result = dict(result, review_assets={k: str(p) for k, p in selected.items()})
        review_paths = set(selected.values())
    size = 0
    for path in directory.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if not (path in review_paths or path.name in MASKS | TABLES
                or result.get('acquisition_mode') == '2d' and path.name in ('labels-raw.nii.gz', 'labels-band-review.nii.gz')
                or request['module'] == 'total-spine' and path.name in ('coronal-annotated.png', 'lateral-annotated.png')
                or path.suffix in ('.pdf', '.html', '.png')
                and (path.name.startswith(('report', 'preview', 'evidence', 'segmentation', 'medial'))
                     or 'ALL_VIZ' in path.parts)):
            continue
        if not path.resolve().is_relative_to(directory):
            raise ValueError('Analysis output link escaped the job directory.')
        size += path.stat().st_size
        if size > 512 * 1024**2 or len(exports) >= 500:
            raise ValueError('Analysis outputs exceed the transfer limit.')
        exports[relative] = path
    path_map = {str(path): {'artifact': relative} for relative, path in exports.items()}
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in ('job_directory', 'artifact_directory')}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, str):
            if value in path_map:
                return path_map[value]
            if Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
                return None
        return value
    packet = clean(result)
    packet['source_binding'] = [{k: r[k] for k in ('study_uid', 'series_uid', 'sop_uid', 'sha256')} for r in records]
    packet['remote_analysis'] = True
    packet['server_job_id'] = job.name
    packet['analysis_series'] = request.get('series', {})
    packet['analysis_study_uid'] = request['study_uid']
    envelope = {k: request[k] for k in ('protocol', 'request_id', 'module', 'study_uid')}
    hashes = {}
    temporary = job / 'artifacts.partial'
    import hashlib
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in exports.items():
            data = path.read_bytes()
            if path.suffix == '.csv':
                # CSV identity is retained; server filesystem paths are not portable.
                rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
                if rows:
                    sources = {r['path']: r['sop_uid'] for r in records}
                    for row in rows:
                        sop = sources.get(row.get('dicom_full_path') or row.get('full_image_path'))
                        if sop:
                            row['sop_instance_uid'] = sop
                            row['full_image_path'] = sop + '.dcm'
                            row['dicom_full_path'] = sop + '.dcm'
                    buffer = io.StringIO(newline='')
                    writer = csv.DictWriter(buffer, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({k: '' if Path(v or '').is_absolute() or PureWindowsPath(v or '').is_absolute() else v
                                         for k, v in row.items()})
                    data = buffer.getvalue().encode()
            archive.writestr(name, data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        envelope.update(result=packet, files=hashes)
        archive.writestr('envelope.json', json.dumps(envelope, allow_nan=False))
    archive_path = job / 'artifacts.zip'
    temporary.replace(archive_path)
    return {'artifact_sha256': digest(archive_path), 'artifact_bytes': archive_path.stat().st_size}
