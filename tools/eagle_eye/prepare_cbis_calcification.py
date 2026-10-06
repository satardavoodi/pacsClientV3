"""Prepare protected CBIS calcification-region candidates and aggregate quality evidence.

JPEG ROI masks describe annotated regions, not exact individual calcification pixels.
Unresolved rows are quarantined; no row becomes a negative through a mapping error.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image


def local_path(root, metadata):
    parts = metadata['image_path'].replace('\\', '/').split('/')
    if len(parts) < 2 or any(part in ('', '.', '..') for part in parts[-2:]):
        raise ValueError('Invalid source image path.')
    path = root / 'jpeg' / parts[-2] / parts[-1]
    if not path.resolve().is_relative_to((root / 'jpeg').resolve()) or not path.is_file():
        raise ValueError('Source image unavailable.')
    return path


def series_key(path):
    parts = str(path).strip().replace('\\', '/').split('/')
    if len(parts) < 2:
        raise ValueError('Annotation series unavailable.')
    return parts[-2]


def region_box(mask, image_size, threshold=128):
    if mask.ndim != 2 or tuple(mask.shape[::-1]) != tuple(image_size):
        raise ValueError('Mask geometry does not match full image.')
    if not np.isfinite(mask).all() or mask.min() < 0 or mask.max() > 255:
        raise ValueError('Invalid mask intensities.')
    # A region-mask candidate must be near binary. This does not prove alignment.
    if np.unique(mask).size > 64:
        raise ValueError('Mask is not a near-binary region candidate.')
    yy, xx = np.where(mask >= threshold)
    if len(xx) < 4 or len(xx) > mask.size / 2:
        raise ValueError('Empty or implausibly extensive region mask.')
    return [int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1]


def patient_partitions(patient_labels, reserved, seed):
    assignments = {patient: 'publisher_test' for patient in reserved}
    strata = defaultdict(list)
    for patient, labels in patient_labels.items():
        if patient not in reserved:
            strata['malignant_present' if 'MALIGNANT' in labels else 'benign_only'].append(patient)
    for members in strata.values():
        ordered = sorted(members, key=lambda patient: hashlib.sha256(f'{seed}:{patient}'.encode()).digest())
        count = max(1, round(len(ordered) * .1)) if len(ordered) >= 3 else 0
        for index, patient in enumerate(ordered):
            assignments[patient] = 'validation' if index < count else 'calibration' if index < 2 * count else 'train'
    return assignments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', default='cbis-calcification-20261001-v1')
    parser.add_argument('--limit', type=int, default=0, help='Diagnostic row limit; zero processes all rows.')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refusing to replace a protected manifest.')
    source = args.root / 'csv - original'
    metadata = list(csv.DictReader((source / 'dicom_info.csv').open(encoding='utf-8-sig')))
    series = defaultdict(list)
    for item in metadata:
        series[item['SeriesInstanceUID']].append(item)
    annotations = []
    source_hashes = {}
    source_hashes['dicom_info.csv'] = hashlib.sha256((source / 'dicom_info.csv').read_bytes()).hexdigest()
    reserved = set()
    all_train_patients = set()
    for kind in ('calc', 'mass'):
        for split in ('train', 'test'):
            path = source / f'{kind}_case_description_{split}_set.csv'
            source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            rows = list(csv.DictReader(path.open(encoding='utf-8-sig')))
            if split == 'test':
                reserved.update(row['patient_id'] for row in rows)
            else:
                all_train_patients.update(row['patient_id'] for row in rows)
            if kind == 'calc':
                annotations.extend({**row, 'publisher_split': split} for row in rows)
    patient_labels = defaultdict(set)
    for row in annotations:
        patient_labels[row['patient_id']].add(row['pathology'])
    partitions = patient_partitions(patient_labels, reserved, args.seed)
    if args.limit:
        annotations = annotations[:args.limit]
    images, quarantined, reasons = {}, [], Counter()
    recovered_empty_roles = 0
    started = time.monotonic()
    for index, row in enumerate(annotations):
        try:
            full_records = [item for item in series[series_key(row['image file path'])]
                            if item['SeriesDescription'] in ('full mammogram images', '')]
            if len(full_records) != 1:
                raise ValueError('Full-image role is unresolved.')
            full = local_path(args.root, full_records[0])
            with Image.open(full) as image:
                size, mode = image.size, image.mode
                if mode != 'L':
                    raise ValueError('Unsupported converted full-image mode.')
            candidates = []
            for item in series[series_key(row['ROI mask file path'])]:
                if item['SeriesDescription'] not in ('ROI mask images', ''):
                    continue
                path = local_path(args.root, item)
                with Image.open(path) as mask_image:
                    if mask_image.mode != 'L' or mask_image.size != size:
                        continue
                    array = np.asarray(mask_image)
                    try:
                        box = region_box(array, size)
                    except ValueError:
                        continue
                candidates.append((path, box, item['SeriesDescription']))
            if len(candidates) != 1:
                raise ValueError('Region-mask role is unresolved.')
            mask, box, mask_role = candidates[0]
            recovered_empty_roles += mask_role == '' or full_records[0]['SeriesDescription'] == ''
            key = str(full.resolve())
            partition = partitions[row['patient_id']]
            # Reserve every original test person across BOTH Mass and Calcification.
            # Cross-category train/test conflicts remain explicit, not reused as new test truth.
            if row['publisher_split'] == 'train' and row['patient_id'] in reserved:
                partition = 'cross_category_test_reserved'
            image = images.setdefault(key, dict(dataset='CBIS-DDSM', patient_id=row['patient_id'],
                                               full_image_path=key, width=size[0], height=size[1],
                                               partition=partition, annotations=[],
                                               input_encoding='converted_grayscale_jpeg_8bit',
                                               target_semantics='annotated calcification-region localization',
                                               negative_completeness='not established outside annotated regions'))
            if image['patient_id'] != row['patient_id'] or image['partition'] != partition:
                raise ValueError('Image identity or partition conflict.')
            image['annotations'].append(dict(box=box, roi_mask_path=str(mask.resolve()),
                                              calc_type=row['calc type'], calc_distribution=row['calc distribution'],
                                              pathology=row['pathology'], assessment=row['assessment'],
                                              subtlety=row['subtlety'], abnormality_id=row['abnormality id'],
                                              mask_derivation='JPEG threshold 128 region envelope; not punctum segmentation'))
        except (ValueError, KeyError, OSError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            reasons[reason] += 1
            quarantined.append(dict(annotation=row, reason=reason))
        if (index + 1) % 100 == 0:
            print(json.dumps(dict(processed=index + 1, selected=len(annotations), quarantined=len(quarantined))), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        for image in images.values():
            handle.write(json.dumps(image) + '\n')
    args.output.with_suffix('.quarantine.json').write_text(json.dumps(quarantined), encoding='utf-8')
    summaries = {}
    for image in images.values():
        item = summaries.setdefault(image['partition'], dict(images=0, region_annotations=0, patients=set(), pathology=Counter()))
        item['images'] += 1
        item['region_annotations'] += len(image['annotations'])
        item['patients'].add(image['patient_id'])
        item['pathology'].update(annotation['pathology'] for annotation in image['annotations'])
    for item in summaries.values():
        item['patients'] = len(item['patients'])
        item['pathology'] = dict(item['pathology'])
    report = dict(status='research_region_candidates_prepared_not_trained', processed=len(annotations),
                  accepted_rows=len(annotations) - len(quarantined), quarantined_rows=len(quarantined),
                  quarantine_reasons=dict(reasons), partitions=summaries, seed=args.seed,
                  source_hashes=source_hashes, empty_role_rows_recovered_by_geometry_and_pixel_checks=recovered_empty_roles,
                  manifest_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                  combined_mass_calc_train_test_patient_overlap=len(all_train_patients & reserved),
                  seconds=time.monotonic() - started,
                  pending_gates=['native source/JPEG quality', 'mask alignment clinical review',
                                 'microcalcification subtype target review', 'negative annotation completeness',
                                 'external digital-mammography evaluation'],
                  target='calcification regions; not all individual microcalcification puncta')
    args.output.with_suffix('.aggregate.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
