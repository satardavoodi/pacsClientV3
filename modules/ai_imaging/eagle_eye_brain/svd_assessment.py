"""Quantitative spatial review of WMH candidates, separate from clinical grading."""
import json
from pathlib import Path
import numpy as np
from .contracts import BrainError


def spatial_burden(mask, anatomy, names):
    import SimpleITK as sitk
    from .lesions import measure_mask
    from .anatomical_groups import CORTICAL_GROUPS
    measure_mask(anatomy, mask)
    labels = sitk.GetArrayFromImage(anatomy)
    positive = sitk.GetArrayFromImage(mask) > 0
    voxel = float(np.prod(mask.GetSpacing()))
    left, right = labels == 2, labels == 41
    wm = left | right
    def distance(binary):
        image = sitk.GetImageFromArray(binary.astype(np.uint8)); image.CopyInformation(mask)
        if not binary.any():
            raise BrainError('Anatomical segmentation is missing a required spatial landmark.')
        return sitk.GetArrayFromImage(sitk.SignedMaurerDistanceMap(image, insideIsPositive=False,
                                    squaredDistance=False, useImageSpacing=True))
    ventricle_distance = distance(np.isin(labels, [4, 43]))
    near = wm & (ventricle_distance <= 10.0)
    compartments = [('Periventricular cerebral WM (within 10 mm)', near),
                    ('Other cerebral WM (beyond 10 mm)', wm & ~near),
                    ('Brainstem', labels == 16),
                    ('Cerebellum', np.isin(labels, [7, 8, 46, 47]))]
    covered = np.logical_or.reduce([region for _,region in compartments])
    compartments.append(('Outside these compartments / boundary review', ~covered))
    total = max(int(positive.sum()), 1)
    rows = [dict(region=name, volume_mm3=float(np.count_nonzero(positive & region)*voxel),
                 percent_of_candidates=float(100*np.count_nonzero(positive & region)/total)) for name,region in compartments]
    lobes = []
    for side, domain in [('left', left), ('right', right)]:
        seeds = np.zeros(labels.shape, np.uint16)
        for index,(group,parcels) in enumerate(CORTICAL_GROUPS,1):
            ids = [int(key) for key,name in names.items()
                   if str(name).startswith('ctx-' + ('lh-' if side=='left' else 'rh-'))
                   and str(name).split('-')[-1] in parcels]
            seeds[np.isin(labels,ids)] = index
        if not seeds.any():
            raise BrainError('Cortical parcellation is unavailable for regional WMH review.')
        image=sitk.GetImageFromArray(seeds); image.CopyInformation(mask)
        mapper=sitk.DanielssonDistanceMapImageFilter(); mapper.SetInputIsBinary(False); mapper.SetUseImageSpacing(True)
        mapper.Execute(image)
        nearest=sitk.GetArrayFromImage(mapper.GetVoronoiMap())
        for index,(group,_) in enumerate(CORTICAL_GROUPS,1):
            count=np.count_nonzero(positive & domain & (nearest == index))
            lobes.append(dict(region=f'{side.title()} {group}', volume_mm3=float(count*voxel)))
    return dict(compartments=rows, cerebral_wm_regions=lobes,
                method='Native FLAIR candidate voxels intersect registered subject-specific SynthSeg anatomy; '
                       'cerebral WM assigned to nearest ipsilateral DK cortical group in physical space.',
                pv_distance_mm=10.0, status='Spatial estimates requiring registration and mask review',
                total_volume_mm3=float(positive.sum()*voxel))


