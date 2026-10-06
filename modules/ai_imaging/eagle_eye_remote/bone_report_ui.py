"""Background preparation and physician confirmation for existing Bone Age results."""
from pathlib import Path
import json
import hashlib
import uuid

from PySide6.QtCore import QObject, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QMessageBox

from .demographics import normalize, prepare_review
from .demographics_ui import DemographicReviewDialog

_WORKERS = set()


def _retain(worker):
    # A destroyed review widget must not destroy a running QThread.
    _WORKERS.add(worker)
    worker.finished.connect(lambda: _WORKERS.discard(worker))
    worker.finished.connect(worker.deleteLater)
    worker.start()


def load_report_inputs(study_uid, *, result=None, review=True):
    """Read an attachment and original headers; never link patients by name."""
    import pydicom
    from pydicom.uid import UID
    from PacsClient.utils.config import ATTACHMENT_PATH
    from PacsClient.utils.db_manager import get_series_by_study_uid
    if not isinstance(study_uid,str) or not UID(study_uid).is_valid:
        raise ValueError('A valid study identity is required for reporting.')
    root=ATTACHMENT_PATH/study_uid
    raw=(root/'bone_age.json').read_bytes() if result is None else None
    result=json.loads(raw) if raw is not None else dict(result)
    context=None
    evidence_path=None
    scanned=0
    for row in get_series_by_study_uid(study_uid):
        if str(row.get('modality') or '').upper() not in ('DX','CR','UNKNOWN',''):
            continue
        folder=Path(row.get('series_path') or '')
        if not row.get('series_path') or not folder.is_dir():
            continue
        for path in folder.iterdir():
            scanned+=1
            if scanned>1000:
                raise ValueError('Source inventory exceeds the report limit.')
            if not path.is_file() or path.suffix.lower() not in ('','.dcm','.dicom'):
                continue
            ds=pydicom.dcmread(path,stop_before_pixels=True)
            if str(ds.get('Modality','')).upper() not in ('DX','CR'):
                continue
            anatomy=str(ds.get('BodyPartExamined') or '').strip().upper()
            if anatomy and anatomy not in ('HAND','WRIST'):
                continue
            if (str(ds.get('StudyInstanceUID','')) != study_uid or
                    str(ds.get('SeriesInstanceUID','')) != str(row.get('series_uid') or '')):
                raise ValueError('Original source identity differs from the selected examination.')
            patient=str(ds.get('PatientID') or '')
            if not patient or context and context['patient_id']!=patient:
                raise ValueError('Original sources do not identify one patient.')
            current=dict(patient_id=patient,patient_name=str(ds.get('PatientName') or '').replace('^',' '),
                         patient_birth_date=str(ds.get('PatientBirthDate') or ''),
                         study_date=str(ds.get('StudyDate') or ''),sex=normalize(ds.get('PatientSex')))
            if context and current['study_date'] != context['study_date']:
                raise ValueError('Original imaging dates disagree; review source selection.')
            if context is None:
                context=current
                evidence_path=path
    if context is None:
        raise ValueError('Download the matching original hand/wrist radiograph before preparing the PDF.')
    if result.get('study_id',study_uid)!=study_uid or result.get('patient_id',context['patient_id'])!=context['patient_id']:
        raise ValueError('Stored result identity differs from the current examination.')
    result.update(study_id=study_uid,patient_id=context['patient_id'])
    draft=prepare_review(context,context['sex'],study_uid) if review else dict(result.get('confirmed_demographics') or {})
    # Preserve a reviewed manual value when authoritative sources remain missing.
    previous=result.get('confirmed_demographics') or {}
    if (previous.get('physician_confirmed') is True and previous.get('study_uid')==study_uid
            and previous.get('patient_id')==context['patient_id']):
        for key in ('name','sex','chronological_age_months'):
            if draft.get(key) in (None,''):
                draft[key]=previous.get(key)
                draft.setdefault('sources',{})[key]='previous physician review'
    source_hash=hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    return dict(result=result,draft=draft,root=str(root),patient_id=context['patient_id'],
                evidence_path=str(evidence_path),evidence_sha256=source_hash,
                result_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None)


