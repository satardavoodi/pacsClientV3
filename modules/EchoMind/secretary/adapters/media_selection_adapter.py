"""Existing CD worker controlled with exact-selection receipts and explicit confirmation."""
import uuid
from pathlib import Path
from PySide6.QtCore import QObject, QEvent, QTimer, QCoreApplication
from ..command_envelope import CommandResult
from PacsClient.utils.support_diagnostics import OperationStore

# Keep running QThreads alive even when a control caller releases its bus.
_RUNNING_WORKERS = set()


class _MediaQuitGuard(QObject):
    """Defer a requested app exit asynchronously until cancellation finishes."""
    def __init__(self,app,adapter):
        super().__init__(app)
        self.app=app
        self.adapter=adapter
        self.exiting=False
        app.installEventFilter(self)

    def eventFilter(self,obj,event):
        worker=self.adapter.worker
        home=getattr(self.adapter.selections,'home',None)
        window=home.window() if home is not None and hasattr(home,'window') else None
        exit_event=event.type()==QEvent.Type.Quit or (
            event.type()==QEvent.Type.Close and window is not None and obj is window)
        if exit_event and worker is not None and worker.isRunning():
            self.exiting=True
            worker.cancel()
            event.ignore()
            return True
        return False

    def resume_exit(self):
        if self.exiting:
            self.app.removeEventFilter(self)
            QTimer.singleShot(0,self.app.quit)


