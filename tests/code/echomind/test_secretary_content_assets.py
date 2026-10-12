"""Content commands preserve author work, exact identity and complete inventories."""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import io
import json

import pytest
from PIL import Image

from tests.code.education.test_course_importer import temp_env


def worker(fn,*args,**kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn,*args,**kwargs).result()


def test_receive_verifies_checksum_and_preserves_session_isolation(tmp_path):
    from modules.EchoMind.secretary.content_assets import receive_asset
    from modules.EchoMind.secretary.session_files import SessionFiles
    stream=io.BytesIO();Image.new('RGB',(32,32),'navy').save(stream,'PNG');raw=stream.getvalue()
    digest=hashlib.sha256(raw).hexdigest()
    value={'name':digest+'.png','data':base64.b64encode(raw).decode(),'sha256':digest,'bytes':len(raw),'source_url':'https://example.org/figure.png'}
    files=SessionFiles(tmp_path)
    session='00000000-0000-0000-0000-000000000001'
    assert worker(receive_asset,session,value,files=files)['delivered']
    assert len(worker(files.snapshot,session))==1
    assert not worker(files.snapshot,'00000000-0000-0000-0000-000000000002')
    with pytest.raises(ValueError):
        worker(receive_asset,session,dict(value,sha256='0'*64),files=files)


def test_organize_inserts_reorders_and_preserves_images_and_unknown_fields(temp_env):
    from modules.education.course_database import insert_course,insert_slide,insert_slide_content,get_course_with_slides
    from modules.EchoMind.secretary.content_assets import inspect_course,organize_course
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.content_assets import OrganizeCourse
    pk=insert_course('Synthetic','Description','Teacher')
    first=insert_slide(pk,1,'First','Notes')
    second=insert_slide(pk,2,'Second','Other notes')
    insert_slide_content(first,'multimedia',1,{'text':'Old','path':'preserved.png','custom':'keep'})
    before=worker(inspect_course,pk)
    request=OrganizeCourse(course_pk=pk,expected_digest=before['content_digest'],author_name='Updated Teacher',slides=[
        {'slide_pk':second,'slide_title':'Second'}, {'slide_title':'Inserted'},
        {'slide_pk':first,'slide_title':'Renamed','text':'New','rich_text':'<b>New</b><script>bad()</script>'}])
    assert worker(organize_course,request)['content_verified']
    actual=get_course_with_slides(pk)
    assert actual['author_name']=='Updated Teacher'
    assert [s['slide_title'] for s in actual['slides']]==['Second','Inserted','Renamed']
    item=actual['slides'][2]['content'][0]['content_data']
    assert item['path']=='preserved.png' and item['custom']=='keep'
    assert item['text']=='New' and 'bad()' not in item['rich_text']
    with pytest.raises(ValueError):
        worker(organize_course,request)


def test_attach_original_image_uses_session_receipt_and_preserves_text(temp_env,tmp_path):
    from modules.education.course_database import insert_course,insert_slide,insert_slide_content,get_course_with_slides
    from modules.EchoMind.secretary.content_assets import inspect_course,attach_asset,receive_asset
    from modules.EchoMind.secretary.session_files import SessionFiles
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.content_assets import CourseAsset
    pk=insert_course('Synthetic','Description','Teacher');slide=insert_slide(pk,1,'Question','Notes')
    content=insert_slide_content(slide,'text',1,{'text':'Keep this explanation','custom':'preserve'})
    stream=io.BytesIO();Image.new('RGB',(32,32),'navy').save(stream,'PNG');raw=stream.getvalue();digest=hashlib.sha256(raw).hexdigest()
    files=SessionFiles(tmp_path/'session');session='00000000-0000-0000-0000-000000000001'
    worker(receive_asset,session,dict(name=digest+'.png',data=base64.b64encode(raw).decode(),sha256=digest,bytes=len(raw)),files=files)
    request=CourseAsset(course_pk=pk,slide_pk=slide,content_pk=content,expected_digest=worker(inspect_course,pk)['content_digest'],sha256=digest,purpose='image')
    assert worker(attach_asset,session,request,files=files)['content_verified']
    item=get_course_with_slides(pk)['slides'][0]['content'][0]
    assert item['content_type']=='multimedia'
    assert item['content_data']['text']=='Keep this explanation'
    assert item['content_data']['custom']=='preserve'


