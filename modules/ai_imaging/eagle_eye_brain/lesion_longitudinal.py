"""Worker-only, review-required longitudinal lesion comparison."""
import json
from datetime import datetime
from pathlib import Path
import threading
import uuid

import numpy as np
from .contracts import BrainError


def load_patient_examinations(study_uid):
    """Read only studies linked by the local patient foreign key; never name-match."""
    import sqlite3
    from PacsClient.utils import data_paths
    from .study_workflow import load_study_series
    with sqlite3.connect(Path(data_paths.DATABASE_FILE).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT study_uid, study_date FROM studies WHERE patient_fk = '
                            '(SELECT patient_fk FROM studies WHERE study_uid = ?) ORDER BY study_date',
                            (study_uid,)).fetchall()
    return [dict(study_uid=uid, date=date or '', series=load_study_series(uid)) for uid, date in rows]


def validate_pair(previous, current):
    """Require positive identity and chronology, not same-name or reported-age matching."""
    for key in ('patient_id', 'birth_date'):
        if not previous.get(key) or previous.get(key) != current.get(key):
            raise BrainError('Comparison requires matching DICOM patient ID and birth date.')
    if previous.get('sex') and current.get('sex') and previous['sex'] != current['sex']:
        raise BrainError('The DICOM patient details conflict between examinations.')
    if not previous.get('study_uid') or not current.get('study_uid') or previous['study_uid'] == current['study_uid']:
        raise BrainError('Select two distinct MRI examinations.')
    try:
        dates = [datetime.strptime(c['study_date'], '%Y%m%d') for c in (previous, current)]
    except (KeyError, ValueError, TypeError):
        raise BrainError('Both examinations require valid DICOM study dates.') from None
    if dates[0] >= dates[1]:
        raise BrainError('The previous MRI must precede the current MRI in DICOM study date.')
    return (dates[1] - dates[0]).days


def compare_masks(previous, current, tolerance_mm=1.0):
    """Spatial candidates, not adjudicated disease activity; masks share physical grid."""
    import SimpleITK as sitk
    from .lesions import measure_mask
    measure_mask(current, previous)
    measure_mask(current, current)
    old = sitk.GetArrayFromImage(previous) > 0
    new = sitk.GetArrayFromImage(current) > 0
    a = sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.Cast(previous > 0, sitk.sitkUInt8), True))
    b = sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.Cast(current > 0, sitk.sitkUInt8), True))
    na, nb = int(a.max()), int(b.max())
    voxel = float(np.prod(current.GetSpacing()))
    distance = (sitk.GetArrayFromImage(sitk.SignedMaurerDistanceMap(sitk.Cast(previous > 0, sitk.sitkUInt8),
                insideIsPositive=False, squaredDistance=False, useImageSpacing=True))
                if old.any() else np.full(old.shape, np.inf))
    expanded = distance <= tolerance_mm
    rows = []
    for i in range(1, nb + 1):
        mask = b == i
        matches = np.unique(a[mask]); matches = matches[matches > 0]
        if not matches.size:
            status = 'Possible new' if not np.any(expanded[mask]) else 'Boundary / registration ambiguity'
            prior_volume = None
        elif len(matches) > 1 or any(len(np.unique(b[a == k][b[a == k] > 0])) > 1 for k in matches):
            status, prior_volume = 'Merge / split: review', None
        else:
            prior_volume = float(np.count_nonzero(a == matches[0]) * voxel)
            grows = np.count_nonzero(mask) * voxel > prior_volume and np.any(~expanded[mask])
            status = 'Possible enlargement' if grows else 'Matched: review'
        rows.append({'current_component': i, 'status': status,
                     'previous_components': [int(k) for k in matches],
                     'current_mm3': float(np.count_nonzero(mask) * voxel),
                     'previous_registered_mm3': prior_volume})
    return {'rows': rows, 'possible_new': sum(r['status'] == 'Possible new' for r in rows),
            'possible_enlarged': sum(r['status'] == 'Possible enlargement' for r in rows),
            'unmatched_previous': sum(not np.any(new[a == i]) for i in range(1, na + 1)),
            'boundary_tolerance_mm': tolerance_mm,
            'qualification': 'Experimental spatial candidates; registration and lesion review required'}


