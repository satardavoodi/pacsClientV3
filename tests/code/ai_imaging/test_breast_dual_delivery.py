"""Synthetic server-to-viewer calcium delivery and branch failure contracts."""
import json
from pathlib import Path
import threading
import pytest
from modules.ai_imaging.eagle_eye_engines import breast_dual as dual


def record():
    return dict(study_uid='1.2.3',series_uid='1.2.4',sop_uid='1.2.5',sha256='a'*64)


def payload():
    return dict(status='success',study_id='1.2.3',coordinate_space='native_source_pixels_xy',
                files=[dict(series_uid='1.2.4',sop_uid='1.2.5',source_sha256='a'*64,
                            shape_hw=[512,512],points_xy=[[20,30]],scores=[.01])])


def test_foreign_image_rejected():
    p=payload();p['files'][0]['sop_uid']='1.2.6'
    with pytest.raises(ValueError):dual.validate_calcium(p,[record()],'1.2.3')


@pytest.mark.parametrize('mutate',[lambda p:p['files'].append(p['files'][0]),
 lambda p:p['files'][0].update(points_xy=[[512,0]]),
 lambda p:p['files'][0].update(scores=[]),
 lambda p:p.update(study_id='1.2.6')])
def test_invalid_result_rejected(mutate):
    p=payload();mutate(p)
    with pytest.raises(ValueError):dual.validate_calcium(p,[record()],'1.2.3')


def test_both_branches_start_and_failure_preserves_detection(tmp_path,monkeypatch):
    barrier=threading.Barrier(2,timeout=3)
    def tissue(*a,**kw):
        barrier.wait();return dict(csv='detection.csv',classification_status='completed')
    def calcium(*a,**kw):
        barrier.wait();raise RuntimeError('private information must not escape')
    monkeypatch.setattr(dual,'run_tissue',tissue)
    monkeypatch.setattr(dual,'run_calcium',calcium)
    result=dual.run([], '1.2.3',tmp_path)
    assert result['csv']=='detection.csv'
    assert result['calcium']['status']=='unavailable'
    assert 'private information' not in json.dumps(result)
    assert result['breast_status']=='incomplete'


def test_cancel_cannot_publish_partial(tmp_path,monkeypatch):
    monkeypatch.setattr(dual,'run_tissue',lambda *a,**k:{'classification_status':'completed'})
    monkeypatch.setattr(dual,'run_calcium',lambda *a,**k:payload())
    with pytest.raises(RuntimeError,match='cancelled'):
        dual.run([], '1.2.3',tmp_path,cancelled=lambda:True)


def test_full_result_requires_both_branches(tmp_path,monkeypatch):
    monkeypatch.setattr(dual,'run_tissue',lambda *a,**k:{'classification_status':'unavailable'})
    monkeypatch.setattr(dual,'run_calcium',lambda *a,**k:payload())
    assert dual.run([], '1.2.3',tmp_path)['breast_status']=='incomplete'


from modules.ai_imaging.eagle_eye_remote.breast_results import save_calcium, load_calcium, completion_message


def test_result_roundtrip_and_old_run_isolation(tmp_path):
    detection=tmp_path/'detection_one.csv';detection.write_text('synthetic')
    result=dict(csv=str(detection),source_binding=[record()],calcium=payload())
    save_calcium(result,'1.2.3')
    assert load_calcium(detection,'1.2.3')==payload()
    assert load_calcium(tmp_path/'detection_two.csv','1.2.3')['status']=='unavailable'
    with pytest.raises(ValueError):load_calcium(detection,'1.2.6')


def test_failed_or_legacy_server_never_reuses_old_calcium(tmp_path):
    detection=tmp_path/'detection.csv';detection.write_text('synthetic')
    result=dict(csv=str(detection),source_binding=[record()],calcium=payload())
    save_calcium(result,'1.2.3')
    result.pop('calcium');save_calcium(result,'1.2.3')
    assert load_calcium(detection,'1.2.3')['status']=='unavailable'


def test_completion_reports_both_branches_separately():
    text=completion_message(dict(classification_status='completed',calcium={'status':'unavailable'}))
    assert 'Lesion classification: completed' in text
    assert 'Microcalcification analysis: unavailable' in text
    assert 'absence has not been established' in text


