"""Exploratory location and enhancement evidence, with explicit quality gates."""
import numpy as np
import SimpleITK as sitk
from .lesion_multisequence import same_grid, as_image


def locations(mask, anatomy, *, thickness):
    """Native 2D in-plane contact only; no contact inferred across slice gaps."""
    same_grid(mask,anatomy)
    a=sitk.GetArrayFromImage(anatomy)
    ids=sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.Cast(mask>0,sitk.sitkUInt8),True))
    cortex=np.isin(a,[3,42]) | ((a>=1000)&(a<1036)) | ((a>=2000)&(a<2036))
    vent=np.isin(a,[4,43]);infra=np.isin(a,[7,8,16,46,47])
    def adjacent(x):
        y=np.zeros_like(x)
        y[:,1:] |= x[:,:-1];y[:,:-1] |= x[:,1:]
        y[:,:,1:] |= x[:,:,:-1];y[:,:,:-1] |= x[:,:,1:]
        return y
    # Lesions can replace WM labels in an anatomical segmentation.
    tissue=np.isin(a,[2,41]) | (ids>0)
    zones={'Periventricular contact':tissue & adjacent(vent) & ~vent,
           'Juxtacortical contact':tissue & adjacent(cortex) & ~cortex,
           'Infratentorial':infra,
           'Supratentorial':np.isin(a,[2,3,4,10,11,12,13,17,18,26,28,41,42,43,49,50,51,52,53,54,58,60]) | cortex,
           'Corpus callosum':np.isin(a,[251,252,253,254,255])}
    available={'Periventricular contact':bool(vent.any()),'Juxtacortical contact':bool(cortex.any()),
               'Infratentorial':bool(infra.any()),'Supratentorial':bool(zones['Supratentorial'].any()),
               'Corpus callosum':bool(zones['Corpus callosum'].any())}
    left=np.isin(a,[2,3,4,7,8,10,11,12,13,17,18,26,28])|((a>=1000)&(a<1036))
    right=np.isin(a,[41,42,43,46,47,49,50,51,52,53,54,58,60])|((a>=2000)&(a<2036))
    rows=[];voxel=mask.GetSpacing()[0]*mask.GetSpacing()[1]*thickness
    for i in range(1,int(ids.max())+1):
        hit=ids==i;regions=[k for k,v in zones.items() if available[k] and np.any(hit&v)]
        l,r=int(np.sum(hit&left)),int(np.sum(hit&right))
        side='Bilateral' if l and r else ('Left' if l else ('Right' if r else 'Midline / unassigned'))
        rows.append(dict(id=i,regions=regions,side=side,volume_mm3=float(hit.sum()*voxel),
                         boundary_overlap_review=bool(np.any(hit&(vent|cortex)))))
    return dict(method='T1 anatomy mapped to native FLAIR; in-plane face contact only',rows=rows,
                regions=[dict(region=k,available=available[k],count=sum(k in r['regions'] for r in rows)) for k in zones],
                clinical_qualification=False,diagnosis=None,component_basis='All primary FLAIR candidates',
                limitations='Contact candidates require native-image review. Slice gaps and partial volume limit contact assessment. Missing callosal labels are unavailable, not negative.')


