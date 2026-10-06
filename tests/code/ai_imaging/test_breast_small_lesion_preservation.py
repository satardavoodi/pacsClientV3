"""Exercise the detector's actual postfilter without importing model frameworks."""
import ast
from pathlib import Path

import numpy as np


def test_small_valid_lesion_is_not_discarded_by_default_postfilter():
    path = Path('modules/ai_imaging/eagle_eye_engines/vendor/breast/FCOS_INFERENCE.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cutoff = next(ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and any(
                      isinstance(t, ast.Name) and t.id == 'MIN_BOX_AREA_FRAC' for t in n.targets))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'filter_tiny_boxes')
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)

    class Array(np.ndarray):
        def numel(self):
            return self.size

        def clamp(self, min):
            return np.maximum(self, min).view(Array)

    boxes = np.array([[100., 100., 104., 104.], [20., 20., 60., 60.]]).view(Array)
    scores = np.array([.9, .8]).view(Array)
    actual_boxes, actual_scores = namespace['filter_tiny_boxes'](boxes, scores, cutoff, (512, 512))
    np.testing.assert_array_equal(actual_boxes, boxes)
    np.testing.assert_array_equal(actual_scores, scores)
