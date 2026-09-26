"""Server-owned adapters for the existing analysis services; no viewer state."""
from pathlib import Path
import json
import os
import threading

from .source import role_path


def execute(request, records, output, cancel=None):
    cancel = cancel or threading.Event()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    module, params = request['module'], request['parameters']
    study = request['study_uid']
    if module in ('brain', 'brain-lesions') and 'correction' in params:
        from .segmentation_review import calculate
        return calculate(request, output, cancel)
    if module == 'total-spine' and 'correction' in params:
        from .spine_review import calculate
        return calculate(request, records, output)
    if module == 'alignment' and 'correction' in params:
        from .reviews import calculate
        return calculate(request, records, output)
    if module in ('breast', 'bone-age'):
        from ..eagle_eye_engines.service import run
        result = run(module, [r['path'] for r in records], study, output,
                     sex=params.get('sex'), threshold=params.get('threshold', .45), cancelled=cancel.is_set)
        result['artifact_directory'] = result['job_directory']
        if module == 'breast':
            from .artifacts import prepare_breast_tables
            prepare_breast_tables(result, records)
        return result
    if module == 'brain':
        from ..eagle_eye_brain.service import run_analysis
        from ..eagle_eye_brain.contracts import BrainPlan
        return run_analysis(role_path(records, 't1'),
            role_path(records, 'flair') if 'flair' in request['series'] else '', output,
            plan=BrainPlan(profile=params.get('profile', 'standard')), cancel=cancel,
            reference_id=params.get('reference_id', 'volbrain'))
    if module == 'brain-lesions':
        from ..eagle_eye_brain.lesions import run_lesions
        return run_lesions(role_path(records, 't1'), role_path(records, 'flair'),
            study_uid=study, t1_uid=request['series']['t1']['series_uid'],
            flair_uid=request['series']['flair']['series_uid'], root=output, cancel=cancel, **params)
    if module in ('alignment', 'total-spine'):
        from ..eagle_eye_alignment.service import load_image, predict
        ref = request['series']['primary']
        record = next(r for r in records if r['sop_uid'] == ref['sop_uid'])
        image = load_image(record['path'], study, ref['series_uid'])
        if module == 'alignment':
            result = predict(image, cancel)
        else:
            from ..eagle_eye_total_spine.service import load_view, predict as spine_predict
            from ..eagle_eye_total_spine.review_workflow import predict_region
            image = load_view(record['path'], study, ref['series_uid'], params.get('projection', 'coronal'))
            if params.get('model') == 'sam':
                import numpy as np
                from ..eagle_eye_total_spine.assist_service import segment_body
                result = segment_body(image, params['level'], params['region'], cancel)
                mask = result.pop('mask')
                np.save(output / 'spine-mask.npy', mask, allow_pickle=False)
                result.update(mask_file=str(output / 'spine-mask.npy'), artifact_directory=str(output),
                              radiograph_binding=image['radiograph_binding'])
                return result
            if params.get('model', 'isbi') == 'scoliovis':
                from ..eagle_eye_total_spine.assist_service import predict_scoliovis
                spine_predict = predict_scoliovis
            result = predict_region(image, params['region'], cancel, spine_predict)
        result['radiograph_binding'] = image['radiograph_binding']
        result['artifact_directory'] = str(output)
        return result
    if module == 'lumbar':
        import numpy as np
        import SimpleITK as sitk
        from ..offline_lumbar.service import run_snapshot
        from ..eagle_eye.assets import installed_feature_roots
        folder = role_path(records, 'primary')
        series = request['series']['primary']['series_uid']
        filenames = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(folder), series)
        if len(filenames) != len(records):
            raise ValueError('Lumbar source inventory cannot form one volume.')
        validate_lumbar_geometry(filenames)
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(filenames)
        image = reader.Execute()
        if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
            raise ValueError('A scalar MR volume is required.')
        affine = np.eye(4)
        affine[:3, :3] = np.diag([-1, -1, 1]) @ np.asarray(image.GetDirection()).reshape(3, 3) @ np.diag(image.GetSpacing())
        affine[:3, 3] = np.diag([-1, -1, 1]) @ image.GetOrigin()
        roots = installed_feature_roots('lumbar')
        roots.insert(0, Path(__file__).resolve().parents[3] / 'generated-files/offline-lumbar/bundle')
        if os.environ.get('AIPACS_OFFLINE_LUMBAR_ROOT'):
            roots.insert(0, Path(os.environ['AIPACS_OFFLINE_LUMBAR_ROOT']))
        bundle = next((p for p in roots if (p / 'manifest.json').is_file()), None)
        if bundle is None:
            raise ValueError('Lumbar model package is unavailable on the server.')
        result, labels = run_snapshot(bundle, output, sitk.GetArrayFromImage(image), affine, cancel=cancel)
        directory = Path(result['artifact_directory'])
        np.save(directory / 'labels.npy', labels, allow_pickle=False)
        result['labels_file'] = str(directory / 'labels.npy')
        result['shape_kji'] = list(labels.shape)
        result['affine_ras'] = affine.tolist()
        return result
    raise ValueError('Unknown analysis module.')


def validate_lumbar_geometry(filenames):
    import numpy as np
    import pydicom
    orientations, positions = [], []
    for name in filenames:
        ds = pydicom.dcmread(name, stop_before_pixels=True)
        if (str(ds.get('Modality', '')) != 'MR' or int(ds.get('NumberOfFrames', 1)) != 1
                or int(ds.get('SamplesPerPixel', 1)) != 1):
            raise ValueError('Server lumbar analysis requires original single-frame MR slices.')
        orientations.append(list(ds.get('ImageOrientationPatient', [])))
        positions.append(list(ds.get('ImagePositionPatient', [])))
    orientations, positions = np.asarray(orientations, dtype=float), np.asarray(positions, dtype=float)
    if len(filenames) < 3 or orientations.shape != (len(filenames), 6) or positions.shape != (len(filenames), 3):
        raise ValueError('Lumbar source geometry is incomplete.')
    if not np.isfinite(orientations).all() or not np.isfinite(positions).all() or not np.allclose(orientations, orientations[0], atol=1e-5):
        raise ValueError('Lumbar source orientation is inconsistent.')
    normal = np.cross(orientations[0, :3], orientations[0, 3:])
    delta = np.diff(positions, axis=0)
    distances = delta @ normal
    if (not np.all(distances > 0) or not np.allclose(distances, distances[0], rtol=.01, atol=.01)
            or not np.allclose(delta, distances[:, None] * normal, atol=.01)):
        raise ValueError('Lumbar slices contain gaps, duplicates or unsupported shear.')


def main(job_path=None):
    import sys
    os.environ['AIPACS_EAGLE_EYE_WORKER'] = '1'
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    job = Path(job_path or sys.argv[1]).resolve()
    request = json.loads((job / 'request.json').read_text(encoding='utf-8'))
    records = json.loads((job / 'sources.json').read_text(encoding='utf-8'))
    # The worker also owns read leases if the hosting service terminates.
    from .source import SourceLease
    from .contracts import digest
    with SourceLease() as lease:
        for record in records:
            if record.get('storage_mode') == 'hardlink':
                lease.pin(record['path'])
                if digest(record['path']) != record['sha256']:
                    raise ValueError('Shared input changed before worker admission.')
        result = execute(request, records, job / 'work')
    (job / 'worker-result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    app.quit()


if __name__ == '__main__':
    main()