def enhancement(pre, post, anatomy, component_ids, coverage):
    """WM/GM calibrated focal-increase screen; never a trained CE classifier."""
    for x in (post,anatomy,component_ids,coverage):same_grid(pre,x)
    p=sitk.GetArrayFromImage(pre).astype(float);q=sitk.GetArrayFromImage(post).astype(float)
    a=sitk.GetArrayFromImage(anatomy);ids=sitk.GetArrayFromImage(component_ids)
    valid=sitk.GetArrayFromImage(coverage)>0
    finite=np.isfinite(p)&np.isfinite(q);valid &= finite
    lesion=sitk.Cast(component_ids>0,sitk.sitkUInt8)
    distance=sitk.GetArrayFromImage(sitk.SignedMaurerDistanceMap(lesion,insideIsPositive=False,squaredDistance=False,useImageSpacing=True))
    far=(distance>5) if (ids>0).any() else np.ones(ids.shape,bool)
    wm=np.isin(a,[2,41]);gm=np.isin(a,[3,42])|((a>=1000)&(a<1036))|((a>=2000)&(a<2036))
    controls=[valid&far&sitk.GetArrayFromImage(sitk.BinaryErode(as_image(x.astype('uint8'),pre),[1,1,1])).astype(bool) for x in (gm,wm)]
    problems=[]
    if min(int(c.sum()) for c in controls)<500:problems.append('Insufficient non-lesional GM/WM reference tissue')
    gain=1.;offset=0.;scale=1.;threshold=None;correlation=None;noise=None
    delta=np.zeros(p.shape,float)
    if not problems:
        pm=np.array([np.median(p[c]) for c in controls]);qm=np.array([np.median(q[c]) for c in controls])
        # Normalize to WM signal, not the small GM-WM difference of low-contrast VIBE.
        scale=abs(pm[1])
        if scale<1e-5 or abs(pm[1]-pm[0])<1e-5 or abs(qm[1]-qm[0])<1e-5:problems.append('Insufficient tissue contrast')
        else:
            gain=float((pm[1]-pm[0])/(qm[1]-qm[0]));offset=float(pm[0]-gain*qm[0])
            if not .1<gain<10:problems.append('Incompatible tissue intensity scaling')
            delta=(q*gain+offset-p)/scale
            # Reference noise uses non-lesional WM; cortical vessels must not set the lesion threshold.
            control=controls[1]
            residual=delta[control];center=float(np.median(residual))
            noise=float(1.4826*np.median(np.abs(residual-center)))
            brain=(a>0)&valid&far
            correlation=float(np.corrcoef(p[brain],q[brain])[0,1])
            threshold=max(.1,center+5*noise,float(np.percentile(residual,99.9)))
            if not np.isfinite(correlation) or correlation<.8:
                problems.append('Poor pre/post tissue correspondence')
                if not np.isfinite(correlation):correlation=None
            if noise>.15:problems.append('Excessive residual tissue intensity variation')
    rows=[];positive=np.zeros(p.shape,bool)
    boundary_tissues=np.isin(a,[4,43,14,15,24])|gm
    boundary_distance=sitk.GetArrayFromImage(sitk.SignedMaurerDistanceMap(
        as_image(boundary_tissues.astype('uint8'),pre),insideIsPositive=False,squaredDistance=False,useImageSpacing=True))
    boundary_zone=boundary_distance<=1.5
    if not problems:positive=(delta>threshold)&valid&(ids>0)
    for i in sorted(set(np.unique(ids))-{0}):
        hit=ids==i;fraction=float(valid[hit].mean())
        status='No focal increase detected by screen';reason='No qualifying focal positive subtraction cluster'
        max_diameter=0.;volume=0.;boundary_volume=0.
        if fraction<.95 or problems:
            status='Not evaluable';reason='; '.join(problems or ['Incomplete paired T1 coverage'])
        else:
            clusters=sitk.ConnectedComponent(as_image((positive&hit).astype('uint8'),pre),True)
            stats=sitk.LabelShapeStatisticsImageFilter();stats.SetComputeFeretDiameter(True);stats.Execute(clusters)
            for lab in stats.GetLabels():
                diam=stats.GetFeretDiameter(lab);v=stats.GetPhysicalSize(lab)
                max_diameter=max(max_diameter,float(diam))
                if diam>=3 and v>=3:
                    volume+=float(v)
                    cluster=sitk.GetArrayViewFromImage(clusters)==lab
                    if np.mean(boundary_zone[cluster])>=.5:boundary_volume+=float(v)
            if volume:
                status='Possible enhancement; confirm on native T1'
                reason='Focal positive subtraction cluster; exclude vessels, misregistration and intrinsic T1 signal'
                if boundary_volume>=volume*.5:
                    status='Indeterminate: boundary-associated signal increase'
                    reason='Increase lies near CSF/cortical boundaries; partial volume or misregistration can mimic enhancement'
        rows.append(dict(component_id=int(i),assessment=status,reason=reason,support_fraction=fraction,
                         positive_cluster_mm3=volume,boundary_positive_mm3=boundary_volume,max_positive_diameter_mm=max_diameter,
                         mean_normalized_delta=float(np.mean(delta[hit&valid])) if np.any(hit&valid) and not problems else None,
                         p95_normalized_delta=float(np.percentile(delta[hit&valid],95)) if np.any(hit&valid) and not problems else None))
    delta[~valid]=0
    result=dict(method='GM-WM calibrated subtraction screen v1',classifier='Exploratory intensity screen, not a trained model',
                clinical_qualification=False,lesions=rows,quality_passed=not problems,quality_reasons=problems,
                gain=gain,offset=offset,control_correlation=correlation,robust_residual_noise=noise,threshold=threshold,
                minimum_positive_diameter_mm=3,minimum_positive_volume_mm3=3,
                injection_delay_status='Not verified; confirm adequate post-injection timing',
                component_basis='All primary FLAIR candidates on acquired slabs; primary mask IDs',
                interpretation='Possible enhancement and no detected increase are machine screens, not confirmed enhancement or exclusion. Physician confirmation is required.',
                reference='https://doi.org/10.1093/brain/awz144')
    return result,as_image(delta.astype('float32'),pre)


