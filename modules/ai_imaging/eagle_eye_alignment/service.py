"""Background-only DICOM loading, owned inference, and private report export."""
from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import html
import io
import json
import os
import subprocess
import tempfile
import time
import uuid

import numpy as np

SOURCE_REVISION = '64b292e6398803082e0bd7535774efa2792c6a4b'
WEIGHT_REVISION = '1e1edf999a0e51b1e47e4bfc19de6753ee5ae026'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_bundle(root, cancel=None):
    root=Path(root).resolve()
    try:
        m=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if m['source_revision']!=SOURCE_REVISION or m['weight_revision']!=WEIGHT_REVISION:
            raise ValueError
        from .inference import WEIGHTS
        required={*WEIGHTS.values(),'runtime/python.exe','inference.py','vendor/BaseModels.py',
                  'vendor/SGRModel.py','vendor/LICENSE','vendor/NOTICE'}
        if not required.issubset(m['sha256']):raise ValueError
        for name,expected in m['sha256'].items():
            if cancel is not None and cancel.is_set():raise RuntimeError('Analysis cancelled.')
            path=(root/name).resolve()
            if not path.is_relative_to(root) or digest(path)!=expected:raise ValueError
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('The Alignment model package is missing or changed. Run the documented preparation tool.') from None
    return m


def bundle_root():
    from ..eagle_eye.assets import installed_feature_roots
    override=os.environ.get('AIPACS_ALIGNMENT_BUNDLE')
    if override:return Path(override)
    roots=installed_feature_roots('alignment')
    if not getattr(__import__('sys'),'frozen',False):
        roots.insert(0,Path(__file__).resolve().parents[3]/'generated-files/eagle-eye/alignment')
    for root in roots:
        if (root/'manifest.json').is_file():return root
    raise ValueError('The Eagle Eye Alignment model package is not installed. Manual measurement is available.')


def study_images(study_uid):
    """Bounded read-only image inventory; no image/name payload in shared logs."""
    from PacsClient.utils.db_manager import get_series_by_study_uid
    import pydicom
    rows=[]
    for series in get_series_by_study_uid(study_uid):
        if str(series.get('modality','')).upper() not in ('DX','CR'):continue
        if not series.get('series_path'):continue
        folder=Path(series['series_path'])
        if not folder.is_dir():continue
        for index,path in enumerate(folder.iterdir()):
            if index >= 1000:raise ValueError('Too many files in the series. Select a single alignment DICOM file.')
            if not path.is_file() or path.suffix.lower() not in ('','.dcm','.dicom'):continue
            try:
                ds=pydicom.dcmread(path,stop_before_pixels=True)
            except (OSError,pydicom.errors.InvalidDicomError):continue
            if str(ds.get('StudyInstanceUID',''))!=study_uid:continue
            if str(ds.get('SeriesInstanceUID',''))!=str(series.get('series_uid','')):continue
            if int(ds.get('NumberOfFrames',1))!=1:continue
            rows.append({'path':str(path),'series_uid':str(ds.SeriesInstanceUID),
                         'series_label':f"Series {series.get('series_number','')} | {ds.get('SeriesDescription','Radiograph')}",
                         'label':f"Image {ds.get('InstanceNumber','')} | {ds.get('Rows',0)} x {ds.get('Columns',0)}"})
    return rows


def _spacing(ds):
    for key in ('PixelSpacing','ImagerPixelSpacing','NominalScannedPixelSpacing'):
        try:
            values=tuple(float(x) for x in ds.get(key,[]))
            if len(values)==2 and all(np.isfinite(x) and x>0 for x in values):
                calibrated=(key=='PixelSpacing' and str(ds.get('PixelSpacingCalibrationType','')) in ('GEOMETRY','FIDUCIAL'))
                return values, calibrated, key+(' (patient-plane calibration)' if calibrated else ' (scale requires verification)')
        except (ValueError,TypeError):continue
    aspect=ds.get('PixelAspectRatio',[1,1])
    try:
        r,c=map(float,aspect)
        if min(r,c)<=0 or not np.isfinite([r,c]).all():raise ValueError
    except (ValueError,TypeError):r,c=1.,1.
    return (r/c,1.),False,'Uncalibrated'


