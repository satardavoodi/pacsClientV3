"""Recovered arithmetic must preserve train/inference feature semantics."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


def contract():
    path = Path('modules/ai_imaging/eagle_eye_engines/vendor/breast/feature_contract.py')
    spec = importlib.util.spec_from_file_location('breast_contract_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interactions_preserve_requested_order_and_zero_ratio_unknown():
    frame = pd.DataFrame({'feat_a': [2., 3.], 'feat_b': [4., 0.]})
    result = contract().build_feature_matrix(frame, [
        'feat_inter_feat_a__diff__feat_b', 'feat_inter_feat_a__x__feat_b',
        'feat_inter_feat_a__ratio__feat_b', 'feat_a'])
    np.testing.assert_allclose(result, [[2., 8., .5, 2.], [3., 0., np.nan, 3.]], equal_nan=True)


def test_missing_raw_feature_is_not_silently_imputed():
    with pytest.raises(ValueError, match='missing'):
        contract().build_feature_matrix(pd.DataFrame({'feat_a': [1.]}), ['feat_b'])


def test_stack_statistics_follow_recovered_order():
    base = np.array([[.1, .3, .5, .7]])
    imputer = SimpleNamespace(n_features_in_=9, transform=lambda x: x)
    result = contract().build_stack_matrix(base, 9, imputer)
    np.testing.assert_allclose(result, [[.1, .3, .5, .7, .4, np.sqrt(.05), .7, .1, .6]], rtol=1e-6)


def test_unknown_stack_schema_or_partial_base_predictions_fail_closed():
    with pytest.raises(ValueError):
        contract().build_stack_matrix([[.1, np.nan]], 7)
    with pytest.raises(ValueError):
        contract().build_stack_matrix([[.1, .2]], 8)


def test_recovered_nine_feature_stack_requires_matching_saved_imputer():
    from modules.ai_imaging.eagle_eye_engines.worker import validate_stacker_schema
    cache = {'used_kinds': ['SINGLE', 'MV', 'BL', 'BOTH'],
             'stackers': {'fixture': SimpleNamespace(n_features_in_=9)},
             'stack_imputer': SimpleNamespace(n_features_in_=9)}
    validate_stacker_schema(cache)
    cache['stack_imputer'].n_features_in_ = 8
    with pytest.raises(ValueError):
        validate_stacker_schema(cache)


def test_nonfinite_native_result_is_not_a_normal_prediction():
    estimator = SimpleNamespace(predict_proba=lambda x: np.array([[np.nan, np.nan]]))
    with pytest.raises(ValueError, match='Invalid'):
        contract().positive_probability(estimator, np.ones((1, 2)))


def test_saved_logistic_calibrator_applies_its_model_instead_of_identity():
    import ast
    path = Path('modules/ai_imaging/eagle_eye_engines/vendor/breast/XGBOOST_INFERENCE.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PlattCalibrator')
    namespace = {'np': np}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    calibrator = namespace['PlattCalibrator']()
    calibrator.logistic_model = SimpleNamespace(
        predict_proba=lambda x: np.column_stack([np.full(len(x), .8), np.full(len(x), .2)]))
    np.testing.assert_allclose(calibrator.transform([.9, .7]), [.2, .2])
