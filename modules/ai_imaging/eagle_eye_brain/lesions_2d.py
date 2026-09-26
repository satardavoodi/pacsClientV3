"""Worker-only native-slice MindGlide route; never a 3D LST fallback."""
import json
import threading
import uuid
from pathlib import Path

import numpy as np

from .contracts import BrainError

MODEL_SHA256 = '881e30efd9444a25ee70c01d795dd9fb21ac750a48f1ba8070fcd79fb75e76ca'
REFERENCE = 'https://doi.org/10.1038/s41467-025-58274-8'


def filesystem_path(path):
    """Extended Windows paths for Python I/O; keep native libraries in short scratch paths."""
    import os
    value = str(Path(path).absolute())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def publish_artifacts(source, destination):
    import shutil
    target = filesystem_path(destination)
    target.mkdir(parents=True, exist_ok=True)
    # Publish the success descriptor last. Partial directories have no result.json.
    for path in sorted(Path(source).iterdir(), key=lambda p: p.name == 'result.json'):
        if path.is_file():
            shutil.copyfile(path, target / path.name)


def measure_slices(image, mask, *, thickness_mm):
    """Report sampled slabs separately from gap-filled grid estimates."""
    import SimpleITK as sitk
    from .lesions import measure_mask
    m = measure_mask(image, mask)
    step = float(image.GetSpacing()[2])
    if (not isinstance(thickness_mm, (int, float)) or not np.isfinite(thickness_mm)
            or thickness_mm <= 0 or thickness_mm > step + .01):
        raise BrainError('2D measurement requires known, positive, non-overlapping slice thickness.')
    thickness_mm = min(float(thickness_mm), step)
    ratio = thickness_mm / step
    m['grid_estimate_volume_mm3'] = m['total_volume_mm3']
    m['grid_estimate_volume_cm3'] = m['total_volume_cm3']
    m['total_volume_mm3'] *= ratio
    m['total_volume_cm3'] *= ratio
    m['components_mm3'] = [v * ratio for v in m['components_mm3']]
    m['sampled_slab_voxel_mm3'] = m['voxel_volume_mm3'] * ratio
    m['slice_candidate_count'] = sum(int(sitk.GetArrayFromImage(sitk.ConnectedComponent(
        sitk.GetImageFromArray((s > 0).astype(np.uint8)), True)).max())
        for s in sitk.GetArrayFromImage(mask))
    m.update(volume_basis='sampled_slabs', slice_thickness_mm=thickness_mm,
             slice_step_mm=step, slice_gap_mm=max(0., step - thickness_mm),
             unique_lesion_count_confirmed=False)
    return m


def slice_geometry(source):
    """DICOM slice thickness cannot be inferred from NIfTI centre spacing."""
    import SimpleITK as sitk
    import pydicom
    source = Path(source)
    if not source.is_dir():
        raise BrainError('Select the original 2D FLAIR DICOM series so slice thickness and gaps can be verified.')
    ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(source))
    if len(ids or ()) != 1:
        raise BrainError('Select exactly one 2D FLAIR series.')
    values = []
    for path in sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(source), ids[0]):
        ds = pydicom.dcmread(path, stop_before_pixels=True, specific_tags=['SliceThickness', 'MRAcquisitionType'])
        if str(getattr(ds, 'MRAcquisitionType', '')).upper() != '2D':
            raise BrainError('2D mode requires DICOM-confirmed 2D FLAIR; choose 3D mode for 3D acquisitions.')
        try:
            values.append(float(ds.SliceThickness))
        except (AttributeError, TypeError, ValueError):
            raise BrainError('DICOM slice thickness is missing; sampled-slab volume cannot be calculated.') from None
    if not values or not np.isfinite(values).all() or min(values) <= 0 or not np.allclose(values, values[0], atol=.01, rtol=0):
        raise BrainError('2D slice thickness is invalid or inconsistent.')
    return values[0]


