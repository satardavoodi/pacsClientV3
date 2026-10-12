"""Full-stack Dixon vertebral-body evaluation in an Eagle Eye server worker."""
import csv
import json
import os
from pathlib import Path
import numpy as np

from .marrow_quantitative import body_labels, erode_physical, fit_signal, select_branch


def validate_parameters(params):
    from .lumbar_marrow import validate_parameters as validate_clinical
    if params.get('mode') != 'multiparametric' or params.get('inputs_confirmed') is not True:
        raise ValueError('Confirm the selected marrow sequence roles.')
    if type(params.get('input_protocol',1)) is not int or params.get('input_protocol',1) not in (1,2):
        raise ValueError('Unsupported marrow input protocol.')
    if type(params.get('alignment_confirmed',False)) is not bool:
        raise ValueError('Alignment review must be a boolean.')
    validate_clinical({'t1_confirmed':True,'clinical':params.get('clinical',{})})


def read_headers(paths):
    import pydicom
    values=[pydicom.dcmread(p) for p in paths]
    if not values or len(values)>10000:
        raise ValueError('Missing or oversized MRI source.')
    for d in values:
        if (str(d.get('Modality',''))!='MR' or int(d.get('NumberOfFrames',1))!=1
                or int(d.get('SamplesPerPixel',1))!=1 or d.get('ContrastBolusAgent')):
            raise ValueError('Scalar single-frame precontrast MRI is required.')
        if 'PHASE' in [str(x).upper() for x in d.get('ImageType',[])]:
            raise ValueError('Magnitude images are required, not phase images.')
    return values


def volume(headers):
    """Build a checked LPS scalar image, preserving every acquired spatial slice."""
    import SimpleITK as sitk
    first=headers[0]
    orient=np.asarray(first.ImageOrientationPatient,float).reshape(2,3)
    normal=np.cross(*orient)
    if not np.allclose(orient@orient.T,np.eye(2),atol=1e-4):
        raise ValueError('MRI orientation must be orthonormal.')
    ordered=sorted(headers,key=lambda d:np.dot(d.ImagePositionPatient,normal))
    positions=np.asarray([d.ImagePositionPatient for d in ordered],float)
    pixel_spacing=np.asarray(first.PixelSpacing,float)
    if (not np.isfinite(positions).all() or not np.isfinite(pixel_spacing).all() or np.any(pixel_spacing<=0)):
        raise ValueError('MRI geometry is incomplete.')
    z=float(first.SliceThickness)
    if len(ordered)>1:
        delta=np.diff(positions,axis=0); distances=delta@normal
        if np.any(distances<=0) or not np.allclose(distances,distances[0],rtol=.01,atol=.01) or not np.allclose(delta,distances[:,None]*normal,atol=.02):
            raise ValueError('MRI slices contain duplicates, irregular spacing or shear.')
        z=float(distances[0])
    arrays=[]
    for d in ordered:
        if (not np.allclose(d.ImageOrientationPatient,orient.ravel(),atol=1e-5)
                or not np.allclose(d.PixelSpacing,pixel_spacing,atol=1e-5)
                or (int(d.Rows),int(d.Columns))!=(int(first.Rows),int(first.Columns))):
            raise ValueError('Inconsistent MRI slice geometry.')
        a=d.pixel_array.astype(float)*float(d.get('RescaleSlope',1))+float(d.get('RescaleIntercept',0))
        if not np.isfinite(a).all() or np.any(a<0):
            raise ValueError('Magnitude images must be finite and nonnegative.')
        arrays.append(a)
    image=sitk.GetImageFromArray(np.stack(arrays).astype(np.float32))
    image.SetOrigin(tuple(positions[0]));image.SetSpacing((float(pixel_spacing[1]),float(pixel_spacing[0]),z))
    image.SetDirection(tuple(np.column_stack([orient[0],orient[1],normal]).ravel()))
    return image


def same_grid(a,b):
    return all(np.allclose(getattr(a,g)(),getattr(b,g)(),atol=1e-4)
               for g in ('GetSize','GetOrigin','GetSpacing','GetDirection'))


def affine_ras(image):
    value=np.eye(4);flip=np.diag([-1,-1,1])
    value[:3,:3]=flip@np.asarray(image.GetDirection()).reshape(3,3)@np.diag(image.GetSpacing())
    value[:3,3]=flip@image.GetOrigin()
    return value


