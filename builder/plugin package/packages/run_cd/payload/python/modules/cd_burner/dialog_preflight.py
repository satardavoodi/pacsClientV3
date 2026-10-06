"""Worker-only data preparation for the existing CD configuration dialog."""
from types import SimpleNamespace
from pathlib import Path
from copy import deepcopy


def prepare_dialog(studies):
    import comtypes
    from .cd_burn_dialog import CDBurnDialog, _get_light_viewer_widget, _fallback_viewer_selection
    from .cd_burn_manager import CDBurnManager, get_available_drives, check_imapi2_available
    from .dicomdir_builder import check_pydicom_available
    from .center_identity import load_center_identity
    from database.manager import get_study_info_with_series
    comtypes.CoInitialize()
    try:
        studies = deepcopy(studies)
        probe = SimpleNamespace(studies=studies)
        probe._has_dicom_files = lambda path: CDBurnDialog._has_dicom_files(probe, path)
        downloaded, missing = CDBurnDialog._check_download_status(probe)
        manager = CDBurnManager()
        try:
            viewer = _get_light_viewer_widget().get_viewer_selection()
        except Exception:
            viewer = _fallback_viewer_selection()
        series = {}
        from .media_readiness import study_files_ready
        from modules.download_manager.state.state_store import get_state_store
        state_store = get_state_store()
        ready, incomplete = [], list(missing)
        for study in downloaded:
            uid = str(study.get('study_uid') or '')
            series[uid] = (get_study_info_with_series(uid) or {}).get('series', [])
            expected = max(int(study.get('images_count') or study.get('image_count') or 0),
                           sum(int(row.get('image_count') or 0) for row in series[uid]))
            transfer = state_store.get(uid)
            if transfer is not None:
                expected = max(expected, int(transfer.total_count or 0))
            transfer_ready = transfer is None or transfer.status.name == 'COMPLETED'
            if transfer_ready and study_files_ready(study, expected):
                ready.append(study)
            else:
                incomplete.append(study)
        downloaded, missing = ready, incomplete
        drives = get_available_drives()
        media = {d['id']: manager.get_media_info(d['id']) for d in drives}
        speeds = {d['id']: manager.get_write_speeds(d['id']) for d in drives}
        viewer_mb = 0
        if viewer.get('path'):
            viewer_mb = sum(p.stat().st_size for p in Path(viewer['path']).parent.rglob('*')
                            if p.is_file()) / (1024 * 1024)
        return {'studies': studies, 'downloaded': downloaded, 'missing': missing,
                'size_mb': manager.get_studies_size_estimate(downloaded),
                'identity': load_center_identity(), 'viewer': viewer, 'series': series,
                'drives': drives, 'media': media, 'speeds': speeds, 'viewer_mb': viewer_mb,
                'portability': manager.inspect_viewer_portability(viewer.get('path')),
                'pydicom': check_pydicom_available(), 'imapi': check_imapi2_available()}
    finally:
        comtypes.CoUninitialize()


def open_dialog(studies, parent):
    """Home entry: prepare filesystem/COM data without blocking the GUI thread."""
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QProgressDialog, QMessageBox
    from PacsClient.utils.support_diagnostics import OperationStore
    from .cd_burn_dialog import CDBurnDialog
    existing = getattr(parent, '_cd_burn_dialog', None)
    if existing is not None and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return
    pending = getattr(parent, '_cd_burn_preflight', None)
    if pending is not None and pending.isVisible():
        return
    selected = deepcopy(studies)
    store = OperationStore()
    operation = store.start('cd_dialog_preflight', lambda: prepare_dialog(selected))['operation_id']
    progress = QProgressDialog('Checking selected studies and CD/DVD drives...', 'Cancel', 0, 0, parent)
    progress.setWindowTitle('Write to CD/DVD')
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    parent._cd_burn_preflight = progress
    timer = QTimer(progress)

    def ready():
        result = store.status(operation)
        if result['state'] == 'running':
            return
        timer.stop()
        progress.close()
        if result['state'] != 'succeeded':
            QMessageBox.warning(parent, 'CD Preparation', 'Unable to check the selected studies or media drives. Please try again.')
            return
        try:
            prepared = result['data']
            dialog = CDBurnDialog(prepared['studies'], parent, prepared=prepared)
            parent._cd_burn_dialog = dialog
            dialog.open()
        except Exception:
            QMessageBox.warning(parent, 'CD Preparation', 'Unable to open the CD/DVD dialog. Please try again.')

    timer.timeout.connect(ready)
    progress.canceled.connect(timer.stop)
    timer.start(100)
    progress.show()
