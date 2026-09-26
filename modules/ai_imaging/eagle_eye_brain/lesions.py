"""Worker-only LST-AI lesion workflow, separate from anatomical volumetry."""
import json
from pathlib import Path
import threading
import uuid

import numpy as np

from .contracts import BrainError

LST_VERSION = '2.0.0rc1'


def lesion_bundle():
    import os
    from aipacs_runtime import is_frozen
    from modules.ai_imaging.eagle_eye.assets import installed_feature_roots
    override = os.environ.get('AIPACS_BRAIN_LESION_BUNDLE')
    candidates = [Path(override)] if override else installed_feature_roots('brain_lesions')
    if not is_frozen() and not override:
        # Source service exports keep the package layout but omit Git metadata.
        candidates.append(Path(__file__).resolve().parents[3] / 'generated-files/eagle-eye/brain-lesions')
    for root in candidates:
        if (root / 'manifest.json').is_file():
            return root.resolve()
    raise BrainError('The Eagle Eye MS lesion model is not installed. Install the Eagle Eye lesion package.')


def validate_lesion_bundle(root):
    from .runtime import sha256
    root = Path(root).resolve()
    try:
        data = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        required = {'python/python.exe', 'python/Lib/site-packages/lst_ai/segment.py',
                    'python/Scripts/lst', 'data/atlas/sub-mni152_space-mni_t1.nii.gz',
                    'runner.py', 'data/model/UNet3D_MS_final_mdlA.pt',
                    'data/model/UNet3D_MS_final_mdlB.pt', 'data/model/UNet3D_MS_final_mdlC.pt'}
        required.update(f'python/Lib/site-packages/brainles_hd_bet/model_weights/{i}.model' for i in range(5))
        if data['version'] != LST_VERSION or data['format_version'] != 1 or not required.issubset(data['sha256']):
            raise ValueError
        for name, digest in data['sha256'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or sha256(path) != digest:
                raise ValueError
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise BrainError('The MS lesion package is incomplete or changed. Reinstall the verified Eagle Eye package.') from None


def measure_mask(flair, mask):
    """Count all positive components using 26-connectivity; no hidden size filter."""
    import SimpleITK as sitk
    if (mask.GetDimension() != 3 or mask.GetSize() != flair.GetSize()
            or mask.GetNumberOfComponentsPerPixel() != 1
            or any(not np.allclose(a, b, atol=1e-5, rtol=0) for a, b in
                   ((mask.GetSpacing(), flair.GetSpacing()), (mask.GetOrigin(), flair.GetOrigin()),
                    (mask.GetDirection(), flair.GetDirection())))):
        raise BrainError('Lesion mask does not match native FLAIR geometry; no measurements were published.')
    values = sitk.GetArrayFromImage(mask)
    if not np.isfinite(values).all() or not np.isin(values, [0, 1]).all():
        raise BrainError('The lesion mask is not a finite binary segmentation.')
    components = sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.Cast(mask > 0, sitk.sitkUInt8), True))
    voxel_mm3 = float(np.prod(flair.GetSpacing()))
    sizes = np.bincount(components.ravel())[1:]
    return {'candidate_count': len(sizes), 'voxel_volume_mm3': voxel_mm3,
            'total_volume_mm3': int(np.count_nonzero(values)) * voxel_mm3,
            'total_volume_cm3': int(np.count_nonzero(values)) * voxel_mm3 / 1000,
            'connectivity': 26, 'minimum_component_volume_mm3': 0,
            'components_mm3': sorted((float(n * voxel_mm3) for n in sizes), reverse=True)}


def run_lesions(t1_source, flair_source, *, study_uid, t1_uid, flair_uid, root,
                cancel=None, progress=None, demographics=None, primary_disease='other', clinical_note='', fazekas_overall=None,
                acquisition_mode='3d'):
    if acquisition_mode not in ('3d', '2d'):
        raise BrainError('Select 2D or 3D acquisition mode.')
    from ..eagle_eye_remote.settings import remote_required
    if remote_required():
        from ..eagle_eye_remote.routing import lesions
        return lesions(t1_source, flair_source, study_uid, t1_uid, flair_uid, root,
                       cancel=cancel, progress=progress, primary_disease=primary_disease,
                       clinical_note=clinical_note, fazekas_overall=fazekas_overall,
                       **({'acquisition_mode': '2d'} if acquisition_mode == '2d' else {}))
    from .service import _ANALYSIS_LOCK
    if not _ANALYSIS_LOCK.acquire(blocking=False):
        raise BrainError('Another brain analysis is running. Wait for it to finish or cancel it first.')
    try:
        if acquisition_mode == '2d':
            from .lesions_2d import run_2d
            return run_2d(t1_source, flair_source, study_uid=study_uid, t1_uid=t1_uid,
                          flair_uid=flair_uid, root=root, cancel=cancel, progress=progress,
                          demographics=demographics, primary_disease=primary_disease,
                          clinical_note=clinical_note, fazekas_overall=fazekas_overall)
        return _run_lesions(t1_source, flair_source, study_uid=study_uid, t1_uid=t1_uid,
                            flair_uid=flair_uid, root=root, cancel=cancel, progress=progress,
                            demographics=demographics, primary_disease=primary_disease, clinical_note=clinical_note,
                            fazekas_overall=fazekas_overall)
    finally:
        _ANALYSIS_LOCK.release()


