"""Media continuation must wait for every selected transfer and file validation."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


def test_dialog_does_not_skip_missing_study_in_mixed_selection(monkeypatch):
    from modules.cd_burner.cd_burn_dialog import CDBurnDialog
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    owner = SimpleNamespace(is_burning=False, downloaded_studies=[{'study_uid': 'one'}],
        not_downloaded_studies=[{'study_uid': 'two'}], studies=[{}, {}], drive_combo=Mock(),
        disc_label_edit=Mock(), _build_options=Mock(), include_viewer_cb=Mock(),
        _confirm_viewer_available=Mock(return_value=True), _options_summary=Mock(return_value=''),
        _get_viewer_launch_summary=Mock(return_value=''), burn_btn=Mock(), prepare_btn=Mock(),
        cancel_btn=Mock(), log_output=Mock(), burn_manager=Mock(), _current_series_selection=Mock(),
        _start_auto_download=Mock(), _set_media_busy=Mock())
    owner.include_viewer_cb.isChecked.return_value = False
    CDBurnDialog._execute_burn(owner)
    owner._start_auto_download.assert_called_once()
    owner.burn_manager.prepare_and_burn.assert_not_called()


def coordinator(qapp, states):
    from modules.cd_burner.download_before_media import DownloadBeforeMedia
    manager = SimpleNamespace(state_store=SimpleNamespace(get=states.get))
    store = SimpleNamespace(start=Mock(return_value={'operation_id': 'check'}),
                            status=Mock(return_value={'state': 'running'}))
    job = DownloadBeforeMedia(manager, ['one', 'two'], lambda: {}, store=store)
    job.start()
    return job, store


def state(status, percent=0):
    return SimpleNamespace(status=SimpleNamespace(name=status), progress_percent=percent)


def test_mixed_selection_waits_for_all_and_continues_once(qapp):
    states = {'one': state('COMPLETED'), 'two': state('DOWNLOADING', 50)}
    job, store = coordinator(qapp, states)
    ready = Mock()
    job.ready.connect(ready)
    job.poll()
    store.start.assert_not_called()
    states['two'] = state('COMPLETED')
    job.poll()
    job.poll()
    store.start.assert_called_once()
    store.status.return_value = {'state': 'succeeded', 'data': {'missing': [], 'studies': [1, 2]}}
    job.poll()
    job.poll()
    ready.assert_called_once()


@pytest.mark.parametrize('status', ['FAILED', 'CANCELLED'])
def test_failed_transfer_never_starts_media(qapp, status):
    job, store = coordinator(qapp, {'one': state(status)})
    failed = Mock()
    job.failed.connect(failed)
    job.poll()
    failed.assert_called_once()
    store.start.assert_not_called()


def test_cancel_ignores_late_validation_without_cancelling_shared_download(qapp):
    job, store = coordinator(qapp, {'one': state('COMPLETED'), 'two': state('COMPLETED')})
    ready = Mock()
    job.ready.connect(ready)
    job.poll()
    job.cancel()
    store.status.return_value = {'state': 'succeeded', 'data': {'missing': [], 'studies': []}}
    job.poll()
    ready.assert_not_called()


def test_files_still_missing_after_terminal_signal_blocks_media(qapp):
    job, store = coordinator(qapp, {'one': state('COMPLETED'), 'two': state('COMPLETED')})
    ready, failed = Mock(), Mock()
    job.ready.connect(ready)
    job.failed.connect(failed)
    job.poll()
    store.status.return_value = {'state': 'succeeded', 'data': {'missing': [{'study_uid': 'two'}]}}
    job.poll()
    ready.assert_not_called()
    failed.assert_called_once()


def test_media_requires_expected_unique_instances_and_matching_identity(tmp_path):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage
    from modules.cd_burner.media_readiness import study_files_ready
    folder = tmp_path / 'study'
    folder.mkdir()
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = '1.2.3.1'
    ds = FileDataset(None, {}, file_meta=meta, preamble=b'\0' * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = '1.2.3'
    ds.PatientID = 'synthetic'
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(folder / 'first.dcm', write_like_original=False)
    study = {'study_path': str(folder), 'study_uid': '1.2.3', 'patient_id': 'synthetic'}
    assert study_files_ready(study, 1)
    assert not study_files_ready(study, 2)
    ds.save_as(folder / 'duplicate.dcm', write_like_original=False)
    assert not study_files_ready(study, 2)
    assert not study_files_ready({**study, 'study_uid': '1.2.4'}, 1)
    assert not study_files_ready({**study, 'patient_id': 'another'}, 1)


def test_queue_timeout_never_continues(qapp, monkeypatch):
    job, store = coordinator(qapp, {})
    failed = Mock()
    job.failed.connect(failed)
    monkeypatch.setattr('modules.cd_burner.download_before_media.time.monotonic', lambda: job.started + 181)
    job.poll()
    failed.assert_called_once()
    store.start.assert_not_called()


def test_reentrant_cancel_from_progress_does_not_start_validation(qapp):
    job, store = coordinator(qapp, {'one': state('COMPLETED'), 'two': state('COMPLETED')})
    job.progress.connect(lambda *args: job.cancel())
    job.poll()
    store.start.assert_not_called()


def test_real_dialog_retains_options_and_auto_continues_without_second_confirmation(qapp, monkeypatch):
    from modules.cd_burner.cd_burn_dialog import CDBurnDialog
    from PySide6.QtWidgets import QMessageBox
    rows = [{'study_uid': '1.2.3', 'patient_id': 'synthetic'}]
    prepared = dict(studies=rows, downloaded=[], missing=rows, viewer={'path': None, 'display_name': 'None'},
                    series={}, size_mb=0, identity={}, drives=[{'id': 'drive', 'name': 'Synthetic'}],
                    media={}, speeds={}, viewer_mb=0, pydicom=True, imapi=True, portability={})
    dialog = CDBurnDialog(rows, prepared=prepared)
    dialog.include_viewer_cb.setChecked(False)
    from modules.cd_burner.cd_burn_manager import BurnOptions
    monkeypatch.setattr(dialog, '_build_options', Mock(return_value=BurnOptions()))
    question = Mock(return_value=QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, 'question', question)
    download = Mock()
    monkeypatch.setattr(dialog, '_start_auto_download', download)
    write = Mock()
    monkeypatch.setattr(dialog.burn_manager, 'prepare_and_burn', write)
    dialog.start_burn()
    download.assert_called_once_with('burn')
    write.assert_not_called()
    assert question.call_count == 1
    approved = dialog._approved_burn['options']
    # The normal download-completion slot updates prepared inputs and resumes.
    dialog._media_action = ('burn', None)
    dialog._on_media_download_ready({**prepared, 'downloaded': rows, 'missing': [], 'size_mb': 1})
    write.assert_called_once()
    assert write.call_args.kwargs['options'] is approved
    assert write.call_args.kwargs['studies'] == rows
    assert question.call_count == 1
    dialog.is_burning = False
    dialog.close()


def test_dialog_keeps_download_progress_and_cancel_inside_popup(qapp, monkeypatch):
    from modules.cd_burner.cd_burn_dialog import CDBurnDialog
    from modules.cd_burner.cd_burn_manager import BurnOptions
    from PySide6.QtWidgets import QWidget, QMessageBox
    home = QWidget()
    manager = SimpleNamespace(state_store=SimpleNamespace(get=lambda uid: state('DOWNLOADING', 50)))
    home.data_access_panel_widget = SimpleNamespace(get_server_selected=lambda: {'server_type': 'socket'})
    home._get_or_create_download_manager_tab = Mock(return_value=manager)
    home._reset_stale_terminal_dm_state = Mock()
    home._on_download_requested = Mock()
    rows = [{'study_uid': '1.2.3', 'patient_id': 'synthetic'}]
    prepared = dict(studies=rows, downloaded=[], missing=rows, viewer={'path': None, 'display_name': 'None'},
                    series={}, size_mb=0, identity={}, drives=[{'id': 'drive', 'name': 'Synthetic'}],
                    media={}, speeds={}, viewer_mb=0, pydicom=True, imapi=True, portability={})
    dialog = CDBurnDialog(rows, home, prepared=prepared)
    dialog.include_viewer_cb.setChecked(False)
    monkeypatch.setattr(dialog, '_build_options', lambda: BurnOptions())
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    dialog.show()
    dialog.start_burn()
    home._on_download_requested.assert_called_once_with(rows, set_current_tab=False)
    assert dialog.isVisible()
    assert not dialog.burn_btn.isEnabled()
    dialog._media_download.poll()
    assert dialog.progress_bar.value() == 50
    dialog.cancel_or_close()
    assert not dialog._media_download.active
    assert dialog.isVisible()
    assert 'Shared downloads continue' in dialog.progress_message.text()
    dialog.close()
    home.close()


def test_home_preflight_runs_off_gui_thread_and_uses_prepared_dialog(qapp, monkeypatch):
    import threading
    import time
    from PySide6.QtWidgets import QWidget
    from modules.cd_burner import dialog_preflight, cd_burn_dialog
    caller = threading.get_ident()
    worker_threads = []
    rows = [{'study_uid': 'synthetic'}]
    result = {'studies': rows}
    def prepare(studies):
        worker_threads.append(threading.get_ident())
        return result
    monkeypatch.setattr(dialog_preflight, 'prepare_dialog', prepare)
    dialog = Mock()
    constructor = Mock(return_value=dialog)
    monkeypatch.setattr(cd_burn_dialog, 'CDBurnDialog', constructor)
    home = QWidget()
    dialog_preflight.open_dialog(rows, home)
    deadline = time.monotonic() + 3
    while not dialog.open.called and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert worker_threads and worker_threads[0] != caller
    constructor.assert_called_once_with(rows, home, prepared=result)
    dialog.open.assert_called_once()
    home.close()
