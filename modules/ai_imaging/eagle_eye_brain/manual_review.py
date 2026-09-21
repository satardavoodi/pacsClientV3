"""Worker-only, isolated manual segmentation sessions; never overwrite inference."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from .contracts import BrainError


def prepare_review(result):
    from .runtime import slicer_executable, sha256
    executable = slicer_executable()
    lesion = result.get('analysis_type') == 'brain_lesions'
    source = Path(result['mask_path']) if lesion else Path(result['artifact_directory']) / 'labels.nii.gz'
    image_name = 'flair.nii.gz' if lesion else 'resampled.nii.gz'
    roots = [Path(result['artifact_directory']), *source.parents]
    root = next((p for p in roots if (p / image_name).is_file() and source.is_file()), None)
    if root is None:
        raise BrainError('Original image and segmentation are required for manual correction.')
    directory = root / 'manual-reviews' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    shutil.copy2(root / image_name, directory / 'image.nii.gz')
    shutil.copy2(source, directory / 'original.nii.gz')
    manifest = dict(source_result=result, source_mask=str(source), source_sha256=sha256(source),
                    lesion=lesion, directory=str(directory))
    if not lesion:
        manifest['label_names'] = json.loads((root / 'label_names.json').read_text(encoding='utf-8'))
    (directory / 'session.json').write_text(json.dumps(manifest, allow_nan=False), encoding='utf-8')
    env = os.environ.copy(); env['AIPACS_MANUAL_REVIEW'] = str(directory)
    subprocess.Popen([str(executable), '--no-splash', '--ignore-slicerrc', '--disable-settings',
                      '--python-script', str(Path(__file__).with_name('manual_slicer.py'))], env=env)
    return str(directory)


def validate_edit(original, edited):
    import numpy as np
    import SimpleITK as sitk
    if (original.GetDimension() != 3 or edited.GetDimension() != 3
            or original.GetSize() != edited.GetSize()
            or edited.GetNumberOfComponentsPerPixel() != 1
            or any(not np.allclose(getattr(original, k)(), getattr(edited, k)(), atol=1e-5, rtol=0)
                   for k in ('GetSpacing', 'GetOrigin', 'GetDirection'))):
        raise BrainError('Corrected segmentation geometry does not match the original examination.')
    before, after = sitk.GetArrayFromImage(original), sitk.GetArrayFromImage(edited)
    if not np.isfinite(after).all() or not np.isin(after, np.append(np.unique(before), 0)).all():
        raise BrainError('Corrected segmentation contains unsupported labels.')


def recalculate_review(session, *, cancel=None, progress=None):
    from .service import _ANALYSIS_LOCK
    if not _ANALYSIS_LOCK.acquire(blocking=False):
        raise BrainError('Another brain analysis is running. Wait for it to finish before recalculating.')
    try:
        return _recalculate_review(session, cancel=cancel, progress=progress)
    finally:
        _ANALYSIS_LOCK.release()


def _recalculate_review(session, *, cancel=None, progress=None):
    import SimpleITK as sitk
    from .runtime import sha256
    directory = Path(session)
    if cancel is not None and cancel.is_set():
        raise BrainError('Manual recalculation cancelled.')
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    edited_path = directory / 'corrected.nii.gz'
    if not edited_path.is_file():
        raise BrainError('In Slicer, click Save correction for AI-PACS before recalculating.')
    if sha256(manifest['source_mask']) != manifest['source_sha256']:
        raise BrainError('Original segmentation changed. Start a new review session.')
    original, edited = sitk.ReadImage(str(directory / 'original.nii.gz')), sitk.ReadImage(str(edited_path))
    validate_edit(original, edited)
    if not manifest['lesion']:
        return brain_revision(directory, manifest, original, edited)
    from .lesions import measure_mask
    from .lesion_report import write_lesion_report
    result = manifest['source_result']
    if result.get('longitudinal'):
        raise BrainError('Re-run longitudinal comparison after correcting an individual examination.')
    out = directory / ('revision-' + uuid.uuid4().hex[:12]); out.mkdir()
    sitk.WriteImage(edited, str(out / 'corrected.nii.gz'))
    result.update(mask_path=str(out / 'corrected.nii.gz'), artifact_directory=str(out),
                  manual_correction={'source_mask_sha256': manifest['source_sha256'],
                                     'corrected_mask_sha256': sha256(out / 'corrected.nii.gz')},
                  pdf_available=False)
    image = sitk.ReadImage(str(directory / 'image.nii.gz'))
    result['metrics'] = measure_mask(image, edited)
    for key in ('svd_spatial', 'ms_topography', 'wmh_reference'):
        result.pop(key, None)
    root = next(p for p in Path(manifest['source_mask']).parents if (p / 'flair.nii.gz').is_file())
    indication = result.get('clinical_context', {}).get('primary_disease')
    if indication == 'svd':
        from .svd_assessment import enrich_svd
        result['svd_spatial'] = enrich_svd(result, root, cancel=cancel, progress=progress)
    elif indication == 'ms':
        from .ms_assessment import enrich_ms
        result['ms_topography'] = enrich_ms(result, root, cancel=cancel, progress=progress)
    if cancel is not None and cancel.is_set():
        raise BrainError('Manual recalculation cancelled.')
    write_lesion_report(result, image, edited, out)
    result['pdf_available'] = True
    (out / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    return result


def brain_revision(directory, manifest, original, edited):
    """A separately identified binary-label measurement addendum, not posterior inference."""
    import numpy as np
    import SimpleITK as sitk
    from html import escape
    from .organized_report import PAGE, _table, write_paged_pdf
    from .volbrain_reference import range_text, scientific_reference_page
    from .runtime import sha256
    result = manifest['source_result']
    before, after = sitk.GetArrayFromImage(original), sitk.GetArrayFromImage(edited)
    voxel_ml = abs(float(np.linalg.det(np.array(edited.GetDirection()).reshape(3, 3)))) * float(np.prod(edited.GetSpacing())) / 1000
    original_counts = dict(zip(*np.unique(before, return_counts=True)))
    corrected_counts = dict(zip(*np.unique(after, return_counts=True)))
    rows = []
    for label in sorted(int(x) for x in original_counts if x):
        old, new = original_counts[label] * voxel_ml, corrected_counts.get(label, 0) * voxel_ml
        rows.append(dict(label=label, structure=manifest['label_names'][str(label)],
                         before_cm3=float(old), volume_cm3=float(new), volume_mm3=float(new * 1000),
                         method='Manually corrected binary labelmap'))
    out = directory / ('revision-' + uuid.uuid4().hex[:12]); out.mkdir()
    sitk.WriteImage(edited, str(out / 'corrected.nii.gz'))
    context = result.get('patient_context', {})
    identity = ' | '.join(str(context.get(k) or 'Not supplied') for k in ('patient_name', 'patient_id', 'study_date'))
    intro = ('<h1>Manual brain segmentation measurement addendum</h1><p>' + escape(identity) + '</p>'
             '<p>Volumes below are voxel-count measurements before and after manual boundary editing. '
             'They do not replace or relabel SynthSeg posterior estimates. Original inference is retained. '
             'Reference intervals, when available, retain the original examination age, sex and ICV; '
             'cross-method qualification remains pending. No exact scores or automated diagnosis.</p>')
    pages = []
    for start in range(0, len(rows), 16):
        table = [[r['structure'], f'{r["before_cm3"]:.3f}', f'{r["volume_cm3"]:.3f}',
                  f'{r["volume_cm3"]-r["before_cm3"]:+.3f}', range_text(result.get('normative', {}), r['structure'])]
                 for r in rows[start:start + 16]]
        pages.append(intro + _table(['Region', 'Before cm3', 'Corrected cm3', 'Change cm3', 'Reference cm3'],
                                   table, [32, 15, 16, 15, 22]))
    pages.append(scientific_reference_page())
    html = ('<html><head><meta name="brain-patient" content="' + escape(identity, quote=True) + '">'
            '<style>body,p,td,th,h1,h2{color:#223344}body{font-family:Arial;font-size:9pt;background:white}h1{font-size:16pt}th{background:#dfeaf0} '
            'td{border-bottom:1px solid #dddddd}</style></head><body>' + PAGE.join(pages) + '</body></html>')
    write_paged_pdf(html, out / 'report.pdf', title='AI-PACS | Manual brain measurement addendum | Review required')
    result.update(artifact_directory=str(out), manual_rows=rows, pdf_available=True,
                  manual_correction={'source_mask_sha256': manifest['source_sha256'],
                                     'corrected_mask_sha256': sha256(out / 'corrected.nii.gz')})
    (out / 'report.html').write_text(html, encoding='utf-8')
    (out / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    return result
