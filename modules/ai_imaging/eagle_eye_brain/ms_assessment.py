"""Review-only MRI topography support; never an automated McDonald diagnosis."""
import json
from pathlib import Path
import threading
import numpy as np
from .contracts import BrainError

REGIONS = ('Periventricular contact', 'Juxtacortical contact', 'Infratentorial',
           'Supratentorial', 'Corpus callosum')


def face_neighbors(values):
    """Six face neighbours only; no dilation radius or wrap across image borders."""
    out = np.zeros_like(values, dtype=bool)
    for axis in range(3):
        first, second = [slice(None)] * 3, [slice(None)] * 3
        first[axis], second[axis] = slice(1, None), slice(None, -1)
        out[tuple(first)] |= values[tuple(second)]
        out[tuple(second)] |= values[tuple(first)]
    return out


def assess_topography(mask, anatomy, names):
    import SimpleITK as sitk
    from .lesions import measure_mask
    measure_mask(anatomy, mask)
    labels = sitk.GetArrayFromImage(anatomy)
    lesions = sitk.GetArrayFromImage(mask) > 0
    wm = np.isin(labels, [2, 41])
    cortex = np.isin(labels, [3, 42]) | ((labels >= 1000) & (labels < 1036)) | ((labels >= 2000) & (labels < 2036))
    ventricles = np.isin(labels, [4, 43])
    infra = np.isin(labels, [7, 8, 16, 46, 47])
    supra = wm | cortex | np.isin(labels, [10, 11, 12, 13, 17, 18, 26, 28, 49, 50, 51, 52, 53, 54, 58, 60])
    cc_ids = [int(key) for key, name in names.items() if 'corpus callosum' in str(name).lower()]
    callosum = np.isin(labels, cc_ids)
    availability = dict(zip(REGIONS, [bool(ventricles.any() and wm.any()), bool(cortex.any() and wm.any()),
                                     bool(infra.any()), bool(supra.any()), bool(callosum.any())]))
    # Anatomical overlap with ventricle/cortex is ambiguous; only WM-side face
    # adjacency supports a contact candidate, never a 3/10 mm proximity band.
    zones = dict(zip(REGIONS, [wm & face_neighbors(ventricles), wm & face_neighbors(cortex),
                              infra, supra | callosum, callosum]))
    components_image = sitk.ConnectedComponent(sitk.Cast(mask > 0, sitk.sitkUInt8), True)
    components = sitk.GetArrayFromImage(components_image)
    stats = sitk.LabelShapeStatisticsImageFilter()
    stats.SetComputeFeretDiameter(True); stats.Execute(components_image)
    voxel = float(np.prod(mask.GetSpacing()))
    rows = []
    for component in stats.GetLabels():
        support = components == component
        regions = [name for name, zone in zones.items() if availability[name] and np.any(support & zone)]
        diameter = float(stats.GetFeretDiameter(component))
        overlaps_boundary = bool(np.any(support & (ventricles | cortex)))
        rows.append(dict(id=int(component), volume_mm3=float(support.sum() * voxel),
                         feret_diameter_mm=diameter, size_candidate=diameter >= 3.0,
                         regions=regions, boundary_overlap_review=overlaps_boundary))
    summary = []
    for name in REGIONS:
        matched = [row for row in rows if name in row['regions']]
        summary.append(dict(region=name, available=availability[name], count=len(matched),
                            volume_mm3=sum(r['volume_mm3'] for r in matched),
                            size_candidate_count=sum(r['size_candidate'] and not r['boundary_overlap_review'] for r in matched)))
    # Only three brain DIS categories. Callosal and supratentorial findings
    # never create additional DIS categories; one bridge component cannot by
    # itself yield two-region support.
    categories = REGIONS[:3]
    eligible = {name: {r['id'] for r in rows if name in r['regions'] and r['size_candidate']
                      and not r['boundary_overlap_review']} for name in categories}
    distinct_support = any(a != b for i, first in enumerate(categories) for second in categories[i+1:]
                           for a in eligible[first] for b in eligible[second])
    complete = all(availability[name] for name in categories)
    conclusion = ('Potential two-region brain topographic support; physician confirmation required'
                  if distinct_support else 'Two-region brain topographic support not demonstrated by eligible automated candidates')
    if not complete and not distinct_support:
        conclusion = 'Indeterminate: required brain anatomical masks are incomplete'
    return dict(version='MS topographic review v1; McDonald 2024 context', rows=rows, regions=summary,
                unique_candidate_count=len(rows), potential_brain_dis_support=distinct_support,
                conclusion=conclusion, physician_confirmation_required=True, diagnosis=None,
                unassessed=['Lesion typicality / alternative causes', 'Purely cortical lesions',
                            'Spinal cord', 'Optic nerve', 'Enhancement', 'Central vein sign',
                            'Paramagnetic rim lesions', 'CSF and clinical criteria', 'Full dissemination in time'],
                contact_method='WM-side face adjacency in the registered voxel grid; a contact candidate, not proof of anatomical contact')


