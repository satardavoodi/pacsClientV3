"""Development-only comparison of full-image and label-blind sliding-window FCOS.

Outputs are aggregate localization diagnostics, not typed calcification accuracy.
Selection uses training annotations; no image data leaves the dataset host.
"""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
import torch
from torchvision.models.detection import fcos_resnet50_fpn
from torchvision.ops import nms
from torchvision.transforms import functional as TF

from evaluate_breast_detector import overlap


def starts(length, window, stride):
    if length <= window:
        return [0]
    return sorted(set(list(range(0, length - window + 1, stride)) + [length - window]))


def select_groups(keys, groups, count):
    selected = []
    seen = set()
    for key in sorted(keys, key=lambda value: hashlib.sha256(value.encode()).digest()):
        study = groups[key][0]['study_id']
        if study not in seen:
            seen.add(study)
            selected.append(key)
        if len(selected) == count:
            break
    return selected


def predict(model, crops):
    tensors = [TF.to_tensor(TF.resize(crop, [512, 512], antialias=True)) for crop, _ in crops]
    all_boxes, all_scores = [], []
    for start in range(0, len(crops), 4):
        inputs = tensors[start:start + 4]
        with torch.inference_mode():
            original = model(inputs)
            flipped = model([tensor.flip(2) for tensor in inputs])
        for offset, (first, second) in enumerate(zip(original, flipped)):
            crop, origin = crops[start + offset]
            boxes = second['boxes'].clone()
            boxes[:, [0, 2]] = 511 - boxes[:, [2, 0]]
            boxes = torch.cat([first['boxes'], boxes])
            scores = torch.cat([first['scores'], second['scores']])
            boxes *= torch.tensor([crop.width / 512, crop.height / 512] * 2)
            boxes += torch.tensor([origin[0], origin[1]] * 2)
            all_boxes.append(boxes)
            all_scores.append(scores)
    boxes, scores = torch.cat(all_boxes), torch.cat(all_scores)
    keep = nms(boxes, scores, .5)
    return boxes[keep].numpy(), scores[keep].numpy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--per-group', type=int, default=12)
    parser.add_argument('--window', type=int, default=1536)
    parser.add_argument('--stride', type=int, default=1152)
    args = parser.parse_args()
    torch.set_num_threads(4)
    groups, paths = {}, {}
    for row in csv.DictReader((args.data / 'original data/finding_annotations.csv').open()):
        if row['split'] == 'training':
            groups.setdefault(row['image_id'], []).append(row)
    for name in ('train', 'valid', 'test'):
        for row in csv.DictReader((args.data / f'modified/CSV-PNG-full/{name}.csv').open()):
            paths.setdefault(row['image_id'], row['png_full_path'])
    positives = select_groups([key for key, rows in groups.items() if any(
        'Suspicious Calcification' in ast.literal_eval(r['finding_categories']) for r in rows)], groups, args.per_group)
    positive_studies = {groups[key][0]['study_id'] for key in positives}
    negatives = select_groups([key for key, rows in groups.items() if groups[key][0]['study_id'] not in positive_studies and all(
        ast.literal_eval(r['finding_categories']) == ['No Finding'] for r in rows)], groups, args.per_group)
    model = fcos_resnet50_fpn(weights=None, weights_backbone=None, num_classes=1, score_thresh=.2,
                            nms_thresh=.5, detections_per_img=100, topk_candidates=1000, min_size=512, max_size=512)
    model.load_state_dict(torch.load(args.weights, map_location='cpu', weights_only=True), strict=True)
    model.eval()
    totals = {mode: {str(threshold): dict(targets=0, matched=0, normal_boxes=0, normal_images=0,
                                         normal_images_with_boxes=0) for threshold in (.3, .4, .45)}
              for mode in ('full_image', 'sliding_window')}
    start = time.monotonic()
    crop_count = 0
    for index, key in enumerate(positives + negatives):
        image = Image.open(paths[key]).convert('RGB')
        rows = groups[key]
        targets = [np.array([float(r[col]) for col in ('xmin', 'ymin', 'xmax', 'ymax')])
                   for r in rows if 'Suspicious Calcification' in ast.literal_eval(r['finding_categories'])]
        tiles = []
        for top in starts(image.height, args.window, args.stride):
            for left in starts(image.width, args.window, args.stride):
                tiles.append((image.crop((left, top, min(left + args.window, image.width),
                                          min(top + args.window, image.height))), (left, top)))
        crop_count += len(tiles)
        for mode, crops in (('full_image', [(image, (0, 0))]), ('sliding_window', tiles)):
            boxes, scores = predict(model, crops)
            for threshold, values in totals[mode].items():
                predicted = boxes[scores >= float(threshold)]
                remaining = list(range(len(predicted)))
                matched = 0
                for target in targets:
                    candidates = [(overlap(target, predicted[j]), j) for j in remaining]
                    if candidates and max(candidates)[0] >= .5:
                        matched += 1
                        remaining.remove(max(candidates)[1])
                values['targets'] += len(targets)
                values['matched'] += matched
                if not targets:
                    values['normal_images'] += 1
                    values['normal_boxes'] += len(predicted)
                    values['normal_images_with_boxes'] += bool(len(predicted))
        report = dict(complete=index + 1 == len(positives + negatives), processed=index + 1,
                      positive_images=len(positives), normal_images=len(negatives), totals=totals,
                      native_window=args.window, stride=args.stride, tile_model_input=512,
                      tile_count=crop_count, seconds=time.monotonic() - start,
                      protocol='training-split diagnostic; label-blind tiling; generic abnormal localization only; checkpoint lineage unverified')
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(dict(processed=index + 1, selected=len(positives + negatives))), flush=True)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
