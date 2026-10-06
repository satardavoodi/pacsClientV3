"""Existing-result PDF preparation stays off the GUI thread and bound to a study."""
import hashlib
import json
import time
from types import SimpleNamespace
import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_writer_runs_in_background_and_rejects_changed_analysis(app,tmp_path,monkeypatch):
    from PySide6.QtCore import QThread
    from modules.ai_imaging.eagle_eye_remote import bone_report_ui as ui
    from modules.ai_imaging.eagle_eye_engines import bone_age_report as reports
    raw=b'{"sex":"M"}'; (tmp_path/'bone_age.json').write_bytes(raw)
    inputs=dict(result={'sex':'M'},root=str(tmp_path),patient_id='fixture',
                result_sha256=hashlib.sha256(raw).hexdigest())
    confirmed=dict(study_uid='1.2.3')
    calls=[]
    def create(*args,**kwargs):
        calls.append(QThread.currentThread()!=app.thread())
        return {'pdf_path':'synthetic.pdf'}
    monkeypatch.setattr(reports,'create_report',create)
    worker=ui._Write(inputs,confirmed); ready=[]; failed=[]
    worker.ready.connect(ready.append); worker.failed.connect(failed.append)
    worker.start()
    deadline=time.monotonic()+3
    while worker.isRunning() and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.01)
    worker.wait(1000); app.processEvents()
    assert calls==[True] and len(ready)==1 and not failed
    (tmp_path/'bone_age.json').write_bytes(b'{"sex":"F"}')
    worker=ui._Write(inputs,confirmed); worker.failed.connect(failed.append); worker.run()
    assert len(calls)==1 and len(failed)==1


def test_changed_case_does_not_open_demographic_popup(app,monkeypatch):
    from PySide6.QtWidgets import QWidget,QPushButton,QLabel
    from modules.ai_imaging.eagle_eye_remote import bone_report_ui as ui
    panel=QWidget(); panel.study_uid='1.2.3'; panel.imaging_tab=SimpleNamespace(study_uid='1.2.9')
    panel.pdf_btn=QPushButton(panel); panel.pdf_status=QLabel(panel); panel._report_result={'sex':'M'}
    controller=ui.BoneReportController(panel); controller.identity='1.2.3'; controller.busy=True
    def forbidden(*args): raise AssertionError('Foreign case opened a dialog')
    monkeypatch.setattr(ui,'DemographicReviewDialog',forbidden)
    controller.review({})
    assert controller.busy is False
    panel.close()


def test_load_inputs_checks_original_patient_and_series(tmp_path,monkeypatch):
    import pydicom
    from tests.code.ai_imaging.test_eagle_eye_local_engines import source
    from modules.ai_imaging.eagle_eye_remote import bone_report_ui as ui
    from PacsClient.utils import config,db_manager
    path=source(tmp_path,sex='M')
    ds=pydicom.dcmread(path); ds.PatientID='fixture'; ds.StudyDate='20260101'; ds.PatientBirthDate='20160101'; ds.save_as(path)
    root=tmp_path/'attachments'; out=root/'1.2.3'; out.mkdir(parents=True)
    (out/'bone_age.json').write_text(json.dumps({'sex':'M','predicted_bone_age_months':120}))
    monkeypatch.setattr(config,'ATTACHMENT_PATH',root)
    row=dict(modality='Unknown',series_uid=str(ds.SeriesInstanceUID),series_path=str(path.parent))
    monkeypatch.setattr(db_manager,'get_series_by_study_uid',lambda _: [row])
    monkeypatch.setattr(ui,'prepare_review',lambda context,*args:dict(context))
    prepared=ui.load_report_inputs('1.2.3')
    assert prepared['patient_id']=='fixture' and prepared['draft']['study_date']=='20260101'
    row['series_uid']='1.2.999'
    with pytest.raises(ValueError,match='identity'):
        ui.load_report_inputs('1.2.3')


@pytest.mark.parametrize('raw,expected', [('13991230','2021-03-20'),('1400/01/01','2021-03-21'),
    ('1400-12-30',None),('1400-0101',None),('140001/01',None),('2020-02-30',None)])
def test_calendar_rejects_invalid_dates_and_preserves_leap_day(raw,expected):
    from modules.ai_imaging.eagle_eye_remote.demographics import parse_date
    value,_=parse_date(raw,reception=True)
    assert (value.isoformat() if value else None)==expected
