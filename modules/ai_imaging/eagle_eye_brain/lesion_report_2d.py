"""Explicit sampled-slab reporting, without borrowing 3D normative claims."""
from html import escape


def sections(result, identity, age_text, correction):
    from .organized_report import _table
    from .lesion_indication import context_html
    m = result['metrics']
    measurements = [
        ['Sampled-slab candidate burden (cm3)', f'{m["total_volume_cm3"]:.3f}'],
        ['Gap-inclusive grid estimate (cm3)', f'{m["grid_estimate_volume_cm3"]:.3f}'],
        ['In-plane slice components (not unique lesions)', str(m['slice_candidate_count'])],
        ['Connected stack candidates (26-connectivity)', str(m['candidate_count'])],
        ['Slice thickness / centre step / gap (mm)',
         f'{m["slice_thickness_mm"]:.2f} / {m["slice_step_mm"]:.2f} / {m["slice_gap_mm"]:.2f}'],
    ]
    review = result.get('band_filter', {})
    band_note = ''
    if review.get('status') == 'applied':
        measurements[0][0] = 'Retained candidate burden after band separation (cm3)'
        measurements[0:0] = [
            ['Raw model burden before separation (cm3)', f'{review["raw_metrics"]["total_volume_cm3"]:.3f}'],
            ['Suspected smooth bands, separated (cm3)', f'{review["separated_metrics"]["total_volume_cm3"]:.3f}'],
        ]
        band_note = ('<h2>Reversible MS band review</h2><p>Paired, thin, elongated bands parallel to the '
                     'lateral ventricular wall were separated from the retained MS candidate mask. '
                     'Raw and separated masks remain available. Amber previews show the separated bands. '
                     '<b>This is an unvalidated morphological heuristic, not confirmation of normal tissue.</b> '
                     'The raw burden remains visible above. Review before accepting the reduced burden. '
                     'Focal bulges, radial extensions, unilateral or uncertain candidates are retained. '
                     'Rounded caps are not automatically removed. This rule is not applied to SVD/other contexts.</p>')
    elif result.get('source_band_filter'):
        band_note = ('<p>The mask was manually revised after automated band separation. '
                     'Current measurements follow the edited mask; the automatic filter was not reapplied.</p>')
    if result.get('multisequence'):
        measurements[0:0] = [['Primary-only burden kept for review (cm3)',
            f'{result["multisequence"]["primary_only_metrics"]["total_volume_cm3"]:.3f}']]
        for row in measurements:
            if row[0].startswith(('Retained candidate burden','Sampled-slab candidate burden')):
                row[0] = 'Cross-plane supported primary burden (cm3)'
        band_note += '<p>Main measurements retain only cross-plane supported primary components. One-plane findings are preserved separately; see the cross-plane section.</p>'
    first = ('<h1>2D FLAIR | White-matter candidates</h1><h2>Patient and examination</h2>'
             f'<p>{escape(identity)}<br>Age: {age_text} years | Sex: {escape(result["sex"])}</p>'
             + correction + context_html(result) + '<h2>Measured burden</h2>'
             + _table(['Measurement', 'Value'], measurements, [70, 30]) + band_note
             + '<p><b>Research output; review and clinical sign-off required.</b> '
               'T1 provides examination context. The segmentation model uses FLAIR only. '
               'A zero result does not exclude disease.</p>')
    location_data = result.get('sampled_topography')
    location_table = (_table(['Location', 'Count / assessment'],
        [[r['region'], str(r['count']) + ' contact/location candidates' if r['available'] else 'Unavailable: anatomical label absent']
         for r in location_data['regions']], [45,55]) if location_data else
        _table(['Location', 'Assessment'], [[name, 'Requires native-image review'] for name in
        ('Periventricular', 'Juxtacortical / cortical', 'Corpus callosum', 'Supratentorial', 'Infratentorial')], [40,60]))
    second = ('<h1>Method and interpretation</h1>'
              '<p>MindGlide 1.3.0, CPU; joint 20-label prediction. Label 18 supplies the binary candidate mask. '
              'The model resamples internally; this does not create acquired through-plane resolution. '
              'Measurements use its output restored to the original FLAIR grid.</p>'
              '<h2>Volume and count definitions</h2><p>Sampled-slab burden = positive voxel count x '
              'in-plane pixel area x DICOM SliceThickness. Unobserved gaps are excluded. '
              'The grid estimate substitutes slice-centre spacing and therefore estimates tissue in gaps. '
              'Neither is an exact continuous lesion volume when slices are thick or separated. '
              'In-plane counts use 8-connectivity; stack counts use 26-connectivity with no size removal. '
              'One lesion may span several slice components, while neighbouring lesions can merge.</p>'
              '<h2>Anatomical distribution and MS criteria</h2>'
              + location_table
              + '<p>When available, registered T1 anatomy supplies descriptive locations and in-plane contact candidates. '
                'Missing labels are unavailable, not negative. No contact is inferred across slice gaps. '
                'Automated McDonald criteria remain unqualified for this 2D acquisition. '
                'No MS diagnosis, automated Fazekas grade, age percentile or Z/T score is inferred. '
                'For SVD/other contexts, transfer from this MS-trained model is unvalidated.</p>')
    third = ('<h1>Scientific basis and review</h1><p>Goebl et al. (2025). Enabling new insights from old scans '
             'by repurposing clinical MRI archives for multiple sclerosis research. Nature Communications 16, 3149. '
             'https://doi.org/10.1038/s41467-025-58274-8</p>'
             '<p>Reported training: 4,247 scans, 2,934 MS patients, 592 scanners. External validation: '
             '14,952 scans, 1,001 patients. These cohort results do not establish accuracy for this examination '
             'or superiority over our 3D pipeline.</p>'
             '<p>Review all native FLAIR slices with the full mask, especially small frontal, cortical and '
             'infratentorial candidates. Partial-volume effects and missed lesions remain possible. '
             'Use Manual correction to edit the native mask and generate a separate recalculated report. '
             'Original automated results remain preserved.</p>')
    if review.get('version'):
        third += ('<h2>Band-review scientific basis</h2><p>Filippi et al. Assessment of lesions on magnetic '
                  'resonance imaging in multiple sclerosis: practical guidelines. Brain 142 (2019), 1858-1875. '
                  'https://doi.org/10.1093/brain/awz144<br>'
                  'The guideline excludes symmetric linear periventricular bands from typical MS lesion counting. '
                  'It does not validate our numeric thresholds or establish normal tissue in an individual case.</p>'
                  '<p>Review method: ' + escape(review['version']) + '. Limited to paired elongated bands '
                  'on axial or mildly oblique 2D images. Shape, local width and alignment to the ventricular '
                  'wall are assessed together. Numeric engineering settings and component decisions are retained '
                  'in the analysis audit record. This method does not establish MS diagnostic criteria.</p>')
    return [first, second, third]
