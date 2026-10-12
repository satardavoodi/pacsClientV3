"""PACS case selections and complete, identity-verified Education imports on workers."""
import asyncio
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .session_files import worker_only


def verify_study(folder, study):
    """Fail before attachment for missing/extra files, duplicate SOPs or wrong identity."""
    import pydicom
    seen=set()
    numbers=[int(s['series_number']) for s in study['series']]
    if len(numbers)!=len(set(numbers)) or not numbers:
        raise ValueError('Series numbers are ambiguous; use the normal PACS import workflow')
    if int(study['total_instances'])>10000:
        raise ValueError('Study exceeds bounded course import limits')
    actual={p.name for p in Path(folder).iterdir() if p.is_dir() and p.name.isdigit()}
    if actual!=set(map(str,numbers)):
        raise ValueError('Study series inventory mismatch')
    for series in study['series']:
        files=list((Path(folder)/str(int(series['series_number']))).glob('*.dcm'))
        if len(files)!=int(series['instance_count']):
            raise ValueError('Incomplete DICOM series')
        for file in files:
            ds=pydicom.dcmread(file,stop_before_pixels=True)
            if (str(ds.PatientID).strip()!=str(study['patient_id']).strip()
                or str(ds.StudyInstanceUID)!=study['study_instance_uid']
                or str(ds.SeriesInstanceUID)!=series['series_uid']
                or int(ds.SeriesNumber)!=int(series['series_number'])
                or str(ds.SOPInstanceUID) in seen):
                raise ValueError('DICOM identity mismatch')
            seen.add(str(ds.SOPInstanceUID))
    if len(seen)!=int(study['total_instances']):
        raise ValueError('Study instance inventory mismatch')
    return len(seen)