def load_inputs(records, params=None):
    by_role={role:[r['path'] for r in records if role in r['roles']]
             for role in ('primary','opposed','fat','water','multiecho','t1','t2','stir')}
    headers={r:read_headers(p) for r,p in by_role.items() if p}
    from .marrow_inputs import require_roles
    version=(params or {}).get('input_protocol', 2 if 'opposed' in headers else 1)
    require_roles(headers, version)
    if version == 2:
        for role in ('primary','opposed','t1','t2','stir'):
            for d in headers.get(role, []):
                orient=np.asarray(d.get('ImageOrientationPatient',[]),float)
                if orient.size!=6 or abs(np.cross(orient[:3],orient[3:])[0])<.9:
                    raise ValueError('Required marrow series and STIR must be sagittal.')
    studies={str(d.get('StudyInstanceUID','')) for h in headers.values() for d in h}
    if len(studies)!=1 or not next(iter(studies)):
        raise ValueError('All marrow sources must belong to one identified examination.')
    frames={str(d.FrameOfReferenceUID) for h in headers.values() for d in h if d.get('FrameOfReferenceUID')}
    if len(frames)>1:
        raise ValueError('Marrow sources have different frames of reference; registered inputs are required.')
    if 't1' in by_role and by_role['t1']:
        from .lumbar_marrow import validate_t1_headers
        validate_t1_headers(by_role['t1'])
    images={r:volume(h) for r,h in headers.items() if r!='multiecho'}
    ref=images['primary']
    for role in ('primary',):
        for tag,key in [('RepetitionTime','marrow_tr_ms'),('FlipAngle','marrow_flip_degrees')]:
            images[role].SetMetaData(key,str(float(headers[role][0].get(tag,float('nan')))))
    if ref.GetSize()[2]<3 or not all(same_grid(ref,images[r]) for r in ('opposed','fat','water') if r in images):
        raise ValueError('Dixon components must cover the same complete spatial grid.')
    # Identical DICOM scaling is necessary but does not establish vendor PDFF calibration.
    def scales(h):return {(float(d.get('RescaleSlope',1)),float(d.get('RescaleIntercept',0))) for d in h}
    for pair in [('fat','water'),('primary','opposed')]:
        if all(r in headers for r in pair) and (scales(headers[pair[0]])!=scales(headers[pair[1]]) or len(scales(headers[pair[0]]))!=1):
            raise ValueError('Dixon component scaling differs.')
    if 'multiecho' not in headers:
        return images,[]
    echo=headers['multiecho'];groups={}
    if not all(np.isclose(float(d.MagneticFieldStrength),float(headers['primary'][0].MagneticFieldStrength),atol=.01) for d in echo):
        raise ValueError('Dixon and multi-echo field strengths differ.')
    for d in echo:
        position=tuple(round(float(v),5) for v in d.ImagePositionPatient)
        groups.setdefault(position,[]).append(d)
    planes=[];reference_times=None
    for group in groups.values():
        ordered=sorted(group,key=lambda d:float(d.EchoTime));times=np.array([float(d.EchoTime)/1000 for d in ordered])
        if len(times)<6 or np.any(np.diff(times)<=0):
            raise ValueError('Each multi-echo plane requires at least six distinct echo times.')
        if reference_times is not None and not np.array_equal(times,reference_times):
            raise ValueError('Multi-echo spatial planes have different echo timing.')
        reference_times=times
        plane=volume([ordered[0]])
        plane.SetMetaData('marrow_tr_ms',str(float(ordered[0].RepetitionTime)))
        plane.SetMetaData('marrow_flip_degrees',str(float(ordered[0].FlipAngle)))
        if not all(same_grid(plane,volume([d])) for d in ordered):
            raise ValueError('Echoes are not spatially matched.')
        field=float(ordered[0].MagneticFieldStrength)
        for key in ('MagneticFieldStrength','RepetitionTime','FlipAngle','PixelBandwidth'):
            values=[float(d.get(key,float('nan'))) for d in ordered]
            if not np.isfinite(values).all() or not np.allclose(values,values[0],rtol=.001):
                raise ValueError('Multi-echo acquisition settings change across echoes; use a consistent echo subset.')
        arrays=np.stack([d.pixel_array.astype(float)*float(d.get('RescaleSlope',1))+float(d.get('RescaleIntercept',0)) for d in ordered])
        if not np.isfinite(arrays).all() or np.any(arrays<0):
            raise ValueError('Invalid multi-echo magnitude pixels.')
        planes.append((plane,arrays,times,field))
    return images,planes


