"""Unknown or proposal-only review must never authorize an empty crop target."""
import ast
from pathlib import Path

import pytest


def negative_gate():
    path = Path(__file__).resolve().parents[3] / 'tools/eagle_eye/prepare_calcification_review.py'
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verified_negative')
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['verified_negative']


@pytest.mark.parametrize('review', [
    {},
    {'proposal_label': 'not_calcification', 'reviewer': 'reviewer'},
    {'proposal_label': 'not_calcification', 'whole_crop': 'uncertain', 'reviewer': 'reviewer'},
    {'proposal_label': 'not_calcification', 'whole_crop': 'contains_calcification', 'reviewer': 'reviewer'},
    {'proposal_label': 'calcification', 'whole_crop': 'reviewed_no_calcification', 'reviewer': 'reviewer'},
    {'proposal_label': 'not_calcification', 'whole_crop': 'reviewed_no_calcification', 'reviewer': ' '},
    {'proposal_label': 'not_calcification', 'whole_crop': 'reviewed_no_calcification', 'reviewer': None},
])
def test_unreviewed_incomplete_or_contradictory_crop_is_not_negative(review):
    assert not negative_gate()(review)


def test_explicit_complete_crop_review_supports_negative():
    assert negative_gate()({'proposal_label': 'not_calcification',
                           'whole_crop': 'reviewed_no_calcification', 'reviewer': 'reviewer',
                           'image_quality': 'adequate'})


@pytest.mark.parametrize('quality', [None, 'unreviewed', 'too_bright', 'unassessable'])
def test_inadequate_or_unknown_quality_cannot_be_negative(quality):
    assert not negative_gate()({'proposal_label': 'not_calcification',
                               'whole_crop': 'reviewed_no_calcification',
                               'reviewer': 'reviewer', 'image_quality': quality})


def test_positive_correction_cannot_be_negative():
    assert not negative_gate()({'proposal_label': 'not_calcification',
                               'whole_crop': 'reviewed_no_calcification',
                               'reviewer': 'reviewer', 'image_quality': 'adequate',
                               'point_annotations': [{'crop_x': 20, 'crop_y': 30}]})
