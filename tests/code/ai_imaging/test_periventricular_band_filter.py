"""Protect focal lesions while separating only paired smooth-band candidates."""
import numpy as np
import pytest
import SimpleITK as sitk


def case(kind='bands'):
    a = np.zeros((4, 120, 120), dtype=np.uint8)
    a[:, 15:105, 40:80] = 9
    a[1:3, 30:90, 38:40] = 18
    a[1:3, 30:90, 80:82] = 18
    if kind == 'unilateral':
        a[:, :, 80:82] = 0
    elif kind == 'bulge':
        a[1, 52:64, 30:40] = 18
    elif kind == 'adjacent_bulge':
        a[0, 52:64, 30:40] = 18
    elif kind == 'wide':
        a[1:3, 30:90, 34:40] = 18
    elif kind == 'remote':
        a[1, 8:11, 8:11] = 18
    elif kind == 'no_ventricles':
        a[a == 9] = 0
    elif kind == 'radial':
        a[a == 18] = 0
        a[1:3, 60:62, 20:40] = 18
        a[1:3, 60:62, 80:100] = 18
    im = sitk.GetImageFromArray(a)
    im.SetSpacing((1., 1., 6.))
    return im, sitk.Cast(im == 18, sitk.sitkUInt8)


def test_paired_bands_are_separated_losslessly():
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    anatomy, raw = case('remote')
    kept, bands, audit = separate_bands(raw, anatomy, context='ms')
    r, k, b = map(sitk.GetArrayFromImage, (raw, kept, bands))
    assert b.sum() == 480
    assert k.sum() == 9
    assert np.array_equal(k + b, r) and not np.any(k & b)
    assert audit['excluded_component_count'] == 2
    assert audit['clinical_qualification'] is False


@pytest.mark.parametrize('kind', ['unilateral', 'bulge', 'adjacent_bulge', 'wide', 'radial', 'no_ventricles'])
def test_ambiguous_or_focal_components_are_retained(kind):
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    anatomy, raw = case(kind)
    kept, bands, _ = separate_bands(raw, anatomy, context='ms')
    assert not sitk.GetArrayFromImage(bands).any()
    assert np.array_equal(sitk.GetArrayFromImage(raw), sitk.GetArrayFromImage(kept))


@pytest.mark.parametrize('context', ['svd', 'other'])
def test_no_ms_exclusion_in_other_contexts(context):
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    a, raw = case()
    kept, bands, audit = separate_bands(raw, a, context=context)
    assert audit['status'] == 'not_applied_context'
    assert not sitk.GetArrayFromImage(bands).any()


def test_geometry_and_resolution_gates():
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    a, raw = case()
    a.SetOrigin((1., 0., 0.))
    with pytest.raises(BrainError):
        separate_bands(raw, a, context='ms')
    a, raw = case()
    for im in (a, raw):
        im.SetDirection((1, 0, 0, 0, 0, -1, 0, 1, 0))
    assert separate_bands(raw, a, context='ms')[2]['status'] == 'not_applied_geometry'


def test_orientation_flip_preserves_decision():
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    a, raw = case()
    for im in (a, raw):
        im.SetDirection((-1, 0, 0, 0, -1, 0, 0, 0, 1))
    assert separate_bands(raw, a, context='ms')[2]['excluded_component_count'] == 2


def test_oblique_axial_and_end_fragments_do_not_change_band_identity():
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    a, raw = case()
    values = sitk.GetArrayFromImage(a)
    values[0, 31, 38] = 18
    updated = sitk.GetImageFromArray(values); updated.CopyInformation(a)
    a = updated; raw = sitk.Cast(a == 18, sitk.sitkUInt8)
    t = np.deg2rad(25)
    for im in (a, raw):
        im.SetDirection((1., 0., 0., 0., float(np.cos(t)), -float(np.sin(t)),
                         0., float(np.sin(t)), float(np.cos(t))))
    _, bands, _ = separate_bands(raw, a, context='ms')
    assert sitk.GetArrayFromImage(bands).sum() == 481


def test_report_context_change_restores_raw_burden(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_brain.lesion_indication import regenerate_lesion_report
    from modules.ai_imaging.eagle_eye_brain import lesion_report
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import measure_slices
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    a, raw = case('remote')
    kept, bands, audit = separate_bands(raw, a, context='ms')
    for name, im in [('flair.nii.gz', a), ('labels.nii.gz', kept), ('labels-raw.nii.gz', raw), ('labels-band-review.nii.gz', bands)]:
        sitk.WriteImage(im, str(tmp_path / name))
    result = dict(analysis_type='brain_lesions', acquisition_mode='2d', pdf_available=True,
                  clinical_context={'primary_disease': 'ms'}, band_filter=audit,
                  mask_path=str(tmp_path / 'labels.nii.gz'), raw_mask_path=str(tmp_path / 'labels-raw.nii.gz'),
                  band_mask_path=str(tmp_path / 'labels-band-review.nii.gz'), metrics=measure_slices(a, kept, thickness_mm=5))
    path = tmp_path / 'result.json'; path.write_text(json.dumps(result))
    monkeypatch.setattr(lesion_report, 'write_lesion_report', lambda *args: None)
    revised = regenerate_lesion_report(path, 'svd')
    assert revised['metrics']['total_volume_mm3'] == measure_slices(a, raw, thickness_mm=5)['total_volume_mm3']
    assert 'band_filter' not in revised
    assert json.loads(path.read_text()) == result


def test_filtered_report_shows_raw_separated_retained_and_not_normal():
    from modules.ai_imaging.eagle_eye_brain.lesion_report_2d import sections
    from modules.ai_imaging.eagle_eye_brain.lesions_2d import measure_slices
    from modules.ai_imaging.eagle_eye_brain.periventricular_band_filter import separate_bands
    a, raw = case('remote'); kept, bands, audit = separate_bands(raw, a, context='ms')
    audit['raw_metrics'] = measure_slices(a, raw, thickness_mm=5)
    audit['separated_metrics'] = measure_slices(a, bands, thickness_mm=5)
    result = dict(sex='F', metrics=measure_slices(a, kept, thickness_mm=5), band_filter=audit)
    html = '\n'.join(sections(result, 'Synthetic', '30', ''))
    assert 'Raw model burden' in html and 'after band separation' in html
    assert 'not confirmation of normal tissue' in html and 'awz144' in html
