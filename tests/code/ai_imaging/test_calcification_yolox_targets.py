"""Native region conversion guards; run in the isolated Torch research worker."""
import ast
import os
from pathlib import Path

import pytest

torch = pytest.importorskip('torch')
SOURCE = Path(os.environ.get('CALCIFICATION_SCREEN_SOURCE',
              str(Path(__file__).resolve().parents[3] / 'tools/eagle_eye/run_calcification_yolox_screen.py')))


def converter():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'targets_for_yolox')
    scope = {'torch': torch}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope['targets_for_yolox']


def test_native_pixel_geometry_and_class_zero():
    output = converter()([[100, 200, 110, 220], [1, 2, 5, 8]], 'cpu')
    assert output.shape == (1, 2, 5)
    assert torch.equal(output, torch.tensor([[[0, 105, 210, 10, 20],
                                            [0, 3, 5, 4, 6]]], dtype=torch.float32))


@pytest.mark.parametrize('boxes', [[], [[0, 0, 0, 2]], [[0, 0, float('nan'), 2]]])
def test_unknown_empty_and_invalid_geometry_rejected(boxes):
    with pytest.raises(ValueError):
        converter()(boxes, 'cpu')


def test_nonfinite_detection_is_failure_not_empty_normal():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'prediction')
    scope = {'torch': torch, 'nms': lambda *args: torch.empty(0, dtype=torch.int64)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), scope)
    output = torch.tensor([[[float('nan'), 1, 2, 2, .8, .8]]])
    with pytest.raises(RuntimeError, match='Nonfinite detector output'):
        scope['prediction'](lambda *args: output, torch.zeros(3, 32, 32), 'yolox')
