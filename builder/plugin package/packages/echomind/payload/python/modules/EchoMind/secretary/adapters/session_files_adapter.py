"""Shared MCP/CommandBus attachment operations, with worker-only I/O and AI."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from modules.ai_imaging.eagle_eye_remote.secretary.validation.session_files import SESSION_FILE_MODELS


class SessionFilesAdapter:
    def __init__(self, memory_getter):
        self._memory_getter = memory_getter
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='secretary-files')
        self._operations = {}

    def execute(self, plan, state):
        from ..command_envelope import CommandResult
        entities = SESSION_FILE_MODELS[plan.action].model_validate(plan.entities or {})
        if plan.action == 'session_file_status':
            operation = self._operations.get(entities.operation_id)
            if operation is None:
                return CommandResult(ok=False,action=plan.action,error_code='SESSION_FILE_OPERATION_NOT_FOUND')
            session, future = operation
            memory = self._memory_getter()
            if memory is None or memory.get_conversation()['id'] != session:
                return CommandResult(ok=False,action=plan.action,error_code='SESSION_CHANGED')
            if not future.done():
                data = {'operation_id':entities.operation_id,'state':'pending'}
            else:
                try:
                    data = {'operation_id':entities.operation_id,'state':'succeeded',**future.result()}
                except Exception:
                    return CommandResult(ok=False,action=plan.action,error_code='SESSION_FILES_FAILED',message='Session file operation failed. Check file limits and Eagle Eye connectivity.')
            return CommandResult(ok=True,action=plan.action,data=data)
        memory = self._memory_getter()
        if memory is None:
            return CommandResult(ok=False,action=plan.action,error_code='SESSION_UNAVAILABLE')
        conversation = memory.get_conversation()
        if len(self._operations) >= 32:
            self._operations = {k:v for k,v in self._operations.items() if not v[1].done()}
            if len(self._operations) >= 32:
                return CommandResult(ok=False,action=plan.action,error_code='SESSION_FILES_BUSY')
        handle = uuid4().hex
        def work():
            from ..session_files import SessionFiles
            sources = SessionFiles().snapshot(conversation['id'])
            if plan.action == 'list_session_files':
                return {'session_id':conversation['id'],'files':[
                    {'name':s['name'],'sha256':s['sha256']} for s in sources]}
            selected = [s for s in sources if s['sha256']==entities.sha256]
            if not selected:
                raise ValueError('Session file not found or changed')
            from .. import remote_planner
            if not remote_planner.uses_server():
                raise ValueError('Session file inspection requires Eagle Eye Server')
            reply = remote_planner.request('plan',entities.question,
                interaction_mode='ask',conversation=dict(conversation,mode='ask'),session_sources=selected)
            return {'session_id':conversation['id'],'answer':reply['answer'],'files':reply['session_sources']}
        self._operations[handle] = (conversation['id'],self._pool.submit(work))
        return CommandResult(ok=True,action=plan.action,data={'operation_id':handle,'state':'pending'})

    def close(self):
        self._pool.shutdown(wait=False,cancel_futures=True)
