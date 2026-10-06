"""Every successful confirmed analysis presents only its own current PDF."""
import pytest


@pytest.mark.parametrize('current,confirmed,opens', [
    (('1.2.3','fixture'),True,True),
    (('1.2.9','fixture'),True,False),
    (('1.2.3','other'),True,False),
    (('1.2.3','fixture'),False,False)])
def test_completed_report_opens_only_confirmed_current_identity(monkeypatch,current,confirmed,opens):
    from modules.ai_imaging.eagle_eye_remote import bone_report_ui as ui
    calls=[]
    monkeypatch.setattr(ui.QDesktopServices,'openUrl',lambda url:calls.append(url.toLocalFile()) or True)
    data=dict(pdf_path='C:/synthetic/bone_age_report.pdf',
              confirmed_demographics=dict(study_uid='1.2.3',patient_id='fixture',physician_confirmed=confirmed))
    assert ui.show_completed_report(data,'1.2.3',current) is opens
    assert bool(calls) is opens


def test_missing_pdf_is_never_opened(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import bone_report_ui as ui
    def forbidden(*args): raise AssertionError('Missing report opened')
    monkeypatch.setattr(ui.QDesktopServices,'openUrl',forbidden)
    assert ui.show_completed_report({},'1.2.3',('1.2.3','fixture')) is False


def test_actual_analysis_worker_always_builds_template_with_source_image(tmp_path,monkeypatch):
    import ast
    from pathlib import Path
    from PySide6.QtCore import QThread,Signal,Qt
    from modules.ai_imaging.eagle_eye_remote import demographics,routing,bone_report_ui
    from modules.ai_imaging.eagle_eye_engines import bone_age_report
    tree=ast.parse(Path('modules/viewer/interactor_styles/ai_chat_interactorstyle.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BoneAgeWorker')
    scope=dict(QThread=QThread,Signal=Signal,Path=Path,ATTACHMENT_PATH=tmp_path)
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<actual-bone-worker>','exec'),scope)
    draft=dict(study_uid='1.2.3',patient_id='fixture',name='Synthetic Child',sex='M',chronological_age_months=120)
    monkeypatch.setattr(demographics,'prepare_review',lambda *args:dict(draft))
    monkeypatch.setattr(routing,'study',lambda *args,**kwargs:dict(sex='M',predicted_bone_age_months=125.68))
    calls=[]
    def inputs(study,**kwargs):
        assert kwargs['review'] is False and kwargs['result']['patient_id']=='fixture'
        return {'source':'synthetic'}
    monkeypatch.setattr(bone_report_ui,'load_report_inputs',inputs)
    monkeypatch.setattr(bone_report_ui,'load_evidence',lambda *args:b'synthetic-png')
    def report(data,study,patient,path,**kwargs):
        calls.append((study,patient,kwargs['evidence_png']))
        return {'pdf_path':str(tmp_path/'bone_age_report.pdf')}
    monkeypatch.setattr(bone_age_report,'create_report',report)
    worker=scope['BoneAgeWorker']('1.2.3','M','',metadata_context={'patient_id':'fixture'})
    monkeypatch.setattr(worker,'_save_result_json',lambda _:tmp_path/'bone_age.json')
    worker.sex_required.connect(lambda:worker.confirm_demographics(dict(draft)),Qt.DirectConnection)
    completed=[]; errors=[]
    worker.finished.connect(completed.append,Qt.DirectConnection)
    worker.error.connect(errors.append,Qt.DirectConnection)
    worker.run()
    assert not errors and calls==[('1.2.3','fixture',b'synthetic-png')]
    assert len(completed)==1 and completed[0]['pdf_path'].endswith('bone_age_report.pdf')
