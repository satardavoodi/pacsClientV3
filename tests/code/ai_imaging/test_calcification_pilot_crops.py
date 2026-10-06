"""Verify actual crop geometry without importing a GPU runtime into workstation tests."""
import ast
from pathlib import Path

import numpy as np
import pytest


def crop_function():
    path = Path(__file__).resolve().parents[3] / 'tools/eagle_eye/run_calcification_pilot.py'
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'crop_targets')
    namespace = {'np': np}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['crop_targets']


def test_all_visible_targets_are_translated_without_resizing():
    crop = crop_function()
    assert crop([[110, 210, 120, 220], [150, 250, 180, 280]], (100, 200, 1024)) == [
        [10, 10, 20, 20], [50, 50, 80, 80]]


def test_unknown_background_never_becomes_an_empty_negative():
    with pytest.raises(ValueError, match='not a negative'):
        crop_function()([[300, 300, 400, 400]], (0, 0, 128))


def test_ambiguous_visible_target_rejects_whole_crop_instead_of_dropping_box():
    with pytest.raises(ValueError, match='partial'):
        crop_function()([[20, 20, 40, 40], [125, 20, 200, 100]], (0, 0, 128))


def test_clear_partial_target_retains_clipped_geometry():
    assert crop_function()([[100, 100, 150, 150]], (0, 0, 128)) == [[100, 100, 128, 128]]
