"""Digital adaptation uses positive train studies only, never held-out controls."""
import ast
import hashlib
from pathlib import Path

import pytest


def select_function():
    path = Path(__file__).resolve().parents[3] / 'tools/eagle_eye/stage_vindr_calcification_training.py'
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'select_training')
    namespace = {'hashlib': hashlib}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['select_training']


def row(image, study, partition='train', positive=True):
    return dict(image_id=image, study_id=study, partition=partition,
                boxes=[[10, 10, 20, 20], [30, 30, 40, 40]] if positive else [])


def test_selection_excludes_heldout_and_unknown_negatives_preserves_regions():
    records = [row('train-a', 'a'), row('train-b', 'b'), row('unlabelled', 'c', positive=False)]
    records += [row(partition, partition, partition) for partition in
                ['validation', 'calibration', 'publisher_test_previously_inspected']]
    selected = select_function()(records, 2)
    assert {r['study_id'] for r in selected} == {'a', 'b'}
    assert all(len(r['boxes']) == 2 for r in selected)


def test_only_one_view_per_training_study_is_selected():
    selected = select_function()([row('a1', 'a'), row('a2', 'a'), row('b', 'b')], 2)
    assert len({r['study_id'] for r in selected}) == 2


def test_cohort_shortfall_is_explicit():
    with pytest.raises(ValueError, match='Insufficient'):
        select_function()([row('a', 'a'), row('a2', 'a')], 2)