def enrich_svd(result, source_directory, *, cancel=None, progress=None):
    """Find only completed same-study anatomy, then explicitly register its T1 to FLAIR."""
    import threading
    import SimpleITK as sitk
    from .lesion_longitudinal import register_previous
    source=Path(source_directory)
    candidates=sorted(source.parent.glob('brain-*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    context=result['patient_context']
    selected=None
    for path in candidates:
        other=json.loads(path.read_text(encoding='utf-8'))
        if all(context.get(k) and context.get(k)==other.get('patient_context',{}).get(k)
               for k in ('patient_id','birth_date','study_uid')) and (path.parent/'labels.nii.gz').is_file():
            selected=path.parent; break
    if selected is None:
        return dict(status='Anatomical localization unavailable: complete same-study brain volumetry first.')
    progress=progress or (lambda text:None)
    progress('Aligning same-study anatomical segmentation for SVD spatial review')
    cancel=cancel or threading.Event()
    target=sitk.ReadImage(str(source/'flair.nii.gz'))
    moving=sitk.ReadImage(str(selected/'resampled.nii.gz'))
    anatomy=sitk.ReadImage(str(selected/'labels.nii.gz'))
    if moving.GetSize()!=anatomy.GetSize():
        raise BrainError('Anatomical labels do not match their source image.')
    transform=register_previous(moving,target,cancel)
    mapped=sitk.Resample(anatomy,target,transform,sitk.sitkNearestNeighbor,0,sitk.sitkUInt16)
    mask=sitk.ReadImage(result['mask_path'])
    summary=spatial_burden(mask,mapped,json.loads((selected/'label_names.json').read_text()))
    from .wmh_fraction import candidate_fractions
    try:
        summary['candidate_fractions'] = candidate_fractions(result['metrics']['total_volume_cm3'], other)
    except BrainError as exc:
        summary['candidate_fractions'] = {'status': 'unavailable', 'reason': str(exc)}
    summary['anatomical_source']=str(selected/'result.json')
    destination=Path(result['artifact_directory'])
    sitk.WriteImage(mapped,str(destination/'svd-anatomy-in-flair.nii.gz'))
    sitk.WriteImage(sitk.Resample(moving,target,transform,sitk.sitkLinear,0,sitk.sitkFloat32),
                    str(destination/'svd-t1-in-flair.nii.gz'))
    sitk.WriteTransform(transform,str(destination/'svd-anatomy-resampling.tfm'))
    return summary


def svd_pages(result):
    from html import escape
    from .wmh_reference import reference_html
    if result.get('clinical_context',{}).get('primary_disease')!='svd':
        return []
    grade=result.get('clinical_context',{}).get('fazekas_overall')
    grade_text=('Not provided' if grade is None else
                f'{grade} ({("none", "mild", "moderate", "severe")[grade]}) — clinician-reported overall rating')
    first=('<h1>Small-vessel disease assessment</h1><h2>Clinical visual severity</h2><p>Fazekas: '
           +escape(grade_text)+'. Separate periventricular and deep scores were not supplied.</p>'
           '<h2>Other SVD markers</h2><p>Lacunes, microbleeds, enlarged perivascular spaces and recent '
           'small subcortical infarcts have not been assessed by this segmentation workflow. '
           'No total SVD score is assigned. Unassessed does not mean absent.</p>'
           +reference_html(result)+
           '<p>Fazekas grade describes visual morphology. An age percentile describes position in a '
           'reference population. They are not interchangeable measures of severity.</p>'
           '<h2>Scientific sources</h2><p>Fazekas et al., AJR 1987;149:351-356. '
           'doi:10.2214/ajr.149.2.351.<br>Duering et al., STRIVE-2, Lancet Neurology 2023. '
           'doi:10.1016/S1474-4422(23)00131-X.<br>de Kort et al., Neurobiology of Aging 2025;146:38-47. '
           'doi:10.1016/j.neurobiolaging.2024.11.006.</p>')
    pages=[first]
    data=result.get('svd_spatial',{})
    if not data.get('compartments'):
        pages.append('<h1>Spatial assessment</h1><p>'+escape(data.get('status','Not computed'))+'</p>')
        return pages
    amounts={}
    for row in data['cerebral_wm_regions']:
        name=row['region'].split(' ',1)[1]
        amounts[name]=amounts.get(name,0)+row['volume_mm3']
    leading=sorted(amounts,key=amounts.get,reverse=True)[:2]
    wm=sum(amounts.values())
    if wm:
        text=', '.join(f'{name}: {amounts[name]:.1f} mm3 ({100*amounts[name]/wm:.1f}% of mapped cerebral WM candidates)' for name in leading)
        pages.append('<h1>Distribution summary</h1><p>The largest nearest-cortical-territory estimates are '
                     +escape(text)+'.</p><p>This is an anatomical proximity estimate for segmented WM candidates, '
                     'not proof of a lobar vascular pattern. Missed lesions and registration errors can alter '
                     'the apparent predominance.</p><p>The supplied overall Fazekas rating is kept separate '
                     'from this automated spatial analysis.</p>')
    for title,rows in [('Candidate distribution by compartment',data['compartments']),
                       ('Cerebral white-matter regional estimates',data['cerebral_wm_regions'])]:
        table='<h1>'+title+'</h1><table width="100%"><tr><th>Region</th><th>Volume (mm3)</th></tr>'
        table+=''.join(f'<tr><td align="left">{escape(r["region"])}</td><td align="center">{r["volume_mm3"]:.1f}</td></tr>' for r in rows)
        pages.append(table+'</table><p>'+escape(data['method'])+'</p><p>The 10 mm periventricular band is an '
                     'operational spatial definition, not a Fazekas classifier. Regions outside cerebral WM '
                     'are retained for review, not silently counted as vascular WMH. Inspect the saved '
                     'registered anatomy before accepting localization.</p>')
    return pages