def execute(request,records,output,cancel):
    import SimpleITK as sitk
    from .offline_lumbar.service import run_snapshot
    from .eagle_eye.assets import installed_feature_roots
    from .marrow_body_service import run_body
    validate_parameters(request['parameters'])
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    images,planes=load_inputs(records, request['parameters']);image=images['primary'];affine=affine_ras(image)
    roots=installed_feature_roots('lumbar')
    roots.insert(0,Path(__file__).resolve().parents[2]/'generated-files/offline-lumbar/bundle')
    if os.environ.get('AIPACS_OFFLINE_LUMBAR_ROOT'):
        roots.insert(0,Path(os.environ['AIPACS_OFFLINE_LUMBAR_ROOT']))
    bundle=next((p for p in roots if (p/'manifest.json').is_file()),None)
    if bundle is None:
        raise ValueError('Server lumbar model is unavailable.')
    supplements=[Path(__file__).resolve().parents[2]/'generated-files/marrow-body',
                 *[p/'marrow-body' for p in installed_feature_roots('lumbar')]]
    if os.environ.get('AIPACS_MARROW_BODY_ROOT'):
        supplements.insert(0,Path(os.environ['AIPACS_MARROW_BODY_ROOT']))
    assets=next((p for p in supplements if (p/'manifest.json').is_file()),None)
    if assets is None:
        raise ValueError('Install the pinned MR vertebral-body supplement on Eagle Eye Server.')
    model,whole=run_snapshot(bundle,output,sitk.GetArrayFromImage(image),affine,cancel=cancel)
    body=run_body(bundle,assets,image,output,cancel)
    names={int(s['label']):s['name'].rsplit('_',1)[-1] for s in model['segments']
           if s['name'] in {f'vertebrae_L{i}' for i in range(1,6)}}
    labels=body_labels(whole,body)
    labels[~np.isin(labels,list(names))]=0
    if not labels.any():
        raise ValueError('No lumbar vertebral bodies were detected.')
    return calculate(images,planes,labels,names,output,request['parameters'],cancel)