def validate_engine(bundle, *, cancel=None):
    from .runtime import sha256
    root = Path(bundle) / 'mindglide'
    try:
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if (manifest['version'] != '1.3.0' or manifest['model_sha256'] != MODEL_SHA256
                or manifest['sha256'].get('model.pt') != MODEL_SHA256
                or not {'runner.py', 'site-packages-v1/mindglide/infer.py', 'site-packages-v1/monai/__init__.py'} <= manifest['sha256'].keys()):
            raise ValueError
        for name, digest in manifest['sha256'].items():
            if cancel is not None and cancel.is_set():
                raise BrainError('2D lesion analysis cancelled.')
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
                raise ValueError
        if sha256(Path(bundle) / 'python/python.exe') != manifest['python_sha256']:
            raise ValueError
        shared = manifest['shared_sha256']
        if not {'python/python.exe', 'python/python310.dll', 'python/python310.zip',
                'python/Lib/site-packages/torch/__init__.py', 'python/Lib/site-packages/numpy/__init__.py'} <= shared.keys():
            raise ValueError
        for name, digest in shared.items():
            if cancel is not None and cancel.is_set():
                raise BrainError('2D lesion analysis cancelled.')
            path = (Path(bundle) / name).resolve()
            if not path.is_relative_to(Path(bundle).resolve()) or sha256(path) != digest:
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise BrainError('The separate 2D MindGlide engine is missing or changed. Install its verified server bundle.') from None
    return root, manifest


def spatial_status():
    # A 20-class joint segmentation is not a lesion-independent anatomical atlas.
    # Do not turn proximity to its labels into confirmed McDonald locations.
    return {'status': 'requires_native_image_review', 'method': '2d_native_slices',
            'regions': {key: {'candidate_count': None, 'volume_cm3': None,
                              'status': 'Not qualified for this 2D backend'} for key in
                        ('periventricular', 'juxtacortical', 'corpus_callosum',
                         'supratentorial', 'infratentorial')},
            'diagnostic_criteria_evaluable': False}


