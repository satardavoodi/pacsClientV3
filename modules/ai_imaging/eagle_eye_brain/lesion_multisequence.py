"""Worker-only, reversible cross-plane support and contrast subtraction pilot."""
import json
import threading
import uuid
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from .contracts import BrainError

VERSION = 'cross-plane-support-1'


def same_grid(first, second):
    if first.GetSize() != second.GetSize() or any(not np.allclose(getattr(first, k)(), getattr(second, k)(), atol=1e-5, rtol=0)
            for k in ('GetSpacing', 'GetOrigin', 'GetDirection')):
        raise ValueError('Images must share the exact physical grid.')


def as_image(array, reference):
    result = sitk.GetImageFromArray(array)
    result.CopyInformation(reference)
    return result


def match_components(primary, secondary, secondary_components=None):
    """Keep complete primary components with overlap, never intersect their volumes.

    Secondary is already aligned and restricted to acquired slice slabs. Thresholds
    are engineering safeguards, not validated diagnostic or probability thresholds.
    """
    same_grid(primary, secondary)
    for mask in (primary, secondary):
        if not np.isin(sitk.GetArrayViewFromImage(mask), (0, 1)).all():
            raise ValueError('Cross-plane masks must be binary.')
    a = sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.Cast(primary, sitk.sitkUInt8), True))
    b = sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.Cast(secondary, sitk.sitkUInt8), True))
    if secondary_components is not None:
        same_grid(primary, secondary_components)
        b = sitk.GetArrayFromImage(secondary_components)
        if b.dtype.kind not in 'ui' or not np.array_equal(b > 0, sitk.GetArrayViewFromImage(secondary) > 0):
            raise ValueError('Secondary component identities must match the resampled mask.')
    secondary_ids = set(np.unique(b)) - {0}
    pairs = []
    primary_sizes = np.bincount(a.ravel())
    both = (a > 0) & (b > 0)
    voxel_mm3 = float(np.prod(primary.GetSpacing()))
    if both.any():
        values, counts = np.unique(np.column_stack((a[both], b[both])), axis=0, return_counts=True)
        for (first, second), count in zip(values, counts):
            if count >= 3 and count * voxel_mm3 >= .5 and count / primary_sizes[first] >= .1:
                pairs.append(dict(primary_id=int(first), secondary_id=int(second), overlap_voxels=int(count)))
    first_ids = sorted({p['primary_id'] for p in pairs})
    second_ids = {p['secondary_id'] for p in pairs}
    supported = np.isin(a, first_ids) & (a > 0)
    disagreement = (a > 0) & ~supported
    report = dict(version=VERSION, pairs=pairs, supported_primary_count=len(first_ids),
                  primary_only_count=int(a.max())-len(first_ids),
                  secondary_only_count=len(secondary_ids-second_ids),
                  secondary_count_on_primary_grid=len(secondary_ids),
                  min_overlap_voxels=3, min_overlap_mm3=.5, min_primary_overlap_fraction=.1,
                  registration_status='Requires visual confirmation', clinical_qualification=False,
                  interpretation='Cross-plane supported candidates, not confirmed MS lesions')
    return as_image(supported.astype('uint8'), primary), as_image(disagreement.astype('uint8'), primary), report


def subtraction(pre, post, support):
    """Normalized difference only; no invented enhancement classifier."""
    same_grid(pre, post); same_grid(pre, support)
    selected = sitk.GetArrayViewFromImage(support) > 0
    arrays = [sitk.GetArrayFromImage(im).astype('float32') for im in (pre, post)]
    if selected.sum() < 100 or any(not np.isfinite(a).all() for a in arrays):
        raise ValueError('Insufficient valid support for contrast normalization.')
    normalized = []
    for a in arrays:
        lo, hi = np.percentile(a[selected], (.5, 99.5))
        if hi - lo <= 1e-6:
            raise ValueError('Constant contrast input cannot be normalized.')
        normalized.append(np.clip((a-lo)/(hi-lo), 0, 1))
    delta = normalized[1]-normalized[0]
    delta[~selected] = 0
    return as_image(delta.astype('float32'), pre)


