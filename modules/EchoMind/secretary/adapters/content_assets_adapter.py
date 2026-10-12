"""Thin shared MCP/Secretary commands; all network, file and DB I/O uses workers."""
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

from modules.ai_imaging.eagle_eye_remote.secretary.validation.content_assets import CONTENT_ASSET_MODELS, WEB_MODELS
from ..command_envelope import CommandResult


class ContentAssetsAdapter:
    def __init__(self, memory_getter, education_launcher=None):
        self.memory_getter=memory_getter
        self.education_launcher=education_launcher
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='secretary-content-assets')
        self.operations={}
        from ..course_dicom import CourseDicom
        self.dicom=CourseDicom()

    def execute(self, plan, state):
        entities=CONTENT_ASSET_MODELS[plan.action].model_validate(plan.entities or {})
        memory=self.memory_getter()
        if memory is None:
            return CommandResult(ok=False,action=plan.action,error_code='SESSION_UNAVAILABLE')
        session=memory.get_conversation()['id']
        if plan.action=='content_asset_status':
            record=self.operations.get(entities.operation_id)
            if record is None or record[0]!=session:
                return CommandResult(ok=False,action=plan.action,error_code='ASSET_OPERATION_NOT_FOUND')
            future=record[1]
            if not future.done():
                data={'operation_id':entities.operation_id,'state':'pending'}
            else:
                try:
                    data={'operation_id':entities.operation_id,'state':'succeeded',**future.result()}
                except Exception:
                    return CommandResult(ok=False,action=plan.action,error_code='CONTENT_ASSET_FAILED',
                        data={'operation_id':entities.operation_id,'state':'failed'},
                        message='Content operation failed. Check server availability, file limits, selected course and source permissions.')
            return CommandResult(ok=True,action=plan.action,data=data)
        if plan.action in {'attach_course_asset','organize_course_content','import_course_dicom'} and self.education_launcher:
            widget=self.education_launcher({})
            page=getattr(widget,'build_page',None)
            if page is not None and page.command_authoring_busy():
                return CommandResult(ok=False,action=plan.action,error_code='COURSE_EDITOR_DIRTY')
        if len(self.operations)>=64:
            self.operations={k:v for k,v in self.operations.items() if not v[1].done()}
            if len(self.operations)>=64:
                return CommandResult(ok=False,action=plan.action,error_code='CONTENT_ASSETS_BUSY')
        def work():
            from ..content_assets import inspect_course,attach_asset,receive_asset,organize_course
            if plan.action=='find_course_dicom':
                return self.dicom.find(session,entities.patient_ids)
            if plan.action=='import_course_dicom':
                return self.dicom.import_studies(session,entities)
            if plan.action=='organize_course_content':
                return organize_course(entities)
            if plan.action=='inspect_course_content':
                return inspect_course(entities.course_pk)
            if plan.action=='attach_course_asset':
                return attach_asset(session,entities)
            from modules.ai_imaging.eagle_eye_remote.client import Client
            payload={'action':plan.action,'session_id':session,**entities.model_dump()}
            with Client().open('/v1/secretary/assets',payload,timeout=240) as response:
                raw=response.read(12*1024*1024+1)
            if len(raw)>12*1024*1024:
                raise ValueError('Server asset response too large')
            result=json.loads(raw)
            if result.get('session_id')!=session:
                raise ValueError('Server session mismatch')
            if 'file' in result:
                return receive_asset(session,result['file'])
            return result
        handle=uuid4().hex
        self.operations[handle]=(session,self.pool.submit(work))
        return CommandResult(ok=True,action=plan.action,data={'operation_id':handle,'state':'pending'})

    def close(self):
        self.pool.shutdown(wait=False,cancel_futures=True)
