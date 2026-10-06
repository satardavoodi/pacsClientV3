"""Build complete per-image targets for a dedicated suspicious-calcification detector.

This prepares protected research manifests, not trained weights. Study grouping is
the available proxy; patient independence must be verified before qualification.
"""
import argparse
import ast
import csv
import hashlib
import json
import math
from pathlib import Path

TARGET = 'Suspicious Calcification'


def group_annotations(rows, clip_out_of_bounds=False):
    images = {}
    for row in rows:
        key = row['image_id']
        width, height = int(row['width']), int(row['height'])
        identity = (row['study_id'], row['split'], width, height)
        if key not in images:
            images[key] = dict(image_id=key, study_id=identity[0], publisher_split=identity[1],
                               width=width, height=height, boxes=[], box_labels=[], all_finding_labels=[],
                               reference_box_corrections=[])
        image = images[key]
        if identity != (image['study_id'], image['publisher_split'], image['width'], image['height']):
            raise ValueError('Inconsistent image identity or geometry.')
        labels = ast.literal_eval(row['finding_categories'])
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise ValueError('Invalid finding label schema.')
        image['all_finding_labels'] = sorted(set(image['all_finding_labels']) | set(labels))
        if TARGET not in labels:
            continue
        box = [float(row[column]) for column in ('xmin', 'ymin', 'xmax', 'ymax')]
        original_box = list(box)
        if clip_out_of_bounds and all(math.isfinite(value) for value in box):
            box = [max(0., min(width, box[0])), max(0., min(height, box[1])),
                   max(0., min(width, box[2])), max(0., min(height, box[3]))]
        if not all(math.isfinite(value) for value in box) or not (
                0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError('Invalid suspicious-calcification reference geometry.')
        if box != original_box:
            image['reference_box_corrections'].append(dict(original=original_box, clipped=box,
                                                           reason='outside_image_bounds'))
        if box in image['boxes']:
            index = image['boxes'].index(box)
            image['box_labels'][index] = sorted(set(image['box_labels'][index]) | set(labels))
        else:
            image['boxes'].append(box)
            image['box_labels'].append(sorted(labels))
    return list(images.values())


def partition(study, publisher_split, seed):
    if publisher_split == 'test':
        return 'publisher_test_previously_inspected'
    if publisher_split != 'training':
        raise ValueError('Unknown publisher split.')
    bucket = int(hashlib.sha256(f'{seed}:{study}'.encode()).hexdigest()[:8], 16) % 10
    return 'validation' if bucket == 0 else 'calibration' if bucket == 1 else 'train'


def assign_partitions(images, seed):
    studies = {}
    for image in images:
        entry = studies.setdefault(image['study_id'], dict(publisher_split=image['publisher_split'],
                                                          calc=False, calc_with_mass=False, other=False))
        if entry['publisher_split'] != image['publisher_split']:
            raise ValueError('Publisher split crosses study boundary.')
        entry['calc'] |= bool(image['boxes'])
        entry['calc_with_mass'] |= any('Mass' in labels for labels in image['box_labels'])
        entry['other'] |= any(label != 'No Finding' for label in image['all_finding_labels'])
    strata = {}
    assignments = {}
    for study, entry in studies.items():
        if entry['publisher_split'] == 'test':
            assignments[study] = 'publisher_test_previously_inspected'
            continue
        if entry['publisher_split'] != 'training':
            raise ValueError('Unknown publisher split.')
        stratum = ('calc_with_coannotated_mass' if entry['calc_with_mass'] else 'calc_without_coannotated_mass') if entry['calc'] else ('other_findings' if entry['other'] else 'normal')
        strata.setdefault(stratum, []).append(study)
    for members in strata.values():
        ordered = sorted(members, key=lambda study: hashlib.sha256(f'{seed}:{study}'.encode()).digest())
        count = max(1, round(len(ordered) * .1)) if len(ordered) >= 3 else 0
        for index, study in enumerate(ordered):
            assignments[study] = 'validation' if index < count else 'calibration' if index < 2 * count else 'train'
    return assignments, {name: len(members) for name, members in strata.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', default='calcification-20261001-v2')
    parser.add_argument('--clip-out-of-bounds', action='store_true',
                        help='Explicitly record and clip reference boxes; review corrections before training.')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refusing to replace an existing protected manifest.')
    annotation_path = args.data / 'original data/finding_annotations.csv'
    images = group_annotations(csv.DictReader(annotation_path.open()), args.clip_out_of_bounds)
    assignments, strata = assign_partitions(images, args.seed)
    metadata = {}
    for split in ('train', 'valid', 'test'):
        for row in csv.DictReader((args.data / f'modified/CSV-PNG-full/{split}.csv').open()):
            metadata.setdefault(row['image_id'], row)
    summaries = {}
    studies = {}
    records = []
    for image in images:
        source = metadata[image['image_id']]
        for name in ('png_full_path', 'full_image_path'):
            if not Path(source[name]).is_file():
                raise ValueError('Missing protected image source.')
            image[name] = source[name]
        image['partition'] = assignments[image['study_id']]
        image['target_label'] = TARGET
        image['target_semantics'] = 'annotated suspicious regions; not all benign calcifications or individual puncta'
        if image['study_id'] in studies and studies[image['study_id']] != image['partition']:
            raise ValueError('Study partition leakage.')
        studies[image['study_id']] = image['partition']
        summary = summaries.setdefault(image['partition'], dict(images=0, positive_images=0, boxes=0,
                                                                images_with_multiple_target_boxes=0, boxes_with_mass=0))
        summary['images'] += 1
        summary['positive_images'] += bool(image['boxes'])
        summary['boxes'] += len(image['boxes'])
        summary['images_with_multiple_target_boxes'] += len(image['boxes']) > 1
        summary['boxes_with_mass'] += sum('Mass' in labels for labels in image['box_labels'])
        records.append(image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        for image in records:
            handle.write(json.dumps(image) + '\n')
    report = dict(status='prepared_not_trained', target=TARGET, seed=args.seed,
                  source_sha256=hashlib.sha256(annotation_path.read_bytes()).hexdigest(),
                  study_groups=len(studies), partitions=summaries,
                  grouping='study proxy; patient independence unverified',
                  test_status='publisher test already inspected; external qualification required',
                  allocation='study-stratified calcification/coannotated-mass/other/normal; scanner and patient review pending',
                  training_study_strata=strata)
    report['reference_box_corrections'] = sum(len(image['reference_box_corrections']) for image in records)
    report['geometry_policy'] = 'recorded clipping; review pending' if args.clip_out_of_bounds else 'strict rejection'
    args.output.with_suffix('.aggregate.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
