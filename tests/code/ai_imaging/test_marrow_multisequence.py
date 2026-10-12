"""Synthetic full-volume marrow and ambiguity-preservation guards."""
import uuid
import numpy as np
import pytest
from test_eagle_eye_total_spine import qapp


def test_multisequence_contract_is_module_scoped():
    from modules.ai_imaging.eagle_eye_remote.contracts import validate
    roles = ['primary', 'fat', 'water', 'multiecho']
    request = dict(protocol=1, request_id=uuid.uuid4().hex, module='lumbar-marrow',
                   study_uid='1.2.3', parameters={'mode': 'multiparametric', 'inputs_confirmed': True},
                   series={r: {'series_uid': f'1.2.4.{i}', 'expected_count': 9} for i,r in enumerate(roles)})
    assert validate(request) is request
    request['module'] = 'lumbar'
    with pytest.raises(ValueError):
        validate(request)


def test_fit_recovers_synthetic_signal_and_keeps_competing_branches():
    from modules.ai_imaging.marrow_quantitative import signal_model, fit_signal
    te = np.arange(9) * .00155 + .00302
    signal = 200 * signal_model(te, 1.5, .72, 60)
    result = fit_signal(signal, te, 1.5)
    best = min(result['branches'], key=lambda x: x['sse'])
    assert best['fat_signal_fraction'] == pytest.approx(.72, abs=.005)
    assert best['r2star_s_inverse'] == pytest.approx(60, abs=2)
    assert len(result['branches']) == 2
    assert result['selection'] == 'unresolved'


def test_dixon_prior_does_not_force_near_half_or_unreviewed_alignment():
    from modules.ai_imaging.marrow_quantitative import select_branch
    branches = [{'fat_signal_fraction': .35, 'sse': 100}, {'fat_signal_fraction': .78, 'sse': 110}]
    assert select_branch(branches, [.4,.58,.7], True)['selection'] == 'unresolved'
    assert select_branch(branches, [.65,.7,.8], False)['selection'] == 'unresolved'
    protocol=dict(dixon_tr_ms=7.49,dixon_flip_degrees=12,echo_tr_ms=400,echo_flip_degrees=20)
    result = select_branch(branches, [.45,.55,.65], True,protocol)
    assert result['selection'] == 'conditional_T1_supported_low_fat'
    assert result['clinical_ambiguity_resolved'] is False
    assert result['t1_sensitivity_assumptions']['measured_t1'] is False
    assert select_branch(branches,[.45,.55,.65],False,protocol)['dixon_supported_branch'] is None
    assert select_branch(branches,[.45,.55,.65],True)['dixon_supported_branch'] is None


def test_body_labels_exclude_arch_and_preserve_every_spatial_slice():
    from modules.ai_imaging.marrow_quantitative import body_labels, fat_volume_statistics
    labels = np.zeros((7,20,20), np.uint8)
    labels[:,3:14,3:14] = 6
    body = np.zeros_like(labels); body[:,3:10,3:14] = 1
    mask = body_labels(labels, body)
    assert not mask[:,10:].any()
    fat = np.full(mask.shape, 6.); water=np.full(mask.shape,4.)
    result, ratio = fat_volume_statistics(fat, water, mask, {6:'L1'}, np.eye(4))
    assert result[0]['spatial_slices'] == 7
    assert result[0]['signal_ff_median_percent'] == pytest.approx(60)
    assert result[0]['body_volume_mm3'] == int((mask==6).sum())
    assert np.isnan(ratio[mask==0]).all()


def test_bad_signal_and_duplicate_echo_times_fail_closed():
    from modules.ai_imaging.marrow_quantitative import fit_signal
    for signal,te in [(np.zeros(9),np.arange(9)*.001), (np.ones(9),np.ones(9)*.002)]:
        with pytest.raises(ValueError):
            fit_signal(signal,te,1.5)


def test_body_model_manifest_is_sealed():
    from modules.ai_imaging.marrow_body_worker import verify_manifest
    for manifest in ({}, {'task':'total_mr','dataset':850,'engine':'2.14.0','files':[]}):
        with pytest.raises(ValueError):
            verify_manifest(manifest)


