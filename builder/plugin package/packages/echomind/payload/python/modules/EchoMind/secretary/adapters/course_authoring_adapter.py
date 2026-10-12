"""Thin shared Education command adapter; content I/O stays on workers."""
from ..command_envelope import CommandResult
from modules.ai_imaging.eagle_eye_remote.secretary.validation.course_authoring import COURSE_AUTHORING_MODELS

COURSE_AUTHORING_ACTIONS = {action:'execute' for action in COURSE_AUTHORING_MODELS}


class CourseAuthoringAdapter:
    def __init__(self, launcher, service=None):
        from modules.education.course_authoring import CourseAuthoringService
        self.service = service or CourseAuthoringService()
        self._launcher = launcher
        self._pending_ui = {}
        self._windows = []
        self._widget = None
        self._ui_results = {}

    def _editor_busy(self):
        page = getattr(self._widget,'build_page',None)
        return page is not None and page.command_authoring_busy()

    def execute(self, plan, state):
        action = plan.action
        try:
            entities = COURSE_AUTHORING_MODELS[action].model_validate(plan.entities or {})
            if action == 'prepare_course_draft':
                data = self.service.prepare(entities.model_dump())
            elif action == 'update_course_draft':
                data = self.service.update(entities.draft_id,entities.expected_revision,
                    entities.fields.model_dump(exclude_unset=True),
                    [s.model_dump(exclude_unset=True) for s in entities.slides])
            elif action == 'get_course_draft':
                data = self.service.get(entities.draft_id)
            elif action == 'load_course_draft':
                data = self.service.load(entities.course_pk)
            elif action == 'save_course_draft':
                # Opening the singleton also exposes unsaved human edits before a write.
                self._widget = self._launcher({})
                if self._widget is None:
                    raise ValueError('MODULE_UNAVAILABLE')
                if self._editor_busy():
                    raise ValueError('COURSE_EDITOR_DIRTY')
                data = self.service.save(entities.draft_id,entities.expected_revision)
            elif action in {'open_course_editor','preview_course'}:
                self.service.saved_course(entities.draft_id)
                self._widget = self._launcher({})
                if self._widget is None:
                    raise ValueError('MODULE_UNAVAILABLE')
                if action == 'open_course_editor' and self._editor_busy():
                    raise ValueError('COURSE_EDITOR_DIRTY')
                data = self.service.check_saved(entities.draft_id)
                self._pending_ui[data['operation_id']] = (action,entities.draft_id)
            else:
                data = self.service.status(entities.operation_id)
                pending = self._pending_ui.get(entities.operation_id)
                if pending and data['state'] != 'pending':
                    del self._pending_ui[entities.operation_id]
                    if data['state'] == 'succeeded':
                        kind,handle = pending
                        course = self.service.saved_course(handle)
                        if kind == 'open_course_editor':
                            page = self._widget.build_page
                            if self._editor_busy() or not page.load_course_for_edit(course['course_pk'],prepared_course=course):
                                raise ValueError('COURSE_EDITOR_DIRTY')
                            self._widget.tab_widget.setCurrentWidget(page)
                            data = dict(data,editor_loaded=True)
                        else:
                            from modules.education.presentation_window import CoursePresentationWindow
                            window = CoursePresentationWindow(course,self._widget)
                            self._windows.append(window)
                            window.destroyed.connect(lambda *_: self._windows.remove(window) if window in self._windows else None)
                            window.show()
                            data = dict(data,preview_opened=True,render_review='pending')
                        # Poll retries return the same UI receipt without reopening windows.
                        self._ui_results[entities.operation_id] = data
                if entities.operation_id in getattr(self,'_ui_results',{}):
                    data = self._ui_results[entities.operation_id]
            ok = data.get('state') != 'failed'
            return CommandResult(ok=ok,action=action,data=data,
                error_code=data.get('error_code') if not ok else None,
                message='Course authoring operation queued.' if data.get('state')=='pending' else 'Course authoring result ready.')
        except Exception as exc:
            allowed = {'DRAFT_NOT_FOUND','DRAFT_LOADING','DRAFT_LIMIT','DRAFT_BUSY','REVISION_CONFLICT',
                'INCOMPLETE_DRAFT','INVALID_SLIDE_ORDER','INVALID_SLIDE_VALUE','COURSE_TOO_LARGE',
                'COURSE_CHANGED','COURSE_READ_ONLY','COURSE_NOT_FOUND','OPERATION_NOT_FOUND',
                'AUTHORING_BUSY','UNSAVED_DRAFT','COURSE_EDITOR_DIRTY','MODULE_UNAVAILABLE'}
            code = str(exc) if str(exc) in allowed else 'INVALID_COURSE_COMMAND'
            if action == 'course_authoring_status':
                operation_id = (plan.entities or {}).get('operation_id')
                if operation_id:
                    self._ui_results[operation_id] = {'state':'failed','error_code':code}
            return CommandResult(ok=False,action=action,error_code=code,message='Course command could not complete. Review the draft and retry.')