def calculate(images,planes,labels,names,output,params,cancel):
    import SimpleITK as sitk
    image=images['primary'];affine=affine_ras(image);output=Path(output)
    if not np.isin(labels,[0,*names]).all() or not np.any(labels):
        raise ValueError('Edited body masks contain unknown labels or no bodies.')
    # Private same-job inputs retained for server-side corrected-mask recalculation.
    # They are not in the portable artifact allowlist.
    for role,source in images.items():
        sitk.WriteImage(source,str(output/f'input-{role}.nii.gz'))
    plane_manifest=[]
    for i,(plane,echoes,times,field) in enumerate(planes):
        sitk.WriteImage(plane,str(output/f'input-echo-plane-{i}.nii.gz'))
        np.savez_compressed(output/f'input-echo-{i}.npz',echoes=echoes,times=times)
        plane_manifest.append({'index':i,'field_tesla':field,
            'tr_ms':float(plane.GetMetaData('marrow_tr_ms')) if plane.HasMetaDataKey('marrow_tr_ms') else None,
            'flip_degrees':float(plane.GetMetaData('marrow_flip_degrees')) if plane.HasMetaDataKey('marrow_flip_degrees') else None})
    (output/'input-planes.json').write_text(json.dumps(plane_manifest))
    from .marrow_signal_maps import measurements
    rows,ratio,map_kind=measurements(images,labels,names,affine)
    label_image=sitk.GetImageFromArray(labels);label_image.CopyInformation(image)
    for role in ('t1','t2','stir'):
        if role not in images:
            continue
        source=images[role]
        matched=sitk.GetArrayFromImage(sitk.Resample(label_image,source,sitk.Transform(),sitk.sitkNearestNeighbor,0,sitk.sitkUInt8))
        values=sitk.GetArrayFromImage(source)
        for row in rows:
            mask=erode_physical(matched==row['label'],affine_ras(source))
            sample=values[mask]
            row[role+'_signal']=dict(sample_voxels=int(mask.sum()),median_si=float(np.median(sample)) if len(sample)>=20 else None,
                mean_si=float(np.mean(sample)) if len(sample)>=20 else None,
                alignment='DICOM coordinates only; arbitrary signal units')
    np.save(output/'labels.npy',labels,allow_pickle=False)
    sitk.WriteImage(label_image,str(output/'labels.nii.gz'))
    sitk.WriteImage(image,str(output/'review-image.nii.gz'))
    ff=sitk.GetImageFromArray(ratio.astype(np.float32));ff.CopyInformation(image)
    map_name='marrow-signal-ff.nii.gz' if map_kind=='fat_water_signal_ratio' else 'marrow-signal-drop.nii.gz'
    sitk.WriteImage(ff,str(output/map_name))
    (output/'label_names.json').write_text(json.dumps({str(k):'vertebrae_'+v for k,v in names.items()}))
    for row in rows:row['echo_measurements']=[]
    for plane_index,(plane,echoes,times,field) in enumerate(planes):
        if cancel.is_set():
            raise RuntimeError('Analysis cancelled.')
        sampled=sitk.Resample(label_image,plane,sitk.Transform(),sitk.sitkNearestNeighbor,0,sitk.sitkUInt8)
        mapped=sitk.GetArrayFromImage(sampled)[0]
        # Resample F and W separately; interpolating a precomputed ratio biases mixtures.
        pf,pw=([sitk.GetArrayFromImage(sitk.Resample(images[r],plane,sitk.Transform(),sitk.sitkLinear,0,sitk.sitkFloat32))[0] for r in ('fat','water')]
               if 'fat' in images else (np.zeros(mapped.shape),np.zeros(mapped.shape)))
        for row in rows:
            mask=mapped==row['label']
            if mask.sum()<20:
                continue
            # In-plane erosion keeps the single acquired echo slice available.
            eroded=erode_physical(np.repeat(mask[None],5,axis=0),affine_ras(plane))[2]
            if eroded.sum()<20:
                continue
            signal=echoes[:,eroded].mean(axis=1)
            fitted=fit_signal(signal,times,field)
            valid=eroded&((pf+pw)>0)
            prior=np.percentile(pf[valid]/(pf[valid]+pw[valid]),[10,50,90]) if valid.sum()>=20 else [np.nan]*3
            def metadata(source,key):
                return float(source.GetMetaData(key)) if source.HasMetaDataKey(key) else None
            protocol={'dixon_tr_ms':metadata(image,'marrow_tr_ms'),'dixon_flip_degrees':metadata(image,'marrow_flip_degrees'),
                      'echo_tr_ms':metadata(plane,'marrow_tr_ms'),'echo_flip_degrees':metadata(plane,'marrow_flip_degrees')}
            fitted.update(select_branch(fitted['branches'],prior,params.get('alignment_confirmed',False),protocol))
            fitted.update(plane_index=plane_index,sample_pixels=int(eroded.sum()),
                          dixon_signal_percentiles=[float(v) if np.isfinite(v) else None for v in prior],
                          alignment_method='DICOM physical coordinates; physician review required')
            row['echo_measurements'].append(fitted)
        if plane_index==0:
            sitk.WriteImage(sampled,str(output/'marrow-echo-labels.nii.gz'))
    result=dict(task='lumbar_marrow_multiparametric_v1',marrow_measurements=rows,
        segments=[{'label':k,'name':'vertebrae_'+v} for k,v in names.items()],
        shape_kji=list(labels.shape),affine_ras=affine.tolist(),labels_file=str(output/'labels.npy'),
        clinical_context=params.get('clinical',{}),parameters=params,report_status='unreviewed_research_draft',
        roi_method='MR_body_mask_intersect_numbered_vertebrae_2mm_interior',
        red_marrow_fraction=None,iron_concentration=None,artifact_directory=str(output),
        acquisition={'dixon_spatial_slices':image.GetSize()[2],'multiecho_spatial_planes':len(planes),
                     'dixon_tr_ms':float(image.GetMetaData('marrow_tr_ms')) if image.HasMetaDataKey('marrow_tr_ms') else None,
                     'dixon_flip_degrees':float(image.GetMetaData('marrow_flip_degrees')) if image.HasMetaDataKey('marrow_flip_degrees') else None},
        fat_fraction_kind='signal_ratio_not_PDFF' if 'fat' in images else None,
        map_kind=map_kind, signal_map=str(output/map_name),
        signal_ff_map=str(output/map_name) if 'fat' in images else None,
        input_roles=sorted(images)+(['multiecho'] if planes else []),
        optional_inputs={'stir':'acquired' if 'stir' in images else 'not_acquired',
                         'multiecho':'acquired' if planes else 'not_acquired'},
        review_assets={'image':str(output/'review-image.nii.gz'),'mask':str(output/'labels.nii.gz'),
                       'names':str(output/'label_names.json')})
    create_previews(image,labels,ratio,output,result)
    with (output/'marrow.csv').open('w',newline='',encoding='utf-8') as stream:
        fields=[k for k in rows[0] if k!='echo_measurements']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        writer.writerows({k:r[k] for k in fields} for r in rows)
    from .marrow_multisequence_report import report_html
    result['report_html']=str(output/'report.html')
    (output/'report.html').write_text(report_html(result),encoding='utf-8')
    return result


