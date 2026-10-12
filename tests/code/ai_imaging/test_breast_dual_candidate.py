"""Research dual-branch integrity and native reconstruction contracts."""
import json

import numpy as np
import pytest

from tools.eagle_eye.breast_dual_candidate import collect
from tools.eagle_eye.calcium_candidate import digest, pixels, windows


@pytest.mark.parametrize('shape', [(512, 512), (513, 777), (1024, 1024), (2049, 1531)])
def test_trimmed_tiles_cover_every_native_pixel(shape):
    coverage = np.zeros(shape, bool)
    for t, b, l, r in windows(shape):
        a, c = (0 if t == 0 else 128), (0 if b == shape[0] else 128)
        d, e = (0 if l == 0 else 128), (0 if r == shape[1] else 128)
        coverage[t+a:b-c, l+d:r-e] = True
        assert b - t == r - l == 512
    assert coverage.all()


def test_tiny_native_input_is_not_silently_resized():
    with pytest.raises(ValueError):
        windows((128, 2048))


def fixture_job(tmp_path):
    source = tmp_path / 'synthetic.bin'
    source.write_bytes(b'original')
    request = {'study_uid': '1.2.3', 'files': [{'path': str(source), 'sha256': digest(source), 'sop_uid': '1.2.3.1', 'series_uid': '1.2.3.2'}]}
    for branch in ('parenchymal', 'calcium'):
        (tmp_path / branch).mkdir()
        (tmp_path / branch / 'result.json').write_text(json.dumps({'study_id': '1.2.3', 'status': 'success', 'files': [{'sop_uid': '1.2.3.1', 'series_uid': '1.2.3.2', 'source_sha256': digest(source)}]}))
    return source, request


def test_failed_calcium_does_not_become_a_normal_result(tmp_path):
    _, request = fixture_job(tmp_path)
    result = collect(tmp_path, {'parenchymal': 0, 'calcium': 1}, request)
    assert result['status'] == 'incomplete'
    assert result['branches']['parenchymal']['status'] == 'success'
    assert result['branches']['calcium'] == {'status': 'unavailable', 'exit_code': 1}


def test_foreign_result_cannot_be_joined(tmp_path):
    _, request = fixture_job(tmp_path)
    (tmp_path / 'calcium/result.json').write_text(json.dumps({'status': 'success', 'study_id': '1.2.4'}))
    with pytest.raises(ValueError, match='identity'):
        collect(tmp_path, {'parenchymal': 0, 'calcium': 0}, request)


def test_changed_source_discards_both_branches(tmp_path):
    source, request = fixture_job(tmp_path)
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Source changed'):
        collect(tmp_path, {'parenchymal': 0, 'calcium': 0}, request)


def test_missing_branch_cannot_report_success(tmp_path):
    _, request = fixture_job(tmp_path)
    with pytest.raises(ValueError, match='Both branch'):
        collect(tmp_path, {'parenchymal': 0}, request)


def test_duplicate_calcium_image_cannot_replace_missing_image(tmp_path):
    _, request = fixture_job(tmp_path)
    path = tmp_path / 'calcium/result.json'
    data = json.loads(path.read_text())
    data['files'].append(data['files'][0])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='per-image'):
        collect(tmp_path, {'parenchymal': 0, 'calcium': 0}, request)


class SyntheticDataset(dict):
    @property
    def pixel_array(self):
        return np.arange(512 * 512, dtype=np.uint16).reshape(512, 512) % 4096


def test_frozen_low_range_normalization_and_spacing():
    ds = SyntheticDataset(PhotometricInterpretation='MONOCHROME2', PixelRepresentation=0,
                          BitsAllocated=16, PixelSpacing=[.07, .08])
    im, spacing = pixels(ds)
    expected = (np.floor(ds.pixel_array.astype(float) / 65535 * 16 * 65535).astype(np.uint16) >> 8).astype(np.float32) / 255
    np.testing.assert_array_equal(im, expected)
    np.testing.assert_array_equal(spacing, [.07, .08])
    ds['PhotometricInterpretation'] = 'MONOCHROME1'
    with pytest.raises(ValueError, match='Unsupported'):
        pixels(ds)