def load_evidence(inputs,confirmed):
    """Validate and encode local evidence off the GUI thread for every report route."""
    import io
    import pydicom
    from PIL import Image
    from ..eagle_eye_engines.vendor.bone_age.dicom_utils import dicom_to_uint8
    raw=Path(inputs['evidence_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=inputs['evidence_sha256']:
        raise ValueError('Original source changed during review.')
    ds=pydicom.dcmread(io.BytesIO(raw))
    if (str(ds.get('StudyInstanceUID',''))!=confirmed['study_uid'] or
            str(ds.get('PatientID',''))!=inputs['patient_id']):
        raise ValueError('Evidence source identity mismatch.')
    buffer=io.BytesIO(); Image.fromarray(dicom_to_uint8(ds)).save(buffer,format='PNG')
    return buffer.getvalue()


def show_completed_report(data,study_uid,current_identity):
    """GUI-thread presentation has no file reads and rejects a switched case."""
    confirmed=data.get('confirmed_demographics') or {}
    if (not data.get('pdf_path') or confirmed.get('physician_confirmed') is not True
            or confirmed.get('study_uid')!=study_uid
            or data.get('study_id',study_uid)!=study_uid
            or current_identity!=(study_uid,confirmed.get('patient_id'))):
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(data['pdf_path']))


class _Load(QThread):
    ready=Signal(dict)
    failed=Signal(str)

    def __init__(self,study_uid):
        super().__init__(); self.study_uid=study_uid

    def run(self):
        try: self.ready.emit(load_report_inputs(self.study_uid))
        except Exception: self.failed.emit('Cannot prepare report inputs. Check the saved result and matching original radiograph.')


class _Write(QThread):
    ready=Signal(dict)
    failed=Signal(str)

    def __init__(self,inputs,confirmed):
        super().__init__(); self.inputs=inputs; self.confirmed=confirmed

    def run(self):
        try:
            from ..eagle_eye_engines.bone_age_report import create_report
            result=dict(self.inputs['result'],confirmed_demographics=self.confirmed)
            root=Path(self.inputs['root'])
            if hashlib.sha256((root/'bone_age.json').read_bytes()).hexdigest()!=self.inputs['result_sha256']:
                raise ValueError('Analysis changed while patient information was reviewed.')
            evidence=None
            if self.inputs.get('evidence_path'):
                evidence=load_evidence(self.inputs,self.confirmed)
            output=root/'bone-age-reports'/uuid.uuid4().hex
            outcome=create_report(result,self.confirmed['study_uid'],self.inputs['patient_id'],output,evidence_png=evidence)
            self.ready.emit(outcome)
        except Exception:
            self.failed.emit('PDF preparation failed. Review patient information and the recorded model result.')


class BoneReportController(QObject):
    def __init__(self,panel):
        super().__init__(panel); self.panel=panel; self.busy=False; self.identity=None

    def _current(self):
        host=self.panel.imaging_tab
        return self.panel.study_uid if host is None or host.study_uid==self.panel.study_uid else None

    @Slot()
    def request(self):
        if self.busy or not self._current(): return
        self.identity=self._current(); self.busy=True
        self.panel.pdf_btn.setEnabled(False)
        worker=_Load(self.identity); worker.ready.connect(self.review); worker.failed.connect(self.failed)
        _retain(worker)

    @Slot(dict)
    def review(self,inputs):
        if self._current()!=self.identity:
            self.finish(); return
        dialog=DemographicReviewDialog(self.panel,inputs['draft'])
        dialog.setWindowTitle('Bone Age: Confirm PDF Information')
        from PySide6.QtWidgets import QDialogButtonBox
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).setText('Confirm and Prepare PDF')
        if dialog.exec()!=QDialog.Accepted or self._current()!=self.identity:
            self.finish(); return
        if normalize(inputs['result'].get('sex'))!=dialog.confirmed['sex']:
            self.failed('Sex differs from the recorded model input. Repeat Bone Age analysis with the confirmed sex before preparing this report.')
            return
        worker=_Write(inputs,dialog.confirmed); worker.ready.connect(self.completed); worker.failed.connect(self.failed)
        _retain(worker)

    @Slot(dict)
    def completed(self,outcome):
        current=self._current()==self.identity
        self.finish()
        if current:
            self.panel.pdf_status.setText('Unsigned PDF prepared; physician signature required.')
            QDesktopServices.openUrl(QUrl.fromLocalFile(outcome['pdf_path']))

    @Slot(str)
    def failed(self,message):
        current=self._current()==self.identity
        self.finish()
        if current: QMessageBox.warning(self.panel,'Bone Age PDF',message)

    def finish(self):
        self.busy=False
        self.panel.pdf_btn.setEnabled(bool(getattr(self.panel,'_report_result',{})))
