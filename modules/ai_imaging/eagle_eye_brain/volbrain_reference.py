"""Offline volBrain intervals, with explicitly non-diagnostic cortical analogues."""
from dataclasses import asdict
import csv
import math
from pathlib import Path
from .contracts import BrainError
from .runtime import sha256

SOURCE='https://github.com/volBrain-net/AssemblyNet#normative-ranges'
REVISION='6bc4383c812314879aa22e96781936e2cb21a298'
HASHES={'female':'2ba915163c8dcfd22c602ebf621ac050c48731f3c02a68c93b2174706d66fc19',
        'male':'74be09eedf6d2ca901c61fb25d28f642908b96d85551cb157641cacd1efe8ced',
        'unknown':'0ab7eab81f15eed10e62f4a899d7bf7ddc9b8cc2045207665955abc66bdbbf29'}
MAPPING={'brain-stem':'Brainstem','3rd ventricle':'3rd ventricle','4th ventricle':'4th ventricle'}
for side in ('left','right'):
    for name in ('thalamus','caudate','putamen','pallidum','hippocampus','amygdala','accumbens area','ventral DC','lateral ventricle','inferior lateral ventricle','cerebral white matter','cerebellum white matter'):
        base={'cerebral white matter':'Cerebrum WM','cerebellum white matter':'Cerebellum WM'}.get(name)
        base=base or 'Left '+name.replace('accumbens area','accumbens').replace('inferior lateral','inf. lateral')
        MAPPING[side+' '+name]=base+'_'+side

# Anatomical counterparts, not validated interchangeable atlas regions.
# Split/merged territories are deliberately excluded; never add interval endpoints.
CORTICAL_ANALOGUES = {
    'parsopercularis': 'opercular inf. frontal gyrus',
    'parstriangularis': 'triangular inf. frontal gyrus',
    'parsorbitalis': 'orbital inf. frontal gyrus',
    'frontalpole': 'frontal pole', 'temporalpole': 'temporal pole',
    'inferiortemporal': 'inf. temporal gyrus',
    'transversetemporal': 'transverse temporal gyrus',
    'superiorparietal': 'sup. parietal lobule', 'precuneus': 'precuneus',
    'cuneus': 'cuneus', 'lingual': 'lingual gyrus',
    'pericalcarine': 'calcarine cortex', 'entorhinal': 'entorhinal area',
    'parahippocampal': 'parahippocampal gyrus',
}
for side, prefix in (('left', 'lh'), ('right', 'rh')):
    MAPPING[side+' cerebellum cortex'] = 'Cerebellum GM_'+side
    for native, source_name in CORTICAL_ANALOGUES.items():
        MAPPING[f'ctx-{prefix}-{native}'] = 'Left '+source_name+'_'+side


def data_root():
    from aipacs_runtime import user_data_root, modules_runtime_search_roots
    local = user_data_root()/'ai/eagle_eye/brain/references/volbrain'
    if local.exists():
        return local
    from modules.ai_imaging.eagle_eye.assets import installed_feature_roots
    for root in installed_feature_roots('brain'):
        candidate = root / 'references/volbrain'
        if candidate.is_dir():
            return candidate
    for root in modules_runtime_search_roots():
        candidate = root/'eagle_eye_brain/references/volbrain'
        if candidate.is_dir():
            return candidate
    return local


def load_source(sex):
    path=data_root()/('bounds_'+({'unknown':'general'}.get(sex,sex))+'.csv')
    if not path.is_file() or sha256(path)!=HASHES[sex]:
        raise BrainError('Published volBrain reference data is missing or changed. See the reference setup documentation.')
    with path.open(encoding='utf-8-sig',newline='') as stream:
        records=list(csv.DictReader(stream))
    result={}
    for key in set(MAPPING.values()):
        selected=[row for row in records if row['name']==key]
        if len(selected)!=1:
            raise BrainError('Published reference contains missing or duplicate mapped regions.')
        result[key]=selected[0]
    return result


