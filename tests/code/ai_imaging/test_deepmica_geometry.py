"""Geometry and unknown-input guards for the isolated segmentation worker."""
import ast
import os
from pathlib import Path

import pytest

np = pytest.importorskip('numpy')
cv2 = pytest.importorskip('cv2')
SOURCE = Path(os.environ.get('DEEPMICA_SCREEN_SOURCE',
    str(Path(__file__).resolve().parents[3]/'tools/eagle_eye/run_deepmica_screen.py')))


def functions():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    wanted = {'preprocess','restore_map','proposals'}
    nodes = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
    scope = {'np':np,'cv2':cv2}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
    return scope


@pytest.mark.parametrize('flipped,column',[(False,4),(True,7)])
def test_crop_probability_restored_without_resize(flipped,column):
    crop = np.zeros((4,4),dtype=np.float32)
    crop[1,2] = .9
    restored = functions()['restore_map'](crop,(2,3,6,7),flipped,(10,12))
    assert restored.shape == (10,12)
    assert np.count_nonzero(restored) == 1
    assert restored[4,column] == pytest.approx(.9)


def test_blank_foreground_is_unavailable():
    with pytest.raises(ValueError,match='No image-derived breast foreground'):
        functions()['preprocess'](np.zeros((64,64),dtype=np.uint8))


def test_cluster_bounds_exclude_dilation_support():
    probability = np.zeros((128,128),dtype=np.float32)
    probability[40:42,40] = .9
    probability[40:42,60] = .9
    binary,boxes,_,_ = functions()['proposals'](probability,.5)
    assert int(binary.sum()) == 4
    assert boxes == [[40,40,61,42]]


def test_invalid_restoration_extent_rejected():
    with pytest.raises(ValueError,match='geometry mismatch'):
        functions()['restore_map'](np.zeros((2,2)),(0,0,3,3),False,(10,10))