class MediaSelectionAdapter:
    def __init__(self, selections):
        self.selections=selections
        self.operations={}
        self.worker=None
        self.probes=OperationStore()
        self.preparations={}
        self.dialog=None

    def prepare_selection_media(self,plan,state):
        from aipacs_runtime import is_module_enabled
        if not is_module_enabled('run_cd'):
            return CommandResult(ok=False,action=plan.action,error_code='MODULE_UNAVAILABLE')
        if self.dialog is not None and self.dialog.isVisible():
            return CommandResult(ok=False,action=plan.action,error_code='MEDIA_DIALOG_OPEN')
        handle=plan.entities['selection_id']
        rows=self.selections.selected(handle)
        if rows is None:
            return CommandResult(ok=False,action=plan.action,error_code='STALE_SELECTION')
        from modules.cd_burner.dialog_preflight import prepare_dialog
        receipt=self.probes.start('prepare_selection_media',lambda:prepare_dialog(rows))
        key=receipt['operation_id']
        self.preparations[key]=handle
        return CommandResult(ok=True,action=plan.action,
                             data={'operation_id':key,'state':'running'})

    def media_drives(self,plan,state):
        def collect():
            from modules.cd_burner.cd_writer import get_available_drives
            import comtypes
            comtypes.CoInitialize()
            try:
                return {'drives':get_available_drives()}
            finally:
                comtypes.CoUninitialize()
        receipt=self.probes.start('media_drives',collect)
        handle=receipt['operation_id']
        return CommandResult(ok=True,action=plan.action,data={'operation_id':handle,'state':'running'})

    def media_status(self,plan,state):
        key=plan.entities['operation_id']
        data=self.operations.get(key)
        if data is None:
            try:
                data=self.probes.status(key)
            except ValueError:
                data=None
        if key in self.preparations and data is not None:
            if data['state']=='succeeded':
                selection=self.selections.selected(self.preparations[key])
                if selection is None:
                    data={'operation_id':key,'state':'failed','error_code':'STALE_SELECTION'}
                else:
                    prepared=data['data']
                    from modules.cd_burner.cd_burn_dialog import CDBurnDialog
                    self.dialog=CDBurnDialog(prepared['studies'],self.selections.home,prepared=prepared)
                    self.dialog.open()
                    data={'operation_id':key,'state':'succeeded','dialog_open':True,
                          'selected_count':len(selection),
                          'downloaded_count':len(prepared['downloaded']),
                          'missing_count':len(prepared['missing'])}
                self.operations[key]=data
                del self.preparations[key]
            else:
                data={k:v for k,v in data.items() if k in ('operation_id','state','error_code')}
        return CommandResult(ok=data is not None,action=plan.action,data=data,
                             error_code=None if data is not None else 'UNKNOWN_OPERATION')

    def write_selection_media(self,plan,state):
        if not state.get('confirmed'):
            return CommandResult(ok=False,action=plan.action,error_code='CONFIRM_REQUIRED')
        from aipacs_runtime import is_module_enabled
        if not is_module_enabled('run_cd'):
            return CommandResult(ok=False,action=plan.action,error_code='MODULE_UNAVAILABLE')
        if self.worker is not None and self.worker.isRunning():
            return CommandResult(ok=False,action=plan.action,error_code='MEDIA_BUSY')
        rows=self.selections.selected(plan.entities['selection_id'])
        if rows is None:
            return CommandResult(ok=False,action=plan.action,error_code='STALE_SELECTION')
        from modules.cd_burner.cd_burn_manager import CDBurnWorker, BurnOptions
        ent=plan.entities
        class ExactWorker(CDBurnWorker):
            def run(self):
                original=self.studies
                com_ready=False
                try:
                    for study in original:
                        self.studies=[study]
                        if not self._collect_study_folders():
                            self.completed.emit(False,'A selected study is not downloaded.')
                            return
                    from modules.cd_burner.center_identity import load_center_identity
                    identity=load_center_identity() or {}
                    self.options.center_name=identity.get('center_name','')
                    self.options.center_address=identity.get('center_address','')
                    self.options.center_phone=identity.get('center_phone','')
                    if ent.get('include_viewer',True):
                        from PacsClient.pacs.workstation_ui.settings_ui.lightviewer_settings import LightViewerSettingsWidget
                        viewer=LightViewerSettingsWidget.get_viewer_selection()
                        if not viewer.get('path'):
                            self.completed.emit(False,'Configured portable viewer unavailable.')
                            return
                        self.light_viewer_path=viewer['path']
                        self.viewer_display_name=viewer.get('display_name')
                    if self.output_folder:
                        target=Path(self.output_folder)
                        if not target.is_absolute():
                            self.completed.emit(False,'Choose an absolute new output folder.')
                            return
                        target.mkdir(parents=False,exist_ok=False)
                    self.studies=original
                    if self.burn_to_disc:
                        import comtypes
                        comtypes.CoInitialize()
                        com_ready=True
                    super().run()
                except Exception:
                    self.completed.emit(False,'Media preparation could not start.')
                finally:
                    if com_ready:
                        comtypes.CoUninitialize()
                    self.studies=original
        options=BurnOptions(anonymize=ent.get('anonymize',False),
                            include_report=ent.get('include_report',False),
                            include_images=ent.get('include_images',False),
                            include_attachments=ent.get('include_attachments',False),
                            dicom_format=ent.get('dicom_format','original'),
                            write_speed_sectors=ent.get('write_speed_sectors'),
                            finalize_disc=ent.get('finalize_disc',True),
                            verify_after_burn=ent.get('verify_after_burn',True))
        worker=ExactWorker(studies=rows,disc_label=ent.get('disc_label','DICOM_IMAGES'),
            drive_id=ent.get('drive_id'),burn_to_disc=ent['mode']=='burn',
            output_folder=ent.get('output_folder') if ent['mode']=='folder' else None,
            options=options)
        handle=uuid.uuid4().hex
        self.operations={handle:{'state':'running','progress':0,'selected_count':len(rows)}}
        worker.progress.connect(lambda percent,message:self.operations[handle].update(progress=int(percent)))
        worker.completed.connect(lambda ok,message:self.operations[handle].update(
            state='cancelled' if getattr(worker,'_cancelled',False) else ('succeeded' if ok else 'failed'),error_code=None if ok else 'MEDIA_FAILED'))
        _RUNNING_WORKERS.add(worker)
        worker.finished.connect(lambda:_RUNNING_WORKERS.discard(worker))
        self.worker=worker
        from PySide6.QtCore import QCoreApplication
        app=QCoreApplication.instance()
        if app is not None:
            if not hasattr(self,"_quit_guard"):
                self._quit_guard=_MediaQuitGuard(app,self)
            worker.finished.connect(self._quit_guard.resume_exit)
            app.aboutToQuit.connect(worker.cancel)
        worker.start()
        return CommandResult(ok=True,action=plan.action,data={'operation_id':handle,'state':'running'})

    def cancel_media(self,plan,state):
        key=plan.entities['operation_id']
        if key not in self.operations or self.worker is None:
            return CommandResult(ok=False,action=plan.action,error_code='UNKNOWN_OPERATION')
        self.worker.cancel()
        self.operations[key]['state']='cancelling'
        return CommandResult(ok=True,action=plan.action,data={'state':'cancelling'})