def _run_lesions(t1_source, flair_source, *, study_uid, t1_uid, flair_uid, root,
                 cancel=None, progress=None, demographics=None, primary_disease='other', clinical_note='', fazekas_overall=None):
    from .lesion_indication import clinical_context
    indication = clinical_context(primary_disease, clinical_note, fazekas_overall)
    from .images import read_volume
    from .patient_context import dicom_context, require_same_examination, demographics_for_report
    from .study_workflow import patient_output_root
    from .runtime import run_process, sha256
    import SimpleITK as sitk
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    if not flair_source or not study_uid or not t1_uid or not flair_uid or t1_uid == flair_uid:
        raise BrainError('Select distinct T1 and 3D FLAIR series from the current examination.')
    progress('Checking examination identity and MRI inputs')
    context, flair_context = dicom_context(t1_source), dicom_context(flair_source)
    if (context.get('study_uid') != study_uid or flair_context.get('study_uid') != study_uid
            or context.get('series_uid') != t1_uid or flair_context.get('series_uid') != flair_uid):
        raise BrainError('The selected T1/FLAIR series no longer match this examination.')
    require_same_examination(context, flair_context)
    progress('Checking the local MS lesion model')
    bundle = lesion_bundle()
    manifest = validate_lesion_bundle(bundle)
    t1, flair = read_volume(t1_source), read_volume(flair_source, expected_protocol='flair')
    if max(t1.GetSpacing() + flair.GetSpacing()) > 2:
        raise BrainError('This lesion workflow requires full-brain 3D T1 and FLAIR with spacing at most 2 mm.')
    if cancel.is_set():
        raise BrainError('Lesion analysis cancelled.')
    directory = patient_output_root(root, context) / ('lesions-' + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True)
    try:
        sitk.WriteImage(t1, str(directory / 't1.nii.gz'))
        sitk.WriteImage(flair, str(directory / 'flair.nii.gz'))
        progress('Registering T1/FLAIR, extracting brain and segmenting white-matter lesion candidates')
        # Windows CreateProcess and registration tools cannot use the deeply
        # nested patient store as cwd. Keep engine scratch private and short;
        # persist only outputs and diagnostics in the original identity scope.
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory(prefix='ee-lst-') as temporary:
            scratch = Path(temporary)
            for name in ('t1.nii.gz', 'flair.nii.gz'):
                shutil.copyfile(directory / name, scratch / name)
            try:
                run_process([bundle / 'python/python.exe', bundle / 'runner.py', str(scratch)], scratch,
                            cancel, timeout=7200, environment={'LST_AI_DATA_DIR': str(bundle / 'data'),
                                                             'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
                                                             'PYTHONUNBUFFERED': '1'})
                if cancel.is_set():
                    raise BrainError('Lesion analysis cancelled.')
                shutil.copytree(scratch / 'output', directory / 'output')
            finally:
                for name in ('process.log', 'process-diagnostics.jsonl'):
                    if (scratch / name).is_file():
                        shutil.copyfile(scratch / name, directory / name)
        mask_path = directory / 'output/space-flair_seg-lst.nii.gz'
        mask = sitk.ReadImage(str(mask_path))
        metrics = measure_mask(flair, mask)
        demo = demographics_for_report(context, demographics)
        result = {'analysis_type': 'brain_lesions', 'artifact_directory': str(directory),
                  'clinical_context': indication,
                  'patient_context': context, 'age_years': demo.age_years, 'sex': demo.sex,
                  'model': 'LST-AI', 'model_version': manifest['version'], 'metrics': metrics,
                  'model_manifest_sha256': sha256(bundle / 'manifest.json'),
                  'flair_series_uid': flair_uid,
                  'input_sha256': {name: sha256(directory / f'{name}.nii.gz') for name in ('t1', 'flair')},
                  'mask_path': str(mask_path), 'review_status': 'Unreviewed lesion candidates',
                  'clinical_qualification': False, 'pdf_available': False}
        if cancel.is_set():
            raise BrainError('Lesion analysis cancelled.')
        progress('Creating lesion burden report and native FLAIR mask previews')
        from .lesion_report import write_lesion_report
        if primary_disease == 'svd':
            from .svd_assessment import enrich_svd
            result['svd_spatial'] = enrich_svd(result, directory, t1_source=t1_source, cancel=cancel, progress=progress)
        from .ms_assessment import enrich_ms
        topography = enrich_ms(result, directory, t1_source=t1_source, cancel=cancel, progress=progress)
        # Anatomical distribution is required for every white-matter report.
        # Diagnostic-criteria interpretation remains specific to clinician-selected MS.
        result['lesion_topography'] = {k: v for k, v in topography.items()
                                      if k not in ('conclusion', 'potential_brain_dis_support', 'diagnosis')}
        if primary_disease == 'ms':
            result['ms_topography'] = topography
        write_lesion_report(result, flair, mask, directory)
        if cancel.is_set():
            raise BrainError('Lesion analysis cancelled; partial files remain marked incomplete.')
        result['pdf_available'] = True
        (directory / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
        return result
    except Exception:
        (directory / 'FAILED').write_text('Incomplete lesion analysis. Do not release partial outputs.', encoding='utf-8')
        raise