def register_previous(previous, current, cancel):
    import SimpleITK as sitk
    fixed, moving = sitk.Cast(current, sitk.sitkFloat32), sitk.Cast(previous, sitk.sitkFloat32)
    registration = sitk.ImageRegistrationMethod()
    registration.SetNumberOfThreads(2)
    registration.SetMetricAsMattesMutualInformation(50)
    registration.SetMetricSamplingStrategy(registration.RANDOM)
    registration.SetMetricSamplingPercentage(0.15, 121212)
    registration.SetInterpolator(sitk.sitkLinear)
    registration.SetOptimizerAsRegularStepGradientDescent(1.0, 0.001, 200)
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetShrinkFactorsPerLevel([4, 2, 1])
    registration.SetSmoothingSigmasPerLevel([2, 1, 0])
    registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    initial = sitk.CenteredTransformInitializer(fixed, moving, sitk.Euler3DTransform(),
                                               sitk.CenteredTransformInitializerFilter.GEOMETRY)
    registration.SetInitialTransform(initial, inPlace=False)
    registration.AddCommand(sitk.sitkIterationEvent,
                            lambda: registration.StopRegistration() if cancel.is_set() else None)
    if cancel.is_set():
        raise BrainError('MS comparison cancelled.')
    transform = registration.Execute(fixed, moving)
    if cancel.is_set() or not np.isfinite(registration.GetMetricValue()):
        raise BrainError('MS comparison cancelled or registration did not produce a finite result.')
    return transform


def run_comparison(previous, current, *, root, cancel=None, progress=None, clinical_note=''):
    """Each selection supplies T1 + FLAIR from one examination; lock spans both jobs."""
    from ..eagle_eye_remote.settings import remote_required
    if remote_required():
        raise BrainError('Server comparison of two examinations is not available in the initial single-study workflow.')
    from .patient_context import dicom_context, require_same_examination
    from .lesions import _run_lesions
    from .service import _ANALYSIS_LOCK
    cancel, progress = cancel or threading.Event(), progress or (lambda text: None)
    contexts = []
    for selection in (previous, current):
        context = dicom_context(selection['t1']['path'])
        flair = dicom_context(selection['flair']['path'])
        require_same_examination(context, flair)
        if context.get('study_uid') != selection['study_uid'] or flair.get('study_uid') != selection['study_uid']:
            raise BrainError('Selected comparison series do not match their examinations.')
        contexts.append(context)
    days = validate_pair(*contexts)
    if not _ANALYSIS_LOCK.acquire(blocking=False):
        raise BrainError('Another brain analysis is running.')
    try:
        results = []
        for index, selection in enumerate((previous, current), 1):
            if cancel.is_set():
                raise BrainError('MS comparison cancelled.')
            results.append(_run_lesions(selection['t1']['path'], selection['flair']['path'],
                study_uid=selection['study_uid'], t1_uid=selection['t1']['series_uid'],
                flair_uid=selection['flair']['series_uid'], root=root, cancel=cancel,
                progress=lambda text, i=index: progress(f'Examination {i}/2: {text}'),
                primary_disease='ms', clinical_note=clinical_note))
        return compare_results(*results, days=days, cancel=cancel, progress=progress)
    finally:
        _ANALYSIS_LOCK.release()


