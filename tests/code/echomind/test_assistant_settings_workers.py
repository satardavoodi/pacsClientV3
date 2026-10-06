"""Actual Qt delivery and worker persistence with isolated synthetic settings."""
import json
import threading
import time

import pytest
from PySide6.QtCore import QObject, Signal


class Theme(QObject):
    themeChanged = Signal(object)
    def __init__(self):
        super().__init__()
        self._settings = {'active_theme':'Blue', 'custom_theme':{}}
    def current_theme_name(self):
        return self._settings['active_theme']
    def current_theme(self):
        return dict(self._settings)
    def theme_names(self):
        return ['Blue', 'Green']


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait_for(app, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_theme_applies_only_after_worker_persistence(app, tmp_path):
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    theme = Theme()
    service = AssistantSettingsService(theme, lambda: None, theme_path=tmp_path/'theme.json')
    threads = []
    application_threads = []
    theme.themeChanged.connect(lambda _:application_threads.append(threading.get_ident()))
    writer = service._write_theme
    def write(path, data):
        threads.append(threading.get_ident())
        writer(path, data)
    service._write_theme = write
    response = service.set_theme('Green')
    assert response['state'] == 'running'
    assert theme.current_theme_name() == 'Blue'
    wait_for(app, lambda: service.operation_status(response['operation_id'])['state'] == 'succeeded')
    assert theme.current_theme_name() == 'Green'
    assert json.loads((tmp_path/'theme.json').read_text())['active_theme'] == 'Green'
    assert threads and all(thread != threading.get_ident() for thread in threads)
    assert application_threads == [threading.get_ident()]


def test_theme_failure_keeps_old_theme_and_sanitizes_error(app, tmp_path):
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    theme = Theme()
    service = AssistantSettingsService(theme, lambda:None, theme_path=tmp_path/'theme.json')
    def fail(*args):
        raise OSError('synthetic private storage detail')
    service._write_theme = fail
    response = service.set_theme('Green')
    wait_for(app, lambda: service.operation_status(response['operation_id'])['state'] == 'failed')
    assert theme.current_theme_name() == 'Blue'
    assert 'private' not in str(service.operation_status(response['operation_id']))


def test_manual_theme_change_supersedes_pending_request(app, tmp_path):
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    theme = Theme()
    service = AssistantSettingsService(theme, lambda:None, theme_path=tmp_path/'theme.json')
    release = threading.Event()
    writer = service._write_theme
    def write(path, data):
        assert release.wait(2)
        writer(path, data)
    service._write_theme = write
    response = service.set_theme('Green')
    theme._settings = {'active_theme':'Blue', 'custom_theme':{'accent':'synthetic'}}
    release.set()
    wait_for(app, lambda: service.operation_status(response['operation_id'])['state'] == 'superseded')
    assert json.loads((tmp_path/'theme.json').read_text()) == theme._settings


def test_unsupported_theme_never_creates_file(app, tmp_path):
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    service = AssistantSettingsService(Theme(), lambda:None, theme_path=tmp_path/'theme.json')
    with pytest.raises(ValueError):
        service.set_theme('Invented')
    assert not (tmp_path/'theme.json').exists()


def test_cleanup_only_requests_existing_local_confirmation(app):
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    from types import SimpleNamespace
    calls = []
    panel = SimpleNamespace(request_assistant_cleanup=calls.append)
    service = AssistantSettingsService(Theme(), lambda:panel)
    response = service.request_cleanup('cache')
    assert calls == ['cache'] and response['state'] == 'awaiting_local_confirmation'
    assert response['deleted_files'] is None
    with pytest.raises(ValueError):
        service.request_cleanup('patients')


def test_cleanup_dialog_is_deferred_and_duplicate_requests_are_blocked(monkeypatch, app):
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as module
    callbacks = []
    monkeypatch.setattr(module, 'QTimer', SimpleNamespace(singleShot=lambda delay,owner,fn:callbacks.append(fn)))
    panel = SimpleNamespace(_cleanup_thread=None, _handle_cleanup_action=lambda category:False)
    method = module.StorageCleanupPanelWidget.request_assistant_cleanup
    assert method(panel, 'cache') is True
    assert panel._assistant_cleanup_state['state'] == 'awaiting_local_confirmation'
    assert method(panel, 'cache') is False
    callbacks[0]()
    assert panel._assistant_cleanup_state['state'] == 'cancelled_or_blocked'
    assert panel._assistant_cleanup_pending is False


def test_cleanup_completion_counts_come_from_actual_worker_result(monkeypatch, app):
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.settings_ui import storage_cleanup_panel as module
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *args:None)
    panel = SimpleNamespace(_assistant_cleanup_owned=True,
        _assistant_cleanup_state={'state':'running', 'category':'cache'},
        _close_cleanup_progress=lambda:None, refresh_storage_insights=lambda **kwargs:None,
        storageChanged=SimpleNamespace(emit=lambda:None))
    result = SimpleNamespace(success=True, warnings=[], files_deleted=3,
        folders_touched=1, db_rows_affected=0, message='Synthetic cleanup')
    module.StorageCleanupPanelWidget._on_category_cleanup_finished(panel, panel, result)
    assert panel._assistant_cleanup_state == {'state':'succeeded', 'category':'cache',
        'files_deleted':3, 'folders_touched':1, 'db_rows_affected':0}


def test_resource_diagnosis_runs_off_gui_without_deleting_data(monkeypatch, app):
    from types import SimpleNamespace
    import psutil
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    threads = []
    def ram():
        threads.append(threading.get_ident())
        return SimpleNamespace(total=100, available=20, percent=80)
    monkeypatch.setattr(psutil, 'virtual_memory', ram)
    monkeypatch.setattr(psutil, 'disk_usage', lambda _:SimpleNamespace(total=1000, free=50, percent=95))
    monkeypatch.setattr(psutil, 'cpu_percent', lambda interval: 94)
    class Process:
        def cpu_percent(self, interval=None):
            return 180
        def memory_info(self):
            return SimpleNamespace(rss=1234)
    monkeypatch.setattr(psutil, 'Process', Process)
    service = AssistantSettingsService(Theme(), lambda:None)
    response = service.diagnose_resources()
    wait_for(app, lambda: service.operation_status(response['operation_id'])['state'] == 'succeeded')
    data = service.operation_status(response['operation_id'])['data']
    assert data['ram']['used_percent'] == 80
    assert data['app_storage_drive']['free_bytes'] == 50
    assert data['deleted_files'] == 0
    assert data['cpu']['used_percent'] == 94
    assert data['application']['cpu_percent'] == 180
    assert data['application']['resident_bytes'] == 1234
    assert data['assessment']['observations'] == ['high_cpu', 'low_disk_space']
    assert data['assessment']['root_cause_confirmed'] is False
    assert data['assessment']['ticket_submitted'] is False
    assert threads == [threads[0]] and threads[0] != threading.get_ident()