def test_dicom_missing_or_wrong_identity_is_never_complete(tmp_path):
    from modules.EchoMind.secretary.course_dicom import verify_study
    import pydicom
    from pydicom.dataset import FileDataset,FileMetaDataset
    folder=tmp_path/'study';(folder/'3').mkdir(parents=True)
    study={'study_instance_uid':'1.2.3','patient_id':'synthetic','total_instances':2,
           'series':[{'series_uid':'1.2.3.4','series_number':3,'instance_count':2}]}
    meta=FileMetaDataset();meta.TransferSyntaxUID=pydicom.uid.ExplicitVRLittleEndian
    ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
    ds.is_little_endian=True;ds.is_implicit_VR=False
    ds.PatientID='synthetic';ds.StudyInstanceUID='1.2.3';ds.SeriesInstanceUID='1.2.3.4';ds.SeriesNumber=3;ds.SOPInstanceUID='1.2.3.4.1'
    ds.save_as(folder/'3'/'one.dcm')
    with pytest.raises(ValueError):verify_study(folder,study)
    ds.SOPInstanceUID='1.2.3.4.2';ds.PatientID='wrong';ds.save_as(folder/'3'/'two.dcm')
    with pytest.raises(ValueError):verify_study(folder,study)
    ds.PatientID='synthetic';ds.save_as(folder/'3'/'two.dcm')
    assert verify_study(folder,study)==2


def test_pacs_import_downloads_every_series_and_never_attaches_partial_study(temp_env,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pydicom
    from pydicom.dataset import FileDataset,FileMetaDataset
    from modules.education.course_database import insert_course,insert_slide,get_course_with_slides
    from modules.EchoMind.secretary.content_assets import inspect_course
    from modules.EchoMind.secretary.course_dicom import CourseDicom
    from modules.ai_imaging.eagle_eye_remote.secretary.validation.content_assets import ImportDicom
    pk=insert_course('Synthetic','Description','Teacher');slide=insert_slide(pk,1,'Case','')
    study={'study_instance_uid':'1.2.3','patient_id':'synthetic','total_instances':2,'total_series':2,
           'series':[{'series_uid':f'1.2.3.{n}','series_number':n,'instance_count':1,'modality':'MR'} for n in (1,2)]}
    calls=[];fail=[True]
    class Client:
        def __init__(self,**kwargs):pass
        def disconnect(self):pass
        async def download_series(self,uid,info,folder):
            calls.append(info.series_number)
            if fail[0] and info.series_number==2:return SimpleNamespace(success=False)
            folder.mkdir(parents=True,exist_ok=True)
            meta=FileMetaDataset();meta.TransferSyntaxUID=pydicom.uid.ExplicitVRLittleEndian
            ds=FileDataset(None,{},file_meta=meta,preamble=b'\0'*128)
            ds.is_little_endian=True;ds.is_implicit_VR=False
            ds.PatientID='synthetic';ds.StudyInstanceUID=uid;ds.SeriesInstanceUID=info.series_uid
            ds.SeriesNumber=info.series_number;ds.SOPInstanceUID=info.series_uid+'.1'
            ds.save_as(folder/'one.dcm')
            return SimpleNamespace(success=True)
    monkeypatch.setattr('modules.download_manager.network.socket_client.SocketDicomClient',Client)
    monkeypatch.setattr('PacsClient.utils.config.EDUCATION_STORAGE_PATH',str(tmp_path/'courses'))
    monkeypatch.setattr('modules.EchoMind.secretary.course_dicom.ensure_thumbnails',lambda folder,study:len(study['series']))
    service=CourseDicom();service.selections['actual-selection']=('session',[study])
    request=ImportDicom(course_pk=pk,slide_pk=slide,selection_id='actual-selection',study_uids=['1.2.3'],
                        expected_digest=worker(inspect_course,pk)['content_digest'])
    with pytest.raises(ValueError,match='incomplete'):worker(service.import_studies,'session',request)
    assert not get_course_with_slides(pk)['slides'][0]['content']
    assert calls==[1,2]
    fail[0]=False;calls.clear()
    receipt=worker(service.import_studies,'session',request)
    assert calls==[1,2] and receipt['series']==2 and receipt['instances']==2
    assert len(get_course_with_slides(pk)['slides'][0]['content'])==1