def ensure_thumbnails(folder, study):
    """Use the existing bounded Education preview decoder; do not invent clinical pixels."""
    from modules.education.authoring_thumbnails import _dicom_image
    from PacsClient.utils.config import THUMBNAIL_PATH
    from PySide6.QtGui import QImageReader
    count=0
    for series in study['series']:
        number=str(int(series['series_number']))
        target=Path(THUMBNAIL_PATH)/study['study_instance_uid']/(number+'.png')
        if target.is_file() and not QImageReader(str(target)).read().isNull():
            count+=1
            continue
        files=sorted((Path(folder)/number).glob('*.dcm'))
        image=_dicom_image(files[len(files)//2])
        if image.isNull():
            raise ValueError('Series preview unsupported; review this study in the normal viewer')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name('.'+uuid4().hex+'.png')
        try:
            if not image.save(str(temporary),'PNG'):
                raise ValueError('Thumbnail save failed')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        count+=1
    return count


class CourseDicom:
    def __init__(self):
        self.selections={}

    def find(self, session, patient_ids):
        worker_only()
        from modules.network.socket_client import PatientListSocketClient
        if len(self.selections)>=32:
            raise ValueError('PACS selection limit reached')
        client=PatientListSocketClient(timeout=20)
        studies=[]
        try:
            for code in dict.fromkeys(patient_ids):
                rows=client.get_patient_list_safe(patient_id=code,limit=30)
                if rows is None:
                    raise ValueError('PACS unavailable')
                exact=[r for r in rows if str(r.get('patient_id','')).strip()==code.strip()]
                if len(exact)!=1:
                    raise ValueError('PACS patient identity missing or ambiguous')
                uids=exact[0]['study_uids']
                if not isinstance(uids,list) or len(uids)>20:
                    raise ValueError('Select a bounded examination set in PACS')
                for uid in uids:
                    study=client.get_study_info(uid)
                    if not study or str(study['patient_id']).strip()!=code.strip():
                        raise ValueError('PACS study identity mismatch')
                    studies.append(study)
                    if len(studies)>50:
                        raise ValueError('Too many matching studies')
        finally:
            client.disconnect()
        handle=uuid4().hex
        self.selections[handle]=(session,studies)
        return {'selection_id':handle,'studies':[
            {k:s.get(k) for k in ('study_instance_uid','patient_id','study_date','study_description','total_series','total_instances')}
            for s in studies],'selection_review':'Select exact study UIDs; patient name or image appearance is not proof of identity.'}

    def import_studies(self,session,request):
        worker_only()
        selection=self.selections.get(request.selection_id)
        if selection is None or selection[0]!=session:
            raise ValueError('PACS selection belongs to another conversation')
        selected=[s for s in selection[1] if s['study_instance_uid'] in request.study_uids]
        if len(selected)!=len(set(request.study_uids)) or len(request.study_uids)!=len(set(request.study_uids)):
            raise ValueError('Use exact study UIDs from the current selection')
        for study in selected:
            numbers=[int(series['series_number']) for series in study['series']]
            if not numbers or len(numbers)!=len(set(numbers)) or any(n<0 for n in numbers):
                raise ValueError('Unsupported or ambiguous series numbering')
            counts=[int(series['instance_count']) for series in study['series']]
            if any(n<=0 for n in counts) or sum(counts)>10000:
                raise ValueError('Study exceeds bounded DICOM import limits')
        from PacsClient.utils.database import get_db_connection
        from modules.education.course_database import _require_editable
        from modules.education.course_authoring import _snapshot,_digest
        with get_db_connection() as conn:
            conn.row_factory=sqlite3.Row
            before=_snapshot(conn,request.course_pk)
            _require_editable(conn,course_pk=request.course_pk)
        if _digest(before)!=request.expected_digest:
            raise ValueError('Course changed; inspect again')
        slide=next((s for s in before['slides'] if s['slide_pk']==request.slide_pk),None)
        if slide is None:
            raise ValueError('Select an actual course slide')
        existing={i['content_data'].get('study_uid'):i for i in slide['content'] if i['content_type']=='dicom'}
        if len(slide['content'])+sum(s['study_instance_uid'] not in existing for s in selected)>5:
            raise ValueError('Use another slide for more than five resources')
        from PacsClient.utils.config import EDUCATION_STORAGE_PATH
        from modules.network.socket_config import get_socket_config
        from modules.download_manager.network.socket_client import SocketDicomClient
        from modules.download_manager.core.models import SeriesInfo
        cfg=get_socket_config()
        client=SocketDicomClient(host=cfg.get_socket_host(),port=cfg.get_socket_port(),timeout=30)
        resources=[]
        try:
            for study in selected:
                uid=study['study_instance_uid']
                # Canonical UID is checked before using it as a folder component.
                import re
                if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+',uid):
                    raise ValueError('Invalid study identity')
                folder=Path(EDUCATION_STORAGE_PATH)/f'course_{request.course_pk}'/'assets'/'dicom'/uid
                old=existing.get(uid)
                if old:
                    folder=Path(old['content_data']['path'])
                async def download():
                    for series in study['series']:
                        info=SeriesInfo(series_uid=series['series_uid'],series_number=int(series['series_number']),
                            series_description=series.get('series_description') or '',modality=series.get('modality') or '',
                            image_count=int(series['instance_count']))
                        result=await client.download_series(uid,info,folder/str(info.series_number))
                        if not result.success:
                            raise ValueError('DICOM download incomplete')
                asyncio.run(download())
                instances=verify_study(folder,study)
                thumbs=ensure_thumbnails(folder,study)
                resources.append({'name':f'Case {len(resources)+1} - '+('MRI' if any(s.get('modality')=='MR' for s in study['series']) else 'Imaging'),
                    'path':str(folder),'study_uid':uid,'series_number':min(int(s['series_number']) for s in study['series']),
                    'series_count':len(study['series']),'instance_count':instances,'thumbnail_count':thumbs,
                    'description':'Original PACS study: patient, study, series and SOP identity and complete counts verified. Clinical interpretation requires physician review.'})
        finally:
            client.disconnect()
        with get_db_connection() as conn:
            conn.row_factory=sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            try:
                _require_editable(conn,course_pk=request.course_pk)
                if _digest(_snapshot(conn,request.course_pk))!=request.expected_digest:
                    raise ValueError('Course changed; inspect again')
                order=max((i['content_order'] for i in slide['content']),default=0)
                for resource in resources:
                    if resource['study_uid'] not in existing:
                        order+=1
                        conn.execute('INSERT INTO slide_content(slide_fk,content_type,content_order,content_data) VALUES(?,?,?,?)',
                            (request.slide_pk,'dicom',order,json.dumps(resource)))
                conn.execute('UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE course_pk=?',(request.course_pk,))
                after=_snapshot(conn,request.course_pk)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {'course_pk':request.course_pk,'content_digest':_digest(after),'studies':len(resources),
                'instances':sum(r['instance_count'] for r in resources),'series':sum(r['series_count'] for r in resources),
                'thumbnail_count':sum(r['thumbnail_count'] for r in resources),'content_verified':True,
                'native_drag_drop_review':'pending','clinical_review':'pending'}