def load_image(path,study_uid,series_uid=None):
    import pydicom
    from pydicom.pixel_data_handlers.util import apply_modality_lut
    ds=pydicom.dcmread(path,stop_before_pixels=True)
    if not study_uid or str(ds.get('StudyInstanceUID',''))!=study_uid:
        raise ValueError('This DICOM image belongs to another examination.')
    if series_uid is not None and str(ds.get('SeriesInstanceUID',''))!=series_uid:
        raise ValueError('This image does not belong to the selected primary alignment series.')
    if str(ds.get('Modality','')).upper() not in ('DX','CR'):
        raise ValueError('Select a DX or CR full-length radiograph.')
    if int(ds.get('NumberOfFrames',1))!=1 or int(ds.get('SamplesPerPixel',1))!=1:
        raise ValueError('Select one monochrome, single-frame alignment image.')
    if not ds.get('SOPInstanceUID') or not ds.get('SeriesInstanceUID'):
        raise ValueError('The DICOM image identity is incomplete.')
    if not (0<int(ds.Rows)*int(ds.Columns)<=80_000_000):
        raise ValueError('The image dimensions exceed the alignment input limit.')
    header_identity=(str(ds.StudyInstanceUID),str(ds.SeriesInstanceUID),str(ds.SOPInstanceUID),int(ds.Rows),int(ds.Columns))
    ds=pydicom.dcmread(path)
    if header_identity!=(str(ds.StudyInstanceUID),str(ds.SeriesInstanceUID),str(ds.SOPInstanceUID),int(ds.Rows),int(ds.Columns)):
        raise ValueError('The source image changed during loading. Select it again.')
    raw=ds.pixel_array
    if raw.ndim!=2:raise ValueError('Select one complete two-dimensional radiograph.')
    valid=np.ones(raw.shape,dtype=bool)
    if 'PixelPaddingValue' in ds:
        lo=float(ds.PixelPaddingValue);hi=float(ds.get('PixelPaddingRangeLimit',lo))
        valid=~((raw>=min(lo,hi))&(raw<=max(lo,hi)))
    pixels=np.asarray(apply_modality_lut(raw,ds),dtype=np.float32)
    valid &= np.isfinite(pixels)
    if not valid.any():raise ValueError('The image has no usable pixels.')
    low,high=float(pixels[valid].min()),float(pixels[valid].max())
    if high<=low:raise ValueError('The image has no usable contrast.')
    pixels=np.clip((pixels-low)*255/(high-low),0,255)
    if str(ds.PhotometricInterpretation)=='MONOCHROME1':pixels=255-pixels
    elif str(ds.PhotometricInterpretation)!='MONOCHROME2':raise ValueError('Unsupported photometric interpretation.')
    pixels[~valid]=0
    spacing,calibrated,method=_spacing(ds)
    from ..eagle_eye_remote.radiograph_binding import fingerprint
    semantic_binding = fingerprint(ds, raw, pixels, valid, spacing, calibrated, method)
    return dict(pixels=pixels.astype(np.uint8),spacing=spacing,calibrated=calibrated,calibration_method=method,
                identity={'study_uid':study_uid,'series_uid':str(ds.SeriesInstanceUID),'sop_uid':str(ds.SOPInstanceUID),
                          'patient_id':str(ds.get('PatientID','')),'patient_name':str(ds.get('PatientName','')),
                          'study_date':str(ds.get('StudyDate','')),
                          'accession':str(ds.get('AccessionNumber','')),
                          'institution':str(ds.get('InstitutionName','')),
                          'birth_date':str(ds.get('PatientBirthDate','')),
                          'sex':str(ds.get('PatientSex','')),
                          'series_number':str(ds.get('SeriesNumber','')),
                          'series_description':str(ds.get('SeriesDescription','')),
                          'instance_number':str(ds.get('InstanceNumber',''))},source_sha256=digest(path),
                radiograph_binding=semantic_binding)


