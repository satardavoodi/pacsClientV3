"""Stage positive-only digital training records; preserve all annotated regions."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from PIL import Image


def select_training(rows, count):
    selected, seen = [], set()
    for row in sorted(rows, key=lambda r: hashlib.sha256(r['image_id'].encode()).digest()):
        if row['partition'] != 'train' or not row['boxes'] or row['study_id'] in seen:
            continue
        seen.add(row['study_id']); selected.append(row)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError('Insufficient distinct positive training studies.')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=64)
    args = parser.parse_args()
    if args.output.exists() or args.count < 1:
        raise ValueError('Output exists or invalid cohort size.')
    rows = [json.loads(line) for line in args.manifest.read_text().splitlines()]
    selected = select_training(rows, args.count)
    protected = {r['study_id'] for r in rows if r['partition'] != 'train'}
    if {r['study_id'] for r in selected} & protected:
        raise ValueError('Training study crosses a protected partition.')
    staged = []
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_STORED) as archive:
        for index, row in enumerate(selected):
            path = Path(row['png_full_path'])
            with Image.open(path) as image:
                image.load()
                if image.size != (row['width'], row['height']):
                    raise ValueError('Digital training geometry mismatch.')
            name = f'images/{index:03d}.png'
            archive.write(path, name)
            staged.append(dict(image=name, partition='train', boxes=row['boxes'],
                               person_key=hashlib.sha256(row['study_id'].encode()).hexdigest(),
                               source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               grouping='study proxy; patient grouping unverified',
                               label_semantics='VinDr suspicious calcification regions; incomplete benign labels'))
        archive.writestr('manifest.json', json.dumps(staged))
    report = dict(images=len(staged), regions=sum(len(r['boxes']) for r in staged),
                  distinct_training_studies=len(staged), protected_study_overlap=0,
                  negative_training_images=0, archive_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.output.with_suffix('.aggregate.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