def enrich_ms(result, directory, *, t1_source=None, cancel=None, progress=None):
    """Reuse verified same-study anatomy or compute it inside the caller's Brain lock."""
    import SimpleITK as sitk
    from .lesion_longitudinal import register_previous
    from .runtime import sha256
    cancel, progress = cancel or threading.Event(), progress or (lambda text: None)
    directory = Path(directory)
    context = result['patient_context']
    selected = None
    candidates = [directory/'ms-anatomy/result.json', directory/'svd-anatomy/result.json',
                  *sorted(directory.parent.glob('brain-*/result.json'), key=lambda p:p.stat().st_mtime, reverse=True)]
    for path in candidates:
        try:
            other = json.loads(path.read_text(encoding='utf-8'))
            if (other.get('pdf_available') and not (path.parent/'FAILED').exists()
                and all(context.get(k) and context.get(k) == other.get('patient_context', {}).get(k)
                        for k in ('patient_id', 'birth_date', 'study_uid'))):
                selected = path.parent; break
        except (OSError, ValueError, TypeError):
            continue
    if selected is None:
        if not t1_source:
            return {'conclusion': 'Not assessed: same-study anatomical segmentation is unavailable',
                    'physician_confirmation_required': True}
        from .anatomy_context import compute_anatomy
        progress('Preparing T1 anatomical segmentation for lesion topography')
        selected = compute_anatomy(t1_source, directory / 'ms-anatomy', cancel=cancel, progress=progress)
    progress('Registering anatomical boundaries for lesion contact review')
    fixed = sitk.ReadImage(str(directory/'flair.nii.gz'))
    moving = sitk.ReadImage(str(selected/'resampled.nii.gz'))
    anatomy = sitk.ReadImage(str(selected/'labels.nii.gz'))
    if (moving.GetSize() != anatomy.GetSize() or any(not np.allclose(a,b,atol=1e-5,rtol=0) for a,b in
        ((moving.GetSpacing(),anatomy.GetSpacing()),(moving.GetOrigin(),anatomy.GetOrigin()),
         (moving.GetDirection(),anatomy.GetDirection())))):
        raise BrainError('MS anatomy does not match its source geometry.')
    transform = register_previous(moving, fixed, cancel)
    mapped = sitk.Resample(anatomy, fixed, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt16)
    if cancel.is_set():
        raise BrainError('MS topography cancelled.')
    assessment = assess_topography(sitk.ReadImage(result['mask_path']), mapped,
                                   json.loads((selected/'label_names.json').read_text()))
    assessment.update(anatomical_source=str(selected/'result.json'),
                      anatomy_sha256=sha256(selected/'labels.nii.gz'))
    destination = Path(result['artifact_directory'])
    sitk.WriteImage(mapped, str(destination/'ms-anatomy-in-flair.nii.gz'))
    sitk.WriteImage(components_for_review(sitk.ReadImage(result['mask_path'])), str(destination/'ms-candidate-ids.nii.gz'))
    sitk.WriteTransform(transform, str(destination/'ms-anatomy-resampling.tfm'))
    return assessment


def components_for_review(mask):
    import SimpleITK as sitk
    return sitk.ConnectedComponent(sitk.Cast(mask > 0, sitk.sitkUInt8), True)


