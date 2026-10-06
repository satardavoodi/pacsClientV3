"""Resume aggregate scoring of protected cascade outputs without rerunning inference."""
import ast
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def overlap(a, b):
    intersection = np.maximum(np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2]), 0).prod()
    union = (a[2:] - a[:2]).prod() + (b[2:] - b[:2]).prod() - intersection
    return intersection / union if union else 0


def main(root, data):
    report_path = root / 'detector-040-cascade.json'
    report = json.loads(report_path.read_text())
    job = root / 'private-040-cascade'
    classified = pd.read_csv(job / 'classification.csv')
    normalized = pd.read_csv(job / 'normalized.csv').iloc[classified.row_index.to_numpy()].reset_index(drop=True)
    if not classified.full_image_path.equals(normalized.full_image_path) or not np.allclose(
            classified[['xmin', 'ymin', 'xmax', 'ymax']], normalized[['xmin', 'ymin', 'xmax', 'ymax']]):
        raise ValueError('Classification identity or geometry changed.')
    classified['image_id'] = normalized.image_id
    groups = {}
    for row in csv.DictReader((data / 'original data/finding_annotations.csv').open()):
        if row['split'] == 'test':
            groups.setdefault(row['image_id'], []).append(row)
    positives = sorted(key for key, rows in groups.items() if any(
        'Suspicious Calcification' in ast.literal_eval(r['finding_categories']) for r in rows))
    negatives = sorted(key for key, rows in groups.items() if all(
        ast.literal_eval(r['finding_categories']) == ['No Finding'] for r in rows))[:100]
    results = {}
    for threshold in (.275, .4):
        values = dict(calc_targets=0, typed_calc_matched=0, typed_calc_predictions=0,
                      normal_typed_calc_predictions=0, normal_images_with_typed_calc=0,
                      with_mass_matched=0, without_mass_matched=0)
        for key in positives + negatives:
            rows = groups[key]
            targets = [np.array([float(r[col]) for col in ('xmin', 'ymin', 'xmax', 'ymax')])
                       for r in rows if 'Suspicious Calcification' in ast.literal_eval(r['finding_categories'])]
            frame = classified[(classified.image_id.astype(str) == key) &
                               (classified['prob_Suspicious Calcification'] >= threshold)]
            predicted = frame[['xmin', 'ymin', 'xmax', 'ymax']].to_numpy()
            remaining = list(range(len(predicted)))
            matched = 0
            for target in targets:
                candidates = [(overlap(target, predicted[j]), j) for j in remaining]
                if candidates and max(candidates)[0] >= .5:
                    matched += 1
                    remaining.remove(max(candidates)[1])
            values['calc_targets'] += len(targets)
            values['typed_calc_matched'] += matched
            values['typed_calc_predictions'] += len(predicted)
            with_mass = any('Mass' in ast.literal_eval(r['finding_categories']) for r in rows)
            values[('with_mass' if with_mass else 'without_mass') + '_matched'] += matched
            if not targets:
                values['normal_typed_calc_predictions'] += len(predicted)
                values['normal_images_with_typed_calc'] += bool(len(predicted))
        results[str(threshold)] = values
    report['cascade'] = dict(status='completed', detector_threshold=.4,
                             proposal_count=len(normalized), classification_thresholds=results,
                             context='selected images only; companion views outside cohort not added',
                             identity_join='row_index with verified source path and box geometry')
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(threshold040=report['totals']['0.4'], cascade=report['cascade'])))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