def recalculate(parent_result, edited, output, cancel):
    import SimpleITK as sitk
    root=Path(parent_result['artifact_directory']).resolve()
    images={role:sitk.ReadImage(str(root/f'input-{role}.nii.gz')) for role in
            ('primary','opposed','fat','water','t1','t2','stir') if (root/f'input-{role}.nii.gz').is_file()}
    for key in ('dixon_tr_ms','dixon_flip_degrees'):
        value=parent_result['acquisition'].get(key)
        if value is not None:
            images['primary'].SetMetaData('marrow_'+('tr_ms' if key.endswith('tr_ms') else 'flip_degrees'),str(value))
    planes=[]
    for item in json.loads((root/'input-planes.json').read_text()):
        i=item['index']
        if type(i) is not int or not 0<=i<10000:
            raise ValueError('Invalid parent echo manifest.')
        with np.load(root/f'input-echo-{i}.npz',allow_pickle=False) as stored:
            plane=sitk.ReadImage(str(root/f'input-echo-plane-{i}.nii.gz'))
            for source,key in [('tr_ms','marrow_tr_ms'),('flip_degrees','marrow_flip_degrees')]:
                if item.get(source) is not None:
                    plane.SetMetaData(key,str(item[source]))
            planes.append((plane,stored['echoes'],stored['times'],item['field_tesla']))
    names={int(s['label']):s['name'].rsplit('_',1)[-1] for s in parent_result['segments']}
    return calculate(images,planes,sitk.GetArrayFromImage(edited).astype(np.uint8),names,output,
                     parent_result['parameters'],cancel)


def create_previews(image,labels,ratio,output,result):
    from PIL import Image,ImageDraw
    import SimpleITK as sitk
    array=sitk.GetArrayFromImage(image);lo,hi=np.percentile(array,[2,99])
    previews=[]
    for k in range(len(array)):
        gray=np.uint8(np.clip((array[k]-lo)/max(hi-lo,1e-8),0,1)*255)
        rgb=np.repeat(gray[...,None],3,axis=2);valid=np.isfinite(ratio[k])
        f=np.clip(np.nan_to_num(ratio[k],nan=0),0,1)
        colors=np.stack([55+200*f,40+175*f,130-100*f],axis=-1)
        rgb[valid]=(.3*rgb[valid]+.7*colors[valid]).astype(np.uint8)
        # Physical aspect ratio, including anisotropic source pixels.
        width=max(1,round(rgb.shape[1]*image.GetSpacing()[0]/image.GetSpacing()[1]))
        im=Image.fromarray(rgb).resize((width,rgb.shape[0]))
        name=output/f'preview-slice-{k:03d}.png';im.save(name);previews.append(str(name))
    middle=int(np.argmax(np.count_nonzero(labels,axis=(1,2))))
    result.update(preview=previews[middle],slice_previews=previews)
    columns=8;tw,th=180,330;canvas=Image.new('RGB',(columns*tw,((len(previews)+columns-1)//columns)*th),'#101923')
    draw=ImageDraw.Draw(canvas)
    for i,path in enumerate(previews):
        im=Image.open(path);im.thumbnail((tw,th-24))
        x=(i%columns)*tw;y=(i//columns)*th
        canvas.paste(im,(x+(tw-im.width)//2,y+24));draw.text((x+5,y+4),f'Slice {i+1}',fill='white')
    canvas.save(output/'preview-all-slices.png');result['overview_preview']=str(output/'preview-all-slices.png')