def ms_pages(result):
    from html import escape
    if result.get('clinical_context',{}).get('primary_disease') != 'ms':
        return []
    data = result.get('ms_topography', {})
    page = ('<h1>MS topography and McDonald criteria review</h1><p><b>' +
            escape(data.get('conclusion','Not assessed: MS topographic analysis was not performed for this result.')) +
            '</b></p><p>This is a machine-derived anatomical calculation. A physician must confirm '
            'lesion typicality, direct contact, registration and competing explanations before using '
            'any finding in the diagnostic criteria. MS diagnosis is not established.</p>')
    if data.get('regions'):
        page += '<table width="100%"><tr><th>Region</th><th>Count</th><th>Volume mm3</th><th>Size-screened*</th></tr>'
        for row in data['regions']:
            values = [str(row['count']), f"{row['volume_mm3']:.1f}",str(row['size_candidate_count'])] if row['available'] else ['Not assessed','-','-']
            page += '<tr><td align="left">'+escape(row['region'])+'</td>'+''.join('<td align="center">'+v+'</td>' for v in values)+'</tr>'
        page += ('</table><p>*Feret diameter at least 3 mm, without detected cortex/ventricle overlap. '
                 'This computational screen does not verify lesion morphology or substitute for multiplanar review. '
                 'Counts and whole-component volumes overlap between categories; total unique candidates: '+str(data['unique_candidate_count'])+'. '
                 'A missing callosal mask is not a negative finding.</p>')
    pages=[page]
    pages.append('<h1>Criteria scope and required confirmation</h1>'
                 '<p>McDonald 2024 uses five anatomical DIS locations: periventricular, cortical/juxtacortical, '
                 'infratentorial, spinal cord and optic nerve. This module screens only the available brain '
                 'locations. Callosal and supratentorial findings are descriptive; neither adds a separate DIS location.</p>'
                 '<p>Two distinct size-screened components in two brain categories flag potential topographic support, '
                 'conditional on physician confirmation of typical MS lesions. Lack of this flag does not exclude MS. '
                 'One component is never sufficient for the automatic two-region flag.</p>'
                 '<p>Periventricular and juxtacortical contact use WM-side voxel-face adjacency, not a 10 mm '
                 'periventricular band or nearest-cortex assignment. Partial volume and registration can create '
                 'false contact. Corpus callosum is assessed only if an explicit callosal label is available; '
                 'it is not inferred from a midline box.</p>'
                 '<p>Purely cortical lesions, optic nerve, spinal cord, enhancement, central vein sign, '
                 'paramagnetic rims, CSF and clinical criteria are not assessed here. Any longitudinal candidate '
                 'changes remain separately documented; full dissemination-in-time/diagnostic criteria are not adjudicated. '
                 'Additional caution is needed with older age, vascular comorbidity and alternative diagnoses.</p>'
                 '<h2>Scientific references</h2><p>Filippi et al., Brain 2019;142:1858-1875. '
                 'doi:10.1093/brain/awz144.<br>Montalban et al., Diagnosis of multiple sclerosis: '
                 '2024 revisions of the McDonald criteria. Lancet Neurology 2025;24:850-865. '
                 'https://discovery.ucl.ac.uk/id/eprint/10211287/</p>')
    for start in range(0,len(data.get('rows',[])),8):
        table='<h1>MS candidate review list</h1><table width="100%"><tr><th>ID</th><th>Volume mm3</th><th>Feret mm</th><th>Topography / review</th></tr>'
        for row in data['rows'][start:start+8]:
            detail=', '.join(row['regions']) or 'No assessed category'
            if row['boundary_overlap_review']: detail+='; boundary overlap: review'
            if not row['size_candidate']: detail+='; below size screen'
            table+=f'<tr><td align="center">{row["id"]}</td><td align="center">{row["volume_mm3"]:.1f}</td><td align="center">{row["feret_diameter_mm"]:.1f}</td><td align="left">{escape(detail)}</td></tr>'
        pages.append(table+'</table><p>Component IDs are spatial review identifiers, not diagnoses.</p>')
    return pages
