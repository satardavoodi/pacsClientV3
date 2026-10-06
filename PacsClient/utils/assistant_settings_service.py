"""Asynchronous, bounded settings operations; workers never touch Qt widgets."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from PySide6.QtCore import QObject, Signal, Slot


class AssistantSettingsService(QObject):
    completed = Signal(object)
    modalitiesChanged = Signal(object)
    aiPreferencesChanged = Signal(object)

    def __init__(self, theme_manager, storage_panel_getter, parent=None, theme_path=None):
        super().__init__(parent)
        self._theme = theme_manager
        self._panel = storage_panel_getter
        self._theme_path = theme_path
        self._operations = {}
        self._theme_pending = None
        self.completed.connect(self._finish)

    def get_theme(self):
        return {'active_theme':self._theme.current_theme_name(),
                'themes':self._theme.theme_names()}

    def settings_control(self, action, entities):
        from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_MODELS
        from PacsClient.utils.assistant_settings_repository import SettingsRepository
        values = SETTINGS_CONTROL_MODELS[action].model_validate(entities).model_dump(exclude_none=True)
        key = self._new(action)
        self._run(key, lambda: SettingsRepository().execute(action, values))
        return self.operation_status(key)

    def operation_status(self, operation_id):
        if operation_id not in self._operations:
            raise ValueError('Unknown operation')
        item = self._operations[operation_id]
        return {k:deepcopy(v) for k,v in item.items() if not k.startswith('_')}

    def _new(self, kind):
        if len(self._operations) >= 32:
            completed = [key for key,item in self._operations.items()
                         if item['state'] in ('succeeded', 'failed', 'superseded')]
            if not completed:
                raise ValueError('Too many pending operations')
            del self._operations[completed[0]]
        key = str(uuid4())
        self._operations[key] = {'operation_id':key, 'kind':kind, 'state':'running'}
        return key

    def _run(self, key, fn):
        def run():
            from PacsClient.utils.assistant_settings_repository import SettingsControlError
            try:
                data = fn()
                result = {'operation_id':key, 'ok':True, 'data':data}
            except SettingsControlError as error:
                result = {'operation_id':key, 'ok':False, 'message':str(error)}
            except Exception:
                result = {'operation_id':key, 'ok':False}
            try:
                self.completed.emit(result)
            except RuntimeError:
                pass  # GUI owner has already closed; no widget callbacks.
        threading.Thread(target=run, name='assistant-settings', daemon=True).start()

    @staticmethod
    def _write_theme(path, snapshot):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + str(uuid4()) + '.tmp')
        try:
            temporary.write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def set_theme(self, name):
        if name not in self._theme.theme_names() or self._theme_pending:
            raise ValueError('Unknown theme or theme change pending')
        if name == self._theme.current_theme_name():
            return {'state':'succeeded', 'active_theme':name, 'changed':False}
        from PacsClient.utils.theme_manager import THEME_STORAGE_PATH
        key = self._new('theme')
        item = self._operations[key]
        original = deepcopy(self._theme._settings)
        requested = deepcopy(original)
        requested['active_theme'] = name
        item.update(_original=original, _requested=requested)
        self._theme_pending = key
        self._run(key, lambda: self._write_theme(self._theme_path or THEME_STORAGE_PATH, requested))
        return self.operation_status(key)

    @Slot(object)
    def _finish(self, result):
        key = result['operation_id']
        item = self._operations.get(key)
        if item is None:
            return
        if item['kind'] == 'theme':
            if self._theme._settings != item['_original']:
                # A manual change supersedes the assistant request. Restore the
                # latest user settings off-thread before exposing terminal status.
                from PacsClient.utils.theme_manager import THEME_STORAGE_PATH
                latest = deepcopy(self._theme._settings)
                item.update(_original=latest, _requested=latest, _superseded=True)
                self._run(key, lambda: self._write_theme(self._theme_path or THEME_STORAGE_PATH, latest))
                return
            if result['ok'] and not item.get('_superseded'):
                self._theme._settings = item['_requested']
                self._theme.themeChanged.emit(self._theme.current_theme())
            self._theme_pending = None
        item['state'] = ('superseded' if item.get('_superseded') else 'succeeded') if result['ok'] else 'failed'
        if result['ok']:
            item['data'] = result.get('data') or (self.get_theme() if item['kind'] == 'theme' else {})
            if item['kind'] == 'remove_settings_modalities':
                self.modalitiesChanged.emit(item['data']['modalities'])
            if item['kind'] in ('set_voice_to_text_preferences','set_ai_proxy_preferences','set_personal_ai_preferences','set_eagle_eye_connection'):
                self.aiPreferencesChanged.emit({'action':item['kind'], 'data':item['data']})
        else:
            item['error_code'] = 'SETTINGS_OPERATION_FAILED'
            item['message'] = result.get('message', 'The settings operation failed. Review the local Settings configuration and retry.')

    def diagnose_resources(self):
        existing = next((key for key,item in self._operations.items()
                         if item['kind'] == 'resources' and item['state'] == 'running'), None)
        if existing:
            return self.operation_status(existing)
        key = self._new('resources')
        def probe():
            import psutil
            from PacsClient.utils.data_paths import USER_DATA_ROOT
            process = psutil.Process()
            process.cpu_percent(interval=None)
            cpu = psutil.cpu_percent(interval=0.25)
            app_cpu = process.cpu_percent(interval=None)
            resident = process.memory_info().rss
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage(str(USER_DATA_ROOT))
            observations = []
            if cpu >= 90:
                observations.append('high_cpu')
            if ram.percent >= 90:
                observations.append('high_memory')
            if disk.percent >= 90:
                observations.append('low_disk_space')
            return {'cpu':{'used_percent':cpu, 'sample_seconds':0.25},
                    'application':{'cpu_percent':app_cpu, 'resident_bytes':resident,
                                   'cpu_scale':'100_percent_per_logical_processor'},
                    'ram':{'total_bytes':ram.total, 'available_bytes':ram.available,
                           'used_percent':ram.percent},
                    'app_storage_drive':{'total_bytes':disk.total, 'free_bytes':disk.free,
                                         'used_percent':disk.percent},
                    'deleted_files':0,
                    'assessment':{'observations':observations,
                                  'root_cause_confirmed':False,
                                  'ticket_submitted':False},
                    'recommendation':'Resource readings describe the current sample. Review download and viewer evidence before assigning a cause.'}
        self._run(key, probe)
        return self.operation_status(key)

    def request_cleanup(self, category, strategy=None, value=None):
        if category not in ('cache', 'printing', 'patients'):
            raise ValueError('Unsupported cleanup category')
        from modules.EchoMind.secretary.command_envelope import SettingsCleanupEntities
        SettingsCleanupEntities(category=category, strategy=strategy, value=value)
        panel = self._panel()
        if panel is None:
            raise ValueError('Storage panel is unavailable')
        # Existing panel owns active-work safeguards, confirmation, workers,
        # database consistency and result presentation. Do not bypass them.
        requested = (panel.request_assistant_cleanup(category, strategy=strategy, value=value)
                     if category == 'patients' else panel.request_assistant_cleanup(category))
        if requested is False:
            raise ValueError('Cleanup is already pending')
        return {'state':'awaiting_local_confirmation', 'category':category,
                'deleted_files':None, 'completion_source':'local_storage_panel'}

    def cleanup_status(self):
        panel = self._panel()
        return deepcopy(getattr(panel, '_assistant_cleanup_state', {'state':'idle'}))


    def release_memory(self):
        key = self._new('memory_release')
        def release():
            import psutil
            before = psutil.Process().memory_info().rss
            trimmed = False
            if os.name == 'nt':
                import ctypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.GetCurrentProcess.restype = ctypes.c_void_p
                trim = ctypes.WinDLL('psapi', use_last_error=True).EmptyWorkingSet
                trim.argtypes = [ctypes.c_void_p]
                trim.restype = ctypes.c_int
                trimmed = bool(trim(kernel.GetCurrentProcess()))
            after = psutil.Process().memory_info().rss
            return {'resident_before_bytes':before, 'resident_after_bytes':after,
                    'released_resident_bytes':max(0, before-after),
                    'working_set_trimmed':trimmed,
                    'deleted_files':0, 'scope':'process_working_set',
                    'message':'Active images remain open. Resident memory can grow again during use.'}
        self._run(key, release)
        return self.operation_status(key)

    def get_viewer_preferences(self):
        key = self._new('viewer_preferences')
        def read():
            from modules.viewer.viewer_backend_config import load_viewer_backend
            from modules.viewer.gpu_boost import load_gpu_boost_enabled
            return {'backend':load_viewer_backend(), 'gpu_boost':load_gpu_boost_enabled()}
        self._run(key, read)
        return self.operation_status(key)

    def set_viewer_preferences(self, backend=None, gpu_boost=None):
        if backend is not None and backend not in ('pydicom_2d', 'pydicom_qt', 'vtk_simpleitk'):
            raise ValueError('Unknown viewer backend')
        if gpu_boost is not None and type(gpu_boost) is not bool:
            raise ValueError('GPU boost must be boolean')
        key = self._new('viewer_preferences')
        def write():
            from modules.viewer.viewer_backend_config import load_viewer_backend, save_viewer_backend
            from modules.viewer.gpu_boost import load_gpu_boost_enabled, save_gpu_boost_enabled
            if backend is not None:
                save_viewer_backend(backend)
            if gpu_boost is not None:
                save_gpu_boost_enabled(gpu_boost)
            actual = {'backend':load_viewer_backend(), 'gpu_boost':load_gpu_boost_enabled()}
            if ((backend is not None and actual['backend'] != backend)
                    or (gpu_boost is not None and actual['gpu_boost'] != gpu_boost)):
                raise ValueError('Viewer preferences did not persist')
            return dict(actual, restart_required=True, active_viewers_changed=False)
        self._run(key, write)
        return self.operation_status(key)