def assess(rows, demographics, source):
    result=dict(status='unavailable',reference_id='volbrain',reference_name='volBrain / AssemblyNet published intervals',
                source=SOURCE,revision=REVISION,demographics=asdict(demographics),qualified=False,
                diagnostic_flags_enabled=False,z_score=None,t_score=None,percentile=None,curves=[],rows=[],
                reasons=['Published 95% age/sex intervals, expressed as percent intracranial volume.',
                         'Cross-method comparison: SynthSeg and AssemblyNet boundaries and ICV are not proven interchangeable.',
                         'Starred cortical ranges describe anatomical analogues, not matched SynthSeg normal limits; no interval classification is assigned.',
                         'Fractional ages use local linear interpolation; website interpolation equivalence is unverified.',
                         'Z/T scores and exact percentiles are unavailable from interval tables alone.'])
    age=demographics.age_years
    if age is None or not 1<=age<=90:
        result['reasons'].append('Age unavailable or outside supported ages 1-90; no extrapolation or adult-age substitution.')
        return result
    values={}
    for row in rows:
        name=row['structure'];mm=row['volume_mm3'];cm=row['volume_cm3']
        if (name in values or row.get('method')!='SynthSeg posterior' or
                any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (mm,cm)) or
                not math.isclose(mm/1000,cm,rel_tol=1e-8,abs_tol=1e-8)):
            raise BrainError('Invalid, duplicate or inconsistent reference measurement units.')
        values[name]=cm
    icv=values.get('total intracranial',0)
    if icv<=0 or any(v>icv+1e-6 for v in values.values()):
        raise BrainError('A valid matching intracranial volume is required.')
    a,b=math.floor(age),math.ceil(age);weight=age-a
    for name,value in values.items():
        key=MAPPING.get(name)
        if not key:continue
        if key not in source:raise BrainError('Mapped volBrain reference region is missing.')
        row=source[key]
        try:
            limits=[(1-weight)*float(row[f'{a}yo_{s}'])+weight*float(row[f'{b}yo_{s}']) for s in ('lower_bound','median','upper_bound')]
        except (KeyError,ValueError,TypeError):
            raise BrainError('Published reference interval is malformed.') from None
        lo,mid,hi=limits
        if not all(math.isfinite(v) for v in limits) or not 0<=lo<=mid<=hi<=100:
            raise BrainError('Published reference interval is invalid.')
        pct=100*value/icv
        analogue = name.startswith('ctx-')
        result['rows'].append(dict(structure=name,observed_cm3=value,icv_percent=pct,
            lower_cm3=lo*icv/100,median_cm3=mid*icv/100,upper_cm3=hi*icv/100,
            lower_percent=lo,upper_percent=hi,source_row=key,z_score=None,t_score=None,percentile=None,
            mapping_status='anatomical_analogue' if analogue else 'cross_method',
            position='Atlas analogue only' if analogue else
            'Below published interval' if pct<lo else 'Above published interval' if pct>hi else 'Within published interval'))
    result.update(status='published_intervals',icv_cm3=icv)
    return result


def attach_reference(result, source_directory, demographics):
    if result.get('model')!='SynthSeg 2.0' or sha256(Path(source_directory)/'t1.nii.gz')!=result.get('source_sha256'):
        raise BrainError('Published reference input does not match this measurement job.')
    if demographics.age_years is None or not 1<=demographics.age_years<=90:
        reference=assess([],demographics,{})
    else:
        try:source=load_source(demographics.sex)
        except BrainError as error:
            from .normative import reference_assessment
            reference=reference_assessment(demographics,'volbrain')
            reference['reasons'].append(str(error))
        else:reference=assess(result['posterior_rows'],demographics,source)
    result['normative']=reference
    result['normative_status']=('Published volBrain interval comparison; cross-method validation pending'
                                if reference['status']=='published_intervals' else 'Published volBrain intervals unavailable')
    # Invalidate previous score fields; retain the original physical measurements.
    for row in result['posterior_rows']:
        row.update(z_score=None,t_score=None,percentile=None,normative_status=result['normative_status'])
    return reference


def range_text(reference, name):
    row=next((r for r in reference.get('rows',[]) if r['structure']==name),None)
    if row:
        return f"{row['lower_cm3']:.3f} - {row['upper_cm3']:.3f}" + (' *' if row.get('mapping_status') == 'anatomical_analogue' else '')
    return 'Atlas differs' if reference and name.startswith('ctx-') else 'Not available'


def boundary_deviation_percent(row):
    """Distance outside the nearest endpoint; not a statistical significance test."""
    value, low, high = (row.get(k) for k in ('observed_cm3', 'lower_cm3', 'upper_cm3'))
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (value, low, high)):
        return None
    if not 0 <= low <= high or value < 0:
        return None
    if value < low and low > 0:
        return 100 * (low - value) / low
    if value > high and high > 0:
        return 100 * (value - high) / high
    return 0.0 if low <= value <= high else None


def large_deviation(row):
    distance = boundary_deviation_percent(row)
    return distance is not None and distance > 25 and not math.isclose(distance, 25, abs_tol=1e-9)


class HighlightedText(str):
    highlight = True


