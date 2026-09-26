"""Review-only lesion burden report; no anatomical normative extrapolation."""
import base64
from html import escape
import numpy as np


def write_lesion_report(result, flair, mask, directory):
    from .lesion_indication import context_html
    two_d = result.get('acquisition_mode') == '2d'
    if not two_d and result.get("clinical_context", {}).get("primary_disease") == "svd":
        from .wmh_reference import reference_status
        result["wmh_reference"] = reference_status(result)
    import SimpleITK as sitk
    from PIL import Image
    from .organized_report import PAGE, write_paged_pdf
    values, labels = sitk.GetArrayFromImage(flair), sitk.GetArrayFromImage(mask)
    bands = np.zeros_like(labels)
    if two_d and result.get('band_filter', {}).get('status') == 'applied':
        from .lesions import measure_mask
        band_image = sitk.ReadImage(result['band_mask_path'])
        measure_mask(flair, band_image)
        bands = sitk.GetArrayFromImage(band_image)
    lo, hi = np.percentile(values, (1, 99.5))
    gray = np.clip((values - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype('uint8')
    # Native slice indices are explicit: these are review previews, not an atlas.
    occupied = np.flatnonzero(np.any((labels > 0) | (bands > 0), axis=(1, 2)))
    candidates = occupied if occupied.size else np.arange(len(values))
    indices = np.unique(candidates[np.linspace(0, len(candidates) - 1, min(6, len(candidates))).astype(int)])
    previews = []
    for index in indices:
        rgb = np.repeat(gray[index, :, :, None], 3, axis=2)
        positive = labels[index] > 0
        rgb[positive] = (rgb[positive] * 0.45 + np.array([255, 65, 65]) * 0.55).astype('uint8')
        amber = bands[index] > 0
        rgb[amber] = (rgb[amber] * .35 + np.array([255, 185, 40]) * .65).astype('uint8')
        path = directory / f'lesion-preview-{index}.png'
        image = Image.fromarray(rgb)
        # Preserve physical in-plane aspect ratio even for anisotropic input.
        width = 500
        height = round(width * flair.GetSize()[1] * flair.GetSpacing()[1] /
                       (flair.GetSize()[0] * flair.GetSpacing()[0]))
        image.resize((width, height)).save(path)
        previews.append((int(index), path, height))
    context, metrics = result['patient_context'], result['metrics']
    age = result.get('age_years')
    age_text = f'{age:.2f}' if isinstance(age, (int, float)) else 'Not supplied'
    title = ('Small-vessel disease | WMH assessment'
             if result.get('clinical_context', {}).get('primary_disease') == 'svd'
             else 'White-matter lesion assessment')
    identity = ' | '.join(str(context.get(k) or 'Not supplied') for k in ('patient_name', 'patient_id', 'study_date'))
    head = ('<html><head><meta name="brain-patient" content="' + escape(identity, quote=True) + '">'
            '<style>body { font-family: Arial; color: #243946; font-size: 10pt; } '
            'h1 { color: #203e54; font-size: 20pt; } h2 { color: #27618a; } '
            'td, th { padding: 9px; } th { background: #dfebf0; text-align: center; }'
            '</style></head><body>')
    rows = [('Candidate lesions', str(metrics['candidate_count'])),
            ('Total candidate volume (cm3)', f"{metrics['total_volume_cm3']:.3f}"),
            ('Total candidate volume (mm3)', f"{metrics['total_volume_mm3']:.1f}"),
            ('Largest candidate (mm3)', f"{max(metrics['components_mm3'], default=0):.1f}")]
    table = '<table width="100%" cellspacing="0"><tr><th>Measurement</th><th>Value</th></tr>'
    table += ''.join(f'<tr><td align="left">{name}</td><td align="center">{value}</td></tr>' for name, value in rows) + '</table>'
    correction = ('<p><b>Manually corrected segmentation revision.</b> Measurements were recomputed '
                  'from the saved edited mask. The original automated result is preserved. '
                  'Clinical sign-off remains required.</p>' if result.get('manual_correction') else '')
    first = (f'<h1>{title}</h1><h2>Patient and examination</h2>'
             f'<p>{escape(identity)}<br>Age: {age_text} years | Sex: {escape(result["sex"])}</p>'
             + correction + context_html(result) + '<h2>Measured candidate burden</h2>' + table +
             PAGE + '<h1>Method and review requirements</h1>'
             '<h2>Review status</h2><p><b>Unreviewed segmentation. Clinical qualification pending.</b> '
             'These are model-selected lesion candidates; their cause is not determined by the model. '
             'Review the complete native FLAIR mask, registration and MRI sequences before interpretation. '
             'A zero result does not exclude disease.</p>'
             '<h2>Measurement method</h2><p>LST-AI 2.0.0rc1, three-model ensemble, CPU; '
             'probability threshold 0.5. Volume is positive voxel count multiplied by native FLAIR voxel volume. '
             'Candidate counts use 26-connectivity with no minimum-size removal. '
             'No normative Z/T score is inferred. Anatomical topography, when computed, is documented separately. '
             'Longitudinal analysis, when performed, is documented in a separate comparison section.</p>'
             '<h2>Scientific reference</h2><p>Wiltgen et al. LST-AI: A deep learning ensemble for accurate MS lesion '
             'segmentation. NeuroImage: Clinical 42 (2024), 103611.<br>'
             'https://doi.org/10.1016/j.nicl.2024.103611<br>'
             'Implementation: https://github.com/CompImg/LST-AI</p>'
             '<p>Brain extraction: Isensee et al. Automated brain extraction of multisequence MRI using artificial '
             'neural networks. Human Brain Mapping 40 (2019), 4952-4964. https://doi.org/10.1002/hbm.24750</p>')
    from .lesion_longitudinal import comparison_pages
    from .svd_assessment import svd_pages
    from .ms_assessment import ms_pages
    from .lesion_topography import topography_pages
    if two_d:
        from .lesion_report_2d import sections
        pages = sections(result, identity, age_text, correction)
    else:
        pages = [first] + svd_pages(result) + topography_pages(result) + ms_pages(result) + comparison_pages(result)
    for index, path, height in previews:
        display_width = min(500, round(500 * 580 / max(height, 1)))
        preview_data = base64.b64encode(path.read_bytes()).decode('ascii')
        pages.append('<h1>Native FLAIR mask review</h1>'
                     f'<p>Native slice index: {index} (zero-based). Red: retained lesion candidates. '
                     + ('Amber: suspected smooth bands separated for review; not confirmed normal tissue.'
                        if bands.any() else '') + '</p>'
                     f'<p><img src="data:image/png;base64,{preview_data}" width="{display_width}"></p>'
                     '<p>Selected slices are previews only. Inspect the complete NIfTI mask in the image viewer. '
                     'Native storage orientation is retained; these previews do not assign anatomical laterality.</p>')
    html = head + PAGE.join(pages) + '</body></html>'
    (directory / 'report.html').write_text(html, encoding='utf-8')
    write_paged_pdf(html, directory / 'report.pdf', title='AI-PACS | White-matter lesion candidates | Review required')