def test_point_payload_has_authenticated_source_binding(tmp_path):
    with pytest.raises(ValueError,match='source binding'):
        save_calcium(dict(csv=str(tmp_path/'d.csv'),calcium=payload()),'1.2.3')


def test_stale_viewer_callback_does_not_replace_current_overlay():
    import ast
    from types import SimpleNamespace
    path=Path('modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py')
    tree=ast.parse(path.read_text(encoding='utf-8'))
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_on_calcium_ready')
    ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(path),'exec'),ns)
    applied=[]
    obj=SimpleNamespace(_calcium_delivery_token=2,csv_details_path='new.csv',
        image_viewer=SimpleNamespace(metadata_fixed={'study_uid':'1.2.3'}),
        set_microcalcification_result=applied.append)
    ns['_on_calcium_ready'](obj,(1,'old.csv','1.2.3'),payload())
    assert not applied
    ns['_on_calcium_ready'](obj,(2,'new.csv','1.2.3'),payload())
    assert applied==[payload()]



def test_normal_breast_adapter_calls_dual_execution(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import adapters,artifacts
    called=[]
    def run(*args,**kwargs):
        called.append(args)
        return {'job_directory':str(tmp_path),'calcium':payload(),'classification_status':'completed'}
    monkeypatch.setattr(dual,'run',run)
    monkeypatch.setattr(artifacts,'prepare_breast_tables',lambda *args:None)
    request=dict(module='breast',study_uid='1.2.3',parameters={})
    result=adapters.execute(request,[dict(path='synthetic.dcm')],tmp_path)
    assert len(called)==1 and result['calcium']==payload()


def test_tissue_failure_cancels_parallel_calcium(tmp_path,monkeypatch):
    observed=threading.Event()
    def tissue(*args,**kwargs):raise ValueError('tissue failure')
    def calcium(*args,**kwargs):
        import time
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if kwargs['cancelled']():observed.set();return {'status':'unavailable'}
            time.sleep(.01)
        raise AssertionError('Calcium was not cancelled')
    monkeypatch.setattr(dual,'run_tissue',tissue)
    monkeypatch.setattr(dual,'run_calcium',calcium)
    with pytest.raises(ValueError,match='tissue failure'):dual.run([], '1.2.3',tmp_path)
    assert observed.is_set()



@pytest.mark.parametrize('bits',[12,14,16])
def test_mono1_and_mono2_equivalent_stored_pixels(bits):
    import numpy as np
    from tools.eagle_eye.calcium_candidate import pixels
    class Dataset(dict):
        @property
        def pixel_array(self):return self.array
    maximum=(1<<bits)-1
    mono2=Dataset(PhotometricInterpretation='MONOCHROME2',BitsAllocated=16,
        BitsStored=bits,HighBit=bits-1,PixelRepresentation=0,PixelSpacing=[.07,.07])
    mono2.array=(np.arange(512*512,dtype=np.uint32).reshape(512,512)%(maximum+1)).astype(np.uint16)
    mono1=Dataset(mono2);mono1['PhotometricInterpretation']='MONOCHROME1'
    mono1.array=(maximum-mono2.array).astype(np.uint16)
    np.testing.assert_array_equal(pixels(mono1)[0],pixels(mono2)[0])



def test_real_pydicom_padding_is_background_after_polarity_conversion():
    import numpy as np
    import pydicom
    from tools.eagle_eye.calcium_candidate import pixels
    ds=pydicom.Dataset();ds.file_meta=pydicom.dataset.FileMetaDataset()
    ds.file_meta.TransferSyntaxUID=pydicom.uid.ExplicitVRLittleEndian
    ds.is_little_endian=True;ds.is_implicit_VR=False
    ds.Rows=ds.Columns=512;ds.SamplesPerPixel=1
    ds.BitsAllocated=ds.BitsStored=16;ds.HighBit=15;ds.PixelRepresentation=0
    ds.PhotometricInterpretation='MONOCHROME1';ds.PixelSpacing=[.07,.07]
    ds.PixelPaddingValue=0;ds.PixelPaddingRangeLimit=1
    raw=np.full((512,512),60000,dtype=np.uint16);raw[0,:]=0;raw[1,:]=1;raw[100,100]=10000
    ds.PixelData=raw.tobytes()
    image,_=pixels(ds)
    assert not image[:2].any()
    assert image[100,100]>image[200,200]
