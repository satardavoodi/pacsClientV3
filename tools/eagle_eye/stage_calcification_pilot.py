"""Create a protected, bounded internal-worker pilot archive with aggregate QA."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
from prepare_cbis_calcification import region_box


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--train-count', type=int, default=32)
    parser.add_argument('--validation-count', type=int, default=8)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Pilot archive exists.')
    if not args.weights.is_file():
        raise FileNotFoundError('Initialization checkpoint unavailable.')
    records = [json.loads(line) for line in args.manifest.read_text().splitlines()]
    selected = []
    if min(args.train_count, args.validation_count) < 1:
        raise ValueError('Partition sizes must be positive.')
    for partition, count in (('train', args.train_count), ('validation', args.validation_count)):
        candidates = [r for r in records if r['partition'] == partition and any(
            any(label in a['calc_type'] for label in ('PLEOMORPHIC', 'AMORPHOUS', 'PUNCTATE', 'FINE_LINEAR_BRANCHING'))
            for a in r['annotations'])]
        seen = set()
        for record in sorted(candidates, key=lambda r: hashlib.sha256(r['full_image_path'].encode()).digest()):
            if record['patient_id'] in seen:
                continue
            seen.add(record['patient_id'])
            selected.append(record)
            if len(seen) == count:
                break
        if len(seen) != count:
            raise ValueError('Insufficient independent pilot people.')
    people = {partition: {r['patient_id'] for r in selected if r['partition'] == partition}
              for partition in ('train', 'validation')}
    if people['train'] & people['validation']:
        raise ValueError('Pilot person leakage.')
    staged = []
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_STORED) as archive:
        for index, record in enumerate(selected):
            path = Path(record['full_image_path'])
            with Image.open(path) as image:
                image.load()
                if image.mode != 'L' or image.size != (record['width'], record['height']):
                    raise ValueError('Pilot full-image QA failed.')
            for annotation in record['annotations']:
                with Image.open(annotation['roi_mask_path']) as image:
                    if region_box(np.asarray(image), (record['width'], record['height'])) != annotation['box']:
                        raise ValueError('Pilot reference geometry changed.')
            name = f'images/{index:03d}.jpg'
            archive.write(path, name)
            staged.append(dict(image=name, partition=record['partition'],
                               person_key=hashlib.sha256(record['patient_id'].encode()).hexdigest(),
                               boxes=[a['box'] for a in record['annotations']],
                               morphology=[a['calc_type'] for a in record['annotations']],
                               source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        archive.writestr('manifest.json', json.dumps(staged))
        archive.write(args.weights, 'initialization.pth')
    report = dict(status='protected_pilot_staged', train_images=args.train_count, validation_images=args.validation_count,
                  train_regions=sum(len(r['boxes']) for r in staged if r['partition'] == 'train'),
                  validation_regions=sum(len(r['boxes']) for r in staged if r['partition'] == 'validation'),
                  person_overlap=0, image_and_mask_geometry_checked=len(staged),
                  archive_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                  qa='automated decoding/geometry only; clinical alignment and JPEG quality unqualified')
    args.output.with_suffix('.aggregate.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