def prepare_anatomy(t1_source, directory, flair, cancel, progress):
    """Compute anatomy from this exact T1, then register it to the FLAIR grid."""
    import json
    from .anatomy_context import compute_anatomy
    from .images import register_flair
    from .runtime import sha256
    progress('Computing T1 anatomy for lesion locations and tissue calibration')
    selected=compute_anatomy(t1_source,directory/'anatomy-context',cancel=cancel,progress=progress)
    moving=sitk.ReadImage(str(selected/'resampled.nii.gz'))
    labels=sitk.ReadImage(str(selected/'labels.nii.gz'));same_grid(moving,labels)
    _,transform=register_flair(flair,moving,cancel)
    mapped=sitk.Resample(labels,flair,transform,sitk.sitkNearestNeighbor,0,sitk.sitkUInt16)
    sitk.WriteImage(mapped,str(directory/'ms-anatomy-in-flair.nii.gz'))
    sitk.WriteTransform(transform,str(directory/'ms-anatomy-resampling.tfm'))
    provenance=dict(model='SynthSeg 2.0',labels_sha256=sha256(selected/'labels.nii.gz'),
                    source_sha256=sha256(selected/'t1.nii.gz'),registration_review_required=True)
    source_result=json.loads((selected/'result.json').read_text(encoding='utf-8'))
    provenance['qc_scores']=source_result.get('qc_scores',{})
    provenance['bundle_manifest_sha256']=source_result.get('bundle_manifest_sha256')
    return labels,mapped,provenance


def pages(result):
    from .organized_report import _table
    data=result.get('sampled_topography')
    if not data:return []
    output=['<h1>Lesion anatomical distribution</h1><p>All primary candidates, including single-plane findings. '
            'In-plane contact candidates from registered T1 anatomy; physician confirmation is required.</p>'+
            _table(['Region','Candidate count'],[[r['region'],r['count'] if r['available'] else 'Unavailable: label absent'] for r in data['regions']],[70,30])+
            '<p>Regions overlap; do not sum counts. A missing corpus callosum label is not a negative finding. '
            'Through-slice contact and McDonald criteria are not inferred from thick, gapped FLAIR.</p>']
    for start in range(0,len(data['rows']),12):
        output.append('<h1>Candidate locations</h1>'+_table(['Primary ID','Side','Location / contact candidate'],
            [[r['id'],r['side'],(', '.join(r['regions']) or 'No assigned category')+ ('; cortex/ventricle overlap: review' if r['boundary_overlap_review'] else '')]
             for r in data['rows'][start:start+12]],[15,20,65]))
    return output


