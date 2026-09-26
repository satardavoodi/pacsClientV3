"""Study-scoped Eagle Eye control through the existing workspace and viewer adapters.

No screen coordinates, DICOM reads, model execution or network I/O in this adapter.
Commands execute on the CommandBus GUI thread; the existing widgets own their workers.
"""
from ..command_envelope import CommandPlan, CommandResult

ACTIONS = {name:name for name in (
    'eagle_eye_open', 'eagle_eye_series', 'eagle_eye_select_series',
    'eagle_eye_functions', 'eagle_eye_run', 'eagle_eye_status', 'eagle_eye_inputs')}

class EagleEyeCommandAdapter:
    def __init__(self, launcher):
        self._launcher = launcher
        self._windows = {}
        self._selected = {}

    def _result(self, plan, data=None, error=None):
        return CommandResult(ok=error is None, action=plan.action, data=data,
                             error_code=error, message=error or '')

    def _window(self, plan):
        uid = str(plan.entities.get('study_uid') or '').strip()
        window = self._windows.get(uid)
        if window is not None:
            try:
                from PySide6.QtCore import QObject
                from shiboken6 import isValid
                if isinstance(window, QObject) and not isValid(window):
                    self._windows.pop(uid, None)
                    return None
            except ImportError:
                pass
        return window

    def eagle_eye_open(self, plan, state):
        uid = str(plan.entities.get('study_uid') or '').strip()
        if not uid:
            return self._result(plan, error='STUDY_REQUIRED')
        window = self._window(plan)
        if window is None:
            window = self._launcher({'study_uid':uid})
            if window is None:
                return self._result(plan, error='WORKSPACE_UNAVAILABLE')
            if str(getattr(window, '_study_uid', '')) != uid:
                return self._result(plan, error='STUDY_MISMATCH')
            self._windows[uid] = window
        if callable(getattr(window, 'show', None)): window.show()
        return self._result(plan, {'study_uid':uid, 'state':'workspace_open'})

    def eagle_eye_series(self, plan, state):
        window = self._window(plan)
        if window is None: return self._result(plan, error='OPEN_WORKSPACE_FIRST')
        from .viewer_command_adapter import ViewerCommandAdapter
        patient = getattr(getattr(window, 'imaging_tab', None), 'patient_widget', None)
        result = ViewerCommandAdapter(lambda:patient).get_thumbnails_data(plan, state)
        result.action = plan.action
        if result.ok:
            inventory = getattr(patient, 'lst_thumbnails_data', []) or []
            for row, source in zip(result.data['rows'], [x for x in inventory if isinstance(x, dict)]):
                metadata = source.get('metadata') or {}
                series = metadata.get('series') or {}
                row['description'] = str(series.get('series_description') or '')
                row['protocol'] = str(series.get('protocol_name') or '')
                row['body_part'] = str(series.get('body_part_examined') or '')
        return result

    def eagle_eye_select_series(self, plan, state):
        uid = str(plan.entities.get('series_uid') or '')
        if not uid: return self._result(plan, error='SERIES_UID_REQUIRED')
        listing = self.eagle_eye_series(plan, state)
        if not listing.ok: return listing
        rows = [r for r in listing.data['rows'] if r['series_uid'] == uid]
        if len(rows) != 1: return self._result(plan, error='SERIES_NOT_UNIQUE')
        study = str(plan.entities.get('study_uid') or '')
        if rows[0]['study_uid'] != study:
            return self._result(plan, error='STUDY_MISMATCH')
        from .viewer_write_adapter import ViewerWriteCommandAdapter
        window = self._window(plan)
        result = ViewerWriteCommandAdapter(lambda:window.imaging_tab.patient_widget).change_series(plan, state)
        if result.ok: self._selected[study] = uid
        result.action = plan.action
        return result

    def _context(self, plan):
        window = self._window(plan)
        if window is None: return None, None
        from modules.ai_imaging.eagle_eye_function_dialog import active_viewer_context
        context = active_viewer_context(window.imaging_tab.patient_widget)
        if context['study_uid'] != str(plan.entities.get('study_uid')):
            return window, None
        return window, context

    def eagle_eye_functions(self, plan, state):
        window, context = self._context(plan)
        if not context or not context['series_uid']:
            return self._result(plan, error='SERIES_NOT_READY')
        from dataclasses import asdict
        from modules.ai_imaging.eagle_eye_function_catalog import function_options_for_modality
        return self._result(plan, {'series_uid':context['series_uid'], 'functions':[
            asdict(x) for x in function_options_for_modality(context['modality'], context['eagle_eye_mode'])]})

    def eagle_eye_run(self, plan, state):
        window, context = self._context(plan)
        requested = str(plan.entities.get('series_uid') or '')
        if not context or not requested or context['series_uid'] != requested:
            return self._result(plan, error='SERIES_NOT_READY')
        controller = getattr(window, 'workspace_controller', None)
        if controller is None: return self._result(plan, error='WORKSPACE_UNAVAILABLE')
        try:
            data = controller.run_controlled(str(plan.entities.get('function') or ''), plan.entities.get('inputs'))
        except ValueError as error:
            return self._result(plan, {'reason':str(error)}, error='FUNCTION_NOT_READY')
        return self._result(plan, data)

    def eagle_eye_status(self, plan, state):
        window = self._window(plan)
        controller = getattr(window, 'workspace_controller', None)
        if controller is None: return self._result(plan, error='OPEN_WORKSPACE_FIRST')
        return self._result(plan, controller.control_status())

    def eagle_eye_inputs(self, plan, state):
        window = self._window(plan)
        controller = getattr(window, 'workspace_controller', None)
        if controller is None: return self._result(plan, error='OPEN_WORKSPACE_FIRST')
        uid = str(plan.entities.get('series_uid') or '')
        if not uid or uid != getattr(controller, '_controlled_series_uid', None):
            return self._result(plan, error='SERIES_MISMATCH')
        try:
            return self._result(plan, controller.apply_control_inputs(plan.entities.get('inputs') or {}))
        except ValueError as error:
            return self._result(plan, {'reason':str(error)}, error='INVALID_INPUTS')