def predict(image,cancel,root=None):
    from ..eagle_eye_remote.settings import remote_required
    if remote_required():
        from ..eagle_eye_remote.routing import radiograph
        return radiograph('alignment', image, cancel)
    from modules.mpr.advanced_3d_slicer.owned_process import ProcessJob
    root=Path(root or bundle_root()).resolve()
    validate_bundle(root,cancel)
    if cancel.is_set():raise ValueError('Analysis cancelled.')
    with tempfile.TemporaryDirectory(prefix='aipacs-alignment-') as job:
        directory=Path(job)
        np.save(directory/'input.npy',image['pixels'],allow_pickle=False)
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','QT_'))}
        env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='-1',
                   HF_HUB_OFFLINE='1',OMP_NUM_THREADS='4')
        owner=ProcessJob();process=None
        try:
            process=subprocess.Popen([str(root/'runtime/python.exe'),'-E','-s','-B',str(root/'inference.py'),str(root),
                                      str(directory/'input.npy'),str(directory/'result.json')],
                                     cwd=directory,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            owner.assign(process);deadline=time.monotonic()+600
            while process.poll() is None:
                if cancel.wait(.1):raise ValueError('Analysis cancelled.')
                if time.monotonic()>deadline:raise ValueError('Alignment analysis timed out. Manual measurement is available.')
            if cancel.is_set():raise ValueError('Analysis cancelled.')
            if process.returncode:raise ValueError('AI could not analyze this image. Verify coverage or place landmarks manually.')
            result=json.loads((directory/'result.json').read_text(encoding='utf-8'))
            validate_points(result['landmarks'],image['pixels'].shape)
            result['weight_revision']=WEIGHT_REVISION
            return result
        finally:
            owner.close()
            if process is not None:
                if process.poll() is None:process.kill()
                process.wait(timeout=15)


def validate_points(points,shape):
    from .geometry import LANDMARKS, measure_bilateral
    h,w=shape
    for side in ('R','L'):
        for key in LANDMARKS:
            x,y=points[side][key]
            if not np.isfinite([x,y]).all() or not (0<=x<w and 0<=y<h):
                raise ValueError('Landmarks must remain inside this image.')
    measure_bilateral(points)


def export_report(image,points,metrics,provenance,destination):
    """Atomic self-contained HTML + machine-readable JSON, with annotated image."""
    from PIL import Image,ImageDraw
    from .geometry import MEASUREMENT_LABELS,measure_bilateral
    validate_points(points,image['pixels'].shape)
    metrics=measure_bilateral(points,image['spacing'],calibrated=image['calibrated'])
    destination=Path(destination)
    raster=Image.fromarray(image['pixels']).convert('RGB')
    draw=ImageDraw.Draw(raster)
    for side,color in (('R','#38bdf8'),('L','#fb923c')):
        p=points[side];a=np.mean([p['ankle_lateral'],p['ankle_medial']],axis=0).tolist()
        for pair in ((p['hip'],p['knee']),(p['knee'],a),(p['hip'],a),
                     (p['femur_lateral'],p['femur_medial']),(p['tibia_lateral'],p['tibia_medial']),
                     (p['ankle_lateral'],p['ankle_medial'])):
            draw.line([tuple(x) for x in pair],fill=color,width=max(2,raster.width//500))
        for key,(x,y) in p.items():
            r=max(3,raster.width//250);draw.ellipse((x-r,y-r,x+r,y+r),fill=color)
    data=io.BytesIO();raster.thumbnail((1600,4000));raster.save(data,format='PNG')
    payload=dict(format_version=1,identity=image['identity'],source_sha256=image['source_sha256'],
                 horizontal_flip=image.get('flipped',False),calibration_method=image['calibration_method'],
                 spacing=image['spacing'],calibrated=image['calibrated'],landmarks=points,measurements=metrics,
                 provenance=provenance,reviewed=True)
    columns=''.join(f'<tr><td>{MEASUREMENT_LABELS[k]} ({"deg" if k.endswith("_deg") else metrics["R"]["length_unit"]})</td><td>{v:.2f}</td><td>{metrics["L"][k]:.2f}</td></tr>'
                    for k,v in metrics['R'].items() if isinstance(v,(float,int)))
    details=' | '.join(html.escape(str(image['identity'][k])) for k in ('patient_name','patient_id','study_date'))
    document=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Eagle Eye Alignment View</title>
<style>body{{font:15px Arial;margin:32px;color:#162438}}table{{border-collapse:collapse}}td,th{{padding:8px;border:1px solid #aaa}}img{{max-height:1000px;max-width:100%}}.content{{display:flex;gap:25px}}@media print{{body{{margin:0}}img{{max-height:850px}}}}</style>
<h1>Eagle Eye Alignment View</h1><p>{details}</p><p>Reviewed standing AP full-length radiograph.</p>
<div class="content"><img alt="Reviewed alignment landmarks" src="data:image/png;base64,{base64.b64encode(data.getvalue()).decode()}">
<div><table><tr><th>Measurement</th><th>Right</th><th>Left</th></tr>{columns}</table>
<p>Length unit: {metrics['R']['length_unit']}. Right minus left projected limb length: {metrics['lld']:.2f} {metrics['R']['length_unit']}.</p>
<p>Calibration: {html.escape(image['calibration_method'])}.</p><p>HKA: 0 neutral; negative varus, positive valgus. MAD: positive medial, negative lateral. JLCA is the unsigned convergence magnitude.</p>
<p>Mechanical axes share the reviewed knee center. Femoral and tibial lengths use their respective joint-line midpoints; total length is the direct hip-to-ankle distance. These are projected lengths.</p>
<p>Landmarks: {html.escape(provenance.get('model','Manual'))}. Physician-reviewed points determine the results. Coronal projection does not measure torsion or sagittal deformity.</p></div></div></html>'''
    # A unique sibling JSON keeps concurrent/repeated exports distinct.
    companion=destination.with_name(destination.stem+'-'+uuid.uuid4().hex[:8]+'.json')
    for path,content in ((companion,json.dumps(payload,indent=2,allow_nan=False)),(destination,document)):
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False,suffix='.tmp') as stream:
            tmp=Path(stream.name);stream.write(content)
        try:os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
    return str(destination)