def compare_results(previous, current, *, days=None, cancel=None, progress=None):
    import SimpleITK as sitk
    from .lesions import measure_mask
    from .lesion_report import write_lesion_report
    days = validate_pair(previous['patient_context'], current['patient_context'])
    if any(r.get('clinical_context', {}).get('primary_disease') != 'ms' for r in (previous, current)):
        raise BrainError('MS comparison requires clinician-selected MS context for both examinations.')
    if previous.get('model_manifest_sha256') != current.get('model_manifest_sha256') or not current.get('model_manifest_sha256'):
        raise BrainError('Both MRI analyses must use the same verified lesion model.')
    cancel, progress = cancel or threading.Event(), progress or (lambda text: None)
    old_root, new_root = [Path(r['artifact_directory']) for r in (previous, current)]
    old, new = [sitk.ReadImage(str(p / 'flair.nii.gz')) for p in (old_root, new_root)]
    old_mask, new_mask = [sitk.ReadImage(r['mask_path']) for r in (previous, current)]
    old_metrics, new_metrics = measure_mask(old, old_mask), measure_mask(new, new_mask)
    progress('Aligning previous FLAIR to current FLAIR for candidate-change review')
    transform = register_previous(old, new, cancel)
    mapped = sitk.Resample(old_mask, new, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    coverage = sitk.Image(old.GetSize(), sitk.sitkUInt8) + 1
    coverage.CopyInformation(old)
    coverage = sitk.Resample(coverage, new, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    if np.any((sitk.GetArrayFromImage(new_mask) > 0) & (sitk.GetArrayFromImage(coverage) == 0)):
        raise BrainError('Current lesions extend outside previous image coverage; no comparison report was published.')
    reverse_coverage = sitk.Image(new.GetSize(), sitk.sitkUInt8) + 1
    reverse_coverage.CopyInformation(new)
    reverse_coverage = sitk.Resample(reverse_coverage, old, transform.GetInverse(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    if np.any((sitk.GetArrayFromImage(old_mask) > 0) & (sitk.GetArrayFromImage(reverse_coverage) == 0)):
        raise BrainError('Previous lesions extend outside current image coverage; no comparison report was published.')
    comparison = compare_masks(mapped, new_mask)
    comparison.update(previous_date=previous['patient_context']['study_date'],
                      current_date=current['patient_context']['study_date'], interval_days=days,
                      previous_volume_cm3=old_metrics['total_volume_cm3'],
                      current_volume_cm3=new_metrics['total_volume_cm3'])
    baseline = comparison['previous_volume_cm3']
    delta = comparison['current_volume_cm3'] - baseline
    comparison.update(volume_change_cm3=delta, volume_change_percent=100 * delta / baseline if baseline else None)
    directory = new_root / ('comparison-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    try:
        sitk.WriteTransform(transform, str(directory / 'previous-to-current-resampling.tfm'))
        sitk.WriteImage(mapped, str(directory / 'previous-mask-in-current.nii.gz'))
        sitk.WriteImage(sitk.Resample(old, new, transform, sitk.sitkLinear, 0, sitk.sitkFloat32),
                        str(directory / 'previous-flair-in-current.nii.gz'))
        result = dict(current, artifact_directory=str(directory), longitudinal=comparison,
                      previous_result=str(old_root / 'result.json'), current_result=str(new_root / 'result.json'),
                      metrics=new_metrics, pdf_available=False)
        if cancel.is_set():
            raise BrainError('MS comparison cancelled.')
        progress('Creating MS comparison PDF')
        write_lesion_report(result, new, new_mask, directory)
        if cancel.is_set():
            raise BrainError('MS comparison cancelled.')
        result['pdf_available'] = True
        (directory / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
        return result
    except Exception:
        (directory / 'FAILED').write_text('Incomplete comparison; do not release.', encoding='utf-8')
        raise


def comparison_pages(result):
    from html import escape
    c = result.get('longitudinal')
    if not c:
        return []
    fields = [('Previous MRI (DICOM date)', c['previous_date']), ('Current MRI (DICOM date)', c['current_date']),
              ('Interval (days)', c['interval_days']), ('Previous native volume (cm3)', f"{c['previous_volume_cm3']:.3f}"),
              ('Current native volume (cm3)', f"{c['current_volume_cm3']:.3f}"),
              ('Volume change (cm3)', f"{c['volume_change_cm3']:+.3f}"),
              ('Volume change (%)', 'Not defined: zero baseline' if c['volume_change_percent'] is None else f"{c['volume_change_percent']:+.1f}"),
              ('Possible new candidates', c['possible_new']), ('Possible enlarged candidates', c['possible_enlarged']),
              ('Previous components without overlap (review)', c['unmatched_previous'])]
    table = '<table width="100%"><tr><th>Comparison</th><th>Value</th></tr>'
    table += ''.join(f'<tr><td align="left">{escape(k)}</td><td align="center">{escape(str(v))}</td></tr>' for k,v in fields) + '</table>'
    pages = ['<h1>MS longitudinal comparison</h1>' + table +
             '<p><b>Experimental change candidates; not confirmed MS activity.</b> Review registration, '
             'masks and acquisition differences. Native volumes are measured separately; component matching '
             'uses the resampled previous mask. A 1 mm boundary tolerance is a technical heuristic, '
             'not a validated clinical growth threshold. Merge/split and unmatched components need review. '
             'Enhancement is not assessed.</p>'
             '<p>Reference: Wattjes et al., 2021 MAGNIMS-CMSC-NAIMS MRI consensus. '
             'https://doi.org/10.1016/S1474-4422(21)00095-8. This consensus does not validate this algorithm.</p>']
    for start in range(0, len(c['rows']), 15):
        table = '<h1>Spatial candidate matching</h1><table width="100%"><tr><th>Current ID</th><th>Status</th><th>Current mm3</th><th>Prior registered mm3</th></tr>'
        for r in c['rows'][start:start+15]:
            prior = '-' if r['previous_registered_mm3'] is None else f"{r['previous_registered_mm3']:.1f}"
            table += f'<tr><td align="center">{r["current_component"]}</td><td align="left">{escape(r["status"])}</td><td align="center">{r["current_mm3"]:.1f}</td><td align="center">{prior}</td></tr>'
        pages.append(table + '</table><p>IDs refer to current 26-connected mask components; not anatomical labels.</p>')
    return pages