def acquired_support(moving, fixed, transform, thickness, cancel):
    """Nearest resampling cannot invent evidence in unsampled slice gaps."""
    output = np.zeros(tuple(reversed(fixed.GetSize())), np.uint8)
    dx = np.array(fixed.GetDirection()).reshape(3, 3)
    dm = np.array(moving.GetDirection()).reshape(3, 3)
    origin = np.array(moving.GetOrigin()); spacing = np.array(moving.GetSpacing())
    # A rigid transform can be applied vectorially with its basis and offset.
    offset = np.array(transform.TransformPoint((0., 0., 0.)))
    matrix = np.column_stack([np.array(transform.TransformPoint(tuple(np.eye(3)[i])))-offset for i in range(3)])
    yy, xx = np.indices(output.shape[1:])
    for z in range(output.shape[0]):
        if cancel.is_set(): raise BrainError('Cross-plane review cancelled.')
        ijk = np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, z)))
        physical = (ijk * fixed.GetSpacing()) @ dx.T + fixed.GetOrigin()
        indexes = ((physical @ matrix.T + offset - origin) @ dm) / spacing
        inside = np.all((indexes >= -.5) & (indexes <= np.array(moving.GetSize())-.5), axis=1)
        sampled = np.abs(indexes[:, 2]-np.round(indexes[:, 2])) * spacing[2] <= thickness/2 + 1e-5
        output[z] = (inside & sampled).reshape(xx.shape)
    return as_image(output, fixed)


def verify_contrast_pair(first, second):
    """Check matching acquisition families before an intensity subtraction."""
    import pydicom
    def header(path):
        for file in Path(path).iterdir():
            if not file.is_file(): continue
            try:
                ds=pydicom.dcmread(file,stop_before_pixels=True)
                if getattr(ds,'Modality','') == 'MR': return ds
            except pydicom.errors.InvalidDicomError:
                continue
        raise BrainError('Contrast review requires original DICOM MRI inputs.')
    pre,post=header(first),header(second)
    for ds in (pre,post):
        if str(ds.get('MRAcquisitionType','')) != '3D' or 'DERIVED' in ds.get('ImageType',[]):
            raise BrainError('Contrast review requires two original 3D T1 acquisitions, not subtraction or MPR series.')
    for key in ('RepetitionTime','EchoTime','FlipAngle'):
        a,b=pre.get(key),post.get(key)
        if a is None or b is None or not np.isclose(float(a),float(b),rtol=.05,atol=.01):
            raise BrainError('The T1 contrast pair has missing or incompatible acquisition settings.')
    if str(pre.get('ScanningSequence','')) != str(post.get('ScanningSequence','')):
        raise BrainError('The pre/post T1 sequence families differ; subtraction is not qualified.')


