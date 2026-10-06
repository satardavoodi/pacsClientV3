"""Aggregate paired detector ablation on an existing protected dataset host.

This is diagnostic development evaluation, not a clinical qualification receipt.
Inputs and predictions remain on the dataset host; only aggregate JSON is emitted.
"""
import argparse
import ast
import csv
import json
from pathlib import Path
import time
import sys
import contextlib

import numpy as np
import torch
from PIL import Image
from torchvision.models.detection import fcos_resnet50_fpn
from torchvision.ops import nms
from torchvision.transforms import functional as TF


def overlap(a, b):
    lo = np.maximum(a[:2], b[:2])
    hi = np.minimum(a[2:], b[2:])
    intersection = np.maximum(hi - lo, 0).prod()
    union = (a[2:] - a[:2]).prod() + (b[2:] - b[:2]).prod() - intersection
    return intersection / union if union else 0.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--negative-limit', type=int, default=100)
    parser.add_argument('--size', type=int, default=512)
    parser.add_argument('--cascade-root', type=Path)
    parser.add_argument('--job', type=Path)
    args = parser.parse_args()
    torch.set_num_threads(4)
    records = list(csv.DictReader((args.data / 'original data/finding_annotations.csv').open()))
    paths = {}
    metadata = {}
    for name in ('train', 'valid', 'test'):
        for row in csv.DictReader((args.data / f'modified/CSV-PNG-full/{name}.csv').open()):
            paths.setdefault(row['image_id'], row['png_full_path'])
            metadata.setdefault(row['image_id'], row)
    grouped = {}
    for row in records:
        if row['split'].lower() != 'test':
            continue
        grouped.setdefault(row['image_id'], []).append(row)
    positives = [key for key, rows in grouped.items() if any(
        'Suspicious Calcification' in ast.literal_eval(r['finding_categories']) for r in rows)]
    negatives = sorted(key for key, rows in grouped.items() if all(
        ast.literal_eval(r['finding_categories']) == ['No Finding'] for r in rows))[:args.negative_limit]
    selected = sorted(positives) + negatives
    model = fcos_resnet50_fpn(weights=None, weights_backbone=None, num_classes=1,
                              score_thresh=.2, nms_thresh=.5, detections_per_img=100,
                              topk_candidates=1000, min_size=args.size, max_size=args.size)
    model.load_state_dict(torch.load(args.weights, map_location='cpu', weights_only=True), strict=True)
    model.eval()
    totals = {str(t): {mode: dict(calc_targets=0, calc_matched=0, negatives=0,
                                negative_predictions=0, with_mass_targets=0,
                                with_mass_matched=0, without_mass_targets=0,
                                without_mass_matched=0)
                      for mode in ('before', 'after')} for t in (.2, .3, .4, .45)}
    proposals = []
    references = {}
    failures = 0
    start = time.monotonic()
    for index, key in enumerate(selected):
        rows = grouped[key]
        path = paths.get(key)
        if not path or not Path(path).is_file():
            failures += 1
            continue
        image = Image.open(path).convert('RGB')
        width, height = image.size
        tensor = TF.to_tensor(TF.resize(image, [args.size, args.size], antialias=True))
        with torch.inference_mode():
            result = model([tensor])[0]
            flipped = model([tensor.flip(2)])[0]
        flip_boxes = flipped['boxes'].clone()
        flip_boxes[:, [0, 2]] = args.size - 1 - flip_boxes[:, [2, 0]]
        boxes = torch.cat([result['boxes'], flip_boxes])
        scores = torch.cat([result['scores'], flipped['scores']])
        keep = nms(boxes, scores, .5)
        boxes, scores = boxes[keep].numpy(), scores[keep].numpy()
        areas = np.maximum(boxes[:, 2:] - boxes[:, :2], 0).prod(axis=1)
        targets = [np.array([float(r[c]) for c in ('xmin', 'ymin', 'xmax', 'ymax')]) *
                   np.array([args.size / width, args.size / height] * 2) for r in rows
                   if 'Suspicious Calcification' in ast.literal_eval(r['finding_categories'])]
        with_mass = any('Mass' in ast.literal_eval(r['finding_categories']) for r in rows)
        references[key] = (targets, with_mass)
        if args.cascade_root:
            for box, score in zip(boxes[scores >= .4], scores[scores >= .4]):
                source = metadata[key]
                record = {name: source.get(name, '') for name in
                          ('study_id', 'image_id', 'laterality', 'view_position', 'full_image_path')}
                record.update(study_instance_uid=source['study_id'],
                              series_instance_uid=source['series_id'], width=width, height=height,
                              prediction_score=float(score))
                record.update(zip(('xmin', 'ymin', 'xmax', 'ymax'),
                                  box * np.array([width / args.size, height / args.size] * 2)))
                proposals.append(record)
        for threshold, modes in totals.items():
            for mode, values in modes.items():
                pred = boxes[(scores >= float(threshold)) & (areas >= (.002 * args.size**2 if mode == 'before' else 0))]
                remaining = list(range(len(pred)))
                matched = 0
                for target in targets:
                    candidates = [(overlap(target, pred[j]), j) for j in remaining]
                    if candidates and max(candidates)[0] >= .5:
                        matched += 1
                        remaining.remove(max(candidates)[1])
                values['calc_targets'] += len(targets)
                values['calc_matched'] += matched
                prefix = 'with_mass' if with_mass else 'without_mass'
                values[prefix + '_targets'] += len(targets)
                values[prefix + '_matched'] += matched
                if not targets:
                    values['negatives'] += 1
                    values['negative_predictions'] += len(pred)
        if (index + 1) % 10 == 0:
            print(json.dumps({'processed': index + 1, 'selected': len(selected)}), flush=True)
            args.output.write_text(json.dumps({'complete': False, 'processed': index + 1,
                                               'totals': totals}), encoding='utf-8')
    report = dict(complete=True, protocol='publisher-test diagnostic; checkpoint training independence unverified',
                  matching_iou=.5, input_size=args.size, selected=len(selected), calc_positive_images=len(positives),
                  failures=failures, seconds=time.monotonic() - start, totals=totals)
    if args.cascade_root:
        import pandas as pd
        import traceback
        args.job.mkdir(parents=True, exist_ok=False)
        sys.path.insert(0, str(args.cascade_root))
        import worker
        import XGBOOST_INFERENCE as xgb
        try:
            with (args.job / 'private.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                original_streams = sys.__stdout__, sys.__stderr__
                try:
                    # Vendor stage loggers tee to the original streams explicitly.
                    sys.__stdout__ = sys.__stderr__ = log
                    xgb.preload_models(str(args.cascade_root / 'weights/models_stacked'))
                    worker.validate_stacker_schema(xgb._GLOBAL_CACHE)
                    xgb._GLOBAL_CACHE['base_models'] = {k: worker.normalize_estimators(v) for k, v in xgb._GLOBAL_CACHE['base_models'].items()}
                    output = worker.classify(args.cascade_root, args.job, proposals)
                finally:
                    sys.__stdout__, sys.__stderr__ = original_streams
            classified = pd.read_csv(output)
            normalized = pd.DataFrame(proposals).iloc[classified.row_index.to_numpy()].reset_index(drop=True)
            if not np.allclose(classified[['xmin', 'ymin', 'xmax', 'ymax']], normalized[['xmin', 'ymin', 'xmax', 'ymax']]):
                raise ValueError('Classification row geometry changed.')
            if not classified.full_image_path.equals(normalized.full_image_path):
                raise ValueError('Classification row identity changed.')
            classified['image_id'] = normalized.image_id
            results = {}
            for threshold in (.275, .4):
                values = dict(calc_targets=sum(len(item[0]) for item in references.values()), typed_calc_matched=0, typed_calc_predictions=0,
                              normal_typed_calc_predictions=0, normal_images_with_typed_calc=0,
                              with_mass_matched=0, without_mass_matched=0)
                for key, (targets, with_mass) in references.items():
                    frame = classified[(classified.image_id.astype(str) == str(key)) &
                                       (classified['prob_Suspicious Calcification'] >= threshold)]
                    width, height = float(metadata[key]['width']), float(metadata[key]['height'])
                    predicted = frame[['xmin', 'ymin', 'xmax', 'ymax']].to_numpy() * np.array([args.size / width, args.size / height] * 2)
                    remaining = list(range(len(predicted)))
                    matched = 0
                    for target in targets:
                        candidates = [(overlap(target, predicted[j]), j) for j in remaining]
                        if candidates and max(candidates)[0] >= .5:
                            matched += 1
                            remaining.remove(max(candidates)[1])
                    values['typed_calc_matched'] += matched
                    values['typed_calc_predictions'] += len(predicted)
                    values[('with_mass' if with_mass else 'without_mass') + '_matched'] += matched
                    if not targets:
                        values['normal_typed_calc_predictions'] += len(predicted)
                        values['normal_images_with_typed_calc'] += bool(len(predicted))
                results[str(threshold)] = values
            report['cascade'] = dict(status='completed', detector_threshold=.4,
                                     proposal_count=len(proposals), classification_thresholds=results,
                                     context='selected images only; companion views outside cohort not added')
        except Exception as exc:
            (args.job / 'private-error.log').write_text(traceback.format_exc(), encoding='utf-8')
            report['cascade'] = dict(status='failed', error_type=type(exc).__name__, proposal_count=len(proposals))
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