def highlight(reference, name, text):
    row = next((r for r in reference.get('rows', []) if r['structure'] == name), None)
    return HighlightedText(text) if row and large_deviation(row) else text


def scientific_reference_page():
    return (
        '<h1>Scientific reference and calculation method</h1>'
        '<h2>Reference population underlying the published intervals</h2>'
        '<p>Coupe P, Catheline G, Lanuza E, Manjon JV; ADNI. '
        '<i>Towards a unified analysis of brain maturation and aging across the entire lifespan: A MRI analysis.</i> '
        'Human Brain Mapping. 2017;38:5501-5518. '
        '<a href="https://doi.org/10.1002/hbm.23743">doi:10.1002/hbm.23743</a>.</p>'
        '<p>The AssemblyNet authors identify this article as describing the MRI data used to compute '
        'their published normative tables and request its citation. The numerical bounds in this report '
        'come from those published tables, not from reconstructing curves in the article. '
        'The paper does not establish that SynthSeg and AssemblyNet measurements are interchangeable.</p>'
        '<h2>Segmentation and atlas provenance</h2>'
        '<p>Coupe P et al. <i>AssemblyNet: A large ensemble of CNNs for 3D whole brain MRI segmentation.</i> '
        'NeuroImage. 2020;219:117026. doi:10.1016/j.neuroimage.2020.117026. '
        'This describes the reference publisher\'s segmentation pipeline; the measurements here use SynthSeg.</p>'
        '<p>Desikan RS et al. <i>An automated labeling system for subdividing the human cerebral cortex '
        'on MRI scans into gyral based regions of interest.</i> NeuroImage. 2006;31:968-980. '
        'doi:10.1016/j.neuroimage.2006.01.021. Native cortical parcels follow this atlas; '
        'starred BrainColor counterparts are contextual anatomical analogues.</p>'
        '<h2>Patient-specific calculation</h2>'
        '<p>Sex-specific age rows from 1-90 years; fractional ages use linear interpolation between '
        'adjacent years. Each published percent-ICV endpoint is multiplied by the same examination\'s '
        'estimated ICV / 100 to obtain cm3. No adult-age substitution is used for the adolescent. '
        'Exact Z/T scores and percentiles are not recoverable from interval endpoints alone.</p>'
        '<h2>Red highlighting rule</h2>'
        '<p><font color="#b91c1c">Red = more than 25% beyond the nearest reference endpoint.</font> '
        'Above: 100 x (measured - upper) / upper. Below: 100 x (lower - measured) / lower. '
        'Exactly 25%, smaller departures and in-range values are not red. '
        'This is a user-selected visual attention threshold, not a p-value, validated atrophy cutoff '
        'or diagnosis. Starred cortical red values may reflect atlas mismatch.</p>'
        '<h2>Reproducibility</h2><p>Publisher data: '+SOURCE+'; pinned revision '+REVISION+'. '
        'Files: bounds_male.csv, bounds_female.csv and bounds_general.csv; integrity checked locally. '
        'The GitHub repository distributes the data; the scientific citation above describes their provenance.</p>')


def pages(reference):
    from .organized_report import _table
    rows=reference.get('rows',[])
    output=[]
    size = 8 if any(r.get('mapping_status') == 'anatomical_analogue' for r in rows) else 14
    for offset in range(0,max(len(rows),1),size):
        data=[[highlight(reference,r['structure'],r['structure'] + ('; source: '+r['source_row'] if r.get('mapping_status') == 'anatomical_analogue' else '')),highlight(reference,r['structure'],f"{r['observed_cm3']:.3f}"),range_text(reference,r['structure']),f"{r['icv_percent']:.3f}",r['position']] for r in rows[offset:offset+size]]
        output.append('<h1>Published volBrain reference intervals</h1>'+
            '<p>95% age/sex reference; cross-method comparison, not a diagnostic classification.</p>'+
            _table(['Region','Measured cm3','Published 95% range cm3','% ICV','Interval position'],data,[25,14,24,10,27])+
            '<p>Bounds use the same local ICV as the measured volume. Fractional ages: linear interpolation. '+
            'Red: >25% beyond nearest interval endpoint; attention threshold, not statistical significance. '
            '* Cortical ranges are anatomical analogues only, not matched normal limits. Split/merged regions remain unavailable. '
            'Source names retain publisher naming; side is the final suffix. Z/T scores cannot be inferred from these bounds.</p>'+
            '<p>Source: '+SOURCE+'; revision '+REVISION+'. '+
            'Coupé et al., Human Brain Mapping (2017), doi:10.1002/hbm.23743.</p>')
    output.append(scientific_reference_page())
    return output
