"""Synthetic CBIS mapping, mask geometry and patient-boundary guards."""
import numpy as np
import pytest

from tools.eagle_eye.prepare_cbis_calcification import local_path, patient_partitions, region_box, series_key


def test_mask_region_uses_exclusive_original_image_coordinates():
    mask = np.zeros((20, 30), dtype=np.uint8)
    mask[5:9, 10:15] = 255
    assert region_box(mask, (30, 20)) == [10, 5, 15, 9]


def test_wrong_geometry_empty_and_textured_masks_are_rejected():
    with pytest.raises(ValueError, match='geometry'):
        region_box(np.zeros((20, 30)), (20, 30))
    with pytest.raises(ValueError, match='Empty'):
        region_box(np.zeros((20, 30)), (30, 20))
    with pytest.raises(ValueError, match='near-binary'):
        region_box(np.arange(100).reshape(10, 10), (10, 10))


def test_series_references_and_local_paths_cannot_escape_dataset(tmp_path):
    assert series_key('CBIS/series-a/example.dcm') == 'series-a'
    assert series_key('CBIS\\series-a\\example.dcm') == 'series-a'
    with pytest.raises(ValueError, match='path'):
        local_path(tmp_path, dict(image_path='CBIS/../example.jpg'))
    with pytest.raises(ValueError, match='unavailable'):
        local_path(tmp_path, dict(image_path='CBIS/series-a/example.jpg'))
    target = tmp_path / 'jpeg/series-a/example.jpg'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'synthetic file existence only')
    assert local_path(tmp_path, dict(image_path='untrusted-prefix/series-a/example.jpg')) == target


def test_original_test_people_from_either_task_never_enter_training():
    labels = {f'person-{i}': {'MALIGNANT'} for i in range(20)}
    reserved = {'person-0', 'mass-test-person'}
    partitions = patient_partitions(labels, reserved, 'seed')
    assert partitions['person-0'] == 'publisher_test'
    assert partitions['mass-test-person'] == 'publisher_test'
    assert set(partitions.values()) == {'publisher_test', 'train', 'validation', 'calibration'}
    assert partitions == patient_partitions(dict(reversed(list(labels.items()))), reserved, 'seed')
