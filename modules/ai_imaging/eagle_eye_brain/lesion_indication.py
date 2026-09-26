"""Clinician-declared context; never an inferred diagnosis or model selector."""
from .contracts import BrainError

INDICATIONS = {
    'ms': 'Multiple sclerosis',
    'svd': 'Small-vessel disease',
    'other': 'Other / undetermined cause',
}


def clinical_context(primary_disease='other', note='', fazekas_overall=None):
    if primary_disease not in INDICATIONS:
        raise BrainError('Select the primary disease / reporting context.')
    note = str(note).strip()
    if len(note) > 500:
        raise BrainError('Clinical context must be at most 500 characters.')
    if fazekas_overall is not None and (type(fazekas_overall) is not int or fazekas_overall not in range(4) or primary_disease != 'svd'):
        raise BrainError('Fazekas must be a clinician-supplied SVD grade from 0 to 3.')
    return {'primary_disease': primary_disease, 'label': INDICATIONS[primary_disease],
            'fazekas_overall': fazekas_overall,
            'note': note, 'source': 'Clinician selected; not inferred from imaging'}


def context_html(result):
    from html import escape
    supplied = result.get('clinical_context')
    if not supplied:
        return '<h2>Clinical context</h2><p>Not recorded in this earlier analysis.</p>'
    context = clinical_context(supplied['primary_disease'], supplied.get('note', ''))
    text = ('<h2>Clinical context supplied by the clinician</h2><p><b>'
            + escape(context['label']) + '</b><br>' + escape(context['note'])
            + '<br>This indication is not an automated diagnosis.</p>')
    if context['primary_disease'] == 'svd':
        from .wmh_reference import reference_status
        reference_note = ('Age/sex percentile: unavailable for this 2D backend.' if result.get('acquisition_mode') == '2d' else
                          'Age/sex reference: approximate graphical band; see the dedicated assessment.'
                          if reference_status(result)['status'] == 'approximate_graphical_band' else
                          'Age/sex percentile: not calculated; see the reference-method explanation.')
        grade = supplied.get('fazekas_overall')
        visual = ('Fazekas: not assessed' if grade is None else
                  f'Fazekas {grade}: {("none", "mild", "moderate", "severe")[grade]} visual WMH burden (clinician-reported).')
        text += ('<h2>Vascular WMH summary</h2><p>' + visual +
                 ' Quantitative burden is shown below; compartment and regional estimates follow when available. '
                 + reference_note + '</p>')
        data = result.get('svd_spatial', {})
        if data.get('compartments'):
            wm = sum(r['volume_mm3'] for r in data['compartments'][:2])
            total = data['total_volume_mm3']
            text += (f'<p><b>Candidates within segmented cerebral white matter: {wm:.1f} mm3.</b> '
                     f'Other compartments and boundary-review candidates: {total-wm:.1f} mm3. '
                     'The total candidate volume is not automatically the total cerebral vascular WMH volume.</p>')
    return text


def regenerate_lesion_report(result_path, primary_disease, note='', *, fazekas_overall=None, spatial=False):
    """Create a new report revision without modifying masks or the original report."""
    import json
    import uuid
    from pathlib import Path
    from datetime import datetime, timezone
    import SimpleITK as sitk
    from .lesions import measure_mask
    from .lesion_report import write_lesion_report
    source = Path(result_path).resolve()
    result = json.loads(source.read_text(encoding='utf-8'))
    if result.get('analysis_type') != 'brain_lesions' or not result.get('pdf_available'):
        raise BrainError('Select a completed lesion analysis.')
    context = clinical_context(primary_disease, note, fazekas_overall)
    flair = sitk.ReadImage(str(source.parent / 'flair.nii.gz'))
    mask = sitk.ReadImage(result['mask_path'])
    metrics = measure_mask(flair, mask)
    two_d = result.get('acquisition_mode') == '2d'
    if two_d:
        from .lesions_2d import measure_slices
        previous_context = result.get('clinical_context', {}).get('primary_disease')
        if result.get('source_band_filter') and primary_disease != previous_context:
            raise BrainError('Re-run analysis before changing the context of a manually revised band-filter result.')
        if result.get('band_filter') and primary_disease != previous_context:
            if primary_disease == 'ms':
                raise BrainError('Re-run 2D analysis for MS context so native band review can be recalculated.')
            raw_path = result.get('raw_mask_path')
            if not raw_path or not Path(raw_path).is_file():
                raise BrainError('The raw 2D mask is required when changing report context. Re-run analysis.')
            mask = sitk.ReadImage(raw_path)
            result.pop('band_filter', None)
            result.pop('raw_mask_path', None)
            result.pop('band_mask_path', None)
        metrics = measure_slices(flair, mask, thickness_mm=result['metrics']['slice_thickness_mm'])
    directory = source.parent / 'reports' / ('revision-' + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True)
    result.update(clinical_context=context, metrics=metrics, artifact_directory=str(directory),
                  source_result=str(source), revised_at=datetime.now(timezone.utc).isoformat(), pdf_available=False)
    if two_d:
        sitk.WriteImage(flair, str(directory / 'flair.nii.gz'))
        sitk.WriteImage(mask, str(directory / 'labels.nii.gz'))
        result['mask_path'] = str(directory / 'labels.nii.gz')
        for key, name in (('raw_mask_path', 'labels-raw.nii.gz'), ('band_mask_path', 'labels-band-review.nii.gz')):
            if result.get(key):
                image = sitk.ReadImage(result[key])
                sitk.WriteImage(image, str(directory / name))
                result[key] = str(directory / name)
    if primary_disease == 'svd' and spatial and not two_d:
        from .svd_assessment import enrich_svd
        result['svd_spatial'] = enrich_svd(result, source.parent)
    elif primary_disease == 'ms' and spatial and not two_d:
        from .ms_assessment import enrich_ms
        result['ms_topography'] = enrich_ms(result, source.parent)
    write_lesion_report(result, flair, mask, directory)
    result['pdf_available'] = True
    (directory / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    return result
