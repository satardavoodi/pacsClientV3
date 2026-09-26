"""Manual correction geometry and background ownership contracts."""
import numpy as np
import pytest
import SimpleITK as sitk
from modules.ai_imaging.eagle_eye_brain.manual_review import validate_edit, recalculate_review
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError


def test_boundary_edits_and_empty_mask_keep_label_identity():
    original = sitk.GetImageFromArray(np.ones((3, 4, 5), dtype=np.uint8))
    edited = sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.uint8))
    validate_edit(original, edited)


@pytest.mark.parametrize('kind', ['origin', 'label', 'size', 'nan'])
def test_wrong_examination_geometry_or_labels_rejected(kind):
    original = sitk.GetImageFromArray(np.ones((3, 4, 5), dtype=np.float32))
    edited = sitk.Image(original)
    if kind == 'origin': edited.SetOrigin((1, 0, 0))
    if kind == 'label': edited[0, 0, 0] = 2
    if kind == 'size': edited = sitk.Image(2, 2, 2, sitk.sitkUInt8)
    if kind == 'nan': edited[0, 0, 0] = float('nan')
    with pytest.raises(BrainError): validate_edit(original, edited)


def test_unsaved_correction_does_not_publish_report(tmp_path):
    (tmp_path / 'session.json').write_text('{}')
    with pytest.raises(BrainError, match='Save correction'):
        recalculate_review(tmp_path)
    assert not (tmp_path / 'report.pdf').exists()


def test_corrected_binary_measurements_preserve_original_posterior(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    from modules.ai_imaging.eagle_eye_brain import organized_report
    original = sitk.GetImageFromArray(np.ones((3, 3, 3), dtype=np.uint8))
    edited = sitk.Image(original); edited[0, 0, 0] = 0
    sitk.WriteImage(original, str(tmp_path / 'original.nii.gz'))
    sitk.WriteImage(edited, str(tmp_path / 'corrected.nii.gz'))
    posterior = [{'structure': 'synthetic', 'volume_cm3': .024, 'method': 'SynthSeg posterior'}]
    manifest = dict(lesion=False, source_mask=str(tmp_path / 'original.nii.gz'),
                    source_sha256=sha256(tmp_path / 'original.nii.gz'), label_names={'1': 'synthetic'},
                    source_result={'posterior_rows': posterior})
    (tmp_path / 'session.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(organized_report, 'write_paged_pdf', lambda html, path, **kw: path.write_bytes(b'test'))
    result = recalculate_review(tmp_path)
    assert result['manual_rows'][0]['before_cm3'] == pytest.approx(.027)
    assert result['manual_rows'][0]['volume_cm3'] == pytest.approx(.026)
    assert result['posterior_rows'] == posterior
    assert sha256(tmp_path / 'original.nii.gz') == manifest['source_sha256']


def test_manual_recalculation_does_not_queue_behind_another_brain_job(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.service import _ANALYSIS_LOCK
    with _ANALYSIS_LOCK:
        with pytest.raises(BrainError, match='Another brain analysis'):
            recalculate_review(tmp_path)


def test_custom_slicer_has_visible_review_controls_independent_of_hidden_statusbar():
    import ast
    from pathlib import Path
    from modules.ai_imaging.eagle_eye_brain import manual_slicer
    tree = ast.parse(Path(manual_slicer.__file__).read_text())
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert 'QDialog' in attrs and 'setModal' in attrs and 'show' in attrs


def test_segment_array_uses_vtk_supported_unsigned_bytes():
    from modules.ai_imaging.eagle_eye_brain.manual_slicer import segment_array
    data = segment_array(np.array([0, 1, 2, 1]), 1)
    assert data.dtype == np.uint8
    assert data.tolist() == [0, 1, 0, 1]


def test_lesion_revision_remeasures_and_invalidates_stale_spatial_scores(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_brain import lesion_report, svd_assessment, ms_assessment
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    original = sitk.GetImageFromArray(np.ones((3, 3, 3), dtype=np.uint8))
    edited = sitk.Image(original); edited[0, 0, 0] = 0
    for name, data in [('original', original), ('image', original), ('flair', original), ('corrected', edited)]:
        sitk.WriteImage(data, str(tmp_path / (name + '.nii.gz')))
    manifest = dict(lesion=True, source_mask=str(tmp_path/'original.nii.gz'),
                    source_sha256=sha256(tmp_path/'original.nii.gz'),
                    source_result=dict(clinical_context={'primary_disease':'svd'},
                                       wmh_reference={'percentile':99}, svd_spatial={'stale':True}))
    (tmp_path/'session.json').write_text(json.dumps(manifest))
    def spatial(result, root, **kwargs):
        assert 'wmh_reference' not in result and 'svd_spatial' not in result
        return {'status':'new assessment'}
    monkeypatch.setattr(svd_assessment, 'enrich_svd', spatial)
    def topography(result, root, **kwargs):
        assert 'lesion_topography' not in result
        return {'regions': [], 'status': 'remeasured', 'conclusion': 'Not a diagnosis'}
    monkeypatch.setattr(ms_assessment, 'enrich_ms', topography)
    monkeypatch.setattr(lesion_report, 'write_lesion_report', lambda r,f,m,d: (d/'report.pdf').write_bytes(b'test'))
    result = recalculate_review(tmp_path)
    assert result['metrics']['total_volume_mm3'] == 26
    assert result['svd_spatial'] == {'status':'new assessment'}
    assert sha256(tmp_path/'original.nii.gz') == manifest['source_sha256']