def preserve_primary_ids(review, primary_ids, paired_fov):
    """Never silently lose candidates outside the T1 field or below its sampling."""
    same_grid(primary_ids,paired_fov)
    ids=sitk.GetArrayFromImage(primary_ids);valid=sitk.GetArrayFromImage(paired_fov)>0
    rows={r['component_id']:r for r in review['lesions']}
    for i in sorted(set(np.unique(ids))-{0}):
        fraction=float(valid[ids==i].mean())
        if i not in rows or fraction<.95:
            rows[int(i)]=dict(component_id=int(i),assessment='Not evaluable',
                reason='Insufficient native T1 sampling or primary candidate outside T1 field',
                mean_normalized_delta=None,p95_normalized_delta=None,support_fraction=fraction,
                positive_cluster_mm3=0,max_positive_diameter_mm=0)
    review['lesions']=[rows[i] for i in sorted(rows)]


def enhancement_pages(result):
    """Native T1 review crops for flagged increases; no diagnosis from colors."""
    import base64
    from pathlib import Path
    from PIL import Image,ImageDraw
    review=result.get('enhancement_review',{})
    flagged=[r for r in review.get('lesions',[]) if r.get('positive_cluster_mm3',0)>0]
    if not flagged:return []
    directory=Path(result['artifact_directory'])
    files=['t1-pre-review.nii.gz','t1-post-registered.nii.gz','t1-subtraction.nii.gz','primary-ids-in-t1.nii.gz']
    pre,post,delta,ids=[sitk.ReadImage(str(directory/n)) for n in files]
    p,q,d,c=[sitk.GetArrayFromImage(i) for i in (pre,post,delta,ids)]
    q=q*review['gain']+review['offset']
    brain=p[p>0];lo,hi=np.percentile(brain,(5,95));output=[]
    for row in flagged[:6]:
        support=(c==row['component_id'])&(d>review['threshold'])
        points=np.argwhere(support)
        if not len(points):continue
        z=int(np.bincount(points[:,0]).argmax());y,x=points[points[:,0]==z][:,1:].mean(axis=0).astype(int)
        canvas=Image.new('RGB',(840,735),'white');draw=ImageDraw.Draw(canvas)
        half_x=max(10,round(25/pre.GetSpacing()[0]));half_y=max(10,round(25/pre.GetSpacing()[1]))
        for k,zz in enumerate([max(0,z-1),z,min(len(p)-1,z+1)]):
            for j,(title,a) in enumerate([('Pre T1',p),('Calibrated post T1',q),('Subtraction',d)]):
                low,high=(lo,hi) if j<2 else (-.3,.3)
                g=np.clip((a[zz]-low)/max(high-low,1e-6)*255,0,255).astype('uint8')
                crop=Image.fromarray(g).convert('RGB').crop((max(0,x-half_x),max(0,y-half_y),min(g.shape[1],x+half_x),min(g.shape[0],y+half_y)))
                crop=crop.resize((250,210))
                canvas.paste(crop,(j*280+10,k*245+28));draw.text((j*280+10,k*245+7),f'{title} | slice {zz}',fill='black')
        path=directory/f'enhancement-review-{row["component_id"]}.png';canvas.save(path)
        data=base64.b64encode(path.read_bytes()).decode('ascii')
        output.append(f'<h1>Primary candidate {row["component_id"]}: T1 evidence</h1><p>{row["assessment"]}. '
            'Three adjacent native T1 slices; post T1 uses the measured tissue calibration and the same display window as pre T1. '
            'Subtraction: bright positive, dark negative. These are review crops, not confirmed enhancement.</p>'
            f'<p><img src="data:image/png;base64,{data}" width="500"></p>')
    return output
