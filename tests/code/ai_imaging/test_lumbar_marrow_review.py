"""Synthetic reporting, colors and server-only correction guards."""
import json
import threading
from pathlib import Path
import numpy as np
import pytest
from test_eagle_eye_total_spine import qapp


def test_report_rounding_colors_and_pdf(qapp, tmp_path):
    from modules.ai_imaging.lumbar_marrow_review import report_html, save_pdf, label_color, MarrowReview
    result = {'marrow_measurements':[dict(level='L1',label=1,sample_volume_mm3=12345.678,
              sample_voxels=100,mean_si=123.456,median_si=120.,std_si=2.345,qc='unreviewed')]}
    content = report_html(result)
    assert '12.35' in content and '123.46' in content
    assert 'not red marrow volume' in content
    page = MarrowReview(); page.show_result(result)
    assert page.table.item(0, 0).background().color().getRgb()[:3] == label_color(1)
    path = tmp_path / 'draft.pdf'
    save_pdf(result, path)
    assert path.read_bytes().startswith(b'%PDF-') and path.stat().st_size > 2000
    page.deleteLater()


def test_marrow_corrected_mask_remeasured_without_inference(tmp_path):
    import SimpleITK as sitk
    from modules.ai_imaging.lumbar_marrow_revision import calculate
    from modules.ai_imaging.eagle_eye_remote.segmentation_review import encode
    from modules.ai_imaging.eagle_eye_remote.contracts import digest, validate
    parent = tmp_path / ('a' * 32); root = parent / 'work'; root.mkdir(parents=True)
    data = np.full((16,16,16), 100., dtype=np.float32)
    labels = np.zeros(data.shape, dtype=np.uint16); labels[2:14,2:14,2:14] = 1
    image = sitk.GetImageFromArray(data); mask = sitk.GetImageFromArray(labels)
    sitk.WriteImage(image, str(root/'review-image.nii.gz')); sitk.WriteImage(mask, str(root/'labels.nii.gz'))
    (root/'label_names.json').write_text('{"1":"vertebrae_L1"}')
    result = dict(artifact_directory=str(root),affine_ras=np.diag([-1,-1,1,1]).tolist(),
                  segments=[dict(label=1,name='vertebrae_L1')],clinical_context={},
                  review_assets={k:str(root/v) for k,v in [('image','review-image.nii.gz'),('mask','labels.nii.gz'),('names','label_names.json')]})
    (parent/'worker-result.json').write_text(json.dumps(result))
    labels[2:5] = 0; edited = sitk.GetImageFromArray(labels)
    value = encode(mask, edited, parent.name, digest(root/'labels.nii.gz'))
    request = dict(protocol=1,request_id='b'*32,module='lumbar-marrow',study_uid='1.2.3',
                   series={'primary':{'series_uid':'1.2.4','expected_count':16}},parameters={'correction':value})
    validate(request)
    output = tmp_path / ('c'*32) / 'work'
    revised = calculate(request, output, threading.Event())
    assert revised['marrow_measurements'][0]['mean_si'] == 100.
    assert revised['parent_job_id'] == parent.name
    assert digest(root/'labels.nii.gz') == value['source_mask_sha256']
    value['source_mask_sha256'] = 'd'*64
    with pytest.raises(ValueError, match='match parent'):
        calculate(request, output, threading.Event())
