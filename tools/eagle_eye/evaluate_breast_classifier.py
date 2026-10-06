"""Diagnostic aggregate classification on existing reference-ROI feature rows.

Keeps private feature records on the dataset host. Not end-to-end detection proof,
and not an independent accuracy claim without checkpoint training lineage.
"""
import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source))
    import XGBOOST_INFERENCE as xgb
    from feature_contract import build_stack_matrix, positive_probability

    annotations = pd.read_csv(args.data / 'original data/finding_annotations.csv')
    test_groups = set(annotations.loc[annotations.split == 'test', 'study_id'].astype(str))
    frame = pd.read_csv(args.data / 'modified/XGBoostData/output_multiview_features.csv')
    group_col = 'study_id' if 'study_id' in frame else 'study_instance_uid'
    frame = frame[frame[group_col].astype(str).isin(test_groups)].reset_index(drop=True)
    if frame.empty or 'finding_categories' not in frame:
        raise ValueError('No diagnostic publisher-test feature rows with labels.')
    categories = frame.finding_categories.map(ast.literal_eval)
    with contextlib.redirect_stdout(io.StringIO()):
        xgb.preload_models(str(args.models))
    cache = xgb._GLOBAL_CACHE
    # Preserve the estimator grouping while removing serialization name wrappers.
    def unwrap(value):
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
            return value[1]
        if isinstance(value, (list, tuple)):
            return [unwrap(item) for item in value]
        return value
    base = {}
    for kind in cache['used_kinds']:
        matrix = xgb._build_X(frame, cache['feature_lists'][kind])
        base[kind] = xgb._predict_kind(unwrap(cache['base_models'][kind]), matrix)
    report = dict(protocol='reference-ROI diagnostic; independent training lineage unverified',
                  rows=len(frame), study_groups=frame[group_col].nunique(), targets={})
    for index, label in enumerate(xgb.LABELS):
        if index == 0:
            continue  # Runtime No Finding is the complement of pathological outputs.
        estimator = cache['stackers'][label]
        matrix = np.column_stack([base[kind][:, index] for kind in xgb.KINDS if kind in base])
        matrix = build_stack_matrix(matrix, estimator.n_features_in_, cache.get('stack_imputer'))
        probability = positive_probability(estimator, matrix)
        calibrator = cache['calibrators'].get(label)
        if calibrator is not None:
            probability = calibrator.transform(probability)
        if not np.isfinite(probability).all():
            raise ValueError('Nonfinite calibrated prediction.')
        truth = categories.map(lambda values: label in values).to_numpy()
        threshold = float(cache['thresholds'][index])
        predicted = probability >= threshold
        tp = int((predicted & truth).sum()); fn = int((~predicted & truth).sum())
        fp = int((predicted & ~truth).sum()); tn = int((~predicted & ~truth).sum())
        report['targets'][label] = dict(tp=tp, fn=fn, fp=fp, tn=tn,
                                       sensitivity=tp/(tp+fn) if tp+fn else None,
                                       specificity=tn/(tn+fp) if tn+fp else None,
                                       ppv=tp/(tp+fp) if tp+fp else None, threshold=threshold,
                                       auroc=roc_auc_score(truth, probability) if len(set(truth))==2 else None,
                                       average_precision=average_precision_score(truth, probability) if truth.any() else None)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