def run_2d(t1_source, flair_source, *, study_uid, t1_uid, flair_uid, root,
           cancel=None, progress=None, demographics=None, primary_disease='other', clinical_note='', fazekas_overall=None):
    import shutil
    import tempfile
    import SimpleITK as sitk
    from .images import read_volume
    from .lesions import lesion_bundle, measure_mask
    from .patient_context import dicom_context, require_same_examination, demographics_for_report
    from .study_workflow import patient_output_root
    from .lesion_indication import clinical_context
    from .runtime import run_process, sha256
    cancel = cancel or threading.Event()
    progress = progress or (lambda _: None)
    indication = clinical_context(primary_disease, clinical_note, fazekas_overall)
    progress('Checking 2D examination identity, slice thickness and spacing')
    context, fc = dicom_context(t1_source), dicom_context(flair_source)
    if (not study_uid or t1_uid == flair_uid or context.get('study_uid') != study_uid
            or fc.get('study_uid') != study_uid or context.get('series_uid') != t1_uid
            or fc.get('series_uid') != flair_uid):
        raise BrainError('Selected 2D T1/FLAIR identities do not match this examination.')
    require_same_examination(context, fc)
    thickness = slice_geometry(flair_source)
    flair = read_volume(flair_source, expected_protocol='flair', allow_2d=True)
    # Validate the accompanying T1 role; it is not a model channel or registered atlas.
    read_volume(t1_source, allow_2d=True)
    if max(flair.GetSpacing()[:2]) > 2 or flair.GetSpacing()[2] > 8 or thickness > 8:
        raise BrainError('This 2D pilot supports in-plane spacing up to 2 mm and slice step/thickness up to 8 mm.')
    empty = sitk.Image(flair.GetSize(), sitk.sitkUInt8); empty.CopyInformation(flair)
    measure_slices(flair, empty, thickness_mm=thickness)
    if cancel.is_set():
        raise BrainError('2D lesion analysis cancelled.')
    progress('Verifying the separate offline 2D engine and shared runtime')
    bundle = lesion_bundle()
    engine, manifest = validate_engine(bundle, cancel=cancel)
    destination = patient_output_root(root, context) / ('lesions-2d-' + uuid.uuid4().hex[:12])
    workspace = tempfile.TemporaryDirectory(prefix='ee-2d-result-')
    directory = Path(workspace.name)
    try:
        sitk.WriteImage(flair, str(directory / 'flair.nii.gz'))
        progress('MindGlide: segmenting 2D FLAIR; CPU processing may take several minutes')
        with tempfile.TemporaryDirectory(prefix='ee-2d-') as temporary:
            scratch = Path(temporary)
            shutil.copyfile(directory / 'flair.nii.gz', scratch / 'flair.nii.gz')
            try:
                run_process([bundle / 'python/python.exe', engine / 'runner.py', scratch], scratch, cancel,
                            timeout=3600, environment={'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
                                                      'HF_HUB_OFFLINE': '1', 'PYTHONUNBUFFERED': '1'})
                shutil.copyfile(scratch / 'anatomy.nii.gz', directory / 'anatomy.nii.gz')
            finally:
                for name in ('process.log', 'process-diagnostics.jsonl'):
                    if (scratch / name).is_file():
                        shutil.copyfile(scratch / name, directory / name)
        anatomy = sitk.ReadImage(str(directory / 'anatomy.nii.gz'))
        a = sitk.GetArrayFromImage(anatomy)
        if not np.isfinite(a).all() or not np.isin(a, np.arange(20)).all():
            raise BrainError('MindGlide returned invalid anatomical labels.')
        mask = sitk.Cast(anatomy == 18, sitk.sitkUInt8)
        measure_mask(flair, mask)  # Requires exact native grid, no silent resampling.
        raw_mask = mask
        from .periventricular_band_filter import separate_bands
        progress('Reviewing smooth periventricular bands; preserving original candidates')
        mask, band_mask, band_audit = separate_bands(raw_mask, anatomy, context=primary_disease, cancel=cancel)
        band_audit['raw_metrics'] = measure_slices(flair, raw_mask, thickness_mm=thickness)
        band_audit['separated_metrics'] = measure_slices(flair, band_mask, thickness_mm=thickness)
        sitk.WriteImage(raw_mask, str(directory / 'labels-raw.nii.gz'))
        sitk.WriteImage(band_mask, str(directory / 'labels-band-review.nii.gz'))
        mask_path = directory / 'labels.nii.gz'
        sitk.WriteImage(mask, str(mask_path))
        demo = demographics_for_report(context, demographics)
        result = dict(analysis_type='brain_lesions', acquisition_mode='2d', artifact_directory=str(directory),
                      clinical_context=indication, patient_context=context, age_years=demo.age_years, sex=demo.sex,
                      model='MindGlide', model_version=manifest['version'], model_manifest_sha256=sha256(engine / 'manifest.json'),
                      flair_series_uid=flair_uid, mask_path=str(mask_path),
                      input_sha256={'flair': sha256(directory / 'flair.nii.gz')},
                      review_status='Unreviewed 2D candidates', clinical_qualification=False, pdf_available=False,
                      metrics=measure_slices(flair, mask, thickness_mm=thickness), lesion_topography=spatial_status(),
                      band_filter=band_audit, raw_mask_path=str(directory / 'labels-raw.nii.gz'),
                      band_mask_path=str(directory / 'labels-band-review.nii.gz'),
                      reference=REFERENCE, normative_status='No matched 2D age/sex reference applied')
        progress('Preparing 2D measurements, native-slice previews and report')
        if cancel.is_set():
            raise BrainError('2D lesion analysis cancelled.')
        from .lesion_report import write_lesion_report
        write_lesion_report(result, flair, mask, directory)
        if cancel.is_set():
            raise BrainError('2D lesion analysis cancelled.')
        result['pdf_available'] = True
        result['artifact_directory'] = str(destination)
        result['mask_path'] = str(destination / 'labels.nii.gz')
        result['raw_mask_path'] = str(destination / 'labels-raw.nii.gz')
        result['band_mask_path'] = str(destination / 'labels-band-review.nii.gz')
        (directory / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
        publish_artifacts(directory, destination)
        return result
    except Exception:
        (directory / 'FAILED').write_text('Incomplete 2D analysis. Do not release partial outputs.', encoding='utf-8')
        (directory / 'result.json').unlink(missing_ok=True)
        publish_artifacts(directory, destination)
        raise
    finally:
        workspace.cleanup()
