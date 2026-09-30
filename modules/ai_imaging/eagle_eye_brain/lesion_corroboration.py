"""Reversible cross-plane display and exploratory pre-contrast T1 support."""
import numpy as np
import SimpleITK as sitk



def comparison_classes(primary_ids, secondary_ids, pairs):
    from .lesion_multisequence import same_grid, as_image
    same_grid(primary_ids, secondary_ids)
    a=sitk.GetArrayFromImage(primary_ids);b=sitk.GetArrayFromImage(secondary_ids)
    matched=np.isin(a,[p['primary_id'] for p in pairs]) | np.isin(b,[p['secondary_id'] for p in pairs])
    out=np.zeros(a.shape,np.uint8)
    out[b>0]=2;out[a>0]=1;out[matched]=3
    return as_image(out,primary_ids)


def plane_name(image):
    normal=np.array(image.GetDirection()).reshape(3,3)[:,2]
    return ('Sagittal','Coronal','Axial')[int(np.argmax(np.abs(normal)))]


def t1_support(pre, anatomy, ids, expected_ids):
    from .lesion_multisequence import same_grid
    same_grid(pre,anatomy);same_grid(pre,ids)
    t=sitk.GetArrayFromImage(pre);a=sitk.GetArrayFromImage(anatomy);c=sitk.GetArrayFromImage(ids)
    def distance_to(selected):
        image=sitk.GetImageFromArray(selected.astype('uint8'));image.CopyInformation(pre)
        return sitk.GetArrayFromImage(sitk.SignedMaurerDistanceMap(image,insideIsPositive=False,squaredDistance=False,useImageSpacing=True))
    boundary=distance_to(np.isin(a,[0,4,43,5,44,14,15,24,3,42]))>1.5
    wm=np.isin(a,[2,41]) & boundary & (distance_to(c>0)>5) & np.isfinite(t) & (t>0)
    ref=float(np.median(t[wm])) if wm.sum()>=500 else None
    rows=[]
    for identifier in expected_ids:
        selected=c==identifier;core=selected & boundary & np.isfinite(t)
        fraction=float(core.sum()/selected.sum()) if selected.any() else 0.
        ratio=float(np.median(t[core])/ref) if core.sum()>=3 and ref else None
        assessment='Not evaluable'
        if selected.any() and ref:
            assessment='Indeterminate boundary or insufficient tissue'
            if fraction>=.5 and core.sum()*np.prod(pre.GetSpacing())>=3:
                assessment='Low T1 signal; supportive evidence' if ratio<.8 else 'No additional low-T1 support'
        rows.append(dict(component_id=int(identifier),assessment=assessment,lesion_to_wm_ratio=ratio,interior_fraction=fraction))
    return dict(version='t1-support-exploratory-1',clinical_qualification=False,wm_reference_median=ref,rows=rows,
                interpretation='Pre-contrast T1 evidence only; no lesion removal, enhancement or chronic black-hole diagnosis.',
                thresholds=dict(ratio_below=.8,min_interior_fraction=.5,min_core_mm3=3,boundary_distance_mm=1.5))


def pages(result):
    from .organized_report import _table
    data=result.get('t1_support')
    if not data:return []
    intro=('<h1>T1 hypointensity: additional finding</h1><p>Low T1 signal is additional evidence, not proof of pathology. '
           'Persistent T1 hypointensity in MS can be associated with severe tissue injury and axonal loss. '
           'Chronicity requires longitudinal confirmation; a single scan cannot distinguish transient hypointensity from a persistent black hole. '
           'This screen does not measure neuronal or axonal loss directly. '
           'Absent support never removes a FLAIR candidate. This is separate from enhancement and does not establish a chronic black hole. '
           'Intensity depends on acquisition, bias field and registration. CSF/cortical boundary voxels within 1.5 mm are excluded. '
           'Exploratory thresholds: median lesion/WM below 0.8, at least 50% interior tissue and 3 mm3 interior; '
           'these thresholds are not clinically validated. Inspect native T1 and FLAIR.</p>'
           '<p>Longitudinal scientific basis: Andermatt et al. Tracking the Evolution of Cerebral Gadolinium-Enhancing Lesions '
           'to Persistent T1 Black Holes in Multiple Sclerosis: Validation of a Semiautomated Pipeline. '
           'Journal of Neuroimaging (2017). doi:10.1111/jon.12439.</p>'
           '<p>Scientific context: Two Classes of T1 Hypointense Lesions in Multiple Sclerosis With Different Clinical Relevance, '
           'Frontiers in Neurology 2021; doi:10.3389/fneur.2021.619135. This paper does not validate our screening thresholds.</p>')
    return [intro+_table(['FLAIR component','T1 / WM','T1 evidence'],
            [[r.get('display_id',r['component_id']),f"{r['lesion_to_wm_ratio']:.3f}" if r['lesion_to_wm_ratio'] is not None else 'N/A',r['assessment']]
             for r in data['rows'][i:i+10]],[20,20,60]) for i in range(0,len(data['rows']),10)]
