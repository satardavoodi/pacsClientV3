"""Deterministic feature reconstruction from the recovered training formulas."""
import numpy as np


def positive_probability(estimator, matrix):
    """Validate binary predictions; native compatibility belongs to the runtime."""
    result = estimator.predict_proba(matrix)[:, 1]
    result = np.asarray(result, dtype='float32')
    if result.ndim != 1 or not np.isfinite(result).all() or np.any((result < 0) | (result > 1)):
        raise ValueError('Invalid breast classification probabilities.')
    return result


def build_feature_matrix(frame, columns):
    values = {}
    for name in columns:
        if name in frame.columns:
            values[name] = frame[name].astype('float32').to_numpy()
            continue
        if not name.startswith('feat_inter_'):
            raise ValueError('Required breast feature is missing: ' + name)
        expression = name[len('feat_inter_'):]
        for token in ('__x__', '__diff__', '__ratio__'):
            if token in expression:
                left, right = expression.split(token, 1)
                break
        else:
            raise ValueError('Unknown breast interaction formula.')
        if left not in frame.columns or right not in frame.columns:
            raise ValueError('Required breast interaction inputs are missing.')
        a = frame[left].astype('float32').to_numpy()
        b = frame[right].astype('float32').to_numpy()
        a = np.where(np.isfinite(a), a, np.nan)
        b = np.where(np.isfinite(b), b, np.nan)
        with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
            values[name] = (a * b if token == '__x__' else
                            np.abs(a - b) if token == '__diff__' else
                            a / np.where(b == 0, np.nan, b))
    result = np.column_stack([values[name] for name in columns]).astype('float32')
    return np.where(np.isfinite(result), result, np.nan)


def build_stack_matrix(base, expected_width, imputer=None):
    """Support only the recovered base-only and base-plus-five contracts."""
    base = np.asarray(base, dtype='float32')
    if base.ndim != 2 or base.shape[1] == 0 or not np.isfinite(base).all():
        raise ValueError('Incomplete breast base predictions.')
    if expected_width == base.shape[1]:
        return base
    if expected_width != base.shape[1] + 5 or imputer is None:
        raise ValueError('Unsupported breast stack feature schema.')
    result = np.column_stack([base, np.mean(base, axis=1), np.std(base, axis=1),
                              np.max(base, axis=1), np.min(base, axis=1),
                              np.max(base, axis=1) - np.min(base, axis=1)])
    if getattr(imputer, 'n_features_in_', None) != expected_width:
        raise ValueError('Breast stacking imputer schema mismatch.')
    return imputer.transform(result).astype('float32')
