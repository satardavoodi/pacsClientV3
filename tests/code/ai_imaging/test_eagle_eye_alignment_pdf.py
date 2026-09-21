"""Synthetic identity, report pagination and primary-series workflow guards."""
import json
from pathlib import Path

import pytest

from test_eagle_eye_alignment import image, points, dicom, qapp


def test_selected_series_identity_is_enforced_before_decode(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import load_image
    ds=dicom(tmp_path)
    with pytest.raises(ValueError,match='primary alignment series'):
        load_image(ds.filename,'1.2.3','1.2.99')


def test_primary_series_selection_discards_stale_review_and_pdf(qapp):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w=AlignmentWidget(study_uid='1.2.3')
    w._file_rows=[dict(series_uid='1.2.3.1',label='First',path='first'),
                  dict(series_uid='1.2.3.2',label='Second',path='second')]
    w.series.addItem('First','1.2.3.1');w.series.addItem('Second','1.2.3.2')
    w._apply_image(image());w.points={'R':points(),'L':points('L')}
    w.confirm.setChecked(True);w._redraw_points();w.review.setChecked(True)
    w.report_result={'pdf_available':True};w.series.setCurrentIndex(1)
    assert w.image is None and w.metrics is None and w.report_result is None
    assert not w.review.isChecked() and w.files.currentData()=='second'
    w.teardown();w.deleteLater();qapp.processEvents()


def test_pdf_has_three_pages_shared_furniture_and_matching_evidence(qapp,tmp_path):
    from PySide6.QtGui import QFontDatabase
    import os
    for font in ('arial.ttf','arialbd.ttf'):
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/font
        if path.is_file():QFontDatabase.addApplicationFont(str(path))
    from pypdf import PdfReader
    from modules.ai_imaging.eagle_eye_alignment.report import generate_report
    sample=image();sample['identity'].update(sop_uid='1.2.3.4.5',series_uid='1.2.3.4',
        institution='SYNTHETIC CENTER',series_number='3',instance_number='1')
    p={'R':points(),'L':points('L')}
    result=generate_report(sample,p,{'model':'Synthetic'},dict(impression='Synthetic review only.'),True,root=tmp_path)
    folder=Path(result['artifact_directory']);doc=PdfReader(folder/'report.pdf').pages
    assert len(doc)==3
    for i,page in enumerate(doc):
        text=page.extract_text().replace('\t',' ')
        assert 'EAGLE EYE ALIGNMENT' in text and 'EAGLE EYE BRAIN' not in text
        assert 'SYNTHETIC' in text and f'Page {i+1} of 3' in text
        assert page.images, 'Each report page needs actual image evidence'
    assert 'Core measurements' in doc[0].extract_text().replace('\t',' ')
    assert 'Advanced measurements' in doc[1].extract_text().replace('\t',' ')
    assert 'Method references' in doc[2].extract_text().replace('\t',' ')
    payload=json.loads((folder/'report.json').read_text())
    assert payload['landmarks']==p and payload['measurements']['R']['limb_length']==400
    assert payload['landmarks_reviewed'] and not payload['clinical_report_signed']
    assert 'SYNTHETIC &lt;b&gt;' in (folder/'report.html').read_text()


def test_uncalibrated_report_does_not_imply_millimeter_lengths():
    from modules.ai_imaging.eagle_eye_alignment.report import render_html
    sample=image();sample['calibrated']=False
    html=render_html(sample,{'R':points(),'L':points('L')},{})
    assert 'physical leg-length discrepancy cannot be determined' in html
    assert '800.00' in html and '>px</td>' in html
    assert 'Draft; landmark and clinical review required.' in html


def test_direct_report_does_not_claim_operator_confirmed_acquisition():
    from modules.ai_imaging.eagle_eye_alignment.report import render_html
    html=render_html(image(),{'R':points(),'L':points('L')},{})
    assert 'orientation and coverage reviewed by operator' not in html
    assert 'positioning and laterality require operator verification' in html


def test_ai_completion_automatically_requests_draft_pdf(qapp,monkeypatch):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w=AlignmentWidget(study_uid='1.2.3');w._apply_image(image())
    calls=[];monkeypatch.setattr(w,'_generate_pdf',lambda:calls.append('draft'))
    future=Future();future.set_result({'landmarks':{'R':points(),'L':points('L')}})
    w._future=future;w._kind='ai';w._poll()
    assert calls==['draft'] and not w.review.isChecked()
    assert w.provenance['initial_landmarks']==w.points
    w.teardown();w.deleteLater();qapp.processEvents()


def test_report_failure_does_not_publish_partial_result(qapp,tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_alignment.report import generate_report
    from modules.ai_imaging.eagle_eye_brain import organized_report
    sample=image();sample['identity']['sop_uid']='1.2.3.4'
    def fail(*args,**kwargs):raise RuntimeError('Synthetic renderer failure')
    monkeypatch.setattr(organized_report,'write_paged_pdf',fail)
    with pytest.raises(RuntimeError):generate_report(sample,{'R':points(),'L':points('L')},{},root=tmp_path)
    assert not list(tmp_path.rglob('report.pdf'))