def run(t1_source, flair_source, *, study_uid, t1_uid, flair_uid, root,
        flair_secondary_source=None, flair_secondary_uid=None, t1_post_source=None, t1_post_uid=None,
        contrast_roles_confirmed=False, acquisition_mode='2d', cancel=None, progress=None,
        demographics=None, primary_disease='ms', clinical_note='', fazekas_overall=None):
    from .images import read_volume, register_flair
    from .patient_context import dicom_context, require_same_examination
    from .lesions_2d import run_2d, measure_slices, filesystem_path, publish_artifacts
    from .lesions import _run_lesions, measure_mask
    from .lesion_report import write_lesion_report
    import tempfile
    cancel = cancel or threading.Event(); progress = progress or (lambda _: None)
    if primary_disease != 'ms': raise BrainError('Multi-sequence review currently requires MS context.')
    if flair_secondary_source and acquisition_mode != '2d':
        raise BrainError('Cross-plane review currently requires two native 2D FLAIR acquisitions.')
    if t1_post_source and not contrast_roles_confirmed:
        raise BrainError('Verify the selected pre-contrast and post-contrast T1 roles.')
    if t1_post_source: verify_contrast_pair(t1_source,t1_post_source)
    context = dicom_context(t1_source)
    for path, expected in ((flair_secondary_source, flair_secondary_uid), (t1_post_source, t1_post_uid)):
        if path:
            other = dicom_context(path); require_same_examination(context, other, allow_frame_registration=True)
            if other.get('study_uid') != study_uid or other.get('series_uid') != expected:
                raise BrainError('An additional series no longer matches the selected examination.')
    ids = [x for x in (t1_uid, flair_uid, flair_secondary_uid, t1_post_uid) if x]
    if len(set(ids)) != len(ids): raise BrainError('Select distinct source series for each input role.')
    # Verify roles and independent physical planes before expensive inference.
    if flair_secondary_source:
        first = read_volume(flair_source, expected_protocol='flair', allow_2d=True)
        second = read_volume(flair_secondary_source, expected_protocol='flair', allow_2d=True)
        normals = [np.array(im.GetDirection()).reshape(3, 3)[:, 2] for im in (first, second)]
        if abs(np.dot(*normals)) > .35:
            raise BrainError('Select independent approximately orthogonal FLAIR acquisitions.')
    common = dict(study_uid=study_uid, t1_uid=t1_uid, root=root, cancel=cancel, progress=progress,
                  demographics=demographics, primary_disease=primary_disease, clinical_note=clinical_note,
                  fazekas_overall=fazekas_overall)
    runner = run_2d if acquisition_mode == '2d' else _run_lesions
    progress('Analyzing primary FLAIR')
    result = runner(t1_source, flair_source, flair_uid=flair_uid,
                    **({'defer_anatomy': True} if acquisition_mode == '2d' else {}), **common)
    parent = filesystem_path(result['artifact_directory'])
    flair = sitk.ReadImage(str(parent/'flair.nii.gz'))
    mask = sitk.ReadImage(str(filesystem_path(result['mask_path'])))
    destination = Path(result['artifact_directory']).parent / ('ms-multisequence-' + uuid.uuid4().hex[:12])
    with tempfile.TemporaryDirectory(prefix='ee-ms-review-') as scratch:
        directory = Path(scratch)
        result = dict(result, source_result=str(parent/'result.json'), artifact_directory=str(directory), pdf_available=False)
        for key, name in (('raw_mask_path','labels-raw.nii.gz'), ('band_mask_path','labels-band-review.nii.gz')):
            if result.get(key):
                sitk.WriteImage(sitk.ReadImage(str(filesystem_path(result[key]))), str(directory/name)); result[key] = str(directory/name)
        sitk.WriteImage(flair, str(directory/'flair.nii.gz'))
        if flair_secondary_source:
            progress('Analyzing independent secondary FLAIR')
            secondary = run_2d(t1_source, flair_secondary_source, flair_uid=flair_secondary_uid,
                               allow_frame_registration=True, defer_anatomy=True, **common)
            secondary_root = filesystem_path(secondary['artifact_directory'])
            secondary_image = sitk.ReadImage(str(secondary_root/'flair.nii.gz'))
            secondary_mask = sitk.ReadImage(str(filesystem_path(secondary['mask_path'])))
            progress('Registering FLAIR planes and retaining acquisition-gap uncertainty')
            aligned, transform = register_flair(flair, secondary_image, cancel)
            support = acquired_support(secondary_image, flair, transform, secondary['metrics']['slice_thickness_mm'], cancel)
            aligned_mask = sitk.Resample(secondary_mask, flair, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8) & support
            native_components = sitk.ConnectedComponent(sitk.Cast(secondary_mask, sitk.sitkUInt8), True)
            aligned_components = sitk.Resample(native_components, flair, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt32)
            aligned_components = sitk.Mask(aligned_components, support)
            original = mask
            mask, disagreement, matching = match_components(mask, aligned_mask, aligned_components)
            matching.update(primary_metrics=result['metrics'], secondary_metrics=secondary['metrics'],
                            secondary_source_result=str(secondary_root/'result.json'),
                            primary_only_metrics=measure_slices(flair, disagreement, thickness_mm=result['metrics']['slice_thickness_mm']))
            from .lesion_corroboration import comparison_classes, plane_name
            primary_components=sitk.ConnectedComponent(sitk.Cast(original,sitk.sitkUInt8),True)
            classes=comparison_classes(primary_components,aligned_components,matching['pairs'])
            sitk.WriteImage(classes,str(directory/'labels-cross-plane.nii.gz'))
            matching['primary_plane']=plane_name(flair)
            matching['secondary_plane']=plane_name(secondary_image)
            matching['display_semantics']='Whole matched component extents; green takes priority, then primary. Not exact voxel agreement.'
            result['multisequence'] = matching
            result['metrics'] = measure_slices(flair, mask, thickness_mm=result['metrics']['slice_thickness_mm'])
            for name, im in [('labels-primary.nii.gz',original), ('labels-disagreement.nii.gz',disagreement),
                             ('secondary-flair.nii.gz',secondary_image), ('secondary-labels.nii.gz',secondary_mask),
                             ('secondary-aligned.nii.gz',aligned), ('secondary-aligned-labels.nii.gz',aligned_mask)]:
                sitk.WriteImage(im, str(directory/name))
            sitk.WriteTransform(transform, str(directory/'secondary-registration.tfm'))
        from .lesion_characterization import prepare_anatomy, locations, enhancement
        anatomy, mapped_anatomy, anatomy_provenance = prepare_anatomy(t1_source, directory, flair, cancel, progress)
        evaluation_mask = original if flair_secondary_source else mask
        if acquisition_mode == '2d':
            result['sampled_topography'] = locations(evaluation_mask, mapped_anatomy, thickness=result['metrics']['slice_thickness_mm'])
            result['sampled_topography']['provenance'] = anatomy_provenance
        progress('Measuring pre-contrast T1 corroboration')
        pre = read_volume(t1_source)
        pre_aligned, to_pre = register_flair(flair, pre, cancel)
        primary_ids = sitk.ConnectedComponent(sitk.Cast(evaluation_mask>0,sitk.sitkUInt8),True)
        ids_on_pre = sitk.Resample(primary_ids,pre,to_pre.GetInverse(),sitk.sitkNearestNeighbor,0,sitk.sitkUInt32)
        if acquisition_mode == '2d':
            slab_support = acquired_support(flair,pre,to_pre.GetInverse(),result['metrics']['slice_thickness_mm'],cancel)
            ids_on_pre = sitk.Mask(ids_on_pre,slab_support)
        anatomy_on_pre = sitk.Resample(anatomy,pre,sitk.Transform(3,sitk.sitkIdentity),sitk.sitkNearestNeighbor,0,sitk.sitkUInt16)
        from .lesion_corroboration import t1_support
        expected=list(range(1,int(sitk.GetArrayViewFromImage(primary_ids).max())+1))
        result['t1_support']=t1_support(pre,anatomy_on_pre,ids_on_pre,expected)
        for row in result['t1_support']['rows']: row['display_id']='P'+str(row['component_id'])
        if flair_secondary_source:
            _, secondary_to_pre = register_flair(secondary_image,pre,cancel)
            secondary_pre=sitk.Resample(native_components,pre,secondary_to_pre.GetInverse(),sitk.sitkNearestNeighbor,0,sitk.sitkUInt32)
            secondary_pre=sitk.Mask(secondary_pre,acquired_support(secondary_image,pre,secondary_to_pre.GetInverse(),secondary['metrics']['slice_thickness_mm'],cancel))
            matched_secondary={p['secondary_id'] for p in matching['pairs']}
            secondary_expected=[i for i in range(1,int(sitk.GetArrayViewFromImage(native_components).max())+1) if i not in matched_secondary]
            extra=t1_support(pre,anatomy_on_pre,secondary_pre,secondary_expected)
            for row in extra['rows']: row['display_id']='S'+str(row['component_id'])
            result['t1_support']['rows']+=extra['rows']
        sitk.WriteImage(pre,str(directory/'t1-pre-review.nii.gz'))
        sitk.WriteImage(pre_aligned,str(directory/'pre-flair.nii.gz'))
        if t1_post_source:
            progress('Registering T1 pair and preparing normalized subtraction for review')
            pre = read_volume(t1_source); post = read_volume(t1_post_source)
            post_aligned, post_transform = register_flair(pre, post, cancel)
            moving_support = sitk.Image(post.GetSize(), sitk.sitkUInt8)+1; moving_support.CopyInformation(post)
            coverage = sitk.Resample(moving_support, pre, post_transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
            review, delta = enhancement(pre,post_aligned,anatomy_on_pre,ids_on_pre,coverage)
            from .lesion_characterization import preserve_primary_ids
            pre_fov = sitk.Image(pre.GetSize(),sitk.sitkUInt8)+1;pre_fov.CopyInformation(pre)
            paired_fov = sitk.Resample(pre_fov,flair,to_pre,sitk.sitkNearestNeighbor,0,sitk.sitkUInt8)
            preserve_primary_ids(review,primary_ids,paired_fov)
            review['roles'] = 'Clinician-confirmed pre/post T1'
            review['anatomy_provenance'] = anatomy_provenance
            result['enhancement_review'] = review
            delta_flair = sitk.Resample(delta, flair, to_pre, sitk.sitkLinear, 0, sitk.sitkFloat32)
            sitk.WriteImage(ids_on_pre,str(directory/'primary-ids-in-t1.nii.gz'))
            for name, im in [('t1-pre-review.nii.gz',pre),('t1-post-registered.nii.gz',post_aligned),
                             ('t1-subtraction.nii.gz',delta),('subtraction-flair.nii.gz',delta_flair),
                             ('pre-flair.nii.gz',pre_aligned),
                             ('post-flair.nii.gz',sitk.Resample(post_aligned,flair,to_pre,sitk.sitkLinear,0,sitk.sitkFloat32))]:
                sitk.WriteImage(im, str(directory/name))
            sitk.WriteTransform(post_transform, str(directory/'post-registration.tfm'))
            sitk.WriteTransform(to_pre, str(directory/'flair-to-pre.tfm'))
        if cancel.is_set(): raise BrainError('Multi-sequence review cancelled.')
        result['mask_path'] = str(directory/'labels.nii.gz'); result.pop('review_assets',None)
        sitk.WriteImage(mask, result['mask_path'])
        write_lesion_report(result, flair, mask, directory)
        result.update(pdf_available=True, artifact_directory=str(destination), mask_path=str(destination/'labels.nii.gz'))
        for key in ('raw_mask_path','band_mask_path'):
            if result.get(key): result[key] = str(destination/Path(result[key]).name)
        (directory/'result.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        publish_artifacts(directory,destination)
    return result


def report_pages(result):
    from .organized_report import _table
    pages=[]
    if result.get('multisequence'):
        m=result['multisequence']
        pages.append('<h1>Cross-plane FLAIR support</h1><p>Primary result: candidates supported in both acquisitions. '
            'Whole supported primary components are measured on the original primary FLAIR grid. '
            'Volumes are not averaged or summed between views. One-plane findings remain available for review.</p>'
            +_table(['Group','Count'],[['Supported primary components',m['supported_primary_count']],
            ['Primary-only components',m['primary_only_count']],['Secondary-only components on primary grid',m['secondary_only_count']],
            ['Native secondary stack candidates',m['secondary_metrics']['candidate_count']]], [75,25])
            +'<p><b>Registration requires visual confirmation. Two-plane agreement does not prove pathology.</b> '
            'Caps, smooth bands and shared artifacts can appear in both views. Slice gaps, limited coverage '
            'and resampling can miss, split or merge candidates. Secondary native mask is preserved. '
            'Matching uses at least 3 overlapping primary-grid voxels, 0.5 mm3 and 10% of a primary component; these are unvalidated engineering thresholds.</p>')
    if result.get('enhancement_review'):
        e=result['enhancement_review']
        pages.append('<h1>T1 enhancement evidence</h1><p>Pre/post T1 were rigidly registered. Non-lesional GM and WM '
            'medians calibrate global intensity differences. A focal-increase screen is applied to each primary candidate. '
            '<b>This is an exploratory screen, not a trained enhancement classifier.</b> '
            'Possible enhancement requires native T1 confirmation and exclusion of vessels, motion and intrinsic T1 signal. '
            'No focal increase detected does not exclude enhancement.</p>'
            '<p>Engineering screen: non-lesional WM control 99.9th percentile, 5 robust noise units and a 0.1 WM-signal floor; '
            'positive cluster at least 3 mm diameter and 3 mm3. These numeric thresholds have not been clinically validated. '
            'Quality requires adequate non-lesional reference tissue, correspondence and coverage. Increases concentrated within 1.5 mm of CSF/cortical boundaries are flagged as indeterminate boundary effects; this is also an unvalidated engineering screen.</p>'
            + '<p>Quality: ' + ('Passed computational checks; visual review required' if e.get('quality_passed') else
            '; '.join(e.get('quality_reasons', ['Legacy subtraction: no classifier']))) + '</p>'
            '<p>Post-injection timing is not verified. Scientific definition: Filippi et al., Brain 2019;142:1858-1875, '
            'https://doi.org/10.1093/brain/awz144. The paper does not validate this intensity threshold algorithm.</p>')
        for start in range(0,len(e['lesions']),10):
            pages.append('<h1>Candidate subtraction measurements</h1>'+_table(['Component','Mean delta','95th percentile delta','Assessment'],
                [[r['component_id'],f"{r['mean_normalized_delta']:.4f}" if r['mean_normalized_delta'] is not None else 'N/A',
                  f"{r['p95_normalized_delta']:.4f}" if r['p95_normalized_delta'] is not None else 'N/A',r['assessment'] + ('; ' + r['reason'] if r.get('reason') else '')]
                 for r in e['lesions'][start:start+10]],[15,20,25,40]))
    from .lesion_characterization import pages as location_pages, enhancement_pages
    from .lesion_corroboration import pages as support_pages
    pages += support_pages(result)
    pages += location_pages(result)
    pages += enhancement_pages(result)
    if result.get('source_multisequence') or result.get('source_enhancement_review') or result.get('source_sampled_topography'):
        pages.append('<h1>Manual revision</h1><p>Current mask follows the manual edit. Earlier cross-plane support '
                     ', locations and subtraction measurements have been invalidated and were not recomputed.</p>')
    if result.get('multisequence') or result.get('enhancement_review'):
        pages += visual_pages(result)
    return pages


def visual_pages(result):
    """Native-index review panels; interpolation does not restore acquired resolution."""
    import base64
    from PIL import Image, ImageDraw
    directory=Path(result['artifact_directory'])
    mask=sitk.ReadImage(str(directory/'labels.nii.gz'))
    labels=sitk.GetArrayFromImage(mask)
    occupied=np.flatnonzero(np.any(labels>0,axis=(1,2)))
    if not len(occupied): occupied=np.array([labels.shape[0]//2])
    indices=np.unique(occupied[np.linspace(0,len(occupied)-1,min(3,len(occupied))).astype(int)])
    names=[('Primary FLAIR','flair.nii.gz')]
    if result.get('multisequence'): names.append(('Aligned second FLAIR','secondary-aligned.nii.gz'))
    if result.get('enhancement_review'):
        names += [('T1 before','pre-flair.nii.gz'),('T1 after, registered','post-flair.nii.gz'),('Normalized subtraction','subtraction-flair.nii.gz')]
    arrays=[]
    for title,name in names:
        im=sitk.ReadImage(str(directory/name));same_grid(mask,im)
        a=sitk.GetArrayFromImage(im)
        if 'subtraction' in name:
            rgb=np.zeros((*a.shape,3),np.uint8)
            positive=np.clip(a*400,0,255).astype('uint8');negative=np.clip(-a*400,0,255).astype('uint8')
            rgb[...,0]=positive;rgb[...,1]=np.maximum((positive*.7).astype('uint8'),negative);rgb[...,2]=negative
        else:
            lo,hi=np.percentile(a,(1,99.5));g=np.clip((a-lo)/max(hi-lo,1e-6)*255,0,255).astype('uint8')
            rgb=np.repeat(g[...,None],3,axis=3)
        arrays.append((title,rgb))
    pages=[]
    for index in indices:
        canvas=Image.new('RGB',(720,275*((len(arrays)+1)//2)),'white');draw=ImageDraw.Draw(canvas)
        for j,(title,a) in enumerate(arrays):
            panel=Image.fromarray(a[index]);w,h=panel.size
            ratio=mask.GetSpacing()[0]/mask.GetSpacing()[1]
            panel=panel.resize((max(1,round(w*ratio)),h));panel.thumbnail((355,245))
            x=(j%2)*360;y=(j//2)*275
            draw.text((x+5,y+4),title,fill='black');canvas.paste(panel,(x+(360-panel.width)//2,y+25))
        path=directory/f'review-panel-{index}.png';canvas.save(path)
        data=base64.b64encode(path.read_bytes()).decode('ascii')
        pages.append(f'<h1>Multi-sequence alignment review</h1><p>Primary native slice {index} (zero-based). '
                     'All panels resampled to primary FLAIR for comparison; inspect original 3D T1 for enhancement. '
                     'Subtraction: amber positive, cyan negative; color is not a diagnosis.</p>'
                     f'<p><img src="data:image/png;base64,{data}" width="500"></p>')
    return pages