def test_full_volume_report_pdf_and_legacy_review_reset(qapp, tmp_path):
    from modules.ai_imaging.lumbar_marrow_review import MarrowReview, save_pdf
    from modules.ai_imaging.marrow_multisequence_report import report_html
    row=dict(level='L1',label=6,body_volume_mm3=12000.,spatial_slices=7,
             sample_volume_mm3=5000.,sample_voxels=100,signal_ff_median_percent=55.,
             signal_ff_p10_percent=40.,signal_ff_p90_percent=65.,qc='body_mask_review_required',
             echo_measurements=[])
    result=dict(task='lumbar_marrow_multiparametric_v1',marrow_measurements=[row],
                acquisition={'dixon_spatial_slices':32,'multiecho_spatial_planes':1})
    content=report_html(result)
    assert 'Dixon spatial slices: 32' in content and 'not a fat-cell volume fraction' in content
    page=MarrowReview();page.show_result(result)
    assert page.table.horizontalHeaderItem(3).text()=='Signal FF (%)'
    page.show_result({'marrow_measurements':[]})
    assert page.table.horizontalHeaderItem(3).text()=='Mean SI'
    assert 'arbitrary signal' in page.explanation.text()
    pdf=tmp_path/'multiparametric.pdf';save_pdf(result,pdf)
    assert pdf.read_bytes().startswith(b'%PDF-') and pdf.stat().st_size>2000
    page.deleteLater()


def test_marrow_input_mode_describes_the_selected_method(qapp, monkeypatch):
    from modules.ai_imaging.lumbar_marrow_widget import LumbarMarrowWidget
    monkeypatch.setattr(LumbarMarrowWidget, 'load_series', lambda self:None)
    widget=LumbarMarrowWidget(study_uid='synthetic-study')
    widget.mode.setCurrentIndex(1)
    assert 'Full-stack vertebral-body' in widget.method_note.text()
    assert 'Dixon in-phase' in widget.confirm.text()
    assert not widget.confirm.isChecked()
    widget.mode.setCurrentIndex(0)
    assert 'arbitrary units' in widget.method_note.text()
    widget.teardown();widget.deleteLater()


def test_full_stack_artifacts_exclude_private_recalculation_inputs(tmp_path):
    import json, zipfile
    from modules.ai_imaging.eagle_eye_remote.artifacts import publish
    job=tmp_path/'job';out=job/'work';out.mkdir(parents=True)
    for name in ['review-image.nii.gz','labels.nii.gz','label_names.json',
                 'marrow-signal-ff.nii.gz','input-primary.nii.gz','input-echo-0.npz']:
        (out/name).write_bytes(b'synthetic')
    previews=[]
    for i in range(32):
        p=out/f'preview-slice-{i:03d}.png';p.write_bytes(b'synthetic');previews.append(str(p))
    result=dict(artifact_directory=str(out),slice_previews=previews,
        review_assets={'image':str(out/'review-image.nii.gz'),'mask':str(out/'labels.nii.gz'),
                       'names':str(out/'label_names.json')})
    request=dict(protocol=1,request_id='synthetic',module='lumbar-marrow',study_uid='1.2.3',series={})
    publish(job,request,[],result)
    with zipfile.ZipFile(job/'artifacts.zip') as z:
        assert len([n for n in z.namelist() if n.startswith('preview-slice-')])==32
        assert not any(n.startswith('input-') for n in z.namelist())
        assert 'marrow-signal-ff.nii.gz' in z.namelist()
        packet=json.loads(z.read('envelope.json'))
        assert len(packet['result']['slice_previews'])==32


def test_pdf_images_fit_pages_without_blank_continuations(qapp,tmp_path):
    from PIL import Image
    from pypdf import PdfReader
    from modules.ai_imaging.lumbar_marrow_review import save_pdf
    preview=tmp_path/'preview.png';overview=tmp_path/'preview-all.png'
    Image.new('RGB',(336,576),'gray').save(preview)
    Image.new('RGB',(1440,1320),'gray').save(overview)
    result=dict(task='lumbar_marrow_multiparametric_v1',marrow_measurements=[],
                preview=str(preview),overview_preview=str(overview))
    path=tmp_path/'layout.pdf';save_pdf(result,path)
    assert len(PdfReader(path).pages)==5
